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
