import gc
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import scripts.run_procedure_eval as procedure_eval


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
PIPELINE_EVAL = "tests/skills/procedure/agentic-sdlc-pipeline.json"


def run_cli(*args, cwd=REPO):
    return subprocess.run(
        [sys.executable, "scripts/run_procedure_eval.py", *[str(a) for a in args]],
        cwd=cwd,
        capture_output=True,
        text=True, encoding="utf-8",
    )


def write_jsonl(path, events):
    path.write_bytes("".join(json.dumps(e) + "\n" for e in events).encode("utf-8"))
    return path


def stream_tool_use(tool_id, name, input_obj, index=0):
    """A streamed tool_use reconstruction: start, one input_json_delta, stop."""
    return [
        {"type": "stream_event", "event": {"type": "content_block_start", "index": index,
                                           "content_block": {"type": "tool_use", "id": tool_id, "name": name}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "index": index,
                                           "delta": {"type": "input_json_delta", "partial_json": json.dumps(input_obj)}}},
        {"type": "stream_event", "event": {"type": "content_block_stop", "index": index}},
    ]


def full_tool_use(tool_id, name, input_obj, parent_tool_use_id=None):
    block = {"type": "tool_use", "name": name, "input": input_obj}
    if tool_id is not None:
        block["id"] = tool_id
    event = {"type": "assistant", "message": {"content": [block]}}
    if parent_tool_use_id is not None:
        event["parent_tool_use_id"] = parent_tool_use_id
    return event

PER_PACKAGE_FIXTURE = (
    REPO / "tests" / "fixtures" / "transcripts"
    / "agentic-sdlc-pipeline-procedure-per-package-pass.jsonl"
)
PER_PACKAGE_CASE_ID = "agentic-sdlc-pipeline-per-package"

# A spec whose every required section clears the strict depth checks (mirrors the
# known-good skill-depth-deep fixture). Reused to prove flat /specs/ classification
# and per-package gate firing without coupling those tests to a fixture file.
DEEP_SPEC = (
    # Frontmatter: validate_artifacts.py now checks the keys resolve_work_package.py
    # requires, and evaluate_artifact_depth runs that validator under --strict, so a spec
    # without it is reported as a shallow artifact.
    "---\nwork_id: deep-spec\nstatus: draft\n---\n\n"
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

    def test_unknown_case_id_fails(self):
        proc = subprocess.run(
            [
                sys.executable,
                "scripts/run_procedure_eval.py",
                "--eval-set",
                "tests/skills/procedure/agentic-sdlc-pipeline.json",
                "--case-id",
                "does-not-exist",
                "--dry-run",
            ],
            cwd=REPO,
            capture_output=True,
            text=True, encoding="utf-8",
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("error=unknown_case_id:does-not-exist", proc.stdout)
        self.assertIn("procedure_eval=failed", proc.stdout)

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
        self.assertTrue(procedure_eval.required_skill_satisfied(trace, "agentic-sdlc:implementation-control"))

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

    def test_pipeline_case_needs_no_focused_skill_and_forbids_calling_one(self):
        # C7 / D1: case 1 no longer requires feature-build, its two gate skills are met by their agents, and a Skill
        # call to a focused skill trips forbidden pattern 1 even in default mode.
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
        procedure_eval._record_tool(trace, "Agent", {"subagent_type": "agentic-sdlc:security-reviewer"})
        procedure_eval._record_tool(trace, "Agent", {"subagent_type": "agentic-sdlc:implementation-auditor"})
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:completion-claim-gate"})

        errors = procedure_eval.evaluate_case(case, trace, REPO)
        self.assertEqual([e for e in errors if e.startswith(("missing_", "forbidden_"))], [])

        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:feature-build"})
        errors = procedure_eval.evaluate_case(case, trace, REPO)
        self.assertEqual([e for e in errors if e.startswith(("missing_", "forbidden_"))],
                         [f"forbidden_pattern:{FORBIDDEN_SKILL_CALL}"])

    def test_live_fixture_has_baseline_commit_before_claude_runs(self):
        case = {
            "id": "agentic-sdlc-pipeline-feature-no-commit",
            "fixture_dir": "tests/fixtures/agentic-sdlc-pipeline-basic",
        }
        with tempfile.TemporaryDirectory() as td:
            cwd = procedure_eval.copy_fixture(case, Path(td), allow_commit=True)
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
                "--case-id",
                PER_PACKAGE_CASE_ID,
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


class TestTraceDedup(unittest.TestCase):
    """AC63: one Claude tool_use id is recorded once, whichever carrier arrives first.

    Claude ids are unique per call, so a transcript that reused one id for two genuinely different
    calls would lose the second call; that loss is accepted. Mutation: dropping the seen-id check in
    either the streamed or the full-block path turns the first three tests red (count 2).
    """

    COMMAND = {"command": "python -m pytest -q"}

    def events(self, streamed_first=True):
        streamed = stream_tool_use("toolu_dup1", "Bash", self.COMMAND)
        full = [full_tool_use("toolu_dup1", "Bash", self.COMMAND)]
        return streamed + full if streamed_first else full + streamed

    def assert_recorded_once(self, trace):
        self.assertEqual(trace.tools, ["Bash"])
        self.assertEqual(len(trace.commands), 1)
        self.assertEqual(len(trace.tool_inputs), 1)

    def test_streamed_then_full_tool_use_same_id_recorded_once(self):
        self.assert_recorded_once(procedure_eval.trace_events(self.events(streamed_first=True)))

    def test_full_then_streamed_tool_use_same_id_recorded_once(self):
        self.assert_recorded_once(procedure_eval.trace_events(self.events(streamed_first=False)))

    def test_cli_tools_count_single_for_duplicated_id(self):
        with tempfile.TemporaryDirectory() as td:
            transcript = write_jsonl(Path(td) / "dup.jsonl", self.events())
            proc = run_cli("--eval-set", PIPELINE_EVAL, "--case-id", "agentic-sdlc-pipeline-feature-no-commit",
                           "--transcript", transcript)
        self.assertIn("case_agentic-sdlc-pipeline-feature-no-commit_tools=1", proc.stdout, proc.stdout + proc.stderr)

    def test_full_block_replaces_unparseable_or_empty_streamed_reconstruction(self):
        """The full assistant block is authoritative over a streamed reconstruction with the same id.

        Mutation: keeping the first (streamed) copy drops the real command, so commands is [] and the
        forbidden_command error disappears.
        """
        full_command = {"command": "git push --force origin main"}
        start = {"type": "stream_event", "event": {"type": "content_block_start", "index": 0,
                                                   "content_block": {"type": "tool_use", "id": "toolu_x", "name": "Bash"}}}
        stop = {"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}}
        malformed = {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                                       "delta": {"type": "input_json_delta", "partial_json": '{"command": "git pu'}}}
        case = {"id": "dedup-probe", "prompt": "probe", "forbidden_commands": ["git\\s+push"]}
        for label, streamed in (("malformed", [start, malformed, stop]), ("empty", [start, stop])):
            with self.subTest(stream=label):
                trace = procedure_eval.trace_events(streamed + [full_tool_use("toolu_x", "Bash", full_command)])
                self.assertEqual(trace.tools, ["Bash"])
                self.assertEqual(trace.commands, [full_command["command"]])
                self.assertEqual(trace.tool_inputs, [{"name": "Bash", "input": full_command}])
                calls = [entry for entry in trace.timeline if entry["kind"] == "tool_call"]
                self.assertEqual([call["input"] for call in calls], [full_command])
                self.assertIn("forbidden_command:git\\s+push", procedure_eval.evaluate_case(case, trace, REPO))

    def test_replaced_streamed_records_keep_stream_order(self):
        """Full blocks arriving in reverse order still leave commands and writes in stream order.

        Mutation: dropping the position shift for later streamed records puts the second call first.
        """
        def empty_stream(tool_id, name, index):
            return [
                {"type": "stream_event", "event": {"type": "content_block_start", "index": index,
                                                   "content_block": {"type": "tool_use", "id": tool_id, "name": name}}},
                {"type": "stream_event", "event": {"type": "content_block_stop", "index": index}},
            ]

        edit = {"file_path": "src/app.py", "content": "x = 1\n"}
        events = (empty_stream("toolu_a", "Bash", 0) + empty_stream("toolu_w", "Write", 1)
                  + empty_stream("toolu_b", "Bash", 2)
                  + [full_tool_use("toolu_b", "Bash", {"command": "second"}), full_tool_use("toolu_w", "Write", edit),
                     full_tool_use("toolu_a", "Bash", {"command": "first"})])
        trace = procedure_eval.trace_events(events)
        self.assertEqual(trace.tools, ["Bash", "Write", "Bash"])
        self.assertEqual(trace.commands, ["first", "second"])
        self.assertEqual(trace.writes, ["src/app.py"])
        self.assertEqual(trace.artifact_writes, [("src/app.py", "x = 1\n")])
        self.assertEqual([(e["kind"], e.get("id")) for e in trace.timeline],
                         [("tool_call", "toolu_a"), ("tool_call", "toolu_w"), ("write", None), ("tool_call", "toolu_b")])

    def test_distinct_ids_and_idless_blocks_still_recorded(self):
        distinct = procedure_eval.trace_events(
            [full_tool_use("toolu_a", "Bash", self.COMMAND), full_tool_use("toolu_b", "Bash", self.COMMAND)]
        )
        self.assertEqual(len(distinct.tools), 2)
        idless = procedure_eval.trace_events(
            [full_tool_use(None, "Bash", self.COMMAND), full_tool_use(None, "Bash", self.COMMAND)]
        )
        self.assertEqual(len(idless.tools), 2)


FIXTURE_CASE = {"id": "agentic-sdlc-pipeline-feature-no-commit", "fixture_dir": "tests/fixtures/agentic-sdlc-pipeline-basic"}


def git_out(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def run_main(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = procedure_eval.main([str(a) for a in argv])
    return code, out.getvalue()


class TestFixtureConsent(unittest.TestCase):
    """AC73: --live needs --allow-fixture-commit, and the baseline commit stays inside the fixture copy."""

    def test_live_without_consent_exits_before_tempdir_git_or_model(self):
        # Mutation: moving the consent check after TemporaryDirectory or run_live_case turns this red.
        with mock.patch.object(procedure_eval.tempfile, "TemporaryDirectory") as tmpdir, \
                mock.patch.object(procedure_eval.subprocess, "run") as run, \
                mock.patch.object(procedure_eval.shutil, "which") as which:
            code, stdout = run_main(["--eval-set", PIPELINE_EVAL, "--live"])
        self.assertNotEqual(code, 0)
        self.assertIn("error=live_requires_allow_fixture_commit", stdout)
        self.assertIn("procedure_eval=failed", stdout)
        tmpdir.assert_not_called()
        run.assert_not_called()
        which.assert_not_called()

    def test_copy_fixture_without_consent_creates_no_commit(self):
        for label, kwargs in (("explicit-false", {"allow_commit": False}), ("default", {})):
            with self.subTest(call=label), tempfile.TemporaryDirectory() as td:
                dst = procedure_eval.copy_fixture(FIXTURE_CASE, Path(td), **kwargs)
                self.assertNotEqual(git_out(dst, "rev-parse", "--verify", "HEAD").returncode, 0)

    def test_consented_baseline_commit_exists_only_inside_fixture(self):
        if not (REPO / ".git").exists():
            self.skipTest("not a git checkout")
        repo_head = git_out(REPO, "rev-parse", "HEAD").stdout.strip()
        with tempfile.TemporaryDirectory() as td:
            dst = procedure_eval.copy_fixture(FIXTURE_CASE, Path(td), allow_commit=True)
            head = git_out(dst, "rev-parse", "--verify", "HEAD")
            self.assertEqual(head.returncode, 0, head.stderr)
            toplevel = git_out(dst, "rev-parse", "--show-toplevel").stdout.strip()
            self.assertEqual(Path(toplevel).resolve(), dst.resolve())
            self.assertNotEqual(git_out(REPO, "cat-file", "-e", head.stdout.strip()).returncode, 0)
        self.assertEqual(git_out(REPO, "rev-parse", "HEAD").stdout.strip(), repo_head)


GIT_STEP_PREFIXES = (
    ("init", ["git", "init"]),
    ("config-user-email", ["git", "config", "user.email"]),
    ("config-user-name", ["git", "config", "user.name"]),
    ("add", ["git", "add"]),
    ("commit", ["git", "commit"]),
)


def is_git_program(program):
    """git by bare name or by the absolute path the D25 lookup resolves (`.../git` or `...\\git.exe`)."""
    return program == "git" or Path(program).name.lower() in ("git", "git.exe")


def git_step_of(argv):
    if not argv or not is_git_program(argv[0]):
        return None
    for step, prefix in GIT_STEP_PREFIXES:
        if list(argv[1: len(prefix)]) == prefix[1:]:
            return step
    return None


class TestFixtureGitFailure(unittest.TestCase):
    """AC72: a failed fixture Git step stops preparation, named, before any model process starts."""

    def fake_run(self, failing_step, calls):
        real_run = subprocess.run

        def run(argv, *args, **kwargs):
            calls.append(list(argv))
            if git_step_of(argv) == failing_step:
                return subprocess.CompletedProcess(argv, 128, stdout="", stderr="fatal: synthetic failure")
            if not argv or not is_git_program(argv[0]):
                # Never execute anything but git here: a regression that reaches the model must be
                # recorded and asserted on, not launch a real (paid) `claude -p` process.
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            return real_run(argv, *args, **kwargs)

        return run

    def test_copy_fixture_raises_named_step_on_git_failure(self):
        order = [step for step, _prefix in GIT_STEP_PREFIXES]
        for step in order:
            with self.subTest(step=step), tempfile.TemporaryDirectory() as td:
                calls = []
                with mock.patch.object(procedure_eval.subprocess, "run", side_effect=self.fake_run(step, calls)):
                    with self.assertRaises(procedure_eval.FixtureGitError) as ctx:
                        procedure_eval.copy_fixture(FIXTURE_CASE, Path(td), allow_commit=True)
                self.assertEqual(str(ctx.exception), f"fixture_git_failed:{step}")
                later = set(order[order.index(step) + 1:])
                self.assertEqual([git_step_of(c) for c in calls if git_step_of(c) in later], [])

    def test_live_run_stops_before_model_on_git_failure(self):
        # The CLI must resolve for the run to reach the fixture step, but WHICH binary is not this
        # test's subject: it patches the resolver, not shutil.which. SEC-8 moved the bare-name lookup
        # off shutil.which (Windows searches the current directory first), so patching which left the
        # real PATH in play - the test then passed on a machine with `claude` installed and failed on
        # CI with `error=claude CLI missing`, asserting the environment instead of AC72.
        calls = []
        stub = os.path.join(os.sep, "stub", "bin", "claude")
        with mock.patch.object(procedure_eval, "resolve_agent_cli", return_value=stub), \
                mock.patch.object(procedure_eval.subprocess, "run", side_effect=self.fake_run("add", calls)):
            code, stdout = run_main(["--eval-set", PIPELINE_EVAL, "--case-id", "agentic-sdlc-pipeline-feature-no-commit",
                                     "--live", "--allow-fixture-commit"])
        self.assertEqual(code, 1, stdout)
        self.assertIn("error=fixture_git_failed:add", stdout)
        self.assertIn("procedure_eval=failed", stdout)
        self.assertEqual([c for c in calls if c and c[0] == stub], [])


PASS_TRANSCRIPT = "tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-pass.jsonl"


def case_lines(stdout):
    return [line for line in stdout.splitlines() if line.startswith("case_")]


class TestStrictFlags(unittest.TestCase):
    """AC74, AC124, AC66: the strict flags validate statically, create nothing, and keep dry-run working."""

    def test_dry_run_with_every_new_flag_passes(self):
        with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
            evidence = Path(tmp_a) / "ev"
            proc = run_cli("--eval-set", PIPELINE_EVAL, "--dry-run", "--strict-evidence", "--evidence-dir", evidence,
                           "--fixture-root", tmp_b, "--allow-fixture-commit")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("procedure_eval=dry-run-passed", proc.stdout)
            self.assertFalse(evidence.exists(), "static checks must not create the evidence dir")

    def assert_rejected_before_evaluation(self, proc, error):
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(f"error={error}", proc.stdout)
        self.assertEqual(case_lines(proc.stdout), [], "no case may be evaluated")

    def test_nonexistent_fixture_root_exits_before_evaluation(self):
        with tempfile.TemporaryDirectory() as td:
            proc = run_cli("--eval-set", PIPELINE_EVAL, "--transcript", PASS_TRANSCRIPT,
                           "--fixture-root", Path(td) / "missing")
        self.assert_rejected_before_evaluation(proc, "fixture_root_invalid")

    def test_fixture_root_regular_file_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            regular = Path(td) / "not-a-dir.txt"
            regular.write_text("x", encoding="utf-8")
            proc = run_cli("--eval-set", PIPELINE_EVAL, "--transcript", PASS_TRANSCRIPT, "--fixture-root", regular)
        self.assert_rejected_before_evaluation(proc, "fixture_root_invalid")

    def test_evidence_dir_inside_fixture_root_rejected_and_not_created(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            variants = [("same-case", root / "ev")]
            if os.name == "nt":
                # Windows paths compare case-insensitively; a mixed-case spelling must not slip past.
                variants.append(("mixed-case", Path(str(root).swapcase()) / "ev"))
            for label, evidence in variants:
                with self.subTest(spelling=label):
                    proc = run_cli("--eval-set", PIPELINE_EVAL, "--transcript", PASS_TRANSCRIPT, "--strict-evidence",
                                   "--fixture-root", root, "--evidence-dir", evidence)
                    self.assert_rejected_before_evaluation(proc, "evidence_dir_inside_fixture")
                    self.assertFalse((root / "ev").exists())

    def test_evidence_dir_without_strict_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            evidence = Path(td) / "ev"
            proc = run_cli("--eval-set", PIPELINE_EVAL, "--transcript", PASS_TRANSCRIPT, "--evidence-dir", evidence)
            self.assert_rejected_before_evaluation(proc, "evidence_dir_requires_strict_evidence")
            self.assertFalse(evidence.exists())


PROBE_ARTIFACT = "docs/agentic-sdlc/specs/procedure-fixture-root-probe.md"


def write_probe_eval(directory, case_id="fixture-root-probe", artifacts=(PROBE_ARTIFACT,)):
    """A temp eval set with no fixture_dir, so load_eval's REPO-relative fixture validation is not involved."""
    eval_set = Path(directory) / "eval.json"
    eval_set.write_text(json.dumps({"cases": [
        {"id": case_id, "prompt": "probe the fixture root", "required_artifacts": list(artifacts)}
    ]}), encoding="utf-8")
    transcript = write_jsonl(Path(directory) / "transcript.jsonl", [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "No files were written."}]}}
    ])
    return eval_set, transcript


class TestFixtureRootReplay(unittest.TestCase):
    """AC64, AC124: replay artifact checks resolve under --fixture-root and reject escapes."""

    def test_artifact_only_under_fixture_root_passes_with_flag(self):
        with tempfile.TemporaryDirectory() as meta_td, tempfile.TemporaryDirectory() as root_td:
            eval_set, transcript = write_probe_eval(meta_td)
            artifact = Path(root_td) / PROBE_ARTIFACT
            artifact.parent.mkdir(parents=True)
            artifact.write_text("probe\n", encoding="utf-8")
            with_flag = run_cli("--eval-set", eval_set, "--transcript", transcript, "--fixture-root", root_td)
            without_flag = run_cli("--eval-set", eval_set, "--transcript", transcript)
        self.assertIn("case_fixture-root-probe=passed", with_flag.stdout, with_flag.stdout + with_flag.stderr)
        # Without the flag, replay grades against the repository exactly as at 5801cb9.
        self.assertIn(f"missing_artifact:{PROBE_ARTIFACT}", without_flag.stdout, without_flag.stdout + without_flag.stderr)

    def test_absolute_parent_and_symlink_escapes_fail_named(self):
        # Mutation: dropping the containment check lets the symlink pattern pass as present.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "root"
            outside = Path(td) / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "outside.md").write_text("outside\n", encoding="utf-8")
            for label, pattern in (("absolute", str(outside / "outside.md")), ("parent", "docs/../../outside.md"),
                                   ("symlink", "link/outside.md")):
                with self.subTest(escape=label):
                    if label == "symlink":
                        try:
                            os.symlink(outside, root / "link", target_is_directory=True)
                        except (OSError, NotImplementedError):
                            self.skipTest("symlinks unavailable")
                    case = {"id": "escape-probe", "prompt": "p", "required_artifacts": [pattern]}
                    errors = procedure_eval.evaluate_case(case, procedure_eval.Trace(), root, contained_root=root)
                    self.assertIn(f"artifact_escape:{pattern}", errors)

    def test_anchored_glob_pattern_is_a_named_escape(self):  # SEC-10, AC124
        # Mutation: checking only Path.is_absolute() (a rooted `/Win*` or drive-relative `C:*` glob is not absolute on
        # Windows, and cwd.glob raises NotImplementedError instead of naming the escape).
        patterns = ("/Win*/win.ini", "C:*")
        with tempfile.TemporaryDirectory() as meta_td, tempfile.TemporaryDirectory() as root_td:
            root = Path(root_td)
            for pattern in patterns:
                with self.subTest(pattern=pattern):
                    case = {"id": "anchor-probe", "prompt": "p", "required_artifacts": [pattern]}
                    errors = procedure_eval.evaluate_case(case, procedure_eval.Trace(), root, contained_root=root)
                    self.assertIn(f"artifact_escape:{pattern}", errors)
                    with self.assertRaises(ValueError):
                        procedure_eval.artifact_present(pattern, procedure_eval.Trace(), root)
            eval_set, transcript = write_probe_eval(meta_td, case_id="anchor-probe", artifacts=patterns)
            proc = run_cli("--eval-set", eval_set, "--transcript", transcript, "--fixture-root", root_td)
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertNotIn("Traceback", proc.stdout + proc.stderr)
        if sys.platform == "win32":  # elsewhere load_eval already rejects the absolute `/Win*` pattern by name
            for pattern in patterns:
                self.assertIn(f"error=anchor-probe:artifact_escape:{pattern}", proc.stdout.splitlines())

    def test_replay_leaves_repository_head_and_status_unchanged(self):
        if not (REPO / ".git").exists():
            self.skipTest("not a git checkout")
        head_before = git_out(REPO, "rev-parse", "HEAD").stdout
        status_before = git_out(REPO, "status", "--porcelain").stdout
        with tempfile.TemporaryDirectory() as root_td, tempfile.TemporaryDirectory() as evidence_td:
            proc = run_cli("--eval-set", PIPELINE_EVAL, "--transcript", PASS_TRANSCRIPT, "--fixture-root", root_td,
                           "--strict-evidence", "--evidence-dir", Path(evidence_td) / "ev")
        self.assertTrue(case_lines(proc.stdout), proc.stdout + proc.stderr)
        self.assertEqual(git_out(REPO, "rev-parse", "HEAD").stdout, head_before)
        self.assertEqual(git_out(REPO, "status", "--porcelain").stdout, status_before)


# Codex rollout record builders. Shapes follow tests/fixtures/transcripts/codex-0.154.0-native-tool-carriers.jsonl
# (function_call / custom_tool_call and their outputs); session_meta, turn_context and task_complete follow
# the protocol field names (D10).
def rollout(payload, rtype="response_item"):
    return {"timestamp": "2026-09-15T00:00:00.000Z", "type": rtype, "payload": payload}


def exec_call(call_id, cmd):
    return rollout({"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": cmd}),
                    "call_id": call_id})


def exec_output(call_id, exit_code, body):
    header = f"Chunk ID: {call_id}\nWall time: 0.1 seconds\nProcess exited with code {exit_code}\nOriginal token count: 2\n"
    return rollout({"type": "function_call_output", "call_id": call_id, "output": header + "Output:\n" + body})


def patch_call(call_id, patch):
    return rollout({"type": "custom_tool_call", "status": "completed", "call_id": call_id, "name": "apply_patch",
                    "input": patch})


def patch_output(call_id, output):
    return rollout({"type": "custom_tool_call_output", "call_id": call_id, "output": output})


def patch_success(call_id, marker, path):
    return patch_output(call_id, f"Exit code: 0\nWall time: 0.2 seconds\nOutput:\nSuccess. Updated the following files:\n{marker} {path}\n")


def add_file_patch(path, body):
    """An apply_patch Add File body: one `+` line per content line (a trailing newline adds no empty line)."""
    lines = (body[:-1] if body.endswith("\n") else body).split("\n")
    plus = "".join("+" + line + "\n" for line in lines)
    return f"*** Begin Patch\n*** Add File: {path}\n{plus}*** End Patch\n"


def assistant_message(text):
    return rollout({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]})


def call_exits(trace):
    """Exit per tool_call in timeline order: the correlated tool_result's exit, else None."""
    results = {r["id"]: r for r in trace.timeline if r["kind"] == "tool_result"}
    return [results[c["id"]]["exit"] if c["id"] in results else None
            for c in trace.timeline if c["kind"] == "tool_call"]


class TestStrictTrace(unittest.TestCase):
    """AC70, AC68, AC123: ordered results, messages and Codex rollout carriers for strict grading."""

    def test_malformed_line_is_a_named_strict_error(self):  # D25 model (4), QUAL-4
        # Mutation: skipping malformed or non-object lines silently under --strict-evidence, recording one per line,
        # or failing the default mode on them.
        with tempfile.TemporaryDirectory() as td:
            eval_set = Path(td) / "eval.json"
            eval_set.write_text(json.dumps({"cases": [{"id": "malformed-probe", "prompt": "p"}]}), encoding="utf-8")
            text = assistant_text_event("working")
            transcript = Path(td) / "t.jsonl"
            transcript.write_bytes(("{not json\r\n" + json.dumps(text) + "\r\n[1]\n\n" + json.dumps(text) + "\n")
                                   .encode("utf-8"))
            strict_code, strict_out = run_main(["--eval-set", eval_set, "--transcript", transcript, "--strict-evidence"])
            default_code, default_out = run_main(["--eval-set", eval_set, "--transcript", transcript])
            # Valid JSON that is not an object is malformed on its own (no invalid-JSON line to trip the check).
            for non_object in ("[1]", '"x"'):
                with self.subTest(line=non_object):
                    only = Path(td) / "only.jsonl"
                    only.write_bytes((json.dumps(text) + "\n" + non_object + "\n" + json.dumps(text) + "\n")
                                     .encode("utf-8"))
                    code, out = run_main(["--eval-set", eval_set, "--transcript", only, "--strict-evidence"])
                    self.assertEqual(code, 1, out)
                    self.assertIn("error=malformed-probe:strict_transcript_malformed_line", out.splitlines())
                    code, out = run_main(["--eval-set", eval_set, "--transcript", only])
                    self.assertEqual(code, 0, out)
                    self.assertIn("case_malformed-probe=passed", out.splitlines())
        self.assertEqual(strict_code, 1)
        self.assertEqual(strict_out.splitlines().count("error=malformed-probe:strict_transcript_malformed_line"), 1)
        self.assertNotIn("{not json", strict_out)
        self.assertEqual(default_code, 0, default_out)
        self.assertIn("case_malformed-probe=passed", default_out.splitlines())
        self.assertIn("case_malformed-probe_tools=0", default_out.splitlines())

    def test_claude_tool_result_correlated_by_id_with_error_flag(self):
        trace = procedure_eval.trace_events([
            full_tool_use("t1", "Agent", {"subagent_type": "agentic-sdlc:implementation-auditor"}),
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "audit crashed"}]}},
        ])
        self.assertEqual([r["kind"] for r in trace.timeline], ["tool_call", "tool_result"])
        result = trace.timeline[1]
        self.assertEqual((result["id"], result["is_error"], result["text"]), ("t1", True, "audit crashed"))

    def rollout_runs(self):
        return [
            exec_call("c1", "python -m pytest -q"),
            exec_output("c1", 1, "1 failed\n"),
            exec_call("c2", "python -m pytest -q"),
            rollout({"type": "function_call_output", "call_id": "c2",
                     "output": "Exit code: 0\nWall time: 0.2 seconds\nOutput:\n2 passed\n"}),
            exec_call("c3", "python -m pytest -q"),
        ]

    def test_rollout_exec_command_output_exit_code_parsed_via_codex_rollout_module(self):
        # Mutation: reading the exit from the body (`1 failed`) or dropping correlation changes [1, 0, None].
        trace = procedure_eval.trace_events(self.rollout_runs(), strict=True)
        self.assertEqual(call_exits(trace), [1, 0, None])
        self.assertEqual(len(trace.commands), 3)
        self.assertEqual(trace.runtime, "codex-rollout")
        self.assertEqual(trace.strict_errors, [])

    def test_rollout_apply_patch_add_file_recorded_only_after_success_output(self):
        path = "docs/agentic-sdlc/specs/x.md"
        ok = procedure_eval.trace_events([
            patch_call("p1", add_file_patch(path, "# Title\nbody\n")),
            patch_success("p1", "A", path),
        ], strict=True)
        self.assertEqual(ok.writes, [path])
        self.assertEqual(ok.artifact_writes, [(path, "# Title\nbody\n")])
        blocked = procedure_eval.trace_events([
            patch_call("p2", add_file_patch("denied-probe.txt", "VALUE=1\n")),
            patch_output("p2", "Command blocked by PreToolUse hook: Write blocked: possible secret in newly written "
                               "content (values masked).\n  • target(s): denied-probe.txt\n"),
        ], strict=True)
        self.assertEqual(blocked.writes, [])
        self.assertEqual(blocked.artifact_writes, [])

    def test_rollout_meta_and_final_message_recorded(self):
        final = "Done. Codex Adapter Gate: completion-claim-gate"
        base = [
            rollout({"id": "s1", "cli_version": "0.154.0"}, "session_meta"),
            rollout({"model": "gpt-5.5", "effort": "low"}, "turn_context"),
            rollout({"type": "task_complete", "last_agent_message": final}, "event_msg"),
        ]
        trace = procedure_eval.trace_events(base, strict=True)
        self.assertEqual(trace.meta, {"cli_version": "0.154.0", "model": "gpt-5.5", "effort": "low"})
        self.assertEqual(trace.final_assistant_text, final)
        with self.subTest(turn_context="no effort"):
            partial = procedure_eval.trace_events(
                [base[0], rollout({"model": "gpt-5.5"}, "turn_context"), base[2]], strict=True)
            self.assertNotIn("effort", partial.meta)
            self.assertEqual(partial.meta.get("model"), "gpt-5.5")

    def test_default_mode_ignores_rollout_records_as_at_5801cb9(self):
        trace = procedure_eval.trace_events(self.rollout_runs() + [assistant_message("Runtime: Codex")])
        self.assertEqual(trace.tools, [])
        self.assertEqual(trace.text, "")

    def test_strict_codex_exec_started_and_completed_counted_once(self):
        item = {"id": "c1", "type": "command_execution", "command": "python -m pytest -q",
                "aggregated_output": "1 passed\n", "exit_code": 0, "status": "completed"}
        events = [{"type": "item.started", "item": dict(item, status="in_progress")}, {"type": "item.completed", "item": item}]
        self.assertEqual(len(procedure_eval.trace_events(events, strict=True).commands), 1)


BR6_TABLE = REPO / "tests" / "fixtures" / "transcripts" / "br6-attribution-cases.json"
TEST_RE = re.compile(
    json.loads((REPO / "hooks" / "flow-requirements.json").read_text(encoding="utf-8"))["testCommand"], re.IGNORECASE
)


def load_br6_rows():
    # Read-only consumer of the Task 0 table (D3); the row count is never written as a literal.
    return json.loads(BR6_TABLE.read_bytes().decode("utf-8"))["rows"]


def claude_result(tool_id, is_error, text, *, tool_use_result=None):
    event = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "is_error": is_error, "content": text}]}}
    if tool_use_result is not None:
        event["tool_use_result"] = tool_use_result
    return event


def launch_receipt(tool_id, status="async_launched", text="Agent launched"):
    return claude_result(tool_id, False, text, tool_use_result={"status": status})


def task_notification(status, tool_use_id=None):
    event = {"type": "system", "subtype": "task_notification", "status": status}
    if tool_use_id is not None:
        event["tool_use_id"] = tool_use_id
    return event


def claude_run(tool_id, command, is_error, text):
    return [full_tool_use(tool_id, "Bash", {"command": command}), claude_result(tool_id, is_error, text)]


def trace_from_carrier(row):
    """Build a trace from a BR6 table row's carrier (shared with the parity test).

    exitCode null with an output record: a Codex exec trace whose completed item carries no exit_code.
    Otherwise: a Claude trace with callEvents full Bash tool_use blocks and outputRecords tool_results.
    """
    carrier = row["carrier"]
    if carrier["exitCode"] is None and carrier["outputRecords"] >= 1:
        item = {"id": "c-row", "type": "command_execution", "command": row["command"],
                "aggregated_output": carrier["outputSummary"], "status": "completed"}
        events = [{"type": "item.completed", "item": dict(item)} for _ in range(carrier["callEvents"])]
        return procedure_eval.trace_events(events, strict=True)
    events = [full_tool_use("toolu_row", "Bash", {"command": row["command"]}) for _ in range(carrier["callEvents"])]
    events += [claude_result("toolu_row", carrier["exitCode"] == 1, carrier["outputSummary"])
               for _ in range(carrier["outputRecords"])]
    return procedure_eval.trace_events(events)


RED_GREEN_CASE = {"id": "red-green-probe", "prompt": "probe", "strict": {"require_red_green": True}}

# D23 safe-grammar production lists, shared with the Node grammar test in test_codex_current_rollout.py.
GRAMMAR_INSIDE = (
    "pytest",
    "cd repo; pytest -x",
    "A=1 B=$HOME/x pytest -k \"$K\" $1 $? $# $@",
    "pytest -k 'a;b $( ` ${'",
    "pytest -k \"a\\\"b \\$(x) \\`y\\`\"",
    "pytest \\( \\) \\{ \\} \\; \\|",
    "pytest tests/test_[ab].py ]",
    "pytest # (x) {y} $(z) [[",
    "pytest > out 2>&1 >> log < in <> rw >| clob &> both &>> both2 >&2 <&0",
    "pytest |& tee x | cat && true || false; x & y",
    "pytest \\\n-q",
    "pytest ~/x @a %b ^c !d ?e *f ,g +h :i =j",
    "pytest é",
    "set -euo pipefail; set +e -o errexit +o nounset; pytest",
    "cd repo; export X=1; echo ok; pwd; : note; true; false; pytest",
    "2>err.txt pytest",
    "> out.txt pytest",
    "echo>out.txt x; pytest",
    "X='eval' Y=\"$Z\" pytest",
    "ev\\\nal=1 pytest",
    "pytest eval source trap 'exit 0'",
    "set -euo pipefail 2>/dev/null; pytest",
    "echo $? *.txt; cd \"$D\"; export PATH=$PATH:bin; pytest",
    # Expansions after the minimized safe builtins that bash 5.2.37 still follows with a real runner run.
    "OLDPWD='BASH_CMDS[pytest]'; cd ~-; pytest",
    "OLDPWD='BASH_CMDS[pytest]'; echo ~- ~+; pytest",
    "V='BASH_CMDS[pytest]=/usr/bin/true'; echo $V; pwd; pytest",
    "V='BASH_CMDS[pytest]=/usr/bin/true'; : $V; true; pytest",
    "X='BASH_CMDS[pytest]'; cd \"$X\" 2>/dev/null; pytest",
    "CDPATH='BASH_CMDS[pytest]'; cd -P . ; pytest",
    "set -euo pipefail; cd .; echo ok; pytest",
    # Assignments to variables without bash 5.2.37's integer attribute, and literal export arguments (runner runs).
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; SECONDS=V; pytest",
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; LINENO=V; pytest",
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; export -n X=V -- Y; pytest",
)
GRAMMAR_OUTSIDE = (
    "pytest $(x)", "pytest $((1))", "pytest ${x}", "pytest $'x'", "pytest $\"x\"", "pytest $[1]", "pytest $",
    "pytest $ x", "pytest \"$(x)\"", "pytest \"${x}\"", "pytest `x`", "pytest \"`x`\"", "(pytest)", "pytest )",
    "{ pytest; }", "pytest }", "[[ -n x ]] && pytest", "pytest <<EOF", "pytest <<-EOF", "pytest <<<x", "pytest <(x)",
    "pytest >(x)", "pytest >", "pytest > ;", "pytest >#x", "pytest 'x", "pytest \"x", "pytest \\", "pytest\r",
    "eval x; pytest", ". ./f.sh; pytest", "source f.sh && pytest", "set -n; pytest", "set -x; pytest",
    "set -o noexec", "set -- a", "hash -p /usr/bin/true pytest", "trap x EXIT; pytest", "exit 0", "exec true",
    "builtin true", "command true", "alias pytest=true", "shopt -s expand_aliases", "$E x; pytest", "\"eval\" x",
    "e\\val x", "ev\\\nal x", "function f if true; then true; fi", "! pytest", "time pytest",
    "BASH_CMDS[pytest]=x; pytest", "printf -v 'a[b]' x", "echo '[x]'; pytest", "test -v \"a[b]\"",
    "2>/dev/null eval x", "X=1 eval x", "type pytest", "p?test", "pyt*st", "[x] && pytest",
    # printf, test, `[`, wait and unset take a variable name or evaluate an arithmetic subscript, so any expansion
    # (parameter, glob, tilde) carries a BASH_CMDS subscript past the `[` check (bash 5.2.37 exit 0); they are outside.
    "OLDPWD='BASH_CMDS[pytest]'; printf -v ~- %s /usr/bin/true; pytest",
    "cp /usr/bin/true 0; a=1; V='a[BASH_CMDS[pytest]=0]'; unset $V; pytest",
    "test -f x; pytest", "printf '%s\\n' x; pytest", "unset X; pytest", "unset $X; pytest", "wait; pytest",
    "test -f x && [ -d y ] && pytest",
    # A `[` after a safe builtin stays outside even where bash rejects the identifier and the runner runs.
    "export 'BASH_CMDS[pytest]=/usr/bin/true'; pytest",
    "V='BASH_CMDS[pytest]'; printf -v $V %s /usr/bin/true; pytest",
    "V='BASH_CMDS[pytest]'; printf -v \"$V\" %s /usr/bin/true; pytest",
    "ls 'BASH_CMDS[pytest]'; printf -v $_ %s /usr/bin/true; pytest",
    "touch 'BASH_CMDS[pytest]'; printf -v BASH_CMDS?pytest? %s /usr/bin/true; pytest",
    "touch 'BASH_CMDS[pytest]'; printf -v BASH_CMDS*pytest* %s /usr/bin/true; pytest",
    "cp /usr/bin/true 0; V='a[BASH_CMDS[pytest]=0]'; test -v $V; pytest",
    "cp /usr/bin/true 0; V='a[BASH_CMDS[pytest]=0]'; [ -v \"$V\" ]; pytest",
    "V='BASH_CMDS[pytest]'; wait -n -p $V; pytest",
    # Assigning an integer-attributed variable (bash 5.2.37 `declare -p`) evaluates the value as arithmetic, which can
    # write BASH_CMDS (bash exit 0, runner not run); an export argument must name its variable literally.
    "echo exit 0 > 1; chmod +x 1; RANDOM=BASH_CMDS[pytest]=1; pytest",
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; RANDOM=V; pytest",
    "echo exit 0 > 1; chmod +x 1; ls BASH_CMDS[pytest]=1; RANDOM=_; pytest",
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; RANDOM+=V; pytest",
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; export RANDOM=V; pytest",
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; SRANDOM=$V; pytest",
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; OPTIND=V; pytest",
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; HISTCMD=V; pytest",
    "echo exit 0 > 1; chmod +x 1; W='RANDOM=BASH_CMDS[pytest]=1'; export $W; pytest",
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; export \"RANDOM=V\"; pytest",
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; touch RANDOM=V; export RAND?M=V; pytest",
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; OLDPWD=RANDOM=V; export ~-; pytest",
    "echo exit 0 > 1; chmod +x 1; V=BASH_CMDS[pytest]=1; export -n RANDOM=V; pytest",
    # Disclosed false 'missing': any integer-attributed assignment, prefix or standalone, and a non-literal export word.
    "RANDOM=5; pytest", "RANDOM=5 true; pytest", "RANDOM=V pytest", "export \"X=1\"; pytest",
) + ('pytest "a' + chr(1) + 'b"',)
# bash 5.2.37 `bash -c 'declare -p' | grep '^declare -[a-zA-Z]*i'` (SECONDS is not marked).
INTEGER_VARIABLES = frozenset({"BASHPID", "EUID", "HISTCMD", "OPTIND", "PPID", "RANDOM", "SRANDOM", "UID"})


class TestStrictRedGreen(unittest.TestCase):
    """AC69, AC123: attributable RED-before-GREEN runs, judged by the shared BR6 table's strict column."""

    def test_attribution_table_matches_shared_cases(self):
        # D27: runner identification is the grammar-derived rule, so no node process classifies anything here.
        rows = load_br6_rows()
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(id=row["id"]):
                statements = procedure_eval.br6_statements(row["command"])
                self.assertEqual(statements, row["statements"])
                last = statements[-1]
                self.assertEqual(procedure_eval.has_unquoted_pipe(last), row["lastHasPipe"])
                self.assertEqual(procedure_eval.has_unquoted_background(last), row["lastHasBackground"])
                self.assertEqual(procedure_eval.is_br6_runner_statement(last, TEST_RE), row["lastIsRealRunner"])
                self.assertEqual(procedure_eval.is_version_or_help_only(last, TEST_RE), row["lastVersionOrHelpOnly"])
                self.assertEqual(procedure_eval.in_safe_br6_grammar(row["command"]), row["inSafeGrammar"])
                self.assertEqual(procedure_eval.br6_trailing_or_run(row["command"]), row["orRun"])
                self.assertEqual(all(procedure_eval.is_br6_runner_statement(s, TEST_RE)
                                     and not procedure_eval.is_version_or_help_only(s, TEST_RE) for s in row["orRun"]),
                                 row["orRunAllRealRunners"])
                runs = procedure_eval.attributable_test_runs(trace_from_carrier(row), TEST_RE)
                self.assertEqual(bool(runs), row["strictAttributable"])
                self.assertEqual(any(run.exit == 0 for run in runs), row["strictTests"] == "satisfied")

    # D25 word and segment model (Task 141). `<bs>` stands for one backslash, built with chr(92).
    VERSION_ONLY_WORDS = (
        "pytest --vers<bs>ion", "pytest -<bs>V", "pytest <bs>--help", 'pytest --ver""sion',
        "pytest $V", 'pytest "$V"', "pytest ~-", "pytest --versio?", "pytest -*", "pytest [--]version",
        "pytest -k test_*",
        "pytest <bs>| --version", "pytest --version>out.txt", "pytest -h>o", "pytest --version&>x",
        "pytest --version<>y",
        "echo pytest && pytest --version", "pytest -V && echo pytest", "true pytest && pytest -V",
        # A runner match inside an earlier quoted assignment value only adds words; it never swallows them.
        "X='a pytest' pytest --version", 'X="a pytest" pytest -V',
    )
    RUNNER_WORDS = (
        'pytest "--<bs>version"', "pytest -k '$V'", "pytest tests/*.py", "pytest ~/x", "pytest -k a<bs>|b",
        'pytest "*"', "pytest <bs>*", "pytest -x", "pytest>out.txt", "pytest -k a<bs>>b", "pytest -k 'a>b'",
        "pytest -V && pytest", "echo pytest && pytest",
    )

    def test_runner_words_follow_bash_quote_removal(self):
        # Mutation: comparing raw words (no quote/backslash removal), splitting only at blanks, treating expansions as
        # literal text, or counting every segment the runner pattern matches, makes a forged version run attributable.
        bs = chr(92)
        version_only = [c.replace("<bs>", bs) for c in self.VERSION_ONLY_WORDS]
        runner = [c.replace("<bs>", bs) for c in self.RUNNER_WORDS]
        for command, expected in [(c, True) for c in version_only] + [(c, False) for c in runner]:
            with self.subTest(command=command):
                self.assertIs(procedure_eval.is_version_or_help_only(command, TEST_RE), expected)
        nbsp_pipe = chr(0xA0) + "#x | pytest | tee log.txt"
        self.assertEqual(procedure_eval.br6_statements(nbsp_pipe), [nbsp_pipe])
        self.assertIs(procedure_eval.has_unquoted_pipe(nbsp_pipe), True)

    # D27 (DP39) lists, shared with the Node tests in test_codex_flow_step_guard.py and test_codex_current_rollout.py.
    # `<bs>`, `<nl>` and `<tab>` stand for a backslash, a newline and a tab; the Unicode blanks are built with chr().
    RUNNER_STATEMENTS = tuple(c.replace("<bs>", chr(92)).replace("<nl>", chr(10)) for c in (
        "pytest", "PYTEST -q", "X=a pytest", "A+=1 pytest", "X=a<bs> b pytest", "X=$V pytest", "npm test",
        "npm run test -- --ci", "pnpm run test", "go test ./...", "cargo test", "python -m pytest",
        "python3.11 -m pytest", "py -3 -m pytest", "python -m unittest", "python3 -m tox", "py -m nox", "tox",
        "echo x | pytest", "echo x & pytest", "pytest > out.txt 2>&1", "pyt<bs><nl>est -q",
    ))
    NON_RUNNER_STATEMENTS = tuple(c.replace("<bs>", chr(92)).replace("<nl>", chr(10)).replace("<tab>", chr(9)) for c in (
        "pytest+=1", "tox+=x", "A=1 pytest+=1", "X=a<bs> pytest",
        "X=a" + chr(0xA0) + "pytest", "X=a" + chr(0x3000) + "pytest", "X=a" + chr(0x2028) + "pytest",
        "X=a" + chr(0xFEFF) + "pytest", "X=a<bs><tab>pytest", "echo <bs>; pytest", "echo <bs>| pytest", "echo pytest",
        "echo x #; pytest", "echo ok <bs><nl>pytest", "X=1<bs><nl>pytest", "2>/dev/null pytest", "pytest.exe",
        "pytest-3 -q", "pytest" + chr(0xA0) + "-q", "npm test+=1", "npm run", "python -m pytest.main",
        "Python -m pytest", "python -m jest", "python -m vitest", "python -m PYTEST", "pyte" + chr(0x17F) + "t",
        "python -m pyte" + chr(0x17F) + "t",
    ))
    OPERAND_OUTSIDE = tuple(c.replace("<nl>", chr(10)) for c in (
        "pytest ||", "pytest &&", "pytest |", "pytest |&", "; pytest", "& pytest", "pytest;;", "pytest; && pytest",
        "true;;<nl>pytest", "pytest &&<nl>", "pytest ||<nl># done", "pytest<nl>;", "pytest &;",
    ))
    OPERAND_INSIDE = tuple(c.replace("<nl>", chr(10)) for c in (
        "pytest;", "pytest &", "pytest ; ", "pytest<nl><nl>", "echo ok &&<nl>pytest", "pytest ||<nl><nl>pytest",
        "> out.txt; pytest", "pytest # ; &&",
    ))

    def test_runner_rule_matches_whole_words(self):
        # Mutations: reading `NAME+=` as a command word, splitting at an escaped `;` or `|`, ending an assignment value
        # at a Unicode or escaped blank, matching with search/match instead of fullmatch (pytest-3, pytest.exe),
        # dropping the ASCII word check or compiling it with re.IGNORECASE (U+017F), dropping the python -m module set,
        # or accepting a redirection word before the command word, each turns a NON_RUNNER entry into a runner.
        for command, expected in ([(c, True) for c in self.RUNNER_STATEMENTS]
                                  + [(c, False) for c in self.NON_RUNNER_STATEMENTS]):
            with self.subTest(command=command):
                self.assertIs(procedure_eval.is_br6_runner_statement(command, TEST_RE), expected)
        for command in ("pytest --version;", "pytest --version\n", "pytest --help # ;"):
            with self.subTest(version=command):
                self.assertIs(procedure_eval.is_version_or_help_only(command, TEST_RE), True)
        # The bound is the longest testCommand alternative in words; an optional group counts at its maximum.
        source = json.loads((REPO / "hooks" / "flow-requirements.json").read_text(encoding="utf-8"))["testCommand"]
        self.assertTrue(source.startswith("\\b(") and source.endswith(")\\b"), source)
        body = source[3:-3]
        alternatives, depth, current, index = [], 0, "", 0
        while index < len(body):
            ch = body[index]
            if ch == "\\":
                current += body[index:index + 2]
                index += 2
                continue
            depth += {"(": 1, ")": -1}.get(ch, 0)
            if ch == "|" and depth == 0:
                alternatives.append(current)
                current = ""
            else:
                current += ch
            index += 1
        alternatives.append(current)
        self.assertEqual(procedure_eval.BR6_RUNNER_MAX_WORDS, max(a.count("\\s+") + 1 for a in alternatives))
        for command in ("npm run test", "pnpm run test", "gradle test", "mvn test", "make test", "yarn test", "go test",
                        "cargo test"):
            with self.subTest(pattern=command):
                self.assertIsNotNone(TEST_RE.fullmatch(command))

    def test_operand_rule_puts_syntax_errors_outside(self):
        # Mutation: dropping either half of the operand rule (an operator after an empty simple command, or an
        # operator still waiting for a word at the end) admits a bash syntax error that runs nothing.
        for command, expected in ([(c, False) for c in self.OPERAND_OUTSIDE]
                                  + [(c, True) for c in self.OPERAND_INSIDE]):
            with self.subTest(command=command):
                self.assertIs(procedure_eval.in_safe_br6_grammar(command), expected)

    # D28 (DP40) lists, shared with the Node tests in test_codex_flow_step_guard.py and test_codex_current_rollout.py.
    # `<bs>` and `<nl>` stand for a backslash and a newline.
    D28_PIPE_NEWLINE_OUTSIDE = tuple(c.replace("<nl>", chr(10)) for c in (
        "true || echo |<nl>pytest", "true || echo |&<nl>pytest", "true || echo | # c<nl>pytest",
        "true || echo |<nl><nl>pytest", "pytest |<nl>pytest", "echo x |& # c<nl>npm test",
    ))
    D28_PIPE_NEWLINE_INSIDE = tuple(c.replace("<bs>", chr(92)).replace("<nl>", chr(10)) for c in (
        "echo ok |<bs><nl>pytest", "echo ok &&<nl>pytest", "pytest ||<nl><nl>pytest", "echo ok | tee log<nl>pytest",
        "echo ok | > out.txt<nl>pytest",
    ))
    D28_RUNNER_STATEMENTS = (
        "py -3 -m pytest", "py -3.13 -m pytest", "py -2 -m pytest", "py -3.99 -m pytest", "npm run test:unit",
        "npm run test-ci -- --coverage", "NPM run test:unit", "npm run test:unit_fast", "pnpm test:e2e",
        "pnpm run test.x", "yarn test:unit", "make test-unit",
    )
    D28_NON_RUNNER_STATEMENTS = (
        "py -0 -m pytest", "py -00 -m pytest", "py -0p -m pytest", "py -4 -m pytest", "py -1 -m pytest",
        "py -03 -m pytest", "py -3. -m pytest", "py -3-64 -m pytest", "py -V:3.13 -m pytest", "python -3 -m pytest",
        "python3 -3.13 -m pytest", "python -0 -m pytest", "python3.13 -3 -m pytest", "npm test:unit",
        "npm run test_unit", "npm run test:", "npm run testing", "yarn run test:unit", "go test-x", "cargo test:x",
        "mvn test-compile", "npm run test:$X",
    )
    # Script words whose non-ASCII letter case-folds (U+017F) or lowercases (U+212A) onto an ASCII letter.
    D28_NON_ASCII_SCRIPT_WORDS = ("npm run test:uni" + chr(0x17F), "npm run test:" + chr(0x212A))
    D28_VERSION_ONLY = (
        "npm test --if-present", "npm run test:nope --if-present", "pytest -Vq", "pytest -qV", "pytest -hq",
        "python -m pytest -qV", "python -m unittest --he", "pytest --version=x", "pytest --help=x", "pytest --usage",
        "npm test -v", "npm run test -v", "npm test -H", "npm test --usage=1", "npm test -hq", "npm test -ddv",
        "npm test -vq", "npm test -qH", "npm test --h", "npm test --hel", "npm test -usage", "npm test --HELP",
        "npm test -x", "npm test -- -v", "pnpm test -v", "yarn test -v", "make test -v", "mvn test -v", "jest -v",
        "npm run test:unit --version", "npm run test:unit -v", "pytest -kh",
    )
    D28_NOT_VERSION_ONLY = (
        "pytest -v", "pytest -qx", "pytest -k test_help", "python -m pytest -v", "tox -v", "go test -v ./...",
        "cargo test -v", "npm test -s", "npm test --silent", "npm test -q", "npm test --quiet", "npm test -d",
        "npm test -ddd", "npm test -- --coverage", "npm run test -- --ci", "npm test help", "pytest --verbose",
        "pytest --co", "make test -j4",
    )

    def test_newline_while_pipe_waits_is_outside(self):
        # Mutation: not returning None at a newline while a `|` or `|&` waits, or not clearing the pipe flag at a
        # word (a redirection target included: `echo ok | > out.txt<nl>pytest`), flips an entry.
        for command, outside in ([(c, True) for c in self.D28_PIPE_NEWLINE_OUTSIDE]
                                 + [(c, False) for c in self.D28_PIPE_NEWLINE_INSIDE]):
            with self.subTest(command=command):
                self.assertIs(procedure_eval.br6_simple_commands(command) is None, outside)
                self.assertIs(procedure_eval.in_safe_br6_grammar(command), not outside)

    def test_d28_runner_words(self):
        # Mutations: a selector after a python word, a `-[0-9.]+` or `-[1-9]` selector (py -0, py -4), no npm k == 3
        # rule (npm test:unit), `_` as a script separator, re.IGNORECASE without re.ASCII (U+017F folds to `s`), lower()
        # before the ASCII script-word check (U+212A lowers to `k`), or match instead of fullmatch.
        for command, expected in ([(c, True) for c in self.D28_RUNNER_STATEMENTS]
                                  + [(c, False) for c in self.D28_NON_RUNNER_STATEMENTS + self.D28_NON_ASCII_SCRIPT_WORDS]):
            with self.subTest(command=command):
                self.assertIs(procedure_eval.is_br6_runner_statement(command, TEST_RE), expected)

    def test_d28_version_and_help_spellings(self):
        # Mutations: dropping the verbose `-v` runner set (pytest -v), applying the package-manager allowlist after
        # `--` (npm test -- --coverage), dropping `--usage` from the prefix list, or adding `--if-present` to the
        # neutral set (npm run test:nope --if-present).
        for command, expected in ([(c, True) for c in self.D28_VERSION_ONLY]
                                  + [(c, False) for c in self.D28_NOT_VERSION_ONLY]):
            with self.subTest(command=command):
                self.assertIs(procedure_eval.is_br6_runner_statement(command, TEST_RE), True)
                self.assertIs(procedure_eval.is_version_or_help_only(command, TEST_RE), expected)


    # D29 (DP41) lists, shared with the Node tests in test_codex_flow_step_guard.py and test_codex_current_rollout.py.
    # Every entry runs a runner. `<bs>` stands for a backslash and `<e9>` for U+00E9.
    D29_TARGET_SEPARATOR_VERSION_ONLY = (
        "npm run test:nope >-- --if-present", "npm run test:nope 2>-- --if-present",
        "npm run test:nope &>-- --if-present", "npm run test:nope >>-- --if-present",
        "npm run test:nope >|-- --if-present", "npm run test:nope >'--' --if-present",
        "npm run test:nope >\"--\" --if-present", "npm run test:nope >-- --if-present=true", "npm test >-- '-?'",
        "npm test 2>-- -x", "pnpm test >-- -x", "yarn test >-- --if-present", "npm run test:unit >-- --if-present",
    )
    D29_TARGET_SEPARATOR_NOT_VERSION_ONLY = (
        "npm test >-- -s", "npm test >--", "npm run test:unit 2>-- -- --coverage", "npm test -- --if-present",
        "npm run test:unit -- '-?'", "npm test >out.txt -- -x", "pnpm test >-- -- --if-present",
    )
    D29_KEY_LETTER_VERSION_ONLY = tuple(c.replace("<bs>", chr(92)).replace("<e9>", chr(0xE9)) for c in (
        "pytest -h1", "pytest -hx1", "pytest -xh1", "pytest -h_", "pytest -h.", "pytest -h/", "pytest -hhhh1",
        "pytest -V1", "pytest -h=x", "pytest -h<bs> x", "pytest -h<e9>", "pytest -1h", "pytest -x1h", "pytest -x1V",
        "pytest -<e9>h", "pytest -kh1", "pytest -pno:cacheprovider", "python -m pytest -xh1", "py -3 -m pytest -h1",
        "python -m unittest -bh_", "python3 -m unittest -h1", "tox -h1", "jest -x1h", "jest -1h", "jest -b_h",
        "vitest run -1h", "vitest run -x1h", "vitest -b_h", "npm test -- -h1", "npm test -- -1h", "npm test -- -v1",
        "npm test -- -x1v", "npm test -- -xH1", "npm test -- -1H", "npm test -H1", "make test -v1", "make test -1v",
        "jest -v1",
    ))
    D29_KEY_LETTER_NOT_VERSION_ONLY = (
        "pytest -v1", "pytest -x1v", "pytest --tb=short", "pytest -rA", "tox -v1", "go test -v1",
        "jest -x1k", "vitest run -rA", "npm test -- -x1k", "npm test -- --watch", "make test -1k",
    )

    def test_d29_redirect_target_and_key_letter(self):
        # Mutations: a redirection target `--` that still ends the package-manager option region (the first list), a
        # redirection target `--` counted as an option word (`npm test >-- -s`), letters required to the end of the
        # word, the key letter required in the leading letter run (`jest -x1h`), or the H or v rule without the
        # any-position change (the third list), or a `--` word matched by the single-dash patterns (the fourth list).
        cases = ([(c, True) for c in self.D29_TARGET_SEPARATOR_VERSION_ONLY + self.D29_KEY_LETTER_VERSION_ONLY]
                 + [(c, False) for c in self.D29_TARGET_SEPARATOR_NOT_VERSION_ONLY
                    + self.D29_KEY_LETTER_NOT_VERSION_ONLY])
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertIs(procedure_eval.is_br6_runner_statement(command, TEST_RE), True)
                self.assertIs(procedure_eval.is_version_or_help_only(command, TEST_RE), expected)

    # D30 (DP42) lists, shared with the Node tests in test_codex_current_rollout.py. Every entry runs a runner.
    # `<bs>` stands for a backslash and `<e9>` for U+00E9. DP42 (a) moved `pytest --h1` here from
    # D29_KEY_LETTER_NOT_VERSION_ONLY (real pytest 8.3.3 exits 4 for it).
    D30_DASH_WORD_VERSION_ONLY = tuple(c.replace("<bs>", chr(92)) for c in (
        "jest ---h", "jest ---help", "jest ---version", "jest ---xh", "jest ---=h", "jest ---.h", "jest ----h",
        "jest ---HELP", "jest ---v", "jest ---", "vitest run ---h", "vitest run ---help", "vitest run ---xh",
        "vitest ---v", "npm test -- ---h", "pytest ---h", "python -m unittest ---help", "tox ---x",
        "jest --help.x", "jest --help.", "jest --help.0", "jest --help.x=1", "jest --h.x", "jest --version.",
        "jest --version-", "jest --version.x", "jest --HELP-", "jest --help-", "jest --hel.x", "jest --usage.x",
        "jest --ver.x", "jest --h1", "vitest run --help.x", "vitest --version.x", "npm test -- --help.x",
        "pnpm test -- --HELP-", "make test --help.x", "pytest --help.x", "pytest --h1", 'pytest "--vers<bs>ion"',
        "python -m pytest --version-", "go test --usage.x",
    ))
    D30_DASH_WORD_NOT_VERSION_ONLY = tuple(c.replace("<bs>", chr(92)).replace("<e9>", chr(0xE9)) for c in (
        "jest --verbose", "jest --no-help", "jest --update-snapshot", "jest --coverage", "jest --1help", "jest --.h",
        "jest --_h", "jest --x-help", "jest --hx", "jest --helpx", "jest --=h", "jest --", "jest --<e9>help",
        "vitest run --no-help", "vitest run --update", "pytest --verbose", "pytest --tb=short",
        'pytest "--<bs>version"', "npm test -- --.h", "npm test -- --no-help", "npm test -- --update-snapshot",
        "npm test -- --1help", "go test --verbose", "make test --no-help",
        # Embedded, non-leading `--<letters>`: both mirrors must anchor the long-option run at the start of the word
        # (a Python `.search`, or a JS pattern without `^`, would read these as help-only and diverge).
        "pytest tests/x--help.py", "pytest a--version",
    ))

    def test_d30_dash_word_shapes(self):
        # Mutations: leaving out the three-dash rule (`jest ---help`), reading a three-dash word as a short-option group
        # (`jest ---version`) or like a two-dash word (`jest ---xh`), requiring letters up to `=` or the end or taking the
        # whole part before `=` (`jest --help.x`), not lowercasing the run (`jest --HELP-`), or taking a letter run that
        # does not start directly after `--` (`jest --1help`, `jest --.h`).
        cases = ([(c, True) for c in self.D30_DASH_WORD_VERSION_ONLY]
                 + [(c, False) for c in self.D30_DASH_WORD_NOT_VERSION_ONLY])
        for command, expected in cases:
            with self.subTest(command=command):
                self.assertIs(procedure_eval.is_br6_runner_statement(command, TEST_RE), True)
                self.assertIs(procedure_eval.is_version_or_help_only(command, TEST_RE), expected)

    # A long cluster word per cluster rule: `h` (help), `v` (version, npm is not a verbose runner) and `H` (package
    # manager, after `--` so the allowlist rule does not decide first). Under DP41 (b) each holds its key letter, so
    # each counts; the D29_NEAR_MISS_WORDS are long single-dash words without the key letter, so none counts.
    D28_NEAR_MISS_CLUSTERS = tuple(prefix + "-" + letter * 100000 + "1"
                                   for prefix, letter in (("pytest ", "h"), ("npm test -- ", "v"), ("npm test -- ", "H")))

    D29_NEAR_MISS_WORDS = tuple(prefix + "-" + letter * 100000 + "1k"
                                for prefix, letter in (("pytest ", "x"), ("npm test -- ", "w"), ("npm test -- ", "G")))

    # D30 long words: a two-dash word whose long letter run is not a prefix, a prefix run with a long non-letter tail,
    # and a word of many leading dashes.
    D30_LONG_WORDS = ("jest --" + "help" * 25000 + ".x", "jest --h" + "." * 100000, "jest " + "-" * 100000 + "h")

    def test_d28_cluster_checks_are_linear(self):
        # Mutations: an end-anchored `-[A-Za-z]*<letter>[A-Za-z]*` pattern backtracks quadratically on the D28 words
        # (seconds per word) and rejects them; a pattern that drops its key letter accepts the D29 words; a long rule
        # that needs letters to the end rejects the second D30 word.
        import time
        for command, expected in ([(c, True) for c in self.D28_NEAR_MISS_CLUSTERS]
                                  + [(c, False) for c in self.D29_NEAR_MISS_WORDS]
                                  + list(zip(self.D30_LONG_WORDS, (False, True, True)))):
            with self.subTest(command=command[:20]):
                start = time.perf_counter()
                self.assertIs(procedure_eval.is_version_or_help_only(command, TEST_RE), expected)
                self.assertLess(time.perf_counter() - start, 1.0)

    def test_simple_commands_follow_the_grammar(self):
        # Mutation: ending an assignment at an escaped blank, splitting a word at an escaped separator, reading
        # `NAME+=` as a word, dropping the redirection marks, or keeping a backslash-newline in a word.
        bs, nl = chr(92), chr(10)

        def word(value, unknown=False, redirect=False):
            return {"value": value, "unknown": unknown, "redirect": redirect}

        def command(assignments, words, op=""):
            return {"assignments": assignments, "words": words, "op": op}

        cases = {
            "X=a" + bs + " pytest": [{"via_or": False, "commands": [command(["X=a" + bs + " pytest"], [])]}],
            "echo " + bs + "; pytest": [{"via_or": False, "commands": [
                command([], [word("echo"), word(";"), word("pytest")])]}],
            "pytest+=1": [{"via_or": False, "commands": [command(["pytest+=1"], [])]}],
            "pytest 2>o --version && echo ok | tee l &": [{"via_or": False, "commands": [
                command([], [word("pytest"), word("2", redirect=True), word("o", redirect=True), word("--version")],
                        "&&"),
                command([], [word("echo"), word("ok")], "|"),
                command([], [word("tee"), word("l")], "&")]}],
            "pytest; X=1" + bs + nl + "pytest": [
                {"via_or": False, "commands": [command([], [word("pytest")])]},
                {"via_or": False, "commands": [command(["X=1pytest"], [])]}],
            "A=1 B+=x" + bs + " y pytest -k 'a b' \"$K\"": [{"via_or": False, "commands": [
                command(["A=1", "B+=x" + bs + " y"],
                        [word("pytest"), word("-k"), word("a b"), word("$K", unknown=True)])]}],
            "true ||" + nl + "# c" + nl + "pytest": [
                {"via_or": False, "commands": [command([], [word("true")])]},
                {"via_or": True, "commands": [command([], [word("pytest")])]}],
            "pytest ||": None,
        }
        for text, expected in cases.items():
            with self.subTest(command=text):
                self.assertEqual(procedure_eval.br6_simple_commands(text), expected)

    def test_strict_attribution_needs_no_node(self):
        # Mutation: classifying through node drops every run (and records strict_runner_classifier_unavailable)
        # when node cannot be found.
        script = (
            "import json, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import scripts.run_procedure_eval as pe\n"
            "verdicts, errors = [], []\n"
            "for events in json.load(sys.stdin):\n"
            "    trace = pe.trace_events(events)\n"
            "    verdicts.append(bool(pe.attributable_test_runs(trace, pe.load_test_re())))\n"
            "    errors += trace.strict_errors\n"
            "print(json.dumps([verdicts, errors]))\n"
        )
        batches = [claude_run("t1", command, False, "1 failed") for command in ("pytest", "pytest; pytest+=1")]
        with tempfile.TemporaryDirectory() as empty:
            env = dict(os.environ, PATH=empty)
            proc = subprocess.run([sys.executable, "-c", script, str(REPO)], input=json.dumps(batches),
                                  capture_output=True, text=True, encoding="utf-8", cwd=empty, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), [[True, False], []])

    def test_safe_grammar_production_lists(self):
        # Mutation: dropping any character or command-word production (each listed construct would be admitted).
        self.assertEqual((len(GRAMMAR_INSIDE), len(GRAMMAR_OUTSIDE)), (33, 96))
        for command, expected in [(c, True) for c in GRAMMAR_INSIDE] + [(c, False) for c in GRAMMAR_OUTSIDE]:
            with self.subTest(command=command):
                self.assertIs(procedure_eval.in_safe_br6_grammar(command), expected)

    def test_integer_attributed_assignments_outside(self):
        # Mutation: dropping any name from the pinned set, or checking only standalone assignments (not prefix or
        # export arguments), admits that name's arithmetic BASH_CMDS write.
        self.assertEqual(procedure_eval.BR6_INTEGER_VARIABLES, INTEGER_VARIABLES)
        for name in sorted(INTEGER_VARIABLES):
            for command in (f"{name}=V; pytest", f"{name}+=V; pytest", f"{name}=V true; pytest",
                            f"export X=1 {name}=V; pytest"):
                with self.subTest(command=command):
                    self.assertIs(procedure_eval.in_safe_br6_grammar(command), False)
        for command in ("SECONDS=V; pytest", "export SECONDS=V PATH=$PATH:bin; pytest", "RANDOMX=V; pytest"):
            with self.subTest(command=command):
                self.assertIs(procedure_eval.in_safe_br6_grammar(command), True)

    def test_statement_joins_carry_oror(self):
        # The values slice B's test_trailing_oror_run_records_the_joining_separator pins for Node (D23 mirror).
        cases = {"cd a; pytest || true": ["pytest", "true"], "echo ok ||\npytest": ["echo ok", "pytest"],
                 "a ||\n# note\nb": ["a", "b"], "a || b; c": ["c"], "a || b\nc": ["c"],
                 "a && b || c": ["a && b", "c"], "pytest -k 'a||b'": ["pytest -k 'a||b'"], "": []}
        for command, run in cases.items():
            with self.subTest(command=command):
                self.assertEqual(procedure_eval.br6_trailing_or_run(command), run)
        # A backslash-newline inside single quotes is data (the Task 125 global replacement removed it).
        self.assertEqual(procedure_eval.br6_statements("'a\\\nb'; pytest"), ["'a\\\nb'", "pytest"])

    def test_grammar_forged_green_run_not_counted(self):
        # Mutation: judging only the last statement lets each forged exit 0 count as GREEN.
        red = claude_run("t1", "python -m pytest -q", True, "1 failed")
        for command in ("python -m pytest -q; echo ${x:-; python -m pytest -q #}", "true || python -m pytest -q",
                        "python -m pytest -q & wait || python -m pytest -q", "set -n; python -m pytest -q"):
            with self.subTest(command=command):
                errors = self.strict_errors(red + claude_run("t2", command, False, "1 failed"))
                self.assertIn("strict_missing_green", errors)
                self.assertIn("strict_test_run_unattributable", errors)
        control = self.strict_errors(red + claude_run("t2", "python -m pytest -q -x || python -m pytest -q --lf", False,
                                                      "2 passed"))
        self.assertNotIn("strict_missing_green", control)
        self.assertNotIn("strict_test_run_unattributable", control)

    def test_safe_grammar_linear(self):
        import time
        floods = ["pytest " + "a;" * 200000, '"' + "x" * 399999, "# " * 200000 + "\npytest", "$a" * 200000,
                  "X=1 " * 100000 + "pytest"]
        started = time.time()
        for text in floods:
            procedure_eval.in_safe_br6_grammar(text)
            procedure_eval.br6_statement_joins(text)
        self.assertLess(time.time() - started, 5.0, "the safe grammar pass must stay linear")

    def test_safe_grammar_boolean_validation_has_bounded_allocation(self):
        import tracemalloc

        command = "pytest a;" * 20000
        tracemalloc.start()
        try:
            self.assertTrue(procedure_eval.in_safe_br6_grammar(command))
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 2 * 1024 * 1024,
                        "boolean validation must not retain per-command parse records")

    def test_double_quote_spans_preserve_grammar_and_statement_boundaries(self):
        cases = [
            ('pytest "a;#||\t\nb"; true', True, [('pytest "a;#||\t\nb"', False), ('true', False)]),
            ('pytest "a\\"b" || true', True, [('pytest "a\\"b"', False), ('true', True)]),
            ('pytest "a\\\nb"; true', True, [('pytest "ab"', False), ('true', False)]),
            ('pytest "$x"', True, [('pytest "$x"', False)]),
            ('pytest "$(', False, [('pytest "$(', False)]),
            ('pytest "\\$(x)"', True, [('pytest "\\$(x)"', False)]),
            ('pytest "`x`"', False, [('pytest "`x`"', False)]),
            ('pytest "a\x01b"', False, [('pytest "a\x01b"', False)]),
            ('pytest "[x]"', True, [('pytest "[x]"', False)]),
            ('echo "[x]"', False, [('echo "[x]"', False)]),
            ('echo "\\[x]"', False, [('echo "\\[x]"', False)]),
            ('pytest "', False, [('pytest "', False)]),
        ]
        for text, accepted, statements in cases:
            with self.subTest(command=text):
                self.assertIs(procedure_eval.in_safe_br6_grammar(text), accepted)
                self.assertIs(procedure_eval.br6_simple_commands(text) is not None, accepted)
                self.assertEqual(procedure_eval.br6_statement_joins(text), statements)

    # Shared literal lists (D21): hooks/codex-rollout.mjs hasUnquotedBackground is checked against the same forms.
    BACKGROUND_TRUE = ("pytest &", "pytest & wait", "pytest&", "cd a && pytest &", "pytest \\&& wait", "pytest \\>& wait",
                       "pytest \\|& wait", "pytest &\\> x")
    BACKGROUND_FALSE = ("pytest && true", "pytest 2>&1", "pytest >&2", "pytest <&0", "pytest &> log.txt",
                        "pytest &>> log.txt", "pytest |& tee log", 'pytest -k "a&b"', "pytest -k 'a&b'", "pytest \\& x",
                        "pytest # & wait")

    def test_has_unquoted_background_operator_forms(self):
        # Mutation: reading raw neighbour characters (an escaped `&`, `>` or `|` would join), or scanning comments.
        for command, expected in [(c, True) for c in self.BACKGROUND_TRUE] + [(c, False) for c in self.BACKGROUND_FALSE]:
            with self.subTest(command=command):
                self.assertIs(procedure_eval.has_unquoted_background(command), expected)

    def test_br6_statements_drop_word_start_comments(self):
        # Mutation: keeping a word-start comment (its `&` or `|` would taint the last statement).
        for command, expected in (("pytest # & wait", ["pytest"]), ("pytest # | tail", ["pytest"]),
                                  ("pytest\n# done", ["pytest"]), ("echo a#b; pytest", ["echo a#b", "pytest"]),
                                  ("pytest '#' x", ["pytest '#' x"])):
            with self.subTest(command=command):
                self.assertEqual(procedure_eval.br6_statements(command), expected)

    def test_background_green_run_not_counted(self):
        # E3 gaming vector: a backgrounded runner's exit is the shell's, so its exit 0 must never count as GREEN.
        red = claude_run("t1", "python -m pytest -q", True, "1 failed")
        for command, forged in (("python -m pytest -q & wait", True), ("python -m pytest -q \\&& wait", True),
                                ("python -m pytest -q 2>&1", False)):
            with self.subTest(command=command):
                errors = self.strict_errors(red + claude_run("t2", command, False, "1 failed"))
                for name in ("strict_missing_green", "strict_test_run_unattributable"):
                    self.assertEqual(name in errors, forged, name)

    def strict_errors(self, events):
        return procedure_eval.evaluate_case(RED_GREEN_CASE, procedure_eval.trace_events(events), REPO, strict=True)

    def test_green_only_fails_missing_red(self):
        # Mutation: accepting GREEN without an earlier RED removes the error.
        errors = self.strict_errors(claude_run("t1", "python -m pytest -q", False, "2 passed"))
        self.assertIn("strict_missing_red_before_green", errors)
        self.assertNotIn("strict_missing_green", errors)

    def test_red_then_green_passes_red_check(self):
        errors = self.strict_errors(
            claude_run("t1", "python -m pytest -q", True, "1 failed") + claude_run("t2", "python -m pytest -q", False, "2 passed")
        )
        for name in ("strict_missing_green", "strict_missing_red_before_green", "strict_test_run_unattributable"):
            self.assertNotIn(name, errors)

    def test_red_hidden_by_echo_not_counted(self):
        # Table row plan-python-m-echo-exit-red-hidden: the echo's exit 0 must not lend a status to the runner.
        errors = self.strict_errors(
            claude_run("t1", "python -m pytest -q; echo EXIT=$?", False, "1 failed\nEXIT=1")
            + claude_run("t2", "python -m pytest -q", False, "2 passed")
        )
        self.assertIn("strict_missing_red_before_green", errors)
        self.assertIn("strict_test_run_unattributable", errors)

    def test_duplicate_result_record_makes_run_unattributable(self):
        duplicated = procedure_eval.trace_events(
            claude_run("t1", "python -m pytest -q", False, "2 passed") + [claude_result("t1", False, "2 passed")]
        )
        self.assertEqual(procedure_eval.attributable_test_runs(duplicated, TEST_RE), [])
        # AC63 counting: a streamed reconstruction plus its full block is one call event.
        streamed = procedure_eval.trace_events(
            stream_tool_use("t2", "Bash", {"command": "python -m pytest -q"})
            + claude_run("t2", "python -m pytest -q", False, "2 passed")
        )
        runs = procedure_eval.attributable_test_runs(streamed, TEST_RE)
        self.assertEqual([run.exit for run in runs], [0])


CODEX_FLOW_EVIDENCE = REPO / "hooks" / "codex-flow-evidence.mjs"
STRICT_EXPORT_PROBE_JS = (
    "import { pathToFileURL } from 'node:url';"
    "let s='';process.stdin.on('data',d=>s+=d).on('end',async()=>{"
    "const q=JSON.parse(s);const m=await import(pathToFileURL(q.module).href);"
    "process.stdout.write(typeof m.isStrictlyAttributable==='function'?'present':'absent');});"
)
STRICT_BATCH_JS = (
    "import { pathToFileURL } from 'node:url';"
    "let s='';process.stdin.on('data',d=>s+=d).on('end',async()=>{"
    "const q=JSON.parse(s);const m=await import(pathToFileURL(q.module).href);"
    "const re=new RegExp(q.testCommand,'i');const out={};"
    "for(const r of q.rows){out[r.id]=m.isStrictlyAttributable(r.carrier,re);}"
    "process.stdout.write(JSON.stringify(out));});"
)


class TestBR6Parity(unittest.TestCase):
    """AC123, AC69: slice B's JS strict attribution and this Python one agree with the shared table.

    Skips only while slice B's export is absent (pre-integration); D4 makes it a must_run from after_B, so a
    lingering skip fails integration. A missing node binary or a crashing probe is a failure, never a skip.
    """

    def run_node(self, script, payload):
        node = shutil.which("node")
        self.assertIsNotNone(node, "node binary missing: the BR6 parity check cannot run")
        proc = subprocess.run([node, "--input-type=module", "-e", script], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, "node parity probe crashed: " + proc.stderr[-400:])
        return proc.stdout

    def test_python_and_js_strict_attribution_agree_on_shared_table(self):
        probe = self.run_node(STRICT_EXPORT_PROBE_JS, {"module": str(CODEX_FLOW_EVIDENCE)}).strip()
        if probe == "absent":
            self.skipTest("slice B isStrictlyAttributable export absent (pre-integration)")
        self.assertEqual(probe, "present", probe)
        rows = load_br6_rows()
        payload = {
            "module": str(CODEX_FLOW_EVIDENCE),
            "testCommand": TEST_RE.pattern,
            "rows": [{"id": row["id"], "carrier": {
                "command": row["command"],
                "callEvents": row["carrier"]["callEvents"],
                "outputRecords": row["carrier"]["outputRecords"],
                "exitCode": row["carrier"]["exitCode"],
            }} for row in rows],
        }
        js_verdicts = json.loads(self.run_node(STRICT_BATCH_JS, payload))
        mismatches = []
        for row in rows:
            expected = row["strictAttributable"]
            python_verdict = bool(procedure_eval.attributable_test_runs(trace_from_carrier(row), TEST_RE))
            wrong = [side for side, verdict in (("js", js_verdicts.get(row["id"])), ("python", python_verdict))
                     if verdict is not expected]
            if wrong:
                mismatches.append(f"{row['id']}:{'both' if len(wrong) == 2 else wrong[0]}")
        self.assertEqual(mismatches, [], "rows where strict attribution disagrees with the table")


AUDIT_CASE = {"id": "audit-probe", "prompt": "probe"}


def auditor_result(tool_id, text, *, agent="agentic-sdlc:implementation-auditor"):
    return [full_tool_use(tool_id, "Agent", {"subagent_type": agent, "prompt": "audit the flow"}),
            claude_result(tool_id, False, text)]


def assistant_text_event(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def audit_errors(errors):
    return sorted(e for e in errors if e.startswith("strict_critical_audit:"))


class TestStrictCriticalAudit(unittest.TestCase):
    """AC68: the last documented implementation-auditor verdict decides; a generic PASS sentence does not."""

    def evaluate(self, events, *, strict=True, trace=None):
        trace = trace or procedure_eval.trace_events(events)
        return procedure_eval.evaluate_case(AUDIT_CASE, trace, REPO, strict=strict)

    def test_partial_then_generic_overall_pass_fails_named(self):
        # Mutation: letting any later "PASS" word supersede the verdict removes both errors.
        errors = self.evaluate(auditor_result("a1", "overallStatus: PARTIAL\nfinalDecision: block-final (spec gap)")
                               + [assistant_text_event("Overall: PASS")])
        self.assertEqual(audit_errors(errors), ["strict_critical_audit:finalDecision=block-final",
                                                "strict_critical_audit:overallStatus=PARTIAL"])

    def test_report_heading_form_partial_fails_named(self):
        # Codex path: the report arrives only as assistant text (no tool_result carrier).
        report = ("# Implementation Control Report\n\n## Overall Status\n\nPARTIAL\n\n## Checked Flow\n- [x] Spec\n\n"
                  "## Final Decision\nblock-final: the security review result is missing\n")
        trace = procedure_eval.trace_events([assistant_message(report)], strict=True)
        self.assertEqual(audit_errors(self.evaluate([], trace=trace)),
                         ["strict_critical_audit:finalDecision=block-final",
                          "strict_critical_audit:overallStatus=PARTIAL"])

    def test_fail_status_fails_named(self):
        errors = self.evaluate(auditor_result("a1", "- `overallStatus`: **FAIL**\n- `finalDecision`: allow-final"))
        self.assertEqual(audit_errors(errors), ["strict_critical_audit:overallStatus=FAIL"])

    def test_block_final_with_pass_status_fails_named(self):
        errors = self.evaluate(auditor_result("a1", '{"overallStatus": "PASS", "finalDecision": "block-final"}'))
        self.assertEqual(audit_errors(errors), ["strict_critical_audit:finalDecision=block-final"])

    def test_later_full_pass_verdict_supersedes_partial(self):
        errors = self.evaluate(auditor_result("a1", "overallStatus: PARTIAL\nfinalDecision: block-final")
                               + auditor_result("a2", "overallStatus: PASS\nfinalDecision: allow-final"))
        self.assertEqual(audit_errors(errors), [])

    def test_verdict_quoted_inside_spec_write_does_not_count(self):
        write = full_tool_use("w1", "Write", {"file_path": "docs/agentic-sdlc/specs/x.md",
                                               "content": "The auditor may report overallStatus: PARTIAL."})
        self.assertEqual(audit_errors(self.evaluate([write])), [])

    def test_default_mode_has_no_critical_audit_check(self):
        errors = self.evaluate(auditor_result("a1", "overallStatus: PARTIAL\nfinalDecision: block-final"), strict=False)
        self.assertEqual(audit_errors(errors), [])

    def test_raw_line_separator_inside_auditor_result_keeps_the_verdict(self):  # D25 model (4), QUAL-4
        # Mutation: splitting the transcript with str.splitlines (U+2028 ends a line there, so the auditor record is
        # dropped and the FAIL verdict vanishes).
        with tempfile.TemporaryDirectory() as td:
            eval_set = Path(td) / "eval.json"
            eval_set.write_text(json.dumps({"cases": [AUDIT_CASE]}), encoding="utf-8")
            events = auditor_result("a1", "- `overallStatus`: **FAIL**" + chr(0x2028) + "- `finalDecision`: allow-final")
            transcript = Path(td) / "t.jsonl"
            transcript.write_bytes("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events).encode("utf-8"))
            self.assertIn(chr(0x2028).encode("utf-8"), transcript.read_bytes())
            code, stdout = run_main(["--eval-set", eval_set, "--transcript", transcript, "--strict-evidence"])
        self.assertEqual(code, 1)
        self.assertIn("error=audit-probe:strict_critical_audit:overallStatus=FAIL", stdout.splitlines())


AUDITOR_PARTIAL = "overallStatus: PARTIAL\nfinalDecision: block-final"
AUDITOR_PASS = "overallStatus: PASS\nfinalDecision: allow-final"
CONTROL_SKILL_TEMPLATE = "# Implementation Control Report\n\n## Overall Status\nPASS / PARTIAL / FAIL\n"
PARTIAL_REPORT = "# Implementation Control Report\n\n## Overall Status\nPARTIAL\n\n## Final Decision\nblock-final\n"
BOTH_CRITICAL = ["strict_critical_audit:finalDecision=block-final", "strict_critical_audit:overallStatus=PARTIAL"]


class TestStrictAuditorCarriers(unittest.TestCase):
    """AC68 (D21): auditor verdict carriers are scoped per runtime, so the model under test cannot override an audit."""

    def verdict(self, events):
        return procedure_eval.latest_auditor_verdict(procedure_eval.trace_events(events))

    def critical(self, trace):
        return audit_errors(procedure_eval.evaluate_case(AUDIT_CASE, trace, REPO, strict=True))

    def skill_result(self, tool_id, text):
        return [full_tool_use(tool_id, "Skill", {"skill": "agentic-sdlc:implementation-control"}),
                claude_result(tool_id, False, text)]

    def test_claude_main_loop_pass_does_not_override_auditor_partial(self):
        # Probe P2. Mutation: counting main-loop assistant text after an auditor result lets PASS win.
        events = auditor_result("a1", AUDITOR_PARTIAL) + [assistant_text_event(AUDITOR_PASS)]
        self.assertEqual(self.verdict(events), ("PARTIAL", "block-final"))
        self.assertEqual(self.critical(procedure_eval.trace_events(events)), BOTH_CRITICAL)

    def test_claude_other_sub_agent_result_is_not_a_carrier(self):
        # Probe P3b. Mutation: a substring match on the dispatch input makes a general-purpose result a carrier.
        other = [full_tool_use("g1", "Agent", {"subagent_type": "general-purpose", "prompt": "act as implementation-auditor"}),
                 claude_result("g1", False, AUDITOR_PASS)]
        with self.subTest(case="alone"):
            self.assertEqual(self.verdict(other), (None, None))
        with self.subTest(case="after-auditor-partial"):
            self.assertEqual(self.verdict(auditor_result("a1", AUDITOR_PARTIAL) + other), ("PARTIAL", "block-final"))

    def test_claude_skill_result_text_is_not_a_carrier(self):
        # Probe P3d. Mutation: reading the implementation-control skill body, whose template line reads as PASS.
        with self.subTest(case="after-auditor-partial"):
            events = auditor_result("a1", AUDITOR_PARTIAL) + self.skill_result("k1", CONTROL_SKILL_TEMPLATE)
            self.assertEqual(self.verdict(events), ("PARTIAL", "block-final"))
        with self.subTest(case="alone"):
            self.assertEqual(self.verdict(self.skill_result("k1", CONTROL_SKILL_TEMPLATE)), (None, None))

    # ---- guards: pass before and after the carrier scoping ----
    def test_claude_skill_path_main_loop_partial_fails_named(self):
        """D21 rule (2): on the Skill-only control path no auditor result exists, so the main loop's own verdict is
        read. A critical verdict written by the main loop there still fails (the self-authored AC39 limit)."""
        events = self.skill_result("k1", "skill loaded") + [assistant_text_event(AUDITOR_PARTIAL)]
        self.assertEqual(self.critical(procedure_eval.trace_events(events)), BOTH_CRITICAL)

    def test_claude_main_loop_read_when_auditor_result_has_no_verdict(self):
        events = auditor_result("a1", "done") + [assistant_text_event("overallStatus: PARTIAL")]
        self.assertEqual(self.critical(procedure_eval.trace_events(events)), ["strict_critical_audit:overallStatus=PARTIAL"])

    def test_codex_carriers_are_assistant_messages_last_verdict_decides(self):
        user_partial = rollout({"type": "message", "role": "user", "content": [{"type": "input_text", "text": AUDITOR_PARTIAL}]})
        final_partial = rollout({"type": "task_complete", "last_agent_message": PARTIAL_REPORT}, "event_msg")
        cases = (
            ("assistant-partial-then-pass", [assistant_message(PARTIAL_REPORT), assistant_message(CONTROL_REPORT)], []),
            ("partial-only-in-exec-output", [exec_call("c1", "cat report.md"), exec_output("c1", 0, AUDITOR_PARTIAL),
                                             assistant_message("done")], []),
            ("partial-only-in-user-message", [user_partial, assistant_message("done")], []),
            ("pass-then-task-complete-partial", [assistant_message(CONTROL_REPORT), final_partial], BOTH_CRITICAL),
        )
        for label, events, expected in cases:
            with self.subTest(case=label):
                trace = procedure_eval.trace_events(events, strict=True)
                self.assertEqual(trace.runtime, "codex-rollout")
                self.assertEqual(self.critical(trace), expected)


STRICT_ORDER = ["dispatch-strategy", "spec-written", "plan-written", "core-read", "red-run", "green-run", "security",
                "control", "completion-claim-gate"]  # contract C7/C15.10: core-skill is gone, core-read joins
SECURITY_REVIEWER = {"step": "security", "skills": [], "agents": ["security-reviewer"], "codex_result": "findings-table"}
CONTROL_REVIEWER = {"step": "control", "skills": [], "agents": ["implementation-auditor"],
                    "codex_result": "control-verdict"}
# Skill membership is still a grader mechanism (no pipeline case uses it after C7); these probes keep it exercised.
SKILL_LISTING_SECURITY_REVIEWER = dict(SECURITY_REVIEWER, skills=["agentic-sdlc:security-audit"])
FINDINGS_TABLE = ("Severity | Category | File:Line | Risk | Recommendation\n|---|---|---|---|---|\n"
                  "| Low | Input handling | greeting.py:3 | Suffix is not length-bounded | Keep as is for the fixture |")
CONTROL_REPORT = "# Implementation Control Report\n\n## Overall Status\nPASS\n\n## Final Decision\nallow-final\n"


def reviewer_case(*reviewers, required_order=None):
    strict = {"reviewers": list(reviewers)}
    if required_order is not None:
        strict["required_order"] = required_order
    return {"id": "reviewer-probe", "prompt": "probe", "strict": strict}


def reviewer_errors(errors):
    return sorted(e for e in errors if e.startswith("strict_reviewer_result_"))


class TestStrictReviewerOrder(unittest.TestCase):
    """AC70, AC123: reviewer results, required step order and artifact depth under --strict-evidence."""

    def evaluate(self, case, trace):
        return procedure_eval.evaluate_case(case, trace, REPO, strict=True)

    def test_both_pipeline_cases_carry_valid_strict_config(self):
        # Contract C7: cases 1 and 2 carry the full strict object literally (case 2 keeps check_artifact_depth true).
        cases = procedure_eval.load_eval(REPO / PIPELINE_EVAL)
        self.assertEqual(len(cases), 2)
        self.assertEqual([case["id"] for case in cases], list(PIPELINE_CASES))
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertIn("strict", case)
                self.assertEqual(case["strict"], C7_FULL_RUN_STRICT)
                self.assertEqual(case["strict"]["required_order"], STRICT_ORDER)
                self.assertEqual(case["strict"]["reviewers"], [SECURITY_REVIEWER, CONTROL_REVIEWER])

    def test_missing_reviewer_result_fails_named(self):
        trace = procedure_eval.trace_events([full_tool_use("s1", "Agent", {"subagent_type": "agentic-sdlc:security-reviewer"})])
        self.assertEqual(reviewer_errors(self.evaluate(reviewer_case(SECURITY_REVIEWER), trace)),
                         ["strict_reviewer_result_missing:security"])

    def test_errored_reviewer_result_fails_named(self):
        trace = procedure_eval.trace_events([
            full_tool_use("a1", "Agent", {"subagent_type": "agentic-sdlc:implementation-auditor"}),
            claude_result("a1", True, "auditor crashed"),
        ])
        self.assertEqual(reviewer_errors(self.evaluate(reviewer_case(CONTROL_REVIEWER), trace)),
                         ["strict_reviewer_result_errored:control"])

    def test_mixed_member_success_clears_step(self):
        """One member dispatch with exactly one non-error result clears the step.

        Accepted limit: a Claude Skill load returns a non-error result and counts as a member result under the
        BR6 identity (spec), so a clean Skill result alone would also clear the step.
        """
        trace = procedure_eval.trace_events([
            full_tool_use("k1", "Skill", {"skill": "agentic-sdlc:security-audit"}),
            claude_result("k1", True, "skill failed to load"),
            full_tool_use("s1", "Agent", {"subagent_type": "agentic-sdlc:security-reviewer"}),
            claude_result("s1", False, FINDINGS_TABLE),
        ])
        self.assertEqual(reviewer_errors(self.evaluate(reviewer_case(SKILL_LISTING_SECURITY_REVIEWER), trace)), [])

    def test_codex_reviewer_result_read_from_documented_output(self):
        """Codex has no reviewer dispatch or result event (AC39): the documented reviewer output clears the step.

        Accepted limit: a live Codex security review that reports a clean result without the documented table
        header fails strict_reviewer_result_missing:security, a visible FAIL, never a false PASS.
        """
        case = reviewer_case(SECURITY_REVIEWER, CONTROL_REVIEWER)
        complete = procedure_eval.trace_events(
            [assistant_message(FINDINGS_TABLE), assistant_message(CONTROL_REPORT)], strict=True)
        self.assertEqual(complete.runtime, "codex-rollout")
        self.assertEqual(reviewer_errors(self.evaluate(case, complete)), [])
        no_table = procedure_eval.trace_events(
            [assistant_message("Codex Adapter Gate: security-reviewer"), assistant_message(CONTROL_REPORT)], strict=True)
        self.assertEqual(reviewer_errors(self.evaluate(case, no_table)), ["strict_reviewer_result_missing:security"])

    def test_codex_never_reports_errored(self):
        trace = procedure_eval.trace_events(
            [assistant_message("Codex Adapter Gate: security-reviewer"),
             exec_call("c1", "python -m pytest -q"), exec_output("c1", 1, "1 failed\n")], strict=True)
        errors = self.evaluate(reviewer_case(SECURITY_REVIEWER, CONTROL_REVIEWER), trace)
        self.assertFalse([e for e in errors if e.startswith("strict_reviewer_result_errored:")], errors)
        self.assertEqual(reviewer_errors(errors), ["strict_reviewer_result_missing:control",
                                                   "strict_reviewer_result_missing:security"])

    def test_reordered_steps_fail_named(self):
        # Mutation: comparing only adjacent ids, or dropping the order check, removes the violation.
        events = [
            full_tool_use("d1", "Skill", {"skill": "agentic-sdlc:dispatch-strategy"}), claude_result("d1", False, "ok"),
            full_tool_use("w1", "Write", {"file_path": "docs/agentic-sdlc/specs/x.md", "content": "spec"}),
            full_tool_use("w2", "Write", {"file_path": "docs/agentic-sdlc/plans/x.md", "content": "plan"}),
            full_tool_use("cr1", "Read", {"file_path": "/opt/agentic-sdlc/skills/feature-build/references/core.md"}),
            claude_result("cr1", False, "# feature-build - work-type core"),
            full_tool_use("s1", "Agent", {"subagent_type": "agentic-sdlc:security-reviewer"}),
            claude_result("s1", False, FINDINGS_TABLE),
            *claude_run("r1", "python -m pytest -q", True, "1 failed"),
            *claude_run("g1", "python -m pytest -q", False, "2 passed"),
            full_tool_use("a1", "Agent", {"subagent_type": "agentic-sdlc:implementation-auditor"}),
            claude_result("a1", False, "overallStatus: PASS\nfinalDecision: allow-final"),
            full_tool_use("c1", "Skill", {"skill": "agentic-sdlc:completion-claim-gate"}), claude_result("c1", False, "ok"),
        ]
        errors = self.evaluate(reviewer_case(SECURITY_REVIEWER, CONTROL_REVIEWER, required_order=STRICT_ORDER),
                               procedure_eval.trace_events(events))
        self.assertTrue([e for e in errors if e.startswith("strict_order_violation:")], errors)
        self.assertIn("strict_order_violation:red-run->security", errors)
        self.assertFalse([e for e in errors if e.startswith("strict_step_missing:")], errors)

    def test_invalid_strict_config_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            eval_set = Path(td) / "eval.json"
            eval_set.write_text(json.dumps({"cases": [
                {"id": "bogus-order", "prompt": "p", "strict": {"required_order": ["bogus"]}}
            ]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"strict\.required_order"):
                procedure_eval.load_eval(eval_set)


class TestStrictReviewerMembership(unittest.TestCase):
    """AC70 (D21): strict reviewer membership reads the exact subagent_type and skill fields, never a substring."""

    def dispatch_errors(self, name, input_obj, reviewers):
        trace = procedure_eval.trace_events([full_tool_use("m1", name, input_obj), claude_result("m1", False, "done")])
        return procedure_eval.reviewer_result_errors(trace, reviewers)

    def test_general_purpose_agent_naming_reviewers_is_not_a_member(self):
        # Probe P3. Mutation: a substring search over the JSON input clears both steps from the prompt text.
        errors = self.dispatch_errors("Agent", {"subagent_type": "general-purpose",
                                                "prompt": "act as security-reviewer and implementation-auditor"},
                                      [SECURITY_REVIEWER, CONTROL_REVIEWER])
        self.assertEqual(errors, ["strict_reviewer_result_missing:security", "strict_reviewer_result_missing:control"])

    def test_skill_args_naming_reviewer_skill_is_not_a_member(self):
        # Probe P3c. Mutation: matching the reviewer skill name anywhere in the Skill input (here: args).
        errors = self.dispatch_errors("Skill", {"skill": "agentic-sdlc:feature-build", "args": "then run security-audit"},
                                      [SKILL_LISTING_SECURITY_REVIEWER])
        self.assertEqual(errors, ["strict_reviewer_result_missing:security"])

    def test_agent_type_must_equal_listed_agent_or_house_prefix(self):
        # Mutation: prefix/suffix matching, a foreign namespace, or reading description instead of subagent_type.
        missing = ["strict_reviewer_result_missing:security"]
        for input_obj, expected in (({"subagent_type": "security-reviewer"}, []),
                                    ({"subagent_type": "agentic-sdlc:security-reviewer"}, []),
                                    ({"subagent_type": "other-plugin:security-reviewer"}, missing),
                                    ({"subagent_type": "security-reviewer-lite"}, missing),
                                    ({"description": "security-reviewer"}, missing)):
            with self.subTest(input=input_obj):
                self.assertEqual(self.dispatch_errors("Agent", input_obj, [SECURITY_REVIEWER]), expected)

    def test_skill_field_must_equal_listed_skill_or_short_name(self):
        # Mutation: accepting any skill that merely starts with or contains the listed name.
        missing = ["strict_reviewer_result_missing:security"]
        for skill, expected in (("agentic-sdlc:security-audit", []), ("security-audit", []),
                                ("agentic-sdlc:security-audit-extra", missing)):
            with self.subTest(skill=skill):
                self.assertEqual(self.dispatch_errors("Skill", {"skill": skill}, [SKILL_LISTING_SECURITY_REVIEWER]),
                                 expected)


PACKET_CASE = "agentic-sdlc-pipeline-feature-no-commit"
BASIC_FIXTURE = REPO / "tests" / "fixtures" / "agentic-sdlc-pipeline-basic"
BUILD_RELEASE = REPO / "scripts" / "build_release.py"
UNAVAILABLE_IDENTITIES = {
    "unavailable:no-git-checkout",
    "unavailable:build-release-absent",
    "unavailable:build-release-api-missing",
    "unavailable:build-release-failed",
}
PACKET_FIELDS = {
    "schema_version", "case_id", "runtime", "cli_version", "model", "effort", "git_commit",
    "runtime_payload_identity", "fixture_hash", "spec_sha256", "plan_sha256", "terminal_status", "errors",
    "scoring_source", "procedure_row_scorable", "transcript_path", "helper_paths",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def strict_replay(evidence, fixture_root, *, transcript=PASS_TRANSCRIPT, case_id=PACKET_CASE, eval_set=PIPELINE_EVAL):
    return run_cli("--eval-set", eval_set, "--transcript", transcript, "--case-id", case_id, "--strict-evidence",
                   "--evidence-dir", evidence, "--fixture-root", fixture_root)


def stub_build_release(**attributes):
    module = types.ModuleType("build_release")
    for name, value in attributes.items():
        setattr(module, name, value)
    # Patch the exact loader `_payload_identity` calls. A sys.modules patch alone is defeated once any real import
    # has bound `build_release` as an attribute of the `scripts` package (e.g. test_release_distribution at load).
    return mock.patch.object(procedure_eval, "_import_build_release", lambda: module)


class TestEvidencePacket(unittest.TestCase):
    """AC65, AC66, AC67, AC124, AC128: masked, contained evidence packets with the scoring source."""

    def copy_fixture_root(self, td):
        root = Path(td) / "fixture"
        shutil.copytree(BASIC_FIXTURE, root)
        return root

    def test_build_release_import_survives_a_shadowing_namespace_package(self):
        """A foreign `scripts` namespace package (e.g. pywin32) must not make the payload identity unavailable.

        `from scripts import build_release` then raises ImportError, not ModuleNotFoundError, so a fallback that
        catches only ModuleNotFoundError leaves every packet with `unavailable:build-release-failed` (D11 blocks
        scoring on it). Mutation: narrow the except clause back to ModuleNotFoundError.
        """
        with tempfile.TemporaryDirectory() as td:
            shadow = Path(td) / "site-packages"
            (shadow / "scripts").mkdir(parents=True)  # a namespace package without build_release
            saved_path = list(sys.path)
            saved_modules = {name: sys.modules.pop(name)
                             for name in ("scripts", "scripts.build_release", "build_release")
                             if name in sys.modules}
            # The CLI runs as `python3 scripts/run_procedure_eval.py`, so the repository root is NOT on sys.path;
            # only its scripts directory is. Reproduce that, then add the foreign namespace portion.
            roots = {str(REPO), str(REPO) + os.sep, os.getcwd(), ""}
            sys.path[:] = [p for p in sys.path if p not in roots]
            sys.path.insert(0, str(REPO / "scripts"))
            sys.path.insert(0, str(shadow))
            try:
                with self.assertRaises(ImportError) as raised:
                    from scripts import build_release  # noqa: F401
                self.assertNotIsInstance(raised.exception, ModuleNotFoundError)
                module = procedure_eval._import_build_release()
                self.assertTrue(callable(getattr(module, "release_members", None)))
                self.assertTrue(callable(getattr(module, "payload_identity", None)))
            finally:
                sys.path[:] = saved_path
                for name in ("scripts", "scripts.build_release", "build_release"):
                    sys.modules.pop(name, None)
                sys.modules.update(saved_modules)

    def test_secret_split_across_stream_chunks_is_not_recoverable(self):
        """SEC-1: the copy must not hold a secret that only appears once the stream block is reassembled.

        The token is assembled at runtime (never a literal in this file) in a classic PAT shape the HIGH patterns
        match. Mutation: redact per JSON record only, which leaves the joined chunks recoverable.
        """
        token = "ghp_" + "A1b2" * 9
        chunks = [token[:7], token[7:19], token[19:]]

        def chunk_line(index, piece):
            return json.dumps({"type": "stream_event", "session_id": "s1", "parent_tool_use_id": None,
                               "event": {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": piece}}})

        lines = [json.dumps({"type": "stream_event", "session_id": "s1", "parent_tool_use_id": None,
                             "event": {"type": "content_block_start", "index": 0}})]
        lines += [chunk_line(i, piece) for i, piece in enumerate(chunks)]
        lines.append(json.dumps({"type": "stream_event", "session_id": "s1", "parent_tool_use_id": None,
                                 "event": {"type": "content_block_stop", "index": 0}}))
        copy = procedure_eval.redact_transcript_lines("\n".join(lines) + "\n")

        joined_text = "".join(
            json.loads(line)["event"]["delta"]["text"]
            for line in copy.split("\n")
            if line.strip() and json.loads(line).get("event", {}).get("type") == "content_block_delta"
        )
        self.assertNotIn(token, copy)
        self.assertNotIn(token, joined_text, "the reassembled block still holds the secret")
        for line in copy.split("\n"):
            if line.strip():
                json.loads(line)  # every line still parses

    def test_same_record_secret_is_still_redacted(self):
        """Control: the per-record pass keeps working, so the block pass is additive."""
        token = "ghp_" + "C3d4" * 9
        line = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": token}]}})
        copy = procedure_eval.redact_transcript_lines(line + "\n")
        self.assertNotIn(token, copy)

    def test_packet_contains_required_bindings(self):
        with tempfile.TemporaryDirectory() as td:
            evidence = Path(td) / "ev"
            proc = strict_replay(evidence, self.copy_fixture_root(td))
            packet_path = evidence / f"{PACKET_CASE}.json"
            self.assertTrue(packet_path.is_file(), proc.stdout + proc.stderr)
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            self.assertLessEqual(PACKET_FIELDS, set(packet))
            self.assertEqual((packet["schema_version"], packet["case_id"]), (1, PACKET_CASE))
            # QUAL-15: the pass transcript is a Claude stream, and its strict replay fails (its spec and plan are the
            # shallow "spec"/"plan" stubs, so the strict depth check reports them).
            self.assertEqual(packet["runtime"], "claude")
            self.assertIn(f"case_{PACKET_CASE}=failed", proc.stdout.splitlines())
            self.assertEqual(packet["terminal_status"], "failed")
            identity = packet["runtime_payload_identity"]
            self.assertEqual(set(identity), {"definition", "commit", "sha256"})
            self.assertEqual(identity["commit"], packet["git_commit"])
            self.assertTrue(HEX64.match(identity["sha256"]) or identity["sha256"] in UNAVAILABLE_IDENTITIES, identity)
            self.assertEqual(identity["sha256"] == "unavailable:build-release-absent", not BUILD_RELEASE.exists())
            self.assertEqual((packet["scoring_source"], packet["procedure_row_scorable"]), ("transcript-replay", True))
            self.assertIn(packet["terminal_status"], {"passed", "failed"})
            self.assertFalse(os.path.isabs(packet["transcript_path"]))
            self.assertTrue((evidence / packet["transcript_path"]).is_file())
            self.assertTrue(packet["helper_paths"])
            for helper in packet["helper_paths"]:
                self.assertEqual(set(helper), {"path", "sha256"})
                self.assertFalse(os.path.isabs(helper["path"]), helper)
                self.assertTrue(HEX64.match(helper["sha256"]), helper)

    def test_packet_identity_equals_build_release_output(self):
        if not BUILD_RELEASE.exists():
            self.skipTest("scripts/build_release.py absent (slice D pre-integration)")
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run([sys.executable, "scripts/build_release.py", "--output", str(Path(td) / "a.zip")],
                                  cwd=REPO, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        fields = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
        self.assertEqual(procedure_eval.runtime_payload_identity_for_commit(fields["source_commit"], cache={}),
                         fields["runtime_payload_identity"])

    def test_identity_uses_commit_tree_function_not_archive_build(self):
        calls = []

        def release_members(repo_root, commit):
            calls.append((Path(repo_root), commit))
            return {"a.txt": b"a", "b.txt": b"b"}

        def build_archive(*_args, **_kwargs):
            raise AssertionError("the packet identity must not build a release archive")

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(procedure_eval, "BUILD_RELEASE_SCRIPT", REPO / "scripts" / "run_procedure_eval.py"), \
                stub_build_release(release_members=release_members, payload_identity=lambda members, exclude: "ab" * 32,
                                   RUNTIME_PAYLOAD_EXCLUDE=frozenset(), build_archive=build_archive):
            evidence = Path(td) / "ev"
            code, _stdout = run_main(["--eval-set", PIPELINE_EVAL, "--transcript", PASS_TRANSCRIPT, "--strict-evidence",
                                      "--evidence-dir", evidence, "--fixture-root", self.copy_fixture_root(td)])
            packets = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(evidence.glob("*.json"))]
        self.assertEqual(len(packets), 2, _stdout)
        self.assertEqual({p["runtime_payload_identity"]["sha256"] for p in packets}, {"ab" * 32})
        self.assertEqual(calls, [(procedure_eval.REPO, packets[0]["git_commit"])])

    def test_packet_commit_resolved_once_and_bound_to_identity(self):
        """AC65, D21: one resolved commit feeds both the packet's git_commit and its payload identity.

        Mutation: resolving HEAD again inside build_evidence_packet records a second commit ("b" * 40) that the
        identity does not cover, and calls repository_commit twice.
        """
        answers = iter(["a" * 40, "b" * 40])
        resolved = []

        def repository_commit():
            value = next(answers, "c" * 40)
            resolved.append(value)
            return value

        member_commits = []

        def release_members(repo_root, commit):
            member_commits.append(commit)
            return {"a.txt": b"a"}

        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(procedure_eval, "repository_commit", side_effect=repository_commit), \
                mock.patch.object(procedure_eval, "BUILD_RELEASE_SCRIPT", REPO / "scripts" / "run_procedure_eval.py"), \
                stub_build_release(release_members=release_members, payload_identity=lambda members, exclude: "ab" * 32,
                                   RUNTIME_PAYLOAD_EXCLUDE=frozenset()):
            evidence = Path(td) / "ev"
            _code, stdout = run_main(["--eval-set", PIPELINE_EVAL, "--transcript", PASS_TRANSCRIPT,
                                      "--case-id", PACKET_CASE, "--strict-evidence", "--evidence-dir", evidence,
                                      "--fixture-root", self.copy_fixture_root(td)])
            packet = json.loads((evidence / f"{PACKET_CASE}.json").read_text(encoding="utf-8"))
        self.assertEqual(resolved, ["a" * 40], stdout)
        self.assertEqual(packet["git_commit"], "a" * 40)
        self.assertEqual(packet["runtime_payload_identity"]["commit"], "a" * 40)
        self.assertEqual(member_commits, ["a" * 40])

    def test_identity_fallback_when_build_release_absent(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(procedure_eval, "BUILD_RELEASE_SCRIPT", Path(td) / "missing.py"):
            self.assertEqual(procedure_eval.runtime_payload_identity_for_commit("0" * 40, cache={}),
                             "unavailable:build-release-absent")
        self.assertEqual(procedure_eval.runtime_payload_identity_for_commit("unavailable:no-git-checkout", cache={}),
                         "unavailable:no-git-checkout")

    def test_identity_api_missing_is_named(self):
        def raising_members(repo_root, commit):
            raise ValueError("BR13 member violation")

        variants = (
            ("api-missing", {"payload_identity": lambda m, e: "ab" * 32, "RUNTIME_PAYLOAD_EXCLUDE": frozenset()},
             "unavailable:build-release-api-missing"),
            ("raises", {"release_members": raising_members, "payload_identity": lambda m, e: "ab" * 32,
                        "RUNTIME_PAYLOAD_EXCLUDE": frozenset()}, "unavailable:build-release-failed"),
            ("not-hex", {"release_members": lambda r, c: {}, "payload_identity": lambda m, e: "not-a-digest",
                         "RUNTIME_PAYLOAD_EXCLUDE": frozenset()}, "unavailable:build-release-failed"),
        )
        for label, attributes, expected in variants:
            with self.subTest(stub=label), \
                    mock.patch.object(procedure_eval, "BUILD_RELEASE_SCRIPT", REPO / "scripts" / "run_procedure_eval.py"), \
                    stub_build_release(**attributes):
                self.assertEqual(procedure_eval.runtime_payload_identity_for_commit("0" * 40, cache={}), expected)

    def test_stub_wins_after_real_build_release_import_in_same_process(self):
        # Order-independent regression: an earlier `scripts.build_release` import binds the submodule as a `scripts`
        # package attribute, which `from scripts import build_release` returns ahead of sys.modules. Hermetic: a decoy
        # bound on that attribute stands in for the real import, so no real module is loaded and nothing is skipped.
        # The stub must still control exactly the loader `_payload_identity` uses.
        decoy = types.ModuleType("build_release")
        decoy.release_members = lambda repo_root, commit: {}
        decoy.payload_identity = lambda members, exclude: "ef" * 32
        decoy.RUNTIME_PAYLOAD_EXCLUDE = frozenset()
        scripts_package = sys.modules["scripts"]
        with mock.patch.object(scripts_package, "build_release", decoy, create=True), \
                mock.patch.object(procedure_eval, "BUILD_RELEASE_SCRIPT", REPO / "scripts" / "run_procedure_eval.py"):
            from scripts import build_release as bound
            self.assertIs(bound, decoy)  # precondition: the package attribute wins over sys.modules
            with stub_build_release(release_members=lambda repo_root, commit: {},
                                    payload_identity=lambda m, e: "cd" * 32, RUNTIME_PAYLOAD_EXCLUDE=frozenset()):
                self.assertEqual(procedure_eval.runtime_payload_identity_for_commit("0" * 40, cache={}), "cd" * 32)

    def test_identity_loader_raising_is_named_failed(self):
        # Mutation: narrowing the loader's `except Exception` (a SyntaxError in build_release.py) lets the eval crash.
        with mock.patch.object(procedure_eval, "BUILD_RELEASE_SCRIPT", REPO / "scripts" / "run_procedure_eval.py"), \
                mock.patch.object(procedure_eval, "_import_build_release", side_effect=SyntaxError("broken module")):
            self.assertEqual(procedure_eval.runtime_payload_identity_for_commit("0" * 40, cache={}),
                             "unavailable:build-release-failed")

    def test_traversal_non_slug_and_reserved_case_ids_write_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            evidence = parent / "ev"
            for case_id, expected in (("../escape", "evidence_case_id_invalid"), ("Bad_Id", "evidence_case_id_invalid"),
                                      ("specs", "evidence_case_id_reserved"), ("plan", "evidence_case_id_reserved")):
                with self.subTest(case_id=case_id):
                    with self.assertRaises(ValueError) as ctx:
                        procedure_eval.write_evidence_packet({"case_id": case_id}, evidence, case_id, "{}\n", fixture_roots=[])
                    self.assertEqual(str(ctx.exception), expected)
                    self.assertEqual(os.listdir(parent), [])
                    self.assertFalse(evidence.exists())

    def test_cli_reserved_case_id_exits_nonzero_nothing_outside_root(self):
        with tempfile.TemporaryDirectory() as meta_td, tempfile.TemporaryDirectory() as parent_td:
            eval_set, _transcript = write_probe_eval(meta_td, case_id="plan", artifacts=())
            evidence = Path(parent_td) / "ev"
            evidence.mkdir()
            proc = run_cli("--eval-set", eval_set, "--transcript", PASS_TRANSCRIPT, "--strict-evidence",
                           "--evidence-dir", evidence)
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("error=evidence_case_id_reserved:plan", proc.stdout)
            self.assertEqual(os.listdir(parent_td), ["ev"])
            self.assertEqual(os.listdir(evidence), [])

    def test_evidence_dir_inside_live_fixture_copy_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "copy"
            copy.mkdir()
            with self.assertRaises(ValueError) as ctx:
                procedure_eval.write_evidence_packet({"case_id": "safe-case"}, copy / "ev", "safe-case", "x\n",
                                                     fixture_roots=[copy])
            self.assertEqual(str(ctx.exception), "evidence_dir_inside_fixture")
            self.assertFalse((copy / "ev").exists())

    def test_synthetic_credential_masked_on_disk(self):
        token = "ghp_" + "A1b2" * 9  # assembled at runtime, as in tests/test_sensitive_redaction.py
        with tempfile.TemporaryDirectory() as td:
            transcript = write_jsonl(Path(td) / "denied.jsonl", [
                full_tool_use("b1", "Bash", {"command": "python -m pytest -q"}),
                {"type": "result", "subtype": "success", "result": "done",
                 "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "echo " + token}}]},
            ])
            evidence = Path(td) / "ev"
            strict_replay(evidence, self.copy_fixture_root(td), transcript=transcript)
            packet_bytes = (evidence / f"{PACKET_CASE}.json").read_bytes()
            transcript_bytes = (evidence / f"{PACKET_CASE}.transcript.jsonl").read_bytes()
        # Boolean assertions with fixed messages: assertIn/assertNotIn would echo the file bytes, and stdout carries
        # the unredacted denial detail, so a failure must never print the synthetic credential.
        raw = token.encode("utf-8")
        self.assertFalse(raw in packet_bytes, "raw credential persisted in the packet")
        self.assertFalse(raw in transcript_bytes, "raw credential persisted in the transcript copy")
        self.assertTrue(b"***MASKED" in packet_bytes, "packet lacks the masked form")
        self.assertTrue(b"***MASKED" in transcript_bytes, "transcript copy lacks the masked form")

    def test_json_escaped_credential_masked_in_transcript_copy(self):  # D25 model (6), SEC-5
        # Mutation: redacting the copy as plain text only (the JSON-escaped member evades the text pattern).
        value = hashlib.sha256(b"d25-synthetic-client-secret").hexdigest()[:32]  # runtime-built, never a literal
        command = "curl -d '{\"client_secret\": \"" + value + "\"}' https://example.invalid/token"
        with tempfile.TemporaryDirectory() as td:
            transcript = write_jsonl(Path(td) / "escaped.jsonl", [full_tool_use("b1", "Bash", {"command": command})])
            self.assertTrue(value.encode("utf-8") in transcript.read_bytes(), "precondition: the value is on disk")
            evidence = Path(td) / "ev"
            strict_replay(evidence, self.copy_fixture_root(td), transcript=transcript)
            copy_bytes = (evidence / f"{PACKET_CASE}.transcript.jsonl").read_bytes()
        self.assertFalse(value.encode("utf-8") in copy_bytes, "raw credential persisted in the transcript copy")
        self.assertTrue(b"***MASKED" in copy_bytes, "transcript copy lacks the masked form")
        lines = [line for line in copy_bytes.decode("utf-8").split("\n") if line]
        self.assertTrue(lines, "transcript copy is empty")
        parsed = []
        for line in lines:
            try:
                parsed.append(isinstance(json.loads(line), dict))
            except json.JSONDecodeError:
                parsed.append(False)
        self.assertTrue(all(parsed), "a transcript copy line no longer parses as a JSON object")

    def test_scalar_json_lines_do_not_split_a_private_key_block(self):  # D25 models (4) and (6)
        # Mutation: treating any line json.loads accepts (a bare number, true, null) as a structured event, which
        # splits the PEM run so the body lines after the scalar reach disk, and rewrites the scalar line itself.
        begin, end = "-----BEGIN " + "RSA PRIVATE KEY-----", "-----END " + "RSA PRIVATE KEY-----"  # runtime-built
        body = ["MIIEow" + "A" * 40, "12", "true", "QWERTY" + "B" * 40]
        big = "1" * 64
        text = "\n".join(['{"type": "x"}', big, begin, *body, end, "null", ""])
        out = procedure_eval.redact_transcript_lines(text)
        for line in (body[0], body[3], end):
            self.assertFalse(line in out, "a private-key block line persisted in the redacted copy")
        self.assertTrue("***MASKED" in out, "redacted copy lacks the masked form")
        self.assertEqual(out.split("\n")[:2], ['{"type": "x"}', big])  # the scalar line keeps its bytes
        self.assertEqual(out.split("\n")[-2:], ["null", ""])

    def test_home_directory_segments_masked_in_packet_and_transcript(self):  # D25 model (6), follow-up b
        # Mutation: skipping mask_home_paths for the packet or the copy, missing JSON-escaped separators, ending the
        # segment at a blank (a spaced profile name leaks its tail) or matching `home`/`Users` case-sensitively.
        user, spaced, folded = "evaluser", "Evan Doe", "lowname"
        with tempfile.TemporaryDirectory() as td:
            transcript = write_jsonl(Path(td) / "home.jsonl", [
                full_tool_use("w1", "Write", {"file_path": "/home/" + user + "/work/docs/agentic-sdlc/specs/x.md",
                                              "content": "spec\n"}),
                full_tool_use("b1", "Bash", {"command": "dir C:\\Users\\" + user + "\\repo"}),
                full_tool_use("b2", "Bash", {"command": "dir C:\\Users\\" + spaced + "\\repo"}),
                full_tool_use("b3", "Bash", {"command": "ls /home/" + spaced + "/x c:/users/" + folded + "/x"}),
                # A denied command carries a home path into a packet error id (since C17.1 unsafe_artifact_path does not).
                {"type": "result", "subtype": "success", "is_error": False, "result": "done", "permission_denials": [
                    {"tool_name": "Bash", "tool_input": {"command": "ls /home/" + user + "/work"}}]},
            ])
            self.assertTrue(b"C:\\\\Users\\\\" + user.encode() in transcript.read_bytes(), "precondition: escaped path")
            evidence = Path(td) / "ev"
            proc = strict_replay(evidence, self.copy_fixture_root(td), transcript=transcript)
            # C17.1: a spec path no root can relativize keeps unsafe_artifact_path, but its id never carries the
            # absolute path or the home segment (the last two segments only).
            self.assertIn("unsafe_artifact_path:specs/x.md", proc.stdout)
            self.assertFalse(("unsafe_artifact_path:/home/" in proc.stdout), "an absolute path reached the error id")
            self.assertIn("permission_denied:Bash:ls /home/" + user + "/work", proc.stdout)
            packet_bytes = (evidence / f"{PACKET_CASE}.json").read_bytes()
            copy_bytes = (evidence / f"{PACKET_CASE}.transcript.jsonl").read_bytes()
        for label, data in (("packet", packet_bytes), ("transcript copy", copy_bytes)):
            with self.subTest(file=label):
                for part in (user, "Evan", "Doe", folded):
                    self.assertFalse(part.encode() in data, f"home user segment {part!r} persisted in the {label}")
                self.assertTrue(b"***MASKED:home***" in data, f"{label} lacks the masked home segment")
        self.assertTrue(b"permission_denied:Bash:ls /home/***MASKED:home***/work" in packet_bytes)
        self.assertTrue(b"unsafe_artifact_path:specs/x.md" in packet_bytes)
        raw = "C:\\Users\\" + spaced + "\\repo /home/" + spaced + "\tx/y c:/users/" + folded + "/z"
        self.assertEqual(procedure_eval.mask_home_paths(raw),
                         "C:\\Users\\***MASKED:home***\\repo /home/***MASKED:home***/y c:/users/***MASKED:home***/z")

    @staticmethod
    def stream_record(index, body, session="s1"):
        return {"type": "stream_event", "session_id": session, "parent_tool_use_id": None,
                "event": dict(body, index=index)}

    def stream_block(self, index, kind, pieces, content_block):
        field = "partial_json" if kind == "input_json_delta" else "text"
        return ([self.stream_record(index, {"type": "content_block_start", "content_block": content_block})]
                + [self.stream_record(index, {"type": "content_block_delta", "delta": {"type": kind, field: piece}})
                   for piece in pieces]
                + [self.stream_record(index, {"type": "content_block_stop"})])

    @staticmethod
    def joined_block(records, index):
        pieces = []
        for record in records:
            event = record.get("event") if isinstance(record, dict) else None
            if record.get("type") == "stream_event" and isinstance(event, dict) and event.get("index") == index \
                    and event.get("type") == "content_block_delta":
                delta = event["delta"]
                pieces.append(delta.get("partial_json", delta.get("text")))
        return "".join(pieces)

    @staticmethod
    def decoded_strings(value):
        out, stack = [], [value]
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                stack.extend(item.values())
        return out

    def test_home_identity_forms_masked_everywhere(self):  # D26 / DP38
        # Mutations: chunk-by-chunk masking (no block rule), omitting the slug grammar, requiring a blank before the
        # path form (misses -I/home/), omitting the backslash-only path form, collecting only the spaced run, or
        # applying identity matching to packet structural fields.
        bs, marker, case = chr(92), "***MASKED:home***", "identity-probe"
        user, flag, unc, space = "evaluser", "evalflag", "evalunc", "evalspace"
        control = "The home page lists users; the test runner ran in /home/runner/work; users-admin and --home-dir stay."
        records = [
            *self.stream_block(0, "input_json_delta", ['{"command": "ls /home/', user + '/.cache/x"}'],
                               {"type": "tool_use", "id": "b0", "name": "Bash", "input": {}}),
            *self.stream_block(1, "text_delta", ["ls /home/", "evalu", "ser/w"], {"type": "text", "text": ""}),
            {"type": "system", "subtype": "init", "memory": "/p/projects/-home-" + user + "--cache-agentic-sdlc-eval/memory"},
            {"type": "system", "subtype": "note", "memory": "C:/p/projects/C--Users-" + user + "-repo/memory"},
            full_tool_use("b1", "Bash", {"command": "dir C:" + bs + "Users" + bs + user + bs + "repo"}),
            assistant_text_event("logged in as EvalUser"),
            full_tool_use("b2", "Bash", {"command": "gcc -I/home/" + flag + "/inc"}),
            assistant_text_event(flag + " ran"),
            full_tool_use("b3", "Bash", {"command": bs + bs + "wsl$" + bs + "Distro" + bs + "home" + bs + unc + bs + "x"}),
            assistant_text_event(unc + " ran"),
            full_tool_use("b4", "Bash", {"command": "cp /home/" + space + " ab/c"}),
            assistant_text_event(space + " ran"),
            assistant_text_event(control),
            # The case-id word is also a collected identity, so identity matching on structural fields is observable.
            {"type": "system", "subtype": "note", "cwd": "/home/probe/x"},
        ]
        transcript_text = "".join(json.dumps(record) + "\n" for record in records)
        with tempfile.TemporaryDirectory() as td:
            packet = procedure_eval.build_evidence_packet(
                {"id": case, "prompt": "probe"}, procedure_eval.Trace(),
                ["unsafe_artifact_path:/p/-home-" + user + "--cache-x"], cwd=Path(td), fixture_root=None,
                scoring_source="transcript-replay", strict=True, identity="unavailable:build-release-absent",
                git_commit="0" * 40)
            evidence = Path(td) / "ev"
            procedure_eval.write_evidence_packet(packet, evidence, case, transcript_text, fixture_roots=[])
            packet_text = (evidence / f"{case}.json").read_text(encoding="utf-8")
            copy_text = (evidence / f"{case}.transcript.jsonl").read_text(encoding="utf-8")
            unmasked = procedure_eval.redact_json(
                dict(packet, helper_paths=procedure_eval.helper_paths(evidence.resolve(strict=False))))
            unmasked = json.loads(procedure_eval.mask_home_paths(json.dumps(unmasked, indent=2, ensure_ascii=False)))
        # Boolean assertions with fixed messages, so a failure never echoes file text.
        for label, text in (("packet", packet_text), ("copy", copy_text)):
            for name in (user, flag, unc, space):
                self.assertFalse(name in text.lower(), f"a synthetic home identity persisted in the {label}")
            self.assertTrue(marker in text, f"the {label} lacks the home marker")
        copy_lines = copy_text.split("\n")
        self.assertTrue(len(copy_lines) == len(transcript_text.split("\n")), "the copy changed its line count")
        parsed = []
        for line in copy_lines:
            if not line:
                continue
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                self.fail("a copy line no longer parses as JSON")
        block_a = self.joined_block(parsed, 0)
        try:
            command_a = json.loads(block_a)["command"]
        except (json.JSONDecodeError, KeyError, TypeError):
            self.fail("block (a) no longer reassembles to JSON with a command")
        self.assertTrue(command_a == "ls /home/" + marker + "/.cache/x", "block (a) lacks the masked path")
        self.assertTrue(self.joined_block(parsed, 1) == "ls /home/" + marker + "/w", "block (b) is not masked whole")
        try:
            packet_value = json.loads(packet_text)
        except json.JSONDecodeError:
            self.fail("the packet no longer parses")
        self.assertTrue(set(packet_value) == set(unmasked), "the packet key set changed")
        for field in ("case_id", "transcript_path", "helper_paths"):
            self.assertTrue(packet_value[field] == unmasked[field], f"packet {field} changed under identity masking")
        self.assertTrue(packet_value["errors"][0] == "unsafe_artifact_path:/p/-home-" + marker + "--cache-x",
                        "packet error slug is not masked in position")
        strings = [s for record in parsed for s in self.decoded_strings(record)]
        for expected, label in (
                ("/p/projects/-home-" + marker + "--cache-agentic-sdlc-eval/memory", "dash slug"),
                ("C:/p/projects/C--Users-" + marker + "-repo/memory", "drive slug"),
                ("dir C:" + bs + "Users" + bs + marker + bs + "repo", "backslash Users path"),
                ("logged in as " + marker, "prose identity"),
                ("gcc -I/home/" + marker + "/inc", "flag-glued path"),
                (bs + bs + "wsl$" + bs + "Distro" + bs + "home" + bs + marker + bs + "x", "backslash-only path"),
                ("cp /home/" + marker + "/c", "spaced run path"),
                (control.replace("/home/runner/", "/home/" + marker + "/"), "control text")):
            self.assertTrue(expected in strings, f"the copy lacks the expected {label}")
        self.assertTrue(strings.count(marker + " ran") == 3, "prose identities are not all masked")

    def test_split_stream_block_masks_like_the_joined_block(self):  # D26 / DP38
        # Mutations: masking chunk by chunk, collecting from raw chunks (a two-character prefix becomes an identity),
        # or treating a source escape backslash as a separator in partial_json blocks.
        marker = "***MASKED:home***"
        text = 'cd "/home/evaluser/x" && ls /p/-home-evaluser--cache-y'
        expected = 'cd "/home/' + marker + '/x" && ls /p/-home-' + marker + "--cache-y"
        for cut in range(len(text) - 1):
            pieces = [text[:cut], text[cut:cut + 2], text[cut + 2:]]
            records = self.stream_block(3, "text_delta", pieces, {"type": "text", "text": ""})
            jsonl = "".join(json.dumps(record) + "\n" for record in records)
            with self.subTest(block="text", cut=cut):
                out = procedure_eval.mask_home_identities([jsonl])[0]
                joined = self.joined_block([json.loads(line) for line in out.split("\n") if line], 3)
                self.assertEqual(joined, expected)
                self.assertNotIn("evaluser", out)
                # Raw chunks are never a collection source: a chunk prefix such as `eva` is not an identity.
                self.assertEqual(procedure_eval.collect_home_identities([jsonl]), ["evaluser"])
        source = json.dumps({"command": "cd /Users/" + chr(10) + "x && ls /home/evaluser/y"})
        self.assertIn(chr(92) + "n", source)  # precondition: the source holds a newline escape
        for cut in range(len(source) - 1):
            pieces = [source[:cut], source[cut:cut + 2], source[cut + 2:]]
            records = self.stream_block(4, "input_json_delta", pieces, {"type": "tool_use", "id": "t", "name": "Bash"})
            jsonl = "".join(json.dumps(record) + "\n" for record in records)
            with self.subTest(block="partial_json", cut=cut):
                out = procedure_eval.mask_home_identities([jsonl])[0]
                joined = self.joined_block([json.loads(line) for line in out.split("\n") if line], 4)
                self.assertEqual(json.loads(joined)["command"],
                                 "cd /Users/" + chr(10) + "x && ls /home/" + marker + "/y")
                self.assertNotIn("evaluser", out)
                self.assertEqual(procedure_eval.collect_home_identities([jsonl]), ["evaluser"])
        # An identity that starts with an escape letter: a match right after an odd backslash run sits inside the
        # escape (`\nate` is a newline and `ate`) and stays; after an escaped backslash pair it is masked.
        # Mutation: checking only the character before the match leaves `\*` in the source, which no longer parses.
        source = json.dumps({"command": "cat /home/nate/x", "note": "done" + chr(10) + "ate lunch",
                             "raw": "x" + chr(92) + "nate y"})
        for cut in range(len(source) - 1):
            pieces = [source[:cut], source[cut:cut + 2], source[cut + 2:]]
            records = self.stream_block(5, "input_json_delta", pieces, {"type": "tool_use", "id": "t", "name": "Bash"})
            jsonl = "".join(json.dumps(record) + "\n" for record in records)
            with self.subTest(block="escape-letter identity", cut=cut):
                out = procedure_eval.mask_home_identities([jsonl])[0]
                joined = self.joined_block([json.loads(line) for line in out.split("\n") if line], 5)
                try:
                    value = json.loads(joined)
                except json.JSONDecodeError:
                    self.fail("masking broke a JSON escape in the reassembled block")
                self.assertEqual(value, {"command": "cat /home/" + marker + "/x",
                                         "note": "done" + chr(10) + "ate lunch", "raw": "x" + chr(92) + marker + " y"})

    def test_masking_keeps_json_escapes_and_prose_controls(self):  # D26 / DP38
        # Mutations: masking the serialized line instead of decoded strings, dropping the generic-name set or the
        # minimum length (prose root / ab), reading URL tokens (prose list), or treating `_` as a boundary.
        bs, marker = chr(92), "***MASKED:home***"
        name = chr(0xC7) + "a" + chr(0x11F) + "r" + chr(0x131)
        cases = [
            ("ls /Users/" + chr(10) + "Shared", "ls /Users/" + chr(10) + "Shared"),
            ("cd /home/" + chr(9) + "x", "cd /home/" + marker),
            ("/home/ab/x and ab", "/home/" + marker + "/x and ab"),
            ("/home/root/x and root", "/home/" + marker + "/x and root"),
            ("the-home-page and --home-dir", "the-home-page and --home-dir"),
            # The URL path is quoted so the DP37 segment ends before the prose word (an unquoted segment would run on
            # over " and list" and hide the URL-token mutation); the URL token keeps its position mask only.
            ('see "https://example.test/users/list" and list',
             'see "https://example.test/users/' + marker + '" and list'),
            ("C:" + bs + "Users" + bs + "Evan Doe" + bs + "r and C--Users-Evan-Doe-r",
             "C:" + bs + "Users" + bs + marker + bs + "r and C--Users-" + marker + "-r"),
            ("/home/" + name + "/x and " + name, "/home/" + marker + "/x and " + marker),
            ("logged in as EvalUser after /home/evaluser/w; evaluser_tmp and preevaluser stay",
             "logged in as " + marker + " after /home/" + marker + "/w; evaluser_tmp and preevaluser stay"),
            # A slug-only identity: without the slug grammar its prose occurrence would survive.
            ("/p/-home-evalslug--cache and evalslug ran", "/p/-home-" + marker + "--cache and " + marker + " ran"),
        ]
        line = json.dumps([raw for raw, _ in cases])
        out = procedure_eval.mask_home_identities([line])[0]
        self.assertEqual(json.loads(out), [want for _, want in cases])

    def test_live_harness_packet_not_scorable(self):
        case = {"id": "safe-case", "prompt": "probe"}
        with tempfile.TemporaryDirectory() as td:
            common = {"cwd": Path(td), "fixture_root": None, "identity": "unavailable:build-release-absent",
                      "git_commit": "0" * 40}
            live = procedure_eval.build_evidence_packet(case, procedure_eval.Trace(), [], scoring_source="live-harness",
                                                        strict=True, **common)
            replay = procedure_eval.build_evidence_packet(case, procedure_eval.Trace(), [],
                                                          scoring_source="transcript-replay", strict=True, **common)
        self.assertIs(live["procedure_row_scorable"], False)
        self.assertIs(replay["procedure_row_scorable"], True)

    def test_unwritable_evidence_dir_named_write_failure_not_unreadable_transcript(self):
        """A filesystem write failure is named evidence_write_failed; the transcript itself is readable.

        Mutation: letting mkdir's OSError reach the transcript-read handler reports evidence_transcript_unreadable.
        """
        with tempfile.TemporaryDirectory() as td:
            blocker = Path(td) / "blocker"
            blocker.write_bytes(b"regular file\n")
            proc = strict_replay(blocker / "ev", self.copy_fixture_root(td))
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn(f"error=evidence_write_failed:{PACKET_CASE}", proc.stdout)
            self.assertNotIn("evidence_transcript_unreadable", proc.stdout)
            self.assertEqual(blocker.read_bytes(), b"regular file\n")

    def test_existing_packet_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            evidence = Path(td) / "ev"
            root = self.copy_fixture_root(td)
            strict_replay(evidence, root)
            packet_path = evidence / f"{PACKET_CASE}.json"
            self.assertTrue(packet_path.is_file())
            original = packet_path.read_bytes()
            second = strict_replay(evidence, root)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn(f"error=evidence_packet_exists:{PACKET_CASE}", second.stdout)
            self.assertEqual(packet_path.read_bytes(), original)


def plant_fake_program(directory, name):
    """A fake `name` program in `directory` that never prints JSON; returns (program, sentinel).

    POSIX: a `#!/bin/sh` script that writes the sentinel and exits 1. win32: a copy of whoami.exe named
    `<name>.exe` (the caller skips when whoami.exe is absent); there the sentinel is never written.
    """
    directory = Path(directory)
    sentinel = directory / f"{name}-ran.txt"
    if sys.platform == "win32":
        whoami = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "whoami.exe"
        if not whoami.is_file():
            return None, sentinel
        program = directory / f"{name}.exe"
        shutil.copyfile(whoami, program)
    else:
        program = directory / name
        program.write_bytes(f"#!/bin/sh\necho ran > '{sentinel}'\nexit 1\n".encode("utf-8"))
        program.chmod(0o755)
    return program, sentinel


def relative_first_env():
    """The process environment with `.` first on PATH and NoDefaultCurrentDirectoryInExePath removed."""
    env = {k: v for k, v in os.environ.items() if k.upper() != "NODEFAULTCURRENTDIRECTORYINEXEPATH"}
    env["PATH"] = "." + os.pathsep + os.environ.get("PATH", "")
    return env


LOOKUP_PROBE = (
    "import json, sys; sys.path.insert(0, sys.argv[1]); import scripts.run_procedure_eval as m;"
    "print(json.dumps(m.run_node_helpers(commands=['pytest'], test_command='pytest') if sys.argv[2] == 'helpers'"
    " else m._program_on_absolute_path(sys.argv[2])))"
)


class TestProgramLookup(unittest.TestCase):
    """D25 model (5), SEC-7: node and git start only from an absolute path found in an absolute PATH entry."""

    def planted(self, name):
        directory = Path(tempfile.mkdtemp(prefix="lookup-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        program, sentinel = plant_fake_program(directory, name)
        if program is None:
            self.skipTest("whoami.exe absent: no planted win32 program")
        return directory, sentinel

    def probe(self, cwd, what):
        proc = subprocess.run([sys.executable, "-c", LOOKUP_PROBE, str(REPO), what], cwd=cwd,
                              env=relative_first_env(), capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        return json.loads(proc.stdout)

    def test_node_behind_relative_path_entry_is_not_run(self):
        # Mutation: resolving node with shutil.which (the cwd or a relative PATH entry wins).
        directory, sentinel = self.planted("node")
        self.assertEqual(self.probe(directory, "helpers"), {"exits": [], "real": [True]})
        self.assertFalse(sentinel.exists(), "the planted node ran")

    def test_git_lookup_skips_relative_entries(self):
        # Mutation: accepting a relative PATH entry (or the cwd) as a git location.
        directory, sentinel = self.planted("git")
        git = self.probe(directory, "git")
        self.assertIsNotNone(git, "no git on an absolute PATH entry")
        self.assertTrue(os.path.isabs(git), git)
        self.assertFalse(path_is_within(git, directory), git)
        self.assertFalse(sentinel.exists())

    @unittest.skipUnless(sys.platform == "win32", "batch files are a win32 lookup concern")
    def test_batch_file_is_not_a_candidate(self):
        # Mutation: consulting PATHEXT (a .cmd would run through cmd.exe without a shell being asked for).
        directory = Path(tempfile.mkdtemp(prefix="lookup-cmd-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        (directory / "node.cmd").write_bytes(b"@echo not-json\r\n")
        path = str(directory) + os.pathsep + os.environ.get("PATH", "")
        with mock.patch.dict(os.environ, {"PATH": path}):
            node = procedure_eval._program_on_absolute_path("node")
            helpers = procedure_eval.run_node_helpers(commands=["pytest"], test_command="pytest")
        self.assertIsNotNone(node)
        self.assertFalse(path_is_within(node, directory), node)
        self.assertEqual(helpers, {"exits": [], "real": [True]})


class TestLiveAgentCliSpawn(unittest.TestCase):
    """SEC-8: the agent CLI is the highest-privilege spawn in this file (the repository as
    `--plugin-dir`, the case prompt on argv) and was the only program left on a BARE NAME, gated by a
    `shutil.which` call that is itself what pulls the win32 current-directory lookup in. D25 model (5)
    already resolves `git` and `node` to an absolute path found on an absolute PATH entry.

    No CLI is started here and no paid call can happen: `copy_fixture` and the redactor are stubbed,
    the CLI stand-in is an inert file in a temp directory, and the subprocess fake RAISES on any argv
    it does not recognize instead of falling through to the real `subprocess.run`."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="live-spawn-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cli = self.tmp / ("claude.exe" if sys.platform == "win32" else "claude")
        self.cli.write_bytes(b"inert stand-in, never executed\n")
        if sys.platform != "win32":
            self.cli.chmod(0o755)

    def _args(self, **over):
        base = dict(transcript_dir=self.tmp / "transcripts", timeout=30, model=None,
                    permission_mode="auto", max_budget_usd="1.00", allow_fixture_commit=False,
                    strict_evidence=False)
        base.update(over)
        return types.SimpleNamespace(**base)

    def _spawn_argv(self, args, *, resolved):
        """run_live_case's argv, with the fixture copy, the redactor and the spawn all stubbed."""
        recorded = {}

        def fake_run(cmd, **kwargs):
            # Fail closed: only the agent-CLI argv is accepted, and it is never executed.
            if not isinstance(cmd, list) or len(cmd) < 3 or cmd[1] != "-p":
                raise AssertionError(f"unexpected subprocess argv: {cmd!r}")
            recorded["cmd"] = list(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        real_which = shutil.which

        def stub_which(name, **kwargs):
            # A BARE name never reaches a real installation here; an explicit path (the temp
            # stand-in) resolves normally, which is what the --claude override has to keep working.
            return real_which(name, **kwargs) if os.path.dirname(name) else resolved

        case = {"id": "spawn-probe", "prompt": "hello", "fixture_dir": "tests/fixtures"}
        with mock.patch.object(procedure_eval, "copy_fixture", lambda *a, **k: self.tmp), \
             mock.patch.object(procedure_eval, "redact_text", lambda text: text), \
             mock.patch.object(procedure_eval, "_program_on_absolute_path", lambda name: resolved), \
             mock.patch.object(procedure_eval.shutil, "which", stub_which), \
             mock.patch.object(procedure_eval.subprocess, "run", fake_run):
            procedure_eval.run_live_case(case, args, self.tmp)
        return recorded["cmd"]

    def test_default_spawn_uses_an_absolute_cli_path(self):
        # Mutation: spawning the bare name `claude`, which on win32 searches the current directory first.
        argv = self._spawn_argv(self._args(), resolved=str(self.cli))
        self.assertTrue(os.path.isabs(argv[0]), argv[0])
        self.assertEqual(argv[0], str(self.cli))
        self.assertIn("--plugin-dir", argv)

    def test_explicit_override_is_used_when_the_cli_is_off_the_absolute_path(self):
        # WSL/nvm layouts keep the CLI outside any absolute PATH entry; --claude names it explicitly.
        argv = self._spawn_argv(self._args(claude=str(self.cli)), resolved=None)
        self.assertTrue(os.path.isabs(argv[0]), argv[0])
        self.assertEqual(argv[0], str(self.cli))

    def test_unresolvable_cli_still_raises_the_named_runtime_error(self):
        # CONTROL: the existing gate must stay; a missing CLI is an error, never a bare-name spawn.
        def refuse(cmd, **kwargs):
            raise AssertionError(f"a spawn was attempted with no resolved CLI: {cmd!r}")

        with mock.patch.object(procedure_eval, "copy_fixture", lambda *a, **k: self.tmp), \
             mock.patch.object(procedure_eval, "_program_on_absolute_path", lambda name: None), \
             mock.patch.object(procedure_eval.shutil, "which", lambda name, **k: None), \
             mock.patch.object(procedure_eval.subprocess, "run", refuse):
            with self.assertRaises(RuntimeError):
                procedure_eval.run_live_case({"id": "spawn-probe", "prompt": "hello",
                                              "fixture_dir": "tests/fixtures"}, self._args(), self.tmp)


class TestRepositoryCommitEnvironment(unittest.TestCase):
    """SEC-5: the evidence packet's git_commit names THIS repository, not whatever GIT_DIR selects.

    `repository_commit()` hardened its program and argv but passed no `env=`, so it inherited the
    repository-selecting keys its sibling `scripts/build_release.py::_run_git` drops (`_GIT_ENV_DROP`).
    An ambient GIT_DIR then stamps another repository's commit into the packet, or erases it."""

    def test_repository_commit_ignores_repository_selecting_environment(self):
        if procedure_eval._program_on_absolute_path("git") is None:
            self.skipTest("git is not on an absolute PATH entry")
        head = procedure_eval.repository_commit()
        self.assertRegex(head, r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
        elsewhere = Path(tempfile.mkdtemp(prefix="commit-env-"))
        self.addCleanup(shutil.rmtree, elsewhere, ignore_errors=True)
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                     "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR"):
            with self.subTest(variable=name):
                with mock.patch.dict(os.environ, {name: str(elsewhere)}):
                    self.assertEqual(procedure_eval.repository_commit(), head)


def path_is_within(path, directory):
    return os.path.normcase(os.path.abspath(path)).startswith(os.path.normcase(os.path.abspath(directory)) + os.sep)


TRANSCRIPTS = REPO / "tests" / "fixtures" / "transcripts"
PIPELINE_CASES = ("agentic-sdlc-pipeline-feature-no-commit", "agentic-sdlc-pipeline-per-package")


def strict_fixture_replay(td, fixture_name, case_ids=PIPELINE_CASES, eval_set=PIPELINE_EVAL):
    """CLI strict replay of one committed fixture against the named cases only (contract C7 test helpers).

    Each case id is passed as `--case-id`, so a full-run fixture is graded against cases 1/2 only and a single-case
    fixture (the per-package run, the gate-stop runs) against its own case, whatever else the eval set holds.
    """
    root = Path(td) / "fixture"
    if not root.exists():
        shutil.copytree(BASIC_FIXTURE, root)
    args = ["--eval-set", eval_set, "--transcript", TRANSCRIPTS / fixture_name, "--strict-evidence",
            "--fixture-root", root]
    for case_id in case_ids:
        args += ["--case-id", case_id]
    return run_cli(*args)


class StrictFixtureAssertions(unittest.TestCase):
    def require_eval_set(self, eval_set):
        self.assertTrue((REPO / eval_set).is_file(),
                        f"{eval_set} is missing: contract C7 puts the gate-stop case (case 3) in this separate file")

    def load_cases(self, eval_set):
        """load_eval for a committed eval set; a missing file or a rejected case is this test's failure, not an error."""
        self.require_eval_set(eval_set)
        try:
            return procedure_eval.load_eval(REPO / eval_set)
        except ValueError as exc:
            self.fail(f"{eval_set} does not load: {exc}")

    def assert_positive_strict_pass(self, fixture_name, case_ids=PIPELINE_CASES, eval_set=PIPELINE_EVAL):
        self.require_eval_set(eval_set)
        with tempfile.TemporaryDirectory() as td:
            proc = strict_fixture_replay(td, fixture_name, case_ids, eval_set)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("procedure_eval=passed", proc.stdout)
        for case_id in case_ids:
            self.assertIn(f"case_{case_id}=passed", proc.stdout)

    def assert_negative_fixtures(self, expectations):
        for fixture_name, names in expectations:
            with self.subTest(fixture=fixture_name), tempfile.TemporaryDirectory() as td:
                proc = strict_fixture_replay(td, fixture_name)
                self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn("procedure_eval=failed", proc.stdout)
                for name in names:
                    self.assertIn(name, proc.stdout)

    def assert_committed_clean_lf(self, pattern, expected_count):
        from scripts.sensitive_redaction import redact_text

        files = sorted(TRANSCRIPTS.glob(pattern))
        self.assertEqual(len(files), expected_count, [f.name for f in files])
        for path in files:
            with self.subTest(fixture=path.name):
                data = path.read_bytes()
                self.assertFalse(b"\r" in data, f"{path.name} contains a CR byte")
                text = data.decode("utf-8")
                self.assertTrue(redact_text(text) == text, f"{path.name} has a HIGH-confidence secret finding")


class TestStrictClaudeFixtures(StrictFixtureAssertions):
    """AC71, AC68, AC69: committed Claude strict fixtures pass or fail with named errors."""

    def test_completed_positive_fixture_passes_both_cases_strict(self):
        self.assert_positive_strict_pass("procedure-strict-claude-complete-pass.jsonl")

    def test_negative_fixtures_fail_with_named_errors(self):
        self.assert_negative_fixtures((
            ("procedure-strict-claude-echo-hidden-red.jsonl", ["strict_missing_red_before_green"]),
            ("procedure-strict-claude-auditor-partial-overridden.jsonl", ["strict_critical_audit:"]),
            # C7/C15.10: the core's first step (the failing-test write) is missing, so RED precedes any test edit.
            ("procedure-strict-claude-missing-failing-test.jsonl", [
                "agentic-sdlc-pipeline-feature-no-commit:strict_red_not_before_source_edit",
                "agentic-sdlc-pipeline-per-package:strict_red_not_before_source_edit",
            ]),
            ("agentic-sdlc-pipeline-procedure-permission-denied.jsonl", ["permission_denied:"]),
            ("agentic-sdlc-pipeline-procedure-runtime-error.jsonl", ["runtime_error:"]),
        ))

    def test_positive_fixture_passes_default_mode(self):
        proc = run_cli("--eval-set", PIPELINE_EVAL, "--transcript", TRANSCRIPTS / "procedure-strict-claude-complete-pass.jsonl")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("procedure_eval=passed", proc.stdout)

    @unittest.skipUnless(shutil.which("node"), "node unavailable: the redaction check needs hooks/redact-sensitive.mjs")
    def test_strict_fixtures_are_committed_clean_lf(self):
        # 4 pre-C7 fixtures (missing-core renamed missing-failing-test) + 14 C7/C15 full-run + 6 gate-stop fixtures
        # + the 9 C16 review probes (7 full-run, 2 gate-stop) + the C17.1 absolute-paths shallow negative.
        self.assert_committed_clean_lf("procedure-strict-claude-*.jsonl", 34)


class TestStrictCodexFixtures(StrictFixtureAssertions):
    """AC123: committed Codex rollout fixtures: fail-open, ;-forged, GREEN-only and reviewer-less runs fail named."""

    CODEX_FIXTURES = (
        "procedure-strict-codex-complete-pass.jsonl",
        "procedure-strict-codex-fail-open.jsonl",
        "procedure-strict-codex-semicolon-forged.jsonl",
        "procedure-strict-codex-green-only.jsonl",
        "procedure-strict-codex-reviewer-missing-security.jsonl",
        "procedure-strict-codex-reviewer-missing-control.jsonl",
        "procedure-strict-codex-focused-adapter-gate.jsonl",
        "procedure-strict-codex-gate-stop-spec-approved.jsonl",
    )

    def test_completed_codex_positive_fixture_passes_strict(self):
        self.assert_positive_strict_pass("procedure-strict-codex-complete-pass.jsonl")

    def test_codex_negative_fixtures_fail_with_named_errors(self):
        self.assert_negative_fixtures((
            ("procedure-strict-codex-fail-open.jsonl", ["strict_missing_green", "strict_test_run_unattributable"]),
            ("procedure-strict-codex-semicolon-forged.jsonl", ["strict_missing_green", "strict_test_run_unattributable"]),
            ("procedure-strict-codex-green-only.jsonl", ["strict_missing_red_before_green"]),
            ("procedure-strict-codex-reviewer-missing-security.jsonl", ["strict_reviewer_result_missing:security"]),
            ("procedure-strict-codex-reviewer-missing-control.jsonl", ["strict_reviewer_result_missing:control"]),
        ))

    def test_codex_rollout_fixtures_default_mode_unchanged(self):
        for fixture_name in self.CODEX_FIXTURES:
            with self.subTest(fixture=fixture_name):
                proc = run_cli("--eval-set", PIPELINE_EVAL, "--transcript", TRANSCRIPTS / fixture_name)
                for case_id in PIPELINE_CASES:
                    # Default mode ignores rollout records exactly as at 5801cb9.
                    self.assertIn(f"case_{case_id}_tools=0", proc.stdout, proc.stdout + proc.stderr)

    @unittest.skipUnless(shutil.which("node"), "node unavailable: the redaction check needs hooks/redact-sensitive.mjs")
    def test_codex_strict_fixtures_are_committed_clean_lf(self):
        self.assert_committed_clean_lf("procedure-strict-codex-*.jsonl", len(self.CODEX_FIXTURES))


MIXED_RUNTIME_ERROR = "strict_mixed_runtime_carriers"
CODEX_EXEC_MESSAGE = {"type": "item.completed", "item": {"id": "m1", "type": "agent_message", "text": "working"}}


class TestStrictMixedRuntime(unittest.TestCase):
    """AC68, AC70, AC123 (D21): a strict transcript carrying records of more than one runtime family fails named."""

    def test_leading_session_meta_then_claude_text_fails_named(self):
        # Probe P4. Mutation: keeping first-event-wins under strict lets Codex-style assistant text clear both steps.
        events = [rollout({"id": "s1", "cli_version": "0.154.0"}, "session_meta"),
                  assistant_text_event(FINDINGS_TABLE), assistant_text_event(CONTROL_REPORT)]
        trace = procedure_eval.trace_events(events, strict=True)
        errors = procedure_eval.evaluate_case(reviewer_case(SECURITY_REVIEWER, CONTROL_REVIEWER), trace, REPO, strict=True)
        self.assertEqual(trace.runtime, "unknown")
        self.assertIn(MIXED_RUNTIME_ERROR, errors)
        self.assertEqual(reviewer_errors(errors), ["strict_reviewer_result_missing:control",
                                                   "strict_reviewer_result_missing:security"])

    def test_codex_exec_item_then_claude_events_fails_named(self):
        # Probe P5. Mutation: dropping the family set leaves runtime codex-exec with no error.
        events = [CODEX_EXEC_MESSAGE] + claude_run("t1", "pytest", False, "1 passed")
        trace = procedure_eval.trace_events(events, strict=True)
        errors = procedure_eval.evaluate_case(AUDIT_CASE, trace, REPO, strict=True)
        self.assertIn(MIXED_RUNTIME_ERROR, errors)
        self.assertEqual(errors.count(MIXED_RUNTIME_ERROR), 1)

    def test_cli_concatenated_positive_fixtures_fail_named(self):
        codex = (TRANSCRIPTS / "procedure-strict-codex-complete-pass.jsonl").read_bytes()
        claude = (TRANSCRIPTS / "procedure-strict-claude-complete-pass.jsonl").read_bytes()
        with tempfile.TemporaryDirectory() as td:
            transcript = Path(td) / "mixed.jsonl"
            transcript.write_bytes(codex + (b"" if codex.endswith(b"\n") else b"\n") + claude)
            root = Path(td) / "fixture"
            shutil.copytree(BASIC_FIXTURE, root)
            proc = run_cli("--eval-set", PIPELINE_EVAL, "--transcript", transcript, "--strict-evidence",
                           "--fixture-root", root)
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for case_id in PIPELINE_CASES:
            self.assertIn(f"error={case_id}:{MIXED_RUNTIME_ERROR}", proc.stdout)

    def test_single_runtime_fixtures_have_no_mixed_error(self):
        # Guard: every committed single-runtime strict fixture keeps its runtime and gets no mixed-runtime error.
        for pattern, runtime in (("procedure-strict-claude-*.jsonl", "claude"),
                                 ("procedure-strict-codex-*.jsonl", "codex-rollout")):
            paths = sorted(TRANSCRIPTS.glob(pattern))
            self.assertTrue(paths, pattern)
            for path in paths:
                with self.subTest(fixture=path.name):
                    trace = procedure_eval.trace_events(procedure_eval.load_json_lines(path), strict=True)
                    self.assertNotIn(MIXED_RUNTIME_ERROR, trace.strict_errors)
                    self.assertEqual(trace.runtime, runtime)

    def test_default_mode_keeps_first_event_runtime(self):
        # Guard: with strict off, first-event-wins is exact and no strict error is recorded.
        trace = procedure_eval.trace_events([CODEX_EXEC_MESSAGE] + claude_run("t1", "pytest", False, "1 passed"))
        self.assertEqual(trace.runtime, "codex-exec")
        self.assertEqual(trace.strict_errors, [])


HANDBACK_PARTIAL = {"overallStatus": "PARTIAL", "finalDecision": "block-final"}
HANDBACK_NOTE = "Subagent completed with a note."
CLAUDE_WORKFLOW_FIXTURES = (
    "agentic-sdlc-pipeline-procedure-pass.jsonl",
    "agentic-sdlc-pipeline-procedure-per-package-pass.jsonl",
    "agentic-sdlc-pipeline-procedure-permission-denied.jsonl",
    "agentic-sdlc-pipeline-procedure-runtime-error.jsonl",
    "procedure-strict-claude-complete-pass.jsonl",
    "procedure-strict-claude-echo-hidden-red.jsonl",
    "procedure-strict-claude-auditor-partial-overridden.jsonl",
    "procedure-strict-claude-missing-failing-test.jsonl",  # renamed from missing-core (C15.10)
    # Contract C7/C15 fixtures (pipeline v2.1): every one carries spec-plan-draft Workflow calls.
    "procedure-strict-claude-missing-core-read.jsonl",
    "procedure-strict-claude-absolute-paths-pass.jsonl",
    "procedure-strict-claude-gate-stop-absolute-edit.jsonl",
    "procedure-strict-claude-forbidden-skill-top-level.jsonl",
    "procedure-strict-claude-forbidden-skill-in-subagent.jsonl",
    "procedure-strict-claude-focused-skill-read-posix.jsonl",
    "procedure-strict-claude-focused-skill-read-windows.jsonl",
    "procedure-strict-claude-piped-red.jsonl",
    "procedure-strict-claude-red-before-source-pass.jsonl",
    "procedure-strict-claude-red-after-source-edit.jsonl",
    "procedure-strict-claude-source-edit-unobserved.jsonl",
    "procedure-strict-claude-dispatch-twice.jsonl",
    "procedure-strict-claude-dispatch-substituted.jsonl",
    "procedure-strict-claude-reviewer-before-last-edit.jsonl",
    "procedure-strict-claude-missing-tdd-evidence.jsonl",
    "procedure-strict-claude-gate-stop-pass.jsonl",
    "procedure-strict-claude-gate-stop-edit-after-spec.jsonl",
    "procedure-strict-claude-gate-stop-spec-approved.jsonl",
    "procedure-strict-claude-gate-stop-plan-written.jsonl",
    "procedure-strict-claude-gate-stop-no-stop-text.jsonl",
)


def auditor_handback_stream(handback_input, *, parent="a1", handback_id="hb1", agent_result=HANDBACK_NOTE,
                            agent_receipt=None, handback_error=False, parent_id=None):
    """Auditor Agent dispatch, optional SubagentHandback, Agent result, then a main-loop PASS."""
    parent_id = parent if parent_id is None else parent_id
    events = [full_tool_use(parent, "Agent", {"subagent_type": "agentic-sdlc:implementation-auditor",
                                              "prompt": "audit the flow"})]
    if handback_input is not None:
        events.append(full_tool_use(handback_id, "SubagentHandback", handback_input, parent_tool_use_id=parent_id))
        events.append(claude_result(handback_id, handback_error, "handed back"))
    if agent_receipt is not None:
        events.append(launch_receipt(parent, status=agent_receipt))
    else:
        events.append(claude_result(parent, False, agent_result))
    events.append(assistant_text_event(AUDITOR_PASS))
    return events


class TestSubagentHandback(unittest.TestCase):
    """AC14, AC15: SubagentHandback is the post-2.1.271 auditor verdict carrier."""

    def evaluate(self, events):
        return procedure_eval.evaluate_case(AUDIT_CASE, procedure_eval.trace_events(events), REPO, strict=True)

    def test_ac14_auditor_handback_grades_over_main_loop_pass(self):
        errors = self.evaluate(auditor_handback_stream(HANDBACK_PARTIAL))
        self.assertEqual(audit_errors(errors), BOTH_CRITICAL)

    def test_ac14_handback_error_carries_no_verdict(self):
        errors = self.evaluate(auditor_handback_stream(HANDBACK_PARTIAL, handback_error=True))
        self.assertEqual(audit_errors(errors), [])
        self.assertNotIn("strict_auditor_verdict_unobservable", errors)

    def test_ac14_non_auditor_parent_carries_no_verdict(self):
        events = [
            full_tool_use("g1", "Agent", {"subagent_type": "general-purpose", "prompt": "act as auditor"}),
            full_tool_use("hb1", "SubagentHandback", HANDBACK_PARTIAL, parent_tool_use_id="g1"),
            claude_result("hb1", False, "handed back"),
            claude_result("g1", False, HANDBACK_NOTE),
            assistant_text_event(AUDITOR_PASS),
        ]
        self.assertEqual(audit_errors(self.evaluate(events)), [])

    def test_ac14_stream_only_raw_input_carries_no_verdict(self):
        raw = "overallStatus: PARTIAL\nfinalDecision: block-final"
        events = [
            full_tool_use("a1", "Agent", {"subagent_type": "agentic-sdlc:implementation-auditor",
                                          "prompt": "audit the flow"}),
            *stream_tool_use("hb1", "SubagentHandback", None),
        ]
        events[1] = {"type": "stream_event", "parent_tool_use_id": "a1", "event": {
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "tool_use", "id": "hb1", "name": "SubagentHandback"}}}
        events[2] = {"type": "stream_event", "parent_tool_use_id": "a1", "event": {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": raw}}}
        events.append(claude_result("hb1", False, "handed back"))
        events.append(claude_result("a1", False, HANDBACK_NOTE))
        events.append(assistant_text_event(AUDITOR_PASS))
        errors = self.evaluate(events)
        self.assertEqual(audit_errors(errors), [])
        trace = procedure_eval.trace_events(events)
        handbacks = [r for r in trace.timeline if r["kind"] == "tool_call" and r.get("name") == "SubagentHandback"]
        self.assertTrue(handbacks)
        self.assertIn("_raw", handbacks[0].get("input") or {})

    def test_ac14_pre_2_1_271_agent_tool_result_shape_unchanged(self):
        errors = self.evaluate(auditor_result("a1", AUDITOR_PARTIAL) + [assistant_text_event(AUDITOR_PASS)])
        self.assertEqual(audit_errors(errors), BOTH_CRITICAL)

    def test_ac14_cli_reports_failed_for_handback_partial(self):
        events = auditor_handback_stream(HANDBACK_PARTIAL)
        with tempfile.TemporaryDirectory() as td:
            eval_set = Path(td) / "eval.json"
            eval_set.write_text(json.dumps({"cases": [AUDIT_CASE]}), encoding="utf-8")
            transcript = write_jsonl(Path(td) / "t.jsonl", events)
            code, stdout = run_main(["--eval-set", eval_set, "--transcript", transcript, "--strict-evidence"])
        self.assertEqual(code, 1)
        self.assertIn("strict_critical_audit:overallStatus=PARTIAL", stdout)
        self.assertIn("strict_critical_audit:finalDecision=block-final", stdout)
        self.assertIn("procedure_eval=failed", stdout)

    def test_ac15_receipt_without_verdict_carrier_is_unobservable(self):
        events = auditor_handback_stream(None, agent_receipt="async_launched")
        events[-1] = assistant_text_event(AUDITOR_PARTIAL)
        errors = self.evaluate(events)
        self.assertIn("strict_auditor_verdict_unobservable", errors)
        self.assertEqual(audit_errors(errors), [])

    def test_ac15_ignores_main_loop_verdict_text(self):
        events = [
            full_tool_use("a1", "Agent", {"subagent_type": "agentic-sdlc:implementation-auditor",
                                          "prompt": "audit the flow"}),
            launch_receipt("a1"),
            assistant_text_event("overallStatus: PASS\nfinalDecision: allow-final"),
        ]
        errors = self.evaluate(events)
        self.assertIn("strict_auditor_verdict_unobservable", errors)
        self.assertEqual(procedure_eval.latest_auditor_verdict(procedure_eval.trace_events(events)), (None, None))


class TestAsyncReviewerResults(unittest.TestCase):
    """AC16: a launch receipt is not a reviewer result; task_notification is."""

    def evaluate(self, events):
        return procedure_eval.evaluate_case(
            reviewer_case(SECURITY_REVIEWER), procedure_eval.trace_events(events), REPO, strict=True)

    def test_ac16_receipt_without_notification_is_missing(self):
        events = [
            full_tool_use("s1", "Agent", {"subagent_type": "agentic-sdlc:security-reviewer"}),
            launch_receipt("s1"),
        ]
        self.assertEqual(reviewer_errors(self.evaluate(events)), ["strict_reviewer_result_missing:security"])

    def test_ac16_completed_notification_clears_at_its_index(self):
        events = [
            full_tool_use("s1", "Agent", {"subagent_type": "agentic-sdlc:security-reviewer"}),
            launch_receipt("s1"),
            task_notification("completed", tool_use_id="s1"),
        ]
        trace = procedure_eval.trace_events(events)
        index, state = procedure_eval.reviewer_step(trace, SECURITY_REVIEWER)
        notify_at = [i for i, record in enumerate(trace.timeline) if record.get("kind") == "task_notification"]
        self.assertTrue(notify_at, "task_notification must appear on the timeline")
        self.assertEqual(state, "cleared")
        self.assertEqual(index, notify_at[0])
        self.assertEqual(reviewer_errors(self.evaluate(events)), [])

    def test_ac16_failed_or_stopped_notification_is_errored(self):
        for status in ("failed", "stopped"):
            with self.subTest(status=status):
                events = [
                    full_tool_use("s1", "Agent", {"subagent_type": "agentic-sdlc:security-reviewer"}),
                    launch_receipt("s1"),
                    task_notification(status, tool_use_id="s1"),
                ]
                self.assertEqual(reviewer_errors(self.evaluate(events)),
                                 ["strict_reviewer_result_errored:security"])

    def test_ac16_notification_without_tool_use_id_is_ignored(self):
        events = [
            full_tool_use("s1", "Agent", {"subagent_type": "agentic-sdlc:security-reviewer"}),
            launch_receipt("s1"),
            task_notification("completed"),
        ]
        self.assertEqual(reviewer_errors(self.evaluate(events)), ["strict_reviewer_result_missing:security"])


class TestSubagentAttribution(unittest.TestCase):
    """AC17: only main-loop Skill, test and spec-write evidence satisfies a requirement."""

    def test_ac17_subagent_skill_does_not_satisfy(self):
        case = {"id": "skill-probe", "prompt": "p", "required_skills": ["agentic-sdlc:feature-build"]}
        sub = [full_tool_use("k1", "Skill", {"skill": "agentic-sdlc:feature-build"}, parent_tool_use_id="agent-1"),
               claude_result("k1", False, "ok")]
        main = [full_tool_use("k1", "Skill", {"skill": "agentic-sdlc:feature-build"}),
                claude_result("k1", False, "ok")]
        self.assertIn("missing_skill:agentic-sdlc:feature-build",
                      procedure_eval.evaluate_case(case, procedure_eval.trace_events(sub), REPO))
        self.assertNotIn("missing_skill:agentic-sdlc:feature-build",
                         procedure_eval.evaluate_case(case, procedure_eval.trace_events(main), REPO))

    def test_ac17_subagent_spec_write_does_not_satisfy(self):
        case = {"id": "spec-probe", "prompt": "p", "required_artifacts": ["docs/agentic-sdlc/specs/x.md"]}
        payload = {"file_path": "docs/agentic-sdlc/specs/x.md", "content": DEEP_SPEC}
        sub = [full_tool_use("w1", "Write", payload, parent_tool_use_id="agent-1")]
        main = [full_tool_use("w1", "Write", payload)]
        self.assertIn("missing_artifact:docs/agentic-sdlc/specs/x.md",
                      procedure_eval.evaluate_case(case, procedure_eval.trace_events(sub), REPO))
        self.assertNotIn("missing_artifact:docs/agentic-sdlc/specs/x.md",
                         procedure_eval.evaluate_case(case, procedure_eval.trace_events(main), REPO))

    def test_ac17_subagent_test_run_does_not_satisfy(self):
        case = {"id": "test-probe", "prompt": "p", "strict": {"require_red_green": True}}
        sub = [
            full_tool_use("r1", "Bash", {"command": "python -m pytest -q"}, parent_tool_use_id="agent-1"),
            claude_result("r1", True, "1 failed"),
            full_tool_use("g1", "Bash", {"command": "python -m pytest -q"}, parent_tool_use_id="agent-1"),
            claude_result("g1", False, "1 passed"),
        ]
        main = claude_run("r1", "python -m pytest -q", True, "1 failed") + claude_run(
            "g1", "python -m pytest -q", False, "1 passed")
        self.assertIn("strict_missing_green",
                      procedure_eval.evaluate_case(case, procedure_eval.trace_events(sub), REPO, strict=True))
        self.assertNotIn("strict_missing_green",
                         procedure_eval.evaluate_case(case, procedure_eval.trace_events(main), REPO, strict=True))


class TestClaudeChildEnvironment(unittest.TestCase):
    """AC18: CLAUDE_CODE_SIMPLE is stripped from the procedure runner child environment."""

    def test_ac18_strips_claude_code_simple_from_child_env(self):
        tmp = Path(tempfile.mkdtemp(prefix="proc-env-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cli = tmp / ("claude.exe" if sys.platform == "win32" else "claude")
        cli.write_bytes(b"inert\n")
        if sys.platform != "win32":
            cli.chmod(0o755)
        captured = {}

        def fake_run(cmd, **kwargs):
            if not isinstance(cmd, list) or len(cmd) < 3 or cmd[1] != "-p":
                raise AssertionError(f"unexpected subprocess argv: {cmd!r}")
            captured["env"] = kwargs.get("env")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        args = types.SimpleNamespace(
            transcript_dir=tmp / "transcripts", timeout=30, model=None, permission_mode="auto",
            max_budget_usd="1.00", allow_fixture_commit=False, strict_evidence=False, claude=str(cli),
        )
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SIMPLE": "1"}), \
                mock.patch.object(procedure_eval, "copy_fixture", lambda *a, **k: tmp), \
                mock.patch.object(procedure_eval, "redact_text", lambda text: text), \
                mock.patch.object(procedure_eval, "_program_on_absolute_path", lambda name: str(cli)), \
                mock.patch.object(procedure_eval.subprocess, "run", fake_run):
            procedure_eval.run_live_case({"id": "env-probe", "prompt": "hello",
                                          "fixture_dir": "tests/fixtures"}, args, tmp)
        self.assertIsNotNone(captured.get("env"))
        self.assertNotIn("CLAUDE_CODE_SIMPLE", captured["env"])


class TestFixtureWorkflowInput(unittest.TestCase):
    """AC24: Claude fixtures model Workflow input as name, not workflow."""

    def test_ac24_claude_fixtures_use_name_not_workflow(self):
        self.assertEqual(len(CLAUDE_WORKFLOW_FIXTURES), 28)  # 8 pre-C7 fixtures + 20 contract C7/C15 fixtures
        self.assertEqual(len(set(CLAUDE_WORKFLOW_FIXTURES)), len(CLAUDE_WORKFLOW_FIXTURES))
        for name in CLAUDE_WORKFLOW_FIXTURES:
            with self.subTest(fixture=name):
                events = procedure_eval.load_json_lines(TRANSCRIPTS / name)
                inputs = []
                for event in events:
                    for item in event.get("message", {}).get("content", []) if isinstance(
                            event.get("message"), dict) else []:
                        if isinstance(item, dict) and item.get("name") == "Workflow":
                            payload = item.get("input") or {}
                            inputs.append(payload)
                            self.assertIn("name", payload)
                            self.assertNotIn("workflow", payload)
                self.assertTrue(inputs, f"{name} has no Workflow input")
                data = (TRANSCRIPTS / name).read_bytes()
                self.assertNotIn(b'"workflow":', data)
                self.assertFalse(b"\r" in data)


# ---------------------------------------------------------------------------------------------------------------------
# Contract C7 (pipeline v2.1, plan D11/D12) with the C15 rulings: the new strict keys, the three forbidden patterns,
# cases 1-3, the final-assistant-text field, the path helpers and the acceptance lines. Every expected value is a literal
# copied from the contract; the fixtures are the committed tests/fixtures/transcripts/*.jsonl files (replay only, no
# model CLI is ever started).
GATE_STOP_EVAL = "tests/skills/procedure/agentic-sdlc-pipeline-gate-stop.json"
GATE_STOP_CASE = "agentic-sdlc-pipeline-gate-stop"
GATE_STOP_ONLY = {"eval_set": GATE_STOP_EVAL, "case_ids": (GATE_STOP_CASE,)}
FOCUSED_SKILLS = ["feature-build", "root-cause-fix", "safe-refactor", "test-authoring", "security-audit",
                  "implementation-control"]
FORBIDDEN_SKILL_CALL = (r'"skill":\s*"(?:agentic-sdlc:)?(?:feature-build|root-cause-fix|safe-refactor|test-authoring|'
                        r'security-audit|implementation-control)"')
# C16.1: one character class. The earlier `(?:[\\/]|\\\\)+` alternation backtracked exponentially on a backslash run.
FORBIDDEN_SKILL_PATH = (r'(?:feature-build|root-cause-fix|safe-refactor|test-authoring|security-audit|'
                        r'implementation-control)[\\/]+SKILL\.md')
FORBIDDEN_ADAPTER_GATE = (r'Adapter Gate:\s*(?:feature-build|root-cause-fix|safe-refactor|test-authoring|security-audit|'
                          r'implementation-control)\b')
C7_FORBIDDEN_PATTERNS = [FORBIDDEN_SKILL_CALL, FORBIDDEN_SKILL_PATH, FORBIDDEN_ADAPTER_GATE]
P1_HIT = f"forbidden_pattern:{FORBIDDEN_SKILL_CALL}"
P2_HIT = f"forbidden_pattern:{FORBIDDEN_SKILL_PATH}"
P3_HIT = f"forbidden_pattern:{FORBIDDEN_ADAPTER_GATE}"
GIT_PUBLISH_COMMANDS = ["\\bgit\\s+commit\\b", "\\bgit\\s+push\\b", "\\bgit\\s+merge\\b"]
C7_FULL_RUN_STRICT = {
    "require_red_green": True, "check_artifact_depth": True, "red_before_source_edit": True,
    "skill_call_counts": {"dispatch-strategy": [1, 1]},
    "forbid_skills_anywhere": ["feature-build", "root-cause-fix", "safe-refactor", "test-authoring", "security-audit",
                               "implementation-control"],
    "reviewers_after_last_source_edit": True, "evidence_file_before_control": True,
    "reviewers": [{"step": "security", "skills": [], "agents": ["security-reviewer"], "codex_result": "findings-table"},
                  {"step": "control", "skills": [], "agents": ["implementation-auditor"],
                   "codex_result": "control-verdict"}],
    "required_order": ["dispatch-strategy", "spec-written", "plan-written", "core-read", "red-run", "green-run",
                       "security", "control", "completion-claim-gate"],  # C15.10 adds core-read
}
C7_GATE_STOP_STRICT = {
    "stop_at_gate": "spec-review", "skill_call_counts": {"dispatch-strategy": [1, 1]},
    "forbid_skills_anywhere": ["feature-build", "root-cause-fix", "safe-refactor", "test-authoring", "security-audit",
                               "implementation-control"],
    "required_order": ["dispatch-strategy", "spec-written"],
}
C7_CASE1_PROMPT = (
    "Use /agentic-sdlc-pipeline to add a small production-impacting feature to this fixture: expose a new greeting "
    "suffix behavior in greeting.py. This is an automated eval: after saving the spec and plan, treat the Spec Review "
    "and Plan Review gates as approved so you can continue. Follow spec, plan, TDD, security review, implementation "
    "control, and do not commit, push, or merge."
)
C7_CASE2_PROMPT = (
    "Use /agentic-sdlc-pipeline to add a small production-impacting feature using the per-package artifact layout: "
    "expose a new greeting suffix behavior in greeting.py, and write the spec and plan under docs/agentic-sdlc/<slug>/spec/ "
    "and docs/agentic-sdlc/<slug>/plan/. This is an automated eval: after saving the spec and plan, treat the Spec Review "
    "and Plan Review gates as approved so you can continue. Follow spec, plan, TDD, security review, implementation "
    "control, and do not commit, push, or merge."
)
C7_GATE_STOP_PROMPT = (
    "Use /agentic-sdlc-pipeline to add a small production-impacting feature to this fixture: expose a new greeting "
    "suffix behavior in greeting.py. Do not commit, push, or merge."
)
C7_REQUIRED_SKILLS = ["agentic-sdlc:dispatch-strategy", "agentic-sdlc:security-audit",
                      "agentic-sdlc:implementation-control", "agentic-sdlc:completion-claim-gate"]
C7_ADAPTER_SATISFIES = ["skill:agentic-sdlc:dispatch-strategy", "skill:agentic-sdlc:security-audit",
                        "skill:agentic-sdlc:implementation-control", "skill:agentic-sdlc:completion-claim-gate",
                        "workflow:agentic-sdlc:spec-plan-draft"]
C7_ADAPTER_PATTERNS = ["Runtime:\\s*Codex|OpenCode|Kimi Code|non-Claude",
                       "Workflow unavailable|embedded author/critic adapter", "Codex Adapter Gate", "dispatch-strategy",
                       "work-type core", "security-reviewer", "implementation-auditor", "completion-claim-gate",
                       "spec-plan-author", "spec-plan-critic", "docs/agentic-sdlc/specs/", "docs/agentic-sdlc/plans/"]
# Every error id the C7 checks can emit (the forbidden-pattern hits included).
C7_ERROR_PREFIXES = (
    "forbidden_pattern:", "strict_forbidden_skill:", "strict_skill_call_count:", "strict_red_not_before_source_edit",
    "strict_source_edit_unobserved", "strict_reviewer_before_last_edit:", "strict_missing_tdd_evidence",
    "strict_edit_after_spec_gate:", "strict_spec_status_without_approval", "strict_plan_after_spec_gate",
    "strict_missing_gate_stop",
)
FLAT_SPEC_PATH = "docs/agentic-sdlc/specs/greeting-suffix.md"
PP_SPEC_PATH = "docs/agentic-sdlc/greeting-suffix/spec/greeting-suffix.md"
FLAT_TDD_PATH = "docs/agentic-sdlc/evidence/greeting-suffix.tdd.md"
CORE_READ_PATH = "/opt/agentic-sdlc/skills/feature-build/references/core.md"
SHALLOW_STUBS = ["shallow_artifact:docs/agentic-sdlc/plans/greeting-suffix.md",
                 "shallow_artifact:docs/agentic-sdlc/specs/greeting-suffix.md"]
# C17.1: a spec/plan path no root can relativize keeps unsafe_artifact_path, its id carrying only the last two segments.
NO_ROOT_UNSAFE = ["unsafe_artifact_path:plans/greeting-suffix.md", "unsafe_artifact_path:specs/greeting-suffix.md"]
UNATTRIBUTED_RED = ["strict_missing_red_before_green", "strict_red_not_before_source_edit",
                    "strict_step_missing:red-run", "strict_test_run_unattributable"]
NO_ATTRIBUTABLE_RUN = ["strict_missing_green", "strict_red_not_before_source_edit", "strict_step_missing:green-run",
                       "strict_step_missing:red-run", "strict_test_run_unattributable"]
CLAUDE_FINAL_TEXT = "Greeting suffix feature implemented; see the verification summary above."
CODEX_FINAL_TEXT = ("Codex Adapter Gate: completion-claim-gate\nVerified: tests ran red then green, the security review "
                    "and implementation control completed.\n<!-- agentic-sdlc:gate:completion-claim:verified -->")
GATE_STOP_FINAL_TEXT = ("Stopped at the Spec Review gate. Please review docs/agentic-sdlc/specs/greeting-suffix.md and "
                        "approve it, or ask for changes, before I write the plan.")
STRICT_POSITIVE_RUNS = (  # (fixture, eval set, case ids): each must pass strict replay with no error at all
    ("procedure-strict-claude-complete-pass.jsonl", PIPELINE_EVAL, PIPELINE_CASES),
    ("procedure-strict-claude-red-before-source-pass.jsonl", PIPELINE_EVAL, PIPELINE_CASES),
    ("procedure-strict-codex-complete-pass.jsonl", PIPELINE_EVAL, PIPELINE_CASES),
    ("agentic-sdlc-pipeline-procedure-per-package-pass.jsonl", PIPELINE_EVAL, (PER_PACKAGE_CASE_ID,)),
    ("procedure-strict-claude-gate-stop-pass.jsonl", GATE_STOP_EVAL, (GATE_STOP_CASE,)),
    # C17.1: absolute spec/plan paths under the init cwd are relativized and depth-checked (both are deep).
    ("procedure-strict-claude-absolute-paths-pass.jsonl", PIPELINE_EVAL, PIPELINE_CASES),
)
DEFAULT_POSITIVE_RUNS = (  # (fixture, case ids): each must pass default-mode replay
    ("agentic-sdlc-pipeline-procedure-pass.jsonl", PIPELINE_CASES),
    ("agentic-sdlc-pipeline-procedure-codex-adapter-pass.jsonl", PIPELINE_CASES),
    ("agentic-sdlc-pipeline-procedure-codex-exec-current.jsonl", PIPELINE_CASES),
    ("agentic-sdlc-pipeline-procedure-codex-exec-bash-wrapper.jsonl", PIPELINE_CASES),
    ("procedure-strict-claude-complete-pass.jsonl", PIPELINE_CASES),
    ("procedure-strict-claude-red-before-source-pass.jsonl", PIPELINE_CASES),
    ("procedure-strict-claude-absolute-paths-pass.jsonl", PIPELINE_CASES),
    ("agentic-sdlc-pipeline-procedure-per-package-pass.jsonl", (PER_PACKAGE_CASE_ID,)),
)


def c7_errors(errors):
    return sorted(e for e in errors if e.startswith(C7_ERROR_PREFIXES))


def fixture_events(name):
    return procedure_eval.load_json_lines(TRANSCRIPTS / name)


def claude_blocks(event):
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def claude_call_ids(event):
    ids = set()
    for block in claude_blocks(event):
        if block.get("type") == "tool_use":
            ids.add(block.get("id"))
        elif block.get("type") == "tool_result":
            ids.add(block.get("tool_use_id"))
    return ids


def index_after(events, call_id, kind):
    """Index just after the event holding call_id's `tool_use` or `tool_result` block."""
    key = "id" if kind == "tool_use" else "tool_use_id"
    for index, event in enumerate(events):
        if any(block.get("type") == kind and block.get(key) == call_id for block in claude_blocks(event)):
            return index + 1
    raise AssertionError(f"fixture has no {kind} for {call_id}")


def rollout_text_index(events, text):
    for index, event in enumerate(events):
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        parts = payload.get("content") if isinstance(payload.get("content"), list) else []
        if any(isinstance(part, dict) and part.get("text") == text for part in parts):
            return index
    raise AssertionError(f"rollout fixture has no assistant message {text!r}")


def replaced(events, old, new, call_ids=None):
    """Events with `old` replaced by `new` in their JSON text (only in the events of `call_ids` when given)."""
    return [json.loads(json.dumps(event).replace(json.dumps(old)[1:-1], json.dumps(new)[1:-1]))
            if call_ids is None or claude_call_ids(event) & call_ids else event for event in events]


def subagent_call(tool_id, name, input_obj, parent, text):
    return [full_tool_use(tool_id, name, input_obj, parent_tool_use_id=parent),
            dict(claude_result(tool_id, False, text), parent_tool_use_id=parent)]


class C7FixtureReplay(StrictFixtureAssertions):
    """In-process replay exactly as main() grades a transcript: load_trace, then evaluate_case per case with the cwd and
    the contained root set to a copy of the basic fixture (the `--fixture-root` replay). `disk` adds files to that copy."""

    def replay(self, transcript, *, eval_set=PIPELINE_EVAL, case_ids=PIPELINE_CASES, strict=True, disk=None):
        cases = {case["id"]: case for case in self.load_cases(eval_set)}
        path = transcript if isinstance(transcript, Path) else TRANSCRIPTS / transcript
        self.assertTrue(path.is_file(), f"fixture missing: {path.name}")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "fixture"
            shutil.copytree(BASIC_FIXTURE, root)
            for relative, content in (disk or {}).items():
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_bytes(content.encode("utf-8"))
            trace = procedure_eval.load_trace(path, strict)
            results = {}
            for case_id in case_ids:
                self.assertIn(case_id, cases, f"{eval_set} has no case {case_id}")
                results[case_id] = procedure_eval.evaluate_case(cases[case_id], trace, root, strict=strict,
                                                                contained_root=root)
        return results

    def replay_events(self, events, **kwargs):
        with tempfile.TemporaryDirectory() as td:
            return self.replay(write_jsonl(Path(td) / "derived.jsonl", events), **kwargs)

    def assert_errors(self, results, expected):
        """Exact sorted errors per case (C15.4: never a set); `expected` is one list or a {case id: list} map."""
        for case_id, errors in results.items():
            want = expected[case_id] if isinstance(expected, dict) else expected
            with self.subTest(case=case_id):
                self.assertEqual(sorted(errors), sorted(want))

    def assert_fixture_errors(self, fixture, expected, **kwargs):
        with self.subTest(fixture=fixture):
            self.assert_errors(self.replay(fixture, **kwargs), expected)


class TestC7EvalSets(StrictFixtureAssertions):
    """C7: the pipeline eval files carry the zero-delegation cases literally (cases 1/2 here, case 3 separately)."""

    def main_cases(self):
        cases = self.load_cases(PIPELINE_EVAL)
        self.assertEqual([case["id"] for case in cases], list(PIPELINE_CASES))
        return cases

    def gate_stop_cases(self):
        return self.load_cases(GATE_STOP_EVAL)

    def test_case_prompts_drop_smoke_depth_and_pre_approve_the_gates(self):
        first, second = self.main_cases()
        self.assertEqual(first["prompt"], C7_CASE1_PROMPT)
        self.assertEqual(second["prompt"], C7_CASE2_PROMPT)

    def test_case1_gates_are_met_by_agents_and_c5_markers(self):
        first = self.main_cases()[0]
        self.assertIn("required_skills", first)
        self.assertEqual(first["required_skills"], C7_REQUIRED_SKILLS)
        adapters = first.get("required_runtime_adapters", [])
        self.assertEqual(len(adapters), 1)  # regression guard: C7 changes the one adapter, it does not add one
        self.assertEqual(adapters[0].get("satisfies"), C7_ADAPTER_SATISFIES)
        self.assertEqual(adapters[0].get("required_patterns"), C7_ADAPTER_PATTERNS)
        # Regression guard: C7 leaves required_workflows as it is.
        self.assertEqual(first.get("required_workflows"), ["agentic-sdlc:spec-plan-draft"])

    def test_every_pipeline_case_forbids_the_three_patterns_and_git_publishing(self):
        for case in list(self.main_cases()) + list(self.gate_stop_cases()):
            with self.subTest(case=case["id"]):
                self.assertIn("forbidden_patterns", case)
                self.assertCountEqual(case["forbidden_patterns"], C7_FORBIDDEN_PATTERNS)
                self.assertEqual(case.get("forbidden_commands"), GIT_PUBLISH_COMMANDS)

    def test_gate_stop_file_holds_one_strict_only_case(self):
        cases = self.gate_stop_cases()
        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual(case["id"], GATE_STOP_CASE)
        self.assertEqual(case.get("fixture_dir"), "tests/fixtures/agentic-sdlc-pipeline-basic")  # C15.12
        self.assertEqual(case["prompt"], C7_GATE_STOP_PROMPT)
        self.assertEqual(case.get("required_commands"), ["detect_context\\.py", "validate_artifacts\\.py"])
        self.assertEqual(case.get("required_patterns"), ["docs/agentic-sdlc/(?:specs|[a-z0-9][a-z0-9-]*/spec)/"])
        self.assertIn("strict", case)
        self.assertEqual(case["strict"], C7_GATE_STOP_STRICT)

    def test_gate_stop_file_dry_run_passes(self):
        self.require_eval_set(GATE_STOP_EVAL)
        proc = run_cli("--eval-set", GATE_STOP_EVAL, "--dry-run", "--strict-evidence")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("cases=1", proc.stdout.splitlines())

    def test_forbidden_pattern_literals_catch_only_the_focused_shapes(self):
        # Guards the literals this file copies from C7: each catches its shape and stays silent on the allowed ones.
        hits = {
            FORBIDDEN_SKILL_CALL: ['"skill": "agentic-sdlc:feature-build"', '"skill":"implementation-control"'],
            FORBIDDEN_SKILL_PATH: ["skills/feature-build/SKILL.md", "skills\\root-cause-fix\\SKILL.md",
                                   "skills\\\\safe-refactor\\\\SKILL.md", "skills/test-authoring//SKILL.md"],
            FORBIDDEN_ADAPTER_GATE: ["Codex Adapter Gate: security-audit", "Grok Adapter Gate: test-authoring activated",
                                     "Cursor Adapter Gate:implementation-control"],
        }
        misses = {
            FORBIDDEN_SKILL_CALL: ['"skill": "agentic-sdlc:dispatch-strategy"', '"skill": "agentic-sdlc:feature-build-x"',
                                   "run security-audit later"],
            FORBIDDEN_SKILL_PATH: ["skills/feature-build/references/core.md",
                                   "skills\\feature-build\\references\\core.md", "skills/dispatch-strategy/SKILL.md"],
            FORBIDDEN_ADAPTER_GATE: ["Codex Adapter Gate: security-reviewer", "Codex Adapter Gate: implementation-auditor",
                                     "Codex Adapter Gate: work-type core feature",
                                     "Codex Adapter Gate: dispatch-strategy activated"],
        }
        for pattern, samples in hits.items():
            for sample in samples:
                with self.subTest(pattern=pattern[:20], sample=sample):
                    self.assertTrue(procedure_eval.regex_present(pattern, sample))
        for pattern, samples in misses.items():
            for sample in samples:
                with self.subTest(pattern=pattern[:20], sample=sample):
                    self.assertFalse(procedure_eval.regex_present(pattern, sample))

    @unittest.skipUnless(shutil.which("node"), "node unavailable: the redaction check needs hooks/redact-sensitive.mjs")
    def test_pipeline_fixtures_outside_the_strict_globs_are_committed_clean_lf(self):
        # C15.14: the agentic-sdlc-pipeline-* fixtures (incl. per-package-pass, codex-adapter-pass, codex-exec-current
        # and the codex-exec bash-wrapper run) get the same LF and redaction pin as the procedure-strict-* globs.
        self.assert_committed_clean_lf("agentic-sdlc-pipeline-*.jsonl", 7)


C7_MALFORMED_STRICT_VALUES = (
    ("red_before_source_edit", "yes"), ("red_before_source_edit", 1), ("red_before_source_edit", None),
    ("stop_at_gate", "plan-review"), ("stop_at_gate", True), ("stop_at_gate", ["spec-review"]),
    ("skill_call_counts", ["dispatch-strategy"]), ("skill_call_counts", {"dispatch-strategy": 1}),
    ("skill_call_counts", {"dispatch-strategy": [1]}), ("skill_call_counts", {"dispatch-strategy": [1, 1, 1]}),
    ("skill_call_counts", {"dispatch-strategy": ["1", "1"]}),
    ("skill_call_counts", {"dispatch-strategy": [2, 1]}),  # C15.14: min above max
    ("skill_call_counts", {"dispatch-strategy": [-1, 1]}),  # C15.14: a negative bound
    ("skill_call_counts", {"dispatch-strategy": [True, True]}),  # C15.14: booleans are not counts
    ("skill_call_counts", {"dispatch-strategy": [1.0, 1]}),
    ("forbid_skills_anywhere", "feature-build"), ("forbid_skills_anywhere", [1]),
    ("forbid_skills_anywhere", {"feature-build": True}), ("forbid_skills_anywhere", [True]),
    ("reviewers_after_last_source_edit", "true"), ("reviewers_after_last_source_edit", None),
    ("evidence_file_before_control", 0), ("evidence_file_before_control", "yes"),
    ("required_order", ["dispatch-strategy", "core-step"]),
)


class TestC7StrictConfig(unittest.TestCase):
    """C7: validate_strict_config accepts the six new keys and rejects malformed values by name."""

    def assert_accepted(self, call, *args):
        try:
            return call(*args)
        except ValueError as exc:  # a rejection is this test's failure, never an error of the test itself
            self.fail(f"C7 strict config rejected: {exc}")

    def test_validate_strict_config_accepts_the_c7_keys(self):
        self.assert_accepted(procedure_eval.validate_strict_config, "c7-full", C7_FULL_RUN_STRICT)
        self.assert_accepted(procedure_eval.validate_strict_config, "c7-gate", C7_GATE_STOP_STRICT)
        for key, value in (("red_before_source_edit", False), ("reviewers_after_last_source_edit", False),
                           ("evidence_file_before_control", False), ("stop_at_gate", "spec-review"),
                           ("skill_call_counts", {"dispatch-strategy": [0, 2], "completion-claim-gate": [1, 1]}),
                           ("forbid_skills_anywhere", ["feature-build"]),
                           ("required_order", ["dispatch-strategy", "core-read", "core-skill"])):
            with self.subTest(key=key):
                self.assert_accepted(procedure_eval.validate_strict_config, "c7-key", {key: value})

    def test_load_eval_accepts_a_case_with_every_c7_key(self):
        with tempfile.TemporaryDirectory() as td:
            eval_set = Path(td) / "eval.json"
            strict = dict(C7_FULL_RUN_STRICT, stop_at_gate="spec-review")
            eval_set.write_text(json.dumps({"cases": [{"id": "c7-probe", "prompt": "p", "strict": strict}]}),
                                encoding="utf-8")
            cases = self.assert_accepted(procedure_eval.load_eval, eval_set)
        self.assertEqual(cases[0]["strict"], strict)

    def test_validate_strict_config_rejects_malformed_c7_values(self):
        for key, value in C7_MALFORMED_STRICT_VALUES:
            with self.subTest(key=key, value=value):
                with self.assertRaisesRegex(ValueError, rf"^case c7-bad invalid strict\.{re.escape(key)}$"):
                    procedure_eval.validate_strict_config("c7-bad", {key: value})

    def test_order_ids_add_core_read_and_keep_core_skill(self):
        # C15.10: core-read joins STRICT_ORDER_IDS; core-skill stays defined but no pipeline case uses it.
        self.assertEqual(procedure_eval.STRICT_ORDER_IDS, frozenset({
            "dispatch-strategy", "spec-written", "plan-written", "core-skill", "core-read", "red-run", "green-run",
            "security", "control", "completion-claim-gate"}))
        self.assertNotIn("core-skill", C7_FULL_RUN_STRICT["required_order"])


class TestC7FinalAssistantText(unittest.TestCase):
    """C7: the final assistant text comes from the rollout final_assistant_text, else the LAST Claude `result` string,
    else the last codex-exec agent_message."""

    def test_claude_result_string_is_the_final_text(self):
        events = [assistant_text_event("Spec Review gate reached; asking for approval."),
                  {"type": "result", "subtype": "success", "is_error": False,
                   "result": "Stopped at the Spec Review gate."}]
        self.assertEqual(procedure_eval.trace_events(events, strict=True).final_assistant_text,
                         "Stopped at the Spec Review gate.")

    def test_codex_exec_last_agent_message_is_the_final_text(self):
        events = [
            {"type": "item.completed", "item": {"id": "m1", "type": "agent_message", "text": "Runtime: Codex."}},
            {"type": "item.completed", "item": {"id": "c1", "type": "command_execution", "command": "python -m pytest -q",
                                                "aggregated_output": "1 passed\n", "exit_code": 0, "status": "completed"}},
            {"type": "item.completed", "item": {"id": "m2", "type": "agent_message",
                                                "text": "Stopped at the Spec Review gate."}},
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
        ]
        self.assertEqual(procedure_eval.trace_events(events, strict=True).final_assistant_text,
                         "Stopped at the Spec Review gate.")

    def test_committed_fixtures_expose_their_final_text(self):
        for fixture, expected in (
            ("procedure-strict-claude-complete-pass.jsonl", CLAUDE_FINAL_TEXT),
            ("procedure-strict-claude-absolute-paths-pass.jsonl", CLAUDE_FINAL_TEXT),  # the second of two results
            ("procedure-strict-claude-gate-stop-pass.jsonl", GATE_STOP_FINAL_TEXT),
            ("procedure-strict-claude-gate-stop-absolute-edit.jsonl", GATE_STOP_FINAL_TEXT),  # second of two results
            ("procedure-strict-claude-gate-stop-no-stop-text.jsonl", "The spec is saved and validated."),
            ("procedure-strict-codex-complete-pass.jsonl", CODEX_FINAL_TEXT),
            ("procedure-strict-codex-gate-stop-spec-approved.jsonl", GATE_STOP_FINAL_TEXT),
            ("agentic-sdlc-pipeline-procedure-codex-exec-bash-wrapper.jsonl",
             "Codex Adapter Gate: completion-claim-gate\nImplemented the greeting suffix; tests ran red then green."),
        ):
            with self.subTest(fixture=fixture):
                trace = procedure_eval.load_trace(TRANSCRIPTS / fixture, True)
                self.assertEqual(trace.final_assistant_text, expected)
        exec_trace = procedure_eval.load_trace(TRANSCRIPTS / "agentic-sdlc-pipeline-procedure-codex-exec-current.jsonl", True)
        self.assertTrue(exec_trace.final_assistant_text.startswith(
            "Codex Adapter Gate: completion-claim-gate satisfied before the final report."), exec_trace.final_assistant_text)


class TestC7ForbiddenSkills(C7FixtureReplay):
    """C7 forbid_skills_anywhere and the three forbidden_patterns: each fires on its negative and stays silent on every
    positive (pattern 2 in both separator styles; a sub-agent call is caught only by forbid_skills_anywhere, AC17)."""

    def test_top_level_focused_skill_call(self):
        self.assert_fixture_errors("procedure-strict-claude-forbidden-skill-top-level.jsonl",
                                   [P1_HIT, "strict_forbidden_skill:feature-build"])

    def test_focused_skill_call_inside_a_subagent(self):
        self.assert_fixture_errors("procedure-strict-claude-forbidden-skill-in-subagent.jsonl",
                                   ["strict_forbidden_skill:security-audit"])

    def test_focused_skill_md_read_posix_and_windows_paths(self):
        self.assert_fixture_errors("procedure-strict-claude-focused-skill-read-posix.jsonl",
                                   [P2_HIT, "strict_forbidden_skill:feature-build"])
        self.assert_fixture_errors("procedure-strict-claude-focused-skill-read-windows.jsonl",
                                   [P2_HIT, "strict_forbidden_skill:root-cause-fix"])

    def test_focused_skill_md_read_inside_a_subagent(self):
        events = fixture_events("procedure-strict-claude-complete-pass.jsonl")
        at = index_after(events, "toolu_s18", "tool_use")
        events[at:at] = subagent_call("toolu_n02", "Read",
                                      {"file_path": "D:\\plugins\\agentic-sdlc\\skills\\safe-refactor\\SKILL.md"},
                                      "toolu_s18", "---\nname: safe-refactor\n---")
        self.assert_errors(self.replay_events(events), ["strict_forbidden_skill:safe-refactor"])
        self.assert_errors(self.replay_events(events, strict=False), [])  # sub-agent records stay out of the haystack

    def test_focused_skill_md_read_through_a_claude_shell_command(self):
        events = fixture_events("procedure-strict-claude-complete-pass.jsonl")
        at = index_after(events, "toolu_s11", "tool_result")
        events[at:at] = claude_run("toolu_b02", "cat /opt/agentic-sdlc/skills/test-authoring/SKILL.md", False,
                                   "---\nname: test-authoring\n---")
        self.assert_errors(self.replay_events(events), [P2_HIT, "strict_forbidden_skill:test-authoring"])

    def test_codex_focused_adapter_gate_marker(self):
        self.assert_fixture_errors("procedure-strict-codex-focused-adapter-gate.jsonl", [P3_HIT])

    def test_codex_focused_skill_md_command(self):
        events = fixture_events("procedure-strict-codex-complete-pass.jsonl")
        at = rollout_text_index(events, "Codex Adapter Gate: work-type core feature") + 1
        events[at:at] = [exec_call("call_x1", 'cat "$PLUGIN_ROOT/skills/security-audit/SKILL.md"'),
                         exec_output("call_x1", 0, "---\nname: security-audit\n---\n")]
        self.assert_errors(self.replay_events(events), [P2_HIT, "strict_forbidden_skill:security-audit"])

    def test_default_mode_reports_the_haystack_patterns(self):
        for fixture, expected in (
            ("procedure-strict-claude-forbidden-skill-top-level.jsonl", [P1_HIT]),
            ("procedure-strict-claude-focused-skill-read-posix.jsonl", [P2_HIT]),
            ("procedure-strict-claude-focused-skill-read-windows.jsonl", [P2_HIT]),
            ("procedure-strict-claude-forbidden-skill-in-subagent.jsonl", []),
        ):
            self.assert_fixture_errors(fixture, expected, strict=False)
        events = fixture_events("agentic-sdlc-pipeline-procedure-codex-exec-current.jsonl")
        events.insert(len(events) - 1, {"type": "item.completed", "item": {
            "id": "item_x", "type": "agent_message", "text": "Codex Adapter Gate: safe-refactor activated"}})
        self.assert_errors(self.replay_events(events, strict=False), [P3_HIT])

    def test_positive_fixtures_pass_default_mode(self):
        for fixture, case_ids in DEFAULT_POSITIVE_RUNS:
            self.assert_fixture_errors(fixture, [], strict=False, case_ids=case_ids)


class TestC7StrictKeys(C7FixtureReplay):
    """C7/C15 red_before_source_edit, skill_call_counts, reviewers_after_last_source_edit, evidence_file_before_control,
    stop_at_gate and core-read: each negative fails with exactly its contract error ids; every positive has none."""

    def test_red_before_source_edit(self):
        # No test write before the RED run (the core's first step is missing).
        self.assert_fixture_errors("procedure-strict-claude-missing-failing-test.jsonl",
                                   ["strict_red_not_before_source_edit"])
        # Test edit and a first production edit both land before the only failing run.
        self.assert_fixture_errors("procedure-strict-claude-red-after-source-edit.jsonl",
                                   ["strict_red_not_before_source_edit"])
        # A piped or echoed RED is unattributable, so no failing run separates Wt from Ws.
        self.assert_fixture_errors("procedure-strict-claude-piped-red.jsonl", UNATTRIBUTED_RED)
        self.assert_fixture_errors("procedure-strict-claude-echo-hidden-red.jsonl", UNATTRIBUTED_RED)
        self.assert_fixture_errors("procedure-strict-codex-green-only.jsonl", [
            "strict_missing_red_before_green", "strict_red_not_before_source_edit", "strict_step_missing:red-run"])
        self.assert_fixture_errors("procedure-strict-codex-fail-open.jsonl", NO_ATTRIBUTABLE_RUN)

    def test_codex_exec_bash_wrapper_runs_stay_unattributed(self):
        # C15.13: pins the CURRENT outcome. Real codex exec wraps every command as `/bin/bash -lc '<cmd>'`, which BR6
        # does not attribute, so RED and GREEN are both unattributable. Extending attribution is open decision O5.
        self.assert_fixture_errors("agentic-sdlc-pipeline-procedure-codex-exec-bash-wrapper.jsonl", NO_ATTRIBUTABLE_RUN)

    def test_green_required_but_source_write_unobserved(self):
        # C15.2: Ws absent emits only strict_source_edit_unobserved (require_red_green is true in cases 1/2).
        self.assert_fixture_errors("procedure-strict-claude-source-edit-unobserved.jsonl",
                                   ["strict_source_edit_unobserved"])

    def test_core_read_order_id(self):
        # C15.10: a run that never reads the work-type core file misses the core-read step.
        self.assert_fixture_errors("procedure-strict-claude-missing-core-read.jsonl", ["strict_step_missing:core-read"])

    def test_skill_call_counts(self):
        self.assert_fixture_errors("procedure-strict-claude-dispatch-twice.jsonl",
                                   ["strict_skill_call_count:dispatch-strategy=2"])
        # With the key present, DELEGATION_SATISFIES no longer lets an Agent call stand in for dispatch-strategy (L858
        # required_skills and L2050 step order).
        self.assert_fixture_errors("procedure-strict-claude-dispatch-substituted.jsonl", {
            PIPELINE_CASES[0]: ["missing_skill:agentic-sdlc:dispatch-strategy",
                                "strict_skill_call_count:dispatch-strategy=0", "strict_step_missing:dispatch-strategy"],
            PIPELINE_CASES[1]: ["strict_skill_call_count:dispatch-strategy=0", "strict_step_missing:dispatch-strategy"],
        })
        # C15.8: every strict key is inert in default mode, which keeps the delegation credit.
        self.assert_fixture_errors("procedure-strict-claude-dispatch-substituted.jsonl", [], strict=False,
                                   case_ids=(PIPELINE_CASES[0],))
        events = fixture_events("procedure-strict-codex-complete-pass.jsonl")  # Codex counts the gate markers
        at = rollout_text_index(events, "Codex Adapter Gate: security-reviewer")
        events[at:at] = [assistant_message("Codex Adapter Gate: dispatch-strategy activated")]
        self.assert_errors(self.replay_events(events), ["strict_skill_call_count:dispatch-strategy=2"])

    def test_skill_call_counts_main_loop_exact_names_only(self):
        events = fixture_events("procedure-strict-claude-complete-pass.jsonl")
        with self.subTest(variant="a sub-agent dispatch-strategy call does not count"):
            sub = list(events)
            at = index_after(sub, "toolu_s18", "tool_use")
            sub[at:at] = subagent_call("toolu_n03", "Skill", {"skill": "agentic-sdlc:dispatch-strategy"}, "toolu_s18",
                                       "Launching skill: agentic-sdlc:dispatch-strategy")
            self.assert_errors(self.replay_events(sub), [])
        with self.subTest(variant="a near-miss name and an args mention do not count"):
            near = list(events)
            at = index_after(near, "toolu_s10", "tool_result")
            near[at:at] = (
                [full_tool_use("toolu_x1", "Skill", {"skill": "agentic-sdlc:dispatch-strategy-x"}),
                 claude_result("toolu_x1", False, "Unknown skill: agentic-sdlc:dispatch-strategy-x")]
                + [full_tool_use("toolu_x2", "Skill", {"skill": "agentic-sdlc:mind-spark",
                                                       "args": "follow the dispatch-strategy map"}),
                   claude_result("toolu_x2", False, "Launching skill: agentic-sdlc:mind-spark")])
            self.assert_errors(self.replay_events(near), [])

    def test_codex_marker_counting_drops_duplicate_carriers(self):
        # C15.5: the positive carries its final message on a response_item AND on task_complete; a task_complete or
        # event_msg copy of the preceding response_item message is one message, and one message counts once.
        counted = {"id": "count-probe", "prompt": "p", "strict": {
            "skill_call_counts": {"dispatch-strategy": [1, 1], "completion-claim-gate": [1, 1]}}}
        trace = procedure_eval.load_trace(TRANSCRIPTS / "procedure-strict-codex-complete-pass.jsonl", True)
        self.assertEqual(c7_errors(procedure_eval.evaluate_case(counted, trace, REPO, strict=True)), [])
        events = fixture_events("procedure-strict-codex-complete-pass.jsonl")
        first = "Runtime: Codex. Activated agentic-sdlc-pipeline. Codex Adapter Gate: dispatch-strategy activated"
        at = rollout_text_index(events, first) + 1
        with self.subTest(variant="event_msg copy of the dispatch message"):
            copied = events[:at] + [rollout({"type": "agent_message", "message": first}, "event_msg")] + events[at:]
            self.assert_errors(self.replay_events(copied), [])
        with self.subTest(variant="the marker twice inside one message"):
            twice = replaced(events, first, first + ". Codex Adapter Gate: dispatch-strategy map reused for Steps 8-16")
            self.assert_errors(self.replay_events(twice), [])

    def test_reviewers_after_last_source_edit(self):
        self.assert_fixture_errors("procedure-strict-claude-reviewer-before-last-edit.jsonl",
                                   ["strict_reviewer_before_last_edit:security"])
        events = fixture_events("procedure-strict-claude-complete-pass.jsonl")  # an edit after the auditor result
        at = index_after(events, "toolu_s20", "tool_result")
        events[at:at] = (
            [full_tool_use("toolu_e11", "Edit", {"file_path": "greeting.py", "old_string": "-> str:",
                                                 "new_string": "-> str:  # suffix-aware"}),
             claude_result("toolu_e11", False, "The file greeting.py has been updated.")]
            + claude_run("toolu_e12", "python -m pytest -q", False, "...\n3 passed in 0.02s")
            + [full_tool_use("toolu_e13", "Agent", {"subagent_type": "agentic-sdlc:security-reviewer",
                                                    "prompt": "Re-review greeting.py after the last edit."}),
               claude_result("toolu_e13", False, FINDINGS_TABLE)])
        self.assert_errors(self.replay_events(events), ["strict_reviewer_before_last_edit:control"])

    def test_evidence_file_before_control(self):
        self.assert_fixture_errors("procedure-strict-claude-missing-tdd-evidence.jsonl", ["strict_missing_tdd_evidence"])
        tdd_calls = {"toolu_s14", "toolu_s17"}
        events = fixture_events("procedure-strict-claude-complete-pass.jsonl")
        moved = [event for event in events if claude_call_ids(event) & tdd_calls]
        rest = [event for event in events if not claude_call_ids(event) & tdd_calls]
        self.assertEqual(len(moved), 4)
        at = index_after(rest, "toolu_s20", "tool_result")
        with self.subTest(variant="written after the auditor"):
            self.assert_errors(self.replay_events(rest[:at] + moved + rest[at:]), ["strict_missing_tdd_evidence"])
        with self.subTest(variant="written by a sub-agent (AC17)"):
            tagged = [dict(event, parent_tool_use_id="agent-1") if claude_call_ids(event) & tdd_calls else event
                      for event in events]
            self.assert_errors(self.replay_events(tagged), ["strict_missing_tdd_evidence"])
        with self.subTest(variant="a .tdd.md outside docs/agentic-sdlc/"):
            outside = replaced(events, FLAT_TDD_PATH, "notes/greeting-suffix.tdd.md", call_ids=tdd_calls)
            self.assert_errors(self.replay_events(outside), ["strict_missing_tdd_evidence"])

    def test_stop_at_gate(self):
        self.assert_fixture_errors("procedure-strict-claude-gate-stop-edit-after-spec.jsonl",
                                   ["strict_edit_after_spec_gate:greeting.py"], **GATE_STOP_ONLY)
        self.assert_fixture_errors("procedure-strict-claude-gate-stop-spec-approved.jsonl",
                                   ["strict_spec_status_without_approval"], **GATE_STOP_ONLY)
        self.assert_fixture_errors("procedure-strict-claude-gate-stop-plan-written.jsonl",
                                   ["strict_plan_after_spec_gate"], **GATE_STOP_ONLY)
        # A deliberate probe of WHICH field is read: an earlier assistant text says "Spec Review gate", but the final
        # assistant text (the result string) does not, so the gate stop is missing.
        self.assert_fixture_errors("procedure-strict-claude-gate-stop-no-stop-text.jsonl",
                                   ["strict_missing_gate_stop"], **GATE_STOP_ONLY)
        # C15.13: init cwd, absolute paths, two results; the path is relativized and the LAST result is the final text.
        self.assert_fixture_errors("procedure-strict-claude-gate-stop-absolute-edit.jsonl",
                                   ["strict_edit_after_spec_gate:greeting.py"], **GATE_STOP_ONLY)

    def test_stop_at_gate_multiplicity_and_notebook_writes(self):
        # C15.4: one strict_edit_after_spec_gate per distinct normalized path; C15.6: NotebookEdit writes notebook_path.
        events = fixture_events("procedure-strict-claude-gate-stop-edit-after-spec.jsonl")
        at = index_after(events, "toolu_g06", "tool_result")
        extra = ([full_tool_use("toolu_g07", "Edit", {"file_path": "greeting.py", "old_string": "-> str:",
                                                      "new_string": "-> str:  # second edit"}),
                  claude_result("toolu_g07", False, "The file greeting.py has been updated.")]
                 + [full_tool_use("toolu_g08", "Edit", {"file_path": "test_greeting.py", "old_string": "def test_greet",
                                                        "new_string": "def test_greet_default"}),
                    claude_result("toolu_g08", False, "The file test_greeting.py has been updated.")])
        with self.subTest(variant="two edits to greeting.py, one to test_greeting.py"):
            self.assert_errors(self.replay_events(events[:at] + extra + events[at:], **GATE_STOP_ONLY),
                               ["strict_edit_after_spec_gate:greeting.py", "strict_edit_after_spec_gate:test_greeting.py"])
        gate = fixture_events("procedure-strict-claude-gate-stop-pass.jsonl")
        at = index_after(gate, "toolu_g05", "tool_result")
        notebook = [full_tool_use("toolu_g09", "NotebookEdit", {"notebook_path": "notebooks/explore.ipynb",
                                                                "cell_id": "c1", "new_source": "greet('Ada', '?')"}),
                    claude_result("toolu_g09", False, "Updated cell c1")]
        with self.subTest(variant="a NotebookEdit after the spec"):
            self.assert_errors(self.replay_events(gate[:at] + notebook + gate[at:], **GATE_STOP_ONLY),
                               ["strict_edit_after_spec_gate:notebooks/explore.ipynb"])

    def test_stop_at_gate_status_sources(self):
        gate = fixture_events("procedure-strict-claude-gate-stop-pass.jsonl")
        at = index_after(gate, "toolu_g05", "tool_result")
        approve = [full_tool_use("toolu_g06", "Edit", {"file_path": FLAT_SPEC_PATH, "old_string": "status: reviewed",
                                                       "new_string": "status: approved"}),
                   claude_result("toolu_g06", False, f"The file {FLAT_SPEC_PATH} has been updated.")]
        with self.subTest(variant="an Edit new_string sets the status"):
            self.assert_errors(self.replay_events(gate[:at] + approve + gate[at:], **GATE_STOP_ONLY),
                               ["strict_spec_status_without_approval"])
        for status in ("approved", "in_progress", "ready_for_audit", "complete", "draft", "reviewed"):
            with self.subTest(written_status=status):
                expected = [] if status in ("draft", "reviewed") else ["strict_spec_status_without_approval"]
                written = replaced(gate, "status: reviewed", f"status: {status}", call_ids={"toolu_g04"})
                self.assert_errors(self.replay_events(written, **GATE_STOP_ONLY), expected)
        on_disk = "---\nwork_id: greeting-suffix\nstatus: {}\n---\n\n# Spec\n"
        with self.subTest(variant="the spec on disk wins over the Write content (approved on disk)"):
            self.assert_fixture_errors("procedure-strict-claude-gate-stop-pass.jsonl",
                                       ["strict_spec_status_without_approval"],
                                       disk={FLAT_SPEC_PATH: on_disk.format("approved")}, **GATE_STOP_ONLY)
        with self.subTest(variant="the spec on disk wins over the Write content (reviewed on disk)"):
            self.assert_fixture_errors("procedure-strict-claude-gate-stop-spec-approved.jsonl", [],
                                       disk={FLAT_SPEC_PATH: on_disk.format("reviewed")}, **GATE_STOP_ONLY)

    def test_stop_at_gate_per_package_layout(self):
        gate = replaced(fixture_events("procedure-strict-claude-gate-stop-pass.jsonl"), FLAT_SPEC_PATH, PP_SPEC_PATH)
        self.assert_errors(self.replay_events(gate, **GATE_STOP_ONLY), [])
        at = index_after(gate, "toolu_g05", "tool_result")
        plan = [full_tool_use("toolu_g06", "Write", {"file_path": "docs/agentic-sdlc/greeting-suffix/plan/greeting-suffix.md",
                                                     "content": "---\nwork_id: greeting-suffix\nstatus: draft\n---\n"}),
                claude_result("toolu_g06", False, "File created successfully")]
        self.assert_errors(self.replay_events(gate[:at] + plan + gate[at:], **GATE_STOP_ONLY),
                           ["strict_plan_after_spec_gate"])

    def test_codex_update_file_hunks(self):
        # C15.9: the `+` lines of an Update File hunk on the spec count like an Edit new_string, and an empty Update
        # record never replaces the spec content (the Codex positive patches status approved with no shallow_artifact).
        self.assert_fixture_errors("procedure-strict-codex-gate-stop-spec-approved.jsonl",
                                   ["strict_spec_status_without_approval"], **GATE_STOP_ONLY)
        events = fixture_events("procedure-strict-codex-gate-stop-spec-approved.jsonl")
        unapproved = [event for event in events if (event.get("payload") or {}).get("call_id") != "call_g04"]
        self.assertEqual(len(events) - len(unapproved), 2)
        self.assert_errors(self.replay_events(unapproved, **GATE_STOP_ONLY), [])
        self.assert_fixture_errors("procedure-strict-codex-complete-pass.jsonl", [])

    def test_full_run_positive_fails_the_gate_stop_case(self):
        # Why case 3 lives in its own file: a pre-approved full run breaks every stop_at_gate rule, each id once.
        self.assert_fixture_errors("procedure-strict-claude-complete-pass.jsonl", [
            "strict_edit_after_spec_gate:greeting.py", "strict_edit_after_spec_gate:test_greeting.py",
            "strict_missing_gate_stop", "strict_plan_after_spec_gate", "strict_spec_status_without_approval"],
            **GATE_STOP_ONLY)

    def test_rewritten_negatives_fail_only_for_their_intended_reason(self):
        self.assert_fixture_errors("procedure-strict-claude-auditor-partial-overridden.jsonl", BOTH_CRITICAL)
        # C15.14: deep spec/plan content, so each runtime negative fails for its one named reason.
        self.assert_fixture_errors("agentic-sdlc-pipeline-procedure-permission-denied.jsonl", [
            "permission_denied:Bash:python C:/repo/agentic-sdlc/scripts/detect_context.py --path ."])
        self.assert_fixture_errors("agentic-sdlc-pipeline-procedure-runtime-error.jsonl", [
            "runtime_error:Reached maximum budget ($2)", "runtime_error:error_max_budget_usd"])
        self.assert_fixture_errors("procedure-strict-codex-semicolon-forged.jsonl", [
            "strict_missing_green", "strict_step_missing:green-run", "strict_test_run_unattributable"])
        # C15.3: a missing clearing result adds nothing beyond strict_reviewer_result_missing and the order gap.
        self.assert_fixture_errors("procedure-strict-codex-reviewer-missing-security.jsonl", [
            "strict_reviewer_result_missing:security", "strict_step_missing:security"])
        self.assert_fixture_errors("procedure-strict-codex-reviewer-missing-control.jsonl", [
            "strict_reviewer_result_missing:control", "strict_step_missing:control"])

    def test_positive_fixtures_have_no_strict_error(self):
        for fixture, eval_set, case_ids in STRICT_POSITIVE_RUNS:
            self.assert_fixture_errors(fixture, [], eval_set=eval_set, case_ids=case_ids)
        # The default-mode pass fixture keeps the shallow "spec"/"plan" stubs, which is its only strict failure.
        self.assert_fixture_errors("agentic-sdlc-pipeline-procedure-pass.jsonl", SHALLOW_STUBS)

    def test_positive_fixtures_pass_strict_cli_replay(self):
        for fixture, eval_set, case_ids in STRICT_POSITIVE_RUNS:
            if "complete-pass" in fixture:
                continue  # the two complete-pass CLI replays live in TestStrictClaudeFixtures / TestStrictCodexFixtures
            with self.subTest(fixture=fixture):
                self.assert_positive_strict_pass(fixture, case_ids, eval_set)


def cli_case_fields(stdout):
    return dict(line.split("=", 1) for line in stdout.splitlines() if line.startswith("case_") and "=" in line)


class TestC7AcceptanceLines(StrictFixtureAssertions):
    """C15.7: the grader prints case_<id>_acceptance=pass|fail and case_<id>_acceptance_excluded=<comma list> next to
    the unchanged case_<id>= line; strict_critical_audit:* and unsafe_artifact_path errors are excluded."""

    def assert_acceptance(self, fixture, case_status, acceptance, excluded):
        with tempfile.TemporaryDirectory() as td:
            proc = strict_fixture_replay(td, fixture)
        fields = cli_case_fields(proc.stdout)
        for case_id in PIPELINE_CASES:
            with self.subTest(fixture=fixture, case=case_id):
                for suffix in ("", "_acceptance", "_acceptance_excluded"):
                    self.assertIn(f"case_{case_id}{suffix}", fields, proc.stdout + proc.stderr)
                self.assertEqual(fields[f"case_{case_id}"], case_status)
                self.assertEqual(fields[f"case_{case_id}_acceptance"], acceptance)
                value = fields[f"case_{case_id}_acceptance_excluded"]
                self.assertEqual(sorted(value.split(",")) if value else [], sorted(excluded))

    def test_clean_run(self):
        self.assert_acceptance("procedure-strict-claude-complete-pass.jsonl", "passed", "pass", [])

    def test_auditor_verdict_is_reported_in_its_own_column(self):
        self.assert_acceptance("procedure-strict-claude-auditor-partial-overridden.jsonl", "failed", "pass",
                               BOTH_CRITICAL)

    def test_unsafe_artifact_path_is_excluded(self):
        # C17.1: only a spec/plan path no root can relativize keeps unsafe_artifact_path, so the absolute-paths
        # positive replays without its init cwd here (its absolute paths then stay absolute).
        events = fixture_events("procedure-strict-claude-absolute-paths-pass.jsonl")
        self.assertEqual(events[0].pop("cwd", None), "/work/greeting-suffix")
        with tempfile.TemporaryDirectory() as td:
            transcript = write_jsonl(Path(td) / "absolute-paths-no-cwd.jsonl", events)
            self.assert_acceptance(transcript, "failed", "pass", NO_ROOT_UNSAFE)

    def test_a_counted_error_fails_acceptance(self):
        self.assert_acceptance("procedure-strict-claude-missing-tdd-evidence.jsonl", "failed", "fail", [])


PATH_CASE = {"id": "path-probe", "prompt": "probe", "strict": {"require_red_green": True, "red_before_source_edit": True}}
PATH_TEST_FORMS = ("tests/test_app.py", "test/app.py", "pkg/tests/helpers.py", "test_app.py", "pkg/app_test.go",
                   "web/app.test.ts", "web/app.spec.js", "C:\\work\\repo\\tests\\app.py")
PATH_SOURCE_FORMS = ("src/app.py", "greeting.py", "lib/app.go", "web/app.tsx", "C:\\work\\repo\\src\\app.ts")
PATH_NON_SOURCE_FORMS = ("README.md", "docs/agentic-sdlc/evidence/w.tdd.md", "docs/agentic-sdlc/specs/w.md",
                         "docs/agentic-sdlc/plans/sketch.py", "config/settings.yaml", "notes.txt")
# C15.6: one shared table for the grader helpers and the hook's isSourceFile: (path, is_test_path, is_source_path).
PATH_PARITY_ROWS = (
    ("tests/test_app.py", True, False), ("test/app.py", True, False), ("pkg/tests/helpers.py", True, False),
    ("test_app.py", True, False), ("pkg/app_test.go", True, False), ("web/app.test.ts", True, False),
    ("web/app.spec.js", True, False), ("src/test_helpers/util.py", True, False),
    ("C:\\work\\repo\\tests\\app.py", True, False),
    ("src/app.py", False, True), ("greeting.py", False, True), ("lib/app.go", False, True), ("web/app.tsx", False, True),
    ("src/App.PY", False, True), ("attest.py", False, True), ("contest_entry.py", False, True),
    ("C:\\work\\repo\\src\\app.ts", False, True),
    ("README.md", False, False), ("notes.txt", False, False), ("config/settings.yaml", False, False),
    ("docs/agentic-sdlc/specs/w.md", False, False), ("docs/agentic-sdlc/plans/sketch.py", False, False),
    ("docs/agentic-sdlc/evidence/w.tdd.md", False, False),
)
IS_SOURCE_BATCH_JS = (
    "import { pathToFileURL } from 'node:url';"
    "let s='';process.stdin.on('data',d=>s+=d).on('end',async()=>{"
    "const q=JSON.parse(s);const m=await import(pathToFileURL(q.module).href);"
    "process.stdout.write(JSON.stringify(q.paths.map(p=>m.isSourceFile(p,q.req))));});"
)


def red_green_events(before, after, init_cwd=None):
    """Main-loop writes before one failing run and after it, then a passing run. Each write is a path or a
    (path, parent_tool_use_id, tool) tuple; tool defaults to Write."""
    events = []
    if init_cwd is not None:
        events.append({"type": "system", "subtype": "init", "cwd": init_cwd, "model": "claude-sonnet-5"})

    def writes(prefix, items):
        out = []
        for number, item in enumerate(items):
            path, parent, tool = (tuple(item) + (None, "Write"))[:3] if isinstance(item, tuple) else (item, None, "Write")
            tool = tool or "Write"
            payload = ({"file_path": path, "edits": [{"old_string": "x", "new_string": "y"}]} if tool == "MultiEdit"
                       else {"file_path": path, "content": "x = 1\n"})
            out.append(full_tool_use(f"{prefix}{number}", tool, payload, parent_tool_use_id=parent))
        return out

    events += writes("wb", before)
    events += claude_run("r1", "python -m pytest -q", True, "1 failed")
    events += writes("wa", after)
    events += claude_run("g1", "python -m pytest -q", False, "1 passed")
    return events


class TestC7PathRules(unittest.TestCase):
    """C7 path rules for Wt and Ws: `\\` becomes `/`, paths under the fixture root or the init cwd become relative, a
    source path has a sourceGlobs extension outside the artifact roots and the test regex, and a test path matches
    `(^|/)tests?/|(^|/)test_|_test\\.|\\.test\\.|\\.spec\\.`. Sub-agent writes are neither (AC17)."""

    RED_NOT_BEFORE = ["strict_red_not_before_source_edit"]

    def errors(self, events, cwd=REPO, contained_root=None, case=PATH_CASE):
        trace = procedure_eval.trace_events(events, strict=True)
        return c7_errors(procedure_eval.evaluate_case(case, trace, cwd, strict=True, contained_root=contained_root))

    def test_test_path_forms_are_the_first_test_write(self):
        for path in PATH_TEST_FORMS:
            with self.subTest(path=path):
                self.assertEqual(self.errors(red_green_events([path], ["src/app.py"])), [])
                self.assertEqual(self.errors(red_green_events([], [path, "src/app.py"])), self.RED_NOT_BEFORE)

    def test_source_path_forms_are_the_first_production_write(self):
        for path in PATH_SOURCE_FORMS:
            with self.subTest(path=path):
                self.assertEqual(self.errors(red_green_events(["tests/test_app.py"], [path])), [])
                self.assertEqual(self.errors(red_green_events(["tests/test_app.py", path], [])), self.RED_NOT_BEFORE)

    def test_non_source_paths_are_never_the_production_write(self):
        self.assertEqual(self.errors(red_green_events(["tests/test_app.py", "src/app.py"], [])), self.RED_NOT_BEFORE)
        for path in PATH_NON_SOURCE_FORMS:
            with self.subTest(path=path):
                self.assertEqual(self.errors(red_green_events(["tests/test_app.py", path], ["src/app.py"])), [])

    def test_multiedit_writes_count(self):
        # The positives use Edit (C15.14); the legacy MultiEdit is still a write for Wt and Ws.
        self.assertEqual(self.errors(red_green_events([("tests/test_app.py", None, "MultiEdit")],
                                                      [("src/app.py", None, "MultiEdit")])), [])
        self.assertEqual(self.errors(red_green_events(["tests/test_app.py", ("src/app.py", None, "MultiEdit")], [])),
                         self.RED_NOT_BEFORE)

    def test_source_write_absent(self):
        # C15.2: Ws absent emits only strict_source_edit_unobserved, and only when require_red_green is true.
        no_source = red_green_events(["tests/test_app.py"], [])
        self.assertEqual(self.errors(no_source), ["strict_source_edit_unobserved"])
        lenient = {"id": "path-probe", "prompt": "probe", "strict": {"red_before_source_edit": True}}
        self.assertEqual(self.errors(no_source, case=lenient), [])

    def test_paths_are_made_relative_to_the_init_cwd(self):
        # Without relativizing, /work/tests/... makes every write a test path and Ws is never observed.
        cwd = "/work/tests/sample"
        test, source = cwd + "/test_greeting.py", cwd + "/greeting.py"
        self.assertEqual(self.errors(red_green_events([test], [source], init_cwd=cwd)), [])
        self.assertEqual(self.errors(red_green_events([test, source], [], init_cwd=cwd)), self.RED_NOT_BEFORE)

    def test_paths_are_made_relative_to_the_fixture_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "tests" / "proj"
            root.mkdir(parents=True)
            test, source = str(root / "test_greeting.py"), str(root / "greeting.py")
            self.assertEqual(self.errors(red_green_events([test], [source]), cwd=root, contained_root=root), [])
            self.assertEqual(self.errors(red_green_events([test, source], []), cwd=root, contained_root=root),
                             self.RED_NOT_BEFORE)

    def test_subagent_writes_are_neither_the_test_nor_the_production_write(self):  # AC17
        sub_source = red_green_events(["tests/test_app.py", ("src/app.py", "agent-1")], ["src/app.py"])
        main_source = red_green_events(["tests/test_app.py", "src/app.py"], ["src/app.py"])
        sub_test = red_green_events([("tests/test_app.py", "agent-1")], ["src/app.py"])
        self.assertEqual(self.errors(sub_source), [])
        self.assertEqual(self.errors(main_source), self.RED_NOT_BEFORE)
        self.assertEqual(self.errors(sub_test), self.RED_NOT_BEFORE)


@unittest.skipUnless(shutil.which("node"), "node unavailable: the parity check runs hooks/flow-evidence.mjs isSourceFile")
class TestC7PathHelperParity(unittest.TestCase):
    """C15.6: the grader's is_test_path / is_source_path and the hook's isSourceFile agree on one shared path table."""

    def hook_verdicts(self, req):
        node = shutil.which("node")
        payload = {"module": str(REPO / "hooks" / "flow-evidence.mjs"), "req": req,
                   "paths": [row[0] for row in PATH_PARITY_ROWS]}
        proc = subprocess.run([node, "--input-type=module", "-e", IS_SOURCE_BATCH_JS], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, "node isSourceFile probe crashed: " + proc.stderr[-400:])
        return json.loads(proc.stdout)

    def requirements(self):
        return json.loads((REPO / "hooks" / "flow-requirements.json").read_text(encoding="utf-8"))

    def test_hook_is_source_file_matches_the_table(self):
        for (path, _is_test, is_source), verdict in zip(PATH_PARITY_ROWS, self.hook_verdicts(self.requirements())):
            with self.subTest(path=path):
                self.assertIs(verdict, is_source)

    def test_grader_helpers_match_the_table_and_the_hook(self):
        for name in ("is_test_path", "is_source_path"):
            self.assertTrue(callable(getattr(procedure_eval, name, None)), f"C15.6: grader helper {name} is missing")
        req = self.requirements()
        for (path, is_test, is_source), verdict in zip(PATH_PARITY_ROWS, self.hook_verdicts(req)):
            with self.subTest(path=path):
                self.assertIs(bool(procedure_eval.is_source_path(path, req)), verdict)
                self.assertIs(bool(procedure_eval.is_source_path(path, req)), is_source)
                self.assertIs(bool(procedure_eval.is_test_path(path)), is_test)


# Contract C16 items 1-7 (the grader fix round after the Phase 2 reviews). The procedure-strict-claude-* fixtures named
# here are the Phase 2 review probes, committed as they were built (compact JSON, LF); every expected value is the
# contract outcome.
FAILED_EDIT_TEXT = "<tool_use_error>File has not been read yet. Read it first before writing to it.</tool_use_error>"
# Times regex_present on the grader's haystack shape: a JSON-dumped command naming a focused skill, then a backslash run
# and no SKILL.md. Each size is the best of three runs, so one slow run does not skew the ratio.
PATTERN_TIMING_CHILD = r"""
import json, sys, time
sys.path.insert(0, '.')
from scripts.run_procedure_eval import regex_present
q = json.loads(sys.stdin.read())
out = []
for n in q['sizes']:
    text = json.dumps({'commands': ['type skills\\feature-build' + '\\' * n + 'X']})
    best = None
    for _ in range(3):
        started = time.perf_counter()
        regex_present(q['pattern'], text)
        took = time.perf_counter() - started
        best = took if best is None else min(best, took)
    out.append(best)
print(json.dumps(out))
"""


class TestC16ForbiddenPatternLinear(StrictFixtureAssertions):
    """C16.1: pattern 2 is `(?:<six>)[\\/]+SKILL\\.md`, linear on a long backslash run (lesson 2026-07-01: assert the
    growth RATIO across doublings, never an absolute time)."""

    SIZES = [25000 * 2 ** step for step in range(5)]  # 4 doublings of the source backslash run
    MAX_GROWTH = 48  # linear is about 16x over 4 doublings and quadratic about 256x; the old alternation never finished
    CHILD_TIMEOUT = 30

    def test_pattern2_time_grows_linearly_across_doublings(self):
        patterns = []
        for eval_set in (PIPELINE_EVAL, GATE_STOP_EVAL):
            for case in self.load_cases(eval_set):
                patterns += [pattern for pattern in case.get("forbidden_patterns", []) if "SKILL" in pattern]
        patterns = list(dict.fromkeys(patterns))  # whatever the eval files hold (the literal is pinned in TestC7EvalSets)
        self.assertTrue(patterns, "no pipeline case carries forbidden pattern 2")
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                try:
                    proc = subprocess.run([sys.executable, "-c", PATTERN_TIMING_CHILD], cwd=REPO,
                                          input=json.dumps({"pattern": pattern, "sizes": self.SIZES}),
                                          capture_output=True, text=True, encoding="utf-8",
                                          timeout=self.CHILD_TIMEOUT)
                except subprocess.TimeoutExpired:
                    self.fail(f"pattern 2 is super-linear: {len(self.SIZES)} sizes up to {self.SIZES[-1]} backslashes "
                              f"did not finish in {self.CHILD_TIMEOUT} s")
                self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
                timings = json.loads(proc.stdout)
                growth = timings[-1] / max(timings[0], 1e-9)
                self.assertLess(growth, self.MAX_GROWTH, f"pattern 2 grew {growth:.0f}x over 4 doublings: {timings}")

    def test_pattern2_still_catches_every_separator_style(self):
        for sample in ("skills/feature-build/SKILL.md", "skills\\root-cause-fix\\SKILL.md",
                       json.dumps("skills\\safe-refactor\\SKILL.md"), "skills/test-authoring//SKILL.md",
                       "skills\\/security-audit\\/SKILL.md"):
            with self.subTest(sample=sample):
                self.assertTrue(procedure_eval.regex_present(FORBIDDEN_SKILL_PATH, sample))


class TestC16DispatchTiming(C7FixtureReplay):
    """C16.2: a reviewer clears the last source edit only when its dispatch call comes after that edit and its result
    clears; the TDD evidence file must be written before the first clearing auditor DISPATCH, not its result."""

    def test_a_reviewer_dispatched_before_the_last_edit_does_not_clear_it(self):
        # The security-reviewer call is issued, a source Edit lands, then the reviewer's clearing result arrives.
        self.assert_fixture_errors("procedure-strict-claude-edit-during-security-review.jsonl",
                                   ["strict_reviewer_before_last_edit:security"])
        # A background security-reviewer launch, a source Edit, then the completed task notification.
        self.assert_fixture_errors("procedure-strict-claude-background-reviewer-then-edit.jsonl",
                                   ["strict_reviewer_before_last_edit:security"])

    def test_tdd_evidence_written_after_the_auditor_dispatch_is_missing(self):
        tdd_calls = {"toolu_s14", "toolu_s17"}
        events = fixture_events("procedure-strict-claude-complete-pass.jsonl")
        moved = [event for event in events if claude_call_ids(event) & tdd_calls]
        rest = [event for event in events if not claude_call_ids(event) & tdd_calls]
        self.assertEqual(len(moved), 4)
        at = index_after(rest, "toolu_s20", "tool_use")  # after the auditor call, before its clearing result
        self.assert_errors(self.replay_events(rest[:at] + moved + rest[at:]), ["strict_missing_tdd_evidence"])


class TestC16GateStopScope(C7FixtureReplay):
    """C16.3: under stop_at_gate any write outside docs/agentic-sdlc/ fails, anywhere in the run and in sub-agents too;
    the plan-write and status checks still start at the first spec write."""

    def test_writes_before_the_spec_fail(self):
        self.assert_fixture_errors("procedure-strict-claude-gate-stop-source-before-spec.jsonl",
                                   ["strict_edit_after_spec_gate:greeting.py",
                                    "strict_edit_after_spec_gate:tests/test_suffix.py"], **GATE_STOP_ONLY)

    def test_sub_agent_writes_fail(self):
        self.assert_fixture_errors("procedure-strict-claude-gate-stop-subagent-edit.jsonl",
                                   ["strict_edit_after_spec_gate:greeting.py"], **GATE_STOP_ONLY)
        gate = fixture_events("procedure-strict-claude-gate-stop-pass.jsonl")
        at = index_after(gate, "toolu_g02", "tool_result")  # before the spec write
        calls = (subagent_call("toolu_a2", "Write", {"file_path": "src/new.py", "content": "x = 1\n"}, "toolu_a1",
                               "File created successfully at: src/new.py")
                 + subagent_call("toolu_a3", "MultiEdit", {"file_path": "greeting.py",
                                                           "edits": [{"old_string": "a", "new_string": "b"}]},
                                 "toolu_a1", "Applied 1 edit to greeting.py")
                 + subagent_call("toolu_a4", "NotebookEdit", {"notebook_path": "notebooks/explore.ipynb",
                                                              "cell_id": "c1", "new_source": "x"},
                                 "toolu_a1", "Updated cell c1")
                 + subagent_call("toolu_a5", "Write", {"file_path": "docs/agentic-sdlc/notes/sketch.md",
                                                       "content": "notes\n"}, "toolu_a1", "File created successfully")
                 + [full_tool_use("toolu_a6", "Edit", {"file_path": "lib/other.py", "old_string": "a", "new_string": "b"},
                                  parent_tool_use_id="toolu_a1"),  # a failed sub-agent write is not a write (C16.4)
                    dict(claude_result("toolu_a6", True, FAILED_EDIT_TEXT), parent_tool_use_id="toolu_a1")])
        dispatch = [full_tool_use("toolu_a1", "Agent", {"subagent_type": "general-purpose", "prompt": "Prototype it."})]
        done = [claude_result("toolu_a1", False, "Prototyped.")]
        self.assert_errors(self.replay_events(gate[:at] + dispatch + calls + done + gate[at:], **GATE_STOP_ONLY),
                           ["strict_edit_after_spec_gate:greeting.py", "strict_edit_after_spec_gate:notebooks/explore.ipynb",
                            "strict_edit_after_spec_gate:src/new.py"])


class TestC16FailedCalls(C7FixtureReplay):
    """C16.4: a Claude write whose correlated tool_result is an error is not a write, and skill_call_counts skips a
    Skill call whose only result is an error (the hook's receiptHasError rule)."""

    def test_a_failed_source_edit_before_red_is_not_the_production_write(self):
        self.assert_fixture_errors("procedure-strict-claude-failed-source-edit-before-red.jsonl", [])

    def test_failed_writes_do_not_break_the_gate_stop(self):
        gate = fixture_events("procedure-strict-claude-gate-stop-pass.jsonl")
        at = index_after(gate, "toolu_g05", "tool_result")
        failed = [full_tool_use("toolu_f0", "Write", {"file_path": FLAT_SPEC_PATH,
                                                      "content": "---\nwork_id: greeting-suffix\nstatus: approved\n---\n"}),
                  claude_result("toolu_f0", True, FAILED_EDIT_TEXT),
                  full_tool_use("toolu_f1", "Edit", {"file_path": "greeting.py", "old_string": "a", "new_string": "b"}),
                  claude_result("toolu_f1", True, FAILED_EDIT_TEXT),
                  full_tool_use("toolu_f2", "Edit", {"file_path": FLAT_SPEC_PATH, "old_string": "status: draft",
                                                     "new_string": "status: approved"}),
                  claude_result("toolu_f2", True, "<tool_use_error>String to replace not found in file.</tool_use_error>"),
                  full_tool_use("toolu_f3", "Write", {"file_path": "docs/agentic-sdlc/plans/greeting-suffix.md",
                                                      "content": "---\nstatus: draft\n---\n"}),
                  claude_result("toolu_f3", True, "<tool_use_error>Permission to write was denied.</tool_use_error>")]
        self.assert_errors(self.replay_events(gate[:at] + failed + gate[at:], **GATE_STOP_ONLY), [])
        with self.subTest(variant="a write with no result still counts"):
            pending = [full_tool_use("toolu_f4", "Edit", {"file_path": "greeting.py", "old_string": "a",
                                                          "new_string": "b"})]
            self.assert_errors(self.replay_events(gate[:at] + pending + gate[at:], **GATE_STOP_ONLY),
                               ["strict_edit_after_spec_gate:greeting.py"])

    def test_an_errored_skill_call_is_not_counted(self):
        # An unknown-name dispatch-strategy call errors, then the real call runs: one call counts.
        self.assert_fixture_errors("procedure-strict-claude-dispatch-errored-retry.jsonl", [])
        events = fixture_events("procedure-strict-claude-complete-pass.jsonl")
        at = index_after(events, "toolu_s01", "tool_result")
        with self.subTest(variant="a second call with no result still counts"):
            pending = [full_tool_use("toolu_d2", "Skill", {"skill": "agentic-sdlc:dispatch-strategy"})]
            self.assert_errors(self.replay_events(events[:at] + pending + events[at:]),
                               ["strict_skill_call_count:dispatch-strategy=2"])


class TestC16PathNormalization(C7FixtureReplay):
    """C16.5: a leading `./` is stripped, a root prefix compares case-insensitively, the Codex rollout cwd is a root, and
    an error id never carries an absolute path (an unrelativized path shows its last two segments)."""

    def test_dot_slash_tdd_evidence_path(self):
        self.assert_fixture_errors("procedure-strict-claude-dot-slash-tdd-evidence.jsonl", [])

    def test_drive_letter_case_mismatch_with_the_init_cwd(self):
        # init cwd C:/tmp/pytest-0/test_run0, tool paths c:/tmp/pytest-0/test_run0/... (a pytest tmp_path shape whose
        # test_ segment makes every unrelativized write a test path). C17.1: the depth check relativizes the spec and
        # plan paths against the same roots, so they are depth-checked (both deep) and no unsafe_artifact_path is left,
        # whether or not the OS reads `c:/...` as absolute.
        self.assert_fixture_errors("procedure-strict-claude-drive-case-cwd.jsonl", [])

    def test_codex_rollout_cwd_is_a_root(self):
        events = fixture_events("procedure-strict-codex-complete-pass.jsonl")
        root = "/srv/tests/greeting-suffix"  # a tests/ segment: unrelativized, every write would be a test path
        absolute = replaced(replaced(events, "*** Update File: greeting.py", f"*** Update File: {root}/greeting.py"),
                            "*** Update File: test_greeting.py", f"*** Update File: {root}/test_greeting.py")
        self.assertNotEqual(absolute, events)
        for carrier in ("session_meta", "turn_context"):
            with self.subTest(carrier=carrier):
                rooted = [dict(event, payload=dict(event["payload"], cwd=root)) if event.get("type") == carrier
                          else event for event in absolute]
                self.assert_errors(self.replay_events(rooted), [])
        with self.subTest(variant="no rollout cwd: the absolute paths are kept, never guessed"):
            self.assert_errors(self.replay_events(absolute), ["strict_source_edit_unobserved"])

    def test_error_ids_never_carry_an_absolute_path(self):
        gate = fixture_events("procedure-strict-claude-gate-stop-pass.jsonl")
        at = index_after(gate, "toolu_g05", "tool_result")
        for path, shown in (("/elsewhere/project/greeting.py", "project/greeting.py"),
                            ("D:\\other\\repo\\src\\app.py", "src/app.py"),
                            ("//server/share/tools/run.py", "tools/run.py"),
                            ("c:/app.py", "app.py"),
                            ("./greeting.py", "greeting.py")):
            with self.subTest(path=path):
                edit = [full_tool_use("toolu_g06", "Edit", {"file_path": path, "old_string": "a", "new_string": "b"}),
                        claude_result("toolu_g06", False, "The file has been updated.")]
                self.assert_errors(self.replay_events(gate[:at] + edit + gate[at:], **GATE_STOP_ONLY),
                                   [f"strict_edit_after_spec_gate:{shown}"])
        with self.subTest(variant="an init cwd differing only in case makes the path relative"):
            init = [dict(gate[0], cwd="C:/Work/Repo")] + gate[1:at]
            edit = [full_tool_use("toolu_g07", "Edit", {"file_path": "c:/work/repo/greeting.py", "old_string": "a",
                                                        "new_string": "b"}),
                    claude_result("toolu_g07", False, "The file has been updated.")]
            self.assert_errors(self.replay_events(init + edit + gate[at:], **GATE_STOP_ONLY),
                               ["strict_edit_after_spec_gate:greeting.py"])


class TestC16ArtifactDepthEmptyContent(C7FixtureReplay):
    """C16.6: only an empty Codex `*** Update File:` record is ignored for depth; an empty Claude Write (or an empty Add
    File) is the latest content and yields shallow_artifact, as at 4262a19."""

    def test_an_emptied_claude_spec_is_shallow(self):
        self.assert_fixture_errors("procedure-strict-claude-spec-emptied.jsonl",
                                   ["shallow_artifact:docs/agentic-sdlc/specs/greeting-suffix.md"])

    def test_an_empty_codex_add_file_is_shallow_but_an_update_file_is_ignored(self):
        events = fixture_events("procedure-strict-codex-complete-pass.jsonl")
        at = rollout_text_index(events, "Codex Adapter Gate: work-type core feature")
        empty_add = [patch_call("call_e1", f"*** Begin Patch\n*** Add File: {FLAT_SPEC_PATH}\n*** End Patch\n"),
                     patch_success("call_e1", "A", FLAT_SPEC_PATH)]
        self.assert_errors(self.replay_events(events[:at] + empty_add + events[at:]),
                           ["shallow_artifact:docs/agentic-sdlc/specs/greeting-suffix.md"])
        self.assert_fixture_errors("procedure-strict-codex-complete-pass.jsonl", [])  # its Update File records


class TestC16ForbiddenSkillScanKeys(C7FixtureReplay):
    """C16.7: forbid_skills_anywhere scans the path, pattern, file_path and command keys of every tool, plus
    notebook_path (here inside a sub-agent, so the haystack patterns stay silent and only the strict id fires)."""

    def test_every_path_key_of_every_tool(self):
        events = fixture_events("procedure-strict-claude-complete-pass.jsonl")
        at = index_after(events, "toolu_s18", "tool_use")
        for tool, payload, name in (
            ("Grep", {"pattern": "Steps", "path": "/opt/agentic-sdlc/skills/feature-build/SKILL.md"}, "feature-build"),
            ("Glob", {"pattern": "**/root-cause-fix/SKILL.md"}, "root-cause-fix"),
            ("Write", {"file_path": "skills/safe-refactor/SKILL.md", "content": "x\n"}, "safe-refactor"),
            ("NotebookEdit", {"notebook_path": "skills\\test-authoring\\SKILL.md", "new_source": "x"}, "test-authoring"),
            ("Bash", {"command": "cat skills/security-audit/SKILL.md"}, "security-audit"),
        ):
            with self.subTest(tool=tool):
                derived = list(events)
                derived[at:at] = subagent_call("toolu_n09", tool, payload, "toolu_s18", "ok")
                self.assert_errors(self.replay_events(derived), [f"strict_forbidden_skill:{name}"])
        with self.subTest(variant="other keys and non-string values are not scanned"):
            derived = list(events)
            derived[at:at] = subagent_call("toolu_n10", "Grep", {"pattern": ["feature-build/SKILL.md"], "glob": "*.md",
                                                                 "prompt": "skills/feature-build/SKILL.md"},
                                           "toolu_s18", "ok")
            self.assert_errors(self.replay_events(derived), [])


# Contract C17 items 1-5 (the grader fix round after the final review of e29c571). The inputs reuse the final review's
# probes: abs-shallow.jsonl (committed as procedure-strict-claude-absolute-paths-shallow.jsonl), the G3/G4 traversal
# writes, the G11 Grep shape and a Codex `*** Move to:` rename.
DEPTH_CASE = {"id": "depth-probe", "prompt": "probe", "check_artifact_depth": True}
SPEC_STUB = "---\nwork_id: greeting-suffix\nstatus: reviewed\n---\nspec\n"


class TestC17ArtifactDepthPaths(C7FixtureReplay):
    """C17.1: evaluate_artifact_depth normalizes each spec/plan path with the strict roots first. A path that becomes
    relative is depth-checked under the fixture root; only a path no root can relativize keeps unsafe_artifact_path,
    and its id comes from _error_path (no absolute path, no user name)."""

    def depth_errors(self, events, cwd=REPO, contained_root=None):
        trace = procedure_eval.trace_events(events, strict=True)
        return procedure_eval.evaluate_case(DEPTH_CASE, trace, cwd, contained_root=contained_root)

    @staticmethod
    def write(path, content):
        return [full_tool_use("toolu_w1", "Write", {"file_path": path, "content": content}),
                claude_result("toolu_w1", False, "File created successfully")]

    def test_absolute_paths_under_the_init_cwd_are_depth_checked(self):
        self.assert_fixture_errors("procedure-strict-claude-absolute-paths-pass.jsonl", [])
        # The same run with stub spec and plan bodies (review probe abs-shallow.jsonl): both are shallow now.
        self.assert_fixture_errors("procedure-strict-claude-absolute-paths-shallow.jsonl", SHALLOW_STUBS)

    def test_an_absolute_path_under_the_fixture_root_reads_the_file_on_disk(self):
        # The live-run shape: the Write names the absolute path inside the copied fixture, so the bytes on disk win.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "fixture"
            spec = root / "docs" / "agentic-sdlc" / "specs" / "deep-spec.md"
            spec.parent.mkdir(parents=True)
            spec.write_bytes(DEEP_SPEC.encode("utf-8"))
            events = self.write(str(spec), SPEC_STUB)
            self.assertEqual(self.depth_errors(events, cwd=root, contained_root=root), [])
            spec.write_bytes(SPEC_STUB.encode("utf-8"))
            self.assertEqual(self.depth_errors(events, cwd=root, contained_root=root),
                             ["shallow_artifact:docs/agentic-sdlc/specs/deep-spec.md"])

    def test_an_unrelativizable_path_id_carries_no_absolute_path_or_user_name(self):
        bs = chr(92)
        for path in ("/home/alice/proj/docs/agentic-sdlc/specs/x.md",
                     bs.join(("C:", "Users", "alice", "proj", "docs", "agentic-sdlc", "specs", "x.md")),
                     "//server/share/alice/docs/agentic-sdlc/specs/x.md",
                     "../alice/docs/agentic-sdlc/specs/x.md"):
            with self.subTest(path=path):
                errors = self.depth_errors(self.write(path, DEEP_SPEC))
                self.assertEqual(errors, ["unsafe_artifact_path:specs/x.md"])
                self.assertFalse(any("alice" in error for error in errors), "a user name reached the error id")
        with self.subTest(variant="the absolute-paths positive without its init cwd"):
            events = fixture_events("procedure-strict-claude-absolute-paths-pass.jsonl")
            self.assertEqual(events[0].pop("cwd", None), "/work/greeting-suffix")
            self.assert_errors(self.replay_events(events), NO_ROOT_UNSAFE)


class TestC17GateStopTraversal(C7FixtureReplay):
    """C17.2: `.` and `..` segments collapse, posix-style, before every stop_at_gate classification:
    `docs/agentic-sdlc/../../greeting.py` counts as `greeting.py`."""

    @staticmethod
    def write(tool_id, path, parent=None):
        result = claude_result(tool_id, False, "File created successfully")
        if parent is not None:
            result["parent_tool_use_id"] = parent
        return [full_tool_use(tool_id, "Write", {"file_path": path, "content": "x = 1\n"}, parent_tool_use_id=parent),
                result]

    def gate_with(self, extra):
        gate = fixture_events("procedure-strict-claude-gate-stop-pass.jsonl")
        at = index_after(gate, "toolu_g05", "tool_result")  # after the spec write and its validation
        return self.replay_events(gate[:at] + extra + gate[at:], **GATE_STOP_ONLY)

    def test_a_traversal_out_of_docs_is_the_collapsed_path(self):
        bs = chr(92)
        for path, shown in (("docs/agentic-sdlc/../../greeting.py", "greeting.py"),  # probe G3
                            ("./src/../greeting.py", "greeting.py"),  # probe G4
                            ("docs/agentic-sdlc/specs/../../../tools/run.py", "tools/run.py"),
                            (bs.join(("docs", "agentic-sdlc", "..", "..", "greeting.py")), "greeting.py")):
            with self.subTest(path=path):
                self.assert_errors(self.gate_with(self.write("toolu_t1", path)),
                                   [f"strict_edit_after_spec_gate:{shown}"])
        with self.subTest(variant="a sub-agent traversal write"):
            dispatch = [full_tool_use("toolu_t2", "Agent", {"subagent_type": "general-purpose", "prompt": "Sketch."})]
            done = [claude_result("toolu_t2", False, "Sketched.")]
            nested = self.write("toolu_t3", "docs/agentic-sdlc/notes/../../../src/app.py", parent="toolu_t2")
            self.assert_errors(self.gate_with(dispatch + nested + done), ["strict_edit_after_spec_gate:src/app.py"])

    def test_a_traversal_into_docs_is_inside_the_artifact_base(self):
        self.assert_errors(self.gate_with(self.write("toolu_t4", "src/../docs/agentic-sdlc/notes/n.md")), [])

    def test_a_path_that_escapes_every_root_shows_its_last_two_segments(self):
        # Collapsing leaves the leading `..` of a path above the fixture root; like an absolute path no root makes
        # relative (C16.5), its id carries the last two segments only.
        self.assert_errors(self.gate_with(self.write("toolu_t5", "../../other/repo/app.py")),
                           ["strict_edit_after_spec_gate:repo/app.py"])

    def test_a_traversal_plan_write_after_the_spec(self):
        plan = self.write("toolu_t6", "docs/agentic-sdlc/specs/../plans/greeting-suffix.md")
        self.assert_errors(self.gate_with(plan), ["strict_plan_after_spec_gate"])

    def test_a_traversal_out_of_specs_is_not_the_spec_write(self):
        gate = fixture_events("procedure-strict-claude-gate-stop-pass.jsonl")
        moved = replaced(gate, "docs/agentic-sdlc/specs/greeting-suffix.md",
                         "docs/agentic-sdlc/specs/../notes/greeting-suffix.md", call_ids={"toolu_g04"})
        self.assertNotEqual(moved, gate)
        self.assert_errors(self.replay_events(moved, **GATE_STOP_ONLY), ["strict_step_missing:spec-written"])


class TestC17ForbiddenSkillGlobKey(C7FixtureReplay):
    """C17.3: forbid_skills_anywhere also scans Grep's `glob` key (inside a sub-agent, so only the strict id fires)."""

    def test_a_grep_glob_naming_a_focused_skill_md(self):
        events = fixture_events("procedure-strict-claude-complete-pass.jsonl")
        at = index_after(events, "toolu_s18", "tool_use")
        for glob, name in (("**/feature-build/SKILL.md", "feature-build"),
                           (chr(92).join(("skills", "root-cause-fix", "SKILL.md")), "root-cause-fix")):
            with self.subTest(glob=glob):
                derived = list(events)
                derived[at:at] = subagent_call("toolu_n11", "Grep", {"pattern": "Steps", "glob": glob}, "toolu_s18",
                                               "ok")
                self.assert_errors(self.replay_events(derived), [f"strict_forbidden_skill:{name}"])


class TestC17CodexMoveTo(C7FixtureReplay):
    """C17.4: a Codex `*** Move to:` rename records a write at the destination path, plus the source path; the
    rename's hunk `+` lines count for the status read on either path."""

    def gate_with_patch(self, patch, listed_path):
        events = fixture_events("procedure-strict-codex-gate-stop-spec-approved.jsonl")
        base = [event for event in events if (event.get("payload") or {}).get("call_id") != "call_g04"]
        self.assertEqual(len(events) - len(base), 2)  # without its approving patch the run is a clean gate stop
        at = rollout_text_index(base, GATE_STOP_FINAL_TEXT)
        moved = [patch_call("call_m1", patch), patch_success("call_m1", "M", listed_path)]
        return self.replay_events(base[:at] + moved + base[at:], **GATE_STOP_ONLY)

    def test_a_rename_out_of_docs_writes_the_destination(self):
        patch = ("*** Begin Patch\n*** Update File: docs/agentic-sdlc/notes/sketch.md\n*** Move to: src/sketch.py\n"
                 "@@\n-notes\n+x = 1\n*** End Patch\n")
        self.assert_errors(self.gate_with_patch(patch, "src/sketch.py"), ["strict_edit_after_spec_gate:src/sketch.py"])

    def test_a_rename_into_docs_still_writes_the_source(self):
        patch = ("*** Begin Patch\n*** Update File: greeting.py\n*** Move to: docs/agentic-sdlc/notes/greeting.py\n"
                 "@@\n-x = 1\n+x = 2\n*** End Patch\n")
        self.assert_errors(self.gate_with_patch(patch, "docs/agentic-sdlc/notes/greeting.py"),
                           ["strict_edit_after_spec_gate:greeting.py"])

    def test_a_rename_onto_the_spec_reads_its_status_lines(self):
        patch = ("*** Begin Patch\n*** Update File: docs/agentic-sdlc/notes/draft.md\n"
                 f"*** Move to: {FLAT_SPEC_PATH}\n@@\n-status: reviewed\n+status: approved\n*** End Patch\n")
        self.assert_errors(self.gate_with_patch(patch, FLAT_SPEC_PATH), ["strict_spec_status_without_approval"])


class TestC17SpecStatusMembershipLinear(unittest.TestCase):
    """C17.5: _spec_statuses tests spec-path membership against a set, so the stop_at_gate status read stays linear in
    the number of distinct spec writes (lesson 2026-07-01: assert the growth RATIO across doublings, never a time)."""

    SIZES = [2000 * 2 ** step for step in range(5)]  # 4 doublings of distinct spec writes
    # Linear is about 16x over 4 doublings (15-17x measured with the collector off); the list membership test grew
    # 64-119x on this shape, and the gap widens with size, so the ladder starts at 2000.
    MAX_GROWTH = 40
    CASE = {"id": "status-probe", "prompt": "probe", "strict": {"stop_at_gate": "spec-review"}}

    @staticmethod
    def spec_writes(count):
        return [full_tool_use(f"toolu_w{k}", "Write", {"file_path": f"docs/agentic-sdlc/specs/s{k:06d}.md",
                                                       "content": "---\nwork_id: s\nstatus: reviewed\n---\n"})
                for k in range(count)]

    def test_the_status_read_grows_linearly_with_distinct_spec_writes(self):
        timings = []
        # The per-spec disk lookup is linear and only adds file-system noise, so it is patched out here.
        with mock.patch.object(procedure_eval, "resolve_under", side_effect=ValueError("no disk in this probe")):
            for count in self.SIZES:
                trace = procedure_eval.trace_events(self.spec_writes(count), strict=True)
                best = None
                for _ in range(3):  # best of three, so one slow run does not skew the ratio
                    # The cyclic collector's full passes scan the whole live heap, which grows with the trace, so
                    # they add superlinear noise unrelated to the read (43x on a Windows CI runner). Time with the
                    # collector off, as timeit does, and collect between runs.
                    gc.collect()
                    gc.disable()
                    try:
                        started = time.perf_counter()
                        errors = procedure_eval.evaluate_case(self.CASE, trace, REPO, strict=True)
                        took = time.perf_counter() - started
                    finally:
                        gc.enable()
                    best = took if best is None else min(best, took)
                self.assertEqual(errors, ["strict_missing_gate_stop"])
                timings.append(best)
        growth = timings[-1] / max(timings[0], 1e-9)
        self.assertLess(growth, self.MAX_GROWTH, f"the spec status read grew {growth:.0f}x over 4 doublings: {timings}")
