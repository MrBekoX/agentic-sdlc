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
  'Deterministic guards on Codex: the PreToolUse command guards (scan-commit, destructive-command, branch-guard) and a pre-write secret guard (scan-write-codex, matcher Bash+apply_patch, a bounded backstop over recognized write forms) block natively via hooks-codex.json. Two Stop backstops are also wired natively: the completion-claim guard (completion-claim-guard-codex, via the rollout sentinel marker the completion-claim-gate emits) and the evidence-only flow-step guard (flow-step-guard-codex, session-scoped - it re-derives spec/plan/test evidence from THIS rollout\'s in-session writes and recorded commands, warns by default and blocks under AGENTIC_FLOW_GATE_BLOCK; committed prior-session artifacts never activate it). The flow-order path-gate is now wired too: flow-order-guard-codex is an env-gated opt-in PreToolUse pre-edit ordering gate (matcher Bash+apply_patch, default silent) that under its own AGENTIC_FLOW_ORDER_BLOCK denies a source edit attempted before a validated spec and matching plan were authored this session - so the AP2 envelope is complete (completion-claim + flow-step + flow-order all bound). The two flow switches are independent: AGENTIC_FLOW_GATE_BLOCK escalates only the flow-step Stop backstop (warn to block) and AGENTIC_FLOW_ORDER_BLOCK activates only the flow-order pre-gate.',
  'If a user names an AGENTIC-SDLC skill and skill descriptions are missing, read ${PLUGIN_ROOT}/skills/<skill>/SKILL.md before acting; replace <skill> with the kebab-case skill name.',
  'Routing authority is the using-agentic-sdlc skill; consult it when no focused skill below clearly fits or scope changes. Route by semantic intent, not exact keywords or prompt language.',
  'Use the smallest sufficient skill. agentic-sdlc-pipeline is only for full-envelope end-to-end SDLC and uses the embedded author -> critic -> revise adapter for internal spec/plan phases.',
  'For agentic-sdlc-pipeline on Codex: emit Runtime: Codex and Codex Adapter Gate: <gate>; run ${PLUGIN_ROOT}/scripts/detect_context.py before file exploration; save canonical docs/agentic-sdlc/specs/<work_id>.md and docs/agentic-sdlc/plans/<work_id>.md; run ${PLUGIN_ROOT}/scripts/validate_artifacts.py for both artifacts; do not use spec.md or plan.md.',
  'Artifact layouts (dual): legacy flat docs/agentic-sdlc/{specs,plans}/<id>.md (back-compat) and per-package canonical docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md, where <slug> is lowercase kebab-case ^[a-z0-9][a-z0-9-]{0,63}$ and never a reserved name (specs, plans, evidence, notes, spec, plan).',
  'Per-package evidence persists to docs/agentic-sdlc/<slug>/evidence/<work_id>.md: per-package only (flat packages get no evidence), overwritten in place per run, git-ignored, and with no validator (it never gates resolution). That evidence write is performed by the main pipeline finalize step, not the read-only implementation-auditor sub-agent.',
  'Per-package plan change-detection runs as a filesystem scan, not a git status query: the whole docs/ tree is git-ignored, so git status never reports new per-package plans and the resolver scans the filesystem instead.',
  'do not run recursive cleanup deletes for generated caches such as __pycache__; report generated cache paths instead.',
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
  '  final process/SDLC audit                -> implementation-control (report missing evidence)',
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
