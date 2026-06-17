---
name: security-audit
description: This skill should be used first before answering, reading git diff, or asking for code when the user asks to audit or review code, a diff, endpoint, login flow, or feature for security: input validation, auth, authorization, IDOR, secrets, injection, dependencies, data exposure, logging, rate limiting, permission boundaries, or vulnerability risk. Do not use for general code-quality review, bug fixing, or feature implementation.
argument-hint: "<file/dir — defaults to current git diff>"
---

# Skill: security-audit

> **Argument:** `/security-audit $ARGUMENTS` — a file/dir to scan, or empty for the current `git diff`. Match the user's language. Governing contract: 06.

Systematically audits changes for vulnerabilities and reports findings safely.

## Orchestration (consult first)
Per **`dispatch-strategy`**: multiple independent lenses (injection / authz-IDOR / secrets / auth) fan out to a **dynamic-workflow** (parallel lenses) or, for interactive multi-angle review, an **agent-team**. Heavy single-lens analysis can go to the **`security-reviewer`** sub-agent.

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
