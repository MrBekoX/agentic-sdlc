# ZCode Runtime Adapter — skill-level mapping

Status: **experimental adapter, not a 0.4.3 release target.** The supported release targets remain Claude Code and Codex (`docs/runtime-adapter.md`). This file maps the Claude-native mechanisms the house skills rely on to their ZCode Runtime equivalents, so the skills behave as designed once this plugin is installed and enabled from the local ZCode marketplace.

Evidence sources, fetched in-session: `zcode.z.ai/en/docs/{plugin,skill,hooks}` on 2026-09-19; `zcode.z.ai/en/docs/{commands,subagents}` on 2026-09-20; the bundled `plugin-creator` 0.1.1 reference (`references/plugin-json-spec.md`) on 2026-09-20. The dynamic-workflow capability is evidenced by the official changelog entry for client 3.14.0 (2026-09-19): "Added dynamic workflows that use a single script to orchestrate multiple sub-agents collaborating on complex tasks" / "Quickly start a workflow from the plus menu in the input box or via the `/workflow` command". Nothing beyond that is published — no API, no file format, no storage path — so every statement here about the workflow *shape* is an unverified in-session observation, not a documented fact. The subagents page states AGENTS.md injection exists since client v3.7.1, a version floor for these behaviors. No `zcode` CLI exists on the capture machine, so the exact client version is unknown.

## Capability map: Claude-native mechanism → ZCode Runtime

| Claude-native mechanism | ZCode Runtime equivalent | Adapter notes |
|---|---|---|
| `Skill` tool with qualified `agentic-sdlc:<skill>` ids | Same `Skill` tool and qualified ids; `$<skill>` in the input box and `/` → Skills group | Works after Install + Enable; the catalog shows plugin skills (flat `skills/<name>/SKILL.md`). Degraded path: read `${ZCODE_PLUGIN_ROOT}/skills/<skill>/SKILL.md` and record the degraded read. |
| `TodoWrite` task tracking | `TodoWrite` (native) | Direct equivalent. |
| `AskUserQuestion` | `AskUserQuestion` (native) | Direct equivalent. |
| Goal lock via `/goal` | ZCode Goal Mode `/goal` (set / replace / pause / resume / clear) | Native and stronger: goals persist across the session. This adapter doc's own build ran under it. |
| `/loop` fail-fix-retest | No built-in equivalent documented | Existing documented fallback applies: manual loop with command evidence (`# Loop Iteration` artifact). |
| Named `Workflow` `agentic-sdlc:spec-plan-draft` (Claude JS facade) | ZCode 3.14.0 added dynamic workflows (official changelog, 2026-09-19), started from the input-box plus menu or `/workflow`. **Its script API, file format and storage path are not published** — `zcode.z.ai/en/docs/workflow` 404s and the docs nav has no workflow page. | The house `workflows/*.js` certainly do not run there, and `plugin.json` has no `workflows` component key, so a plugin install cannot deliver one either. `workflows/zcode/spec-plan-draft.dwf.ts` is an **UNVERIFIED** port kept as a starting point for a live run: its shape was not derived from a Z.ai specification. The supported path is the embedded author → critic → revise adapter (same as Codex). |
| `Agent`/`Task` fresh-context specialists | `Agent` tool + plugin `agents/*.md` discovered as subagents | Frontmatter needs `name` + `description` (both present on all 9 house roles); extra keys such as `tools:` / `model:` are allowed, unrecognized keys are silently ignored. Limits: a subagent cannot spawn subagents, so in-subagent fan-outs degrade; backgrounded read-only research roles stay read-only. |
| Parallel fan-out | Parallel subagent launches in one message (foreground or background) | Reads fan out; writes stay serial — same rule as the portable matrix. |
| Runtime plugin root `${CLAUDE_PLUGIN_ROOT}` | `${ZCODE_PLUGIN_ROOT}` primary, `${CLAUDE_PLUGIN_ROOT}` alias injected | House skill bodies referencing `${CLAUDE_PLUGIN_ROOT}` keep resolving. Durable writes belong under `${ZCODE_PLUGIN_DATA}`. |
| Hook guardrails (`hooks-claude.json`) | `hooks/hooks-zcode.json` via `type: process` executors | Wired: `PreToolUse` (`Bash`) command guards, `PostToolUse` (`Write\|Edit`) write scan, `SessionStart` (`startup\|clear\|compact`) bootstrap. Gaps: Stop completion/flow guards and `flow-order-guard` unwired. The advisory `systemMessage` field is **not** part of ZCode's documented hook protocol, and the protocol states that unknown fields are ignored — so warn-only guards must also emit `hookSpecificOutput.additionalContext`, which is the documented model-visible channel. See `runtime-adapter.md`. |
| Slash commands (`/agentic-sdlc:git-safety-check`) | `commands/*.md` discovered by filename; invoked from `/` → Commands | One house command ships; frontmatter `description` + `allowed-tools` are accepted fields. |
| MCP servers | None declared (by design) | No network surface. |
| Transcript-based Stop gates (completion-claim, flow-step) | Not wired on ZCode | Manual evidence discipline applies: real command output, validator exit codes, and the completion-claim gate marker in the final report. |

## Per-skill adapter table

| Skill | Claude-native behavior it relies on | ZCode Runtime behavior |
|---|---|---|
| `using-agentic-sdlc` | `Skill` invocation with qualified ids | Qualified ids work post-install; else read the catalog-resolved `SKILL.md` and record the degraded mechanism. |
| `mind-spark` | Conditional `references/design-process.md` load | File read through the installed plugin root (flat layout keeps paths stable). |
| `spec-authoring`, `plan-authoring` | Prompt-level only | Unchanged; artifacts under `docs/agentic-sdlc/`. |
| `dispatch-strategy` | Runtime mechanism matrix | Main loop / `Agent` subagents; the dynamic-workflow tier exists in the client but has no published API, so treat it as unavailable and use the degraded note. Agent-team tier unavailable. |
| `agentic-sdlc-pipeline` | Named Workflow, `Skill` calls, `Agent` specialists, `TodoWrite`, `/goal`, `/loop` | Spec/plan steps run through the embedded author → critic → revise adapter with a fresh-context critic subagent (the `.dwf.ts` port is unverified and is not a supported path); `TodoWrite` and Goal Mode are native; loop is manual. Emit `Runtime: ZCode` once and a `ZCode Adapter Gate: <gate>` marker at each adapted gate, mirroring the Codex contract. |
| `feature-build`, `root-cause-fix`, `safe-refactor`, `test-authoring`, `security-audit`, `code-quality-review` | `Agent` fan-outs over the review/analysis roles, validator runs | Roles dispatch as ZCode subagents from `agents/*.md`; validators run via `python3 scripts/...`; in-subagent nesting degrades per the subagent limit. |
| `implementation-control`, `completion-claim-gate` | `Skill` invocation evidence, Stop backstops | `Skill` tool evidence stands; Stop backstops are unwired (documented gap), so the evidence checklist and final-report gate marker carry the claim. |
| `feedback-triage` | File/tool work only | Unchanged. |
| `skill-authoring` | Claude/Codex packaging guidance | ZCode packaging questions resolve through the `plugin-creator` reference and this repository's `.zcode-plugin/` files. |

## Validation status

- Verified (static + gate): manifest/marketplace/hook-wire schema conformance, 16 skill + 9 agent + 1 command discovery inputs, version binding — `tests/test_zcode_packaging.py`, full local gate green.
- Verified in-session (this client, build not recorded): subagent dispatch works, Skill tool resolves qualified ids from installed plugins. The workflow tier was observed but its API was not; treat that observation as unverified.
- Pending live proof (requires Install + Enable by the user): skill/command/agent discovery counts in Settings, hook firing on real events, and whether the `.dwf.ts` port compiles at all under the unpublished runtime.
