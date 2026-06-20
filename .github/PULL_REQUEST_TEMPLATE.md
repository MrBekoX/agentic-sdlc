## Summary
<!-- What changed and why. Link the spec/plan if one exists. -->

## Scope
- [ ] Change is focused on one problem
- [ ] Runtimes affected: Claude Code / Codex

## Evidence (required before merge)
- [ ] **Tests:** command + result pasted (e.g. `py -3 -m unittest discover -s tests` → OK)
- [ ] **Security:** diff reviewed for secrets/injection/authz; secrets masked
- [ ] **Release:** `py -3 scripts/check_all.py`, `harness.py`, and `bump_version.py --check` pass
- [ ] No completion claim without fresh evidence (`completion-claim-gate`)
