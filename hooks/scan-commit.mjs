// PreToolUse (shell commit) — scans secrets ADDED in the commit; BLOCKS if found.
// Only scans lines ADDED to the diff -> doesn't trigger on already-committed secrets.
// On error, fail-open (does not break the commit) - except where a budget, not an error, cut the
// read of a commit's own staged changes: that is denied, because a hook that runs out of time
// renders no decision and the commit would proceed unscanned (R3-CG-4, R3-CG-6).
import { runGit } from './git-exec.mjs';
import { readFileSync, lstatSync, statSync, openSync, readSync, closeSync, existsSync } from 'node:fs';
import { HIGH, scanLines, readStdin } from './secret-patterns.mjs';
import { resolve as resolvePath, dirname, join } from 'node:path';
import { commandCwd, resolveGitCommands, targetCwdsFor, resolveTargetCwd, commitMessages, commitMessageFiles, commitSweepsUnstaged, parseCommitArgs, stagingScope, isStdinPath } from './git-invocation.mjs';
import { addedDiffLines, boundedDiff, displayPath, isCredentialFilename } from './scan-commit-names.mjs';
import { expandAnsiCQuotes } from './shell-quoting.mjs';
import { emitHookResult } from './hook-output.mjs';

// No shell: git is called with an argument array (no command-injection surface, no Windows quoting issues).
// On a read failure we still fail open (never break the commit), but record it so the commit isn't
// silently treated as "scanned & clean" — see the non-blocking warning at the end.
// Same bound as the repository pre-commit scan; the 1 MiB default turned a lockfile-sized change into
// "NOT scanned".
const MAX_DIFF_BYTES = 5 * 1024 * 1024;
let gitReadFailed = false;

// R2-CG-1 / R3-CG-4 / R3-CG-6 / R3-CG-7: one budget for the whole hook. The wired PreToolUse timeout
// is 20 s and a killed hook renders no decision, so everything below spends from one count of git
// processes, one deadline, one cap on the text scanned and one cap on untracked files. Directories
// that do not exist cost nothing, the commit repositories' staged diffs are read first, and their
// findings are reported before anything else is read.
const HOOK_STARTED = Date.now();
const SCAN_DEADLINE = HOOK_STARTED + 14000;
const MAX_GIT_SPAWNS = 48;
const MAX_SCANNED_BYTES = 32 * 1024 * 1024;
const MAX_UNTRACKED_FILES = 5000;
let gitSpawns = 0;
let scannedBytes = 0;
let budgetExceeded = false;
class BudgetExceeded extends Error {}
function runBudgeted(args, cwd) {
  const remaining = SCAN_DEADLINE - Date.now();
  if (gitSpawns >= MAX_GIT_SPAWNS || remaining <= 0) {
    budgetExceeded = true;
    throw new BudgetExceeded('git read budget exceeded');
  }
  gitSpawns += 1;
  return runGit(args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: MAX_DIFF_BYTES,
    timeout: remaining });
}

// A git child killed at the deadline, or otherwise signalled, throws with `.killed`/`.signal`.
// That is the budget running out (the hook would be killed next), not a repository read error, so
// it must not merely warn: on a staged read it denies, like any other budget cut (R4-4).
function isKill(error) {
  return !!error && (error.killed === true || error.signal != null || error.code === 'ETIMEDOUT');
}

// Run a git read; return { text, cut }, where `cut` is true when the hook's budget (not a git
// error) ended the read. A caller that needs to deny on an incomplete read reads `cut`.
function readGit(args, cwd) {
  try {
    return { text: runBudgeted(args, cwd), cut: false };
  } catch (error) {
    if (error instanceof BudgetExceeded) return { text: '', cut: true };
    if (isKill(error)) { budgetExceeded = true; return { text: '', cut: true }; }
    gitReadFailed = true;
    return { text: '', cut: false };
  }
}

function gitDiff(args, cwd) {
  return readGit(args, cwd).text;
}

// R2-CG-2 / R3-CG-9: a path the command names (`-F <file>`, `git apply <patch>`) is read only when
// it is a regular file, and never past MAX_DIFF_BYTES. A FIFO or a device blocked or never ended; a
// procfs file reports size 0 and streams without end. A small regular file is read whole; anything
// else is read through a bounded loop, the first MAX_DIFF_BYTES are scanned and the rest is reported
// as not scanned. stat (not lstat), so a symlink to a regular file is still read, as git reads it.
let partialRead = false;
function namedFileKind(path) {
  try {
    const stat = statSync(path);
    if (!stat.isFile()) return 'none';
    return stat.size > 0 && stat.size <= MAX_DIFF_BYTES ? 'regular' : 'bounded';
  } catch {
    return 'none';
  }
}

function readBounded(path) {
  let fd = null;
  try {
    fd = openSync(path, 'r');
    const buffer = Buffer.alloc(MAX_DIFF_BYTES + 1);
    let filled = 0;
    while (filled < buffer.length) {
      const n = readSync(fd, buffer, filled, buffer.length - filled, null);
      if (n <= 0) break;
      filled += n;
    }
    if (filled > MAX_DIFF_BYTES) { partialRead = true; filled = MAX_DIFF_BYTES; }
    return buffer.subarray(0, filled).toString('utf8');
  } catch {
    return '';
  } finally {
    if (fd !== null) try { closeSync(fd); } catch { /* already closed */ }
  }
}

function readNamed(full) {
  const kind = namedFileKind(full);
  if (kind === 'bounded') return readBounded(full);
  if (kind !== 'regular') return '';
  try { return readFileSync(full, 'utf8'); } catch { return ''; }
}

// SW-6: a patch diff goes through boundedDiff, so one oversized file is skipped and named instead of
// overflowing the single call and dropping the scan of every other file. MAX_PATCH_TOTAL bounds the text
// one diff contributes, which keeps the scan inside the hook's time budget. `lastPatchCut` says that the
// HOOK's budget (process count, deadline, total scanned text), not a single oversized file, cut the read.
const MAX_PATCH_TOTAL = 16 * 1024 * 1024;
const skippedFiles = [];
let lastPatchCut = false;
function patchDiff(base, cwd, pathspec = []) {
  lastPatchCut = false;
  const room = Math.min(MAX_PATCH_TOTAL, MAX_SCANNED_BYTES - scannedBytes);
  if (room <= 0) { budgetExceeded = true; lastPatchCut = true; return ''; }
  const git = (args) => runBudgeted(args, cwd);
  try {
    const { text, skipped } = boundedDiff(git, base, { maxTotal: room, pathspec, deadline: SCAN_DEADLINE });
    for (const file of skipped) skippedFiles.push(file);
    if (skipped.length && (room < MAX_PATCH_TOTAL || Date.now() > SCAN_DEADLINE || budgetExceeded)) {
      budgetExceeded = true;
      lastPatchCut = true;
    }
    scannedBytes += text.length;
    return text;
  } catch (error) {
    if (error instanceof BudgetExceeded) lastPatchCut = true;
    else if (isKill(error)) { budgetExceeded = true; lastPatchCut = true; }   // R4-4
    else gitReadFailed = true;
    return '';
  }
}

// Credential files whose mere presence is a leak, regardless of content (a DER/base64 key body
// or an .npmrc/.netrc has no recognizable header line for the content scan to catch).
// DERIVED copies (`cp id_rsa id_rsa.bak`) leak the same bytes, so they count too. Recognition
// lives in scan-commit-names.mjs as a LINEAR function: the regex that first implemented it used a
// repeated ambiguous group before an end anchor and backtracked catastrophically (459 ms / 1.16 s /
// 20.6 s at 8 / 10 / 12 dotted suffixes) on an agent-influenced filename — that would have timed the
// guard out past its 20 s budget, and the runtime then fails open.

function denyStagedIncomplete() {
  deny('Commit blocked: the staged changes could not be scanned for secrets within the hook\'s time and size budget '
    + '(too many repositories or too much changed text on one command line). Commit in smaller steps, one repository '
    + 'per command, so each commit can be scanned.', '🔒 secret scan: commit blocked (could not scan the staged changes).');
}

function deny(reason, systemMessage) {
  emitHookResult({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: reason,
    },
    systemMessage,
  }, 'PreToolUse');
  process.exit(0);
}

// Scan what has been collected so far and deny at the first finding, so a secret already read is
// reported even when a later read is cut short (R3-CG-7).
function denyOnFindings(added, names, messageText) {
  const contentFindings = scanLines(added, HIGH);
  const messageFindings = scanLines(messageText, HIGH).map((f) => ({ ...f, inMessage: true }));
  const fileFindings = names
    .split('\0')
    .filter(Boolean)
    .filter((p) => isCredentialFilename(p))
    .map((p) => ({ file: displayPath(p), label: 'secret-file' }));
  if (!contentFindings.length && !fileFindings.length && !messageFindings.length) return;
  const list = [
    ...contentFindings.map((f) => `  • ${f.label} (added line ~${f.line})`),
    ...messageFindings.map((f) => `  • ${f.label} (commit message)`),
    ...fileFindings.map((f) => `  • ${f.label} (${f.file})`),
  ].join('\n');
  const reason =
    `Commit blocked: possible secret found in added diff lines (values masked).\n${list}\n` +
    `→ If it is a real secret, move it to an env var or secret store (or unstage a flagged credential file) and remove it from the commit. If you believe this is a false positive, stop and ask the user.`;
  deny(reason, '🔒 secret scan: commit blocked (possible secret).');
}

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { /* ignore */ }
const cmd = String(input?.toolInput?.command || input?.tool_input?.command || '');

// Cheap reject first: this hook is wired on every Bash/PowerShell call (the previous
// `if: Bash(git commit*)` wiring filter was itself bypassable by an alias, so the decision moved
// here). Quote and backslash delimiters are stripped BEFORE the probe: a pre-filter must never be
// narrower than the resolver behind it, or `g'i't commit` exits right here and the quote-aware
// tokenizer that exists precisely for that case never runs.
// The probe must see the command the SHELL will run, so it applies the same normalisation the
// resolver does: ANSI-C decoding first, then quote/backslash stripping. Running it on the raw
// string let `$'\\x67\\x69\\x74' commit` (which bash executes as `git commit`)
// exit right here - the THIRD time a cheap pre-filter turned out to be narrower than the
// resolver behind it. A pre-filter must always be a strict superset of what it guards.
if (!/\bgit\b/i.test(expandAnsiCQuotes(cmd).replace(/['"\\]/g, ''))) process.exit(0);

// Run the git reads against the repository the command actually targets. `git -C <dir>` (and the
// hook payload's own `cwd`) can select a different repo than the hook process's cwd; parsing `-C`
// syntactically without propagating it left alias lookup AND `git diff` pointed at the wrong
// repository, so the guard saw neither the alias nor the staged secret.
const baseCwd = commandCwd(input);
const toolName = String(input?.toolName || input?.tool_name || '');
let info;
try {
  info = resolveGitCommands(cmd, { cwd: baseCwd, allowHeredocStrip: toolName !== 'PowerShell' });
} catch {
  // R3-CG-3: the resolver must never take the hook down. If it throws, nothing on the line was
  // resolved: scan the repository as if `commit -a` runs.
  info = { subcommands: new Set(), texts: [], payloadTexts: [], calls: [], invocations: [], unresolved: true };
}

// R2-CG-10 / R2-CG-11: an alias that could not be resolved - past the lookup cap, or read from a
// config the call does not use (`HOME=`, `--git-dir`, `-c include.path=`) - may be a commit. Scan as
// if `commit -a` runs: the staged and the unstaged changes of the repositories involved.
const unresolved = !!info.unresolved;

// Resolve what git will ACTUALLY run, expanding git aliases the way git does: `git ci` where
// `alias.ci = commit -a` is a commit, and the old raw-substring gate never saw it.
if (!info.subcommands.has('commit') && !unresolved) process.exit(0);

// EVERY repository the command commits into, not just the first one it names. A command line can
// carry two commits with different `-C` targets (`git -C a commit ... && git -C b commit ...`);
// scanning only the first left the second one's staged content completely unread while the guard
// reported clean. `-C` is scoped per statement, so each commit contributes its own directory.
// R3-CG-5: with an unresolved alias, every directory a git call on the line runs in is one of them.
const repoCwds = [...new Set([
  ...targetCwdsFor(info, 'commit', baseCwd),
  ...(unresolved ? (info.invocations || []).map((call) => call.cwd) : []),
])];

// R3-CG-4: a directory that does not exist costs nothing, and directories inside one repository
// are read once (the diff reads are whole-repository: `diff.relative` is pinned off).
function existingDirectory(path) {
  try { return statSync(path).isDirectory(); } catch { return false; }
}
const rootCache = new Map();
function repositoryKey(cwd) {
  if (rootCache.has(cwd)) return rootCache.get(cwd);
  let dir = cwd;
  let key = cwd;
  for (let depth = 0; depth < 64; depth += 1) {
    if (existsSync(join(dir, '.git'))) { key = dir; break; }
    const up = dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  rootCache.set(cwd, key);
  return key;
}
// A `-C` path that carries an expansion (`git -C $(pwd) commit`) names a directory only the shell
// knows: it is not "missing". Read the hook's own repository in its place, and keep the notice that
// the named target itself could not be read.
function hasExpansion(path) {
  return /[$`~]/.test(path);
}
const commitRepos = new Map();
let skippedCommitCwd = false;
const addRepo = (cwd) => {
  const key = repositoryKey(cwd);
  if (!commitRepos.has(key)) commitRepos.set(key, cwd);
};
for (const cwd of repoCwds) {
  if (existingDirectory(cwd)) addRepo(cwd);
  else if (hasExpansion(cwd)) { gitReadFailed = true; if (existingDirectory(baseCwd)) addRepo(baseCwd); }
  else skippedCommitCwd = true;                          // R4-6: a missing commit target was not scanned
}

// `commit -a/-am/--all` also commits tracked changes -> scan unstaged too. Test the RESOLVED
// texts, not the typed command: `alias.ci = "commit -a -m wip"` means `git ci` really does sweep
// unstaged TRACKED changes while the raw string carries no -a at all. An inner shell payload counts
// too: `bash -c 'git commit -am x'` sweeps exactly like the typed form.
const sweepsUnstaged = unresolved || [...info.texts, ...(info.payloadTexts || [])].some(commitSweepsUnstaged);

// Phase 1: the staged changes of every commit repository, before anything else.
let diff = '';
let names = '';
let stagedIncomplete = false;
for (const cwd of commitRepos.values()) {
  diff += patchDiff(['diff', '--cached', '--unified=0'], cwd) + '\n';
  if (lastPatchCut) stagedIncomplete = true;
  // -z: NUL-separated, verbatim names. Without it git C-quotes any name with non-ASCII, `"`, `\` or
  // control characters ("klas\303\266r/id_rsa"), and a quoted name never matches the filename rules.
  // T: a type change (a committed symlink replaced by a real key file) adds a new body under the name.
  const nm = readGit(['diff', '--cached', '--name-only', '-z', '--diff-filter=ACMRT'], cwd);
  names += nm.text + '\0';
  if (nm.cut) stagedIncomplete = true;                   // R4-3: the names read was cut, not just the diff
}
denyOnFindings(addedDiffLines(diff), names, '');
// R3-CG-4 / R3-CG-6: the hook's own budget cut the read of a commit repository's staged changes.
// That is not a git error to fail open on: the commit would land unread. Deny right here, before
// phases 2-4 and their scans, so a cut at the deadline cannot run past the runtime timeout (R5).
if (stagedIncomplete) denyStagedIncomplete();

// Phase 2: what `-a` sweeps in, read once per repository.
const wholeUnstagedRead = new Set();
if (sweepsUnstaged) {
  for (const [key, cwd] of commitRepos) {
    diff += patchDiff(['diff', '--unified=0'], cwd) + '\n';
    names += gitDiff(['diff', '--name-only', '-z', '--diff-filter=ACMRT'], cwd) + '\0';
    wholeUnstagedRead.add(key);
  }
}

// Phase 3: the commit MESSAGE is part of the commit and git persists it forever (`git log`/`git show`),
// but it never appears in `git diff --cached`. A secret pasted into `-m` therefore reached permanent,
// shareable history completely unscanned. Scan it with the same HIGH set as the diff.
// Scan the message of EVERY resolved command text, not just the one the agent typed. The secret
// can live inside the alias definition itself (`alias.ci = "commit -a -m '<token>'"`), in which
// case `git ci` carries no -m at all yet still writes that message into permanent history.
// A `-F <file>` message file is resolved against the repository of the statement that NAMES it.
// Searching every repo in order and taking the first readable hit let a clean `repoA/msg.txt` mask
// the secret in `repoB/msg.txt` for `git -C repoA commit -F msg.txt && git -C repoB commit -F msg.txt`.
const messageText = (info.calls || []).flatMap((call) => {
  const cwd = resolveTargetCwd(baseCwd, call.dirs);
  return call.texts.flatMap((text) => [
    ...commitMessages(text),
    ...commitMessageFiles(text).map((f) => {
      const kind = namedFileKind(resolvePath(cwd, f));
      if (kind === 'bounded') return readBounded(resolvePath(cwd, f));
      if (kind !== 'regular') return '';
      try { return readFileSync(resolvePath(cwd, f), 'utf8'); } catch { return ''; }
    }),
  ]);
}).concat(
  // A git call found INSIDE an inner shell payload (`bash -c "git commit -m ..."`). Its
  // message is scanned; its `-F`/`--file` is deliberately NOT read and its `-C` deliberately
  // does not redirect anything, so reaching into the payload does not widen what this hook
  // opens on disk. See the payload notes in hooks/git-invocation.mjs.
  (info.calls || []).flatMap((call) => (call.payloadTexts || []).flatMap(commitMessages)),
  // CG-8: `git commit -F - <<'EOF'` (and `-F /dev/stdin`, a here-string) takes the message from
  // the statement's stdin. That text is part of the command line, not a disk read, so a payload
  // call contributes it too.
  (info.invocations || [])
    .filter((call) => call.subcommand === 'commit' && typeof call.stdin === 'string'
      && parseCommitArgs(call.args).files.some(isStdinPath))
    .map((call) => call.stdin),
  // The arguments the resolved commit really receives. A wrapper can carry them inside one word
  // the text readers above see whole (`env -S 'git commit -m <msg>'`); the resolver has split it.
  // Same file rule as above: a payload call's `-F` is not opened.
  (info.invocations || []).filter((call) => call.subcommand === 'commit').flatMap((call) => {
    const parsed = parseCommitArgs(call.args);
    const files = call.viaPayload ? [] : parsed.files.filter((f) => !isStdinPath(f));
    return [...parsed.messages, ...files.map((f) => readNamed(resolvePath(call.cwd, f)))];
  }),
).join('\n');
denyOnFindings(addedDiffLines(diff), names, messageText);

// Phase 4 - CG-1: the index this commit records is the one the SAME command line builds first.
// `git add f && git commit` was scanned against the index as it stood before the add ran, so a
// secret staged by that add was committed unscanned. Every change the line can stage is read:
//   * a commit's own pathspecs, `-i`/`-o`, `--pathspec-from-file` and `-a` (payloads included);
//   * `add`/`stage` for their paths (with untracked files, and ignored ones under `-f`);
//   * the patch text of `apply` (top-level files only, or the statement's here-document).
// Order on the line is not modelled: shell functions, loops and `||` make it unreliable, and reading
// more can only add findings.
const scopes = [];
for (const call of info.invocations || []) {
  if (call.subcommand === 'commit') {
    const parsed = parseCommitArgs(call.args);
    if (parsed.all) scopes.push({ cwd: call.cwd, paths: null, untracked: false });
    if (parsed.pathspecFromFile) scopes.push({ cwd: call.cwd, paths: null, untracked: false });
    else if (parsed.pathspecs.length) {
      const paths = parsed.pathspecs.some((p) => /[$`]/.test(p)) ? null : parsed.pathspecs;
      scopes.push({ cwd: call.cwd, paths, untracked: false });
    }
    continue;
  }
  const scope = stagingScope(call);
  if (!scope) continue;
  scopes.push({ cwd: call.cwd, ...scope });
  for (const patch of scope.patches) {
    // Same rule as `-F`: a file named inside an inner shell payload is never opened.
    if (call.viaPayload || isStdinPath(patch)) continue;
    const text = readNamed(resolvePath(call.cwd, patch));
    scannedBytes += text.length;
    diff += text + '\n';
  }
  if (scope.stdinPatch && typeof call.stdin === 'string') diff += call.stdin + '\n';
}

// R2-CG-1 / R3-CG-6: one read per (directory, untracked, ignored), with every path of that group in
// one pathspec, instead of three git processes per `git add <path>`. A whole-tree group is keyed by its
// repository, and a repository whose whole diff was already read is not read again. A group that names
// too many paths, or a line with too many groups, is read whole instead - once per commit repository.
const MAX_GROUP_PATHS = 1000;
const MAX_SCOPE_GROUPS = 8;
let groups = new Map();
for (let scope of scopes) {
  if (scope.paths && !scope.paths.length && !scope.untracked) continue;   // `apply`: patch text only
  if (!existingDirectory(scope.cwd)) {
    if (!hasExpansion(scope.cwd) || !existingDirectory(baseCwd)) continue;
    scope = { ...scope, cwd: baseCwd, paths: null };      // unknown target: read the whole repository
  }
  const whole = !scope.paths || scope.paths.length > MAX_GROUP_PATHS;
  const where = whole ? repositoryKey(scope.cwd) : scope.cwd;
  const key = [where, !!scope.untracked, !!scope.ignored].join('\u0001');
  const group = groups.get(key) || { cwd: scope.cwd, key: repositoryKey(scope.cwd), untracked: !!scope.untracked,
    ignored: !!scope.ignored, paths: new Set() };
  if (whole) group.paths = null;
  else if (group.paths) for (const path of scope.paths) group.paths.add(path);
  if (group.paths && group.paths.size > MAX_GROUP_PATHS) group.paths = null;
  groups.set(key, group);
}
if (groups.size > MAX_SCOPE_GROUPS) {
  const untracked = [...groups.values()].some((g) => g.untracked);
  const ignored = [...groups.values()].some((g) => g.ignored);
  groups = new Map([...commitRepos].map(([key, cwd]) => [key, { cwd, key, untracked, ignored, paths: null }]));
}

// Untracked files that an `add` stages have no diff yet: read their bytes, bounded like a diff.
let untrackedText = '';
let untrackedFiles = 0;
const untrackedListed = new Set();
for (const group of groups.values()) {
  const paths = group.paths ? [...group.paths] : null;
  const spec = paths ? ['--', ...paths] : [];
  if (!wholeUnstagedRead.has(group.key)) {
    diff += patchDiff(['diff', '--unified=0'], group.cwd, paths || []) + '\n';
    names += gitDiff(['diff', '--name-only', '-z', '--diff-filter=ACMRT', ...spec], group.cwd) + '\0';
    if (!paths) wholeUnstagedRead.add(group.key);
  }
  if (!group.untracked) continue;
  const listKey = [paths ? group.cwd : group.key, paths ? paths.join('\0') : '*', group.ignored].join('\u0001');
  if (untrackedListed.has(listKey)) continue;
  untrackedListed.add(listKey);
  const listed = gitDiff(['ls-files', '-z', '--others', ...(group.ignored ? [] : ['--exclude-standard']), ...spec],
    group.cwd);
  for (const rel of listed.split('\0').filter(Boolean)) {
    if (untrackedFiles >= MAX_UNTRACKED_FILES || Date.now() > SCAN_DEADLINE
        || scannedBytes >= MAX_SCANNED_BYTES) {
      budgetExceeded = true;
      break;
    }
    untrackedFiles += 1;
    names += rel + '\0';
    try {
      const full = resolvePath(group.cwd, rel);
      const stat = lstatSync(full);
      if (!stat.isFile()) continue;                       // a symlink stores its target path only
      if (stat.size > MAX_DIFF_BYTES || scannedBytes + stat.size > MAX_SCANNED_BYTES) { partialRead = true; continue; }
      const bytes = readFileSync(full);
      scannedBytes += bytes.length;
      if (bytes.subarray(0, 8000).includes(0)) continue;  // binary, as git itself would treat it
      untrackedText += bytes.toString('utf8') + '\n';
    } catch {
      partialRead = true;
    }
  }
}

denyOnFindings(addedDiffLines(diff) + (untrackedText ? '\n' + untrackedText : ''), names, messageText);


// Fail-open is deliberate (never break a commit), but surface it: if a git read failed, the commit
// was not actually scanned, so don't let its silence read as "scanned & clean". Non-blocking.
if (gitReadFailed) {
  emitHookResult({
    systemMessage: '⚠️ secret scan: could not read `git diff` — this commit was NOT scanned for secrets.',
  }, 'PreToolUse');
} else if (budgetExceeded) {
  emitHookResult({
    systemMessage: '⚠️ secret scan: this command stages more than the hook can read within its time budget — some staged changes were NOT scanned for secrets.',
  }, 'PreToolUse');
} else if (skippedCommitCwd) {
  emitHookResult({
    systemMessage: '⚠️ secret scan: a commit target directory does not exist at check time — it was NOT scanned for secrets.',
  }, 'PreToolUse');
} else if (skippedFiles.length) {
  const shown = skippedFiles.slice(0, 10).map(displayPath).join(', ') + (skippedFiles.length > 10 ? ', ...' : '');
  emitHookResult({
    systemMessage: `⚠️ secret scan: ${skippedFiles.length} file(s) with a diff too large to read were NOT scanned for secrets: ${shown}.`,
  }, 'PreToolUse');
} else if (partialRead) {
  emitHookResult({
    systemMessage: '⚠️ secret scan: some files this command stages were too large or unreadable — they were NOT scanned for secrets.',
  }, 'PreToolUse');
} else if (unresolved) {
  emitHookResult({
    systemMessage: '⚠️ secret scan: some git subcommands on this line could not be resolved (alias lookup budget or a different config) — staged and unstaged changes were scanned as if they were committed.',
  }, 'PreToolUse');
}

process.exit(0);
