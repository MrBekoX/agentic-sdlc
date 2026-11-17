"""The agent roles of the spec/plan loop and the draft scribe (middleware-chain plan Task 10).

The loop definition `flows/loops/spec-plan.json` names the author modes and the loop modes, the
critic schema `flows/schemas/critic.schema.json` names the critic's output, the validator
(`scripts/validate_artifacts.py`) names the bugfix-plan sections, and `sdlc_runner/loop.py` names
the loop's subcommands and its blocking severities and kinds. These tests read the role files
against those sources, so a mode, a schema field or a section the roles do not name fails here
instead of in a live run:
- `agents/spec-plan-author.md` has one section per author mode, and its last message is the draft.
- `agents/spec-plan-critic.md` audits each loop mode and the fit between spec and plan, repeats
  the validator's blocking findings, and its last message is only the JSON the schema describes.
- `agents/draft-scribe.md` writes files and runs the loop's runner commands for the native
  engines, with exactly Read, Write, Bash and PowerShell; the author and the critic stay read-only.
- `agents/implementation-auditor.md` grades a spec-less plan of a bugfix, feature or plan run against
  the plan's own criteria, and only a bugfix plan against a `## Bug` section.
- Contracts 02, 03 and 07 allow the joint loop, its one review gate and the spec-less bugfix plan.
"""
import argparse
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from sdlc_runner import frontmatter, loop  # noqa: E402

LOOP_DEF = REPO / "flows" / "loops" / "spec-plan.json"
CRITIC_SCHEMA = REPO / "flows" / "schemas" / "critic.schema.json"
AUTHOR = REPO / "agents" / "spec-plan-author.md"
CRITIC = REPO / "agents" / "spec-plan-critic.md"
SCRIBE = REPO / "agents" / "draft-scribe.md"
AUDITOR = REPO / "agents" / "implementation-auditor.md"
CONTRACTS = REPO / "contracts" / "skills"
READ_ONLY_TOOLS = {"Glob", "Grep", "Read", "WebFetch", "WebSearch"}
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
FENCE = re.compile(r"^ {0,3}(```|~~~)")


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_artifacts_roles", REPO / "scripts" / "validate_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()


def read(path):
    return path.read_bytes().decode("utf-8")


def body(path):
    return frontmatter.split(read(path))[1]


def tools(path):
    meta = frontmatter.split(read(path))[0]
    return {tool.strip() for tool in str(meta.get("tools", "")).split(",") if tool.strip()}


def headings(text):
    """(line index, level, text) of each heading outside code fences."""
    found, fenced = [], False
    for at, line in enumerate(text.splitlines()):
        if FENCE.match(line):
            fenced = not fenced
            continue
        match = None if fenced else HEADING.match(line)
        if match:
            found.append((at, len(match.group(1)), match.group(2)))
    return found


def section(text, title, level):
    """The lines under the one heading `title` at `level`, up to the next heading of the same or a
    higher level. A missing or repeated heading fails, so a renamed section never passes."""
    lines = text.splitlines()
    marks = headings(text)
    hits = [at for at, lvl, name in marks if lvl == level and name == title]
    if len(hits) != 1:
        raise AssertionError("expected one level-%d heading %r, found %d" % (level, title, len(hits)))
    end = next((at for at, lvl, _name in marks if at > hits[0] and lvl <= level), len(lines))
    return "\n".join(lines[hits[0] + 1:end])


def subheadings(text, level):
    return [name for _at, lvl, name in headings(text) if lvl == level]


def heading_starting(text, prefix, level):
    names = [name for name in subheadings(text, level) if name.startswith(prefix)]
    if len(names) != 1:
        raise AssertionError("expected one level-%d heading starting %r, found %r" % (level, prefix, names))
    return names[0]


def subsection(text, prefix, level):
    return section(text, heading_starting(text, prefix, level), level)


def field_line(text, field):
    lines = [line for line in text.splitlines() if re.match(r"^\s*- `%s`:" % re.escape(field), line)]
    if len(lines) != 1:
        raise AssertionError("expected one line for field %r, found %d" % (field, len(lines)))
    return lines[0]


def loop_definition():
    return json.loads(read(LOOP_DEF))


def author_modes(definition):
    return {item["author_mode"] for mode in definition["modes"].values()
            for item in mode["first_round"] + mode["revise"]}


def loop_subcommands():
    """The subcommand names `sdlc_runner.loop.register_cli` registers on a fresh parser."""
    subparsers = argparse.ArgumentParser(prog="sdlc").add_subparsers()
    loop.register_cli(subparsers)
    return list(subparsers.choices)


class TestAuthorRole(unittest.TestCase):
    def test_author_names_each_mode(self):
        modes = author_modes(loop_definition())
        self.assertEqual(modes, {"spec", "plan", "bugfix-plan", "revise"})
        text = body(AUTHOR)
        modes_text = section(text, "Modes", 2)
        named = set()
        for heading in subheadings(modes_text, 3):
            match = re.fullmatch(r"`([a-z+-]+)` mode\b.*", heading)
            self.assertIsNotNone(match, "a Modes sub-heading names no author mode: %r" % heading)
            named.add(match.group(1))
        self.assertEqual(named, modes, "the author's mode sections must be exactly the loop's author modes")
        intro = modes_text.split("\n### ", 1)[0]
        self.assertIn("gate feedback", intro, "every author mode must address the gate feedback of a reopened visit")
        plan = subsection(text, "`plan` mode", 3)
        for phrase in ("Derive every task from the spec", "not yet approved", "`## Task N`",
                       "acceptance-criterion ids"):
            self.assertIn(phrase, plan)
        revise = subsection(text, "`revise` mode", 3)
        for source in ("previous draft", "`critic.r<N>.json`", "`validator.r<N>.json`", "gate feedback"):
            self.assertIn(source, revise, "revise mode does not name its input %r" % source)
        self.assertIn("`target`", revise, "revise mode must fix the issues whose target is the author's artifact")

    def test_author_decision_points_match_what_the_runner_reads(self):
        output = section(body(AUTHOR), "Output", 2)
        decisions = next((line for line in output.splitlines() if line.startswith("- Decision points")), None)
        self.assertIsNotNone(decisions, "the author's Output names no decision-point rule")
        self.assertIn("`{%s}`" % ", ".join(loop.POINT_FIELDS), decisions)
        # A task block runs to the end of the plan, so AC ids in a trailing section would count as covered.
        self.assertIn("before the first `## Task N`", decisions)
        # The runner reads only the final round's decisions file.
        self.assertIn("every round", decisions)


class TestCriticRole(unittest.TestCase):
    def test_critic_checks_fit_and_names_targets(self):
        text = body(CRITIC)
        audit = section(text, "Audit", 2)
        audit_headings = subheadings(audit, 3)
        for mode in loop_definition()["modes"]:
            with self.subTest(loop_mode=mode):
                self.assertTrue(any("`%s`" % mode in heading for heading in audit_headings),
                                "no audit section names loop mode %s: %r" % (mode, audit_headings))
        for heading in audit_headings:
            with self.subTest(audit_section=heading):
                self.assertRegex(section(audit, heading, 3), r"(?m)^- \S", "an audit section has no check")
        fit = subsection(audit, "Fit between spec and plan", 3)
        for phrase in ("both artifacts", "names its id", "invents", "files and layers", "contradict", "`target`"):
            self.assertIn(phrase, fit, "the fit check does not cover %r" % phrase)

    def test_critic_reads_the_brief_and_repeats_blocking_validator_findings(self):
        inputs = section(body(CRITIC), "Inputs", 2)
        for phrase in ("brief", "approved spec", "gate feedback", "validator findings are facts",
                       "`errors`", "`strict_warnings`"):
            self.assertIn(phrase, inputs, "the critic's inputs do not name %r" % phrase)
        # tests/test_sdlc_loop.py pins that the runner's critic card lists the brief first.

    def test_critic_output_matches_schema_keys(self):
        schema = json.loads(read(CRITIC_SCHEMA))
        issue = schema["properties"]["issues"]["items"]
        output = section(body(CRITIC), "Output", 2)
        top = set(re.findall(r"(?m)^- `(\w+)`:", output))
        self.assertEqual(top, set(schema["properties"]), "top-level critic fields differ from the schema")
        listed = re.search(r"`issues`: a list of `\{([^}]*)\}`", output)
        self.assertIsNotNone(listed, "the critic names no issue field list")
        fields = [field.strip() for field in listed.group(1).split(",")]
        self.assertEqual(len(fields), len(set(fields)))
        self.assertEqual(set(fields), set(issue["required"]), "issue fields differ from critic.schema.json")
        self.assertEqual(set(issue["required"]), set(issue["properties"]))
        nested = set(re.findall(r"(?m)^\s+- `(\w+)`:", output))
        self.assertEqual(nested, set(issue["required"]), "each issue field gets its own line")
        verdict = field_line(output, "verdict")
        for value in schema["properties"]["verdict"]["enum"]:
            self.assertIn("`%s`" % value, verdict.split(".")[0], "the verdict line must open with its values")
        for key in ("target", "severity", "kind"):
            line = field_line(output, key)
            for value in issue["properties"][key]["enum"]:
                with self.subTest(field=key, value=value):
                    self.assertIn("`%s`" % value, line, "the %s line must name the value %s" % (key, value))
        for value in loop.BLOCKING_SEVERITIES + loop.BLOCKING_KINDS:
            with self.subTest(blocking=value):
                self.assertIn("`%s`" % value, verdict, "the verdict rule must name every blocking severity and kind")
        self.assertEqual(schema["properties"]["coverageCheck"]["type"], "string")
        self.assertIn("one string", field_line(output, "coverageCheck"))

    def test_critic_targets_only_the_artifacts_the_mode_drafts(self):
        output = section(body(CRITIC), "Output", 2)
        target = field_line(output, "target")
        plan_only = [name for name, mode in loop_definition()["modes"].items() if "spec" not in mode["artifacts"]]
        self.assertEqual(sorted(plan_only), ["bugfix-plan", "plan"])
        for name in plan_only:
            with self.subTest(loop_mode=name):
                self.assertIn("`%s`" % name, target, "a spec-target note is dropped in a mode without a spec")


class TestBugfixPlan(unittest.TestCase):
    def test_bugfix_plan_mode_names_bug_and_ac_sections(self):
        definition = loop_definition()
        self.assertEqual([item["author_mode"] for item in definition["modes"]["bugfix-plan"]["first_round"]],
                         ["bugfix-plan"])
        mode = subsection(body(AUTHOR), "`bugfix-plan` mode", 3)
        for phrase in ("`## Bug`", "`## Acceptance Criteria`", "before the first task", "expected", "actual",
                       "reproduction"):
            self.assertIn(phrase, mode, "bugfix-plan mode does not name %r" % phrase)
        # The headings the role names pass the validator's own bugfix-plan checks.
        named = re.findall(r"`## ([^`]+)`", mode)
        plan = "".join("## %s\n\n%s\n\n" % (heading, "Given a saved report, when it is exported, then AC1 holds; "
                                                     "expected and actual differ in the reproduction run.")
                       for heading in named if not heading.startswith("Task"))
        plan += "## Task 1: Fix the export (AC1)\n\nModify `src/export.py`. RED test first: `test_export`. " \
                "Verify: `pytest -q`.\n"
        report = VALIDATOR.check_plan(plan, None, bugfix=True)
        self.assertEqual([e for e in report["errors"] if e.startswith(("missing_section:", "bugfix_"))], [],
                         report)
        bugfix = subsection(section(body(CRITIC), "Audit", 2), "Bugfix plan", 3)
        self.assertIn("`bugfix-plan`", heading_starting(section(body(CRITIC), "Audit", 2), "Bugfix plan", 3))
        self.assertIn("`## Acceptance Criteria`", bugfix)
        self.assertIn("invents WHAT", bugfix, "the critic must say the plan-invents-WHAT blocker reads the plan's "
                                              "own criteria in bugfix-plan mode")

    def specless_path(self, path=AUDITOR):
        bullet = next((line for line in read(path).splitlines() if line.startswith("- **Spec-less path")), None)
        self.assertIsNotNone(bullet, "the auditor has no spec-less path")
        return bullet

    def test_auditor_reads_bugfix_criteria_from_the_plan(self):
        bullet = self.specless_path()
        for phrase in ("`spec=none`", "`spec: none`", "`flow: bugfix`", "`## Bug`", "`## Acceptance Criteria`",
                       "`N/A (criteria in the plan)`", "against the plan's own criteria",
                       '"Spec produced?"', "reproduces the bug", "is FAIL"):
            self.assertIn(phrase, bullet)

    def test_auditor_role_accepts_specless_feature_plans(self):
        # Hybrid design §5: a feature or plan run without a spec carries its criteria in the plan; the fresh
        # auditor grades it the bugfix way, and only a bugfix plan states a bug.
        bullet = self.specless_path()
        for phrase in ("`flow:` `bugfix`, `feature` or `plan`", "only a bugfix plan has one",
                       "`spec: none` with any other flow is not this path"):
            self.assertIn(phrase, bullet)
        light = next(line for line in read(AUDITOR).splitlines() if line.startswith("- **Light-flow path"))
        self.assertIn("except the spec-less path below", light)
        self.assertNotIn("Bugfix path", read(AUDITOR))
        # The Cursor mirror carries the same role text.
        self.assertEqual(self.specless_path(REPO / "cursor" / "agents" / "implementation-auditor.md"), bullet)
        # The step file that gathers the audit's rows names the same path and Spec row.
        audit = read(REPO / "skills" / "implementation-control" / "steps" / "audit.md")
        self.assertIn("`N/A (criteria in the plan)`", audit)
        self.assertNotIn("N/A (bugfix:", audit)
        for row in ("intent:", "spec:", "spec-check:", "spec-review:", "plan:", "plan-review:"):
            self.assertIn(row, audit)


class TestScribeAndReadOnlyRoles(unittest.TestCase):
    def test_scribe_tools_exclude_skill_and_agent(self):
        self.assertEqual(tools(SCRIBE), {"Read", "Write", "Bash", "PowerShell"})
        self.assertEqual(frontmatter.split(read(SCRIBE))[0].get("name"), "draft-scribe")
        text = body(SCRIBE)
        for phrase in ("byte for byte", "inside the package", "<runtime-root>/scripts/sdlc.py", "`-B`",
                       "Nothing else"):
            self.assertIn(phrase, text, "the scribe's job does not say %r" % phrase)
        commands = section(text, "Command calls", 2)
        allowed = loop_subcommands()
        self.assertEqual(allowed, ["draft-check", "loop-record", "ingest-draft"])
        for name in allowed:
            self.assertIn("`%s`" % name, commands, "the scribe does not allow the loop subcommand %s" % name)
        named = set(re.findall(r"`([a-z]+(?:-[a-z]+)+)`", commands))
        self.assertEqual(named - set(allowed), set(), "the scribe names a subcommand outside the loop's own")

    def test_loop_roles_stay_read_only(self):
        roles = loop_definition()["roles"]
        self.assertTrue(roles)
        for role in roles.values():
            with self.subTest(agent=role["agent"]):
                path = loop.role_path(REPO, role["agent"])
                self.assertTrue(tools(path), role)
                self.assertLessEqual(tools(path), READ_ONLY_TOOLS)


class TestLastMessage(unittest.TestCase):
    def test_roles_say_last_message_is_result(self):
        author = section(body(AUTHOR), "Output", 2)
        self.assertIn("Your last message is the complete result", author)
        critic = section(body(CRITIC), "Output", 2)
        self.assertIn("Your last message is only the JSON", critic)
        for name, text in (("author", author), ("critic", critic)):
            with self.subTest(role=name):
                self.assertIn("structured-output tool", text)
                # Codex reads the result from the card's write path, so a role that can write files writes it.
                self.assertIn("When your card names a write path and you have a file-writing tool", text)
        for path in (AUTHOR, CRITIC):
            self.assertNotIn("StructuredOutput", read(path))
        self.assertIn("Your last message reports", body(SCRIBE))

    def test_unresolved_plugin_root_stays_out_of_the_result(self):
        for path, place in ((AUTHOR, "nothing about it"), (CRITIC, "`coverageCheck`")):
            with self.subTest(role=path.stem):
                line = next((line for line in read(path).splitlines() if "plugin root unresolved" in line), "")
                self.assertIn(place, line, "%s must say where an unresolved root is noted" % path.stem)


class TestContracts(unittest.TestCase):
    def test_contracts_allow_joint_gate_and_bugfix_plan(self):
        spec = read(CONTRACTS / "02-spec-driven-development.md")
        exception = section(spec, "Bugfix exception", 2)
        for phrase in ("`flow: bugfix`", "`spec: none`", "`## Bug`", "`## Acceptance Criteria`"):
            self.assertIn(phrase, exception)
        self.assertIn("except a bugfix plan", section(spec, "Forbidden", 2))
        plan = read(CONTRACTS / "03-plan-mode.md")
        applied = section(plan, "When applied", 2)
        for phrase in ("joint loop", "one review gate", "gated form", "A bugfix plan has no spec"):
            self.assertIn(phrase, applied)
        self.assertNotIn("After an approved spec", applied)
        refactor = read(CONTRACTS / "07-refactoring.md")
        self.assertIsNone(re.search(r"(?i)\bsteps? \d+", refactor), "contract 07 names a pipeline step number")


if __name__ == "__main__":
    unittest.main()
