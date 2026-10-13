// PreToolUse (Bash, if: git commit/push) — guards against direct work on main/master.
// Generic, tech-agnostic. Non-blocking by default; set AGENTIC_BRANCH_GUARD_BLOCK=true
// to deny protected-branch commit/push without editing this file.
// On error, fail-open (does not break the command).
import { runGit } from './git-exec.mjs';
import { readStdin } from './secret-patterns.mjs';
import { commandCwd, resolveGitCommands } from './git-invocation.mjs';
import { PUSH_CONFIG_PATTERN, resolvePushTargets } from './push-targets.mjs';
import { expandAnsiCQuotes } from './shell-quoting.mjs';
import { emitHookResult } from './hook-output.mjs';

const BLOCK = /^(true|1|yes)$/i.test(String(process.env.AGENTIC_BRANCH_GUARD_BLOCK || ''));
const PROTECTED = /^(main|master)$/i;
const stateCache = new Map();
const branchCache = new Map();
let stateDeadline;

function queryGit(args, cwd, allowNoMatch = false) {
  try {
    const timeout = Math.min(1000, stateDeadline - Date.now());
    if (timeout <= 0) return { text: '', known: false };
    return { text: runGit(args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'],
      timeout, maxBuffer: 1024 * 1024 }).trim(), known: true };
  } catch (error) {
    return { text: '', known: allowNoMatch && error.status === 1 && !String(error.stdout || '') };
  }
}

function currentBranch(cwd) {
  if (!branchCache.has(cwd)) {
    branchCache.set(cwd, queryGit(['branch', '--show-current'], cwd).text
      || queryGit(['rev-parse', '--abbrev-ref', 'HEAD'], cwd).text);
  }
  return branchCache.get(cwd);
}

function localPushState(invocation) {
  // Shell payload -C/config paths must never widen the existing reader boundary.
  if (!invocation.readContextKnown) return {};
  const cwd = invocation.cwd;
  if (stateCache.has(cwd)) return stateCache.get(cwd);
  const config = [];
  const configRead = queryGit(['config', '--null', '--get-regexp', PUSH_CONFIG_PATTERN], cwd, true);
  for (const entry of configRead.text.split('\0').filter(Boolean)) {
    const newline = entry.indexOf('\n');
    config.push(newline >= 0 ? [entry.slice(0, newline), entry.slice(newline + 1)] : [entry, 'true']);
  }
  const refsRead = queryGit(['for-each-ref', '--format=%(refname)'], cwd);
  const remotesRead = queryGit(['remote'], cwd);
  const branch = currentBranch(cwd);
  const state = { config, refs: refsRead.text.split('\n').filter(Boolean), refsKnown: refsRead.known,
    remotes: remotesRead.text.split('\n').filter(Boolean), branch,
    available: configRead.known && refsRead.known && remotesRead.known && !!branch };
  stateCache.set(cwd, state);
  return state;
}

const raw = await readStdin();
stateDeadline = Date.now() + 4000;
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
const invocations = (info.invocations || []).filter((call) => call.subcommand === 'commit' || call.subcommand === 'push');
const repoCwds = [...new Set(invocations.map((call) => call.cwd))];
const isPush = info.subcommands.has('push');
if (!info.subcommands.has('commit') && !isPush) process.exit(0);

// Check EVERY repository the command touches, not just the first. One protected branch anywhere in
// a compound command is enough to warn/deny.
const protectedBranch = repoCwds.map(currentBranch).find((b) => b && PROTECTED.test(b));
const pushes = invocations.filter((call) => call.subcommand === 'push')
  .map((call) => resolvePushTargets(call, localPushState(call)));
const protectedPush = pushes.find((push) => push.targets.length);
const branch = protectedBranch || protectedPush?.targets[0];
const forcePush = isPush && pushes.some((push) => push.force);

if (branch && PROTECTED.test(branch)) {
  const msg =
    `Protected branch '${branch}': commit/push directly to ${branch} is risky (contract 08 — git-safety). ` +
    `Prefer a feature branch and a reviewed PR.`
    + (protectedPush?.mirror ? ' Mirror push may delete protected remote refs even when they are absent locally.' : '')
    + (protectedPush?.prune ? ' Prune push may delete protected remote refs even when they are absent locally.' : '')
    + (forcePush ? ' FORCE-PUSH detected — extra caution.' : '');
  if (BLOCK) {
    emitHookResult({
      hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: msg },
      systemMessage: `🚧 branch-guard: blocked on '${branch}'.`,
    }, 'PreToolUse');
  } else {
    emitHookResult({ systemMessage: `🚧 branch-guard: ${msg}` }, 'PreToolUse');
  }
}

process.exit(0);
