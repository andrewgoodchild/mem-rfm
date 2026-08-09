//! Minimal SQL-execution shim over sqlite-loadable's raw `ext::` wrappers.
//!
//! sqlite-loadable 0.0.6-alpha.6 has no high-level way to run SQL against the
//! host connection from inside a scalar function (its `exec` feature can't
//! read REALs), so this module wraps prepare/step/finalize directly — the same
//! pattern as SQLite's own ext/misc/eval.c. Statements are built as full text:
//! the only interpolated values are i64 ids and f64 literals we produced
//! ourselves (checked finite), so there is no injection surface.

use std::ffi::CString;
use std::os::raw::c_char;
use std::ptr;

use sqlite_loadable::api::{self, ValueType};
use sqlite_loadable::ext::{
    sqlite3, sqlite3_stmt, sqlite3ext_column_value, sqlite3ext_finalize, sqlite3ext_prepare_v2,
    sqlite3ext_step,
};
use sqlite_loadable::{Error, Result};

const SQLITE_OK: i32 = 0;
const SQLITE_ROW: i32 = 100;
const SQLITE_DONE: i32 = 101;

/// Owned prepared statement; finalized on drop so errors can't leak handles.
struct Stmt(*mut sqlite3_stmt);

impl Drop for Stmt {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe {
                sqlite3ext_finalize(self.0);
            }
        }
    }
}

fn prepare(db: *mut sqlite3, sql: &str) -> Result<Stmt> {
    let c = CString::new(sql)?;
    let mut stmt: *mut sqlite3_stmt = ptr::null_mut();
    let rc = unsafe { sqlite3ext_prepare_v2(db, c.as_ptr(), -1, &mut stmt, ptr::null_mut()) };
    if rc != SQLITE_OK {
        return Err(Error::new_message(format!(
            "rfm: prepare failed (code {rc}) for: {sql}"
        )));
    }
    Ok(Stmt(stmt))
}

fn step_to_done(stmt: &Stmt, sql: &str) -> Result<()> {
    loop {
        match unsafe { sqlite3ext_step(stmt.0) } {
            SQLITE_ROW => continue,
            SQLITE_DONE => return Ok(()),
            rc => {
                return Err(Error::new_message(format!(
                    "rfm: step failed (code {rc}) for: {sql}"
                )))
            }
        }
    }
}

/// Execute a single statement to completion.
pub fn exec(db: *mut sqlite3, sql: &str) -> Result<()> {
    let stmt = prepare(db, sql)?;
    step_to_done(&stmt, sql)
}

/// Execute a script of ';'-separated statements (used by rfm_init to run the
/// embedded schema). Iterates via prepare_v2's tail pointer, so comments and
/// literals containing ';' are handled correctly.
pub fn exec_multi(db: *mut sqlite3, sql: &str) -> Result<()> {
    let c = CString::new(sql)?;
    let end = unsafe { c.as_ptr().add(sql.len()) };
    let mut cur: *const c_char = c.as_ptr();
    while !cur.is_null() && (cur as usize) < (end as usize) {
        let mut stmt: *mut sqlite3_stmt = ptr::null_mut();
        let mut tail: *const c_char = ptr::null();
        let rc = unsafe { sqlite3ext_prepare_v2(db, cur, -1, &mut stmt, &mut tail) };
        if rc != SQLITE_OK {
            return Err(Error::new_message(format!(
                "rfm: schema prepare failed (code {rc})"
            )));
        }
        if stmt.is_null() {
            // Empty statement (';;', comment-only segment): no statement was
            // produced but the tail advanced — keep going. Break only if the
            // parser made no progress (whitespace-only remainder).
            if tail.is_null() || tail == cur {
                break;
            }
            cur = tail;
            continue;
        }
        let stmt = Stmt(stmt);
        step_to_done(&stmt, "<schema statement>")?;
        cur = tail;
    }
    Ok(())
}

/// Collect a single TEXT column over all rows (NULLs skipped). Used by
/// endorser liability, which must visit every distinct endorser of a memory.
pub fn query_column_text(db: *mut sqlite3, sql: &str) -> Result<Vec<String>> {
    let stmt = prepare(db, sql)?;
    let mut out = Vec::new();
    loop {
        match unsafe { sqlite3ext_step(stmt.0) } {
            SQLITE_ROW => {
                let value = unsafe { sqlite3ext_column_value(stmt.0, 0) };
                if api::value_type(&value) != ValueType::Null {
                    out.push(api::value_text(&value)?.to_string());
                }
            }
            SQLITE_DONE => return Ok(out),
            rc => {
                return Err(Error::new_message(format!(
                    "rfm: query failed (code {rc}) for: {sql}"
                )))
            }
        }
    }
}

/// Run a query expected to yield at most one row of `ncols` numeric columns.
/// Returns None if no row matched; NULL columns come back as None. INTEGER
/// and REAL columns are both read through sqlite3_value_double (exact for the
/// int64 ranges we store).
pub fn query_row(db: *mut sqlite3, sql: &str, ncols: usize) -> Result<Option<Vec<Option<f64>>>> {
    let stmt = prepare(db, sql)?;
    match unsafe { sqlite3ext_step(stmt.0) } {
        SQLITE_ROW => {
            let mut out = Vec::with_capacity(ncols);
            for i in 0..ncols {
                let value = unsafe { sqlite3ext_column_value(stmt.0, i as i32) };
                if api::value_type(&value) == ValueType::Null {
                    out.push(None);
                } else {
                    out.push(Some(api::value_double(&value)));
                }
            }
            Ok(Some(out))
        }
        SQLITE_DONE => Ok(None),
        rc => Err(Error::new_message(format!(
            "rfm: query failed (code {rc}) for: {sql}"
        ))),
    }
}
