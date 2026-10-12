// Stop hook — effect-layer DETECTION: scans what actually landed in the working tree.
//
// WHY THIS EXISTS
// The PreToolUse write guard reads the command string and can only recognize a bounded set of
// write forms; `tee`, `dd`, `base64`, `python -c`, any interpreter, and several redirect families
// are documented as out of reach there. This hook does not look at commands at all. It reads the
// bytes on disk, so HOW they were written is irrelevant — an unrecognized redirect, a pipe into
// `tee`, and a Python one-liner all produce the same finding.
//
// POSTURE: detection, not prevention. By the time this runs the bytes are already on disk, so
// blocking the turn does not unwrite them — what it buys is that the leak is SEEN. Prevention for
// the commit path lives in the repo's own `pre-commit`/`commit-msg` hooks
// (scripts/install_git_hooks.py); this is the net under everything else.
//
// Default is a non-blocking advisory. `AGENTIC_WORKTREE_SCAN_BLOCK=true` escalates it to a Stop
// block, matching the opt-in pattern of the other gates in this plugin.

import { runGit } from './git-exec.mjs';
import { readFileSync, statSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve as resolvePath } from 'node:path';
import { createHash } from 'node:crypto';
import { HIGH, scanLines, readStdin } from './secret-patterns.mjs';
import { addedDiffLines, displayPath, isCredentialFilename } from './scan-commit-names.mjs';

const BLOCK = /^(true|1|yes)$/i.test(String(process.env.AGENTIC_WORKTREE_SCAN_BLOCK || ''));

// Vendored / build trees. Scanning ignored paths is what makes `.env` visible, but it must not
// mean walking a dependency tree on every turn: those hits are the vendor's test fixtures, and the
// walk itself would blow the Stop budget (a timed-out hook renders NO decision at all).
// Also excluded: agent/tool STATE directories. A token in `.claude/` or `.opencode/` was written
// by that tool, is gitignored by it, and the user cannot act on the report - it is pure noise,
// unlike `.env`, which is theirs and is exactly what this scan exists to surface.
// Bounds keep this linear and cheap: a Stop hook runs every turn, and a timed-out hook renders
// no decision at all, so a slow scan is the same as no scan.
const VENDOR_DIR = /(?:^|\/)(?:node_modules|\.venv|venv|vendor|dist|build|target|\.next|\.nuxt|__pycache__|\.mypy_cache|\.pytest_cache|\.tox|\.gradle|Pods|\.git|\.claude|\.codex|\.opencode|\.idea|\.vscode)\//i;
// The same names as git exclude pathspecs (case-insensitive, at any depth), derived from VENDOR_DIR
// so the two lists cannot drift apart.
const VENDOR_PATHSPECS = VENDOR_DIR.source.split('(?:')[2].split(')')[0].split('|')
  .map((name) => `:(exclude,glob,icase)**/${name.replace(/\\/g, '')}/**`);
const MAX_UNTRACKED_FILES = 200;
const MAX_FILE_BYTES = 256 * 1024;
const MAX_TOTAL_BYTES = 4 * 1024 * 1024;

function quiet() { process.exit(0); }

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { quiet(); }

// Loop protection: if this Stop already blocked once, do not block again on the same turn.
if (input?.stop_hook_active) quiet();

const cwd = typeof input?.cwd === 'string' && input.cwd ? input.cwd : process.cwd();

function git(args, dir = cwd) {
  return runGit(args, {
    cwd: dir, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: MAX_TOTAL_BYTES,
  });
}

let root;
try {
  root = git(['rev-parse', '--show-toplevel']).trim();
} catch {
  quiet();                                   // not a repository: nothing to diff against
}
if (!root) quiet();

const findings = [];
let budget = MAX_TOTAL_BYTES;

// Record one scanned text. `fp` is the matched line itself: it goes into the suppression key (so a
// DIFFERENT secret at the same place is not mistaken for an old finding) and is never printed.
function report(text, where) {
  const lines = String(text).split(/\r?\n/);
  for (const f of scanLines(text, HIGH)) findings.push({ what: f.label, where, fp: lines[f.line - 1] ?? '' });
}

// Before the first commit there is no HEAD to diff against, and `git diff HEAD` fails. The delta
// then is everything staged (against the empty tree) plus the unstaged edits on top of it.
let hasHead = true;
try { git(['rev-parse', '--verify', '--quiet', 'HEAD^{commit}']); } catch { hasHead = false; }
const trackedDelta = (extra) => (hasHead
  ? git(['diff', 'HEAD', ...extra])
  : git(['diff', '--cached', ...extra]) + git(['diff', ...extra]));

// Each stage fails open ON ITS OWN. One failing git call used to abort the whole scan through a
// single outer catch, so a broken diff also skipped the untracked and ignored files.

// 1) Tracked changes, staged AND unstaged, against the last commit. This is the whole
//    uncommitted delta regardless of which tool produced it.
try {
  const added = addedDiffLines(trackedDelta(['--unified=0']));
  budget -= added.length;
  report(added, 'uncommitted change');
} catch { /* stage 1 produced nothing; stages 2 and 3 still run */ }

// -z (here and in the listings below): NUL-separated, verbatim names. Without it git C-quotes any
// name with non-ASCII, `"`, `\` or control characters ("\347\233\256..."); reading the quoted
// string as a file failed silently, so nothing under such a folder was scanned.
let changed = [];
try {
  changed = trackedDelta(['--name-only', '-z', '--diff-filter=ACMRT']).split('\0').filter(Boolean);
} catch { changed = []; }

let listed = [];
try {
  // 2) Untracked files, INCLUDING gitignored ones. A secret written to a brand-new file never
  //    appears in `git diff` at all — and `.env` is both the likeliest home for one and almost
  //    always gitignored, so `--exclude-standard` alone skipped exactly the file that matters.
  //    Vendored dependency trees are excluded instead: a token in node_modules is the vendor's
  //    fixture, not the user's secret, and walking them on every turn would blow the time budget.
  //    ls-files names are relative to its cwd, so it runs at the root the files are read from: from a
  //    subdirectory, `app/notes.txt` was listed as `notes.txt` and read from the wrong place.
  //    Vendor trees are also excluded by pathspec, so git never lists them: a large node_modules
  //    overflowed the listing buffer and dropped every ignored file. A listing that still fails
  //    yields nothing, instead of throwing away the tracked-change findings above.
  const listing = (args) => {
    try {
      return git([...args, '--', '.', ...VENDOR_PATHSPECS], root).split('\0').filter(Boolean)
        .filter((rel) => !VENDOR_DIR.test(rel));
    } catch {
      return [];
    }
  };
  // Likely secret homes first among ignored files (`.env`-style and credential names), then
  // shallow paths (stable sort): caches, logs and build output sit deeper.
  const rank = (rel) => (/^\.env/i.test(rel.split('/').pop()) || isCredentialFilename(rel) ? 0 : 1);
  const ignored = listing(['ls-files', '-z', '--others', '--ignored', '--exclude-standard'])
    .sort((a, b) => rank(a) - rank(b) || a.split('/').length - b.split('/').length);
  const others = listing(['ls-files', '-z', '--others', '--exclude-standard']);
  listed = [...ignored, ...others];

  //    Two content-scan budgets, files and bytes: when there are new untracked files, ignored files
  //    may use at most half of each, and whatever a class leaves unused goes to the other. Ignored
  //    artifacts (coverage HTML, logs) are large, so sharing only file slots let them spend the bytes
  //    before a new multi-file feature was read; new files alone pushed `.env` past the file cap.
  //    An over-cap file is skipped by size before it takes a slot.
  const scanFiles = (files, maxFiles, maxBytes) => {
    let used = 0;
    let spent = 0;
    for (const rel of files) {
      if (used >= maxFiles || spent >= maxBytes) break;
      let text = '';
      try {
        if (statSync(resolvePath(root, rel)).size > MAX_FILE_BYTES) continue;  // over-cap, before taking a slot
        const buf = readFileSync(resolvePath(root, rel));
        if (buf.length > MAX_FILE_BYTES) continue;      // over-cap: skipped to keep the Stop hook bounded
        used += 1;
        if (buf.includes(0)) continue;                  // binary: no text lines to scan
        text = buf.toString('utf8');
      } catch { continue; }
      spent += text.length;
      report(text, displayPath(rel));
    }
    return { used, spent };
  };
  const shared = others.length > 0;
  const ignoredUse = scanFiles(ignored,
    shared ? Math.max(MAX_UNTRACKED_FILES / 2, MAX_UNTRACKED_FILES - others.length) : MAX_UNTRACKED_FILES,
    shared ? budget / 2 : budget);
  scanFiles(others, MAX_UNTRACKED_FILES - ignoredUse.used, budget - ignoredUse.spent);
} catch { /* fail open: a broken scan must not wedge the turn */ }

// 3) Credential files by name, whether tracked-changed or brand new — a DER/binary key body has
//    no header for the content scan to find, so the name is the only signal. Names are cheap, so
//    every listed file is checked, not only those within the content-scan cap.
for (const rel of [...changed, ...listed]) {
  if (isCredentialFilename(rel)) findings.push({ what: 'credential file', where: displayPath(rel), fp: '' });
}

if (!findings.length) quiet();

// Per-session dedup. A Stop hook fires every turn; re-reporting an unchanged finding each time
// trains the reader to ignore it, which is worse than not reporting at all.
const sessionId = String(input?.session_id || 'nosession').replace(/[^A-Za-z0-9_-]/g, '');
const stateFile = process.env.AGENTIC_WORKTREE_SCAN_STATE
  || join(tmpdir(), 'agentic-sdlc', 'worktree-scan-' + sessionId + '.json');

let seen = [];
try { seen = JSON.parse(readFileSync(stateFile, 'utf8')); } catch { seen = []; }
const seenSet = new Set(Array.isArray(seen) ? seen : []);

const keyed = findings.map((f) => ({
  ...f,
  // The matched line is part of the key: label + location alone cannot tell a new secret from an old
  // one when they sit in the same file (or, for the uncommitted diff, under one shared label).
  key: createHash('sha256').update(f.what + '\u0000' + f.where + '\u0000' + f.fp).digest('hex').slice(0, 16),
}));
const fresh = keyed.filter((f) => !seenSet.has(f.key));
if (!fresh.length) quiet();

try {
  mkdirSync(join(tmpdir(), 'agentic-sdlc'), { recursive: true });
  writeFileSync(stateFile, JSON.stringify([...seenSet, ...fresh.map((f) => f.key)]), 'utf8');
} catch { /* dedup is a convenience; losing it must never change the verdict */ }

// Values are never printed, only the pattern label and where it was seen.
const list = fresh.map((f) => '  - ' + f.what + ' (' + f.where + ')').join('\n');
const msg =
  'agentic-sdlc worktree scan: possible secret(s) present in the working tree (values masked).\n'
  + list + '\n'
  + 'These bytes are already on disk, so this is a detection, not a block. Remove and rotate the '
  + 'value before committing; the repo pre-commit hook (scripts/install_git_hooks.py) is what '
  + 'stops it entering history.';

process.stdout.write(JSON.stringify(
  BLOCK
    ? { decision: 'block', reason: msg, systemMessage: 'agentic-sdlc: secret detected in the working tree.' }
    : { systemMessage: msg },
));
process.exit(0);
