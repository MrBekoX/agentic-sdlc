// Stop — deterministic backstop for the flow-step gate (root-cause-fix and other flows).
// At stop, for each ACTIVE flow (its activeWhen.skill appears in a real Skill tool_use), this
// re-derives evidence for every step that carries a `stop` field. A step counts only when its
// evidence is observable: an artifact that re-validates via validate_artifacts.py, a real
// tool_use, or a real command — never the agent's prose.
//
// With AGENTIC_FLOW_GATE_BLOCK=true, missing `stop:block` steps block the stop so the work is
// finished; otherwise (and for `stop:warn` steps) it reminds. When NO flow ran but the turn shows
// source edits plus a completion claim, a heuristic warns that root-cause-fix may have been
// skipped. Evidence is thorough here (validate=true). Fail-open on any error.
import { readStdin } from './secret-patterns.mjs';
import {
  loadRequirements,
  blockFlag,
  parseTranscript,
  activeFlowNames,
  stepSatisfied,
  isSourceFile,
  completionClaimPresent,
  turnEndsOnSkill,
  turnInvokesSkill,
  turnTextAfterLastResult,
  finalAssistantText,
  emit,
} from './flow-evidence.mjs';

try {
  const raw = await readStdin();
  let input = {};
  try { input = JSON.parse(raw || '{}'); } catch { /* ignore */ }

  // Loop guard: if this stop already results from a prior Stop-hook block, allow.
  if (input?.stop_hook_active) process.exit(0);

  const tpath = input?.transcript_path;
  if (!tpath) process.exit(0);

  const req = loadRequirements();
  const trace = parseTranscript(tpath);
  const lastAssistant = input?.last_assistant_message;
  const ctx = {
    cwd: process.cwd(), req, validate: true,
    backgroundTasks: input?.background_tasks,
  }; // Stop = thorough: re-validate artifacts

  const flows = activeFlowNames(trace, req);

  // A flow's stop-steps are obligations of IMPLEMENTING through that flow. If the flow skill was
  // invoked but no production source file was edited this session (a diagnose/report-only run),
  // nothing was implemented -> nothing to test/secure/audit. Mirror flow-order-guard, which only
  // ever gates real source edits. (completion-claim-guard still catches a bare "fixed" claim.)
  const sourceEdited = trace.edits.some((e) => isSourceFile(e, req));

  const missing = [];
  for (const flow of flows) {
    if (!sourceEdited) continue; // diagnose/report-only run: no implementation, no obligations
    const steps = req.flows?.[flow]?.steps || [];
    for (const step of steps) {
      if (!step.stop) continue;
      if (!stepSatisfied(step, trace, ctx)) {
        missing.push({ flow, id: step.id, label: step.label, mode: step.stop });
      }
    }
  }

  // Heuristic only when no flow was active: source edits + a completion claim but no flow skill.
  const heuristic = flows.length === 0
    && trace.edits.some((e) => isSourceFile(e, req))
    && completionClaimPresent(trace, req, lastAssistant);

  const block = missing.filter((m) => m.mode === 'block');
  const warn = missing.filter((m) => m.mode === 'warn');

  // O4 dispatch-terminal check (pipeline v2.1 C6/C14/C16): the pipeline was activated inside the current
  // turn (a later turn's standalone dispatch decision stays silent), the turn's last top-level tool_use is
  // the dispatch-strategy Skill call, the final text is known (a string last_assistant_message, or a
  // transcript that caught up: a top-level assistant text after that call's result), and it asks the user
  // nothing (no ASCII '?'). Missing-step output wins: this branch is reached only when none is emitted.
  const dispatchTerminal = flows.includes('agentic-sdlc-pipeline')
    && turnInvokesSkill(trace, 'agentic-sdlc-pipeline')
    && turnEndsOnSkill(trace, 'dispatch-strategy')
    && (typeof lastAssistant === 'string' || turnTextAfterLastResult(trace))
    && !finalAssistantText(trace, lastAssistant).includes('?');

  if (blockFlag() && block.length) {
    emit({
      decision: 'block',
      reason: `${block[0].flow}: required step(s) [${block.map((m) => m.id).join(', ')}] have no evidence this turn. Produce them before finishing - for example write and validate the spec/plan, run the tests, and run the required reviewer or audit step. Evidence is re-derived, not taken from text.`,
      systemMessage: 'flow-step-guard: blocked - required flow steps lack evidence.',
    });
  } else if (block.length || warn.length || heuristic) {
    const detail = heuristic
      ? 'implementation edits and a completion claim, but no flow skill was invoked - did you skip root-cause-fix?'
      : `missing evidence for step(s): ${missing.map((m) => m.id).join(', ')}`;
    emit({ systemMessage: `flow-step-guard: ${detail}` });
  } else if (dispatchTerminal) {
    const reason = "agentic-sdlc-pipeline: the turn ended on the dispatch-strategy decision. Continue with the pipeline's next step in the same turn.";
    emit(blockFlag() ? { decision: 'block', reason } : { systemMessage: reason });
  } else {
    emit({});
  }
} catch {
  process.exit(0); // fail-open / allow on any error
}
