#!/usr/bin/env python3
"""mem_rfm_cli.py setup/doctor against a throwaway HOME. Stdlib only.

Never touches the real home directory: every run gets HOME=<tmpdir>, a PATH
holding only a stub `claude` (which records its argv and edits
$HOME/.claude.json the way `claude mcp add/remove -s user` does) plus
/usr/bin:/bin, and a stub venv interpreter that passes the dependency probe.
The preflight (smoke_test.py, which needs the real venv) is skipped here
except in the last section, which runs only when the real venv exists.

Usage: python3 test_setup.py
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "mem_rfm_cli.py")
REAL_HOME = os.path.realpath(os.path.expanduser("~"))
failures = []


def check(name, ok, detail=""):
    print(f"  {'ok' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


STUB_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
home = os.environ["HOME"]
with open(os.path.join(home, "claude-calls.log"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
if os.environ.get("STUB_CLAUDE_FAIL"):
    print("boom", file=sys.stderr); sys.exit(3)
a = sys.argv[1:]
path = os.path.join(home, ".claude.json")
try:
    cfg = json.load(open(path))
except FileNotFoundError:
    cfg = {}
servers = cfg.setdefault("mcpServers", {})
if a[:2] == ["mcp", "add"]:
    name = a[4]; rest = a[a.index("--") + 1:]
    if name in servers:
        print(f"MCP server {name} already exists", file=sys.stderr); sys.exit(1)
    servers[name] = {"type": "stdio", "command": rest[0], "args": rest[1:], "env": {}}
elif a[:2] == ["mcp", "remove"]:
    servers.pop(a[4], None)
else:
    sys.exit(0)
json.dump(cfg, open(path, "w"), indent=2)
'''


def make_env(root, with_claude=True):
    home = os.path.join(root, "home")
    bin_ = os.path.join(root, "bin")
    os.makedirs(home, exist_ok=True)
    os.makedirs(bin_, exist_ok=True)
    assert os.path.realpath(home) != REAL_HOME
    if with_claude:
        p = os.path.join(bin_, "claude")
        with open(p, "w") as f:
            f.write(STUB_CLAUDE.replace("/usr/bin/env python3", sys.executable, 1))
        os.chmod(p, 0o755)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("RFM_", "CLAUDE"))}
    env.update(HOME=home, PATH=f"{bin_}:/usr/bin:/bin")
    return env, home


def stub_python(root, name="venv"):
    p = os.path.join(root, name, "bin", "python")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write("#!/bin/sh\nexit 0\n")
    os.chmod(p, 0o755)
    return p


def cli(env, *args):
    r = subprocess.run([sys.executable, CLI, *args], env=env,
                       capture_output=True, text=True, timeout=600)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode, last, r.stdout + r.stderr


def tree(home):
    out = {}
    for d, _, files in os.walk(home):
        for n in files:
            p = os.path.join(d, n)
            out[os.path.relpath(p, home)] = os.stat(p).st_mtime_ns
    return out


def calls(home):
    p = os.path.join(home, "claude-calls.log")
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def main():
    root = tempfile.mkdtemp(prefix="rfm-setup-test-")
    try:
        run(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n{len(failures)} failure(s)" if failures else "\nall passed")
    return 1 if failures else 0


def run(root):
    print("host probe")
    env, home = make_env(os.path.join(root, "a"), with_claude=False)
    py = stub_python(root)
    rc, last, _ = cli(env, "doctor", "--python", py, "--no-preflight")
    check("doctor without claude on PATH: FAILED HOST_BINARY_MISSING",
          rc == 1 and last.startswith("FAILED HOST_BINARY_MISSING"), last)
    rc, last, _ = cli(env, "setup", "--python", py, "--no-preflight")
    check("setup without claude stops before writing",
          rc == 1 and "HOST_BINARY_MISSING" in last and tree(home) == {}, str(tree(home)))

    print("fresh home")
    env, home = make_env(os.path.join(root, "b"))
    rc, last, out = cli(env, "doctor", "--python", py, "--no-preflight")
    check("doctor on a fresh home fails (wiring/mcp missing)", rc == 1, last)
    rc, last, out = cli(env, "setup", "--dry-run", "--python", py, "--no-preflight")
    check("setup --dry-run succeeds", rc == 0 and last.startswith("READY"), out)
    check("--dry-run writes nothing to HOME", tree(home) == {}, str(tree(home)))
    check("--dry-run lists the MCP registration it would make",
          "would register rfm-memory" in out, out)

    # Fresh checkout: setup --dry-run plans the venv it would create, so
    # the wiring step must plan against that python rather than fail.
    probe = ("import install_hooks as ih\n"
             "ih.PYTHON = '/nonexistent/.venv/bin/python'\n"
             "try:\n    ih.apply(dry=True)\nexcept ih.InstallError as e:\n"
             "    print('refused', e.code)\n"
             "print('planned', len(ih.apply(dry=True, python_planned=True)))\n")
    r = subprocess.run([sys.executable, "-c", probe], env=env, cwd=HERE,
                       capture_output=True, text=True, timeout=60)
    check("wiring dry run without a venv: refused unless planned",
          "refused VENV_MISSING" in r.stdout, r.stdout + r.stderr)
    check("wiring dry run with a planned venv lists changes, writes nothing",
          "planned 0" not in r.stdout and "planned" in r.stdout
          and tree(home) == {}, r.stdout + r.stderr + str(tree(home)))

    # pre-existing user config that must survive untouched
    os.makedirs(os.path.join(home, ".claude"))
    user_settings = {"permissions": {"allow": ["Bash(ls:*)"]},
                     "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
    with open(os.path.join(home, ".claude", "settings.json"), "w") as f:
        json.dump(user_settings, f)
    with open(os.path.join(home, ".claude", "CLAUDE.md"), "w") as f:
        f.write("# my rules\nbe terse\n")
    with open(os.path.join(home, ".claude.json"), "w") as f:
        json.dump({"numStartups": 7, "mcpServers": {"other": {"command": "x"}}}, f)

    rc, last, out = cli(env, "setup", "--python", py, "--no-preflight")
    check("setup succeeds: READY", rc == 0 and last == "READY", out)
    s = json.load(open(os.path.join(home, ".claude", "settings.json")))
    check("user settings preserved", s["permissions"] == user_settings["permissions"]
          and s["hooks"]["Stop"] == user_settings["hooks"]["Stop"])
    check("all five hook events registered",
          {"SessionStart", "SessionEnd", "PostToolUse", "UserPromptSubmit",
           "PreToolUse"} <= set(s["hooks"]), str(sorted(s["hooks"])))
    pre = s["hooks"].get("PreToolUse", [{}])[0]
    check("PreToolUse guard matches only rfm-memory tools",
          pre.get("matcher") == "mcp__rfm-memory__.*", str(pre))
    check("hooks run with the chosen interpreter",
          all(py in h["command"] for g in s["hooks"]["SessionEnd"] for h in g["hooks"]))
    check("settings backed up verbatim",
          json.load(open(os.path.join(home, ".claude", "settings.json.bak-rfm"))) == user_settings)
    md = open(os.path.join(home, ".claude", "CLAUDE.md")).read()
    check("CLAUDE.md keeps user text and gains the fence",
          md.startswith("# my rules\nbe terse\n") and "rfm-memory:begin" in md)
    check("skill installed", os.path.exists(
        os.path.join(home, ".claude", "skills", "memory-review", "SKILL.md")))
    cj = json.load(open(os.path.join(home, ".claude.json")))
    check("MCP registered via the CLI with venv + server.py",
          cj["mcpServers"].get("rfm-memory", {}).get("command") == py
          and cj["mcpServers"]["rfm-memory"]["args"] == [os.path.join(HERE, "server.py")], str(cj))
    check("other ~/.claude.json content preserved",
          cj["numStartups"] == 7 and "other" in cj["mcpServers"])
    check("~/.claude.json backed up before registration",
          json.load(open(os.path.join(home, ".claude.json.bak-rfm")))["numStartups"] == 7)
    check("store initialised", os.path.exists(os.path.join(home, ".sqlite-rfm", "claude-code.db")))

    print("idempotence")
    before, n_calls = tree(home), len(calls(home))
    rc, last, out = cli(env, "setup", "--python", py, "--no-preflight")
    after = tree(home)
    changed = sorted(k for k in after if after[k] != before.get(k)
                     and not k.startswith(".sqlite-rfm") and k != "claude-calls.log")
    check("second setup: READY, nothing rewritten", rc == 0 and last == "READY"
          and not changed, f"{changed}\n{out}")
    check("second setup: no claude CLI writes", not any(
        c[:2] in (["mcp", "add"], ["mcp", "remove"]) for c in calls(home)[n_calls:]))
    check("second setup reports 'already up to date'", "already up to date" in out, out)
    rc, last, out = cli(env, "doctor", "--python", py, "--no-preflight")
    check("doctor after setup: READY", rc == 0 and last == "READY", out)

    print("moved venv")
    py2 = stub_python(root, "venv2")
    rc, last, out = cli(env, "doctor", "--python", py2, "--no-preflight")
    check("doctor flags the stale registration",
          rc == 1 and ("MCP_INVALID" in out and "HOOKS_STALE" in out), out)
    rc, last, out = cli(env, "setup", "--python", py2, "--no-preflight")
    cj = json.load(open(os.path.join(home, ".claude.json")))
    check("setup re-registers (remove + add) onto the new venv",
          rc == 0 and cj["mcpServers"]["rfm-memory"]["command"] == py2
          and ["mcp", "remove", "-s", "user", "rfm-memory"] in calls(home), out)
    s = json.load(open(os.path.join(home, ".claude", "settings.json")))
    hooks = [h for ev in s["hooks"].values() for g in ev for h in g["hooks"]]
    check("hooks repointed in place, no duplicates",
          sum("session_end.py" in h["command"] for h in hooks) == 1
          and all(py not in h["command"] for h in hooks if "rfm-memory-hook" in h["command"]))

    print("failure codes")
    env3, home3 = make_env(os.path.join(root, "c"))
    os.makedirs(os.path.join(home3, ".claude"))
    bad = '{"hooks": '
    with open(os.path.join(home3, ".claude", "settings.json"), "w") as f:
        f.write(bad)
    rc, last, out = cli(env3, "setup", "--python", py, "--no-preflight")
    check("malformed settings.json: FAILED SETTINGS_INVALID, file untouched",
          rc == 1 and last.startswith("FAILED SETTINGS_INVALID")
          and open(os.path.join(home3, ".claude", "settings.json")).read() == bad, out)

    env4, home4 = make_env(os.path.join(root, "d"))
    ro = os.path.join(root, "d", "ro")
    os.makedirs(ro)
    os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)
    env4["RFM_MEMORY_DB"] = os.path.join(ro, "sub", "m.db")
    rc, last, out = cli(env4, "setup", "--python", py, "--no-preflight")
    check("unwritable store: FAILED STORE_NOT_WRITABLE",
          rc == 1 and last.startswith("FAILED STORE_NOT_WRITABLE"), out)
    rc, last, out = cli(env4, "doctor", "--python", py, "--no-preflight")
    check("doctor reports STORE_NOT_WRITABLE too", "STORE_NOT_WRITABLE" in out, out)
    os.chmod(ro, stat.S_IRWXU)

    env5, home5 = make_env(os.path.join(root, "e"))
    env5["STUB_CLAUDE_FAIL"] = "1"
    rc, last, out = cli(env5, "setup", "--python", py, "--no-preflight")
    check("claude mcp add failing: FAILED MCP_REGISTER_FAILED",
          rc == 1 and last.startswith("FAILED MCP_REGISTER_FAILED"), out)

    env6, home6 = make_env(os.path.join(root, "f"))
    nodeps = os.path.join(root, "nodeps", "bin", "python")
    os.makedirs(os.path.dirname(nodeps))
    with open(nodeps, "w") as f:
        f.write("#!/bin/sh\necho 'ModuleNotFoundError: No module named mcp' >&2\nexit 1\n")
    os.chmod(nodeps, 0o755)
    rc, last, out = cli(env6, "doctor", "--python", nodeps, "--no-preflight")
    check("venv without deps: doctor says DEPS_MISSING", "DEPS_MISSING" in out, out)
    rc, last, out = cli(env6, "setup", "--python", nodeps, "--no-preflight")
    check("...and setup without uv says UV_MISSING, writes nothing",
          rc == 1 and "UV_MISSING" in last and tree(home6) == {}, out)
    rc, last, out = cli(env6, "doctor", "--python", os.path.join(root, "none", "python"),
                        "--no-preflight")
    check("missing interpreter: VENV_MISSING", "VENV_MISSING" in out, out)

    # The real integration venv: this checkout's, or RFM_TEST_VENV_PYTHON
    # (a worktree has no .venv of its own). RFM_TEST_PREFLIGHT=0 skips.
    real = os.environ.get("RFM_TEST_VENV_PYTHON") or os.path.join(HERE, ".venv", "bin", "python")
    if os.path.exists(real) and os.environ.get("RFM_TEST_PREFLIGHT", "1") == "1":
        print("live preflight (real venv)")
        rc, last, out = cli(env, "setup", "--python", real)
        check("setup with the real venv passes the live preflight",
              rc == 0 and last == "READY", out)
    else:
        print("live preflight skipped (no integration venv)")


if __name__ == "__main__":
    sys.exit(main())
