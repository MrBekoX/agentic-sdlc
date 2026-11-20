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

// The ONE heredoc grammar shared by every reader of shell writes (this extractor, the Codex precise
// write-target recognizer in codex-rollout.mjs and the test-run shape check in flow-evidence.mjs), so
// their heredoc coverage cannot drift apart (the #5 root cause). Groups: 1 head (opener + rest of its
// line), 2 backslash, 3 quote, 4 delimiter, 5 CR, 6 rest of the opener line, 7 body. Bash treats ANY
// quoting of the delimiter word as literal: `<<'EOF'`, `<<"EOF"` and `<<\EOF` (SW-7).
// R2-FH-3: a CR is part of the delimiter only when it directly follows the delimiter word on the opener
// line (a CRLF command), exactly as bash reads it: then the closing line is `EOF` + CR; otherwise a line
// `EOF` + CR is still body, and the lines after it are still written (and scanned).
// R2-FH-1: `(?!\w)` stops the delimiter word from being split on a failed match, and the opener blanks
// are `[ \t]*`: the old `([A-Za-z_]\w*)\3([^\n]*)` tried every split of a long word, O(n^2) on one
// `<<aaaa...` with no newline. Per opener the match is now linear; the lazy body still scans to the end
// once per UNTERMINATED opener, so callers skip heredoc parsing above HEREDOC_OPENER_CAP openers.
export const HEREDOC_OPENER_CAP = 24;
// R2-b: the delimiter may be any word of letters, digits, `_`, `.` and `-` (`<<EOF-1`, `<<'END.1'`,
// `<<1EOF`), not only an identifier, which ended `EOF-1` at `EOF` and left the body unread. The set is
// deliberately small: those characters read the same inside and outside quotes, so the delimiter word
// never makes the grammar read a body LONGER than bash does, which would swallow the commands after it (security reviews of
// Round 2). Any other word - a `\` or an expansion inside quotes (`<<"E\"F"`, `<<"A$(x "`), a word bash
// continues (`<<'EOF'X`, `<<EOF$x`), a CR inside the word (`<<EOF\rX`), an escaped quote (`<<\'EOF'`)
// - is left unread, and so is a here-string (`<<<`). `<<` takes its `-` only as the `<<-` operator.
// An empty quote pair after the word (`<<EOF''`) leaves bash's word unchanged, so it is read as 1905c15
// read it; an escaped `\<<` is no operator.
const HEREDOC_SOURCE = String.raw`(?<![<\\])(<<(?:-|(?!-))[ \t]*(\\?)((?<!\\)['"]|)([A-Za-z0-9_.-]+)\3(?:''|"")*(\r?)(?=[ \t\n<>|&;()]|$)([^\n]*))\n([\s\S]*?)\n\4\5(?=\n|$)`;

export function heredocPattern() {
  return new RegExp(HEREDOC_SOURCE, 'g'); // a fresh global regex per use: no shared lastIndex state
}

// 1905c15's grammar, kept as a second reading. A change to the grammar above reads some lines
// differently, and a reviewer found a new spelling each round where the new reading saw less than the
// old one. So every check runs both readings and combines them on its safe side: the written content
// and the write targets are the union, and a test run counts only when both readings count it. No check
// can then be narrower than 1905c15 by construction. Same group order (1 head .. 7 body); linear under
// the same opener cap.
const LEGACY_HEREDOC_SOURCE = String.raw`(<<-?[ \t]*(\\?)(['"]?)([A-Za-z_]\w*)(?!\w)\3(\r?)(?!\r)([^\n]*))\n([\s\S]*?)\n\4\5(?=\n|$)`;
export function legacyHeredocPattern() {
  return new RegExp(LEGACY_HEREDOC_SOURCE, 'g');
}
function overHeredocCap(cmd) {
  return (cmd.match(/<</g) || []).length > HEREDOC_OPENER_CAP;
}

// The offset of the first `<<` the grammar does NOT read as a heredoc (an opener outside its small
// delimiter set, an unterminated one, an even backslash run before it such as `\\<<`, a second opener
// on a read opener's line, or any opener past the opener cap), or -1. A `<<` inside a body the grammar
// did read is data and is skipped; `<<<` and an odd backslash run (`\<<`) are no heredoc operators.
// Bash's body for such an opener is unknown, so callers err to their safe side: the Codex write guard
// scans every byte from here on, and the test-run check reads no line after this one as a command.
// Linear: one pass of the (capped) heredoc grammar plus one scan for `<<`; the backslash runs counted
// back from distinct `<<` never overlap.
const HEREDOC_OPERATOR = /(?<!<)<<(?!<)/g;
export function firstUnreadHeredoc(command) {
  const cmd = String(command || '');
  const spans = overHeredocCap(cmd) ? []
    : [...cmd.matchAll(heredocPattern())].map((m) => [m.index, m.index + m[1].length, m.index + m[0].length]);
  let k = 0;
  for (const m of cmd.matchAll(HEREDOC_OPERATOR)) {
    let j = m.index;
    while (j > 0 && cmd[j - 1] === '\\') j -= 1;
    if ((m.index - j) % 2 === 1) continue;                      // `\<<`: an escaped `<`, no operator
    while (k < spans.length && spans[k][2] <= m.index) k += 1;
    const span = spans[k];
    if (span && (m.index === span[0] || (span[1] <= m.index && m.index < span[2]))) continue; // read opener or body
    return m.index;
  }
  return -1;
}

// Drop every heredoc BODY and closing delimiter, keeping the opener line (its redirect target and any
// `&& next` command on it run). Over the opener cap the command is returned unchanged.
export function blankHeredocBodies(command, pattern = heredocPattern) {
  const cmd = String(command || '');
  if (overHeredocCap(cmd)) return cmd;
  return cmd.replace(pattern(), (_full, head) => `${head} `);
}

// One shell word with its quote DELIMITERS removed when the whole word is quoted (`"src/app.py"`).
export function unquoteWord(word) {
  const s = String(word);
  if (s.length >= 2 && (s[0] === '"' || s[0] === "'") && s[s.length - 1] === s[0]) return s.slice(1, -1);
  return s;
}

// FH-5: `apply_patch <<'PATCH'` (or `... <<'PATCH' | apply_patch`) run through the shell applies the
// heredoc body as a V4A patch, so the body's file headers are write targets.
// R2-FH-2: read with plain splits and one pass per part. The regex `\|\s*(?:\S*\/)?apply_patch` this
// replaces was O(k^2) on an opener line carrying a long run of `|`.
function isApplyPatchCommand(text) {
  const t = text.trim();
  let end = 0;
  while (end < t.length && t[end] !== ' ' && t[end] !== '\t') end += 1; // the command word
  const word = t.slice(0, end);
  const base = word.slice(word.lastIndexOf('/') + 1);
  return base === 'apply_patch' || base === 'applypatch';
}

function heredocFeedsApplyPatch(cmd, offset, rest) {
  const piped = rest.split('|');
  for (let k = 1; k < piped.length; k += 1) if (isApplyPatchCommand(piped[k])) return true;
  const lineStart = cmd.lastIndexOf('\n', offset - 1) + 1;
  return isApplyPatchCommand(cmd.slice(lineStart, offset).split(/;|&&|\|\||\||\(/).pop());
}

// R2-FH-1: the segment's trailing `>`/`>>` redirect, read in one linear pass: { before, target } for
// `<before> > <word>` or `<before>><word>` at the end of the (trimmed) segment, else null. It keeps the
// earliest-operator reading of the regexes it replaces, `/(?:>>?)\s*\S+\s*$/` and
// `/^(...)([\s\S]*?)\s*>>?\s*(\S+)\s*$/`, which retried the `\S+` run from every `>` and were O(n^2)
// on one long `>` run (`echo '>>>...> y'` held a Claude flow hook past its timeout).
const BLANK = /\s/;
function trailingRedirect(seg) {
  let k = seg.length;
  while (k > 0 && !BLANK.test(seg[k - 1])) k -= 1;          // start of the last word
  if (k === seg.length) return null;
  let p = k - 1;
  while (p >= 0 && BLANK.test(seg[p])) p -= 1;              // last character before the blank run
  if (k > 0 && p >= 0 && seg[p] === '>') {                  // `... > word`
    const op = p > 0 && seg[p - 1] === '>' ? p - 1 : p;
    return { before: seg.slice(0, op), target: seg.slice(k) };
  }
  const gt = seg.indexOf('>', k);                           // `...>word` inside the last word
  if (gt === -1) return null;
  if (seg[gt + 1] === '>' && gt + 2 < seg.length) return { before: seg.slice(0, gt), target: seg.slice(gt + 2) };
  if (gt + 1 < seg.length) return { before: seg.slice(0, gt), target: seg.slice(gt + 1) };
  return null;
}
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
  if (toolName === 'apply_patch') return parseApplyPatch(cmd);
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
    // FH-5: an Update hunk with `*** Move to: <path>` writes its content to the new path.
    const mv = /^\*\*\* Move to: (.+)$/.exec(line);
    if (mv) { targets.push(mv[1].trim()); continue; }
    if (/^\*\*\* /.test(line)) continue;                 // *** Begin/End Patch, *** Delete File:
    if (/^@@/.test(line)) continue;                      // hunk header
    if (line.startsWith('+')) added.push(line.slice(1)); // an added content line
  }
  return { addedContent: added.join('\n'), targets, parsed: true };
}

// Both readings (see LEGACY_HEREDOC_SOURCE): the content and the targets are the union, with the
// current reading first and unchanged; `parsed` is the current reading's.
function parseBash(cmd) {
  const now = readBash(cmd, heredocPattern, false);
  const before = readBash(cmd, legacyHeredocPattern, true);
  const seenParts = new Set(now.added);
  const seenTargets = new Set(now.targets);
  const added = now.added.concat(before.added.filter((part) => !seenParts.has(part)));
  const targets = now.targets.concat(before.targets.filter((t) => !seenTargets.has(t)));
  return { addedContent: added.join('\n'), targets, parsed: now.parsed };
}

// One reading of a Bash command under one heredoc grammar. `legacy` reproduces 1905c15's reader: none
// of the Round 2 additions (the unread-opener slice, raw multi-line segments, the opener line's rest).
function readBash(cmd, pattern, legacy) {
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
  // `<<-` (tab-stripping) is as common as `<<`. Matching only `<<\s*` left `cat <<-EOF > f` both
  // unread AND unflagged: no substitution happened, the segment's trailing text was the closing
  // delimiter rather than a redirect, and no UNREAD_WRITE token appeared -> parsed:true with empty
  // content. The same CWE-636 shape as `sed --in-place`, one review round later.
  // The grammar is the shared heredocPattern (SW-7: `<<"EOF"`, `<<\EOF` and CRLF are read as well).
  const work = overHeredocCap(cmd) ? cmd : cmd.replace(pattern(), (full, head, bs, q, _delim, _cr, rest, body, offset) => {
    // Any quoting of the delimiter word => no expansion of the body; that includes an empty quote pair
    // after the word (`<<EOF''`), which the word class (no quote characters) leaves outside group 3.
    const literal = Boolean(bs || q) || /['"]/.test(head.slice(0, head.length - rest.length));
    const tgt = /(?:>>?)\s*(\S+)/.exec(rest);
    // The redirect target is known whatever the body expands to; only the CONTENT depends on it.
    if (tgt) targets.push(unquoteWord(tgt[1]));
    if (heredocFeedsApplyPatch(cmd, offset, rest)) {
      for (const t of parseApplyPatch(body).targets) targets.push(t);
    }
    if (!literal && EXPANSION.test(body)) { hasExpansion = true; }
    else { added.push(body); }
    // The rest of the opener line can hold more commands (`; printf … > b`); they leave `work` with the
    // match, so scan their raw text too (a superset; the deny stays exact).
    if (!legacy && rest.trim()) added.push(rest);
    return ' ';
  });

  // An opener the grammar cannot read still writes its body, which bash ends at a delimiter line this
  // grammar cannot name (or never). 1905c15 read some of these spellings (`<<'EOF'X`) with a shorter
  // delimiter, so scan every byte from the opener on: a superset of what lands on disk, while the deny
  // stays exact because a HIGH pattern is a vendor-shaped token that neighbouring text cannot make.
  const unread = legacy ? -1 : firstUnreadHeredoc(cmd);
  if (unread >= 0) added.push(cmd.slice(unread));

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
    // A segment that spans lines or still holds a `<<` can write in ways this reader does not follow
    // (`true` LF `echo … > f`, the lines after `<<<` or `\<<`, a body bash ends later than the grammar).
    // Scan its raw text as well: a superset of what lands on disk, with the deny still exact (HIGH).
    if (!legacy && (seg.includes('\n') || seg.includes('<<'))) added.push(seg);
    if (!seg || /^cd\b/.test(seg)) continue;            // a `cd` prefix is not a write
    // A `<<` still here means a heredoc the reader above could NOT consume (unterminated, over the
    // opener cap, or an opener shape outside its grammar). Its body never reached `added`, so this
    // command is not accounted for — say so instead of letting it pass as parsed.
    if (seg.includes('<<')) { unreadWrite = true; continue; }
    const redirect = trailingRedirect(seg);
    if (!redirect) {
      // No trailing `>`/`>>`. The segment may still WRITE by other means (tee/dd/sed -i/cp/...) or
      // via a redirect form outside this grammar (`>|`, `&>`, `N>`, `>&N`). We cannot read those,
      // so we must not go on claiming we accounted for the command.
      if (UNREAD_WRITE.test(seg)) unreadWrite = true;
      continue;
    }
    const lead = /^(?:printf|echo)\b\s+/.exec(redirect.before);
    if (!lead) { unreadWrite = true; continue; }         // a redirect driven by some other command
    const m = [null, redirect.before.slice(lead[0].length), redirect.target];
    const payload = m[1].trim();
    // Quote-AWARE expansion test. Bash never expands inside single quotes, so
    // `echo 'password=p$ssw0rd…' > f` is a fully literal write of the declared-covered form (agentic-sdlc:allow-secret)
    // form — but a raw `EXPANSION.test` matched the `$s` and skipped the payload entirely, a false
    // negative inside the coverage this extractor claims. The heredoc path one block above already
    // gets this right by checking the delimiter's quoting; this branch had no equivalent.
    if (hasUnquotedExpansion(payload)) { hasExpansion = true; continue; }
    targets.push(unquoteWord(m[2])); // FH-5: `> "src/app.py"` writes src/app.py
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

  return { added, targets, parsed: !hasExpansion && !unreadWrite };
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
