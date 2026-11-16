"""Flow manifests, shared policy, loop definition and schemas of the sdlc runner (plan Task 3).

Contract: docs/agentic-sdlc/notes/2026-10-22-runner-contract.md §6, §7, §9, §10, §12; design
docs/agentic-sdlc/notes/2026-10-22-middleware-chain-design.md §5.8, §5.9.2, §5.15. Covers
scripts/sdlc_runner/manifest.py and every file under flows/. Step files do not exist until P3, so
the real manifests are validated with check_files=False; the fixture flow under
tests/fixtures/sdlc/flows/ exercises check_files=True with its own step files in a temp plugin root.
Every rejection has a clean twin, so a validator that always fails (or always passes) is caught.
"""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sdlc_runner import fingerprint, manifest, paths, schema, textio  # noqa: E402

FLOWS = REPO / "flows"
SCHEMAS = FLOWS / "schemas"
FIXTURES = REPO / "tests" / "fixtures" / "sdlc" / "flows"

# Design §5.15, written out: every flow begins strategy -> context; bracketed steps are conditional.
DESIGN_ORDER = {
    "full": ["strategy", "context", "intent", "draft", "review", "branch", "docs-check", "implement",
             "security", "quality-gates", "diff-review", "quality-review", "audit", "claim"],
    "feature": ["strategy", "context", "draft", "review", "branch", "implement", "security", "audit", "claim"],
    "bugfix": ["strategy", "context", "draft", "review", "branch", "implement", "security", "audit", "claim"],
    "refactor": ["strategy", "context", "characterize", "branch", "implement", "security", "audit", "claim"],
    "test": ["strategy", "context", "branch", "implement", "claim"],
    "spec": ["strategy", "context", "draft", "review", "claim"],
    "plan": ["strategy", "context", "draft", "review", "claim"],
    "security-review": ["strategy", "context", "security", "claim"],
    "code-review": ["strategy", "context", "quality-review", "claim"],
    "audit": ["strategy", "context", "audit", "claim"],
    "design": ["strategy", "context", "intent", "claim"],
    "feedback": ["strategy", "context", "feedback", "claim"],
}
# Design §5.15: the conditional steps and what they hang on. Any step not listed always applies.
DESIGN_APPLIES = {
    ("full", "intent"): {"option": "intent"},
    ("full", "docs-check"): {"probe": "deps", "not": "stdlib_only"},
    ("full", "quality-gates"): {"probe": "toolchain", "not": "absent"},
    ("full", "quality-review"): {"option": "quality-review"},
    ("feature", "review"): {"form": "gated"},
    ("bugfix", "review"): {"form": "gated"},
}
# Design §5.8: the loop mode of each flow's draft step (None: the flow has no draft step).
DESIGN_LOOP_MODE = {
    "full": "spec+plan", "feature": "spec+plan", "bugfix": "bugfix-plan", "spec": "spec", "plan": "plan",
    "refactor": None, "test": None, "security-review": None, "code-review": None, "audit": None,
    "design": None, "feedback": None,
}
# Design §5.14: which skill enters each flow.
DESIGN_ENTRY = {
    "full": "agentic-sdlc-pipeline", "feature": "feature-build", "bugfix": "root-cause-fix",
    "refactor": "safe-refactor", "test": "test-authoring", "spec": "spec-authoring",
    "plan": "plan-authoring", "security-review": "security-audit", "code-review": "code-quality-review",
    "audit": "implementation-control", "design": "mind-spark", "feedback": "feedback-triage",
}

PINNED_CAPS = {
    "max_visits": 3, "implement_max_visits": 5, "transition_cap": 60, "no_progress_k": 3,
    "loop_max_rounds": 3, "loop_hard_max_rounds": 5, "loop_role_reentry": 2, "fix_rounds": 3,
}
# Contract §9 rows, values pinned by plan Task 3 (design §5.9.2); every row unverified until a live run.
PINNED_RUNTIMES = {
    "claude": {"workflow": "native", "subagent": "yes", "team": "flag", "freshness": "claude-agent", "verified": False},
    "grok": {"workflow": "staged", "subagent": "yes", "team": "no", "freshness": "grok-subagent", "verified": False},
    "zcode": {"workflow": "explicit-request", "subagent": "yes", "team": "no", "freshness": "zcode-new-actor",
              "verified": False},
    "kimi": {"workflow": "none", "subagent": "yes", "team": "no", "freshness": "kimi-agent", "verified": False},
    "codex": {"workflow": "none", "subagent": "yes", "team": "no", "freshness": "codex-v1-v2", "verified": False},
    "cursor": {"workflow": "none", "subagent": "yes", "team": "no", "freshness": "cursor-task", "verified": False},
    "antigravity": {"workflow": "none", "subagent": "yes", "team": "no", "freshness": "antigravity-invoke",
                    "verified": False},
    "other": {"workflow": "none", "subagent": "no", "team": "no", "freshness": "inline", "verified": False},
}
# Design D8 surfaces and the synonyms plan Task 3 names.
RISK_SURFACES = {"auth", "payment", "db-migration", "api-contract", "permissions", "user-data",
                 "token-session", "rls"}
PINNED_RISK_TERMS = [
    "auth", "authentication", "login", "password", "oauth", "session", "token", "jwt", "payment",
    "billing", "checkout", "migration", "schema change", "api contract", "breaking change",
    "permission", "role", "rbac", "acl", "user data", "pii", "gdpr", "rls", "row level security",
]
# The globs tests/test_sdlc_git_fingerprint.py (Task 2) classifies with; _shared.json keeps each verbatim.
TASK2_TEST_GLOBS = [
    "tests/**", "**/test_*.py", "**/*.test.{js,ts}", "**/*_test.go", "**/__tests__/**", "**/*Tests.cs",
    "spec/**",
]
CONTRACT_CHECKS = {
    "exists", "validator", "sidecar_ok", "report", "run_recorded", "approval", "branch_ok", "resolver_ok",
    "strategy_ok", "unchanged", "loop_done",
}
CONTRACT_MECHANISMS = ["main", "subagent", "workflow", "team", "runner-loop", "runner-loop-inline",
                       "inline-degraded", "parallel-runs"]
CONTRACT_MECHANISM_KEYS = ["context", "draft", "draft.critic", "spec-check", "implement", "security",
                           "quality-gates", "quality-review", "audit", "docs-check"]
LOOP_MODES = {"spec+plan", "spec", "plan", "bugfix-plan"}
# Every step file the real manifests name exists since plan Task 16; a step file that is later
# deleted or misnamed shows up here as a diff.
MISSING_STEP_FILES_P1 = []
# The report check of each step id (path, header), the same in every flow that has the step.
REPORT_CHECKS = {
    "context": ("context.md", "## Scope Lock"),
    "characterize": ("evidence/{work_id}.characterize.md", "## Goal Lock"),
    "docs-check": ("evidence/{work_id}.docs.md", "# Docs check"),
    "implement": ("evidence/{work_id}.tdd.md", "# TDD evidence"),
    "security": ("evidence/{work_id}.security.md", "# Security review"),
    "quality-gates": ("evidence/{work_id}.gates.md", "# Quality gates"),
    "diff-review": ("evidence/{work_id}.diff.md", "# Diff review"),
    "quality-review": ("evidence/{work_id}.quality.md", "# Quality review"),
    "audit": ("evidence/{work_id}.audit.md", "# Implementation audit"),
    "feedback": ("evidence/{work_id}.feedback.md", "# Feedback triage"),
    "claim": ("evidence/{work_id}.claim.md", "# Completion claim"),
}
# The security step blocks on a pass verdict in every flow that changes source; the one-step
# security-review flow only reports.
SECURITY_VERDICT = {"full": "Verdict: pass", "feature": "Verdict: pass", "bugfix": "Verdict: pass",
                    "refactor": "Verdict: pass", "security-review": None}
# Design §5.11 escalate lattice (light -> gated is a form change, not an edge): (from, to, work type the
# target runs with; "keep" carries the package's own work type).
DESIGN_LATTICE = [
    ("spec", "feature", "feature"), ("design", "spec", "keep"), ("feature", "full", "keep"),
    ("bugfix", "full", "keep"), ("refactor", "full", "keep"), ("test", "feature", "feature"),
    ("feedback", "bugfix", "bugfix"),
]
SCHEMA_IDS = {
    "flow": "agentic-sdlc/flow@1", "shared": "agentic-sdlc/shared@1", "loop": "agentic-sdlc/loop-def@1",
    "critic": "agentic-sdlc/critic@1", "draft-result": "agentic-sdlc/draft-result@1",
    "sidecar": "agentic-sdlc/sidecar@1", "strategy": "agentic-sdlc/strategy@1",
}


def _errors_text(errors):
    return "\n".join(errors) or "(no errors)"


def _rename(source, target):
    """Rename through a temporary name, so a case-only rename also works on case-insensitive disks."""
    middle = Path(str(target) + ".renaming")
    source.rename(middle)
    middle.rename(target)


def _steps(flow):
    return {step["id"]: step for step in flow["steps"]}


def _reference_match(shared, argv, inner_of_module=False, depth=0):
    """The runner id `argv` resolves to under the allowlist semantics in shared.schema.json, or None.

    A reference reading for the data only (Task 4's runexec.resolve_command is the real resolver):
    entries are tried in order and the first whose program and subcommand match decides; a token in
    `deny_args` (or `token=value`) refuses; a `script_after` subcommand needs a script named by
    `run_scripts`; a wrapping entry checks the rest as an inner command; a `module_only` entry is
    reachable only as the module after a `-m` subcommand.
    """
    if not argv or depth > 4:
        return None
    program, rest = argv[0], list(argv[1:])
    for entry in shared["run_allowlist"]:
        if entry["program"] != program:
            continue
        if entry.get("module_only") and not inner_of_module:
            return None
        matched = None
        for sub in entry.get("subcommand", [""]):
            tokens = sub.split(" ") if sub else []
            if rest[:len(tokens)] == tokens:
                matched = tokens
                break
        if matched is None:
            continue
        denied = entry.get("deny_args", [])
        if any(arg == d or arg.startswith(d + "=") for arg in rest for d in denied):
            return None
        after = rest[len(matched):]
        if matched and " ".join(matched) in entry.get("script_after", []):
            if not after or not any(fingerprint.glob_match(after[0], p) for p in shared["run_scripts"]):
                return None
        if entry.get("wraps"):
            return _reference_match(shared, after, bool(matched) and matched[-1] == "-m", depth + 1)
        runner = entry.get("runner")
        return runner or (program[2:] if program.startswith("./") else program)
    return None


class TempRoot(unittest.TestCase):
    """A throwaway plugin root: the real loop definitions plus the fixture flow and its step files."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "plugin root ğ"
        (self.root / "flows" / "loops").mkdir(parents=True)
        for loop in (FLOWS / "loops").glob("*.json"):
            shutil.copyfile(str(loop), str(self.root / "flows" / "loops" / loop.name))
        shutil.copyfile(str(FLOWS / "_shared.json"), str(self.root / "flows" / "_shared.json"))
        shutil.copyfile(str(FIXTURES / "fixture.json"), str(self.root / "flows" / "fixture.json"))
        steps = self.root / "skills" / "fixture" / "steps"
        steps.mkdir(parents=True)
        for step in (FIXTURES / "steps").glob("*.md"):
            shutil.copyfile(str(step), str(steps / step.name))


class TestShared(unittest.TestCase):
    def setUp(self):
        self.shared = manifest.load_shared(REPO)

    def test_shared_validates(self):
        self.assertEqual(manifest.validate_shared(self.shared), [])
        self.assertEqual(schema.validate(self.shared, manifest.load_schema("shared")), [])
        self.assertEqual(self.shared["schema"], "agentic-sdlc/shared@1")

    def test_caps_are_pinned(self):
        self.assertEqual(self.shared["caps"], PINNED_CAPS)

    def test_runtime_rows_are_pinned(self):
        self.assertEqual(self.shared["runtimes"], PINNED_RUNTIMES)
        self.assertEqual(sorted(self.shared["runtimes"]), sorted(manifest.RUNTIMES))
        # contract §9: explicit-request is never a default workflow; only zcode carries it.
        explicit = [rid for rid, row in self.shared["runtimes"].items() if row["workflow"] == "explicit-request"]
        self.assertEqual(explicit, ["zcode"])

    def test_risk_lexicon_names_the_eight_surfaces_and_the_pinned_terms(self):
        lexicon = self.shared["risk_lexicon"]
        self.assertEqual(set(lexicon), RISK_SURFACES)
        terms = [term for surface in lexicon.values() for term in surface]
        self.assertEqual(len(terms), len(set(terms)), "a term listed under two surfaces")
        for term in PINNED_RISK_TERMS:
            with self.subTest(term=term):
                self.assertIn(term, terms)
        for surface, surface_terms in lexicon.items():
            with self.subTest(surface=surface):
                self.assertTrue(surface_terms)
                for term in surface_terms:
                    self.assertEqual(term, " ".join(term.lower().split()))

    def test_test_globs_keep_the_task2_fixture_and_stay_in_the_glob_dialect(self):
        globs = self.shared["test_globs"]
        for glob in TASK2_TEST_GLOBS:
            with self.subTest(glob=glob):
                self.assertIn(glob, globs)
        self.assertEqual(len(globs), len(set(globs)))
        for glob in globs:
            with self.subTest(glob=glob):
                self.assertIsNone(manifest.glob_problem(glob))

    def test_glob_dialect_check_rejects_what_the_translator_reads_literally(self):
        for bad in ["src/[ab].py", "!tests/**", "/tests/**", "./tests/**", "tests/", "a**b/x.py", "a/{b}/c",
                    "a,b", "tests\\x.py", "", "a//b", "{a,b"]:
            with self.subTest(glob=bad):
                self.assertIsNotNone(manifest.glob_problem(bad))
        for good in ["**", "tests/**", "**/*.test.{js,ts}", "**/test_?.py", "src/**/x/*.py"]:
            with self.subTest(glob=good):
                self.assertIsNone(manifest.glob_problem(good))

    def test_test_globs_classify_common_layouts(self):
        tests_paths = [
            "tests/test_a.py", "test/a.js", "pkg/tests/x.py", "src/foo/test_bar.py", "src/foo/bar_test.py",
            "conftest.py", "app/component.test.tsx", "web/a.spec.ts", "lib/x.spec.mjs", "pkg/x_test.go",
            "src/__tests__/a.js", "src/__mocks__/fs.js", "Foo.Tests/BarTests.cs", "Foo/BarTest.cs",
            "src/test/java/FooTest.java", "core/src/main/java/FooTests.java", "src/FooIT.java",
            "app/FooTest.kt", "spec/models/user_spec.rb", "lib/x_spec.rb", "tests/Unit/FooTest.php",
            "Sources/FooTests.swift", "lib/x_test.dart", "test/x_test.exs", "pkg/testdata/in.txt",
            "src/__snapshots__/a.snap",
        ]
        source_paths = [
            "src/app.py", "src/testing_utils.py", "src/contest.py", "lib/latest.js", "src/attest.go",
            "api/spec/openapi.yaml", "src/test_helpers/x.go", "README.md", "src/Testimonial.cs",
            "src/spectest.rb",
        ]
        source, tests = fingerprint.classify(tests_paths + source_paths, self.shared["test_globs"])
        self.assertEqual(sorted(tests), sorted(tests_paths))
        self.assertEqual(sorted(source), sorted(source_paths))

    def test_ignore_globs_drop_tool_caches_only(self):
        ignore = self.shared["ignore_globs"]
        caches = ["src/__pycache__/app.cpython-312.pyc", ".pytest_cache/v/cache/nodeids", "pkg/.mypy_cache/x.json",
                  ".ruff_cache/0.5/1", ".coverage", "sub/.coverage.host.1", "htmlcov/index.html", ".tox/py/log.txt",
                  "web/node_modules/.cache/babel/x", "lib/a.pyc", ".gradle/8.0/x.lock", "app/.eslintcache"]
        kept = ["src/app.py", "tests/test_a.py", "coverage.py", "src/cache/x.py", "docs/coverage.md", "build.gradle"]
        source, ignored = fingerprint.classify(caches + kept, ignore)
        self.assertEqual(sorted(ignored), sorted(caches))
        self.assertEqual(sorted(source), sorted(kept))
        for glob in ignore:
            with self.subTest(glob=glob):
                self.assertIsNone(manifest.glob_problem(glob))

    def test_run_allowlist_admits_common_runners(self):
        admitted = [
            (["pytest", "-q"], "pytest"), (["python", "-m", "pytest", "tests"], "pytest"),
            (["python3", "-m", "pytest"], "pytest"), (["py", "-3", "-m", "pytest"], "pytest"),
            (["py", "-m", "pytest"], "pytest"), (["python", "-m", "unittest", "discover"], "unittest"),
            (["npm", "test"], "npm"), (["npm", "run", "test"], "npm"), (["npm", "run", "test:unit"], "npm"),
            (["npm", "run", "lint"], "npm"), (["npm", "run", "typecheck"], "npm"),
            (["pnpm", "test"], "pnpm"), (["pnpm", "run", "build"], "pnpm"),
            (["pnpm", "exec", "vitest", "run"], "vitest"), (["yarn", "test"], "yarn"),
            (["yarn", "run", "test"], "yarn"), (["yarn", "jest"], "jest"), (["npx", "jest"], "jest"),
            (["npx", "vitest", "run"], "vitest"), (["npx", "mocha"], "mocha"),
            (["npx", "playwright", "test"], "playwright"), (["npx", "tsc", "--noEmit"], "tsc"),
            (["npx", "eslint", "."], "eslint"), (["go", "test", "./..."], "go"), (["go", "vet", "./..."], "go"),
            (["cargo", "test"], "cargo"), (["dotnet", "test"], "dotnet"), (["mvn", "test"], "mvn"),
            (["./mvnw", "test"], "mvn"), (["gradle", "test"], "gradle"), (["./gradlew", "test"], "gradle"),
            (["jest"], "jest"), (["vitest", "run"], "vitest"), (["mocha"], "mocha"), (["rspec"], "rspec"),
            (["bundle", "exec", "rspec"], "rspec"), (["uv", "run", "pytest"], "pytest"),
            (["poetry", "run", "pytest", "-x"], "pytest"), (["tox", "-e", "py"], "tox"),
            (["nox", "-s", "tests"], "nox"), (["ruff", "check", "."], "ruff"), (["eslint", "."], "eslint"),
            (["tsc", "--noEmit"], "tsc"), (["mypy", "src"], "mypy"), (["make", "test"], "make"),
            (["phpunit"], "phpunit"), (["uv", "run", "python", "-m", "pytest"], "pytest"),
        ]
        for argv, runner in admitted:
            with self.subTest(argv=argv):
                self.assertEqual(_reference_match(self.shared, argv), runner)

    def test_run_allowlist_refuses_shells_interpreters_and_other_programs(self):
        refused = [
            ["git", "status"], ["rm", "-rf", "x"], ["bash", "-c", "x"], ["sh", "-c", "x"], ["node", "-e", "x"],
            ["cmd", "/c", "x"], ["powershell", "-c", "x"], ["curl", "x"], ["python", "-c", "x"],
            ["python", "script.py"], ["npm", "install"], ["npm", "run", "deploy"], ["npm", "exec", "x"],
            ["npx", "-c", "x"], ["npx", "node", "-e", "x"], ["uv", "run", "python", "-c", "x"],
            ["go", "test", "-exec", "x"], ["go", "test", "-exec=x"], ["go", "run", "."], ["cargo", "run"],
            ["make", "deploy"], ["make", "test", "--eval=x"], ["tox", "exec", "--", "git"], ["unittest"],
            ["yarn", "node"], ["pnpm", "exec", "bash"], ["playwright", "install"], ["ruff", "server"],
            ["mvn", "deploy"], ["gradle", "publish"], ["dotnet", "run"], ["poetry", "add", "x"],
            ["bundle", "install"], ["python", "-m", "pip", "install", "x"],
        ]
        for argv in refused:
            with self.subTest(argv=argv):
                self.assertIsNone(_reference_match(self.shared, argv))

    def test_every_allowlist_entry_explains_its_restriction(self):
        for index, entry in enumerate(self.shared["run_allowlist"]):
            with self.subTest(entry=index):
                self.assertTrue(entry.get("$comment", "").strip())

    def test_exit_codes_follow_contract_12(self):
        codes = self.shared["exit_codes"]
        self.assertEqual(codes["pytest"]["fail"], [1])
        self.assertTrue({2, 4, 5} <= set(codes["pytest"]["invalid"]))
        runner_ids = manifest.runner_ids(self.shared)
        for runner, row in codes.items():
            with self.subTest(runner=runner):
                self.assertIn(runner, runner_ids)
                self.assertFalse(set(row["fail"]) & set(row["invalid"]))
                self.assertNotIn(0, row["fail"] + row["invalid"])

    def test_run_scripts_follow_contract_12(self):
        self.assertEqual(self.shared["run_scripts"], ["test", "test:*", "lint", "typecheck", "build"])

    def test_validate_shared_rejects(self):
        def runtime_row(s):
            s["runtimes"]["codex"]["workflow"] = "maybe"

        def unknown_runtime(s):
            s["runtimes"]["vim"] = dict(s["runtimes"]["other"])

        def missing_verified(s):
            del s["runtimes"]["claude"]["verified"]

        def rounds_over_hard(s):
            s["caps"]["loop_max_rounds"] = 6

        def glob_class(s):
            s["test_globs"].append("src/[ab].py")

        def glob_inner_star(s):
            s["test_globs"].append("src/a**b.py")

        def script_after_not_sub(s):
            npm = next(e for e in s["run_allowlist"] if e["program"] == "npm")
            npm["script_after"] = ["exec"]

        def unreachable(s):
            s["run_allowlist"].append({"program": "pytest", "$comment": "shadowed by the first pytest entry"})

        def code_in_both(s):
            s["exit_codes"]["pytest"]["invalid"].append(1)

        def unknown_runner_codes(s):
            s["exit_codes"]["nosuch"] = {"fail": [1], "invalid": [2]}

        def no_comment(s):
            del s["run_allowlist"][0]["$comment"]

        def missing_cap(s):
            del s["caps"]["fix_rounds"]

        def duplicate_term(s):
            s["risk_lexicon"]["payment"].append("token")

        def empty_test_globs(s):
            s["test_globs"] = []

        def unreachable_subcommand(s):
            s["run_allowlist"].append({"program": "go", "subcommand": ["test"], "$comment": "shadowed by go test"})

        def wrapper_with_deny_args(s):
            next(e for e in s["run_allowlist"] if e["program"] == "npx")["deny_args"] = ["--yes"]

        def wrapper_with_path_flags(s):
            next(e for e in s["run_allowlist"] if e["program"] == "npx")["path_flags"] = ["--prefix"]

        def inner_on_plain_entry(s):
            s["run_allowlist"][0]["inner"] = ["jest"]

        def inner_unknown_program(s):
            next(e for e in s["run_allowlist"] if e["program"] == "npx")["inner"].append("bash")

        def wrapper_with_deny_prefixes(s):
            next(e for e in s["run_allowlist"] if e["program"] == "npx")["deny_prefixes"] = ["@"]

        def ignore_glob_class(s):
            s["ignore_globs"].append("src/[ab].py")

        def no_ignore_globs(s):
            del s["ignore_globs"]

        def duplicate_edge(s):
            s["escalation"].append({"from": "spec", "to": "feature", "work_type": "feature"})

        def self_edge(s):
            s["escalation"].append({"from": "bugfix", "to": "bugfix", "work_type": "keep"})

        last = len(self.shared["run_allowlist"])
        npx = next(i for i, e in enumerate(self.shared["run_allowlist"]) if e["program"] == "npx")
        edges = len(self.shared["escalation"])
        cases = [
            (runtime_row, "/runtimes/codex/workflow"), (unknown_runtime, "/runtimes/vim"),
            (missing_verified, "/runtimes/claude/verified"), (rounds_over_hard, "/caps/loop_max_rounds"),
            (glob_class, "/test_globs/"), (glob_inner_star, "/test_globs/"),
            (script_after_not_sub, "script_after"), (unreachable, "unreachable"),
            (code_in_both, "/exit_codes/pytest"), (unknown_runner_codes, "/exit_codes/nosuch"),
            (no_comment, "/run_allowlist/0/$comment"), (missing_cap, "/caps/fix_rounds"),
            (duplicate_term, "token"),
            (empty_test_globs, "/test_globs: an empty list makes every changed file a source file"),
            (unreachable_subcommand,
             "/run_allowlist/%d/subcommand: unreachable: go test is matched by an earlier entry" % last),
            (wrapper_with_deny_args, "/run_allowlist/%d/deny_args: a wrapping entry checks its inner command" % npx),
            (wrapper_with_path_flags, "/run_allowlist/%d/path_flags: a wrapping entry checks its inner command" % npx),
            (inner_on_plain_entry, "/run_allowlist/0/inner: only a wrapping entry names inner"),
            (inner_unknown_program, "/run_allowlist/%d/inner/%d: 'bash' is not a program of run_allowlist"
             % (npx, len(self.shared["run_allowlist"][npx]["inner"]))),
            (wrapper_with_deny_prefixes,
             "/run_allowlist/%d/deny_prefixes: a wrapping entry checks its inner command" % npx),
            (ignore_glob_class, "/ignore_globs/%d" % len(self.shared["ignore_globs"])),
            (no_ignore_globs, "/ignore_globs"),
            (duplicate_edge, "/escalation/%d: duplicate edge spec -> feature" % edges),
            (self_edge, "/escalation/%d: an edge leads to another flow" % edges),
        ]
        for mutate, expected in cases:
            with self.subTest(case=mutate.__name__):
                broken = copy.deepcopy(self.shared)
                mutate(broken)
                errors = manifest.validate_shared(broken)
                self.assertTrue(any(expected in e for e in errors), _errors_text(errors))

    def test_escalation_lattice_walks_the_real_flows(self):
        # Design §5.11: every edge lands on a flow that runs the package's work type with an implement
        # variant for it, so an escalated package never names a work type its new flow lacks.
        edges = [(e["from"], e["to"], e["work_type"]) for e in self.shared["escalation"]]
        self.assertEqual(sorted(edges), sorted(DESIGN_LATTICE))
        self.assertEqual(manifest.validate_lattice(REPO, self.shared), [])
        for source_id, target_id, mapped in edges:
            with self.subTest(edge=(source_id, target_id)):
                source = manifest.load_flow(REPO, source_id)
                target = manifest.load_flow(REPO, target_id)
                carried = source["work_types"] if mapped == "keep" else [mapped]
                implement = _steps(target).get("implement")
                for work_type in carried:
                    self.assertIn(work_type, target["work_types"])
                    if implement is not None:
                        self.assertIn(work_type, implement["file"])

    def test_validate_lattice_rejects(self):
        def index(s, source, target):
            return next(i for i, e in enumerate(s["escalation"]) if (e["from"], e["to"]) == (source, target))

        def keep_without_variant(s):
            s["escalation"][index(s, "test", "feature")]["work_type"] = "keep"

        def mapped_outside_target(s):
            s["escalation"][index(s, "spec", "feature")]["work_type"] = "bugfix"

        def unknown_flow(s):
            s["escalation"].append({"from": "nosuch", "to": "full", "work_type": "keep"})

        def downward_edge(s):
            s["escalation"].append({"from": "full", "to": "spec", "work_type": "keep"})

        cases = [
            (keep_without_variant, "/escalation/%d/work_type: 'test' is not a work type of flow 'feature'"
             % index(self.shared, "test", "feature")),
            (mapped_outside_target, "/escalation/%d/work_type: 'bugfix' is not a work type of flow 'feature'"
             % index(self.shared, "spec", "feature")),
            (unknown_flow, "/escalation/%d/from: unknown flow 'nosuch'" % len(self.shared["escalation"])),
            (downward_edge, "/escalation/%d: the lattice is upward only; full -> spec closes a cycle"
             % len(self.shared["escalation"])),
        ]
        for mutate, expected in cases:
            with self.subTest(case=mutate.__name__):
                broken = copy.deepcopy(self.shared)
                mutate(broken)
                errors = manifest.validate_lattice(REPO, broken)
                self.assertTrue(any(e.startswith(expected) for e in errors), _errors_text(errors))


class TestFlows(unittest.TestCase):
    def test_flow_ids_are_the_design_list(self):
        self.assertEqual(manifest.flow_ids(REPO), sorted(DESIGN_ORDER))

    def test_every_flow_validates_without_files(self):
        for flow_id in manifest.flow_ids(REPO):
            with self.subTest(flow=flow_id):
                flow = manifest.load_flow(REPO, flow_id)
                errors = manifest.validate_flow(flow, REPO, check_files=False)
                self.assertEqual(errors, [], _errors_text(errors))
                self.assertEqual(flow["id"], flow_id)

    def test_every_flow_starts_strategy_then_context(self):
        for flow_id in manifest.flow_ids(REPO):
            with self.subTest(flow=flow_id):
                ids = [step["id"] for step in manifest.load_flow(REPO, flow_id)["steps"]]
                self.assertEqual(ids[:2], ["strategy", "context"])

    def test_flow_order_matches_design(self):
        for flow_id, order in DESIGN_ORDER.items():
            with self.subTest(flow=flow_id):
                ids = [step["id"] for step in manifest.load_flow(REPO, flow_id)["steps"]]
                self.assertEqual(ids, order)

    def test_conditional_steps_match_design(self):
        for flow_id in DESIGN_ORDER:
            for step in manifest.load_flow(REPO, flow_id)["steps"]:
                with self.subTest(flow=flow_id, step=step["id"]):
                    self.assertEqual(step.get("applies_when"), DESIGN_APPLIES.get((flow_id, step["id"])))

    def test_forms_entries_and_loop_modes(self):
        for flow_id in DESIGN_ORDER:
            with self.subTest(flow=flow_id):
                flow = manifest.load_flow(REPO, flow_id)
                self.assertEqual(flow["entry_skill"], DESIGN_ENTRY[flow_id])
                self.assertEqual(flow["loop_mode"], DESIGN_LOOP_MODE[flow_id])
                steps = _steps(flow)
                if flow["loop_mode"]:
                    self.assertEqual(steps["draft"]["loop"], "spec-plan")
                    self.assertEqual(steps["draft"]["mechanism_key"], "draft")
                    self.assertEqual(steps["review"]["gate"], "review")
                # design §5.3: --form light is refused for full; a spec or plan flow exists for its gate.
                if flow_id in ("full", "spec", "plan"):
                    self.assertEqual(flow["forms"], ["gated"])
                else:
                    self.assertEqual(flow["forms"], ["gated", "light"])
        self.assertEqual(manifest.load_flow(REPO, "full")["work_types"], ["feature", "bugfix", "refactor"])

    def test_caps_and_run_once_per_design(self):
        caps = manifest.load_shared(REPO)["caps"]
        for flow_id in DESIGN_ORDER:
            steps = _steps(manifest.load_flow(REPO, flow_id))
            with self.subTest(flow=flow_id):
                self.assertTrue(steps["strategy"]["run_once"])
                self.assertEqual(steps["strategy"]["max_visits"], 1)
                if "implement" in steps:
                    self.assertEqual(steps["implement"]["max_visits"], caps["implement_max_visits"])
                for step_id, step in steps.items():
                    if step_id not in ("strategy", "implement"):
                        self.assertNotIn("max_visits", step, step_id + " overrides the shared default")
                        self.assertFalse(step.get("run_once", False), step_id)

    def test_mechanism_keys_and_mandated_fresh_steps(self):
        used = set()
        for flow_id in DESIGN_ORDER:
            for step in manifest.load_flow(REPO, flow_id)["steps"]:
                key = step.get("mechanism_key")
                with self.subTest(flow=flow_id, step=step["id"]):
                    # Contract §9: a mechanism-bearing step prints its own strategy entry. Without the key
                    # a mandated fresh step (security, audit, quality-review) would have no entry that
                    # strategy_ok checks, and could run in main.
                    if step["id"] in CONTRACT_MECHANISM_KEYS:
                        self.assertEqual(key, step["id"])
                    else:
                        self.assertIsNone(key)
                if key:
                    used.add(key)
        # draft.critic is read by the loop's critic role, never by a step card. spec-check is not used
        # by a flow yet (plan Task 6 gives the flows their spec-check step and removes this exemption).
        self.assertEqual(used, set(CONTRACT_MECHANISM_KEYS) - {"draft.critic", "spec-check"})
        self.assertEqual(set(manifest.MANDATED_FRESH_KEYS),
                         {"draft.critic", "spec-check", "security", "audit", "quality-review"})

    def test_spec_check_is_a_mandated_fresh_key(self):
        self.assertIn("spec-check", manifest.MECHANISM_KEYS)
        self.assertIn("spec-check", manifest.MANDATED_FRESH_KEYS)
        entries = manifest.load_schema("strategy")["properties"]["entries"]["properties"]
        self.assertIn("spec-check", entries)
        self.assertIn("spec-check", manifest.load_schema("strategy")["properties"]["degraded"]["items"]
                      ["properties"]["key"]["enum"])

    def test_report_checks_are_pinned_per_flow(self):
        for flow_id in DESIGN_ORDER:
            for step in manifest.load_flow(REPO, flow_id)["steps"]:
                reports = [c for c in step["done_when"] if c["check"] == "report"]
                with self.subTest(flow=flow_id, step=step["id"]):
                    if step["id"] not in REPORT_CHECKS:
                        self.assertEqual(reports, [])
                        continue
                    self.assertEqual(len(reports), 1)
                    path, header = REPORT_CHECKS[step["id"]]
                    self.assertEqual((reports[0]["path"], reports[0]["header"]), (path, header))
                    self.assertIn(path, step["outputs"])
                    verdict = SECURITY_VERDICT[flow_id] if step["id"] == "security" else None
                    self.assertEqual(reports[0].get("verdict"), verdict)
                    self.assertNotIn("fresh", reports[0])  # default true: an earlier visit's report never counts

    def test_gates_and_red_green_evidence(self):
        red = {"check": "run_recorded", "expect": "fail", "label": "red"}
        for flow_id in DESIGN_ORDER:
            steps = _steps(manifest.load_flow(REPO, flow_id))
            gates = [s for s in steps.values() if s.get("gate")]
            with self.subTest(flow=flow_id):
                self.assertEqual([s["id"] for s in gates], ["review"] if "review" in steps else [])
                implement = steps.get("implement")
                if implement is None:
                    continue
                checks = [(c["check"], c.get("expect")) for c in implement["done_when"]]
                self.assertIn(("run_recorded", "pass"), checks)
                reds = [c for c in implement["done_when"] if c["check"] == "run_recorded" and c["expect"] == "fail"]
                if flow_id in ("feature", "bugfix"):
                    self.assertEqual(reds, [red])
                elif flow_id == "full":
                    # The refactor variant shares safe-refactor's step file, which takes no RED (a
                    # behaviour-preserving change has no failing test); only feature and bugfix need one.
                    self.assertEqual(reds, [dict(red, work_types=["feature", "bugfix"])])
                else:
                    self.assertEqual(reds, [])
                if flow_id == "test":
                    self.assertIn(("unchanged", None), checks)
                self.assertEqual(sorted(implement["file"]), sorted(manifest.load_flow(REPO, flow_id)["work_types"]))

    def test_one_step_audit_runs_the_resolver_for_planned_work(self):
        # Design §5.14: the audit step has the runner run the resolver; refactor and test work has no plan.
        audit = _steps(manifest.load_flow(REPO, "audit"))["audit"]
        self.assertIn({"check": "resolver_ok", "work_types": ["feature", "bugfix"]}, audit["done_when"])

    def test_plan_flow_imports_the_approved_spec(self):
        # The plan flow's draft reads an existing approved spec that no step of the flow writes.
        flow = manifest.load_flow(REPO, "plan")
        self.assertEqual(flow["imports"], [{"path": "spec/{work_id}.md", "option": "--spec-file", "status": "approved"}])
        for flow_id in DESIGN_ORDER:
            if flow_id != "plan":
                with self.subTest(flow=flow_id):
                    self.assertNotIn("imports", manifest.load_flow(REPO, flow_id))

    def test_real_manifest_step_files_are_the_p1_missing_list(self):
        missing = set()
        for flow_id in manifest.flow_ids(REPO):
            flow = manifest.load_flow(REPO, flow_id)
            for error in manifest.validate_flow(flow, REPO, check_files=True):
                reason = error.split(": ", 1)[1]
                self.assertTrue(reason.startswith("missing step file "), error)
                missing.add(reason[len("missing step file "):])
        self.assertEqual(sorted(missing), MISSING_STEP_FILES_P1)

    def test_step_files_and_entries_name_existing_skills(self):
        for flow_id in DESIGN_ORDER:
            flow = manifest.load_flow(REPO, flow_id)
            with self.subTest(flow=flow_id):
                self.assertTrue((REPO / "skills" / flow["entry_skill"] / "SKILL.md").is_file())
                for step in flow["steps"]:
                    files = step["file"] if isinstance(step["file"], dict) else {"-": step["file"]}
                    for rel in files.values():
                        parts = rel.split("/")
                        self.assertEqual((parts[0], parts[2]), ("skills", "steps"), rel)
                        self.assertTrue((REPO / "skills" / parts[1]).is_dir(), rel)

    def test_validate_flow_rejects(self):
        base = textio.read_json(FIXTURES / "fixture.json")
        clean = manifest.validate_flow(copy.deepcopy(base), REPO, check_files=False)
        self.assertEqual(clean, [], _errors_text(clean))

        def unknown_key(f):
            f["steps"][1]["colour"] = "red"

        def unknown_top_key(f):
            f["owner"] = "someone"

        def duplicate_id(f):
            f["steps"][2]["id"] = "context"

        def unknown_check(f):
            f["steps"][1]["done_when"][0] = {"check": "vibes"}

        def gate_step_without_gate_id(f):
            del f["steps"][3]["gate"]

        def gate_step_with_null_gate(f):
            f["steps"][3]["gate"] = None

        def gate_without_approval(f):
            f["steps"][3]["done_when"] = [{"check": "exists", "path": "x.md"}]

        def approval_names_other_gate(f):
            f["steps"][3]["done_when"][0]["gate"] = "other"

        def max_visits_zero(f):
            f["steps"][1]["max_visits"] = 0

        def first_step_not_strategy(f):
            f["steps"][0], f["steps"][1] = f["steps"][1], f["steps"][0]

        def unknown_loop_id(f):
            f["steps"][2]["loop"] = "spec-only"

        def loop_without_loop_mode(f):
            f["loop_mode"] = None

        def loop_mode_without_loop_step(f):
            f["steps"][2]["loop"] = None

        def missing_check_param(f):
            f["steps"][1]["done_when"][0] = {"check": "exists"}

        def foreign_check_param(f):
            f["steps"][1]["done_when"][0] = {"check": "exists", "path": "context.md", "header": "# X"}

        def input_leaves_package(f):
            f["steps"][1]["inputs"] = ["../secret.md"]

        def unknown_placeholder(f):
            f["steps"][2]["outputs"] = ["spec/{slug}.md"]

        def named_set_as_output(f):
            f["steps"][1]["outputs"] = ["@source"]

        def implement_variant_missing(f):
            del f["steps"][4]["file"]["bugfix"]

        def map_file_outside_implement(f):
            f["steps"][1]["file"] = {"feature": "skills/fixture/steps/context.md"}

        def form_not_in_flow(f):
            f["forms"] = ["gated"]
            f["steps"][3]["applies_when"] = {"form": "light"}

        def probe_value_unknown(f):
            f["steps"][5]["applies_when"] = {"probe": "deps", "not": "maybe"}

        def probe_without_not(f):
            f["steps"][5]["applies_when"] = {"probe": "deps"}

        def strategy_not_run_once(f):
            f["steps"][0]["run_once"] = False

        def no_steps(f):
            f["steps"] = []

        def file_outside_skills(f):
            f["steps"][1]["file"] = "../x.md"

        def unknown_mechanism_key(f):
            f["steps"][1]["mechanism_key"] = "speed"

        def empty_done_when(f):
            f["steps"][1]["done_when"] = []

        def bad_schema_id(f):
            f["schema"] = "agentic-sdlc/flow@2"

        def duplicate_gate(f):
            f["steps"][5]["gate"] = "review"
            f["steps"][5]["done_when"].append({"check": "approval", "gate": "review"})

        def not_without_probe(f):
            f["steps"][5]["applies_when"] = {"not": "absent"}

        def applies_work_type_outside_flow(f):
            f["steps"][5]["applies_when"] = {"work_type": ["refactor"]}

        def empty_forms(f):
            f["forms"] = []

        def duplicate_form(f):
            f["forms"] = ["gated", "light", "gated"]

        def empty_work_types(f):
            f["work_types"] = []

        def duplicate_work_type(f):
            f["work_types"] = ["feature", "bugfix", "feature"]

        def implement_extra_variant(f):
            f["steps"][4]["file"]["refactor"] = "skills/fixture/steps/implement-feature.md"

        def second_loop_step(f):
            f["steps"][5]["loop"] = "spec-plan"

        def mechanism_step_without_key(f):
            del f["steps"][1]["mechanism_key"]

        def other_steps_key(f):
            f["steps"][6]["mechanism_key"] = "audit"

        def check_work_types_outside_flow(f):
            f["steps"][4]["done_when"][0]["work_types"] = ["refactor"]

        def check_work_types_empty(f):
            f["steps"][4]["done_when"][0]["work_types"] = []

        def input_without_producer(f):
            f["steps"][6]["inputs"] = ["evidence/{work_id}.nosuch.md"]

        def input_written_later(f):
            f["steps"][1]["inputs"] = ["request.md", "plan/{work_id}.md#body"]

        def import_bad_option(f):
            f["imports"] = [{"path": "notes/{work_id}.md", "option": "spec", "status": "approved"}]

        def import_named_set(f):
            f["imports"] = [{"path": "notes/{work_id}.md#body", "option": "--notes-file", "status": "approved"}]

        cases = [
            (unknown_key, "/steps/1/colour"), (unknown_top_key, "/owner"), (duplicate_id, "duplicate step id"),
            (unknown_check, "/steps/1/done_when/0/check"), (gate_step_without_gate_id, "/steps/3"),
            (gate_step_with_null_gate, "/steps/3"), (gate_without_approval, "/steps/3/gate"),
            (approval_names_other_gate, "/steps/3/done_when/0/gate"), (max_visits_zero, "/steps/1/max_visits"),
            (first_step_not_strategy, "/steps/0/id"), (unknown_loop_id, "/steps/2/loop"),
            (loop_without_loop_mode, "/loop_mode"), (loop_mode_without_loop_step, "/loop_mode"),
            (missing_check_param, "/steps/1/done_when/0"), (foreign_check_param, "header"),
            (input_leaves_package, "/steps/1/inputs/0"), (unknown_placeholder, "/steps/2/outputs/0"),
            (named_set_as_output, "/steps/1/outputs/0"), (implement_variant_missing, "/steps/4/file"),
            (map_file_outside_implement, "/steps/1/file"), (form_not_in_flow, "/steps/3/applies_when"),
            (probe_value_unknown, "/steps/5/applies_when"), (probe_without_not, "/steps/5/applies_when"),
            (strategy_not_run_once, "/steps/0"), (no_steps, "/steps"), (file_outside_skills, "/steps/1/file"),
            (unknown_mechanism_key, "/steps/1/mechanism_key"), (empty_done_when, "/steps/1/done_when"),
            (bad_schema_id, "/schema"),
            (duplicate_gate, "/steps/5/gate: gate 'review' is already used by /steps/3"),
            (not_without_probe, "/steps/5/applies_when: probe and not go together"),
            (applies_work_type_outside_flow, "/steps/5/applies_when/work_type: 'refactor' is not a work type of this flow"),
            (empty_forms, "/forms: a flow needs at least one value"),
            (duplicate_form, "/forms/2: duplicate form 'gated'"),
            (empty_work_types, "/work_types: a flow needs at least one value"),
            (duplicate_work_type, "/work_types/2: duplicate work_type 'feature'"),
            (implement_extra_variant, "/steps/4/file/refactor: 'refactor' is not a work type of this flow"),
            (second_loop_step, "/steps/5/loop: only one step runs a loop"),
            (mechanism_step_without_key, "/steps/1/mechanism_key: the context step prints its own strategy entry"),
            (other_steps_key, "/steps/6/mechanism_key: 'audit' is not this step's entry"),
            (check_work_types_outside_flow, "/steps/4/done_when/0/work_types: 'refactor' is not a work type of this flow"),
            (check_work_types_empty, "/steps/4/done_when/0/work_types: an empty list never holds"),
            (input_without_producer,
             "/steps/6/inputs/0: required input 'evidence/{work_id}.nosuch.md' is written by no earlier step"),
            (input_written_later, "/steps/1/inputs/1: required input 'plan/{work_id}.md' is written by no earlier step"),
            (import_bad_option, "/imports/0/option"),
            (import_named_set, "/imports/0/path"),
        ]
        for mutate, expected in cases:
            with self.subTest(case=mutate.__name__):
                broken = copy.deepcopy(base)
                mutate(broken)
                errors = manifest.validate_flow(broken, REPO, check_files=False)
                self.assertTrue(any(expected in e for e in errors), _errors_text(errors))

    def test_validate_flow_clean_twins_of_the_new_rules(self):
        base = textio.read_json(FIXTURES / "fixture.json")
        filtered = copy.deepcopy(base)
        filtered["steps"][4]["done_when"][0]["work_types"] = ["feature"]  # the RED only for feature work
        optional = copy.deepcopy(base)
        optional["steps"][6]["inputs"] = ["@source", "evidence/{work_id}.nosuch.md?"]
        imported = copy.deepcopy(base)
        imported["imports"] = [{"path": "notes/{work_id}.md", "option": "--notes-file", "status": "approved"}]
        imported["steps"][1]["inputs"] = ["request.md", "notes/{work_id}.md#body"]
        for name, flow in (("check work_types", filtered), ("optional input", optional), ("import", imported)):
            with self.subTest(case=name):
                errors = manifest.validate_flow(flow, REPO, check_files=False)
                self.assertEqual(errors, [], _errors_text(errors))

    def test_validate_flow_survives_garbage(self):
        for garbage in [None, [], "flow", {"steps": "x"}, {"steps": [None, 3]}, {"steps": [{"done_when": [7]}]}]:
            with self.subTest(garbage=garbage):
                errors = manifest.validate_flow(garbage, REPO, check_files=True)
                self.assertTrue(errors)
                self.assertTrue(all(isinstance(e, str) for e in errors))


class TestFixtureRoot(TempRoot):
    def test_fixture_flow_validates_with_files(self):
        self.assertEqual(manifest.flow_ids(self.root), ["fixture"])
        flow = manifest.load_flow(self.root, "fixture")
        errors = manifest.validate_flow(flow, self.root, check_files=True)
        self.assertEqual(errors, [], _errors_text(errors))
        used = {check["check"] for step in flow["steps"] for check in step["done_when"]}
        self.assertEqual(used, CONTRACT_CHECKS, "the fixture should exercise every check type")

    def test_missing_step_file_fails_only_with_check_files(self):
        (self.root / "skills" / "fixture" / "steps" / "implement-bugfix.md").unlink()
        flow = manifest.load_flow(self.root, "fixture")
        self.assertEqual(manifest.validate_flow(flow, self.root, check_files=False), [])
        errors = manifest.validate_flow(flow, self.root, check_files=True)
        self.assertTrue(any("/steps/4/file/bugfix" in e and "implement-bugfix.md" in e for e in errors),
                        _errors_text(errors))

    def test_step_file_name_case_must_match(self):
        # Windows and default macOS file systems ignore case; Linux and the release archives do not.
        steps = self.root / "skills" / "fixture" / "steps"
        _rename(steps / "implement-bugfix.md", steps / "Implement-Bugfix.md")
        flow = manifest.load_flow(self.root, "fixture")
        errors = manifest.validate_flow(flow, self.root, check_files=True)
        self.assertTrue(any(e.startswith("/steps/4/file/bugfix: missing step file") for e in errors),
                        _errors_text(errors))
        _rename(steps / "Implement-Bugfix.md", steps / "implement-bugfix.md")
        self.assertEqual(manifest.validate_flow(flow, self.root, check_files=True), [])  # clean twin
        _rename(self.root / "skills" / "fixture", self.root / "skills" / "Fixture")
        errors = manifest.validate_flow(flow, self.root, check_files=True)
        self.assertTrue(any(e.startswith("/steps/0/file: missing step file") for e in errors), _errors_text(errors))

    def test_loop_role_file_case_must_match(self):
        shutil.copytree(str(SCHEMAS), str(self.root / "flows" / "schemas"))
        agents = self.root / "agents"
        agents.mkdir()
        for name in ("spec-plan-author.md", "spec-plan-critic.md"):
            shutil.copyfile(str(REPO / "agents" / name), str(agents / name))
        loop = manifest.load_loop(self.root, "spec-plan")
        self.assertEqual(manifest.validate_loop(loop, self.root, check_files=True), [])
        _rename(agents / "spec-plan-critic.md", agents / "SPEC-PLAN-CRITIC.md")
        errors = manifest.validate_loop(loop, self.root, check_files=True)
        self.assertTrue(any(e.startswith("/roles/critic/role_file: missing role file") for e in errors),
                        _errors_text(errors))
        _rename(self.root / "flows" / "schemas" / "critic.schema.json",
                self.root / "flows" / "schemas" / "Critic.schema.json")
        errors = manifest.validate_loop(loop, self.root, check_files=True)
        self.assertTrue(any(e.startswith("/roles/critic/schema: missing schema file") for e in errors),
                        _errors_text(errors))

    def test_loop_and_spec_are_start_options(self):
        self.assertEqual(manifest.OPTIONS, ("intent", "quality-review", "loop", "spec"))
        flow = manifest.load_flow(self.root, "fixture")
        for option in ("loop", "spec"):
            for key in ("option", "not_option"):
                with self.subTest(option=option, condition=key):
                    broken = copy.deepcopy(flow)
                    broken["steps"][1]["applies_when"] = {key: option}
                    self.assertEqual(manifest.validate_flow(broken, self.root, check_files=True), [])
        broken = copy.deepcopy(flow)
        broken["steps"][1]["applies_when"] = {"not_option": "nosuch"}
        self.assertTrue(manifest.validate_flow(broken, self.root, check_files=True))

    def test_applies_when_imported_is_a_boolean_and_combines(self):
        flow = manifest.load_flow(self.root, "fixture")
        for value in (True, False):
            with self.subTest(value=value):
                ok = copy.deepcopy(flow)
                ok["steps"][1]["applies_when"] = {"imported": value, "form": "gated", "option": "loop"}
                self.assertEqual(manifest.validate_flow(ok, self.root, check_files=True), [])
        bad = copy.deepcopy(flow)
        bad["steps"][1]["applies_when"] = {"imported": "yes"}
        self.assertTrue(manifest.validate_flow(bad, self.root, check_files=True))

    def test_import_required_is_a_boolean(self):
        flow = manifest.load_flow(self.root, "fixture")
        item = {"path": "spec/{work_id}.md", "option": "--spec-file", "status": "approved"}
        for extra in ({}, {"required": True}, {"required": False}):
            with self.subTest(extra=extra):
                ok = copy.deepcopy(flow)
                ok["imports"] = [dict(item, **extra)]
                self.assertEqual(manifest.validate_flow(ok, self.root, check_files=True), [])
        bad = copy.deepcopy(flow)
        bad["imports"] = [dict(item, required="no")]
        self.assertTrue(manifest.validate_flow(bad, self.root, check_files=True))

    def test_step_role_must_resolve_to_a_role_file(self):
        flow = manifest.load_flow(self.root, "fixture")
        flow["steps"][1]["role"] = "spec-plan-critic"
        flow["steps"][1]["role_reads"] = ["request.md"]
        self.assertEqual(manifest.validate_flow(flow, self.root, check_files=False), [])
        errors = manifest.validate_flow(flow, self.root, check_files=True)
        self.assertTrue(any(e.startswith("/steps/1/role") and "role_file_missing:spec-plan-critic" in e
                            for e in errors), _errors_text(errors))
        agents = self.root / "agents"
        agents.mkdir()
        shutil.copyfile(str(REPO / "agents" / "spec-plan-critic.md"), str(agents / "spec-plan-critic.md"))
        self.assertEqual(manifest.validate_flow(flow, self.root, check_files=True), [])  # clean twin
        _rename(agents / "spec-plan-critic.md", agents / "SPEC-PLAN-CRITIC.md")
        errors = manifest.validate_flow(flow, self.root, check_files=True)
        self.assertTrue(any("role_file_missing:spec-plan-critic" in e for e in errors), _errors_text(errors))

    def test_step_role_must_be_an_agent_name(self):
        flow = manifest.load_flow(self.root, "fixture")
        for bad in ("../x", "Spec Plan", "", 3):
            with self.subTest(role=bad):
                broken = copy.deepcopy(flow)
                broken["steps"][1]["role"] = bad
                self.assertTrue(manifest.validate_flow(broken, self.root, check_files=False))

    def test_role_reads_needs_a_role(self):
        flow = manifest.load_flow(self.root, "fixture")
        flow["steps"][1]["role_reads"] = ["request.md"]
        errors = manifest.validate_flow(flow, self.root, check_files=False)
        self.assertTrue(any(e.startswith("/steps/1/role_reads") and "role" in e for e in errors),
                        _errors_text(errors))
        flow["steps"][1]["role"] = "spec-plan-critic"
        self.assertEqual(manifest.validate_flow(flow, self.root, check_files=False), [])  # clean twin
        for bad in (["@source"], ["context.md?"], ["../x"], ["spec/{work_id}.md", "spec/{work_id}.md"]):
            with self.subTest(reads=bad):
                broken = copy.deepcopy(flow)
                broken["steps"][1]["role_reads"] = bad
                self.assertTrue(manifest.validate_flow(broken, self.root, check_files=False))

    def test_load_flow_refuses_unknown_and_invalid_manifests(self):
        for bad_id in ["nosuch", "_shared", "../flows/fixture", "Fixture", "", "loops/spec-plan"]:
            with self.subTest(flow=bad_id):
                with self.assertRaises(textio.SdlcError) as caught:
                    manifest.load_flow(self.root, bad_id)
                self.assertEqual(caught.exception.code, 2)
                self.assertTrue(caught.exception.message.startswith("unknown_flow:"))
        target = self.root / "flows" / "fixture.json"
        for name, text in [("not json", "{"), ("duplicate key", '{"id": "fixture", "id": "fixture"}'),
                           ("wrong id", target.read_text(encoding="utf-8").replace('"id": "fixture"', '"id": "other"')),
                           ("NaN", '{"id": NaN}')]:
            with self.subTest(case=name):
                textio.write_text_atomic(target, text)
                with self.assertRaises(textio.SdlcError) as caught:
                    manifest.load_flow(self.root, "fixture")
                self.assertEqual(caught.exception.code, 2)
                self.assertTrue(caught.exception.message.startswith("manifest_invalid:flows/fixture.json"),
                                caught.exception.message)

    def test_crlf_and_bom_checkout_loads_the_same_manifest(self):
        # Review focus 1: a Windows checkout (CRLF) or an editor's BOM must not change what loads.
        original = manifest.load_flow(self.root, "fixture")
        target = self.root / "flows" / "fixture.json"
        target.write_bytes(b"\xef\xbb\xbf" + target.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(manifest.load_flow(self.root, "fixture"), original)

    def test_load_shared_and_loop_errors(self):
        with self.assertRaises(textio.SdlcError) as caught:
            manifest.load_loop(self.root, "nosuch")
        self.assertEqual((caught.exception.code, caught.exception.message), (2, "unknown_loop:nosuch"))
        (self.root / "flows" / "_shared.json").unlink()
        with self.assertRaises(textio.SdlcError) as caught:
            manifest.load_shared(self.root)
        self.assertEqual((caught.exception.code, caught.exception.message),
                         (2, "manifest_missing:flows/_shared.json"))
        textio.write_text_atomic(self.root / "flows" / "_shared.json", '{"schema": "agentic-sdlc/shared@1"}\n')
        with self.assertRaises(textio.SdlcError) as caught:
            manifest.load_shared(self.root)
        self.assertTrue(caught.exception.message.startswith("manifest_invalid:flows/_shared.json"))


class TestLoop(unittest.TestCase):
    def setUp(self):
        self.loop = manifest.load_loop(REPO, "spec-plan")

    def test_loop_definition_modes_and_caps(self):
        self.assertEqual(set(self.loop["modes"]), LOOP_MODES)
        caps = self.loop["caps"]
        self.assertEqual(caps["max_rounds"], 3)
        self.assertEqual(caps["hard_max_rounds"], 5)
        self.assertLessEqual(caps["max_rounds"], caps["hard_max_rounds"])
        shared = manifest.load_shared(REPO)["caps"]
        self.assertEqual((caps["max_rounds"], caps["hard_max_rounds"], caps["role_reentry"]),
                         (shared["loop_max_rounds"], shared["loop_hard_max_rounds"], shared["loop_role_reentry"]))

    def test_loop_role_order_per_mode(self):
        def order(mode, part):
            return [(step["role"], step["author_mode"]) for step in self.loop["modes"][mode][part]]

        self.assertEqual(order("spec+plan", "first_round"), [("author-spec", "spec"), ("author-plan", "plan")])
        self.assertEqual(order("spec+plan", "revise"), [("author-spec", "revise"), ("author-plan", "revise")])
        self.assertEqual(order("spec", "first_round"), [("author-spec", "spec")])
        self.assertEqual(order("plan", "first_round"), [("author-plan", "plan")])
        # design §5.8 / §5.19: bugfix drafts no spec; its plan carries ## Bug and ## Acceptance Criteria.
        self.assertEqual(order("bugfix-plan", "first_round"), [("author-plan", "bugfix-plan")])
        self.assertEqual(order("bugfix-plan", "revise"), [("author-plan", "revise")])
        self.assertEqual(self.loop["modes"]["spec+plan"]["artifacts"], ["spec", "plan"])
        self.assertEqual(self.loop["modes"]["bugfix-plan"]["artifacts"], ["plan"])
        self.assertEqual(self.loop["later_rounds"], ["critic", "revise"])
        self.assertTrue(self.loop["final_critic"])
        self.assertEqual(self.loop["draft_check"]["before"], "critic")
        self.assertEqual(self.loop["finish"], "ingest-draft --assemble")
        self.assertEqual(self.loop["issue_key"], ["target", "category", "where"])

    def test_loop_roles_files_and_stop_reasons(self):
        roles = self.loop["roles"]
        self.assertEqual(roles["author-spec"]["role_file"], "agents/spec-plan-author.md")
        self.assertEqual(roles["author-plan"]["role_file"], "agents/spec-plan-author.md")
        self.assertEqual(roles["critic"]["role_file"], "agents/spec-plan-critic.md")
        self.assertTrue(roles["critic"]["fresh"])
        self.assertEqual(roles["critic"]["mechanism_key"], "draft.critic")
        self.assertEqual(roles["critic"]["schema"], "flows/schemas/critic.schema.json")
        self.assertEqual(self.loop["result_schema"], "flows/schemas/draft-result.schema.json")
        result_reasons = manifest.load_schema("draft-result")["properties"]["stopReason"]["enum"]
        self.assertEqual(sorted(self.loop["stop"]), sorted(result_reasons))
        self.assertEqual(self.loop["files"]["critic"], "draft/critic.r{round}.json")
        self.assertEqual(self.loop["files"]["prompt"], "draft/prompts/{role}.r{round}.md")
        errors = manifest.validate_loop(self.loop, REPO, check_files=True)
        self.assertEqual(errors, [], _errors_text(errors))

    def test_later_rounds_read_the_previous_rounds_drafts(self):
        # Design §5.9.1: the round-1 critic reads plan.r0.md with validator.r1. Before critic round N only
        # the drafts of round N-1 exist (round N's revise runs after the critic), so draft-check --round N
        # reads them too and writes validator.rN.
        self.assertEqual(self.loop["drafts_read"], "previous-round")
        self.assertEqual(self.loop["draft_check"]["writes"], "validator")
        self.assertEqual(self.loop["files"]["validator"], "draft/validator.r{round}.json")

    def test_author_roles_write_decision_points(self):
        # Design §5.8: decision points travel to the gate; each author writes its own optional file, so
        # the spec and plan authors of one round never overwrite each other.
        roles = self.loop["roles"]
        for name in ("author-spec", "author-plan"):
            with self.subTest(role=name):
                self.assertEqual(roles[name]["also_writes"], ["decisions"])
        self.assertNotIn("also_writes", roles["critic"])
        self.assertEqual(self.loop["files"]["decisions"], "draft/decisions.{role}.r{round}.json")
        produced = {role["writes"] for role in roles.values()}
        produced |= {key for role in roles.values() for key in role.get("also_writes", [])}
        produced.add(self.loop["draft_check"]["writes"])
        self.assertEqual(produced, set(self.loop["files"]) - set(manifest.LOOP_RUNNER_FILES))

    def test_validate_loop_rejects(self):
        def rounds_over_hard(loop):
            loop["caps"]["max_rounds"] = 6

        def unknown_role(loop):
            loop["modes"]["spec"]["first_round"][0]["role"] = "editor"

        def writes_unknown_file(loop):
            loop["roles"]["critic"]["writes"] = "verdict"

        def artifacts_mismatch(loop):
            loop["modes"]["bugfix-plan"]["artifacts"] = ["spec", "plan"]

        def missing_mode(loop):
            del loop["modes"]["plan"]

        def missing_role_file(loop):
            loop["roles"]["critic"]["role_file"] = "agents/no-such-critic.md"

        def revise_out_of_order(loop):
            loop["modes"]["spec+plan"]["revise"].reverse()

        def draft_check_writes_unknown(loop):
            loop["draft_check"]["writes"] = "verdict"

        def no_critic_role(loop):
            del loop["roles"]["critic"]

        def also_writes_unknown(loop):
            loop["roles"]["author-spec"]["also_writes"] = ["notes"]

        def also_writes_own_file(loop):
            loop["roles"]["author-spec"]["also_writes"] = ["spec"]

        def decisions_without_writer(loop):
            for role in ("author-spec", "author-plan"):
                del loop["roles"][role]["also_writes"]

        def drafts_read_current(loop):
            loop["drafts_read"] = "current-round"

        cases = [(rounds_over_hard, "/caps/max_rounds"), (unknown_role, "/modes/spec/first_round/0/role"),
                 (writes_unknown_file, "/roles/critic/writes"), (artifacts_mismatch, "/modes/bugfix-plan/artifacts"),
                 (missing_mode, "/modes/plan"), (missing_role_file, "/roles/critic/role_file"),
                 (revise_out_of_order, "/modes/spec+plan/revise: revise runs the first round's roles again"),
                 (draft_check_writes_unknown, "/draft_check/writes: 'verdict' is not a key of files"),
                 (no_critic_role, "/roles: the later rounds need a critic role"),
                 (also_writes_unknown, "/roles/author-spec/also_writes/0: 'notes' is not a key of files"),
                 (also_writes_own_file, "/roles/author-spec/also_writes/0: 'spec' is already what the role writes"),
                 (decisions_without_writer, "/files/decisions: no role and no draft-check writes it"),
                 (drafts_read_current, "/drafts_read")]
        for mutate, expected in cases:
            with self.subTest(case=mutate.__name__):
                broken = copy.deepcopy(self.loop)
                mutate(broken)
                errors = manifest.validate_loop(broken, REPO, check_files=True)
                self.assertTrue(any(expected in e for e in errors), _errors_text(errors))


def _walk(node, where):
    yield where, node
    for name, sub in node.get("properties", {}).items():
        for item in _walk(sub, "%s/properties/%s" % (where, name)):
            yield item
    if isinstance(node.get("additionalProperties"), dict):
        for item in _walk(node["additionalProperties"], where + "/additionalProperties"):
            yield item
    if isinstance(node.get("items"), dict):
        for item in _walk(node["items"], where + "/items"):
            yield item


def _types(node):
    declared = node.get("type")
    if declared is None:
        return None
    return set(declared if isinstance(declared, list) else [declared])


class TestSchemas(unittest.TestCase):
    def test_schemas_parse_and_self_consistent(self):
        files = sorted(p.name for p in SCHEMAS.glob("*.json"))
        self.assertEqual(files, sorted(name + ".schema.json" for name in SCHEMA_IDS))
        for name, schema_id in SCHEMA_IDS.items():
            with self.subTest(schema=name):
                loaded = json.loads((SCHEMAS / (name + ".schema.json")).read_text(encoding="utf-8"))
                schema.check_schema(loaded)  # raises on any keyword schema.validate does not support
                self.assertEqual(loaded["$id"], schema_id)
                self.assertTrue(loaded.get("title") and loaded.get("description"))
                self.assertEqual(manifest.load_schema(name), loaded)
                for where, node in _walk(loaded, "#"):
                    types = _types(node)
                    required = node.get("required", [])
                    self.assertEqual(len(required), len(set(required)), where)
                    if node.get("additionalProperties") is False:
                        missing = set(required) - set(node.get("properties", {}))
                        self.assertFalse(missing, "%s requires undeclared %s" % (where, sorted(missing)))
                    if types is not None:
                        for value in node.get("enum", []) + ([node["const"]] if "const" in node else []):
                            ok = any(schema.validate(value, {"type": t}) == [] for t in types)
                            self.assertTrue(ok, "%s: %r is not %s" % (where, value, sorted(types)))
                        for keyword, kind in (("pattern", "string"), ("minLength", "string"), ("items", "array"),
                                              ("properties", "object"), ("required", "object")):
                            if keyword in node:
                                self.assertIn(kind, types, "%s: %s on a non-%s" % (where, keyword, kind))
                        for keyword in ("minimum", "maximum"):
                            if keyword in node:
                                self.assertTrue(types & {"integer", "number"}, where)

    def test_check_schema_negative_control(self):
        for bad in [{"oneOf": []}, {"$ref": "#/x"}, {"properties": {"a": {"minItems": 1}}},
                    {"patternProperties": {}}]:
            with self.subTest(schema=bad):
                with self.assertRaises(ValueError):
                    schema.check_schema(bad)

    def test_schema_enums_match_manifest_constants(self):
        flow = manifest.load_schema("flow")
        step = flow["properties"]["steps"]["items"]
        self.assertEqual(set(step["properties"]["done_when"]["items"]["properties"]["check"]["enum"]),
                         CONTRACT_CHECKS)
        self.assertEqual(manifest.CHECK_TYPES, frozenset(CONTRACT_CHECKS))
        self.assertEqual(set(manifest.CHECK_PARAMS), CONTRACT_CHECKS)
        self.assertEqual(step["properties"]["mechanism_key"]["enum"], CONTRACT_MECHANISM_KEYS + [None])
        self.assertEqual(list(manifest.MECHANISM_KEYS), CONTRACT_MECHANISM_KEYS)
        conditions = step["properties"]["applies_when"]["properties"]
        self.assertEqual(conditions["option"]["enum"], list(manifest.OPTIONS))
        self.assertEqual(conditions["not_option"]["enum"], list(manifest.OPTIONS))
        self.assertEqual(conditions["imported"], {"type": "boolean"})
        self.assertEqual(set(flow["properties"]["loop_mode"]["enum"]) - {None}, LOOP_MODES)
        strategy = manifest.load_schema("strategy")
        self.assertEqual(list(strategy["properties"]["entries"]["properties"]), CONTRACT_MECHANISM_KEYS)
        entry = strategy["properties"]["entries"]["properties"]["draft"]
        self.assertEqual(entry["properties"]["mechanism"]["enum"], CONTRACT_MECHANISMS)
        self.assertEqual(list(manifest.MECHANISMS), CONTRACT_MECHANISMS)
        self.assertEqual(strategy["properties"]["runtime"]["enum"], list(manifest.RUNTIMES))
        shared = manifest.load_schema("shared")
        self.assertEqual(sorted(shared["properties"]["runtimes"]["required"]), sorted(PINNED_RUNTIMES))
        self.assertEqual(sorted(shared["properties"]["caps"]["required"]), sorted(PINNED_CAPS))
        for name in ("draft-result", "sidecar"):
            with self.subTest(schema=name):
                self.assertEqual(set(manifest.load_schema(name)["properties"]["mode"]["enum"]), LOOP_MODES)
        loop = manifest.load_schema("loop")
        self.assertEqual(set(loop["properties"]["modes"]["required"]), LOOP_MODES)

    def _note(self):
        return {"target": "plan", "category": "coverage", "severity": "high", "kind": "gap",
                "whatsMissing": "AC2 has no task", "where": "plan ## Tasks", "fix": "add a task naming AC2"}

    def _result(self):
        return {
            "schema": "agentic-sdlc/draft-result@1", "mode": "spec+plan", "engine": "runner-loop",
            "spec": {"markdown": "## Problem\nx\n"}, "plan": {"markdown": "## Task 1\nx\n"},
            "decisionPoints": [{"id": "DP1", "question": "Which store?", "options": ["a", "b"],
                                "recommendation": "a"}],
            "residualCriticNotes": [self._note()], "rounds": 3, "finalVerdict": "issues",
            "stopReason": "max-rounds", "critic": "fresh",
        }

    def test_draft_result_schema_accepts_example_and_rejects_bad_severity(self):
        result_schema = manifest.load_schema("draft-result")
        self.assertEqual(schema.validate(self._result(), result_schema), [])
        bugfix = self._result()
        bugfix.update(mode="bugfix-plan", spec=None, residualCriticNotes=[], finalVerdict="clean",
                      stopReason="clean", critic="degraded", decisionPoints=[])
        self.assertEqual(schema.validate(bugfix, result_schema), [])
        bad = self._result()
        bad["residualCriticNotes"][0]["severity"] = "blocker"
        errors = schema.validate(bad, result_schema)
        self.assertEqual([e.split(":")[0] for e in errors], ["/residualCriticNotes/0/severity"])
        for field, value in [("stopReason", "budget"), ("critic", "skipped"), ("mode", "spec-plan"),
                             ("schema", "agentic-sdlc/draft-result@2"), ("spec", {"markdown": ""}),
                             ("finalVerdict", "ok")]:
            with self.subTest(field=field):
                broken = self._result()
                broken[field] = value
                errors = schema.validate(broken, result_schema)
                self.assertTrue(any(e.startswith("/" + field) for e in errors), _errors_text(errors))
        extra = self._result()
        extra["notes"] = "x"
        self.assertTrue(schema.validate(extra, result_schema))

    def test_critic_schema_accepts_example_and_rejects_bad_kind(self):
        critic_schema = manifest.load_schema("critic")
        critic = {"verdict": "issues", "issues": [self._note()], "coverageCheck": "AC1 covered"}
        self.assertEqual(schema.validate(critic, critic_schema), [])
        self.assertEqual(schema.validate({"verdict": "clean", "issues": []}, critic_schema), [])
        # A model adding an explanatory field is not a malformed critic (design §5.9.1 re-entry cap).
        chatty = copy.deepcopy(critic)
        chatty["summary"] = "two gaps"
        chatty["issues"][0]["evidence"] = "grep shows no task"
        self.assertEqual(schema.validate(chatty, critic_schema), [])
        for field, value in [("kind", "nit"), ("target", "fit"), ("severity", "blocker")]:
            with self.subTest(field=field):
                broken = copy.deepcopy(critic)
                broken["issues"][0][field] = value
                errors = schema.validate(broken, critic_schema)
                self.assertEqual([e.split(":")[0] for e in errors], ["/issues/0/" + field])
        missing = copy.deepcopy(critic)
        del missing["issues"][0]["where"]
        self.assertTrue(schema.validate(missing, critic_schema))
        self.assertTrue(schema.validate({"verdict": "clean"}, critic_schema))

    def test_sidecar_and_strategy_schemas_accept_examples(self):
        sidecar = {
            "schema": "agentic-sdlc/sidecar@1", "artifact": "plan/add-export.md", "body_fingerprint": "a" * 64,
            "mode": "bugfix-plan", "engine": "runner-loop", "rounds": 1, "finalVerdict": "clean",
            "stopReason": "clean", "critic": "fresh", "decisionPoints": [], "residualCriticNotes": [],
        }
        sidecar_schema = manifest.load_schema("sidecar")
        self.assertEqual(schema.validate(sidecar, sidecar_schema), [])
        for field, value in [("artifact", "../plan/x.md"), ("body_fingerprint", "A" * 64), ("artifact", "notes/x.md")]:
            with self.subTest(field=field, value=value):
                broken = dict(sidecar)
                broken[field] = value
                self.assertTrue(schema.validate(broken, sidecar_schema))
        strategy = {
            "schema": "agentic-sdlc/strategy@1", "runtime": "codex",
            "capabilities": {"workflow": "no", "subagent": "yes", "team": "no"},
            "entries": {"draft": {"mechanism": "runner-loop", "reason": "", "source": "default"},
                        "security": {"mechanism": "inline-degraded", "reason": "no sub-agent tool",
                                     "source": "override"}},
            "degraded": [{"key": "security", "capability": "subagent", "reason": "denied"}],
        }
        strategy_schema = manifest.load_schema("strategy")
        self.assertEqual(schema.validate(strategy, strategy_schema), [])
        for mutate in ("runtime", "capability", "mechanism", "key"):
            with self.subTest(mutate=mutate):
                broken = copy.deepcopy(strategy)
                if mutate == "runtime":
                    broken["runtime"] = "vim"
                elif mutate == "capability":
                    broken["capabilities"]["workflow"] = "maybe"
                elif mutate == "mechanism":
                    broken["entries"]["draft"]["mechanism"] = "fork"
                else:
                    broken["entries"]["deploy"] = broken["entries"]["draft"]
                self.assertTrue(schema.validate(broken, strategy_schema))

    def test_load_schema_returns_a_copy(self):
        first = manifest.load_schema("critic")
        first["properties"]["verdict"]["enum"].append("maybe")
        self.assertNotIn("maybe", manifest.load_schema("critic")["properties"]["verdict"]["enum"])
        with self.assertRaises(textio.SdlcError):
            manifest.load_schema("../flows/_shared")


class TestHelpers(unittest.TestCase):
    def test_expand_work_id(self):
        state = {"work_id": "add-export"}
        self.assertEqual(manifest.expand("spec/{work_id}.md", state), "spec/add-export.md")
        self.assertEqual(manifest.expand("evidence/{work_id}.{work_id}.md", state),
                         "evidence/add-export.add-export.md")
        self.assertEqual(manifest.expand("context.md", {}), "context.md")

    def test_expand_refuses_unknown_placeholders_and_bad_work_ids(self):
        for template, state, message in [
            ("spec/{slug}.md", {"work_id": "a"}, "unknown_placeholder:slug"),
            ("spec/{work_id}.md", {}, "invalid_work_id"),
            ("spec/{work_id}.md", {"work_id": "../x"}, "invalid_work_id"),
            ("spec/{work_id.md", {"work_id": "a"}, "unknown_placeholder:spec/{work_id.md"),
        ]:
            with self.subTest(template=template):
                with self.assertRaises(textio.SdlcError) as caught:
                    manifest.expand(template, state)
                self.assertEqual((caught.exception.code, caught.exception.message), (2, message))

    def test_parse_ref(self):
        self.assertEqual(manifest.parse_ref("@source"),
                         {"set": "@source", "path": None, "body": False, "optional": False})
        self.assertEqual(manifest.parse_ref("spec/{work_id}.md#body?"),
                         {"set": None, "path": "spec/{work_id}.md", "body": True, "optional": True})
        self.assertEqual(manifest.parse_ref("feedback.jsonl?"),
                         {"set": None, "path": "feedback.jsonl", "body": False, "optional": True})
        for bad in ["@everything", "../x.md", "/abs.md", "a//b.md", "a/./b.md", ".lock", "a#body#body",
                    "x?y.md", "C:/x.md", "a\\b.md", "{slug}.md", "a/{work_id", ""]:
            with self.subTest(ref=bad):
                with self.assertRaises(ValueError):
                    manifest.parse_ref(bad)


class TestFlowFiles(unittest.TestCase):
    def test_flow_files_are_lf_utf8_json(self):
        files = sorted(FLOWS.rglob("*.json")) + sorted(FIXTURES.rglob("*.json"))
        self.assertGreaterEqual(len(files), 21)
        for path in files + sorted(FIXTURES.rglob("*.md")):
            with self.subTest(path=path.relative_to(REPO).as_posix()):
                data = path.read_bytes()
                self.assertNotIn(b"\r", data)
                self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
                self.assertTrue(data.endswith(b"\n") and not data.endswith(b"\n\n"))
                text = data.decode("utf-8")
                if path.suffix == ".json":
                    json.loads(text)

    def test_plugin_root_holds_the_manifests(self):
        self.assertEqual(paths.plugin_root(), REPO)
        self.assertTrue((paths.plugin_root() / "flows" / "_shared.json").is_file())


if __name__ == "__main__":
    unittest.main()
