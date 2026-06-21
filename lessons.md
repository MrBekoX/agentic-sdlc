# lessons.md — verified, durable lessons for agentic-sdlc

Append a lesson only after a **verified** failure or wrong solution that you have reproduced, fixed, and root-caused — and only when the lesson is general enough to prevent similar mistakes in future work. Prefer enforcing each rule with a test, schema, linter, or hook over relying on this prose.

Review relevant entries before starting similar work. Keep newest entries at the top.

**Do not record:** transient network/tool errors, unverified guesses, secrets or machine-specific data, or duplicates of an existing lesson.

## Entry schema

Each entry includes:

- **Date** — `YYYY-MM-DD`
- **Task / context** — what was being done
- **Symptom** — the observable failure
- **Root cause** — the underlying reason
- **Correct fix** — what actually resolved it
- **Preventive rule / automated check** — what stops recurrence (ideally enforced)
- **Related files & tests** — paths to the change and its coverage

---

## 2026-06-21 — Python interpreter is `python3`, not `python`

- **Task / context:** Running the quality gate (`scripts/check_all.py`, `tests/skills/harness.py`, the unittest suite).
- **Symptom:** Commands invoked as `python ...` fail or select the wrong interpreter where `python` is Python 2 or absent.
- **Root cause:** The project standardizes on `python3`; bare `python` is not guaranteed to exist or resolve to Python 3.
- **Correct fix:** Invoke every gate command and script with `python3`.
- **Preventive rule / automated check:** The gate commands in `AGENTS.md` and `CLAUDE.md` pin `python3`; keep new docs and scripts consistent. (This entry documents an existing repo convention rather than a new incident.)
- **Related files & tests:** `AGENTS.md`, `CLAUDE.md`, `scripts/check_all.py`, `tests/skills/harness.py`.
