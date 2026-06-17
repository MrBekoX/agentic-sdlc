"""Tests for detect_context.py — deterministic dev-flow context probe.

Each behavior is asserted BOTH in-process (call the functions directly) AND via
the subprocess CLI (exit code + exact key=value substrings). Stdlib `unittest`
only — runnable with `python -m unittest`.

The script lives at ../scripts/detect_context.py relative to this file.
We import it by path so the test suite stays independent of cwd / sys.path setup.
"""

import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "detect_context.py"


def _load_module():
    """Load detect_context.py by path so tests don't depend on cwd."""
    spec = importlib.util.spec_from_file_location("detect_context", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dc = _load_module()


def run_cli(*args):
    """Run the context detector via subprocess; return (returncode, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# Core detection tests (Step 3 — no --probe)
# ---------------------------------------------------------------------------

class TestDefaultModeEmptyDir(unittest.TestCase):
    """Case 1: empty directory => greenfield / greenfield_inline."""

    def test_empty_dir_inprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = dc.detect([tmp])
            self.assertEqual(result["context_detection"], "greenfield")
            self.assertEqual(result["source_files"], 0)
            self.assertEqual(result["layers"], [])
            self.assertEqual(result["explore_mode"], "greenfield_inline")

    def test_empty_dir_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--path", tmp)
            self.assertEqual(rc, 0, err)
            self.assertIn("context_detection=greenfield", out)
            self.assertIn("source_files=0", out)
            self.assertIn("layers=", out)
            self.assertIn("explore_mode=greenfield_inline", out)

    def test_output_lines_are_sorted_key_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--path", tmp)
            self.assertEqual(rc, 0, err)
            lines = [ln for ln in out.splitlines() if ln]
            self.assertEqual(lines, sorted(lines))
            for ln in lines:
                self.assertIn("=", ln)


class TestSingleSourceFile(unittest.TestCase):
    """Case 2: one source file at root => brownfield, explore_mode=single."""

    def test_one_py_file_inprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.py").write_text("x = 1\n", encoding="utf-8")
            result = dc.detect([tmp])
            self.assertEqual(result["context_detection"], "brownfield")
            self.assertEqual(result["source_files"], 1)
            self.assertEqual(result["explore_mode"], "single")

    def test_one_py_file_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.py").write_text("x = 1\n", encoding="utf-8")
            rc, out, err = run_cli("--path", tmp)
            self.assertEqual(rc, 0, err)
            self.assertIn("context_detection=brownfield", out)
            self.assertIn("source_files=1", out)
            self.assertIn("explore_mode=single", out)


class TestSingleLayerDir(unittest.TestCase):
    """Case 3: one layer dir (src/) with a .py => explore_mode=single (1 layer < 2)."""

    def test_single_layer_is_single_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            (src / "main.py").write_text("pass\n", encoding="utf-8")
            result = dc.detect([tmp])
            self.assertEqual(result["context_detection"], "brownfield")
            self.assertEqual(result["source_files"], 1)
            self.assertEqual(result["explore_mode"], "single")

    def test_single_layer_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            (src / "main.py").write_text("pass\n", encoding="utf-8")
            rc, out, err = run_cli("--path", tmp)
            self.assertEqual(rc, 0, err)
            self.assertIn("source_files=1", out)
            self.assertIn("explore_mode=single", out)


class TestMultipleLayers(unittest.TestCase):
    """Case 4: >=2 layer dirs => explore_mode=parallel."""

    def _make_fixture(self, tmp):
        for layer in ("api", "ui", "db"):
            d = Path(tmp) / layer
            d.mkdir()
            (d / "index.py").write_text("pass\n", encoding="utf-8")

    def test_parallel_mode_inprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_fixture(tmp)
            result = dc.detect([tmp])
            self.assertEqual(result["explore_mode"], "parallel")
            self.assertEqual(sorted(result["layers"]), ["api", "db", "ui"])
            self.assertEqual(result["source_files"], 3)

    def test_parallel_mode_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_fixture(tmp)
            rc, out, err = run_cli("--path", tmp)
            self.assertEqual(rc, 0, err)
            self.assertIn("explore_mode=parallel", out)
            self.assertIn("layers=api,db,ui", out)
            self.assertIn("source_files=3", out)


class TestIgnoreDirectories(unittest.TestCase):
    """Case 5: IGNORE dirs (node_modules, .git) are excluded from count and layers."""

    def test_ignore_dirs_not_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            # one real source file
            (Path(tmp) / "app.py").write_text("pass\n", encoding="utf-8")
            # ignored dirs with source files inside
            nm = Path(tmp) / "node_modules"
            nm.mkdir()
            (nm / "lib.js").write_text("module.exports={}\n", encoding="utf-8")
            git = Path(tmp) / ".git"
            git.mkdir()
            (git / "x.py").write_text("pass\n", encoding="utf-8")
            result = dc.detect([tmp])
            self.assertEqual(result["source_files"], 1)
            # node_modules must NOT appear as a layer
            self.assertNotIn("node_modules", result["layers"])

    def test_ignore_dirs_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "app.py").write_text("pass\n", encoding="utf-8")
            nm = Path(tmp) / "node_modules"
            nm.mkdir()
            (nm / "lib.js").write_text("x\n", encoding="utf-8")
            rc, out, err = run_cli("--path", tmp)
            self.assertEqual(rc, 0, err)
            self.assertIn("source_files=1", out)


class TestNonExistentPath(unittest.TestCase):
    """Case 6: non-existent path => greenfield + greenfield_inline, exit 0."""

    def test_nonexistent_inprocess(self):
        result = dc.detect(["/nonexistent/path/xyz"])
        self.assertEqual(result["context_detection"], "greenfield")
        self.assertEqual(result["source_files"], 0)
        self.assertEqual(result["explore_mode"], "greenfield_inline")

    def test_nonexistent_cli(self):
        rc, out, err = run_cli("--path", "/nonexistent/path/xyz")
        self.assertEqual(rc, 0, err)
        self.assertIn("context_detection=greenfield", out)
        self.assertIn("explore_mode=greenfield_inline", out)


# ---------------------------------------------------------------------------
# --probe deps tests (Step 6)
# ---------------------------------------------------------------------------

class TestProbeDeps(unittest.TestCase):
    def _write(self, tmp, name, content):
        p = Path(tmp) / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_package_json_with_deps_external(self):
        """Case 7: package.json with non-empty dependencies => external."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "package.json", '{"dependencies":{"left-pad":"^1"}}')
            result = dc.probe_deps([tmp])
            self.assertEqual(result["deps_probe"], "external")
            self.assertIn("package.json", result["manifests"])

    def test_package_json_with_deps_external_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "package.json", '{"dependencies":{"left-pad":"^1"}}')
            rc, out, err = run_cli("--path", tmp, "--probe", "deps")
            self.assertEqual(rc, 0, err)
            self.assertIn("deps_probe=external", out)
            self.assertIn("package.json", out)

    def test_package_json_empty_deps_stdlib_only(self):
        """Case 8: package.json with empty dependencies => stdlib_only."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "package.json", '{"dependencies":{},"devDependencies":{}}')
            result = dc.probe_deps([tmp])
            self.assertEqual(result["deps_probe"], "stdlib_only")

    def test_requirements_txt_external(self):
        """Case 9: requirements.txt with package => external."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "requirements.txt", "requests==2.31.0\n")
            result = dc.probe_deps([tmp])
            self.assertEqual(result["deps_probe"], "external")
            self.assertIn("requirements.txt", result["manifests"])

    def test_requirements_txt_external_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "requirements.txt", "requests==2.31.0\n")
            rc, out, err = run_cli("--path", tmp, "--probe", "deps")
            self.assertEqual(rc, 0, err)
            self.assertIn("deps_probe=external", out)

    def test_no_manifest_stdlib_only(self):
        """Case 10: dir with only a .py file, no manifest => stdlib_only."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "app.py", "import os\n")
            result = dc.probe_deps([tmp])
            self.assertEqual(result["deps_probe"], "stdlib_only")
            self.assertEqual(result["manifests"], [])

    def test_no_manifest_stdlib_only_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "app.py", "import os\n")
            rc, out, err = run_cli("--path", tmp, "--probe", "deps")
            self.assertEqual(rc, 0, err)
            self.assertIn("deps_probe=stdlib_only", out)

    def test_probe_deps_sorted_output_cli(self):
        """Output lines from --probe deps must be sorted key=value."""
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--path", tmp, "--probe", "deps")
            self.assertEqual(rc, 0, err)
            lines = [ln for ln in out.splitlines() if ln]
            self.assertEqual(lines, sorted(lines))


# ---------------------------------------------------------------------------
# --probe toolchain tests (Step 15)
# ---------------------------------------------------------------------------

class TestProbeToolchain(unittest.TestCase):
    def _write(self, tmp, name, content):
        p = Path(tmp) / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_package_json_with_scripts_node(self):
        """Case 11: package.json with build script => present, node."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "package.json", '{"scripts":{"build":"tsc"}}')
            result = dc.probe_toolchain([tmp])
            self.assertEqual(result["toolchain_probe"], "present")
            self.assertIn("node", result["toolchains"])

    def test_package_json_with_scripts_node_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "package.json", '{"scripts":{"build":"tsc"}}')
            rc, out, err = run_cli("--path", tmp, "--probe", "toolchain")
            self.assertEqual(rc, 0, err)
            self.assertIn("toolchain_probe=present", out)
            self.assertIn("node", out)

    def test_bare_js_file_no_toolchain(self):
        """Case 12: only a bare .js file, no manifest/config => absent."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "index.js", "console.log('hi');\n")
            result = dc.probe_toolchain([tmp])
            self.assertEqual(result["toolchain_probe"], "absent")
            self.assertEqual(result["toolchains"], [])

    def test_bare_js_file_no_toolchain_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "index.js", "console.log('hi');\n")
            rc, out, err = run_cli("--path", tmp, "--probe", "toolchain")
            self.assertEqual(rc, 0, err)
            self.assertIn("toolchain_probe=absent", out)

    def test_pyproject_toml_python_toolchain(self):
        """Case 13: pyproject.toml present => present, python."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "pyproject.toml", "[tool.ruff]\nline-length = 88\n")
            result = dc.probe_toolchain([tmp])
            self.assertEqual(result["toolchain_probe"], "present")
            self.assertIn("python", result["toolchains"])

    def test_pyproject_toml_python_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "pyproject.toml", "[tool.ruff]\nline-length = 88\n")
            rc, out, err = run_cli("--path", tmp, "--probe", "toolchain")
            self.assertEqual(rc, 0, err)
            self.assertIn("toolchain_probe=present", out)
            self.assertIn("python", out)

    def test_probe_toolchain_sorted_output_cli(self):
        """Output lines from --probe toolchain must be sorted key=value."""
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--path", tmp, "--probe", "toolchain")
            self.assertEqual(rc, 0, err)
            lines = [ln for ln in out.splitlines() if ln]
            self.assertEqual(lines, sorted(lines))

    def test_exit_always_zero_probe_toolchain(self):
        """detect_context.py always exits 0 — it is a classifier, not a gate."""
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run_cli("--path", tmp, "--probe", "toolchain")
            self.assertEqual(rc, 0, err)


# ---------------------------------------------------------------------------
# Exit-0 invariant under a hostile path (regression guard for H1)
# ---------------------------------------------------------------------------

class TestExitZeroInvariant(unittest.TestCase):
    """The "exit 0 ALWAYS" classifier contract must hold even when traversal/read
    hits an OSError (unreadable subtree, symlink loop, a file locked by another
    process — common on Windows). A crash here would block the very Step 3 this
    script is meant to inform. These tests would have caught H1."""

    def _run_main_capture(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = dc.main(argv)
        return rc, buf.getvalue()

    def test_detect_oserror_exits_zero_with_visible_default(self):
        # An OSError escaping the per-item guards must NOT crash: main() degrades to a
        # visible safe default (detect_error=oserror) and still returns 0.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(dc, "detect", side_effect=OSError("permission denied")):
                rc, out = self._run_main_capture(["--path", tmp])
            self.assertEqual(rc, 0)
            self.assertIn("explore_mode=greenfield_inline", out)
            self.assertIn("detect_error=oserror", out)

    def test_probe_deps_oserror_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(dc, "probe_deps", side_effect=OSError("locked")):
                rc, out = self._run_main_capture(["--path", tmp, "--probe", "deps"])
            self.assertEqual(rc, 0)
            self.assertIn("deps_probe=stdlib_only", out)
            self.assertIn("detect_error=oserror", out)

    def test_unreadable_manifest_survives_partial_no_crash(self):
        # A read-level OSError on the only manifest must not crash probe_deps; the
        # scan tolerates it per-item (proves partial survival, not just the backstop).
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "package.json").write_text('{"dependencies":{"x":"1"}}', encoding="utf-8")
            with mock.patch.object(dc.Path, "read_text", side_effect=OSError("locked")):
                result = dc.probe_deps([tmp])
            self.assertEqual(result["deps_probe"], "stdlib_only")


if __name__ == "__main__":
    unittest.main()
