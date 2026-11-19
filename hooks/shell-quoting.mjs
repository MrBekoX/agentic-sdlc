// Shell quoting helpers shared by the command guards. PURE: string operations only — no eval, no
// spawn, no file I/O — so `codex-write-signal.mjs` can import it without breaking its own contract.
//
// WHY: bash's ANSI-C quoting `$'...'` decodes escape sequences BEFORE the command runs, so the
// bytes git records (or the shell writes to a file) are not the bytes in `tool_input.command`.
// A guard that reads the raw token sees `$'\x73\x6b\x2dlive\x2d…'` and finds no vendor-shaped
// token, while the commit message / file actually contains `sk-live-…`. Verified by execution:
// both the commit-message scan and the write extractor missed it, and the write extractor also
// reported `parsed:true`, claiming coverage it did not have.

const SIMPLE = {
  a: '\u0007', b: '\b', e: '\u001b', E: '\u001b', f: '\f', n: '\n',
  r: '\r', t: '\t', v: '\v', '\\': '\\', "'": "'", '"': '"', '?': '?',
};

/**
 * Decode the BODY of an ANSI-C quoted string (the text between `$'` and its closing `'`),
 * following bash's documented escape set. Single pass, no backtracking.
 */
export function decodeAnsiC(body) {
  const s = String(body ?? '');
  let out = '';
  for (let i = 0; i < s.length; i += 1) {
    if (s[i] !== '\\' || i + 1 >= s.length) { out += s[i]; continue; }
    const c = s[i + 1];
    if (Object.prototype.hasOwnProperty.call(SIMPLE, c)) { out += SIMPLE[c]; i += 1; continue; }
    if (c === 'x') {                                    // \xHH (1-2 hex digits)
      const m = /^[0-9A-Fa-f]{1,2}/.exec(s.slice(i + 2));
      if (m) { out += String.fromCharCode(parseInt(m[0], 16)); i += 1 + m[0].length; continue; }
    }
    if (c === 'u' || c === 'U') {                       // \uHHHH / \UHHHHHHHH
      const width = c === 'u' ? 4 : 8;
      const m = new RegExp('^[0-9A-Fa-f]{1,' + width + '}').exec(s.slice(i + 2));
      if (m) {
        const cp = parseInt(m[0], 16);
        if (cp <= 0x10ffff) { out += String.fromCodePoint(cp); i += 1 + m[0].length; continue; }
      }
    }
    if (c >= '0' && c <= '7') {                         // \nnn octal (1-3 digits)
      const m = /^[0-7]{1,3}/.exec(s.slice(i + 1));
      if (m) { out += String.fromCharCode(parseInt(m[0], 8) & 0xff); i += m[0].length; continue; }
    }
    out += c;                                            // unknown escape: drop the backslash
    i += 1;
  }
  return out;
}

/**
 * Rewrite every `$'...'` span in a command string to its decoded, single-quoted equivalent, so a
 * downstream tokenizer that knows nothing about ANSI-C quoting still sees the REAL bytes.
 * Any embedded `'` in the decoded text is re-escaped so the span stays one token.
 * Linear scan; the inner loop only ever advances.
 */
export function expandAnsiCQuotes(command) {
  const s = String(command ?? '');
  let out = '';
  let i = 0;
  while (i < s.length) {
    if (s[i] === '$' && s[i + 1] === "'") {
      let j = i + 2;
      let body = '';
      let closed = false;
      while (j < s.length) {
        if (s[j] === '\\' && j + 1 < s.length) { body += s[j] + s[j + 1]; j += 2; continue; }
        if (s[j] === "'") { closed = true; j += 1; break; }
        body += s[j];
        j += 1;
      }
      if (!closed) { out += s.slice(i); break; }        // unterminated: leave the rest verbatim
      out += "'" + decodeAnsiC(body).split("'").join("'\\''") + "'";
      i = j;
      continue;
    }
    if (s[i] === '"') {                                  // ANSI-C quotes are inert inside "..."
      let j = i + 1;
      while (j < s.length) {
        if (s[j] === '\\' && j + 1 < s.length) { j += 2; continue; }
        if (s[j] === '"') { j += 1; break; }
        j += 1;
      }
      out += s.slice(i, j);
      i = j;
      continue;
    }
    if (s[i] === "'") {                                  // ordinary single-quoted span: copy as-is
      const end = s.indexOf("'", i + 1);
      if (end === -1) { out += s.slice(i); break; }
      out += s.slice(i, end + 1);
      i = end + 1;
      continue;
    }
    out += s[i];
    i += 1;
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// Shell statement lexer shared by the command guards.
//
// WHY: both resolvers read a command line one statement at a time, and two shell constructs made
// that reading wrong in opposite directions:
//   * A here-document BODY can be data. Splitting it on newlines turned `cat > notes.md <<'EOF'`
//     plus a body line naming a recursive delete into a denied command, and a release note that
//     mentions `git push origin main` into a denied push. But a body fed to a shell, `eval`, `make`
//     or a file that is run later is a script, and an UNQUOTED body still runs `$(...)` and
//     backticks. This lexer only reports the bodies. No caller removes one from what it checks
//     (R3-CG-1): the guards read every body line as a command, as base did, and use this lexer's
//     reading only IN ADDITION (statements after a body, substitutions, comment boundaries).
//   * A command SUBSTITUTION (`$(...)`, backticks, `<(...)`) is a command. `out=$(git commit ...)`
//     reached the git resolver as one statement whose first word is an assignment, so the commit
//     inside was never seen.
//
// One linear pass reads quotes, ANSI-C quotes, escapes, comments, substitutions (recursively),
// arithmetic and parameter expansions (where `<<` is a shift, not a here-document) and
// here-document operators, and returns:
//   statements - every statement, split on `;`, `&&`, `||`, `|`, `&` and newlines (a redirect `&`
//                such as `2>&1` does not split), each with the here-documents it opened. Statements
//                inside substitutions are marked `nested`; statements found by expanding an
//                unquoted here-document body are marked `inBody`. A statement's text is a slice of
//                the input, so a substitution inside it stays verbatim (and a here-document body
//                inside that substitution stays with it, which is what a commit message written
//                as `-m "$(cat <<'EOF' ... EOF)"` needs). A trailing comment is not part of it.
//                Parentheses and braces do NOT split: the git resolver must read `git`, its
//                global options and its subcommand as one unit (lessons.md, 2026-09-21).
//                Each statement also carries `start`/`end` (offsets), `sep` (the separator that
//                ended it: `|`, `;`, `&&`, a newline, ...), `depth` and `region` (which command
//                region it belongs to), so a caller can follow a pipeline. A here-document carries
//                `start`/`end` (its body range) and `uncertain` when its delimiter word holds an
//                expansion the lexer reads only approximately (`<<$(x)`, `<<$'EOF'`).
//   stripped   - the input with every here-document body and its delimiter line removed.
//   bodyRanges, commentRanges - [start, end) offsets of here-document bodies and of comments.
//   truncated  - nesting deeper than MAX_LEX_DEPTH was read as plain text.
//
// Where this lexer and bash could disagree, it errs toward reading MORE as a command: a body ends
// at the first line that matches its delimiter after leading tabs and a trailing CR are dropped,
// which is never later than bash ends it. Linear: every character is read by exactly one frame,
// and recursion is capped.
// ---------------------------------------------------------------------------------------------

const MAX_LEX_DEPTH = 32;

// Only space and tab separate words in bash. A carriage return is an ordinary character, so
// `echo hi\r#; git push` is `echo` with the word `hi\r#`, followed by a push - not a comment
// (R2-CG-5: counting CR as a blank hid the push behind a comment that bash never sees).
function isBlank(c) {
  return c === ' ' || c === '\t';
}

// Characters after which the next character starts a new word.
function endsWord(c) {
  return c === undefined || isBlank(c) || c === '\n' || c === ';' || c === '&' || c === '|'
    || c === '(' || c === ')' || c === '<' || c === '>';
}

// True when an `&` belongs to a redirect operator (`2>&1`, `<&0`, `&>log`, `&>>log`) rather than
// separating two statements; splitting there left a fragment starting with a bare fd digit. An
// ESCAPED `>` is literal text, not an operator: `echo a\> & git commit ...` is two statements.
// Takes the last non-blank character and whether it was escaped as SCALARS carried by the scan.
// An earlier splitter scanned backward over its accumulating segment: the loop body was O(1),
// but indexing a string built by `+=` forces V8 to flatten the rope that `+=` then rebuilds, so a
// shape where every `&` runs the check was quadratic - 13.6 s at 512 KB, past the hook budget
// (lessons.md 2026-09-21). Statements here are slices, so nothing is accumulated at all.
function ampersandIsRedirectAt(next, lastNonSpace, lastWasEscaped) {
  if (next === '>') return true;
  if (lastNonSpace !== '>' && lastNonSpace !== '<') return false;
  return !lastWasEscaped;
}

function skipSingleQuoted(s, i, end) {
  const close = s.indexOf("'", i);
  return close < 0 || close >= end ? end : close + 1;
}

function skipAnsiC(s, i, end) {
  while (i < end) {
    if (s[i] === '\\') { i += 2; continue; }
    if (s[i] === "'") return i + 1;
    i += 1;
  }
  return end;
}

// Read a here-document operator at `i` (pointing at `<<`). Returns { next, heredoc|null }.
function readHeredocOperator(s, i, end) {
  let j = i + 2;
  let strip = false;
  if (s[j] === '-') { strip = true; j += 1; }
  while (j < end && (s[j] === ' ' || s[j] === '\t')) j += 1;
  let delim = '';
  let quoted = false;
  let uncertain = false;
  while (j < end) {
    const c = s[j];
    if (c === "'") {
      quoted = true;
      const close = s.indexOf("'", j + 1);
      const stop = close < 0 || close >= end ? end : close;
      delim += s.slice(j + 1, stop);
      j = stop + 1;
      continue;
    }
    if (c === '"') {
      quoted = true;
      j += 1;
      while (j < end && s[j] !== '"') {
        if (s[j] === '\\' && j + 1 < end) { delim += s[j + 1]; j += 2; continue; }
        delim += s[j];
        j += 1;
      }
      j += 1;
      continue;
    }
    if (c === '\\') {
      quoted = true;
      if (j + 1 < end) delim += s[j + 1];
      j += 2;
      continue;
    }
    if (c === '(' || c === ')') { uncertain = true; break; }
    if (isBlank(c) || c === '\r' || c === '\n' || c === ';' || c === '&' || c === '|' || c === '<'
      || c === '>') break;
    // bash takes the delimiter as a whole shell word without expanding it (`<<$(x)` ends at a
    // line `$(x)`, `<<$'EOF'` is ANSI-C quoted). Those are read only approximately here.
    if (c === '$' || c === '`') uncertain = true;
    delim += c;
    j += 1;
  }
  const next = Math.min(j, end);
  if (!delim) return { next, heredoc: null };
  return { next, heredoc: { body: '', quoted, strip, delim, uncertain } };
}

// Consume the bodies of every pending here-document, starting at `i` (the first character after
// the newline that ended the operator's line). Returns the index after the last body.
function consumeHeredocBodies(ctx, i, end, depth) {
  const s = ctx.s;
  const list = ctx.pending;
  ctx.pending = [];
  for (const h of list) {
    const bodyStart = i;
    let lineStart = i;
    let found = false;
    while (lineStart < end) {
      const nl = s.indexOf('\n', lineStart);
      const lineEnd = nl < 0 || nl >= end ? end : nl;
      let line = s.slice(lineStart, lineEnd);
      if (line.endsWith('\r')) line = line.slice(0, -1);
      let k = 0;
      while (k < line.length && line[k] === '\t') k += 1;
      if (line === h.delim || line.slice(k) === h.delim) {
        h.body = s.slice(bodyStart, lineStart);
        i = lineEnd < end ? lineEnd + 1 : end;
        found = true;
        break;
      }
      lineStart = lineEnd < end ? lineEnd + 1 : end;
    }
    if (!found) { h.body = s.slice(bodyStart, end); i = end; }
    h.start = bodyStart;
    h.end = i;
    ctx.bodyRanges.push([bodyStart, i]);
  }
  // An unquoted body is expanded: its `$(...)` and backticks run. Read them now, each body with a
  // fresh pending list so a here-document inside one cannot consume another's lines.
  for (const h of list) {
    if (h.quoted) continue;
    ctx.inBody += 1;
    scanExpansionText(ctx, h.start, h.start + h.body.length, depth);
    ctx.inBody -= 1;
  }
  return i;
}

// Text in which only expansions are live: an unquoted here-document body (no `close`), or the
// inside of `${...}` / `$[...]` (`close` is the character that ends it, `open` nests it).
function scanExpansionText(ctx, start, end, depth, close = '', open = '') {
  const s = ctx.s;
  let i = start;
  let level = 0;
  while (i < end) {
    const c = s[i];
    if (c === '\\') { i += 2; continue; }
    if (close && (c === "'" || c === '"')) {
      i = c === "'" ? skipSingleQuoted(s, i + 1, end) : scanDoubleQuoted(ctx, i + 1, end, depth);
      continue;
    }
    const sub = enterExpansion(ctx, i, end, depth);
    if (sub >= 0) { i = sub; continue; }
    if (close) {
      if (c === open) level += 1;
      else if (c === close) {
        if (level === 0) return i + 1;
        level -= 1;
      }
    }
    i += 1;
  }
  return end;
}

// Inside "...": escapes, and the expansions bash performs there.
function scanDoubleQuoted(ctx, start, end, depth) {
  const s = ctx.s;
  let i = start;
  while (i < end) {
    const c = s[i];
    if (c === '\\') { i += 2; continue; }
    if (c === '"') return i + 1;
    const sub = enterExpansion(ctx, i, end, depth);
    if (sub >= 0) { i = sub; continue; }
    i += 1;
  }
  return end;
}

// If an expansion starts at `i`, read it and return the index after it; otherwise -1. At the
// depth cap the opener is skipped as plain text and `ctx.truncated` is set.
function enterExpansion(ctx, i, end, depth) {
  const s = ctx.s;
  const c = s[i];
  const n1 = s[i + 1];
  if (c === '`') return enterCommands(ctx, i + 1, end, 'backtick', depth);
  if (c !== '$') return -1;
  if (n1 === '(') {
    if (s[i + 2] === '(') return enterCommands(ctx, i + 3, end, 'arith', depth);
    return enterCommands(ctx, i + 2, end, 'paren', depth);
  }
  if (n1 === '{' || n1 === '[') {
    if (depth + 1 > MAX_LEX_DEPTH) { ctx.truncated = true; return i + 2; }
    return scanExpansionText(ctx, i + 2, end, depth + 1, n1 === '{' ? '}' : ']', n1);
  }
  return -1;
}

function enterCommands(ctx, start, end, mode, depth) {
  if (depth + 1 > MAX_LEX_DEPTH) { ctx.truncated = true; return start; }
  return scanCommands(ctx, start, end, mode, depth + 1);
}

// A command region: the top level, `$( )`, `<( )`, backticks, or arithmetic `$(( ))` / `(( ))`.
// Arithmetic is read as a command region too (bash re-reads `$((cmd) )` as a substitution when it
// is not arithmetic), but with here-documents and comments off: there `<<` is a shift.
function scanCommands(ctx, start, end, mode, depth) {
  const s = ctx.s;
  const arith = mode === 'arith';
  const closesOnParen = mode === 'paren' || arith;
  let i = start;
  let segStart = start;
  let segEnd = -1;
  let heredocs = [];
  let wordStart = true;
  let lastNonSpace = '';
  let lastWasEscaped = false;
  let level = arith ? 1 : 0;                     // unclosed `(` inside this region
  ctx.regions = (ctx.regions || 0) + 1;
  const region = ctx.regions;
  const flush = (stop, sep = '') => {
    if (segEnd >= 0) ctx.commentRanges.push([segEnd, stop]);
    const stopAt = segEnd >= 0 ? segEnd : stop;
    const text = s.slice(segStart, stopAt);
    if (text.trim() || heredocs.length) {
      ctx.statements.push({ text, heredocs, nested: depth > 0, inBody: ctx.inBody > 0, depth, region,
        start: segStart, end: stopAt, sep });
    }
    heredocs = [];
    segEnd = -1;
    lastNonSpace = '';
    lastWasEscaped = false;
    wordStart = true;
  };
  const mark = (c, escaped = false) => {
    if (!isBlank(c)) { lastNonSpace = c; lastWasEscaped = escaped; }
  };
  while (i < end) {
    const c = s[i];
    const n1 = s[i + 1];
    if (segEnd >= 0 && c !== '\n') { i += 1; continue; }          // inside a trailing comment
    if (c === '#' && wordStart && !arith) { segEnd = i; i += 1; continue; }
    if (c === '\\') {
      mark(n1 === undefined ? c : n1, true);
      wordStart = false;
      i += 2;
      continue;
    }
    if (c === "'") { i = skipSingleQuoted(s, i + 1, end); mark("'"); wordStart = false; continue; }
    if (c === '$' && n1 === "'") { i = skipAnsiC(s, i + 2, end); mark("'"); wordStart = false; continue; }
    if (c === '"') { i = scanDoubleQuoted(ctx, i + 1, end, depth); mark('"'); wordStart = false; continue; }
    if (c === '`' && mode === 'backtick') { flush(i, '`'); return i + 1; }
    const sub = enterExpansion(ctx, i, end, depth);
    if (sub >= 0) {
      // At the depth cap the opener was skipped as text; keep this region's parentheses balanced.
      if (ctx.truncated && c === '$' && n1 === '(' && (sub === i + 2 || sub === i + 3)) {
        level += sub - i - 1;
      }
      i = sub;
      mark(')');
      wordStart = false;                                    // an expansion is part of a word
      continue;
    }
    if ((c === '<' || c === '>') && n1 === '(') {           // process substitution
      const next = enterCommands(ctx, i + 2, end, 'paren', depth);
      if (next === i + 2) level += 1;
      i = next;
      mark(')');
      wordStart = false;
      continue;
    }
    if (c === '(' && n1 === '(' && wordStart && !arith) {   // arithmetic command (( ... ))
      const next = enterCommands(ctx, i + 2, end, 'arith', depth);
      i = next;
      mark(')');
      wordStart = true;                   // `))` is an operator: `((1))#x` starts a comment
      continue;
    }
    if (closesOnParen) {
      if (c === '(') { level += 1; mark(c); wordStart = true; i += 1; continue; }
      if (c === ')') {
        if (level === 0) { flush(i, ')'); return i + 1; }
        level -= 1;
        mark(c);
        wordStart = true;                 // `)` is a metacharacter: a new word follows
        i += 1;
        continue;
      }
    }
    if (c === '<' && n1 === '<' && !arith) {
      if (s[i + 2] === '<') { i += 3; mark('<'); wordStart = true; continue; }   // here-string
      const op = readHeredocOperator(s, i, end);
      if (op.heredoc) { heredocs.push(op.heredoc); ctx.pending.push(op.heredoc); }
      i = op.next;
      mark('x');
      wordStart = false;
      continue;
    }
    if (c === '\n') {
      flush(i, '\n');
      i += 1;
      if (ctx.pending.length) i = consumeHeredocBodies(ctx, i, end, depth);
      segStart = i;
      continue;
    }
    if (c === ';') { flush(i, ';'); i += 1; segStart = i; continue; }
    if ((c === '&' || c === '|') && n1 === c) { flush(i, c + c); i += 2; segStart = i; continue; }
    if (c === '&' && ampersandIsRedirectAt(n1, lastNonSpace, lastWasEscaped)) {
      mark(c);
      wordStart = false;
      i += 1;
      continue;
    }
    if (c === '|' || c === '&') { flush(i, c); i += 1; segStart = i; continue; }
    mark(c);
    wordStart = endsWord(c);
    i += 1;
  }
  flush(end);
  return end;
}

function stripRanges(s, ranges) {
  if (!ranges.length) return s;
  const sorted = ranges.slice().sort((a, b) => a[0] - b[0]);
  let out = '';
  let at = 0;
  for (const [a, b] of sorted) {
    if (b <= at) continue;                         // inside a range already removed
    if (a > at) out += s.slice(at, a);
    at = Math.max(at, b);
  }
  return out + s.slice(at);
}

/**
 * The index just past the expansion that starts at `i` - `$(...)`, `$((...))`, `${...}`, `$[...]`,
 * a backtick pair, or a process substitution `<(...)` / `>(...)` - read with the same rules as
 * scanShell, or -1 when none starts there. Used by tokenizers that keep an expansion inside the
 * word that contains it.
 */
export function expansionEnd(text, i) {
  const s = String(text ?? '');
  const ctx = { s, statements: [], pending: [], bodyRanges: [], commentRanges: [], truncated: false, inBody: 0 };
  if ((s[i] === '<' || s[i] === '>') && s[i + 1] === '(') return enterCommands(ctx, i + 2, s.length, 'paren', 0);
  return enterExpansion(ctx, i, s.length, 0);
}

/** Lex a shell command line. See the block comment above for the result shape. */
export function scanShell(text) {
  const s = String(text ?? '');
  const ctx = { s, statements: [], pending: [], bodyRanges: [], commentRanges: [], truncated: false, inBody: 0 };
  scanCommands(ctx, 0, s.length, 'top', 0);
  return { statements: ctx.statements, stripped: stripRanges(s, ctx.bodyRanges), truncated: ctx.truncated,
    bodyRanges: ctx.bodyRanges, commentRanges: ctx.commentRanges };
}
