// Shared command-PREFIX grammar for the resolvers in destructive-command-guard.mjs and
// git-invocation.mjs.
//
// POSIX Shell & Utilities 2.9.1 closes the production that may sit in front of a command name:
//
//   simple_command := cmd_prefix* [ cmd_word cmd_suffix* ]
//   cmd_prefix     := io_redirect | ASSIGNMENT_WORD
//
// plus bash's reserved words and `!`. Because the language fixes that set, this is a positive
// grammar and it is complete - unlike a wrapper table ("programs that run another program"),
// which no specification bounds and which therefore stays an open-ended deny-list in each
// caller.
//
// It lives here because the two resolvers walked off DIFFERENT subsets of it, and every
// resulting bypass was the same mechanical failure: the first token was a prefix construct, so
// the real command was never examined. One source means they cannot diverge again.
//
// Pure string work: no I/O, no subprocess, no state.

// Reserved words that may legally precede a command word.
export const RESERVED_WORDS = new Set([
  'if', 'then', 'elif', 'else', 'fi',
  'for', 'while', 'until', 'select', 'do', 'done',
  'case', 'esac', 'function', 'coproc', 'exec',
  '{', '}', '!', '[[', ']]',
]);

// An ASSIGNMENT_WORD: NAME=value with a portable shell NAME. One linear scan -- deliberately
// not a regex with a quantifier before an anchor (see lessons.md 2026-07-01 / 2026-08-22).
export function isAssignmentWord(token) {
  const eq = token.indexOf('=');
  if (eq <= 0) return false;
  for (let i = 0; i < eq; i += 1) {
    const c = token[i];
    if (i === 0 && c >= '0' && c <= '9') return false;
    const ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
      || (c >= '0' && c <= '9') || c === '_';
    if (!ok) return false;
  }
  return true;
}

// Length of the io_redirect OPERATOR at the head of a token, or 0. Covers `>`, `>>`, `<`,
// `<>`, `>|`, `>&`, a leading fd (`2>`), and the `&>` family. A return value shorter than
// the token means the target is attached (`>/tmp/x`, `2>&1`) and no following word is
// consumed; equal to the token length means the target is the next word (`> /tmp/x`).
export function redirectOperatorLength(token) {
  let i = 0;
  while (i < token.length && token[i] >= '0' && token[i] <= '9') i += 1;
  if (i === 0 && token[0] === '&' && token[1] === '>') i = 1;
  if (i >= token.length) return 0;
  if (token[i] !== '>' && token[i] !== '<') return 0;
  // `<<<` (here-string) and `<<-` (tab-stripping here-document) are three-character operators.
  // Read as `<<` plus an attached target, `<<< word` left `word` behind as an argument.
  if (token[i] === '<' && token[i + 1] === '<' && (token[i + 2] === '<' || token[i + 2] === '-')) {
    return i + 3;
  }
  let j = i + 1;
  if (token[j] === '>' || token[j] === '<' || token[j] === '|' || token[j] === '&') j += 1;
  return j;
}

// A function-definition header word: `name()`. Bash accepts almost any non-metacharacter text as
// a function name, so this only rejects what cannot be one. Linear: one scan, no regex.
function isFunctionHeader(token) {
  if (token.length < 3 || !token.endsWith('()')) return false;
  for (let k = 0; k < token.length - 2; k += 1) {
    const c = token[k];
    if (c === '(' || c === ')' || c === '$' || c === '`' || c === '"' || c === "'" || c === '='
      || c === '<' || c === '>' || c === ';' || c === '&' || c === '|' || c === ' ' || c === '\t') {
      return false;
    }
  }
  return true;
}

function isFunctionName(token) {
  return isFunctionHeader(token + '()');
}

// bash's `exec [-cl] [-a name] [--]`: its own option grammar is fixed by the builtin, so it belongs
// here with the reserved words. Returns the index after exec's options.
function skipExecOptions(tokens, start) {
  let i = start;
  while (i < tokens.length) {
    const t = tokens[i];
    if (t === '--') return i + 1;
    if (t.length < 2 || t[0] !== '-') return i;
    let valueNext = false;
    for (let k = 1; k < t.length; k += 1) {
      const c = t[k];
      if (c === 'c' || c === 'l') continue;
      if (c === 'a') { valueNext = k === t.length - 1; break; }  // -a NAME, or -aNAME attached
      return i;                                                   // not an exec option
    }
    i += valueNext ? 2 : 1;
  }
  return i;
}

// Walk off one run of cmd_prefix tokens. Returns the index of the first token that is not a
// prefix construct. Linear in the number of tokens examined.
export function skipCommandPrefix(tokens, start) {
  let i = start;
  while (i < tokens.length) {
    const raw = tokens[i];
    if (raw.toLowerCase() === 'case') {
      // `case WORD in PATTERN) <command>`: the selector and the pattern list sit between the
      // keyword and the command, and the pattern ends at a `)`. Bounded, and only applied
      // when that `)` is actually found - otherwise this is not a case arm and nothing is
      // consumed, so an unbalanced `)` in ordinary text can never eat a command.
      let j = i + 1;
      const limit = Math.min(tokens.length, i + 9);
      while (j < limit && !tokens[j].endsWith(')')) j += 1;
      if (j < limit && tokens[j].endsWith(')')) { i = j + 1; continue; }
    }
    const lower = raw.toLowerCase();
    // `exec -a NAME cmd` / `exec -cl cmd`: exec's own options sit between it and the command.
    if (lower === 'exec') { i = skipExecOptions(tokens, i + 1); continue; }
    // A function DEFINITION runs its body when called: `f() { git commit ...; }; f`. The header
    // (`name()`, `name ()` or `function name [()]`) is walked off so the body is examined.
    if (lower === 'function' && i + 1 < tokens.length && isFunctionName(tokens[i + 1])) {
      i += 2;
      if (tokens[i] === '()') i += 1;
      continue;
    }
    if (isFunctionHeader(raw)) { i += 1; continue; }
    if (tokens[i + 1] === '()' && isFunctionName(raw)) { i += 2; continue; }
    if (RESERVED_WORDS.has(lower)) { i += 1; continue; }
    if (isAssignmentWord(raw)) { i += 1; continue; }
    const op = redirectOperatorLength(raw);
    if (op > 0) {
      // Attached target (`>/tmp/x`, `2>&1`) consumes only this token; a bare operator
      // (`>`, `2>`) consumes the following word as its target.
      i += op < raw.length ? 1 : 2;
      continue;
    }
    break;
  }
  return i;
}
