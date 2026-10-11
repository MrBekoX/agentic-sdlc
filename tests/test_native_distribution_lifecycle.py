"""No-model native lifecycle in disposable homes and relocated sources.

Missing CLI support is a skip. These checks prove local copying and configuration
preservation, not trusted hook execution, skill triggering or remote publication.
Kimi/Grok checks require AGENTIC_NATIVE_TRUST_SMOKE=1: installing in disposable
profiles accepts plugin code. Ordinary gates never silently grant that consent.
"""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

from scripts.check_plugin_portability import runtime_members
from scripts.sensitive_redaction import redact_text


REPO = Path(__file__).resolve().parents[1]
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
