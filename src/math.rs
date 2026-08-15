//! Pure scoring math — no SQLite dependencies, fully unit-testable.
//!
//! Sources:
//! - ACT-R base-level learning: Anderson & Lebiere (1998), The Atomic
//!   Components of Thought. B = ln(Σ_i t_i^(-d)).
//! - Incremental approximation: Petrov, A. A. (2006), "Computationally
//!   efficient approximation of the base-level learning equation in ACT-R",
//!   Proc. ICCM. We use the hybrid form (Eq. 3) with k = 2.
//! - EWMA: standard exponentially weighted moving average.

/// Minimum lag in seconds. Power-law decay t^(-d) is singular at t = 0, so
/// lags are clamped, mirroring common ACT-R implementation practice. Also the
/// effective lag of a just-recorded access.
pub const EPS: f64 = 1e-3;

/// Logistic squash parameters mapping activation to [0,1]: ACT-R's own
/// retrieval-probability equation P = 1/(1 + exp(-(B - θ)/s))
/// (Anderson & Lebiere 1998). Fixed constants in v0.1.
pub const THETA: f64 = 0.0;
pub const S: f64 = 1.0;

/// Exact ACT-R base-level activation over a full access history.
/// `lags` are seconds since each access. Empty history → -inf.
/// Reference implementation for tests and audits; the extension's hot path
/// uses `bla_hybrid_k2`.
pub fn bla_exact(lags: &[f64], d: f64) -> f64 {
    if lags.is_empty() {
        return f64::NEG_INFINITY;
    }
    lags.iter().map(|t| t.max(EPS).powf(-d)).sum::<f64>().ln()
}

/// Anderson & Lebiere (1998) "optimized learning" (Petrov 2006, Eq. 2):
/// B ≈ ln(n / (1 - d)) - d·ln(L), assuming n uses spread evenly over
/// lifetime L. Kept as the k = 0 comparison baseline for tests.
pub fn bla_optimized(n: i64, lifetime: f64, d: f64) -> f64 {
    let l = lifetime.max(EPS);
    ((n as f64) / (1.0 - d)).ln() - d * l.ln()
}

/// Petrov (2006, Eq. 3) hybrid approximation with k = 2: the two most recent
/// lags t1 ≤ t2 are kept exactly; the remaining n - 2 events are approximated
/// as uniformly distributed over [t2, L] (closed-form integral of a uniform
/// event density under power-law decay):
///
///   B ≈ ln( t1^(-d) + t2^(-d) + (n-2)·(L^(1-d) - t2^(1-d)) / ((1-d)·(L - t2)) )
///
/// n ≤ 2 is exact. n = 0 treats creation as a single virtual use of age L.
/// Rows with summary state but no retained access times (bulk import or
/// migration from another store, or host-modified rows) degrade to optimized
/// learning (k = 0) — the principled Petrov estimate for exactly that state —
/// rather than erroring, which would let one imported row poison every
/// full-table ORDER BY scan.
pub fn bla_hybrid_k2(n: i64, t1: Option<f64>, t2: Option<f64>, lifetime: f64, d: f64) -> f64 {
    let l = lifetime.max(EPS);
    if n <= 0 {
        return -d * l.ln();
    }
    let t1 = match t1 {
        Some(t) => t.max(EPS),
        None => return bla_optimized(n, l, d),
    };
    if n == 1 {
        return t1.powf(-d).ln();
    }
    let t2 = match t2 {
        Some(t) => t.max(t1),
        None => return bla_optimized(n, l, d),
    };
    let head = t1.powf(-d) + t2.powf(-d);
    if n == 2 {
        return head.ln();
    }
    let l = l.max(t2);
    let m = (n - 2) as f64;
    // Degenerate window: all tail events at essentially the same age as t2.
    let tail = if l - t2 < EPS {
        m * t2.powf(-d)
    } else {
        m * (l.powf(1.0 - d) - t2.powf(1.0 - d)) / ((1.0 - d) * (l - t2))
    };
    (head + tail).ln()
}

/// EWMA outcome update. The first outcome initializes the estimate directly
/// (no fake zero prior); afterwards value ← λ·outcome + (1-λ)·value.
pub fn ewma_update(prev: f64, n_prev_outcomes: i64, outcome: f64, lambda: f64) -> f64 {
    if n_prev_outcomes <= 0 {
        outcome
    } else {
        lambda * outcome + (1.0 - lambda) * prev
    }
}

/// Confidence shrink: with few outcomes the EWMA is noise, so pull it toward
/// neutral: effective = value · n/(n + k). k = 0 disables shrinking.
pub fn shrink(value: f64, n_outcomes: i64, k: f64) -> f64 {
    let n = n_outcomes.max(0) as f64;
    if n + k <= 0.0 {
        return 0.0;
    }
    value * n / (n + k)
}

/// Recency component: exp(-Δ/τ) for Δ seconds since the anchor event.
pub fn recency(delta_seconds: f64, tau: f64) -> f64 {
    (-delta_seconds.max(0.0) / tau).exp()
}

/// Frequency component: ln(1 + access_count).
pub fn frequency(access_count: i64) -> f64 {
    (1.0 + access_count.max(0) as f64).ln()
}

/// Activation → [0,1] via ACT-R retrieval probability (see THETA/S).
pub fn logistic(b: f64) -> f64 {
    1.0 / (1.0 + (-(b - THETA) / S).exp())
}

/// Value in [-1,1] → [0,1]; clamped to defend against out-of-range stored data.
pub fn value01(v: f64) -> f64 {
    ((v + 1.0) / 2.0).clamp(0.0, 1.0)
}

/// Headline score: w_a·P(activation) + w_v·value01(effective value).
/// In [0,1] when w_a + w_v = 1; custom weights scale the range (documented,
/// not renormalized).
pub fn score(activation_b: f64, effective_value: f64, w_a: f64, w_v: f64) -> f64 {
    w_a * logistic(activation_b) + w_v * value01(effective_value)
}

#[cfg(test)]
mod tests {
    use super::*;

    const D: f64 = 0.5;

    /// Build (lags, t1, t2, lifetime) from access wall-times and a now.
    fn state(times: &[f64], created: f64, now: f64) -> (Vec<f64>, Option<f64>, Option<f64>, f64) {
        let mut lags: Vec<f64> = times.iter().map(|t| now - t).collect();
        lags.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let t1 = lags.first().copied();
        let t2 = lags.get(1).copied();
        (lags, t1, t2, now - created)
    }

    fn hybrid_err(times: &[f64], created: f64, now: f64) -> (f64, f64) {
        let (lags, t1, t2, l) = state(times, created, now);
        let exact = bla_exact(&lags, D);
        let approx = bla_hybrid_k2(times.len() as i64, t1, t2, l, D);
        let k0 = bla_optimized(times.len() as i64, l, D);
        ((approx - exact).abs(), (k0 - exact).abs())
    }

    #[test]
    fn exact_for_n_up_to_2() {
        let now = 1_000_000.0;
        for times in [vec![999_000.0], vec![990_000.0, 999_500.0]] {
            let (lags, t1, t2, l) = state(&times, 900_000.0, now);
            let exact = bla_exact(&lags, D);
            let approx = bla_hybrid_k2(times.len() as i64, t1, t2, l, D);
            assert!((approx - exact).abs() < 1e-12, "n<=2 must be exact");
        }
    }

    #[test]
    fn never_accessed_uses_creation_age() {
        let b = bla_hybrid_k2(0, None, None, 86_400.0, D);
        assert!((b - (-D * 86_400.0f64.ln())).abs() < 1e-12);
        // Older never-accessed memories decay lower.
        assert!(bla_hybrid_k2(0, None, None, 10.0 * 86_400.0, D) < b);
    }

    #[test]
    fn uniform_history_small_error() {
        // 50 accesses evenly over 10 days — matches the tail's uniformity
        // assumption, so error should be small.
        let created = 0.0;
        let now = 864_000.0;
        let times: Vec<f64> = (0..50).map(|i| 10_000.0 + i as f64 * 17_000.0).collect();
        let (err_k2, _) = hybrid_err(&times, created, now);
        assert!(err_k2 < 0.05, "uniform-history error too large: {err_k2}");
    }

    #[test]
    fn recent_burst_hybrid_beats_optimized() {
        // Quiescent gap then a recent burst — Petrov's motivating case where
        // k = 0 underestimates the recency spike.
        let created = 0.0;
        let now = 864_000.0;
        let mut times: Vec<f64> = (0..20).map(|i| 1_000.0 + i as f64 * 2_000.0).collect();
        times.extend([863_000.0, 863_500.0, 863_900.0]);
        let (err_k2, err_k0) = hybrid_err(&times, created, now);
        assert!(err_k2 < err_k0, "hybrid ({err_k2}) should beat k=0 ({err_k0})");
        assert!(err_k2 < 0.35, "burst-history error too large: {err_k2}");
    }

    #[test]
    fn quiescent_period_bounded_error() {
        // Burst early, then nothing for a long time.
        let created = 0.0;
        let now = 864_000.0;
        let times: Vec<f64> = (0..30).map(|i| 5_000.0 + i as f64 * 300.0).collect();
        let (err_k2, err_k0) = hybrid_err(&times, created, now);
        assert!(err_k2 <= err_k0 + 1e-9);
        assert!(err_k2 < 0.35, "quiescent-history error too large: {err_k2}");
    }

    #[test]
    fn degenerate_same_instant_history() {
        // All accesses at (nearly) the same moment → tail limit branch.
        let now = 1_000_000.0;
        let times = vec![999_000.0; 10];
        let (lags, t1, t2, l) = state(&times, 999_000.0, now);
        let exact = bla_exact(&lags, D);
        let approx = bla_hybrid_k2(10, t1, t2, l, D);
        assert!(
            (approx - exact).abs() < 1e-9,
            "same-instant history should hit the exact limit: {approx} vs {exact}"
        );
    }

    #[test]
    fn ewma_sequence() {
        let l = 0.3;
        let v1 = ewma_update(0.0, 0, 1.0, l);
        assert_eq!(v1, 1.0, "first outcome initializes directly");
        let v2 = ewma_update(v1, 1, 1.0, l);
        assert!((v2 - 1.0).abs() < 1e-12);
        let v3 = ewma_update(v2, 2, -1.0, l);
        assert!((v3 - 0.4).abs() < 1e-12);
    }

    #[test]
    fn shrink_behavior() {
        assert_eq!(shrink(1.0, 0, 3.0), 0.0);
        assert!((shrink(1.0, 3, 3.0) - 0.5).abs() < 1e-12);
        assert!(shrink(1.0, 100, 3.0) > 0.97);
        assert_eq!(shrink(0.8, 5, 0.0), 0.8, "k = 0 disables shrinking");
        assert_eq!(shrink(0.8, 0, 0.0), 0.0, "no outcomes, no shrink constant");
    }

    #[test]
    fn recency_and_frequency_curves() {
        assert_eq!(recency(0.0, 86_400.0), 1.0);
        assert!((recency(86_400.0, 86_400.0) - (-1.0f64).exp()).abs() < 1e-12);
        assert_eq!(recency(-5.0, 86_400.0), 1.0, "future anchors clamp to 1");
        assert_eq!(frequency(0), 0.0);
        assert!((frequency(1) - 2.0f64.ln()).abs() < 1e-12);
    }

    #[test]
    fn logistic_and_score_bounds() {
        assert_eq!(logistic(f64::NEG_INFINITY), 0.0);
        assert!((logistic(0.0) - 0.5).abs() < 1e-12);
        assert!(logistic(50.0) > 0.999);
        assert_eq!(value01(-1.5), 0.0);
        assert_eq!(value01(1.5), 1.0);
        let s = score(0.0, 0.0, 0.7, 0.3);
        assert!((s - (0.7 * 0.5 + 0.3 * 0.5)).abs() < 1e-12);
    }
}
