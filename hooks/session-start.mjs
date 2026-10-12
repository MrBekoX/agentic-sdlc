// SessionStart - injects git status plus AGENTIC-SDLC bootstrap context.
// On git errors, fall back to unknown state rather than breaking session startup.
import { runGit } from './git-exec.mjs';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

// The installed plugin root, from this module's own location: the model's shell has no plugin-root
// variable on every runtime that wires this hook, and the install path differs per user and per
// version, so the bootstrap names the real path.
const PLUGIN_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));

function git(args) {
  try {
    return runGit(args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
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
  'You are in the AGENTIC-SDLC skill plugin. Skills live in the plugin root skills/ folder (not .claude/skills/).',
  'Plugin root (resolved by this hook; use this absolute path wherever a skill says <runtime-root>, quoted for your shell): ' + PLUGIN_ROOT,
  '<PROCESS_OWNER_POLICY>',
  'Before routing, choose one process owner per phase. The user\'s explicit plugin or skill choice wins, including superpowers:<skill> and AGENTIC-SDLC skills.',
  'Otherwise keep the established owner for the current phase. Loading a bootstrap, router, or focused skill does not switch it; preserve the owner across resume/compact in conversation context.',
  'If no owner has been established, use AGENTIC-SDLC for work entering through this bootstrap or its router. State the owner briefly when both plugins overlap.',
  'Apply the house routing table only to AGENTIC-SDLC-owned phases. A Superpowers-owned phase stays with its selected skill and handoff; do not run a house phase or completion skill alongside it.',
  'Load the selected owner\'s actual instructions before phase content. After resume, compaction, or a supplied summary, reload the selected procedure now even if the summary says it already began: keep its owner and saved progress, not an assumption that its body survived. Invoke Skill in Claude Code or ZCode, or read its catalog-resolved SKILL.md in Codex, then continue from saved progress without repeating completed approvals. Reuse a body already present only in uninterrupted context; otherwise load it. If unavailable, report the gap.',
  'Never stack both plugins\' design, planning, TDD, debugging, review, or completion processes for the same phase merely because both are discoverable. Re-evaluate ownership when the user changes it or a new phase starts.',
  'Runtime security hooks still apply independently of the process owner. Owner selection grants no additional permissions and never disables verification requirements.',
  '</PROCESS_OWNER_POLICY>',
  'Routing authority for AGENTIC-SDLC-owned work is agentic-sdlc:using-agentic-sdlc; consult it when no focused skill below clearly fits or scope changes. Route by semantic intent, not exact keywords or prompt language.',
  'Use the smallest sufficient skill. agentic-sdlc-pipeline is only for full-envelope end-to-end SDLC (or high-risk: auth, payment, migration, API contract, permissions, user data, tokens, RLS).',
  'Intent -> skill (AGENTIC-SDLC-owned phases; invoke via the Skill tool; "I will use X" without the tool call is not activation):',
  '  idea / option-exploration / uncertain  -> agentic-sdlc:mind-spark',
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
  'When an AGENTIC-SDLC focused skill applies under the owner policy, invoke it before reading memory, git diff, or files; the skill owns clarification.',
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
