import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import scripts.run_procedure_eval as procedure_eval


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

PER_PACKAGE_FIXTURE = (
    REPO / "tests" / "fixtures" / "transcripts"
    / "agentic-sdlc-pipeline-procedure-per-package-pass.jsonl"
)
PER_PACKAGE_CASE_ID = "agentic-sdlc-pipeline-per-package"

# A spec whose every required section clears the strict depth checks (mirrors the
# known-good skill-depth-deep fixture). Reused to prove flat /specs/ classification
# and per-package gate firing without coupling those tests to a fixture file.
DEEP_SPEC = (
    "# Spec\n\n"
    "## Problem\nThe greet function hardcodes the trailing punctuation.\n\n"
    "## Business Rules\nDefault output is unchanged when no suffix is given.\n\n"
    "## Acceptance Criteria\n"
    '- AC1: Given name Ada and no suffix, when greet runs, then it returns "Hello, Ada!".\n'
    '- AC2: Given suffix "?", when greet runs, then it returns "Hello, Ada?".\n\n'
    '## Edge Cases\nEmpty suffix returns "Hello, Ada" with no trailing punctuation.\n\n'
    "## Definition of Done\nTests for AC1 and AC2 pass and default behaviour is preserved.\n\n"
    "## Must-not-change\nThe single-argument call path keeps returning the exclamation mark.\n"
)


class TestProcedureEvalHarness(unittest.TestCase):
    def test_dry_run_validates_dev_flow_fixture(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--dry-run",
            ],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("procedure_eval=dry-run-passed", proc.stdout)

    def test_sample_transcript_passes_dev_flow_coverage(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--transcript",
                "tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-pass.jsonl",
            ],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("procedure_eval=passed", proc.stdout)

    def test_shallow_artifacts_fail_depth_check(self):
        from run_procedure_eval import trace_events, load_json_lines, evaluate_case, load_eval
        cases = load_eval(REPO / "tests" / "skills" / "procedure" / "skill-depth.json")
        shallow = next(c for c in cases if c["id"] == "skill-depth-shallow")
        trace = trace_events(load_json_lines(REPO / "tests" / "fixtures" / "transcripts" / "skill-depth-shallow-artifacts.jsonl"))
        errors = evaluate_case(shallow, trace, REPO)
        assert any(e.startswith("shallow_artifact:") for e in errors), errors

    def test_deep_artifacts_pass_depth_check(self):
        from run_procedure_eval import trace_events, load_json_lines, evaluate_case, load_eval
        cases = load_eval(REPO / "tests" / "skills" / "procedure" / "skill-depth.json")
        deep = next(c for c in cases if c["id"] == "skill-depth-deep")
        trace = trace_events(load_json_lines(REPO / "tests" / "fixtures" / "transcripts" / "skill-depth-deep-artifacts.jsonl"))
        errors = evaluate_case(deep, trace, REPO)
        assert not any(e.startswith("shallow_artifact:") for e in errors), errors

    def test_codex_adapter_transcript_satisfies_non_claude_spec_plan_gate(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--transcript",
                "tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-codex-adapter-pass.jsonl",
            ],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("procedure_eval=passed", proc.stdout)

    def test_current_codex_exec_transcript_shape_satisfies_adapter_gates(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--transcript",
                "tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-codex-exec-current.jsonl",
            ],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("procedure_eval=passed", proc.stdout)
        self.assertNotIn("_tools=0", proc.stdout)

    def test_load_json_lines_accepts_utf16_codex_transcript(self):
        with tempfile.TemporaryDirectory() as td:
            transcript = Path(td) / "codex.jsonl"
            transcript.write_text(
                '{"type":"item.completed","item":{"type":"agent_message","text":"Runtime: Codex"}}\n',
                encoding="utf-16",
            )

            events = procedure_eval.load_json_lines(transcript)

        self.assertEqual(len(events), 1)
        trace = procedure_eval.trace_events(events)
        self.assertIn("Runtime: Codex", trace.text)

    def test_runtime_error_transcript_fails_even_with_required_calls(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--transcript",
                "tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-runtime-error.jsonl",
            ],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("runtime_error:error_max_budget_usd", proc.stdout)
        self.assertIn("procedure_eval=failed", proc.stdout)

    def test_permission_denial_transcript_fails_even_with_required_calls(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--transcript",
                "tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-permission-denied.jsonl",
            ],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("permission_denied:Bash", proc.stdout)
        self.assertIn("procedure_eval=failed", proc.stdout)

    def test_agent_dispatch_satisfies_mapped_gate_skill(self):
        # A gate delegated to its specialist agent counts as satisfied (delegation path).
        trace = procedure_eval.Trace()
        procedure_eval._record_tool(
            trace, "Agent", {"subagent_type": "agentic-sdlc:security-reviewer", "description": "review the diff"}
        )
        procedure_eval._record_tool(
            trace, "Agent", {"subagent_type": "agentic-sdlc:implementation-auditor", "description": "audit flow"}
        )
        self.assertTrue(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:security-audit"))
        self.assertTrue(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:implementasyon-control"))

    def test_unmapped_gate_skill_not_satisfied_by_agent(self):
        # A skill with no agent equivalent still requires an actual Skill call.
        trace = procedure_eval.Trace()
        procedure_eval._record_tool(trace, "Agent", {"subagent_type": "agentic-sdlc:security-reviewer"})
        self.assertFalse(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:completion-claim-gate"))
        # And the direct Skill call still satisfies it.
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:completion-claim-gate"})
        self.assertTrue(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:completion-claim-gate"))

    def test_dispatch_strategy_satisfied_by_delegation(self):
        # Dispatching a sub-agent IS the mechanism decision dispatch-strategy makes.
        trace = procedure_eval.Trace()
        procedure_eval._record_tool(trace, "Agent", {"subagent_type": "Explore", "description": "scan"})
        self.assertTrue(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:dispatch-strategy"))

    def test_dispatch_strategy_not_satisfied_without_delegation(self):
        # All-inline work with no dispatch and no Skill call still fails the gate.
        trace = procedure_eval.Trace()
        procedure_eval._record_tool(trace, "Read", {"file_path": "greeting.py"})
        procedure_eval._record_tool(trace, "Workflow", {"name": "agentic-sdlc:spec-plan-draft"})
        self.assertFalse(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:dispatch-strategy"))
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:dispatch-strategy"})
        self.assertTrue(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:dispatch-strategy"))

    def test_pipeline_case_fails_when_relevant_core_workflow_skill_is_missing(self):
        case = procedure_eval.load_eval(REPO / "tests/skills/procedure/agentic-sdlc-pipeline.json")[0]
        trace = procedure_eval.Trace()
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:dispatch-strategy"})
        procedure_eval._record_tool(trace, "Workflow", {"name": "agentic-sdlc:spec-plan-draft"})
        procedure_eval._record_tool(
            trace,
            "shell_command",
            {"command": "python ${PLUGIN_ROOT}/scripts/detect_context.py --path ."},
        )
        procedure_eval._record_tool(trace, "write_file", {"file_path": "docs/agentic-sdlc/specs/greeting-suffix.md"})
        procedure_eval._record_tool(
            trace,
            "shell_command",
            {"command": "python ${PLUGIN_ROOT}/scripts/validate_artifacts.py --mode spec --file docs/agentic-sdlc/specs/greeting-suffix.md"},
        )
        procedure_eval._record_tool(trace, "write_file", {"file_path": "docs/agentic-sdlc/plans/greeting-suffix.md"})
        procedure_eval._record_tool(
            trace,
            "shell_command",
            {"command": "python ${PLUGIN_ROOT}/scripts/validate_artifacts.py --mode plan --file docs/agentic-sdlc/plans/greeting-suffix.md --spec docs/agentic-sdlc/specs/greeting-suffix.md --strict"},
        )
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:security-audit"})
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:implementasyon-control"})
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:completion-claim-gate"})

        errors = procedure_eval.evaluate_case(case, trace, REPO)

        self.assertIn("missing_skill:agentic-sdlc:feature-build", errors)
        self.assertNotIn("missing_skill:agentic-sdlc:security-audit", errors)
        self.assertNotIn("missing_workflow:agentic-sdlc:spec-plan-draft", errors)

    def test_live_fixture_has_baseline_commit_before_claude_runs(self):
        case = {
            "id": "agentic-sdlc-pipeline-feature-no-commit",
            "fixture_dir": "tests/fixtures/agentic-sdlc-pipeline-basic",
        }
        with tempfile.TemporaryDirectory() as td:
            cwd = procedure_eval.copy_fixture(case, Path(td))
            proc = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True, encoding="utf-8",
            )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    # --- T10: per-package (singular /spec/, /plan/ segment) recognition ---

    def test_recognizes_per_package_depth_and_artifacts(self):
        # AC16: the per-package fixture passes the offline gate (both cases green),
        # and its singular /spec/, /plan/ writes are recognized AND content-validated.
        from run_procedure_eval import (
            per_package_layout,
            evaluate_artifact_depth,
            trace_events,
            load_json_lines,
            Trace,
            _record_tool,
        )

        # Path classification: singular segment -> (mode, slug, work_id).
        self.assertEqual(
            per_package_layout("docs/agentic-sdlc/work-x/spec/work-x.md"),
            ("spec", "work-x", "work-x"),
        )
        self.assertEqual(
            per_package_layout("docs/agentic-sdlc/work-x/plan/work-x.md"),
            ("plan", "work-x", "work-x"),
        )

        # The deep per-package spec+plan content clears strict depth validation,
        # and the per-package plan is paired with its same-slug spec (no shallow).
        trace = trace_events(load_json_lines(PER_PACKAGE_FIXTURE))
        depth_errors = evaluate_artifact_depth(trace, REPO)
        self.assertEqual(
            [e for e in depth_errors if e.startswith("shallow_artifact:")],
            [],
            depth_errors,
        )

        # The gate actually FIRES on per-package paths: a shallow per-package spec
        # is flagged (proving recognition, not a silent skip).
        shallow = Trace()
        _record_tool(
            shallow,
            "Write",
            {"file_path": "docs/agentic-sdlc/work-x/spec/work-x.md", "content": "spec"},
        )
        shallow_errors = evaluate_artifact_depth(shallow, REPO)
        self.assertIn("shallow_artifact:docs/agentic-sdlc/work-x/spec/work-x.md", shallow_errors)

        # End-to-end via the harness: both cases pass against the per-package fixture.
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--transcript",
                str(PER_PACKAGE_FIXTURE),
            ],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("procedure_eval=passed", proc.stdout)
        self.assertIn(f"case_{PER_PACKAGE_CASE_ID}=passed", proc.stdout)

    def test_reserved_slug_not_misfired(self):
        # AC16/BR11: docs/agentic-sdlc/spec/spec/x.md is NOT a per-package artifact
        # (reserved singular slug `spec`), so it is neither classified nor depth-checked.
        from run_procedure_eval import per_package_layout, evaluate_artifact_depth, Trace, _record_tool

        self.assertIsNone(per_package_layout("docs/agentic-sdlc/spec/spec/x.md"))
        self.assertIsNone(per_package_layout("docs/agentic-sdlc/plan/plan/x.md"))

        trace = Trace()
        _record_tool(
            trace,
            "Write",
            {"file_path": "docs/agentic-sdlc/spec/spec/x.md", "content": "spec"},
        )
        errors = evaluate_artifact_depth(trace, REPO)
        # Not treated as a (per-package) artifact at all -> no shallow_artifact for it.
        self.assertNotIn("shallow_artifact:docs/agentic-sdlc/spec/spec/x.md", errors)

    def test_flat_specs_still_classified_as_spec(self):
        # Guards the /spec/ vs /specs/ trap directly: a flat specs/<id>.md write must
        # still be classified and validated as a SPEC (mode=spec), never as a plan.
        from run_procedure_eval import per_package_layout, evaluate_artifact_depth, Trace, _record_tool

        self.assertIsNone(per_package_layout("docs/agentic-sdlc/specs/flat-classify-x.md"))
        self.assertIsNone(per_package_layout("docs/agentic-sdlc/plans/flat-classify-x.md"))

        trace = Trace()
        _record_tool(
            trace,
            "Write",
            {"file_path": "docs/agentic-sdlc/specs/flat-classify-x.md", "content": DEEP_SPEC},
        )
        errors = evaluate_artifact_depth(trace, REPO)
        # Validated as a deep spec -> passes; a misclassification as plan would fail
        # under --strict (ac_source_missing / no tasks).
        self.assertNotIn("shallow_artifact:docs/agentic-sdlc/specs/flat-classify-x.md", errors)

    def test_flat_fixtures_still_pass(self):
        # AC16/AC9: the three pre-existing flat pipeline fixtures stay GREEN once the
        # second (per-package) case is added to the contract.
        for fixture in (
            "agentic-sdlc-pipeline-procedure-pass.jsonl",
            "agentic-sdlc-pipeline-procedure-codex-adapter-pass.jsonl",
            "agentic-sdlc-pipeline-procedure-codex-exec-current.jsonl",
        ):
            with self.subTest(fixture=fixture):
                proc = subprocess.run(
                    [
                        sys.executable,
                        "scripts/run_procedure_eval.py",
                        "--eval-set",
                        "tests/skills/procedure/agentic-sdlc-pipeline.json",
                        "--transcript",
                        f"tests/fixtures/transcripts/{fixture}",
                    ],
                    cwd=REPO,
                    capture_output=True,
                    text=True, encoding="utf-8",
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn("procedure_eval=passed", proc.stdout)

    def test_slug_rule_parity_across_sources(self):
        # BR2/BR11: the slug reserved-set and regex are triplicated by design (resolver,
        # flow-guard JSON, offline gate). Pin them byte-identical so drift fails CI.
        import json
        import resolve_work_package as rwp
        import run_procedure_eval as rpe

        expected_reserved = {"specs", "plans", "evidence", "notes", "spec", "plan"}
        expected_pattern = r"^[a-z0-9][a-z0-9-]{0,63}$"

        flow = json.loads((REPO / "hooks" / "flow-requirements.json").read_text(encoding="utf-8"))
        pp = flow["perPackageArtifact"]
        json_reserved = set(pp["reservedSlugs"])
        json_pattern = pp["slugPattern"]

        # Each source matches the canonical values.
        self.assertEqual(rwp.RESERVED_SLUGS, expected_reserved)
        self.assertEqual(rwp.SLUG_RE.pattern, expected_pattern)
        self.assertEqual(rpe.RESERVED_SLUGS, expected_reserved)
        self.assertEqual(rpe.SLUG_RE.pattern, expected_pattern)
        self.assertEqual(json_reserved, expected_reserved)
        self.assertEqual(json_pattern, expected_pattern)

        # And the three sources are identical to one another.
        self.assertEqual(rwp.RESERVED_SLUGS, rpe.RESERVED_SLUGS)
        self.assertEqual(rwp.RESERVED_SLUGS, json_reserved)
        self.assertEqual(rwp.SLUG_RE.pattern, rpe.SLUG_RE.pattern)
        self.assertEqual(rwp.SLUG_RE.pattern, json_pattern)
