"""The runner's stdlib masker stays in line with hooks/secret-patterns.mjs.

scripts/sdlc_runner/mask.py is a Python port of the hook layer's secret patterns, because the runner
must not shell out to Node (scripts/sensitive_redaction.py does). Three layers keep the port honest:

* static pins (no Node needed): the pattern labels, their order, their JS sources and value groups,
  the template-value regexes and the published doc samples equal what the .mjs file declares;
* a shared sample table (tests/fixtures/mask-samples.json): every pattern family masks at least one
  sample, and benign text (git output, a sha, placeholders, a doc sample) comes back unchanged;
* a Node cross-check, skipped when node is absent: Python and `redactSecrets` produce the same
  text for every sample, with labels, for both the BROAD and the HIGH pattern lists.
"""
import gc
import json
import re
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sdlc_runner import mask  # noqa: E402

MJS = REPO / "hooks" / "secret-patterns.mjs"
SAMPLES = REPO / "tests" / "fixtures" / "mask-samples.json"
NODE = shutil.which("node")

# A JS regex literal: /body/flags, where body may hold escapes and classes with a `/` inside.
_JS_LITERAL = r"/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\\\[\n])+/[a-z]*"
_PATTERN_ENTRY = re.compile(r"\{ label: '([^']+)', re: (" + _JS_LITERAL + r")(?:, valueGroup: (\d+))? \}")


def _load_samples():
    data = json.loads(SAMPLES.read_text(encoding="utf-8"))
    secrets = [(s["family"], s["name"], s["prefix"] + "".join(s["masked"]) + s["suffix"], "".join(s["masked"]))
               for s in data["secrets"]]
    benign = [(b["name"], "".join(b["text"])) for b in data["benign"]]
    return secrets, benign


def _long_parts():
    """Per secret sample, its parts of 8+ characters: each must vanish on its own (a glued second token too)."""
    data = json.loads(SAMPLES.read_text(encoding="utf-8"))
    return {s["name"]: [p for p in s["masked"] if len(p) >= 8] for s in data["secrets"]}


def _block(text, start_marker, end_marker="];"):
    start = text.index(start_marker)
    return text[start:text.index(end_marker, start)]


def _mjs_entries(block):
    return [(m.group(1), m.group(2), int(m.group(3)) if m.group(3) else None)
            for m in _PATTERN_ENTRY.finditer(block)]


class TestStaticPins(unittest.TestCase):
    def setUp(self):
        self.mjs = MJS.read_text(encoding="utf-8")

    def test_every_mjs_pattern_family_has_a_python_counterpart_in_order(self):
        high = _mjs_entries(_block(self.mjs, "export const HIGH = ["))
        broad_extra = _mjs_entries(_block(self.mjs, "export const BROAD = ["))
        self.assertGreaterEqual(len(high), 11, "the .mjs parser found too few HIGH entries")
        self.assertGreaterEqual(len(broad_extra), 1)
        expected = high + broad_extra
        got = [(p.label, p.source, p.value_group) for p in mask.PATTERNS]
        self.assertEqual(got, expected)
        self.assertEqual([p.label for p in mask.HIGH], [e[0] for e in high])
        self.assertTrue(all(p.high for p in mask.HIGH))
        self.assertFalse(any(p.high for p in mask.PATTERNS if p.label in {e[0] for e in broad_extra}))

    def test_template_values_match_the_mjs(self):
        block = _block(self.mjs, "const TEMPLATE_VALUE = [")
        expected = re.findall(r"^\s*(" + _JS_LITERAL + r"),", block, flags=re.MULTILINE)
        self.assertGreaterEqual(len(expected), 8)
        self.assertEqual(list(mask.TEMPLATE_VALUE_SOURCES), expected)

    def test_doc_samples_match_the_mjs(self):
        block = _block(self.mjs, "export const DOC_SAMPLES = new Set([", "]);")
        expected = set(re.findall(r"^\s*'([^']+)',", block, flags=re.MULTILINE))
        self.assertEqual(len(expected), 3)
        self.assertEqual(set(mask.DOC_SAMPLES), expected)

    def test_parser_negative_control(self):
        # The extraction must see a changed source, or the pin above proves nothing.
        drifted = self.mjs.replace("AKIA[0-9A-Z]{16}", "AKIA[0-9A-Z]{20}", 1)
        self.assertNotEqual(_mjs_entries(_block(drifted, "export const HIGH = [")),
                            _mjs_entries(_block(self.mjs, "export const HIGH = [")))


class TestSampleTable(unittest.TestCase):
    def setUp(self):
        self.secrets, self.benign = _load_samples()

    def test_every_family_has_a_sample(self):
        self.assertEqual({family for family, *_ in self.secrets}, {p.label for p in mask.PATTERNS})

    def test_secret_samples_are_masked(self):
        long_parts = _long_parts()
        for family, name, text, secret in self.secrets:
            with self.subTest(family=family, name=name):
                out = mask.mask_text(text)
                self.assertNotIn(secret, out)
                for part in long_parts[name]:  # e.g. the second token of a glued pair
                    self.assertNotIn(part, out)
                self.assertIn(mask.MASK, out)
                self.assertNotRegex(out, r"\*\*\*MASKED:")

    def test_benign_samples_are_unchanged(self):
        for name, text in self.benign:
            with self.subTest(name=name):
                self.assertEqual(mask.mask_text(text), text)

    def test_labelled_form_names_the_family(self):
        for family, name, text, _secret in self.secrets:
            with self.subTest(family=family, name=name):
                self.assertIn("***MASKED:" + family + "***", mask.redact_labelled(text))

    def test_high_only_leaves_the_broad_family(self):
        text = [t for f, _n, t, _s in self.secrets if f == "assigned-secret"][0]
        self.assertEqual(mask.mask_text(text, mask.HIGH), text)
        self.assertNotEqual(mask.mask_text(text), text)

    def test_allow_marker_does_not_stop_masking(self):
        _f, _n, text, secret = self.secrets[4]
        out = mask.mask_text(text + "  # agentic-sdlc:allow-secret")
        self.assertNotIn(secret, out)

    def test_none_and_empty(self):
        self.assertEqual(mask.mask_text(None), "")
        self.assertEqual(mask.mask_text(""), "")

    def test_fixture_file_itself_holds_no_secret_shape(self):
        raw = SAMPLES.read_text(encoding="utf-8")
        self.assertEqual(mask.mask_text(raw), raw)


class TestMaskIsLinear(unittest.TestCase):
    """A long line with many prefix hits whose value runs reach its end (a URL-encoded form body).

    The .mjs checks a value's length in O(1) (`run.end - valueStart`); counting UTF-16 units of the
    whole remaining run on every hit made the port quadratic (36 KB: 3 s against 0.03 s). Timed
    like `timeit`, with the collector off (lessons.md 2026-10-17). Measured on the fixed code, a
    16x longer line costs about 17x; the quadratic version costs about 230x.
    """

    def _best(self, text, repeats):
        times = []
        for _ in range(repeats):
            gc.collect()
            gc.disable()
            try:
                started = time.perf_counter()
                mask.mask_text(text)
                times.append(time.perf_counter() - started)
            finally:
                gc.enable()
        return min(times)

    def test_many_prefix_hits_on_one_line_stay_linear(self):
        unit = "pass" + "word="
        small = self._best(unit * 250, 7)
        large = self._best(unit * 4000, 3)
        ratio = large / max(small, 1e-6)
        self.assertLess(ratio, 60, "16x input cost %.0fx time (%.4f s -> %.4f s)" % (ratio, small, large))

    def test_short_astral_values_still_count_utf16_units(self):
        # 3 emoji = 3 code points but 6 UTF-16 units: the .mjs minimum of 6 is met, so it is masked.
        self.assertEqual(mask.mask_text("pass" + "word=\U0001F600\U0001F600\U0001F600"), mask.MASK)
        self.assertEqual(mask.mask_text("pass" + "word=\U0001F600\U0001F600"), "pass" + "word=\U0001F600\U0001F600")


@unittest.skipIf(NODE is None, "node not available")
class TestNodeCrossCheck(unittest.TestCase):
    def _node_redact(self, texts):
        src = (
            "let c='';process.stdin.setEncoding('utf8');"
            "process.stdin.on('data',d=>c+=d).on('end',()=>"
            "import('./hooks/secret-patterns.mjs').then(m=>{"
            "const t=JSON.parse(c);"
            "process.stdout.write(JSON.stringify({"
            "broad:t.map(x=>m.redactSecrets(x,m.BROAD)),"
            "high:t.map(x=>m.redactSecrets(x)),"
            "scan:m.scanLines(t.join('\\n'),m.BROAD).length}));"
            "}).catch(e=>{process.stderr.write(String(e&&e.message||e));process.exit(3)}))"
        )
        proc = subprocess.run([NODE, "-e", src], input=json.dumps(texts), cwd=str(REPO),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_python_equals_node_redact_secrets(self):
        secrets, benign = _load_samples()
        texts = [t for _f, _n, t, _s in secrets] + [t for _n, t in benign]
        extra = [
            "two on one line: " + "".join(["gh", "p_R8kLq2Wv9XmT4zNp7Hs3Jd6Fb1Yc5Ge0Ua8K"]) + " and "
            + "".join(["sk", "_live_Vb3Nm8Qz2Wx7Lp4Kt9Rc"]),
            "pass" + "word=<your-password>; pass" + "word=Hq7mK2pWz9",
            "{\"tok" + "en\": \"" + "".join(["gh", "p_R8kLq2Wv9XmT4zNp7Hs3Jd6Fb1Yc5Ge0Ua8K"]) + " extra\"}",
            "emoji value pass" + "word=\U0001F600\U0001F600\U0001F600 tail",
            "nbsp ends a value in JS: pass" + "word=Hq7 mK2pWz9",
            "nbsp after the separator: pass" + "word= Hq7mK2pWz9",
            # JS without the u flag folds case and finds \b in ASCII only.
            "kelvin sign: Bear" + "er Hn4Kq8Zw2Lx7Vt3Rp9MK",
            "cafébear" + "er Hn4Kq8Zw2Lx7Vt3Rp9Mc6Bd",
            # Many prefix hits sharing one value run (the linear-time path of the value match).
            ("pass" + "word=") * 40,
            ("pass" + "word=") * 3 + "\U0001F600\U0001F600 " + ("pass" + "word=") * 2 + "\U0001F600" * 3,
        ]
        texts += extra
        node = self._node_redact(texts)
        for i, text in enumerate(texts):
            with self.subTest(i=i):
                self.assertEqual(mask.redact_labelled(text), node["broad"][i])
                self.assertEqual(mask.redact_labelled(text, mask.HIGH), node["high"][i])
                self.assertEqual(mask.mask_text(text), re.sub(r"\*\*\*MASKED:[a-z0-9-]+\*\*\*", mask.MASK,
                                                              node["broad"][i]))

    def test_node_scanner_sees_nothing_in_the_fixture(self):
        node = self._node_redact([SAMPLES.read_text(encoding="utf-8")])
        self.assertEqual(node["scan"], 0)
        self.assertEqual(node["broad"][0], SAMPLES.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
