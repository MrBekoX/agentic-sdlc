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
  'Use the smallest sufficient skill for the current prompt; dev-flow is only for full-envelope end-to-end SDLC work.',
  'Clear WHAT/spec-only prompts should use spec-flow directly; clear HOW/plan-only prompts should use plan-flow directly.',
  'If a clear focused request is underspecified, invoke the focused skill before asking clarifying questions; the skill owns the clarification.',
  'When a clear focused skill applies, invoke that skill before reading memory, git diff, or project files; context gathering happens inside the selected skill.',
  'Track session-local routing memory: active intent, selected skill, known spec/plan/test artifacts, scope shifts, and escalation signals.',
  'For ambiguous build/design requests, use mind-spark before spec.',
  'For 2+ independent workstreams, use orchestration and sub-agents/workflows instead of bloating the main context.',
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
