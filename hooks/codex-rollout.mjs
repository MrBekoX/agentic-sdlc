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
