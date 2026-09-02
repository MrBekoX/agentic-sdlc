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
  'You are in the AGENTIC-SDLC Claude Code skill plugin. Skills live in root skills/ (not .claude/skills/).',
  'Routing authority is the using-agentic-sdlc skill; consult it when no focused skill below clearly fits or scope changes. Route by semantic intent, not exact keywords or prompt language.',
  'Use the smallest sufficient skill. agentic-sdlc-pipeline is only for full-envelope end-to-end SDLC (or high-risk: auth, payment, migration, API contract, permissions, user data, tokens, RLS).',
  'Intent -> skill (invoke via the Skill tool; "I will use X" without the tool call is not activation):',
  '  idea / option-exploration / uncertain  -> agentic-sdlc:mind-spark (never superpowers:brainstorming)',
  '  spec / WHAT / acceptance criteria only  -> agentic-sdlc:spec-authoring',
  '  plan / HOW / task breakdown only        -> agentic-sdlc:plan-authoring (immediately; never ask for bug details first)',
  '  add / build / implement a feature       -> agentic-sdlc:feature-build',
  '  bug / failing / regression / incident   -> agentic-sdlc:root-cause-fix',
  '  behavior-preserving refactor            -> agentic-sdlc:safe-refactor (before Glob/Read/file checks)',
  '  test-only / coverage / test strategy    -> agentic-sdlc:test-authoring (before file reads)',
  '  security audit                          -> agentic-sdlc:security-audit (not generic security-review)',
  '  code/diff quality review                -> agentic-sdlc:code-quality-review (not generic code-review)',
  '  received review / PR / bot feedback     -> agentic-sdlc:feedback-triage',
  '  parallelism / delegation decision       -> agentic-sdlc:dispatch-strategy (before choosing a mechanism)',
  '  final process/SDLC audit                -> agentic-sdlc:implementation-control (audit now; report missing evidence)',
  '  any done/fixed/passing/ready claim      -> agentic-sdlc:completion-claim-gate first',
  'When a focused skill applies, invoke it before reading memory, git diff, or files; the skill owns clarification.',
  'Before any completion claim, require fresh evidence: command output, test result, diff, transcript, or explicit skip reason.',
  'Commit/push/merge/delete only on explicit user request. Secrets stay masked. Match the user language unless asked otherwise.',
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
