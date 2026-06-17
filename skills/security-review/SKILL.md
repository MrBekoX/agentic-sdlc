---
name: security-review
description: Generic security review of code or a feature — input validation, auth, secrets, injection, dependencies, data exposure, logging, rate limiting, permission boundaries. Use to audit a diff or feature before finalizing. Reports findings with masked secrets and severity.
argument-hint: "<file/dir — defaults to current git diff>"
---

# Skill: security-review

> **Argument:** `/security-review $ARGUMENTS` — a file/dir to scan, or empty for the current `git diff`. Reply in Turkish. Governing rule: 06.

Systematically audits changes for vulnerabilities and reports findings safely.

## Orchestration (consult first)
Per **`orchestration`**: multiple independent lenses (injection / authz-IDOR / secrets / auth) fan out to a **dynamic-workflow** (parallel lenses) or, for interactive multi-angle review, an **agent-team**. Heavy single-lens analysis can go to the **`security-reviewer`** sub-agent.

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
- **Never print a real secret value.** Mask it: `Password=***MASKED***`.
- Give only `file:line` + risk type. Classify by severity (Critical / High / Medium / Low).

## Output
Findings table: `Severity | Category | File:Line | Risk | Recommendation` + a short summary. If fixes are needed, route to `fix-flow` / `feature-flow`.

## Limit
Audits and recommends; code changes happen via an implementation skill with user approval.
