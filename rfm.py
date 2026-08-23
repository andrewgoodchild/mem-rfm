"""sqlite-rfm in pure Python: the same SQL contract, no compiled extension.

Registers the rfm_* scalar functions on a sqlite3 connection via
create_function, so every query written against the Rust extension keeps
working verbatim:

    import rfm, sqlite3
    db = sqlite3.connect("memories.db")
    rfm.register(db)
    db.execute("SELECT rfm_init()")
    db.execute("SELECT id FROM rfm_memories ORDER BY rfm_score(id) DESC")

This is a port of the retired Rust extension's src/{math,functions,config,
clock}.rs — sources that exist only at the `archive/rust-extension` git tag
now, not in this tree. It replaced the extension once a parity check (run at
that tag, before the Rust sources were removed) showed the two agree to
float round-off over a branch-covering corpus and identical operation
sequences; tests/test_rfm.py now pins the semantics. Preserved deliberately:

  * One config per register() call (connection-wide, never cross-process),
    mutated through rfm_config with the same validation and error strings.
  * rfm_config('now', t) freezes the clock for every function.
  * rfm_record_access writes the access-log row before the summary row —
    the summary is what scoring trusts, so it must never advance ahead of
    the log — and shifts last_access into bla_cache (the Petrov k=2 t2
    anchor) in one UPDATE whose RHS reads pre-update values.
  * rfm_record_outcome accepts exactly one outcome per access, enforced by
    the `outcome IS NULL` guard on the latest log row.
  * Rows with summary state but no retained access times degrade to
    optimized learning (k = 0) rather than erroring.

Differences from the extension, all inherent to stdlib sqlite3:

  * DIRECTONLY flags are not exposed by create_function, so the mutators
    are callable from views/triggers. Do not do that.
  * A UDF that raises surfaces to the caller as sqlite3.OperationalError
    ("user-defined function raised exception"); the specific rfm: message
    is printed to stderr and kept on the state object register() returns
    (r.last_error) for hosts that relay errors to a caller.
  * Parameters are bound, not interpolated: stdlib prepare supports it,
    so f64 literal formatting is unnecessary.

Every equation cites its source at the point of use; the derivations are
docs/theory.md.
"""
import math as _m
import sys
import time

VERSION = "0.3.0"

# Minimum lag in seconds: power-law decay t^(-d) is singular at t = 0, so
# lags are clamped, mirroring common ACT-R implementation practice.
EPS = 1e-3

# One tuple entry per statement — never a single string split on ";", which
# breaks silently the day the schema gains a trigger or a string literal
# containing a semicolon. executescript is not an option either: rfm_init
# runs inside a UDF, and executescript issues an implicit COMMIT
# mid-statement.
SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS rfm_memories (
  id            INTEGER PRIMARY KEY,
  content       TEXT NOT NULL,
  created_at    REAL NOT NULL,
  access_count  INTEGER NOT NULL DEFAULT 0,
  last_access   REAL,
  bla_cache     REAL,
  value_score   REAL NOT NULL DEFAULT 0.0,
  outcome_count INTEGER NOT NULL DEFAULT 0
)""",
    """CREATE TABLE IF NOT EXISTS rfm_accesses (
  memory_id   INTEGER NOT NULL REFERENCES rfm_memories(id),
  accessed_at REAL NOT NULL,
  outcome     REAL
)""",
    """CREATE INDEX IF NOT EXISTS rfm_accesses_mem_time
  ON rfm_accesses(memory_id, accessed_at DESC)""",
    # The ledger's path-dependent parameters. value_score is an EWMA, so it
    # is a function of the lambda it was built under; nothing else in the
    # summary row depends on config history.
    """CREATE TABLE IF NOT EXISTS rfm_meta (
  key   TEXT PRIMARY KEY,
  value REAL NOT NULL
)""",
)
SCHEMA = ";\n".join(SCHEMA_STATEMENTS) + ";"


# ---------------------------------------------------------------- pure math
# Anderson & Lebiere (1998): B = ln(Σ t_i^(-d)); Petrov (2006) Eq. 2/3.

def bla_exact(lags, d):
    if not lags:
        return float("-inf")
    return _m.log(sum(max(t, EPS) ** -d for t in lags))


def bla_optimized(n, lifetime, d):
    l = max(lifetime, EPS)
    return _m.log(n / (1.0 - d)) - d * _m.log(l)


def bla_hybrid_k2(n, t1, t2, lifetime, d):
    l = max(lifetime, EPS)
    if n <= 0:
        # Never accessed: creation treated as a single virtual use of age L.
        return -d * _m.log(l)
    if t1 is None:
        # Summary state without retained times (bulk import): Petrov k = 0.
        return bla_optimized(n, l, d)
    t1 = max(t1, EPS)
    if n == 1:
        return _m.log(t1 ** -d)
    if t2 is None:
        return bla_optimized(n, l, d)
    t2 = max(t2, t1)
    head = t1 ** -d + t2 ** -d
    if n == 2:
        return _m.log(head)
    l = max(l, t2)
    m = float(n - 2)
    if l - t2 < EPS:  # degenerate window: tail events all at age ~t2
        tail = m * t2 ** -d
    else:
        tail = m * (l ** (1.0 - d) - t2 ** (1.0 - d)) / ((1.0 - d) * (l - t2))
    return _m.log(head + tail)


def ewma_update(prev, n_prev_outcomes, outcome, lam):
    # First outcome initializes directly — no fake zero prior.
    return outcome if n_prev_outcomes <= 0 else lam * outcome + (1.0 - lam) * prev


def shrink(value, n_outcomes, k):
    n = float(max(n_outcomes, 0))
    if n + k <= 0.0:
        return 0.0
    return value * n / (n + k)


def logistic_p(b, theta, s):
    # ACT-R retrieval probability P = 1/(1 + exp(-(B - θ)/s)).
    if b == float("-inf"):
        return 0.0
    try:
        return 1.0 / (1.0 + _m.exp(-(b - theta) / max(s, 1e-9)))
    except OverflowError:
        return 0.0


def value01(v):
    return min(max((v + 1.0) / 2.0, 0.0), 1.0)


def score_p(b, v_eff, w_a, w_v, theta, s):
    return w_a * logistic_p(b, theta, s) + w_v * value01(v_eff)


# ---------------------------------------------------------------- config

_CHECKS = {
    "tau": lambda v: v > 0.0 or "rfm: tau must be > 0",
    # (0, 1) exclusive: the Petrov tail term divides by (1 - d).
    "decay": lambda v: 0.0 < v < 1.0 or "rfm: decay must be in (0, 1)",
    "lambda": lambda v: 0.0 < v <= 1.0 or "rfm: lambda must be in (0, 1]",
    "w_a": lambda v: v >= 0.0 or "rfm: w_a must be >= 0",
    "w_v": lambda v: v >= 0.0 or "rfm: w_v must be >= 0",
    "shrink_k": lambda v: v >= 0.0 or "rfm: shrink_k must be >= 0",
    "beta": lambda v: 0.0 <= v <= 1.0 or "rfm: beta must be in [0, 1]",
    "theta": lambda v: True,
    "s": lambda v: v > 0.0 or "rfm: s must be > 0",
    "now": lambda v: True,
}

DEFAULTS = {"tau": 86_400.0, "decay": 0.5, "lambda": 0.3, "w_a": 0.7,
            "w_v": 0.3, "shrink_k": 3.0, "beta": 0.3, "theta": 0.0,
            "s": 1.0, "now": None}


def _normalize_row(n, created, t1w, t2w, value, n_out):
    """The six extension-maintained columns (access_count, created_at,
    last_access, bla_cache, value_score, outcome_count), typed and defended
    against a NULL n/created/value/n_out a caller-supplied row might carry
    (the schema's own NOT NULL columns never are). t1w/t2w stay None rather
    than collapsing to 0.0 -- that distinction is bla_hybrid_k2's k=0/k=1/k=2
    branch selector. One shape, shared by _load, rfm_record_access, and
    rfm_prior_of."""
    return (int(n or 0), float(created or 0.0),
            None if t1w is None else float(t1w),
            None if t2w is None else float(t2w),
            float(value or 0.0), int(n_out or 0))


class _Rfm:
    """One instance per register() call; every UDF closes over it."""

    def __init__(self, conn):
        self.conn = conn
        self.cfg = dict(DEFAULTS)
        # Message of the most recent UDF error. stdlib sqlite3 replaces a
        # raising UDF's message with a generic one; hosts that want the
        # specific rfm: text read this right after catching OperationalError.
        self.last_error = None

    # -- plumbing ---------------------------------------------------------

    def now(self):
        return self.cfg["now"] if self.cfg["now"] is not None else time.time()

    def _load(self, mid):
        if not isinstance(mid, int):
            raise ValueError("rfm: id must be an INTEGER")
        row = self.conn.execute(
            "SELECT access_count, created_at, last_access, bla_cache, "
            "value_score, outcome_count FROM rfm_memories WHERE id = ?",
            (mid,)).fetchone()
        if row is None:
            raise ValueError(f"rfm: no such memory id {mid}")
        return _normalize_row(*row)

    def _activation(self, row, now):
        n, created, t1w, t2w, _v, _no = row
        return bla_hybrid_k2(
            n,
            None if t1w is None else now - t1w,
            None if t2w is None else now - t2w,
            now - created, self.cfg["decay"])

    def _score(self, row, now):
        c = self.cfg
        b = self._activation(row, now)
        v_eff = shrink(row[4], row[5], c["shrink_k"])
        return score_p(b, v_eff, c["w_a"], c["w_v"], c["theta"], c["s"])

    # -- UDF bodies (names/arities match src/lib.rs) ------------------------

    def rfm_init(self):
        # DDL only, deliberately: a DML write here would leave the
        # connection's implicit transaction open underneath the SELECT that
        # invoked this UDF, and the host's next statement — the MCP server's
        # is PRAGMA journal_mode=WAL — fails with "cannot change into wal
        # mode from within a transaction". The lambda stamp is therefore
        # written lazily by rfm_record_outcome at the ledger's first outcome,
        # which is also when the ledger's lambda-dependence actually begins.
        cur = self.conn.cursor()
        for stmt in SCHEMA_STATEMENTS:
            cur.execute(stmt)
        return "ok"

    def rfm_record_access(self, mid):
        if not isinstance(mid, int):
            raise ValueError("rfm: id must be an INTEGER")
        now = self.now()
        cur = self.conn.cursor()
        # Log first, summary last; INSERT..SELECT doubles as existence check.
        cur.execute(
            "INSERT INTO rfm_accesses(memory_id, accessed_at) "
            "SELECT id, ? FROM rfm_memories WHERE id = ?", (now, mid))
        row = cur.execute(
            "UPDATE rfm_memories SET access_count = access_count + 1, "
            "bla_cache = last_access, last_access = ? WHERE id = ? "
            "RETURNING access_count, created_at, last_access, bla_cache, "
            "value_score, outcome_count", (now, mid)).fetchone()
        if row is None:
            raise ValueError(f"rfm: no such memory id {mid}")
        return self._activation(_normalize_row(*row), now)

    def rfm_record_outcome(self, mid, outcome):
        if outcome is None or not _m.isfinite(float(outcome)):
            raise ValueError("rfm: outcome must be finite and not NULL")
        outcome = float(outcome)
        if not -1.0 <= outcome <= 1.0:
            raise ValueError("rfm: outcome must be in [-1, 1]")
        row = self._load(mid)
        if row[0] == 0:
            raise ValueError(
                f"rfm: memory {mid} has no recorded access; "
                "call rfm_record_access first")
        lam = self.cfg["lambda"]
        # Path-dependence guard: refuse to extend a ledger under a different
        # lambda than it was built with. A DB predating rfm_meta (or one
        # whose host manages schema itself) gets stamped on first use with
        # the active lambda — the best available truth for a legacy ledger.
        try:
            stamped = self.conn.execute(
                "SELECT value FROM rfm_meta WHERE key = 'lambda'").fetchone()
        except Exception:
            stamped = False    # no rfm_meta table at all: legacy, no guard
        if stamped is None:
            self.conn.execute("INSERT OR IGNORE INTO rfm_meta(key, value) "
                              "VALUES ('lambda', ?)", (lam,))
        elif stamped and abs(stamped[0] - lam) > 1e-12:
            raise ValueError(
                f"rfm: this ledger was built under lambda={stamped[0]:g} and "
                f"the active lambda is {lam:g} — value_score is an EWMA, "
                "path-dependent on lambda, so extending it would silently "
                f"blend two regimes. Restore rfm_config('lambda', "
                f"{stamped[0]:g}), or re-stamp deliberately: UPDATE rfm_meta "
                f"SET value = {lam:g} WHERE key = 'lambda'")
        new_value = ewma_update(row[4], row[5], outcome, lam)
        cur = self.conn.cursor()
        got = cur.execute(
            "UPDATE rfm_accesses SET outcome = ? WHERE rowid = "
            "(SELECT rowid FROM rfm_accesses WHERE memory_id = ? "
            " ORDER BY accessed_at DESC, rowid DESC LIMIT 1) "
            "AND outcome IS NULL RETURNING rowid", (outcome, mid)).fetchone()
        if got is None:
            raise ValueError(
                f"rfm: latest access of memory {mid} already has an outcome; "
                "call rfm_record_access before recording another")
        cur.execute(
            "UPDATE rfm_memories SET value_score = ?, "
            "outcome_count = outcome_count + 1 WHERE id = ?", (new_value, mid))
        return new_value

    def rfm_recency(self, mid):
        row = self._load(mid)
        anchor = row[2] if row[2] is not None else row[1]
        return _m.exp(-max(self.now() - anchor, 0.0) / self.cfg["tau"])

    def rfm_frequency(self, mid):
        return _m.log(1.0 + max(self._load(mid)[0], 0))

    def rfm_activation(self, mid):
        return self._activation(self._load(mid), self.now())

    def rfm_value(self, mid):
        return self._load(mid)[4]

    def rfm_score(self, mid):
        return self._score(self._load(mid), self.now())

    def rfm_prior(self, mid):
        beta = self.cfg["beta"]
        return (1.0 - beta) + beta * self._score(self._load(mid), self.now())

    def rfm_score_w(self, mid, w_a, w_v, *decay):
        # *decay so the 3-arg registration means "omitted" while an explicit
        # SQL NULL in the 4-arg form stays distinguishable and is refused,
        # exactly as the extension's require_f64 did.
        row = self._load(mid)
        for name, w in (("w_a", w_a), ("w_v", w_v)):
            if w is None or not _m.isfinite(float(w)) or float(w) < 0.0:
                raise ValueError("rfm: weights must be finite and >= 0")
        if not decay:
            d = self.cfg["decay"]
        else:
            if decay[0] is None:
                raise ValueError("rfm: decay must not be NULL")
            d = float(decay[0])
            if not 0.0 < d < 1.0:
                raise ValueError("rfm: decay must be in (0, 1)")
        now = self.now()
        n, created, t1w, t2w, value, n_out = row
        b = bla_hybrid_k2(n, None if t1w is None else now - t1w,
                          None if t2w is None else now - t2w,
                          now - created, d)
        v_eff = shrink(value, n_out, self.cfg["shrink_k"])
        # Tuning form keeps the frozen default squash (theta=0, s=1).
        return float(w_a) * logistic_p(b, 0.0, 1.0) + float(w_v) * value01(v_eff)

    def rfm_prunable(self, mid, max_days):
        row = self._load(mid)
        if max_days is None:
            raise ValueError("rfm: max_unused_days must not be NULL")
        m = float(max_days)
        if not _m.isfinite(m):
            # inf would silently mean "never prunable"; fail like the
            # extension's require_f64 did instead of masking a caller bug.
            raise ValueError("rfm: max_unused_days must be finite")
        if m < 0.0:
            raise ValueError("rfm: max_unused_days must be >= 0")
        anchor = row[2] if row[2] is not None else row[1]
        idle_days = max(self.now() - anchor, 0.0) / 86_400.0
        proved_useful = row[5] > 0 and row[4] > 0.0
        return int(idle_days > m and not proved_useful)

    def rfm_compact(self, before_ts):
        """Drop resolved access-log rows older than before_ts. Each memory's
        LATEST row always survives — the one-outcome-per-access slot lives
        there — as does every unresolved row. Scoring reads the summary row
        only, so compaction never changes a score; what it spends is the
        ability to replay the pruned span from the log."""
        if before_ts is None:
            raise ValueError("rfm: before_ts must not be NULL")
        t = float(before_ts)
        if not _m.isfinite(t):
            raise ValueError("rfm: before_ts must be finite")
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM rfm_accesses WHERE accessed_at < ? "
            "AND outcome IS NOT NULL AND rowid NOT IN "
            "(SELECT rowid FROM "
            " (SELECT rowid, ROW_NUMBER() OVER "
            "   (PARTITION BY memory_id "
            "    ORDER BY accessed_at DESC, rowid DESC) AS rn "
            "  FROM rfm_accesses) WHERE rn = 1)", (t,))
        return cur.rowcount

    def rfm_prior_of(self, n, created, t1w, t2w, value, n_out):
        row = _normalize_row(n, created, t1w, t2w, value, n_out)
        beta = self.cfg["beta"]
        return (1.0 - beta) + beta * self._score(row, self.now())

    def rfm_version(self):
        return VERSION

    def rfm_config(self, key, *value):
        if key not in _CHECKS:
            raise ValueError(f"rfm: unknown config key '{key}'")
        if not value:  # getter
            return self.cfg[key]
        v = value[0]
        if v is None:
            if key != "now":
                raise ValueError(f"rfm: config '{key}' cannot be NULL")
            self.cfg["now"] = None
            return None
        v = float(v)
        if not _m.isfinite(v):
            raise ValueError(f"rfm: config '{key}' must be finite")
        ok = _CHECKS[key](v)
        if ok is not True:
            raise ValueError(ok)
        self.cfg[key] = v
        return v


def register(conn):
    """Register all rfm_* functions on `conn`. Returns the state object
    (exposed for tests; hosts normally ignore it)."""
    r = _Rfm(conn)

    def wrap(fn):
        # stdlib sqlite3 replaces a raising UDF's message with a generic one;
        # keep the specific rfm: message visible on stderr for diagnosis and
        # on r.last_error for hosts that relay errors to a caller.
        def call(*args):
            try:
                return fn(*args)
            except Exception as e:
                r.last_error = f"{e}"
                print(f"{e}", file=sys.stderr)
                raise
        return call

    fns = [
        ("rfm_init", 0, r.rfm_init),
        ("rfm_record_access", 1, r.rfm_record_access),
        ("rfm_record_outcome", 2, r.rfm_record_outcome),
        ("rfm_recency", 1, r.rfm_recency),
        ("rfm_frequency", 1, r.rfm_frequency),
        ("rfm_activation", 1, r.rfm_activation),
        ("rfm_value", 1, r.rfm_value),
        ("rfm_score", 1, r.rfm_score),
        ("rfm_prior", 1, r.rfm_prior),
        ("rfm_score_w", 3, r.rfm_score_w),
        ("rfm_score_w", 4, r.rfm_score_w),
        ("rfm_prunable", 2, r.rfm_prunable),
        ("rfm_compact", 1, r.rfm_compact),
        ("rfm_prior_of", 6, r.rfm_prior_of),
        ("rfm_version", 0, r.rfm_version),
        ("rfm_config", 1, r.rfm_config),
        ("rfm_config", 2, r.rfm_config),
    ]
    for name, narg, fn in fns:
        conn.create_function(name, narg, wrap(fn), deterministic=False)
    return r
