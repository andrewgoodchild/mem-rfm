//! The scalar functions registered by the extension. Each callback resolves
//! the host connection via sqlite3_context_db_handle (the eval.c pattern),
//! reads/writes the rfm_* tables through the sql shim, and does all math in
//! the pure `math` module.

use std::sync::{Arc, Mutex};

use sqlite_loadable::ext::{sqlite3, sqlite3ext_context_db_handle};
use sqlite_loadable::prelude::*;
use sqlite_loadable::{api, Error, Result};

use crate::config::{self, RfmConfig};
use crate::{clock, math, sql};

pub type SharedConfig = Arc<Mutex<RfmConfig>>;

const SCHEMA: &str = include_str!("../rfm_schema.sql");

fn lock(aux: &SharedConfig) -> Result<std::sync::MutexGuard<'_, RfmConfig>> {
    aux.lock()
        .map_err(|_| Error::new_message("rfm: config lock poisoned"))
}

fn cfg(aux: &SharedConfig) -> Result<RfmConfig> {
    Ok(lock(aux)?.clone())
}

fn no_such_id(id: i64) -> Error {
    Error::new_message(format!("rfm: no such memory id {id}"))
}

fn db_of(context: *mut sqlite3_context) -> *mut sqlite3 {
    unsafe { sqlite3ext_context_db_handle(context) }
}

/// Format an f64 as a SQL literal. Rust's Debug formatting is shortest
/// round-trip and SQLite's text→REAL parse is correctly rounded, so the value
/// survives bit-exact. Non-finite values are rejected before they can reach
/// SQL text.
fn f64_lit(x: f64) -> Result<String> {
    if !x.is_finite() {
        return Err(Error::new_message("rfm: refusing to store non-finite value"));
    }
    Ok(format!("{x:?}"))
}

/// The extension-maintained columns of one rfm_memories row.
#[derive(Clone, Copy)]
struct MemRow {
    n: i64,
    created_at: f64,
    /// Wall time of most recent access (t1 anchor).
    last_access: Option<f64>,
    /// Wall time of second most recent access (t2 anchor); NULL means none.
    t2_wall: Option<f64>,
    value: f64,
    n_outcomes: i64,
    /// True when the host tagged this memory kind='procedural'.
    procedural: bool,
}

/// The six extension-maintained columns, in canonical SELECT/RETURNING order.
const MEM_COLS: &str = "access_count, created_at, last_access, bla_cache, value_score, outcome_count, kind = 'procedural'";

fn decode_mem(row: &[Option<f64>]) -> MemRow {
    MemRow {
        n: row[0].unwrap_or(0.0) as i64,
        created_at: row[1].unwrap_or(0.0),
        last_access: row[2],
        t2_wall: row[3],
        value: row[4].unwrap_or(0.0),
        n_outcomes: row[5].unwrap_or(0.0) as i64,
        procedural: row[6].unwrap_or(0.0) != 0.0,
    }
}

fn load_mem(db: *mut sqlite3, id: i64) -> Result<MemRow> {
    let sql_text = format!("SELECT {MEM_COLS} FROM rfm_memories WHERE id = {id}");
    let row = sql::query_row(db, &sql_text, 7)?.ok_or_else(|| no_such_id(id))?;
    Ok(decode_mem(&row))
}

/// Ids must be genuine INTEGERs: value_int64 would silently truncate REALs
/// (1.9 → row 1) and coerce text to 0, turning malformed ids into wrong-row
/// reads and writes.
fn value_id(values: &[*mut sqlite3_value]) -> Result<i64> {
    if api::value_type(&values[0]) != api::ValueType::Integer {
        return Err(Error::new_message("rfm: id must be an INTEGER"));
    }
    Ok(api::value_int64(&values[0]))
}

/// Read a REAL argument, rejecting NULL and non-finite values — value_double
/// would silently read both NULL and unparseable text as 0.0.
fn require_f64(values: &[*mut sqlite3_value], idx: usize, name: &str) -> Result<f64> {
    if api::value_type(&values[idx]) == api::ValueType::Null {
        return Err(Error::new_message(format!("rfm: {name} must not be NULL")));
    }
    let v = api::value_double(&values[idx]);
    if !v.is_finite() {
        return Err(Error::new_message(format!("rfm: {name} must be finite")));
    }
    Ok(v)
}

/// ACT-R activation from summary state alone (Petrov k=2; see math.rs).
fn activation_of(row: &MemRow, now: f64, d: f64) -> f64 {
    math::bla_hybrid_k2(
        row.n,
        row.last_access.map(|w| now - w),
        row.t2_wall.map(|w| now - w),
        now - row.created_at,
        d,
    )
}

fn score_of(row: &MemRow, now: f64, d: f64, w_a: f64, w_v: f64, shrink_k: f64) -> f64 {
    let b = activation_of(row, now, d);
    let v_eff = math::shrink(row.value, row.n_outcomes, shrink_k);
    math::score(b, v_eff, w_a, w_v)
}

/// Weights for this row: ACT-R scores procedural knowledge by learned utility
/// and declarative knowledge by base-level activation, so a memory the host
/// tagged 'procedural' uses the utility-weighted pair.
fn weights_for(row: &MemRow, c: &RfmConfig) -> (f64, f64) {
    if row.procedural { (c.w_a_proc, c.w_v_proc) } else { (c.w_a, c.w_v) }
}

pub fn rfm_init(
    context: *mut sqlite3_context,
    _values: &[*mut sqlite3_value],
    _aux: &SharedConfig,
) -> Result<()> {
    let db = db_of(context);
    // Pre-v0.3 databases predate `kind`; add it before the schema script so
    // CREATE TABLE IF NOT EXISTS is a no-op on them. Both failure modes here
    // ("no such table" on a fresh DB, "duplicate column" on a current one)
    // are the expected steady state, hence ignored.
    let _ = sql::exec(db, "ALTER TABLE rfm_memories ADD COLUMN kind TEXT");
    sql::exec_multi(db, SCHEMA)?;
    api::result_text(context, "ok")?;
    Ok(())
}

pub fn rfm_record_access(
    context: *mut sqlite3_context,
    values: &[*mut sqlite3_value],
    aux: &SharedConfig,
) -> Result<()> {
    let c = cfg(aux)?;
    let db = db_of(context);
    let id = value_id(values)?;
    let now = clock::now(&c);
    let now_lit = f64_lit(now)?;
    // Access row first, summary last: the summary is what scoring trusts, so
    // it must never advance ahead of the log (see DESIGN_NOTES on the
    // autocommit crash window). INSERT..SELECT doubles as the existence
    // check, so a bad id inserts nothing rather than an orphan log row.
    sql::exec(
        db,
        &format!(
            "INSERT INTO rfm_accesses(memory_id, accessed_at) \
             SELECT id, {now_lit} FROM rfm_memories WHERE id = {id}"
        ),
    )?;
    // bla_cache ← previous last_access: the one-assignment Petrov k=2 update
    // (RHS reads pre-update column values). RETURNING (SQLite ≥ 3.35) hands
    // back the authoritative post-update row, so the returned activation is
    // computed from exactly the state a subsequent rfm_activation(id) reads —
    // and an empty result is the missing-id case (the INSERT..SELECT above
    // inserted nothing for it either).
    let row = sql::query_row(
        db,
        &format!(
            "UPDATE rfm_memories SET access_count = access_count + 1, \
             bla_cache = last_access, last_access = {now_lit} \
             WHERE id = {id} RETURNING {MEM_COLS}"
        ),
        7,
    )?
    .ok_or_else(|| no_such_id(id))?;
    api::result_double(context, activation_of(&decode_mem(&row), now, c.decay));
    Ok(())
}

pub fn rfm_record_outcome(
    context: *mut sqlite3_context,
    values: &[*mut sqlite3_value],
    aux: &SharedConfig,
) -> Result<()> {
    let c = cfg(aux)?;
    let db = db_of(context);
    let id = value_id(values)?;
    let outcome = require_f64(values, 1, "outcome")?;
    if !(-1.0..=1.0).contains(&outcome) {
        return Err(Error::new_message("rfm: outcome must be in [-1, 1]"));
    }
    let row = load_mem(db, id)?;
    if row.n == 0 {
        return Err(Error::new_message(format!(
            "rfm: memory {id} has no recorded access; call rfm_record_access first"
        )));
    }
    let new_value = math::ewma_update(row.value, row.n_outcomes, outcome, c.lambda);
    let outcome_lit = f64_lit(outcome)?;
    let value_lit = f64_lit(new_value)?;
    // One outcome per access: the `outcome IS NULL` guard makes a second
    // outcome without a new access match nothing — RETURNING then yields no
    // row, caught below. Otherwise the log row would be overwritten while the
    // EWMA absorbed both calls, and replaying rfm_accesses could never
    // reproduce value_score.
    sql::query_row(
        db,
        &format!(
            "UPDATE rfm_accesses SET outcome = {outcome_lit} WHERE rowid = \
             (SELECT rowid FROM rfm_accesses WHERE memory_id = {id} \
              ORDER BY accessed_at DESC, rowid DESC LIMIT 1) \
             AND outcome IS NULL RETURNING rowid"
        ),
        1,
    )?
    .ok_or_else(|| {
        Error::new_message(format!(
            "rfm: latest access of memory {id} already has an outcome; \
             call rfm_record_access before recording another"
        ))
    })?;
    sql::exec(
        db,
        &format!(
            "UPDATE rfm_memories SET value_score = {value_lit}, \
             outcome_count = outcome_count + 1 WHERE id = {id}"
        ),
    )?;
    api::result_double(context, new_value);
    Ok(())
}

pub fn rfm_recency(
    context: *mut sqlite3_context,
    values: &[*mut sqlite3_value],
    aux: &SharedConfig,
) -> Result<()> {
    let c = cfg(aux)?;
    let db = db_of(context);
    let row = load_mem(db, value_id(values)?)?;
    let now = clock::now(&c);
    // Never-accessed memories fall back to creation age.
    let anchor = row.last_access.unwrap_or(row.created_at);
    api::result_double(context, math::recency(now - anchor, c.tau));
    Ok(())
}

pub fn rfm_frequency(
    context: *mut sqlite3_context,
    values: &[*mut sqlite3_value],
    _aux: &SharedConfig,
) -> Result<()> {
    let row = load_mem(db_of(context), value_id(values)?)?;
    api::result_double(context, math::frequency(row.n));
    Ok(())
}

pub fn rfm_activation(
    context: *mut sqlite3_context,
    values: &[*mut sqlite3_value],
    aux: &SharedConfig,
) -> Result<()> {
    let c = cfg(aux)?;
    let row = load_mem(db_of(context), value_id(values)?)?;
    api::result_double(context, activation_of(&row, clock::now(&c), c.decay));
    Ok(())
}

pub fn rfm_value(
    context: *mut sqlite3_context,
    values: &[*mut sqlite3_value],
    _aux: &SharedConfig,
) -> Result<()> {
    let row = load_mem(db_of(context), value_id(values)?)?;
    api::result_double(context, row.value);
    Ok(())
}

pub fn rfm_score(
    context: *mut sqlite3_context,
    values: &[*mut sqlite3_value],
    aux: &SharedConfig,
) -> Result<()> {
    let c = cfg(aux)?;
    let row = load_mem(db_of(context), value_id(values)?)?;
    let now = clock::now(&c);
    let (w_a, w_v) = weights_for(&row, &c);
    api::result_double(
        context,
        score_of(&row, now, c.decay, w_a, w_v, c.shrink_k),
    );
    Ok(())
}

/// rfm_prior(id) = (1-beta) + beta*rfm_score(id) — the bounded multiplier to
/// compose with similarity search: ORDER BY sim * rfm_prior(id) DESC. beta
/// (config key, default 0.3) caps how much usage history can perturb the
/// similarity ranking; the default was frozen by the pre-registered
/// composition experiment (PROTOCOL.md).
pub fn rfm_prior(
    context: *mut sqlite3_context,
    values: &[*mut sqlite3_value],
    aux: &SharedConfig,
) -> Result<()> {
    let c = cfg(aux)?;
    let row = load_mem(db_of(context), value_id(values)?)?;
    let now = clock::now(&c);
    let (w_a, w_v) = weights_for(&row, &c);
    let s = score_of(&row, now, c.decay, w_a, w_v, c.shrink_k);
    api::result_double(context, (1.0 - c.beta) + c.beta * s);
    Ok(())
}

/// rfm_score_w(id, w_a, w_v[, tau, decay]) — parameterised scoring for tuning.
/// tau is accepted for API compatibility but unused: activation subsumes the
/// exponential-recency term (see DESIGN_NOTES).
pub fn rfm_score_w(
    context: *mut sqlite3_context,
    values: &[*mut sqlite3_value],
    aux: &SharedConfig,
) -> Result<()> {
    let c = cfg(aux)?;
    let row = load_mem(db_of(context), value_id(values)?)?;
    let w_a = require_f64(values, 1, "w_a")?;
    let w_v = require_f64(values, 2, "w_v")?;
    if w_a < 0.0 || w_v < 0.0 {
        return Err(Error::new_message("rfm: weights must be finite and >= 0"));
    }
    let decay = if values.len() >= 5 {
        // tau is unused (see doc comment) but still validated: a garbage or
        // NaN argument on a tuning function must error, not silently pass.
        let tau = require_f64(values, 3, "tau")?;
        config::check_tau(tau).map_err(Error::new_message)?;
        let d = require_f64(values, 4, "decay")?;
        config::check_decay(d).map_err(Error::new_message)?;
        d
    } else {
        c.decay
    };
    let now = clock::now(&c);
    api::result_double(context, score_of(&row, now, decay, w_a, w_v, c.shrink_k));
    Ok(())
}

/// rfm_prunable(id, max_unused_days) → 1 when a memory has gone unused for
/// longer than the window AND has never demonstrated usefulness.
///
/// Borrowed from Codex's memory retention: there, citing a memory refreshes
/// it and uncited rows past a window are pruned — usage drives RETENTION, not
/// just ranking. mem-rfm had no GC at all, so memories accumulated forever.
///
/// This is a read-only predicate rather than a delete: the tables are
/// host-owned, and irreversibly dropping a user's memories is the host's
/// decision, not the extension's. Because a mutating scan of the table being
/// mutated has undefined order in SQLite, collect ids first:
///
///   SELECT id FROM rfm_memories WHERE rfm_prunable(id, 30);
///
/// The value guard matters: a memory retrieved rarely but successfully is
/// exactly what this system exists to keep, so anything with a positive
/// outcome record is never prunable however long it has been idle.
pub fn rfm_prunable(
    context: *mut sqlite3_context,
    values: &[*mut sqlite3_value],
    aux: &SharedConfig,
) -> Result<()> {
    let c = cfg(aux)?;
    let row = load_mem(db_of(context), value_id(values)?)?;
    let max_days = require_f64(values, 1, "max_unused_days")?;
    if max_days < 0.0 {
        return Err(Error::new_message("rfm: max_unused_days must be >= 0"));
    }
    // Never accessed → measure from creation, so imported-but-unused rows age out.
    let anchor = row.last_access.unwrap_or(row.created_at);
    let idle_days = (clock::now(&c) - anchor).max(0.0) / 86_400.0;
    let proved_useful = row.n_outcomes > 0 && row.value > 0.0;
    api::result_int(context, i32::from(idle_days > max_days && !proved_useful));
    Ok(())
}

/// rfm_config(key) → current value; rfm_config(key, value) → set and return.
/// rfm_config('now', t) freezes the clock; rfm_config('now', NULL) unfreezes.
pub fn rfm_config(
    context: *mut sqlite3_context,
    values: &[*mut sqlite3_value],
    aux: &SharedConfig,
) -> Result<()> {
    let key = api::value_text(&values[0])?;
    let mut guard = lock(aux)?;
    let result = if values.len() == 1 {
        guard.get(key).map_err(Error::new_message)?
    } else {
        let new = match api::value_type(&values[1]) {
            api::ValueType::Null => None,
            _ => Some(api::value_double(&values[1])),
        };
        guard.set(key, new).map_err(Error::new_message)?
    };
    match result {
        Some(v) => api::result_double(context, v),
        None => api::result_null(context),
    }
    Ok(())
}
