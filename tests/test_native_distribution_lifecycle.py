"""Native install/refresh/uninstall lifecycle, never a model prompt.

Three layers:

* Checker, hermetic layer (scripts/check_native_lifecycle.py; every OS for the pure helpers, POSIX
  for the fake-CLI runs). The checker runs against FAKE claude/codex/grok/kimi programs placed on a
  PATH that holds only the fake folder. Every fake fails closed: an argv outside its allowlist exits
  97 and appends to violations.log, and it refuses to run without its isolated home variable. The
  fixture package has 3 skills and 1 command, so the discovery counts the checker expects are
  derived from the package, not the repository's 16 + 1. Fake runs need a POSIX exec bit and
  shebang; Windows executable resolution (including the .cmd/.bat refusal) is covered by the
  simulated-resolution tests.
* Checker, REAL CLI layer (RealCliLifecycleTests). Runs only when the real vendor CLI resolves on
  this machine's PATH; it asserts native_<platform>=passed for this checkout and that the real
  profile's plugin files keep their size and mtime. A missing, script-shim or too-old CLI is a skip.
* Direct native layer (NativeLoopbackBoundaryTests, NativeCodexLifecycleTests,
  OptionalNativeLifecycleTests): disposable homes and relocated sources driven without the checker.
  Missing CLI support is a skip. These checks prove local copying and configuration preservation,
  not trusted hook execution, skill triggering or remote publication. Kimi/Grok checks require
  AGENTIC_NATIVE_TRUST_SMOKE=1: installing in disposable profiles accepts plugin code. Ordinary
  gates never silently grant that consent.
"""
import contextlib
import getpass
import importlib.util
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from scripts.check_plugin_portability import runtime_members
from scripts.sensitive_redaction import redact_text


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_native_lifecycle.py"
PLATFORMS = ("claude", "codex", "grok", "kimi", "zcode")
LINE_RE = re.compile(r"^native_(claude|codex|grok|kimi|zcode)=(passed|failed:[a-z0-9_:=,.-]+|not-run:[a-z0-9_:=,.-]+)$")
FORBIDDEN_PREFIXES = ("ANTHROPIC_", "OPENAI_", "XAI_", "GROK_API", "MOONSHOT_", "KIMI_API", "ZHIPU_", "ZAI_",
                      "AWS_", "AZURE_", "GOOGLE_", "CLAUDE_CODE_USE_", "GITHUB_TOKEN", "GH_TOKEN", "CI_", "NPM_TOKEN")
SECRET_NAMES = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "GROK_API_KEY", "MOONSHOT_API_KEY",
    "KIMI_API_KEY", "ZHIPU_API_KEY", "ZAI_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "AZURE_OPENAI_API_KEY", "GOOGLE_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "GITHUB_TOKEN", "GH_TOKEN",
    "CI_JOB_TOKEN", "NPM_TOKEN",
)
# Unique placeholder values (derived, so no credential-shaped literal exists), each findable in a leak.
SECRET_ENV = {name: "fixture-value-%02d" % index for index, name in enumerate(SECRET_NAMES)}
# The child environment may carry only these names (the checker's BINDING allowlist).
ALLOWED_CHILD_ENV = {
    "PATH", "SystemRoot", "ComSpec", "PATHEXT", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL",
    "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
    "XDG_CACHE_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "GROK_HOME", "KIMI_CODE_HOME",
    "DISABLE_AUTOUPDATER", "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING",
    "GROK_DISABLE_AUTOUPDATER", "GROK_TELEMETRY_ENABLED", "KIMI_DISABLE_TELEMETRY",
}
HOME_VARS = ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
             "XDG_CACHE_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "GROK_HOME", "KIMI_CODE_HOME",
             "TEMP", "TMP", "TMPDIR")


def load_checker():
    spec = importlib.util.spec_from_file_location("check_native_lifecycle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _write_json(path, value):
    _write(path, json.dumps(value, indent=2) + "\n")


def build_package(base):
    """A small package: 3 skills (plus a directory without SKILL.md), 1 command, 4 manifests."""
    pkg = base / "fixture-package"
    for name in ("alpha-skill", "beta-skill", "using-agentic-sdlc"):
        _write(pkg / "skills" / name / "SKILL.md",
               "---\nname: %s\ndescription: Use for the %s fixture.\n---\nFixture body.\n" % (name, name))
    (pkg / "skills" / "not-a-skill").mkdir(parents=True)
    _write(pkg / "commands" / "git-safety-check.md", "---\ndescription: Fixture command.\n---\nBody.\n")
    _write(pkg / ".git" / "HEAD", "ref: refs/heads/main\n")
    plugin = {"name": "fixture-plugin", "version": "1.2.3", "description": "Lifecycle fixture."}
    _write_json(pkg / ".claude-plugin" / "plugin.json", plugin)
    _write_json(pkg / ".claude-plugin" / "marketplace.json", {
        "name": "fixture-market", "owner": {"name": "Fixture"},
        "plugins": [{"name": "fixture-plugin", "version": "1.2.3", "source": "./"}]})
    _write_json(pkg / ".codex-plugin" / "plugin.json", dict(plugin, skills="./skills/"))
    _write_json(pkg / ".grok-plugin" / "plugin.json", plugin)
    _write_json(pkg / ".grok-plugin" / "marketplace.json", {
        "name": "fixture-market", "plugins": [{"name": "fixture-plugin", "version": "1.2.3", "source": "./"}]})
    _write_json(pkg / ".kimi-plugin" / "plugin.json", dict(plugin, skills="./skills/", commands="./commands/"))
    _write(pkg / "VERSION", "1.2.3\n")
    return pkg


FAKE_CLI = r'''
import json
import os
import secrets
import shutil
import sys
import time

HERE = os.path.dirname(os.path.realpath(sys.argv[0]))
NAME = os.path.basename(sys.argv[0])
ARGV = sys.argv[1:]
with open(os.path.join(HERE, "fake-config.json"), encoding="utf-8") as fh:
    CONFIG = json.load(fh)
MODE = CONFIG.get("modes", {}).get(NAME, "ok")
HOME_VAR = {"claude": "CLAUDE_CONFIG_DIR", "codex": "CODEX_HOME", "grok": "GROK_HOME", "kimi": "KIMI_CODE_HOME"}[NAME]


def record_violation(why):
    with open(os.path.join(HERE, "violations.log"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"cli": NAME, "argv": ARGV, "why": why}) + "\n")


def violation(why):
    record_violation(why)
    sys.stderr.write("fake %s refused this argv\n" % NAME)
    sys.exit(97)


with open(os.path.join(HERE, "calls.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"cli": NAME, "argv": ARGV, "cwd": os.getcwd(), "env": dict(os.environ)}) + "\n")
STATE_HOME = os.environ.get(HOME_VAR)
if not STATE_HOME or not os.path.isdir(STATE_HOME):
    violation("isolated home %s missing" % HOME_VAR)


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=2)


def check_source(src):
    if os.path.exists(os.path.join(src, ".git")):
        violation(".git was copied into the install source")
    if " " not in src or src.isascii() or any(ch in src for ch in "#&%"):
        violation("install source path is not the hostile copy")


def copy_plugin(src, dest):
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest)


def skills(root):
    base = os.path.join(root, "skills")
    return sorted(d for d in os.listdir(base) if os.path.isfile(os.path.join(base, d, "SKILL.md")))


def commands(root):
    base = os.path.join(root, "commands")
    return sorted(f[:-3] for f in os.listdir(base) if f.endswith(".md")) if os.path.isdir(base) else []


def out(value):
    print(json.dumps(value))


def help_or_violation(table, top_level_usage):
    if ARGV and ARGV[-1] == "--help":
        if tuple(ARGV[:-1]) not in table:
            violation("help for a subcommand the checker should not probe")
        print(top_level_usage if MODE == "old" else table[tuple(ARGV[:-1])])
        sys.exit(0)
    if MODE == "old":
        violation("plugin argv sent to a CLI whose help lacks the subcommand")


def claude():
    # "legacy_json" mirrors Claude Code 2.1.282: no --json on marketplace add/update.
    market_json = "" if MODE == "legacy_json" else "\nOptions:\n  --json  machine-readable result\n"
    help_or_violation({
        ("plugin", "marketplace", "add"): "Usage: claude plugin marketplace add [options] <source>\n" + market_json,
        ("plugin", "install"): "Usage: claude plugin install|i [options] <plugin>\n\nOptions:\n  --json  machine-readable result\n",
        ("plugin", "list"): "Usage: claude plugin list [options]\n\nOptions:\n  --json  Output as JSON\n",
        ("plugin", "details"): "Usage: claude plugin details [options] <name>\n",
        ("plugin", "marketplace", "update"): "Usage: claude plugin marketplace update [options] [name]\n" + market_json,
        ("plugin", "update"): "Usage: claude plugin update [options] <plugin>\n\nOptions:\n  --json  machine-readable result\n",
        ("plugin", "uninstall"): "Usage: claude plugin uninstall|remove [options] <plugin>\n\nOptions:\n  --json  machine-readable result\n",
    }, "Usage: claude [options] [command] [prompt]\n")
    state_path = os.path.join(STATE_HOME, "fake-state.json")
    state = read_json(state_path, {"marketplaces": {}, "installed": {}, "uninstalls": 0})
    a = ARGV
    if a[:3] == ["plugin", "marketplace", "add"] and len(a) == 4:
        check_source(a[3])
        name = read_json(os.path.join(a[3], ".claude-plugin", "marketplace.json"), {})["name"]
        state["marketplaces"][name] = a[3]
        write_json(state_path, state)
        return out({"outcome": "ok", "marketplace": name})
    if a[:2] == ["plugin", "install"] and len(a) == 3:
        if MODE == "install_fail":
            sys.stderr.write("fake install failure\n")
            sys.exit(1)
        if MODE == "hang":
            with open(os.path.join(HERE, "hang.pid"), "w", encoding="utf-8") as fh:
                fh.write(str(os.getpid()))
            time.sleep(600)
        plugin, market = a[2].split("@")
        src = state["marketplaces"][market]
        version = read_json(os.path.join(src, ".claude-plugin", "plugin.json"), {})["version"]
        dest = os.path.join(STATE_HOME, "plugins", "cache", market, plugin, version)
        copy_plugin(src, dest)
        state["installed"][a[2]] = {"version": version, "installPath": dest, "market": market}
        write_json(state_path, state)
        write_json(os.path.join(STATE_HOME, "plugins", "installed_plugins.json"), {"version": 2, "plugins": {a[2]: [{"installPath": dest}]}})
        return out({"outcome": "ok"})
    if a == ["plugin", "list", "--json"]:
        return out([{"id": k, "version": v["version"], "installPath": v["installPath"], "enabled": True}
                    for k, v in state["installed"].items()])
    if a[:2] == ["plugin", "details"] and len(a) == 3:
        root = state["installed"][a[2]]["installPath"]
        names = skills(root) + commands(root)
        if MODE == "discovery_short":
            names = names[:-1]
        print("Fixture (%s)\n\nComponent inventory\n  Skills (%d)  %s\n  Agents (0)\n" % (a[2], len(names), ", ".join(names)))
        return
    if a[:3] == ["plugin", "marketplace", "update"] and len(a) == 4:
        return out({"outcome": "ok"})
    if a[:2] == ["plugin", "update"] and len(a) == 3:
        rec = state["installed"][a[2]]
        src = state["marketplaces"][rec["market"]]
        version = read_json(os.path.join(src, ".claude-plugin", "plugin.json"), {})["version"]
        if version != rec["version"] and MODE != "no_refresh":
            plugin, market = a[2].split("@")
            dest = os.path.join(STATE_HOME, "plugins", "cache", market, plugin, version)
            copy_plugin(src, dest)
            rec.update(version=version, installPath=dest)
            write_json(state_path, state)
        return out({"outcome": "ok"})
    if a[:2] == ["plugin", "uninstall"] and len(a) == 3:
        if MODE != "keep_record":
            state["installed"].pop(a[2], None)
            write_json(state_path, state)
        if MODE == "clobber_settings":
            write_json(os.path.join(STATE_HOME, "settings.json"), {"enabledPlugins": {}})
        return out({"outcome": "ok"})
    violation("argv outside the claude allowlist")


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def codex_app_server(state):
    for raw in sys.stdin:
        if not raw.strip():
            continue
        msg = json.loads(raw)
        method = msg.get("method")
        if method == "initialize":
            send({"id": msg["id"], "result": {"userAgent": "fake"}})
        elif method == "initialized":
            continue
        elif method == "skills/list":
            names = []
            for pid, rec in state["installed"].items():
                plugin = pid.split("@")[0]
                names += [plugin + ":" + s for s in skills(rec["installedPath"])]
                names += [plugin + ":source-command-" + c for c in commands(rec["installedPath"])]
            if MODE == "discovery_short":
                names = names[:-1]
            names.append("imagegen")
            cwds = (msg.get("params") or {}).get("cwds") or [""]
            send({"method": "remoteControl/status/changed", "params": {}})
            send({"id": msg["id"], "result": {"data": [{"cwd": cwds[0], "errors": [],
                                                         "skills": [{"name": n, "enabled": True} for n in names]}]}})
        else:
            violation("app-server method %s" % method)


def codex():
    help_or_violation({
        ("plugin", "add"): "Install a plugin\n\nUsage: codex plugin add [OPTIONS] <PLUGIN[@MARKETPLACE]>\n\nOptions:\n      --json\n          Output install result as JSON\n",
        ("plugin", "list"): "Usage: codex plugin list [OPTIONS]\n\nOptions:\n      --json\n          Output plugin list as JSON\n",
        ("plugin", "remove"): "Usage: codex plugin remove [OPTIONS] <PLUGIN[@MARKETPLACE]>\n\nOptions:\n      --json\n",
        ("app-server",): "[experimental] Run the app server\n\nUsage: codex app-server [OPTIONS] [COMMAND]\n\nOptions:\n      --stdio\n",
    }, "Codex CLI\n\nUsage: codex [OPTIONS] [PROMPT]\n")
    state_path = os.path.join(STATE_HOME, "fake-state.json")
    state = read_json(state_path, {"installed": {}})
    home = os.environ["HOME"]
    a = ARGV
    if a == ["app-server", "--stdio"]:
        return codex_app_server(state)
    if a[:2] == ["plugin", "add"] and len(a) == 4 and a[3] == "--json":
        plugin, market = a[2].split("@")
        catalog = read_json(os.path.join(home, ".agents", "plugins", "marketplace.json"), None)
        if not catalog or catalog.get("name") != market:
            sys.stderr.write("fake: unknown marketplace\n")
            sys.exit(1)
        entry = [p for p in catalog["plugins"] if p["name"] == plugin][0]
        src = os.path.normpath(os.path.join(home, entry["source"]["path"]))
        check_source(src)
        version = read_json(os.path.join(src, ".codex-plugin", "plugin.json"), {})["version"]
        if MODE == "no_refresh" and a[2] in state["installed"]:
            rec = state["installed"][a[2]]
        else:
            dest = os.path.join(STATE_HOME, "plugins", "cache", market, plugin, version)
            copy_plugin(src, dest)
            rec = state["installed"][a[2]] = {"version": version, "installedPath": dest}
            write_json(state_path, state)
        return out({"pluginId": a[2], "version": rec["version"], "installedPath": rec["installedPath"]})
    if a == ["plugin", "list", "--json"]:
        return out({"installed": [{"pluginId": k, "version": v["version"], "installed": True}
                                  for k, v in state["installed"].items()], "available": []})
    if a[:2] == ["plugin", "remove"] and len(a) == 4 and a[3] == "--json":
        if MODE != "keep_record":
            state["installed"].pop(a[2], None)
            write_json(state_path, state)
        if MODE == "clobber_settings":
            with open(os.path.join(STATE_HOME, "config.toml"), "w", encoding="utf-8") as fh:
                fh.write("")
        return out({"pluginId": a[2]})
    violation("argv outside the codex allowlist")


def grok():
    help_or_violation({
        ("plugin", "install"): "Install a plugin from a git URL or local path\n\nUsage: grok plugin install [OPTIONS] <SOURCE>\n\nOptions:\n      --trust  Trust the plugin immediately\n",
        ("plugin", "list"): "List installed plugins\n\nUsage: grok plugin list [OPTIONS]\n\nOptions:\n      --json\n",
        ("plugin", "uninstall"): "Uninstall an installed plugin by name\n\nUsage: grok plugin uninstall [OPTIONS] <NAME>\n",
        ("inspect",): "Show the configuration Grok discovers\n\nUsage: grok inspect [OPTIONS]\n\nOptions:\n      --json\n",
    }, "Grok Build TUI\n\nUsage: grok [OPTIONS] [PROMPT] [COMMAND]\n")
    reg_path = os.path.join(STATE_HOME, "installed-plugins", "registry.json")
    reg = read_json(reg_path, {"repos": {}, "uninstalls": 0})
    cfg = os.path.join(STATE_HOME, "config.toml")
    a = ARGV
    if a[:2] == ["plugin", "install"] and len(a) == 4 and a[3] == "--trust":
        src = a[2]
        check_source(src)
        manifest = read_json(os.path.join(src, ".grok-plugin", "plugin.json"), {})
        name = manifest["name"]
        if name in reg["repos"]:
            sys.stderr.write("Error: repo already installed\n")
            sys.exit(1)
        dest = os.path.join(STATE_HOME, "installed-plugins", name + "-fake")
        if not (MODE == "no_refresh" and os.path.isdir(dest)):
            copy_plugin(src, dest)
        reg["repos"][name] = {"version": manifest["version"], "path": dest}
        write_json(reg_path, reg)
        text = open(cfg, encoding="utf-8").read() if os.path.exists(cfg) else ""
        if "[plugins]" not in text:
            with open(cfg, "a", encoding="utf-8") as fh:
                fh.write('\n[plugins]\nenabled = ["%s"]\n' % name)
        print("Installed 1 plugin(s) from %s: %s" % (src, name))
        return
    if a == ["plugin", "list", "--json"]:
        return out([{"status": "installed", "name": k, "version": v["version"], "path": v["path"]}
                    for k, v in reg["repos"].items()])
    if a == ["inspect", "--json"]:
        found = []
        for name, rec in reg["repos"].items():
            names = skills(rec["path"]) + commands(rec["path"])
            if MODE == "discovery_short":
                names = names[:-1]
            found += [{"name": n, "source": {"type": "plugin", "plugin_name": name}} for n in names]
        found.append({"name": "user-skill", "source": {"type": "user"}})
        return out({"grokVersion": "fake", "skills": found, "plugins": []})
    if a[:2] == ["plugin", "uninstall"] and len(a) == 3:
        rec = reg["repos"].get(a[2])
        if rec is None:
            sys.stderr.write("fake: not installed\n")
            sys.exit(1)
        reg["uninstalls"] = reg.get("uninstalls", 0) + 1
        # The refresh is uninstall + install, so a kept record is modelled on the FINAL uninstall.
        if not (MODE == "keep_record" and reg["uninstalls"] >= 2):
            reg["repos"].pop(a[2])
            if MODE != "no_refresh":
                shutil.rmtree(rec["path"], ignore_errors=True)
        write_json(reg_path, reg)
        if MODE == "clobber_settings":
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write("")
        print("Uninstalled 1 plugin(s): %s" % a[2])
        return
    violation("argv outside the grok allowlist")


def kimi_serve(port):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    if MODE == "no_server":
        sys.exit(3)
    token = secrets.token_hex(16)
    if MODE != "token_stdout_only":
        with open(os.path.join(STATE_HOME, "server.token"), "w", encoding="utf-8") as fh:
            fh.write(token + "\n")
    with open(os.path.join(HERE, "kimi.pid"), "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    # Kimi 2.1.1 prints the bearer token in its startup banner.
    print("  ▐█▌  Kimi server ready  fake\n\n  Local:    http://127.0.0.1:%d/#token=%s\n\n  Token:    %s\n" % (port, token, token))
    sys.stdout.flush()
    registry = os.path.join(STATE_HOME, "plugins", "installed.json")
    removals = []

    def summary(entry):
        root = entry["root"]
        count = len(skills(root)) - (1 if MODE == "discovery_short" else 0)
        return {"id": entry["id"], "version": entry["version"], "root": root, "enabled": True,
                "skillCount": count, "commandCount": len(commands(root))}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body):
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            if MODE == "needs_login" or self.headers.get("Authorization") != "Bearer " + token:
                self.reply(401, {"code": 401, "msg": "unauthorized"})
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            reg = read_json(registry, {"version": 1, "plugins": []})
            if self.path == "/api/v1/meta":
                return self.reply(200, {"code": 0, "data": {"server_version": "fake"}})
            if self.path == "/api/v1/plugins":
                return self.reply(200, {"code": 0, "data": {"plugins": [summary(p) for p in reg["plugins"]]}})
            record_violation("GET " + self.path)
            self.reply(404, {"code": 404})

        def do_POST(self):
            if not self.authorized():
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            # Kimi 2.1.1 wants a JSON object body with Content-Type application/json on every POST
            # (an empty body with that type is rejected with code 50001).
            if self.headers.get("Content-Type") != "application/json" or not raw:
                record_violation("POST %s without a JSON body" % self.path)
                return self.reply(400, {"code": 50001, "msg": "invalid body"})
            body = json.loads(raw.decode("utf-8"))
            reg = read_json(registry, {"version": 1, "plugins": []})
            if self.path == "/api/v1/plugins":
                src = body["source"]
                if not os.path.isabs(src):
                    record_violation("relative plugin source")
                    return self.reply(400, {"code": 400})
                if os.path.exists(os.path.join(src, ".git")) or src.isascii() or " " not in src:
                    record_violation("install source path is not the hostile copy")
                manifest = read_json(os.path.join(src, ".kimi-plugin", "plugin.json"), {})
                root = os.path.join(STATE_HOME, "plugins", "managed", manifest["name"])
                if not (MODE == "no_refresh" and os.path.isdir(root)):
                    copy_plugin(src, root)
                entry = {"id": manifest["name"], "version": manifest["version"], "root": root}
                reg["plugins"] = [p for p in reg["plugins"] if p["id"] != entry["id"]] + [entry]
                write_json(registry, reg)
                return self.reply(200, {"code": 0, "msg": "success", "data": summary(entry)})
            if self.path.startswith("/api/v1/plugins/") and self.path.endswith(":remove"):
                plugin_id = self.path[len("/api/v1/plugins/"):-len(":remove")]
                removals.append(plugin_id)
                if MODE != "keep_record":
                    reg["plugins"] = [p for p in reg["plugins"] if p["id"] != plugin_id]
                    write_json(registry, reg)
                if MODE == "clobber_settings":
                    with open(os.path.join(STATE_HOME, "tui.toml"), "w", encoding="utf-8") as fh:
                        fh.write("")
                return self.reply(200, {"code": 0, "data": {"ok": True}})
            record_violation("POST " + self.path)
            self.reply(404, {"code": 404})

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def kimi():
    help_or_violation({
        ("web",): "Usage: kimi web [options] [command]\n\nOptions:\n  --port <port>  Bind port\n  --no-open      Do not open the web UI\n",
    }, "Usage: kimi [options] [command]\n")
    a = ARGV
    if len(a) == 4 and a[:3] == ["web", "--no-open", "--port"] and a[3].isdigit():
        return kimi_serve(int(a[3]))
    violation("argv outside the kimi allowlist")


{"claude": claude, "codex": codex, "grok": grok, "kimi": kimi}[NAME]()
'''


def install_fake(fakebin, name):
    path = fakebin / name
    path.write_bytes(("#!%s\n" % sys.executable + FAKE_CLI).encode("utf-8"))
    path.chmod(0o755)
    return path


def _inside(path, root):
    try:
        Path(os.path.realpath(path)).relative_to(os.path.realpath(root))
        return True
    except ValueError:
        return False


class ExitRuleAndReasonTests(unittest.TestCase):
    """Pure helpers: the BINDING exit rule, the line format and reason hygiene."""

    @classmethod
    def setUpClass(cls):
        cls.checker = load_checker()

    def test_exit_rule(self):
        exit_code = self.checker.exit_code
        passed = {"claude": ("passed", None), "codex": ("passed", None)}
        self.assertEqual(exit_code(passed, required=()), 0)
        self.assertEqual(exit_code(dict(passed, grok=("failed", "install_failed")), required=()), 1)
        self.assertEqual(exit_code(dict(passed, zcode=("not-run", "no_headless_installer")), required=()), 0)
        self.assertEqual(exit_code(dict(passed, zcode=("not-run", "no_headless_installer")), required=("zcode",)), 1)
        self.assertEqual(exit_code(passed, required=("claude",)), 0)

    def test_line_format(self):
        line = self.checker.format_line
        self.assertEqual(line("claude", "passed", None), "native_claude=passed")
        self.assertEqual(line("codex", "failed", "install_failed"), "native_codex=failed:install_failed")
        self.assertEqual(line("zcode", "not-run", "no_headless_installer"), "native_zcode=not-run:no_headless_installer")

    def test_reasons_are_slugs_without_paths_or_identity(self):
        safe = self.checker.safe_reason
        self.assertEqual(safe("discovery_mismatch:expected=17,got=16"), "discovery_mismatch:expected=17,got=16")
        for leaked in ("install failed at /tmp/native-lifecycle-x/plug in", "C:\\Users\\someone\\AppData",
                       "failed:Bad Thing", "install_failed:" + "x" * 200):
            with self.subTest(reason=leaked):
                self.assertEqual(safe(leaked), "internal_error")
        self.assertEqual(safe("install_failed:alice", forbidden=("alice",)), "internal_error")

    def test_hostile_segment_has_space_and_non_ascii_but_no_separator_hazards(self):
        segment = self.checker.HOSTILE_SEGMENT
        self.assertIn(" ", segment)
        self.assertFalse(segment.isascii())
        for hazard in "#&%@":
            self.assertNotIn(hazard, segment)

    def test_kimi_banner_token_needs_a_complete_line(self):
        token = self.checker.banner_token
        banner = "  Kimi server ready  2.1.1\n\n  Local:    http://127.0.0.1:1/#token=abc123\n\n  Token:    abc123\n"
        self.assertEqual(token(banner), "abc123")
        self.assertEqual(token(banner.replace("\n", "\r\n")), "abc123")
        self.assertEqual(token("  \x1b[1mToken:\x1b[0m    abc123\n"), "abc123")
        self.assertIsNone(token("  Token:    abc1"), "a line still being written is not a token")
        self.assertIsNone(token("  Local:    http://127.0.0.1:1/#token=abc123\n"))

    def test_bump_version(self):
        self.assertEqual(self.checker.bump_version("0.4.3"), "0.4.4")
        self.assertEqual(self.checker.bump_version("1.2.9-rc.1"), "1.2.10")
        with self.assertRaises(self.checker.Failed) as ctx:
            self.checker.bump_version("latest")
        self.assertEqual(ctx.exception.reason, "version_unparseable")

    def test_expected_counts_come_from_the_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = build_package(Path(tmp))
            self.assertEqual(self.checker.package_counts(pkg), (3, 1))
        self.assertEqual(self.checker.package_counts(REPO)[1], 1)
        self.assertEqual(self.checker.package_counts(REPO)[0],
                         sum(1 for p in (REPO / "skills").iterdir() if (p / "SKILL.md").is_file()))

    def test_package_copy_excludes_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = build_package(Path(tmp))
            dest = Path(tmp) / "copy" / self.checker.HOSTILE_SEGMENT / "plugins" / "fixture-plugin"
            self.checker.copy_package(pkg, dest)
            self.assertFalse((dest / ".git").exists())
            self.assertEqual((dest / "skills" / "alpha-skill" / "SKILL.md").read_bytes(),
                             (pkg / "skills" / "alpha-skill" / "SKILL.md").read_bytes())

    def test_every_terminating_console_signal_is_turned_into_an_exit(self):
        # Ctrl+Break (Windows SIGBREAK) ends the process without unwinding, like SIGTERM/SIGHUP.
        names = [name for name in ("SIGTERM", "SIGHUP", "SIGBREAK") if hasattr(signal, name)]
        saved = {name: signal.getsignal(getattr(signal, name)) for name in names}
        try:
            self.checker.install_signal_exits()
            for name in names:
                with self.subTest(signal=name):
                    self.assertIs(signal.getsignal(getattr(signal, name)), self.checker._exit_on_signal)
        finally:
            for name, handler in saved.items():
                signal.signal(getattr(signal, name), handler)
        self.assertIn('"SIGBREAK"', SCRIPT.read_text(encoding="utf-8"))


class ResolutionTests(unittest.TestCase):
    """Absolute-PATH executable resolution; Windows suffix rules are simulated on every OS."""

    @classmethod
    def setUpClass(cls):
        cls.checker = load_checker()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _dir(self, name, *files, mode=0o755):
        folder = self.base / name
        folder.mkdir()
        for file in files:
            (folder / file).write_bytes(b"#!/bin/sh\nexit 0\n")
            (folder / file).chmod(mode)
        return str(folder)

    def _not_run(self, *args, **kwargs):
        with self.assertRaises(self.checker.NotRun) as ctx:
            self.checker.resolve_cli(*args, **kwargs)
        return ctx.exception.reason

    def test_windows_script_shims_are_refused(self):
        for shim in ("claude.cmd", "claude.bat", "claude.ps1"):
            with self.subTest(shim=shim):
                folder = self._dir("shim-" + shim.replace(".", "-"), shim)
                self.assertEqual(self._not_run("claude", path_value=folder, windows=True), "cli_is_script_shim")

    def test_windows_exe_wins_over_a_shim_in_the_same_folder(self):
        folder = self._dir("both", "claude.cmd", "claude.exe")
        self.assertEqual(self.checker.resolve_cli("claude", path_value=folder, windows=True),
                         os.path.join(folder, "claude.exe"))

    def test_windows_earlier_shim_shadows_a_later_exe(self):
        first = self._dir("first", "codex.cmd")
        second = self._dir("second", "codex.exe")
        self.assertEqual(self._not_run("codex", path_value=os.pathsep.join([first, second]), windows=True),
                         "cli_is_script_shim")

    def test_relative_path_entries_are_never_searched(self):
        self._dir("relative", "grok.exe", "grok")
        old = os.getcwd()
        os.chdir(self.base)
        try:
            self.assertEqual(self._not_run("grok", path_value="relative", windows=True), "cli_absent")
            self.assertEqual(self._not_run("grok", path_value="relative", windows=False), "cli_absent")
        finally:
            os.chdir(old)

    def test_absent_cli(self):
        self.assertEqual(self._not_run("kimi", path_value=self._dir("empty"), windows=False), "cli_absent")

    @unittest.skipIf(sys.platform == "win32", "POSIX exec-bit rule")
    def test_posix_candidate_needs_the_exec_bit(self):
        folder = self._dir("noexec", "kimi", mode=0o644)
        self.assertEqual(self._not_run("kimi", path_value=folder, windows=False), "cli_absent")
        folder = self._dir("exec", "kimi")
        self.assertEqual(self.checker.resolve_cli("kimi", path_value=folder, windows=False),
                         os.path.join(folder, "kimi"))


class ChildEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checker = load_checker()

    def test_child_environment_is_built_from_the_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_env = dict(SECRET_ENV, PATH=os.pathsep.join([str(root / "abs-bin"), "relative-bin"]),
                            HOME="/real/home", CODEX_HOME="/real/home/.codex", CLAUDE_CONFIG_DIR="/real/claude",
                            LANG="C.UTF-8", SHELL="/bin/bash", EDITOR="vim", SSH_AUTH_SOCK="/tmp/agent")
            env = self.checker.build_child_env(root, home=root / "home", base_env=base_env)
            self.assertLessEqual(set(env), ALLOWED_CHILD_ENV)
            for key in env:
                self.assertFalse(key.startswith(FORBIDDEN_PREFIXES), key)
            for secret in SECRET_ENV.values():
                self.assertNotIn(secret, json.dumps(env))
            for key in HOME_VARS:
                with self.subTest(var=key):
                    self.assertTrue(_inside(env[key], root), key)
                    self.assertTrue(Path(env[key]).is_dir(), key)
            self.assertEqual(env["PATH"], str(root / "abs-bin"))
            self.assertEqual(env["LANG"], "C.UTF-8")
            self.assertEqual(env["DISABLE_AUTOUPDATER"], "1")
            self.assertEqual(env["KIMI_DISABLE_TELEMETRY"], "1")


@unittest.skipIf(sys.platform == "win32",
                 "fake CLIs need a POSIX exec bit and shebang; Windows resolution is covered by ResolutionTests")
class FakeCliLifecycleTests(unittest.TestCase):
    """The full checker against fail-closed fake CLIs on a PATH that holds only the fake folder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="native-lifecycle-test-")
        self.base = Path(self._tmp.name)
        self.fakebin = self.base / "fakebin"
        self.scratch = self.base / "scratch"
        self.pretend_home = self.base / "pretend-real-home"
        for folder in (self.fakebin, self.scratch, self.pretend_home):
            folder.mkdir()
        self.package = build_package(self.base)
        for name in ("claude", "codex", "grok", "kimi"):
            install_fake(self.fakebin, name)

    def tearDown(self):
        pid_file = self.fakebin / "kimi.pid"
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text(encoding="utf-8")), signal.SIGKILL)
            except (ProcessLookupError, ValueError, PermissionError):
                pass
        self._tmp.cleanup()

    def checker_env(self, modes=None):
        (self.fakebin / "fake-config.json").write_text(json.dumps({"modes": modes or {}}), encoding="utf-8")
        return dict(SECRET_ENV, PATH=str(self.fakebin), TMPDIR=str(self.scratch), TEMP=str(self.scratch),
                    TMP=str(self.scratch), HOME=str(self.pretend_home), LANG="C.UTF-8",
                    CODEX_HOME=str(self.pretend_home / ".codex"), CLAUDE_CONFIG_DIR=str(self.pretend_home / ".claude"),
                    GROK_HOME=str(self.pretend_home / ".grok"), KIMI_CODE_HOME=str(self.pretend_home / ".kimi-code"))

    def run_checker(self, *args, modes=None, timeout="60"):
        env = self.checker_env(modes)
        proc = subprocess.run([sys.executable, str(SCRIPT), "--package", str(self.package), "--timeout", timeout, *args],
                              cwd=str(self.base), env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", timeout=600)
        return proc

    def lines(self, proc):
        return proc.stdout.splitlines()

    def calls(self):
        path = self.fakebin / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def violations(self):
        path = self.fakebin / "violations.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_fake_cli_fails_closed_on_a_prompt_argv(self):
        (self.fakebin / "fake-config.json").write_text("{}", encoding="utf-8")
        env = {"PATH": str(self.fakebin), "CLAUDE_CONFIG_DIR": str(self.base)}
        proc = subprocess.run([str(self.fakebin / "claude"), "-p", "hello"], env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 97)
        self.assertIn('"-p"', self.violations())

    def test_all_platforms_pass_and_exit_zero(self):
        proc = self.run_checker("--platform", "all")
        self.assertEqual(self.lines(proc), ["native_claude=passed", "native_codex=passed", "native_grok=passed",
                                            "native_kimi=passed", "native_zcode=not-run:no_headless_installer"],
                         proc.stderr[-3000:])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.violations(), "")
        clis = {call["cli"] for call in self.calls()}
        self.assertEqual(clis, {"claude", "codex", "grok", "kimi"})

    def test_default_platform_is_all(self):
        proc = self.run_checker()
        self.assertEqual([line.split("=")[0] for line in self.lines(proc)],
                         ["native_" + name for name in PLATFORMS])

    def test_only_plugin_management_argv_reaches_the_clis(self):
        self.run_checker("--platform", "all")
        allowed_heads = {"claude": {("plugin",)}, "codex": {("plugin",), ("app-server",)},
                         "grok": {("plugin",), ("inspect",)}, "kimi": {("web",)}}
        for call in self.calls():
            with self.subTest(cli=call["cli"], argv=call["argv"]):
                self.assertIn(tuple(call["argv"][:1]), allowed_heads[call["cli"]])
                for prompt_flag in ("-p", "--prompt", "exec", "agent"):
                    self.assertNotIn(prompt_flag, call["argv"])

    def test_not_run_alone_exits_zero(self):
        proc = self.run_checker("--platform", "zcode")
        self.assertEqual(self.lines(proc), ["native_zcode=not-run:no_headless_installer"])
        self.assertEqual(proc.returncode, 0)

    def test_required_not_run_exits_one(self):
        proc = self.run_checker("--platform", "zcode", "--require", "zcode")
        self.assertEqual(self.lines(proc), ["native_zcode=not-run:no_headless_installer"])
        self.assertEqual(proc.returncode, 1)

    def test_require_outside_the_selection_is_a_usage_error(self):
        proc = self.run_checker("--platform", "zcode", "--require", "claude")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")

    def test_claude_without_json_on_marketplace_subcommands_still_qualifies(self):
        # Claude Code 2.1.282 lacks --json on `plugin marketplace add|update`; only `plugin list`
        # output is parsed, so such a build must pass rather than be called too old.
        proc = self.run_checker("--platform", "claude", modes={"claude": "legacy_json"})
        self.assertEqual(self.lines(proc), ["native_claude=passed"], proc.stderr[-2000:])
        self.assertEqual(self.violations(), "")

    def test_failed_platform_exits_one(self):
        proc = self.run_checker("--platform", "claude", modes={"claude": "install_fail"})
        self.assertEqual(self.lines(proc), ["native_claude=failed:install_failed"])
        self.assertEqual(proc.returncode, 1)

    def test_discovery_count_is_verified_per_platform(self):
        expected = {"claude": 4, "codex": 4, "grok": 4, "kimi": 3}
        for platform, count in expected.items():
            with self.subTest(platform=platform):
                proc = self.run_checker("--platform", platform, modes={platform: "discovery_short"})
                self.assertEqual(self.lines(proc), ["native_%s=failed:discovery_mismatch:expected=%d,got=%d"
                                                    % (platform, count, count - 1)], proc.stderr[-2000:])
                self.assertEqual(proc.returncode, 1)

    def test_refresh_must_replace_the_installed_bytes(self):
        for platform in ("claude", "codex", "grok", "kimi"):
            with self.subTest(platform=platform):
                proc = self.run_checker("--platform", platform, modes={platform: "no_refresh"})
                self.assertEqual(self.lines(proc), ["native_%s=failed:refresh_not_applied" % platform],
                                 proc.stderr[-2000:])

    def test_uninstall_must_remove_the_plugin_record(self):
        for platform in ("claude", "codex", "grok", "kimi"):
            with self.subTest(platform=platform):
                proc = self.run_checker("--platform", platform, modes={platform: "keep_record"})
                self.assertEqual(self.lines(proc), ["native_%s=failed:record_not_removed" % platform],
                                 proc.stderr[-2000:])

    def test_unrelated_sentinel_setting_must_survive(self):
        for platform in ("claude", "codex", "grok", "kimi"):
            with self.subTest(platform=platform):
                proc = self.run_checker("--platform", platform, modes={platform: "clobber_settings"})
                self.assertEqual(self.lines(proc), ["native_%s=failed:sentinel_lost" % platform],
                                 proc.stderr[-2000:])

    def test_absent_cli_is_not_run_unless_required(self):
        (self.fakebin / "kimi").unlink()
        proc = self.run_checker("--platform", "kimi")
        self.assertEqual(self.lines(proc), ["native_kimi=not-run:cli_absent"])
        self.assertEqual(proc.returncode, 0)
        proc = self.run_checker("--platform", "kimi", "--require", "kimi")
        self.assertEqual(proc.returncode, 1)

    def test_old_cli_is_not_run_and_never_receives_plugin_argv(self):
        for platform in ("claude", "codex", "grok", "kimi"):
            with self.subTest(platform=platform):
                proc = self.run_checker("--platform", platform, modes={platform: "old"})
                self.assertEqual(self.lines(proc), ["native_%s=not-run:cli_too_old" % platform])
                self.assertEqual(proc.returncode, 0)
                self.assertEqual(self.violations(), "")
                for call in self.calls():
                    self.assertEqual(call["argv"][-1:], ["--help"], call["argv"])

    def test_child_environment_is_allowlisted_and_isolated(self):
        self.run_checker("--platform", "all")
        calls = self.calls()
        self.assertTrue(calls)
        for call in calls:
            env = call["env"]
            with self.subTest(cli=call["cli"], argv=call["argv"]):
                for key in env:
                    self.assertFalse(key.startswith(FORBIDDEN_PREFIXES), key)
                for secret in SECRET_ENV.values():
                    self.assertNotIn(secret, json.dumps(env))
                for key in HOME_VARS:
                    self.assertIn(key, env)
                    self.assertTrue(_inside(env[key], self.scratch), key)
                    self.assertFalse(_inside(env[key], self.pretend_home), key)
                self.assertEqual(env["PATH"], str(self.fakebin))
                self.assertTrue(_inside(call["cwd"], self.scratch))
                self.assertFalse(_inside(call["cwd"], REPO))

    def test_reasons_never_leak_paths_or_identity(self):
        identity = [str(self.scratch), str(self.base), str(self.package), str(REPO), socket.gethostname()]
        user = getpass.getuser()
        if len(user) >= 3:
            identity.append(user)
        runs = [
            self.run_checker("--platform", "all", modes={"claude": "install_fail", "codex": "discovery_short",
                                                         "grok": "keep_record", "kimi": "needs_login"}),
            self.run_checker("--platform", "all", modes={"claude": "no_refresh", "codex": "clobber_settings",
                                                         "grok": "old", "kimi": "no_server"}),
        ]
        for proc in runs:
            self.assertEqual(len(self.lines(proc)), len(PLATFORMS))
            for line in self.lines(proc):
                with self.subTest(line=line):
                    self.assertRegex(line, LINE_RE)
                    for value in identity:
                        self.assertNotIn(value, line)

    def test_kimi_login_or_start_failure_is_not_run(self):
        proc = self.run_checker("--platform", "kimi", modes={"kimi": "needs_login"})
        self.assertEqual(self.lines(proc), ["native_kimi=not-run:server_auth_unavailable"])
        proc = self.run_checker("--platform", "kimi", modes={"kimi": "no_server"})
        self.assertEqual(self.lines(proc), ["native_kimi=not-run:server_start_failed"])

    def test_kimi_token_is_read_from_the_banner_when_no_token_file_exists(self):
        proc = self.run_checker("--platform", "kimi", modes={"kimi": "token_stdout_only"})
        self.assertEqual(self.lines(proc), ["native_kimi=passed"], proc.stderr[-2000:])
        self.assertEqual(self.violations(), "")

    def test_kimi_server_is_terminated_after_the_run(self):
        proc = self.run_checker("--platform", "kimi")
        self.assertEqual(self.lines(proc), ["native_kimi=passed"], proc.stderr[-2000:])
        pid = int((self.fakebin / "kimi.pid").read_text(encoding="utf-8"))
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_a_hanging_cli_is_killed_and_reported(self):
        started = time.monotonic()
        proc = self.run_checker("--platform", "claude", modes={"claude": "hang"}, timeout="3")
        self.assertEqual(self.lines(proc), ["native_claude=failed:install_timeout"])
        self.assertLess(time.monotonic() - started, 120)

    def test_sigterm_stops_the_running_cli_and_removes_the_temporary_root(self):
        # SIGTERM's default action ended the checker without unwinding: the CLI in its own session
        # (or a `kimi web` server) kept running and the temporary root, token included, stayed.
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "--package", str(self.package), "--timeout", "300",
                                 "--platform", "claude"], cwd=str(self.base), env=self.checker_env({"claude": "hang"}),
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pid_file = self.fakebin / "hang.pid"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not (pid_file.exists() and pid_file.read_text(encoding="utf-8")):
            time.sleep(0.1)
        try:
            hung = int(pid_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            proc.kill()
            proc.communicate()
            self.fail("the fake CLI never reached its hanging step")
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 128 + signal.SIGTERM)
        self.assertEqual(list(self.scratch.iterdir()), [])
        gone = time.monotonic() + 10
        while time.monotonic() < gone:
            try:
                os.kill(hung, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            os.kill(hung, signal.SIGKILL)
            self.fail("the hanging CLI survived the checker's SIGTERM")

    def test_temporary_root_is_removed_unless_kept(self):
        self.run_checker("--platform", "claude")
        self.assertEqual(list(self.scratch.iterdir()), [])
        proc = self.run_checker("--platform", "claude", "--keep-temp")
        kept = list(self.scratch.iterdir())
        self.assertEqual(len(kept), 1)
        self.assertIn(str(kept[0]), proc.stderr)
        self.assertNotIn(str(kept[0]), proc.stdout)


def _real_profile_files(platform):
    """The real profile's plugin files for one platform: they must keep their size and mtime."""
    home = Path.home()
    roots = {
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude"),
        "codex": Path(os.environ.get("CODEX_HOME") or home / ".codex"),
        "grok": Path(os.environ.get("GROK_HOME") or home / ".grok"),
        "kimi": Path(os.environ.get("KIMI_CODE_HOME") or home / ".kimi-code"),
    }
    names = {
        "claude": ("settings.json", "plugins/installed_plugins.json", "plugins/known_marketplaces.json"),
        "codex": ("config.toml",),
        "grok": ("config.toml", "installed-plugins/registry.json"),
        "kimi": ("plugins/installed.json", "tui.toml"),
    }
    return [roots[platform] / name for name in names[platform]]


def _snapshot(paths):
    result = []
    for path in paths:
        try:
            stat = path.stat()
            result.append((str(path), stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            result.append((str(path), None, None))
    return result


class RealCliLifecycleTests(unittest.TestCase):
    """REAL CLI integration: the installed vendor CLI, a disposable profile, this checkout.

    Skipped when the CLI does not resolve (absent or a .cmd/.bat shim) or is too old for the
    plugin subcommands. Never sends a model prompt.
    """

    def _run_real(self, platform):
        checker = load_checker()
        try:
            checker.resolve_cli(platform)
        except checker.NotRun as exc:
            self.skipTest("REAL %s CLI not usable here (%s); native lifecycle not verified" % (platform, exc.reason))
        before = _snapshot(_real_profile_files(platform))
        proc = subprocess.run([sys.executable, str(SCRIPT), "--package", str(REPO), "--platform", platform,
                               "--require", platform], stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", timeout=1800)
        lines = proc.stdout.splitlines()
        if lines == ["native_%s=not-run:cli_too_old" % platform]:
            self.skipTest("REAL %s CLI predates the plugin subcommands" % platform)
        self.assertEqual(lines, ["native_%s=passed" % platform], proc.stderr[-3000:])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(_snapshot(_real_profile_files(platform)), before, "the real profile was modified")

    def test_real_claude_cli_lifecycle(self):
        self._run_real("claude")

    def test_real_codex_cli_lifecycle(self):
        self._run_real("codex")

    def test_real_grok_cli_lifecycle(self):
        self._run_real("grok")

    def test_real_kimi_cli_lifecycle(self):
        self._run_real("kimi")


# --- Direct native layer (no checker) ---

CODEX = shutil.which("codex")
NATIVE_TRUST_SMOKE = os.environ.get("AGENTIC_NATIVE_TRUST_SMOKE") == "1"


class NoLoopbackRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def native_loopback_json(request, timeout=10):
    """Keep native server bearer authentication on the exact direct loopback URL."""
    url = urllib.parse.urlsplit(request.full_url)
    if (url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port
            or url.username is not None or url.password is not None):
        raise ValueError('Native management request must use direct loopback')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoLoopbackRedirects())
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


class NativeLoopbackBoundaryTests(unittest.TestCase):
    @contextlib.contextmanager
    def server(self, route, *, redirect=None):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                if redirect:
                    self.send_response(302)
                    self.send_header('Location', redirect)
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps({'route': route}).encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield 'http://127.0.0.1:' + str(server.server_port), seen
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def request(self, url):
        req = urllib.request.Request(url, headers={'Authorization': 'Bearer fixture-only'})
        return native_loopback_json(req)

    def test_loopback_authentication_never_uses_environment_proxy(self):
        with self.server('direct') as (direct, _), self.server('proxy') as (proxy, seen):
            with mock.patch.dict(os.environ, {'http_proxy': proxy, 'HTTP_PROXY': proxy,
                                              'no_proxy': '', 'NO_PROXY': ''}), \
                    mock.patch('urllib.request.proxy_bypass', return_value=False), \
                    mock.patch('urllib.request._opener', None):
                result = self.request(direct)
            self.assertEqual(result['route'], 'direct')
            self.assertEqual(seen, [], 'Loopback authentication reached a proxy')

    def test_loopback_authentication_never_follows_redirect(self):
        with self.server('target') as (target, seen), self.server('origin', redirect=target) as (origin, _):
            with mock.patch.dict(os.environ, {'no_proxy': '*', 'NO_PROXY': '*'}):
                with self.assertRaises(urllib.error.HTTPError):
                    self.request(origin)
            self.assertEqual(seen, [], 'Loopback authentication followed a redirect')


def isolated_native_env(base, runtime):
    """Isolate sibling catalogs and credential/config lookups as well as runtime home."""
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("GIT_", "AGENTIC_", "KIMI_", "GROK_", "CODEX_",
                                  "OPENAI_", "ANTHROPIC_", "XAI_"))}
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME",
                "XDG_DATA_HOME", "XDG_CACHE_HOME", runtime):
        directory = base / ("home" if key in ("HOME", "USERPROFILE") else key.lower())
        directory.mkdir(exist_ok=True)
        env[key] = str(directory)
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    return env


def copy_native_package(target, env):
    members = runtime_members(REPO)
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "ls-files", "-z", "--",
                             "docs", "workflows"], cwd=REPO, env=env,
                            capture_output=True, check=True, timeout=15)
    for name in result.stdout.decode("utf-8").split("\0"):
        if name:
            members[name] = (REPO / name).read_bytes()
    for name in ("README.md", "LICENSE", "VERSION", ".gitattributes"):
        members[name] = (REPO / name).read_bytes()
    for name, data in members.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def unrelated_native_plugin(target, manifest_dir):
    (target / manifest_dir).mkdir(parents=True)
    (target / "skills" / "sentinel").mkdir(parents=True)
    (target / manifest_dir / "plugin.json").write_text(json.dumps({
        "name": "unrelated-sentinel", "version": "1.0.0", "skills": "./skills/",
        "description": "Temporary configuration preservation fixture."}), encoding="utf-8")
    (target / "skills" / "sentinel" / "SKILL.md").write_text(
        "---\nname: sentinel\ndescription: Use for temporary native fixture inspection.\n---\n"
        "Report the fixture.\n", encoding="utf-8", newline="\n")
    (target / "sentinel.txt").write_bytes(b"keep unrelated plugin\n")


def loopback_origins(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() == "port" and isinstance(item, int) and 0 < item < 65536:
                yield "http://127.0.0.1:" + str(item)
            yield from loopback_origins(item)
    elif isinstance(value, list):
        for item in value:
            yield from loopback_origins(item)
    elif isinstance(value, str):
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost") and parsed.port:
            yield "http://127.0.0.1:" + str(parsed.port)


@unittest.skipUnless(CODEX and shutil.which("git"),
                     "Codex CLI/Git unavailable; native lifecycle not verified")
class NativeCodexLifecycleTests(unittest.TestCase):
    def test_codex_local_install_refresh_remove_preserves_other_settings(self):
        with tempfile.TemporaryDirectory(prefix="native-distribution-") as tmp:
            base = Path(tmp)
            catalog = base / "home \u00e7\u0131\u011f $ ` & # % '"
            codex_home = base / "isolated-profile"
            project = base / "unrelated-project"
            codex_home.mkdir()
            project.mkdir()
            config = codex_home / "config.toml"
            config.write_text('[profiles.preserve_me]\nmodel = "o3"\n', encoding="utf-8")
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("GIT_", "AGENTIC_", "CODEX_", "OPENAI_"))}
            # Also isolate default personal catalogs/config lookups beyond CODEX_HOME.
            env.update(CODEX_HOME=str(codex_home), HOME=str(catalog),
                       USERPROFILE=str(catalog),
                       XDG_CONFIG_HOME=str(base / "config"),
                       XDG_DATA_HOME=str(base / "data"),
                       APPDATA=str(base / "appdata"), LOCALAPPDATA=str(base / "localappdata"))
            for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
                Path(env[key]).mkdir()

            def run(*args, json_output=False):
                proc = subprocess.run([CODEX, "plugin", *args], cwd=project, env=env,
                                      capture_output=True, text=True, encoding="utf-8", timeout=45)
                self.assertEqual(proc.returncode, 0,
                                 f"native plugin {args[0]} exited {proc.returncode}: "
                                 + redact_text(proc.stderr).replace(str(base), "<temporary-root>")[:1200])
                return json.loads(proc.stdout) if json_output else proc.stdout

            # Check capability without reading configured marketplaces or starting a model.
            help_result = subprocess.run([CODEX, "plugin", "remove", "--help"],
                                         cwd=project, env=env, capture_output=True,
                                         text=True, encoding="utf-8", timeout=15)
            if (help_result.returncode and "unrecognized subcommand" in help_result.stderr
                    and any(word in help_result.stderr for word in ("'plugin'", "'remove'"))):
                self.skipTest("Codex CLI predates native plugin remove support")
            self.assertEqual(help_result.returncode, 0, "native CLI capability probe failed")
            if "--json" not in help_result.stdout:
                self.skipTest("Codex CLI lacks native plugin remove --json support")

            source = catalog / "plugins" / "agentic-sdlc"
            members = runtime_members(REPO)
            companions = subprocess.run(["git", "-c", "core.fsmonitor=false", "ls-files", "-z",
                                         "--", "docs", "workflows"], cwd=REPO, env=env,
                                        capture_output=True, check=True, timeout=15)
            for name in companions.stdout.decode("utf-8").split("\0"):
                if name:
                    members[name] = (REPO / name).read_bytes()
            for name in ("README.md", "LICENSE", "VERSION"):
                members[name] = (REPO / name).read_bytes()
            for rel, data in members.items():
                path = source / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            marker = source / "lifecycle-marker.txt"
            marker.write_text("initial source\n", encoding="utf-8")
            other = catalog / "plugins" / "unrelated-sentinel"
            (other / ".codex-plugin").mkdir(parents=True)
            (other / ".codex-plugin" / "plugin.json").write_text(json.dumps({
                "name": "unrelated-sentinel", "version": "1.0.0",
                "description": "Temporary configuration preservation fixture.",
                "skills": "./skills/"}), encoding="utf-8")
            (other / "skills" / "sentinel").mkdir(parents=True)
            (other / "skills" / "sentinel" / "SKILL.md").write_text(
                "---\nname: sentinel\ndescription: Use for temporary fixture inspection.\n---\n"
                "Report the fixture name.\n", encoding="utf-8")
            (other / "unrelated-marker.txt").write_text("keep this plugin\n", encoding="utf-8")
            marketplace = catalog / ".agents" / "plugins" / "marketplace.json"
            marketplace.parent.mkdir(parents=True)
            marketplace.write_text(json.dumps({"name": "distribution-lifecycle-check", "plugins": [
                {"name": name, "source": {"source": "local", "path": "./plugins/" + name},
                 "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                 "category": "Developer Tools"}
                for name in ("agentic-sdlc", "unrelated-sentinel")]}), encoding="utf-8")
            # Use documented personal-catalog discovery. CLI 0.162.1's local
            # marketplace-add path rejects its default ref as Git-only.
            selector = "agentic-sdlc@distribution-lifecycle-check"
            other_selector = "unrelated-sentinel@distribution-lifecycle-check"

            def preserved_settings():
                settings = tomllib.loads(config.read_text(encoding="utf-8"))
                self.assertEqual(settings["profiles"]["preserve_me"], {"model": "o3"})
                self.assertTrue(settings["plugins"][other_selector]["enabled"])
                self.assertNotIn("state", settings.get("hooks", {}), "native test must not grant hook trust")
                return settings

            run("add", other_selector, "--json", json_output=True)
            run("add", selector, "--json", json_output=True)
            preserved_settings()
            copies = list((codex_home / "plugins" / "cache").rglob("lifecycle-marker.txt"))
            self.assertEqual(len(copies), 1, "native install must create exactly one cached copy")
            installed = copies[0]
            self.assertEqual(installed.read_bytes(), marker.read_bytes())
            self.assertNotEqual(installed.parent, source)
            for name in ("hooks/hooks-codex.json", "skills/using-agentic-sdlc/SKILL.md",
                         "skills/agentic-sdlc-pipeline/templates.md", "docs/runtime-adapter.md"):
                self.assertEqual((installed.parent / name).read_bytes(), members[name])
            unrelated = list((codex_home / "plugins" / "cache").rglob("unrelated-marker.txt"))
            self.assertEqual(len(unrelated), 1)
            unrelated_bytes = unrelated[0].read_bytes()
            marker.write_text("refreshed source\n", encoding="utf-8")
            self.assertNotEqual(installed.read_bytes(), marker.read_bytes(),
                                "editing the local source must not silently edit the installed copy")
            run("add", selector, "--json", json_output=True)
            preserved_settings()
            self.assertEqual(installed.read_bytes(), marker.read_bytes(),
                             "native reinstall must recopy the selected local source")
            run("remove", selector, "--json", json_output=True)
            self.assertFalse(installed.exists(), "native uninstall must remove its cached copy")
            self.assertEqual(unrelated[0].read_bytes(), unrelated_bytes)
            settings = preserved_settings()
            self.assertNotIn(selector, settings.get("plugins", {}))
            self.assertFalse((codex_home / "auth.json").exists())
            self.assertFalse((codex_home / "sessions").exists())


@unittest.skipUnless(NATIVE_TRUST_SMOKE,
                     "set AGENTIC_NATIVE_TRUST_SMOKE=1 only after authorizing disposable native installs")
class OptionalNativeLifecycleTests(unittest.TestCase):
    def run_native(self, args, cwd, env, base, success=True):
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=45, creationflags=flags)
        if success:
            reason = redact_text(result.stderr).replace(str(base), "<temporary-root>")
            self.assertEqual(result.returncode, 0, "native command failed: " + reason[:1000])
        return result

    def test_kimi_rest_install_recopy_remove_preserves_other_settings(self):
        executable = shutil.which("kimi")
        if not executable or not shutil.which("git"):
            self.skipTest("Kimi CLI/Git unavailable; native REST lifecycle not verified")
        with tempfile.TemporaryDirectory(prefix="native-kimi-") as tmp:
            base = Path(tmp)
            env = isolated_native_env(base, "KIMI_CODE_HOME")
            profile = Path(env["KIMI_CODE_HOME"])
            env.update(KIMI_CODE_NO_AUTO_UPDATE="1", KIMI_DISABLE_TELEMETRY="1",
                       KIMI_CODE_MODEL_CATALOG_REFRESH_ON_START="false",
                       KIMI_CODE_MODEL_CATALOG_REFRESH_INTERVAL_MS="0")
            project = base / "empty-project"
            project.mkdir()
            version = self.run_native([executable, "--version"], project, env, base).stdout.strip()
            # Startup/background controls were inspected in this exact native build.
            if version != "2.1.1":
                self.skipTest("Kimi build differs from reviewed 2.1.1 server startup controls")
            config = profile / "config.toml"
            config.write_bytes(b"telemetry = false\nauto_session_title = false\n# preserve sentinel\n")
            config_before = config.read_bytes()
            source = base / "source \u00e7\u0131\u011f $ ` & # % '"
            copy_native_package(source, env)
            marker = source / "lifecycle-marker.txt"
            marker.write_bytes(b"initial fixture\n")
            other = base / "unrelated-plugin"
            unrelated_native_plugin(other, ".kimi-plugin")
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            # Startup URL contains the bearer token; never retain raw stdout/stderr.
            process = subprocess.Popen([executable, "web", "--no-open", "--host", "127.0.0.1", "--port", "0"],
                                       cwd=project, env=env, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, creationflags=flags)
            origin = token = None

            def request(path, method="GET", body=None, auth=True):
                headers = {"Accept": "application/json"}
                if auth:
                    headers["Authorization"] = "Bearer " + token
                payload = None if body is None else json.dumps(body).encode()
                if payload is not None:
                    headers["Content-Type"] = "application/json"
                req = urllib.request.Request(origin + path, data=payload, headers=headers, method=method)
                return native_loopback_json(req)

            def api(path, method="GET", body=None):
                response = request(path, method, body)
                # Error envelopes frequently use HTTP 200. Do not print server msg/data.
                self.assertEqual(response.get("code"), 0, "native API returned a failure envelope")
                return response.get("data")

            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline and origin is None:
                    self.assertIsNone(process.poll(), "native server exited before readiness")
                    token_file = profile / "server.token"
                    if token_file.is_file():
                        token = token_file.read_text(encoding="utf-8").strip()
                        for entry in (profile / "server" / "instances").glob("*.json"):
                            try:
                                candidates = loopback_origins(json.loads(entry.read_text(encoding="utf-8")))
                                for candidate in candidates:
                                    origin = candidate
                                    response = request("/api/v1/healthz", auth=False)
                                    if response.get("code") == 0 and response.get("data", {}).get("ok") is True:
                                        break
                                    origin = None
                                if origin is not None:
                                    break
                            except (OSError, ValueError):
                                origin = None
                    if origin is None:
                        time.sleep(0.15)
                self.assertIsNotNone(origin, "native server readiness timed out")
                spec = request("/openapi.json")
                paths = spec.get("data", spec)["paths"]
                for path, method in (("/api/v1/plugins", "get"), ("/api/v1/plugins", "post"),
                                     ("/api/v1/plugins/{tail}", "post"), ("/api/v1/shutdown", "post")):
                    self.assertIn(method, paths.get(path, {}), "required native API route missing")
                self.assertEqual(config.read_bytes(), config_before)
                api("/api/v1/plugins", "POST", {"source": str(other)})
                summary = api("/api/v1/plugins", "POST", {"source": str(source)})
                self.assertEqual(summary["id"], "agentic-sdlc")
                self.assertEqual(summary["state"], "ok")
                self.assertFalse(summary["hasErrors"])
                self.assertEqual((summary["skillCount"], summary["commandCount"], summary["hookCount"],
                                  summary["mcpServerCount"]), (16, 1, 3, 0))
                installed = profile / "plugins" / "managed" / "agentic-sdlc" / marker.name
                unrelated = profile / "plugins" / "managed" / "unrelated-sentinel" / "sentinel.txt"

                def preserved():
                    self.assertEqual(config.read_bytes(), config_before)
                    self.assertEqual(unrelated.read_bytes(), b"keep unrelated plugin\n")

                self.assertEqual(installed.read_bytes(), marker.read_bytes())
                preserved()
                marker.write_bytes(b"refreshed fixture\n")
                self.assertNotEqual(installed.read_bytes(), marker.read_bytes())
                api("/api/v1/plugins", "POST", {"source": str(source)})
                self.assertEqual(installed.read_bytes(), marker.read_bytes())
                preserved()
                api("/api/v1/plugins/agentic-sdlc:remove", "POST", {})
                ids = {row["id"] for row in api("/api/v1/plugins")["plugins"]}
                self.assertNotIn("agentic-sdlc", ids)
                self.assertIn("unrelated-sentinel", ids)
                self.assertEqual(installed.read_bytes(), marker.read_bytes(), "managed copy must survive remove")
                preserved()
                api("/api/v1/shutdown", "POST", {})
                process.wait(timeout=10)
                self.assertEqual(process.returncode, 0)
            finally:
                token = None
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

    def test_grok_local_and_file_git_lifecycle_preserves_other_settings(self):
        executable, git = shutil.which("grok"), shutil.which("git")
        if not executable or not git:
            self.skipTest("Grok CLI/Git unavailable; native lifecycle not verified")
        with tempfile.TemporaryDirectory(prefix="native-grok-") as tmp:
            base = Path(tmp)
            env = isolated_native_env(base, "GROK_HOME")
            profile = Path(env["GROK_HOME"])
            project = base / "empty-project"
            project.mkdir()
            config = profile / "config.toml"
            config.write_bytes(b'[plugins]\ndisabled = ["unused-config-sentinel"]\n')

            def plugin(*args, cwd=project, success=True):
                return self.run_native([executable, "plugin", *args], cwd, env, base, success)

            def installed(name):
                rows = json.loads(plugin("list", "--json").stdout)
                matches = [row for row in rows if row.get("status") == "installed" and row.get("name") == name]
                self.assertEqual(len(matches), 1)
                path = Path(matches[0]["path"])
                self.assertTrue(path.resolve().is_relative_to(profile.resolve()), "native cache escaped isolated profile")
                return path

            other = base / "unrelated-plugin"
            unrelated_native_plugin(other, ".grok-plugin")
            plugin("install", str(other), "--trust")

            def preserved():
                settings = tomllib.loads(config.read_text(encoding="utf-8"))
                self.assertIn("unused-config-sentinel", settings["plugins"]["disabled"])
                self.assertEqual((installed("unrelated-sentinel") / "sentinel.txt").read_bytes(), b"keep unrelated plugin\n")

            local = base / "local source \u00e7\u0131\u011f $ ` & # % '"
            copy_native_package(local, env)
            marker = local / "lifecycle-marker.txt"
            marker.write_bytes(b"local initial\n")
            plugin("validate", str(local))  # Native validator requires a directory.
            rejected = plugin("install", str(local), "--trust", success=False)
            self.assertNotEqual(rejected.returncode, 0, "native #subdir grammar must be accounted for")
            plugin("install", ".", "--trust", cwd=local)
            cached = installed("agentic-sdlc")
            self.assertEqual((cached / marker.name).read_bytes(), marker.read_bytes())
            marker.write_bytes(b"local changed\n")
            plugin("update", "agentic-sdlc")
            self.assertNotEqual((cached / marker.name).read_bytes(), marker.read_bytes(), "local update is not recopy")
            repeated = plugin("install", ".", "--trust", cwd=local, success=False)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertIn("already", (repeated.stdout + repeated.stderr).lower())
            plugin("uninstall", "agentic-sdlc", "--confirm")
            self.assertFalse(cached.exists())
            preserved()
            source = base / "Git-source"
            copy_native_package(source, env)
            marker = source / "lifecycle-marker.txt"
            marker.write_bytes(b"Git initial\n")  # Match the shipped LF checkout policy.

            def fixture_git(*args):
                return self.run_native([git, "-c", "core.fsmonitor=false", "-c", "commit.gpgsign=false",
                                        "-c", "user.name=Native Fixture", "-c", "user.email=fixture@example.invalid", *args],
                                       source, env, base)

            fixture_git("init", "--initial-branch=main")
            fixture_git("add", ".")
            fixture_git("commit", "-m", "Initial native fixture")
            first = fixture_git("rev-parse", "HEAD").stdout.strip()
            plugin("install", source.as_uri() + "@main", "--trust")
            cached = installed("agentic-sdlc")
            self.assertEqual((cached / marker.name).read_bytes(), marker.read_bytes())
            for name in (".grok-plugin/plugin.json", "hooks/hooks-grok.json", "skills/using-agentic-sdlc/SKILL.md"):
                # Git applies .gitattributes, so compare with the committed fixture blob.
                self.assertEqual((cached / name).read_bytes(), fixture_git("show", "HEAD:" + name).stdout.encode("utf-8"))
            preserved()
            marker.write_bytes(b"Git refreshed\n")
            fixture_git("add", marker.name)
            fixture_git("commit", "-m", "Refresh native fixture")
            second = fixture_git("rev-parse", "HEAD").stdout.strip()
            self.assertNotEqual(first, second)
            self.assertNotEqual((cached / marker.name).read_bytes(), marker.read_bytes())
            plugin("update", "agentic-sdlc")
            self.assertEqual((cached / marker.name).read_bytes(), marker.read_bytes())
            actual = self.run_native([git, "-c", "core.fsmonitor=false", "-C", str(cached), "rev-parse", "HEAD"],
                                     project, env, base).stdout.strip()
            self.assertEqual(actual, second)
            preserved()
            plugin("uninstall", "agentic-sdlc", "--confirm")
            self.assertFalse(cached.exists())
            self.assertFalse(any(row.get("name") == "agentic-sdlc" for row in json.loads(plugin("list", "--json").stdout)))
            preserved()
            self.assertFalse((profile / "sessions").exists())


if __name__ == "__main__":
    unittest.main()
