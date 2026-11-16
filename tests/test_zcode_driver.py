"""The ZCode driver of the spec/plan loop (plan Task 13): workflows/zcode/spec-plan-draft.dwf.ts.

Contract: docs/agentic-sdlc/notes/2026-10-22-runner-contract.md §10. A ZCode script cannot write
files, so the runner is the engine: the driver asks `sdlc next --engine zcode-dwf --json` for each
role card, gives the card to a NEW actor, and records the answer with `sdlc loop-record`; the
runner's own `next` ingests the result at the stop.

Static pins on the script, and the driver against the real runner: the script runs under `node`
(type stripping, Node 22.18 or later) with `world.run` spawning the real `scripts/sdlc.py` and
`agent()` returning stub actors. No model and no paid CLI runs; without a type-stripping `node`
the run tests skip (reported, never passed).
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
for folder in (REPO / "scripts", TESTS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from test_sdlc_loop import LoopCase  # noqa: E402
from test_sdlc_engine import PLAN_BODY, SPEC_BODY, card_value  # noqa: E402

DRIVER = REPO / "workflows" / "zcode" / "spec-plan-draft.dwf.ts"
NODE = shutil.which("node")


def _strips_types():
    """Whether this node runs a .mts file with type annotations (Node 22.18+ / 23.6+)."""
    if NODE is None:
        return False
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "probe.mts"
        probe.write_text("const x: number = 1;\ninterface A { b: string }\nprocess.stdout.write(String(x));\n",
                         encoding="utf-8", newline="\n")
        try:
            proc = subprocess.run([NODE, str(probe)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        except (OSError, subprocess.SubprocessError):
            return False
        return proc.returncode == 0 and proc.stdout == "1"


TS = _strips_types()
NO_TS = "node with TypeScript type stripping not available - driver run skipped (not passed)"

STUB = r"""
import { spawnSync } from 'node:child_process';
const calls = [];
const actors = [];
const world = {
  async run(program, argv) {
    const proc = spawnSync(program, argv, { encoding: 'utf8', timeout: 60000 });
    calls.push({ program, argv, code: proc.status });
    return { exitCode: proc.status, stdout: (proc.stdout || '') + (proc.stderr || '') };
  },
};
function agent(name, instructions) {
  const actor = { name, instructions, asks: [] };
  actors.push(actor);
  return {
    async ask(prompt) {
      actor.asks.push(prompt);
      if (/critic\.r\d+\.md/.test(prompt)) {
        const n = Number(/critic\.r(\d+)\.md/.exec(prompt)[1]);
        return JSON.stringify((CONFIG.critics || [])[Math.min(n, (CONFIG.critics || []).length) - 1]
          || { verdict: 'clean', issues: [] });
      }
      return /author-spec/.test(prompt) ? CONFIG.spec : CONFIG.plan;
    },
  };
}
const logs = [];
function log(message) { logs.push(String(message)); }
function report(value) { logs.push(JSON.stringify(value)); }
function phase(title) { logs.push('phase:' + title); }
"""


def run_driver(args, config, timeout=180, cwd=None):
    src = DRIVER.read_text(encoding="utf-8")
    header_end = src.index("*/") + 2
    body = src[header_end:]
    # Interfaces must sit at module level; the body (with its top-level return) goes in a function.
    interfaces = re.findall(r"^interface \w+ \{.*?^\}\n", body, re.S | re.M)
    for block in interfaces:
        body = body.replace(block, "")
    driver = (STUB + "const CONFIG = %s;\nconst args = %s;\n" % (json.dumps(config), json.dumps(args))
              + "".join(interfaces) + "async function __dwf() {\n" + body + "\n}\n"
              + "__dwf().then((result) => process.stdout.write(JSON.stringify({ ok: true, result, calls, actors, logs }) + '\\n'))"
              + ".catch((err) => process.stdout.write(JSON.stringify({ ok: false, message: String(err && err.message || err), "
              + "calls, actors, logs }) + '\\n'));\n")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "driver.mts"
        path.write_text(driver, encoding="utf-8", newline="\n")
        proc = subprocess.run([NODE, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                              cwd=cwd)
    lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    if not lines:
        raise AssertionError("no JSON from the driver (rc=%s):\n%s" % (proc.returncode, proc.stderr))
    return json.loads(lines[-1])


class TestDriverStructure(unittest.TestCase):
    def setUp(self):
        self.text = DRIVER.read_text(encoding="utf-8")
        self.header = self.text.split("*/", 1)[0]
        self.body = self.text.split("*/", 1)[1]

    def test_header_declares_the_launch_args(self):
        self.assertTrue(self.text.startswith("/* zcode-workflow\n"))
        for arg in ("slug", "pluginRoot", "python"):
            block = self.header.split("  %s:\n" % arg, 1)[1].split("\n  ", 4)
            self.assertIn("required: true", "\n".join(block[:3]), arg)
            self.assertIn("args.%s" % arg, self.body)
        rounds = self.header.split("  maxRounds:\n", 1)[1]
        self.assertIn("required: false", rounds.split("description:", 1)[0])
        self.assertIn("args.maxRounds", self.body)

    def test_runs_the_runner_by_argv_and_records_through_it(self):
        self.assertIn('world.run(python, ["-B", sdlc, ...argv])', self.body)
        self.assertIn('runner(["next", "--slug", slug, "--engine", "zcode-dwf", "--json"])', self.body)
        self.assertRegex(self.body, r'runner\(\["loop-record", "--slug", slug, "--role", card\.role, "--round", '
                                    r'String\(card\.round\),\s*"--text", ')
        self.assertNotIn("files.", self.body)
        self.assertNotIn("validate_artifacts", self.body)

    def test_a_new_actor_for_every_card(self):
        loop = self.body.split("for (let asked = 0; asked < cardCap; asked++) {", 1)[1]
        self.assertIn("const actor = agent(", loop)
        self.assertEqual(self.body.count("agent("), 1)
        self.assertLess(loop.index("const actor = agent("), loop.index("actor.ask<string>("))

    def test_phase_names_are_literals(self):
        for call in re.findall(r"phase\(([^)]*)\)", self.body):
            self.assertRegex(call, r'^"[^"]+"$')

    def test_no_claude_facade_tokens(self):
        for token in ("export const meta", "agentType:", "isolation:", "pipeline(", "parallel("):
            self.assertNotIn(token, self.text)


@unittest.skipUnless(TS, NO_TS)
class TestDriverAgainstTheRunner(LoopCase):
    def launch(self, slug="demo"):
        text = self.to_draft(runtime="zcode", capabilities="workflow=yes,subagent=yes,team=no", slug=slug,
                             overrides=("draft=workflow:the user asked for a ZCode workflow",
                                        "draft.critic=workflow:the user asked for a ZCode workflow"))
        launch = card_value(text, "launch")
        self.assertTrue(launch and launch.startswith("CreateWorkflow "), text)
        call = json.loads(launch[len("CreateWorkflow "):])
        self.assertEqual(call["path"], str(self.root / "workflows" / "zcode" / "spec-plan-draft.dwf.ts"))
        # The driver runs this checkout's runner, whose flows are the ones the temp root copied.
        return dict(call["args"], pluginRoot=str(REPO))

    def test_a_clean_loop_is_ingested_by_the_runner(self):
        payload = run_driver(self.launch(), cwd=str(self.project), config={"spec": SPEC_BODY, "plan": PLAN_BODY,
                                             "critics": [{"verdict": "clean", "issues": []}]})
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["result"]["ok"], payload["result"])
        loop_state = self.state()["loop"]
        self.assertEqual((loop_state["engine"], loop_state["stop_reason"], loop_state["ingested"]),
                         ("zcode-dwf", "clean", True))
        sidecar = json.loads((self.pkg() / "spec" / "demo.review.json").read_text(encoding="utf-8"))
        self.assertEqual((sidecar["engine"], sidecar["critic"]), ("zcode-dwf", "fresh"))
        # One new actor per card: two authors and one critic, each asked exactly once.
        self.assertEqual([len(a["asks"]) for a in payload["actors"]], [1, 1, 1])
        self.assertEqual(len({a["name"] for a in payload["actors"]}), 3)
        records = [c["argv"] for c in payload["calls"] if "loop-record" in c["argv"]]
        self.assertEqual([r[r.index("--role") + 1] for r in records], ["author-spec", "author-plan", "critic"])

    def test_a_revised_loop_gives_every_critic_a_new_actor(self):
        issue = {"target": "spec", "category": "coverage", "severity": "high", "kind": "gap",
                 "whatsMissing": "the export file name", "where": "## Business Rules", "fix": "name it"}
        payload = run_driver(self.launch(), cwd=str(self.project), config={"spec": SPEC_BODY, "plan": PLAN_BODY, "critics": [
            {"verdict": "issues", "issues": [issue]}, {"verdict": "clean", "issues": []}]})
        self.assertTrue(payload["result"]["ok"], payload)
        names = [a["name"] for a in payload["actors"]]
        self.assertEqual(len(names), len(set(names)))
        critics = [a for a in payload["actors"] if a["name"].startswith("critic-")]
        self.assertEqual([a["name"].split("-")[1] for a in critics], ["r1", "r2"])
        self.assertEqual(self.state()["loop"]["stop_reason"], "clean")
        self.assertEqual(self.state()["loop"]["rounds"], 2)

    def test_a_refused_answer_is_asked_again_until_the_runner_halts(self):
        # loop-record refuses the critic JSON, the runner keeps the critic card, a new actor is asked
        # again, and the runner's no-progress cap halts the loop: nothing is ingested.
        payload = run_driver(self.launch(), cwd=str(self.project), config={"spec": SPEC_BODY, "plan": PLAN_BODY,
                                             "critics": [{"verdict": "maybe", "issues": []}]})
        result = payload["result"]
        self.assertEqual((result["ok"], result["reason"], result["state"]), (False, "the runner halted the loop", "halted"))
        critics = [a["name"] for a in payload["actors"] if a["name"].startswith("critic-r1-")]
        self.assertEqual(len(critics), 2)
        self.assertFalse(self.state()["loop"].get("ingested"))


class TestDriverArgs(unittest.TestCase):
    @unittest.skipUnless(TS, NO_TS)
    def test_invalid_args_throw_before_the_runner_runs(self):
        good = {"slug": "demo", "pluginRoot": "/opt/agentic-sdlc", "python": "/usr/bin/python3"}
        for args in (dict(good, slug="Demo"), dict(good, pluginRoot="relative"), dict(good, python="/usr/bin/python3\nrm"),
                     dict(good, pluginRoot="//server/share"), dict(good, maxRounds=6), dict(good, maxRounds=2.5)):
            with self.subTest(args=args):
                payload = run_driver(args, {})
                self.assertFalse(payload["ok"], payload)
                self.assertIn("spec-plan-draft:", payload["message"])
                self.assertEqual(payload["calls"], [])


if __name__ == "__main__":
    unittest.main()
