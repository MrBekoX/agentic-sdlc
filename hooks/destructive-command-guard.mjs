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
    label: 'rm-recursive',
    check: hasRecursiveRm,
    reason: 'rm with recursive flags recursively deletes files.',
  },
  {
    label: 'powershell-remove-item-recurse',
    check: hasRecursiveRemoveItem,
    reason: 'Remove-Item -Recurse recursively deletes files.',
  },
];

function stripQuoted(text) {
  let out = '';
  let quote = null;
  let escaped = false;
  for (const ch of text) {
    if (quote) {
      if (escaped) {
        escaped = false;
      } else if (ch === '\\' && quote === '"') {
        escaped = true;
      } else if (ch === quote) {
        quote = null;
      }
      out += /\s/.test(ch) ? ch : ' ';
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      out += ' ';
      continue;
    }
    out += ch;
  }
  return out;
}

function commandSegments(cmd) {
  return stripQuoted(cmd)
    .split(/[;&|\n(){}]+/)
    .map((segment) => segment.trim())
    .filter(Boolean);
}

function rawCommandSegments(cmd) {
  const segments = [];
  let segment = '';
  let quote = null;
  let escaped = false;
  for (const ch of cmd) {
    if (quote) {
      segment += ch;
      if (escaped) {
        escaped = false;
      } else if (ch === '\\' && quote === '"') {
        escaped = true;
      } else if (ch === quote) {
        quote = null;
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      segment += ch;
      continue;
    }
    if (/[;&|\n(){}]/.test(ch)) {
      if (segment.trim()) segments.push(segment.trim());
      segment = '';
      continue;
    }
    segment += ch;
  }
  if (segment.trim()) segments.push(segment.trim());
  return segments;
}

function tokenize(segment) {
  return segment.split(/\s+/).filter(Boolean);
}

function tokenizePreservingQuotes(text) {
  const tokens = [];
  let token = '';
  let quote = null;
  let escaped = false;
  for (const ch of text) {
    if (quote) {
      if (escaped) {
        token += ch;
        escaped = false;
      } else if (ch === '\\' && quote === '"') {
        escaped = true;
      } else if (ch === quote) {
        quote = null;
      } else {
        token += ch;
      }
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (/\s/.test(ch)) {
      if (token) {
        tokens.push(token);
        token = '';
      }
      continue;
    }
    token += ch;
  }
  if (token) tokens.push(token);
  return tokens;
}

function basename(token) {
  return token.replace(/^["']|["']$/g, '').split(/[\\/]/).pop();
}

function commandName(token) {
  return basename(token).toLowerCase().replace(/\.exe$/, '');
}

function commandTokens(cmd) {
  const tokens = commandSegments(cmd).map(tokenize).map(unwrapCommand).filter((items) => items.length);
  const wrapped = rawCommandSegments(cmd).flatMap(powerShellPayloads).flatMap(commandTokens);
  return tokens.concat(wrapped);
}

function powerShellPayloads(segment) {
  const tokens = tokenizePreservingQuotes(segment);
  const payloads = [];
  for (let i = 0; i < tokens.length; i += 1) {
    const name = commandName(tokens[i]);
    if (!['powershell', 'pwsh'].includes(name)) continue;
    for (let j = i + 1; j < tokens.length; j += 1) {
      if (/^(?:-command|-c|\/c)$/i.test(tokens[j])) {
        const payload = tokens.slice(j + 1).join(' ').trim();
        if (payload) payloads.push(payload);
        break;
      }
    }
  }
  return payloads;
}

function unwrapCommand(tokens) {
  let i = 0;
  while (i < tokens.length) {
    const name = commandName(tokens[i]);
    if (name === 'sudo') {
      i += 1;
      while (i < tokens.length && tokens[i].startsWith('-')) {
        const option = tokens[i].toLowerCase();
        i += 1;
        if (/^(?:-[ughpc]|--(?:user|group|host|prompt|chdir))$/.test(option) && i < tokens.length && !tokens[i].startsWith('-')) {
          i += 1;
        }
      }
      while (i < tokens.length && tokens[i].includes('=')) i += 1;
      continue;
    }
    if (name === 'command') {
      i += 1;
      while (i < tokens.length && tokens[i].startsWith('-')) i += 1;
      continue;
    }
    if (name === 'env') {
      i += 1;
      while (i < tokens.length) {
        if (tokens[i].includes('=')) {
          i += 1;
          continue;
        }
        if (!tokens[i].startsWith('-')) break;
        const option = tokens[i].toLowerCase();
        i += 1;
        if (/^(?:-u|--unset|--chdir|-c|-s|--split-string)$/i.test(option) && i < tokens.length && !tokens[i].startsWith('-')) {
          i += 1;
        }
      }
      continue;
    }
    break;
  }
  return tokens.slice(i);
}

function hasRmRecursiveFlag(args) {
  return args.some((arg) => arg === '--recursive' || (arg.length <= 5 && /^-[A-Za-z]*[rR][A-Za-z]*$/.test(arg)));
}

function hasRemoveItemRecursiveFlag(args) {
  return args.some((arg) => /^-r(?:e(?:c\w*)?)?$/i.test(arg));
}

function hasRecursiveRm(cmd) {
  return commandTokens(cmd).some((tokens) => {
    const name = commandName(tokens[0]);
    return name === 'rm' && hasRmRecursiveFlag(tokens.slice(1));
  });
}

function hasRecursiveRemoveItem(cmd) {
  const names = new Set(['remove-item', 'ri', 'del', 'erase', 'rd', 'rmdir', 'rm']);
  return commandTokens(cmd).some((tokens) => {
    const name = commandName(tokens[0]);
    return names.has(name) && hasRemoveItemRecursiveFlag(tokens.slice(1));
  });
}

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
  const blocked = finding.check ? finding.check(cmd) : finding.re.test(cmd);
  if (blocked) {
    deny(finding);
    process.exit(0);
  }
}

process.exit(0);
