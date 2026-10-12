---
name: security-audit
description: This skill should be used first in any language to audit code, a diff, endpoint, or login flow for security covering input validation, auth, authorization, IDOR, secrets, injection, dependencies, data exposure, rate limiting, or vulnerability risk. Not for general code-quality review or bug fixing.
---

# Skill: security-audit

> **Argument:** `/security-audit $ARGUMENTS` — a file/dir to scan, or empty for the current `git diff`. Match the user's language. Governing contract: 06.

Systematically audits changes for vulnerabilities and reports findings safely.

## Invariant
Every finding carries a concrete location and exploit path, or it is not a finding — and no real secret value is ever printed.

## Tripwires
- flagging a "possible issue" with no file:line or reproduction
- about to paste a real secret/token/key into the report
- scanning only the happy path

## Proof
Per finding: file:line, the vulnerable input→sink flow, and a masked example. For "clean": the surfaces actually checked.

## Excuse → check
| Excuse | Check |
|---|---|
| "It looks fine." | Looking is not auditing. Trace the untrusted input to the sink. |
| "It's internal-only." | Internal IDOR/injection still ships and still breaches. |

## Depth contract (proportional — scale rigor to the change)
Scale depth to the diff: a config tweak needs less than a new request handler, but every verdict you reach must rest on a traced flow, not a glance.
- Each finding traces the untrusted input from its entry point through every transformation to the dangerous sink, naming both ends — `req.query.id` (source) → `db.query(\`...${id}\`)` (sink) at `file:line`. A finding with no input→sink trace is a guess.
- A "clean" verdict names the surfaces actually traced and, for each untrusted input, why it cannot reach a sink (parameterized, encoded, allow-listed, never concatenated). "Clean" that names nothing checked is untested.
- Severity is justified by concrete impact — what the attacker gains (reads another tenant's rows, executes shell, forges a session) — not a bare label.
- Trace the failure and bypass paths, not only the happy path: the empty token, the unexpected type, the request that skips the guard.

## Excuse -> check
| Excuse | Check |
|---|---|
| "It's validated upstream." | Name where it's validated, and show the validated value is the same one that reaches the sink — not a re-read or sibling field. |
| "There's no user input here." | Name every parameter and where it originates; one sourced from a request, header, or file IS user input. |
| "Severity is High." | Add the impact sentence: what does the attacker actually get when they exploit it? |

## No placeholders
Do not write "treat as safe" or "standard string handling". Do not write "no concerns" without the traced surfaces behind it. Do not assign a severity with no impact sentence. Do not call a surface "clean" while naming nothing you checked.

## Shallow example (reject this)
A report whose only reasoning is "standard string handling, no issues" asserts safety without tracing a single input to a sink. Reject it: name the surfaces you traced and, per untrusted input, the reason it cannot reach a sink.

## Call-order guard — dispatch-strategy first

After loading `security-audit`, do not read files, run shell commands, or take any other action until you have called `Skill` -> `agentic-sdlc:dispatch-strategy` to set the working strategy for this task. Required even when the likely answer is "small single-file work; main loop is enough" — making the decision explicit is the point. The skill then runs under the chosen mechanism; the Orchestration section below applies it (reads fan out, writes stay serial).

## Orchestration — one reviewer per lens, you coordinate (consult `dispatch-strategy` first)
The lenses (injection / authz-IDOR / secrets / auth) are independent read-only slices: dispatch **one `security-reviewer` per lens in a single message** so they run concurrently — parallel `Agent` calls, or a `Workflow` when you want the fixed lens set run deterministically. You (main loop) stay the **coordinator**: merge findings, dedup overlapping reports across lenses, rank by severity, decide. The audit reads only; fixes route to `root-cause-fix` / `feature-build` with approval.
- **Degrade:** inside a delegated sub-agent (no nesting) or a runtime without parallel agents → run the lenses in the main loop and record `Delegation Degraded: fresh-context specialist unavailable`, marked non-independent.
- **Higher-rigor pass:** the `multi-lens-review` workflow (preset `security`) runs this lens fan-out, then has independent skeptics adversarially refute each finding — only the confirmed survive. A result with `complete: false`, an `incompleteLenses` entry or an `unverified` finding is not a clean review: report those lenses and findings as not reviewed. Use it when a wrong call is costly. Claude Code: named `Workflow` `agentic-sdlc:multi-lens-review`. Grok CLI: `/workflow multi-lens-review` or the `workflow` tool with name `multi-lens-review` and args `{preset:"security", scope:<diff|files>}` when `.grok/workflows/multi-lens-review.rhai` is in the catalog — do not call Claude JS `Workflow`. If that catalog script is unavailable, keep the parallel `Agent`/`spawn_subagent` lens fan-out.

## Review areas
1. **Input validation** — all external input validated/sanitized.
2. **Output encoding** — context-correct encoding; XSS-safe rendering.
3. **Authentication** — token/session validity, lifetime, signing source.
4. **Authorization** — endpoint protection + object-level access (IDOR): a user reaches only their own data; route id ↔ token subject.
5. **Secrets** — none hardcoded; loaded from env/secret store.
6. **Injection** — SQL/NoSQL/command/template: parameterized, no string interpolation into queries/commands.
7. **Dependency risk** — known-vulnerable or unpinned dependencies.
8. **File access** — path traversal, unsafe upload/download.
9. **Data exposure** — over-fetching, leaking internal fields/PII.
10. **Logging hygiene** — no secrets/PII/tokens in logs.
11. **Error handling** — no stack traces / internals leaked to clients.
12. **Rate limiting** — brute-force protection on auth-sensitive endpoints.
13. **Permission boundaries** — least privilege; no privilege escalation paths.

## Reporting rule (critical)
- **Never print a real secret value.** Keep the key name and replace only the value with `***MASKED***` (a connection-string password value is written as `***MASKED***`).
- Give only `file:line` + risk type. Classify by severity (Critical / High / Medium / Low).

## Output
Findings table: `Severity | Category | File:Line | Risk | Recommendation` + a short summary. If fixes are needed, route to `root-cause-fix` / `feature-build`.

## Limit
Audits and recommends; code changes happen via an implementation skill with user approval.
