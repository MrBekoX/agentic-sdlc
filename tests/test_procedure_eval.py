import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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


def full_tool_use(tool_id, name, input_obj):
    block = {"type": "tool_use", "name": name, "input": input_obj}
    if tool_id is not None:
        block["id"] = tool_id
    return {"type": "assistant", "message": {"content": [block]}}

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
        procedure_eval._record_tool(trace, "Skill", {"skill": "agentic-sdlc:implementation-control"})
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


def git_step_of(argv):
    for step, prefix in GIT_STEP_PREFIXES:
        if list(argv[: len(prefix)]) == prefix:
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
            if not argv or argv[0] != "git":
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
        calls = []
        with mock.patch.object(procedure_eval.shutil, "which", return_value="claude"), \
                mock.patch.object(procedure_eval.subprocess, "run", side_effect=self.fake_run("add", calls)):
            code, stdout = run_main(["--eval-set", PIPELINE_EVAL, "--case-id", "agentic-sdlc-pipeline-feature-no-commit",
                                     "--live", "--allow-fixture-commit"])
        self.assertEqual(code, 1, stdout)
        self.assertIn("error=fixture_git_failed:add", stdout)
        self.assertIn("procedure_eval=failed", stdout)
        self.assertEqual([c for c in calls if c and c[0] == "claude"], [])


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


def claude_result(tool_id, is_error, text):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "is_error": is_error, "content": text}]}}


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
) + ('pytest "a' + chr(1) + 'b"',)


class TestStrictRedGreen(unittest.TestCase):
    """AC69, AC123: attributable RED-before-GREEN runs, judged by the shared BR6 table's strict column."""

    def test_attribution_table_matches_shared_cases(self):
        rows = load_br6_rows()
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(id=row["id"]):
                statements = procedure_eval.br6_statements(row["command"])
                self.assertEqual(statements, row["statements"])
                last = statements[-1]
                self.assertEqual(procedure_eval.has_unquoted_pipe(last), row["lastHasPipe"])
                self.assertEqual(procedure_eval.has_unquoted_background(last), row["lastHasBackground"])
                self.assertEqual(procedure_eval.is_version_or_help_only(last, TEST_RE), row["lastVersionOrHelpOnly"])
                self.assertEqual(procedure_eval.in_safe_br6_grammar(row["command"]), row["inSafeGrammar"])
                self.assertEqual(procedure_eval.br6_trailing_or_run(row["command"]), row["orRun"])
                runs = procedure_eval.attributable_test_runs(trace_from_carrier(row), TEST_RE)
                self.assertEqual(bool(runs), row["strictAttributable"])
                self.assertEqual(any(run.exit == 0 for run in runs), row["strictTests"] == "satisfied")

    def test_safe_grammar_production_lists(self):
        # Mutation: dropping any character or command-word production (each listed construct would be admitted).
        self.assertEqual((len(GRAMMAR_INSIDE), len(GRAMMAR_OUTSIDE)), (30, 79))
        for command, expected in [(c, True) for c in GRAMMAR_INSIDE] + [(c, False) for c in GRAMMAR_OUTSIDE]:
            with self.subTest(command=command):
                self.assertIs(procedure_eval.in_safe_br6_grammar(command), expected)

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


STRICT_ORDER = ["dispatch-strategy", "spec-written", "plan-written", "core-skill", "red-run", "green-run",
                "security", "control", "completion-claim-gate"]
SECURITY_REVIEWER = {"step": "security", "skills": ["agentic-sdlc:security-audit"], "agents": ["security-reviewer"],
                     "codex_result": "findings-table"}
CONTROL_REVIEWER = {"step": "control", "skills": ["agentic-sdlc:implementation-control"],
                    "agents": ["implementation-auditor"], "codex_result": "control-verdict"}
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
        cases = procedure_eval.load_eval(REPO / PIPELINE_EVAL)
        self.assertEqual(len(cases), 2)
        for case in cases:
            with self.subTest(case=case["id"]):
                strict = case["strict"]
                self.assertEqual({r["step"] for r in strict["reviewers"]}, {"security", "control"})
                self.assertEqual(strict["required_order"], STRICT_ORDER)
                self.assertIs(strict["require_red_green"], True)
                self.assertIs(strict["check_artifact_depth"], True)

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
        self.assertEqual(reviewer_errors(self.evaluate(reviewer_case(SECURITY_REVIEWER), trace)), [])

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
            [assistant_message("Codex Adapter Gate: security-audit"), assistant_message(CONTROL_REPORT)], strict=True)
        self.assertEqual(reviewer_errors(self.evaluate(case, no_table)), ["strict_reviewer_result_missing:security"])

    def test_codex_never_reports_errored(self):
        trace = procedure_eval.trace_events(
            [assistant_message("Codex Adapter Gate: security-audit"),
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
            full_tool_use("f1", "Skill", {"skill": "agentic-sdlc:feature-build"}), claude_result("f1", False, "ok"),
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
                                      [SECURITY_REVIEWER])
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
                self.assertEqual(self.dispatch_errors("Skill", {"skill": skill}, [SECURITY_REVIEWER]), expected)


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

    def test_packet_contains_required_bindings(self):
        with tempfile.TemporaryDirectory() as td:
            evidence = Path(td) / "ev"
            proc = strict_replay(evidence, self.copy_fixture_root(td))
            packet_path = evidence / f"{PACKET_CASE}.json"
            self.assertTrue(packet_path.is_file(), proc.stdout + proc.stderr)
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            self.assertLessEqual(PACKET_FIELDS, set(packet))
            self.assertEqual((packet["schema_version"], packet["case_id"]), (1, PACKET_CASE))
            self.assertIn(packet["runtime"], {"claude", "codex", "unknown"})
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


TRANSCRIPTS = REPO / "tests" / "fixtures" / "transcripts"
PIPELINE_CASES = ("agentic-sdlc-pipeline-feature-no-commit", "agentic-sdlc-pipeline-per-package")


def strict_fixture_replay(td, fixture_name):
    root = Path(td) / "fixture"
    if not root.exists():
        shutil.copytree(BASIC_FIXTURE, root)
    return run_cli("--eval-set", PIPELINE_EVAL, "--transcript", TRANSCRIPTS / fixture_name, "--strict-evidence",
                   "--fixture-root", root)


class StrictFixtureAssertions(unittest.TestCase):
    def assert_positive_strict_pass(self, fixture_name):
        with tempfile.TemporaryDirectory() as td:
            proc = strict_fixture_replay(td, fixture_name)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("procedure_eval=passed", proc.stdout)
        for case_id in PIPELINE_CASES:
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
            ("procedure-strict-claude-missing-core.jsonl", [
                "agentic-sdlc-pipeline-feature-no-commit:missing_skill:agentic-sdlc:feature-build",
                "agentic-sdlc-pipeline-per-package:strict_step_missing:core-skill",
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
        self.assert_committed_clean_lf("procedure-strict-claude-*.jsonl", 4)


class TestStrictCodexFixtures(StrictFixtureAssertions):
    """AC123: committed Codex rollout fixtures: fail-open, ;-forged, GREEN-only and reviewer-less runs fail named."""

    CODEX_FIXTURES = (
        "procedure-strict-codex-complete-pass.jsonl",
        "procedure-strict-codex-fail-open.jsonl",
        "procedure-strict-codex-semicolon-forged.jsonl",
        "procedure-strict-codex-green-only.jsonl",
        "procedure-strict-codex-reviewer-missing-security.jsonl",
        "procedure-strict-codex-reviewer-missing-control.jsonl",
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
