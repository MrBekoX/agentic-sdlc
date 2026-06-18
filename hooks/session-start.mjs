// SessionStart - injects git status plus AGENTIC-SDLC bootstrap context.
// On git errors, fall back to unknown state rather than breaking session startup.
import { execFileSync } from 'node:child_process';

function git(args) {
  try {
    return execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } catch {
    return '';
  }
}

function currentBranch() {
  return git(['branch', '--show-current']) || git(['rev-parse', '--abbrev-ref', 'HEAD']) || '(unknown)';
}

const branch = currentBranch();
const porcelain = git(['status', '--porcelain']);
const changed = porcelain ? porcelain.split(/\r?\n/).filter(Boolean).length : 0;
const ahead = git(['rev-list', '--count', '@{u}..HEAD']) || '0';
const behind = git(['rev-list', '--count', 'HEAD..@{u}']) || '0';

const bootstrap = [
  '<AGENTIC_SDLC_BOOTSTRAP>',
  'You are in the AGENTIC-SDLC Claude Code skill plugin.',
  'Use root skills/ as the skill source; do not assume .claude/skills/.',
  'Bootstrap guidance: using-agentic-sdlc defines session-local routing memory. Invoke that skill only when no clearer focused skill directly satisfies the prompt or the conversation changes scope.',
  'Use the smallest sufficient skill for the current prompt; agentic-sdlc-pipeline is only for full-envelope end-to-end SDLC work.',
  'Route by semantic intent, not exact keywords or prompt language: any-language brainstorming, option exploration, or uncertain direction -> agentic-sdlc:mind-spark; any-language plan-only, HOW, task breakdown, or no direct code/fix yet -> agentic-sdlc:plan-authoring, even when the prompt mentions a bug.',
  'For any-language plan-only/HOW/no direct code or fix yet prompts, call the Skill tool for agentic-sdlc:plan-authoring immediately; never ask for bug details first or say you will use plan-authoring after details arrive.',
  'Any-language end-to-end/full-envelope prompts that ask for spec, plan, TDD, security/audit, and release-readiness -> agentic-sdlc:agentic-sdlc-pipeline, not mind-spark, even if they mention design or requirements.',
  'Any-language test-only prompts about missing unit/regression/e2e tests, coverage, or test strategy route to agentic-sdlc:test-authoring before any file reads.',
  'Any-language behavior-preserving refactor prompts about preserving behavior while cleaning up, simplifying, or restructuring -> agentic-sdlc:safe-refactor before Glob/Read/file-existence checks; the skill owns missing-target clarification.',
  'Any-language received-review-feedback prompts about PR comments, reviewer comments, bot feedback, or CI review output -> agentic-sdlc:feedback-triage.',
  'Any-language orchestration decision prompts comparing main loop, subagents, workflows, or agent-teams -> agentic-sdlc:dispatch-strategy before answering; do not choose a mechanism directly without the Skill call.',
  'When another plugin exposes a same-purpose skill, prefer the agentic-sdlc:* skill named in this bootstrap for AGENTIC-SDLC prompts.',
  'Do not satisfy AGENTIC-SDLC brainstorming with generic superpowers:brainstorming when agentic-sdlc:mind-spark applies.',
  'Never replace agentic-sdlc:mind-spark with superpowers:brainstorming for any-language option-exploration or uncertain-direction prompts.',
  'Any-language prompt asking to audit whether spec/plan/TDD/security flow was followed before the final response is an explicit request for agentic-sdlc:implementasyon-control now, not a passive session preference. That audit intent requires a Skill call even when no implementation evidence exists; after activation, report missing evidence.',
  'If a clear focused request is underspecified, invoke the focused Skill tool before asking clarifying questions; do not say you will use the skill later.',
  'Clear WHAT/spec-only prompts should use spec-authoring directly; clear HOW/plan-only prompts should use plan-authoring directly.',
  'Any-language clear implementation prompts that ask to add, build, develop, apply, or implement a feature/endpoint -> agentic-sdlc:feature-build unless they explicitly ask only for brainstorming/spec/plan/tests/review or ask for the full pipeline.',
  'For code or diff quality review use agentic-sdlc:code-quality-review, and for a security audit use agentic-sdlc:security-audit, rather than the generic built-in code-review or security-review skills.',
  'For final process audit prompts, call the Skill tool for agentic-sdlc:implementasyon-control; do not answer from memory or summarize without activation.',
  'The selected skill owns clarification after activation.',
  'When a clear focused skill applies, invoke that skill before reading memory, git diff, or project files; context gathering happens inside the selected skill.',
  'In Claude Code, invoking a skill means calling the Skill tool for the agentic-sdlc skill. Text like "I will use X" without the Skill tool is not activation.',
  'Do not read generated commands/*-skill-*.md files as a substitute for invoking the matching Skill tool.',
  'Track session-local routing memory: active intent, selected skill, known spec/plan/test artifacts, scope shifts, and escalation signals.',
  'For ambiguous build/design requests, use mind-spark before spec.',
  'For 2+ independent workstreams, use dispatch-strategy and sub-agents/workflows instead of bloating the main context.',
  'Before any completion claim, require fresh evidence: command output, test result, diff, transcript, or explicit skip reason.',
  'Commit/push/merge/delete only on explicit user request. Secrets must stay masked.',
  'Match the user language unless the user asks otherwise.',
  '</AGENTIC_SDLC_BOOTSTRAP>',
].join('\n');

const context = [
  `Git: branch '${branch}', ahead ${ahead} / behind ${behind}, ${changed} changed/untracked file(s).`,
  bootstrap,
].join('\n');

process.stdout.write(JSON.stringify({
  hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: context },
}));

process.exit(0);
