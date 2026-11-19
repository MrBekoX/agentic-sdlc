"""Regression tests for the skill-text findings of the f430715 bug audit (slice SK).

Each finding is a place where skill, contract or command text tells the model to do something the
code (hooks, validator, resolver) then rejects. Every test pins both sides: it reads the text and,
where the text names a command, runs that command against the real script so the text cannot drift
from the code again.

- SK-1: every spec validation command in skill text carries `--strict`, like the hooks and grader.
- SK-2: feature-build and root-cause-fix save and validate the spec and plan where the resolver and
  the flow hooks look for them.
- SK-3: the runner-only paragraphs of contracts 02 and 03 are scoped to runner flows.
- SK-4: the pipeline's security lenses are direct `Agent(security-reviewer)` calls, never a Workflow.
- SK-6: no "secret scan" is `git diff --check`; git-safety-check scans index, worktree and untracked.
- SK-7: the router sends high-risk implementation work to the pipeline before the focused routes.
- SK-8: mind-spark runs after kickoff and the branch checkpoint, before Step 4.
- SK-9: plan-authoring has a separate validation command for a plan saved without a spec file.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "scripts" / "validate_artifacts.py"
RESOLVER = REPO / "scripts" / "resolve_work_package.py"
PIPELINE = REPO / "skills" / "agentic-sdlc-pipeline" / "SKILL.md"
PLAYBOOK = REPO / "skills" / "agentic-sdlc-pipeline" / "playbook.md"
DISPATCH = REPO / "skills" / "dispatch-strategy" / "SKILL.md"
ROUTER = REPO / "skills" / "using-agentic-sdlc" / "SKILL.md"
PLAN_AUTHORING = REPO / "skills" / "plan-authoring" / "SKILL.md"
GIT_SAFETY = REPO / "commands" / "git-safety-check.md"
CONTRACT_02 = REPO / "contracts" / "skills" / "02-spec-driven-development.md"
CONTRACT_03 = REPO / "contracts" / "skills" / "03-plan-mode.md"
MIND_SPARK_REF = REPO / "skills" / "mind-spark" / "references" / "design-process.md"
FLOW_REQUIREMENTS = REPO / "hooks" / "flow-requirements.json"

WORK_ID = "demo"
BRANCH = "work"

# A spec the strict validator accepts. Synthetic content only: no placeholder, no secret shape.
SPEC_OK = """\
---
work_id: demo
status: reviewed
---
# Spec: demo

## Problem
The export endpoint drops rows whose amount is zero, so the monthly report undercounts orders.

## Business Rules
A zero amount is a valid order amount. Rows keep their input order.

## Acceptance Criteria
- AC1: Given an order with amount 0, when the export runs, then the row appears in the output.
- AC2: Given two orders, when the export runs, then they appear in input order.

## Edge Cases
An empty order list returns an empty export with exit 0.

## Definition of Done
Both criteria pass in the full suite, and the monthly report for a sample month matches the order table.

## Must-not-change
The export column order, the file encoding and the public export API stay exactly the same.
"""

# The same spec with a placeholder: the validator only warns about it, so it passes without
# `--strict` and fails with it (the flow hooks and the grader validate with `--strict`).
SPEC_WITH_PLACEHOLDER = SPEC_OK.replace(
    "Rows keep their input order.", "Rows keep their input order. " + "T" + "BD")

TASKS = """\
## Task 1: keep zero-amount rows (AC1, AC2)
Files: Modify `export.py`.
TDD point: `test_zero_amount_row_kept` asserts the zero row is exported, then `test_order_kept` asserts input order.
Run: `python -m unittest tests.test_export` and expect exit 0.
"""

OWN_CRITERIA = """\
## Acceptance Criteria
- AC1: Given an order with amount 0, when the export runs, then the row appears in the output.
- AC2: Given two orders, when the export runs, then they appear in input order.
"""

HIGH_RISK_SURFACES = ("auth", "payment", "database migration", "API contract", "permissions",
                      "user data", "token/session", "RLS")

# Skill, contract and command text the model reads. Runner step files (`skills/*/steps/`) belong
# to the flow runner and are checked by its own suites.
def skill_text_files():
    files = sorted((REPO / "skills").glob("*/SKILL.md"))
    files += sorted((REPO / "skills").glob("*/references/**/*.md"))
    files += [REPO / "skills" / "agentic-sdlc-pipeline" / name for name in ("playbook.md", "templates.md")]
    files += sorted((REPO / "contracts" / "skills").glob("*.md"))
    files += sorted((REPO / "commands").glob("*.md"))
    files += sorted((REPO / "agents").glob("*.md"))
    files.append(REPO / "docs" / "skill-boundaries.md")
    return [f for f in files if f.is_file()]


def read(path):
    return path.read_text(encoding="utf-8")


def rel(path):
    return path.relative_to(REPO).as_posix()


def code_spans(text):
    """Inline code spans plus every line of a fenced block (a fenced command is a span too)."""
    spans = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            spans.append(line.strip())
        else:
            spans.extend(re.findall(r"`([^`\n]+)`", line))
    return spans


def validator_commands(text, mode):
    """Full validator commands (`python3 ".../validate_artifacts.py" --mode <mode> ...`) in `text`."""
    return [span for span in code_spans(text)
            if span.startswith("python3 ") and "validate_artifacts.py" in span
            and f"--mode {mode}" in span]


def run_documented(command, cwd):
    """Run a command copied from skill text with the placeholders filled in; return the process."""
    command = command.replace("<runtime-root>", str(REPO)).replace("<work_id>", WORK_ID)
    argv = shlex.split(command)
    if argv[0] == "python3":
        argv[0] = sys.executable
    return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8")


def write(root, relpath, text):
    path = Path(root) / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def resolve(repo, *args):
    proc = subprocess.run([sys.executable, str(RESOLVER), "--repo", str(repo), *args],
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, proc.stdout.splitlines()


def paragraphs(text):
    """Blank-line separated blocks; a list item starts a block of its own."""
    blocks, current = [], []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#") or line.startswith("- "):
            if current:
                blocks.append("\n".join(current))
            current = [line] if line.startswith("- ") else []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def section(text, heading):
    """The lines under a `## ` or `### ` heading that starts with `heading`, up to the next one."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(("## ", "### ")) and line.split(" ", 1)[1].startswith(heading):
            body = []
            for following in lines[index + 1:]:
                if following.startswith(("## ", "### ")):
                    break
                body.append(following)
            return "\n".join(body)
    raise AssertionError(f"no section {heading!r}")


# ------------------------------------------------------------------ SK-1


class TestSk1SpecValidationIsStrict(unittest.TestCase):
    def test_sk1_every_validator_command_in_skill_text_is_strict(self):
        # A command is a span that starts with the interpreter or with the mode flags; a span such as
        # `validate_artifacts.py --mode spec` inside a sentence names the tool, it is not a command.
        offenders = []
        for path in skill_text_files():
            for span in code_spans(read(path)):
                if (span.startswith(("python3 ", "--mode ")) and re.search(r"--mode (?:spec|plan)\b", span)
                        and "--strict" not in span):
                    offenders.append(f"{rel(path)}: {span}")
        self.assertEqual(offenders, [], "a spec/plan validation command without --strict")

    def test_sk1_documented_spec_commands_reject_a_warning_only_spec(self):
        # The pipeline claims a non-zero exit blocks the gate on placeholders and untestable criteria;
        # without --strict both are warnings and the command exits 0.
        commands = []
        for path in skill_text_files():
            commands += [(rel(path), c) for c in validator_commands(read(path), "spec")]
        self.assertTrue(commands, "no spec validation command found in skill text")
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, f"docs/agentic-sdlc/specs/{WORK_ID}.md", SPEC_WITH_PLACEHOLDER)
            for where, command in commands:
                with self.subTest(file=where, command=command):
                    proc = run_documented(command, tmp)
                    self.assertEqual(proc.returncode, 1, proc.stdout)
                    self.assertIn("artifacts_validation=failed", proc.stdout)

    def test_sk1_the_hooks_validate_with_strict(self):
        # The other side of the contract: every artifact evidence item the hooks re-validate is strict.
        req = json.loads(read(FLOW_REQUIREMENTS))
        items = [item for flow in req["flows"].values() for step in flow["steps"]
                 for item in step["evidence"] if item.get("kind") == "artifact"]
        self.assertTrue(items)
        for item in items:
            self.assertIs(item["validate"]["strict"], True, item)


# ------------------------------------------------------------------ SK-2


class TestSk2FocusedSkillsSaveArtifacts(unittest.TestCase):
    SKILLS = ("feature-build", "root-cause-fix")

    def test_sk2_skills_name_paths_frontmatter_and_strict_commands(self):
        for name in self.SKILLS:
            text = read(REPO / "skills" / name / "SKILL.md")
            with self.subTest(skill=name):
                for needle in ("docs/agentic-sdlc/specs/<work_id>.md", "docs/agentic-sdlc/plans/<work_id>.md",
                               "`work_id`", "`status`", "`branch`", "`spec: ../specs/<work_id>.md`"):
                    self.assertTrue(needle in text, f"{name} does not name {needle}")
                self.assertTrue(validator_commands(text, "spec"), "no spec validation command")
                plan = validator_commands(text, "plan")
                self.assertTrue(plan, "no plan validation command")
                self.assertTrue(any("--spec docs/agentic-sdlc/specs/<work_id>.md" in c for c in plan), plan)

    def test_sk2_documented_artifacts_validate_and_resolve(self):
        # The files the skills tell the model to write must pass their own commands and resolve for
        # implementation-control, which blocks on a resolver failure.
        plan_text = ("---\nwork_id: demo\nspec: ../specs/demo.md\nbranch: work\nstatus: reviewed\n---\n"
                     "# Implementation Plan\n\n" + TASKS)
        for name in self.SKILLS:
            text = read(REPO / "skills" / name / "SKILL.md")
            with self.subTest(skill=name), tempfile.TemporaryDirectory() as tmp:
                write(tmp, f"docs/agentic-sdlc/specs/{WORK_ID}.md", SPEC_OK)
                write(tmp, f"docs/agentic-sdlc/plans/{WORK_ID}.md", plan_text)
                commands = validator_commands(text, "spec") + validator_commands(text, "plan")
                self.assertGreaterEqual(len(commands), 2, "both validation commands are documented")
                for command in commands:
                    proc = run_documented(command, tmp)
                    self.assertEqual(proc.returncode, 0, f"{command}\n{proc.stdout}")
                code, lines = resolve(tmp, "--branch", BRANCH)
                self.assertEqual(code, 0, lines)
                self.assertIn("work_package_resolution=passed", lines)
                self.assertIn(f"spec=docs/agentic-sdlc/specs/{WORK_ID}.md", lines)


# ------------------------------------------------------------------ SK-3


class TestSk3ContractsScopeRunnerParagraphs(unittest.TestCase):
    RUNNER_ONLY = ("design.md", "spec option", "opt-in", "light form", "imported spec")

    def test_sk3_runner_only_paragraphs_name_the_runner(self):
        for path in (CONTRACT_02, CONTRACT_03):
            for block in paragraphs(read(path)):
                hits = [term for term in self.RUNNER_ONLY if term in block]
                if hits:
                    with self.subTest(contract=path.name, terms=hits):
                        self.assertIn("`scripts/sdlc.py`", block)

    def test_sk3_prompt_driven_skills_keep_spec_and_fresh_critic(self):
        for path in (CONTRACT_02, CONTRACT_03):
            blocks = [b for b in paragraphs(read(path))
                      if all(s in b for s in ("`agentic-sdlc-pipeline`", "`feature-build`",
                                              "`root-cause-fix`", "`spec-plan-critic`"))]
            with self.subTest(contract=path.name):
                self.assertTrue(blocks, "no rule for the prompt-driven skills")
                self.assertTrue(any("fresh" in b for b in blocks), blocks)

    def test_sk3_the_hooks_still_require_a_spec_in_the_prompt_driven_flows(self):
        req = json.loads(read(FLOW_REQUIREMENTS))
        for flow in ("agentic-sdlc-pipeline", "feature-build", "root-cause-fix"):
            steps = {s["id"]: s for s in req["flows"][flow]["steps"]}
            with self.subTest(flow=flow):
                self.assertEqual(steps["spec"]["stop"], "block")
                self.assertTrue(steps["spec"]["beforeSourceEdit"])


# ------------------------------------------------------------------ SK-4


class TestSk4SecurityLensesAreDirectAgentCalls(unittest.TestCase):
    NEVER = "never a `Workflow` or agent-team"

    def test_sk4_pipeline_hook_counts_only_a_direct_agent_call(self):
        req = json.loads(read(FLOW_REQUIREMENTS))
        steps = {s["id"]: s for s in req["flows"]["agentic-sdlc-pipeline"]["steps"]}
        self.assertEqual(steps["security"]["evidence"],
                         [{"kind": "toolUse", "tool": "Agent", "exactName": "security-reviewer"}])

    def test_sk4_dispatch_strategy_maps_pipeline_lenses_to_agent_calls(self):
        text = read(DISPATCH)
        rows = [line for line in text.splitlines() if line.startswith("|") and "security lenses" in line]
        self.assertTrue(rows, "no quick-mapping row for the security lenses")
        for row in rows:
            mechanism = row.strip("|").split("|")[-1]
            with self.subTest(row=row):
                self.assertNotIn("Dynamic-workflow", mechanism)
                self.assertIn("`Agent(security-reviewer)`", mechanism)
        fan_out = next(b for b in paragraphs(text) if b.startswith("- **Fan-out required:**"))
        self.assertIn("`agentic-sdlc-pipeline`", fan_out)
        self.assertIn("never a dynamic-workflow or agent-team", fan_out)  # dispatch-strategy's mechanism name

    def test_sk4_pipeline_and_playbook_forbid_a_workflow_for_steps_11_and_14(self):
        skill = read(PIPELINE)
        parallel = next(b for b in paragraphs(skill) if b.startswith("**Parallel (⇉):**"))
        self.assertIn(self.NEVER, parallel)
        item = next(line for line in skill.splitlines() if line.startswith("8. `Agent` -> `security-reviewer`"))
        self.assertIn(self.NEVER, item)
        step14 = section(read(PLAYBOOK), "14. Security analysis #2")
        self.assertIn(self.NEVER, step14)


# ------------------------------------------------------------------ SK-6


GIT_ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_TERMINAL_PROMPT="0")


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull, *args],
                          cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", env=GIT_ENV,
                          check=True)


class TestSk6SecretScanScansSomething(unittest.TestCase):
    def test_sk6_playbook_does_not_call_whitespace_check_a_secret_scan(self):
        text = read(PLAYBOOK)
        self.assertIsNone(re.search(r"(?i)secret[- ]scan[^.\n]{0,40}`git diff --check`", text))
        step15 = section(text, "15. Lint / typecheck / build / secret-scan")
        self.assertIn("`git ls-files --others --exclude-standard`", step15)
        marker_scans = [s for s in code_spans(step15) if " -G " in s]
        self.assertTrue(marker_scans, "Step 15 has no marker scan")
        for scan in marker_scans:
            self.assertNotIn("--cached", scan, "an index-only scan misses unstaged work")

    def scan_block(self):
        body = section(read(GIT_SAFETY), "Secret scan")
        block = re.search(r"```bash\n(.*?)```", body, re.DOTALL)
        self.assertIsNotNone(block, "no bash block in the secret scan section")
        return [line.strip() for line in block.group(1).splitlines() if line.strip()]

    def test_sk6_git_safety_check_scans_index_worktree_and_untracked(self):
        commands = self.scan_block()
        with tempfile.TemporaryDirectory() as tmp:
            git(tmp, "init", "-q")
            write(tmp, "base.txt", "first line\n")
            write(tmp, "clean.txt", "first line\n")
            git(tmp, "add", "base.txt", "clean.txt")
            git(tmp, "commit", "-q", "-m", "base")
            marker = "auth_" + "token: placeholder-value\n"
            write(tmp, "staged.txt", marker)
            git(tmp, "add", "staged.txt")
            write(tmp, "base.txt", "first line\n" + marker)      # unstaged edit with a marker
            write(tmp, "clean.txt", "first line\nsecond line\n")  # unstaged edit without one
            write(tmp, "untracked.txt", marker)
            listed, marked = set(), set()
            for command in commands:
                out = subprocess.run(shlex.split(command), cwd=tmp, capture_output=True, text=True,
                                     encoding="utf-8", env=GIT_ENV)
                self.assertEqual(out.returncode, 0, f"{command}: {out.stderr}")
                names = set(out.stdout.split())
                listed |= names
                if " -G " in command:
                    marked |= names
        self.assertLessEqual({"staged.txt", "base.txt", "untracked.txt"}, listed)
        self.assertLessEqual({"staged.txt", "base.txt"}, marked)
        self.assertNotIn("clean.txt", marked)

    def test_sk6_new_scan_commands_are_preapproved_exactly(self):
        text = read(GIT_SAFETY)
        allowed = json.loads(re.search(r"allowed-tools:\s*(\[.*\])", text.split("---", 2)[1]).group(1))
        for command in self.scan_block():
            if " -G " in command:
                continue
            for rule in (f"Bash({command})", f"PowerShell({command})"):
                with self.subTest(rule=rule):
                    self.assertIn(rule, allowed)


# ------------------------------------------------------------------ SK-7


class TestSk7RouterEscalatesHighRiskFirst(unittest.TestCase):
    FOCUSED = ("`feature-build`", "`root-cause-fix`", "`safe-refactor`")

    def test_sk7_high_risk_override_comes_before_the_focused_routes(self):
        lines = read(ROUTER).split("---", 2)[2].splitlines()
        routes = [i for i, line in enumerate(lines)
                  if line.startswith("- ") and any(f"-> {s}" in line for s in self.FOCUSED)]
        self.assertTrue(routes)
        overrides = [i for i, line in enumerate(lines)
                     if line.startswith("- ") and "-> `agentic-sdlc-pipeline`" in line
                     and all(surface in line for surface in HIGH_RISK_SURFACES)]
        self.assertTrue(overrides, "no high-risk override bullet naming every surface")
        self.assertLess(overrides[0], routes[0], "the override must be read before the focused routes")
        for i in routes:
            with self.subTest(route=lines[i]):
                self.assertIn("`agentic-sdlc-pipeline`", lines[i], "a focused route without the override")


# ------------------------------------------------------------------ SK-8


class TestSk8MindSparkAfterKickoff(unittest.TestCase):
    def test_sk8_pipeline_runs_mind_spark_after_kickoff_and_branch_checkpoint(self):
        bullet = next(line for line in read(PIPELINE).splitlines() if line.startswith("- **`mind-spark`**"))
        self.assertNotIn("before kickoff", bullet)
        for needle in ("after", "`dispatch-strategy`", "branch checkpoint", "Step 4"):
            self.assertIn(needle, bullet)

    def test_sk8_mind_spark_reference_agrees(self):
        block = next(b for b in paragraphs(section(read(MIND_SPARK_REF), "When to use"))
                     if "agentic-sdlc-pipeline" in b)
        block = " ".join(block.split())  # the reference wraps its prose
        self.assertNotIn("runs first", block)
        self.assertIn("branch checkpoint", block)


# ------------------------------------------------------------------ SK-9


class TestSk9SpecLessPlanCommand(unittest.TestCase):
    def test_sk9_plan_authoring_documents_both_commands(self):
        text = read(PLAN_AUTHORING)
        commands = validator_commands(text, "plan")
        self.assertTrue([c for c in commands if "--spec " in c], "the with-spec command stays")
        self.assertTrue([c for c in commands if "--spec " not in c], "no spec-less command")
        for needle in ("`spec: none`", "`flow: plan`", "## Acceptance Criteria"):
            self.assertIn(needle, text)

    def test_sk9_each_command_passes_its_own_plan(self):
        commands = validator_commands(read(PLAN_AUTHORING), "plan")
        with_spec = [c for c in commands if "--spec " in c]
        specless = [c for c in commands if "--spec " not in c]
        self.assertTrue(with_spec and specless)
        plan_header = "---\nwork_id: demo\n{spec}branch: work\nstatus: reviewed\n---\n# Implementation Plan\n\n"
        with tempfile.TemporaryDirectory() as tmp:
            # A plan saved without a spec file: `spec: none`, `flow: plan`, its own criteria first.
            write(tmp, f"docs/agentic-sdlc/plans/{WORK_ID}.md",
                  plan_header.format(spec="spec: none\nflow: plan\n") + OWN_CRITERIA + "\n" + TASKS)
            for command in specless:
                proc = run_documented(command, tmp)
                self.assertEqual(proc.returncode, 0, f"{command}\n{proc.stdout}")
            for command in with_spec:  # the with-spec command cannot validate this plan
                self.assertEqual(run_documented(command, tmp).returncode, 1)
            code, lines = resolve(tmp, "--branch", BRANCH)
            self.assertEqual(code, 0, lines)
            self.assertIn("spec=none", lines)
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, f"docs/agentic-sdlc/specs/{WORK_ID}.md", SPEC_OK)
            write(tmp, f"docs/agentic-sdlc/plans/{WORK_ID}.md",
                  plan_header.format(spec="spec: ../specs/demo.md\n") + TASKS)
            for command in with_spec:
                proc = run_documented(command, tmp)
                self.assertEqual(proc.returncode, 0, f"{command}\n{proc.stdout}")


if __name__ == "__main__":
    unittest.main()
