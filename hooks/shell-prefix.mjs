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
  let j = i + 1;
  if (token[j] === '>' || token[j] === '<' || token[j] === '|' || token[j] === '&') j += 1;
  return j;
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
    if (RESERVED_WORDS.has(raw.toLowerCase())) { i += 1; continue; }
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
