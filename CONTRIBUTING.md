# Contributing

Thanks for helping improve agentic-sdlc. See [CONTRIBUTORS.md](CONTRIBUTORS.md) for credits.

## Before a PR
Run the full local gate (Windows: `py -3`):

```bash
py -3 scripts/check_all.py
py -3 tests/skills/harness.py
py -3 -m unittest discover -s tests -v
```

## Rules
- Supported runtimes are Claude Code and Codex only.
- Skills use the Assertion-contract house voice (`skills/skill-authoring/references/house-voice.md`); do not import borrowed law/flag/rationalization-style section labels from other plugins.
- No completion claim without fresh evidence. Commit/push only on request.
