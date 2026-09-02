// PreToolUse (Bash) — blocks high-risk destructive shell commands.
// This is intentionally narrow and deterministic. It catches common commands that
// destroy repository state or recursively delete files. On parse errors it fails open.
//
// Scope (deliberate — a backstop, NOT full coverage): rm -rf, git reset --hard, git clean -fd,
// Remove-Item -Recurse — including quoted command names ("rm"/'rm'), wrappers
// (sudo/env/command/timeout/nice/xargs/...), and shell `-c` / `eval` payloads. NOT covered, by
// design: other destructive verbs (find -delete, shred, truncate -s 0, dd of=, >-redirect) and
// runtime shell indirection that is statically undecidable (eval "$(...)", a=rm;$a, rm$IFS-rf).
// The permission prompt remains the primary control; this guard only catches the common cases.
import { readStdin } from './secret-patterns.mjs';
import { expandAnsiCQuotes } from './shell-quoting.mjs';

const BLOCKED = [
  {
    label: 'git-reset-hard',
    check: hasGitResetHard,
    reason: 'git reset --hard discards local changes.',
  },
  {
    label: 'git-clean-force',
    check: hasGitCleanForce,
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

// Command wrappers whose real command follows them: `timeout 5 rm -rf`, `nice -n 10 rm -rf`,
// `nohup rm -rf`, `xargs rm -rf`. positional = positional args the wrapper itself consumes
// (timeout takes a DURATION); argOpts = options that consume a following value.
const WRAPPERS = {
  nohup: { positional: 0, argOpts: new Set() },
  setsid: { positional: 0, argOpts: new Set() },
  nice: { positional: 0, argOpts: new Set(['-n', '--adjustment']) },
  ionice: { positional: 0, argOpts: new Set(['-c', '-n', '-p']) },
  stdbuf: { positional: 0, argOpts: new Set(['-i', '-o', '-e']) },
  time: { positional: 0, argOpts: new Set(['-o', '--output', '-f', '--format']) },
  timeout: { positional: 1, argOpts: new Set(['-s', '--signal', '-k', '--kill-after']) },
  xargs: { positional: 0, argOpts: new Set(['-n', '--max-args', '-p', '--max-procs', '-i', '--replace', '-d', '--delimiter', '-a', '--arg-file', '-s', '--max-chars', '-l', '--max-lines', '-e', '--eof']) },
};

// Shells whose `-c <payload>` (and `eval <payload>`) run an inline command we must inspect.
const SHELL_NAMES = ['powershell', 'pwsh', 'bash', 'sh', 'zsh', 'dash', 'ksh'];

function removeBashLineContinuations(cmd) {
  let out = '';
  let quote = null;
  for (let i = 0; i < cmd.length; i += 1) {
    const ch = cmd[i];
    if (ch === "'" && quote === null) {
      quote = "'";
      out += ch;
      continue;
    }
    if (ch === "'" && quote === "'") {
      quote = null;
      out += ch;
      continue;
    }
    if (ch === '"' && quote !== "'") {
      quote = quote === '"' ? null : '"';
      out += ch;
      continue;
    }
    // Bash removes backslash-newline before tokenization outside single quotes, including inside
    // double quotes. Preserve ordinary backslashes for the one unescape pass in the tokenizer.
    if (ch === '\\' && quote !== "'") {
      if (cmd[i + 1] === '\n') {
        i += 1;
        continue;
      }
      if (cmd[i + 1] === '\r' && cmd[i + 2] === '\n') {
        i += 2;
        continue;
      }
    }
    out += ch;
  }
  return out;
}

function rawCommandSegments(cmd, protectEscapedSeparators = false) {
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
    if (protectEscapedSeparators && escaped) {
      // Keep the pair intact. tokenizePreservingQuotes() performs the ONE Bash unescape pass;
      // consuming it here as well turns safe r\\\\m into rm and creates a false denial.
      segment += ch;
      escaped = false;
      continue;
    }
    if (protectEscapedSeparators && ch === '\\') {
      segment += ch;
      escaped = true;
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

function tokenizePreservingQuotes(text, unescapeUnquoted = false) {
  const tokens = [];
  let token = '';
  let quote = null;
  let escaped = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      if (escaped) {
        token += ch;
        escaped = false;
      } else if (ch === '\\' && quote === '"') {
        // In Bash double quotes, backslash is special only before $, backtick, quote, backslash,
        // or newline. Generic/PowerShell view preserves it, and Bash view preserves \m too.
        const next = text[i + 1];
        if (unescapeUnquoted && next && /[$`"\\\r\n]/.test(next)) escaped = true;
        else token += ch;
      } else if (ch === quote) {
        quote = null;
      } else {
        token += ch;
      }
      continue;
    }
    if (unescapeUnquoted && escaped) {
      token += ch;
      escaped = false;
      continue;
    }
    if (unescapeUnquoted && ch === '\\') {
      escaped = true;
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

function commandTokensOne(cmd, unescapeUnquoted) {
  const source = unescapeUnquoted
    ? expandAnsiCQuotes(removeBashLineContinuations(cmd))
    : cmd;
  // Segment on UNQUOTED separators, then tokenize each segment with quote REMOVAL (not blanking).
  // A quoted command name still runs the command in a shell ("rm"/'rm'/r"m" all execute rm), so
  // unquoting per token — instead of erasing quoted spans before tokenizing — keeps the real
  // command name visible to the checks below while still treating a quoted argument blob
  // (echo "rm -rf x") as a single non-command token.
  const segments = rawCommandSegments(source, unescapeUnquoted);
  const tokens = segments
    .map((segment) => tokenizePreservingQuotes(segment, unescapeUnquoted))
    .map(unwrapCommand)
    .filter((items) => items.length);
  const wrapped = segments
    .flatMap((segment) => shellPayloads(segment, unescapeUnquoted))
    // Each explicit shell starts a new parsing layer. A payload single-quoted for the outer shell
    // can contain a backslash-newline or ANSI-C quote that only the INNER bash/sh realizes.
    .flatMap((payload) => commandTokensOne(payload.text, payload.bashSemantics));
  return tokens.concat(wrapped);
}

function commandTokens(cmd, bashSemantics = false) {
  const raw = commandTokensOne(cmd, false);
  if (!bashSemantics) return raw;
  // Preserve the generic/PowerShell view and add a Bash-realized view. The union prevents Bash
  // quote removal from hiding Windows-style paths while still exposing r\m and $'\\x72\\x6d'.
  return raw.concat(commandTokensOne(cmd, true));
}

function shellPayloads(segment, unescapeUnquoted) {
  const tokens = tokenizePreservingQuotes(segment, unescapeUnquoted);
  const payloads = [];
  for (let i = 0; i < tokens.length; i += 1) {
    const name = commandName(tokens[i]);
    if (name === 'eval') {
      const payload = tokens.slice(i + 1).join(' ').trim();
      if (payload) payloads.push({ text: payload, bashSemantics: unescapeUnquoted });
      continue;
    }
    if (!SHELL_NAMES.includes(name)) continue;
    for (let j = i + 1; j < tokens.length; j += 1) {
      // bash/sh/zsh/dash/ksh: -c (also -lc/-ic); powershell/pwsh: -Command / -c / /c.
      if (/^(?:-command|\/c|-[a-z]*c)$/i.test(tokens[j])) {
        const payload = tokens.slice(j + 1).join(' ').trim();
    if (payload) {
      payloads.push({
        text: payload,
        bashSemantics: ['bash', 'sh', 'zsh', 'dash', 'ksh'].includes(name),
      });
    }
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
    if (WRAPPERS[name]) {
      const wrap = WRAPPERS[name];
      i += 1;
      while (i < tokens.length && tokens[i].startsWith('-')) {
        const raw = tokens[i];
        const opt = raw.split('=')[0].toLowerCase();
        i += 1;
        if (!raw.includes('=') && wrap.argOpts.has(opt) && i < tokens.length && !tokens[i].startsWith('-')) {
          i += 1;
        }
      }
      for (let p = 0; p < wrap.positional && i < tokens.length && !tokens[i].startsWith('-'); p += 1) {
        i += 1;
      }
      continue;
    }
    if (name === 'find') {
      const rest = tokens.slice(i + 1);
      const execAt = rest.findIndex((t) => /^-exec$|^-execdir$/i.test(t));
      if (execAt !== -1) {
        i += 1 + execAt + 1;
        continue;
      }
      break;
    }
    break;
  }
  return tokens.slice(i);
}

function hasRmRecursiveFlag(args) {
  // A single-dash bundle of letters containing r/R is a recursive rm flag at any length
  // (the prior arg.length<=5 cap let `rm -rfvvv` through). `--recursive` starts with two dashes,
  // so the regex never matches it here, and a non-flag path argument never starts with a single dash.
  return args.some((arg) => arg === '--recursive' || /^-[A-Za-z]*[rR][A-Za-z]*$/.test(arg));
}

function hasRemoveItemRecursiveFlag(args) {
  return args.some((arg) => /^-r(?:e(?:c\w*)?)?$/i.test(arg));
}

function hasRecursiveRm(cmd, bashSemantics) {
  return commandTokens(cmd, bashSemantics).some((tokens) => {
    const name = commandName(tokens[0]);
    return name === 'rm' && hasRmRecursiveFlag(tokens.slice(1));
  });
}

function hasRecursiveRemoveItem(cmd, bashSemantics) {
  const names = new Set(['remove-item', 'ri', 'del', 'erase', 'rd', 'rmdir', 'rm']);
  return commandTokens(cmd, bashSemantics).some((tokens) => {
    const name = commandName(tokens[0]);
    return names.has(name) && hasRemoveItemRecursiveFlag(tokens.slice(1));
  });
}

// Return the git subcommand + its args, skipping any global options before the subcommand
// (git -C <dir>, git -c k=v, git --no-pager, ...) so `git -C /tmp reset --hard` is still matched.
function gitSubcommand(tokens) {
  const ARG_OPTS = new Set(['-c', '--git-dir', '--work-tree', '--namespace', '--super-prefix', '--config-env', '--exec-path']);
  let i = 1;
  while (i < tokens.length && tokens[i].startsWith('-')) {
    const raw = tokens[i];
    const base = raw.split('=')[0].toLowerCase();
    i += 1;
    if (!raw.includes('=') && ARG_OPTS.has(base) && i < tokens.length && !tokens[i].startsWith('-')) {
      i += 1;
    }
  }
  return tokens.slice(i);
}

function hasGitResetHard(cmd, bashSemantics) {
  return commandTokens(cmd, bashSemantics).some((tokens) => {
    if (commandName(tokens[0]) !== 'git') return false;
    const sub = gitSubcommand(tokens);
    return sub[0] === 'reset' && sub.slice(1).some((arg) => arg === '--hard');
  });
}

function hasGitCleanForce(cmd, bashSemantics) {
  return commandTokens(cmd, bashSemantics).some((tokens) => {
    if (commandName(tokens[0]) !== 'git') return false;
    const sub = gitSubcommand(tokens);
    if (sub[0] !== 'clean') return false;
    const args = sub.slice(1);
    const force = args.some((arg) => arg === '--force' || /^-[A-Za-z]*f[A-Za-z]*$/.test(arg));
    const target = args.some((arg) => arg === '--ignored' || arg === '--exclude-standard' || /^-[A-Za-z]*[dxX][A-Za-z]*$/.test(arg));
    return force && target;
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
const bashSemantics = String(input?.tool_name || '') === 'Bash';

for (const finding of BLOCKED) {
  const blocked = finding.check ? finding.check(cmd, bashSemantics) : finding.re.test(cmd);
  if (blocked) {
    deny(finding);
    process.exit(0);
  }
}

process.exit(0);
