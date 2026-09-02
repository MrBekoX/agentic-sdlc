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
  const ctx = { cwd: process.cwd(), req, validate: true }; // Stop = thorough: re-validate artifacts

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
    && completionClaimPresent(trace, req);

  const block = missing.filter((m) => m.mode === 'block');
  const warn = missing.filter((m) => m.mode === 'warn');

  if (blockFlag() && block.length) {
    emit({
      decision: 'block',
      reason: `${block[0].flow}: required step(s) [${block.map((m) => m.id).join(', ')}] have no evidence this turn. Produce them before finishing - write+validate the spec/plan, run the tests, and invoke implementation-control. Evidence is re-derived, not taken from text.`,
      systemMessage: 'flow-step-guard: blocked - required flow steps lack evidence.',
    });
  } else if (block.length || warn.length || heuristic) {
    const detail = heuristic
      ? 'implementation edits and a completion claim, but no flow skill was invoked - did you skip root-cause-fix?'
      : `missing evidence for step(s): ${missing.map((m) => m.id).join(', ')}`;
    emit({ systemMessage: `flow-step-guard: ${detail}` });
  } else {
    emit({});
  }
} catch {
  process.exit(0); // fail-open / allow on any error
}
