// PreToolUse (Bash, if: git commit/push) — guards against direct work on main/master.
// Generic, tech-agnostic. Non-blocking by default; set AGENTIC_BRANCH_GUARD_BLOCK=true
// to deny protected-branch commit/push without editing this file.
// On error, fail-open (does not break the command).
import { runGit } from './git-exec.mjs';
import { resolve as resolvePath } from 'node:path';
import { readStdin } from './secret-patterns.mjs';
import { commandCwd, resolveGitCommands, targetCwdsFor } from './git-invocation.mjs';
import { expandAnsiCQuotes } from './shell-quoting.mjs';

const BLOCK = /^(true|1|yes)$/i.test(String(process.env.AGENTIC_BRANCH_GUARD_BLOCK || ''));
const PROTECTED = /^(main|master)$/i;

function git(args, cwd) {
  try {
    return runGit(args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } catch {
    return '';
  }
}

function currentBranch(cwd) {
  return git(['branch', '--show-current'], cwd) || git(['rev-parse', '--abbrev-ref', 'HEAD'], cwd);
}

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { /* ignore */ }
const cmd = String(input?.toolInput?.command || input?.tool_input?.command || '');

// Cheap reject first: this hook is wired on every Bash/PowerShell call, because the previous
// `if: Bash(git commit*)` wiring filter was itself escapable by a git alias. Quote and backslash
// delimiters are stripped so this probe is never NARROWER than the resolver behind it — otherwise
// `g'i't commit` exits right here and the quote-aware tokenizer never runs.
// The probe must see the command the SHELL will run, so it applies the same normalisation the
// resolver does: ANSI-C decoding first, then quote/backslash stripping. Running it on the raw
// string let `$'\\x67\\x69\\x74' commit` (which bash executes as `git commit`)
// exit right here - the THIRD time a cheap pre-filter turned out to be narrower than the
// resolver behind it. A pre-filter must always be a strict superset of what it guards.
if (!/\bgit\b/i.test(expandAnsiCQuotes(cmd).replace(/['"\\]/g, ''))) process.exit(0);

// Only react to git commit / push — resolved through git's own alias table, so `git ci` (where
// `alias.ci = commit -a`) is seen. The old raw-substring test skipped the whole guard for it.
// `-C <dir>` and the payload cwd select the repository whose branch actually matters; parsing `-C`
// without propagating it to the git reads meant reporting the wrong repo's branch.
const baseCwd = commandCwd(input);
const info = resolveGitCommands(cmd, { cwd: baseCwd });
// EVERY repository the command commits or pushes into. scan-commit.mjs was moved to the plural
// resolver when a second `-C` commit was found to go unscanned; this guard was left on the
// singular one, so `git -C feature-repo commit && git -C main-checkout commit` reported only
// the first repo's branch and let a direct commit to main through.
const repoCwds = targetCwdsFor(info, ['commit', 'push'], baseCwd);
const isPush = info.subcommands.has('push');
if (!info.subcommands.has('commit') && !isPush) process.exit(0);

// Check EVERY repository the command touches, not just the first. One protected branch anywhere in
// a compound command is enough to warn/deny.
const protectedBranch = repoCwds.map(currentBranch).find((b) => b && PROTECTED.test(b));
const branch = protectedBranch;
const forcePush = isPush && /(--force\b|--force-with-lease\b|\s-f\b)/.test(cmd);

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
