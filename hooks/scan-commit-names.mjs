// Credential-filename recognition for scan-commit.mjs.
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
  while (name.endsWith('~')) name = name.slice(0, -1);       // emacs-style backup
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
