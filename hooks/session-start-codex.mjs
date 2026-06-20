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
  'You are in the AGENTIC-SDLC Codex plugin. Skills live in root skills/ (not .codex/skills/).',
  'Codex does not expose Claude Code Skill, Workflow, or Agent transcript events. Use Codex skill activation ($skill-name or @agentic-sdlc:skill-name) and available Codex tools.',
  'Routing authority is the using-agentic-sdlc skill; consult it when no focused skill below clearly fits or scope changes. Route by semantic intent, not exact keywords or prompt language.',
  'Use the smallest sufficient skill. agentic-sdlc-pipeline is only for full-envelope end-to-end SDLC and uses the embedded author -> critic -> revise adapter for internal spec/plan phases.',
  'Intent -> skill:',
  '  idea / option-exploration / uncertain  -> mind-spark',
  '  spec / WHAT only                        -> spec-authoring',
  '  plan / HOW only                         -> plan-authoring (never ask for bug details first)',
  '  add / build / implement a feature       -> feature-build',
  '  bug / failing / regression / incident   -> root-cause-fix',
  '  behavior-preserving refactor            -> safe-refactor',
  '  test-only / coverage / test strategy    -> test-authoring',
  '  security audit                          -> security-audit',
  '  code/diff quality review                -> code-quality-review',
  '  received review / PR / bot feedback     -> feedback-triage',
  '  parallelism / delegation decision       -> dispatch-strategy (before choosing a mechanism)',
  '  final process/SDLC audit                -> implementasyon-control (report missing evidence)',
  '  any done/fixed/passing/ready claim      -> completion-claim-gate first',
  'Before any completion claim, require fresh evidence: command output, test result, diff, transcript, or explicit skip reason.',
  'Commit/push/merge/delete only on explicit user request. Secrets stay masked. Match the user language unless asked otherwise.',
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
