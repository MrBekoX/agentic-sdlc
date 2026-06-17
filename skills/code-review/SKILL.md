---
name: code-review
description: Generic code-quality review of a diff or file — readability, maintainability, simplicity, duplication, overengineering, naming, error handling, performance, architecture consistency, testability. Use to review a change before merge, ideally in a fresh context. Technology-agnostic.
argument-hint: "<file/dir — defaults to current git diff>"
---

# Skill: code-review

> **Argument:** `/code-review $ARGUMENTS` — a file/dir, or empty for the current `git diff`. Match the user's language.

Reviews changes for quality. Best run in a **fresh context** (delegate to the **`code-reviewer`** sub-agent) so the review isn't biased toward code it just wrote.

## Orchestration (consult first)
Per **`orchestration`**: prefer a fresh-context **sub-agent** (`code-reviewer`) that sees only the diff + criteria, not the authoring reasoning.

## Review areas
- **Readability** — is intent clear on first read?
- **Maintainability** — easy to change safely later?
- **Simplicity** — minimal solution; no needless complexity.
- **Duplication** — repeated logic that should be unified.
- **Overengineering** — speculative abstraction/config not asked for.
- **Naming** — intention-revealing, consistent with the codebase.
- **Error handling** — real paths handled; no swallowed errors.
- **Performance** — obvious hotspots (N+1, unbounded queries, needless allocation) — flag, don't micro-optimize blindly.
- **Architecture consistency** — respects existing layers/boundaries/conventions.
- **Testability** — is the change covered / coverable by meaningful tests?

## Output
Findings grouped by area, each with `file:line`, the issue, and a concrete suggestion. Separate **must-fix** (correctness, security, requirement gaps) from **optional** (style/preference).

## Discipline
- Flag only gaps that affect correctness, requirements, or maintainability. A reviewer asked to find problems will always find some — don't chase every nit into overengineering.
- No behavior changes here; this skill reviews and recommends.
