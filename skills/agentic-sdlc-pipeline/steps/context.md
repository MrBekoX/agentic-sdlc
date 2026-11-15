# Context

Understand the request and the code before anything is drafted or changed, then lock the scope. This step writes `context.md` in the package and changes no project file.

In the commands below, `<python>` is the interpreter that starts the card's `then=` line and `<root>` is the card's `root=` value. Run helpers with `-B`, as the `then=` line does: it keeps `__pycache__` out of the plugin folder. `<slug>` is the last part of the card's `package=` value.

## 1. Read the request and the probes
- Read `request.md` in the package: the user's words, verbatim.
- The runner probed the workspace at start. Read `probes` in `<package>/state.json`: `explore_mode` (`parallel`, `single` or `greenfield_inline`), the layers under `details.explore_mode.layers`, the manifests under `details.deps`, the toolchains under `details.toolchain`. A probe value `error` means the probe failed: explore by hand and say so.
- For a narrower scope than the project root, run the detector yourself: `"<python>" -B "<root>/scripts/detect_context.py" --path <scope>` (repeat `--path` per root). Never run a same-named file from the project.

## 2. Explore, as the card's mechanism line says
- `main` or `inline-degraded`: read the code yourself.
- `subagent`: give each layer (in `single` mode, the one area) to a fresh sub-agent with the role file `<root>/agents/context-analyst.md`, the scope and the question. Start them in one message so they run in parallel. Merge, deduplicate and judge their findings yourself.
- `team` or `workflow`: run one analyst per layer through that mechanism; you merge.
- `greenfield_inline`: there is no code to explore. Write the analysis from the request; start no analyst with nothing to read.
- When the sub-agent tool is missing or refused, record it and explore inline: `"<python>" -B "<root>/scripts/sdlc.py" note --slug <slug> --degraded subagent --reason missing|denied|unavailable`.

What to read: the files the work will touch, their callers, tests and config, and the conventions (naming, structure, error handling, test style). Check every API and signature in the real code; never assume one. Scope the reading: do not read hundreds of files in the main loop.

## 3. Write context.md
Write `<package>/context.md` with these three sections. Keep each line concrete and checkable; "should work" is not a criterion. Mask any secret you quote as `***MASKED***`.

```md
## Analysis Summary
Problem:
Current behavior:
Expected behavior:
Affected files and modules:
Existing tests:
Conventions:
Initial hypothesis:

## Scope Lock
In scope:
Out of scope:
Files allowed to change:   # `none` when this run changes no project file (a review, an audit, a spec or plan only)
Files read-only:
Risk areas:                # migration, backward compatibility, API contract, security, performance, test breakage, mobile, deploy, secret exposure
High-risk surfaces:        # from the list below, or `none`
Rollback plan:
Verification plan:

## Goal Lock
Main goal:
Non-goals:
Done when:                 # the observable end state
Constraints:
```

The line `## Scope Lock` must appear exactly like that, on its own line. Write the file in this visit: a file left from an earlier visit, or rewritten byte for byte, does not count.

## Scope Lock
The Scope Lock is the boundary for the rest of the run. A file outside "Files allowed to change" is a finding. New work found later becomes a new task in the plan, never a silent change.

High-risk surfaces. When the work changes any of these, the run is high risk and never takes the light form:
- authentication: login, passwords, OAuth, SSO, MFA;
- payment, billing, checkout, refunds;
- security controls;
- database migrations and schema changes;
- a production bug;
- an API contract: a public API, a breaking change, an endpoint signature;
- permissions and roles: RBAC, ACL, authorization, native mobile permissions;
- user data: PII, personal data, data retention;
- tokens and sessions: JWT, cookies, API keys, refresh tokens;
- row-level security and tenant isolation.

When the work changes one of them and the card's flow line shows `form=light` or `risk=normal`, raise the run before you finish:
`"<python>" -B "<root>/scripts/sdlc.py" escalate <flow> --slug <slug> --reason "<surface and file>" --risk high`
`<flow>` is the card's `flow=` value. Add `--form gated` for a light run. Tell the user which surface raised it. When start recorded a risk reason (`risk_reason` in `state.json`), check it against what you found.

If the session already holds an active goal from another process, keep it: write this lock in `context.md` only.

## Finish
Write `context.md`, then run the card's `then=` command.
