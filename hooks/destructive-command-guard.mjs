// PreToolUse (Bash) — blocks high-risk destructive shell commands.
// This is intentionally narrow and deterministic. It catches common commands that
// destroy repository state or recursively delete files. On parse errors it fails open.
import { readStdin } from './secret-patterns.mjs';

const BLOCKED = [
  {
    label: 'git-reset-hard',
    re: /\bgit\s+reset\s+--hard\b/i,
    reason: 'git reset --hard discards local changes.',
  },
  {
    label: 'git-clean-force',
    re: /\bgit\s+clean\b(?=[\s\S]*(?:--force\b|-[A-Za-z]*f))(?=[\s\S]*(?:-[A-Za-z]*[dxX]|--ignored\b|--exclude-standard\b))/i,
    reason: 'git clean with force and directory/ignored-file flags deletes untracked files.',
  },
  {
    label: 'rm-rf',
    re: /\brm\s+-(?:[A-Za-z]*r[A-Za-z]*f|[A-Za-z]*f[A-Za-z]*r)[\w-]*\b/i,
    reason: 'rm -rf recursively deletes files.',
  },
  {
    label: 'powershell-remove-item-recurse',
    re: /\bRemove-Item\b[\s\S]*(?:-Recurse\b|\s-r\b)[\s\S]*(?:-Force\b|\s-f\b)/i,
    reason: 'Remove-Item -Recurse -Force recursively deletes files.',
  },
];

function deny(finding) {
  const msg =
    `Blocked destructive command (${finding.label}): ${finding.reason} ` +
    'Ask for explicit approval and use a scoped, reviewed command if this is intentional.';
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: msg,
    },
    systemMessage: `🛑 destructive-command-guard: ${msg}`,
  }));
}

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { /* fail open */ }
const cmd = String(input?.tool_input?.command || '');

for (const finding of BLOCKED) {
  if (finding.re.test(cmd)) {
    deny(finding);
    process.exit(0);
  }
}

process.exit(0);
