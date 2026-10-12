"""User-facing helpers must not depend on the user's editor or console encoding.

The skills tell the model to run `validate_artifacts.py`, `resolve_work_package.py` and
`detect_context.py` in the user's own project, on whatever OS and shell that user has.

* Windows PowerShell 5.1 `Set-Content -Encoding utf8` (and several Windows editors) write a UTF-8
  byte-order mark. A BOM before `---` hid the frontmatter, so a valid spec failed validation, a
  valid plan was rejected by the resolver, and a BOM-prefixed package.json read as "no
  dependencies" - which silently skipped the docs-lookup step.
* A console or pipe whose code page is cp1252 (the Windows default in many locales) cannot encode
  a Turkish branch name or a CJK folder. `print` raised UnicodeEncodeError and the helper exited 1,
  breaking `detect_context.py`'s "always exit 0" contract and turning a resolvable work package
  into a crash.

Each case pairs the hostile input with its clean twin, so a check that always passes fails here.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "scripts" / "validate_artifacts.py"
RESOLVER = REPO / "scripts" / "resolve_work_package.py"
DETECT = REPO / "scripts" / "detect_context.py"
BOM = "﻿"

SPEC = """---
work_id: enc
status: reviewed
---

# Encoding spec

## Problem
Helpers must read files written by any editor and print to any console.

## Business rules
- BR1 — A byte-order mark never changes a verdict.

## Acceptance criteria
- AC1 — Given a BOM-prefixed spec, when validated, then the verdict equals the BOM-less verdict.

## Edge cases
- A cp1252 console.

## Definition of done
- Tests pass.

## Must-not-change
- The validator's CLI flags.
"""


def run(script, *args, env_extra=None, cwd=None):
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env.update(env_extra or {})
    proc = subprocess.run([sys.executable, str(script), *args], capture_output=True, cwd=cwd,
                          env=env)
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


def write_package(root, *, bom, branch="feature/enc", plan_name="enc"):
    specs = root / "docs" / "agentic-sdlc" / "specs"
    plans = root / "docs" / "agentic-sdlc" / "plans"
    specs.mkdir(parents=True, exist_ok=True)
    plans.mkdir(parents=True, exist_ok=True)
    prefix = BOM if bom else ""
    (specs / f"{plan_name}.md").write_text(prefix + "---\nwork_id: enc\nstatus: reviewed\n---\n\n# s\n",
                                           encoding="utf-8")
    plan = plans / f"{plan_name}.md"
    plan.write_text(prefix + f"---\nwork_id: enc\nspec: ../specs/{plan_name}.md\nbranch: {branch}\n"
                    "status: in_progress\n---\n\n# p\n", encoding="utf-8")
    return plan


class TestByteOrderMark(unittest.TestCase):
    def test_validator_verdict_ignores_a_bom(self):
        with tempfile.TemporaryDirectory() as td:
            clean, marked = Path(td, "clean.md"), Path(td, "bom.md")
            clean.write_text(SPEC, encoding="utf-8")
            marked.write_text(BOM + SPEC, encoding="utf-8")
            rc_clean, out_clean, _ = run(VALIDATOR, "--mode", "spec", "--file", str(clean))
            rc_bom, out_bom, err = run(VALIDATOR, "--mode", "spec", "--file", str(marked))
            self.assertEqual(rc_clean, 0, out_clean)
            self.assertEqual((rc_bom, out_bom), (rc_clean, out_clean), err)

    def test_resolver_reads_a_bom_prefixed_plan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_package(root, bom=True)
            rc, out, err = run(RESOLVER, "--repo", str(root), "--branch", "feature/enc")
            self.assertEqual(rc, 0, out + err)
            self.assertNotIn("missing_frontmatter", out)
            self.assertIn("plans/enc.md", out.replace("\\", "/"))

    def test_dependency_probe_reads_a_bom_prefixed_manifest(self):
        for bom in (False, True):
            with self.subTest(bom=bom), tempfile.TemporaryDirectory() as td:
                Path(td, "package.json").write_text(
                    (BOM if bom else "") + '{"name": "x", "dependencies": {"react": "^18.0.0"}}',
                    encoding="utf-8")
                rc, out, err = run(DETECT, "--path", td, "--probe", "deps")
                self.assertEqual(rc, 0, err)
                self.assertNotIn("deps_probe=stdlib_only", out)


class TestLegacyConsoleEncoding(unittest.TestCase):
    CP1252 = {"PYTHONIOENCODING": "cp1252"}

    def test_resolver_prints_a_non_ascii_branch_without_crashing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_package(root, bom=False, branch="feature/çalışma")
            rc, out, err = run(RESOLVER, "--repo", str(root), "--branch", "feature/çalışma",
                               env_extra=self.CP1252)
            self.assertNotIn("UnicodeEncodeError", err)
            self.assertEqual(rc, 0, out + err)

    def test_detector_prints_a_non_ascii_manifest_name_with_exit_zero(self):
        # The dependency probe prints the names of top-level `*.csproj` manifests; a Turkish or CJK
        # project name is not encodable in cp1252, and `print` used to raise before exit 0.
        with tempfile.TemporaryDirectory() as td:
            Path(td, "Proje_ğ目录.csproj").write_text(
                '<Project><ItemGroup><PackageReference Include="Serilog" Version="3.0.0" />'
                "</ItemGroup></Project>", encoding="utf-8")
            rc, out, err = run(DETECT, "--path", td, "--probe", "deps", env_extra=self.CP1252)
            self.assertNotIn("UnicodeEncodeError", err)
            self.assertEqual(rc, 0, err)
            self.assertIn("manifests=Proje_ğ目录.csproj", out)

    def test_validator_reports_a_non_ascii_value_on_a_legacy_console(self):
        # The validator echoes an unknown frontmatter status; `hazır` is not encodable in cp1252.
        # The verdict (exit 1, invalid_status) must survive instead of a UnicodeEncodeError crash.
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td, "spec.md")
            spec.write_text(SPEC.replace("status: reviewed", "status: hazır"), encoding="utf-8")
            rc, out, err = run(VALIDATOR, "--mode", "spec", "--file", str(spec), env_extra=self.CP1252)
            self.assertNotIn("UnicodeEncodeError", err)
            self.assertEqual(rc, 1, out + err)
            self.assertIn("error=invalid_status:hazır", out)


if __name__ == "__main__":
    unittest.main()
