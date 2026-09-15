import re
import unittest
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def script_inventory_violations(readme_text, plugin_readme_text, names):
    violations = []
    readme_counts = re.findall(r"(\d+) Python helpers", readme_text)
    if not readme_counts:
        violations.append("missing_readme_count")
    elif len(readme_counts) > 1:
        violations.append("ambiguous_readme_count")
    elif int(readme_counts[0]) != len(names):
        violations.append("readme_count_mismatch")
    plugin_counts = re.findall(r"Deterministic scripts \((\d+)\)", plugin_readme_text)
    if len(plugin_counts) != 1 or int(plugin_counts[0]) != len(names):
        violations.append("plugin_readme_count_mismatch")
    for name in names:
        if f"`{name}`" not in plugin_readme_text:
            violations.append(f"helper_not_listed:{name}")
    return violations

# The `!` lines of .gitignore at 5801cb9, in file order. Kept literal: CI's depth-1
# checkout and the extracted-archive gate have no history to read them from.
BASELINE_GITIGNORE_NEGATIONS = (
    "!.env.example",
    "!docs/plugin-readme.md",
    "!docs/claude-code-runtime.md",
    "!docs/testing.md",
    "!docs/troubleshooting.md",
    "!docs/skill-boundaries.md",
    "!docs/runtime-adapter.md",
    "!docs/release-readiness.md",
    "!docs/release-evidence-0.4.3.md",
    "!docs/agentic-sdlc/",
    "!docs/agentic-sdlc/evidence/",
    "!docs/agentic-sdlc/evidence/codex-live-low-strict-2026-06-20.md",
)


# Each docs/data-handling.md statement below is bound to the source text that implements it:
# (fragment of the doc sentence, cited source path with an optional :line, source fragment).
_FLOW_VALIDATOR_HOOKS = ("hooks/flow-evidence.mjs", "hooks/codex-flow-evidence.mjs", "hooks/flow-order-guard-codex.mjs")
DATA_HANDLING_FACTS = (
    *[
        (doc, hook, src)
        for hook in _FLOW_VALIDATOR_HOOKS
        for doc, src in (
            ("run `scripts/validate_artifacts.py` on it", "'validate_artifacts.py'"),
            ("try the interpreter named by the `AGENTIC_SDLC_PYTHON` environment variable first", "process.env.AGENTIC_SDLC_PYTHON"),
            ("then `python3`, `python` and, on Windows, `py -3` from `PATH`", "['py', '-3']"),
            ("Each attempt has a 10-second timeout.", "timeout: 10000"),
        )
    ],
    ("`hooks/flow-evidence.mjs` and `hooks/codex-flow-evidence.mjs` list the directory entries", "hooks/flow-evidence.mjs", "readdirSync(join(cwd, pp.base))"),
    ("`hooks/flow-evidence.mjs` and `hooks/codex-flow-evidence.mjs` list the directory entries", "hooks/codex-flow-evidence.mjs", "readdirSync(join(cwd, pp.base))"),
    ("`docs/agentic-sdlc/specs`, `docs/agentic-sdlc/plans`", "hooks/flow-requirements.json", '"spec": "docs/agentic-sdlc/specs"'),
    ("`docs/agentic-sdlc/specs`, `docs/agentic-sdlc/plans`", "hooks/flow-requirements.json", '"plan": "docs/agentic-sdlc/plans"'),
    ("the `spec` and `plan` folders of each work package under `docs/agentic-sdlc`", "hooks/flow-requirements.json", '"base": "docs/agentic-sdlc"'),
    ("the `spec` and `plan` folders of each work package under `docs/agentic-sdlc`", "hooks/flow-requirements.json", '"subdirs": { "spec": "spec", "plan": "plan" }'),
    ("write a transcript file only when `--transcript-dir` is given", "scripts/run_trigger_eval.py", '"--transcript-dir", default=None'),
    ("write a transcript file only when `--transcript-dir` is given", "scripts/run_trigger_eval.py", "if transcript_dir:"),
    *[
        ("write a transcript file only when `--transcript-dir` is given", runner, frag)
        for runner in ("scripts/run_codex_trigger_eval.py", "scripts/run_routing_eval.py", "scripts/run_glm_trigger_eval.py")
        for frag in ('"--transcript-dir", type=Path)', "if args.transcript_dir:")
    ],
    ("`scripts/run_all_trigger_evals.py:22` sets the default `--transcript-dir`", "scripts/run_all_trigger_evals.py:22", '"tests" / "artifacts" / "trigger-matrix"'),
    ("to the Claude and Codex trigger runners", "scripts/run_all_trigger_evals.py", 'str(args.transcript_dir / "claude" / skill_name)'),
    ("to the Claude and Codex trigger runners", "scripts/run_all_trigger_evals.py", 'str(args.transcript_dir / "codex" / skill_name)'),
    ("otherwise into a `transcripts` folder inside the temporary directory it creates for the run", "scripts/run_procedure_eval.py", 'else (tmp_root / "transcripts")'),
    ("otherwise into a `transcripts` folder inside the temporary directory it creates for the run", "scripts/run_procedure_eval.py", "tempfile.TemporaryDirectory("),
    ("Python removes that temporary directory when the run ends", "scripts/run_procedure_eval.py", 'with tempfile.TemporaryDirectory(prefix="agentic-sdlc-procedure-", ignore_cleanup_errors=True) as td:'),
    ("a file it cannot delete is left in place", "scripts/run_procedure_eval.py", "ignore_cleanup_errors=True"),
    ("read Git alias definitions through `hooks/git-invocation.mjs`", "hooks/git-invocation.mjs", "'config', '--get', 'alias.' + name"),
    ("read Git alias definitions through `hooks/git-invocation.mjs`", "hooks/branch-guard.mjs", "from './git-invocation.mjs'"),
    ("read Git alias definitions through `hooks/git-invocation.mjs`", "hooks/scan-commit.mjs", "from './git-invocation.mjs'"),
    ("`hooks/branch-guard.mjs` runs `git` to read the current branch", "hooks/branch-guard.mjs", "'branch', '--show-current'"),
    ("`hooks/scan-commit.mjs` runs `git diff` to read the added diff lines of a commit", "hooks/scan-commit.mjs", "gitDiff(['diff', '--cached', '--unified=0'], cwd)"),
    ("takes the commit message from the `-m` text in the command", "hooks/scan-commit.mjs", "...commitMessages(text),"),
    ("reads the contents of any file named by `-F` or `--file`", "hooks/git-invocation.mjs", "if (a === '-F' || a === '--file')"),
    ("reads the contents of any file named by `-F` or `--file`", "hooks/scan-commit.mjs", "commitMessageFiles(text).map((f) =>"),
    ("resolved against the working directory of the statement that names it", "hooks/scan-commit.mjs", "readFileSync(resolvePath(cwd, f), 'utf8')"),
    ("reads the new text from the tool input (`new_string`, `edits[].new_string` or `content`)", "hooks/scan-write.mjs", "typeof ti.new_string === 'string'"),
    ("reads the new text from the tool input (`new_string`, `edits[].new_string` or `content`)", "hooks/scan-write.mjs", "ti.edits.map((e) => e?.new_string || '')"),
    ("reads the new text from the tool input (`new_string`, `edits[].new_string` or `content`)", "hooks/scan-write.mjs", "typeof ti.content === 'string'"),
    ("it reads the file named by `tool_input.file_path`", "hooks/scan-write.mjs", "String(ti.file_path || '')"),
    ("it reads the file named by `tool_input.file_path`", "hooks/scan-write.mjs", "readFileSync(file, 'utf8')"),
    ("runs `git` to read the added lines of `git diff HEAD` for tracked changes", "hooks/worktree-scan.mjs", "git(['diff', 'HEAD', '--unified=0'])"),
    ("and to list untracked files, gitignored files included", "hooks/worktree-scan.mjs", "'--others', '--ignored', '--exclude-standard'"),
    ("It reads the bytes of those untracked files", "hooks/worktree-scan.mjs", "readFileSync(resolvePath(root, rel))"),
    ("It skips vendor and tool-state directories, such as `node_modules` and `.claude`", "hooks/worktree-scan.mjs", "filter((rel) => !VENDOR_DIR.test(rel))"),
    ("It skips vendor and tool-state directories, such as `node_modules` and `.claude`", "hooks/worktree-scan.mjs", "(?:node_modules|"),
    ("It skips vendor and tool-state directories, such as `node_modules` and `.claude`", "hooks/worktree-scan.mjs", "|\\.claude|"),
    ("caps the scan at 200 files, 256 KiB per file and 4 MiB in total", "hooks/worktree-scan.mjs", "MAX_UNTRACKED_FILES = 200;"),
    ("caps the scan at 200 files, 256 KiB per file and 4 MiB in total", "hooks/worktree-scan.mjs", "MAX_FILE_BYTES = 256 * 1024;"),
    ("caps the scan at 200 files, 256 KiB per file and 4 MiB in total", "hooks/worktree-scan.mjs", "MAX_TOTAL_BYTES = 4 * 1024 * 1024;"),
    ("binary files and files over the per-file cap are skipped", "hooks/worktree-scan.mjs", "if (buf.includes(0)) continue;"),
    ("binary files and files over the per-file cap are skipped", "hooks/worktree-scan.mjs", "if (buf.length > MAX_FILE_BYTES) continue;"),
    ("It also flags changed or untracked files whose names mark them as credential files", "hooks/worktree-scan.mjs", "{ what: 'credential file', where: rel }"),
    ("a SHA-256 digest over a finding's pattern label and its location", "hooks/worktree-scan.mjs", "update(f.what + '\\u0000' + f.where)"),
    ("for a finding in the tracked diff, the literal `uncommitted change`", "hooks/worktree-scan.mjs", "where: 'uncommitted change'"),
    ("writes a review package into `--out-dir` when it is given", "scripts/review_package.py", "args.out_dir or default_out_dir()"),
    ("otherwise into the Git `sdd` path (`git rev-parse --git-path sdd`)", "scripts/review_package.py", '"rev-parse", "--git-path", "sdd"'),
    ("or `.sdd` when that Git command fails or prints nothing", "scripts/review_package.py", 'return Path(".sdd")'),
    ("otherwise into a `.handoffs` folder beside the plan file", "scripts/task_brief.py", 'args.out_dir or plan.parent / ".handoffs"'),
)


def _require_git_checkout(testcase):
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0 or Path(proc.stdout.strip()).resolve() != REPO.resolve():
        testcase.skipTest("not a git checkout of this tree: ignore rules need git")


class TestReleaseReadinessDocs(unittest.TestCase):
    def test_gitignore_newly_unignores_only_publication_paths(self):
        _require_git_checkout(self)

        def check_ignore_exit(rel):
            return subprocess.run(
                ["git", "check-ignore", "--no-index", "-q", rel], cwd=REPO, capture_output=True
            ).returncode

        for rel in (
            "docs/data-handling.md",
            "docs/publication/claude-community.md",
            "docs/publication/openai-skills-only.md",
            "docs/publication/agent-skills-record.md",
            "docs/publication/link-checks.json",
        ):
            self.assertEqual(check_ignore_exit(rel), 1, f"{rel} must not be ignored")
        for rel in (
            "docs/publication/notes.json",
            "docs/publication/sub/x.md",
            "docs/new-report.md",
            "docs/codex-plugin-runtime-debug-report/x.md",
            "docs/agentic-sdlc/publication-readiness/spec/x.md",
            "audit-docs/x.md",
            "tests/artifacts/publication/x.json",
        ):
            self.assertEqual(check_ignore_exit(rel), 0, f"{rel} must stay ignored")
        gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
        negations = {line for line in gitignore.splitlines() if line.startswith("!")}
        self.assertEqual(
            negations,
            set(BASELINE_GITIGNORE_NEGATIONS)
            | {
                "!docs/data-handling.md",
                "!docs/publication/",
                "!docs/publication/*.md",
                "!docs/publication/link-checks.json",
            },
        )

    def test_current_release_evidence_is_visible_and_linked(self):
        version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        evidence = REPO / "docs" / f"release-evidence-{version}.md"
        self.assertTrue(evidence.is_file(), "current release has no public evidence summary")
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(evidence)], cwd=REPO, capture_output=True
        )
        self.assertNotEqual(ignored.returncode, 0, "current release evidence is ignored")
        release = (REPO / "docs/release-readiness.md").read_text(encoding="utf-8")
        self.assertIn(evidence.name, release)

    def test_current_release_guidance_keeps_verified_runtime_and_eval_scope(self):
        text = (REPO / "docs/release-readiness.md").read_text(encoding="utf-8")
        current_limits = text.split("## Known Limitations", 1)[1].split("\n## ", 1)[0]
        self.assertNotIn("re-probe is pending", current_limits)
        self.assertNotIn("Current documented CLI is **0.153.4**", current_limits)
        for required in ("0.154.0", "2.1.269", "--runs 3", "--threshold 1.0", "claude-sonnet-5"):
            self.assertIn(required, text)
        self.assertIn("both procedure cases", text)

    def test_ci_uses_the_repository_python3_entrypoint(self):
        text = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertNotIn("run: python ", text)
        for command in (
            "python3 scripts/bump_version.py --release-check",
            "python3 scripts/check_all.py",
            "python3 tests/skills/harness.py",
            "python3 -m unittest discover -s tests -v",
        ):
            self.assertIn(command, text)

    def test_release_readiness_names_scope_gates_and_limitations(self):
        text = (REPO / "docs" / "release-readiness.md").read_text(encoding="utf-8")
        version = (REPO / "VERSION").read_text(encoding="utf-8").strip()

        for required in (
            "Claude Code",
            "Codex",
            "python3 scripts/bump_version.py --check",
            "python3 scripts/check_all.py",
            "python3 tests/skills/harness.py",
            "python3 -m unittest discover -s tests -v",
            "run_routing_eval.py",
            "--reasoning-effort low",
            "run_procedure_eval.py",
            "secret",
            "Known Limitations",
            "Codex wires native blocking `PreToolUse` guards",
            "Historical evidence — 2026-06-20 Codex 0.3.0 live low smoke",
            f"not live evidence for the current `{version}` worktree",
            "docs/agentic-sdlc/evidence/codex-live-low-strict-2026-06-20.md",
            "gpt-5.3-codex-spark",
            "model_reasoning_effort=\"low\"",
            "RED->GREEN",
            "`Overall Status: PASS` for Implementation Control",
            "Release Verdict Template",
        ):
            self.assertIn(required, text)

    def test_documented_script_count_matches_repo(self):
        names = sorted(path.name for path in (REPO / "scripts").glob("*.py"))
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        plugin_readme = (REPO / "docs" / "plugin-readme.md").read_text(encoding="utf-8")
        self.assertEqual(script_inventory_violations(readme, plugin_readme, names), [])

    def test_script_inventory_rule_synthetic_cases(self):
        seventeen = [f"helper_{i:02d}.py" for i in range(16)] + ["build_release.py"]

        def plugin_readme(count, names=seventeen):
            return f"## 11. Deterministic scripts ({count})\n\n" + "\n".join(f"| `{n}` | Purpose. |" for n in names) + "\n"

        readme17 = "scripts/           17 Python helpers: probes\n"
        cases = [
            ("readme_count_mismatch", "scripts/           18 Python helpers\n", plugin_readme(17), seventeen),
            ("plugin_readme_count_mismatch", readme17.replace("17", "19"), plugin_readme(17), seventeen + ["a.py", "b.py"]),
            (
                "plugin_readme_count_mismatch",
                readme17,
                plugin_readme(17) + "\n## Deterministic scripts (18)\n",
                seventeen,
            ),
            (
                "helper_not_listed:build_release.py",
                readme17,
                plugin_readme(17, [n for n in seventeen if n != "build_release.py"]),
                seventeen,
            ),
            ("ambiguous_readme_count", readme17 + "Also 18 Python helpers.\n", plugin_readme(17), seventeen),
            ("missing_readme_count", "scripts/ helpers\n", plugin_readme(17), seventeen),
        ]
        for name, readme, plugin, names in cases:
            with self.subTest(name=name):
                self.assertIn(name, script_inventory_violations(readme, plugin, names))
        self.assertEqual(script_inventory_violations(readme17, plugin_readme(17), seventeen), [])

    def test_data_handling_disclosure_is_code_backed(self):
        doc_path = REPO / "docs" / "data-handling.md"
        self.assertTrue(doc_path.is_file(), "docs/data-handling.md is missing")
        doc = doc_path.read_text(encoding="utf-8")
        # Re-derived from hook sources on every run: a new reader or writer needs a doc update.
        for hook in sorted((REPO / "hooks").glob("*.mjs")):
            source = hook.read_text(encoding="utf-8")
            if "transcript_path" in source:
                self.assertIn(hook.name, doc, f"{hook.name} reads transcript_path but is not disclosed")
            if "writeFileSync" in source:
                self.assertIn(hook.name, doc, f"{hook.name} writes files but is not disclosed")
            if "readdirSync" in source:
                self.assertIn(hook.name, doc, f"{hook.name} lists directories but is not disclosed")
            if "spawnSync" in source:
                self.assertIn(hook.name, doc, f"{hook.name} starts a process but is not disclosed")
        for required in (
            "AGENTIC_WORKTREE_SCAN_STATE",
            "AGENTIC_SDLC_PYTHON",
            "SessionStart",
            "transcript_path",
            "writeFileSync",
            "readdirSync",
            "spawnSync",
            "scripts/sensitive_redaction.py",
            "scripts/validate_artifacts.py",
            "--transcript-dir",
            "tests/artifacts/",
        ):
            self.assertIn(required, doc)
        for statement, cited, fragment in DATA_HANDLING_FACTS:
            with self.subTest(statement=statement, source=cited):
                self.assertIn(statement, doc, "doc statement missing")
                rel, _, line = cited.partition(":")
                lines = (REPO / rel).read_text(encoding="utf-8").splitlines()
                scope = lines[int(line) - 1] if line else "\n".join(lines)
                self.assertIn(fragment, scope, f"{cited} no longer implements: {statement}")
        cited = re.compile(r"^((?:hooks|scripts|tests)/[^\s`]+\.(?:mjs|py|json|md))(?::\d+(?:-\d+)?)?$")
        for token in re.findall(r"`([^`]+)`", doc):
            match = cited.match(token)
            if match:
                self.assertTrue((REPO / match.group(1)).is_file(), f"cited path does not exist: {token}")
        lowered = doc.lower()
        for claim in (
            "never leaves",
            "never transmitted",
            "not transmitted",
            "never stored",
            "not stored",
            "no data is collected",
            "no data is processed",
            "deleted after",
            "retained for",
            "we do not collect",
            "eval runners write their outputs under",
            # Superseded statements the source contradicts (worktree-scan dedup key, eval temp dir).
            "pattern label and file path",
            "persist transcripts",
            "reads the content carried in the tool input",
        ):
            self.assertNotIn(claim, lowered, f"unbacked retention or transmission claim: {claim}")

    def test_data_handling_disclosure_is_tracked(self):
        _require_git_checkout(self)
        proc = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "docs/data-handling.md"], cwd=REPO, capture_output=True
        )
        self.assertEqual(proc.returncode, 0, "docs/data-handling.md is not in the Git index")

    def test_readme_links_data_handling_disclosure(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertTrue("(docs/data-handling.md)" in readme, "README documentation list does not link docs/data-handling.md")

    def test_linked_codex_live_evidence_is_release_visible(self):
        target = REPO / "docs/agentic-sdlc/evidence/codex-live-low-strict-2026-06-20.md"
        self.assertTrue(target.is_file())
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(target)], cwd=REPO, capture_output=True
        )
        self.assertNotEqual(ignored.returncode, 0, "release evidence is still git-ignored")
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(target.relative_to(REPO))],
            cwd=REPO,
            capture_output=True,
        )
        self.assertEqual(tracked.returncode, 0, "release evidence is not present in the Git index")


if __name__ == "__main__":
    unittest.main()
