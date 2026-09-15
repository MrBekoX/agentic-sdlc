// Stop (Codex) — deterministic backstop for the completion-claim-gate (contract 00, evidence-before-claim).
// Codex emits no reliable skill-activation signal in its rollout (Phase-0d), so instead of detecting a
// Skill tool_use (the Claude guard's mechanism), this detects the gate's deterministic SENTINEL MARKER
// (GATE_MARKER): if the FINAL message makes a strong "done/passing/ready" claim AND the gate's marker is
// absent from a READABLE rollout, it reminds (default: non-blocking systemMessage) or, with
// AGENTIC_COMPLETION_GATE_BLOCK=true, blocks the stop so the gate runs.
//
// Claude parity: the CLAIM/NEGATED patterns and the BLOCK env check are COPIED byte-for-byte from
// completion-claim-guard.mjs (that file stays byte-identical; a parity test enforces the copy). The
// Claude guard keeps its own Skill tool_use detection — this marker path is the Codex signal only.
// Fail-open on any error; never reflects claim/transcript bytes into the output.
//
// Owner scoping (publication-readiness 0.4.3, BR17/BR18/BR21): when readOwnerSignals reports a
// Superpowers-owned or Ambiguous phase, the message is a fixed owner-neutral string that names no
// house or Superpowers procedure, and a successful superpowers:verification-before-completion
// delivery recorded after the phase start silences it. The no-owner, house-owned and unreadable
// owner-scan paths keep the 5801cb9 output bytes.
import { readStdin } from './secret-patterns.mjs';
import { GATE_MARKER, readRollout, readOwnerSignals } from './codex-rollout.mjs';

const BLOCK = /^(true|1|yes)$/i.test(String(process.env.AGENTIC_COMPLETION_GATE_BLOCK || ''));

// Strong, final-sounding completion claims (COPIED from completion-claim-guard.mjs — keep byte-identical).
const CLAIM =
  /\b(all\s+tests?\s+(pass|passing|green)|all\s+green|ready\s+to\s+(merge|ship)|ready\s+for\s+review|implementation\s+(is\s+)?complete|feature\s+complete|task\s+(is\s+)?complete|done\s+and\s+verified|fixed\s+and\s+verified|verified\s+and\s+(complete|done)|everything\s+(works|passes))\b/i;

// Phrases that signal the work is explicitly NOT finished (COPIED — keep byte-identical).
const NEGATED = /\b(not\s+(yet\s+)?(done|complete|ready|passing)|still\s+(failing|broken|todo)|incomplete|do\s+not\s+claim)\b/i;

const CLAIM_CAP = 64 * 1024; // R11/DP10: over-cap claim text is unscannable -> SILENT (never a block).
const FFFD = '�'; // R5/DP4: U+FFFD in last_assistant_message = the Windows corruption signature.

// BR21: the owner-neutral message for a Superpowers-owned or Ambiguous phase. It contains "fresh
// verification evidence" and no procedure id (no completion-claim-gate, agentic-sdlc: or superpowers:).
const NEUTRAL =
  'Final message claims completion without fresh verification evidence recorded for this phase. ' +
  'Run the verification step that owns this phase and cite its fresh verification evidence (test, ' +
  'security and control output) before claiming done, fixed, passing or ready.';

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { process.exit(0); /* fail open */ }

try {
  if (input?.stop_hook_active) process.exit(0); // R6: a block-induced re-stop -> silent (loop guard)

  const tpath = input?.transcript_path;
  const roll = readRollout(tpath); // ONE read: { finalMessage, gateMarkerPresent, readable }

  // R5: claim text is last_assistant_message unless null/empty/whitespace/U+FFFD-suspect; else rollout final.
  const lam = input?.last_assistant_message;
  const primaryOk = typeof lam === 'string' && lam.trim() !== '' && !lam.includes(FFFD);
  const claimText = primaryOk ? lam : (roll.finalMessage || '');

  if (!claimText || claimText.length > CLAIM_CAP) process.exit(0);     // no claim text / over-cap -> silent
  if (!CLAIM.test(claimText) || NEGATED.test(claimText)) process.exit(0); // no claim, or negated -> silent
  if (!roll.readable) process.exit(0);          // gate unconfirmable (unreadable rollout, DP5) -> silent
  if (roll.gateMarkerPresent) process.exit(0);  // the gate emitted its marker -> nothing to do

  // Owner scoping: an unreadable owner scan keeps the house path.
  const cwd = (typeof input?.cwd === 'string' && input.cwd) ? input.cwd : process.cwd();
  const owner = readOwnerSignals(tpath, cwd);
  const foreignPhase = owner.readable && owner.phase !== 'house';
  if (foreignPhase && owner.verificationDelivered) process.exit(0); // the owning verification ran

  const houseMsg =
    'Final message claims completion but the completion-claim-gate marker is absent this session ' +
    '(contract 00 — evidence before claim). Run agentic-sdlc:completion-claim-gate with the exact ' +
    'evidence (test/security/control output) before claiming done/fixed/passing/ready.';
  const msg = foreignPhase ? NEUTRAL : houseMsg;

  const out = BLOCK
    ? { decision: 'block', reason: msg, systemMessage: '🚧 completion-claim-guard (codex): blocked an unverified completion claim.' }
    : { systemMessage: `⚠️ completion-claim-guard (codex): ${msg}` };
  process.stdout.write(JSON.stringify(out), () => process.exit(0));
} catch {
  process.exit(0); // fail open: never block on an unexpected error
}
