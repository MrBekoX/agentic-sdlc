"""Pipeline v2.1 zero-skill delegation: static checks for the binding contracts C1-C13.

`agentic-sdlc-pipeline` used to hand Steps 8-13 to a focused skill through a `Skill` call and
gate security and the final audit through `security-audit` / `implementation-control`. In v2.1
the pipeline invokes none of the six focused skills. It reads a shared work-type core file
(`skills/<skill>/references/core.md`), dispatches `security-reviewer` and `implementation-auditor`
directly, calls `dispatch-strategy` once at kickoff, before Step 1, and records an approval receipt
before any source or test edit.

What this suite pins, as literals taken from the contracts (never from the file under test):
- C1: the four core files exist, carry the depth blocks byte-identical to their SKILL.md (parity),
  hold none of the envelope (purity), keep the moved steps and sections, and are loaded by both
  entry points; the SKILL.md stubs keep the original step numbers.
- C2-C5, C8-C11, C13: the exact sentences, headings and markers the pipeline, playbook, roles and
  focused skills must carry, and the exact old wording that must be gone.
- C12: a literal sweep that bans stale delegation wording from the pipeline, its read set and the
  docs.
- C16 items 13-21: the fix-round text (amended approval receipt, TDD file write rule, core
  mapping in SKILL.md, the `Envelope reports:` auditor section, markers-once, feedback-triage and
  completion-claim-gate scope, and the minor wording fixes).
- C17 items 8-16: "at kickoff, before Step 1" for the dispatch call, kickoff item 2 as selection
  only with the core read and mapping in the Work-type core gate paragraph, the playbook
  pre-approval clause, markers once per gate occurrence, the SKILL.md TDD write clause, "no
  Finalize evidence" in the docs, the closed Skill-call list in docs/skill-boundaries.md, the
  docs/testing.md strict-key rows and the CHANGELOG 0.6.0 known limitations.
Every comparison asserts PRESENCE first, so deleting the thing a check protects fails it instead
of passing it vacuously.

What it cannot prove: these are text checks. It is a drift gate, not a truth gate - it shows the
instructions say the right thing, not that a model follows them. Run order, the RED-before-source
ordering, the single `dispatch-strategy` call and the reviewer/auditor results are graded offline
by `scripts/run_procedure_eval.py` strict mode and by live runs, not here.
"""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

PIPELINE = "skills/agentic-sdlc-pipeline/SKILL.md"
PLAYBOOK = "skills/agentic-sdlc-pipeline/playbook.md"
TEMPLATES = "skills/agentic-sdlc-pipeline/templates.md"
DISPATCH = "skills/dispatch-strategy/SKILL.md"
AUDITOR = "agents/implementation-auditor.md"
REVIEWER = "agents/security-reviewer.md"
SPEC_PLAN_AUTHOR = "agents/spec-plan-author.md"
CONTROL = "skills/implementation-control/SKILL.md"
GRADER = "scripts/run_procedure_eval.py"

WORK_TYPE_SKILLS = ("feature-build", "root-cause-fix", "safe-refactor", "test-authoring")
FOCUSED_SKILLS = WORK_TYPE_SKILLS + ("security-audit", "implementation-control")


def skill_md(skill):
    return f"skills/{skill}/SKILL.md"


def core_md(skill):
    return f"skills/{skill}/references/core.md"


# --- C7 forbidden patterns 2 and 3 (used by C1 purity, C5 and C12 set B) ---
# Pattern 2 covers `/`, `\` and the JSON-doubled `\\` separators.
FOCUSED_SKILL_PATH = re.compile(
    r"(?:feature-build|root-cause-fix|safe-refactor|test-authoring|security-audit|implementation-control)"
    r"[\\/]+SKILL\.md")  # one character class: the old (?:[\\/]|\\\\)+ alternation backtracks exponentially
FOCUSED_ADAPTER_GATE = re.compile(
    r"Adapter Gate:\s*(?:feature-build|root-cause-fix|safe-refactor|test-authoring|security-audit|implementation-control)\b")

# --- C1 ---
COPIED_BLOCKS = (
    "## Invariant",
    "## Tripwires",
    "## Proof",
    "## Excuse → check",
    "## Depth contract",
    "## Excuse -> check",
    "## No placeholders",
    "## Shallow example (reject this)",
)

CORE_INTRO = (
    "Shared core for `{skill}` work. Two entry points read this file: the standalone `{skill}` "
    "skill, and `agentic-sdlc-pipeline` Steps 8–13 for this work type. It holds only what both "
    "need — the depth rules and the implementation steps. The caller owns the envelope: the "
    "mechanism decision, spec and plan, scope lock, approval, the final audit, and the final report."
)

READ_SENTENCE = (
    "Read [references/core.md](references/core.md) before step {n} and run the steps marked "
    "\"core step\" exactly as its `## Core steps` section writes them. Resolve the link from this "
    "installed skill's directory. In Claude Code, use `Read`; in Codex, use the available "
    "file-reading tool for the exact installed reference path. Reload it after resume, compaction, "
    "or a supplied summary."
)

FIRST_MOVED_STEP = {"feature-build": 5, "root-cause-fix": 6, "safe-refactor": 1, "test-authoring": 1}

# Case-sensitive. None of these may appear in a core file.
PURITY_TOKENS = (
    "dispatch-strategy",
    "implementation-control",
    "`Skill`",
    "Final Response",
    "SKILL.md",
    "spec-plan-author",
    "spec-plan-critic",
    "contract 02",
    "contract 03",
    "Goal Lock",
    "Call-order guard",
    "Orchestration",
)

# Bold step names in `## Core steps` order (old SKILL.md numbering at 4262a19). test-authoring's
# Flow steps carry no bold name, so only its count is fixed.
CORE_STEP_NAMES = {
    "feature-build": ("Failing test", "Implementation + verification", "Security analysis",
                      "Refactor", "Documentation"),
    "root-cause-fix": ("TDD / Regression test (RED)", "Implementation (GREEN)", "Test Run",
                       "Security Analysis (#1)", "Refactor", "Retest", "Final Review"),
    "safe-refactor": ("Characterize current behavior", "Small steps", "No behavior change",
                      "Security re-check"),
    "test-authoring": None,
}
CORE_STEP_COUNT = {"feature-build": 5, "root-cause-fix": 7, "safe-refactor": 4, "test-authoring": 5}

# Body text the moved steps keep ("Keep each step's name in bold and its body text"), as sentences
# from 4262a19. Only the O2 replacement may reword a step.
CORE_STEP_BODIES = {
    "feature-build": (
        "identify the project's available test command, write the smallest test for the requested "
        "behavior and run it; show RED caused by the missing behavior before implementation.",
        "A missing runner does not authorize installing packages: use an already available "
        "equivalent that executes the intended tests, or report the prerequisite for approval.",
        "Preserve failure exit status; a fallback runner must exit nonzero when an assertion fails, "
        "not catch failures and return success.",
        "follow the existing architecture and conventions; only files in scope; justify new abstractions.",
        "Write interdependent code in the main loop, delegate independent fixed-pattern pieces.",
        "Make the RED test GREEN, then run the suite and show output.",
        "Use the runtime loop tool when available; otherwise record each fail -> fix -> retest cycle "
        "with command evidence.",
        "validation, authN/authZ (IDOR), secrets, injection, dependency risk, logging hygiene. "
        "Fix→re-check→retest on findings.",
        "only if needed; behavior unchanged; retest after.",
        "update stale docs, env vars, API signatures, setup.",
    ),
    "root-cause-fix": (
        "Write a failing test that reproduces the bug. **Confirm it actually fails** (show output) "
        "before writing any fix.",
        "Minimal code to pass the test. Only files in plan scope. No unrelated refactor, no "
        "scope-creep, don't break the architecture, justify any new abstraction.",
        "Run the targeted test, then the full suite where feasible. **Show real output.**",
        "**Loop A — test fail:** analyze → fix → retest. Use the runtime loop tool when available; "
        "otherwise record each fail -> fix -> retest cycle with the Loop Iteration template and "
        "command evidence. Don't proceed while red.",
        "Review the diff: input validation, auth/authorization (incl. IDOR), secret leakage, "
        "injection, race conditions, data-loss risk, permission issues, dependency risk. Mask any "
        "secret (`***MASKED***`).",
        "**Loop B — finding:** fix → re-run security analysis → re-run tests.",
        "Only necessary cleanup; behavior unchanged; improve readability, reduce duplication/complexity.",
        "Re-run the full suite after refactor; **show output**. (Loop A applies again if red.)",
        "Review `git diff`: summarize changed files, remaining risks, anything left open. Confirm "
        "only intended files changed and no secrets are present.",
    ),
    "safe-refactor": (
        "identify the behavior that must not change. If tests don't cover it, **add "
        "characterization tests first** and see them pass (show output). This is the safety net.",
        "one structural change at a time (extract, rename, dedupe, simplify). After **each** step "
        "run the relevant tests and **show output**. Use the runtime loop tool when available; "
        "otherwise record each fail -> fix -> retest cycle with command evidence.",
        "if a \"refactor\" alters behavior, stop: that is a feature/fix, not a refactor.",
        "if the refactor touches auth/config/data paths.",
    ),
    "test-authoring": (
        "1. Identify what behavior needs proving and at which level (unit/integration/regression/e2e).",
        # C16.21 rewords step 2 so it no longer demands a failing run before step 3's mutation.
        "2. Write the test; step 3 shows how to prove it can fail.",
        "4. Run targeted tests, then the suite; show output. Use the runtime loop tool when "
        "available; otherwise record each fail -> fix -> retest cycle with command evidence.",
        "5. Review: are the assertions meaningful? Edge cases covered? Any flaky timing/order dependence?",
    ),
}

# O2 replacement text (maintainer, 2026-10-16) and the three lines it replaces.
O2_STEP_3 = (
    "3. Make the test pass without changing production behavior. For a test of existing behavior, "
    "show it fail under a temporary mutation of the code it guards, then revert the mutation; for a "
    "characterization test, capture the baseline. If the test exposes a real production defect, "
    "stop and report it as bug-fix work instead of changing production code here."
)
O2_TDD_BULLET = (
    "- **TDD:** a test is proven by watching it fail for the reason it guards — a failing run for "
    "new expectations, or a temporary mutation for existing behavior — before it passes. Production "
    "code is not changed in test-only work."
)
O2_FORBIDDEN = "- Changing production code in test-only work."
O2_OLD = (
    "3. Implement (or fix) the minimum to pass.",
    "failing test first (RED) → see it fail → minimal code (GREEN)",
    "Implementation before the failing test for new behavior.",
)

# Moved work-type sections, as they must read in the core (block form, trailing blanks stripped).
MOVED_SECTIONS = {
    "test-authoring": {
        "## Test types": (
            "## Test types\n"
            "- **Unit** — one unit in isolation; fast; dependencies faked.\n"
            "- **Integration** — real collaboration across components/boundaries (DB, queue, HTTP).\n"
            "- **Regression** — reproduces a past bug so it can't return.\n"
            "- **E2E** — user-facing flow through the whole system."
        ),
        "## Principles": (
            "## Principles\n"
            + O2_TDD_BULLET + "\n"
            "- **Arrange / Act / Assert**; one clear reason to fail per test.\n"
            "- **Descriptive names** stating scenario + expectation (e.g. `returns_401_when_token_expired`).\n"
            "- **Test doubles:** prefer real objects; use mock/fake/stub only at true boundaries. "
            "Assert **behavior**, not the mock.\n"
            "- **Meaningful coverage:** a test that can't fail for a real reason is noise. Cover edge "
            "cases — empty/null, boundaries, error paths, authorization.\n"
            "- Prefer the smallest scope that proves the behavior; run the full suite before claiming done.\n"
            "- **Always show real test output.**"
        ),
        "## Forbidden": (
            "## Forbidden\n"
            "- \"Passed\" without output.\n"
            + O2_FORBIDDEN + "\n"
            "- Assertion-free tests, or tests asserting mocks instead of behavior.\n"
            "- Over-mocking that turns the test into a tautology."
        ),
    },
    "root-cause-fix": {
        # The template is a fenced block whose own `## ` lines would end a C1 block early, so the
        # whole heading + fence is pinned as one substring instead.
        "## Loop Iteration template": (
            "## Loop Iteration template\n"
            "```md\n"
            "# Loop Iteration\n"
            "## Trigger\n"
            "## Failed Check\n"
            "## Root Cause\n"
            "## Fix Plan\n"
            "## Applied Fix\n"
            "## Verification\n"
            "## Continue or Exit Loop\n"
            "```"
        ),
    },
    "safe-refactor": {
        "## Forbidden": (
            "## Forbidden\n"
            "- Refactoring without a passing-test safety net.\n"
            "- Mixing behavior changes into the refactor.\n"
            "- Large architectural change without approval.\n"
            "- Drive-by refactors bundled into unrelated work."
        ),
    },
    "feature-build": {},
}

LIST_STUBS = {
    "feature-build": {
        5: "5. **Failing test** — core step 1.",
        6: "6. **Implementation + verification** — core step 2.",
        7: "7. **Security analysis** — core step 3.",
        8: "8. **Refactor** — core step 4.",
        9: "9. **Documentation** — core step 5.",
    },
    "safe-refactor": {
        1: "1. **Characterize current behavior** — core step 1.",
        4: "4. **Small steps** — core step 2.",
        5: "5. **No behavior change** — core step 3.",
        6: "6. **Security re-check** — core step 4.",
    },
}
HEADING_STUBS = {
    6: "### 6. TDD / Regression test (RED) — core step 1.",
    7: "### 7. Implementation (GREEN) — core step 2.",
    8: "### 8. Test Run — core step 3.",
    9: "### 9. Security Analysis (#1) — core step 4.",
    10: "### 10. Refactor — core step 5.",
    11: "### 11. Retest — core step 6.",
    12: "### 12. Final Review — core step 7.",
}

# "Envelope steps stay verbatim": a sample of envelope lines per focused SKILL.md, literal from
# 4262a19. safe-refactor step 7 is left out on purpose - C11 rewrites its example.
ENVELOPE_LINES = {
    "feature-build": (
        "1. **Requirement analysis** — what the feature must do; who uses it; constraints.",
        "10. **Implementation control** — run **`implementation-control`** before finalizing; "
        "complete any gap and re-run. Don't give the final answer if a critical step is missing.",
    ),
    "root-cause-fix": (
        "### 5. Goal lock",
        "### 13. Implementation Control (mandatory) — run `implementation-control`",
        "**Loop C — control reports a gap:** complete the missing step → re-run "
        "`implementation-control`. **If a critical step is missing, do NOT give the final answer** "
        "— finish it or tell the user clearly.",
        "### 14. Final Response",
    ),
    "safe-refactor": (
        "2. **Define scope** — what is being restructured and what is explicitly out of scope. Use "
        "the runtime goal tool when available; otherwise write the Goal Lock template inline and "
        "treat it as the scope lock.",
        "3. **Approval gate** — for large/architectural refactors, get user approval before starting.",
    ),
    "test-authoring": (
        "## Call-order guard — dispatch-strategy first",
        "## Orchestration — fan out coverage analysis, you coordinate (consult `dispatch-strategy` first)",
    ),
}

PIPELINE_MAPPING = (
    "Read `<runtime-root>/skills/<skill>/references/core.md` for the selected work type before "
    "Step 8 and run its core steps as Steps 8–13. The core's security step is Step 11 and runs "
    "through `Agent(security-reviewer)`; its refactor step is Step 12; its retest is Step 13; a "
    "root-cause-fix core \"Final Review\" is satisfied by Step 16; a feature-build core "
    "\"Documentation\" step runs before Step 14."
)

# --- C2 ---
TDD_EVIDENCE_PATHS = (
    "docs/agentic-sdlc/<slug>/evidence/<work_id>.tdd.md",
    "docs/agentic-sdlc/evidence/<work_id>.tdd.md",
)
AUDITOR_INPUT_NEW = (
    "not the read-only `implementation-auditor` sub-agent, which receives the resolver output, the "
    "diff and the TDD evidence path in its dispatch prompt and writes nothing."
)
AUDITOR_INPUT_OLD = "which only consumes the report and resolver output as input"
# SKILL.md L172 ended the old sentence here; the new one continues with "sub-agent," (comma).
AUDITOR_INPUT_OLD_ENDING = "not the read-only `implementation-auditor` sub-agent."
FINALIZE_MARKERS = ("finalize step", "not the read-only", "per-package", "overwrit", "git-ignored",
                    "no validator")
# The C2 block format, in order, as it sits in the playbook (C14). Leading whitespace is allowed
# so the block may sit inside a list item.
TDD_EVIDENCE_FORMAT = tuple(re.compile(p, re.MULTILINE) for p in (
    r"^[ \t]*# TDD evidence — <work_id>$",
    r"^[ \t]*Work type: feature \| bugfix \| refactor \| test-only$",
    r"^[ \t]*## Run <n> — RED \| GREEN \| CHARACTERIZATION \| RETEST \| MUTATION$",
    r"^[ \t]*Command: ",
    r"^[ \t]*Exit: ",
    r"^[ \t]*Production files edited before this run: none \| <list>$",  # C16.15, RED blocks
    r"^[ \t]*Output \(last 20 lines or fewer\):$",
))
# C2: "The file is complete before `Agent(implementation-auditor)` is dispatched."
TDD_EVIDENCE_TIMING = "before `Agent(implementation-auditor)` is dispatched"

# --- C3 ---
AUDITOR_TDD_INPUT = "the TDD evidence file path supplied in the dispatch prompt"
AUDITOR_STRUCTURED_FIELDS = ("overallStatus", "checkedFlow[]", "missingSteps[]", "riskyChanges[]",
                             "requiredFixesBeforeFinal[]", "finalDecision")
# The pipeline's Agent(implementation-auditor) dispatch prompt, in the playbook's Implementation
# control section (C14). Spec and Plan may share a line; only the order is fixed.
DISPATCH_PROMPT_LABELS = ("Resolver output:", "Spec:", "Plan:", "TDD evidence:", "Diff:",
                          "Security reviews:", "Branch receipts:",
                          "Envelope reports:")  # C16.17 adds the 8th section
DISPATCH_PROMPT_DIFF = "git diff --no-ext-diff --no-textconv"
BLOCK_FINAL_RULE = re.compile(r"block-final[^\n]*(?i:do not finalize)")

# --- C4 ---
FINDINGS_HEADER = "Severity | Category | File:Line | Risk | Recommendation"
REVIEWER_OUTPUT_LINE = (
    "Findings table with this exact header: `Severity | Category | File:Line | Risk | "
    "Recommendation` (Severity is one of Critical / High / Medium / Low), then a short summary and "
    "the top fixes."
)
REVIEWER_OUTPUT_LINE_OLD = (
    "Findings table: `Severity (Critical/High/Medium/Low) | Category | File:Line | Risk | "
    "Recommendation`, then a short summary and the top fixes."
)
REVIEWER_LENS_LINES = (
    "When dispatched for one lens, review that lens and the checklist items it owns:",
    "- `injection` — injection, input validation, output encoding, file access / path traversal;",
    "- `authz-IDOR` — authorization, object-level access, data exposure, permission boundaries;",
    "- `secrets` — secrets and credentials, logging hygiene, error handling that leaks internals;",
    "- `auth` — authentication, token/session handling, rate limiting.",
    "Dependency, migration and environment-variable changes are reported by whichever lens sees the "
    "manifest or migration file. Report a lens you could not finish as incomplete; an incomplete "
    "lens or an unverified finding is not a clean review — name it as not reviewed.",
)
REVIEWER_MASKING = "keep the key name and replace only the value with `***MASKED***`"
REVIEWER_WHEN_USED = (
    "By `security-audit`, as the security lens of `feature-build` and `root-cause-fix` "
    "verification, by `agentic-sdlc-pipeline` Steps 11 and 14, or whenever a diff/feature needs an "
    "independent security pass."
)
STEP_14_LENSES = re.compile(r"injection / authz-IDOR / secrets / auth\b")
STEP_14_LENSES_OLD = "injection / authz-IDOR / secrets / data-exposure"

# --- C5 ---
CODEX_MARKERS = (
    "Codex Adapter Gate: dispatch-strategy activated",
    "Codex Adapter Gate: spec-plan-draft spec author",
    "Codex Adapter Gate: spec-plan-draft spec critic",
    "Codex Adapter Gate: spec-plan-draft plan author",
    "Codex Adapter Gate: spec-plan-draft plan critic",
    "Codex Adapter Gate: work-type core <feature|bugfix|refactor|test-only>",
    "Codex Adapter Gate: security-reviewer",
    "Codex Adapter Gate: implementation-auditor",
    "Codex Adapter Gate: completion-claim-gate",
)
# C5 rule for all runtimes; the contract does not say which pipeline file carries it. The verb is
# part of the rule, so it is matched too (case-insensitive: it may open or sit inside a sentence).
PRINT_REVIEW_RESULTS = re.compile(
    r"(?i)print the reviewer findings table and the auditor verdict as assistant text")

# --- C8, as amended by C16.13 ---
RECEIPT_SAVE = ("**Approval receipt.** Save the spec (and later the plan) with `status: reviewed` and "
                "validate it.")
RECEIPT_APPROVE = (
    "Set `status: approved` only after the user approves that Review gate — in a later turn or as an "
    "`AskUserQuestion` answer — or when the original request explicitly pre-approves the Review gates."
)
RECEIPT_DECISION_POINTS = (
    "Under pre-approval, resolve each decision point by adopting its recommendation and list it in "
    "the gate message; a decision point with no recommendation, or whose options change scope or "
    "behaviour that the request does not settle, stays unresolved and stops at the gate."
)
RECEIPT_CRITIC = (
    "A critic contradiction — a `residualCriticNotes` item that names a contradiction or a hard "
    "blocker (on Codex: an issue from the critic's last round) — stops at the gate even under "
    "pre-approval."
)
RECEIPT_NO_ANSWER = (
    "If no answer can be obtained, end the turn with a message that names the Spec Review (or Plan "
    "Review) gate, the artifact path and the open decision points."
)
RECEIPT_SILENCE = "Never treat silence or a tool error as approval."
RECEIPT_QUOTE = "Quote any pre-approval text in the gate message."
RECEIPT_NO_EDIT = ("While the spec or plan is `draft` or `reviewed`, make no source or test edit — "
                   "stop at the gate and ask.")
APPROVAL_RECEIPT = " ".join((RECEIPT_SAVE, RECEIPT_APPROVE, RECEIPT_DECISION_POINTS, RECEIPT_CRITIC,
                             RECEIPT_NO_ANSWER, RECEIPT_SILENCE, RECEIPT_QUOTE, RECEIPT_NO_EDIT))
# The C8 wording that C16.13 replaces: a blanket "never covers" rule and a quote in a "gate note".
APPROVAL_RECEIPT_OLD = (
    "quote that text in the gate note",
    "Pre-approval never covers an unresolved decision point or a critic contradiction",
)
OLD_ON_APPROVAL = (
    "On approval, **write the spec to `docs/agentic-sdlc/specs/<work_id>.md`**",   # playbook L71
    "On approval, **write the plan to `docs/agentic-sdlc/plans/<work_id>.md`**",   # playbook L77
    "On approval the spec is saved to **`docs/agentic-sdlc/specs/<work_id>.md`**",  # SKILL.md L147
)
VALIDATOR_COMMANDS = (
    "--mode spec --file docs/agentic-sdlc/specs/<work_id>.md",
    "--mode plan --file docs/agentic-sdlc/plans/<work_id>.md --spec docs/agentic-sdlc/specs/<work_id>.md --strict",
)

# --- C9 ---
DISPATCH_CALLER_RULE = (
    "**Called by a skill or the pipeline:** when another skill or `agentic-sdlc-pipeline` invoked "
    "you (the user did not ask for a mechanism decision), the decision is never the final answer. "
    "State the map in at most 5 lines, then continue with the caller's next step in the same turn; "
    "end the turn only when the caller's flow says so. Within one `agentic-sdlc-pipeline` run you "
    "are called once, at kickoff, before Step 1, and the pipeline reuses that map."  # C17.8
)
DISPATCH_FENCED_LAST_ITEM = "- **Never touch the skill's internal mechanism.**"
DISPATCH_AUDITOR_ROUTE = (
    "route them through `implementation-auditor` — dispatched directly inside "
    "`agentic-sdlc-pipeline`, via `implementation-control` elsewhere"
)
DISPATCH_AUDITOR_ROUTE_OLD = "route them through `implementation-auditor` (via `implementation-control`)"
PIPELINE_DISPATCH_ONCE = (  # C17.8: Step 1 is "Update main"; the dispatch call comes before it
    "Within one pipeline run, call `dispatch-strategy` once at kickoff, before Step 1, and reuse that "
    "mechanism map for every later heavy, independent, or parallel step."
)
PIPELINE_DISPATCH_PER_STEP_OLD = {
    PIPELINE: "for every heavy/independent/parallel step — it picks the mechanism",
    PLAYBOOK: "`dispatch-strategy` chooses the mechanism each time",
}

# --- C10 ---
DESCRIPTION_CLAUSE = "Not for steps inside an active agentic-sdlc-pipeline run."

# --- C11 ---
SPEC_PLAN_AUTHOR_DESCRIPTION = (
    "Produces a deep spec OR plan DRAFT (no file writing; returns markdown + decision points). "
    "Called by the spec-plan-draft workflow and the runtime author/critic adapters during the "
    "spec/plan steps of agentic-sdlc-pipeline, spec-authoring, plan-authoring, root-cause-fix and "
    "feature-build, and the standalone design flow of mind-spark. Technology-agnostic."
)
AUDITOR_DESCRIPTION_NEW = (
    "Used by the implementation-control skill and dispatched directly by agentic-sdlc-pipeline as "
    "an independent pre-final check."
)
AUDITOR_DESCRIPTION_OLD = "Used by the implementation-control skill as an independent pre-final check."
CONTROL_L3_NEW = ("because its read-only auditor independently checks the supplied diff, artifacts, "
                  "and test evidence")
CONTROL_L3_OLD = "because its auditor inspects the diff itself"
CONTROL_L10_NEW = "receives the diff and the resolved work package"
CONTROL_L10_OLD = "sees the diff and the resolved work package"
SAFE_REFACTOR_EXAMPLE_NEW = (
    "(for example, a spec and plan written with `spec-authoring` and `plan-authoring` for this refactor)"
)
SAFE_REFACTOR_EXAMPLE_OLD = "(for example, this refactor is a step inside `agentic-sdlc-pipeline`)"

# --- C12 ---
SET_A_FILES = (
    "skills/agentic-sdlc-pipeline/SKILL.md",
    "skills/agentic-sdlc-pipeline/playbook.md",
    "docs/skill-boundaries.md",
    "docs/plugin-readme.md",
    ".claude-plugin/README.md",
    ".codex-plugin/README.md",
    "README.md",
    "docs/runtime-adapter.md",
    "docs/claude-code-runtime.md",
    "hooks/README.md",
)
SET_A_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"delegates\W+(?:the\s+)?(?:implementation\s+)?core",
    r"core\s+work-flow",
    r"selected\s+core\s+workflow",
    r"core\s+handoff",
    r"\bonion\b",
    r"delegated\s+(?:work-flow|core|skill)",
    r"Delegates to `(?:feature-build|root-cause-fix|safe-refactor|test-authoring|security-audit|implementation-control)`",
    r"`Skill` invocation for (?:the selected|`security-audit`|`implementation-control`)",
    r"delegates to focused",
    r"pipeline building blocks",
    r"feed the pipeline at control points:[^\n]*`(?:security-audit|implementation-control)`",
    r"Activate `(?:security-audit|implementation-control)`",
))
SET_B_AGENT_FILES = (
    "agents/code-reviewer.md",
    "agents/context-analyst.md",
    "agents/debugger.md",
    "agents/implementation-auditor.md",
    "agents/security-reviewer.md",
    "agents/software-architect.md",
    "agents/spec-plan-author.md",
    "agents/spec-plan-critic.md",
    "agents/test-engineer.md",
)
SET_B_PIPELINE_FILES = (
    "skills/agentic-sdlc-pipeline/SKILL.md",
    "skills/agentic-sdlc-pipeline/playbook.md",
    "skills/agentic-sdlc-pipeline/templates.md",
)
SET_B_FILES = SET_B_PIPELINE_FILES + (
    "skills/feature-build/references/core.md",
    "skills/root-cause-fix/references/core.md",
    "skills/safe-refactor/references/core.md",
    "skills/test-authoring/references/core.md",
    "skills/dispatch-strategy/SKILL.md",
    "skills/completion-claim-gate/SKILL.md",
) + SET_B_AGENT_FILES + (
    "docs/runtime-adapter.md",
)
SET_B_PIPELINE_PATTERNS = tuple(re.compile(p) for p in (
    r"`Skill` -> `agentic-sdlc:(?:feature-build|root-cause-fix|safe-refactor|test-authoring|security-audit|implementation-control)`",
    r"<selected-core-skill>",
    r"\.agentic-sdlc/roles",
))

# --- C13 ---
PROHIBITION_SENTENCE = (
    "**Two branches.** Focused skills are standalone entry points. Inside an `agentic-sdlc-pipeline` "
    "run, do not invoke `feature-build`, `root-cause-fix`, `safe-refactor`, `test-authoring`, "
    "`security-audit`, or `implementation-control`: Steps 8–13 read the selected work-type core "
    "file, the security steps dispatch `security-reviewer`, and the implementation-control gate runs "
    "`resolve_work_package.py` and dispatches `implementation-auditor`."
)

# --- C16 (fix round after the Phase 2 reviews; text owner T) ---
FEEDBACK_TRIAGE = "skills/feedback-triage/SKILL.md"
CLAIM_GATE = "skills/completion-claim-gate/SKILL.md"
ZCODE_DOC = "docs/zcode-runtime-adapter.md"

# C16.14: templates.md L18 / L32.
TEMPLATE_SAVE = {
    "## Spec (step 4": "save to `docs/agentic-sdlc/specs/<work_id>.md` with `status: reviewed`; "
                       "set `approved` only per the Approval receipt",
    "## Plan (step 5": "save to `docs/agentic-sdlc/plans/<work_id>.md` with `status: reviewed`; "
                       "set `approved` only per the Approval receipt",
}
TEMPLATE_SAVE_OLD = "save approved"

# C16.15: the TDD evidence file.
TDD_WRITE_RULE = (
    "Run the test bare. Then write its block with the file-edit tool (Claude Code `Write`/`Edit`; "
    "Codex `apply_patch`), never with a shell redirect, `tee` or `tail`. Copy the last ≤20 lines from "
    "the bare run's output."
)
TDD_SLUG = "The slug is the `<slug>` directory the spec and plan were saved in."
TDD_APPEND = (
    "Append every test run from Step 8 until the auditor is dispatched, including retests. Only a new "
    "pipeline run for the same work_id starts the file fresh."
)
TDD_RED_ONLY = "Only RED blocks carry the `Production files edited before this run:` line."
# The wording C16.15 replaces: the resolver runs after Steps 8-13, so it cannot name the slug yet,
# and "a re-run overwrites" read as wiping the retests that the auditor must see.
TDD_OLD = {
    PIPELINE: ("(the slug `resolve_work_package.py` emits)", "is overwritten when the pipeline re-runs"),
    PLAYBOOK: ("(the slug `resolve_work_package.py` emits)", "A pipeline re-run overwrites it."),
}

# C16.16: core mapping next to the core paths in SKILL.md.
CORE_LAST_STEP = (
    "The core's last step never ends the run: continue with Step 14 in the same turn. Read "
    "`playbook.md` (next to this file) before Step 8."
)
SECURITY_EVERY_WORK_TYPE = (
    "Steps 11 and 14 run for every work type; a core whose security step is conditional "
    "(safe-refactor) or absent (test-authoring) does not skip them."
)

# C16.17: the 8th dispatch-prompt section and what it holds.
ENVELOPE_REPORT_PARTS = ("Analysis Summary", "Goal Lock", "Quality Gates", "Diff Review",
                         "Loop Iteration", '"none"')

# C16.18, as amended by C17.11: once per gate occurrence, so Steps 11 and 14 each emit theirs.
MARKERS_ONCE = (
    "Emit each marker once per gate occurrence, in the message where that gate happens (Steps 11 "
    "and 14 are two occurrences); never repeat markers in progress notes, summaries or the final "
    "report."
)
MARKERS_ONCE_OLD = "Emit each marker once, in the message where its gate happens"

# C16.19: feedback-triage inside a run, in the pipeline and in feedback-triage itself.
PIPELINE_FEEDBACK_TRIAGE = (
    "Inside a run, security-reviewer and auditor findings follow the Loop points, not feedback-triage, "
    "and its IMPLEMENT step follows the selected work-type core, not `test-authoring` or "
    "`root-cause-fix`."
)
FEEDBACK_TRIAGE_IMPLEMENT = (
    "Inside an `agentic-sdlc-pipeline` run, follow the pipeline's selected work-type core instead of "
    "deferring to a focused skill."
)

# C16.20: completion-claim-gate L40-41 (whitespace-normalized: the file wraps its prose).
CLAIM_GATE_AUDITOR = (
    "The `implementation-auditor` gate (through `implementation-control`, or dispatched directly by "
    "`agentic-sdlc-pipeline`) audits the *whole flow*"
)
CLAIM_GATE_AUDITOR_OLD = "`implementation-control` audits the *whole flow*"

# C16.21: minor text fixes.
REVIEWER_NO_FINDINGS_ROW = "`None | — | — | — | No finding`"
REVIEWER_CALL_SHAPE = (
    "`subagent_type` `security-reviewer` or `agentic-sdlc:security-reviewer`: one call for all four "
    "lenses, or one call per lens when the kickoff map fans out"  # C17.8: not "the Step 1 map"
)
FM1_CONTINUE = "continue with Step 1 and the branch checkpoint in the same turn"
FM1_RESUME = ("Resuming after a Review gate continues the same run: no second dispatch and no "
              "focused-skill routing.")
KICKOFF_FAN_OUT = "RED/GREEN runs stay in the main loop"
TEST_ONLY_MUTATION = "reverted before Step 11 and recorded as a MUTATION run"
GIT_SAFETY_CHECK_CALL = "the read-only `git-safety-check` command at Step 16"
GAP_LOOP_REOPENS = "a source edit re-opens Steps 13–14"
GAP_LOOP_OWNER = (
    "re-run the implementation-control gate (`resolve_work_package.py` + "
    "`Agent(implementation-auditor)`)"
)
STEP_14_SKIP_ONLY = "only when nothing changed since the last Step 11 result"
READ_ANY_RUNTIME = "`Read` (or the runtime's file-reading tool)"
CORE_READ_AFTER_DISPATCH = "Read it after the `dispatch-strategy` call, never before it."
TEST_ONLY_CORE_STEP_2_OLD = "2. Write the failing test; confirm it fails for the right reason."
FLAT_NO_EVIDENCE_OLD = ("flat packages get none", "keeps no evidence", "flat packages get no evidence")
ADAPTER_PARAGRAPH_STARTS = ("ZCode (experimental adapter)", "Google Antigravity (experimental adapter)")
ADAPTER_STEPS_8_16 = ("Steps 8–16", "work-type core file", "security-reviewer", "implementation-auditor",
                      "completion-claim-gate", "Codex gate names")
ZCODE_CONTROL_ROW_START = "| `implementation-control`, `completion-claim-gate` |"
ZCODE_CONTROL_ROW_NEEDS = ("agentic-sdlc-pipeline", "resolve_work_package.py",
                           "ZCode Adapter Gate: implementation-auditor",
                           "ZCode Adapter Gate: completion-claim-gate")
ZCODE_CONTROL_ROW_OLD = "final-report gate marker"

# --- C17 (fix round after the final review of e29c571; text owner T2) ---
# C17.8: "Step 1" is "Update main". Text that means the dispatch call or its map says "at kickoff,
# before Step 1" (or "the kickoff map"). `\b` after the 1 keeps "at Step 16" out of the ban.
KICKOFF_DISPATCH = "at kickoff, before Step 1"
STEP_1_DISPATCH_OLD = re.compile(r"\bat Step 1\b|Step 1 (?:map|mechanism map|`dispatch-strategy` map)")
STEP_1_DISPATCH_FILES = (
    PIPELINE,
    PLAYBOOK,
    DISPATCH,
    "README.md",
    "docs/plugin-readme.md",
    ".claude-plugin/README.md",
    ".codex-plugin/README.md",
    "docs/skill-boundaries.md",
    "CHANGELOG.md",
)
# C17.9: kickoff item 2 only selects; the read and the mapping live in the core gate paragraph.
KICKOFF_SELECTION = "note the selected core; you read it at Step 8, after the Plan Review gate."
CORE_READ_INSTRUCTION = "Read `<runtime-root>/skills/<skill>/references/core.md`"
CORE_GATE_PARAGRAPH = "**Work-type core gate (Steps 8–13):**"
# C17.10: playbook Spec Review gate.
RESOLVE_WITH_USER = ("Resolve the decision points WITH the user (AskUserQuestion) unless the request "
                     "pre-approves the gates (see Approval receipt)")
RESOLVE_WITH_USER_OLD = "Resolve the decision points WITH the user (AskUserQuestion);"
# C17.12: the SKILL.md TDD paragraph.
TDD_PARAGRAPH = "From Step 8 the main loop writes the **TDD evidence file**"
TDD_SKILL_WRITE_CLAUSE = "write each block with the file-edit tool, never a shell redirect"
# C17.13: the shared Finalize evidence sentence in the docs. "per-package" stays a marker
# (tests/test_artifact_path_prose.py), so only the parenthesis changes.
FLAT_NO_FINALIZE_EVIDENCE = "(flat packages get no Finalize evidence)"
FLAT_NO_EVIDENCE_DOC_FILES = (
    ".claude-plugin/README.md",
    ".codex-plugin/README.md",
    "README.md",
    "docs/claude-code-runtime.md",
    "docs/plugin-readme.md",
    "docs/release-readiness.md",
    "docs/runtime-adapter.md",
    "docs/skill-boundaries.md",
    "docs/testing.md",
    "docs/troubleshooting.md",
    "hooks/README.md",
)
# C17.14: the closed Skill-call list in docs/skill-boundaries.md.
BOUNDARIES = "docs/skill-boundaries.md"
BOUNDARIES_CLOSED_LIST = "The pipeline's own `Skill` calls are"
# C17.15: docs/testing.md strict-key rows (C16.2-C16.4) and the depth relativization (C17.1).
TESTING_DOC = "docs/testing.md"
TESTING_ROW_NEEDS = {
    "| `skill_call_counts` |": ("whose only result is an error",),
    "| `reviewers_after_last_source_edit` |": ("dispatch call",),
    "| `evidence_file_before_control` |": ("dispatch call",),
    "| `stop_at_gate` |": ("anywhere in the run", "sub-agent"),
}
TESTING_STRICT_SECTION = "### Strict evidence keys"
TESTING_STRICT_NEEDS = ("failed write", "relativiz", "unsafe_artifact_path")
# C17.16: CHANGELOG 0.6.0 known limitations.
CHANGELOG = "CHANGELOG.md"
CHANGELOG_NO_LIVE_RUN = (
    "No live pipeline run has measured 0.6.0 yet; the zero-delegation behaviour is stated in the skill text, "
    "checked by the Claude Code flow hooks (warn by default) and graded offline by the strict procedure eval."
)
CHANGELOG_TDD_PATHS = (
    "per-package `docs/agentic-sdlc/<slug>/evidence/<work_id>.tdd.md`",
    "flat `docs/agentic-sdlc/evidence/<work_id>.tdd.md`",
)
CHANGELOG_TDD_OLD = "(`<work_id>.tdd.md` next to the work package's evidence)"


def block(text, heading):
    """The C1 block rule: from the heading line up to, not including, the next line starting
    with `## `, trailing blank lines stripped. The heading matches exactly or as a prefix followed
    by a space (`## Depth contract (proportional ...)`). Returns None when the heading is absent."""
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if line == heading or line.startswith(heading + " "):
            out = [line]
            for following in lines[index + 1:]:
                if following.startswith("## "):
                    break
                out.append(following)
            while out and out[-1].strip() == "":
                out.pop()
            return "\n".join(out)
    return None


FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")


def playbook_section(text, heading_prefix):
    """From the line starting with `heading_prefix` to the next `### ` or `## ` heading outside a
    code fence (the C2 evidence format holds `#`/`##` lines inside a fence). None when absent."""
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if line.startswith(heading_prefix)), None)
    if start is None:
        return None
    fence = None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        marker = FENCE.match(line)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence) and line.strip() == run:
                fence = None
            continue
        if fence is None and line.startswith(("### ", "## ")):
            end = index
            break
    return "\n".join(lines[start:end])


def heading_line_index(text, heading):
    for index, line in enumerate(text.split("\n")):
        if line == heading or line.startswith(heading + " "):
            return index
    return None


def frontmatter_description(text):
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    for line in text[4:end].split("\n"):
        if line.startswith("description:"):
            value = line[len("description:"):].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return None


def pattern_hits(text, patterns):
    hits = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            hits.append(f"L{line}: {match.group(0)!r} (pattern {pattern.pattern!r})")
    return hits


class ContractCase(unittest.TestCase):
    maxDiff = None

    def read(self, rel):
        path = REPO / rel
        self.assertTrue(path.is_file(), f"{rel} does not exist")
        # Bytes decoded without newline translation: parity is byte-level.
        return path.read_bytes().decode("utf-8")

    def section(self, text, heading, rel):
        found = block(text, heading)
        self.assertIsNotNone(found, f"{rel} has no `{heading}` section")
        return found


# ============================================================ C1


class TestC1CoreParity(ContractCase):
    def test_copied_depth_blocks_are_byte_identical_to_skill_md(self):
        for skill in WORK_TYPE_SKILLS:
            with self.subTest(skill=skill):
                source = self.read(skill_md(skill))
                core = self.read(core_md(skill))
                for heading in COPIED_BLOCKS:
                    expected = block(source, heading)
                    actual = block(core, heading)
                    self.assertIsNotNone(expected, f"{skill_md(skill)} lost `{heading}`")
                    self.assertIsNotNone(actual, f"{core_md(skill)} has no copy of `{heading}`")
                    self.assertEqual(actual, expected,
                                     f"{core_md(skill)} `{heading}` drifted from {skill_md(skill)}")


class TestC1CorePurity(ContractCase):
    def test_core_files_hold_none_of_the_envelope(self):
        for skill in WORK_TYPE_SKILLS:
            with self.subTest(skill=skill):
                core = self.read(core_md(skill))
                leaked = [token for token in PURITY_TOKENS if token in core]
                self.assertEqual(leaked, [], f"{core_md(skill)} carries envelope tokens")
                hits = pattern_hits(core, (FOCUSED_SKILL_PATH, FOCUSED_ADAPTER_GATE))
                self.assertEqual(hits, [], f"{core_md(skill)} matches C7 pattern 2 or 3")


class TestC1CoreLoad(ContractCase):
    def test_focused_skill_links_core_with_the_resolution_sentence(self):
        for skill in WORK_TYPE_SKILLS:
            with self.subTest(skill=skill):
                text = self.read(skill_md(skill))
                self.assertIn("[references/core.md](references/core.md)", text,
                              f"{skill_md(skill)} does not link references/core.md")
                sentence = READ_SENTENCE.format(n=FIRST_MOVED_STEP[skill])
                self.assertIn(sentence, text,
                              f"{skill_md(skill)} lacks the core read + resolution sentence")
                self.assertIn("— core step 1.", text, f"{skill_md(skill)} has no core-step stub")
                self.assertLess(text.index(sentence), text.index("— core step 1."),
                                "the read sentence must come before the first moved step")

    def test_pipeline_names_all_four_core_paths(self):
        text = self.read(PIPELINE)
        missing = [f"<runtime-root>/{core_md(skill)}" for skill in WORK_TYPE_SKILLS
                   if f"<runtime-root>/{core_md(skill)}" not in text]
        self.assertEqual(missing, [], f"{PIPELINE} does not name these core files")


class TestC1CoreLayout(ContractCase):
    def test_core_heading_and_intro_paragraph(self):
        for skill in WORK_TYPE_SKILLS:
            with self.subTest(skill=skill):
                core = self.read(core_md(skill))
                first = next((line for line in core.split("\n") if line.strip()), "")
                self.assertEqual(first, f"# {skill} — work-type core")
                self.assertIn(CORE_INTRO.format(skill=skill), core,
                              f"{core_md(skill)} lacks the verbatim intro paragraph")

    def test_core_sections_follow_the_contract_order(self):
        for skill in WORK_TYPE_SKILLS:
            with self.subTest(skill=skill):
                core = self.read(core_md(skill))
                intro = CORE_INTRO.format(skill=skill)
                self.assertIn(intro, core)
                intro_line = core[:core.index(intro)].count("\n")
                positions = [(f"# {skill} — work-type core",
                              heading_line_index(core, f"# {skill} — work-type core")),
                             ("intro paragraph", intro_line)]
                for heading in COPIED_BLOCKS + ("## Core steps",) + tuple(MOVED_SECTIONS[skill]):
                    positions.append((heading, heading_line_index(core, heading)))
                absent = [name for name, index in positions if index is None]
                self.assertEqual(absent, [], f"{core_md(skill)} is missing sections")
                order = [index for _name, index in positions]
                self.assertEqual(order, sorted(order),
                                 f"{core_md(skill)} sections out of order: {positions}")
                self.assertEqual(len(set(order)), len(order), f"overlapping sections: {positions}")

    def test_core_steps_are_a_numbered_list_with_the_moved_step_names(self):
        for skill in WORK_TYPE_SKILLS:
            with self.subTest(skill=skill):
                steps = self.section(self.read(core_md(skill)), "## Core steps", core_md(skill))
                numbered = [line for line in steps.split("\n") if re.match(r"\d+\. ", line)]
                numbers = [int(line.split(".", 1)[0]) for line in numbered]
                self.assertEqual(numbers, list(range(1, CORE_STEP_COUNT[skill] + 1)),
                                 f"{core_md(skill)} `## Core steps` must number 1..n")
                names = CORE_STEP_NAMES[skill]
                if names is None:
                    continue
                for index, (line, name) in enumerate(zip(numbered, names), 1):
                    self.assertTrue(line.startswith(f"{index}. **{name}**"),
                                    f"core step {index} must keep its bold name {name!r}: {line!r}")

    def test_core_steps_keep_their_body_text(self):
        for skill in WORK_TYPE_SKILLS:
            with self.subTest(skill=skill):
                steps = self.section(self.read(core_md(skill)), "## Core steps", core_md(skill))
                missing = [body for body in CORE_STEP_BODIES[skill] if body not in steps]
                self.assertEqual(missing, [], f"{core_md(skill)} reworded or dropped step text")

    def test_feature_core_observes_red_before_implementation(self):
        # The same assertion in test_shared_skill_contract.py runs on SKILL.md, which now holds
        # only stubs; the ordering has to be pinned where the steps live.
        steps = self.section(self.read(core_md("feature-build")), "## Core steps",
                             core_md("feature-build"))
        self.assertIn("**Failing test", steps)
        self.assertIn("**Implementation", steps)
        self.assertLess(steps.index("**Failing test"), steps.index("**Implementation"))


class TestC1MovedSections(ContractCase):
    def test_moved_sections_live_in_the_core(self):
        for skill in WORK_TYPE_SKILLS:
            for heading, expected in MOVED_SECTIONS[skill].items():
                with self.subTest(skill=skill, section=heading):
                    core = self.read(core_md(skill))
                    if heading == "## Loop Iteration template":
                        self.assertIn(expected, core, f"{core_md(skill)} lacks the moved template")
                    else:
                        actual = self.section(core, heading, core_md(skill))
                        self.assertEqual(actual, expected)

    def test_moved_sections_are_gone_from_skill_md(self):
        for skill in WORK_TYPE_SKILLS:
            for heading in MOVED_SECTIONS[skill]:
                with self.subTest(skill=skill, section=heading):
                    text = self.read(skill_md(skill))
                    self.assertIsNone(heading_line_index(text, heading),
                                      f"{skill_md(skill)} still carries `{heading}` (move, not copy)")

    def test_loop_text_moves_with_root_cause_fix_steps(self):
        text = self.read(skill_md("root-cause-fix"))
        for loop in ("**Loop A — test fail:**", "**Loop B — finding:**", "## Continue or Exit Loop"):
            with self.subTest(loop=loop):
                self.assertNotIn(loop, text, f"{loop!r} must move to the core with its step")


class TestC1Stubs(ContractCase):
    def test_list_form_stubs_keep_the_original_numbers(self):
        for skill, stubs in LIST_STUBS.items():
            with self.subTest(skill=skill):
                flow = self.section(self.read(skill_md(skill)), "## Flow", skill_md(skill))
                lines = flow.split("\n")
                for number, stub in stubs.items():
                    numbered = [line for line in lines if line.startswith(f"{number}. ")]
                    self.assertEqual(numbered, [stub], f"{skill_md(skill)} step {number}")

    def test_test_authoring_flow_is_five_core_step_stubs(self):
        flow = self.section(self.read(skill_md("test-authoring")), "## Flow", skill_md("test-authoring"))
        lines = flow.split("\n")
        for number in range(1, 6):
            with self.subTest(step=number):
                numbered = [line for line in lines if line.startswith(f"{number}. ")]
                self.assertEqual(len(numbered), 1, numbered)
                self.assertRegex(numbered[0], rf"^{number}\. .+ — core step {number}\.$")

    def test_root_cause_fix_heading_stubs_have_no_body(self):
        text = self.read(skill_md("root-cause-fix"))
        flow = self.section(text, "## Flow", skill_md("root-cause-fix"))
        lines = flow.split("\n")
        for number, stub in HEADING_STUBS.items():
            with self.subTest(step=number):
                headed = [line for line in lines if line.startswith(f"### {number}. ")]
                self.assertEqual(headed, [stub])
                start = lines.index(stub)
                body = []
                for line in lines[start + 1:]:
                    if line.startswith("### "):
                        break
                    body.append(line)
                self.assertEqual([line for line in body if line.strip()], [],
                                 f"stub {stub!r} must have no body")
        # The gates after steps 3 and 4 stay in SKILL.md.
        self.assertIn("**Gate:** spec exists and criteria are testable.", text)
        self.assertIn("**Gate:** every acceptance criterion has a task.", text)


class TestC1EnvelopeKept(ContractCase):
    # A preservation guard, green before and after the move: the envelope stays in SKILL.md
    # verbatim, so only the moved steps may change there.
    def test_envelope_lines_stay_verbatim(self):
        for skill, expected in ENVELOPE_LINES.items():
            lines = self.read(skill_md(skill)).split("\n")
            for line in expected:
                with self.subTest(skill=skill, line=line[:60]):
                    self.assertIn(line, lines)


class TestC1TestOnlyWording(ContractCase):
    def test_o2_replacement_lines_are_in_the_test_authoring_core(self):
        core = self.read(core_md("test-authoring"))
        steps = self.section(core, "## Core steps", core_md("test-authoring"))
        self.assertIn(O2_STEP_3, steps.split("\n"))
        self.assertIn(O2_TDD_BULLET, self.section(core, "## Principles", core_md("test-authoring")).split("\n"))
        self.assertIn(O2_FORBIDDEN, self.section(core, "## Forbidden", core_md("test-authoring")).split("\n"))

    def test_o2_replaced_lines_are_gone(self):
        for rel in (core_md("test-authoring"), skill_md("test-authoring")):
            text = self.read(rel)
            for old in O2_OLD:
                with self.subTest(file=rel, line=old):
                    self.assertNotIn(old, text)


class TestC1PipelineMapping(ContractCase):
    def test_playbook_maps_core_steps_to_pipeline_steps(self):
        self.assertIn(PIPELINE_MAPPING, self.read(PLAYBOOK))


# ============================================================ C2


class TestC2TddEvidence(ContractCase):
    def test_tdd_evidence_paths_are_named_in_skill_and_playbook(self):
        for rel in (PIPELINE, PLAYBOOK):
            text = self.read(rel)
            for path in TDD_EVIDENCE_PATHS:
                with self.subTest(file=rel, path=path):
                    self.assertIn(path, text)

    def test_auditor_input_sentence_names_the_dispatch_prompt_inputs(self):
        for rel in (PIPELINE, PLAYBOOK):
            with self.subTest(file=rel):
                text = self.read(rel)
                self.assertIn(AUDITOR_INPUT_NEW, text)
                self.assertNotIn(AUDITOR_INPUT_OLD, text)
                self.assertNotIn(AUDITOR_INPUT_OLD_ENDING, text)
                low = text.lower()
                kept = [marker for marker in FINALIZE_MARKERS if marker not in low]
                self.assertEqual(kept, [], f"{rel} lost Finalize evidence markers")

    def test_playbook_carries_the_tdd_evidence_format_and_timing(self):
        playbook = self.read(PLAYBOOK)
        position = 0
        for pattern in TDD_EVIDENCE_FORMAT:
            match = pattern.search(playbook, position)
            self.assertIsNotNone(match, f"{PLAYBOOK} lacks the C2 format line {pattern.pattern!r} "
                                        "(or it is out of order)")
            position = match.end()
        self.assertIn(TDD_EVIDENCE_TIMING, playbook)


# ============================================================ C3


class TestC3AuditorContract(ContractCase):
    def test_auditor_ports_the_control_report_headings(self):
        text = self.read(AUDITOR)
        self.assertRegex(text, r"(?m)^## Overall Status$")
        self.assertRegex(text, r"(?m)^## Final Decision$")
        missing = [field for field in AUDITOR_STRUCTURED_FIELDS if f"`{field}`" not in text]
        self.assertEqual(missing, [], "the existing StructuredOutput fields must stay")

    def test_auditor_names_the_tdd_evidence_input(self):
        # The forbidden evidence-write tokens are pinned by tests/test_evidence_persist.py.
        self.assertIn(AUDITOR_TDD_INPUT, self.read(AUDITOR))

    def test_playbook_dispatch_prompt_carries_the_labelled_sections(self):
        playbook = self.read(PLAYBOOK)
        section = playbook_section(playbook, "### Implementation control")
        self.assertIsNotNone(section, f"{PLAYBOOK} has no `### Implementation control` section")
        position = 0
        for label in DISPATCH_PROMPT_LABELS:
            index = section.find(label, position)
            self.assertNotEqual(index, -1, f"dispatch-prompt label {label!r} missing or out of order")
            position = index + len(label)
        self.assertIn(DISPATCH_PROMPT_DIFF, section)
        self.assertIn("--stat", section)
        self.assertIn("400", section)
        self.assertRegex(section, BLOCK_FINAL_RULE)


# ============================================================ C4


class TestC4SecurityReviewer(ContractCase):
    def test_output_line_carries_the_exact_header(self):
        lines = self.read(REVIEWER).split("\n")
        self.assertIn(REVIEWER_OUTPUT_LINE, lines)
        self.assertNotIn(REVIEWER_OUTPUT_LINE_OLD, lines)

    def test_header_is_byte_identical_to_the_grader_constant(self):
        grader = self.read(GRADER)
        match = re.search(r'(?m)^FINDINGS_TABLE_HEADER = "([^"\n]*)"', grader)
        self.assertIsNotNone(match, f"{GRADER} no longer defines FINDINGS_TABLE_HEADER")
        self.assertEqual(match.group(1), FINDINGS_HEADER)
        self.assertIn(FINDINGS_HEADER, self.read(REVIEWER))

    def test_lenses_section(self):
        lenses = self.section(self.read(REVIEWER), "## Lenses", REVIEWER)
        stripped = [line.strip() for line in lenses.split("\n")]
        missing = [line for line in REVIEWER_LENS_LINES if line not in stripped]
        self.assertEqual(missing, [], f"{REVIEWER} `## Lenses` is missing lines")

    def test_masking_rule(self):
        rule = self.section(self.read(REVIEWER), "## Reporting rule", REVIEWER)
        self.assertIn(REVIEWER_MASKING, rule)

    def test_when_used_line(self):
        when = self.section(self.read(REVIEWER), "## When used", REVIEWER)
        self.assertIn(REVIEWER_WHEN_USED, [line.strip() for line in when.split("\n")])

    def test_playbook_step_14_lens_list(self):
        playbook = self.read(PLAYBOOK)
        self.assertRegex(playbook, STEP_14_LENSES)
        self.assertNotIn(STEP_14_LENSES_OLD, playbook)


# ============================================================ C5


class TestC5RuntimeGateMarkers(ContractCase):
    def test_codex_markers_are_named(self):
        text = self.read(PIPELINE)
        missing = [marker for marker in CODEX_MARKERS if marker not in text]
        self.assertEqual(missing, [], f"{PIPELINE} lacks Codex gate markers")

    def test_no_selected_core_skill_placeholder(self):
        text = self.read(PIPELINE)
        self.assertIn("Codex Adapter Gate", text)
        self.assertNotIn("<selected-core-skill>", text)

    def test_review_results_are_printed_as_assistant_text(self):
        # C5 does not say which pipeline file carries the rule, so either one satisfies it.
        texts = {rel: self.read(rel) for rel in (PIPELINE, PLAYBOOK)}
        carriers = [rel for rel, text in texts.items() if PRINT_REVIEW_RESULTS.search(text)]
        self.assertTrue(carriers, f"neither pipeline file matches {PRINT_REVIEW_RESULTS.pattern!r}")


# ============================================================ C8


class TestC8ApprovalReceipt(ContractCase):
    def test_receipt_paragraph_in_skill_and_playbook(self):
        for rel in (PIPELINE, PLAYBOOK):
            with self.subTest(file=rel):
                text = self.read(rel)
                self.assertIn(APPROVAL_RECEIPT, text)
                for command in VALIDATOR_COMMANDS:
                    self.assertIn(command, text, "the validator commands stay")

    def test_old_on_approval_sentences_are_replaced(self):
        for rel in (PIPELINE, PLAYBOOK):
            text = self.read(rel)
            self.assertIn(APPROVAL_RECEIPT, text)
            for old in OLD_ON_APPROVAL + APPROVAL_RECEIPT_OLD:
                with self.subTest(file=rel, sentence=old):
                    self.assertNotIn(old, text)


# ============================================================ C9


class TestC9DispatchRules(ContractCase):
    def test_scope_carries_the_caller_rule_after_the_fenced_list(self):
        scope = self.section(self.read(DISPATCH), "## Scope", DISPATCH)
        self.assertIn(DISPATCH_FENCED_LAST_ITEM, scope)
        self.assertIn(DISPATCH_CALLER_RULE, scope)
        self.assertLess(scope.index(DISPATCH_FENCED_LAST_ITEM), scope.index(DISPATCH_CALLER_RULE))

    def test_auditor_route_names_direct_pipeline_dispatch(self):
        text = self.read(DISPATCH)
        self.assertIn(DISPATCH_AUDITOR_ROUTE, text)
        self.assertNotIn(DISPATCH_AUDITOR_ROUTE_OLD, text)

    def test_pipeline_calls_dispatch_strategy_once(self):
        for rel in (PIPELINE, PLAYBOOK):
            with self.subTest(file=rel):
                self.assertIn(PIPELINE_DISPATCH_ONCE, self.read(rel))

    def test_old_per_step_dispatch_wording_is_gone(self):
        for rel, old in PIPELINE_DISPATCH_PER_STEP_OLD.items():
            with self.subTest(file=rel):
                self.assertNotIn(old, self.read(rel))


# ============================================================ C10


class TestC10DescriptionClause(ContractCase):
    def test_focused_descriptions_end_with_the_pipeline_clause(self):
        for skill in FOCUSED_SKILLS:
            with self.subTest(skill=skill):
                description = frontmatter_description(self.read(skill_md(skill)))
                self.assertIsNotNone(description, f"{skill_md(skill)} has no description")
                self.assertTrue(description.endswith(" " + DESCRIPTION_CLAUSE),
                                f"{skill} description must end with {DESCRIPTION_CLAUSE!r}")


# ============================================================ C11


class TestC11Wording(ContractCase):
    def test_spec_plan_author_description(self):
        description = frontmatter_description(self.read(SPEC_PLAN_AUTHOR))
        self.assertIsNotNone(description, f"{SPEC_PLAN_AUTHOR} has no description")
        self.assertEqual(description, SPEC_PLAN_AUTHOR_DESCRIPTION)

    def test_implementation_auditor_description(self):
        description = frontmatter_description(self.read(AUDITOR))
        self.assertIsNotNone(description, f"{AUDITOR} has no description")
        self.assertIn(AUDITOR_DESCRIPTION_NEW, description)
        self.assertNotIn(AUDITOR_DESCRIPTION_OLD, description)

    def test_implementation_auditor_body_names_direct_pipeline_dispatch(self):
        # C11 says L8 and L10 change "the same way" as the description; the exact text is not
        # fixed, so only the new caller is required in both places.
        text = self.read(AUDITOR)
        intro = [line for line in text.split("\n") if line.startswith("You are an **implementation auditor**")]
        self.assertEqual(len(intro), 1, intro)
        self.assertIn("agentic-sdlc-pipeline", intro[0])
        self.assertIn("agentic-sdlc-pipeline", self.section(text, "## When used", AUDITOR))

    def test_implementation_control_wording(self):
        text = self.read(CONTROL)
        description = frontmatter_description(text)
        self.assertIsNotNone(description, f"{CONTROL} has no description")
        self.assertIn(CONTROL_L3_NEW, description)
        self.assertNotIn(CONTROL_L3_OLD, text)
        self.assertIn(CONTROL_L10_NEW, text)
        self.assertNotIn(CONTROL_L10_OLD, text)

    def test_safe_refactor_example(self):
        text = self.read(skill_md("safe-refactor"))
        self.assertIn(SAFE_REFACTOR_EXAMPLE_NEW, text)
        self.assertNotIn(SAFE_REFACTOR_EXAMPLE_OLD, text)


# ============================================================ C12


class TestC12SweepBan(ContractCase):
    # Each listed file is asserted to exist (in `read`) before it is scanned, so a renamed file
    # fails the sweep instead of silently dropping out of it.

    def test_set_a_has_no_stale_delegation_wording(self):
        for rel in SET_A_FILES:
            with self.subTest(file=rel):
                hits = pattern_hits(self.read(rel), SET_A_PATTERNS)
                self.assertEqual(hits, [], f"{rel} carries stale delegation wording")

    def test_set_b_has_no_focused_skill_path_or_marker(self):
        # Set B names `agents/*.md`; the literal list must still be the whole role library.
        agents = sorted("agents/" + path.name for path in (REPO / "agents").glob("*.md"))
        self.assertTrue(agents, "agents/ has no role files")
        self.assertEqual(agents, sorted(SET_B_AGENT_FILES),
                         "agents/*.md changed: update SET_B_AGENT_FILES so the sweep covers it")
        for rel in SET_B_FILES:
            with self.subTest(file=rel):
                hits = pattern_hits(self.read(rel), (FOCUSED_SKILL_PATH, FOCUSED_ADAPTER_GATE))
                self.assertEqual(hits, [], f"{rel} matches C7 pattern 2 or 3")

    def test_pipeline_files_have_no_focused_skill_call_target(self):
        for rel in SET_B_PIPELINE_FILES:
            with self.subTest(file=rel):
                hits = pattern_hits(self.read(rel), SET_B_PIPELINE_PATTERNS)
                self.assertEqual(hits, [], f"{rel} still names a focused skill call target")


# ============================================================ C13


class TestC13ProhibitionSentence(ContractCase):
    def test_prohibition_sentence_is_verbatim(self):
        self.assertIn(PROHIBITION_SENTENCE, self.read(PIPELINE))

    def test_onion_rule_section_is_gone(self):
        # Anchored on the sentence that replaces the section, so an emptied file cannot pass.
        text = self.read(PIPELINE)
        self.assertIn(PROHIBITION_SENTENCE, text)
        self.assertIsNone(heading_line_index(text, "## Onion rule"), "the Onion rule section must go")


# ============================================================ C16 (text, owner T)


def flat(text):
    """Whitespace-normalized text, for files that hard-wrap their prose."""
    return " ".join(text.split())


class TestC16ApprovalReceipt(ContractCase):
    # The full paragraph is pinned by TestC8ApprovalReceipt; these name the C16.13 sentences so a
    # failure says which rule went missing.
    def test_amended_receipt_sentences(self):
        for rel in (PIPELINE, PLAYBOOK):
            text = self.read(rel)
            for sentence in (RECEIPT_APPROVE, RECEIPT_DECISION_POINTS, RECEIPT_CRITIC,
                             RECEIPT_NO_ANSWER, RECEIPT_SILENCE, RECEIPT_QUOTE):
                with self.subTest(file=rel, sentence=sentence[:50]):
                    self.assertIn(sentence, text)


class TestC16Templates(ContractCase):
    def test_spec_and_plan_headings_save_reviewed_not_approved(self):
        text = self.read(TEMPLATES)
        lines = text.split("\n")
        for heading, wording in TEMPLATE_SAVE.items():
            with self.subTest(heading=heading):
                found = [line for line in lines if line.startswith(heading)]
                self.assertEqual(len(found), 1, f"{TEMPLATES} needs one `{heading}` heading")
                self.assertIn(wording, found[0])
        self.assertNotIn(TEMPLATE_SAVE_OLD, text)

    def test_flat_packages_get_no_finalize_evidence_only(self):
        text = self.read(TEMPLATES)
        self.assertIn("no Finalize evidence", text)
        for old in FLAT_NO_EVIDENCE_OLD:
            with self.subTest(old=old):
                self.assertNotIn(old, text)


class TestC16TddFile(ContractCase):
    def test_playbook_write_rule(self):
        section = playbook_section(self.read(PLAYBOOK), "## Work-type core steps")
        self.assertIsNotNone(section, f"{PLAYBOOK} has no `## Work-type core steps` section")
        for sentence in (TDD_WRITE_RULE, TDD_SLUG, TDD_APPEND, TDD_RED_ONLY):
            with self.subTest(sentence=sentence[:50]):
                self.assertIn(sentence, section)

    def test_skill_md_slug_and_append_rule(self):
        text = self.read(PIPELINE)
        self.assertIn(TDD_SLUG, text)
        self.assertIn(TDD_APPEND, text)

    def test_replaced_tdd_wording_is_gone(self):
        for rel, olds in TDD_OLD.items():
            text = self.read(rel)
            self.assertIn(TDD_EVIDENCE_PATHS[0], text)
            for old in olds:
                with self.subTest(file=rel, old=old):
                    self.assertNotIn(old, text)


class TestC16CoreMapping(ContractCase):
    # C17.9 moved the C16.16 sentences from kickoff item 2 into the Work-type core gate paragraph:
    # kickoff only selects the core, and the core is read at Step 8, after the Plan Review gate.
    def core_gate_paragraph(self):
        lines = [ln for ln in self.read(PIPELINE).split("\n") if ln.startswith(CORE_GATE_PARAGRAPH)]
        self.assertEqual(len(lines), 1, f"{PIPELINE} needs one `{CORE_GATE_PARAGRAPH}` paragraph")
        return lines[0]

    def test_kickoff_item_2_only_selects_the_core(self):
        kickoff = self.section(self.read(PIPELINE), "## At kickoff (always)", PIPELINE)
        item = next((ln for ln in kickoff.split("\n") if ln.startswith("2. ")), None)
        self.assertIsNotNone(item, "kickoff item 2 is gone")
        missing = [f"<runtime-root>/{core_md(skill)}" for skill in WORK_TYPE_SKILLS
                   if f"<runtime-root>/{core_md(skill)}" not in item]
        self.assertEqual(missing, [], "kickoff item 2 must still name the four core files")
        self.assertIn(KICKOFF_SELECTION, item)
        for moved in (CORE_READ_INSTRUCTION, PIPELINE_MAPPING, CORE_LAST_STEP):
            with self.subTest(moved=moved[:50]):
                self.assertNotIn(moved, kickoff)

    def test_mapping_sits_in_the_core_gate_paragraph(self):
        paragraph = self.core_gate_paragraph()
        for sentence in (PIPELINE_MAPPING, CORE_LAST_STEP):
            with self.subTest(sentence=sentence[:50]):
                self.assertIn(sentence, paragraph)
        self.assertLess(paragraph.index(PIPELINE_MAPPING), paragraph.index(CORE_LAST_STEP))
        self.assertEqual(self.read(PIPELINE).count(PIPELINE_MAPPING), 1,
                         "the mapping sentence lives in one place in SKILL.md")

    def test_security_steps_run_for_every_work_type(self):
        self.assertIn(SECURITY_EVERY_WORK_TYPE, self.read(PIPELINE))


class TestC16AuditorEnvelope(ContractCase):
    def test_playbook_envelope_reports_section_holds_the_reports(self):
        section = playbook_section(self.read(PLAYBOOK), "### Implementation control")
        self.assertIsNotNone(section, f"{PLAYBOOK} has no `### Implementation control` section")
        self.assertIn("`Envelope reports:`", section)
        line = section[section.index("`Envelope reports:`"):].split("\n", 1)[0]
        missing = [part for part in ENVELOPE_REPORT_PARTS if part not in line]
        self.assertEqual(missing, [], "the `Envelope reports:` item must name every report")

    def test_auditor_input_names_envelope_reports(self):
        text = self.read(AUDITOR)
        self.assertIn("`Envelope reports:`", self.section(text, "## Input", AUDITOR))
        self.assertIn(READ_ANY_RUNTIME, text)

    def test_playbook_read_works_on_any_runtime(self):
        section = playbook_section(self.read(PLAYBOOK), "### Implementation control")
        self.assertIsNotNone(section)
        self.assertIn(READ_ANY_RUNTIME, section)


class TestC16Markers(ContractCase):
    def test_markers_are_emitted_once_per_gate_occurrence(self):
        text = self.read(PIPELINE)
        self.assertIn(MARKERS_ONCE, text)
        self.assertNotIn(MARKERS_ONCE_OLD, text)


class TestC16FeedbackTriage(ContractCase):
    def test_pipeline_companion_line(self):
        companions = self.section(self.read(PIPELINE), "## Companion discipline skills", PIPELINE)
        line = next((ln for ln in companions.split("\n") if ln.startswith("- **`feedback-triage`**")),
                    None)
        self.assertIsNotNone(line, "the feedback-triage companion bullet is gone")
        self.assertIn(PIPELINE_FEEDBACK_TRIAGE, line)

    def test_feedback_triage_implement_step_mirrors_it(self):
        text = self.read(FEEDBACK_TRIAGE)
        self.assertIn("6. **IMPLEMENT**", text)
        step = text[text.index("6. **IMPLEMENT**"):]
        step = step.split("\n## ", 1)[0]
        self.assertIn(FEEDBACK_TRIAGE_IMPLEMENT, flat(step))


class TestC16CompletionClaimGate(ContractCase):
    def test_names_the_implementation_auditor_gate(self):
        text = flat(self.read(CLAIM_GATE))
        self.assertIn(CLAIM_GATE_AUDITOR, text)
        self.assertNotIn(CLAIM_GATE_AUDITOR_OLD, text)


class TestC16MinorFixes(ContractCase):
    def test_reviewer_prints_a_row_when_there_are_no_findings(self):
        output = self.section(self.read(REVIEWER), "## Output format", REVIEWER)
        self.assertIn(FINDINGS_HEADER, output)
        self.assertIn(REVIEWER_NO_FINDINGS_ROW, output)

    def test_pipeline_sentences(self):
        text = self.read(PIPELINE)
        for literal in (REVIEWER_CALL_SHAPE, FM1_CONTINUE, FM1_RESUME, TEST_ONLY_MUTATION,
                        GIT_SAFETY_CHECK_CALL, STEP_14_SKIP_ONLY):
            with self.subTest(literal=literal[:50]):
                self.assertIn(literal, text)

    def test_kickoff_mechanism_map_keeps_red_green_in_the_main_loop(self):
        kickoff = self.section(self.read(PIPELINE), "## At kickoff (always)", PIPELINE)
        self.assertIn(KICKOFF_FAN_OUT, kickoff)

    def test_step_map_row_8_gate_is_per_work_type(self):
        rows = [ln for ln in self.read(PIPELINE).split("\n") if ln.startswith("| 8 |")]
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("per work type", rows[0])

    def test_gap_loop_reopens_steps_and_names_the_gate_owner(self):
        loops = self.section(self.read(PIPELINE), "## Loop points", PIPELINE)
        self.assertIn(GAP_LOOP_REOPENS, loops)
        self.assertIn(GAP_LOOP_OWNER, loops)

    def test_playbook_sentences(self):
        text = self.read(PLAYBOOK)
        for literal in (TEST_ONLY_MUTATION, STEP_14_SKIP_ONLY):
            with self.subTest(literal=literal[:50]):
                self.assertIn(literal, text)

    def test_light_core_skills_read_the_core_after_dispatch(self):
        for skill in ("safe-refactor", "test-authoring"):
            with self.subTest(skill=skill):
                text = self.read(skill_md(skill))
                sentence = READ_SENTENCE.format(n=FIRST_MOVED_STEP[skill])
                self.assertIn(sentence, text)
                self.assertIn(CORE_READ_AFTER_DISPATCH, text)
                self.assertLess(text.index("## Call-order guard"), text.index(CORE_READ_AFTER_DISPATCH))
                self.assertLess(text.index(sentence), text.index(CORE_READ_AFTER_DISPATCH))
                self.assertLess(text.index(CORE_READ_AFTER_DISPATCH), text.index("— core step 1."))

    def test_test_authoring_core_step_2_no_longer_demands_a_failing_run(self):
        self.assertNotIn(TEST_ONLY_CORE_STEP_2_OLD, self.read(core_md("test-authoring")))

    def test_zcode_and_antigravity_cover_steps_8_to_16(self):
        lines = self.read(PIPELINE).split("\n")
        for start in ADAPTER_PARAGRAPH_STARTS:
            with self.subTest(runtime=start):
                found = [line for line in lines if line.startswith(start)]
                self.assertEqual(len(found), 1, f"{PIPELINE} needs one `{start}` paragraph")
                missing = [part for part in ADAPTER_STEPS_8_16 if part not in found[0]]
                self.assertEqual(missing, [])

    def test_zcode_doc_control_row_matches_the_pipeline(self):
        rows = [ln for ln in self.read(ZCODE_DOC).split("\n") if ln.startswith(ZCODE_CONTROL_ROW_START)]
        self.assertEqual(len(rows), 1, rows)
        missing = [part for part in ZCODE_CONTROL_ROW_NEEDS if part not in rows[0]]
        self.assertEqual(missing, [])
        self.assertNotIn(ZCODE_CONTROL_ROW_OLD, rows[0])


# ============================================================ C17 (text, owner T2)


class TestC17KickoffDispatch(ContractCase):
    def test_dispatch_call_is_placed_at_kickoff_before_step_1(self):
        for rel in STEP_1_DISPATCH_FILES:
            with self.subTest(file=rel):
                text = self.read(rel)
                self.assertIn(KICKOFF_DISPATCH, text)
                self.assertEqual(pattern_hits(text, (STEP_1_DISPATCH_OLD,)), [],
                                 f"{rel} still places the dispatch call or its map at Step 1")

    def test_step_1_stays_update_main(self):
        rows = [ln for ln in self.read(PIPELINE).split("\n") if ln.startswith("| 1 |")]
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("Update main", rows[0])


class TestC17PlaybookPreApproval(ContractCase):
    def test_spec_review_gate_names_the_pre_approval_exception(self):
        section = playbook_section(self.read(PLAYBOOK), "### 4. Spec phase")
        self.assertIsNotNone(section, f"{PLAYBOOK} has no `### 4. Spec phase` section")
        self.assertIn(RESOLVE_WITH_USER, section)
        self.assertNotIn(RESOLVE_WITH_USER_OLD, section)


class TestC17SkillTddClause(ContractCase):
    def test_skill_md_tdd_paragraph_names_the_write_tool(self):
        lines = [ln for ln in self.read(PIPELINE).split("\n") if ln.startswith(TDD_PARAGRAPH)]
        self.assertEqual(len(lines), 1, f"{PIPELINE} needs one TDD evidence paragraph")
        self.assertIn(TDD_SKILL_WRITE_CLAUSE, lines[0])


class TestC17FlatWording(ContractCase):
    def test_docs_say_flat_packages_get_no_finalize_evidence(self):
        for rel in FLAT_NO_EVIDENCE_DOC_FILES:
            with self.subTest(file=rel):
                text = self.read(rel)
                self.assertIn(FLAT_NO_FINALIZE_EVIDENCE, text)
                for old in FLAT_NO_EVIDENCE_OLD:
                    self.assertNotIn(old, text)


class TestC17SkillBoundaries(ContractCase):
    def test_closed_skill_call_list_names_git_safety_check(self):
        lines = [ln for ln in self.read(BOUNDARIES).split("\n") if BOUNDARIES_CLOSED_LIST in ln]
        self.assertEqual(len(lines), 1, f"{BOUNDARIES} needs one closed Skill-call list")
        self.assertIn(GIT_SAFETY_CHECK_CALL, lines[0])
        self.assertIn(KICKOFF_DISPATCH, lines[0])


class TestC17TestingDoc(ContractCase):
    def test_strict_key_rows_match_the_fix_round_grader(self):
        section = playbook_section(self.read(TESTING_DOC), TESTING_STRICT_SECTION)
        self.assertIsNotNone(section, f"{TESTING_DOC} has no `{TESTING_STRICT_SECTION}` section")
        lines = section.split("\n")
        for start, needs in TESTING_ROW_NEEDS.items():
            with self.subTest(row=start):
                rows = [ln for ln in lines if ln.startswith(start)]
                self.assertEqual(len(rows), 1, rows)
                missing = [need for need in needs if need not in rows[0]]
                self.assertEqual(missing, [])
        missing = [need for need in TESTING_STRICT_NEEDS if need not in section]
        self.assertEqual(missing, [], f"{TESTING_DOC} strict section misses C16.4 / C17.1 wording")


class TestC17Changelog(ContractCase):
    def release_section(self):
        text = self.read(CHANGELOG)
        start = text.find("\n## 0.6.0 - ")
        self.assertNotEqual(start, -1, f"{CHANGELOG} has no 0.6.0 section")
        end = text.find("\n## ", start + 1)
        return text[start:end if end != -1 else len(text)]

    def test_known_limitations_name_the_missing_live_run(self):
        section = self.release_section()
        line = next((ln for ln in section.split("\n") if ln.startswith("- Known limitations:")), None)
        self.assertIsNotNone(line, "the 0.6.0 Known limitations bullet is gone")
        self.assertIn(CHANGELOG_NO_LIVE_RUN, line)

    def test_tdd_evidence_paths_are_exact(self):
        section = self.release_section()
        for path in CHANGELOG_TDD_PATHS:
            with self.subTest(path=path):
                self.assertIn(path, section)
        self.assertNotIn(CHANGELOG_TDD_OLD, section)


if __name__ == "__main__":
    unittest.main()
