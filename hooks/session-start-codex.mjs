// SessionStart for Codex - injects git status plus Codex-specific AGENTIC-SDLC context.
// Keep this separate from session-start.mjs, which contains Claude Code Skill-tool guidance.
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
  '<AGENTIC_SDLC_CODEX_BOOTSTRAP>',
  'You are in the AGENTIC-SDLC Codex plugin.',
  'Use root skills/ as the shared skill source; do not assume .codex/skills/.',
  'Codex does not expose Claude Code Skill, Workflow, or Agent transcript events. Use Codex skill activation semantics and available Codex tools instead.',
  'For explicit skill requests, prefer Codex skill invocation via $skill-name or @agentic-sdlc:skill-name when available.',
  'Use the smallest sufficient AGENTIC-SDLC skill for the current prompt; agentic-sdlc-pipeline is only for full-envelope end-to-end SDLC work.',
  'Route by semantic intent, not exact keywords or prompt language.',
  'Clear WHAT/spec-only prompts should use spec-authoring directly; clear HOW/plan-only prompts should use plan-authoring directly.',
  'Any-language brainstorming, option exploration, or uncertain direction -> mind-spark.',
  'Any-language plan-only, HOW, task breakdown, or no direct code/fix yet -> plan-authoring, even when the prompt mentions a bug.',
  'Any-language test-only prompts about missing unit/regression/e2e tests, coverage, or test strategy -> test-authoring.',
  'Any-language behavior-preserving refactor prompts -> safe-refactor.',
  'Any-language received-review-feedback prompts about PR comments, reviewer comments, bot feedback, or CI review output -> feedback-triage.',
  'Any-language orchestration decision prompts comparing main loop, subagents, workflows, or agent-teams -> dispatch-strategy before choosing a mechanism.',
  'Any-language clear implementation prompts that ask to add, build, develop, apply, or implement a feature/endpoint -> feature-build unless they explicitly ask only for brainstorming/spec/plan/tests/review or ask for the full pipeline.',
  'For code or diff quality review use code-quality-review, and for a security audit use security-audit.',
  'For final process audit prompts, use implementasyon-control; report missing evidence instead of implying the flow was followed.',
  'Before any completion claim, use completion-claim-gate and require fresh evidence: command output, test result, diff, transcript, or explicit skip reason.',
  'In Codex, agentic-sdlc-pipeline uses the embedded author -> critic -> revise adapter for internal spec/plan phases; it does not run the Claude Code spec-plan-draft workflow.',
  'Commit/push/merge/delete only on explicit user request. Secrets must stay masked.',
  'Match the user language unless the user asks otherwise.',
  '</AGENTIC_SDLC_CODEX_BOOTSTRAP>',
].join('\n');

const context = [
  `Git: branch '${branch}', ahead ${ahead} / behind ${behind}, ${changed} changed/untracked file(s).`,
  bootstrap,
].join('\n');

process.stdout.write(JSON.stringify({
  hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: context },
}));

process.exit(0);
