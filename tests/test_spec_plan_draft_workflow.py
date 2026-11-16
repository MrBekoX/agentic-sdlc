"""The Claude Code engine of the spec/plan loop (plan Task 11): workflows/spec-plan-draft.js.

Contract: docs/agentic-sdlc/notes/2026-10-22-runner-contract.md §10 (round numbering, the launch
args, the runner's file names, stop rules, `loop.json`, `ingest-draft --assemble`); design §5.9.2
(the script has no file or shell access, role agents are read-only, a draft-scribe writes the
files and runs the runner commands).

Three layers:
- static pins on the script text (no interpreter needed);
- dry runs under `node` with a stubbed `agent()` whose scribe keeps the files in memory;
- the engine against the real runner: a package brought to its draft step on Claude Code, the
  script driven with stubbed role agents and a scribe that really writes the files and really runs
  `scripts/sdlc.py`, and the runner then ingesting the result.

No model and no paid CLI runs. Without `node` the script tests skip (reported, never passed).
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
from test_sdlc_engine import PLAN_BODY, SPEC_BODY, card_fields, card_value  # noqa: E402
from sdlc_runner import loop  # noqa: E402

NODE = shutil.which("node")
SCRIPT = REPO / "workflows" / "spec-plan-draft.js"
LOOP = json.loads((REPO / "flows" / "loops" / "spec-plan.json").read_text(encoding="utf-8"))
NO_NODE = "node not available - workflow script check skipped (not passed)"

POSIX_PKG = "/work/proj/docs/agentic-sdlc/demo"
WIN_PKG = "C:\\work\\proj\\docs\\agentic-sdlc\\demo"
ARGS = {"slug": "demo", "workId": "demo", "mode": "spec+plan", "maxRounds": 3, "packageDir": POSIX_PKG,
        "pluginRoot": "/opt/agentic-sdlc", "python": "/usr/bin/python3"}


def _issue(where="## Business Rules", severity="high", kind="gap", target="spec", category="coverage"):
    return {"target": target, "category": category, "severity": severity, "kind": kind,
            "whatsMissing": "the export file name", "where": where, "fix": "name it"}


CLEAN = {"verdict": "clean", "issues": [], "coverageCheck": "AC1 covered"}


def issues(*items):
    return {"verdict": "issues", "issues": list(items), "coverageCheck": "AC1 open"}


# The driver: the script body inside the runtime wrapper, and an `agent()` stub. Role agents answer
# from CONFIG; the scribe either keeps files in memory or (CONFIG.real) writes them and runs the
# runner command it was handed.
DRIVER = r"""
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
const files = {};
const calls = [];
const MARK = '=====8<===== ';
function roundOf(label) { const m = /:r(\d+)/.exec(label); return m ? Number(m[1]) : 0; }
function scribeWrite(prompt) {
  const lines = prompt.split('\n');
  const pathLine = lines.find((l) => l.startsWith('Path: '));
  const first = lines.findIndex((l) => l.startsWith(MARK));
  const marker = lines[first];
  const last = lines.lastIndexOf(marker);
  const target = pathLine.slice('Path: '.length).replace(/^"|"$/g, '');
  const text = lines.slice(first + 1, last).join('\n') + '\n';
  if (CONFIG.real) {
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, text, 'utf8');
  }
  files[target] = text;
  return { action: 'write', path: target, bytes: Buffer.byteLength(text) };
}
function scribeCommand(prompt) {
  const line = prompt.split('\n').find((l) => l.startsWith('The same command as an argument list (JSON): '));
  const argv = JSON.parse(line.slice('The same command as an argument list (JSON): '.length));
  const sub = argv[7];
  if (CONFIG.real) {
    const proc = spawnSync(argv[0], argv.slice(1), { encoding: 'utf8', timeout: 60000 });
    return { action: 'command', exitCode: proc.status, output: (proc.stdout || '') + (proc.stderr || ''), argv };
  }
  if (sub === 'draft-check') {
    const n = Number(argv[9]);
    return { action: 'command', exitCode: CONFIG.draftCheckExit || 0, argv,
      output: 'draft_check=' + ((CONFIG.validator || [])[n - 1] || 'clean') + ' round=' + (CONFIG.checkRound || n)
        + '\nstate=do chain=000000000000\n' };
  }
  const code = CONFIG.ingestExit || 0;
  const output = CONFIG.ingestOutput !== undefined ? CONFIG.ingestOutput
    : (code === 0 ? 'ingested=x\nstate=wait chain=000000000000\n' : 'error=loop_json_invalid:x\n');
  return { action: 'command', exitCode: code, argv, output };
}
async function stubAgent(prompt, opts) {
  const label = (opts && opts.label) || '';
  calls.push({ label, prompt: String(prompt), agentType: opts && opts.agentType, effort: opts && opts.effort,
    schema: !!(opts && opts.schema) });
  if (CONFIG.nullLabel && label.startsWith(CONFIG.nullLabel)) return null;
  if (opts.agentType === 'agentic-sdlc:draft-scribe') {
    if (CONFIG.refuse && label.startsWith(CONFIG.refuse)) return { action: 'refused', reason: 'outside the package' };
    const report = prompt.startsWith('Write call.') ? scribeWrite(prompt) : scribeCommand(prompt);
    calls[calls.length - 1].report = report;
    return report;
  }
  if (opts.agentType === 'agentic-sdlc:spec-plan-critic') {
    if (label.endsWith(':retry') && CONFIG.retry) return CONFIG.retry;
    const list = CONFIG.critics || [];
    return list[Math.min(roundOf(label), list.length) - 1] || { verdict: 'clean', issues: [] };
  }
  const artifact = label.split(':')[1];
  const body = (CONFIG.bodies || {})[artifact] || ('# Draft ' + label + '\n\nBody.\n');
  return { draftMarkdown: body, decisionPoints: (CONFIG.points || {})[label] || [] };
}
const logs = [];
__wf(ARGS, stubAgent, null, null, (m) => logs.push(String(m)), null, null, null)
  .then((result) => { process.stdout.write(JSON.stringify({ ok: true, result, calls, files, logs }) + '\n'); })
  .catch((err) => {
    process.stdout.write(JSON.stringify({ ok: false, name: err && err.name, message: String(err && err.message || err),
      calls, files, logs }) + '\n');
  });
"""


def run_script(args, config=None, timeout=60):
    if NODE is None:
        raise unittest.SkipTest(NO_NODE)
    src = SCRIPT.read_text(encoding="utf-8").replace("export const meta", "const meta", 1)
    wrapped = ("async function __wf(args, agent, parallel, pipeline, log, phase, budget, workflow) {\n" + src + "\n}\n")
    head = "const CONFIG = %s;\nconst ARGS = %s;\n" % (json.dumps(config or {}), json.dumps(args))
    with tempfile.TemporaryDirectory() as td:
        driver = Path(td) / "driver.mjs"
        lines = DRIVER.strip().splitlines()
        imports = [line for line in lines if line.startswith("import ")]
        body = [line for line in lines if not line.startswith("import ")]
        driver.write_text("\n".join(imports) + "\n" + head + wrapped + "\n".join(body) + "\n", encoding="utf-8",
                          newline="\n")
        proc = subprocess.run([NODE, str(driver)], capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    out = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    if not out:
        raise AssertionError("no JSON from the driver (rc=%s):\n%s" % (proc.returncode, proc.stderr))
    return json.loads(out[-1])


def labels(payload, scribe=False):
    return [c["label"] for c in payload["calls"] if scribe or not c["label"].startswith("scribe:")]


def written(payload, root=POSIX_PKG):
    """The package-relative files the scribe wrote, in order."""
    prefix = root.rstrip("/\\") + ("\\" if "\\" in root else "/")
    out = []
    for call in payload["calls"]:
        report = call.get("report") or {}
        if report.get("action") == "write":
            out.append(report["path"][len(prefix):].replace("\\", "/"))
    return out


def loop_json(payload, root=POSIX_PKG):
    for target, text in payload["files"].items():
        if target.replace("\\", "/").endswith("/draft/loop.json"):
            return json.loads(text)
    raise AssertionError("no loop.json written")


def rel(key, role=None, round_no=None):
    return LOOP["files"][key].format(role=role or "", round=round_no if round_no is not None else "")


class TestStructure(unittest.TestCase):
    """What the script must say, read from its text."""

    def setUp(self):
        self.src = SCRIPT.read_text(encoding="utf-8")

    def test_meta_name_is_the_launch_name(self):
        self.assertRegex(self.src, r"export const meta = \{\s*name: 'spec-plan-draft',")

    def test_reads_every_launch_arg(self):
        runner_args = self.src.split("function runnerArgs(a) {", 1)[1].split("\n}\n", 1)[0]
        for key in ("slug", "workId", "mode", "maxRounds", "packageDir", "pluginRoot", "python"):
            with self.subTest(arg=key):
                self.assertIn("a.%s" % key, runner_args)

    def test_role_and_scribe_agent_types(self):
        for agent in ("spec-plan-author", "spec-plan-critic", "draft-scribe"):
            with self.subTest(agent=agent):
                self.assertIn("agentType:'agentic-sdlc:%s'" % agent, self.src)
        scribe = re.search(r"agentType:'agentic-sdlc:draft-scribe', effort: '(\w+)'", self.src)
        self.assertEqual(scribe and scribe.group(1), "low")

    def test_finishes_with_assemble_and_names_engine_and_caps(self):
        self.assertIn("'ingest-draft', ['--assemble']", self.src)
        self.assertIn("'draft-check', ['--round', String(n)]", self.src)
        self.assertIn("const ENGINE_ID = 'claude-workflow'", self.src)
        caps = LOOP["caps"]
        self.assertIn("const CAPS = { maxRounds: %d, hardMaxRounds: %d }" % (caps["max_rounds"], caps["hard_max_rounds"]),
                      self.src)

    def test_label_prefixes(self):
        for prefix in ("'author:'", "'author-revise:'", "'critic:'", "':final'"):
            with self.subTest(prefix=prefix):
                self.assertIn(prefix, self.src)


@unittest.skipIf(NODE is None, NO_NODE)
class TestModesTable(unittest.TestCase):
    def test_modes_match_the_loop_definition(self):
        src = SCRIPT.read_text(encoding="utf-8")
        block = re.search(r"const MODES = (\{.*?\n\})\n", src, re.S).group(1)
        proc = subprocess.run([NODE, "-e", "process.stdout.write(JSON.stringify(%s))" % block],
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        table = json.loads(proc.stdout)
        expected = {
            name: {"artifacts": mode["artifacts"],
                   "first": [[i["role"], i["author_mode"]] for i in mode["first_round"]],
                   "revise": [[i["role"], i["author_mode"]] for i in mode["revise"]]}
            for name, mode in LOOP["modes"].items()}
        self.assertEqual(table, expected)


@unittest.skipIf(NODE is None, NO_NODE)
class TestRounds(unittest.TestCase):
    def test_clean_stop_after_the_first_critic(self):
        payload = run_script(ARGS, {"critics": [CLEAN]})
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["result"], {"ingested": True, "stopReason": "clean", "rounds": 1})
        self.assertEqual(labels(payload), ["author:spec:r0", "author:plan:r0", "critic:spec+plan:r1"])
        self.assertEqual(labels(payload, scribe=True), [
            "author:spec:r0", "scribe:write:" + rel("spec", None, 0), "author:plan:r0", "scribe:write:" + rel("plan", None, 0),
            "scribe:draft-check:r1", "critic:spec+plan:r1", "scribe:write:" + rel("critic", "critic", 1),
            "scribe:write:" + rel("loop"), "scribe:ingest-draft"])
        self.assertEqual(written(payload), [rel("spec", None, 0), rel("plan", None, 0), rel("critic", "critic", 1),
                                            rel("loop")])
        self.assertEqual(loop_json(payload), {"schema": "agentic-sdlc/loop@1", "engine": "claude-workflow",
                                              "mode": "spec+plan", "rounds": 1, "stopReason": "clean",
                                              "critic": ["fresh"], "decisionPoints": []})

    def test_every_call_has_a_schema_and_only_the_scribe_runs_at_low_effort(self):
        payload = run_script(ARGS, {"critics": [issues(_issue()), CLEAN]})
        for call in payload["calls"]:
            with self.subTest(label=call["label"]):
                self.assertTrue(call["schema"])
                expected = "low" if call["label"].startswith("scribe:") else None
                self.assertEqual(call.get("effort"), expected)
                if call["label"].startswith("scribe:"):
                    self.assertIn('\nPackage: "%s"\n' % POSIX_PKG, call["prompt"])

    def test_each_reviser_writes_before_the_next_one_reads(self):
        payload = run_script(ARGS, {"critics": [issues(_issue()), CLEAN]})
        calls = labels(payload, scribe=True)
        start = calls.index("author-revise:spec:r1")
        self.assertEqual(calls[start:start + 5], [
            "author-revise:spec:r1", "scribe:write:" + rel("spec", None, 1), "author-revise:plan:r1",
            "scribe:write:" + rel("plan", None, 1), "scribe:draft-check:r2"])

    def test_clean_and_no_progress_win_over_the_round_cap(self):
        one = run_script(dict(ARGS, maxRounds=1), {"critics": [CLEAN]})
        self.assertEqual(one["result"], {"ingested": True, "stopReason": "clean", "rounds": 1}, one)
        self.assertEqual(labels(one)[-1], "critic:spec+plan:r1:final")
        repeated = issues(_issue())
        two = run_script(dict(ARGS, maxRounds=2), {"critics": [repeated, repeated]})
        self.assertEqual(two["result"], {"ingested": True, "stopReason": "no-progress", "rounds": 2}, two)

    def test_issue_keys_match_the_runner_on_unicode_and_whitespace(self):
        # A key the engine and the runner see differently makes the engine claim a stop the runner
        # refuses at assemble, so the whole run is lost: Turkish dotless i, the sharp s and Python's
        # whitespace set are the cases to get right.
        src = SCRIPT.read_text(encoding="utf-8")
        block = src[src.index("const PY_SPACE"):src.index("function sameKeys")]
        samples = ["Sınır durumları", "Sinir durumlari", "IŞIK", "İstanbul", "STRASSE", "Straße", "ẞ", "ſ", "ﬁle",
                   "ΣΑΣ", "a\x1cb", "a\x85b", "a\ufeffb", "a\u3000b", "tab\there", "  ## Business   RULES "]
        cases = [{"target": "spec", "category": "Edge Case", "where": text} for text in samples]
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "keys.mjs"
            script.write_text(block + "\nprocess.stdout.write(JSON.stringify(%s.map(issueKey)));\n" % json.dumps(cases),
                              encoding="utf-8", newline="\n")
            proc = subprocess.run([NODE, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), [loop.issue_key(case) for case in cases])
        self.assertNotEqual(loop.issue_key(cases[0]), loop.issue_key(cases[1]))

    def test_issue_keys_compare_as_a_set_of_target_category_where(self):
        a, b = _issue(where="## Task 1"), _issue(where="## Task 2", category="scope")
        swapped = run_script(ARGS, {"critics": [issues(a, b), issues(b, a)]})
        self.assertEqual((swapped["result"]["stopReason"], swapped["result"]["rounds"]), ("no-progress", 2))
        for change in ({"target": "plan"}, {"category": "scope"}, {"where": "## Task 9"}):
            with self.subTest(change=change):
                moved = run_script(ARGS, {"critics": [issues(a), issues(dict(a, **change)), CLEAN]})
                self.assertEqual((moved["result"]["stopReason"], moved["result"]["rounds"]), ("clean", 3), moved)

    def test_no_progress_stops_when_the_same_keys_return(self):
        repeated = issues(_issue(where="## Business Rules"))
        again = issues(_issue(where="  ## business   RULES "))  # the same key once normalised
        payload = run_script(ARGS, {"critics": [repeated, again]})
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["result"], {"ingested": True, "stopReason": "no-progress", "rounds": 2})
        self.assertEqual(labels(payload), ["author:spec:r0", "author:plan:r0", "critic:spec+plan:r1",
                                           "author-revise:spec:r1", "author-revise:plan:r1", "critic:spec+plan:r2"])
        self.assertEqual(loop_json(payload)["critic"], ["fresh", "fresh"])

    def test_max_rounds_runs_a_final_critic_after_the_last_revision(self):
        critics = [issues(_issue(where="## Task %d" % n)) for n in range(1, 4)]
        payload = run_script(ARGS, {"critics": critics})
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["result"], {"ingested": True, "stopReason": "max-rounds", "rounds": 3})
        self.assertEqual(labels(payload), [
            "author:spec:r0", "author:plan:r0", "critic:spec+plan:r1", "author-revise:spec:r1", "author-revise:plan:r1",
            "critic:spec+plan:r2", "author-revise:spec:r2", "author-revise:plan:r2", "critic:spec+plan:r3:final"])

    def test_max_rounds_comes_from_the_args_with_the_loop_default(self):
        critics = [issues(_issue(where="## Task %d" % n)) for n in range(1, 6)]
        two = run_script(dict(ARGS, maxRounds=2), {"critics": critics})
        self.assertEqual(two["result"]["rounds"], 2, two)
        self.assertEqual(labels(two)[-1], "critic:spec+plan:r2:final")
        default = dict(ARGS)
        del default["maxRounds"]
        three = run_script(default, {"critics": critics})
        self.assertEqual((three["result"]["rounds"], labels(three)[-1]), (3, "critic:spec+plan:r3:final"), three)

    def test_bugfix_plan_mode_runs_only_the_plan_author(self):
        payload = run_script(dict(ARGS, mode="bugfix-plan"), {"critics": [CLEAN]})
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(labels(payload), ["author:plan:r0", "critic:bugfix-plan:r1"])
        self.assertEqual(written(payload), [rel("plan", None, 0), rel("critic", "critic", 1), rel("loop")])
        author = payload["calls"][0]["prompt"]
        self.assertIn(POSIX_PKG + "/" + rel("prompt", "author-plan", 0), author)
        self.assertIn("bugfix-plan draft body", author)
        self.assertEqual(loop_json(payload)["mode"], "bugfix-plan")

    def test_spec_and_plan_modes_draft_one_artifact(self):
        for mode, artifact in (("spec", "spec"), ("plan", "plan")):
            with self.subTest(mode=mode):
                payload = run_script(dict(ARGS, mode=mode), {"critics": [issues(_issue(target=artifact)), CLEAN]})
                self.assertEqual(labels(payload), ["author:%s:r0" % artifact, "critic:%s:r1" % mode,
                                                   "author-revise:%s:r1" % artifact, "critic:%s:r2" % mode])
                self.assertEqual(payload["result"]["stopReason"], "clean")

    def test_a_blocking_validator_or_issue_is_never_clean(self):
        validator = run_script(ARGS, {"critics": [CLEAN, CLEAN], "validator": ["blocking", "clean"]})
        self.assertEqual(validator["result"], {"ingested": True, "stopReason": "clean", "rounds": 2}, validator)
        for issue in (_issue(severity="high"), _issue(severity="critical"), _issue(severity="low", kind="blocker"),
                      _issue(severity="medium", kind="contradiction")):
            with self.subTest(issue=issue):
                payload = run_script(ARGS, {"critics": [{"verdict": "clean", "issues": [issue]}, CLEAN]})
                self.assertEqual(payload["result"]["rounds"], 2, payload)
        for issue in (_issue(severity="low", kind="style"), _issue(severity="medium", kind="gap")):
            with self.subTest(clean_with=issue):
                payload = run_script(ARGS, {"critics": [{"verdict": "clean", "issues": [issue]}]})
                self.assertEqual((payload["result"]["stopReason"], payload["result"]["rounds"]), ("clean", 1), payload)
        verdict = run_script(ARGS, {"critics": [issues(_issue(severity="low", kind="style")), CLEAN]})
        self.assertEqual((verdict["result"]["stopReason"], verdict["result"]["rounds"]), ("clean", 2), verdict)

    def test_decision_points_of_the_ingested_drafts_reach_loop_json(self):
        point = {"id": "DP1", "question": "CSV only?", "options": ["CSV", "CSV and JSON"], "recommendation": "CSV"}
        other = {"id": "DP2", "question": "Header row?", "options": ["yes", "no"], "recommendation": ""}
        broken = {"id": "", "question": "no id", "options": [], "recommendation": "x"}
        first = run_script(ARGS, {"critics": [CLEAN], "points": {"author:spec:r0": [point, broken],
                                                                  "author:plan:r0": [point, other]}})
        self.assertEqual(loop_json(first)["decisionPoints"], [point, other])
        revised = run_script(ARGS, {"critics": [issues(_issue()), CLEAN],
                                    "points": {"author:spec:r0": [point], "author-revise:spec:r1": [other]}})
        self.assertEqual(loop_json(revised)["decisionPoints"], [other])

    def test_role_prompts_name_the_staged_prompt_files(self):
        for package in (POSIX_PKG, WIN_PKG):
            with self.subTest(package=package):
                payload = run_script(dict(ARGS, packageDir=package), {"critics": [issues(_issue()), CLEAN]})
                sep = "\\" if "\\" in package else "/"
                prompts = {c["label"]: c["prompt"] for c in payload["calls"] if not c["label"].startswith("scribe:")}
                expected = {"author:spec:r0": ("author-spec", 0), "author:plan:r0": ("author-plan", 0),
                            "critic:spec+plan:r1": ("critic", 1), "author-revise:spec:r1": ("author-spec", 1),
                            "author-revise:plan:r1": ("author-plan", 1), "critic:spec+plan:r2": ("critic", 2)}
                for label, (role, round_no) in expected.items():
                    path = package + sep + rel("prompt", role, round_no).replace("/", sep)
                    self.assertTrue(prompts[label].startswith('Read "%s" and follow it' % path), prompts[label])
                for call in payload["calls"]:
                    if call["label"].startswith("scribe:write:"):
                        self.assertTrue(call["report"]["path"].startswith(package + sep), call["report"])

    def test_commands_run_the_runner_of_the_plugin_root(self):
        payload = run_script(dict(ARGS, packageDir=WIN_PKG, pluginRoot="C:\\Program Files\\agentic-sdlc",
                                  python="C:\\Python312\\python.exe"), {"critics": [CLEAN]})
        commands = [c["report"]["argv"] for c in payload["calls"] if c["label"] in ("scribe:draft-check:r1",
                                                                                     "scribe:ingest-draft")]
        head = ["C:\\Python312\\python.exe", "-B", "C:\\Program Files\\agentic-sdlc\\scripts\\sdlc.py",
                "--project", "C:\\work\\proj", "--slug", "demo"]
        self.assertEqual(commands, [head + ["draft-check", "--round", "1"], head + ["ingest-draft", "--assemble"]])
        prompt = [c["prompt"] for c in payload["calls"] if c["label"] == "scribe:ingest-draft"][0]
        self.assertIn('Run exactly this runner command: "C:\\Python312\\python.exe" -B '
                      '"C:\\Program Files\\agentic-sdlc\\scripts\\sdlc.py" --project "C:\\work\\proj" --slug demo '
                      'ingest-draft --assemble', prompt)
        self.assertIn('Plugin root (<runtime-root>): "C:\\Program Files\\agentic-sdlc"', prompt)
        for package, project in (("/docs/agentic-sdlc/demo", "/"), ("C:\\docs\\agentic-sdlc\\demo", "C:/"),
                                 ("/work/proj/docs/agentic-sdlc/demo/", "/work/proj")):
            with self.subTest(package=package):
                root = run_script(dict(ARGS, packageDir=package), {"critics": [CLEAN]})
                argv = [c["report"]["argv"] for c in root["calls"] if c["label"] == "scribe:ingest-draft"][0]
                self.assertEqual(argv[3:5], ["--project", project])

    def test_the_scribe_gets_the_exact_text(self):
        body = "# Spec\n\n=====8<===== 0\nline\r\nend\n\n\n"
        payload = run_script(ARGS, {"critics": [CLEAN], "bodies": {"spec": body}})
        self.assertEqual(payload["files"][POSIX_PKG + "/" + rel("spec", None, 0)],
                         "# Spec\n\n=====8<===== 0\nline\nend\n")
        prompt = [c["prompt"] for c in payload["calls"] if c["label"] == "scribe:write:" + rel("spec", None, 0)][0]
        lines = prompt.split("\n")
        markers = [line for line in lines if line.startswith("=====8<===== ")]
        self.assertEqual(markers, ["=====8<===== 1", "=====8<===== 0", "=====8<===== 1"])  # never a line of the text


@unittest.skipIf(NODE is None, NO_NODE)
class TestFailures(unittest.TestCase):
    def assertThrows(self, payload, needle):
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["name"], "Error", payload)
        self.assertIn("spec-plan-draft", payload["message"])
        self.assertIn(needle, payload["message"])

    def test_a_null_agent_throws_a_named_error(self):
        many = [issues(_issue(where="## Task %d" % n)) for n in range(1, 4)]
        for label in ("author:spec:r0", "author:plan:r0", "critic:spec+plan:r1", "author-revise:spec:r1",
                      "critic:spec+plan:r3:final", "scribe:write:draft/spec.r0.md", "scribe:draft-check:r1",
                      "scribe:ingest-draft"):
            with self.subTest(label=label):
                self.assertThrows(run_script(ARGS, {"critics": many, "nullLabel": label}), label)

    def test_a_scribe_refusal_or_failed_check_throws(self):
        self.assertThrows(run_script(ARGS, {"refuse": "scribe:write:draft/plan.r0.md"}), "did not write draft/plan.r0.md")
        self.assertThrows(run_script(ARGS, {"refuse": "scribe:draft-check"}), "did not run draft-check")
        self.assertThrows(run_script(ARGS, {"draftCheckExit": 2}), "draft-check --round 1 exited 2")
        self.assertThrows(run_script(ARGS, {"checkRound": 7}), "draft-check --round 1 printed no result line")

    def test_an_empty_draft_or_two_malformed_critics_throw(self):
        self.assertThrows(run_script(ARGS, {"bodies": {"spec": "  \n"}}), "author:spec:r0 returned an empty draft")
        for bad, why in (({"verdict": "ok", "issues": []}, "verdict"),
                         (issues(dict(_issue(), category="")), "issue category"),
                         (issues(dict(_issue(), whatsMissing="")), "issue whatsMissing"),
                         (issues(dict(_issue(), kind="nit")), "issue kind"),
                         (issues({k: v for k, v in _issue().items() if k != "fix"}), "issue fix")):
            with self.subTest(why=why):
                payload = run_script(ARGS, {"critics": [bad], "retry": bad})
                self.assertThrows(payload, "critic:spec+plan:r1 returned no valid critic object (%s)" % why)
                self.assertEqual(labels(payload)[-2:], ["critic:spec+plan:r1", "critic:spec+plan:r1:retry"])

    def test_a_refused_critic_answer_is_asked_for_once_more(self):
        bad = issues(dict(_issue(), category=""))
        payload = run_script(ARGS, {"critics": [bad], "retry": CLEAN})
        self.assertEqual(payload["result"], {"ingested": True, "stopReason": "clean", "rounds": 1}, payload)
        retry = [c for c in payload["calls"] if c["label"] == "critic:spec+plan:r1:retry"]
        self.assertEqual(len(retry), 1)
        self.assertIn("refused (issue category)", retry[0]["prompt"])
        self.assertEqual(json.loads(payload["files"][POSIX_PKG + "/" + rel("critic", "critic", 1)]), CLEAN)

    def test_a_failed_ingest_reports_not_ingested(self):
        payload = run_script(ARGS, {"critics": [CLEAN], "ingestExit": 4})
        self.assertTrue(payload["ok"], payload)
        result = payload["result"]
        self.assertEqual((result["ingested"], result["stopReason"], result["rounds"]), (False, "clean", 1))
        self.assertIn("loop_json_invalid", result["error"])
        # The exit code decides: a success's `ingested=` line can fall outside the reported tail.
        for code, output, expected in ((0, "...a long next card...\nstate=wait chain=000000000000\n", True),
                                       (4, "ingested=clean\nerror=already_ingested\n", False)):
            with self.subTest(code=code):
                half = run_script(ARGS, {"critics": [CLEAN], "ingestExit": code, "ingestOutput": output})
                self.assertIs(half["result"]["ingested"], expected, half)

    def test_invalid_args_throw_before_any_agent(self):
        bad = [dict(ARGS, slug="Demo"), dict(ARGS, slug="a/../b"), dict(ARGS, slug=""), dict(ARGS, slug=None),
               dict(ARGS, workId=""), dict(ARGS, workId="a..b"), dict(ARGS, mode="full"),
               dict(ARGS, maxRounds=0), dict(ARGS, maxRounds=6), dict(ARGS, maxRounds="3"), dict(ARGS, maxRounds=2.5),
               dict(ARGS, packageDir="docs/agentic-sdlc/demo"), dict(ARGS, packageDir="/work/proj/docs/agentic-sdlc/other"),
               dict(ARGS, packageDir="/work/proj/docs/agentic-sdlc/demo-old"),
               dict(ARGS, packageDir="/work/proj/docs/agentic-sdlc/demo/x"),
               dict(ARGS, pluginRoot="relative"), dict(ARGS, pluginRoot='/x"y'), dict(ARGS, pluginRoot="/x$(id)"),
               dict(ARGS, pluginRoot="/x`id`"), dict(ARGS, pluginRoot="/x\ny"), dict(ARGS, pluginRoot="/x\u201cy"),
               dict(ARGS, pluginRoot="//server/share"), dict(ARGS, python=""), dict(ARGS, python='/usr/bin/python3" -c "1')]
        for args in bad:
            with self.subTest(args=args):
                payload = run_script(args)
                self.assertThrows(payload, "invalid runner args")
                self.assertEqual(payload["calls"], [])
        for args, needle in (({}, "empty/missing `context`"), ("", "non-JSON string"), ("not json", "non-JSON string"),
                             ([1], "args must be an object"), (7, "args must be an object")):
            with self.subTest(args=args):
                payload = run_script(args)
                self.assertThrows(payload, needle)
                self.assertEqual(payload["calls"], [])

    def test_runner_slugs_and_paths_the_shells_keep_literal_pass(self):
        # The resolver's slug rule allows a trailing hyphen; inside double quotes `'`, `&`, `;`,
        # `|`, `<` and `>` are literal in Bash and PowerShell.
        args = dict(ARGS, slug="fix-", workId="fix-", packageDir="C:\\Users\\O'Brien\\R&D app\\docs\\agentic-sdlc\\fix-",
                    pluginRoot="C:\\Users\\O'Brien\\plugins;cache\\agentic-sdlc", python="C:\\Python <3>\\python.exe")
        payload = run_script(args, {"critics": [CLEAN]})
        self.assertTrue(payload["ok"], payload)
        argv = [c["report"]["argv"] for c in payload["calls"] if c["label"] == "scribe:ingest-draft"][0]
        self.assertEqual(argv[:7], ["C:\\Python <3>\\python.exe", "-B",
                                    "C:\\Users\\O'Brien\\plugins;cache\\agentic-sdlc\\scripts\\sdlc.py",
                                    "--project", "C:\\Users\\O'Brien\\R&D app", "--slug", "fix-"])

    def test_args_as_json_string_equal_the_object(self):
        config = {"critics": [issues(_issue()), CLEAN]}
        from_object = run_script(ARGS, config)
        from_string = run_script(json.dumps(ARGS), config)
        self.assertEqual(from_object["result"], from_string["result"])
        self.assertEqual(labels(from_object, scribe=True), labels(from_string, scribe=True))


@unittest.skipIf(NODE is None, NO_NODE)
class TestEngineAgainstTheRunner(LoopCase):
    """The script drives a real package: the runner staged it, the stub scribe writes the files and
    runs scripts/sdlc.py, and the runner ingests what the engine claims only if its files back it."""

    def launch(self, slug="demo"):
        text = self.to_draft(runtime="claude", capabilities="workflow=yes,subagent=yes,team=no", slug=slug)
        launch = card_value(text, "launch")
        self.assertTrue(launch and launch.startswith("Workflow "), text)
        call = json.loads(launch[len("Workflow "):])
        self.assertEqual(call["name"], "agentic-sdlc:spec-plan-draft")
        # The scribe runs this checkout's runner, whose flows are the ones the temp root copied.
        return dict(call["args"], pluginRoot=str(REPO))

    def drive(self, critics, slug="demo"):
        args = self.launch(slug)
        payload = run_script(args, {"real": True, "critics": critics,
                                    "bodies": {"spec": SPEC_BODY, "plan": PLAN_BODY}}, timeout=180)
        self.assertTrue(payload["ok"], payload)
        return payload

    def test_every_prompt_the_engine_names_was_staged(self):
        args = self.launch()
        critics = [issues(_issue(where="## Task %d" % n)) for n in range(1, 4)]
        payload = run_script(args, {"critics": critics})
        self.assertTrue(payload["ok"], payload)
        roles = [c for c in payload["calls"] if not c["label"].startswith("scribe:")]
        self.assertEqual(len(roles), 9, labels(payload))  # 2 authors, then 3 critics and 2 revisions of 2
        for call in roles:
            named = re.search(r'^Read "([^"]+)"', call["prompt"])
            self.assertTrue(named, call["prompt"])
            self.assertTrue(Path(named.group(1)).is_file(), call["label"])

    def test_a_clean_loop_is_ingested(self):
        payload = self.drive([CLEAN])
        self.assertEqual(payload["result"], {"ingested": True, "stopReason": "clean", "rounds": 1})
        loop_state = self.state()["loop"]
        self.assertEqual((loop_state["stop_reason"], loop_state["ingested"], loop_state["engine"]),
                         ("clean", True, "claude-workflow"))
        sidecar = json.loads((self.pkg() / "spec" / "demo.review.json").read_text(encoding="utf-8"))
        self.assertEqual((sidecar["engine"], sidecar["critic"], sidecar["rounds"]), ("claude-workflow", "fresh", 1))
        self.assertTrue((self.pkg() / "plan" / "demo.md").is_file())
        code, text = self.next()
        self.assertNotEqual(card_fields(text).get("step"), "draft", text)

    def test_a_no_progress_loop_is_ingested_with_its_notes(self):
        repeated = issues(_issue(severity="medium"))
        payload = self.drive([repeated, repeated])
        self.assertEqual(payload["result"], {"ingested": True, "stopReason": "no-progress", "rounds": 2})
        sidecar = json.loads((self.pkg() / "spec" / "demo.review.json").read_text(encoding="utf-8"))
        self.assertEqual([n["where"] for n in sidecar["residualCriticNotes"]], ["## Business Rules"])
        self.assertEqual(self.state()["loop"]["stop_reason"], "no-progress")

    def test_a_max_rounds_loop_is_ingested(self):
        critics = [issues(_issue(severity="low", where="## Task %d" % n)) for n in range(1, 4)]
        payload = self.drive(critics)
        self.assertEqual(payload["result"], {"ingested": True, "stopReason": "max-rounds", "rounds": 3})
        self.assertEqual(self.state()["loop"]["rounds"], 3)


if __name__ == "__main__":
    unittest.main()
