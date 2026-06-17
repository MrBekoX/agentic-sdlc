// PreToolUse (Bash, if: git commit/push) — guards against direct work on main/master.
// Generic, tech-agnostic. Non-blocking by default; set AGENTIC_BRANCH_GUARD_BLOCK=true
// to deny protected-branch commit/push without editing this file.
// On error, fail-open (does not break the command).
import { execFileSync } from 'node:child_process';
import { readStdin } from './secret-patterns.mjs';

const BLOCK = /^(true|1|yes)$/i.test(String(process.env.AGENTIC_BRANCH_GUARD_BLOCK || ''));
const PROTECTED = /^(main|master)$/i;

function git(args) {
  try {
    return execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } catch {
    return '';
  }
}

function currentBranch() {
  return git(['branch', '--show-current']) || git(['rev-parse', '--abbrev-ref', 'HEAD']);
}

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { /* ignore */ }
const cmd = String(input?.tool_input?.command || '');

// Only react to git commit / push.
if (!/\bgit\b[\s\S]*\b(commit|push)\b/.test(cmd)) process.exit(0);

const branch = currentBranch();
const forcePush = /\bpush\b[\s\S]*(--force\b|--force-with-lease\b|-f\b)/.test(cmd);

if (branch && PROTECTED.test(branch)) {
  const msg =
    `Protected branch '${branch}': commit/push directly to ${branch} is risky (contract 08 — git-safety). ` +
    `Prefer a feature branch and a reviewed PR.` + (forcePush ? ' FORCE-PUSH detected — extra caution.' : '');
  if (BLOCK) {
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: msg },
      systemMessage: `🚧 branch-guard: blocked on '${branch}'.`,
    }));
  } else {
    process.stdout.write(JSON.stringify({ systemMessage: `🚧 branch-guard: ${msg}` }));
  }
}

process.exit(0);
