# Testing

## Fast Local Gate

Run these before claiming the repo is healthy:

```bash
python scripts/check_all.py
python tests/skills/harness.py
python -m unittest discover -s tests -v
```

What this proves:

- Skill frontmatter and naming are valid.
- Agent, workflow, hook, skill contract, and script references resolve.
- Golden skill cross-references have not drifted.
- Safety fixture evidence is wired to real skill contracts, skills, or hooks.
- Hook and workflow JavaScript parses when `node` is available.
- Python helper scripts pass their deterministic unit tests.

What this does not prove:

- Claude Code actually chose the right skill in a live session.
- The model followed every step in a skill body.
- A human-facing workflow succeeded end-to-end.

## Automation Policy

No CI workflow is configured for now. Use the fast local gate above before making health claims. Publishing, release creation, pushing generated commits, or marketplace/plugin publication must remain a manual, explicit user-requested step.

## Trigger Evals

Trigger eval fixtures live in `tests/skills/evals/*.json`. Each skill has positive and negative prompts.

Run a live trigger eval when Claude CLI/runtime support is available:

```bash
python scripts/run_trigger_eval.py --skill-path skills/dev-flow --eval-set tests/skills/evals/dev-flow.json
```

These evals check whether the skill triggers. They do not yet judge procedure compliance.

## Future Claude Behavior Evals

The procedure eval layer starts with `scripts/run_behavior_eval.py`. You can validate fixture shape without live Claude:

```bash
python scripts/run_behavior_eval.py --eval-set tests/skills/behavior/completion-claim-gate.json --dry-run
```

When Claude CLI/runtime support is available, run it live:

```bash
python scripts/run_behavior_eval.py --eval-set tests/skills/behavior/completion-claim-gate.json --allow-missing-claude
```

This layer should grow toward transcript JSONL checks for evidence such as:

- The intended skill was invoked.
- The agent did not claim success without verification.
- Required subagents or workflows were dispatched.
- Tests/security review were actually run or explicitly skipped with reason.

Do not trust final prose alone; parse transcript/tool evidence where possible.

## Dev-Flow Procedure Evals

`dev-flow` needs a stricter transcript-based check because triggering the skill is not enough. Use:

```bash
python scripts/run_procedure_eval.py --eval-set tests/skills/procedure/dev-flow.json --dry-run
```

To validate evaluator logic against a deterministic sample transcript:

```bash
python scripts/run_procedure_eval.py --eval-set tests/skills/procedure/dev-flow.json --transcript tests/fixtures/transcripts/dev-flow-procedure-pass.jsonl
```

To run a live Claude Code eval in an isolated copied fixture:

```bash
python scripts/run_procedure_eval.py --eval-set tests/skills/procedure/dev-flow.json --live --max-budget-usd 2.00
```

Live mode defaults to `--permission-mode auto` so safe headless commands can run without an interactive prompt. Override it only when intentionally auditing permission behavior.

This live eval is a Claude Code transcript check. It inspects stream-json tool use for:

- required skill invocations such as `agentic-sdlc:dev-flow`, `orchestration`, `feature-flow`, `security-review`, `implementasyon-control`, and `completion-claim-gate`
- `agentic-sdlc:spec-plan-draft` workflow use in Claude Code; Codex dev-flow uses the embedded adapter instead
- `detect_context.py` and `validate_artifacts.py` commands
- spec/plan artifacts under `docs/specs/` and `docs/plans/`
- absence of forbidden publish commands such as `git commit`, `git push`, and `git merge`
- runtime completion without `result` errors such as `error_max_budget_usd`
- no permission denials; a denied command does not count as an executed procedure step
