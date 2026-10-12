// PreToolUse (Bash) — blocks high-risk destructive shell commands.
// This is intentionally narrow and deterministic. It catches common commands that
// destroy repository state or recursively delete files. On parse errors it fails open.
//
// Scope (deliberate — a backstop, NOT full coverage): rm -rf, git reset --hard, git clean -fd,
// Remove-Item -Recurse — including quoted command names ("rm"/'rm'), wrappers
// (sudo/env/command/timeout/nice/xargs/...), shell `-c` / `eval` payloads, and every
// POSIX cmd_prefix that may precede a command word: assignment prefixes, io_redirections in
// all their spellings (spaced, attached, numbered, fd-duplicating, input), bash reserved
// words (if/then/else/elif/for/while/until/select/do/done/case/coproc/exec), `!`, and command
// substitution in all three contexts (unquoted, inside double quotes, backtick spelling).
// Substitution inside SINGLE quotes is literal text and is deliberately not inspected.
// Consequence worth knowing: a commit message that puts a destructive verb in a BACKTICK
// pair inside double quotes is denied, because bash really runs it there and this guard
// is scope-narrow by VERB rather than by target (a bare `rm -rf` with no operand already
// denies). Single quotes suppress the substitution and are allowed - which is what a
// careful shell user would write anyway.
//
// Two halves with different guarantees. The cmd_prefix set is CLOSED by the shell grammar
// (POSIX 2.9.1 plus bash's reserved-word list), so it is a positive grammar and complete.
// The WRAPPERS table is OPEN-ENDED and stays a deny-list: there is no specification that
// bounds "programs that run another program", so a wrapper not in the table is a gap, not a
// bug in the walker. Do not read the parity check as evidence that the table is complete.
//
// NOT covered, by design: other destructive verbs (find -delete, shred, truncate -s 0, dd of=,
// >-redirect) and runtime shell indirection that is statically undecidable (eval "$(...)",
// a=rm;$a, rm$IFS-rf) — the class the shell resolves after this hook has already decided.
// The permission prompt remains the primary control; this guard only catches the common cases.
import { readStdin } from './secret-patterns.mjs';
import { expandAnsiCQuotes } from './shell-quoting.mjs';
import { skipCommandPrefix } from './shell-prefix.mjs';
import { emitHookResult } from './hook-output.mjs';

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
  // argOpts is EXACTLY the options that take a SEPARATE following value. Both errors are
  // bypasses: over-consuming skips past the command name, and under-consuming leaves the
  // option's value sitting where the command name should be, so `5` resolves as the command
  // and nothing matches. In GNU xargs `-p`/`--interactive` is a plain flag, and `-i[R]`,
  // `-l[N]`, `-e[eof]` take only an ATTACHED value - as do the long forms `--replace`,
  // `--max-lines` and `--eof`, whose optional arguments must be written with `=`.
  xargs: { positional: 0, argOpts: new Set(['-n', '--max-args', '-P', '--max-procs', '-I', '-L', '-E', '-d', '--delimiter', '-a', '--arg-file', '-s', '--max-chars']) },
  // `builtin` was carried by git-invocation.mjs and not by this guard - the capability
  // asymmetry BR2 calls a defect by definition.
  builtin: { positional: 0, argOpts: new Set() },
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

// True when the `&` at `index` belongs to a redirect operator rather than being a separator:
// `2>&1`, `<&0`, `&>log`, `&>>log`. Splitting on it left a segment starting with a bare fd
// digit, so the command after it was never resolved.
function ampersandIsRedirect(text, index, segment) {
  if (text[index + 1] === '>') return true;          // &> / &>>
  for (let i = segment.length - 1; i >= 0; i -= 1) { // 2>& / <&
    const c = segment[i];
    if (c === ' ' || c === '\t') continue;
    return c === '>' || c === '<';
  }
  return false;
}

function rawCommandSegments(cmd, protectEscapedSeparators = false) {
  const segments = [];
  let segment = '';
  let quote = null;
  let escaped = false;
  // Command substitution INSIDE a double-quoted string. Bash runs it there, so its BODY is
  // a command context - but the quoted text around it is an argument to the outer command,
  // not a new statement. An earlier revision split the string at the substitution, which
  // restarted the segment mid-text and resolved the next word as a command name: that turned
  // `git commit -m "fix(x) rm -rf handling"` and `echo "$(date) rm -rf /tmp/build finished"`
  // into denials. Extracting the body instead keeps the outer segment intact.
  let subDepth = 0;
  let subBuf = '';
  let backtickOpen = false;
  const extracted = [];
  const flush = () => {
    if (segment.trim()) segments.push(segment.trim());
    segment = '';
  };
  for (let idx = 0; idx < cmd.length; idx += 1) {
    const ch = cmd[idx];
    if (quote) {
      // Command substitution is performed inside DOUBLE quotes, so it opens a new command
      // there and must split. Inside SINGLE quotes it is literal text and must not -- that
      // is what keeps a documentation commit message with a backtick pair from being
      // blocked. The quote state is deliberately left intact across the split: the inner
      // command is exposed as its own segment while the outer string keeps its context.
      if (quote === '"' && !escaped) {
        if (subDepth > 0 || backtickOpen) {
          // Inside the substitution body: accumulate separately, and close on the matching
          // delimiter. An unmatched `)` in ordinary prose never reaches here, because
          // subDepth only rises on a `$(` this scanner saw.
          if (ch === '$' && cmd[idx + 1] === '(') { subBuf += '$('; subDepth += 1; idx += 1; continue; }
          if (ch === ')' && subDepth > 0) {
            subDepth -= 1;
            if (subDepth === 0) { if (subBuf.trim()) extracted.push(subBuf.trim()); subBuf = ''; }
            else subBuf += ch;
            continue;
          }
          if (ch === '`' && backtickOpen) {
            backtickOpen = false;
            if (subBuf.trim()) extracted.push(subBuf.trim());
            subBuf = '';
            continue;
          }
          subBuf += ch;
          continue;
        }
        if (ch === '$' && cmd[idx + 1] === '(') { subDepth = 1; idx += 1; continue; }
        if (ch === '`') { backtickOpen = true; continue; }
      }
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
    // Unquoted backtick: the other spelling of `$( )`, which the paren separators below
    // already handle. Without this the inner command kept the outer command's argv[0].
    if (ch === '`') { flush(); continue; }
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
    if (ch === '&' && ampersandIsRedirect(cmd, idx, segment)) {
      segment += ch;
      continue;
    }
    if (/[;&|\n(){}]/.test(ch)) {
      flush();
      continue;
    }
    segment += ch;
  }
  flush();
  // An unterminated substitution still carries whatever was read: dropping it would let an
  // unbalanced `"$(rm -rf x` go unexamined.
  if (subBuf.trim()) extracted.push(subBuf.trim());
  return segments.concat(extracted);
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

// --- Bounds on the payload walk -------------------------------------------------------
//
// `commandTokensOne` and `shellPayloads` are mutually recursive, and `shellPayloads` restarts
// its scan at EVERY token index, so N nested `-c` shells produced ~2^N expansions. Measured
// before this bound, on a completely BENIGN command (nested shells in front of a harmless
// print): 67 chars 121 ms, 91 chars 854 ms, 103 chars 3056 ms, 115 chars 11.4 s -- against a
// 15 s hook timeout on every wired runtime. A hook the runtime kills renders no decision, so
// the guard fails open: the hardening becomes the bypass, for the third recorded time here.
//
// The ALLOW path is the worst case, which is why it is bounded first: a denial short-circuits
// at the first matching check, while an allow runs all four to completion. No attacker is
// required -- an ordinary command with a few nested shells was one nesting away from
// disabling the guard during normal work.
//
// Depth carries the exponent, so the depth cap is the fix and the budget is the backstop.
// MAX_PAYLOAD_DEPTH 3 sits above real usage: `bash -c "sh -c '...'"` is depth 2.
const MAX_PAYLOAD_DEPTH = 3;
const WORK_BUDGET = 20000;
const MAX_INPUT_CHARS = 20000;
// Payload fan-out per tokenizer level. `shellPayloads` emits one payload per shell/eval token
// in a segment, so a long chain of them is quadratic in work and memory even at depth 1.
// 32 is far above any real command: a shell invocation nests a handful of layers, not dozens.
const MAX_PAYLOADS_PER_LEVEL = 32;

// Per-invocation walk state. A hook process handles ONE command, so a module-level record is
// the whole lifetime. `unresolved` starts FALSE and is set only by a path that gave up: it
// answers "did I account for this input?", never "did I happen to see no hazard".
const WALK = { budget: 0, unresolved: false };

// Linear fallback for input the walk did not fully account for. Deliberately NOT "re-run each
// check at every token position": that is O(n^2), measured at ~18 s on 32k tokens, which would
// make the escape hatch slower than the code it replaces and rebuild the DoS one layer down.
// Instead: ONE pass collecting which command names and which matching flags appear anywhere,
// then a fixed number of set lookups. Order-insensitive, so it over-approximates -- acceptable
// because it runs only on input that could not be parsed, and it is the difference between
// "I could not read this, so I checked coarsely" and "I could not read this, so I allowed it".
function widenedFindingLabel(cmd) {
  // Decode the same layers the precise walk decodes. Reading the raw string here let
  // `r\m -rf x` and `$'\x72\x6d' -rf x` through past the length cap, where the precise walk
  // would have caught them: a backstop that reads a narrower language than the path it backs
  // up has a blind spot exactly where it is needed.
  // The backslash pass is the third decoder the precise walk applies (through the
  // tokenizer's unescape), and without it `r\m -rf x` reads as the literal token `r\m`.
  // Dropping every backslash is coarser than the tokenizer - it ignores quoting context -
  // which is the right direction for a backstop: it can only widen what is examined.
  const decoded = expandAnsiCQuotes(removeBashLineContinuations(cmd)).replace(/\\(.)/g, '$1');
  // Statement-scoped and ORDER-AWARE. The first version collected names and flags into two
  // global sets, so a flag belonging to one command satisfied a rule about another:
  // `grep -rn "rm" src/...` matched the rm rule, with `-rn` grep's and `rm` grep's search
  // pattern. Here a rule matches only when the flag appears AFTER the command name inside
  // the same statement. One backward sweep per statement builds the suffix answers, then one
  // forward sweep asks them - linear, with no slice in the loop.
  for (const statement of decoded.split(/[;&|\n]+/)) {
    const tokens = statement.split(/[\s(){}'"`]+/).filter(Boolean);
    if (!tokens.length) continue;
    const n = tokens.length;
    const recursiveAfter = new Array(n + 1).fill(false);
    const hardAfter = new Array(n + 1).fill(false);
    const forceAfter = new Array(n + 1).fill(false);
    const cleanTargetAfter = new Array(n + 1).fill(false);
    const riAfter = new Array(n + 1).fill(false);
    const resetAfter = new Array(n + 1).fill(false);
    const cleanAfter = new Array(n + 1).fill(false);
    for (let i = n - 1; i >= 0; i -= 1) {
      const t = tokens[i];
      const args = [t];
      recursiveAfter[i] = recursiveAfter[i + 1] || hasRmRecursiveFlag(args);
      hardAfter[i] = hardAfter[i + 1] || t === '--hard';
      forceAfter[i] = forceAfter[i + 1] || t === '--force' || /^-[A-Za-z]*f[A-Za-z]*$/.test(t);
      cleanTargetAfter[i] = cleanTargetAfter[i + 1] || t === '--ignored'
        || t === '--exclude-standard' || /^-[A-Za-z]*[dxX][A-Za-z]*$/.test(t);
      riAfter[i] = riAfter[i + 1] || hasRemoveItemRecursiveFlag(args);
      resetAfter[i] = resetAfter[i + 1] || t === 'reset';
      cleanAfter[i] = cleanAfter[i + 1] || t === 'clean';
    }
    const REMOVE_ITEM = new Set(['remove-item', 'ri', 'del', 'erase', 'rd', 'rmdir', 'rm']);
    for (let i = 0; i < n; i += 1) {
      const name = commandName(tokens[i]);
      if (name === 'git' && resetAfter[i + 1] && hardAfter[i + 1]) return 'git-reset-hard';
      if (name === 'git' && cleanAfter[i + 1] && forceAfter[i + 1] && cleanTargetAfter[i + 1]) {
        return 'git-clean-force';
      }
      if (name === 'rm' && recursiveAfter[i + 1]) return 'rm-recursive';
      if (REMOVE_ITEM.has(name) && riAfter[i + 1]) return 'powershell-remove-item-recurse';
    }
  }
  return null;
}

function commandTokensOne(cmd, unescapeUnquoted, depth = 0) {
  if (cmd.length > MAX_INPUT_CHARS) { WALK.unresolved = true; return []; }
  if (depth > MAX_PAYLOAD_DEPTH) { WALK.unresolved = true; return []; }
  if (WALK.budget <= 0) { WALK.unresolved = true; return []; }
  WALK.budget -= 1;
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
  // Each explicit shell starts a new parsing layer. A payload single-quoted for the outer shell
  // can contain a backslash-newline or ANSI-C quote that only the INNER bash/sh realizes.
  const payloads = segments.flatMap((segment) => shellPayloads(segment, unescapeUnquoted));
  if (payloads.length > MAX_PAYLOADS_PER_LEVEL) {
    WALK.unresolved = true;
    payloads.length = MAX_PAYLOADS_PER_LEVEL;
  }
  const wrapped = [];
  for (const payload of payloads) {
    // Charge by LENGTH, not by call: the cost and the memory are both in the payload text,
    // and a handful of very long payloads is as expensive as many short ones.
    const cost = 1 + (payload.text.length >> 6);
    if (WALK.budget < cost) { WALK.unresolved = true; break; }
    WALK.budget -= cost;
    for (const t of commandTokensOne(payload.text, payload.bashSemantics, depth + 1)) {
      wrapped.push(t);
    }
  }
  return tokens.concat(wrapped);
}

// Memoised across the four BLOCKED checks. Each check re-ran the whole walk, and the two views
// doubled it again -- eight full traversals per command. On the allow path, where nothing
// short-circuits, that multiplier was most of the cost.
let cachedKey = null;
let cachedTokens = null;

function commandTokens(cmd, bashSemantics = false) {
  const key = (bashSemantics ? '1|' : '0|') + cmd;
  if (cachedKey === key) return cachedTokens;
  WALK.unresolved = false;
  // Per-VIEW budget. Sharing one drained on the raw view and then returned [] for the bash
  // view at entry - silently discarding the only view that unescapes, so `r\m -rf x` came
  // back as a fast, confident allow. A bound must narrow what is examined visibly, never
  // delete a whole reading.
  WALK.budget = WORK_BUDGET;
  const raw = commandTokensOne(cmd, false, 0);
  // Preserve the generic/PowerShell view and add a Bash-realized view; the union keeps Bash
  // quote removal from hiding Windows-style paths while still exposing the escaped spellings.
  let all = raw;
  if (bashSemantics) {
    WALK.budget = WORK_BUDGET;
    all = raw.concat(commandTokensOne(cmd, true, 0));
  }
  cachedKey = key;
  cachedTokens = all;
  return all;
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


// POSIX Shell & Utilities 2.9.1 closes the production that sits in front of a command name:
//
//   simple_command := cmd_prefix* [ cmd_word cmd_suffix* ]
//   cmd_prefix     := io_redirect | ASSIGNMENT_WORD
//
// plus bash's reserved words and `!`. That set is fixed BY THE LANGUAGE, which is why this
// half is a positive grammar rather than another deny-list -- unlike WRAPPERS above, which
// is open-ended and stays a deny-list. Every bypass this closes was the same mechanical
// failure: tokens[0] was a prefix construct, so the real command was never examined.
//
// The grammar itself lives in `shell-prefix.mjs` because the git resolver needs exactly the
// same answers about it; what stays here is the alternation with the wrapper table below.

function unwrapCommand(tokens) {
  let i = 0;
  // The prefix walker and the wrapper table must ALTERNATE to a fixed point, not replace one
  // another: `then env FOO=1 nohup rm -rf x` is prefix, wrapper, prefix, wrapper. A first
  // prototype that swapped the table for the walker regressed `env rm -rf` and `nohup rm -rf`
  // from deny to allow -- the exact "a new component re-loses its neighbour's capability"
  // shape recorded in lessons.md 2026-08-23. The round cap makes non-termination impossible.
  for (let round = 0; round < 16; round += 1) {
    const next = skipCommandPrefix(tokens, i);
    if (next === i) break;
    i = next;
  }
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
        // Option names are CASE-SENSITIVE, and lowercasing here made the table unable to
        // express its own contents: in xargs `-I` takes a separate replace-string while
        // `-i` takes only an attached one, and `-L`/`-l`, `-P`/`-p`, `-E`/`-e` are likewise
        // distinct options. Folding case merged each pair, so whichever spelling was listed
        // decided both - and getting it wrong is a bypass in either direction (over-consume
        // and the command name is skipped; under-consume and the option's value is resolved
        // as the command). The wrapper NAME stays case-insensitive, because that is a
        // filename and Windows treats those case-insensitively.
        const opt = raw.split('=')[0];
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
  // A wrapper may be followed by another prefix run (`nohup FOO=1 rm -rf x`).
  if (i !== 0) {
    for (let round = 0; round < 16; round += 1) {
      const next = skipCommandPrefix(tokens, i);
      if (next === i) break;
      i = next;
    }
  }
  return tokens.slice(i);
}

function hasRmRecursiveFlag(args) {
  // A single-dash bundle of letters containing r/R is a recursive rm flag at any length
  // (the prior arg.length<=5 cap let `rm -rfvvv` through). `--recursive` starts with two dashes,
  // so the regex never matches it here, and a non-flag path argument never starts with a single dash.
  return args.some((arg) => arg === '--recursive' || /^-[A-Za-z]*[rR][A-Za-z]*$/.test(arg));
}

// PowerShell switch parameters accept an optional bound value: `-Recurse`, `-Recurse:$true`,
// `-Recurse:$false`. This is parameter BINDING, not a grammar difference, so it needs no
// separate segmenter - only that the switch name may carry a `:value` suffix. `-Recurse:$false`
// is the switch turned OFF, so denying it would be a false block on an explicit opt-out.
// The pattern is a fixed prefix chain with no ambiguous repetition before the anchor: the
// ReDoS shape this repo recorded twice does not apply (see lessons.md 2026-08-22).
function hasRemoveItemRecursiveFlag(args) {
  // `-Recurse: $false` is legal binding syntax with the value in the next token, so a switch
  // ending in `:` takes the following word as its bound value.
  const joined = [];
  for (let i = 0; i < args.length; i += 1) {
    if (args[i].endsWith(':') && i + 1 < args.length) {
      joined.push(args[i] + args[i + 1]);
      i += 1;
    } else joined.push(args[i]);
  }
  return joined.some((arg) => {
    const m = /^-(r(?:e(?:c(?:u(?:r(?:s(?:e)?)?)?)?)?)?)(?::(.*))?$/i.exec(arg);
    if (!m) return false;
    if (m[2] === undefined) return true;                 // bare switch
    return !/^\s*\$?(?:false|0|null)\s*$/i.test(m[2]);   // set unless bound to a falsy value
  });
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
  emitHookResult({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: msg,
    },
    systemMessage: `🛑 destructive-command-guard: ${msg}`,
  }, 'PreToolUse');
}

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { /* fail open */ }
const cmd = String(input?.toolInput?.command || input?.tool_input?.command || '');
const toolName = String(input?.toolName || input?.tool_name || '');
const bashSemantics = toolName === 'Bash' || toolName === 'run_terminal_command';

for (const finding of BLOCKED) {
  if (finding.check(cmd, bashSemantics)) {
    deny(finding);
    process.exit(0);
  }
}

// The walk gave up somewhere: a depth cap, an exhausted budget, or an over-long input. It must
// not report clean on the strength of a parse it did not finish. Widen once, linearly.
if (WALK.unresolved) {
  const label = widenedFindingLabel(cmd);
  const finding = label ? BLOCKED.find((f) => f.label === label) : null;
  if (finding) {
    deny({
      label: finding.label,
      reason: finding.reason
        + ' (matched by a widened scan: this command is longer or more deeply nested than the'
        + ' guard parses, so it was checked coarsely rather than reported clean.)',
    });
    process.exit(0);
  }
}

process.exit(0);
