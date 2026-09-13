---
name: mind-spark
description: This skill should be used first as the AGENTIC-SDLC pre-spec intent gate for mind-spark brainstorming in any language when the user wants to explore options, discuss direction, or resolve ambiguous build or design intent before code and before requirements or success criteria are agreed. It applies to AGENTIC-SDLC-owned design phases, respects explicit selection of another plugin, and skips clear fixes, refactors, tests, reviews, and tiny edits.
---

# Skill: mind-spark (pre-spec intent gate)

## Process owner

Before applying this design gate, follow the user's explicit plugin or skill choice. An explicit `superpowers:brainstorming` request stays with Superpowers. A newer explicit choice overrides the established owner. Otherwise preserve the established owner for this design phase, including across resume/compact; loading mind-spark does not switch it. If the owner is Superpowers, do not execute this design gate; complete the instruction-loading handoff below before continuing its phase.

The selected owner's actual instructions must be loaded **before** asking its next question or presenting design options. After resume, compaction, or a supplied summary, reload the selected procedure now even if the summary says that skill already began: summaries carry ownership and saved progress, not a current instruction body. Invoke `Skill` with the selected identifier in Claude Code (for example `superpowers:brainstorming`), or read that owner's catalog-resolved `SKILL.md` in Codex. Continue from the saved progress without repeating completed approvals. Reuse a body already present only in uninterrupted context; otherwise load it. If loading is unavailable, report the gap instead of continuing from memory.

With no owner established, a direct mind-spark or AGENTIC-SDLC route selects this house design gate. Claude Code activates `agentic-sdlc:mind-spark` with `Skill`; Codex CLI selects the AGENTIC-SDLC catalog entry through `/skills` or `$`. If activation is unavailable, read the selected catalog entry's `SKILL.md` (house fallback: `${PLUGIN_ROOT}/skills/mind-spark/SKILL.md` in Codex, `${CLAUDE_PLUGIN_ROOT}/skills/mind-spark/SKILL.md` in Claude Code) and state the degraded mechanism. Track the owner in conversation context and re-evaluate for a new phase or explicit user change. Never stack both design processes or repeat an approved design just because both plugins are installed. Runtime security hooks still apply independently of the process owner; permission and evidence requirements remain in force.

## Load the house procedure

Only when AGENTIC-SDLC owns this design phase, read [references/design-process.md](references/design-process.md) before the first design step. Resolve the link from this installed skill's directory. In Claude Code, use `Read`; in Codex, use the available file-reading tool for the exact installed reference path. This entrypoint's body is not the house design procedure; reuse the reference's actual body only in uninterrupted context. Reload it after resume, compaction, or a supplied summary, then continue from saved progress.

Do not load or apply the house reference for a phase owned by another plugin. Complete that owner's actual instruction-loading handoff in the Process owner section, then return control to it. If the required instructions cannot be loaded, report the missing capability and stop the phase instead of supplying a design from memory.

The reference retains the scope test for already-specified `root-cause-fix` / `safe-refactor` work, the design approval gate, and the downstream handoff to `agentic-sdlc-pipeline` or the runtime spec-plan adapter (`spec-plan-draft` only where the Claude Code Workflow is available).

## Depth contract

This entrypoint is complete when the selected owner's actual procedure has been loaded or a concrete loading blocker has been reported. Apply the house design-depth contract only after reading its conditional reference.

## Excuse -> check

| Excuse | Check |
|---|---|
| "The owner was named in the summary, so I can continue." | Locate the actual selected procedure in context or load it; a label is not instructions. |
| "mind-spark was loaded, so I have its design checklist." | This file is routing only. House ownership requires the conditional reference; other ownership requires that owner's skill. |

## No placeholders

Do not treat an owner announcement or a promise to load instructions as a completed handoff. Do not provide phase content while the selected procedure is missing.
