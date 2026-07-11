//! End-to-end test: build the loadable extension, load it into a real sqlite3
//! CLI (Apple's binary has .load compiled out — point SQLITE3_BIN at a
//! Homebrew build), exercise every public function with a frozen clock, and
//! assert numeric equality against the same `math` module the extension uses.

use std::collections::HashMap;
use std::io::Write;
use std::process::{Command, Stdio};

use rfm::config::RfmConfig;
use rfm::math;

// Expectations derive from the same defaults the extension compiles in, so
// tuning a default can't silently leave the tests checking stale parameters.
fn defaults() -> RfmConfig {
    RfmConfig::default()
}

const TOL: f64 = 1e-9;

fn sqlite3_bin() -> String {
    if let Ok(bin) = std::env::var("SQLITE3_BIN") {
        return bin;
    }
    // Probe both Homebrew prefixes (Apple's CLI has .load compiled out).
    for cand in [
        "/opt/homebrew/opt/sqlite/bin/sqlite3",
        "/usr/local/opt/sqlite/bin/sqlite3",
    ] {
        if std::path::Path::new(cand).exists() {
            return cand.into();
        }
    }
    panic!("no .load-capable sqlite3 found in Homebrew prefixes; set SQLITE3_BIN");
}

/// The dylib under test: RFM_DYLIB override, else build the target the CLI
/// can load and use that artifact. Building here (cargo caches, so it's
/// milliseconds when fresh) guarantees the tests can never green-light a
/// stale dylib left over from an earlier build of a different target.
fn dylib_path() -> String {
    if let Ok(p) = std::env::var("RFM_DYLIB") {
        return p.trim_end_matches(".dylib").to_string();
    }
    static BUILD: std::sync::Once = std::sync::Once::new();
    let manifest = env!("CARGO_MANIFEST_DIR");
    // The .load-capable sqlite3 on macOS dev boxes is often the Rosetta
    // Homebrew build; match the CLI's architecture, not the host's.
    let target = std::env::var("RFM_TEST_TARGET").unwrap_or_else(|_| "x86_64-apple-darwin".into());
    BUILD.call_once(|| {
        let status = Command::new("cargo")
            .args(["build", "--release", "--target", &target])
            .current_dir(manifest)
            .status()
            .expect("failed to run cargo build");
        assert!(status.success(), "cargo build --release --target {target} failed");
    });
    format!("{manifest}/target/{target}/release/librfm")
}

/// Run a SQL script through the CLI with the extension loaded; return
/// (stdout, stderr).
fn run_sql(script: &str) -> (String, String) {
    let bin = sqlite3_bin();
    assert!(
        std::path::Path::new(&bin).exists(),
        "sqlite3 CLI with .load support not found at {bin}; set SQLITE3_BIN"
    );
    let mut child = Command::new(&bin)
        .arg("-batch")
        .arg(":memory:")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("failed to spawn sqlite3");
    let full = format!(".load {}\n{script}", dylib_path());
    child
        .stdin
        .as_mut()
        .expect("stdin")
        .write_all(full.as_bytes())
        .expect("write script");
    let out = child.wait_with_output().expect("wait sqlite3");
    (
        String::from_utf8_lossy(&out.stdout).into_owned(),
        String::from_utf8_lossy(&out.stderr).into_owned(),
    )
}

/// Parse `label|value` lines into a map.
fn parse(stdout: &str) -> HashMap<String, String> {
    stdout
        .lines()
        .filter_map(|l| l.split_once('|'))
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

fn assert_close(map: &HashMap<String, String>, key: &str, expected: f64) {
    let raw = map
        .get(key)
        .unwrap_or_else(|| panic!("missing output row '{key}'"));
    let got: f64 = raw.parse().unwrap_or_else(|_| panic!("row '{key}' not numeric: {raw}"));
    assert!(
        (got - expected).abs() < TOL,
        "{key}: got {got}, expected {expected}"
    );
}

#[test]
fn full_surface_with_frozen_clock() {
    let script = r#"
SELECT 'init', rfm_init();
SELECT 'init_again', rfm_init();
SELECT 'freeze', rfm_config('now', 1000000.0);
INSERT INTO rfm_memories(id, content, created_at) VALUES
  (1, 'alpha', 900000.0), (2, 'beta', 990000.0);
SELECT 'access1', rfm_record_access(1);
SELECT 'freeze2', rfm_config('now', 1005000.0);
SELECT 'access2', rfm_record_access(1);
SELECT 'outcome1', rfm_record_outcome(1, 1.0);
SELECT 'freeze3', rfm_config('now', 1010000.0);
SELECT 'recency1', rfm_recency(1);
SELECT 'recency2', rfm_recency(2);
SELECT 'freq1', rfm_frequency(1);
SELECT 'freq2', rfm_frequency(2);
SELECT 'act1', rfm_activation(1);
SELECT 'act2', rfm_activation(2);
SELECT 'value1', rfm_value(1);
SELECT 'score1', rfm_score(1);
SELECT 'score_w3', rfm_score_w(1, 1.0, 0.0);
SELECT 'score_w5', rfm_score_w(1, 0.5, 0.5, 3600.0, 0.3);
SELECT 'set_tau', rfm_config('tau', 3600.0);
SELECT 'get_tau', rfm_config('tau');
SELECT 'recency1b', rfm_recency(1);
SELECT 'unfreeze', coalesce(rfm_config('now', NULL), 'cleared');
SELECT 'get_now', coalesce(rfm_config('now'), 'unset');
SELECT 'row1', access_count || ',' || last_access || ',' || bla_cache || ',' || value_score || ',' || outcome_count
  FROM rfm_memories WHERE id = 1;
"#;
    let (stdout, stderr) = run_sql(script);
    assert!(stderr.is_empty(), "unexpected stderr: {stderr}");
    let map = parse(&stdout);

    assert_eq!(map["init"], "ok");
    assert_eq!(map["init_again"], "ok", "rfm_init must be idempotent");

    // access1: first access at t=1,000,000; created 900,000 → n=1, t1=0 (clamped).
    assert_close(&map, "access1", math::bla_hybrid_k2(1, Some(0.0), None, 100_000.0, defaults().decay));
    // access2 at 1,005,000 → n=2, t1=0, t2=5000.
    assert_close(
        &map,
        "access2",
        math::bla_hybrid_k2(2, Some(0.0), Some(5_000.0), 105_000.0, defaults().decay),
    );
    // First outcome initializes the EWMA directly.
    assert_close(&map, "outcome1", 1.0);

    // At t=1,010,000: last access 5,000s ago; memory 2 never accessed
    // (created 20,000s ago → falls back to creation age).
    assert_close(&map, "recency1", math::recency(5_000.0, defaults().tau));
    assert_close(&map, "recency2", math::recency(20_000.0, defaults().tau));
    assert_close(&map, "freq1", math::frequency(2));
    assert_close(&map, "freq2", math::frequency(0));

    let act1 = math::bla_hybrid_k2(2, Some(5_000.0), Some(10_000.0), 110_000.0, defaults().decay);
    let act2 = math::bla_hybrid_k2(0, None, None, 20_000.0, defaults().decay);
    assert_close(&map, "act1", act1);
    assert_close(&map, "act2", act2);

    assert_close(&map, "value1", 1.0);
    let v_eff = math::shrink(1.0, 1, defaults().shrink_k);
    assert_close(&map, "score1", math::score(act1, v_eff, defaults().w_a, defaults().w_v));
    assert_close(&map, "score_w3", math::score(act1, v_eff, 1.0, 0.0));
    let act1_d03 = math::bla_hybrid_k2(2, Some(5_000.0), Some(10_000.0), 110_000.0, 0.3);
    assert_close(&map, "score_w5", math::score(act1_d03, v_eff, 0.5, 0.5));

    // Config round-trip; recency now uses tau = 3600.
    assert_close(&map, "set_tau", 3_600.0);
    assert_close(&map, "get_tau", 3_600.0);
    assert_close(&map, "recency1b", math::recency(5_000.0, 3_600.0));
    assert_eq!(map["unfreeze"], "cleared");
    assert_eq!(map["get_now"], "unset");

    // Extension-maintained columns after two accesses and one outcome.
    assert_eq!(map["row1"], "2,1005000.0,1000000.0,1.0,1");
}

#[test]
fn ewma_progression_through_sql() {
    let script = r#"
SELECT rfm_init();
SELECT rfm_config('now', 1000.0);
INSERT INTO rfm_memories(id, content, created_at) VALUES (7, 'x', 0.0);
SELECT rfm_record_access(7);
SELECT 'v1', rfm_record_outcome(7, 1.0);
SELECT rfm_record_access(7);
SELECT 'v2', rfm_record_outcome(7, 1.0);
SELECT rfm_record_access(7);
SELECT 'v3', rfm_record_outcome(7, -1.0);
SELECT 'n_out', outcome_count FROM rfm_memories WHERE id = 7;
SELECT 'logged', count(*) FROM rfm_accesses WHERE memory_id = 7 AND outcome IS NOT NULL;
"#;
    let (stdout, stderr) = run_sql(script);
    assert!(stderr.is_empty(), "unexpected stderr: {stderr}");
    let map = parse(&stdout);
    let v1 = math::ewma_update(0.0, 0, 1.0, defaults().lambda);
    let v2 = math::ewma_update(v1, 1, 1.0, defaults().lambda);
    let v3 = math::ewma_update(v2, 2, -1.0, defaults().lambda);
    assert_close(&map, "v1", v1);
    assert_close(&map, "v2", v2);
    assert_close(&map, "v3", v3);
    assert_eq!(map["n_out"], "3");
    assert_eq!(map["logged"], "3");
}

#[test]
fn epoch_zero_timestamps_keep_t2_and_stay_consistent() {
    // Regression: bla_cache's old 0.0 sentinel dropped a legitimate second
    // access at wall time <= 0, and rfm_record_access's return value diverged
    // from what rfm_activation read back. Both must now agree exactly.
    let script = r#"
SELECT rfm_init();
SELECT rfm_config('now', 0.0);
INSERT INTO rfm_memories(id, content, created_at) VALUES (1, 'x', -100.0);
SELECT rfm_record_access(1);
SELECT rfm_config('now', 100.0);
SELECT 'returned', rfm_record_access(1);
SELECT 'reread', rfm_activation(1);
SELECT 'stored_t2', coalesce(bla_cache, 'NULL') FROM rfm_memories WHERE id = 1;
"#;
    let (stdout, stderr) = run_sql(script);
    assert!(stderr.is_empty(), "unexpected stderr: {stderr}");
    let map = parse(&stdout);
    // n=2, t1=0 (just accessed), t2=100 (the epoch-0 access), L=200.
    let expected = math::bla_hybrid_k2(2, Some(0.0), Some(100.0), 200.0, defaults().decay);
    assert_close(&map, "returned", expected);
    assert_close(&map, "reread", expected);
    assert_eq!(map["stored_t2"], "0.0", "epoch-0 access time must survive as t2");
}

#[test]
fn invalid_inputs_error_instead_of_coercing() {
    // Regression battery: NULL/typed-wrong inputs must error, never coerce.
    let script = r#"
SELECT rfm_init();
INSERT INTO rfm_memories(id, content, created_at) VALUES (0, 'zero', 0.0), (1, 'one', 0.0);
SELECT rfm_record_access(1);
SELECT rfm_record_outcome(1, NULL);
SELECT rfm_record_access(1.9);
SELECT rfm_record_access('abc');
SELECT rfm_score_w(1, NULL, 0.3);
SELECT rfm_score_w(1, 0.7, 0.3, 'garbage', 0.5);
SELECT rfm_score_w(1, 0.7, 0.3, -1.0, 0.5);
SELECT 'count0', access_count FROM rfm_memories WHERE id = 0;
SELECT 'count1', access_count FROM rfm_memories WHERE id = 1;
SELECT 'value1', value_score FROM rfm_memories WHERE id = 1;
"#;
    let (stdout, stderr) = run_sql(script);
    // Note: 'garbage' coerces to 0.0 under SQLite text affinity (Text, not
    // NULL, so require_f64 passes) and is then caught by the tau > 0 check.
    for needle in [
        "outcome must not be NULL",
        "id must be an INTEGER",
        "w_a must not be NULL",
        "tau must be > 0",
    ] {
        assert!(stderr.contains(needle), "stderr missing '{needle}': {stderr}");
    }
    let map = parse(&stdout);
    assert_eq!(map["count0"], "0", "id coercion must not touch memory 0");
    assert_eq!(map["count1"], "1", "fractional id must not touch memory 1");
    assert_eq!(map["value1"], "0.0", "NULL outcome must not move the EWMA");
}

#[test]
fn one_outcome_per_access() {
    // Regression: a second outcome without a new access must error and leave
    // both the log and the summary untouched, so replaying rfm_accesses can
    // always reproduce value_score.
    let script = r#"
SELECT rfm_init();
INSERT INTO rfm_memories(id, content, created_at) VALUES (1, 'x', 0.0);
SELECT rfm_record_access(1);
SELECT 'first', rfm_record_outcome(1, 1.0);
SELECT rfm_record_outcome(1, -1.0);
SELECT 'value', value_score FROM rfm_memories WHERE id = 1;
SELECT 'n_out', outcome_count FROM rfm_memories WHERE id = 1;
SELECT 'logged', outcome FROM rfm_accesses WHERE memory_id = 1;
SELECT rfm_record_access(1);
SELECT 'second', rfm_record_outcome(1, -1.0);
SELECT 'n_out2', outcome_count FROM rfm_memories WHERE id = 1;
"#;
    let (stdout, stderr) = run_sql(script);
    assert!(
        stderr.contains("already has an outcome"),
        "double outcome must error: {stderr}"
    );
    let map = parse(&stdout);
    assert_close(&map, "first", 1.0);
    assert_eq!(map["value"], "1.0", "rejected outcome must not move the EWMA");
    assert_eq!(map["n_out"], "1");
    assert_eq!(map["logged"], "1.0", "log must keep the first outcome");
    // After a fresh access, feedback is accepted again.
    assert_close(&map, "second", math::ewma_update(1.0, 1, -1.0, defaults().lambda));
    assert_eq!(map["n_out2"], "2");
}

#[test]
fn errors_are_sql_errors_not_crashes() {
    let script = r#"
SELECT rfm_init();
INSERT INTO rfm_memories(id, content, created_at) VALUES (1, 'a', 0.0);
SELECT rfm_record_access(999);
SELECT rfm_record_outcome(1, 0.5);
SELECT rfm_record_outcome(1, 2.0);
SELECT rfm_config('bogus');
SELECT rfm_config('decay', 1.5);
SELECT rfm_config('tau', NULL);
SELECT 'alive', 1;
"#;
    let (stdout, stderr) = run_sql(script);
    for needle in [
        "no such memory id 999",
        "has no recorded access",
        "unknown config key 'bogus'",
        "decay must be in (0, 1)",
        "cannot be NULL",
    ] {
        assert!(stderr.contains(needle), "stderr missing '{needle}': {stderr}");
    }
    // outcome 2.0 rejected before any access exists is masked by the
    // no-access error; validate the range check separately:
    let (_, stderr2) = run_sql(
        "SELECT rfm_init();\n\
         INSERT INTO rfm_memories(id, content, created_at) VALUES (1, 'a', 0.0);\n\
         SELECT rfm_record_access(1);\n\
         SELECT rfm_record_outcome(1, 2.0);\n",
    );
    assert!(stderr2.contains("outcome must be in [-1, 1]"), "{stderr2}");
    assert!(parse(&stdout).contains_key("alive"), "CLI session must survive errors");
}
