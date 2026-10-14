# Contributing

Thanks for helping improve agentic-sdlc. See [CONTRIBUTORS.md](CONTRIBUTORS.md) for credits.

## Before a PR

Run the full local gate with Python 3:

```bash
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
python3 scripts/bump_version.py --check
```

On Windows, use `py -3` in place of `python3` when `python3` is missing or is the Microsoft Store
alias. `.github/workflows/ci.yml` runs the same deterministic gate on Windows, Linux and macOS for every
pull request and every push to `main`; still attach local gate output to the PR, and name the OS
when a failure is platform-specific.

## Rules

- Supported runtimes are Claude Code and Codex. Kimi Code, Grok CLI, ZCode and Cursor are
  adapters with narrower hook wiring; a change that touches a runtime adapter names the runtimes
  it was checked on.
- Skills use the Assertion-contract house voice (`skills/skill-authoring/references/house-voice.md`); do not import borrowed law/flag/rationalization-style section labels from other plugins.
- No completion claim without fresh evidence. Commit/push only on request.
