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
//   * `git commit --no-verify` / `-n` — git documents this as the way to skip the hook.
//   * History rewrites and server-side pushes of commits made elsewhere.
//   * A repo whose `core.hooksPath` points somewhere else.
// A client-side hook is a fast local backstop, not an enforcement boundary; that belongs on the
// server (pre-receive) or in CI.
//
// Detection reuses the SAME hardened primitives as the command guards, so every fix they received
// applies here unchanged — there is exactly one secret-pattern implementation in this plugin.

import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { HIGH, scanLines } from './secret-patterns.mjs';
import { isCredentialFilename } from './scan-commit-names.mjs';

const MODE = process.argv[2] || '';
const ARG = process.argv[3] || '';

// Bounded so a pathological index can never hang a commit: the guard must fail open loudly rather
// than wedge the user's workflow.
const MAX_BYTES = 5 * 1024 * 1024;

function git(args) {
  return execFileSync('git', args, {
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: MAX_BYTES,
  });
}

function addedLines(diff) {
  return diff
    .split(/\r?\n/)
    .filter((l) => l.startsWith('+') && !l.startsWith('+++'))
    .map((l) => l.slice(1))
    .join('\n');
}

function report(findings) {
  // Values are never printed — only the pattern label and where it was seen, exactly like the
  // PreToolUse guards. A guard that echoes the secret it found has leaked it again.
  const list = findings.map((f) => '  - ' + f.what + (f.where ? ' (' + f.where + ')' : '')).join('\n');
  process.stderr.write(
    '\nagentic-sdlc: commit blocked - possible secret detected (values masked).\n'
    + list + '\n\n'
    + 'If it is a real secret: remove it, rotate it, and move it to env / a secret store.\n'
    + 'If it is a false positive: `git commit --no-verify` bypasses this hook, and the finding is\n'
    + 'worth reporting so the pattern set can be corrected.\n\n',
  );
  process.exit(1);
}

function stagedFindings() {
  const diff = git(['diff', '--cached', '--unified=0']);
  const names = git(['diff', '--cached', '--name-only', '--diff-filter=ACMR']);
  return [
    ...scanLines(addedLines(diff), HIGH).map((f) => ({ what: f.label, where: 'added line ~' + f.line })),
    ...names.split(/\r?\n/).map((s) => s.trim()).filter(Boolean)
      .filter(isCredentialFilename)
      .map((p) => ({ what: 'credential file', where: p })),
  ];
}

function messageFindings(file) {
  // Comment lines are git's own template and are stripped from the recorded message.
  const body = readFileSync(file, 'utf8').split(/\r?\n/).filter((l) => !l.startsWith('#')).join('\n');
  return scanLines(body, HIGH).map((f) => ({ what: f.label, where: 'commit message' }));
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
