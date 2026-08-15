//! sqlite-rfm: RFM-scored agent memory as a SQLite extension.
//!
//! Recency + Frequency arrive unified as ACT-R base-level activation
//! (Petrov 2006 incremental approximation); the Monetary analog is an EWMA of
//! retrieval-outcome feedback. `rfm_score(id)` is designed to be composed
//! with a similarity search: ORDER BY similarity * rfm_score(id) DESC.

mod clock;
pub mod config;
mod functions;
pub mod math;
mod sql;

use std::sync::{Arc, Mutex};

use sqlite_loadable::prelude::*;
use sqlite_loadable::{define_scalar_function_with_aux, Result};

use config::RfmConfig;
use functions::SharedConfig;

#[sqlite_entrypoint]
pub fn sqlite3_rfm_init(db: *mut sqlite3) -> Result<()> {
    // One config per connection load; every function shares it via aux.
    let cfg: SharedConfig = Arc::new(Mutex::new(RfmConfig::default()));

    // All functions read the clock and table state → none are DETERMINISTIC.
    let plain = FunctionFlags::UTF8;
    // Mutators are barred from views/triggers/generated columns.
    let direct = FunctionFlags::UTF8 | FunctionFlags::DIRECTONLY;

    define_scalar_function_with_aux(db, "rfm_init", 0, functions::rfm_init, direct, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_record_access", 1, functions::rfm_record_access, direct, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_record_outcome", 2, functions::rfm_record_outcome, direct, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_recency", 1, functions::rfm_recency, plain, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_frequency", 1, functions::rfm_frequency, plain, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_activation", 1, functions::rfm_activation, plain, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_value", 1, functions::rfm_value, plain, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_score", 1, functions::rfm_score, plain, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_prior", 1, functions::rfm_prior, plain, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_score_w", 3, functions::rfm_score_w, plain, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_score_w", 5, functions::rfm_score_w, plain, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_prunable", 2, functions::rfm_prunable, plain, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_config", 1, functions::rfm_config, plain, Arc::clone(&cfg))?;
    define_scalar_function_with_aux(db, "rfm_config", 2, functions::rfm_config, direct, Arc::clone(&cfg))?;
    Ok(())
}
