---
name: test-authoring
description: This skill should be used first in any language to write, add, repair, or design tests before inspecting code for test-only prompts covering unit, integration, regression, e2e, flaky/failing tests, meaningful assertions, coverage, test doubles, or test strategy. Test-only work that must not change production behavior; not for features, fixes, or refactors. Not for steps inside an active agentic-sdlc-pipeline run.
---

# Skill: test-authoring

> **Argument:** `/test-authoring $ARGUMENTS`. Match the user's language. Governing contract: 05.

Designs and writes meaningful tests, or repairs broken ones.

## Invariant
A test that has never failed proves nothing — each test must be able to fail for the reason it guards.

## Tripwires
- wrote the test green-first without ever seeing it fail
- asserting on implementation details instead of behavior
- coverage went up but no behavior is actually pinned

## Proof
Each new test shown failing for the right reason before it passes; for characterization tests, the captured baseline.

## Excuse → check
| Excuse | Check |
|---|---|
| "It obviously tests X." | Break X and watch the test fail — that is the only proof it tests X. |
| "Coverage is 100%." | Coverage is lines executed, not regressions caught. Assert behavior. |

## Depth contract (proportional — scale rigor to the change)
Scale the suite to the surface under test: a pure helper needs less than an auth path, but every test you do write must pin something real.
- Each test names the specific behaviour it guards **and** the concrete code mutation (flipped comparison, dropped branch, off-by-one) that would turn it red. If no mutation makes it fail, it pins nothing — delete or rewrite it.
- An edge case is a concrete input, not the phrase "edge cases": the empty/null value, the boundary value on both sides, the actual error or unauthorized path. Name the input.
- Assert the observable outcome the caller sees — the returned value, the raised error, the persisted state — not that a collaborator was invoked. A test that checks `mock.called` describes the test's own scaffolding.
- Show the failing run before the passing one; for characterization tests, capture the baseline first.

## Excuse -> check
| Excuse | Check |
|---|---|
| "The happy path is covered, good enough." | Name the boundary or error input that has no failing test yet, then add it. |
| "The mock returns X, so it works." | Assert the outcome the caller observes, not that the mock was called. |
| "I'll mark the edge cases later." | Write the concrete input now — empty, null, the boundary — or it never gets pinned. |

## No placeholders
Do not ship "covers edge cases" without listing each one as a concrete input. Do not ship a test name that fails to state scenario + expectation (`test_works` names nothing). Do not assert on a mock/spy in place of the behaviour the caller observes.

## Shallow example (reject this)
A test named `test_works` whose body asserts only `mock.called` pins nothing — flip any real logic and it still passes. Reject it: name the behaviour, name the input that would break it, and watch it go red first.

## Call-order guard — dispatch-strategy first

After loading `test-authoring`, do not read files, run shell commands, or take any other action until you have called `Skill` -> `agentic-sdlc:dispatch-strategy` to set the working strategy for this task. Required even when the likely answer is "small single-file work; main loop is enough" — making the decision explicit is the point. The skill then runs under the chosen mechanism; the Orchestration section below applies it (reads fan out, writes stay serial).

## Orchestration — fan out coverage analysis, you coordinate (consult `dispatch-strategy` first)
For a broad suite across several behavior-areas or modules, dispatch **one `test-engineer` per area in a single message** to analyze coverage gaps and judge whether existing tests pin real behavior — read-only, concurrent. You (main loop) stay the **coordinator**: merge the gap reports, prioritize, decide what to write. Writing/repairing the tests stays serial in the main loop (or worktree-isolated for a large multi-file pass) — never two agents on one file.
- **Degrade:** a single small target, or running inside a delegated sub-agent (no nesting), or a runtime without parallel agents → analyze in the main loop and flag `Delegation Degraded: parallel specialists unavailable`.

## Flow
Read [references/core.md](references/core.md) before step 1 and run the steps marked "core step" exactly as its `## Core steps` section writes them. Resolve the link from this installed skill's directory. In Claude Code, use `Read`; in Codex, use the available file-reading tool for the exact installed reference path. Reload it after resume, compaction, or a supplied summary. Read it after the `dispatch-strategy` call, never before it.

1. **Behavior and test level** — core step 1.
2. **Failing test** — core step 2.
3. **Pass without changing production code** — core step 3.
4. **Targeted run, then the suite** — core step 4.
5. **Assertion review** — core step 5.
