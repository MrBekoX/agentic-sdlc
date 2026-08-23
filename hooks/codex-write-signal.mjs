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
//
// `parsed` means "this extractor accounted for the whole command", and its honest default is FALSE.
// It used to be computed as `!hasExpansion`, which only ever meant "I saw no `$` or backtick": every
// "I do not recognize this form" path was a bare `continue` that left the flag true, so `tee`, `dd`,
// `sed -i`, `cp`, `>|` and `&>` all reported parsed:true with empty content. That is the OWASP
// "fail securely" anti-pattern (CWE-636): an optimistic initial value that survives every path that
// failed to disprove it. Recognition is now under-approximated and content is over-approximated —
// the two must go in opposite directions for a scanner to be safe.

import { expandAnsiCQuotes, decodeAnsiC } from './shell-quoting.mjs';

const MAX = 512 * 1024;
// Any expansion token: `$` + word/brace/paren, or a backtick. Conservative on purpose (R6a).
const EXPANSION = /\$[\w{(]|`/;
// Write-capable forms this extractor deliberately does NOT read. Matching one does not change what
// is scanned (nothing is readable from them); it only stops `parsed` from claiming coverage we do
// not have. Bounded character classes only — every quantifier here is linear (no ReDoS surface).
// NB the sed clause covers BOTH the short option (`sed -i`, `sed -ni`) and the GNU long form
// (`sed --in-place`, `sed --in-place=.bak`). Matching only `-[A-Za-z]*i` let `--in-place`
// through, which put the exact CWE-636 shape back: an unread write reporting parsed:true.
const UNREAD_WRITE = /(?:^|\s)(?:tee|dd|cp|mv|install|truncate|split|base64|sponge)\b|(?:^|\s)sed\b[^|;&]{0,200}?(?:\s--in-place\b|\s-[A-Za-z]{0,8}i\b)|\s(?:&>>?|>\||\d{1,3}>|>&\d{1,3})/;

export function extractWrittenContent(toolName, command) {
  // Decode `$'...'` up front. Bash substitutes those escapes before the write happens, so
  // `echo $'\x73\x6b\x2dlive\x2d…' > f` really puts `sk-live-…` on disk while the raw token carries
  // no vendor-shaped text at all — and `$'` is not an expansion, so the extractor happily called
  // the segment literal and returned parsed:true over content that was never going to be written.
  const cmd = expandAnsiCQuotes(String(command || ''));
  if (!cmd || cmd.length > MAX) return { addedContent: '', targets: [], parsed: false };
  if (toolName === 'apply_patch' || cmd.includes('*** Begin Patch')) return parseApplyPatch(cmd);
  return parseBash(cmd);
}

function parseApplyPatch(cmd) {
  const targets = [];
  const added = [];
  // Split on CRLF *or* LF and drop the carriage return. Codex's own V4A parser accepts CRLF and
  // mixed endings (its fixtures 023/024 pin that), and Codex on Windows produces them. Splitting on
  // '\n' alone leaves a trailing '\r' on every line, and in JS `.` does not match '\r' (it is a line
  // terminator), so `/^\*\*\* Add File: (.+)$/` failed to match and EVERY target was dropped — the
  // deny message lost the path, and flow-order-guard-codex.mjs, which consumes these targets as its
  // current-edit set, saw no edit at all and failed open. Verified against an unmodified checkout,
  // so this is a pre-existing defect, not a regression from the write-content fix.
  for (const line of cmd.split(/\r?\n/)) {
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
  // Recognition is UNDER-approximated: this stays false only while every segment was either a
  // non-write or a write form we fully read. Any unread write form flips it and clears `parsed`.
  let unreadWrite = false;

  // 1) Heredocs FIRST — capture the body intact (newlines preserved) BEFORE any boundary split, so
  //    the heredoc's own newlines never reach the segmenter, then blank the window out.
  // ReDoS guard: the heredoc body `[\s\S]*?` scans to end for every UNTERMINATED `<<` opener, which is
  // O(n^2) in opener count — a crafted command of thousands of `<<EOF` openers (within the 512 KiB cap)
  // would hang the secret scanner past its hook timeout (a default-reachable DoS/bypass). A real command
  // has at most a handful of heredocs, so if there are absurdly many `<<` openers we skip heredoc parsing
  // entirely (the command is then handled by the redirect/segment path; its heredoc bodies are not
  // scanned — accepted within the bounded-backstop posture, and far better than a timeout-then-allow).
  const HEREDOC_OPENER_CAP = 24;
  const openerCount = (cmd.match(/<</g) || []).length;
  // `<<-` (tab-stripping) is as common as `<<`. Matching only `<<\s*` left `cat <<-EOF > f` both
  // unread AND unflagged: no substitution happened, the segment's trailing text was the closing
  // delimiter rather than a redirect, and no UNREAD_WRITE token appeared -> parsed:true with empty
  // content. The same CWE-636 shape as `sed --in-place`, one review round later.
  const heredocRe = /<<-?\s*(['"]?)([A-Za-z_]\w*)\1([^\n]*)\n([\s\S]*?)\n\2(?=\n|$)/g;
  const work = openerCount > HEREDOC_OPENER_CAP ? cmd : cmd.replace(heredocRe, (full, q, _delim, rest, body) => {
    const literal = q === "'";                 // single-quoted delimiter => no expansion of the body
    const tgt = /(?:>>?)\s*(\S+)/.exec(rest);
    if (!literal && EXPANSION.test(body)) { hasExpansion = true; }
    else { if (tgt) targets.push(tgt[1]); added.push(body); }
    return ' ';
  });

  // 2) Segment on statement boundaries (quote-aware): ; && || | — NOT on \n (heredocs gone) and not
  //    structurally on (){}; strip a wrapping subshell so an in-subshell redirect is still seen.
  for (let seg of splitSegments(work)) {
    // Strip a wrapping subshell `( ... )`. LINEAR trim + single-char slices — deliberately NOT a
    // `/\s*\)$/` regex: a greedy `\s*` before a `$` end-anchor is O(n^2) on a long internal whitespace
    // run, a default-reachable ReDoS via scan-write-codex on every Bash command (#6-C; twin of the #5
    // fix in codex-rollout.mjs stripWrappingSubshell; see lessons.md). Behavior-identical strip.
    seg = seg.trim();
    if (seg.startsWith('(')) seg = seg.slice(1);
    if (seg.endsWith(')')) seg = seg.slice(0, -1);
    seg = seg.trim();
    if (!seg || /^cd\b/.test(seg)) continue;            // a `cd` prefix is not a write
    // A `<<` still here means a heredoc the reader above could NOT consume (unterminated, over the
    // opener cap, or an opener shape outside its grammar). Its body never reached `added`, so this
    // command is not accounted for — say so instead of letting it pass as parsed.
    if (seg.includes('<<')) { unreadWrite = true; continue; }
    if (!/(?:>>?)\s*\S+\s*$/.test(seg)) {
      // No trailing `>`/`>>`. The segment may still WRITE by other means (tee/dd/sed -i/cp/...) or
      // via a redirect form outside this grammar (`>|`, `&>`, `N>`, `>&N`). We cannot read those,
      // so we must not go on claiming we accounted for the command.
      if (UNREAD_WRITE.test(seg)) unreadWrite = true;
      continue;
    }
    const m = /^(?:printf|echo)\b\s+([\s\S]*?)\s*>>?\s*(\S+)\s*$/.exec(seg);
    if (!m) { unreadWrite = true; continue; }            // a redirect driven by some other command
    const payload = m[1].trim();
    // Quote-AWARE expansion test. Bash never expands inside single quotes, so
    // `echo 'password=p$ssw0rd…' > f` is a fully literal write of the declared-covered form (agentic-sdlc:allow-secret)
    // form — but a raw `EXPANSION.test` matched the `$s` and skipped the payload entirely, a false
    // negative inside the coverage this extractor claims. The heredoc path one block above already
    // gets this right by checking the delimiter's quoting; this branch had no equivalent.
    if (hasUnquotedExpansion(payload)) { hasExpansion = true; continue; }
    targets.push(m[2]);
    // Scan the WHOLE payload, not just its first literal token. The previous extractLiteral() read
    // only the text between the FIRST pair of quotes (or a bare word containing no whitespace) and
    // silently dropped the rest, so
    //     echo "" <token> > f   |   echo x <token> > f   |   echo <token> extra > f
    // handed the scanner an empty string while the shell wrote every argument to the file. The byte
    // set we scan must be a SUPERSET of what lands on disk; the DENY decision stays exact because a
    // HIGH pattern is a vendor-shaped token that neighbouring text cannot manufacture.
    // Scan BOTH the quote-stripped text and its escape-decoded form. POSIX `printf` interprets
    // backslash escapes in its FORMAT string unconditionally (no -e needed), and `echo -e` does the
    // same, so `printf '\163\153\137\154\151\166\145\137A4242424242424242' > f` really writes
    // `sk_live_A424…` (agentic-sdlc:allow-secret) while the raw text reads `163153137…`. Pushing both is a strict
    // superset: it can only add detections, never lose one.
    const literal = payloadText(payload);
    added.push(literal);
    // decodeAnsiC must run on text that STILL HAS its backslashes — payloadText already consumed
    // them (`\163` -> `163`), so decoding its output would find nothing left to decode.
    const escaped = decodeAnsiC(stripQuoteDelimiters(payload));
    if (escaped !== literal) added.push(escaped);
  }

  return { addedContent: added.join('\n'), targets, parsed: !hasExpansion && !unreadWrite };
}

// Quote-stripping reader for a printf/echo argument list: drop quote DELIMITERS and backslash
// escapes so a value split across quoting styles reads as contiguous text. Single pass, no
// backtracking — this runs on every Bash command, so a quadratic regex here would be a DoS
// (the #5/#6-C class already fixed elsewhere in this file).
// True only when an expansion token appears where bash would actually expand it: outside single
// quotes. Inside double quotes `$`/backtick DO expand, so those still count. Single pass, linear.
function hasUnquotedExpansion(payload) {
  const s = String(payload);
  const expands = (i) => (s[i] === '`') || (s[i] === '$' && /[\w{(]/.test(s[i + 1] || ''));
  let q = null;
  for (let i = 0; i < s.length; i += 1) {
    const c = s[i];
    if (q === "'") { if (c === "'") q = null; continue; }      // nothing expands in single quotes
    if (c === '\\' && i + 1 < s.length) { i += 1; continue; }
    if (q === '"') {
      if (c === '"') { q = null; continue; }
      if (expands(i)) return true;
      continue;
    }
    if (c === "'" || c === '"') { q = c; continue; }
    if (expands(i)) return true;
  }
  return false;
}

// Remove quote DELIMITERS but keep every backslash, so the escape decoder still has something to
// decode. Single pass, no backtracking.
function stripQuoteDelimiters(payload) {
  let out = '';
  let q = null;
  for (let i = 0; i < payload.length; i += 1) {
    const c = payload[i];
    if (q) {
      if (c === q) { q = null; continue; }
      out += c;
      continue;
    }
    if (c === '"' || c === "'") { q = c; continue; }
    out += c;
  }
  return out;
}

function payloadText(payload) {
  let out = '';
  for (let i = 0; i < payload.length; i++) {
    const c = payload[i];
    if (c === '\\' && i + 1 < payload.length) { out += payload[i + 1]; i += 1; continue; }
    if (c === '"' || c === "'") continue;
    out += c;
  }
  return out;
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

