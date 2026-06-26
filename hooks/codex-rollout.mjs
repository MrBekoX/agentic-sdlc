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

// ALL text strings carried by a message line (assistant, agent, task_complete, AND user) — the
// whole-rollout surface scanned for the sentinel (R3).
function carrierTexts(p) {
  const out = [];
  if (!p || typeof p !== 'object') return out;
  if (typeof p.message === 'string') out.push(p.message);                       // agent_message / user_message
  if (typeof p.last_agent_message === 'string') out.push(p.last_agent_message); // task_complete
  if (Array.isArray(p.content)) {
    for (const c of p.content) if (c && typeof c.text === 'string') out.push(c.text); // message content (asst+user)
  }
  return out;
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

  let gateMarkerPresent = false;
  let lastTaskComplete = null;
  let lastAssistant = null;
  for (const line of raw.split(/\r?\n/)) {
    if (!line) continue;
    let o;
    try { o = JSON.parse(line); } catch { continue; } // tolerate a malformed line
    const p = payloadOf(o);
    if (!gateMarkerPresent) {
      for (const t of carrierTexts(p)) if (t.includes(GATE_MARKER)) { gateMarkerPresent = true; break; }
    }
    const tc = taskCompleteText(p);
    if (tc != null) lastTaskComplete = tc;
    else {
      const at = assistantText(p);
      if (at != null) lastAssistant = at;
    }
  }
  const finalMessage = lastTaskComplete != null ? lastTaskComplete : (lastAssistant != null ? lastAssistant : '');
  return { finalMessage, gateMarkerPresent, readable: true };
}

// Additive second slice for the flow-step adapter (AP2b): surface the executed COMMANDS and the
// patch-style EDIT TARGETS a Codex session recorded, scoped to this rollout. Same fail-open
// discipline as readRollout: missing/non-file/over-ceiling/unreadable -> EMPTY readable:false, so the
// caller never blocks on an unconfirmable rollout. Pure: one read, JSON-decode per line, no eval,
// no spawn. readRollout / GATE_MARKER / carrierTexts / payloadOf are untouched (AC20).
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

export function readRolloutSignals(path) {
  const EMPTY = { commands: [], editTargets: [], readable: false };
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
  // A1/BR4a closure: a Codex shell-redirect WRITE is recorded as a raw command string (verified live:
  // exec_command {cmd:"printf 'hi' > note.txt"}), and codex often BUNDLES several writes into one
  // exec_command separated by newlines, so the single-write `extractWrittenContent` (which keys on a
  // trailing redirect) only catches the LAST target. Here we want every file a command redirected to,
  // so scan for ALL `>`/`>>` redirect targets across the whole command string — a spec/plan (or source)
  // written via a `>`/`>>` redirect is no longer invisible to flow-step/flow-order. fd redirects (`2>`,
  // `>&2`) are skipped. Still bounded (narrowed BR4a): a `bash -lc`-wrapped redirect, `sed -i`, `tee`,
  // a `cat` copy, `base64`, or a `$`-expansion target are not surfaced. Pure: a single regex scan.
  const REDIRECT = /[^0-9&>]>>?\s*(['"]?)([^\s'";&|<>()]+)/g;
  const pushRedirectTargets = (s) => {
    for (const m of String(s).matchAll(REDIRECT)) editTargets.push(m[2]);
  };
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
        if (s != null) { commands.push(s); pushRedirectTargets(s); }
      } else if (p.name === 'apply_patch' || p.name === 'patch') {
        const patchText = a && a.input;
        if (typeof patchText === 'string') {
          for (const t of extractWrittenContent('apply_patch', patchText).targets) editTargets.push(t);
        }
      }
    } else if (p.type === 'exec_command_begin') {
      if (typeof p.command === 'string' && p.command) { commands.push(p.command); pushRedirectTargets(p.command); }
      if (Array.isArray(p.parsed_cmd)) {
        const toks = p.parsed_cmd.filter((x) => typeof x === 'string');
        if (toks.length) commands.push(toks.join(' '));
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
  return { commands, editTargets, readable: true };
}
