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

  let lastTaskComplete = null;
  let lastAssistant = null;
  for (const line of raw.split(/\r?\n/)) {
    if (!line) continue;
    let o;
    try { o = JSON.parse(line); } catch { continue; } // tolerate a malformed line
    const p = payloadOf(o);
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
    const s = cur.trim();
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
// other code, or the exit status is rewritten, only through a reserved word, a builtin or a shell-variable
// assignment that needs `[` or `set -x`; a builtin a later bash adds is read as an external program (a
// disclosed limit), and how a name resolves outside the command text (PATH, profile functions) is not seen.
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
// printf, test, `[`, wait and unset stay out: each takes a variable name or evaluates an arithmetic subscript from
// an argument, so any expansion there (parameter, glob, tilde) can supply a BASH_CMDS subscript.
const BR6_SAFE_BUILTINS = new Set([':', 'cd', 'echo', 'export', 'false', 'pwd', 'set', 'true']);
const GRAMMAR_ALNUM = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
const GRAMMAR_WORD_CHARS = new Set(GRAMMAR_ALNUM + '_-./:=+,@%^~!?*]');
const GRAMMAR_PARAMETER_CHARS = new Set(GRAMMAR_ALNUM + '_?#$!@*-');
const GRAMMAR_COMMAND_WORD = /^[A-Za-z0-9_\-./:=+,@%^~!#\u0080-\uFFFF]+$/;
const GRAMMAR_ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*\+?=/;
const GRAMMAR_DIGITS = /^[0-9]+$/;
const GRAMMAR_SET_OPTION = /^[-+][euo]+$/;
const GRAMMAR_SET_WORDS = new Set(['errexit', 'nounset', 'pipefail']);

// One linear left-to-right pass. Inside the grammar: unquoted words, single quotes, double quotes without
// substitution, `$NAME`-style parameters, backslash pairs and continuations, word-start comments, the
// separators `;`, newline, `||`, `&&`, `|`, `|&` and a background `&`, and simple redirections followed by a
// word. Each simple command's command word is an external program or a BR6_SAFE_BUILTINS name; after such a
// builtin no later `[` may appear (an array subscript reaches BASH_CMDS); and `set` only takes the
// errexit/nounset/pipefail forms. A word of only
// digits directly before `<` or `>` is that redirection's file descriptor in any position. Always outside: `(`,
// `)`, `{`, `}`, a backtick, `[[`, `<<`, `<(` and `>(`.
// scripts/run_procedure_eval.py in_safe_br6_grammar mirrors this pass branch for branch.
export function inSafeBr6Grammar(command) {
  const str = String(command || '');
  const length = str.length;
  let word = [];
  let inWord = false;
  let wordStart = true;
  let commandSeen = false;
  let safeBuiltin = false;
  let setCommand = false;
  let redirectPending = false; // an operator was read and its target word has not started
  let targetWord = false;      // the current word is a redirection target
  const finishWord = (next) => {
    if (!inWord) return true;
    inWord = false;
    const raw = word.join('');
    if (targetWord) { targetWord = false; return true; }
    if ((next === '<' || next === '>') && GRAMMAR_DIGITS.test(raw)) return true; // the redirection's fd
    if (!commandSeen) {
      if (GRAMMAR_ASSIGNMENT.test(raw)) return true;
      commandSeen = true;
      if (!GRAMMAR_COMMAND_WORD.test(raw)) return false;
      if (BR6_RESERVED_WORDS.has(raw) || (BR6_BASH_BUILTINS.has(raw) && !BR6_SAFE_BUILTINS.has(raw))) return false;
      safeBuiltin = BR6_SAFE_BUILTINS.has(raw);
      setCommand = raw === 'set';
      return true;
    }
    return !setCommand || GRAMMAR_SET_OPTION.test(raw) || GRAMMAR_SET_WORDS.has(raw);
  };
  let i = 0;
  while (i < length) {
    const c = str[i];
    const n = i + 1 < length ? str[i + 1] : '';
    if (c === '[' && safeBuiltin) return false;
    if (c === ' ' || c === '\t') {
      if (!finishWord(c)) return false;
      wordStart = true;
      i += 1;
      continue;
    }
    if ((c === ';' || c === '\n' || c === '|' || c === '&') && !(c === '&' && n === '>')) {
      if (!finishWord(c) || redirectPending) return false;
      i += (c === '|' && (n === '|' || n === '&')) || (c === '&' && n === '&') ? 2 : 1;
      commandSeen = false;
      safeBuiltin = false;
      setCommand = false;
      wordStart = true;
      continue;
    }
    if (c === '<' || c === '>' || c === '&') { // `&` here is `&>` or `&>>`
      if (!finishWord(c) || redirectPending) return false;
      if (c === '&') i += str.startsWith('&>>', i) ? 3 : 2;
      else if (c === '<') {
        if (n === '<' || n === '(') return false;
        i += n === '>' || n === '&' ? 2 : 1;
      } else {
        if (n === '(') return false;
        i += n === '>' || n === '|' || n === '&' ? 2 : 1;
      }
      redirectPending = true;
      wordStart = true;
      continue;
    }
    const code = str.charCodeAt(i);
    if (c === '(' || c === ')' || c === '{' || c === '}' || c === '`' || code < 32 || code === 127) return false;
    if (!inWord) {
      if (c === '#' && wordStart) {
        if (redirectPending) return false;
        const nl = str.indexOf('\n', i);
        i = nl === -1 ? length : nl;
        continue;
      }
      if (c === '\\' && n === '\n') { i += 2; continue; } // a continuation keeps the word-start state
      inWord = true;
      word = [];
      targetWord = redirectPending;
      redirectPending = false;
    }
    if (c === '$') {
      if (!n || !GRAMMAR_PARAMETER_CHARS.has(n)) return false;
      word.push(str.slice(i, i + 2));
      i += 2;
    } else if (c === '\\') {
      if (n === '\n') { i += 2; continue; } // removed from the word, as bash removes it
      if (!n || (safeBuiltin && n === '[')) return false;
      word.push(str.slice(i, i + 2));
      i += 2;
    } else if (c === "'") {
      const end = str.indexOf("'", i + 1);
      if (end === -1 || (safeBuiltin && str.slice(i, end).includes('['))) return false;
      word.push(str.slice(i, end + 1));
      i = end + 1;
    } else if (c === '"') {
      let scan = i + 1;
      for (;;) {
        if (scan >= length) return false; // unterminated
        const inner = str[scan];
        if (inner === '"') break;
        if (inner === '\\') {
          if (scan + 1 >= length || (safeBuiltin && str[scan + 1] === '[')) return false;
          scan += 2;
          continue;
        }
        if (inner === '$') {
          const following = scan + 1 < length ? str[scan + 1] : '';
          if (!following || !GRAMMAR_PARAMETER_CHARS.has(following)) return false;
          scan += 2;
          continue;
        }
        const innerCode = str.charCodeAt(scan);
        if (inner === '`' || (innerCode < 32 && inner !== '\t' && inner !== '\n') || innerCode === 127) return false;
        if (safeBuiltin && inner === '[') return false;
        scan += 1;
      }
      word.push(str.slice(i, scan + 1));
      i = scan + 1;
    } else if (c === '[') {
      if (n === '[') return false;
      word.push(c);
      i += 1;
    } else if (c === '#' || GRAMMAR_WORD_CHARS.has(c) || code >= 0x80) {
      word.push(c);
      i += 1;
    } else {
      return false;
    }
    wordStart = false;
  }
  return finishWord('') && !redirectPending;
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
// visit that returns false stops the scan.
function forEachUnquoted(str, visit) {
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
    if (c === '#' && wordStart) { i = commentEnd(str, i) - 1; continue; }
    wordStart = COMMENT_BOUNDARY.has(c);
    if (visit(i, c, str[i + 1]) === false) return;
  }
}

// True when the command holds an unquoted heredoc operator (`<<` or `<<-`, not the `<<<` here-string).
// Its body lines are data to bash but separate statements to splitBr6Statements, so no exit code of
// such a command is attributed to its last statement. Disclosed conservative limit: an arithmetic shift
// such as `$((1<<2))` matches too, which gives a false 'missing', never a false satisfy.
export function hasUnquotedHeredoc(command) {
  const str = String(command || '');
  let heredoc = false;
  forEachUnquoted(str, (i, c, n) => {
    if (c !== '<' || n !== '<' || str[i - 1] === '<' || str[i + 2] === '<') return true;
    heredoc = true;
    return false;
  });
  return heredoc;
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

// Quote-aware argument words after the runner match, up to the first unquoted pipe.
function runnerArgs(segment, match) {
  let rest = segment.slice(match.index + match[0].length);
  forEachUnquoted(rest, (i, c) => {
    if (c !== '|') return true;
    rest = rest.slice(0, i);
    return false;
  });
  return shellTokens(rest);
}

// True only when every `&&` segment that contains a test-runner match passes a standalone
// --version, -V, --help or -h argument (arguments after `--` count). A statement with no runner
// segment is not version/help-only.
export function isVersionOrHelpOnly(statement, testRe) {
  if (!testRe) return false;
  const str = String(statement || '');
  const cuts = [];
  let skip = -1;
  forEachUnquoted(str, (i, c, n) => {
    if (i !== skip && c === '&' && n === '&') { cuts.push(i); skip = i + 1; }
    return true;
  });
  let runnerSegments = 0;
  let start = 0;
  for (const end of [...cuts, str.length]) {
    const segment = str.slice(start, end);
    start = end + 2;
    const match = testRe.exec(segment);
    if (!match) continue;
    runnerSegments += 1;
    if (!runnerArgs(segment, match).some((t) => VERSION_HELP_ARGS.has(t))) return false;
  }
  return runnerSegments > 0;
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
const INSTALLED_SUPERPOWERS_SKILL = /\/plugins\/cache\/[^/]+\/superpowers\/[^/]+\/skills\/([^/]+)\/SKILL\.md$/;
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

// BR19 delivery read (D9): only `cat <absolute installed SKILL.md path>` as the last statement counts.
// Any other form (a command outside the D23 safe shell grammar, pipe, background, `&&`, a `cd` anywhere, a
// relative path, a `..` segment, a path under the session cwd, a last statement reached through `||`)
// returns null, which leaves the phase Ambiguous.
export function deliveryReadSkill(command, cwd) {
  if (!inSafeBr6Grammar(command)) return null;
  const joined = splitBr6StatementJoins(command);
  if (!joined.length || joined.some((s) => s.text.startsWith('cd'))) return null;
  if (joined[joined.length - 1].viaOr) return null; // `true || cat <SKILL.md>` never runs the cat
  const last = joined[joined.length - 1].text;
  if (/[|&()`]/.test(last)) return null;
  const tokens = shellTokens(last);
  if (tokens.length !== 2 || tokens[0] !== 'cat') return null;
  const path = tokens[1].replace(/\\/g, '/');
  const drive = /^[A-Za-z]:\//.test(path);
  if (!(path.startsWith('/') || drive) || path.split('/').includes('..')) return null;
  const fold = (s) => (drive ? s.toLowerCase() : s);
  const base = withoutTrailingSlashes(String(cwd || '').replace(/\\/g, '/'));
  if (base === '/' || (base && (fold(path) === fold(base) || fold(path).startsWith(fold(base) + '/')))) return null;
  const m = INSTALLED_SUPERPOWERS_SKILL.exec(path);
  return m && SKILL_NAME.test(m[1]) ? m[1] : null;
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

export function readOwnerSignals(path, cwd) {
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
    const skill = deliveryReadSkill(call.command, cwd);
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
