// PreToolUse (shell commit) — scans secrets ADDED in the commit; BLOCKS if found.
// Only scans lines ADDED to the diff -> doesn't trigger on already-committed secrets.
// On error, fail-open (does not break the commit).
import { runGit } from './git-exec.mjs';
import { readFileSync } from 'node:fs';
import { HIGH, scanLines, readStdin } from './secret-patterns.mjs';
import { resolve as resolvePath } from 'node:path';
import { commandCwd, resolveGitCommands, targetCwdsFor, resolveTargetCwd, commitMessages, commitMessageFiles, commitSweepsUnstaged } from './git-invocation.mjs';
import { addedDiffLines, displayPath, isCredentialFilename } from './scan-commit-names.mjs';
import { expandAnsiCQuotes } from './shell-quoting.mjs';
import { emitHookResult } from './hook-output.mjs';

// No shell: git is called with an argument array (no command-injection surface, no Windows quoting issues).
// On a read failure we still fail open (never break the commit), but record it so the commit isn't
// silently treated as "scanned & clean" — see the non-blocking warning at the end.
// Same bound as the repository pre-commit scan; the 1 MiB default turned a lockfile-sized change into
// "NOT scanned".
const MAX_DIFF_BYTES = 5 * 1024 * 1024;
let gitReadFailed = false;
function gitDiff(args, cwd) {
  try {
    return runGit(args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: MAX_DIFF_BYTES });
  } catch {
    gitReadFailed = true;
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
const info = resolveGitCommands(cmd, { cwd: baseCwd });

// Resolve what git will ACTUALLY run, expanding git aliases the way git does: `git ci` where
// `alias.ci = commit -a` is a commit, and the old raw-substring gate never saw it.
if (!info.subcommands.has('commit')) process.exit(0);

// EVERY repository the command commits into, not just the first one it names. A command line can
// carry two commits with different `-C` targets (`git -C a commit ... && git -C b commit ...`);
// scanning only the first left the second one's staged content completely unread while the guard
// reported clean. `-C` is scoped per statement, so each commit contributes its own directory.
const repoCwds = targetCwdsFor(info, 'commit', baseCwd);

// `commit -a/-am/--all` also commits tracked changes -> scan unstaged too. Test the RESOLVED
// texts, not the typed command: `alias.ci = "commit -a -m wip"` means `git ci` really does sweep
// unstaged TRACKED changes while the raw string carries no -a at all.
const sweepsUnstaged = info.texts.some(commitSweepsUnstaged);

let diff = '';
let names = '';
for (const cwd of repoCwds) {
  diff += gitDiff(['diff', '--cached', '--unified=0'], cwd) + '\n';
  // -z: NUL-separated, verbatim names. Without it git C-quotes any name with non-ASCII, `"`, `\` or
  // control characters ("klas\303\266r/id_rsa"), and a quoted name never matches the filename rules.
  // T: a type change (a committed symlink replaced by a real key file) adds a new body under the name.
  names += gitDiff(['diff', '--cached', '--name-only', '-z', '--diff-filter=ACMRT'], cwd) + '\0';
  if (sweepsUnstaged) {
    diff += gitDiff(['diff', '--unified=0'], cwd) + '\n';
    names += gitDiff(['diff', '--name-only', '-z', '--diff-filter=ACMRT'], cwd) + '\0';
  }
}

const added = addedDiffLines(diff);

// The commit MESSAGE is part of the commit and git persists it forever (`git log`/`git show`), but
// it never appears in `git diff --cached`. A secret pasted into `-m` therefore reached permanent,
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
      try { return readFileSync(resolvePath(cwd, f), 'utf8'); } catch { return ''; }
    }),
  ]);
}).concat(
  // A git call found INSIDE an inner shell payload (`bash -c "git commit -m ..."`). Its
  // message is scanned; its `-F`/`--file` is deliberately NOT read and its `-C` deliberately
  // does not redirect anything, so reaching into the payload does not widen what this hook
  // opens on disk. See the payload notes in hooks/git-invocation.mjs.
  (info.calls || []).flatMap((call) => (call.payloadTexts || []).flatMap(commitMessages)),
).join('\n');

const contentFindings = scanLines(added, HIGH);
const messageFindings = scanLines(messageText, HIGH).map((f) => ({ ...f, inMessage: true }));
const fileFindings = names
  .split('\0')
  .filter(Boolean)
  .filter((p) => isCredentialFilename(p))
  .map((p) => ({ file: displayPath(p), label: 'secret-file' }));

if (contentFindings.length || fileFindings.length || messageFindings.length) {
  const list = [
    ...contentFindings.map((f) => `  • ${f.label} (added line ~${f.line})`),
    ...messageFindings.map((f) => `  • ${f.label} (commit message)`),
    ...fileFindings.map((f) => `  • ${f.label} (${f.file})`),
  ].join('\n');
  const reason =
    `Commit blocked: possible secret found in added diff lines (values masked).\n${list}\n` +
    `→ If it is a real secret, move it to an env var or secret store (or unstage a flagged credential file) and remove it from the commit. If you believe this is a false positive, stop and ask the user.`;
  emitHookResult({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: reason,
    },
    systemMessage: '🔒 secret scan: commit blocked (possible secret).',
  }, 'PreToolUse');
  process.exit(0);
}

// Fail-open is deliberate (never break a commit), but surface it: if a git read failed, the commit
// was not actually scanned, so don't let its silence read as "scanned & clean". Non-blocking.
if (gitReadFailed) {
  emitHookResult({
    systemMessage: '⚠️ secret scan: could not read `git diff` — this commit was NOT scanned for secrets.',
  }, 'PreToolUse');
}

process.exit(0);
