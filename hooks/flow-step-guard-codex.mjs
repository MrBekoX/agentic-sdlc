// Stop (Codex) - evidence-only backstop for the flow-step gate (AP2b). The Claude flow-step-guard
// detects an active flow from a `Skill` tool_use and parses Claude-JSONL `type:"assistant"` events,
// neither of which appears in the Codex rollout (Phase-0d / AP2a). This adapter instead re-derives
// evidence from signals Codex actually emits - in-session spec/plan writes, recorded commands, and
// patch-style edit targets - scoped to the current rollout (codex-flow-evidence.mjs).
//
// With AGENTIC_FLOW_GATE_BLOCK truthy, a missing stop:block step blocks; otherwise it warns. All other
// states are silent (exit 0). Fail-open on any error (BR8). The operator message is assembled ONLY
// from a code-authored static label plus step ids - never a rollout byte, command string, artifact
// filename, or work-id (BR9). The Codex Stop payload is ASSUMED to carry `cwd` (un-probed, VERIFY);
// the guard falls back to process.cwd(), in which case artifactRoots resolve nowhere and it no-ops
// (fail-safe: never a false block).
import { readStdin } from './secret-patterns.mjs';
import { deriveFlowEvidence } from './codex-flow-evidence.mjs';
import { blockFlag } from './flow-evidence.mjs';

const FLOW_LABEL = 'an artifact-bearing SDLC flow (spec/plan/tests)';

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { process.exit(0); /* fail open */ }

try {
  if (input?.stop_hook_active) process.exit(0); // BR7: a block-induced re-stop -> silent (loop guard)

  const tpath = input?.transcript_path;
  if (!tpath) process.exit(0); // AC9: no transcript -> unconfirmable -> silent

  const cwd = (typeof input?.cwd === 'string' && input.cwd) ? input.cwd : process.cwd();
  const ev = deriveFlowEvidence(tpath, cwd);

  if (!ev.flow) process.exit(0);                  // AC6/AC12/AC23: no active in-session flow -> silent
  if (!ev.missingBlockSteps.length) process.exit(0); // AC7/AC14: nothing missing -> silent

  const ids = ev.missingBlockSteps;
  const reason = `${FLOW_LABEL} finished this session with required step(s) `
    + `[${ids.join(', ')}] lacking observable evidence (re-derived from validated `
    + `artifacts and recorded commands, not prose). Produce them for the same work id `
    + `- write+validate the spec/plan and run the tests - before finishing.`;

  const out = blockFlag()
    ? { decision: 'block', reason, systemMessage: '🚧 flow-step-guard (codex): blocked - required flow steps lack evidence.' }
    : { systemMessage: `⚠️ flow-step-guard (codex): ${reason}` };
  process.stdout.write(JSON.stringify(out), () => process.exit(0));
} catch {
  process.exit(0); // fail open: never block on an unexpected error
}
