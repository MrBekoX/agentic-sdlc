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
// Carriers (DP-E union; carrier SHAPES stay labelled VERIFY, reused from AP1/AP2a probes):
//   commands  - function_call exec_command {cmd}, AND event_msg exec_command_begin {command, parsed_cmd}.
//   edits     - function_call apply_patch/patch {input: <V4A patch>}, AND event_msg patch_apply_begin {changes}.
// Edit targets are read ONLY from patch carriers via extractWrittenContent('apply_patch', ...), which
// always routes to the V4A patch parser - a command string is NEVER inspected for an edit target, so a
// Bash redirect/heredoc/`sed -i` surfaces no edit (AC27 fail-open).
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

// A2 substrate: codex prepends an `Exit code: N` line to an exec `function_call_output` (OFFICIAL-
// SOURCE openai/codex rust-v0.142.x). Parse the FIRST line-anchored occurrence as the run's real exit
// status. LINEAR ([ \t]* avoids any \s*-over-newline ambiguity). RESIDUAL: the combined stdout/stderr
// is agent/tool-authored, so the exact placement of codex's own line vs. a tool-printed one needs a
// LIVE rollout capture to pin down; matching the first line-anchored occurrence is the best-effort
// heuristic within the bounded-backstop posture (flagged in the A2 report).
export function parseCodexExitCode(text) {
  if (typeof text !== 'string') return null;
  const m = /(?:^|\n)[ \t]*Exit code:\s*(-?\d+)/.exec(text);
  return m ? Number(m[1]) : null;
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
  const REDIRECT = /[^0-9&>]>>?\s*(['"]?)([^\s'";&|<>()]+)/g; // LINEAR (disjoint classes, no nested quantifier)
  const TEE = /\btee\b\s+(?:-a\s+)?([^\s;|&<>'"]+)/g;          // LINEAR
  // B3: in-place / pipe writes that carry no `>` redirect. `tee [-a]` writes its file argument. `sed -i`
  // rewrites its file argument(s) — the file is the LAST token of the sed statement (best-effort: only the
  // last file of a multi-file sed). The earlier single-regex SED form used a `(?=...)` lookahead that
  // re-scanned the tail at every `\bsed\b`, which is O(n^2) on a crafted command of many `sed ` tokens
  // (a default-reachable ReDoS). Instead split on shell statement boundaries FIRST (O(n)), then read each
  // sed statement's last token once — total linear, no lookahead, so an 8 MiB rollout cannot DoS the hook.
  const SED_LAST = /\s([^\s;|&<>'"]+)\s*$/;
  const pushWriteTargets = (s) => {
    const str = String(s);
    for (const m of str.matchAll(REDIRECT)) editTargets.push(m[2]);
    for (const m of str.matchAll(TEE)) editTargets.push(m[1]);
    for (const seg of str.split(/[;\n|&]+/)) {
      if (!/\bsed\b/.test(seg) || !/(?:^|\s)-i/.test(seg)) continue; // only an in-place sed is a write
      const m = seg.split('>')[0].match(SED_LAST); // drop any redirect tail (REDIRECT already has it)
      if (m) editTargets.push(m[1]);
    }
  };
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
