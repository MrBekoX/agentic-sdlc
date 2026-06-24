// PreToolUse (Bash, if: git commit) — scans secrets ADDED in the commit; BLOCKS if found.
// Only scans lines ADDED to the diff -> doesn't trigger on already-committed secrets.
// On error, fail-open (does not break the commit).
import { execFileSync } from 'node:child_process';
import { HIGH, scanLines, readStdin } from './secret-patterns.mjs';

// No shell: git is called with an argument array (no command-injection surface, no Windows quoting issues).
// On a read failure we still fail open (never break the commit), but record it so the commit isn't
// silently treated as "scanned & clean" — see the non-blocking warning at the end.
let gitReadFailed = false;
function gitDiff(args) {
  try {
    return execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  } catch {
    gitReadFailed = true;
    return '';
  }
}

// Credential files whose mere presence is a leak, regardless of content (a DER/base64 key body
// or an .npmrc/.netrc has no recognizable header line for the content scan to catch).
const SECRET_FILENAME = /(?:^|\/)(?:id_(?:rsa|dsa|ecdsa|ed25519)|\.npmrc|\.netrc)$|\.(?:pem|key|p12|pfx)$/i;

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { /* ignore */ }
const cmd = String(input?.tool_input?.command || '');

// Second safety check: only git commit.
if (!/\bgit\b[\s\S]*\bcommit\b/.test(cmd)) process.exit(0);

let diff = gitDiff(['diff', '--cached', '--unified=0']);
let names = gitDiff(['diff', '--cached', '--name-only', '--diff-filter=ACMR']);
// `commit -a/-am/--all` also commits tracked changes -> scan unstaged too.
if (/\bcommit\b[^|&;]*\s-[A-Za-z]*a/.test(cmd) || /\s--all\b/.test(cmd)) {
  diff += '\n' + gitDiff(['diff', '--unified=0']);
  names += '\n' + gitDiff(['diff', '--name-only', '--diff-filter=ACMR']);
}

const added = diff
  .split(/\r?\n/)
  .filter((l) => l.startsWith('+') && !l.startsWith('+++'))
  .map((l) => l.slice(1))
  .join('\n');

const contentFindings = scanLines(added, HIGH);
const fileFindings = names
  .split(/\r?\n/)
  .map((s) => s.trim())
  .filter(Boolean)
  .filter((p) => SECRET_FILENAME.test(p))
  .map((p) => ({ file: p, label: 'secret-file' }));

if (contentFindings.length || fileFindings.length) {
  const list = [
    ...contentFindings.map((f) => `  • ${f.label} (added line ~${f.line})`),
    ...fileFindings.map((f) => `  • ${f.label} (${f.file})`),
  ].join('\n');
  const reason =
    `Commit blocked: possible secret found in added diff lines (values masked).\n${list}\n` +
    `→ If it is a real secret, move it to env / secret store and remove it from code. If intentional/false-positive, disable temporarily via /hooks.`;
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: reason,
    },
    systemMessage: '🔒 secret scan: commit blocked (possible secret).',
  }));
  process.exit(0);
}

// Fail-open is deliberate (never break a commit), but surface it: if a git read failed, the commit
// was not actually scanned, so don't let its silence read as "scanned & clean". Non-blocking.
if (gitReadFailed) {
  process.stdout.write(JSON.stringify({
    systemMessage: '⚠️ secret scan: could not read `git diff` — this commit was NOT scanned for secrets.',
  }));
}

process.exit(0);
