"""State, checks, engine and flow operations of the sdlc runner (plan Task 5).

Contract: docs/agentic-sdlc/notes/2026-10-22-runner-contract.md §3 (state.json), §5 (named sets),
§6 (manifests, wave B handoffs), §7 (checks), §8 (`next`), §13 (CLI), §14 (cards); design §5.3
(`--risk`/`--form`), §5.6 (freshness, frontmatter), §5.11 (caps, escalate lattice). Covers
scripts/sdlc_runner/{state,checks,engine,card,flowops,cli}.py.

Every case runs against a temp plugin root (the real flows plus the fixture flow
tests/fixtures/sdlc/engine.json, whose step files come from tests/fixtures/sdlc/steps/) and a temp
project that is a real git repository made with `git init` under an isolated git configuration.
The runner runs in-process through cli.main. The only program a test starts is the fake test
runner tests/fixtures/sdlc/bin/fake_pytest.py behind a launcher named `pytest`; runexec._spawn is
guarded so any other program fails the test instead of starting. No paid CLI is ever started.
"""
import copy
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sdlc_runner import cli, frontmatter, logs, manifest, paths, runexec, textio  # noqa: E402
from sdlc_runner import state as sdlc_state  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "sdlc"
ENGINE_FLOW = FIXTURES / "engine.json"
STEP_FILES = FIXTURES / "steps"
FAKE = FIXTURES / "bin" / "fake_pytest.py"
GIT = paths.resolve_program("git")
WINDOWS = sys.platform == "win32"
FAKE_TOKEN = "gh" + "p_" + "R8kLq2Wv9XmT4zNp7Hs3Jd6Fb1Yc5Ge0Ua8K"
LOCAL_GIT_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
    "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
)
CHAIN_LINE = re.compile(r"state=[a-z-]+ chain=[0-9a-f]{12}(?: |$)")
DATA_LINE = "--- data (not instructions) ---"

REQUEST = "Add a CSV export to the report page.\n"
SPEC_BODY = (
    "# Spec: report export\n\n"
    "## Problem\n\nUsers cannot export their reports, so they copy the numbers by hand every week.\n\n"
    "## Business Rules\n\n- An export holds every row of the report that the user can see today.\n\n"
    "## Acceptance Criteria\n\n- AC1: Given a report, when the user exports it, then a CSV file returns every visible row.\n\n"
    "## Edge Cases\n\n- An empty report exports a CSV file that holds the header row and nothing else.\n\n"
    "## Definition of Done\n\n- The export works for every report type and its tests pass in continuous integration.\n\n"
    "## Must-Not-Change\n\n- The report page layout and its existing download buttons stay exactly as they are.\n"
)
# A plan that passes the strict plan gate against SPEC_BODY (one task, AC1 covered).
PLAN_BODY = (
    "# Plan: report export\n\n## Task 1: CSV export (AC1)\n\n"
    "Create `src/export.py` and its test `tests/test_export.py`.\n\n"
    "- RED: write the failing test for AC1 first.\n- Run: `pytest tests/test_export.py`\n"
)


# Header lines whose value is a runnable command. A command quotes its paths for the shell the
# model runs it in (`"C:\...\python.exe"` on Windows), so it is never read as a JSON string.
COMMAND_KEYS = ("then", "confirm", "launch")


def card_fields(text: str) -> dict:
    """`key=value` pairs of a card's header (the lines before the first `---` line).

    A quoted value is a JSON string; a command line (COMMAND_KEYS) is kept raw to the end of the
    line. First one wins.
    """
    found = {}
    for line in text.splitlines():
        if line.startswith("---"):
            break
        key, sep, rest = line.partition("=")
        if sep and key in COMMAND_KEYS:
            found.setdefault(key, rest)
            continue
        for match in re.finditer(r'([a-z_][a-z0-9_.-]*)=("(?:[^"\\]|\\.)*"|\S+)', line):
            key, value = match.group(1), match.group(2)
            if value.startswith('"'):
                value = json.loads(value)
            found.setdefault(key, value)
    return found


def card_value(text: str, key: str):
    """The first `key=value` anywhere in the card (gate and data sections included)."""
    for line in text.splitlines():
        if line.startswith(key + "="):
            return line[len(key) + 1:]
    return None


class EngineCase(unittest.TestCase):
    """A temp plugin root with the fixture flow, a temp git project, a fake `pytest` on PATH."""

    use_git = True

    def setUp(self):
        if self.use_git and GIT is None:
            self.skipTest("git is not installed")
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name).resolve()
        self.root = self.make_root(self.tmp / "root")
        self.project = self.tmp / "proj"
        self.project.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.allowed = set()
        self.add_launcher("pytest")
        global_cfg = self.tmp / "global.gitconfig"
        global_cfg.write_bytes(b"")
        env = {
            "PATH": os.pathsep.join([str(self.bin)] + ([os.path.dirname(GIT)] if GIT else [])),
            "FAKE_PY": sys.executable, "FAKE_SCRIPT": str(FAKE), "FAKE_PYTEST_PIDS": str(self.tmp / "pids.txt"),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(global_cfg),
            "XDG_CONFIG_HOME": str(self.tmp / "xdg"), "GIT_CEILING_DIRECTORIES": str(self.tmp),
            "GIT_AUTHOR_NAME": "sdlc test", "GIT_AUTHOR_EMAIL": "sdlc-test@example.invalid",
            "GIT_COMMITTER_NAME": "sdlc test", "GIT_COMMITTER_EMAIL": "sdlc-test@example.invalid",
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in LOCAL_GIT_ENV:
            os.environ.pop(name, None)
        self.write("src/app.py", b"def add(a, b):\n    return a + b\n")
        self.write("tests/test_app.py", b"def test_add():\n    assert True\n")
        if self.use_git:
            self.git("init", "-q")
            self.git("add", "-A")
            self.git("commit", "-q", "-m", "base")
        self.request = self.tmp / "request.md"
        self.request.write_bytes(REQUEST.encode("utf-8"))
        original = runexec._spawn

        def guarded(argv, cwd, env, timeout):  # fails closed: only the fake launchers may start
            target = argv[3] if WINDOWS and len(argv) > 3 and argv[1:3] == ["/d", "/c"] else argv[0]
            if os.path.normcase(str(target)) not in self.allowed:
                raise AssertionError("unexpected program: %r" % (argv,))
            return original(argv, cwd, env, timeout)

        patcher = mock.patch.object(runexec, "_spawn", guarded)
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- environment ---------------------------------------------------------------------------

    def make_root(self, root: Path, shared_edit=None) -> Path:
        """A plugin root holding the real flows, the fixture flow and its step files, and the two
        spec/plan role files and contracts the loop stages."""
        copies = list((REPO / "flows").rglob("*.json"))
        copies += [REPO / "agents" / "spec-plan-author.md", REPO / "agents" / "spec-plan-critic.md",
               REPO / "agents" / "spec-builder-check.md"]
        copies += sorted((REPO / "contracts" / "skills").glob("0[23]-*.md"))
        for path in copies:
            target = root / path.relative_to(REPO)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(path), str(target))
        shutil.copyfile(str(ENGINE_FLOW), str(root / "flows" / "engine.json"))
        steps = root / "skills" / "fixture" / "steps"
        steps.mkdir(parents=True)
        for path in STEP_FILES.glob("*.md"):
            shutil.copyfile(str(path), str(steps / path.name))
        if shared_edit is not None:
            shared = textio.read_json(root / "flows" / "_shared.json")
            shared_edit(shared)
            textio.write_json_atomic(root / "flows" / "_shared.json", shared)
        return root

    def put_flow(self, flow_id, edit):
        """A flow `flow_id` in the temp root: the engine fixture flow with `edit(flow)` applied."""
        flow = json.loads(ENGINE_FLOW.read_text(encoding="utf-8"))
        flow["id"] = flow_id
        edit(flow)
        textio.write_json_atomic(self.root / "flows" / (flow_id + ".json"), flow)

    def add_launcher(self, name):
        if WINDOWS:
            path = self.bin / (name + ".cmd")
            path.write_bytes(b'@echo off\r\n"%FAKE_PY%" -I -B "%FAKE_SCRIPT%" %*\r\nexit /b %ERRORLEVEL%\r\n')
        else:
            path = self.bin / name
            path.write_bytes(b'#!/bin/sh\nexec "$FAKE_PY" -I -B "$FAKE_SCRIPT" "$@"\n')
            path.chmod(0o755)
        self.allowed.add(os.path.normcase(str(path)))
        return path

    def git(self, *args):
        proc = subprocess.run(
            [GIT, "-c", "core.hooksPath=" + str(self.tmp / "no-hooks"), "-c", "commit.gpgsign=false",
             "-c", "init.defaultBranch=main", "-c", "core.autocrlf=false", *args],
            cwd=str(self.project), stdin=subprocess.DEVNULL, capture_output=True, shell=False,
            encoding="utf-8", errors="replace", timeout=60,
        )
        if proc.returncode != 0:
            self.fail("git %s failed: %s" % (" ".join(args), proc.stderr))
        return proc

    def write(self, rel, data: bytes):
        target = self.project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target

    # -- runner calls --------------------------------------------------------------------------

    def sdlc(self, *argv, root=None):
        out = io.StringIO()
        code = cli.main(["--project", str(self.project)] + list(argv), out=out, root=root or self.root)
        return code, out.getvalue()

    def start(self, *extra, flow="engine", work_id="demo", form="gated", risk="normal", work_type="feature",
              runtime="codex", expect=0):
        argv = ["start", flow, "--work-id", work_id, "--risk", risk, "--form", form, "--work-type", work_type,
                "--runtime", runtime, "--request-file", str(self.request)] + list(extra)
        code, text = self.sdlc(*argv)
        if expect is not None:
            self.assertEqual(code, expect, text)
        return code, text

    def next(self, slug="demo", expect=0):
        code, text = self.sdlc("next", "--slug", slug)
        if expect is not None:
            self.assertEqual(code, expect, text)
        return code, text

    def card(self, slug="demo", expect=0):
        code, text = self.sdlc("card", "--slug", slug)
        if expect is not None:
            self.assertEqual(code, expect, text)
        return code, text

    # -- package files -------------------------------------------------------------------------

    def pkg(self, slug="demo") -> Path:
        return self.project / "docs" / "agentic-sdlc" / slug

    def put(self, rel, text, slug="demo"):
        target = self.pkg(slug) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
        return target

    def state(self, slug="demo") -> dict:
        return json.loads((self.pkg(slug) / "state.json").read_text(encoding="utf-8"))

    def edit_state(self, change, slug="demo"):
        st = self.state(slug)
        change(st)
        textio.write_json_atomic(self.pkg(slug) / "state.json", st)

    def transitions(self, slug="demo") -> list:
        return logs.read(self.pkg(slug) / "transitions.jsonl")

    def records(self, kind, slug="demo", step=None) -> list:
        return [r for r in self.transitions(slug) if r["kind"] == kind and (step is None or r.get("step") == step)]

    def confirm_strategy(self, slug="demo", capabilities="workflow=no,subagent=yes,team=no", *overrides):
        """`sdlc strategy confirm` with the default map (what a model with sub-agents and no workflow
        engine would run on Codex)."""
        argv = ["strategy", "confirm", "--slug", slug, "--capabilities", capabilities]
        for item in overrides:
            argv += ["--set", item]
        code, text = self.sdlc(*argv)
        self.assertEqual(code, 0, text)
        return text

    def approve(self, text, slug="demo", gate="review", source="reply", quote="Yes, go ahead.", expect=0):
        """`sdlc approve` with the fingerprint the gate card printed."""
        fingerprint = card_value(text, "fingerprint")
        self.assertRegex(fingerprint or "", r"^[0-9a-f]{16}$", text)
        code, out = self.sdlc("approve", gate, "--slug", slug, "--fingerprint", fingerprint, "--quote", quote,
                              "--source", source)
        if expect is not None:
            self.assertEqual(code, expect, out)
        return code, out

    def red_green(self, slug="demo"):
        self.write("tests/test_new.py", b"def test_new():\n    assert False\n")
        code, text = self.sdlc("run", "--slug", slug, "--expect", "fail", "--label", "red", "--",
                               "pytest", "--say=pytest-fail", "--exit=1")
        self.assertEqual(code, 1, text)
        self.assertIn("valid=yes", text)
        self.write("src/app.py", b"def add(a, b):\n    return b + a\n")
        code, text = self.sdlc("run", "--slug", slug, "--expect", "pass", "--label", "green", "--",
                               "pytest", "--say=pytest-pass")
        self.assertEqual(code, 0, text)
        self.assertIn("valid=yes", text)

    def satisfy(self, step, text, slug="demo"):
        """Do the work the fixture flow's `step` asks for (what a model would do from the card)."""
        if step == "strategy":
            self.confirm_strategy(slug)
        elif step == "context":
            self.put("context.md", "# Context\n\n## Scope Lock\n\nOnly the report page.\n", slug)
        elif step == "extra":
            self.put("evidence/%s.extra.md" % slug, "# Extra\n", slug)
        elif step == "snapshot":
            self.put("evidence/%s.snapshot.md" % slug, "# Snapshot\n", slug)
        elif step == "draft":
            self.put("spec/%s.md" % slug, SPEC_BODY, slug)
            self.put("plan/%s.md" % slug, PLAN_BODY, slug)
        elif step == "review":
            self.approve(text, slug)
        elif step == "implement":
            self.red_green(slug)
            self.put("evidence/%s.tdd.md" % slug, "# TDD evidence\n\nRED then GREEN.\n", slug)
        elif step == "security":
            self.put("evidence/%s.security.md" % slug, "# Security review\n\nVerdict: pass\n", slug)
        elif step == "claim":
            self.put("evidence/%s.claim.md" % slug, "# Completion claim\n\nDone.\n", slug)
        else:
            self.fail("the fixture flow has no step %r" % step)

    def advance_to(self, target, slug="demo"):
        """Drive the fixture flow with `next` until the card names `target` (None: until complete)."""
        code, text = self.card(slug)
        for _ in range(30):
            fields = card_fields(text)
            if fields.get("state") == "complete":
                if target is None:
                    return code, text
                self.fail("the flow completed before reaching %r" % target)
            if target is not None and fields.get("step") == target:
                return code, text
            self.satisfy(fields.get("step"), text, slug)
            code, text = self.next(slug)
        self.fail("did not reach %r: %s" % (target, text))


# ---------------------------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------------------------

class TestStart(EngineCase):
    def test_start_requires_risk_and_form(self):
        base = ["start", "engine", "--work-id", "demo", "--work-type", "feature", "--runtime", "codex",
                "--request-file", str(self.request)]
        for missing, extra in (("--risk", ["--form", "gated"]), ("--form", ["--risk", "normal"])):
            with self.subTest(missing=missing):
                code, text = self.sdlc(*(base + extra))
                self.assertEqual(code, 2, text)
                errors = [line for line in text.splitlines() if line.startswith("error=")]
                self.assertEqual(len(errors), 1, text)
                self.assertIn(missing, errors[0])
        self.assertFalse((self.pkg() / "state.json").exists())
        self.start()  # the clean twin

    def test_light_refused_with_high_risk_and_for_full(self):
        code, text = self.start(form="light", risk="high", expect=4)
        self.assertIn("error=light_refused:risk_high", text)
        code, text = self.start(flow="full", form="light", expect=4)
        self.assertIn("error=light_refused:full", text)
        self.assertFalse((self.pkg() / "state.json").exists())
        self.start(form="light", risk="normal")
        self.assertEqual(self.state()["form"], "light")

    def test_lexicon_match_needs_risk_reason(self):
        self.request.write_bytes(b"Add OAuth login to the admin page.\n")
        code, text = self.start(expect=4)
        self.assertIn("error=risk_reason_required:auth:", text)
        self.assertFalse((self.pkg() / "state.json").exists())
        reason = "Only the text of the login button changes; no auth code is touched."
        self.start("--risk-reason", reason)
        st = self.state()
        self.assertEqual((st["risk"], st["risk_reason"]), ("normal", reason))
        self.assertEqual(self.records("start")[0]["risk_reason"], reason)
        self.start(work_id="demo-high", risk="high")  # high risk needs no reason
        self.assertIsNone(self.state("demo-high")["risk_reason"])

    def test_start_refuses_second_active_flow_on_slug(self):
        self.start()
        code, text = self.start(expect=4)
        self.assertIn("error=active_flow_on_slug:demo:engine", text)
        code, text = self.start(flow="audit", expect=4)
        self.assertIn("error=active_flow_on_slug:demo:engine", text)
        self.assertEqual(len(self.records("start")), 1)
        self.assertEqual(self.state()["flow"], "engine")


class TestStartWithoutGit(EngineCase):
    use_git = False

    def test_start_without_git_uses_walk_baseline(self):
        code, text = self.start()
        st = self.state()
        self.assertFalse(st["git"]["repo"])
        self.assertIsNone(st["base_commit"])
        baseline = textio.read_json(self.pkg() / "baseline.json")
        self.assertIn("src/app.py", baseline)
        self.assertIn("tests/test_app.py", baseline)
        self.assertFalse(any(key.startswith("docs/agentic-sdlc") for key in baseline))
        self.assertFalse((self.pkg() / "dirty.json").exists())
        self.assertEqual(card_fields(text)["step"], "strategy")
        # A RED run is judged on the walk: only a test file changed since start.
        self.write("tests/test_new.py", b"def test_new():\n    assert False\n")
        code, text = self.sdlc("run", "--expect", "fail", "--label", "red", "--", "pytest", "--say=pytest-fail",
                               "--exit=1")
        self.assertEqual(code, 1, text)
        self.assertIn("valid=yes", text)
        self.assertEqual(self.state()["red"], {"recorded": True, "order": "ok"})


# ---------------------------------------------------------------------------------------------
# next / card
# ---------------------------------------------------------------------------------------------

class TestEngine(EngineCase):
    def test_command_lines_read_raw_with_a_windows_interpreter(self):
        # The Windows CI run of b4da09b could not read the strategy card: `confirm=` holds a
        # runnable command whose interpreter path is quoted for cmd.exe ("C:\...\python.exe"), which
        # is not a JSON string. A command line is read raw to the end of the line, like `then=`.
        from sdlc_runner import card as card_mod
        python = r"C:\hostedtoolcache\windows\Python\3.12.10\x64\python.exe"
        with mock.patch.object(card_mod, "_WINDOWS", True), mock.patch.object(sys, "executable", python):
            code, text = self.start()
        fields = card_fields(text)
        self.assertEqual(fields["step"], "strategy", text)
        for key in ("then", "confirm"):
            with self.subTest(key=key):
                self.assertTrue(fields[key].startswith('"%s" -B "' % python), fields[key])

    def test_first_card_is_strategy(self):
        self.write("src/wip.py", b"x = 1\n")  # the user's uncommitted work before start
        self.request.write_bytes(("Add a CSV export to the report page (ref %s).\n" % FAKE_TOKEN).encode("utf-8"))
        code, text = self.start()
        fields = card_fields(text)
        self.assertEqual((fields["state"], fields["step"], fields["visit"], fields["transition"]),
                         ("do", "strategy", "1/1", "1/60"))
        self.assertEqual(fields["root"], str(self.root))
        self.assertEqual(fields["package"], "docs/agentic-sdlc/demo")
        st = self.state()
        self.assertEqual((st["current"], st["steps"]["strategy"]["visits"], st["status"]), ("strategy", 1, "active"))
        self.assertEqual([r["kind"] for r in self.transitions()], ["start", "enter"])
        self.assertEqual(set(textio.read_json(self.pkg() / "dirty.json")), {"src/wip.py"})
        self.assertTrue((self.pkg() / "strategy.default.json").is_file())
        request = (self.pkg() / "request.md").read_text(encoding="utf-8")
        self.assertIn("Add a CSV export", request)
        self.assertNotIn(FAKE_TOKEN, request)
        self.assertRegex(text.splitlines()[-1], CHAIN_LINE)

    def test_next_advances_when_outputs_exist(self):
        self.start()
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "strategy")  # nothing confirmed yet
        self.confirm_strategy()
        code, text = self.next()
        fields = card_fields(text)
        self.assertEqual((fields["step"], fields["visit"], fields["transition"]), ("context", "1/3", "2/60"))
        confirmed = json.loads((self.pkg() / "strategy.json").read_text(encoding="utf-8"))
        self.assertEqual(fields["mechanism"], confirmed["entries"]["context"]["mechanism"])
        self.put("context.md", "# Context\n")
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "snapshot")  # extra does not apply
        st = self.state()
        self.assertEqual(st["steps"]["strategy"]["state"], "done")
        self.assertEqual(st["steps"]["context"]["state"], "done")
        self.assertRegex(st["steps"]["context"]["done_fp"], r"^[0-9a-f]{64}$")
        self.assertEqual([r["step"] for r in self.records("done")], ["strategy", "context"])
        self.assertEqual([r["step"] for r in self.records("enter")], ["strategy", "context", "snapshot"])

    def test_skipped_step_recorded_once_with_reason(self):
        self.start(form="light")
        self.advance_to("implement")
        self.card()
        self.next()  # a third `next` with nothing changed would halt (no progress)
        skips = self.records("skip")
        self.assertEqual(sorted(r["step"] for r in skips), ["extra", "review"])
        reasons = {r["step"]: r["reason"] for r in skips}
        self.assertIn("form", reasons["review"])
        self.assertIn("gated", reasons["review"])
        self.assertIn("quality-review", reasons["extra"])
        st = self.state()
        self.assertEqual(st["steps"]["review"]["state"], "skipped")
        self.assertEqual(st["steps"]["review"]["skip_reason"], reasons["review"])
        self.assertFalse(st["steps"]["review"]["applies"])

    def test_applies_when_frozen_after_first_evaluation(self):
        self.start()
        code, text = self.advance_to("snapshot")
        self.assertFalse(self.state()["steps"]["extra"]["applies"])
        self.edit_state(lambda st: st["options"].append("quality-review"))
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "snapshot")
        self.assertEqual(self.records("enter", step="extra"), [])
        # The other way round: a step that applied keeps applying.
        self.start("--option", "quality-review", work_id="opt")
        code, text = self.advance_to("extra", slug="opt")
        self.assertTrue(self.state("opt")["steps"]["extra"]["applies"])
        self.edit_state(lambda st: st.__setitem__("options", []), slug="opt")
        code, text = self.next("opt")
        self.assertEqual(card_fields(text)["step"], "extra")

    def test_stale_input_reopens_done_step(self):
        self.start()
        self.advance_to("snapshot")
        self.put("request.md", "Add a CSV and a JSON export to the report page.\n")
        code, text = self.next()
        fields = card_fields(text)
        self.assertEqual((fields["step"], fields["visit"]), ("context", "2/3"))
        stale = self.records("stale")
        self.assertEqual([(r["step"], r["input"]) for r in stale], [("context", "request.md")])
        self.assertEqual(self.records("enter", step="context")[-1]["cause"], "stale")
        code, text = self.next()  # context.md is unchanged: the old evidence does not count again
        self.assertEqual(card_fields(text)["step"], "context")
        self.put("context.md", "# Context\n\nCSV and JSON.\n")
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "snapshot")
        self.assertEqual(self.state()["steps"]["context"]["state"], "done")

    def test_restamped_frontmatter_is_no_new_evidence(self):
        self.start()
        self.advance_to("review")
        self.next()  # stamps `reviewed`
        self.put("context.md", "# Context\n\n## Scope Lock\n\nThe report page and the export menu.\n")
        code, text = self.next()  # draft goes stale on its context.md input
        self.assertEqual(card_fields(text)["step"], "draft")
        code, text = self.next()  # stamps `draft` again: a runner write, not the model redoing the draft
        self.assertEqual((card_fields(text)["state"], card_fields(text)["step"]), ("do", "draft"))
        self.put("spec/demo.md", SPEC_BODY.replace("every week", "every Monday"))
        code, text = self.next()
        self.assertEqual(card_fields(text)["state"], "wait-gate")

    def test_run_once_never_reopens(self):
        self.start()
        self.advance_to("draft")
        self.put("notes.md", "A note the snapshot step reads.\n")
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "draft")
        st = self.state()
        self.assertEqual((st["steps"]["snapshot"]["state"], st["steps"]["snapshot"]["visits"]), ("done", 1))
        self.assertEqual(self.records("stale", step="snapshot"), [])

    def test_visit_cap_halts(self):
        self.start()
        self.advance_to("snapshot")
        for visit in (2, 3):
            self.put("request.md", "Request version %d.\n" % visit)
            code, text = self.next()
            self.assertEqual(card_fields(text)["visit"], "%d/3" % visit)
            self.put("context.md", "# Context %d\n" % visit)
            code, text = self.next()
            self.assertEqual(card_fields(text)["step"], "snapshot")
        self.put("request.md", "Request version 4.\n")
        code, text = self.card(expect=3)  # card shows the halt next would make, and records nothing
        self.assertEqual((card_fields(text)["state"], card_fields(text)["preview"]), ("halted", "true"))
        self.assertEqual(self.state()["status"], "active")
        code, text = self.next(expect=3)
        self.assertEqual(card_fields(text)["state"], "halted")
        self.assertIn("loop cap reached: context", text)
        st = self.state()
        self.assertEqual((st["status"], st["steps"]["context"]["visits"]), ("halted", 3))
        self.assertEqual(st["halt"]["reason"], "loop cap reached: context")
        self.next(expect=3)
        self.assertEqual(len(self.records("halt")), 1)

    def test_transition_cap_halts(self):
        self.root = self.make_root(self.tmp / "root-capped",
                                   shared_edit=lambda s: s["caps"].__setitem__("transition_cap", 2))
        code, text = self.start()
        self.assertEqual(card_fields(text)["transition"], "1/2")
        self.confirm_strategy()
        code, text = self.next()
        self.assertEqual(card_fields(text)["transition"], "2/2")
        self.put("context.md", "# Context\n")
        code, text = self.next(expect=3)
        self.assertIn("transition cap reached", text)
        st = self.state()
        self.assertEqual((st["status"], st["transitions"]), ("halted", 2))

    def test_no_progress_halts_after_three(self):
        self.start()
        self.confirm_strategy()
        self.next()  # enters context: returned once
        code, text = self.next()  # returned twice, nothing changed
        self.assertEqual(card_fields(text)["step"], "context")
        code, text = self.next(expect=3)  # the third return with an unchanged world halts
        self.assertIn("no progress: context", text)
        self.assertEqual(self.state()["no_progress"]["count"], 3)

    def test_no_progress_resets_when_the_world_changes(self):
        self.start()
        self.confirm_strategy()
        self.next()
        self.next()
        self.write("src/app.py", b"def add(a, b):\n    return a + b  # edited\n")
        self.next()
        self.assertEqual(self.state()["no_progress"]["count"], 1)
        self.next()
        self.assertEqual(self.state()["status"], "active")

    def test_waits_and_card_do_not_count(self):
        self.start()
        code, text = self.advance_to("review")
        self.assertEqual(card_fields(text)["state"], "wait-gate")
        before = self.state()
        for _ in range(4):
            code, text = self.next()
            self.assertEqual(card_fields(text)["state"], "wait-gate")
        for _ in range(3):
            self.card()
        after = self.state()
        for key in ("transitions", "no_progress", "status", "current"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(after["steps"]["review"]["visits"], before["steps"]["review"]["visits"])
        self.assertEqual(len(self.records("wait")), 1)
        self.assertEqual(after["waiting"]["kind"], "gate")

    def test_card_is_read_only(self):
        self.start()
        self.advance_to("draft")
        self.put("spec/demo.md", SPEC_BODY)
        self.put("plan/demo.md", PLAN_BODY)
        before = {p: p.read_bytes() for p in self.pkg().rglob("*") if p.is_file()}
        code, text = self.card()
        after = {p: p.read_bytes() for p in self.pkg().rglob("*") if p.is_file()}
        self.assertEqual(after, before)
        self.assertEqual(card_fields(text)["preview"], "true")
        code, nexted = self.next()
        self.assertEqual(card_fields(text)["state"], card_fields(nexted)["state"])
        self.assertEqual(card_fields(nexted)["state"], "wait-gate")
        self.assertNotIn("preview", card_fields(nexted))

    def test_runner_stamps_frontmatter_before_validating(self):
        import validate_artifacts

        self.start()
        self.advance_to("draft")
        unstamped = self.put("spec/demo.md", SPEC_BODY)
        self.put("plan/demo.md", PLAN_BODY)
        control = self.tmp / "unstamped-spec.md"
        shutil.copyfile(str(unstamped), str(control))
        self.assertNotEqual(validate_artifacts.run("spec", str(control), None, False)[0], 0)
        code, text = self.next()
        self.assertEqual(card_fields(text)["state"], "wait-gate")  # the validator passed in this same next
        meta, body, had_block = frontmatter.split((self.pkg() / "spec" / "demo.md").read_text(encoding="utf-8"))
        self.assertTrue(had_block)
        # Stamped `draft` before the validator ran, then `reviewed` once this call marked the draft done.
        self.assertEqual(meta, {"work_id": "demo", "status": "reviewed"})
        self.assertEqual(body, SPEC_BODY)
        plan_meta = frontmatter.split((self.pkg() / "plan" / "demo.md").read_text(encoding="utf-8"))[0]
        self.assertEqual(plan_meta, {"work_id": "demo", "spec": "../spec/demo.md", "branch": "main",
                                     "flow": "engine", "status": "reviewed"})
        self.assertEqual(self.state()["stamps"], {"spec/demo.md": "reviewed", "plan/demo.md": "reviewed"})

    def test_foreign_status_fails_check(self):
        self.start()
        self.advance_to("review")
        self.next()  # stamps `reviewed`
        spec = self.pkg() / "spec" / "demo.md"
        original = spec.read_text(encoding="utf-8")
        self.assertIn("status: reviewed", original)
        spec.write_bytes(original.replace("status: reviewed", "status: approved").encode("utf-8"))
        code, text = self.next()
        fields = card_fields(text)
        self.assertEqual((fields["state"], fields["step"]), ("do", "review"))
        self.assertIn("foreign_status:spec/demo.md:approved", text)
        self.assertIn("status: approved", spec.read_text(encoding="utf-8"))  # not stamped over
        self.assertNotEqual(self.state()["steps"]["review"]["state"], "done")
        spec.write_bytes(original.encode("utf-8"))
        code, text = self.next()
        self.assertEqual(card_fields(text)["state"], "wait-gate")

    def test_corrupt_state_exits_2(self):
        self.start()
        (self.pkg() / "state.json").write_bytes(b'{"schema": "agentic-sdlc/state@1", "steps": ')
        for argv in (["next"], ["card"], ["next", "--slug", "demo"], ["status", "--slug", "demo"]):
            with self.subTest(argv=argv):
                code, text = self.sdlc(*argv)
                self.assertEqual(code, 2, text)
                self.assertIn("error=state_corrupt", text)
        # A file that parses but lost a counter or a step field is corrupt too, never a traceback.
        self.start(work_id="other")
        good = self.state("other")
        damaged = [("transitions", lambda st: st.pop("transitions")),
                   ("transition_cap", lambda st: st.__setitem__("transition_cap", "60")),
                   ("visits", lambda st: st["steps"]["strategy"].pop("visits"))]
        for name, damage in damaged:
            with self.subTest(damaged=name):
                st = copy.deepcopy(good)
                damage(st)
                textio.write_json_atomic(self.pkg("other") / "state.json", st)
                for argv in (["next", "--slug", "other"], ["card", "--slug", "other"]):
                    code, text = self.sdlc(*argv)
                    self.assertEqual(code, 2, text)
                    self.assertIn("error=state_corrupt", text)

    def test_complete_flow_exit_0_state_complete(self):
        self.start()
        code, text = self.advance_to(None)
        self.assertEqual(code, 0)
        self.assertEqual(card_fields(text)["state"], "complete")
        st = self.state()
        self.assertEqual((st["status"], st["red"]["order"]), ("complete", "ok"))
        self.assertEqual(self.transitions()[-1]["kind"], "complete")
        self.assertEqual([r["step"] for r in self.records("done")],
                         ["strategy", "context", "snapshot", "draft", "review", "implement", "security", "claim"])
        for name in ("spec", "plan"):
            meta = frontmatter.split((self.pkg() / name / "demo.md").read_text(encoding="utf-8"))[0]
            self.assertEqual(meta["status"], "complete", name)
        self.assertTrue(logs.verify(self.pkg() / "transitions.jsonl")[0])
        self.assertEqual(sdlc_state.find_active(self.project), [])
        code, text = self.next()
        self.assertEqual(card_fields(text)["state"], "complete")

    def test_fix_round_cap_halts(self):
        self.start()
        self.advance_to("security")
        report = "evidence/demo.security.md"
        for version in range(1, 5):  # a failing review, then three re-reviews that fail again
            self.put(report, "# Security review\n\nFinding %d: an injection.\nVerdict: fail\n" % version)
            code, text = self.next()
            self.assertEqual(card_fields(text)["step"], "security")
        self.assertEqual(self.state()["fix_rounds"], 3)
        self.put(report, "# Security review\n\nFinding 5: still there.\nVerdict: fail\n")
        code, text = self.next(expect=3)
        self.assertIn("fix-round cap reached: security", text)
        # The cap is the package's own copy of _shared.caps.fix_rounds; only the user's quote raises it.
        code, text = self.sdlc("resume", "--raise-cap", "fix-rounds", "--quote", "Three more rounds.")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.state()["fix_round_cap"], 6)
        self.put(report, "# Security review\n\nFinding 6.\nVerdict: fail\n")
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "security")

    def test_external_records_another_process_for_draft(self):
        self.start()
        self.advance_to("draft")
        self.write("notes/spec-from-superpowers.md", b"# A spec written by another plugin\n")
        code, text = self.sdlc("external", "implement", "--owner", "superpowers:brainstorming",
                               "--artifact", "notes/spec-from-superpowers.md", "--quote", "Use superpowers for this.")
        self.assertEqual(code, 4, text)
        self.assertIn("error=external_not_allowed:implement", text)
        code, text = self.sdlc("external", "draft", "--owner", "superpowers:brainstorming",
                               "--artifact", "notes/spec-from-superpowers.md", "--quote", "Use superpowers for this.")
        self.assertEqual(code, 0, text)
        st = self.state()
        self.assertEqual(st["steps"]["draft"]["state"], "done")
        self.assertEqual(st["steps"]["draft"]["external"]["owner"], "superpowers:brainstorming")
        record = self.records("external")[0]
        self.assertEqual((record["step"], record["artifact"]), ("draft", "notes/spec-from-superpowers.md"))


# ---------------------------------------------------------------------------------------------
# wave B handoffs (contract §6 and §12 "as built")
# ---------------------------------------------------------------------------------------------

class TestHandoffs(EngineCase):
    def test_start_imports_an_approved_spec(self):
        source = self.tmp / "approved-spec.md"
        code, text = self.start(flow="plan", expect=2)
        self.assertIn("error=import_missing:--spec-file", text)
        source.write_bytes(("---\nwork_id: demo\nstatus: draft\n---\n" + SPEC_BODY).encode("utf-8"))
        code, text = self.start("--spec-file", str(source), flow="plan", expect=4)
        self.assertIn("error=import_status:--spec-file:draft", text)
        self.assertFalse((self.pkg() / "state.json").exists())
        approved = "---\nwork_id: demo\nstatus: approved\n---\n" + SPEC_BODY
        source.write_bytes(approved.encode("utf-8"))
        self.start("--spec-file", str(source), flow="plan")
        self.assertEqual((self.pkg() / "spec" / "demo.md").read_text(encoding="utf-8"), approved)
        self.assertEqual(self.state()["loop"]["mode"], "plan")

    def test_not_option_skips_the_step_when_the_option_is_given(self):
        step = {"id": "alone", "file": "skills/fixture/steps/extra.md", "inputs": [],
                "outputs": ["evidence/{work_id}.alone.md"],
                "done_when": [{"check": "exists", "path": "evidence/{work_id}.alone.md"}],
                "applies_when": {"not_option": "quality-review"}}
        self.put_flow("notopt", lambda flow: flow["steps"].insert(2, step))
        self.start(flow="notopt", work_id="plain")
        self.advance_to("alone", slug="plain")
        self.assertTrue(self.state("plain")["steps"]["alone"]["applies"])
        self.start("--option", "quality-review", flow="notopt", work_id="given")
        self.advance_to("extra", slug="given")
        entry = self.state("given")["steps"]["alone"]
        self.assertFalse(entry["applies"])
        self.assertEqual(entry["skip_reason"], "applies_when not_option=quality-review (given at start)")
        self.assertEqual(entry["state"], "skipped")

    def test_imported_condition_follows_start(self):
        def edit(flow):
            flow["imports"] = [{"path": "seed/{work_id}.md", "option": "--spec-file", "status": "approved",
                                "required": False}]
            for step_id, value in (("with-spec", True), ("without-spec", False)):
                flow["steps"].insert(2, {
                    "id": step_id, "file": "skills/fixture/steps/extra.md", "inputs": [],
                    "outputs": ["evidence/{work_id}.%s.md" % step_id],
                    "done_when": [{"check": "exists", "path": "evidence/{work_id}.%s.md" % step_id}],
                    "applies_when": {"imported": value}})

        self.put_flow("impcond", edit)
        source = self.tmp / "approved-spec.md"
        approved = "---\nwork_id: demo\nstatus: approved\n---\n" + SPEC_BODY
        source.write_bytes(approved.encode("utf-8"))
        self.start("--spec-file", str(source), flow="impcond", work_id="have")
        self.put("evidence/have.with-spec.md", "# with spec", "have")
        self.advance_to("snapshot", slug="have")
        steps = self.state("have")["steps"]
        self.assertTrue(steps["with-spec"]["applies"])
        self.assertFalse(steps["without-spec"]["applies"])
        self.assertEqual(steps["without-spec"]["skip_reason"], "applies_when imported=False (start imported 1 files)")
        self.start(flow="impcond", work_id="none")
        self.put("evidence/none.without-spec.md", "# without spec", "none")
        self.advance_to("snapshot", slug="none")
        steps = self.state("none")["steps"]
        self.assertFalse(steps["with-spec"]["applies"])
        self.assertEqual(steps["with-spec"]["skip_reason"], "applies_when imported=True (start imported 0 files)")
        self.assertTrue(steps["without-spec"]["applies"])

    def test_check_outside_its_work_types_passes(self):
        from sdlc_runner import checks, engine

        self.start()
        ctx = engine.load_context(self.project, self.root, "demo")
        spec = {"check": "exists", "path": "nothing.md", "work_types": ["bugfix"]}
        self.assertTrue(checks.run_check(ctx, spec).ok)
        spec["work_types"] = ["feature"]
        self.assertFalse(checks.run_check(ctx, spec).ok)
        calls = []

        def resolve(repo, plan_path=None, spec_path=None, branch=None, changed_plans=None):
            calls.append({"plan_path": plan_path, "branch": branch, "spec_path": spec_path})
            return mock.Mock(ok=True, errors=[])

        with mock.patch.object(paths, "_resolver", return_value=mock.Mock(resolve=resolve)):
            self.assertTrue(checks.run_check(ctx, {"check": "resolver_ok"}).ok)
        self.assertEqual(calls, [{"plan_path": None, "branch": "main", "spec_path": None}])

    def test_red_saver_merges_only_red(self):
        self.start()
        self.edit_state(lambda st: st.__setitem__("transitions", 7))
        snapshot = self.state()
        snapshot["transitions"] = 1
        snapshot["red"] = {"recorded": True, "order": "ok"}
        sdlc_state.red_saver(self.pkg())(snapshot)
        st = self.state()
        self.assertEqual((st["transitions"], st["red"]), (7, {"recorded": True, "order": "ok"}))

    def test_fix_round_cap_counts_stale_reentries(self):
        self.start()
        self.advance_to("security")
        report = "evidence/demo.security.md"
        self.put(report, "# Security review\n\nFinding A.\nVerdict: fail\n")
        self.next()
        self.put(report, "# Security review\n\nFinding A again.\nVerdict: fail\n")
        self.next()  # an in-visit re-review that failed: round 1
        self.put(report, "# Security review\n\nFixed.\nVerdict: pass\n")
        code, text = self.next()  # the re-review that passed: round 2
        self.assertEqual(card_fields(text)["step"], "claim")
        self.write("src/app.py", b"def add(a, b):\n    return a + b  # after the review\n")
        code, text = self.next()  # a source change reopens security: round 3
        self.assertEqual((card_fields(text)["step"], card_fields(text)["visit"]), ("security", "2/3"))
        self.assertEqual(self.state()["fix_rounds"], 3)
        self.put(report, "# Security review\n\nFinding B.\nVerdict: fail\n")
        self.next()
        self.put(report, "# Security review\n\nFinding B again.\nVerdict: fail\n")
        code, text = self.next(expect=3)
        self.assertIn("fix-round cap reached: security", text)


# ---------------------------------------------------------------------------------------------
# escalate, halt, resume, abandon
# ---------------------------------------------------------------------------------------------

class TestFlowOps(EngineCase):
    def test_escalate_lattice_upward_only(self):
        self.start(flow="bugfix", work_type="bugfix")
        code, text = self.sdlc("escalate", "feature", "--reason", "it is a feature after all")
        self.assertEqual(code, 4, text)
        self.assertIn("error=escalate_not_upward:bugfix->feature", text)
        code, text = self.sdlc("escalate", "full", "--reason", "the fix needs a spec")
        self.assertEqual(code, 0, text)
        st = self.state()
        self.assertEqual((st["flow"], st["work_type"], st["form"]), ("full", "bugfix", "gated"))
        for target in ("bugfix", "full"):  # downward, then sideways
            code, text = self.sdlc("escalate", target, "--reason", "again")
            self.assertEqual(code, 4, text)
        self.assertEqual(self.state()["flow"], "full")
        # light -> gated on the same flow is upward; doing it twice is sideways.
        self.start(flow="feature", work_id="lite", form="light")
        code, text = self.sdlc("escalate", "feature", "--slug", "lite", "--form", "gated", "--reason", "auth after all")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.state("lite")["form"], "gated")
        code, text = self.sdlc("escalate", "feature", "--slug", "lite", "--form", "gated", "--reason", "again")
        self.assertEqual(code, 4, text)
        # spec -> feature maps the work type.
        self.start(flow="spec", work_id="spec-only", work_type="test")
        code, text = self.sdlc("escalate", "feature", "--slug", "spec-only", "--reason", "build it")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.state("spec-only")["work_type"], "feature")

    def test_escalate_carries_strategy_and_counter(self):
        self.start(flow="bugfix", work_type="bugfix")
        self.confirm_strategy()
        self.next()
        strategy_before = json.loads((self.pkg() / "strategy.json").read_text(encoding="utf-8"))
        before = self.state()
        self.assertEqual(before["current"], "context")
        code, text = self.sdlc("escalate", "full", "--reason", "the fix needs a spec")
        self.assertEqual(code, 0, text)
        after = self.state()
        strategy_after = json.loads((self.pkg() / "strategy.json").read_text(encoding="utf-8"))
        for key, entry in strategy_before["entries"].items():  # carried; only missing keys are added
            self.assertEqual(strategy_after["entries"][key], entry, key)
        self.assertEqual(after["transitions"], before["transitions"])
        old_ids = {s["id"] for s in manifest.load_flow(self.root, "bugfix")["steps"]}
        added = [s for s in manifest.load_flow(self.root, "full")["steps"] if s["id"] not in old_ids]
        self.assertEqual(sorted(s["id"] for s in added),
                         ["diff-review", "docs-check", "intent", "quality-gates", "quality-review"])
        self.assertEqual(after["transition_cap"], 60 + sum(s.get("max_visits", 3) for s in added))
        self.assertEqual(after["steps"]["strategy"], before["steps"]["strategy"])
        self.assertEqual(after["steps"]["context"]["visits"], 1)
        self.assertEqual(after["loop"]["mode"], "spec+plan")
        record = self.records("escalate")[0]
        self.assertEqual((record["from"], record["to"], record["reason"]), ("bugfix", "full", "the fix needs a spec"))

    def test_halt_resume_abandon(self):
        self.start()
        self.confirm_strategy()
        self.next()
        code, text = self.sdlc("halt", "--reason", "The user stops for today.")
        self.assertEqual(code, 3, text)
        self.assertEqual(card_fields(text)["state"], "halted")
        self.next(expect=3)
        self.card(expect=3)
        self.assertEqual(self.state()["status"], "halted")
        code, text = self.sdlc("resume")
        self.assertEqual(code, 0, text)
        st = self.state()
        self.assertEqual((st["status"], st["halt"]), ("active", None))
        self.assertEqual(st["no_progress"]["count"], 0)
        code, text = self.next()
        self.assertEqual(card_fields(text)["step"], "context")
        code, text = self.sdlc("abandon", "--quote", "Drop this work.")
        self.assertEqual(code, 0, text)
        self.assertEqual(card_fields(text)["state"], "abandoned")
        code, text = self.next()
        self.assertEqual(card_fields(text)["state"], "abandoned")
        self.assertEqual(sdlc_state.find_active(self.project), [])
        code, text = self.sdlc("resume", "--slug", "demo")
        self.assertEqual(code, 4, text)
        for kind in ("halt", "resume", "abandon"):
            self.assertEqual(len(self.records(kind)), 1, kind)

    def test_resume_raise_cap_needs_quote(self):
        self.start()
        self.confirm_strategy()
        self.next()
        self.sdlc("halt", "--reason", "pause")
        code, text = self.sdlc("resume", "--raise-cap", "context")
        self.assertEqual(code, 4, text)
        self.assertIn("error=raise_cap_needs_quote", text)
        self.assertEqual(self.state()["status"], "halted")
        code, text = self.sdlc("resume", "--raise-cap", "context", "--quote", "Give it three more tries.")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.state()["steps"]["context"]["max_visits"], 6)
        record = self.records("resume")[-1]
        self.assertEqual((record["raise_cap"], record["quote"]), ("context", "Give it three more tries."))
        self.sdlc("halt", "--reason", "pause again")
        code, text = self.sdlc("resume", "--raise-cap", "transitions", "--quote", "Go on.")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.state()["transition_cap"], 120)
        self.sdlc("halt", "--reason", "pause once more")
        code, text = self.sdlc("resume", "--raise-cap", "nosuch", "--quote", "Go on.")
        self.assertEqual(code, 2, text)
        self.assertIn("error=unknown_step:nosuch", text)



DESIGN_BODY = (
    "# Design: report export\n\n"
    "## Intent\nUsers export a report as CSV so they stop copying numbers by hand every week.\n\n"
    "## Non-goals\n- No PDF or spreadsheet export in this change.\n\n"
    "## Approaches\n- A: stream the rows. B: build the file in memory first.\n\n"
    "## Decisions\n- D1: The export is a CSV file. (user)\n"
    "- D2: Rows are streamed. (author's call: memory stays flat)\n"
)
SOURCED_SPEC_BODY = SPEC_BODY.replace(
    "then a CSV file returns every visible row.", "then a CSV file returns every visible row. (source: D1, Q1)")
SPECLESS_PLAN = (
    "---\nwork_id: demo\nspec: none\nflow: feature\nbranch: feat/demo\nstatus: draft\n---\n\n"
    "# Plan: report export\n\n## Acceptance Criteria\n"
    "- AC1: Given a report, when the user exports it, then a CSV file returns every row. (source: D2)\n\n"
    "## Task 1: CSV export (AC1)\n\n"
    "Create `src/export.py` and its test `tests/test_export.py`.\n\n"
    "- RED: write the failing test for AC1 first.\n- Run: `pytest tests/test_export.py`\n"
)


class TestValidatorCheckModes(EngineCase):
    """`design` reads the package root; `sources` hands the validator design.md and the check file."""

    def ctx(self):
        from sdlc_runner import engine

        self.start()
        return engine.load_context(self.project, self.root, "demo")

    def put(self, rel, text):
        target = self.pkg() / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))

    def test_validator_check_design_reads_the_package_root(self):
        from sdlc_runner import checks, engine

        ctx = self.ctx()
        spec = {"check": "validator", "mode": "design", "strict": True}
        missing = checks.run_check(ctx, spec)
        self.assertFalse(missing.ok)
        self.assertIn("design.md is missing", missing.detail)
        # Not `design/demo.md`: the design sits at the package root beside request.md.
        self.put("design/demo.md", DESIGN_BODY)
        self.assertFalse(checks.run_check(ctx, spec).ok)
        self.put("design.md", DESIGN_BODY)
        found = checks.run_check(ctx, spec)
        self.assertTrue(found.ok, found.detail)
        self.assertIn("design.md", found.detail)
        self.put("design.md", DESIGN_BODY.replace("(user)", ""))
        broken = checks.run_check(ctx, spec)
        self.assertFalse(broken.ok)
        self.assertIn("decision_missing_owner:D1", broken.detail)
        # A step that names the check treats design.md as a file it references.
        step = {"id": "intent", "done_when": [spec]}
        self.assertIn("design.md", engine._referenced(ctx, step))

    def test_validator_check_sources_reads_design_and_check(self):
        from sdlc_runner import checks

        ctx = self.ctx()
        self.put("spec/demo.md", "---\nwork_id: demo\nstatus: draft\n---\n" + SOURCED_SPEC_BODY)
        spec = {"check": "validator", "mode": "spec", "sources": True}
        # Neither file exists: D1 and Q1 are unknown.
        result = checks.run_check(ctx, spec)
        self.assertFalse(result.ok)
        self.assertIn("ac_unknown_source:AC1:D1", result.detail)
        self.assertIn("ac_unknown_source:AC1:Q1", result.detail)
        self.put("design.md", DESIGN_BODY)
        result = checks.run_check(ctx, spec)
        self.assertFalse(result.ok)
        self.assertNotIn("ac_unknown_source:AC1:D1", result.detail)
        self.assertIn("ac_unknown_source:AC1:Q1", result.detail)
        self.put("spec/demo.check.json", json.dumps({"questions": [{"id": "Q1"}]}))
        result = checks.run_check(ctx, spec)
        self.assertTrue(result.ok, result.detail)
        # Without the parameter, sources are not read at all.
        self.put("spec/demo.md", "---\nwork_id: demo\nstatus: draft\n---\n" + SPEC_BODY)
        self.assertTrue(checks.run_check(ctx, {"check": "validator", "mode": "spec"}).ok)
        self.assertFalse(checks.run_check(ctx, spec).ok)
        # A spec-less plan: its own criteria are sourced from design.md (D2); no spec file is read.
        self.put("plan/demo.md", SPECLESS_PLAN)
        plan_spec = {"check": "validator", "mode": "plan", "strict": True, "sources": True}
        result = checks.run_check(ctx, plan_spec)
        self.assertFalse(result.ok, "a spec beside a spec-less plan")
        (self.pkg() / "spec" / "demo.md").unlink()
        result = checks.run_check(ctx, plan_spec)
        self.assertTrue(result.ok, result.detail)
        (self.pkg() / "design.md").unlink()
        result = checks.run_check(ctx, plan_spec)
        self.assertFalse(result.ok)
        self.assertIn("ac_unknown_source:AC1:D2", result.detail)

    def test_validator_check_rejects_an_unknown_mode_and_bad_sources(self):
        from sdlc_runner import checks, manifest

        ctx = self.ctx()
        self.assertEqual(checks.run_check(ctx, {"check": "validator", "mode": "all"}).detail,
                         "unknown_validator_mode:all")
        required, optional = manifest.CHECK_PARAMS["validator"]
        self.assertEqual(required, ("mode",))
        self.assertIn("sources", optional)


if __name__ == "__main__":
    unittest.main()
