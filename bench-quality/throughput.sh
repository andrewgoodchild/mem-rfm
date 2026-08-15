#!/bin/bash
# Scoring-throughput benchmark: rfm_score(id) (Petrov k=2 from one summary row)
# vs exact ACT-R recompute scanning rfm_accesses. Also reports max activation
# approximation error. Requires a .load-capable sqlite3 (SQLITE3_BIN).
set -euo pipefail
cd "$(dirname "$0")"

# Resolve a .load-capable CLI and a dylib it can actually load (arch must
# match, so probe the combination rather than assume a machine layout).
if [ -z "${SQLITE3_BIN:-}" ]; then
  for cand in /opt/homebrew/opt/sqlite/bin/sqlite3 /usr/local/opt/sqlite/bin/sqlite3 "$(command -v sqlite3 || true)"; do
    [ -n "$cand" ] && [ -x "$cand" ] && SQLITE3_BIN="$cand" && break
  done
fi
DYLIB="${DYLIB:-${RFM_DYLIB:-}}"
if [ -z "${DYLIB:-}" ]; then
  for cand in ../target/release/librfm ../target/x86_64-apple-darwin/release/librfm; do
    [ -f "$cand.dylib" ] || continue
    # Probe must call an rfm_ function: a failed .load via -cmd still exits 0
    # if the follow-up SQL doesn't need the extension.
    if echo "SELECT rfm_config('tau');" | "$SQLITE3_BIN" -cmd ".load $cand" :memory: >/dev/null 2>&1; then
      DYLIB="$cand"; break
    fi
  done
fi
if [ -z "${DYLIB:-}" ]; then
  echo "no loadable librfm.dylib found for $SQLITE3_BIN — run cargo build --release (or set DYLIB)" >&2
  exit 1
fi
NOW=1800000000.0

run_timed() { # db sql -> seconds (.timer output only prints on the stdin path)
  printf '.load %s\nSELECT rfm_config(%s, %s);\n.timer on\n%s\n' \
    "$DYLIB" "'now'" "$NOW" "$2" \
    | "$SQLITE3_BIN" "$1" 2>&1 | grep -o 'real [0-9.]*' | tail -1 | awk '{print $2}'
}

run_value() { # db sql -> last output line
  printf '.load %s\nSELECT rfm_config(%s, %s);\n%s\n' "$DYLIB" "'now'" "$NOW" "$2" \
    | "$SQLITE3_BIN" "$1" 2>&1 | tail -1
}

echo "| rows | accesses/row | rfm_score (s) | exact recompute (s) | us/row | max abs err |"
echo "|---|---|---|---|---|---|"

for spec in "10000 20" "100000 20" "1000000 20" "100000 200"; do
  set -- $spec; N=$1; A=$2
  DB="bench_${N}_${A}.db"
  [ -f "$DB" ] || python3 throughput_gen.py "$DB" "$N" "$A" > /dev/null

  T_SCORE=$(run_timed "$DB" "SELECT sum(rfm_score(id)) FROM rfm_memories;")
  T_EXACT=$(run_timed "$DB" "SELECT sum(b) FROM (
      SELECT ln(sum(pow(max($NOW - accessed_at, 0.001), -0.5))) AS b
      FROM rfm_accesses GROUP BY memory_id);")
  ERR=$(run_value "$DB" "SELECT max(abs(rfm_activation(m.id) - e.b)) FROM rfm_memories m JOIN (
       SELECT memory_id, ln(sum(pow(max($NOW - accessed_at, 0.001), -0.5))) AS b
       FROM rfm_accesses GROUP BY memory_id) e ON e.memory_id = m.id;")
  US_PER_ROW=$(echo "$T_SCORE $N" | awk '{printf "%.2f", $1 / $2 * 1000000}')
  echo "| $N | $A | $T_SCORE | $T_EXACT | $US_PER_ROW | $ERR |"
done
