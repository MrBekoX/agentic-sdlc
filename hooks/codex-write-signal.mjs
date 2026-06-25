// Pure write-content extractor for the Codex secret-write guard (AP1).
// Given a Codex tool payload (`tool_input.command` for the Bash or apply_patch tool), return the
// newly-written literal content + target paths it can RELIABLY recognize, and a `parsed` flag.
// Pure: string/regex only — no eval, no spawn, no file I/O; the command is treated as data.
//
// Coverage is a deliberately BOUNDED backstop (see the spec): apply_patch V4A added lines, and the
// literal Bash write forms printf/echo with `>`/`>>` redirects and single-quoted (literal) heredocs,
// including those inside compound (`;`/`&&`/`||`) commands and a wrapping subshell. Anything whose
// written value depends on shell expansion (`$VAR`/`${...}`/`$(...)`/backtick), or that is not one
// of these forms (pipe/tee/base64/cp/dd/...), is reported `parsed:false` / empty -> the caller fails
// open. NOT a full shell parser.

const MAX = 512 * 1024;
// Any expansion token: `$` + word/brace/paren, or a backtick. Conservative on purpose (R6a).
const EXPANSION = /\$[\w{(]|`/;

export function extractWrittenContent(toolName, command) {
  const cmd = String(command || '');
  if (!cmd || cmd.length > MAX) return { addedContent: '', targets: [], parsed: false };
  if (toolName === 'apply_patch' || cmd.includes('*** Begin Patch')) return parseApplyPatch(cmd);
  return parseBash(cmd);
}

function parseApplyPatch(cmd) {
  const targets = [];
  const added = [];
  for (const line of cmd.split('\n')) {
    const m = /^\*\*\* (?:Add|Update) File: (.+)$/.exec(line);
    if (m) { targets.push(m[1].trim()); continue; }
    if (/^\*\*\* /.test(line)) continue;                 // *** Begin/End Patch, *** Delete File:
    if (/^@@/.test(line)) continue;                      // hunk header
    if (line.startsWith('+++') || line.startsWith('---')) continue; // unified file markers
    if (line.startsWith('+')) added.push(line.slice(1)); // an added content line
  }
  return { addedContent: added.join('\n'), targets, parsed: true };
}

function parseBash(cmd) {
  const targets = [];
  const added = [];
  // PER-SEGMENT: an expansion-dependent write segment/heredoc contributes NO scannable content (its
  // real value is unknown), but it does NOT poison its literal siblings — a literal write in the same
  // compound command is still extracted and scanned. `hasExpansion` is informational (the command was
  // not fully literal) for the caller's clean-vs-not-checkable distinction; it does not blank `added`.
  let hasExpansion = false;

  // 1) Heredocs FIRST — capture the body intact (newlines preserved) BEFORE any boundary split, so
  //    the heredoc's own newlines never reach the segmenter, then blank the window out.
  const heredocRe = /<<\s*(['"]?)([A-Za-z_]\w*)\1([^\n]*)\n([\s\S]*?)\n\2(?=\n|$)/g;
  const work = cmd.replace(heredocRe, (full, q, _delim, rest, body) => {
    const literal = q === "'";                 // single-quoted delimiter => no expansion of the body
    const tgt = /(?:>>?)\s*(\S+)/.exec(rest);
    if (!literal && EXPANSION.test(body)) { hasExpansion = true; }
    else { if (tgt) targets.push(tgt[1]); added.push(body); }
    return ' ';
  });

  // 2) Segment on statement boundaries (quote-aware): ; && || | — NOT on \n (heredocs gone) and not
  //    structurally on (){}; strip a wrapping subshell so an in-subshell redirect is still seen.
  for (let seg of splitSegments(work)) {
    seg = seg.trim().replace(/^\(\s*/, '').replace(/\s*\)$/, '').trim();
    if (!seg || /^cd\b/.test(seg)) continue;            // a `cd` prefix is not a write
    if (!/(?:>>?)\s*\S+\s*$/.test(seg)) continue;        // no trailing redirect -> not a recognized write
    const m = /^(?:printf|echo)\b\s+([\s\S]*?)\s*>>?\s*(\S+)\s*$/.exec(seg);
    if (!m) continue;                                    // only printf/echo literal redirects are recognized
    const payload = m[1].trim();
    if (EXPANSION.test(payload)) { hasExpansion = true; continue; } // expansion segment: no content, siblings survive
    const lit = extractLiteral(payload);
    if (lit === null) continue;
    targets.push(m[2]);
    added.push(lit);
  }

  return { addedContent: added.join('\n'), targets, parsed: !hasExpansion };
}

// Quote-aware split on ; && || and single |. Does not split inside single/double quotes.
function splitSegments(s) {
  const segs = [];
  let cur = '';
  let q = null;
  for (let i = 0; i < s.length; i += 1) {
    const c = s[i];
    const n = s[i + 1];
    if (q) { cur += c; if (c === q) q = null; continue; }
    if (c === "'" || c === '"') { q = c; cur += c; continue; }
    if (c === ';') { segs.push(cur); cur = ''; continue; }
    if (c === '&' && n === '&') { segs.push(cur); cur = ''; i += 1; continue; }
    if (c === '|' && n === '|') { segs.push(cur); cur = ''; i += 1; continue; }
    if (c === '|') { segs.push(cur); cur = ''; continue; }
    cur += c;
  }
  if (cur) segs.push(cur);
  return segs;
}

// Read the printf/echo payload literal: a single- or double-quoted string, or a bare word.
// Returns null if it is not a single clean literal we can read (expansion is filtered upstream).
function extractLiteral(payload) {
  if (payload[0] === "'") {
    const end = payload.indexOf("'", 1);
    return end === -1 ? null : payload.slice(1, end);
  }
  if (payload[0] === '"') {
    const end = payload.indexOf('"', 1);
    return end === -1 ? null : payload.slice(1, end);
  }
  if (!/\s/.test(payload)) return payload;   // bare single-token word (e.g. `printf clean`)
  return null;
}
