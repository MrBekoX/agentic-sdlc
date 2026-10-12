## Summary
<!-- What changed and why. Link the spec/plan if one exists. -->

## Scope
- [ ] Change is focused on one problem
- [ ] Runtimes affected: Claude Code / Codex / Kimi Code / Grok CLI / ZCode

## Evidence (required before merge)
<!-- On Windows, use `py -3` when `python3` is missing or is the Microsoft Store alias. -->
- [ ] **Tests:** command + result pasted (e.g. `python3 -m unittest discover -s tests` → OK)
- [ ] **Security:** diff reviewed for secrets/injection/authz; secrets masked
- [ ] **Release:** `python3 scripts/check_all.py`, `python3 tests/skills/harness.py`, and `python3 scripts/bump_version.py --check` pass
- [ ] No completion claim without fresh evidence (`completion-claim-gate`)
