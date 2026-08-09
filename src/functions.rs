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

/// Quote a TEXT value as a SQL literal — single quotes doubled, so the
/// interpolation surface stays closed (ids and f64 literals elsewhere).
fn text_lit(s: &str) -> String {
    format!("'{}'", s.replace('\'', "''"))
}

/// Optional TEXT argument at `idx`: absent or NULL means "actor unknown".
fn value_actor(values: &[*mut sqlite3_value], idx: usize) -> Result<Option<String>> {
    if values.len() <= idx || api::value_type(&values[idx]) == api::ValueType::Null {
        return Ok(None);
    }
    Ok(Some(api::value_text(&values[idx])?.to_string()))
}

/// Hardened-mode self-endorsement test: does `actor` equal the memory's
/// created_by? Untagged memories (created_by NULL) never match.
fn is_self(db: *mut sqlite3, id: i64, actor: &str) -> Result<bool> {
    let sql_text = format!(
        "SELECT 1 FROM rfm_memories WHERE id = {id} AND created_by = {}",
        text_lit(actor)
    );
    Ok(sql::query_row(db, &sql_text, 1)?.is_some())
}

/// Ballot-stuffing check: has this actor already recorded an outcome for
/// this memory? Served by rfm_accesses_mem_actor.
fn has_voted(db: *mut sqlite3, id: i64, actor: &str) -> Result<bool> {
    let sql_text = format!(
        "SELECT 1 FROM rfm_accesses WHERE memory_id = {id} AND actor = {} \
         AND outcome IS NOT NULL LIMIT 1",
        text_lit(actor)
    );
    Ok(sql::query_row(db, &sql_text, 1)?.is_some())
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
}

/// The six extension-maintained columns, in canonical SELECT/RETURNING order.
const MEM_COLS: &str = "access_count, created_at, last_access, bla_cache, value_score, outcome_count";

fn decode_mem(row: &[Option<f64>]) -> MemRow {
    MemRow {
        n: row[0].unwrap_or(0.0) as i64,
        created_at: row[1].unwrap_or(0.0),
        last_access: row[2],
        t2_wall: row[3],
        value: row[4].unwrap_or(0.0),
        n_outcomes: row[5].unwrap_or(0.0) as i64,
    }
}

fn load_mem(db: *mut sqlite3, id: i64) -> Result<MemRow> {
    let sql_text = format!("SELECT {MEM_COLS} FROM rfm_memories WHERE id = {id}");
    let row = sql::query_row(db, &sql_text, 6)?.ok_or_else(|| no_such_id(id))?;
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
    score_of_trusted(row, now, d, w_a, w_v, shrink_k, None)
}

/// `author_trust`: the writer's (value, outcome_count) from rfm_actors, or
/// None to apply no cap (trust mode off, untagged memory, or a writer with no
/// third-party outcomes yet).
fn score_of_trusted(
    row: &MemRow,
    now: f64,
    d: f64,
    w_a: f64,
    w_v: f64,
    shrink_k: f64,
    author_trust: Option<(f64, i64)>,
) -> f64 {
    let b = activation_of(row, now, d);
    let v_eff = math::shrink(row.value, row.n_outcomes, shrink_k);
    let capped = math::trust_cap(
        v_eff,
        author_trust.map(|(tv, tn)| math::shrink(tv, tn, shrink_k)),
    );
    math::score(b, capped, w_a, w_v)
}

/// The author's reputation row for a memory, if trust mode is on and the
/// memory has a known writer with third-party outcomes.
fn author_trust_of(db: *mut sqlite3, id: i64, c: &RfmConfig) -> Result<Option<(f64, i64)>> {
    if c.trust == 0.0 {
        return Ok(None);
    }
    let sql_text = format!(
        "SELECT a.value_score, a.outcome_count FROM rfm_memories m \
         JOIN rfm_actors a ON a.actor = m.created_by WHERE m.id = {id}"
    );
    Ok(sql::query_row(db, &sql_text, 2)?
        .map(|r| (r[0].unwrap_or(0.0), r[1].unwrap_or(0.0) as i64)))
}

/// Fold `outcome` into one actor's reputation EWMA (rfm_actors upsert).
fn bump_actor_trust(db: *mut sqlite3, actor: &str, outcome: f64, lambda: f64) -> Result<()> {
    let lit = text_lit(actor);
    let prev = sql::query_row(
        db,
        &format!("SELECT value_score, outcome_count FROM rfm_actors WHERE actor = {lit}"),
        2,
    )?;
    let (prev_v, prev_n) = match prev {
        Some(r) => (r[0].unwrap_or(0.0), r[1].unwrap_or(0.0) as i64),
        None => (0.0, 0),
    };
    let new_v = f64_lit(math::ewma_update(prev_v, prev_n, outcome, lambda))?;
    sql::exec(
        db,
        &format!(
            "INSERT INTO rfm_actors(actor, value_score, outcome_count) \
             VALUES ({lit}, {new_v}, 1) \
             ON CONFLICT(actor) DO UPDATE SET value_score = {new_v}, \
             outcome_count = outcome_count + 1"
        ),
    )
}

/// Endorser liability (Amendment 10): charge this outcome to every DISTINCT
/// prior positive endorser of the memory, excluding the current voter. An
/// endorsement is then a stake rather than a free favour — a ring's mutual
/// praise becomes mutually destructive once outsiders' retrievals fail,
/// while honest endorsers of memories that keep working are repaid.
/// Bounded by distinct endorsers (team size) and confined to the write path.
fn charge_endorsers(db: *mut sqlite3, id: i64, voter: &str, outcome: f64, lambda: f64) -> Result<()> {
    let endorsers = sql::query_column_text(
        db,
        &format!(
            "SELECT DISTINCT actor FROM rfm_accesses WHERE memory_id = {id} \
             AND outcome > 0 AND actor IS NOT NULL AND actor <> {}",
            text_lit(voter)
        ),
    )?;
    for e in endorsers {
        bump_actor_trust(db, &e, outcome, lambda)?;
    }
    Ok(())
}

/// Fold one third-party outcome into the writer's reputation EWMA. Called
/// only when the voter is TAGGED and differs from the writer: reputation is
/// built from identifiable third-party verdicts, never from self-assessment
/// or from anonymous votes that cannot be checked against authorship.
fn update_author_trust(db: *mut sqlite3, id: i64, voter: &str, outcome: f64, c: &RfmConfig) -> Result<()> {
    let lambda = c.lambda;
    // Voter weighting (Amendment 9): scale this vote's influence on the
    // AUTHOR's reputation by the VOTER's own standing, so a ring that loses
    // standing also loses the power to confer it. An unknown voter counts
    // 0.5 (neutral) rather than 0, or nobody could ever bootstrap trust.
    let weight = if c.trust_weighted == 0.0 {
        1.0
    } else {
        match sql::query_row(
            db,
            &format!(
                "SELECT value_score, outcome_count FROM rfm_actors WHERE actor = {}",
                text_lit(voter)
            ),
            2,
        )? {
            Some(r) => math::value01(math::shrink(
                r[0].unwrap_or(0.0),
                r[1].unwrap_or(0.0) as i64,
                c.shrink_k,
            )),
            None => 0.5,
        }
    };
    let outcome = outcome * weight;
    let author_sql = format!(
        "SELECT 1 FROM rfm_memories WHERE id = {id} AND created_by IS NOT NULL \
         AND created_by <> {}",
        text_lit(voter)
    );
    if sql::query_row(db, &author_sql, 1)?.is_none() {
        return Ok(());
    }
    let prev = sql::query_row(
        db,
        &format!(
            "SELECT a.value_score, a.outcome_count FROM rfm_memories m \
             JOIN rfm_actors a ON a.actor = m.created_by WHERE m.id = {id}"
        ),
        2,
    )?;
    let (prev_v, prev_n) = match prev {
        Some(r) => (r[0].unwrap_or(0.0), r[1].unwrap_or(0.0) as i64),
        None => (0.0, 0),
    };
    let new_v = f64_lit(math::ewma_update(prev_v, prev_n, outcome, lambda))?;
    sql::exec(
        db,
        &format!(
            "INSERT INTO rfm_actors(actor, value_score, outcome_count) \
             SELECT created_by, {new_v}, 1 FROM rfm_memories WHERE id = {id} \
             ON CONFLICT(actor) DO UPDATE SET value_score = {new_v}, \
             outcome_count = outcome_count + 1"
        ),
    )
}

pub fn rfm_init(
    context: *mut sqlite3_context,
    _values: &[*mut sqlite3_value],
    _aux: &SharedConfig,
) -> Result<()> {
    let db = db_of(context);
    // Migrate pre-v0.3 databases BEFORE the schema runs: the schema's
    // rfm_accesses_mem_actor index references a column those databases lack,
    // and a failing CREATE INDEX would abort the whole script. On a fresh
    // database the ALTERs fail (no table yet) and CREATE TABLE below supplies
    // the columns; on a current one they fail as "duplicate column". Both
    // failures are the expected steady state, hence ignored.
    let _ = sql::exec(db, "ALTER TABLE rfm_memories ADD COLUMN created_by TEXT");
    let _ = sql::exec(db, "ALTER TABLE rfm_accesses ADD COLUMN actor TEXT");
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
    let actor = value_actor(values, 1)?;
    let now = clock::now(&c);
    // Hardened mode (Amendment 6): a writer touching their own memory
    // neither logs an access nor freshens the summary — self-access is the
    // R/F inflation channel. The call still errors on a missing id and
    // returns the truthful current activation.
    if c.exclude_self != 0.0 {
        if let Some(a) = &actor {
            if is_self(db, id, a)? {
                let row = load_mem(db, id)?;
                api::result_double(context, activation_of(&row, now, c.decay));
                return Ok(());
            }
        }
    }
    let now_lit = f64_lit(now)?;
    let actor_cols = if actor.is_some() { ", actor" } else { "" };
    let actor_vals = match &actor {
        Some(a) => format!(", {}", text_lit(a)),
        None => String::new(),
    };
    // Access row first, summary last: the summary is what scoring trusts, so
    // it must never advance ahead of the log (see DESIGN_NOTES on the
    // autocommit crash window). INSERT..SELECT doubles as the existence
    // check, so a bad id inserts nothing rather than an orphan log row.
    sql::exec(
        db,
        &format!(
            "INSERT INTO rfm_accesses(memory_id, accessed_at{actor_cols}) \
             SELECT id, {now_lit}{actor_vals} FROM rfm_memories WHERE id = {id}"
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
        6,
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
    // Hardened modes: both ignore the call entirely (no EWMA update, no
    // access-slot consumption) and return the unchanged value, so a rejected
    // vote can never block a legitimate one on the same access. Untagged
    // callers are unaffected — neither rule can identify a voter.
    if let Some(a) = value_actor(values, 2)? {
        // exclude_self (Amendment 6): self-feedback is the M inflation channel.
        if c.exclude_self != 0.0 && is_self(db, id, &a)? {
            api::result_double(context, row.value);
            return Ok(());
        }
        // one_vote (Amendment 7): one outcome per (actor, memory) ever, so
        // value counts DISTINCT endorsers rather than repetitions.
        if c.one_vote != 0.0 && has_voted(db, id, &a)? {
            api::result_double(context, row.value);
            return Ok(());
        }
    }
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
    // Writer reputation is maintained unconditionally (cheap, and it must
    // already exist when trust mode is switched on); only its USE is gated.
    if let Some(a) = value_actor(values, 2)? {
        update_author_trust(db, id, &a, outcome, &c)?;
        if c.endorser_liability != 0.0 {
            charge_endorsers(db, id, &a, outcome, c.lambda)?;
        }
    }
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
    let db = db_of(context);
    let id = value_id(values)?;
    let row = load_mem(db, id)?;
    let now = clock::now(&c);
    let trust = author_trust_of(db, id, &c)?;
    api::result_double(
        context,
        score_of_trusted(&row, now, c.decay, c.w_a, c.w_v, c.shrink_k, trust),
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
    let db = db_of(context);
    let id = value_id(values)?;
    let row = load_mem(db, id)?;
    let now = clock::now(&c);
    let trust = author_trust_of(db, id, &c)?;
    let s = score_of_trusted(&row, now, c.decay, c.w_a, c.w_v, c.shrink_k, trust);
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
