#!/usr/bin/env python3
"""`setup` and `doctor` for the Claude Code integration: one command from a
checkout to a working install, and one that says exactly what is broken.

    python3 mem_rfm_cli.py setup  [--dry-run] [--python PY] [--no-preflight]
    python3 mem_rfm_cli.py doctor [--no-preflight]
    python3 mem_rfm_cli.py export FILE    every row, ledger included (JSONL)
    python3 mem_rfm_cli.py import FILE    restore into an empty store
    python3 mem_rfm_cli.py reembed        re-embed under $RFM_EMBEDDER

setup runs six steps, each idempotent, each skipped when already done:

  1. probe      `claude` on PATH, and `uv` if the venv must be built
  2. venv       .venv with mcp sqlite-vec fastembed numpy (uv)
  3. store      create/open $RFM_MEMORY_DB and initialise the schema
  4. wiring     install_hooks.apply(): settings.json hooks (merge, never
                replace), CLAUDE.md fence, /memory-review skill
  5. mcp        `claude mcp add -s user rfm-memory` — via the CLI, never by
                editing ~/.claude.json directly; ~/.claude.json is backed
                up to .bak-rfm first. A stale registration (moved checkout
                or venv) is removed and re-added.
  6. preflight  smoke_test.py: the server launched over stdio, every tool
                exercised against a temporary DB

doctor runs the same checks without writing anything. Both end with one
line, READY or FAILED <CODE>, and exit 0 / 1. Codes:

  HOST_BINARY_MISSING  `claude` not on PATH
  UV_MISSING           venv missing and `uv` not on PATH
  VENV_MISSING         venv python not found
  DEPS_MISSING         venv lacks mcp / sqlite_vec / fastembed / numpy
  STORE_NOT_WRITABLE   the DB cannot be created, opened or initialised
  SETTINGS_INVALID     ~/.claude/settings.json is not valid JSON
  HOOKS_STALE          hooks, CLAUDE.md block or skill missing / outdated
  MCP_MISSING          rfm-memory not registered at user scope
  MCP_INVALID          registered, but not with this venv + server.py
  MCP_REGISTER_FAILED  `claude mcp add` failed
  PREFLIGHT_FAILED     smoke_test.py failed

Writes are confined to: this directory's .venv, the store directory,
~/.claude/{settings.json,CLAUDE.md,skills/memory-review} (install_hooks),
and ~/.claude.json (through the claude CLI). Every pre-existing file is
backed up to <file>.bak-rfm before its first change. Everything is resolved
from $HOME at startup, so tests run it against a temporary HOME with a stub
`claude` on PATH (test_setup.py).
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

SERVER_NAME = "rfm-memory"
SERVER = os.path.join(HERE, "server.py")
DEPS = ("mcp", "sqlite-vec", "fastembed", "numpy")
IMPORTS = ("mcp", "sqlite_vec", "fastembed", "numpy")


class Failed(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class Run:
    """Collects step results; prints as it goes."""
    def __init__(self, dry):
        self.dry = dry

    def step(self, name, msg):
        print(f"  {name:<10} {msg}")

    def change(self, name, msg):
        self.step(name, ("would " if self.dry else "") + msg)


def default_python():
    return os.path.join(HERE, ".venv", "bin", "python")


def claude_json():
    return os.path.expanduser("~/.claude.json")


def db_path():
    return os.path.expanduser(os.environ.get("RFM_MEMORY_DB",
                                             "~/.sqlite-rfm/claude-code.db"))


def backup(path):
    """<path>.bak-rfm, once per run that changes the file."""
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak-rfm")


# ------------------------------------------------------------------ checks
# Each check returns a message on success and raises Failed otherwise, so
# setup and doctor share one definition of "ok".

def check_host():
    path = shutil.which("claude")
    if not path:
        raise Failed("HOST_BINARY_MISSING", "`claude` not found on PATH — "
                     "install Claude Code first")
    return path


def check_venv(python):
    if not os.path.exists(python):
        raise Failed("VENV_MISSING", f"no venv python at {python}")
    probe = "import " + ", ".join(IMPORTS)
    r = subprocess.run([python, "-c", probe], capture_output=True, text=True)
    if r.returncode != 0:
        last = (r.stderr.strip().splitlines() or ["?"])[-1]
        raise Failed("DEPS_MISSING", f"{python} cannot import deps: {last}")
    return python


def check_store(create):
    """Open (and with create=True, initialise) the store. Uses the pure-Python
    engine directly: no embedder, no sqlite-vec, so it isolates 'the path is
    unusable' from 'the server's dependencies are broken'."""
    path = db_path()
    d = os.path.dirname(path) or "."
    exists = os.path.exists(path)
    if not exists and not create:
        if os.path.isdir(d) and not os.access(d, os.W_OK):
            raise Failed("STORE_NOT_WRITABLE", f"{d} is not writable")
        # Doctor before setup: the server creates the file lazily, which is
        # fine as long as the directory can be made.
        parent = d
        while not os.path.exists(parent):
            parent = os.path.dirname(parent)
        if not os.access(parent, os.W_OK):
            raise Failed("STORE_NOT_WRITABLE", f"cannot create {d}")
        return f"{path} (not created yet; the server creates it on first use)"
    try:
        if create:
            os.makedirs(d, exist_ok=True)
        import rfm
        conn = sqlite3.connect(path if create else f"file:{path}?mode=rw",
                               uri=not create, timeout=10.0)
        try:
            rfm.register(conn)
            if create:
                conn.execute("SELECT rfm_init()")
                conn.commit()
            n = conn.execute("SELECT count(*) FROM rfm_memories").fetchone()[0]
        finally:
            conn.close()
    except (OSError, sqlite3.Error) as e:
        raise Failed("STORE_NOT_WRITABLE", f"{path}: {e}")
    if not os.access(path, os.W_OK):
        raise Failed("STORE_NOT_WRITABLE", f"{path} is read-only")
    return f"{path} ({n} memories)"


def registered_server():
    """The user-scope rfm-memory entry from ~/.claude.json, or None. Read
    directly (cheap, no server spawn); written only through the CLI."""
    try:
        with open(claude_json()) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        raise Failed("MCP_INVALID", f"{claude_json()} is not valid JSON ({e})")
    return (cfg.get("mcpServers") or {}).get(SERVER_NAME)


def check_mcp(python):
    entry = registered_server()
    if entry is None:
        raise Failed("MCP_MISSING", f"{SERVER_NAME} not registered at user scope")
    want = (python, [SERVER])
    got = (entry.get("command"), list(entry.get("args") or []))
    if got != want:
        raise Failed("MCP_INVALID", f"{SERVER_NAME} runs {got[0]} {' '.join(got[1])}"
                     f", expected {want[0]} {SERVER}")
    if not os.path.exists(got[0]):
        raise Failed("MCP_INVALID", f"{SERVER_NAME} command missing: {got[0]}")
    return f"{SERVER_NAME} -> {python} {SERVER}"


def check_wiring():
    import install_hooks as ih
    try:
        pending = ih.install(ih.load_settings())
        pending += ih.sync_claude_md(dry=True)
        pending += ih.sync_skill(dry=True)
    except ih.InstallError as e:
        raise Failed(e.code, str(e))
    if pending:
        raise Failed("HOOKS_STALE", "; ".join(pending))
    return "hooks, CLAUDE.md block and /memory-review skill current"


def preflight(python):
    r = subprocess.run([python, os.path.join(HERE, "smoke_test.py")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        tail = " | ".join((r.stdout + r.stderr).strip().splitlines()[-3:])
        raise Failed("PREFLIGHT_FAILED", tail or f"exit {r.returncode}")
    return (r.stdout.strip().splitlines() or ["ok"])[-1]


# ------------------------------------------------------------------ setup

def setup(args):
    run = Run(args.dry_run)
    python = args.python
    run.step("probe", f"claude: {check_host()}")

    # venv
    if not os.path.exists(python):
        if python != default_python():
            raise Failed("VENV_MISSING", f"--python {python} does not exist")
        uv = shutil.which("uv")
        if not uv:
            raise Failed("UV_MISSING", "venv missing and `uv` not on PATH")
        run.change("venv", f"create {os.path.dirname(os.path.dirname(python))}")
        if not args.dry_run:
            subprocess.run([uv, "venv", "--python", "3.12",
                            os.path.join(HERE, ".venv")], check=True)
    try:
        if os.path.exists(python):
            run.step("venv", check_venv(python))
        else:
            raise Failed("DEPS_MISSING", "venv not built yet (dry run)")
    except Failed as e:
        if e.code != "DEPS_MISSING":
            raise
        uv = shutil.which("uv")
        if not uv:
            raise Failed("UV_MISSING", f"{e}; `uv` not on PATH to install them")
        run.change("venv", f"install {' '.join(DEPS)}")
        if not args.dry_run:
            subprocess.run([uv, "pip", "install", "--python", python, *DEPS],
                           check=True)
            run.step("venv", check_venv(python))

    # store
    run.step("store", check_store(create=not args.dry_run))

    # wiring: install_hooks reads PYTHON at call time
    import install_hooks as ih
    ih.PYTHON = python
    try:
        changes = ih.apply(dry=args.dry_run, python_planned=True)
    except ih.InstallError as e:
        raise Failed(e.code, str(e))
    for c in changes:
        run.change("wiring", c)
    if not changes:
        run.step("wiring", "already up to date")

    # mcp
    try:
        run.step("mcp", check_mcp(python))
    except Failed as e:
        if e.code not in ("MCP_MISSING", "MCP_INVALID"):
            raise
        claude = check_host()
        stale = e.code == "MCP_INVALID" and registered_server() is not None
        run.change("mcp", ("re-register" if stale else "register")
                   + f" {SERVER_NAME} -> {python} {SERVER}"
                   + f" (backup: {claude_json()}.bak-rfm)")
        if not args.dry_run:
            backup(claude_json())
            if stale:
                subprocess.run([claude, "mcp", "remove", "-s", "user", SERVER_NAME],
                               capture_output=True, text=True)
            r = subprocess.run([claude, "mcp", "add", "-s", "user", SERVER_NAME,
                                "--", python, SERVER],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise Failed("MCP_REGISTER_FAILED",
                             (r.stderr or r.stdout).strip() or f"exit {r.returncode}")
            run.step("mcp", check_mcp(python))

    if args.no_preflight or args.dry_run:
        run.step("preflight", "skipped")
    else:
        run.step("preflight", preflight(python))
    if changes and not args.dry_run:
        print("note: a running Claude Code session needs a restart (or /hooks "
              "opened once) to pick up the changes")


def doctor(args):
    run = Run(False)
    failures = []

    def do(name, fn, *a):
        try:
            run.step(name, fn(*a))
            return True
        except Failed as e:
            run.step(name, f"FAIL {e.code}: {e}")
            failures.append(e)
            return False

    do("probe", check_host)
    venv_ok = do("venv", check_venv, args.python)
    do("store", check_store, False)
    import install_hooks as ih
    ih.PYTHON = args.python
    do("wiring", check_wiring)
    do("mcp", check_mcp, args.python)
    if args.no_preflight or not venv_ok:
        run.step("preflight", "skipped")
    else:
        do("preflight", preflight, args.python)
    if failures:
        raise failures[0]


def portable(command, path):
    """export / import: stdlib only, so a backup needs no venv."""
    import rfm
    import store
    target = db_path()
    if command == "export" and not os.path.exists(target):
        print(f"FAILED: no store at {target}")
        return 1
    os.makedirs(os.path.dirname(target), exist_ok=True)
    conn = sqlite3.connect(target, timeout=10.0)
    try:
        rfm.register(conn)
        store.ensure(conn)
        if command == "export":
            # 'x': a backup never replaces an earlier one. 0600: memories
            # are redacted at write, but they are still private.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                n = store.export_store(conn, fh)
        else:
            with open(path) as fh:
                n = store.import_store(conn, fh)
    except (OSError, ValueError, sqlite3.Error) as e:
        print(f"FAILED: {e}")
        return 1
    finally:
        conn.close()
    print(f"{command}: {n} rows, {target} {'->' if command == 'export' else '<-'} {path}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command",
                    choices=("setup", "doctor", "export", "import", "reembed",
                             "decide"))
    ap.add_argument("file", nargs="?",
                    help="export/import: the JSONL file; decide: a transcript")
    ap.add_argument("--dry-run", action="store_true",
                    help="setup: print every change, write nothing")
    ap.add_argument("--python", default=os.environ.get("RFM_PYTHON") or default_python(),
                    help="interpreter for the server and hooks "
                         "(default: this checkout's .venv)")
    ap.add_argument("--no-preflight", action="store_true",
                    help="skip the smoke test (it loads the embedder)")
    args = ap.parse_args(argv)
    args.python = os.path.abspath(args.python)
    if args.command in ("export", "import"):
        if not args.file:
            ap.error(f"{args.command} needs a FILE")
        return portable(args.command, args.file)
    if args.command == "decide":
        if not args.file:
            ap.error("decide needs a transcript FILE")
        return subprocess.call([args.python,
                                os.path.join(HERE, "decisions.py"), args.file])
    if args.command == "reembed":
        # In the venv: the embedder is not stdlib, and server.py owns it.
        return subprocess.call([args.python, SERVER, "--reembed"])
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        print("  warning: CLAUDE_CONFIG_DIR is set; this tool only manages "
              "~/.claude and ~/.claude.json", file=sys.stderr)
    print(f"mem-rfm {args.command}" + (" (dry run)" if args.dry_run else ""))
    try:
        (setup if args.command == "setup" else doctor)(args)
    except Failed as e:
        print(f"FAILED {e.code}: {e}")
        return 1
    except subprocess.CalledProcessError as e:
        print(f"FAILED VENV_MISSING: {' '.join(map(str, e.cmd))} exited {e.returncode}")
        return 1
    print("READY" + (" (dry run: nothing written)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
