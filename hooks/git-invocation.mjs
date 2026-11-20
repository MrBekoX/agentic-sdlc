// Shared git-invocation analyzer for the command guards (scan-commit.mjs, branch-guard.mjs), and
// the shared command-resolution layer (wrapper table, shell payloads) that
// destructive-command-guard.mjs walks too.
//
// WHY THIS EXISTS
// Both guards used to gate their entire logic on a raw substring test:
//     if (!/\bgit\b[\s\S]*\bcommit\b/.test(cmd)) process.exit(0);
// A git ALIAS performs a real commit with that substring absent. `git config alias.ci 'commit -a'`
// then `git ci -m x` commits (including `-a`, which sweeps unstaged changes) while the guard sees
// no "commit" and skips every check. Setting the alias matched neither guard either, so one
// unguarded `git config` call silently disarmed both controls for the rest of the session.
// Verified against real git: alias chains resolve (deep -> ci -> commit), `-c alias.x=y` works
// inline, and `git config --get alias.<name>` reads the same table git itself uses.
//
// WHAT THIS CAN AND CANNOT SEE (honest coverage — read before trusting it)
// Resolvable here, because git resolves them itself from config we can read:
//   * `git config alias.*`, including chains and `!shell` aliases (shell functions inside them too)
//   * `-c alias.x=y` inline config, global options (`-C`, `--no-pager`, `--git-dir=`), wrappers
//     (`sudo`, `env` including `env -S`, `command`, `timeout`, ...), and quoted command names
//   * command substitution (`$(...)`, backticks, `<(...)`), shell functions defined on the line,
//     inner shell payloads (`bash -c`, `eval`, here-strings, a here-document fed to a shell)
// NOT resolvable at this layer, by construction:
//   * SHELL aliases and functions from ~/.bashrc / ~/.zshrc. Claude Code sources the user's shell
//     startup file and applies those aliases to every Bash command AFTER the hook has decided, so
//     `alias gc='git commit'` + `gc` reaches us as the string "gc" with nothing to resolve.
//   * $PATH shadowing, variable indirection (`C=commit; git $C`), base64-decode-pipe-to-sh.
// Those need enforcement below the alias layer (a repo `pre-commit` hook, or a state-based scan of
// what actually landed). This module makes the PreToolUse gate correct for everything git itself
// resolves; it does not make a pre-execution string gate authoritative, which is impossible.

import { runGit } from './git-exec.mjs';
import { resolve as resolvePath, parse as parsePath, sep } from 'node:path';
import { skipCommandPrefix, redirectOperatorLength } from './shell-prefix.mjs';
import { expandAnsiCQuotes, scanShell, expansionEnd } from './shell-quoting.mjs';

// The hooks' cheap probe (`scan-commit.mjs`, `branch-guard.mjs`): could this text run git? Used to
// count only the dropped statements that matter (R1-d), so a long payload without git stays quiet.
function mayNameGit(text) {
  return /\bgit\b/i.test(expandAnsiCQuotes(String(text ?? '')).replace(/['"\\]/g, ''));
}

// ---------------------------------------------------------------------------------------------
// Shared command resolution: ONE wrapper table and ONE payload reader for both resolvers.
//
// The destructive guard and this resolver used to keep separate wrapper tables. Each table was
// right about some wrappers and wrong about others, so `env -u HOME git push` reached neither git
// guard while `env -u HOME rm -rf` was denied, and `timeout --kill 1 30 rm -rf` reached neither.
// Every asymmetry was a bypass of the narrower side. destructive-command-guard.mjs now imports
// `unwrapCommandTokens` and `shellPayloadAt` from here, so the two cannot drift again.
//
// The table stays an open-ended DENY-LIST: no specification bounds "programs that run another
// program". What it must get right is each listed wrapper's own option grammar, because both
// errors are bypasses: over-consuming skips past the command name, under-consuming leaves an
// option's value where the command name should be.
// ---------------------------------------------------------------------------------------------

// The command-name form of a word: no directory, no surrounding quote, no `.exe`, lower case.
export function commandName(token) {
  const t = String(token ?? '').replace(/^["']|["']$/g, '');
  const i = Math.max(t.lastIndexOf('/'), t.lastIndexOf('\\'));
  return (i === -1 ? t : t.slice(i + 1)).toLowerCase().replace(/\.exe$/, '');
}

// The full name a long option resolves to: the exact name, else the one option the text is a
// unique prefix of (GNU getopt_long and git's parse-options both accept unique abbreviations:
// `timeout --kill 1`, `git commit --mess x`). Null when unknown or ambiguous.
export function resolveLongOption(table, name) {
  if (!name) return null;
  if (Object.prototype.hasOwnProperty.call(table, name)) return name;
  let found = null;
  for (const key of Object.keys(table)) {
    if (!key.startsWith(name)) continue;
    if (found !== null) return null;                    // ambiguous: the program itself refuses
    found = key;
  }
  return found;
}

// Per wrapper:
//   short     - option letters that take a value, attached (`-uHOME`) or as the next word
//   optShort  - option letters that take only an ATTACHED value (`xargs -i`, `sudo -h`)
//   long      - long options: 1 = value (attached with `=` or the next word), 2 = only with `=`,
//               0 = no value. Abbreviations resolve through `resolveLongOption`.
//   positional- operands the wrapper consumes before the command (timeout's DURATION)
//   assignments - NAME=value words may follow the options (sudo, env)
//   splitShort / splitLong - the option whose value is itself split into words (`env -S`)
// Verified against GNU coreutils 9.4, findutils xargs, sudo 1.9 `--help`.
const COMMAND_WRAPPERS = {
  sudo: {
    short: 'aCcDgpRrTtUu', optShort: 'h', assignments: true,
    long: {
      askpass: 0, 'auth-type': 1, background: 0, bell: 0, 'close-from': 1, 'login-class': 1,
      chdir: 1, 'preserve-env': 2, edit: 0, group: 1, 'set-home': 0, help: 0, host: 1, login: 0,
      'remove-timestamp': 0, 'reset-timestamp': 0, list: 0, 'non-interactive': 0,
      'preserve-groups': 0, prompt: 1, chroot: 1, role: 1, stdin: 0, shell: 0, type: 1,
      'command-timeout': 1, 'other-user': 1, user: 1, version: 0, validate: 0,
    },
  },
  doas: { short: 'aCu' },
  env: {
    short: 'uCSa', assignments: true, splitShort: 'S', splitLong: 'split-string',
    long: {
      'ignore-environment': 0, null: 0, unset: 1, chdir: 1, 'split-string': 1, argv0: 1,
      'block-signal': 2, 'default-signal': 2, 'ignore-signal': 2, 'list-signal-handling': 0,
      debug: 0, help: 0, version: 0,
    },
  },
  command: {},
  builtin: {},
  nohup: {},
  busybox: {},
  // PowerShell dot-sourcing runs the command that follows (`. Remove-Item ...`); in bash `.` reads
  // a file, so treating the next word as a command can only over-read.
  '.': {},
  setsid: { long: { ctty: 0, fork: 0, wait: 0 } },
  time: { short: 'of', long: { output: 1, format: 1, append: 0, portability: 0, verbose: 0, quiet: 0 } },
  stdbuf: { short: 'ioe', long: { input: 1, output: 1, error: 1 } },
  timeout: {
    short: 'sk', positional: 1,
    long: { signal: 1, 'kill-after': 1, 'preserve-status': 0, foreground: 0, verbose: 0 },
  },
  nice: { short: 'n', long: { adjustment: 1 } },
  ionice: { short: 'cnpPu', long: { class: 1, classdata: 1, pid: 1, pgid: 1, uid: 1, ignore: 0 } },
  // In GNU xargs `-p` is a plain flag, and `-i[R]`, `-l[N]`, `-e[eof]` take only an ATTACHED
  // value - as do the long forms `--replace`, `--max-lines` and `--eof` (`=` only).
  xargs: {
    short: 'adEILnPs', optShort: 'eil',
    long: {
      'arg-file': 1, delimiter: 1, 'max-args': 1, 'max-procs': 1, 'max-chars': 1,
      'process-slot-var': 1, eof: 2, replace: 2, 'max-lines': 2, null: 0, interactive: 0,
      'no-run-if-empty': 0, verbose: 0, exit: 0, 'open-tty': 0, 'show-limits': 0,
    },
  },
};

export function isCommandWrapper(name) {
  return Object.prototype.hasOwnProperty.call(COMMAND_WRAPPERS, name);
}

// Default word splitter for `env -S`: the git tokenizer below.
function defaultSplitWords(text) {
  return tokenizeDetailed(text).tokens;
}

/**
 * Walk off cmd_prefix constructs (shell-prefix.mjs) and command wrappers, alternating to a fixed
 * point, and return { rest, consumed, spliced, unresolved }: `rest` starts at the real command
 * name, `consumed` is every word walked off, `spliced` says an `env -S` string was split into the
 * word list, `unresolved` says the split cap was reached and the rest was not read.
 *
 * No round cap: every round walks off at least one word, so the walk ends within the word count.
 * A cap of 32 rounds returned the 33rd `nohup` as the command name, so `nohup` x33 in front of a
 * recursive delete was allowed (R2-CG-6). Only `env -S` can add words, and it is capped.
 */
const MAX_SPLITS = 64;

export function unwrapCommand(tokens, { splitWords = defaultSplitWords } = {}) {
  let t = tokens;
  let i = 0;
  let spliced = false;
  let unresolved = false;
  let splitsTotal = 0;
  const consumed = [];
  const take = (to) => { for (let k = i; k < to && k < t.length; k += 1) consumed.push(t[k]); i = to; };
  while (i < t.length) {
    take(skipCommandPrefix(t, i));
    if (i >= t.length) break;
    const name = commandName(t[i]);
    if (name === 'find') {
      // find ... -exec|-execdir|-ok|-okdir <command> ...
      let k = i + 1;
      while (k < t.length && !/^-(?:exec|execdir|ok|okdir)$/i.test(t[k])) k += 1;
      if (k >= t.length) break;
      take(k + 1);
      continue;
    }
    const spec = COMMAND_WRAPPERS[name];
    if (!spec || !isCommandWrapper(name)) break;
    take(i + 1);
    while (i < t.length) {
      const a = t[i];
      if (a === '--') { take(i + 1); break; }
      // env and sudo set any NAME=value word before the command (env does not check the name).
      if (spec.assignments && a.indexOf('=') > 0 && a[0] !== '-') { take(i + 1); continue; }
      if (a === '-' && name === 'env') { take(i + 1); continue; }   // a lone `-` is `env -i`
      if (a.length < 2 || a[0] !== '-') break;
      let splitValue = null;
      if (a.startsWith('--')) {
        const eq = a.indexOf('=');
        const key = resolveLongOption(spec.long || {}, eq < 0 ? a.slice(2) : a.slice(2, eq));
        let value = eq < 0 ? null : a.slice(eq + 1);
        let next = i + 1;
        if (key && spec.long[key] === 1 && value === null && next < t.length) { value = t[next]; next += 1; }
        take(next);
        if (key && key === spec.splitLong && value !== null) splitValue = value;
      } else {
        let next = i + 1;
        for (let k = 1; k < a.length; k += 1) {
          const ch = a[k];
          if (spec.short && spec.short.includes(ch)) {
            let value = a.slice(k + 1);
            if (!value && next < t.length) { value = t[next]; next += 1; }
            if (ch === spec.splitShort) splitValue = value;
            break;
          }
          if (spec.optShort && spec.optShort.includes(ch)) break;
        }
        take(next);
      }
      // `env -S 'A=1 cmd args'` splits its value into words that env then reads as its own
      // arguments, options and assignments included.
      if (splitValue !== null) {
        if (splitsTotal >= MAX_SPLITS) { unresolved = true; break; }
        splitsTotal += 1;
        spliced = true;
        t = [...splitWords(splitValue), ...t.slice(i)];
        i = 0;
      }
    }
    for (let p = 0; p < (spec.positional || 0) && i < t.length && !t[i].startsWith('-'); p += 1) {
      take(i + 1);
    }
    if (unresolved) break;
  }
  return { rest: t.slice(i), consumed, spliced, unresolved };
}

/** The tokens from the real command name on (see `unwrapCommand`). */
export function unwrapCommandTokens(tokens, opts) {
  return unwrapCommand(tokens, opts).rest;
}

// Shells that run a command line given with `-c`, or read one from a here-string / stdin.
const POSIX_SHELLS = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh', 'mksh', 'ash', 'fish']);
const POWERSHELLS = new Set(['powershell', 'pwsh']);

// PowerShell matches a parameter by any prefix of its name (`-com`, `-Comm`), from `-` or `/`.
function powershellParameter(token) {
  const m = /^(?:-{1,2}|\/)([A-Za-z]+)$/.exec(String(token));
  return m ? m[1].toLowerCase() : null;
}

function decodeEncodedCommand(value) {
  const text = String(value ?? '');
  if (!text || !/^[A-Za-z0-9+/=]+$/.test(text)) return '';
  try {
    return Buffer.from(text, 'base64').toString('utf16le').replace(/\u0000/g, '');
  } catch {
    return '';
  }
}

/**
 * True when `word` is a single-dash cluster of letters (`-rf`, `-lc`) containing one of `letters`.
 * One linear pass. The regex it replaces (`^-[A-Za-z]*c[A-Za-z]*$`) backtracked quadratically on a
 * long cluster that fails at its last character, and it ran from every shell word against every
 * later word: about 19 KB of input kept the destructive guard busy past its timeout (R2-CG-7).
 */
export function shortCluster(word, letters) {
  const w = String(word);
  if (w.length < 2 || w[0] !== '-' || w[1] === '-') return false;
  let found = false;
  for (let k = 1; k < w.length; k += 1) {
    const c = w[k];
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'))) return false;
    if (!found && letters.includes(c)) found = true;
  }
  return found;
}

// A shell or PowerShell invocation does not carry dozens of options before its command string.
// Past this many words the scan stops and reports `unresolved` instead of reading on, so scanning
// from every word of a long line stays linear.
const MAX_OPTION_WORDS = 64;

// The here-string word of a redirection token at tokens[k] (`<<<word` or `<<< word`), or null.
function hereStringWord(tokens, k) {
  const t = tokens[k];
  const op = redirectOperatorLength(t);
  if (op < 3 || t.slice(op - 3, op) !== '<<<') return null;
  if (op < t.length) return t.slice(op);
  return k + 1 < tokens.length ? tokens[k + 1] : '';
}

/**
 * The command line that the shell or evaluator at `tokens[i]` runs, or null. Returns
 * { text, semantics } where semantics is 'bash' (a POSIX shell parses it), 'ps' (PowerShell) or
 * 'inherit' (`eval`: the current shell).
 *
 *   eval [--] args                         bash -c [options] [--] 'cmd'     bash <<< 'cmd'
 *   iex / Invoke-Expression [-Command] x   su [opts] -c 'cmd'
 *   powershell|pwsh -Command|-c|-com... x  powershell|pwsh -EncodedCommand|-e|-ec|-enc... <base64>
 */
export function shellPayloadAt(tokens, i) {
  const name = commandName(tokens[i]);
  const rest = (from) => tokens.slice(from).join(' ').trim();
  if (name === 'eval') {
    let j = i + 1;
    if (tokens[j] === '--') j += 1;
    const text = rest(j);
    return text ? { text, semantics: 'inherit' } : null;
  }
  if (name === 'iex' || name === 'invoke-expression') {
    let j = i + 1;
    const p = powershellParameter(tokens[j]);
    if (p && 'command'.startsWith(p)) j += 1;
    const text = rest(j);
    return text ? { text, semantics: 'ps' } : null;
  }
  if (name === 'su') {
    for (let j = i + 1; j < tokens.length; j += 1) {
      if (j - i > MAX_OPTION_WORDS) return { text: '', semantics: 'bash', unresolved: true };
      const a = tokens[j];
      const long = /^--(command|session-command)(?:=(.*))?$/.exec(a);
      if (long && long[2] !== undefined) {
        const text = [long[2], ...tokens.slice(j + 1)].join(' ').trim();
        return text ? { text, semantics: 'bash' } : null;
      }
      if (long || (shortCluster(a, 'c') && a.endsWith('c'))) {
        const text = rest(j + 1);
        return text ? { text, semantics: 'bash' } : null;
      }
    }
    return null;
  }
  if (POSIX_SHELLS.has(name)) {
    // `bash [options] [-c] [options] [--] operand...`: options come first, `-c` may sit among
    // them (`-c`, `-lc`, `-ce`), and the first operand ends them - the command string under `-c`,
    // a script path otherwise (`bash script.sh -c x` hands `-c` to the script). Redirections can
    // sit anywhere; a here-string among them is the script when no `-c` is given.
    let j = i + 1;
    let command = false;
    let here = null;
    while (j < tokens.length) {
      if (j - i > MAX_OPTION_WORDS) return { text: '', semantics: 'bash', unresolved: true };
      const a = tokens[j];
      const op = redirectOperatorLength(a);
      if (op > 0) {
        const word = hereStringWord(tokens, j);
        if (word !== null) here = word;
        j += op === a.length ? 2 : 1;
        continue;
      }
      if (a === '--' || a === '-') { j += 1; break; }
      if (shortCluster(a, 'c')) { command = true; j += 1; continue; }
      if (/^[-+][oO]$/.test(a) || /^--(?:rcfile|init-file)$/.test(a)) { j += 2; continue; }
      if (/^[-+][A-Za-z]/.test(a) || /^--[A-Za-z]/.test(a)) { j += 1; continue; }
      break;
    }
    if (command) {
      const text = rest(j);
      return text ? { text, semantics: 'bash' } : null;
    }
    return here && here.trim() ? { text: here.trim(), semantics: 'bash' } : null;
  }
  if (POWERSHELLS.has(name)) {
    for (let j = i + 1; j < tokens.length; j += 1) {
      if (j - i > MAX_OPTION_WORDS) return { text: '', semantics: 'ps', unresolved: true };
      const p = powershellParameter(tokens[j]);
      if (p && (p === 'ec' || 'encodedcommand'.startsWith(p))) {
        const text = decodeEncodedCommand(tokens[j + 1]).trim();
        if (text) return { text, semantics: 'ps' };
        continue;
      }
      if ((p && ('command'.startsWith(p) || 'commandwithargs'.startsWith(p) || p === 'cwa'))
          || /^(?:-command|\/c|-[a-z]*c)$/i.test(tokens[j])) {
        const text = rest(j + 1);
        return text ? { text, semantics: 'ps' } : null;
      }
    }
    return null;
  }
  return null;
}

// ---------------------------------------------------------------------------------------------
// Here-documents (CG-10, re-planned in R3-CG-1).
//
// No here-document body is ever removed from what the guards read. Two earlier attempts did remove
// bodies the lexer judged to be data - first unless a listed stdin reader was on the line, then
// unless an allow-list proved the body inert - and both had bypasses, because any such rule relies on
// the lexer modelling bash exactly. Body lines are read as commands again, as base f430715 read them.
//
// The one exception is a whole command that matches one of these exact shapes, checked by a linear
// match on the trimmed text with nothing before the opener line and nothing after the closing line:
//   cat > PATH <<'D' | cat >> PATH <<'D' | cat <<'D' > PATH | cat <<'D' >> PATH | tee PATH <<'D'
//   git commit [simple flags] -F - <<'D'                      (the body is the commit message)
// D is quoted and an identifier; the closing line is exactly D and no earlier body line starts with D
// (bash's comsub/heredoc back-compat can end a body there); the command holds no CR or NUL;
// PATH is a plain relative path with no `..`, no dot-component, no expansion or glob. Never used for
// the PowerShell tool. The `-m "$(cat <<'D' ... )"` commit idiom is NOT an exception (R4-1): bash can
// end that body early and run the next line, so every line of it is read.
// ---------------------------------------------------------------------------------------------
const SHAPE_COMMIT_FLAGS = new Set(['--allow-empty', '--allow-empty-message', '-q', '--quiet', '-s',
  '--signoff', '--no-verify', '-n', '-v', '--verbose', '--amend', '-a', '--all', '--no-edit', '-e',
  '--edit', '--no-gpg-sign']);

function plainRelativePath(path) {
  if (!path || path.length > 1024 || path[0] === '/') return false;
  for (let k = 0; k < path.length; k += 1) {
    const c = path[k];
    const ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')
      || c === '_' || c === '-' || c === '.' || c === '/';
    if (!ok) return false;
  }
  return path.split('/').every((segment) => segment.length > 0 && segment[0] !== '.');
}

function heredocToken(token) {
  const m = /^<<(['"])([A-Za-z_][A-Za-z0-9_]*)\1$/.exec(token);
  return m ? m[2] : null;
}

// The opener line's shape: { kind: 'file' | 'commit', delim } or null.
function openerShape(opener) {
  if (/[\r\t]/.test(opener)) return null;
  const words = opener.split(' ').filter(Boolean);
  const hd = words.map(heredocToken);
  const at = hd.findIndex((d) => d !== null);
  if (at < 0 || hd.filter((d) => d !== null).length !== 1) return null;
  const delim = hd[at];
  const plain = (w) => /^[A-Za-z0-9_./=-]+$/.test(w) || w === '>' || w === '>>';
  const others = words.filter((_, k) => k !== at);
  if (words[0] === 'cat' || words[0] === 'tee') {
    if (!others.every(plain)) return null;
    const w = words;
    if (w[0] === 'tee' && w.length === 3 && at === 2 && plainRelativePath(w[1])) return { kind: 'file', delim };
    if (w[0] !== 'cat' || w.length !== 4) return null;
    if (at === 3 && (w[1] === '>' || w[1] === '>>') && plainRelativePath(w[2])) return { kind: 'file', delim };
    if (at === 1 && (w[2] === '>' || w[2] === '>>') && plainRelativePath(w[3])) return { kind: 'file', delim };
    return null;
  }
  if (words[0] !== 'git' || words[1] !== 'commit' || at !== words.length - 1) return null;
  const flags = words.slice(2, at);
  let stdin = 0;
  for (let k = 0; k < flags.length; k += 1) {
    const f = flags[k];
    if (SHAPE_COMMIT_FLAGS.has(f)) continue;
    if (f === '--file=-') { stdin += 1; continue; }
    if ((f === '-F' || f === '--file') && flags[k + 1] === '-') { stdin += 1; k += 1; continue; }
    return null;
  }
  return stdin === 1 ? { kind: 'commit', delim } : null;
}

/**
 * The exact here-document shape of a whole command (see above), or null:
 * { kind, opener, body } - `opener` is the first line, `body` the here-document text.
 */
export function exactHeredocShape(command) {
  const raw = String(command ?? '');
  if (raw.includes('\r') || raw.includes('\0')) return null;   // not whitespace; checked before trimming (R4-5)
  const text = raw.trim();
  const first = text.indexOf('\n');
  if (first < 0) return null;
  const opener = text.slice(0, first);
  const shape = openerShape(opener);
  if (!shape) return null;
  const lines = text.slice(first + 1).split('\n');
  const close = lines.length - 1;
  if (close < 0 || lines[close] !== shape.delim) return null;
  // bash ends the body at the first line that STARTS WITH the delimiter: its 4.x-5.3 back-compat
  // branches close a here-document on such a line inside a comsub, so one earlier close would leave
  // the lines after it as commands. Rejecting the exact shape there falls back to base, which reads
  // every line. Leading tabs are ignored too, which can only reject more (R4-1).
  for (let k = 0; k < close; k += 1) {
    let j = 0;
    while (j < lines[k].length && lines[k][j] === '\t') j += 1;
    if (lines[k].slice(j).startsWith(shape.delim)) return null;
  }
  const body = close > 0 ? lines.slice(0, close).join('\n') + '\n' : '';
  return { kind: shape.kind, opener, body, text };
}

// Base f430715's statement splitter, unchanged: it splits on `;`, `&&`, `||`, `|`, `&` (not the `&`
// of a redirect) and newlines outside quotes, with no comment, here-document or substitution model.
// The resolver walks its statements as well as the lexer's (R3-CG-1), so a reading where the lexer
// and bash disagree can never see less than base did: every here-document body line is a top-level
// statement again, with base's `-C`, `-F` and push-state handling.
function baseAmpersandIsRedirect(next, lastNonSpace, lastWasEscaped) {
  if (next === '>') return true;
  if (lastNonSpace !== '>' && lastNonSpace !== '<') return false;
  return !lastWasEscaped;
}

// PowerShell comments: `#` at the start of a word runs to the end of the line, `<# ... #>` is a
// block comment (R3-CG-8). Strings are skipped: '...' (a doubled '' re-opens, same effect) and
// "..." with backtick escapes. Linear: each character is read once. Returns [start, end) ranges.
export function powershellCommentRanges(text) {
  const out = [];
  const s = String(text ?? '');
  const n = s.length;
  let i = 0;
  let wordStart = true;
  while (i < n) {
    const c = s[i];
    if (c === "'") {
      const close = s.indexOf("'", i + 1);
      i = close < 0 ? n : close + 1;
      wordStart = false;
      continue;
    }
    if (c === '"') {
      let j = i + 1;
      while (j < n && s[j] !== '"') j += s[j] === '`' ? 2 : 1;
      i = Math.min(n, j + 1);
      wordStart = false;
      continue;
    }
    if (c === '`') { i += 2; wordStart = false; continue; }
    if (c === '<' && s[i + 1] === '#') {
      const close = s.indexOf('#>', i + 2);
      const stop = close < 0 ? n : close + 2;
      out.push([i, stop]);
      i = stop;
      wordStart = true;
      continue;
    }
    if (c === '#' && wordStart) {
      const nl = s.indexOf('\n', i);
      const stop = nl < 0 ? n : nl;
      out.push([i, stop]);
      i = stop;
      continue;
    }
    wordStart = c === ' ' || c === '\t' || c === '\n' || c === '\r' || c === ';' || c === '|'
      || c === '&' || c === '(' || c === ')' || c === '{' || c === '}';
    i += 1;
  }
  return out;
}

/** `text` with the given [start, end) ranges replaced by spaces (newlines kept). */
export function blankRanges(text, ranges) {
  const s = String(text ?? '');
  let out = '';
  let at = 0;
  for (const [a, b] of [...ranges].sort((x, y) => x[0] - y[0])) {
    if (b <= at) continue;
    const from = Math.max(a, at);
    out += s.slice(at, from) + s.slice(from, b).replace(/[^\n]/g, ' ');
    at = b;
  }
  return out + s.slice(at);
}

/**
 * Every statement a command line can run, as { text, heredocs }: the lexer's statements
 * (substitutions, comments, here-document stdin) UNION base f430715's statements (no comment,
 * here-document or substitution model: every here-document body line is a statement), without
 * exact duplicates. For PowerShell, base's statements of the text with PowerShell comments blanked
 * are added too (`<#x#> git push` is a block comment and a push). The union can only add (R3-CG-1).
 *
 * A statement that a literal here-document reaches through a pipe carries that body as `stdin`:
 * in `cat <<'EOF' | git commit -F -` the body is the commit's message, but the lexer keeps it on
 * the `cat` statement, so the commit read no stdin and its message went unscanned (R1-b). Only the
 * exact producer `cat <<WORD` (one here-document, no other word or redirect) is followed; `cat -`,
 * `/bin/cat`, `echo` and `printf` are not, and neither is anything under the PowerShell tool.
 * The body RIDES ON the consumer statement (`pipedStdins`), never replaces its own stdin: a redirect
 * on the consumer (`... | git commit -F - <<'B'`) wins over the pipe, so git reads B, and B must still
 * be scanned. It is not a second queue item: an extra item was read even when its statement was
 * dropped by a budget, an uncharged re-read (security reviews 2-4). On the statement's one reading,
 * each body adds one more invocation record with that body as stdin; a dropped statement drops its
 * bodies with it.
 */
const PIPED_HEREDOC_PRODUCER = /^cat[ \t]+<<-?[ \t]*(?:'[^'\n]*'|"[^"\n]*"|[^\s'"<>|;&()]+)$/;

export function statementsOf(text, { powershell = false } = {}) {
  const out = [];
  const byKey = new Map();
  const add = (st, pipedStdin) => {
    const key = st.text.trim();
    if (!key) return;
    let kept = byKey.get(key);
    if (!kept) {
      kept = st;
      byKey.set(key, kept);
      out.push(kept);
    }
    // Two `git commit -F -` statements fed different bodies are two messages: a repeated statement
    // adds its body to the one already kept, so the second message is still scanned.
    if (pipedStdin !== undefined) (kept.pipedStdins || (kept.pipedStdins = [])).push(pipedStdin);
  };
  const lexed = scanShell(text).statements;
  // The producer is the previous statement of the same region and depth: a substitution inside the
  // consumer (`... | git commit --date="$(date -R)" -F -`) is lexed before it and is not the producer.
  const lastIn = new Map();
  for (const st of lexed) {
    const key = st.region + ':' + st.depth;
    const prev = lastIn.get(key);
    lastIn.set(key, st);
    const piped = !powershell && prev && prev.sep === '|'
      && prev.heredocs.length === 1 && !prev.heredocs[0].uncertain
      && PIPED_HEREDOC_PRODUCER.test(prev.text.trim());
    add({ text: st.text, heredocs: st.heredocs }, piped ? prev.heredocs[0].body : undefined);
  }
  for (const t of baseStatements(text)) add({ text: t, heredocs: [] });
  if (powershell && String(text).includes('#')) {
    const ranges = powershellCommentRanges(text);
    if (ranges.length) for (const t of baseStatements(blankRanges(text, ranges))) add({ text: t, heredocs: [] });
  }
  return out;
}

export function baseStatements(text) {
  const segs = [];
  const s = String(text ?? '');
  let start = 0;
  let q = null;
  let lastNonSpace = '';
  let lastWasEscaped = false;
  let backslashRun = 0;
  const keep = (ch) => {
    if (ch !== ' ' && ch !== '\t') {
      lastNonSpace = ch;
      lastWasEscaped = backslashRun % 2 === 1;
    }
    backslashRun = ch === '\\' ? backslashRun + 1 : 0;
  };
  const flush = (stop, next) => {
    segs.push(s.slice(start, stop));
    start = next;
    lastNonSpace = '';
    lastWasEscaped = false;
    backslashRun = 0;
  };
  for (let i = 0; i < s.length; i += 1) {
    const c = s[i];
    const n = s[i + 1];
    if (q) { keep(c); if (c === q) q = null; continue; }
    if (c === "'" || c === '"') { q = c; keep(c); continue; }
    if (c === ';' || c === '\n') { flush(i, i + 1); continue; }
    if ((c === '&' || c === '|') && n === c) { flush(i, i + 2); i += 1; continue; }
    if (c === '&' && baseAmpersandIsRedirect(n, lastNonSpace, lastWasEscaped)) { keep(c); continue; }
    if (c === '|' || c === '&') { flush(i, i + 1); continue; }
    keep(c);
  }
  if (start < s.length) segs.push(s.slice(start));
  return segs.filter((seg) => seg.trim());
}

// Names git resolves as real commands. git DOES NOT honour an alias that hides an existing git
// command -- verified: with `alias.status = "commit -a"` set, `git status` still runs status. So a
// builtin name must never be expanded, or `git status` in a repo carrying that alias would be
// treated as a commit and scanned (a false positive that could DENY a read-only command). Skipping
// them also removes the `git config` subprocess from the common path entirely.
const GIT_BUILTINS = new Set([
  'add', 'am', 'annotate', 'apply', 'archive', 'bisect', 'blame', 'branch', 'bundle', 'cat-file',
  'check-ignore', 'checkout', 'cherry', 'cherry-pick', 'clean', 'clone', 'commit', 'config',
  'describe', 'diff', 'difftool', 'fetch', 'for-each-ref', 'format-patch', 'fsck', 'gc', 'grep',
  'help', 'init', 'log', 'ls-files', 'ls-remote', 'ls-tree', 'merge', 'mergetool', 'mv', 'notes',
  'pull', 'push', 'range-diff', 'rebase', 'reflog', 'remote', 'repack', 'replace', 'reset',
  'restore', 'rev-list', 'rev-parse', 'revert', 'rm', 'shortlog', 'show', 'show-ref', 'sparse-checkout',
  'stash', 'status', 'submodule', 'switch', 'symbolic-ref', 'tag', 'update-index', 'update-ref',
  'version', 'whatchanged', 'worktree', 'write-tree',
]);

// git global options that take a SEPARATE value argument, so the value is not the subcommand.
const GIT_GLOBAL_VALUE_OPTS = new Set(['-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path', '--config-env']);

/**
 * Quote-aware tokenizer: splits on unquoted whitespace and removes quote delimiters, so
 * `"git" commit`, `g'i't commit` and `git   commit` all tokenize to ["git", "commit"].
 * Single pass, no backtracking.
 *
 * An unquoted `<` or `>` starts a new word, as in the shell: `HEAD:main>/dev/null` is the refspec
 * `HEAD:main` plus a redirection, not one refspec. `redirect[i]` marks a word that an UNQUOTED
 * redirection operator began (`2>&1`, `>/dev/null`, `<<'EOF'`, `<<<`), so a caller can drop
 * redirections without dropping a quoted argument that merely starts with `>`.
 */
export function tokenizeDetailed(text) {
  // Decode `$'...'` first: bash substitutes those escapes before git sees them, so a message
  // written as $'\\x73\\x6b...' really lands in history as `sk-...`. Reading the raw token made
  // the scanner blind to it.
  const s = String(expandAnsiCQuotes(String(text ?? '')));
  const tokens = [];
  const redirect = [];
  let cur = '';
  let has = false;
  let q = null;
  let isRedirect = false;
  let opOnly = false;                 // the redirect word holds only operator characters so far
  let digitsOnly = true;              // the word so far is an unquoted run of digits (an fd)
  const push = () => {
    if (has) { tokens.push(cur); redirect.push(isRedirect); }
    cur = ''; has = false; isRedirect = false; opOnly = false; digitsOnly = true;
  };
  for (let i = 0; i < s.length; i += 1) {
    const c = s[i];
    // A command substitution, arithmetic or parameter expansion is part of the word around it,
    // whatever it contains: `git -c user.name=$(git config user.name) commit` has `commit` as its
    // subcommand, and splitting inside the `$( )` made `config` the subcommand instead. Its own
    // commands are statements of their own (see scanShell); here it is opaque text. Live in
    // double quotes too; literal in single quotes.
    if (q !== "'" && (c === '$' || c === '`' || (!q && (c === '<' || c === '>') && s[i + 1] === '('))) {
      const stop = expansionEnd(s, i);
      if (stop > i + 1) {
        cur += s.slice(i, stop); has = true; opOnly = false; digitsOnly = false; i = stop - 1;
        continue;
      }
    }
    if (q) {
      if (c === q) { q = null; continue; }
      // In double quotes a backslash escapes only `$`, a backtick, `"`, `\` and a newline.
      if (q === '"' && c === '\\' && i + 1 < s.length && '$`"\\\n'.includes(s[i + 1])) {
        cur += s[i + 1]; has = true; i += 1;
        continue;
      }
      cur += c; has = true; opOnly = false; digitsOnly = false;
      continue;
    }
    if (c === '\\' && i + 1 < s.length) {
      cur += s[i + 1]; has = true; opOnly = false; digitsOnly = false; i += 1;
      continue;
    }
    if (c === "'" || c === '"') { q = c; has = true; opOnly = false; digitsOnly = false; continue; }
    if (c === ' ' || c === '\t' || c === '\n' || c === '\r' || c === '\f' || c === '\v') { push(); continue; }
    if (c === '<' || c === '>') {
      if (isRedirect && opOnly) { cur += c; continue; }               // `>>`, `<<`, `<<<`
      if (has && !(digitsOnly || cur === '&')) push();                 // `main>x` -> `main`, `>x`
      cur += c; has = true; isRedirect = true; opOnly = true; digitsOnly = false;
      continue;
    }
    if (isRedirect && opOnly && (c === '&' || c === '|' || c === '-')) { cur += c; continue; }
    cur += c; has = true; opOnly = false;
    if (c < '0' || c > '9') digitsOnly = false;
  }
  push();
  return { tokens, redirect };
}

export function tokenize(text) {
  return tokenizeDetailed(text).tokens;
}

/** The words of a tokenized statement with every redirection (and a detached target) removed. */
export function stripRedirections(detailed) {
  const { tokens, redirect } = detailed;
  const out = [];
  for (let i = 0; i < tokens.length; i += 1) {
    if (!redirect[i]) { out.push(tokens[i]); continue; }
    const op = redirectOperatorLength(tokens[i]);
    if (op > 0 && op === tokens[i].length) i += 1;      // `> file`, `2> err`, `<<< word`
  }
  return out;
}

// The text a statement feeds to its command's stdin: its first here-document body, else a
// here-string word. Used for `git commit -F -` and for shells that read a script from stdin.
function statementStdin(heredocs, detailed) {
  if (heredocs && heredocs.length) return heredocs[0].body;
  const { tokens, redirect } = detailed;
  for (let i = 0; i < tokens.length; i += 1) {
    if (!redirect[i]) continue;
    const t = tokens[i];
    const op = redirectOperatorLength(t);
    if (op < 3 || t.slice(op - 3, op) !== '<<<') continue;
    if (op < t.length) return t.slice(op);
    return i + 1 < tokens.length ? tokens[i + 1] : '';
  }
  return null;
}

/**
 * Statements of a command line, as text: top-level statements, then the statements inside its
 * command substitutions. Here-document bodies are not statements (see scanShell).
 */
export function splitStatements(text) {
  return scanShell(text).statements.map((st) => st.text);
}

// Top-level statements only: the per-statement readers below must not read options that belong
// to a command substitution inside a message (`-m "$(git diff -a)"`).
function topLevelTexts(text) {
  return scanShell(text).statements.filter((st) => !st.nested && !st.inBody).map((st) => st.text);
}

// Strip wrapping subshell `( ... )` / brace-group `{ ...; }` delimiters. Without this the first
// token of `(git commit -am x)` is `(git`, whose basename is not `git`, so the whole statement was
// invisible to the resolver and BOTH guards exited — a plain, everyday shell construct defeating
// them completely. destructive-command-guard.mjs has stripped these for a long time; this resolver
// simply never re-asked the question. LINEAR single-char slices, deliberately not a regex with a
// greedy quantifier before an anchor (see lessons.md).
function stripGroupWrappers(seg) {
  let s = String(seg).trim();
  for (let i = 0; i < 8; i += 1) {
    const before = s;
    if (s.startsWith('(') || s.startsWith('{')) s = s.slice(1).trim();
    if (s.endsWith(')') || s.endsWith('}')) s = s.slice(0, -1).trim();
    if (s === before) break;
  }
  return s;
}

// Given the tokens of ONE command (redirections already removed), return
// { subcommand, args, inlineAliases, inlineConfig, dirs, readContextKnown } if it invokes git.
function gitCall(tokens) {
  const { rest: t, consumed, spliced } = unwrapCommand(tokens);
  if (!t.length) return null;
  if (commandName(t[0]) !== 'git') return null;
  const inlineAliases = new Map();
  const inlineConfig = [];
  const dirs = [];
  // Every word walked off before `git`: an environment prefix such as GIT_DIR= redirects git.
  let readContextKnown = !spliced && !consumed.some((token) =>
    /^(?:GIT_(?:DIR|WORK_TREE|NAMESPACE|CONFIG(?:_[A-Z0-9_]+)?|CEILING_DIRECTORIES)|HOME|XDG_CONFIG_HOME)=/.test(token));
  const config = (kv) => {
    const j = kv.indexOf('=');
    const key = j < 0 ? kv : kv.slice(0, j);
    const value = j < 0 ? 'true' : kv.slice(j + 1);
    inlineConfig.push([key, value]);
    if (/^alias\./i.test(key)) inlineAliases.set(key.slice(6).toLowerCase(), value);
    if (/^core\.(?:bare|worktree)$/i.test(key)) readContextKnown = false;
    if (/^(?:include|includeif\..+)\.path$/i.test(key)) readContextKnown = false;
  };
  let i = 1;
  while (i < t.length) {
    const a = t[i];
    if (!a.startsWith('-')) break;
    // `-c alias.ci=commit` and `-c=` / `--git-dir=...` inline forms.
    const eq = a.indexOf('=');
    if (a === '-c' && i + 1 < t.length) {
      config(t[i + 1]);
      i += 2;
      continue;
    }
    if (a.startsWith('-c') && a.length > 2) { config(a.slice(2)); i += 1; continue; }
    if (a === '-C' && i + 1 < t.length) { dirs.push(t[i + 1]); i += 2; continue; }
    if (a.startsWith('-C') && a.length > 2) { dirs.push(a.slice(2)); i += 1; continue; }
    if (/^--(?:git-dir|work-tree|namespace|exec-path|config-env)(?:=|$)/.test(a) || a === '--bare') {
      readContextKnown = false;
    }
    if (eq > 0) { i += 1; continue; }                 // --git-dir=/x : value is attached
    if (GIT_GLOBAL_VALUE_OPTS.has(a) && i + 1 < t.length) { i += 2; continue; }
    i += 1;
  }
  if (i >= t.length) return null;
  return { subcommand: t[i], args: t.slice(i + 1), inlineAliases, inlineConfig, dirs, readContextKnown };
}

// CG-11: one alias table read costs a `git config` process (~4 ms). A command line of thousands of
// unknown `git <word>` statements used to spend one per statement and run the hook past its
// runtime budget, and a killed hook renders no decision. Lookups are now cached per
// (repository, name) and capped per invocation; past the cap an unknown name is reported as
// unresolved rather than looked up, and every statement is still walked, so an explicit
// `git push origin main` later on the line is still seen.
const MAX_ALIAS_LOOKUPS = 32;
const ALIAS_LOOKUP_BUDGET_MS = 4000;

// Returns the expansion, '' when git says there is no such alias (exit 1), or null when the answer is
// unknown (timeout, an unreadable or hostile config, any other failure).
function makeAliasLookup(cwd, deadline) {
  return function lookup(name) {
    if (!/^[A-Za-z0-9._-]{1,64}$/.test(name)) return '';  // never pass odd text to git
    const timeout = Math.min(3000, deadline - Date.now());
    if (timeout <= 0) return null;
    try {
      // Argument array, no shell: nothing here is interpolated into a command line.
      return runGit(['config', '--get', 'alias.' + name], {
        cwd: cwd || process.cwd(),
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout,
      }).trim();
    } catch (error) {
      return error && error.status === 1 && !error.signal ? '' : null;
    }
  };
}

// The directory a shell command runs in. Kimi Code's Bash tool takes its own `tool_input.cwd`
// (relative paths resolve against the session cwd); the command executes THERE, so a guard reading
// only the payload's session `cwd` would check another repository's branch and staged content.
// Only Kimi defines that field, and Kimi exports KIMI_PLUGIN_ROOT to its hook processes: honouring
// a `cwd` argument on a runtime that ignores it when running the command would let a model point the
// guards at a clean repository. Everything else uses the session cwd, then the hook process cwd.
export function commandCwd(input, env = process.env) {
  const session = typeof input?.cwd === 'string' && input.cwd ? input.cwd : process.cwd();
  const tool = env.KIMI_PLUGIN_ROOT ? input?.tool_input?.cwd : undefined;
  return typeof tool === 'string' && tool ? resolvePath(session, tool) : session;
}

// `git -C a -C b` is CUMULATIVE: each non-absolute -C resolves against the PREVIOUS one, so
// the target is a/b (verified against real git). Taking dirs[0] pointed every git read at a
// strict ancestor of the real target repository, which silently un-scoped the guard.
export function resolveTargetCwd(baseCwd, dirs) {
  // Normalize components once rather than resolving an ever-growing path for every -C.
  // Absolute steps reset the path; Windows root/drive-relative steps retain native semantics.
  let root;
  let parts;
  const assign = (value) => {
    const absolute = resolvePath(value);
    root = parsePath(absolute).root;
    parts = absolute.slice(root.length).split(sep).filter(Boolean);
  };
  assign(baseCwd || process.cwd());
  for (const dir of dirs || []) {
    if (!dir) continue; // Git's -C '' leaves cwd unchanged
    let rest = dir;
    const stepRoot = parsePath(dir).root;
    if (sep === '\\' && /^[A-Za-z]:$/.test(stepRoot)) {
      if (root.slice(0, 2).toLowerCase() !== stepRoot.toLowerCase()) { assign(dir); continue; }
      root = stepRoot + root.slice(2);
      rest = dir.slice(stepRoot.length);
    } else if (sep === '\\' && /^[\\/]$/.test(stepRoot)) {
      parts = [];
      rest = dir.slice(stepRoot.length);
    } else if (stepRoot) { assign(dir); continue; }
    for (const part of rest.split(sep === '\\' ? /[\\/]/ : /\//)) {
      if (!part || part === '.') continue;
      if (part === '..') parts.pop();
      else parts.push(part);
    }
  }
  return root + parts.join(sep);
}

// The inline command line a statement hands to another shell, or null.
//
// Only the COMMAND position counts. Scanning every token meant a statement that merely
// MENTIONS a shell - `echo bash -c "git push origin main"`, `which bash -c git push` - had
// its remaining arguments re-analyzed as a command line and denied. `unwrapCommandTokens` is what
// resolves that position, walking off prefixes and wrappers exactly as it does for a git call.
function innerShellPayload(tokens) {
  const t = unwrapCommandTokens(tokens);
  if (!t.length) return null;
  const payload = shellPayloadAt(t, 0);
  return payload ? payload.text : null;
}

/**
 * Resolve what a command line will actually make git do.
 *
 * Returns:
 *   subcommands - lowercase Set of every git subcommand reached, after alias expansion
 *   texts       - the original statements PLUS every alias expansion, as command strings. The
 *                 caller needs these because a secret can live inside the ALIAS DEFINITION
 *                 (`alias.ci = "commit -a -m '<token>'"`), where the typed command carries no -m
 *                 at all yet the commit still records that message.
 *   dirs        - values of `git -C <dir>`, so the caller can run its own git reads against the
 *                 repository the command targets rather than the hook process's cwd.
 *   invocations - one record per git call reached (every subcommand): { subcommand, args (no
 *                 redirections), inlineConfig, cwd, viaPayload, readContextKnown, stdin, depth }.
 *   aliasShellTexts - the command lines of `!` aliases reached, for a caller that checks shell
 *                 commands rather than git calls (the destructive guard).
 *   aliasLookupsExhausted - the per-invocation alias lookup cap was reached (CG-11).
 *
 * `opts.lookup` is injectable so the resolution logic is testable without a live repo;
 * `opts.cwd` selects the repository whose alias table is consulted.
 */
export function resolveGitCommands(command, opts = {}) {
  const injected = typeof opts === 'function' ? opts : opts.lookup;
  const baseCwd = (typeof opts === 'object' && opts.cwd) || process.cwd();
  // The alias table lives in the repo the command TARGETS, and `-C <dir>` is only discovered while
  // parsing that same call — so the lookup cwd is chosen per call, not once up front. Fixing it in
  // advance made `git -C ../other ci` consult the wrong repository, find no alias, and skip the guard.
  const aliasCache = new Map();
  const deadline = Date.now() + ALIAS_LOOKUP_BUDGET_MS;
  let lookups = 0;
  let exhausted = false;
  let aliasesUnresolved = false;
  const lookupAlias = (dirs, name) => {
    const cwd = injected ? '' : resolveTargetCwd(baseCwd, dirs);
    const key = cwd + '\0' + name;
    if (aliasCache.has(key)) return aliasCache.get(key);
    if (lookups >= MAX_ALIAS_LOOKUPS || Date.now() > deadline) { exhausted = true; return ''; }
    lookups += 1;
    let value = injected ? injected(name) : makeAliasLookup(cwd, deadline)(name);
    if (value === null) { aliasesUnresolved = true; value = ''; }
    aliasCache.set(key, value);
    return value;
  };
  // R2-CG-8: one budget for the text this walk re-reads beyond the statements of the command line
  // itself (inner shell payloads, alias expansions, executed here-document bodies). Nested
  // `eval $(...)` around a long word made every level re-read the whole word; each top-level
  // statement is still always walked, so a plain `git push` later on the line is still seen.
  const workLimit = 1024 * 1024 + 8 * String(command ?? '').length;
  let work = 0;
  // R1-d skipped-read probe, shared by every walk of this command line (see `dropped` in walk()).
  let skippedReads = 0;
  let probedChars = 0;
  let workExhausted = false;
  const spend = (size) => {
    work += size;
    if (work > workLimit) workExhausted = true;
    return !workExhausted;
  };
  // PowerShell has no here-documents: no exact shape is honoured there (R3-CG-1).
  const allowHeredocShapes = !(typeof opts === 'object' && opts.allowHeredocStrip === false);
  const powershell = !allowHeredocShapes;

  // PER-STATEMENT scoping. `-C` belongs to the git call that carries it, not to the command line:
  // collecting every `-C` into one shared array let an unrelated `git -C /tmp status;` earlier on
  // the line redirect the COMMIT's own diff read to /tmp, where it found nothing and allowed.
  function walk(root) {
    const subcommands = new Set();
    const texts = [];
    const payloadTexts = [];
    const dirs = [];
    const invocations = [];
    const aliasShellTexts = [];
    // `dirs` stays the ordered result; `dirSeen` is the membership test. It used to be
    // `dirs.includes(d)`, which compares each new directory against every one already
    // collected - quadratic, and this path has no input cap, so a long enough command line
    // pushed the hook past its runtime budget. A killed hook renders no decision at all, so
    // the command then proceeds unguarded. A Set rather than a plain object: `-C constructor`
    // and `-C __proto__` must be data, not properties.
    const dirSeen = new Set();
    const seen = new Set();
    const queue = [{ text: root.text, heredocs: root.heredocs, depth: 0, viaPayload: !!root.viaPayload,
      payloadDepth: root.viaPayload ? 1 : 0, root: !root.viaPayload,
      ...(root.pipedStdins ? { pipedStdins: root.pipedStdins } : {}) }];
    let budget = 64;                                     // hard bound: alias chains cannot spin
    // SEPARATE from the alias budget above. Sharing one means a payload chain can exhaust the
    // budget an alias expansion needs, and exhaustion in this loop is a silent allow.
    let payloadBudget = 128;
    // R1-d: a statement a budget drops is not read, so a commit or push inside it is neither checked
    // nor seen. A dropped text that could name git (the hooks' own cheap probe) is reported. The
    // hooks need only whether one exists, so probing stops at the first hit, and all walks share one
    // character cap: past it a drop counts without a probe (the notice errs toward "not scanned").
    const dropped = (t) => {
      if (skippedReads > 0) return;
      const s = String(t ?? '');
      if (probedChars + s.length > workLimit) { probedChars = workLimit; skippedReads = 1; return; }
      probedChars += s.length;
      if (mayNameGit(s)) skippedReads = 1;
    };
    while (queue.length) {
      const item = queue.shift();
      const { text, depth, viaPayload, payloadDepth } = item;
      // Two budgets, spent by whoever the work belongs to. Charging payload-derived dequeues
      // to the alias budget made the separation nominal: a payload chain starved the alias
      // walk at 61 fillers, and running out of THAT budget is a silent allow.
      if (viaPayload) {
        if (payloadBudget <= 0) { dropped(text); continue; }
        payloadBudget -= 1;
      } else {
        if (budget <= 0) { dropped(text); continue; }
        budget -= 1;
      }
      if (depth > 5) continue;                           // git itself bounds alias recursion
      if (!item.root && !spend(String(text).length)) continue;
      const detailed = tokenizeDetailed(stripGroupWrappers(text));
      const stdin = item.stdin !== undefined ? item.stdin : statementStdin(item.heredocs, detailed);
      // CG-5: a redirection is not an argument. `git push origin 2>&1` read `2>&1` as a refspec,
      // which hid the configured destination the push really uses.
      const call = gitCall(stripRedirections(detailed));
      if (!call) {
        // Not a git call itself - but it may HAND one to another shell. Re-analyze the inline
        // payload as its own statement, bounded independently of the alias walk.
        const inner = innerShellPayload(detailed.tokens);
        if (inner !== null && !(payloadDepth < 3 && payloadBudget > 0)) { dropped(inner); continue; }
        if (inner && spend(inner.length)) {
          payloadBudget -= 1;
          for (const st of statementsOf(inner, { powershell })) {
            queue.push({ text: st.text, heredocs: st.heredocs, depth, viaPayload: true,
              payloadDepth: payloadDepth + 1,
              ...(st.pipedStdins ? { pipedStdins: st.pipedStdins } : {}) });
          }
        }
        continue;
      }
      // Additive argv records preserve normal-alias caller operands and ordered -C context.
      // Keep legacy text/directory views for existing commit readers. Payload paths still never
      // become disk-read locations, and arbitrary inline config is never passed to a Git child.
      const orderedDirs = [...(item.orderedDirs || []), ...call.dirs];
      const inlineConfig = [...(item.inlineConfig || []), ...call.inlineConfig];
      const effectiveArgs = [...call.args, ...(item.extraArgs || [])];
      const contextKnown = item.readContextKnown !== false && call.readContextKnown;
      const effectiveAliases = new Map();
      for (const [key, value] of inlineConfig) {
        if (/^alias\./i.test(key)) effectiveAliases.set(key.slice(6).toLowerCase(), value);
      }
      if (viaPayload) {
        // Message text only, collected separately. A payload-derived call contributes no `-C`
        // directory and never reaches the `-F`/`--file` reader, so reaching into a payload does
        // not widen what the commit scanner opens on disk - otherwise
        // `bash -c "git commit -F /etc/passwd"` would newly cause an arbitrary file read. The
        // payload's SUBCOMMANDS still register below, which is what lets branch-guard see a
        // commit or a push through an inner shell.
        payloadTexts.push(text);
      } else {
        texts.push(text);
        for (const d of call.dirs) if (!dirSeen.has(d)) { dirSeen.add(d); dirs.push(d); }
      }
      const sub = String(call.subcommand || '').toLowerCase();
      if (!sub || sub.startsWith('-')) continue;
      subcommands.add(sub);
      invocations.push({
        subcommand: sub, args: effectiveArgs, inlineConfig,
        cwd: viaPayload ? baseCwd : resolveTargetCwd(baseCwd, orderedDirs),
        viaPayload, readContextKnown: contextKnown && !viaPayload, stdin, depth,
      });
      // A literal here-document piped into this statement (R1-b): one more record per body, from this
      // same reading. Not passed to alias children, whose stdin is the statement's own.
      for (const body of item.pipedStdins || []) {
        invocations.push({
          subcommand: sub, args: effectiveArgs, inlineConfig,
          cwd: viaPayload ? baseCwd : resolveTargetCwd(baseCwd, orderedDirs),
          viaPayload, readContextKnown: contextKnown && !viaPayload, stdin: body, depth,
        });
      }
      const key = depth + ':' + sub;
      if (seen.has(key)) continue;
      seen.add(key);
      // An alias that hides a real git command is ignored by git, so a builtin name is never
      // expanded. This mirrors git's own behaviour and keeps `git status` off the subprocess path.
      if (GIT_BUILTINS.has(sub)) continue;
      // Resolution order mirrors git: inline `-c alias.x=y` wins over stored config.
      const inline = effectiveAliases.get(sub);
      let expansion = inline;
      if (expansion === undefined) {
        // R2-CG-11: an environment prefix or global option that changes which config git reads
        // (`HOME=`, `GIT_CONFIG_GLOBAL=`, `--git-dir`, `-c include.path=`) means the stored alias
        // table read here is not the one git will use.
        if (!call.readContextKnown) { aliasesUnresolved = true; continue; }
        expansion = lookupAlias(viaPayload ? call.dirs : orderedDirs, sub);
      }
      if (!expansion) continue;
      if (expansion.startsWith('!')) {
        // `!`-alias: the expansion is a shell command line, so re-analyze it as one. Shell
        // functions defined inside it (`!f() { git push ...; }; f`) are walked through the shared
        // prefix grammar; the caller's operands go to the last top-level statement.
        aliasShellTexts.push(expansion.slice(1));
        // The lexer's statements (which know the last top-level one) plus base's, as for a payload.
        const lexed = scanShell(expansion.slice(1)).statements;
        let last = -1;
        lexed.forEach((st, k) => { if (!st.nested && !st.inBody) last = k; });
        const extra = statementsOf(expansion.slice(1)).filter((st) => !lexed.some((l) => l.text.trim() === st.text.trim()));
        const statements = [...lexed, ...extra];
        for (let k = 0; k < statements.length; k += 1) {
          queue.push({ text: statements[k].text, heredocs: statements[k].heredocs, depth: depth + 1,
            viaPayload, payloadDepth, orderedDirs, inlineConfig, readContextKnown: false,
            extraArgs: k === last ? effectiveArgs : [], stdin });
        }
      } else {
        queue.push({ text: 'git ' + expansion, heredocs: [], depth: depth + 1, viaPayload, payloadDepth,
          orderedDirs, inlineConfig, extraArgs: effectiveArgs, readContextKnown: contextKnown, stdin });
      }
    }
    return { subcommands, texts, payloadTexts, dirs, invocations, aliasShellTexts };
  }

  const lex = { truncated: false };
  const roots = [];
  const shape = allowHeredocShapes ? exactHeredocShape(command) : null;
  if (shape) {
    // `cat`/`tee` writes the body to a file; `git commit -F -` reads it as the message (stdin).
    // There is no message-substitution exception: `git commit -m "$(cat <<'D' ... D)"` ends the
    // heredoc early in every bash since 3.2 and runs the next line, so it is read line by line (R4-1).
    roots.push({ text: shape.opener, heredocs: [{ body: shape.body }], viaPayload: false });
  } else {
    // R3-CG-1: the lexer's statements (substitutions, comments, here-document stdin) AND base's
    // statements (every body line a top-level statement), without exact duplicates.
    for (const st of statementsOf(command, { powershell })) {
      roots.push({ text: st.text, heredocs: st.heredocs, viaPayload: false,
        ...(st.pipedStdins ? { pipedStdins: st.pipedStdins } : {}) });
    }
  }
  const calls = roots
    .map(walk)
    .filter((c) => c.texts.length || c.payloadTexts.length);
  const subcommands = new Set();
  const texts = [];
  const payloadTexts = [];
  const dirs = [];
  const invocations = [];
  const aliasShellTexts = [];
  const dirSeen = new Set();                             // same reason as in walk() above
  // Plain loops, not `push(...list)`: a spread call throws RangeError above about 125k items, and
  // a hook that throws renders no decision (R3-CG-3).
  const append = (target, list) => { for (const item of list) target.push(item); };
  for (const c of calls) {
    for (const sub of c.subcommands) subcommands.add(sub);
    append(texts, c.texts);
    append(payloadTexts, c.payloadTexts);
    append(invocations, c.invocations);
    append(aliasShellTexts, c.aliasShellTexts);
    for (const d of c.dirs) if (!dirSeen.has(d)) { dirSeen.add(d); dirs.push(d); }
  }
  return { subcommands, texts, payloadTexts, dirs, calls, invocations, aliasShellTexts,
    aliasLookupsExhausted: exhausted, aliasesUnresolved, workExhausted, truncated: lex.truncated,
    // Statements a budget dropped unread that could name git (R1-d). Not `unresolved`: the hooks
    // report them, but they do not change a decision.
    skippedReads,
    probedChars, probeLimit: workLimit,
    // Some git subcommand on this line may hide a commit or push that was not resolved.
    unresolved: exhausted || aliasesUnresolved || workExhausted };
}

/**
 * The working directory to run git reads in for a PARTICULAR subcommand — the `-C` chain of the
 * statement that actually invokes it, never a `-C` borrowed from an unrelated statement.
 */
export function targetCwdFor(info, subcommands, baseCwd) {
  return targetCwdsFor(info, subcommands, baseCwd)[0];
}

/**
 * EVERY working directory that a matching subcommand will run in, deduped and in command order.
 *
 * A command line can carry more than one commit — `git -C repoA commit -m ok && git -C repoB
 * commit -m ok2` — and picking only the first match left repoB's staged content completely
 * unscanned while the guard reported clean. A guard has to inspect every repository the command
 * touches, not the first one it happens to name.
 */
export function targetCwdsFor(info, subcommands, baseCwd) {
  const wanted = Array.isArray(subcommands) ? subcommands : [subcommands];
  const matched = (info.calls || []).filter((c) => wanted.some((s) => c.subcommands.has(s)));
  const cwds = matched.map((c) => resolveTargetCwd(baseCwd, c.dirs));
  const seen = new Set();
  const out = [];
  for (const c of cwds) if (!seen.has(c)) { seen.add(c); out.push(c); }
  return out.length ? out : [resolveTargetCwd(baseCwd, [])];
}

/** Subcommands only. Kept as the simple entry point for callers that need nothing else. */
export function resolveGitSubcommands(command, lookup) {
  return resolveGitCommands(command, lookup ? { lookup } : {}).subcommands;
}

// ---------------------------------------------------------------------------------------------
// git commit options, read the way git's parse-options reads them (git 2.43 `git commit -h`):
// short clusters (`-am msg`, `-qFmsg.txt`), attached values, and unique long-option prefixes
// (`--mess x`, `--fil=msg.txt`). Reading only the exact spellings let `--mess '<secret>'` and
// `-Fmsg.txt` commit a message that was never scanned.
// ---------------------------------------------------------------------------------------------
const COMMIT_LONG = {
  quiet: 0, verbose: 0, file: 1, author: 1, date: 1, message: 1, 'reedit-message': 1,
  'reuse-message': 1, fixup: 1, squash: 1, 'reset-author': 0, trailer: 1, signoff: 0, template: 1,
  edit: 0, cleanup: 1, status: 0, 'gpg-sign': 2, all: 0, include: 0, interactive: 0, patch: 0,
  only: 0, 'no-verify': 0, verify: 0, 'dry-run': 0, short: 0, branch: 0, 'ahead-behind': 0,
  porcelain: 0, long: 0, null: 0, amend: 0, 'no-post-rewrite': 0, 'post-rewrite': 0,
  'untracked-files': 2, 'pathspec-from-file': 1, 'pathspec-file-nul': 0, 'allow-empty': 0,
  'allow-empty-message': 0,
};
const COMMIT_SHORT_VALUE = { F: 'file', m: 'message', c: 'reedit-message', C: 'reuse-message', t: 'template' };
const COMMIT_SHORT_OPTIONAL = 'Su';          // -S[<keyid>], -u[<mode>]: attached value only
const COMMIT_SHORT_FLAG = { a: 'all', i: 'include', o: 'only', p: 'patch', n: 'no-verify', z: 'null',
  q: 'quiet', v: 'verbose', s: 'signoff', e: 'edit' };

/**
 * Read git-commit arguments. Returns { messages, files, all, include, only, pathspecs,
 * pathspecFromFile }. Also used over a whole statement (global options included) by the text
 * readers below, where non-option words land in `pathspecs` and are ignored.
 */
export function parseCommitArgs(args) {
  const r = { messages: [], files: [], all: false, include: false, only: false, pathspecs: [],
    pathspecFromFile: false };
  const apply = (key, value, negated) => {
    if (key === 'message' && value !== null && value !== undefined) r.messages.push(value);
    else if (key === 'file' && value !== null && value !== undefined) r.files.push(value);
    else if (key === 'all') r.all = !negated;
    else if (key === 'include') r.include = !negated;
    else if (key === 'only') r.only = !negated;
    else if (key === 'pathspec-from-file') r.pathspecFromFile = !negated;
  };
  let operands = false;
  for (let i = 0; i < args.length; i += 1) {
    const a = String(args[i]);
    if (operands) { r.pathspecs.push(a); continue; }
    if (a === '--') { operands = true; continue; }
    // The two common spellings first; abbreviations and attached values are read below.
    if (a === '-F' || a === '--file') { if (i + 1 < args.length) { r.files.push(args[i + 1]); i += 1; } continue; }
    if (a.startsWith('--') && a.length > 2) {
      const eq = a.indexOf('=');
      const raw = eq < 0 ? a.slice(2) : a.slice(2, eq);
      let value = eq < 0 ? null : a.slice(eq + 1);
      let key = resolveLongOption(COMMIT_LONG, raw);
      let negated = false;
      if (key === null && raw.startsWith('no-')) {
        key = resolveLongOption(COMMIT_LONG, raw.slice(3));
        negated = key !== null;
      }
      if (key === null) continue;
      if (negated) value = null;
      else if (COMMIT_LONG[key] === 1 && value === null) {
        value = i + 1 < args.length ? args[i + 1] : null;
        i += 1;
      }
      apply(key, value, negated);
      continue;
    }
    if (a.length > 1 && a[0] === '-') {
      for (let k = 1; k < a.length; k += 1) {
        const ch = a[k];
        if (Object.prototype.hasOwnProperty.call(COMMIT_SHORT_VALUE, ch)) {
          let value = a.slice(k + 1);
          if (!value) { value = i + 1 < args.length ? args[i + 1] : null; i += 1; }
          apply(COMMIT_SHORT_VALUE[ch], value, false);
          break;
        }
        if (COMMIT_SHORT_OPTIONAL.includes(ch)) break;
        if (Object.prototype.hasOwnProperty.call(COMMIT_SHORT_FLAG, ch)) apply(COMMIT_SHORT_FLAG[ch], null, false);
      }
      continue;
    }
    r.pathspecs.push(a);
  }
  return r;
}

function statementWords(text) {
  return stripRedirections(tokenizeDetailed(text));
}

/**
 * True when this git command sweeps unstaged TRACKED changes into the commit (`-a` / `--all`).
 *
 * Token-aware on purpose: the previous regex test ran over the raw statement, so an ordinary
 * `git commit -m "docs: describe -a flag behavior"` matched the `-a` inside its own MESSAGE and
 * pulled the whole working tree into the scan — a false block driven by prose.
 */
export function commitSweepsUnstaged(text) {
  return topLevelTexts(text).some((seg) => parseCommitArgs(statementWords(stripGroupWrappers(seg))).all);
}

/**
 * Commit message text carried on the command line (`-m`, `-m<msg>`, `--message`, `--message=`,
 * and any unique abbreviation such as `--mess`). The message is part of the commit and git
 * persists it forever, so a secret pasted into it must be scanned exactly like a diff line.
 * Returns the message strings, never the surrounding quotes.
 */
export function commitMessages(command) {
  const out = [];
  // Short options bundle: `git commit -am"<msg>"` and `-qam <msg>` are ordinary git, and `-m`
  // consumes the REST of its cluster as the value.
  for (const seg of topLevelTexts(command)) {
    for (const message of parseCommitArgs(statementWords(seg)).messages) out.push(message);
  }
  return out;
}

/**
 * Paths given to `-F` / `--file` (also `-Fpath`, `--fil=path`), whose contents become the commit
 * message. `-` and `/dev/stdin` mean the statement's stdin; the caller reads that from the
 * resolved invocation, never from disk.
 */
export function commitMessageFiles(command) {
  const out = [];
  for (const seg of topLevelTexts(command)) {
    for (const f of parseCommitArgs(statementWords(seg)).files) if (!isStdinPath(f)) out.push(f);
  }
  return out;
}

/** True when a `-F` value names the commit's stdin rather than a file. */
export function isStdinPath(path) {
  return path === '-' || path === '/dev/stdin' || path === '/dev/fd/0' || path === '/proc/self/fd/0';
}

// ---------------------------------------------------------------------------------------------
// CG-1: index changes made by the same command line before the commit.
// `git add f && git commit -m x` was scanned against the index as it stood BEFORE the add ran, so
// a secret staged by that very add was committed unscanned. A staging statement anywhere on the
// line widens the scan to what it will stage. Order on the line is deliberately not modelled:
// functions, loops and `||` make textual order unreliable, and reading more is the safe direction.
// ---------------------------------------------------------------------------------------------
const ADD_LONG = {
  'dry-run': 0, verbose: 0, interactive: 0, patch: 0, edit: 0, force: 0, update: 0, renormalize: 0,
  'intent-to-add': 0, all: 0, 'ignore-removal': 0, refresh: 0, 'ignore-errors': 0,
  'ignore-missing': 0, sparse: 0, chmod: 1, 'pathspec-from-file': 1, 'pathspec-file-nul': 0,
  'warn-embedded-repo': 0,
};
// Generic option reader: returns { flags: Set of long names (and short letters), operands }.
function readOptions(args, long, shortValue = '', shortNames = {}) {
  const flags = new Set();
  const operands = [];
  let end = false;
  for (let i = 0; i < args.length; i += 1) {
    const a = String(args[i]);
    if (end) { operands.push(a); continue; }
    if (a === '--') { end = true; continue; }
    if (a.startsWith('--') && a.length > 2) {
      const eq = a.indexOf('=');
      const raw = eq < 0 ? a.slice(2) : a.slice(2, eq);
      let key = resolveLongOption(long, raw);
      let negated = false;
      if (key === null && raw.startsWith('no-')) { key = resolveLongOption(long, raw.slice(3)); negated = key !== null; }
      if (key === null) continue;
      if (!negated && long[key] === 1 && eq < 0) i += 1;
      if (negated) flags.delete(key); else flags.add(key);
      continue;
    }
    if (a.length > 1 && a[0] === '-') {
      for (let k = 1; k < a.length; k += 1) {
        const ch = a[k];
        if (shortValue.includes(ch)) { if (k === a.length - 1) i += 1; break; }
        flags.add(shortNames[ch] || ch);
      }
      continue;
    }
    operands.push(a);
  }
  return { flags, operands };
}

// A pathspec carrying an expansion we cannot evaluate stands for "anything".
function knownPaths(paths) {
  return paths.some((p) => /[$`]/.test(p)) ? null : paths;
}

/**
 * What a staging invocation (`add`/`stage`, `apply`) adds to the index, or null when it adds nothing:
 * { paths: string[] | null (every path), untracked, ignored, patches, stdinPatch }.
 */
export function stagingScope(invocation) {
  const sub = invocation.subcommand;
  const args = invocation.args || [];
  if (sub === 'add' || sub === 'stage') {
    const { flags, operands } = readOptions(args, ADD_LONG, '', {
      n: 'dry-run', v: 'verbose', i: 'interactive', p: 'patch', e: 'edit', f: 'force', u: 'update',
      A: 'all', N: 'intent-to-add' });
    if (flags.has('dry-run')) return null;
    const all = flags.has('all') || flags.has('update') || flags.has('pathspec-from-file');
    if (!operands.length && !all) return null;              // "Nothing specified, nothing added."
    return { paths: operands.length && !flags.has('pathspec-from-file') ? knownPaths(operands) : null,
      untracked: !flags.has('update'), ignored: flags.has('force'), patches: [], stdinPatch: false };
  }
  // `rm` (also `--cached`), `mv` and `restore --staged` stage no working-tree content: they drop,
  // rename or reset index entries. Reading their paths' unstaged edits denied cleanup commits for a
  // token that the commit does not record (R2-CG-12).
  if (sub === 'apply') {
    // Any apply on a commit line: `--cached`/`--index` stage the patch, and a plain apply changes
    // the working tree that a later `add` stages. The patch text is read, not the working tree.
    const patches = args.filter((a) => !String(a).startsWith('-'));
    return { paths: [], untracked: false, ignored: false, patches, stdinPatch: !patches.length || patches.includes('-') };
  }
  return null;
}
