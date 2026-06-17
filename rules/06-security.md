# Rule 06 — Security

## Purpose
Catch vulnerabilities and secret leaks before they ship. No final answer without a security pass.

## When applied
On every code change; especially auth, input handling, config, data access, dependencies.

## Required
Review the changed diff for:
- Input validation; output encoding.
- Authentication and authorization (including object-level access / IDOR — users see only their own data).
- Secrets — none hardcoded; loaded from env / secret store.
- Injection (SQL/NoSQL/command/XSS) — parameterized queries, no string interpolation into queries.
- Dependency risk; file access; sensitive data exposure.
- Logging hygiene (no secrets/PII in logs); error handling that doesn't leak internals.
- Rate limiting on auth-sensitive endpoints; permission boundaries.

Secret reporting rule: **never print a real secret value.** Mask it (`***MASKED***`) and report only `file:line` + risk type. Classify findings by severity.

## Forbidden
- Finalizing without a security analysis.
- Writing/committing/logging real secret values.
- Trusting input or assuming a caller is authorized.

## Checklist
- [ ] Input validated, output encoded.
- [ ] AuthN + AuthZ (incl. IDOR) checked.
- [ ] No hardcoded secrets; injection-safe.
- [ ] Logs/errors leak nothing.
- [ ] Findings masked + severity-tagged.
