"""Helpers the skills tell the model to run must import on the documented Python floor (3.8).

They run in the user's environment, not CI's: stock macOS ships Python 3.9 with the Xcode command
line tools, and many Linux LTS images still carry 3.8. CI runs only 3.12, so nothing there notices a
3.10+ construct. Two checks are static because no older interpreter is available to the gate:

* the source parses with the 3.8 grammar (`ast.parse(..., feature_version=(3, 8))`), which rejects
  `match`, parenthesized context managers and other newer syntax;
* a PEP 604 `X | None` annotation is evaluated when its `def` runs on 3.8/3.9 and raises TypeError at
  import, so any file using one must defer annotations with `from __future__ import annotations`.
"""
import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FLOOR = (3, 8)
# Run by skills, hooks or users in their own projects (not maintainer-only eval tooling).
USER_FACING = (
    "scripts/validate_artifacts.py",
    "scripts/resolve_work_package.py",
    "scripts/detect_context.py",
    "scripts/install_git_hooks.py",
    "scripts/check_codex_hook_trust.py",
    "scripts/strict_flow_evidence.py",
    "scripts/check_plugin_portability.py",
    "scripts/check_cursor_plugin.py",
    "scripts/install_cursor_plugin.py",
    # The Cursor installer imports the release exclusion rules, which import the path-safety helper.
    "scripts/build_release.py",
    "scripts/eval_safety.py",
    "skills/skill-authoring/scripts/resolve_skill_creator.py",
    # The sdlc runner (python3 <root>/scripts/sdlc.py) runs in the user's project.
    "scripts/sdlc.py",
    "scripts/sdlc_runner/__init__.py",
    "scripts/sdlc_runner/textio.py",
    "scripts/sdlc_runner/paths.py",
    "scripts/sdlc_runner/lock.py",
    "scripts/sdlc_runner/logs.py",
    "scripts/sdlc_runner/frontmatter.py",
    "scripts/sdlc_runner/schema.py",
    "scripts/sdlc_runner/mask.py",
    "scripts/sdlc_runner/gitinfo.py",
    "scripts/sdlc_runner/fingerprint.py",
    "scripts/sdlc_runner/probes.py",
    "scripts/sdlc_runner/manifest.py",
    "scripts/sdlc_runner/runexec.py",
    "scripts/sdlc_runner/state.py",
    "scripts/sdlc_runner/checks.py",
    "scripts/sdlc_runner/engine.py",
    "scripts/sdlc_runner/card.py",
    "scripts/sdlc_runner/speccheck.py",
    "scripts/sdlc_runner/cli.py",
    "scripts/sdlc_runner/flowops.py",
    "scripts/sdlc_runner/strategy.py",
    "scripts/sdlc_runner/gates.py",
    "scripts/sdlc_runner/loop.py",
)


def _annotations(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                yield node.returns
            args = node.args
            for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
                if arg is not None and arg.annotation is not None:
                    yield arg.annotation
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


def _uses_pep604(annotation):
    return any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for n in ast.walk(annotation))


def _defers_annotations(tree):
    return any(isinstance(n, ast.ImportFrom) and n.module == "__future__"
               and any(a.name == "annotations" for a in n.names) for n in tree.body)


# Methods added in Python 3.9 (str/bytes.removeprefix and removesuffix, PurePath.is_relative_to).
# The grammar check cannot see them: the call parses on 3.8 and raises AttributeError when it runs.
NEWER_METHODS = frozenset({"removeprefix", "removesuffix", "is_relative_to"})


def _newer_method_calls(tree):
    return sorted({(node.lineno, node.func.attr) for node in ast.walk(tree)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in NEWER_METHODS})


# `Path.write_text(..., newline=...)` is Python 3.10+: on the floor the call parses and raises
# TypeError when it runs (the git-hook installer's `--install` did, R1-e Task 5).
def _write_text_newline_calls(tree):
    return sorted(node.lineno for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr == "write_text"
                  and any(kw.arg == "newline" for kw in node.keywords))


class TestHelperPythonFloor(unittest.TestCase):
    def test_user_facing_helpers_parse_with_the_floor_grammar(self):
        for rel in USER_FACING:
            with self.subTest(helper=rel):
                source = (REPO / rel).read_text(encoding="utf-8")
                ast.parse(source, filename=rel, feature_version=FLOOR)

    def test_pep604_annotations_are_deferred(self):
        for rel in USER_FACING:
            with self.subTest(helper=rel):
                tree = ast.parse((REPO / rel).read_text(encoding="utf-8"), filename=rel)
                if any(_uses_pep604(a) for a in _annotations(tree)):
                    self.assertTrue(_defers_annotations(tree),
                                    rel + " evaluates `X | Y` annotations at import; add "
                                    "`from __future__ import annotations`")

    def test_rl6_floor_helpers_call_no_python39_methods(self):
        for rel in USER_FACING:
            with self.subTest(helper=rel):
                tree = ast.parse((REPO / rel).read_text(encoding="utf-8"), filename=rel)
                self.assertEqual(_newer_method_calls(tree), [],
                                 rel + " calls a 3.9+ method that raises AttributeError on 3.8")

    def test_rl6_the_method_check_fires(self):
        # Negative control: each method the floor forbids is seen as a call, an attribute name alone is not.
        tree = ast.parse("a = p.removeprefix('./')\nb = s.removesuffix('\\r')\nc = x.is_relative_to(y)\n"
                         "d = getattr(s, 'removeprefix', None)\n")
        self.assertEqual(_newer_method_calls(tree), [(1, "removeprefix"), (2, "removesuffix"), (3, "is_relative_to")])

    def test_no_user_facing_helper_passes_newline_to_write_text(self):
        for rel in USER_FACING:
            with self.subTest(helper=rel):
                tree = ast.parse((REPO / rel).read_text(encoding="utf-8"), filename=rel)
                self.assertEqual(_write_text_newline_calls(tree), [],
                                 rel + " passes newline= to Path.write_text, which needs Python 3.10")

    def test_the_write_text_newline_check_fires(self):
        # Negative control: the keyword is seen; a plain write_text and an open(newline=) are not.
        tree = ast.parse("p.write_text(s, encoding='utf-8', newline='\\n')\np.write_text(s)\n"
                         "open(f, 'w', newline='\\n')\n")
        self.assertEqual(_write_text_newline_calls(tree), [1])

    def test_the_check_fires_on_an_undeferred_union(self):
        # Negative control: the detector must see the construct that broke 3.9 imports.
        tree = ast.parse("def f(x: str | None = None) -> int | None:\n    return None\n")
        self.assertTrue(any(_uses_pep604(a) for a in _annotations(tree)))
        self.assertFalse(_defers_annotations(tree))
        with self.assertRaises(SyntaxError):
            ast.parse("match x:\n    case 1:\n        pass\n", feature_version=FLOOR)


if __name__ == "__main__":
    unittest.main()
