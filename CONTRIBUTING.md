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

On Windows, use `py -3` in place of `python3` when the Python launcher is configured. Pull requests
also run the same deterministic gate on Windows and Linux in `.github/workflows/ci.yml`; attach local
output when a platform-specific failure cannot be reproduced in CI.

## Rules

- Supported runtimes are Claude Code and Codex only.
- Skills use the Assertion-contract house voice (`skills/skill-authoring/references/house-voice.md`); do not import borrowed law/flag/rationalization-style section labels from other plugins.
- No completion claim without fresh evidence. Commit/push only on request.
