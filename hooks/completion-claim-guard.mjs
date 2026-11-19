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
import { parseTranscript, skillInvoked } from './flow-evidence.mjs';
import { completionClaimed } from './codex-rollout.mjs';

const BLOCK = /^(true|1|yes)$/i.test(String(process.env.AGENTIC_COMPLETION_GATE_BLOCK || ''));

// Strong, final-sounding completion claims (kept narrow to avoid false positives on casual "done").
// FH-8: read through completionClaimed (codex-rollout.mjs), which scopes NEGATED to the claim's sentence
// and skips questions, conditionals and quoted spans; the Codex guard and the offline reader share it.
const CLAIM =
  /\b(?:all\s+(?:the\s+)?(?:\d+\s+)?tests?\s+(?:(?:are|have)\s+(?:now\s+)?)?(?:pass|passes|passed|passing|green)|all\s+green|ready\s+to\s+(?:merge|ship)|ready\s+for\s+review|implementation\s+(?:is\s+)?(?:now\s+)?completed?|feature\s+(?:is\s+)?completed?|task\s+(?:is\s+)?completed?|done\s+and\s+verified|fixed\s+and\s+verified|verified\s+and\s+(?:complete|done)|everything\s+(?:works|passes))\b|(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:(?:tüm|bütün)\s+(?:\d+\s+)?test(?:ler)?\s+(?:başarıyla\s+)?(?:geçti|geçiyor)|testlerin\s+(?:hepsi|tamamı)\s+(?:başarıyla\s+)?(?:geçti|geçiyor)|(?:uygulama|görev|geliştirme|özellik|düzeltme)\s+(?:başarıyla\s+)?tamamlandı|(?:birleştirmeye|incelemeye|yayına)\s+hazır|(?:düzeltildi|tamamlandı)\s+ve\s+doğrulandı|her\s+şey\s+çalışıyor)(?![A-Za-zÇĞİÖŞÜçğıöşü])/i;

// Phrases that signal the work is explicitly NOT finished — suppress to avoid false positives.
const NEGATED = /\b(?:not\s+(?:yet\s+)?(?:all|done|complete|completed|ready|passing|passed|green)|still\s+(?:failing|broken|todo)|incomplete|do\s+not\s+claim)\b|n['’]t\s+(?:yet\s+)?(?:been\s+)?(?:all\s+)?(?:done|complete|completed|ready|pass|passing|passed|green|work|working)\b|(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:hazır\s+değil|tamamlanmadı|geçmedi|geçmiyor)(?![A-Za-zÇĞİÖŞÜçğıöşü])/i;

function recordText(e) {
  const content = e?.message?.content;
  if (typeof content === 'string') return content;
  if (Array.isArray(content)) {
    return content.filter((c) => c?.type === 'text').map((c) => c.text || '').join('\n');
  }
  return '';
}

function lastAssistantText(events) {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e?.type !== 'assistant') continue;
    const txt = recordText(e);
    if (txt) return txt;
  }
  return '';
}

function collapseWs(s) {
  return String(s).trim().replace(/\s+/g, ' ');
}

function lastAssistantCaughtUpText(events) {
  let last = null;
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i]?.type === 'assistant') { last = events[i]; break; }
  }
  if (!last) return '';
  const id = last?.message?.id;
  if (typeof id === 'string' && id) {
    let out = '';
    for (const e of events) {
      if (e?.type === 'assistant' && e?.message?.id === id) out += recordText(e);
    }
    return out;
  }
  return recordText(last);
}

function transcriptCaughtUp(events, lastAssistantMessage) {
  return collapseWs(lastAssistantCaughtUpText(events)) === collapseWs(lastAssistantMessage);
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
let events = [];
try {
  transcriptRaw = readFileSync(tpath, 'utf8');
  events = transcriptRaw
    .split(/\r?\n/)
    .filter(Boolean)
    .map((l) => { try { return JSON.parse(l); } catch { return null; } })
    .filter(Boolean);
  const lam = input?.last_assistant_message;
  text = typeof lam === 'string' ? lam : lastAssistantText(events);
} catch {
  process.exit(0); // fail-open: cannot read transcript
}

if (!text || !completionClaimed(text, CLAIM, NEGATED)) process.exit(0);
// FH-7: the gate ran only if a non-errored Skill call names it exactly (not args, a look-alike or a prompt).
if (skillInvoked(parseTranscript(tpath), 'completion-claim-gate')) process.exit(0); // gate ran — nothing to do

const msg =
  'Final message claims completion but completion-claim-gate was not invoked this session ' +
  '(contract 00 — evidence before claim). Invoke agentic-sdlc:completion-claim-gate with the exact ' +
  'evidence (test/security/control output) before claiming done/fixed/passing/ready.';

const lam = input?.last_assistant_message;
const mayBlock = BLOCK && (typeof lam !== 'string' || transcriptCaughtUp(events, lam));
const out = mayBlock
  ? { decision: 'block', reason: msg, systemMessage: '🚧 completion-claim-guard: blocked an unverified completion claim.' }
  : { systemMessage: `⚠️ completion-claim-guard: ${msg}` };
// Write, then exit only after stdout has flushed (avoids truncation on a piped stdout under Windows).
process.stdout.write(JSON.stringify(out), () => process.exit(0));
