/// Per-connection tunables. One instance is created when the extension loads
/// into a connection and shared (Arc<Mutex<_>>) across all registered
/// functions, so `rfm_config` changes are visible connection-wide but never
/// cross-process or cross-connection.
#[derive(Clone, Debug)]
pub struct RfmConfig {
    /// Recency time constant in seconds (rfm_recency only).
    pub tau: f64,
    /// ACT-R base-level decay d. Must be in (0, 1): the Petrov tail term
    /// divides by (1 - d).
    pub decay: f64,
    /// EWMA weight for outcome feedback.
    pub lambda: f64,
    /// Weight of normalized activation in rfm_score.
    pub w_a: f64,
    /// Weight of normalized value in rfm_score.
    pub w_v: f64,
    /// Confidence-shrink constant k: effective value = value * n/(n + k).
    pub shrink_k: f64,
    /// Prior strength for rfm_prior: (1-beta) + beta*rfm_score. Bounds how
    /// much usage history can perturb a similarity ranking. Default frozen
    /// at 0.3 by the pre-registered composition experiment (PROTOCOL.md).
    pub beta: f64,
    /// ACT-R's retrieval threshold τ and activation noise s, which set where
    /// the activation→[0,1] squash is centred and how steep it is. ACT-R fits
    /// these PER MODEL (τ spans −60..+0.5 across its own tutorial; s is
    /// recommended in [0.2, 0.8]). Ours were hardcoded at 0.0/1.0, which on
    /// second-scale lags puts a whole store in the squash's left tail — see
    /// docs/theory.md. Exposed for fitting under PROTOCOL.md Amendment 11;
    /// defaults unchanged so nothing moves until an experiment says so.
    pub theta: f64,
    pub s: f64,
    /// Weights for memories tagged kind='procedural'. ACT-R selects
    /// production rules by learned UTILITY rather than base-level activation,
    /// so procedural memories weight the outcome axis higher. Theoretically
    /// motivated, NOT measured — see docs/theory.md.
    pub w_a_proc: f64,
    pub w_v_proc: f64,
    /// When set via rfm_config('now', t), all functions read this instead of
    /// the wall clock. Cleared with rfm_config('now', NULL).
    pub frozen_now: Option<f64>,
}

impl Default for RfmConfig {
    fn default() -> Self {
        RfmConfig {
            tau: 86_400.0,
            decay: 0.5,
            lambda: 0.3,
            w_a: 0.7,
            w_v: 0.3,
            shrink_k: 3.0,
            beta: 0.3,
            theta: 0.0,
            s: 1.0,
            w_a_proc: 0.3,
            w_v_proc: 0.7,
            frozen_now: None,
        }
    }
}

/// Per-parameter range rules. Single owner of what a valid value is (and of
/// the error strings) for both the rfm_config path and rfm_score_w overrides.
pub fn check_tau(v: f64) -> Result<(), String> {
    if v > 0.0 { Ok(()) } else { Err("rfm: tau must be > 0".into()) }
}

pub fn check_decay(v: f64) -> Result<(), String> {
    // (0, 1) exclusive: the Petrov tail term divides by (1 - d).
    if v > 0.0 && v < 1.0 { Ok(()) } else { Err("rfm: decay must be in (0, 1)".into()) }
}

pub fn check_lambda(v: f64) -> Result<(), String> {
    if v > 0.0 && v <= 1.0 { Ok(()) } else { Err("rfm: lambda must be in (0, 1]".into()) }
}

pub fn check_positive(key: &str, v: f64) -> Result<(), String> {
    if v > 0.0 { Ok(()) } else { Err(format!("rfm: {key} must be > 0")) }
}

pub fn check_nonnegative(key: &str, v: f64) -> Result<(), String> {
    if v >= 0.0 { Ok(()) } else { Err(format!("rfm: {key} must be >= 0")) }
}

pub fn check_beta(v: f64) -> Result<(), String> {
    if (0.0..=1.0).contains(&v) { Ok(()) } else { Err("rfm: beta must be in [0, 1]".into()) }
}

impl RfmConfig {
    pub fn get(&self, key: &str) -> Result<Option<f64>, String> {
        match key {
            "tau" => Ok(Some(self.tau)),
            "decay" => Ok(Some(self.decay)),
            "lambda" => Ok(Some(self.lambda)),
            "w_a" => Ok(Some(self.w_a)),
            "w_v" => Ok(Some(self.w_v)),
            "shrink_k" => Ok(Some(self.shrink_k)),
            "beta" => Ok(Some(self.beta)),
            "theta" => Ok(Some(self.theta)),
            "s" => Ok(Some(self.s)),
            "w_a_proc" => Ok(Some(self.w_a_proc)),
            "w_v_proc" => Ok(Some(self.w_v_proc)),
            "now" => Ok(self.frozen_now),
            _ => Err(format!("rfm: unknown config key '{key}'")),
        }
    }

    /// Set a key; `None` clears 'now' (invalid for other keys). Returns the
    /// stored value.
    pub fn set(&mut self, key: &str, value: Option<f64>) -> Result<Option<f64>, String> {
        let v = match value {
            Some(v) if !v.is_finite() => {
                return Err(format!("rfm: config '{key}' must be finite"));
            }
            Some(v) => v,
            None => {
                if key == "now" {
                    self.frozen_now = None;
                    return Ok(None);
                }
                return Err(format!("rfm: config '{key}' cannot be NULL"));
            }
        };
        match key {
            "tau" => { check_tau(v)?; self.tau = v }
            "decay" => { check_decay(v)?; self.decay = v }
            "lambda" => { check_lambda(v)?; self.lambda = v }
            "w_a" => { check_nonnegative(key, v)?; self.w_a = v }
            "w_v" => { check_nonnegative(key, v)?; self.w_v = v }
            "shrink_k" => { check_nonnegative(key, v)?; self.shrink_k = v }
            "beta" => { check_beta(v)?; self.beta = v }
            "theta" => { self.theta = v }
            "s" => { check_positive(key, v)?; self.s = v }
            "w_a_proc" => { check_nonnegative(key, v)?; self.w_a_proc = v }
            "w_v_proc" => { check_nonnegative(key, v)?; self.w_v_proc = v }
            "now" => self.frozen_now = Some(v),
            _ => return Err(format!("rfm: unknown config key '{key}'")),
        }
        Ok(Some(v))
    }
}
