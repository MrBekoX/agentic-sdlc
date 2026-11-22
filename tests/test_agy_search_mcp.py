"""AC2: the read-only workspace search MCP server bundled in the agy package (`scripts/agy_search_mcp.py`)."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "scripts" / "agy_search_mcp.py"
NEEDLE = "planted-needle-" + "4417"


class Client:
    """A minimal MCP client over the server's stdio; `roots` answers its roots/list request."""

    def __init__(self, *args, roots=None, advertise_roots=True):
        self.proc = subprocess.Popen([sys.executable, str(SERVER), *args], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.roots = roots
        self.next = 100
        caps = {"roots": {"listChanged": True}} if advertise_roots else {}
        # agy 1.5.14 sends `server/discover` before `initialize` (live probe 2026-11-22).
        discover = self.request("server/discover", {})
        assert "error" in discover, discover
        init = self.request("initialize", {"protocolVersion": "2025-11-25", "capabilities": caps,
                                           "clientInfo": {"name": "test", "version": "0"}})
        self.init = init
        self.notify("notifications/initialized", {})

    def send(self, message):
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def notify(self, method, params):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method, params):
        self.next += 1
        wanted = self.next
        self.send({"jsonrpc": "2.0", "id": wanted, "method": method, "params": params})
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise AssertionError("server closed: " + self.proc.stderr.read())
            message = json.loads(line)
            if message.get("method") == "roots/list":
                uris = [Path(r).resolve().as_uri() for r in (self.roots or [])]
                self.send({"jsonrpc": "2.0", "id": message["id"], "result": {"roots": [{"uri": u} for u in uris]}})
                continue
            if message.get("id") == wanted:
                return message

    def call(self, name, arguments):
        reply = self.request("tools/call", {"name": name, "arguments": arguments})
        result = reply["result"]
        return result["isError"], result["content"][0]["text"]

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=20)
        self.proc.stdout.close()
        self.proc.stderr.close()


class SearchServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.ws = base / "workspace"
        self.outside = base / "outside"
        (self.ws / "src" / "deep").mkdir(parents=True)
        (self.ws / ".git").mkdir()
        (self.ws / "node_modules").mkdir()
        self.outside.mkdir()
        (self.ws / "src" / "a.py").write_text(f"x = 1\nvalue = '{NEEDLE}'\n", encoding="utf-8")
        (self.ws / "src" / "deep" / "b.md").write_text(f"# B\n{NEEDLE.upper()}\n", encoding="utf-8")
        (self.ws / "notes.txt").write_text("a.b literal\naxb\n", encoding="utf-8")
        (self.ws / "blob.bin").write_bytes(b"\0" + NEEDLE.encode())
        (self.ws / "huge.txt").write_bytes((NEEDLE + "\n").encode() * (2 * 1024 * 1024 // len(NEEDLE)))
        (self.ws / ".git" / "config").write_text(NEEDLE, encoding="utf-8")
        (self.ws / "node_modules" / "m.js").write_text(NEEDLE, encoding="utf-8")
        (self.outside / "secret.txt").write_text(NEEDLE + " outside\n", encoding="utf-8")
        self.links = True
        try:
            os.symlink(self.outside / "secret.txt", self.ws / "link-out.txt")
            os.symlink(self.outside, self.ws / "dir-out", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.links = False
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.tmp.cleanup()

    def client(self, *args, **kwargs):
        kwargs.setdefault("roots", [self.ws])
        client = Client(*args, **kwargs)
        self.clients.append(client)
        return client

    def test_initialize_and_tools_list_describe_two_read_only_tools(self):
        client = self.client()
        self.assertIn("tools", client.init["result"]["capabilities"])
        self.assertEqual(client.init["result"]["protocolVersion"], "2025-11-25")
        tools = client.request("tools/list", {})["result"]["tools"]
        self.assertEqual(sorted(t["name"] for t in tools), ["glob", "grep"])
        for tool in tools:
            self.assertTrue(tool["annotations"]["readOnlyHint"])
            self.assertEqual(tool["inputSchema"]["required"], ["pattern"])
        self.assertIn("error", client.request("resources/write", {}))

    def test_grep_finds_the_needle_from_the_client_roots_only(self):
        client = self.client()
        error, text = client.call("grep", {"pattern": NEEDLE, "literal": True})
        self.assertFalse(error, text)
        lines = text.splitlines()
        self.assertEqual(lines, [f"{(self.ws / 'src' / 'a.py').resolve()}:2: value = '{NEEDLE}'"])

    def test_grep_regex_ignore_case_and_path_glob(self):
        client = self.client()
        error, text = client.call("grep", {"pattern": r"needle-\d+", "ignore_case": True, "path": "src/**/*.md"})
        self.assertFalse(error, text)
        self.assertEqual(text.splitlines(), [f"{(self.ws / 'src' / 'deep' / 'b.md').resolve()}:2: {NEEDLE.upper()}"])
        error, text = client.call("grep", {"pattern": "a.b", "literal": True})
        self.assertEqual(len(text.splitlines()), 1, text)
        error, text = client.call("grep", {"pattern": "a.b"})
        self.assertEqual(len(text.splitlines()), 2, text)

    def test_binary_huge_git_node_modules_and_links_out_are_skipped(self):
        client = self.client()
        _error, text = client.call("grep", {"pattern": NEEDLE, "literal": True, "ignore_case": True})
        for skipped in ("blob.bin", "huge.txt", ".git", "node_modules", "link-out.txt", "dir-out", "outside"):
            self.assertNotIn(skipped, text)
        _error, listed = client.call("glob", {"pattern": "**/*"})
        self.assertNotIn("link-out.txt", listed)
        self.assertNotIn("secret.txt", listed)
        self.assertIn("blob.bin", listed)

    def test_glob_matches_relative_paths(self):
        client = self.client()
        error, text = client.call("glob", {"pattern": "**/*.py"})
        self.assertFalse(error, text)
        self.assertEqual(text.splitlines(), [str((self.ws / "src" / "a.py").resolve())])
        _error, text = client.call("glob", {"pattern": "*.txt"})
        self.assertEqual(text.splitlines(), [str((self.ws / "huge.txt").resolve()), str((self.ws / "notes.txt").resolve())])

    def test_escaping_and_invalid_arguments_are_refused(self):
        client = self.client()
        for name, args in (
            ("glob", {"pattern": "../outside/*"}),
            ("glob", {"pattern": "/etc/*"}),
            ("grep", {"pattern": NEEDLE, "path": "../**"}),
            ("grep", {"pattern": "("}),
            ("grep", {"pattern": ""}),
            ("grep", {"pattern": "x", "max_results": 0}),
            ("grep", {"pattern": "x", "literal": "yes"}),
            ("grep", {"pattern": "x", "write": True}),
            ("grep", "not an object"),
            ("delete", {"pattern": "x"}),
        ):
            with self.subTest(name=name, args=args):
                error, text = client.call(name, args)
                self.assertTrue(error, text)
                self.assertTrue(text.startswith("error: "), text)

    def test_results_are_bounded(self):
        many = self.ws / "many.txt"
        many.write_text("hit\n" * 2000, encoding="utf-8")
        client = self.client()
        error, text = client.call("grep", {"pattern": "hit", "max_results": 5, "path": "many.txt"})
        self.assertFalse(error, text)
        self.assertEqual(len(text.splitlines()), 6)
        self.assertIn("max_results=5", text.splitlines()[-1])
        _error, text = client.call("grep", {"pattern": "hit", "max_results": 100000, "path": "many.txt"})
        self.assertEqual(len(text.splitlines()), 501)

    def test_catastrophic_regex_is_stopped_by_the_deadline(self):
        (self.ws / "evil.txt").write_text("a" * 40 + "b\n", encoding="utf-8")
        client = self.client("--timeout", "2")
        started = time.monotonic()
        error, text = client.call("grep", {"pattern": "(a+)+$", "path": "evil.txt"})
        self.assertLess(time.monotonic() - started, 15)
        self.assertTrue(error)
        self.assertIn("longer than 2 seconds", text)
        error, text = client.call("glob", {"pattern": "*.py"})
        self.assertFalse(error, text)

    def test_no_root_fails_closed(self):
        client = self.client(roots=[], advertise_roots=False)
        error, text = client.call("glob", {"pattern": "**/*"})
        self.assertTrue(error)
        self.assertIn("no workspace root", text)
        client = self.client(roots=[])
        error, text = client.call("glob", {"pattern": "**/*"})
        self.assertTrue(error)

    def test_a_fixed_root_argument_is_used_without_client_roots(self):
        client = self.client("--root", str(self.ws), roots=[], advertise_roots=False)
        error, text = client.call("grep", {"pattern": NEEDLE, "literal": True})
        self.assertFalse(error, text)
        self.assertIn("a.py:2:", text)

    def test_the_server_never_writes(self):
        before = sorted(str(p) for p in Path(self.tmp.name).rglob("*"))
        client = self.client()
        client.call("grep", {"pattern": NEEDLE})
        client.call("glob", {"pattern": "**"})
        self.assertEqual(sorted(str(p) for p in Path(self.tmp.name).rglob("*")), before)


class PackagedConfigTests(unittest.TestCase):
    def test_mcp_config_starts_this_server_from_the_plugin_root(self):
        config = json.loads((REPO / ".antigravity-plugin" / "mcp_config.json").read_text(encoding="utf-8"))
        self.assertEqual(list(config), ["mcpServers"])
        self.assertEqual(list(config["mcpServers"]), ["search"])
        server = config["mcpServers"]["search"]
        self.assertEqual(set(server), {"command", "args"})
        self.assertEqual(server["command"], "python3")
        self.assertEqual(server["args"], ["${PLUGIN_ROOT}/scripts/agy_search_mcp.py"])


if __name__ == "__main__":
    unittest.main()
