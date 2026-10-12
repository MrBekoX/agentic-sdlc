"""The flow hooks must tell "no Python here" apart from "the artifact failed validation".

`hooks/flow-evidence.mjs` re-validates a saved spec/plan by running `scripts/validate_artifacts.py`.
Its contract (docs/data-handling.md) is to FAIL OPEN when no interpreter can run. On Windows the
Microsoft Store alias `python3.exe`/`python.exe` is on PATH by default and exits 9009 without
running anything; a `py` launcher can point at an uninstalled Python; `python` can be Python 2.
Each of those returned a non-zero status that the engine read as "validation failed", so a valid
spec was reported missing on every Stop, and a gate under AGENTIC_FLOW_GATE_BLOCK could never be
satisfied on a machine without a real Python 3.

The fakes below reproduce those interpreters on an isolated PATH that holds no real Python.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
ENGINE = (REPO / "hooks" / "flow-evidence.mjs").as_uri()

VALID_SPEC = """---
work_id: interp
status: reviewed
---

# Interpreter spec

## Problem
The flow hook must fail open when no Python 3 interpreter exists.

## Business rules
- BR1 — A stub interpreter is not an interpreter.

## Acceptance criteria
- AC1 — Given only stub interpreters, when the step is evaluated, then it returns satisfied.

## Edge cases
- The Microsoft Store alias, a launcher without an installed Python, and Python 2.

## Definition of done
- Every interpreter case is covered by a test that was seen failing first.

## Must-not-change
- The validator command line and its exit-code meaning stay unchanged.
"""

# Evaluates ONE artifact evidence item through the real exported engine API.
DRIVER = """
import { loadRequirements, stepSatisfied } from %s;
const step = { evidence: [ { kind: 'artifact', role: 'spec', validate: { mode: 'spec', strict: true } } ] };
const trace = { edits: [], commands: [], tools: [] };
const ok = stepSatisfied(step, trace, { cwd: process.argv[1], req: loadRequirements(), validate: true, sessionScoped: false });
process.stdout.write(JSON.stringify({ ok }));
"""


def _fake(bindir, name, body):
    if os.name == "nt":
        path = bindir / (name + ".cmd")
        path.write_text("@echo off\r\n" + body["cmd"] + "\r\n", encoding="utf-8")
    else:
        path = bindir / name
        path.write_text("#!/bin/sh\n" + body["sh"] + "\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


STORE_ALIAS = {"sh": "echo 'Python was not found; run without arguments to install from the Microsoft Store' >&2; exit 9009",
               "cmd": "echo Python was not found 1>&2\r\nexit /b 9009"}
PYTHON2 = {"sh": "echo 2; exit 0", "cmd": "echo 2\r\nexit /b 0"}


RESOLVER = """
import { programOnAbsolutePath } from %s;
process.stdout.write(JSON.stringify({ found: programOnAbsolutePath(process.argv[1]) }));
"""
GIT_EXEC = (REPO / "hooks" / "git-exec.mjs").as_uri()


def _empty_executable(path):
    path.write_bytes(b"")
    if os.name != "nt":
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


@unittest.skipIf(NODE is None, "node not available")
class TestInterpreterResolution(unittest.TestCase):
    """The resolver itself, testable on every OS (the fake interpreters below are POSIX-only)."""

    def _resolve(self, name, path_entries, cwd):
        env = {k: v for k, v in os.environ.items() if k.upper() != "PATH"}
        env["PATH"] = os.pathsep.join(path_entries)
        proc = subprocess.run([NODE, "--input-type=module", "-e", RESOLVER % json.dumps(GIT_EXEC), name],
                              capture_output=True, text=True, encoding="utf-8", env=env, cwd=cwd, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["found"]

    def test_a_relative_path_entry_never_reaches_the_project_directory(self):
        exe = "python3.exe" if os.name == "nt" else "python3"
        with tempfile.TemporaryDirectory() as project:
            _empty_executable(Path(project, exe))
            self.assertIsNone(self._resolve("python3", [".", str(Path(NODE).parent)], project))
            # Control: the same file on an ABSOLUTE PATH entry is found.
            with tempfile.TemporaryDirectory() as bindir:
                _empty_executable(Path(bindir, exe))
                found = self._resolve("python3", [bindir], project)
                self.assertEqual(Path(found).resolve(), Path(bindir, exe).resolve())

    def test_a_name_with_a_directory_part_is_not_resolved_relatively(self):
        with tempfile.TemporaryDirectory() as project:
            self.assertIsNone(self._resolve("scripts/python3", [project], project))


@unittest.skipIf(NODE is None, "node not available")
@unittest.skipIf(os.name == "nt", "Node cannot start the .cmd fake interpreters; the resolver tests "
                                  "above cover Windows")
class TestFlowValidatorInterpreter(unittest.TestCase):
    def _project(self, spec_text):
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)
        specs = td / "docs" / "agentic-sdlc" / "specs"
        specs.mkdir(parents=True)
        (specs / "interp.md").write_text(spec_text, encoding="utf-8")
        return td

    def _evaluate(self, project, path_dirs, extra_env=None, cwd=None):
        env = {k: v for k, v in os.environ.items() if k.upper() not in ("PATH", "AGENTIC_SDLC_PYTHON")}
        env["PATH"] = os.pathsep.join(str(d) for d in path_dirs)
        env.update(extra_env or {})
        proc = subprocess.run([NODE, "--input-type=module", "-e", DRIVER % json.dumps(ENGINE), str(project)],
                              capture_output=True, text=True, encoding="utf-8", env=env, timeout=120,
                              cwd=cwd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["ok"]

    def _bin(self, **fakes):
        bindir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, bindir, ignore_errors=True)
        for name, body in fakes.items():
            _fake(bindir, name, body)
        return bindir

    def test_store_alias_interpreters_fail_open(self):
        bindir = self._bin(python3=STORE_ALIAS, python=STORE_ALIAS, py=STORE_ALIAS)
        project = self._project(VALID_SPEC)
        self.assertTrue(self._evaluate(project, [bindir, Path(NODE).parent]),
                        "a Store-alias interpreter was read as a failed validation")

    def test_python2_is_not_used_as_the_validator_interpreter(self):
        bindir = self._bin(python3=STORE_ALIAS, python=PYTHON2, py=STORE_ALIAS)
        project = self._project(VALID_SPEC)
        self.assertTrue(self._evaluate(project, [bindir, Path(NODE).parent]))

    def test_configured_stub_falls_through_to_fail_open(self):
        bindir = self._bin(python3=STORE_ALIAS, python=STORE_ALIAS)
        stub = _fake(bindir, "stubpython", STORE_ALIAS)
        project = self._project(VALID_SPEC)
        self.assertTrue(self._evaluate(project, [bindir, Path(NODE).parent],
                                       {"AGENTIC_SDLC_PYTHON": str(stub)}))

    def test_an_interpreter_planted_in_the_project_is_never_run(self):
        # The hook runs inside the user's project. Spawning a bare `python3` lets Windows search the
        # working directory first, and a relative PATH entry (`.`) does the same on every OS, so a
        # repository could ship its own `python3` and have the hook execute it.
        project = self._project(VALID_SPEC)
        marker = project / "planted-ran"
        planted = {"sh": "touch '%s'; echo 1; exit 0" % marker,
                   "cmd": "type nul > \"%s\"\r\necho 1\r\nexit /b 0" % marker}
        _fake(project, "python3", planted)
        _fake(project, "python", planted)
        env_path = [Path("."), Path(NODE).parent]
        self.assertTrue(self._evaluate(project, env_path, cwd=project))
        self.assertFalse(marker.exists(), "an interpreter planted in the project directory was executed")

    def test_a_real_python3_still_decides_the_verdict(self):
        # Control: fail-open must not swallow a REAL failed validation.
        real = Path(sys.executable)
        for spec_text, expected in ((VALID_SPEC, True), ("spec\n", False)):
            with self.subTest(expected=expected):
                project = self._project(spec_text)
                self.assertEqual(
                    self._evaluate(project, [Path(NODE).parent], {"AGENTIC_SDLC_PYTHON": str(real)}),
                    expected)


if __name__ == "__main__":
    unittest.main()
