// Pure reader for the Codex rollout transcript (first slice of the shared rollout parser).
// Given a rollout JSONL path, returns the final assistant text and whether the completion-claim-gate
// sentinel marker (GATE_MARKER) appears anywhere in the readable rollout. Pure: node:fs stat + one
// read, JSON-decode per line, string scan — no eval, no spawn, no child process. Fails open: any
// missing/unreadable/over-ceiling input returns readable:false so the caller never blocks on it.
//
// Detection (R3): the sentinel is matched as an EXACT, case-sensitive byte substring over each
// per-message-DECODED carrier value (so a token inside one message is never split by the JSON record
// envelope), across the whole rollout (user- and assistant-authored carriers alike).
import { statSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { extractWrittenContent } from './codex-write-signal.mjs';

// Single source of truth for the gate's self-signature. The completion-claim-gate SKILL.md emits this
// exact literal when it runs; AC17's drift test asserts the two copies stay byte-identical.
export const GATE_MARKER = '<!-- agentic-sdlc:gate:completion-claim:verified -->';

// Byte copies of completion-claim-guard-codex.mjs CLAIM and NEGATED for the offline strict evaluator's
// completion line (a parity test keeps the copies identical).
export const COMPLETION_CLAIM =
  /\b(all\s+tests?\s+(pass|passing|green)|all\s+green|ready\s+to\s+(merge|ship)|ready\s+for\s+review|implementation\s+(is\s+)?complete|feature\s+complete|task\s+(is\s+)?complete|done\s+and\s+verified|fixed\s+and\s+verified|verified\s+and\s+(complete|done)|everything\s+(works|passes))\b/i;
export const COMPLETION_NEGATED = /\b(not\s+(yet\s+)?(done|complete|ready|passing)|still\s+(failing|broken|todo)|incomplete|do\s+not\s+claim)\b/i;

const MAX = 8 * 1024 * 1024; // 8 MiB whole-rollout ceiling (R11/DP10); over-ceiling -> unconfirmable.

function payloadOf(o) {
  return o && typeof o === 'object' && o.payload && typeof o.payload === 'object' ? o.payload : o;
}

// task_complete.last_agent_message — Codex's authoritative end-of-turn final agent message (R5).
function taskCompleteText(p) {
  if (p && p.type === 'task_complete' && typeof p.last_agent_message === 'string') return p.last_agent_message;
  return null;
}

// A streaming assistant-text carrier: event_msg agent_message{message} or response_item assistant message.
function assistantText(p) {
  if (!p) return null;
  if (p.type === 'agent_message' && typeof p.message === 'string') return p.message;
  if (p.type === 'message' && p.role === 'assistant' && Array.isArray(p.content)) {
    const t = p.content
      .filter((c) => c && (c.type === 'output_text' || c.type === 'text') && typeof c.text === 'string')
      .map((c) => c.text)
      .join('\n');
    return t || null;
  }
  return null;
}

// A turn boundary in the rollout: codex writes `event_msg task_started` when a turn begins and a
// `turn_context` record when the turn's context is set. Records before the last boundary belong to an
// earlier turn, so they can never supply this turn's final message (SEC-2).
function isTurnBoundary(o, p) {
  if (o && typeof o === 'object' && o.type === 'turn_context') return true;
  return Boolean(p && p.type === 'task_started');
}

export function readRollout(path) {
  const EMPTY = { finalMessage: '', gateMarkerPresent: false, readable: false };
  if (!path || typeof path !== 'string') return EMPTY;
  let raw;
  try {
    const st = statSync(path);
    if (!st.isFile() || st.size > MAX) return EMPTY; // missing/non-file/over-ceiling -> unconfirmable
    raw = readFileSync(path, 'utf8');
  } catch {
    return EMPTY; // unreadable -> unconfirmable
  }

  // Inside one turn `task_complete.last_agent_message` stays authoritative (AC1), but the carriers are
  // scoped to the CURRENT turn: a turn boundary (`event_msg task_started`, or a `turn_context` record)
  // clears both. Without that scope a previous turn's last_agent_message became this turn's final
  // message, because a Stop hook fires before this turn's task_complete is persisted, so a marker
  // emitted once silenced the backstop for every later turn of the session (Security #2, SEC-2).
  let lastTaskComplete = null;
  let lastAssistant = null;
  for (const line of raw.split(/\r?\n/)) {
    if (!line) continue;
    let o;
    try { o = JSON.parse(line); } catch { continue; } // tolerate a malformed line
    const p = payloadOf(o);
    if (isTurnBoundary(o, p)) { lastTaskComplete = null; lastAssistant = null; continue; }
    const tc = taskCompleteText(p);
    if (tc != null) lastTaskComplete = tc;
    else {
      const at = assistantText(p);
      if (at != null) lastAssistant = at;
    }
  }
  const finalMessage = lastTaskComplete != null ? lastTaskComplete : (lastAssistant != null ? lastAssistant : '');
  // A1 injection-hardening: the gate marker counts ONLY when it appears in the model's own FINAL
  // message (where completion-claim-gate emits it), not anywhere in the rollout. This stops a bare
  // literal echoed in an EARLIER assistant message or a quoted/injected carrier from silencing the
  // backstop. Self-forgery/replay by the model in its own final message stay out of scope — the
  // marker proves the ceremony ran, not that the evidence is real (that is A2's job).
  const gateMarkerPresent = finalMessage.includes(GATE_MARKER);
  return { finalMessage, gateMarkerPresent, readable: true };
}

// Additive second slice for the flow-step adapter (AP2b): surface the executed COMMANDS and the
// patch-style EDIT TARGETS a Codex session recorded, scoped to this rollout. Same fail-open
// discipline as readRollout: missing/non-file/over-ceiling/unreadable -> EMPTY readable:false, so the
// caller never blocks on an unconfirmable rollout. Pure: one read, JSON-decode per line, no eval,
// no spawn. GATE_MARKER / payloadOf are shared with readRollout above; readRollout's marker check
// is scoped to the final message only (A1 injection-hardening).
//
// Carriers (historical AP1/AP2 shapes plus native 0.154.0 WSL capture):
//   commands  - function_call exec_command {cmd}, AND event_msg exec_command_begin {command, parsed_cmd}.
//   edits     - historical patch carriers, successful custom_tool_call apply_patch/patch {input},
//               plus the bounded shell-write recognizer below. A custom patch attempt counts only
//               after its correlated output confirms success; a denied/failed attempt is not a write.
function parseArgs(args) {
  if (args && typeof args === 'object') return args;
  if (typeof args === 'string') { try { return JSON.parse(args); } catch { return null; } }
  return null;
}

// A2 substrate: extract the plain output text of a `function_call_output` payload. codex persists
// either a bare string or an object carrying `content` (string, or a text-part array). Fail-soft null.
function outputTextOf(o) {
  if (typeof o === 'string') return o;
  if (o && typeof o === 'object') {
    if (typeof o.content === 'string') return o.content;
    if (Array.isArray(o.content)) {
      const t = o.content.filter((c) => c && typeof c.text === 'string').map((c) => c.text).join('\n');
      return t || null;
    }
  }
  return null;
}

// Parse only the native leading metadata, never headers echoed inside tool output or a denial's
// raw-command suffix. Both historical Exit-code and 0.154.0 Process-exited headers are supported.
// Scan disjoint lines until Output: or unknown text; no body-wide status search or greedy regex.
function nativeOutputParts(text) {
  let exitCode = null;
  if (typeof text !== 'string') return { exitCode, body: null };
  let offset = 0;
  while (offset <= text.length) {
    const end = text.indexOf('\n', offset);
    const line = text.slice(offset, end < 0 ? text.length : end).trim();
    if (line === 'Output:') return { exitCode, body: end < 0 ? '' : text.slice(end + 1) };
    const match = /^(?:Exit code:[ \t]*|Process exited with code[ \t]+)(-?\d+)$/.exec(line);
    if (match) {
      if (exitCode !== null) return { exitCode, body: null }; // conflicting/repeated metadata
      exitCode = Number(match[1]);
    } else if (line && !/^(?:Chunk ID|Wall time|Original token count):/.test(line)) {
      return { exitCode, body: null };
    }
    if (end < 0) break;
    offset = end + 1;
  }
  return { exitCode, body: null };
}

export function parseCodexExitCode(text) {
  return nativeOutputParts(text).exitCode;
}

// ---------------------------------------------------------------------------
// B5 (write-form symmetry): ONE shared recognizer of the write FORMS (in-place
// `sed -i`, `tee`, plain `>`/`>>` redirect) feeds BOTH consumers so recognition
// breadth cannot drift apart again (the #5 root cause). The two consumers differ
// ONLY in precision:
//   - writeTargetsOf(cmd)        -> RAW / over-approximating, for prior-evidence
//     (readRolloutSignals.editTargets). Extra targets there only bias the flow-
//     ORDER decision toward ALLOW (BR6-safe). It is a STRICT SUPERSET of HEAD:
//     HEAD's REDIRECT/TEE/SED_LAST run verbatim, and the shared multi-operand
//     extractors only ADD the remaining `sed`/`tee` file operands (BR5).
//   - preciseWriteTargetsOf(cmd) -> PRECISE, for the flow-ORDER current-edit deny
//     trigger. Quote/heredoc/statement/expansion-aware, so a redirect/tee/sed-
//     looking token that is quoted, an argument value, a heredoc body, or
//     expansion-bearing is NOT counted (BR7); an over-approximation on the
//     DENY-biased side would be a spurious block (BR4).
// The precision *pattern* mirrors codex-write-signal.mjs (a quote-aware splitter +
// the EXPANSION marker), RE-IMPLEMENTED here so that byte-locked module stays
// untouched. All scans are single-pass / disjoint-class regex -> linear (BR10).
// Redirect scope is exactly `>`/`>>`; the fd-excluded class leaves `&>`, `>|`,
// `N>`, `>&N` unrecognized (deferred residual #6). Pure: string/regex over the
// command treated as DATA (no eval, no spawn).
const CMD_MAX = 512 * 1024;                                   // per-command scan cap (mirrors codex-write-signal)
const HEREDOC_OPENER_CAP = 24;                               // pathological `<<` flood -> skip heredoc parse
const EXPANSION = /\$[\w{(]|`/;                              // any shell-expansion marker (re-implemented, not imported)
const REDIRECT = /[^0-9&>]>>?\s*(['"]?)([^\s'";&|<>()]+)/g;  // `>`/`>>` only; fd/&-excluded; LINEAR
const TEE = /\btee\b\s+(?:-a\s+)?([^\s;|&<>'"]+)/g;          // HEAD first-operand baseline (raw superset); LINEAR
const SED_LAST = /\s([^\s;|&<>'"]+)\s*$/;                    // HEAD last-token baseline (raw superset)

// Quote-aware tokenizer: an unquoted whitespace run separates tokens; a single- or
// double-quoted span stays ONE token with quotes stripped (so a quoted sed script
// `'s/a/> b.py/'` is one opaque token, never scanned for `>`).
function shellTokens(str) {
  const toks = [];
  let cur = null;
  let q = null;
  for (let i = 0; i < str.length; i += 1) {
    const c = str[i];
    if (q) { if (c === q) q = null; else cur += c; continue; }
    if (c === "'" || c === '"') { q = c; if (cur === null) cur = ''; continue; }
    if (c === ' ' || c === '\t' || c === '\n') { if (cur !== null) { toks.push(cur); cur = null; } continue; }
    cur = (cur === null ? '' : cur) + c;
  }
  if (cur !== null) toks.push(cur);
  return toks;
}

// Replace every quoted span (and its quote chars) with spaces, positions kept, so a
// REDIRECT scan over the result never sees a `>` that lives inside quotes.
function quoteBlank(str) {
  let out = '';
  let q = null;
  for (let i = 0; i < str.length; i += 1) {
    const c = str[i];
    if (q) { if (c === q) q = null; out += ' '; continue; }
    if (c === "'" || c === '"') { q = c; out += ' '; continue; }
    out += c;
  }
  return out;
}

// Quote-aware statement split on ; && || | & and newline (a separator inside quotes
// does not split). Single pass (LINEAR).
function splitSegmentsQA(str) {
  const segs = [];
  let cur = '';
  let q = null;
  for (let i = 0; i < str.length; i += 1) {
    const c = str[i];
    const n = str[i + 1];
    if (q) { cur += c; if (c === q) q = null; continue; }
    if (c === "'" || c === '"') { q = c; cur += c; continue; }
    if (c === '\n' || c === ';') { segs.push(cur); cur = ''; continue; }
    if (c === '&' && n === '&') { segs.push(cur); cur = ''; i += 1; continue; }
    if (c === '|' && n === '|') { segs.push(cur); cur = ''; i += 1; continue; }
    if (c === '|' || c === '&') { segs.push(cur); cur = ''; continue; }
    cur += c;
  }
  if (cur) segs.push(cur);
  return segs;
}

// Blank every heredoc window (opener + body) to spaces so a body line like `> evil.py`
// is never mistaken for a redirect. The heredoc's own opener redirect target is
// supplied by extractWrittenContent in the caller's union, so it need not be
// re-extracted here. `[\s\S]*?` is opener-capped by the caller against a `<<` flood.
function blankHeredocs(cmd) {
  const heredocRe = /<<\s*(['"]?)([A-Za-z_]\w*)\1([^\n]*)\n([\s\S]*?)\n\2(?=\n|$)/g;
  return cmd.replace(heredocRe, (full) => full.replace(/[^\n]/g, ' '));
}

// Strip a wrapping subshell `( ... )`. LINEAR: trim + single-char slices only — deliberately NOT a
// `/\s*\)$/` regex. A greedy `\s*` before an end `$` anchor is O(n^2) on a long internal whitespace
// run (e.g. `echo <200k spaces> x`): at the 512 KiB cap that hangs the hook for minutes and then
// fail-open-bypasses under AGENTIC_FLOW_ORDER_BLOCK (a self-inflicted DoS). Keep this branchy + linear.
function stripWrappingSubshell(seg) {
  let s = seg.trim();
  if (s.startsWith('(')) s = s.slice(1);
  if (s.endsWith(')')) s = s.slice(0, -1);
  return s.trim();
}

// First token that is not a leading `VAR=val` assignment (the command word).
function commandWord(toks) {
  for (const t of toks) {
    if (/^[A-Za-z_]\w*=/.test(t)) continue;
    return t;
  }
  return '';
}

function teeIndex(toks) {
  return toks.findIndex((t) => t === 'tee' || t.endsWith('/tee'));
}

// A `sed` in-place flag: `-i`, `-i.bak` (glued suffix), a combined short group
// containing `i` (e.g. `-ni`), or the GNU long form `--in-place[=SUFFIX]`.
function isInplaceSedFlag(t) {
  if (t.startsWith('--in-place')) return true;
  if (t.startsWith('--')) return false;
  return /^-[A-Za-z]*i/.test(t);
}

// A redirect operator token (bare or glued), incl. fd-numbered `N>` and `<`.
function isRedirectToken(t) {
  return /^\d*(?:>>?|<)/.test(t);
}

// FILE operands of a `sed` invocation (tokens are quote-aware). The sed script — the
// leading script token when no `-e`/`-f` is present, and any `-e`/`-f`/`--expression`/
// `--file` argument (separated OR glued) — is NOT a write target, nor are option flags.
// Stops at a redirect token (REDIRECT owns it). Single pass (LINEAR).
function sedFileOperands(toks) {
  const start = toks.findIndex((t) => t === 'sed' || t.endsWith('/sed'));
  if (start < 0) return [];
  const files = [];
  let scriptTaken = false;
  for (let j = start + 1; j < toks.length; j += 1) {
    const t = toks[j];
    if (isRedirectToken(t)) break;
    if (t === '--') continue;
    if (t.startsWith('-')) {
      if (t === '-e' || t === '-f' || t === '--expression' || t === '--file') { j += 1; scriptTaken = true; continue; }
      if (/^--(?:expression|file)=/.test(t)) { scriptTaken = true; continue; }
      if (/^-[A-Za-z]*[ef]\S/.test(t)) { scriptTaken = true; continue; }
      continue;
    }
    if (!scriptTaken && files.length === 0) { scriptTaken = true; continue; }
    files.push(t);
  }
  return files;
}

// FILE operands of a `tee` invocation after index `i` (caller guards i>=0). Option
// flags skipped; stops at a redirect token. Single pass (LINEAR).
function teeFileOperands(toks, i) {
  if (i < 0) return [];
  const files = [];
  for (let j = i + 1; j < toks.length; j += 1) {
    const t = toks[j];
    if (isRedirectToken(t)) break;
    if (t === '--') continue;
    if (t.startsWith('-') && t !== '-') continue; // -a, --append, -i, -p, --output-error, ...
    files.push(t);
  }
  return files;
}

// RAW / over-approximating write targets (prior-evidence). STRICT SUPERSET of HEAD:
// lines (1)(2a)(3a) reproduce HEAD's exact output; (2b)(3b) add the remaining shared
// multi-file operands (BR5). Duplicates are harmless (every downstream consumer dedups).
export function writeTargetsOf(command) {
  const str = String(command || '');
  const targets = [];
  for (const m of str.matchAll(REDIRECT)) targets.push(m[2]);   // (1) HEAD redirects
  for (const m of str.matchAll(TEE)) targets.push(m[1]);        // (2a) HEAD tee first-operand
  for (const seg of str.split(/[;\n|&]+/)) {
    const toks = shellTokens(seg);
    const ti = teeIndex(toks);
    if (ti >= 0) for (const t of teeFileOperands(toks, ti)) targets.push(t); // (2b) BR5 all tee operands
    if (/\bsed\b/.test(seg) && /(?:^|\s)-i/.test(seg)) {
      const m = seg.split('>')[0].match(SED_LAST);
      if (m) targets.push(m[1]);                                 // (3a) HEAD sed last-token
      for (const t of sedFileOperands(toks)) targets.push(t);    // (3b) BR5 all sed operands
    }
  }
  return targets;
}

// PRECISE write targets (current-edit deny trigger). Quote/heredoc/statement/expansion-
// aware: only real, unquoted, statement-level, non-expansion targets count (BR7). NOT a
// raw union of writeTargetsOf. Bash-only (the caller never runs this over patch text, BR8).
export function preciseWriteTargetsOf(command) {
  const cmd = String(command || '');
  if (!cmd || cmd.length > CMD_MAX) return [];
  if ((cmd.match(/<</g) || []).length > HEREDOC_OPENER_CAP) return []; // `<<` flood -> fail-open
  const work = blankHeredocs(cmd);
  const targets = [];
  for (const rawSeg of splitSegmentsQA(work)) {
    const stmt = stripWrappingSubshell(rawSeg);
    if (!stmt) continue;
    for (const m of quoteBlank(stmt).matchAll(REDIRECT)) {       // redirect over the QUOTE-BLANKED statement
      if (!EXPANSION.test(m[2])) targets.push(m[2]);             // drop `$`-expansion targets (DP1/BR4)
    }
    const toks = shellTokens(stmt);                             // quote-aware (script stays one token)
    const cw = commandWord(toks);
    if ((cw === 'sed' || cw.endsWith('/sed')) && toks.some(isInplaceSedFlag)) {
      for (const t of sedFileOperands(toks)) if (!EXPANSION.test(t)) targets.push(t);
    }
    if (cw === 'tee' || cw.endsWith('/tee')) {
      for (const t of teeFileOperands(toks, teeIndex(toks))) if (!EXPANSION.test(t)) targets.push(t);
    }
  }
  return targets;
}

export function readRolloutSignals(path) {
  const EMPTY = { commands: [], editTargets: [], commandRuns: [], readable: false };
  if (!path || typeof path !== 'string') return EMPTY;
  let raw;
  try {
    const st = statSync(path);
    if (!st.isFile() || st.size > MAX) return EMPTY; // missing/non-file/over-ceiling -> unconfirmable
    raw = readFileSync(path, 'utf8');
  } catch {
    return EMPTY; // unreadable -> unconfirmable
  }

  const commands = [];
  const editTargets = [];
  // A2: a per-invocation view of the recorded commands carrying their correlated exit code + output.
  // `commandRuns` is parallel to `commands` (one entry per pushed command string); exitCode/output are
  // filled AFTER the pass from the by-call_id maps below (the `function_call_output` for a
  // `function_call exec_command`, or the defensive `exec_command_end`). A run with no correlated exit
  // stays exitCode:null -> the flow-STEP consumer FAILS OPEN on it (substrate absent, no regression).
  const commandRuns = [];
  const outputByCallId = new Map(); // call_id -> function_call_output text (primary exit/output carrier)
  const customPatches = new Map(); // call_id -> input; conflicting definitions become null
  const customOutputs = new Map(); // preserve the native custom-tool output type boundary
  const endByCallId = new Map();    // call_id -> { exitCode, output } from exec_command_end (defensive)
  const pushCmd = (s, callId) => { commands.push(s); commandRuns.push({ command: s, callId: callId ?? null, exitCode: null, output: null }); };
  // A1/BR4a closure: a Codex shell-redirect WRITE is recorded as a raw command string (verified live:
  // exec_command {cmd:"printf 'hi' > note.txt"}), and codex often BUNDLES several writes into one
  // exec_command separated by newlines, so the single-write `extractWrittenContent` (which keys on a
  // trailing redirect) only catches the LAST target. Here we want every file a command redirected to,
  // so scan for ALL `>`/`>>` redirect targets across the whole command string — a spec/plan (or source)
  // written via a `>`/`>>` redirect is no longer invisible to flow-step/flow-order. fd redirects (`2>`,
  // `>&2`) are skipped. Still bounded (narrowed BR4a): a `cat` copy, `base64`, or a `$`-expansion
  // target are not surfaced. Pure: regex scans only.
  // B5: prior-evidence write targets come from the SHARED raw recognizer writeTargetsOf — a strict
  // superset of the earlier inline REDIRECT/TEE/SED_LAST scan that ADDS the multi-file `sed`/`tee`
  // operands (BR5). Sharing the form-recognition with the current-edit detector is what keeps their
  // breadth from drifting apart (the #5 root cause). Over-approximation here only biases flow-ORDER
  // toward ALLOW (BR6-safe); the cross-consumer flow-STEP effect of the widening is accepted (AC18).
  const pushWriteTargets = (s) => { for (const t of writeTargetsOf(s)) editTargets.push(t); };
  const pushRedirectTargets = pushWriteTargets; // keep the call sites below stable
  for (const line of raw.split(/\r?\n/)) {
    if (!line) continue;
    let o;
    try { o = JSON.parse(line); } catch { continue; } // tolerate a malformed line
    const p = payloadOf(o);
    if (!p || typeof p !== 'object') continue;

    if (p.type === 'function_call') {
      const a = parseArgs(p.arguments);
      if (p.name === 'exec_command') {
        const cmd = a && a.cmd;
        const s = Array.isArray(cmd) ? cmd.map((x) => String(x)).join(' ') : (typeof cmd === 'string' ? cmd : null);
        if (s != null) { pushCmd(s, p.call_id); pushRedirectTargets(s); }
      } else if (p.name === 'apply_patch' || p.name === 'patch') {
        const patchText = a && a.input;
        if (typeof patchText === 'string') {
          for (const t of extractWrittenContent('apply_patch', patchText).targets) editTargets.push(t);
        }
      }
    } else if (p.type === 'custom_tool_call') {
      if ((p.name === 'apply_patch' || p.name === 'patch') && p.call_id != null && typeof p.input === 'string') {
        if (!customPatches.has(p.call_id)) customPatches.set(p.call_id, p.input);
        else if (customPatches.get(p.call_id) !== p.input) customPatches.set(p.call_id, null);
      }
    } else if (p.type === 'custom_tool_call_output') {
      if (p.call_id != null) {
        const output = outputTextOf(p.output);
        if (!customOutputs.has(p.call_id)) customOutputs.set(p.call_id, output);
        else if (customOutputs.get(p.call_id) !== output) customOutputs.set(p.call_id, null);
      }
    } else if (p.type === 'function_call_output') {
      // A2 primary exit/output carrier: correlate to its `function_call` by call_id (either order).
      if (p.call_id != null) {
        const t = outputTextOf(p.output);
        if (t != null) outputByCallId.set(p.call_id, t);
      }
    } else if (p.type === 'exec_command_begin') {
      if (typeof p.command === 'string' && p.command) { pushCmd(p.command, p.call_id); pushRedirectTargets(p.command); }
      if (Array.isArray(p.parsed_cmd)) {
        const toks = p.parsed_cmd.filter((x) => typeof x === 'string');
        if (toks.length) pushCmd(toks.join(' '), p.call_id);
      }
    } else if (p.type === 'exec_command_end') {
      // A2 DEFENSIVE secondary exit carrier (a prior live probe saw event_msg exec_command_end with a
      // structured exit_code). Correlated by call_id; used only when no function_call_output exit exists.
      if (p.call_id != null) {
        const ec = typeof p.exit_code === 'number' ? p.exit_code : null;
        const ao = typeof p.aggregated_output === 'string' ? p.aggregated_output : null;
        endByCallId.set(p.call_id, { exitCode: ec, output: ao });
      }
    } else if (p.type === 'patch_apply_begin') {
      for (const t of Object.keys(p.changes || {})) editTargets.push(t);
    } else if (p.type === 'patch_apply_end') {
      // The shape codex-cli 0.142.0 actually persists for a native apply_patch (verified live): an
      // event_msg `patch_apply_end` carrying `{ changes: { <absolute path>: {type,content} }, success }`.
      // (No `patch_apply_begin` / `function_call apply_patch` is emitted in the rollout.) Count only a
      // SUCCESSFUL apply as a real in-session write; a failed patch wrote nothing.
      if (p.success !== false) for (const t of Object.keys(p.changes || {})) editTargets.push(t);
    }
  }
  const seenEditTargets = new Set(editTargets);
  for (const [callId, input] of customPatches) {
    if (input === null) continue;
    const output = nativeOutputParts(customOutputs.get(callId));
    if (output.exitCode !== 0 || !/^Success\. Updated the following files:\r?\n/.test(output.body)) continue;
    for (const target of extractWrittenContent('apply_patch', input).targets) {
      if (!seenEditTargets.has(target)) {
        seenEditTargets.add(target);
        editTargets.push(target);
      }
    }
  }
  // A2 correlation pass: fill each run's exitCode/output from its call_id. The function_call_output's
  // codex `Exit code:` line is primary; the exec_command_end structured exit_code is the fallback.
  for (const run of commandRuns) {
    if (run.callId == null) continue;
    const out = outputByCallId.get(run.callId);
    if (typeof out === 'string') { run.output = out; run.exitCode = parseCodexExitCode(out); }
    if (run.exitCode == null && endByCallId.has(run.callId)) {
      const e = endByCallId.get(run.callId);
      if (typeof e.exitCode === 'number') run.exitCode = e.exitCode;
      if (run.output == null && typeof e.output === 'string') run.output = e.output;
    }
  }
  return { commands, editTargets, commandRuns, readable: true };
}

// ---------------------------------------------------------------------------
// BR6 exit attribution (publication-readiness 0.4.3). A correlated exit code belongs to the LAST
// statement of a command, so `pytest; echo EXIT=$?` must not lend echo's exit 0 to pytest.
// Statements split on unquoted `;`, newline and `||` only: `&&` keeps attribution (a failing left
// side stops the chain), and `|` / `&` stay inside one statement. Pure single-pass helpers over the
// command treated as DATA (no eval, no spawn, no backtracking regex), so each is linear (BR10).
const VERSION_HELP_ARGS = new Set(['--version', '-V', '--help', '-h']);
// An unquoted `#` starts a comment only at the start of a word: the start of the command or statement,
// or right after one of these characters, which are exactly bash's word-breaking metacharacters. The
// comment runs to the next newline and hides its separators. `)` matters: in `pytest; (echo x)# ; pytest`
// bash ends on the subshell. After `(`, `<` or `>` bash stops on a syntax error, so no later statement runs.
const COMMENT_BOUNDARY = new Set([' ', '\t', '\n', ';', '|', '&', '(', ')', '<', '>']);

// Index of the newline that ends a comment starting at i, or the string length.
function commentEnd(str, i) {
  const nl = str.indexOf('\n', i);
  return nl === -1 ? str.length : nl;
}

// D25 blank model: only space, tab and newline are blanks; every other character is a word character.
const BR6_BLANKS = new Set([' ', '\t', '\n']);

// Trim BR6 blanks from both ends. A linear loop, never an end-anchored regex (quadratic on a long blank run).
function trimBlanks(s) {
  let start = 0;
  let end = s.length;
  while (start < end && BR6_BLANKS.has(s[start])) start += 1;
  while (end > start && BR6_BLANKS.has(s[end - 1])) end -= 1;
  return s.slice(start, end);
}

// Statements in order, each with `viaOr`: true when an unquoted `||` joins it to the statement before.
// The join survives the empty lines and comments bash allows after `||` (`echo ok ||\npytest`).
export function splitBr6StatementJoins(command) {
  const str = String(command || '');
  const statements = [];
  let cur = '';
  let q = null;
  let wordStart = true;
  let pendingOr = false;
  const flush = (viaOr) => {
    const s = trimBlanks(cur);
    if (s) { statements.push({ text: s, viaOr: pendingOr }); pendingOr = false; } // empty/comment-only ignored
    cur = '';
    if (viaOr) pendingOr = true;
  };
  for (let i = 0; i < str.length; i += 1) {
    const c = str[i];
    const n = str[i + 1];
    if (q === "'") { cur += c; if (c === q) q = null; continue; } // single quotes: all bytes literal
    if (c === '\\') {
      if (n === '\n') { i += 1; continue; }                        // line continuation joins the lines
      cur += c;
      if (n !== undefined) { cur += n; i += 1; }                    // an escaped character is data
      wordStart = false;
      continue;
    }
    if (q) { cur += c; if (c === q) q = null; continue; }
    if (c === "'" || c === '"') { q = c; cur += c; wordStart = false; continue; }
    if (c === '#' && wordStart) { i = commentEnd(str, i) - 1; continue; } // the newline still separates
    wordStart = COMMENT_BOUNDARY.has(c);
    if (c === ';' || c === '\n') { flush(false); continue; }
    if (c === '|' && n === '|') { flush(true); i += 1; continue; }
    cur += c;
  }
  flush(false);
  return statements;
}

export function splitBr6Statements(command) {
  return splitBr6StatementJoins(command).map((s) => s.text);
}

export function lastStatement(command) {
  const statements = splitBr6Statements(command);
  return statements.length ? statements[statements.length - 1] : '';
}

// The maximal trailing run of statements joined by `||`, whose exit the command's exit can come from.
// When a left operand succeeds bash never runs the right side, so `true || pytest` exits with true's 0:
// the exit is attributable only when EVERY operand of this run is a real runner (plan for callers).
export function trailingOrRun(command) {
  const joined = splitBr6StatementJoins(command);
  let start = joined.length - 1;
  while (start > 0 && joined[start].viaOr) start -= 1;
  return joined.slice(Math.max(start, 0)).map((s) => s.text);
}

// D23 safe shell grammar (spec DP35). An exit code is attributable only while the command lies entirely
// inside it; anything outside is not attributable. The word sets are bash 5.2.37's own `compgen -k`
// reserved words and `compgen -b` builtins. Within one bash process a later literal command name runs
// other code, or the exit status is rewritten, only through a reserved word, a builtin, a shell-variable
// assignment that needs `[` or `set -x`, or an assignment to an integer-attributed variable (its value is
// evaluated as arithmetic, which can write BASH_CMDS); a builtin a later bash adds is read as an external
// program (a disclosed limit), and how a name resolves outside the command text (PATH, EXECIGNORE, profile
// functions) is not seen.
const BR6_RESERVED_WORDS = new Set([
  '!', '[[', ']]', '{', '}', 'case', 'coproc', 'do', 'done', 'elif', 'else', 'esac', 'fi', 'for', 'function', 'if',
  'in', 'select', 'then', 'time', 'until', 'while',
]);
const BR6_BASH_BUILTINS = new Set([
  '.', ':', '[', 'alias', 'bg', 'bind', 'break', 'builtin', 'caller', 'cd', 'command', 'compgen', 'complete',
  'compopt', 'continue', 'declare', 'dirs', 'disown', 'echo', 'enable', 'eval', 'exec', 'exit', 'export', 'false',
  'fc', 'fg', 'getopts', 'hash', 'help', 'history', 'jobs', 'kill', 'let', 'local', 'logout', 'mapfile', 'popd',
  'printf', 'pushd', 'pwd', 'read', 'readarray', 'readonly', 'return', 'set', 'shift', 'shopt', 'source', 'suspend',
  'test', 'times', 'trap', 'true', 'type', 'typeset', 'ulimit', 'umask', 'unalias', 'unset', 'wait',
]);
// bash 5.2.37's integer-attributed variables (`bash -c 'declare -p' | grep '^declare -[a-zA-Z]*i'`; SECONDS is not
// marked). An assignment to one, standalone, prefix or as an export argument, lies outside the grammar.
const BR6_INTEGER_VARIABLES = new Set(['BASHPID', 'EUID', 'HISTCMD', 'OPTIND', 'PPID', 'RANDOM', 'SRANDOM', 'UID']);
// printf, test, `[`, wait and unset stay out: each takes a variable name or evaluates an arithmetic subscript from
// an argument, so any expansion there (parameter, glob, tilde) can supply a BASH_CMDS subscript.
const BR6_SAFE_BUILTINS = new Set([':', 'cd', 'echo', 'export', 'false', 'pwd', 'set', 'true']);
const GRAMMAR_ALNUM = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
const GRAMMAR_WORD_CHARS = new Set(GRAMMAR_ALNUM + '_-./:=+,@%^~!?*]');
const GRAMMAR_PARAMETER_CHARS = new Set(GRAMMAR_ALNUM + '_?#$!@*-');
const GRAMMAR_COMMAND_WORD = /^[A-Za-z0-9_\-./:=+,@%^~!#\u0080-\uFFFF]+$/;
const GRAMMAR_ASSIGNMENT = /^([A-Za-z_][A-Za-z0-9_]*)\+?=/;
const GRAMMAR_PLAIN_ARGUMENT = /^[A-Za-z0-9_-]+$/;
const GRAMMAR_DIGITS = /^[0-9]+$/;
const GRAMMAR_SET_OPTION = /^[-+][euo]+$/;
const GRAMMAR_SET_WORDS = new Set(['errexit', 'nounset', 'pipefail']);

// One linear left-to-right pass. Inside the grammar: unquoted words, single quotes, double quotes without
// substitution, `$NAME`-style parameters, backslash pairs and continuations, word-start comments, the
// separators `;`, newline, `||`, `&&`, `|`, `|&` and a background `&`, and simple redirections followed by a
// word. Each simple command's command word is an external program or a BR6_SAFE_BUILTINS name; after such a
// builtin no later `[` may appear (an array subscript reaches BASH_CMDS); `set` only takes the
// errexit/nounset/pipefail forms; no assignment word names an integer-attributed variable; and each `export`
// argument is a literal `NAME=`/`NAME+=` assignment or a plain word of letters, digits, `_` and `-`, so
// no expansion, quote or glob can build the assigned name. A word of only
// digits directly before `<` or `>` is that redirection's file descriptor in any position. Always outside: `(`,
// `)`, `{`, `}`, a backtick, `[[`, `<<`, `<(` and `>(`. Operand rule (DP39 (2)): a `;`, `&`, `&&`, `||`, `|` or
// `|&` after a simple command with no assignment, word or redirection, or an `&&`, `||`, `|` or `|&` still waiting
// for a word at the end (newlines and comments do not end the wait), is outside; bash rejects both before it runs
// anything. A newline while a `|` or `|&` still waits for a word is outside too, because bash joins the next line
// into the pipeline (DP40 (a)).
// Inside, the result lists the statements of splitBr6StatementJoins, in order, as {viaOr, commands}; empty and
// comment-only statements are dropped and the `||` join carries over them. Each simple command is {assignments: the
// raw leading NAME=/NAME+= words, words: [{value, unknown, redirect}] for every other word, op: the operator that
// ended it inside its statement ('', '&&', '|', '|&' or '&')} (DP39 (1)); outside, the result is null.
// scripts/run_procedure_eval.py br6_simple_commands mirrors this pass branch for branch.
export function br6SimpleCommands(command) {
  const str = String(command || '');
  const length = str.length;
  let word = [];
  let inWord = false;
  let wordStart = true;
  let commandSeen = false;
  let safeBuiltin = false;
  let setCommand = false;
  let exportCommand = false;
  let redirectPending = false; // an operator was read and its target word has not started
  let targetWord = false;      // the current word is a redirection target
  let waiting = false;         // an `&&`, `||`, `|` or `|&` still waits for a word (operand rule)
  let pipeWaiting = false;     // a `|` or `|&` still waits for a word (DP40 (a))
  const statements = [];
  let commands = [];
  let current = { assignments: [], words: [], op: '' };
  let pendingOr = false;
  const record = (raw, redirect) => {
    const { value, unknown } = wordValue(raw);
    current.words.push({ value, unknown, redirect });
  };
  const finishWord = (next) => {
    if (!inWord) return true;
    inWord = false;
    const raw = word.join('');
    if (targetWord) { targetWord = false; record(raw, true); return true; }
    if ((next === '<' || next === '>') && GRAMMAR_DIGITS.test(raw)) { record(raw, true); return true; } // the fd
    const assignment = GRAMMAR_ASSIGNMENT.exec(raw);
    if (!commandSeen) {
      if (assignment) {
        current.assignments.push(raw);
        return !BR6_INTEGER_VARIABLES.has(assignment[1]);
      }
      commandSeen = true;
      if (!GRAMMAR_COMMAND_WORD.test(raw)) return false;
      if (BR6_RESERVED_WORDS.has(raw) || (BR6_BASH_BUILTINS.has(raw) && !BR6_SAFE_BUILTINS.has(raw))) return false;
      safeBuiltin = BR6_SAFE_BUILTINS.has(raw);
      setCommand = raw === 'set';
      exportCommand = raw === 'export';
      record(raw, false);
      return true;
    }
    record(raw, false);
    if (exportCommand) return assignment ? !BR6_INTEGER_VARIABLES.has(assignment[1]) : GRAMMAR_PLAIN_ARGUMENT.test(raw);
    return !setCommand || GRAMMAR_SET_OPTION.test(raw) || GRAMMAR_SET_WORDS.has(raw);
  };
  const endSimpleCommand = (op) => {
    commandSeen = false;
    safeBuiltin = false;
    setCommand = false;
    exportCommand = false;
    current.op = op;
    if (current.assignments.length || current.words.length) commands.push(current);
    current = { assignments: [], words: [], op: '' };
  };
  const endStatement = (viaOr) => {
    if (commands.length) {
      statements.push({ viaOr: pendingOr, commands });
      pendingOr = false;
    }
    commands = [];
    if (viaOr) pendingOr = true;
  };
  let i = 0;
  while (i < length) {
    const c = str[i];
    const n = i + 1 < length ? str[i + 1] : '';
    if (c === '[' && safeBuiltin) return null;
    if (c === ' ' || c === '\t') {
      if (!finishWord(c)) return null;
      wordStart = true;
      i += 1;
      continue;
    }
    if ((c === ';' || c === '\n' || c === '|' || c === '&') && !(c === '&' && n === '>')) {
      if (!finishWord(c) || redirectPending) return null;
      let op = c;
      if (c === '|' && (n === '|' || n === '&')) op = c + n;
      else if (c === '&' && n === '&') op = '&&';
      i += op.length;
      if (op !== '\n' && !(current.assignments.length || current.words.length)) {
        return null; // an operator after an empty simple command (operand rule)
      }
      if (op === '\n' && pipeWaiting) return null; // bash joins the next line into the pipeline (DP40 (a))
      waiting = op === '&&' || op === '||' || op === '|' || op === '|&' || (waiting && op === '\n');
      pipeWaiting = op === '|' || op === '|&';
      if (op === ';' || op === '\n' || op === '||') {
        endSimpleCommand('');
        endStatement(op === '||');
      } else {
        endSimpleCommand(op);
      }
      wordStart = true;
      continue;
    }
    if (c === '<' || c === '>' || c === '&') { // `&` here is `&>` or `&>>`
      if (!finishWord(c) || redirectPending) return null;
      if (c === '&') i += str.startsWith('&>>', i) ? 3 : 2;
      else if (c === '<') {
        if (n === '<' || n === '(') return null;
        i += n === '>' || n === '&' ? 2 : 1;
      } else {
        if (n === '(') return null;
        i += n === '>' || n === '|' || n === '&' ? 2 : 1;
      }
      redirectPending = true;
      wordStart = true;
      continue;
    }
    const code = str.charCodeAt(i);
    if (c === '(' || c === ')' || c === '{' || c === '}' || c === '`' || code < 32 || code === 127) return null;
    if (!inWord) {
      if (c === '#' && wordStart) {
        if (redirectPending) return null;
        const nl = str.indexOf('\n', i);
        i = nl === -1 ? length : nl;
        continue;
      }
      if (c === '\\' && n === '\n') { i += 2; continue; } // a continuation keeps the word-start state
      inWord = true;
      waiting = false;
      pipeWaiting = false;
      word = [];
      targetWord = redirectPending;
      redirectPending = false;
    }
    if (c === '$') {
      if (!n || !GRAMMAR_PARAMETER_CHARS.has(n)) return null;
      word.push(str.slice(i, i + 2));
      i += 2;
    } else if (c === '\\') {
      if (n === '\n') { i += 2; continue; } // removed from the word, as bash removes it
      if (!n || (safeBuiltin && n === '[')) return null;
      word.push(str.slice(i, i + 2));
      i += 2;
    } else if (c === "'") {
      const end = str.indexOf("'", i + 1);
      if (end === -1 || (safeBuiltin && str.slice(i, end).includes('['))) return null;
      word.push(str.slice(i, end + 1));
      i = end + 1;
    } else if (c === '"') {
      let scan = i + 1;
      for (;;) {
        if (scan >= length) return null; // unterminated
        const inner = str[scan];
        if (inner === '"') break;
        if (inner === '\\') {
          if (scan + 1 >= length || (safeBuiltin && str[scan + 1] === '[')) return null;
          scan += 2;
          continue;
        }
        if (inner === '$') {
          const following = scan + 1 < length ? str[scan + 1] : '';
          if (!following || !GRAMMAR_PARAMETER_CHARS.has(following)) return null;
          scan += 2;
          continue;
        }
        const innerCode = str.charCodeAt(scan);
        if (inner === '`' || (innerCode < 32 && inner !== '\t' && inner !== '\n') || innerCode === 127) return null;
        if (safeBuiltin && inner === '[') return null;
        scan += 1;
      }
      word.push(str.slice(i, scan + 1));
      i = scan + 1;
    } else if (c === '[') {
      if (n === '[') return null;
      word.push(c);
      i += 1;
    } else if (c === '#' || GRAMMAR_WORD_CHARS.has(c) || code >= 0x80) {
      word.push(c);
      i += 1;
    } else {
      return null;
    }
    wordStart = false;
  }
  if (!finishWord('') || redirectPending || waiting) return null;
  endSimpleCommand('');
  endStatement(false);
  return statements;
}

// True only when the command lies inside the D23 safe grammar with the DP39 operand rule.
export function inSafeBr6Grammar(command) {
  return br6SimpleCommands(command) !== null;
}

// True when the command holds a `;`, newline or `||` (so bash could form a second BR6 statement) and lies
// outside the safe shell grammar, whose constructs and command words can hide such a separator, shadow the
// runner or rewrite the exit status. No exit code of such a command is attributed and no delivery read
// counts. Disclosed conservative limit: a legitimate `cd repo; pytest $(cat args)` or
// `source .venv/bin/activate; pytest` gives a false 'missing', never a false satisfy.
export function hasUnmodeledShellSyntax(command) {
  const str = String(command || '');
  if (!(str.includes(';') || str.includes('\n') || str.includes('||'))) return false;
  return !inSafeBr6Grammar(str);
}

// Visit every character outside single/double quotes and comments that is not backslash-escaped. A
// visit that returns false stops the scan. `onComment(i)`, when given, sees the index of each word-start `#`
// that opens a comment; returning false from it stops the scan too.
function forEachUnquoted(str, visit, onComment) {
  let q = null;
  let wordStart = true;
  for (let i = 0; i < str.length; i += 1) {
    const c = str[i];
    if (q) {
      if (c === q) q = null;
      else if (q === '"' && c === '\\') i += 1;
      continue;
    }
    if (c === '\\') { i += 1; wordStart = false; continue; }
    if (c === "'" || c === '"') { q = c; wordStart = false; continue; }
    if (c === '#' && wordStart) {
      if (onComment && onComment(i) === false) return;
      i = commentEnd(str, i) - 1;
      continue;
    }
    wordStart = COMMENT_BOUNDARY.has(c);
    if (visit(i, c, str[i + 1]) === false) return;
  }
}

export function hasUnquotedPipe(statement) {
  let pipe = false;
  let skip = -1;
  forEachUnquoted(String(statement || ''), (i, c, n) => {
    if (i === skip || c !== '|') return true;
    if (n === '|') { skip = i + 1; return true; } // `||` separates statements; it is not a pipe
    pipe = true;                                   // `|` or `|&`
    return false;
  });
  return pipe;
}

// A background job `&` gives the shell's own exit status, never the job's, so no exit code of such a statement is
// attributed (D21). A `&` joined to an adjacent unquoted `&`, `>`, `<` or `|` before it, or `&` or `>` after it, is
// part of `&&`, `>&`, `<&`, `|&`, `&>` or `&>>`. Neighbours are read only through the recorded unquoted indexes, so
// an escaped neighbour (`pytest \&& wait`) never joins, and a `&` inside a comment is never visited. Linear.
export function hasUnquotedBackground(statement) {
  const str = String(statement || '');
  const unquoted = new Uint8Array(str.length);
  const amps = [];
  forEachUnquoted(str, (i, c) => {
    unquoted[i] = 1;
    if (c === '&') amps.push(i);
    return true;
  });
  const operatorAt = (i, chars) => i >= 0 && i < str.length && unquoted[i] === 1 && chars.includes(str[i]);
  return amps.some((i) => !operatorAt(i - 1, '&><|') && !operatorAt(i + 1, '&>'));
}

// Inside double quotes a backslash is removed only before these characters (bash quote removal).
const DOUBLE_QUOTE_ESCAPES = new Set(['$', '`', '"', '\\', '\n']);

// { value, unknown } of one raw grammar word after bash quote and backslash removal (DP37 (a)). A word is UNKNOWN
// when it holds an unquoted or double-quoted `$`, or when its value has no `/` and it holds an unquoted `*`, `?` or
// `[` or starts with an unquoted `~`. The raw word already lies inside the grammar, so every quote it opens is
// closed. Linear. scripts/run_procedure_eval.py _br6_word_value mirrors this.
function wordValue(raw) {
  const value = [];
  let unknown = false;
  let pattern = raw.startsWith('~');
  let i = 0;
  while (i < raw.length) {
    const c = raw[i];
    if (c === '\\') {
      if (i + 1 < raw.length && raw[i + 1] !== '\n') value.push(raw[i + 1]);
      i += 2;
    } else if (c === "'") {
      const end = raw.indexOf("'", i + 1);
      value.push(raw.slice(i + 1, end));
      i = end + 1;
    } else if (c === '"') {
      i += 1;
      while (raw[i] !== '"') {
        const inner = raw[i];
        if (inner === '\\') {
          if (DOUBLE_QUOTE_ESCAPES.has(raw[i + 1])) {
            if (raw[i + 1] !== '\n') value.push(raw[i + 1]);
          } else {
            value.push(raw.slice(i, i + 2));
          }
          i += 2;
          continue;
        }
        if (inner === '$') unknown = true;
        value.push(inner);
        i += 1;
      }
      i += 1;
    } else {
      if (c === '$') unknown = true;
      if (c === '*' || c === '?' || c === '[') pattern = true;
      value.push(c);
      i += 1;
    }
  }
  const joined = value.join('');
  return { value: joined, unknown: unknown || (pattern && !joined.includes('/')) };
}

// DP39 (3) runner rule. BR6_RUNNER_MAX_WORDS is the longest testCommand alternative in words (an optional group
// counts at its maximum). The word patterns carry neither the `i` nor the `u` flag, so they never fold case.
const BR6_RUNNER_MAX_WORDS = 3;
const BR6_RUNNER_WORD = /^[A-Za-z0-9]+$/;
const BR6_PYTHON_WORD = /^(?:python[0-9.]*|py)$/;
// DP40 (b): only the `py` launcher takes a selector word, and only -2, -3 or -3.<digits> select a runtime; -0 lists
// the runtimes and exits 0, other digit words make the launcher or Python exit nonzero without running tests.
const BR6_PY_SELECTOR = /^-[23](?:\.[0-9]+)?$/;
// DP40 (d): a script-name runner word (`npm run test:unit`, `pnpm test:e2e`, `yarn test:unit`, `make test-unit`).
const BR6_SCRIPT_RUNNERS = new Set(['make', 'npm', 'pnpm', 'yarn']);
const BR6_SCRIPT_WORD = /^([A-Za-z0-9]+)[.:-][A-Za-z0-9.:_-]+$/;
// DP40 (c): version, help and no-run spellings.
const BR6_PACKAGE_MANAGERS = new Set(['npm', 'pnpm', 'yarn']);
// DP41 (b): a single-dash word (a `-` not followed by `-`) holding the key letter anywhere counts, because jest and
// vitest act on `h` anywhere in a short-option group (`jest -x1h`). Each pattern excludes its key letter before the
// key and has no end anchor, so a match has one split and every word is decided in linear time.
const BR6_HELP_CLUSTER = /^-(?!-)[^Vh]*[Vh]/;
// DP42 (a): a word is read by its leading dashes. One dash: BR6_HELP_CLUSTER (DP41 (b)). Two dashes: the maximal
// ASCII-letter run directly after `--` counts when, lowercased, it is a prefix of version, help or usage
// (`--help.x`, `--help-`, `--h.x`; not `--verbose`, `--no-help` or `--1help`), because yargs (jest) and cac
// (vitest) read dot-notation and camel-case tails as help or version. Three or more dashes always count
// (`jest ---help`, `vitest run ---xh`). The pattern carries no flags: `i` or `u` would change matching, and `g` or
// `y` would make this module-level regex stateful through `lastIndex`, because the code below calls `.exec` instead
// of `.test`. The pattern has no end anchor, so every word is decided in linear time.
const BR6_LONG_OPTION_HEAD = /^--([A-Za-z]+)/;
const BR6_LONG_VERSION_HELP = ['--version', '--help', '--usage'];
const BR6_VERSION_V_CLUSTER = /^-(?!-)[^v]*v/;
// Runners whose documented `-v` means verbose.
const BR6_VERBOSE_V_RUNNERS = new Set(['cargo', 'go', 'nox', 'pytest', 'tox', 'unittest']);
const BR6_PACKAGE_H_CLUSTER = /^-(?!-)[^H]*H/;
// Package-manager options that run an existing script and change nothing for a missing one (npm 11.13.0).
// `--if-present` is deliberately absent: it makes npm skip a missing script and exit 0 without running anything
// (D28 C1).
const BR6_PACKAGE_NEUTRAL = new Set(['-s', '--silent', '-q', '--quiet', '-d', '-dd', '-ddd']);
// `python -m <module>` runs tests only for these modules; any other module exits 1 (`No module named ...`) unrun.
const BR6_PYTHON_MODULES = new Set(['pytest', 'unittest', 'tox', 'nox']);

// How many leading words of a simple command name a test runner (DP39 (3)); 0 when it runs none. Only the words
// before the first redirection word count, and a redirection word before the first word gives 0. Generic form: the
// smallest k (1..BR6_RUNNER_MAX_WORDS) whose first k words are known, fully ASCII letters and digits, and whose
// single-space join the anchored pattern matches; word k (k >= 2) may instead be a script name (`test:unit`,
// `test-ci`, `test.x`) of make, npm (k === 3 only), pnpm or yarn whose `test` part completes the match (DP40 (d)).
// Python form: python[0-9.]* or py, a -2/-3/-3.<digits> selector word after `py` only (DP40 (b)), exactly -m, and a
// known module in BR6_PYTHON_MODULES that the anchored pattern matches.
// scripts/run_procedure_eval.py _br6_runner_word_count mirrors this.
function runnerWordCount(simpleCommand, anchored) {
  const { words } = simpleCommand;
  if (!words.length || words[0].redirect) return 0;
  const plain = [];
  for (const w of words) {
    if (w.redirect) break;
    plain.push(w);
  }
  if (BR6_PYTHON_WORD.test(plain[0].value)) {
    let k = 1;
    if (plain[0].value === 'py' && k < plain.length && BR6_PY_SELECTOR.test(plain[k].value)) k += 1;
    if (k + 1 < plain.length && plain[k].value === '-m') {
      const module = plain[k + 1];
      if (!module.unknown && BR6_PYTHON_MODULES.has(module.value) && anchored.test(module.value)) return k + 2;
    }
    return 0;
  }
  for (let k = 1; k <= Math.min(BR6_RUNNER_MAX_WORDS, plain.length); k += 1) {
    const w = plain[k - 1];
    if (w.unknown) return 0;
    if (!BR6_RUNNER_WORD.test(w.value)) {
      // DP40 (d): word k may still be a script name whose part before the first `.`, `:` or `-` is `test`.
      const m = BR6_SCRIPT_WORD.exec(w.value);
      if (k < 2 || !m || m[1].toLowerCase() !== 'test') return 0;
      const lead = plain[0].value.toLowerCase(); // plain[0] passed the ASCII word check
      if (BR6_SCRIPT_RUNNERS.has(lead) && (lead !== 'npm' || k === 3)
        && anchored.test(plain.slice(0, k - 1).map((x) => x.value).concat([m[1]]).join(' '))) return k;
      return 0;
    }
    if (anchored.test(plain.slice(0, k).map((x) => x.value).join(' '))) return k;
  }
  return 0;
}

// True when the statement text lies inside the grammar and one of its simple commands runs a test runner (DP39).
export function isBr6RunnerStatement(statement, testRe) {
  if (!testRe) return false;
  const parsed = br6SimpleCommands(statement);
  if (parsed === null) return false;
  const anchored = new RegExp('^(?:' + testRe.source + ')$', testRe.flags.replace(/[gy]/g, '')); // whole-string match
  return parsed.some((s) => s.commands.some((c) => runnerWordCount(c, anchored) > 0));
}

// DP40 (c) 1-3 and DP42 (a): UNKNOWN, an exact version/help flag, a single-dash word holding `V` or `h` anywhere
// (DP41 (b)), a word with three or more leading dashes, or a two-dash word whose leading ASCII-letter run is a
// case-insensitive prefix of version, help or usage (`--hel`, `--help=x`, `--help.x`, `--HELP-`).
// scripts/run_procedure_eval.py _br6_generic_version_or_help_word mirrors this.
function isGenericVersionOrHelpWord(w) {
  const v = w.value;
  if (w.unknown || VERSION_HELP_ARGS.has(v) || BR6_HELP_CLUSTER.test(v)) return true;
  if (v.startsWith('---')) return true;
  const m = BR6_LONG_OPTION_HEAD.exec(v);
  if (m === null) return false;
  const low = '--' + m[1].toLowerCase(); // ASCII only: the run passed the ASCII pattern
  return BR6_LONG_VERSION_HELP.some((o) => o.startsWith(low));
}

// DP40 (c): whether one argument word makes a runner command exit without running tests. Beyond the generic words,
// a single-dash word holding `v` anywhere counts unless `lead` documents `-v` as verbose; for npm, pnpm and yarn a
// single-dash word holding `H` anywhere counts, and so does any other `-` word before the first argument word `--`
// that is not on the BR6_PACKAGE_NEUTRAL allowlist. scripts/run_procedure_eval.py
// _br6_has_version_or_help_argument mirrors this.
function hasVersionOrHelpArgument(args, lead) {
  const packageManager = BR6_PACKAGE_MANAGERS.has(lead);
  const versionV = !BR6_VERBOSE_V_RUNNERS.has(lead);
  let beforeSeparator = true;
  for (const w of args) {
    if (isGenericVersionOrHelpWord(w)) return true;
    if (versionV && BR6_VERSION_V_CLUSTER.test(w.value)) return true;
    if (!packageManager) continue;
    // DP41 (a): a redirection target spelled `--` (bash consumes it) neither ends the option region nor counts as
    // an option word; only an argument word spelled `--` ends the region.
    if (beforeSeparator && w.value === '--') {
      if (!w.redirect) beforeSeparator = false;
      continue;
    }
    if (beforeSeparator && w.value.startsWith('-') && !BR6_PACKAGE_NEUTRAL.has(w.value)) return true;
    if (BR6_PACKAGE_H_CLUSTER.test(w.value)) return true;
  }
  return false;
}

// True only when the statement runs a runner and every simple command that runs one is version/help-only (DP39 (4),
// DP40 (c)): one of its argument words (every word after the runner words, redirection words included) passes
// hasVersionOrHelpArgument for the command's lead word (the module word of the Python form, else the first word);
// arguments after `--` count (`npm test -- --help`). A statement outside the grammar is neither.
// scripts/run_procedure_eval.py is_version_or_help_only mirrors this.
export function isVersionOrHelpOnly(statement, testRe) {
  if (!testRe) return false;
  const parsed = br6SimpleCommands(statement);
  if (parsed === null) return false;
  const anchored = new RegExp('^(?:' + testRe.source + ')$', testRe.flags.replace(/[gy]/g, '')); // whole-string match
  let runners = 0;
  for (const s of parsed) {
    for (const c of s.commands) {
      const count = runnerWordCount(c, anchored);
      if (count === 0) continue;
      runners += 1;
      // Both words passed an ASCII pattern in runnerWordCount, so toLowerCase folds ASCII only.
      const first = c.words[0].value;
      const lead = (BR6_PYTHON_WORD.test(first) ? c.words[count - 1].value : first).toLowerCase();
      if (!hasVersionOrHelpArgument(c.words.slice(count), lead)) return false;
    }
  }
  return runners > 0;
}

// Ordered per-call run records for strict evaluation (AC44). An independent scan with the same
// ceiling and fail-open discipline as readRolloutSignals, which stays untouched. One entry per
// distinct call_id, ordered by its first call event; seq is that record's ordinal. callEvents
// counts function_call exec_command plus exec_command_begin records, outputRecords counts
// function_call_output plus exec_command_end records, so a replayed or lost record stays visible.
// exitCode comes only from the native output header or a numeric exec_command_end exit_code;
// conflicting values give null. Calls without a call_id are omitted.
export function readRolloutRuns(path) {
  const EMPTY = { readable: false, runs: [] };
  if (!path || typeof path !== 'string') return EMPTY;
  let raw;
  try {
    const st = statSync(path);
    if (!st.isFile() || st.size > MAX) return EMPTY; // missing/non-file/over-ceiling -> unconfirmable
    raw = readFileSync(path, 'utf8');
  } catch {
    return EMPTY; // unreadable -> unconfirmable
  }

  const runs = [];
  const runById = new Map();
  const outputCount = new Map(); // call_id -> output record count (either order relative to the call)
  const exitCodes = new Map();   // call_id -> Set of parsed exit codes
  let seq = -1;
  for (const line of raw.split(/\r?\n/)) {
    if (!line) continue;
    seq += 1;
    let o;
    try { o = JSON.parse(line); } catch { continue; } // tolerate a malformed line
    const p = payloadOf(o);
    if (!p || typeof p !== 'object' || p.call_id == null) continue;

    let command = null;
    if (p.type === 'function_call' && p.name === 'exec_command') {
      const cmd = parseArgs(p.arguments)?.cmd;
      command = Array.isArray(cmd) ? cmd.map((x) => String(x)).join(' ') : (typeof cmd === 'string' ? cmd : '');
    } else if (p.type === 'exec_command_begin') {
      const parsed = Array.isArray(p.parsed_cmd) ? p.parsed_cmd.filter((x) => typeof x === 'string').join(' ') : '';
      command = typeof p.command === 'string' && p.command ? p.command : parsed;
    }
    if (command !== null) {
      let run = runById.get(p.call_id);
      if (!run) {
        run = { callId: p.call_id, command, seq, callEvents: 0, outputRecords: 0, exitCode: null };
        runById.set(p.call_id, run);
        runs.push(run);
      }
      run.callEvents += 1;
      continue;
    }

    let exit;
    if (p.type === 'function_call_output') exit = parseCodexExitCode(outputTextOf(p.output));
    else if (p.type === 'exec_command_end') exit = typeof p.exit_code === 'number' ? p.exit_code : null;
    else continue;
    outputCount.set(p.call_id, (outputCount.get(p.call_id) || 0) + 1);
    if (exit !== null) {
      if (!exitCodes.has(p.call_id)) exitCodes.set(p.call_id, new Set());
      exitCodes.get(p.call_id).add(exit);
    }
  }
  for (const run of runs) {
    run.outputRecords = outputCount.get(run.callId) || 0;
    const codes = exitCodes.get(run.callId);
    run.exitCode = codes && codes.size === 1 ? [...codes][0] : null;
  }
  return { readable: true, runs };
}

// ---------------------------------------------------------------------------
// Process-owner signals for the Codex completion hook (publication-readiness 0.4.3, BR18/BR19).
// A phase is Superpowers-owned only when the LAST user-authored choice names superpowers:<skill> AND
// that skill's installed body was read successfully after the choice and after any later compaction
// boundary. Choices come only from user-role input_text items; injected blocks (instruction files,
// environment context, bootstrap, hook feedback), assistant text, tool output and compaction summaries
// never carry one. Anything short of that proof is Ambiguous, never a silent exemption. Pure and
// linear: fixed-class patterns with bounded lookarounds, no spawn.
const QUALIFIED_CHOICE = /(?<![A-Za-z0-9_./:-])(superpowers|agentic-sdlc):([a-z0-9]+(?:-[a-z0-9]+)*)(?![A-Za-z0-9_-])/g;
const HOUSE_CHOICE = /(?<![A-Za-z0-9_./:-])AGENTIC-SDLC(?![A-Za-z0-9_-])/g;
const SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
// The exact rest of an installed Superpowers skill body path after `<Codex home>/plugins/cache/`.
const INSTALLED_SUPERPOWERS_REST = /^[^/]+\/superpowers\/[^/]+\/skills\/([^/]+)\/SKILL\.md$/;
const INJECTED_TAG = /^<([A-Za-z_][A-Za-z0-9_.:-]*)[\s>]/;
// The heading Codex prepends to an injected instruction-file block: `# <file>.md instructions for <dir>`.
const INJECTED_INSTRUCTIONS = /^# [A-Za-z0-9_.-]+\.md instructions\b/;
const VERIFICATION_SKILL = 'verification-before-completion';

export function ownerChoicesIn(text) {
  const str = String(text || '');
  const found = [];
  for (const m of str.matchAll(QUALIFIED_CHOICE)) {
    found.push({ index: m.index, owner: m[1] === 'superpowers' ? 'superpowers' : 'house', skill: m[2] });
  }
  for (const m of str.matchAll(HOUSE_CHOICE)) found.push({ index: m.index, owner: 'house', skill: null });
  found.sort((a, b) => a.index - b.index);
  return found.map(({ owner, skill }) => ({ owner, skill }));
}

function withoutTrailingSlashes(p) {
  let end = p.length;
  while (end > 1 && p[end - 1] === '/') end -= 1; // a loop, not a `/+$` regex (quadratic on a long run)
  return p.slice(0, end);
}

// D25 model (3): a literal path holds only ASCII letters, digits, `_ . - @ + , /`, characters at or above U+0080
// and an optional drive `X:`, so bash reads it as the same bytes (no expansion, quote, escape or blank).
const LITERAL_ABSOLUTE_PATH = /^(?:[A-Za-z]:)?\/[A-Za-z0-9_.\-@+,/\u0080-\uFFFF]*$/;
const WORD_BLANKS = /[ \t\n]+/;

// A literal absolute path whose segments after the root are never empty, `.` or `..`.
function isCanonicalLiteralPath(p) {
  if (!LITERAL_ABSOLUTE_PATH.test(p)) return false;
  const rest = p.slice(p.indexOf('/') + 1);
  return rest.split('/').every((seg) => seg !== '' && seg !== '.' && seg !== '..');
}

// The Codex home: CODEX_HOME, else <home>/.codex, with backslashes turned into `/` and trailing `/` stripped.
// Null unless the result is a canonical absolute literal path. No filesystem call.
export function resolveCodexHome(env = process.env, home = homedir()) {
  return canonicalHome(env && env.CODEX_HOME ? String(env.CODEX_HOME) : `${home}/.codex`);
}

function canonicalHome(raw) {
  if (typeof raw !== 'string') return null;
  const p = withoutTrailingSlashes(raw.replace(/\\/g, '/'));
  return isCanonicalLiteralPath(p) ? p : null;
}

// The cwd with backslashes turned into `/`, and, when absolute, empty and `.` segments dropped and `..` applied.
function normalizedCwd(cwd) {
  const s = String(cwd || '').replace(/\\/g, '/');
  const drive = /^[A-Za-z]:/.test(s) ? s.slice(0, 2) : '';
  const rest = s.slice(drive.length);
  if (!rest.startsWith('/')) return withoutTrailingSlashes(s);
  const kept = [];
  for (const seg of rest.split('/')) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') kept.pop();
    else kept.push(seg);
  }
  return `${drive}/${kept.join('/')}`;
}

// BR19 delivery read (D9, D25 model (3)): the command, read under the D23 safe grammar and the BR6 split, is
// exactly one statement (empty and comment-only statements ignored) of exactly the two raw words `cat` and a
// literal, canonical path under `<codexHome>/plugins/cache/` (case-folded when a drive is present) whose rest is
// exactly `<marketplace>/superpowers/<version>/skills/<skill>/SKILL.md`, and the path lies outside the lexically
// normalized cwd. Anything else (an earlier `cd`, write or other command, a pipe, background or `&&`, an
// expansion, glob, quote or backslash, a non-canonical path, another home spelling, a null home) returns null,
// which leaves the phase Ambiguous.
export function deliveryReadSkill(command, cwd, codexHome = resolveCodexHome()) {
  const home = canonicalHome(codexHome); // an explicit home gets the same normalization as a resolved one
  if (!home || !inSafeBr6Grammar(command)) return null;
  const joined = splitBr6StatementJoins(command);
  if (joined.length !== 1 || joined[0].viaOr) return null;
  const words = joined[0].text.split(WORD_BLANKS);
  if (words.length !== 2 || words[0] !== 'cat') return null;
  const path = words[1];
  if (!isCanonicalLiteralPath(path)) return null;
  const drive = /^[A-Za-z]:/.test(path);
  const fold = (s) => (drive ? s.toLowerCase() : s);
  const anchor = `${home}/plugins/cache/`;
  if (!fold(path).startsWith(fold(anchor))) return null;
  const m = INSTALLED_SUPERPOWERS_REST.exec(path.slice(anchor.length));
  if (!m || !SKILL_NAME.test(m[1])) return null;
  const base = normalizedCwd(cwd);
  if (base === '/') return null;
  const prefix = base.endsWith('/') ? base : `${base}/`;
  if (base && (fold(path) === fold(base) || fold(path).startsWith(fold(prefix)))) return null;
  return m[1];
}

function hookAuthored(message) {
  const kinds = message.internal_chat_message_metadata_passthrough?.content_item_kinds;
  return Array.isArray(kinds) && kinds.some((k) => typeof k === 'string' && k.startsWith('hooks.'));
}

function isInjectedItem(text) {
  const t = text.trim();
  if (INJECTED_INSTRUCTIONS.test(t)) return true;
  const m = INJECTED_TAG.exec(t);
  return Boolean(m) && t.endsWith(`</${m[1]}>`);
}

// `codexHome` is resolved once per call (default: the process environment); a null home counts no delivery.
export function readOwnerSignals(path, cwd, codexHome = resolveCodexHome()) {
  const EMPTY = { readable: false, phase: 'house', skill: null, verificationDelivered: false };
  if (!path || typeof path !== 'string') return EMPTY;
  let raw;
  try {
    const st = statSync(path);
    if (!st.isFile() || st.size > MAX) return EMPTY; // missing/non-file/over-ceiling -> unconfirmable
    raw = readFileSync(path, 'utf8');
  } catch {
    return EMPTY; // unreadable -> unconfirmable
  }

  const choices = [];      // { seq, owner, skill } in rollout order
  const boundaries = [];   // seq of each compaction boundary, ascending
  const calls = new Map(); // call_id -> { seq, command } of the first exec_command call event
  const exits = new Map(); // call_id -> Set of correlated exit codes
  let seq = -1;
  for (const line of raw.split(/\r?\n/)) {
    if (!line) continue;
    seq += 1;
    let o;
    try { o = JSON.parse(line); } catch { continue; } // tolerate a malformed line
    if (o && o.type === 'compacted') { boundaries.push(seq); continue; } // replacement_history is never scanned
    const p = payloadOf(o);
    if (!p || typeof p !== 'object') continue;
    if (p.type === 'context_compacted') { boundaries.push(seq); continue; } // event_msg carrier (assumption)
    if (p.type === 'message') {
      if (p.role === 'user' && Array.isArray(p.content) && !hookAuthored(p)) {
        for (const item of p.content) {
          if (!item || item.type !== 'input_text' || typeof item.text !== 'string' || isInjectedItem(item.text)) continue;
          for (const choice of ownerChoicesIn(item.text)) choices.push({ seq, ...choice });
        }
      }
      continue;
    }
    if (p.call_id == null) continue;
    if (p.type === 'function_call' && p.name === 'exec_command') {
      const cmd = parseArgs(p.arguments)?.cmd;
      const command = Array.isArray(cmd) ? cmd.map((x) => String(x)).join(' ') : (typeof cmd === 'string' ? cmd : '');
      if (!calls.has(p.call_id)) calls.set(p.call_id, { seq, command });
    } else if (p.type === 'exec_command_begin') {
      if (!calls.has(p.call_id) && typeof p.command === 'string') calls.set(p.call_id, { seq, command: p.command });
    } else {
      let exit = null;
      if (p.type === 'function_call_output') exit = parseCodexExitCode(outputTextOf(p.output));
      else if (p.type === 'exec_command_end' && typeof p.exit_code === 'number') exit = p.exit_code;
      if (exit === null) continue;
      if (!exits.has(p.call_id)) exits.set(p.call_id, new Set());
      exits.get(p.call_id).add(exit);
    }
  }

  const deliveries = []; // { seq, skill } of successful installed-body reads
  for (const [callId, call] of calls) {
    const codes = exits.get(callId);
    if (!codes || codes.size !== 1 || !codes.has(0)) continue;
    const skill = deliveryReadSkill(call.command, cwd, codexHome);
    if (skill) deliveries.push({ seq: call.seq, skill });
  }

  // The last choice wins; repeating the current Superpowers skill does not start a new phase.
  let phase = { owner: 'house', skill: null, start: -1 };
  for (const choice of choices) {
    const repeat = choice.owner === 'superpowers' && phase.owner === 'superpowers' && choice.skill === phase.skill;
    if (!repeat) phase = { owner: choice.owner, skill: choice.skill, start: choice.seq };
  }
  const verificationDelivered = deliveries.some((d) => d.skill === VERIFICATION_SKILL && d.seq > phase.start);
  if (phase.owner === 'house') return { readable: true, phase: 'house', skill: null, verificationDelivered };
  const boundary = boundaries.reduce((last, b) => (b > phase.start ? b : last), phase.start);
  const delivered = deliveries.some((d) => d.skill === phase.skill && d.seq > boundary);
  return { readable: true, phase: delivered ? 'superpowers' : 'ambiguous', skill: phase.skill, verificationDelivered };
}
