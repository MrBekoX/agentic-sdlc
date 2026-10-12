"""multi-lens-review: a missing agent answer must never read as a clean or confirmed review.

The workflow fans one finder out per lens and then skeptics out per finding. Two silent failures
used to hide a missing answer:
- a finder that returned null became an empty list, so "every lens failed" was reported exactly
  like "every lens looked and found nothing";
- a finding whose skeptics all returned null had zero votes and fell through to `confirmed`.

The workflow body is run under the same runtime wrapper test_static_node uses, with stubbed
`agent` / `parallel` / `phase` / `log` globals.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_static_node import WORKFLOWS_DIR, _runtime_wrap

NODE = shutil.which("node")

DRIVER = """
const ARGS = %(args)s;
const SCENARIO = %(scenario)s;
const calls = [];
async function stubAgent(prompt, opts) {
  const label = (opts && opts.label) || '';
  calls.push(label);
  const parts = label.split(':');
  if (parts[0] === 'find') {
    const mode = SCENARIO.find[parts[1]] || SCENARIO.find['*'] || 'none';
    if (mode === 'null') return null;
    if (mode === 'one') return { findings: [{ title: parts[1] + '-issue', severity: 'high', location: 'a.js:1', evidence: 'e' }] };
    return { findings: [] };
  }
  const index = Number(parts[2]);
  const mode = SCENARIO.verify;
  if (mode === 'null') return null;
  if ((mode === 'first-only' || mode === 'first-refute-only') && index > 0) return null;
  if (mode === 'first-refute-only') return { refuted: true, reason: 'false positive' };
  if (mode === 'refute') return { refuted: true, reason: 'false positive' };
  return { refuted: false, reason: 'holds' };
}
const parallel = (thunks) => Promise.all(thunks.map((t) => Promise.resolve().then(t).catch(() => null)));
__wf(ARGS, stubAgent, parallel, null, () => {}, () => {}, null, null)
  .then((result) => process.stdout.write(JSON.stringify({ ok: true, result, calls }) + '\\n'))
  .catch((err) => process.stdout.write(JSON.stringify({
    ok: false, name: err && err.name ? err.name : 'Error', message: String(err && err.message ? err.message : err), calls,
  }) + '\\n'));
"""


def run_review(scenario, args=None):
    if NODE is None:
        raise unittest.SkipTest("node not available - static JS check skipped (not passed)")
    src = (WORKFLOWS_DIR / "multi-lens-review.js").read_text(encoding="utf-8")
    body = _runtime_wrap(src) + DRIVER % {
        "args": json.dumps(args or {"preset": "security", "scope": "diff --git a/x b/x", "verifyVotes": 3}),
        "scenario": json.dumps(scenario),
    }
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as handle:
        handle.write(body)
        path = Path(handle.name)
    try:
        proc = subprocess.run([NODE, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=20)
    finally:
        path.unlink(missing_ok=True)
    lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    if not lines:
        raise AssertionError(f"no JSON output (rc={proc.returncode}):\n{proc.stderr}")
    return json.loads(lines[-1])


@unittest.skipIf(NODE is None, "node not available - static JS check skipped (not passed)")
class TestMultiLensReviewMissingAnswers(unittest.TestCase):
    LENSES = ("injection", "authz-IDOR", "secrets", "auth")

    def test_every_finder_missing_is_an_error_not_a_clean_review(self):
        payload = run_review({"find": {"*": "null"}, "verify": "keep"})
        self.assertFalse(payload["ok"], f"all finders returned null yet the review reported: {payload}")
        self.assertEqual(payload["name"], "Error")
        self.assertIn("multi-lens-review", payload["message"])

    def test_a_missing_finder_marks_the_review_incomplete(self):
        payload = run_review({"find": {"injection": "null", "*": "one"}, "verify": "keep"})
        self.assertTrue(payload["ok"], payload)
        result = payload["result"]
        self.assertIs(result["complete"], False)
        self.assertEqual(result["incompleteLenses"], ["injection"])
        self.assertEqual(result["findingCount"], 3, "the lenses that did answer must still report")

    def test_a_missing_finder_is_incomplete_even_when_the_others_find_nothing(self):
        payload = run_review({"find": {"injection": "null", "*": "none"}, "verify": "keep"})
        self.assertTrue(payload["ok"], payload)
        result = payload["result"]
        self.assertIs(result["complete"], False)
        self.assertEqual(result["incompleteLenses"], ["injection"])
        self.assertEqual(result["findingCount"], 0)

    def test_a_genuinely_clean_review_is_complete(self):
        payload = run_review({"find": {"*": "none"}, "verify": "keep"})
        self.assertTrue(payload["ok"], payload)
        result = payload["result"]
        self.assertIs(result["complete"], True)
        self.assertEqual(result["incompleteLenses"], [])
        self.assertEqual((result["findingCount"], result["confirmed"], result["unverified"]), (0, [], []))

    def test_a_finding_no_verifier_answered_is_unverified_not_confirmed(self):
        payload = run_review({"find": {"injection": "one", "*": "none"}, "verify": "null"})
        self.assertTrue(payload["ok"], payload)
        result = payload["result"]
        self.assertEqual(result["confirmed"], [], f"a finding with zero verifier answers was confirmed: {result}")
        self.assertEqual([u["title"] for u in result["unverified"]], ["injection-issue"])
        self.assertIn("no verifier", result["unverified"][0]["reason"])
        self.assertIs(result["complete"], False, "an unverified finding means the review is not complete")

    def test_verification_by_a_subset_of_skeptics_is_visible(self):
        payload = run_review({"find": {"injection": "one", "*": "none"}, "verify": "first-only"})
        self.assertTrue(payload["ok"], payload)
        confirmed = payload["result"]["confirmed"]
        self.assertEqual(len(confirmed), 1)
        self.assertEqual((confirmed[0]["votes"], confirmed[0]["requestedVotes"]), (1, 3))
        self.assertIs(payload["result"]["complete"], False, "a finding judged by fewer skeptics than asked")

    def test_one_refute_among_silent_skeptics_neither_drops_nor_confirms(self):
        # 3 requested, 1 answered and refuted it, 2 silent: a missing answer must not decide the verdict.
        payload = run_review({"find": {"injection": "one", "*": "none"}, "verify": "first-refute-only"})
        self.assertTrue(payload["ok"], payload)
        result = payload["result"]
        self.assertEqual(result["dropped"], [], f"a minority of the requested skeptics dropped a finding: {result}")
        self.assertEqual(result["confirmed"], [])
        self.assertEqual([u["title"] for u in result["unverified"]], ["injection-issue"])
        self.assertIn("1 of 1 answering skeptics refuted it, 3 requested", result["unverified"][0]["reason"])
        self.assertIs(result["complete"], False)

    def test_a_majority_of_the_requested_skeptics_still_drops_a_finding(self):
        # CONTROL: all three answered and refuted -> dropped, exactly as before.
        payload = run_review({"find": {"injection": "one", "*": "none"}, "verify": "refute"})
        self.assertEqual([d["title"] for d in payload["result"]["dropped"]], ["injection-issue"])

    def test_control_confirmed_and_dropped_behaviour_is_unchanged(self):
        kept = run_review({"find": {"injection": "one", "*": "none"}, "verify": "keep"})["result"]
        self.assertEqual([f["title"] for f in kept["confirmed"]], ["injection-issue"])
        self.assertEqual((kept["dropped"], kept["unverified"]), ([], []))
        self.assertIs(kept["complete"], True)
        dropped = run_review({"find": {"injection": "one", "*": "none"}, "verify": "refute"})["result"]
        self.assertEqual(dropped["confirmed"], [])
        self.assertEqual([d["title"] for d in dropped["dropped"]], ["injection-issue"])
        self.assertIs(dropped["complete"], True)

    def test_the_verify_cap_still_reports_lower_severity_findings_as_unverified(self):
        payload = run_review({"find": {"*": "one"}, "verify": "keep"},
                             {"preset": "security", "scope": "s", "verifyVotes": 1, "maxVerify": 1})
        self.assertTrue(payload["ok"], payload)
        result = payload["result"]
        self.assertEqual(len(result["confirmed"]), 1)
        self.assertEqual(len(result["unverified"]), 3)
        self.assertTrue(all("cap" in u["reason"] for u in result["unverified"]), result["unverified"])
        self.assertIs(result["complete"], False, "findings left unverified mean the review is not complete")


if __name__ == "__main__":
    unittest.main()
