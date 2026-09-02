// Stop — deterministic backstop for the completion-claim-gate (contract 00, evidence-before-claim).
// If the agent's FINAL message makes a strong "done / complete / passing / ready" claim AND the
// session transcript shows NO completion-claim-gate skill invocation, this reminds (default) or,
// with AGENTIC_COMPLETION_GATE_BLOCK=true, blocks the stop so the gate runs.
//
// This is a DETERMINISTIC check (narrow claim pattern + gate-skill absence), complementing — not
// replacing — the judgment gate inside completion-claim-gate / implementation-control. Whether the
// evidence is GOOD stays a model judgment; this only catches the case where the gate was skipped
// entirely. Narrow patterns + warn-by-default keep false positives low. Fail-open on any error.
import { readFileSync } from 'node:fs';
import { readStdin } from './secret-patterns.mjs';

const BLOCK = /^(true|1|yes)$/i.test(String(process.env.AGENTIC_COMPLETION_GATE_BLOCK || ''));

// Strong, final-sounding completion claims (kept narrow to avoid false positives on casual "done").
const CLAIM =
  /\b(all\s+tests?\s+(pass|passing|green)|all\s+green|ready\s+to\s+(merge|ship)|ready\s+for\s+review|implementation\s+(is\s+)?complete|feature\s+complete|task\s+(is\s+)?complete|done\s+and\s+verified|fixed\s+and\s+verified|verified\s+and\s+(complete|done)|everything\s+(works|passes))\b/i;

// Phrases that signal the work is explicitly NOT finished — suppress to avoid false positives.
const NEGATED = /\b(not\s+(yet\s+)?(done|complete|ready|passing)|still\s+(failing|broken|todo)|incomplete|do\s+not\s+claim)\b/i;

function lastAssistantText(events) {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e?.type !== 'assistant') continue;
    const content = e?.message?.content;
    if (typeof content === 'string') return content;
    if (Array.isArray(content)) {
      const txt = content.filter((c) => c?.type === 'text').map((c) => c.text || '').join('\n');
      if (txt) return txt;
    }
  }
  return '';
}

// True if a Skill tool_use referencing completion-claim-gate appears anywhere in the transcript.
function gateInvoked(raw) {
  return /"skill"\s*:\s*"[^"]*completion-claim-gate"/.test(raw)
    || /"name"\s*:\s*"Skill"[\s\S]{0,400}?completion-claim-gate/.test(raw);
}

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { /* ignore */ }

// Avoid infinite loops: if this stop already results from a prior Stop-hook block, allow.
if (input?.stop_hook_active) process.exit(0);

const tpath = input?.transcript_path;
if (!tpath) process.exit(0);

let text = '';
let transcriptRaw = '';
try {
  transcriptRaw = readFileSync(tpath, 'utf8');
  const events = transcriptRaw
    .split(/\r?\n/)
    .filter(Boolean)
    .map((l) => { try { return JSON.parse(l); } catch { return null; } })
    .filter(Boolean);
  text = lastAssistantText(events);
} catch {
  process.exit(0); // fail-open: cannot read transcript
}

if (!text || !CLAIM.test(text) || NEGATED.test(text)) process.exit(0);
if (gateInvoked(transcriptRaw)) process.exit(0); // gate ran — nothing to do

const msg =
  'Final message claims completion but completion-claim-gate was not invoked this session ' +
  '(contract 00 — evidence before claim). Invoke agentic-sdlc:completion-claim-gate with the exact ' +
  'evidence (test/security/control output) before claiming done/fixed/passing/ready.';

const out = BLOCK
  ? { decision: 'block', reason: msg, systemMessage: '🚧 completion-claim-guard: blocked an unverified completion claim.' }
  : { systemMessage: `⚠️ completion-claim-guard: ${msg}` };
// Write, then exit only after stdout has flushed (avoids truncation on a piped stdout under Windows).
process.stdout.write(JSON.stringify(out), () => process.exit(0));
