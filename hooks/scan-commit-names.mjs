// Credential-filename recognition for scan-commit.mjs, plus the diff and display helpers the three
// diff scanners (scan-commit, git-hook-scan, worktree-scan) share.
//
// WHY THIS IS NOT A REGEX
// The first attempt at supporting DERIVED credential names (`cp id_rsa id_rsa.bak`, `.npmrc.old`,
// `server.key.bak`) extended the pattern with `(?:\.[A-Za-z0-9]{1,8}|~)*$` — a repeated group whose
// inner `{1,8}` is ambiguous, sitting in front of an end anchor. When the anchor fails the engine
// must try every way of splitting the suffix run, which is exponential. Measured on
// `id_rsa` + `.a`*N + `!`:
//     N=8 -> 459 ms      N=10 -> 1.16 s      N=12 -> 20.6 s
// A staged filename is agent-influenced, so that is a default-reachable DoS: the commit guard blows
// past its 20 s hook timeout and the runtime then fails open — the hardening becomes the bypass.
// This is the same lesson already recorded for `/\s*\)$/` in lessons.md, in a new shape: the trap is
// an AMBIGUOUS REPEATED GROUP before an anchor, not just greedy whitespace.
//
// The replacement is a single linear pass with no backtracking surface at all.

// Names that are a credential by themselves.
const CRED_BASENAMES = new Set([
  'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519', '.npmrc', '.netrc', '.pgpass', '.htpasswd',
]);
// Extensions that make the file a credential container.
const CRED_EXTENSIONS = new Set(['pem', 'key', 'p12', 'pfx', 'jks', 'keystore', 'ppk']);
// A suffix that marks a copy rather than a different kind of file.
const MAX_SUFFIX = 8;
// The PUBLIC half of a keypair is exactly what you are supposed to commit (deploy keys, dotfiles,
// authorized_keys tooling). Flagging `id_rsa.pub` is a false BLOCK, and a guard that denies safe,
// routine work is the fastest way to get itself switched off.
const PUBLIC_SUFFIXES = new Set(['pub']);
// Credential extensions that really do have a `.pub` counterpart (`ssh-keygen -f deploy.key`
// produces `deploy.key.pub`). Container formats — p12/pfx/jks/keystore/ppk — have no such
// convention, so a `.pub` after one of those is a rename, not a public key.
const PUB_PAIRED_EXTENSIONS = new Set(['key', 'pem']);

/**
 * True when `path` names a credential file, including a derived copy of one.
 *
 * `id_rsa` / `id_rsa.bak` / `.npmrc.old` / `server.key.bak` / `cert.p12` -> true
 * `notes.bak` / `keys.md` / `monkey.txt` / `keyboard.js` / `main.py`     -> false
 *
 * Linear in the length of the name: one split, then a bounded scan of the parts.
 */
export function isCredentialFilename(path) {
  let name = String(path ?? '').replace(/\\/g, '/');
  const slash = name.lastIndexOf('/');
  if (slash !== -1) name = name.slice(slash + 1);
  // Verbatim (NUL-separated) git listings keep surrounding blanks: ` id_rsa` or `cert.p12 ` is the
  // same credential, so judge the trimmed name.
  name = name.trim();
  while (name.endsWith('~')) name = name.slice(0, -1).trimEnd(); // emacs-style backup
  if (!name) return false;

  // Split into a leading name and its dotted parts. A dotfile keeps its leading dot in part 0.
  const leadingDot = name.startsWith('.');
  const body = leadingDot ? name.slice(1) : name;
  const parts = body.split('.');
  const base = (leadingDot ? '.' : '') + parts[0];
  const rest = parts.slice(1);

  // The `.pub` carve-out has to be narrow in BOTH directions, and getting it wrong created a
  // bypass twice. Matching `pub` anywhere in the tail let `secrets.pub.pem` through; matching it
  // as the terminal suffix alone let `cert.p12.pub` through, because appending `.pub` to any
  // credential container then defeated the filename check AND the content check (those formats are
  // binary, so there is no PEM header for the diff scan to find).
  // A `.pub` file is only genuine where the convention actually exists: next to a credential BASE
  // name (`id_rsa.pub`) or a `.key`/`.pem` sibling (`deploy.key.pub`). Nobody names a public key
  // `cert.p12.pub` — that is a rename, not a keypair half.
  if (rest.length && PUBLIC_SUFFIXES.has(rest[rest.length - 1].toLowerCase())) {
    const prev = rest.length >= 2 ? rest[rest.length - 2].toLowerCase() : null;
    if (prev === null || !CRED_EXTENSIONS.has(prev) || PUB_PAIRED_EXTENSIONS.has(prev)) return false;
  }

  if (CRED_BASENAMES.has(base.toLowerCase())) {
    // Every trailing part must look like a derived suffix, or this is a different file that merely
    // starts with a credential name (`id_rsa_notes.longextension` style inputs stay clean).
    return rest.every((p) => p.length >= 1 && p.length <= MAX_SUFFIX && /^[A-Za-z0-9]+$/.test(p));
  }
  // Otherwise a credential EXTENSION anywhere in the dotted tail marks it (`server.key.bak`).
  return rest.some((p) => CRED_EXTENSIONS.has(p.toLowerCase()));
}

/**
 * A file name made safe to print in guard output: control characters (ESC sequences can rewrite or
 * hide a terminal's block message) become visible `\xNN` escapes; everything else is kept verbatim.
 */
export function displayPath(path) {
  return String(path ?? '').replace(/[\u0000-\u001f\u007f]/g,
    (ch) => '\\x' + ch.charCodeAt(0).toString(16).padStart(2, '0'));
}

// The added lines of a unified diff, joined by newlines. `+++` is a file header only between a
// `diff ` line and its first `@@` hunk; inside a hunk every `+` line is added content, including
// content that itself starts with `++` (a `!startsWith('+++')` filter dropped those unscanned).
export function addedDiffLines(diff) {
  const added = [];
  let inHunk = false;
  for (const line of String(diff ?? '').split(/\r?\n/)) {
    if (line.startsWith('diff ')) inHunk = false;
    else if (line.startsWith('@@')) inHunk = true;
    else if (inHunk && line.startsWith('+')) added.push(line.slice(1));
  }
  return added.join('\n');
}

// True when a git call failed only because its output passed the caller's maxBuffer.
function overflowed(err) {
  return Boolean(err) && (err.code === 'ENOBUFS' || /maxBuffer/i.test(String(err.message)));
}

// `--numstat -z` records as { weight, paths }: weight is added + deleted lines (a binary or unknown count
// is 0), and a rename or copy keeps both of its names, so a pathspec limited to the group still pairs them.
function numstatUnits(out) {
  const fields = String(out ?? '').split('\0');
  const units = [];
  for (let i = 0; i < fields.length; i += 1) {
    const record = /^(\d+|-)\t(\d+|-)\t([\s\S]*)$/.exec(fields[i]);
    if (!record) continue;
    const weight = (Number(record[1]) || 0) + (Number(record[2]) || 0);
    if (record[3] !== '') {
      units.push({ weight, paths: [record[3]] });
    } else {
      units.push({ weight, paths: [fields[i + 1], fields[i + 2]].filter(Boolean) });
      i += 2;
    }
  }
  return units.filter((unit) => unit.paths.length);
}

// Pathspec groups stay far below the Windows command-line limit.
const GROUP_FILES = 64;
const GROUP_CHARS = 8000;

/**
 * A unified diff that stays under the caller's output cap, with the files it had to leave out (SW-6).
 *
 * `git(args)` is the caller's runner (its maxBuffer is the per-call cap) and `base` the diff argv, such as
 * `['diff', '--cached', '--unified=0']`. The whole diff is one call when it fits. When it does not, one
 * oversized file used to drop the scan of every other file; now the changed files are listed with
 * `--numstat -z`, smallest first, and diffed in groups. A group that overflows is split until one file is
 * left, and that file is skipped and named. The text this fallback collects never passes `maxTotal`: the
 * files that would pass it are skipped and named too, so the total work stays bounded. Once `deadline` (a
 * Date.now() value) has passed, the groups not yet diffed are skipped and named the same way, so a caller
 * with a hook timeout keeps time for its other stages (R2-SW-7). The listing keeps unmerged (`U`) paths.
 * `pathspec` limits the diff (and the fallback listing) to those paths; it is never part of `base`,
 * because the fallback appends its own options and `--` group after `base`.
 */
export function boundedDiff(git, base, { maxTotal = Infinity, pathspec = [], deadline = Infinity } = {}) {
  const limit = pathspec.length ? ['--', ...pathspec] : [];
  try {
    return { text: git([...base, ...limit]), skipped: [] };
  } catch (err) {
    if (!overflowed(err)) throw err;
  }
  // `--unified` implies `--patch`, which would print the whole oversized diff next to the counts.
  const listing = base.filter((arg) => !/^(?:-U\d*|--unified(?:=\d+)?)$/.test(arg));
  const units = numstatUnits(git([...listing, '--numstat', '-z', '--diff-filter=ACMRTU', ...limit]))
    .sort((a, b) => a.weight - b.weight);
  const skipped = [];
  const skip = (group) => { for (const unit of group) skipped.push(unit.paths[unit.paths.length - 1]); };
  let text = '';
  let full = false;
  const run = (group) => {
    if (full || Date.now() > deadline) { skip(group); return; }
    let out = null;
    try {
      out = git([...base, '--', ...group.flatMap((unit) => unit.paths.map((p) => ':(top,literal)' + p))]);
    } catch (err) {
      if (!overflowed(err)) throw err;
    }
    if (out !== null && text.length + out.length <= maxTotal) {
      text += out.endsWith('\n') || !out ? out : out + '\n';
      return;
    }
    if (group.length > 1) {
      run(group.slice(0, group.length >> 1));
      run(group.slice(group.length >> 1));
      return;
    }
    skip(group);
    // One file that fits a call but not what is left of maxTotal: the files after it are larger (they
    // are sorted), so they are skipped without another git call.
    if (out !== null) full = true;
  };
  let group = [];
  let chars = 0;
  for (const unit of units) {
    const size = unit.paths.reduce((sum, p) => sum + p.length + 16, 0);
    if (group.length && (group.length >= GROUP_FILES || chars + size > GROUP_CHARS)) {
      run(group);
      group = [];
      chars = 0;
    }
    group.push(unit);
    chars += size;
  }
  if (group.length) run(group);
  return { text, skipped };
}
