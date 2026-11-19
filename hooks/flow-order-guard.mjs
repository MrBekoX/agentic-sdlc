// PreToolUse (Write/Edit/MultiEdit and Bash/PowerShell) — enforces flow ordering: spec + plan must exist
// before the first production-source edit inside an active flow. This is the cheap,
// pre-edit counterpart to flow-step-guard.mjs (which runs thorough checks on Stop):
// here we only check existence / tool_use evidence, never the full validator. On any
// error, or outside an active flow / on non-source files, it fails open (allows).
// A shell command is an edit of every file the shared write-target recognizer reads from it (FH-1);
// a command that writes no source file stays silent.
import { readStdin } from './secret-patterns.mjs';
import {
  loadRequirements, blockFlag, parseTranscript, activeFlowNames, stepSatisfied, isSourceFile, shellWriteTargets,
  pendingCallIds, withoutCalls, emit,
} from './flow-evidence.mjs';

try {
  const raw = await readStdin();
  let input = {};
  try { input = JSON.parse(raw || '{}'); } catch { /* fail open */ }

  const req = loadRequirements();
  const toolInput = input?.tool_input || {};
  const cwd = (typeof input?.cwd === 'string' && input.cwd) ? input.cwd : process.cwd();
  const targets = typeof toolInput.command === 'string'
    ? shellWriteTargets(toolInput.command, Infinity)          // Bash / PowerShell: the current call is read whole
    : [toolInput.file_path];                                  // Write / Edit / MultiEdit
  if (!targets.some((t) => isSourceFile(t, req, cwd))) process.exit(0); // spec/plan/test/docs/non-source -> allow

  // The current call may already be in the transcript, but it has not run: its own `&& pytest` or its own
  // spec write is not evidence that came BEFORE this edit. Drop it by id, or (no id) by its identical,
  // still-unresolved input - from the one parse (R2-FH-1: the transcript is read and analysed once).
  const toolUseId = (typeof input?.tool_use_id === 'string' && input.tool_use_id) ? input.tool_use_id : null;
  const parsed = parseTranscript(input?.transcript_path);
  const trace = withoutCalls(parsed, toolUseId ? new Set([toolUseId]) : pendingCallIds(parsed, toolInput));
  const flows = activeFlowNames(trace, req);
  if (!flows.length) process.exit(0); // ordering only applies inside an active flow

  const ctx = { cwd: process.cwd(), req, validate: false, sessionScoped: true }; // count only spec/plan written THIS turn, not a pre-existing file

  const missing = [];
  for (const flow of flows) {
    const steps = req.flows?.[flow]?.steps || [];
    for (const step of steps) {
      if (step.beforeSourceEdit !== true) continue;
      if (!stepSatisfied(step, trace, ctx)) missing.push({ flow, id: step.id });
    }
  }

  if (missing.length) {
    if (blockFlag()) {
      emit({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'deny',
          permissionDecisionReason: `${missing[0].flow}: produce spec and plan before editing source (missing: ${missing.map((m) => m.id).join(', ')}). Externalize them as validated artifacts first.`,
        },
        systemMessage: 'flow-order-guard: spec/plan required before source edits.',
      });
    } else {
      emit({ systemMessage: `flow-order-guard: spec/plan not present before a source edit (missing: ${missing.map((m) => m.id).join(', ')}).` });
    }
  } else {
    process.exit(0);
  }
} catch {
  process.exit(0); // fail open / allow
}
