# Strategy

Decide once, for this run, how each heavy part of the work runs: in the main loop, in a fresh sub-agent, in the runtime's own workflow engine, in an agent team, or as parallel command runs. Later cards print the mechanism decided here on their `mechanism=` line. This step runs once: after the map is confirmed it cannot change, and re-entry is read-only.

Do only this step now. Decide from the card and the request: read no project file, change nothing, and create no branch before the map is confirmed.

## Read the card
- `default=` lists `<key>:<mechanism>` for each part of this run that needs a mechanism. The runner built it from the runtime's capability row and the start probes.
- `confirm=` is the command that writes `strategy.json`, with placeholders to fill in.
- Runner commands start like the card's `then=` line: `"<python>" -B "<root>/scripts/sdlc.py"`. `-B` keeps `__pycache__` out of the plugin folder. `<slug>` is the last part of the card's `package=` value.

Keys: `context` (analysis), `draft` (spec and plan authors), `draft.critic` (their critic), `implement`, `security`, `quality-gates`, `quality-review`, `audit`, `docs-check`.

Mechanisms:
- `main`: you do it in the main loop.
- `subagent`: a fresh sub-agent does it and returns the result.
- `workflow`: the runtime's own workflow engine runs it.
- `team`: an agent team whose members talk to each other, with you as the live lead.
- `runner-loop`: the runner drives the spec/plan loop, and each role runs in a fresh sub-agent.
- `runner-loop-inline`: the same loop, with you playing each role.
- `inline-degraded`: a fresh-context role run in the main loop because no sub-agent is available; the final claim reports it.
- `parallel-runs`: independent check commands run side by side.

## 1. Declare what this session has
Fill `--capabilities workflow=<v>,subagent=<v>,team=<v>` from the tools you can call now, not from what the runtime usually offers:
- `workflow`: a tool that launches the runtime's own multi-agent workflow engine;
- `subagent`: a tool that starts a separate agent with a fresh context and returns its result;
- `team`: agent teams whose members message each other.

Each value is `yes` (you can call it now), `no` (there is no such tool) or `denied` (the tool exists, but the user or the permission settings refuse it). Declare honestly: the record can be compared with the session's tool list.

## 2. Keep or override each default
Keep a default unless the shape of the work says otherwise. Override only a key the card's `default=` line lists: any other key is refused (`not_applicable:<key>`). An override is `--set <key>=<mechanism>:"<reason>"`, and the reason names the property of the work that picks the mechanism:
- an independent part whose intermediate reads are not needed later: `subagent`;
- about three or more similar independent items (layers, libraries, review lenses): one `subagent` per item, or `workflow`;
- interdependent code, ordering or design decisions, small single-file work: `main`;
- peers who must talk under a live lead, in an interactive session only (never a headless or scheduled run): `team`.

Pick the smallest mechanism that fits: `main` < `subagent` < `workflow` < `team`. "Delegate it" and "to be safe" are not reasons. Heavy independent work kept in `main` needs a reason too.

## 3. Rules the runner enforces
`confirm` is refused with `strategy_refused:<rule>` until all of these hold:
- A mechanism needs its capability declared `yes`: `subagent` and `runner-loop` need `subagent=yes`; `workflow` needs `workflow=yes` and a runtime with an engine; `team` needs `team=yes`.
- The fresh-context keys `draft.critic`, `security`, `audit` and `quality-review` are never `main`, `team` or `parallel-runs`. They take `workflow`, `subagent`, `runner-loop` (`draft.critic` only), or `inline-degraded` / `runner-loop-inline` when `subagent` is declared `no` or `denied`.
- `runner-loop` and `runner-loop-inline` belong to `draft` and `draft.critic` only.
- A workflow engine that the runtime runs only on the user's explicit request is never a default. Override to it only when the user asked for it, and quote their words in the reason.
- Every override has a reason.

When a default needs a capability you declared `no` or `denied`, override that entry. For example:
- no workflow tool, sub-agents available: `--set draft=runner-loop:"no workflow tool in this session" --set draft.critic=runner-loop:"no workflow tool in this session"`;
- no sub-agent tool: `--set security=inline-degraded:"no sub-agent tool in this session"`, the same for `audit` and `quality-review`, `runner-loop-inline` for the two draft keys, and `main` for `context`.

## 4. Confirm
Run the card's `confirm=` command with your values filled in, for example:

`"<python>" -B "<root>/scripts/sdlc.py" strategy confirm --slug <slug> --capabilities workflow=no,subagent=yes,team=no --set draft=runner-loop:"no workflow tool in this session" --set draft.critic=runner-loop:"no workflow tool in this session"`

It prints `strategy=confirmed` and a preview of the next card. A refusal names the failing rule: correct the declaration or the override and run it again. `strategy_already_confirmed` means the map is already fixed: follow the current card.

## Finish
Run the card's `then=` command. It records this step and prints the next card.
