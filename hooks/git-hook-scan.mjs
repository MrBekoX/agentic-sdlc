// Effect-layer secret scanner, invoked from a repository's own git hooks.
//
//   node git-hook-scan.mjs pre-commit
//   node git-hook-scan.mjs commit-msg <message-file>
//
// WHY THIS EXISTS
// The PreToolUse command guards inspect the COMMAND STRING, and that layer cannot be made
// complete: shell aliases and functions, `$PATH` shadowing, `eval`, variable indirection and
// base64-pipe-to-shell are all resolved by the shell AFTER the hook has decided, and the write
// surface (`tee`, `dd`, any interpreter) is unbounded. Those are documented residuals there.
//
// Git runs THIS on the operation. By the time `pre-commit` fires, git has already resolved its
// alias table, the shell has already done quote removal and $PATH lookup, and the index already
// holds the exact bytes that are about to become a commit. There is no command string to outwit:
// `git ci`, `g'i't commit`, a shell function named `git`, and `eval "$(printf 'git com'; ...)"`
// all arrive here identically.
//
// WHAT IT STILL DOES NOT COVER (say it plainly, never imply otherwise):
//   * `git commit --no-verify` / `-n` skips pre-commit and commit-msg. It does not skip
//     prepare-commit-msg, which re-scans the staged content and the message.
//   * `git -c core.hooksPath=/dev/null commit` skips every repository hook.
//   * History rewrites and server-side pushes of commits made elsewhere.
//   * A repo whose `core.hooksPath` points somewhere else.
// A client-side hook is a fast local backstop, not an enforcement boundary; that belongs on the
// server (pre-receive) or in CI.
//
// Detection reuses the SAME hardened primitives as the command guards, so every fix they received
// applies here unchanged — there is exactly one secret-pattern implementation in this plugin.

import { runGit } from './git-exec.mjs';
import { readFileSync } from 'node:fs';
import { HIGH, scanLines } from './secret-patterns.mjs';
import { addedDiffLines, boundedDiff, displayPath, isCredentialFilename } from './scan-commit-names.mjs';

const MODE = process.argv[2] || '';
const ARG = process.argv[3] || '';

// Bounded so a pathological index can never hang a commit: the guard must fail open loudly rather
// than wedge the user's workflow. MAX_BYTES caps one git call (one file's diff at worst); MAX_SCAN caps
// the diff text scanned over all files.
const MAX_BYTES = 5 * 1024 * 1024;
const MAX_SCAN = 32 * 1024 * 1024;

function git(args) {
  return runGit(args, {
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: MAX_BYTES,
  });
}

function report(findings) {
  // Values are never printed — only the pattern label and where it was seen, exactly like the
  // PreToolUse guards. A guard that echoes the secret it found has leaked it again.
  const list = findings.map((f) => '  - ' + f.what + (f.where ? ' (' + f.where + ')' : '')).join('\n');
  // The skip advice names what really gets past THIS hook (SW-5). `--no-verify` does not skip
  // prepare-commit-msg, and that hook re-scans the staged content and the message, so recommending it
  // sent the user into the same block again.
  const noVerify = MODE === 'prepare-commit-msg'
    ? 'This is the prepare-commit-msg backstop: `--no-verify` does not skip it.\n'
    : '`--no-verify` skips this hook, but not the prepare-commit-msg backstop, which scans the same\n'
      + 'staged content and message.\n';
  process.stderr.write(
    '\nagentic-sdlc: commit blocked - possible secret detected (values masked).\n'
    + list + '\n\n'
    + 'If it is a real secret: remove it, rotate it, and move it to env / a secret store.\n'
    + 'If it is a false positive: add `agentic-sdlc:allow-secret` to the flagged line.\n'
    + noVerify
    + 'An agent must not switch the repository hooks off to get past this check: stop and ask the user.\n'
    + 'A false positive is worth reporting so the pattern set can be corrected.\n\n',
  );
  process.exit(1);
}

// A file whose diff is over the per-call cap is skipped on its own and named, instead of one large
// file switching off the scan of every other staged file (SW-6).
function warnSkipped(skipped) {
  if (!skipped.length) return;
  const shown = skipped.slice(0, 10).map(displayPath).join(', ') + (skipped.length > 10 ? ', ...' : '');
  process.stderr.write('agentic-sdlc: WARNING - ' + skipped.length + ' staged file(s) NOT scanned, their diff '
    + 'is over the scan limit: ' + shown + '\n');
}

function stagedFindings() {
  const { text: diff, skipped } = boundedDiff(git, ['diff', '--cached', '--unified=0'], { maxTotal: MAX_SCAN });
  warnSkipped(skipped);
  // -z: NUL-separated, verbatim names. Without it git C-quotes any name with non-ASCII, `"`, `\` or
  // control characters, and a quoted credential file name never matches the filename rules.
  const names = git(['diff', '--cached', '--name-only', '-z', '--diff-filter=ACMRTU']);
  return [
    ...scanLines(addedDiffLines(diff), HIGH).map((f) => ({ what: f.label, where: 'added line ~' + f.line })),
    ...names.split('\0').filter(Boolean)
      .filter(isCredentialFilename)
      .map((p) => ({ what: 'credential file', where: displayPath(p) })),
  ];
}

// git's scissors line, after the comment string and a space (wt-status.c `cut_line`). `git commit -v`
// writes the staged diff below it, and git discards everything from it on when -v is given.
const CUT_LINE = '------------------------ >8 ------------------------\n';
// The characters `core.commentChar=auto` chooses from (builtin/commit.c).
const AUTO_COMMENT_CHARS = '#;@!$%^&|:';

function commentStrings() {
  const read = (key) => {
    try { return git(['config', '--get', key]).replace(/\r?\n$/, ''); } catch { return ''; }
  };
  const value = read('core.commentString') || read('core.commentChar');
  if (!value) return ['#'];
  return value === 'auto' ? [...AUTO_COMMENT_CHARS] : [value];
}

// Where git's scissors line starts, or -1: the message's first line or a line right after a newline,
// as wt_status_locate_end finds it.
function scissorsAt(body) {
  if (!body.includes(' ' + CUT_LINE)) return -1;        // no git config read for an ordinary message
  let first = -1;
  for (const comment of commentStrings()) {
    const line = comment + ' ' + CUT_LINE;
    const after = body.indexOf('\n' + line);
    const at = body.startsWith(line) ? 0 : (after === -1 ? -1 : after + 1);
    if (at !== -1 && (first === -1 || at < first)) first = at;
  }
  return first;
}

// The old content `git commit -v` can show below the scissors line: the removed and context lines, and
// the hunk headers (whose function context git copies from the old file), of the staged diff against
// HEAD, against HEAD^ (an amend), and of the unstaged diff (-vv). A diff over the call cap adds nothing,
// so its lines stay scanned.
function verboseOldContent() {
  const old = new Set();
  const headers = new Set();
  for (const args of [['diff', '--cached'], ['diff', '--cached', 'HEAD^'], ['diff']]) {
    let out;
    try { out = git(args); } catch { continue; }
    for (const line of out.split('\n')) {
      if (line[0] === ' ' || line[0] === '-') old.add(line.slice(1));
      else if (line.startsWith('@@')) headers.add(line);
    }
  }
  return { old, headers };
}

// The text below the scissors line, less the old content of git's own -v diff (SW-5). A removed (`-`)
// or context (` `) line of that diff is a line of the file as it was, so scanning it as message text
// blocked the very commit that removed a secret. A line is dropped only when the diff git would show
// really holds it (R2-SW-1): without -v git records everything below a scissors line typed into the
// message, `@@`, ` ` and `-` lines included, so those are message text and are scanned.
function belowScissors(tail) {
  const { old, headers } = verboseOldContent();
  return tail.split('\n').filter((line) => {
    if (line[0] === ' ' || line[0] === '-') return !old.has(line.slice(1));
    if (line.startsWith('@@')) return !headers.has(line);
    return true;
  }).join('\n');
}

function messageFindings(file) {
  // Git can retain commentary with whitespace/verbatim cleanup, nonedited -m/-F defaults,
  // or a custom comment marker. Scan the supplied bytes conservatively instead of guessing
  // what cleanup will discard. Ordinary templates and same-line suppressions keep their rules.
  // The one exception is the old content of the -v diff below git's scissors line (belowScissors).
  const body = readFileSync(file, 'utf8');
  const cut = scissorsAt(body);
  const text = cut === -1 ? body : body.slice(0, cut) + belowScissors(body.slice(cut));
  return scanLines(text, HIGH).map((f) => ({ what: f.label, where: 'commit message' }));
}

try {
  if (MODE === 'pre-commit' || MODE === 'pre-merge-commit') {
    // `git merge` runs `pre-merge-commit`, NOT `pre-commit`, so without this mode a merge commit
    // carrying a secret went in completely unscanned. Git's own sample pre-merge-commit simply
    // execs pre-commit for the same reason.
    const findings = stagedFindings();
    if (findings.length) report(findings);
  } else if (MODE === 'prepare-commit-msg') {
    // The one commit-path hook `--no-verify` does NOT suppress (githooks: "it is not suppressed by
    // the --no-verify option"), and it can read BOTH channels: the staged index and the message
    // file. Without it, a single flag disarmed this whole layer. Git's own docs say it "should not
    // be used as a replacement for the pre-commit hook", so it is an additional backstop, not the
    // primary one — and its firing on cherry-pick/revert/rebase is undocumented behaviour that git
    // has said may change.
    const findings = [...stagedFindings(), ...(ARG ? messageFindings(ARG) : [])];
    if (findings.length) report(findings);
  } else if (MODE === 'commit-msg') {
    // `pre-commit` runs before a message exists, so the message needs its own hook.
    const findings = messageFindings(ARG);
    if (findings.length) report(findings);
  }
} catch (err) {
  // FAIL OPEN, but never silently: an unscanned commit must not read as a scanned-and-clean one.
  // This mirrors scan-commit.mjs's gitReadFailed notice, which exists for the same reason.
  process.stderr.write(
    'agentic-sdlc: WARNING - the secret scan did not run, so this commit was NOT scanned ('
    + String((err && err.message) || err).slice(0, 200) + ')\n',
  );
}

process.exit(0);
