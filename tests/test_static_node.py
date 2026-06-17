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
    """Return (returncode, stderr) from `node --check <path>`."""
    proc = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True)
    return proc.returncode, proc.stderr


@unittest.skipIf(NODE is None, "node not available — static JS check skipped (not passed)")
class TestHookSyntax(unittest.TestCase):
    def test_every_hook_mjs_parses(self):
        mjs = sorted(HOOKS_DIR.glob("*.mjs"))
        self.assertGreaterEqual(len(mjs), 1, "no hook .mjs files found")
        for p in mjs:
            rc, err = _node_check(p)
            self.assertEqual(rc, 0, f"{p.name} failed node --check:\n{err}")


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


if __name__ == "__main__":
    unittest.main()
