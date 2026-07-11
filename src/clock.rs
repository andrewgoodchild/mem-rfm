use std::time::{SystemTime, UNIX_EPOCH};

use crate::config::RfmConfig;

/// The single wall-clock touchpoint in the extension. Every function that
/// needs "now" goes through here, so rfm_config('now', t) freezes time for
/// tests and replay benchmarks.
pub fn now(cfg: &RfmConfig) -> f64 {
    cfg.frozen_now.unwrap_or_else(|| {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0)
    })
}
