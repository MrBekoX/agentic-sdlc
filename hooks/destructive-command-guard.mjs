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
// Also read the way the programs themselves read them: unique long-option prefixes
// (`rm --rec`, `git reset --ha`, `git clean --fo`), `clean.requireForce=false` (inline, from the
// environment, or stored), git aliases (inline `-c alias.x=...` and stored, `!` aliases included,
// through git-invocation.mjs), `env -S`, brace expansion, `exec -a`, here-strings, a here-document
// fed to a shell, and PowerShell's `iex`, dot-sourcing, `-Command` prefixes, `-EncodedCommand`
// and backtick escapes. A here-document body that nothing executes is data, not a command.
//
// Two halves with different guarantees. The cmd_prefix set is CLOSED by the shell grammar
// (POSIX 2.9.1 plus bash's reserved-word list), so it is a positive grammar and complete.
// The wrapper table (shared with the git resolver in git-invocation.mjs) is OPEN-ENDED and stays
// a deny-list: there is no specification that bounds "programs that run another program", so a
// wrapper not in the table is a gap, not a bug in the walker. Do not read the parity check as
// evidence that the table is complete.
//
// NOT covered, by design: other destructive verbs (find -delete, shred, truncate -s 0, dd of=,
// >-redirect) and runtime shell indirection that is statically undecidable (eval "$(...)",
// a=rm;$a, rm$IFS-rf) — the class the shell resolves after this hook has already decided.
// The permission prompt remains the primary control; this guard only catches the common cases.
import { readStdin } from './secret-patterns.mjs';
import { expandAnsiCQuotes } from './shell-quoting.mjs';
import { isAssignmentWord } from './shell-prefix.mjs';
import { emitHookResult } from './hook-output.mjs';
import { runGit } from './git-exec.mjs';
import {
  commandCwd, resolveGitCommands, resolveTargetCwd, unwrapCommand, shellPayloadAt, shortCluster,
  exactHeredocShape, powershellCommentRanges, powershellHereStringRanges,
} from './git-invocation.mjs';
import { scanShell } from './shell-quoting.mjs';

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
  {
    label: 'cmd-remove-recursive',
    check: hasCmdRecursiveRemove,
    reason: 'rd, rmdir, del or erase with /s deletes a whole folder tree.',
  },
];

// cmd.exe's own delete commands: `rd /s` removes a folder tree, `del /s` deletes matching files in
// every subfolder. A bare `rd build` or `del file` is not recursive.
const CMD_REMOVE = new Set(['rd', 'rmdir', 'del', 'erase']);

// cmd.exe escapes with `^` outside double quotes: `r^d` is `rd`, `^&` a literal `&`. The payload is
// read with the carets removed. Inside quotes a caret stays, but the tokenizer has already removed
// the quotes, so it is removed there too: that can only make a payload look MORE like a command.
function stripCmdCarets(text) {
  return text.replace(/\^(.?)/g, '$1');
}

// `/s` alone or in a switch run such as `/s/q`, `/q/s` or `/s/a:h`, any case, carets removed. Git
// Bash users write `//s`, because its path conversion would turn a lone `/s` into a path.
// One left-to-right pass over the switch run. The regex it replaces had a starred group on both
// sides of the `/s` it looked for, so a long run that failed at its last character backtracked
// quadratically - reachable through the widened scan, which reads tokens of any length.
function isSubtreeSwitchRun(raw) {
  const t = stripCmdCarets(String(raw)).toLowerCase();
  if (!t.startsWith('/')) return false;
  let found = false;
  let i = 0;
  while (i < t.length) {
    if (t[i] !== '/') return false;
    i += 1;
    if (t[i] === '/') i += 1;
    const c = t[i];
    if (!c || !((c >= 'a' && c <= 'z') || c === '?')) return false;
    i += 1;
    if (t[i] === ':') {                                   // `/a:h`: a value-carrying switch
      i += 1;
      while (i < t.length && ((t[i] >= 'a' && t[i] <= 'z') || t[i] === '-')) i += 1;
      continue;
    }
    if (c === 's') found = true;
  }
  return found;
}

function hasCmdSubtreeSwitch(args) {
  return args.some(isSubtreeSwitchRun);
}

// cmd.exe by name, by the variable that names it, or glued to its switch (`cmd/c`).
const CMD_NAMES = new Set(['cmd', '%comspec%', '$env:comspec']);
const CMD_GLUED_RUN = /^(?:.*[\\/])?cmd(?:\.exe)?\/{1,2}[ckr]$/i;

// The payload of `cmd [switches] /c|/k|/r <command>` (also `//c`, and `/c` glued to the command, as in
// `/crd /s x` or `/c"rd /s x"` once the quotes are removed), read without its `^` escapes.
function cmdPayload(tokens, i) {
  let start = -1;
  let head = '';
  if (CMD_GLUED_RUN.test(stripCmdCarets(String(tokens[i])))) {
    start = i + 1;
  } else {
    for (let j = i + 1; j < tokens.length; j += 1) {
      const m = /^\/{1,2}([ckr])(.*)$/i.exec(stripCmdCarets(tokens[j]));
      if (m) {
        head = m[2];
        start = j + 1;
        break;
      }
    }
  }
  if (start < 0) return '';
  return stripCmdCarets([head, ...tokens.slice(start)].join(' ').trim());
}

// A cmd.exe tree delete in one segment: `@` and `call` in front still run it, and the switches may be
// glued to the name (`rd/s/q x`).
function isCmdTreeDelete(tokens) {
  let i = 0;
  while (i < tokens.length && /^(?:@|call)$/i.test(stripCmdCarets(String(tokens[i])))) i += 1;
  if (i >= tokens.length) return false;
  const first = stripCmdCarets(String(tokens[i])).replace(/^@/, '');
  const glued = /^(?:.*\\)?(rd|rmdir|del|erase)((?:\/{1,2}[a-z?](?::[a-z-]*)?)+)$/i.exec(first);
  if (glued) return hasCmdSubtreeSwitch([glued[2]]) || hasCmdSubtreeSwitch(tokens.slice(i + 1));
  return CMD_REMOVE.has(commandName(first)) && hasCmdSubtreeSwitch(tokens.slice(i + 1));
}

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

// True when an `&` belongs to a redirect operator rather than being a separator: `2>&1`, `<&0`,
// `&>log`, `&>>log`. Splitting on it left a segment starting with a bare fd digit, so the command
// after it was never resolved. An ESCAPED `>` is literal text, not an operator: without that
// distinction `echo a\> & rm -rf x` read as a redirect and the `&` stopped separating - the parity
// regression git-invocation.mjs had already fixed. Takes scalars carried beside the segment, never
// the segment itself (indexing a `+=`-built string flattens it, see lessons.md 2026-09-21).
function ampersandIsRedirect(next, lastNonSpace, lastWasEscaped) {
  if (next === '>') return true;                       // &> / &>>
  if (lastNonSpace !== '>' && lastNonSpace !== '<') return false;
  return !lastWasEscaped;
}

// Bash brace expansion: `{rm,-rf,x}` is the three words `rm -rf x`, and `rm -{r,f}` is `rm -r -f`.
// The splitter keeps such a word whole (instead of splitting at its braces) and the bash view
// expands it after tokenizing. A brace word needs an unquoted comma or `..` at its own level;
// `{ cmd; }` (a group: blank after `{`) and `${x}` are not brace words. Returns the index of the
// closing brace, or -(stop index) - 1 when this is not a brace word, so the caller never rescans
// the same word (linear).
function braceWordEnd(cmd, start) {
  let depth = 0;
  let list = false;
  for (let k = start; k < cmd.length; k += 1) {
    const c = cmd[k];
    if (c === '\\') { k += 1; continue; }
    // A double quote, `$` or a backtick can carry an escaped quote or a command substitution that
    // this linear scan reads wrongly: `indexOf('"')` stopped at an escaped `\"`, swallowing the
    // statements after the brace word, and a `"$(...)"` part was added raw so substitution
    // extraction never saw it (R4-2). Treat the candidate as NOT a brace word and let the normal
    // segmenter, which models escapes and extracts substitutions, read it instead.
    if (c === '"' || c === '$' || c === '`') return -k - 1;
    if (c === "'") {
      const close = cmd.indexOf("'", k + 1);
      if (close < 0) return -k - 1;
      k = close;
      continue;
    }
    if (c === ' ' || c === '\t' || c === '\n' || c === ';' || c === '&' || c === '|' || c === '<'
      || c === '>' || c === '(' || c === ')') return -k - 1;
    if (c === '{') depth += 1;
    else if (c === '}') {
      depth -= 1;
      if (depth === 0) return list ? k : -k - 1;
    } else if (depth === 1 && (c === ',' || (c === '.' && cmd[k + 1] === '.'))) list = true;
  }
  return -cmd.length - 1;
}

const MAX_BRACE_WORDS = 64;

// Expand one word's brace lists (comma lists only; a `..` sequence is left as written). One pass
// with a stack finds an innermost list with a comma at its own level; that list is expanded and the
// results are expanded again, until no list is left or the word count reaches the cap.
function expandBraces(word) {
  if (!word.includes('{') || !word.includes(',')) return [word];
  let work = [word];
  for (let round = 0; round < 16; round += 1) {
    const next = [];
    let changed = false;
    for (const w of work) {
      const group = findBraceList(w);
      if (!group) { next.push(w); continue; }
      // Count before building: one list of thousands of alternatives must not be materialised.
      if (next.length + group.commas.length + 1 > MAX_BRACE_WORDS) { WALK.unresolved = true; return [word]; }
      changed = true;
      const prefix = w.slice(0, group.start);
      const suffix = w.slice(group.end + 1);
      let from = group.start + 1;
      for (const comma of [...group.commas, group.end]) {
        next.push(prefix + w.slice(from, comma) + suffix);
        from = comma + 1;
      }
    }
    if (next.length > MAX_BRACE_WORDS) { WALK.unresolved = true; return [word]; }
    work = next;
    if (!changed) break;
  }
  return work;
}

function findBraceList(word) {
  const stack = [];
  for (let k = 0; k < word.length; k += 1) {
    const c = word[k];
    if (c === '{' && word[k - 1] !== '$') stack.push({ start: k, commas: [] });
    else if (c === ',' && stack.length) stack[stack.length - 1].commas.push(k);
    else if (c === '}' && stack.length) {
      const open = stack.pop();
      if (open.commas.length) return { start: open.start, end: k, commas: open.commas };
    }
  }
  return null;
}

function rawCommandSegments(cmd, protectEscapedSeparators = false, nest = 0) {
  const segments = [];
  let segment = '';
  let quote = null;
  let escaped = false;
  // Carried beside `segment` for the redirect test (see ampersandIsRedirect).
  let lastNonSpace = '';
  let lastWasEscaped = false;
  let backslashRun = 0;
  let noBraceBefore = -1;
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
  const add = (ch) => {
    segment += ch;
    if (ch !== ' ' && ch !== '\t') {
      lastNonSpace = ch;
      lastWasEscaped = backslashRun % 2 === 1;
    }
    backslashRun = ch === '\\' ? backslashRun + 1 : 0;
  };
  const flush = () => {
    if (segment.trim()) segments.push(segment.trim());
    segment = '';
    lastNonSpace = '';
    lastWasEscaped = false;
    backslashRun = 0;
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
      add(ch);
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
      add(ch);
      escaped = false;
      continue;
    }
    if (protectEscapedSeparators && ch === '\\') {
      add(ch);
      escaped = true;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      add(ch);
      continue;
    }
    if (ch === '&' && ampersandIsRedirect(cmd[idx + 1], lastNonSpace, lastWasEscaped)) {
      add(ch);
      continue;
    }
    if (protectEscapedSeparators && ch === '{' && idx > noBraceBefore && cmd[idx - 1] !== '$') {
      const close = braceWordEnd(cmd, idx);
      if (close > idx) {
        for (let k = idx; k <= close; k += 1) add(cmd[k]);
        idx = close;
        continue;
      }
      noBraceBefore = -close - 1;
    }
    if (/[;&|\n(){}]/.test(ch)) {
      flush();
      continue;
    }
    add(ch);
  }
  flush();
  // An unterminated substitution still carries whatever was read: dropping it would let an
  // unbalanced `"$(rm -rf x` go unexamined.
  if (subBuf.trim()) extracted.push(subBuf.trim());
  // A substitution body is a command line of its own, so it is segmented again:
  // `"$(true; rm -rf x)"` runs both statements, and the second is not the body's first word.
  if (nest >= 8) {
    if (extracted.length) WALK.unresolved = true;
    return segments.concat(extracted);
  }
  return segments.concat(extracted.flatMap((body) =>
    rawCommandSegments(body, protectEscapedSeparators, nest + 1)));
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

// PowerShell's escape character is the backtick: outside single quotes `` `X `` is the character X
// (`` Remove-It`em `` runs Remove-Item), and a backtick before a newline continues the line. An
// escaped quote is replaced by `_` so it cannot open a string the shell never opened.
function psUnescape(text) {
  let out = '';
  let quote = null;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (quote === "'") {
      out += c;
      if (c === "'") quote = null;
      continue;
    }
    if (c === '`' && i + 1 < text.length) {
      const n = text[i + 1];
      i += 1;
      if (n === '\n') continue;
      if (n === '\r' && text[i + 1] === '\n') { i += 1; continue; }
      out += n === '"' || n === "'" ? '_' : n;
      continue;
    }
    if (c === "'" && quote === null) quote = "'";
    else if (c === '"') quote = quote === '"' ? null : '"';
    out += c;
  }
  return out;
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

// Per-invocation git context: the directory the command runs in, the git resolver's view of the
// command (aliases expanded), and stored `clean.requireForce` answers. `lookups` bounds the config
// reads: a repository can make each one stall (a FIFO include), so all of them share one count and
// one deadline, and an answer that is not known in time counts as switched off (R2-CG-9).
const GIT_CONTEXT = { cwd: process.cwd(), resolved: null, requireForce: new Map(), lookups: 0, deadline: 0 };
const MAX_CONFIG_LOOKUPS = 4;
const CONFIG_LOOKUP_BUDGET_MS = 2500;

// Unique long-option prefixes (GNU getopt_long and git's parse-options accept them):
// `--rec`/`--r` is `--recursive`, `--ha`/`--h` is `git reset --hard`, `--fo`/`--f` is
// `git clean --force`. Each is the only option of its program starting with that letter.
function isLongPrefixOf(arg, option) {
  return arg.length >= 3 && option.startsWith(arg);
}

function isHardOption(arg) {
  return isLongPrefixOf(arg, '--hard');
}

// Single-dash letter clusters are read with `shortCluster` (one linear pass). The regexes they
// replace (`^-[A-Za-z]*f[A-Za-z]*$` and kin) backtracked quadratically on a long cluster that
// fails at its last character, and the widened scan applies them to tokens of any length (R2-CG-13).
function isCleanForceOption(arg) {
  return isLongPrefixOf(arg, '--force') || shortCluster(arg, 'f');
}

function isCleanTargetOption(arg) {
  return arg === '--ignored' || arg === '--exclude-standard' || shortCluster(arg, 'dxX');
}

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
  // forward sweep asks them - linear, with no slice in the loop. A comma also separates words
  // here, so an unexpanded brace word (`{rm,-rf,x}`) is read as its parts.
  for (const statement of decoded.split(/[;&|\n]+/)) {
    const tokens = statement.split(/[\s(){}'"`,]+/).filter(Boolean);
    if (!tokens.length) continue;
    const n = tokens.length;
    const recursiveAfter = new Array(n + 1).fill(false);
    const hardAfter = new Array(n + 1).fill(false);
    const forceAfter = new Array(n + 1).fill(false);
    const cleanTargetAfter = new Array(n + 1).fill(false);
    const riAfter = new Array(n + 1).fill(false);
    const resetAfter = new Array(n + 1).fill(false);
    const cleanAfter = new Array(n + 1).fill(false);
    const subtreeAfter = new Array(n + 1).fill(false);
    for (let i = n - 1; i >= 0; i -= 1) {
      const t = tokens[i];
      const args = [t];
      recursiveAfter[i] = recursiveAfter[i + 1] || hasRmRecursiveFlag(args);
      hardAfter[i] = hardAfter[i + 1] || isHardOption(t);
      forceAfter[i] = forceAfter[i + 1] || isCleanForceOption(t);
      cleanTargetAfter[i] = cleanTargetAfter[i + 1] || isCleanTargetOption(t);
      riAfter[i] = riAfter[i + 1] || hasRemoveItemRecursiveFlag(args);
      resetAfter[i] = resetAfter[i + 1] || t === 'reset';
      cleanAfter[i] = cleanAfter[i + 1] || t === 'clean';
      subtreeAfter[i] = subtreeAfter[i + 1] || hasCmdSubtreeSwitch(args);
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
      if (CMD_REMOVE.has(stripCmdCarets(name)) && subtreeAfter[i + 1]) return 'cmd-remove-recursive';
    }
  }
  return null;
}

// R3-CG-1 / R3-CG-2: what each view reads.
//   * The command exactly as written - base f430715's reading, here-document body lines included.
//     Nothing is ever removed from this reading: two attempts at dropping "data" bodies had bypasses.
//   * In addition, when the command has comments or here-documents: the same text with comments
//     blanked and here-document bodies removed. That reading finds what an odd quote hid from the
//     first one - `# don't forget` followed by a delete, or a body line `We're shipping` followed by
//     a delete after the closing delimiter (H0/H1). The union can only add findings.
//   * A whole command of one exact here-document shape (git-invocation.mjs `exactHeredocShape`) is
//     read as its opener line only: the body is a file's contents or a commit message. Never for
//     PowerShell, where `<<` is not a here-document.
function rewriteRanges(text, blanks, removes) {
  const ranges = [
    ...blanks.map(([a, b]) => ({ a, b, remove: false })),
    ...removes.map(([a, b]) => ({ a, b, remove: true })),
  ].sort((x, y) => x.a - y.a);
  let out = '';
  let at = 0;
  for (const { a, b, remove } of ranges) {
    if (b <= at) continue;
    const from = Math.max(a, at);
    out += text.slice(at, from);
    if (!remove) out += text.slice(from, b).replace(/[^\n]/g, ' ');
    at = b;
  }
  return out + text.slice(at);
}

// The tool's raw command string, the only text an exact here-document shape may be judged on.
let RAW_COMMAND = null;

function commandVariants(cmd, view, depth = 0) {
  const powershell = view === 'ps' || TOOL === 'PowerShell';
  // The exact here-document shape is judged only on the tool's raw command (depth 0), as the git
  // resolver does. A nested payload's text comes out of a lossy decode (`\\` before a newline,
  // `\cJ` in ANSI-C quoting), so a delimiter line bash sees can merge into the line above in this
  // copy, the shape would match, and the lines after it would go unread (R5).
  // The same holds for a `!` alias text: it comes out of the resolver's tokenizer, not raw, so the
  // shape is judged only on text that IS the tool's own command string.
  if (!powershell && depth === 0 && cmd === RAW_COMMAND) {
    const shape = exactHeredocShape(cmd);
    if (shape) return [shape.opener];
  }
  const variants = [cmd];
  if (powershell) {
    if (cmd.includes('#')) {
      const comments = powershellCommentRanges(cmd);
      if (comments.length) variants.push(rewriteRanges(cmd, comments, []));
    }
    // R2-a: the command with its single-quoted here-strings blanked, so an apostrophe in a body no
    // longer pairs with the `'` of `@'` and hides the line after `'@`. The variants are a union.
    if (cmd.includes("@'")) {
      const bodies = powershellHereStringRanges(cmd);
      if (bodies.length) {
        const stripped = rewriteRanges(cmd, bodies, []);
        variants.push(stripped);
        if (stripped.includes('#')) {
          const comments = powershellCommentRanges(stripped);
          if (comments.length) variants.push(rewriteRanges(stripped, comments, []));
        }
      }
    }
  } else if (cmd.includes('#') || cmd.includes('<<')) {
    const lex = scanShell(cmd);
    if (lex.commentRanges.length || lex.bodyRanges.length) {
      variants.push(rewriteRanges(cmd, lex.commentRanges, lex.bodyRanges));
    }
  }
  return variants;
}

// The shared wrapper walk (git-invocation.mjs), with this view's word splitter for `env -S`.
// A `GIT_CONFIG_*` assignment naming requireForce in front of the command is remembered on the
// result: it can switch `git clean`'s force requirement off from the environment.
function unwrapForView(tokens, bash) {
  const { rest, consumed, unresolved } = unwrapCommand(tokens, {
    splitWords: (text) => tokenizePreservingQuotes(text, bash),
  });
  if (unresolved) WALK.unresolved = true;
  if (consumed.some((word) => isAssignmentWord(word)
      && /^GIT_CONFIG_(?:PARAMETERS|KEY_\d+)=.*requireforce/i.test(word))) {
    rest.requireForceFromEnv = true;
  }
  // R2-CG-11: an environment prefix that changes which config git reads makes a stored
  // `clean.requireForce` read from here meaningless for this call.
  if (consumed.some((word) => isAssignmentWord(word) && /^(?:GIT_[A-Z0-9_]+|HOME|XDG_CONFIG_HOME)=/.test(word))) {
    rest.configContextUnknown = true;
  }
  return rest;
}

function commandTokensOne(cmd, view, depth = 0) {
  if (cmd.length > MAX_INPUT_CHARS) { WALK.unresolved = true; return []; }
  if (depth > MAX_PAYLOAD_DEPTH) { WALK.unresolved = true; return []; }
  if (WALK.budget <= 0) { WALK.unresolved = true; return []; }
  WALK.budget -= 1;
  let all = [];
  // A payload is walked once per level, whichever variant shows it: the here-string and comment
  // variants repeat the same payloads, and walking each copy multiplied the cost per level (security
  // review of Round 2). The same payload text gives the same tokens, so the union is unchanged.
  const walked = new Set();
  for (const text of commandVariants(cmd, view, depth)) all = all.concat(tokensOfText(text, view, depth, walked));
  return all;
}

function tokensOfText(text, view, depth, walked = new Set()) {
  const bash = view === 'bash';
  const decoded = view === 'ps' ? psUnescape(text) : text;
  const source = bash ? expandAnsiCQuotes(removeBashLineContinuations(decoded)) : decoded;
  // Segment on UNQUOTED separators, then tokenize each segment with quote REMOVAL (not blanking).
  // A quoted command name still runs the command in a shell ("rm"/'rm'/r"m" all execute rm), so
  // unquoting per token — instead of erasing quoted spans before tokenizing — keeps the real
  // command name visible to the checks below while still treating a quoted argument blob
  // (echo "rm -rf x") as a single non-command token.
  const segments = rawCommandSegments(source, bash);
  const tokens = segments
    .map((segment) => tokenizePreservingQuotes(segment, bash))
    .map((items) => (bash ? items.flatMap(expandBraces) : items))
    .map((items) => unwrapForView(items, bash))
    .filter((items) => items.length);
  // Each explicit shell starts a new parsing layer. A payload single-quoted for the outer shell
  // can contain a backslash-newline or ANSI-C quote that only the INNER bash/sh realizes.
  const payloads = segments.flatMap((segment) => shellPayloads(segment, view));
  if (payloads.length > MAX_PAYLOADS_PER_LEVEL) {
    WALK.unresolved = true;
    payloads.length = MAX_PAYLOADS_PER_LEVEL;
  }
  const wrapped = [];
  for (const payload of payloads) {
    const key = payload.view + '\u0000' + payload.text;
    if (walked.has(key)) continue;
    walked.add(key);
    // Charge by LENGTH, not by call: the cost and the memory are both in the payload text,
    // and a handful of very long payloads is as expensive as many short ones.
    const cost = 1 + (payload.text.length >> 6);
    if (WALK.budget < cost) { WALK.unresolved = true; break; }
    WALK.budget -= cost;
    for (const t of commandTokensOne(payload.text, payload.view, depth + 1)) {
      wrapped.push(t);
    }
  }
  return tokens.concat(wrapped);
}

// Memoised across the BLOCKED checks. Each check re-ran the whole walk, and the views multiplied
// it again. On the allow path, where nothing short-circuits, that multiplier was most of the cost.
let cachedKey = null;
let cachedTokens = null;

function commandTokens(cmd, views) {
  const key = views.join(',') + '|' + cmd;
  if (cachedKey === key) return cachedTokens;
  WALK.unresolved = false;
  // Per-VIEW budget. Sharing one drained on the raw view and then returned [] for the bash
  // view at entry - silently discarding the only view that unescapes, so `r\m -rf x` came
  // back as a fast, confident allow. A bound must narrow what is examined visibly, never
  // delete a whole reading.
  // Every view is read and the union is checked: the generic view keeps Windows-style paths,
  // the Bash view exposes escaped spellings, the PowerShell view backtick escapes.
  let all = [];
  for (const view of views) {
    WALK.budget = WORK_BUDGET;
    all = all.concat(commandTokensOne(cmd, view, 0));
  }
  cachedKey = key;
  cachedTokens = all;
  return all;
}

function shellPayloads(segment, view) {
  const tokens = tokenizePreservingQuotes(segment, view === 'bash');
  const payloads = [];
  for (let i = 0; i < tokens.length; i += 1) {
    const name = commandName(tokens[i]);
    if (CMD_NAMES.has(name) || CMD_GLUED_RUN.test(stripCmdCarets(String(tokens[i])))) {
      const payload = cmdPayload(tokens, i);
      if (payload) payloads.push({ text: payload, view: 'raw' });
      continue;
    }
    // bash/sh/zsh/... -c [options] [--] (also -lc/-ce), here-strings, eval [--], su -c,
    // powershell/pwsh -Command and its prefixes, -EncodedCommand, iex / Invoke-Expression.
    const found = shellPayloadAt(tokens, i);
    if (found && found.unresolved) WALK.unresolved = true;
    if (found && found.text) payloads.push({ text: found.text, view: found.semantics === 'inherit' ? view : found.semantics });
  }
  return payloads;
}

function hasRmRecursiveFlag(args) {
  // A single-dash bundle of letters containing r/R is a recursive rm flag at any length
  // (the prior arg.length<=5 cap let `rm -rfvvv` through). `--recursive` and every unique prefix
  // of it (`--rec`, `--r`) is too: GNU rm has no other long option starting with `r`.
  return args.some((arg) => isLongPrefixOf(arg, '--recursive') || shortCluster(arg, 'rR'));
}

// PowerShell switch parameters accept an optional bound value: `-Recurse`, `-Recurse:$true`,
// `-Recurse:$false`. This is parameter BINDING, not a grammar difference, so it needs no
// separate segmenter - only that the switch name may carry a `:value` suffix. `-Recurse:$false`
// is the switch turned OFF, so denying it would be a false block on an explicit opt-out.
// The pattern is a fixed prefix chain with no ambiguous repetition before the anchor: the
// ReDoS shape this repo recorded twice does not apply (see lessons.md 2026-08-22).
const PS_FALSY = new Set(['false', '$false', '0', '$0', 'null', '$null']);

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
    // Set unless bound to a falsy value. Trim and look up, linear: the anchored `\s*` pattern this
    // replaces backtracked quadratically on a long run of blanks before a non-matching word.
    return !PS_FALSY.has(m[2].trim().toLowerCase());
  });
}

function hasRecursiveRm(cmd, views) {
  return commandTokens(cmd, views).some((tokens) => {
    const name = commandName(tokens[0]);
    return name === 'rm' && hasRmRecursiveFlag(tokens.slice(1));
  });
}

function hasCmdRecursiveRemove(cmd, views) {
  return commandTokens(cmd, views).some(isCmdTreeDelete);
}

function hasRecursiveRemoveItem(cmd, views) {
  const names = new Set(['remove-item', 'ri', 'del', 'erase', 'rd', 'rmdir', 'rm']);
  return commandTokens(cmd, views).some((tokens) => {
    const name = commandName(tokens[0]);
    return names.has(name) && hasRemoveItemRecursiveFlag(tokens.slice(1));
  });
}

// The git global options before the subcommand (git -C <dir>, git -c k=v, git --no-pager, ...),
// so `git -C /tmp reset --hard` is still matched. Returns { sub: [subcommand, ...args], config, dirs,
// contextKnown }. `--config-env=<key>=<ENV>` takes its value from the environment: recorded as
// `<key>=?`. `contextKnown` is false when an option changes which config git reads (R2-CG-11).
function gitParts(tokens) {
  const VALUE_OPTS = new Set(['-c', '-C', '--git-dir', '--work-tree', '--namespace', '--super-prefix', '--exec-path']);
  const fromEnv = (text) => {
    const j = String(text).indexOf('=');
    return (j < 0 ? String(text) : String(text).slice(0, j)) + '=?';
  };
  const config = [];
  const dirs = [];
  let contextKnown = true;
  let i = 1;
  while (i < tokens.length && tokens[i].startsWith('-')) {
    const raw = tokens[i];
    i += 1;
    if (raw.startsWith('-c') && raw.length > 2) { config.push(raw.slice(2)); continue; }
    if (raw.startsWith('-C') && raw.length > 2) { dirs.push(raw.slice(2)); continue; }
    const eq = raw.indexOf('=');
    const name = eq < 0 ? raw : raw.slice(0, eq);
    if (/^--(?:git-dir|work-tree|bare)$/.test(name)) contextKnown = false;
    if (name === '--config-env') {
      if (eq >= 0) config.push(fromEnv(raw.slice(eq + 1)));
      else if (i < tokens.length) { config.push(fromEnv(tokens[i])); i += 1; }
      continue;
    }
    if (eq >= 0 || !VALUE_OPTS.has(name) || i >= tokens.length) continue;
    if (name === '-c') config.push(tokens[i]);
    else if (name === '-C') dirs.push(tokens[i]);
    i += 1;
  }
  if (config.some((pair) => /^(?:include\.path|includeif\..*\.path|core\.worktree|core\.bare)(?:=|$)/i.test(String(pair)))) {
    contextKnown = false;
  }
  return { sub: tokens.slice(i), config, dirs, contextKnown };
}

const GIT_FALSE = new Set(['false', 'no', 'off', '0', '']);
function gitBooleanIsFalse(value) {
  return GIT_FALSE.has(String(value).trim().toLowerCase());
}

// `clean.requireForce=false` makes `git clean -dx` delete without `-f`. Read from inline `-c`
// pairs, a `GIT_CONFIG_*` environment prefix, and the repository's stored config. `--config-env`
// takes its value from the environment, so it counts as switched off.
function inlineRequireForceDisabled(configPairs) {
  for (const pair of configPairs) {
    const text = String(pair);
    const eq = text.indexOf('=');
    const key = (eq < 0 ? text : text.slice(0, eq)).toLowerCase();
    if (key !== 'clean.requireforce') continue;
    const value = eq < 0 ? 'true' : text.slice(eq + 1);
    if (value === '?' || gitBooleanIsFalse(value)) return true;
  }
  return false;
}

function requireForceDisabled(configPairs, cwd, fromEnv = false, contextKnown = true) {
  if (fromEnv || !contextKnown || inlineRequireForceDisabled(configPairs)) return true;
  if (!GIT_CONTEXT.requireForce.has(cwd)) {
    // Unknown (over the count, past the deadline, a stalled or failing read) counts as switched off.
    let disabled = true;
    const remaining = GIT_CONTEXT.deadline - Date.now();
    if (GIT_CONTEXT.lookups < MAX_CONFIG_LOOKUPS && remaining > 0) {
      GIT_CONTEXT.lookups += 1;
      try {
        const stored = String(runGit(['config', '--get', 'clean.requireForce'], {
          cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: Math.min(2000, remaining),
        })).trim();
        disabled = stored !== '' && gitBooleanIsFalse(stored);
      } catch (error) {
        disabled = !(error && error.status === 1 && !error.signal);     // exit 1: not set
      }
    }
    GIT_CONTEXT.requireForce.set(cwd, disabled);
  }
  return GIT_CONTEXT.requireForce.get(cwd);
}

function resolvedInvocations(subcommand) {
  return (GIT_CONTEXT.resolved?.invocations || []).filter((inv) => inv.subcommand === subcommand);
}

// `lookups` is false in the first phase: no check may start a subprocess there (R2-CG-9).
function hasGitResetHard(cmd, views, lookups = false) {
  const typed = commandTokens(cmd, views).some((tokens) => {
    if (commandName(tokens[0]) !== 'git') return false;
    const { sub } = gitParts(tokens);
    return sub[0] === 'reset' && sub.slice(1).some(isHardOption);
  });
  // Aliases (`git -c alias.nuke='reset --hard' nuke`, a stored `alias.nuke`) resolved by the git
  // resolver, which expands them the way git does.
  return typed || (lookups && resolvedInvocations('reset').some((inv) => inv.args.some(isHardOption)));
}

// `-n` / `--dry-run` (and its prefixes) deletes nothing. Only consulted when the force comes from
// configuration, so an explicit `-f` keeps the existing reading.
function isCleanDryRun(args) {
  return args.some((arg) => isLongPrefixOf(arg, '--dry-run') || shortCluster(arg, 'n'));
}

function cleanDeletes(args, config, cwd, fromEnv, contextKnown, lookups) {
  if (!args.some(isCleanTargetOption)) return false;
  if (args.some(isCleanForceOption)) return true;
  if (isCleanDryRun(args)) return false;
  // Inline and environment answers need no subprocess; a stored one waits for the second phase.
  if (!lookups) return fromEnv || !contextKnown || inlineRequireForceDisabled(config);
  return requireForceDisabled(config, cwd, fromEnv, contextKnown);
}

function hasGitCleanForce(cmd, views, lookups = false) {
  const typed = commandTokens(cmd, views).some((tokens) => {
    if (commandName(tokens[0]) !== 'git') return false;
    const { sub, config, dirs, contextKnown } = gitParts(tokens);
    if (sub[0] !== 'clean') return false;
    return cleanDeletes(sub.slice(1), config, resolveTargetCwd(GIT_CONTEXT.cwd, dirs),
      !!tokens.requireForceFromEnv, contextKnown && !tokens.configContextUnknown, lookups);
  });
  // Alias-derived calls only: the typed ones are read above, with their own context.
  return typed || (lookups && resolvedInvocations('clean').some((inv) => inv.depth > 0
    && cleanDeletes(inv.args, inv.inlineConfig.map(([k, v]) => k + '=' + v), inv.cwd, false,
      inv.readContextKnown, true)));
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
RAW_COMMAND = cmd;
const toolName = String(input?.toolName || input?.tool_name || '');
const TOOL = toolName;
const VIEWS = toolName === 'Bash' || toolName === 'run_terminal_command' ? ['raw', 'bash']
  : toolName === 'PowerShell' ? ['raw', 'ps'] : ['raw'];
GIT_CONTEXT.cwd = commandCwd(input);

function widenedDeny(text) {
  const label = widenedFindingLabel(text);
  const finding = label ? BLOCKED.find((f) => f.label === label) : null;
  if (!finding) return false;
  deny({
    label: finding.label,
    reason: finding.reason
      + ' (matched by a widened scan: this command is longer or more deeply nested than the'
      + ' guard parses, so it was checked coarsely rather than reported clean.)',
  });
  return true;
}

// Phase 1 (R2-CG-9): every check that needs no subprocess, first. A repository that stalls config
// reads can then delay a decision, but never ahead of a plain recursive delete on the same line.
for (const finding of BLOCKED) {
  if (finding.check(cmd, VIEWS, false)) {
    deny(finding);
    process.exit(0);
  }
}

// The walk gave up somewhere: a depth cap, an exhausted budget, or an over-long input. It must
// not report clean on the strength of a parse it did not finish. Widen once, linearly.
if (WALK.unresolved && widenedDeny(cmd)) process.exit(0);

// Phase 2: git config reads - aliases through the shared resolver, stored `clean.requireForce` -
// under one count and one deadline. Oversized input never reaches it: base sent that straight to
// the widened scan above, and the resolver must not be the slow path (R2-CG-8).
GIT_CONTEXT.deadline = Date.now() + CONFIG_LOOKUP_BUDGET_MS;
if (cmd.length <= MAX_INPUT_CHARS && /\bgit\b/i.test(expandAnsiCQuotes(cmd).replace(/['"\\]/g, ''))) {
  try {
    GIT_CONTEXT.resolved = resolveGitCommands(cmd, {
      cwd: GIT_CONTEXT.cwd, allowHeredocStrip: TOOL !== 'PowerShell',
    });
  } catch {
    GIT_CONTEXT.resolved = null;
  }
  const resolved = GIT_CONTEXT.resolved;
  // `!` git aliases are shell command lines (`git -c alias.x='!<delete> build' x`).
  for (const alias of resolved?.aliasShellTexts || []) {
    for (const finding of BLOCKED) {
      if (finding.check(alias, ['raw', 'bash'], false)) {
        deny(finding);
        process.exit(0);
      }
    }
    if (WALK.unresolved && widenedDeny(alias)) process.exit(0);
  }
  if (resolved?.workExhausted && widenedDeny(cmd)) process.exit(0);
}
for (const [label, check] of [['git-reset-hard', hasGitResetHard], ['git-clean-force', hasGitCleanForce]]) {
  if (check(cmd, VIEWS, true)) {
    deny(BLOCKED.find((f) => f.label === label));
    process.exit(0);
  }
}

process.exit(0);
