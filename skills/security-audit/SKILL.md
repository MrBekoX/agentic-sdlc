---
name: security-audit
description: Use first in any language to audit code, a diff, endpoint, or login flow for security covering input validation, auth, authorization, IDOR, secrets, injection, dependencies, data exposure, rate limiting, or vulnerability risk. Not for general code-quality review or bug fixing.
---

# Skill: security-audit

> **Argument:** `/security-audit $ARGUMENTS` — a file/dir to scan, or empty for the current `git diff`. Match the user's language. Governing contract: 06.

Systematically audits changes for vulnerabilities and reports findings safely.

## Orchestration (consult first)
Per **`dispatch-strategy`** and `docs/runtime-adapter.md`: multiple independent lenses (injection / authz-IDOR / secrets / auth) fan out to a dynamic-workflow, agent-team, subagents, or the runtime's parallel equivalent. Heavy single-lens analysis should use a fresh-context `security-reviewer` specialist when available. If the runtime lacks a fresh-context specialist, record `Delegation Degraded: fresh-context specialist unavailable`, perform the pass in the main loop, and mark the result non-independent.

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
Findings table: `Severity | Category | File:Line | Risk | Recommendation` + a short summary. If fixes are needed, route to `root-cause-fix` / `feature-build`.

## Limit
Audits and recommends; code changes happen via an implementation skill with user approval.
