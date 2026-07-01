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

## 2026-07-01 — A greedy `\s*`/`\s+` before a `$` end-anchor is O(n²) (ReDoS in command parsers)

- **Task / context:** B5 (#5) closing the Codex flow-order write-form bypass — new `preciseWriteTargetsOf` in `hooks/codex-rollout.mjs` re-implemented a subshell-strip helper as `seg.trim().replace(/^\(\s*/, '').replace(/\s*\)$/, '')`, mirroring the existing `parseBash` in `hooks/codex-write-signal.mjs`.
- **Symptom:** Security review measured the strip at ~1.1 s (40 KiB) → ~4.3 s (80 KiB) → ~17.6 s (160 KiB) on `"echo" + " ".repeat(N) + "x"` — a clean 4×-per-2× quadratic. At the 512 KiB command cap that hangs the PreToolUse hook for minutes; under `AGENTIC_FLOW_ORDER_BLOCK` the timeout then fail-opens → the hardening becomes a self-inflicted DoS/bypass. Triggered by ANY long internal whitespace run with no trailing `)` (not just a write).
- **Root cause:** `/\s*\)$/` is unanchored at the start, so the engine retries from every index in the whitespace run; each retry's greedy `\s*` scans to end then backtracks to find the required `)`+`$` — O(n) work × O(n) start positions = O(n²). The `$`-anchored greedy-whitespace shape is the trap, independent of the `g` flag.
- **Correct fix:** Replace with linear string ops — `trim()`, then single-char `slice` for a leading `(` / trailing `)`, then `trim()` again. No regex with a start-unanchored greedy `\s*` before `$`.
- **Preventive rule / automated check:** Never put a greedy `\s*`/`\s+` (or `[\s\S]*`) immediately before a `$` end-anchor in a scanner that runs on attacker/agent-influenced input; prefer `trim()`/two-pointer strips. A "linear (BR10)" claim in a comment is not evidence — add a timing regression test on a long internal-whitespace input (see `test_precise_scan_linear_internal_whitespace`). **Known residual:** the identical twin at `hooks/codex-write-signal.mjs:69` (`parseBash`) is byte-locked and pre-existing; it is reachable by default via the always-on `scan-write-codex.mjs` secret guard on every Bash command — a separate follow-up (needs a byte-lock rebaseline), not fixed in #5.
- **Related files & tests:** `hooks/codex-rollout.mjs` (`stripWrappingSubshell`); `tests/test_codex_flow_order_guard.py` (`test_precise_scan_linear_internal_whitespace`, `test_precise_scan_linear`, `test_raw_scan_linear_flood`).

---

## 2026-06-21 — Python interpreter is `python3`, not `python`

- **Task / context:** Running the quality gate (`scripts/check_all.py`, `tests/skills/harness.py`, the unittest suite).
- **Symptom:** Commands invoked as `python ...` fail or select the wrong interpreter where `python` is Python 2 or absent.
- **Root cause:** The project standardizes on `python3`; bare `python` is not guaranteed to exist or resolve to Python 3.
- **Correct fix:** Invoke every gate command and script with `python3`.
- **Preventive rule / automated check:** The gate commands in `AGENTS.md` and `CLAUDE.md` pin `python3`; keep new docs and scripts consistent. (This entry documents an existing repo convention rather than a new incident.)
- **Related files & tests:** `AGENTS.md`, `CLAUDE.md`, `scripts/check_all.py`, `tests/skills/harness.py`.
