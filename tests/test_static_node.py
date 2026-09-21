"""Static Node syntax check for hook + workflow scripts (test matrix E / F, static slice).

`node --check` parses without executing, so undefined runtime globals (args, agent) and
unresolved imports don't matter — only syntax is validated.

- Hook files are .mjs (always ESM) and are checked directly.
- Workflow files are .js but the Workflow runtime strips `export const meta` and runs the
  REST inside an async function wrapper — which is why they legitimately use top-level
  `return`/`await` (illegal in a bare module). To syntax-check the body the way it actually
  runs, we de-export `meta` and wrap the source in `async function(){ ... }`, then run
  `node --check`. A genuine syntax error in the body still surfaces; the wrapper only makes
  the runtime's top-level await/return legal.

If `node` is unavailable the tests SKIP (reported as skipped, never counted as passed) —
the same honesty rule the live trigger eval follows for a missing `claude` CLI.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
HOOKS_DIR = REPO / "hooks"
WORKFLOWS_DIR = REPO / "workflows"
NODE = shutil.which("node")


def _node_check(path):
    """Return (returncode, stderr) from `node --check <path>`.

    Raises `SkipTest` when no interpreter is available. The class decorators below skip without
    paying a subprocess, but the guarantee belongs HERE: a class added later that forgets the
    decorator degrades to the skip this file's docstring promises instead of raising TypeError
    on `[None, "--check", ...]` and turning a missing interpreter into a red gate.
    """
    if NODE is None:
        raise unittest.SkipTest("node not available - static JS check skipped (not passed)")
    proc = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, proc.stderr


@unittest.skipIf(NODE is None, "node not available — static JS check skipped (not passed)")
class TestHookSyntax(unittest.TestCase):
    def test_every_hook_mjs_parses(self):
        mjs = sorted(HOOKS_DIR.glob("*.mjs"))
        self.assertGreaterEqual(len(mjs), 1, "no hook .mjs files found")
        for p in mjs:
            rc, err = _node_check(p)
            self.assertEqual(rc, 0, f"{p.name} failed node --check:\n{err}")


# NOT decorated: this class only reads bytes. It was skipped when `node` was missing, which
# lost real coverage for a reason that does not apply to it.
class TestHookSourcesAreText(unittest.TestCase):
    """A hook source must stay TEXT, or git stores it as a binary blob and its diffs become
    unreviewable — the worst possible property for a security guard.

    This fired for real: `worktree-scan.mjs` used a raw NUL byte as a hash-key separator, so
    `git diff` reported `Bin 0 -> 7566 bytes` and the whole file was invisible in review. Write
    control characters as escape sequences (`'\\u0000'`), never as raw bytes.
    """

    def test_no_control_bytes_in_hook_or_workflow_sources(self):
        for path in sorted(HOOKS_DIR.glob("*.mjs")) + sorted(WORKFLOWS_DIR.glob("*.js")):
            with self.subTest(file=path.name):
                raw = path.read_bytes()
                bad = sorted({b for b in raw if b < 9 or 13 < b < 32})
                self.assertEqual(
                    bad, [],
                    f"{path.name} carries raw control byte(s) {bad}; git will treat it as binary "
                    "and its diffs will not be reviewable. Use an escape sequence instead.",
                )


@unittest.skipIf(NODE is None, "node not available — static JS check skipped (not passed)")
class TestWorkflowSyntax(unittest.TestCase):
    def test_every_workflow_js_parses_in_runtime_wrapper(self):
        js = sorted(WORKFLOWS_DIR.glob("*.js"))
        self.assertGreaterEqual(len(js), 1, "no workflow .js files found")
        for p in js:
            src = p.read_text(encoding="utf-8")
            # Mirror the Workflow runtime: de-export meta, wrap the body in an async fn so
            # the script's top-level await/return are legal.
            src = src.replace("export const meta", "const meta", 1)
            wrapped = (
                "async function __wf(args, agent, parallel, pipeline, log, phase, "
                "budget, workflow) {\n" + src + "\n}\n"
            )
            with tempfile.NamedTemporaryFile(
                "w", suffix=".mjs", delete=False, encoding="utf-8"
            ) as tf:
                tf.write(wrapped)
                tmp = Path(tf.name)
            try:
                rc, err = _node_check(tmp)
                self.assertEqual(rc, 0, f"{p.name} failed node --check (runtime wrapper):\n{err}")
            finally:
                tmp.unlink(missing_ok=True)


class TestWorkflowUntrustedFencing(unittest.TestCase):
    """Workflows interpolate caller-supplied scope/context into sub-agent prompts. That untrusted
    text must be wrapped in a delimited DATA block (prompt-injection hardening), not concatenated
    raw, so a malicious file under review cannot smuggle instructions into a sub-agent."""

    def _src(self, name):
        return (WORKFLOWS_DIR / name).read_text(encoding="utf-8")

    def test_all_three_fence_untrusted_input(self):
        for name in ["multi-lens-review.js", "spec-plan-draft.js", "skill-draft.js"]:
            with self.subTest(workflow=name):
                src = self._src(name)
                self.assertIn("fenceUntrusted", src, f"{name}: fence helper missing")
                self.assertIn("[UNTRUSTED", src, f"{name}: untrusted-data delimiter missing")

    def test_raw_context_interpolation_removed(self):
        for name in ["spec-plan-draft.js", "skill-draft.js"]:
            with self.subTest(workflow=name):
                self.assertNotIn("Context: ${ctxStr}", self._src(name), f"{name}: raw ctx interpolation remains")


class TestMissingNodeIsASkipNotAnError(unittest.TestCase):
    """The docstring above, docs/testing.md:42, :100 and :585 all promise the same thing: with
    no `node` on PATH these checks SKIP, reported as skipped and never counted as passed.

    They did not. `TestWorkflowSyntax` carried no skip decorator and calls `_node_check`, which
    ran `subprocess.run([NODE, ...])`; with `NODE is None` that raises `TypeError`, so a
    missing interpreter turned a promised skip into a red gate. A decorator on every class is
    not enough on its own - the next class added can forget it - so the guarantee lives in the
    helper, where forgetting is impossible.
    """

    def test_node_check_skips_when_no_interpreter_is_available(self):
        import test_static_node as module

        original = module.NODE
        module.NODE = None
        try:
            with self.assertRaises(unittest.SkipTest):
                module._node_check(Path(__file__))
        finally:
            module.NODE = original
        self.assertEqual(module.NODE, original, "the probe must restore the module state")


if __name__ == "__main__":
    unittest.main()
