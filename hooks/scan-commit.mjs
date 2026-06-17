// PreToolUse (Bash, if: git commit) — scans secrets ADDED in the commit; BLOCKS if found.
// Only scans lines ADDED to the diff -> doesn't trigger on already-committed secrets.
// On error, fail-open (does not break the commit).
import { execFileSync } from 'node:child_process';
import { HIGH, scanLines, readStdin } from './secret-patterns.mjs';

// No shell: git is called with an argument array (no command-injection surface, no Windows quoting issues).
function gitDiff(args) {
  try {
    return execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  } catch {
    return '';
  }
}

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { /* ignore */ }
const cmd = String(input?.tool_input?.command || '');

// Second safety check: only git commit.
if (!/\bgit\b[\s\S]*\bcommit\b/.test(cmd)) process.exit(0);

let diff = gitDiff(['diff', '--cached', '--unified=0']);
// `commit -a/-am/--all` also commits tracked changes -> scan unstaged too.
if (/\bcommit\b[^|&;]*\s-[A-Za-z]*a/.test(cmd) || /\s--all\b/.test(cmd)) {
  diff += '\n' + gitDiff(['diff', '--unified=0']);
}

const added = diff
  .split(/\r?\n/)
  .filter((l) => l.startsWith('+') && !l.startsWith('+++'))
  .map((l) => l.slice(1))
  .join('\n');

const findings = scanLines(added, HIGH);

if (findings.length) {
  const list = findings.map((f) => `  • ${f.label} (added line ~${f.line})`).join('\n');
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

process.exit(0);
