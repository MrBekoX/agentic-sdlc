/* zcode-workflow
description: AGENTIC-SDLC spec/plan drafting on ZCode — an author subagent drafts, a fresh-context critic reviews, up to two revise rounds run, and deterministic validators gate the result.
whenToUse: Use when agentic-sdlc-pipeline runs its spec/plan phases (steps 4-5) on ZCode and the scripted author→critic adapter is preferred over the embedded main-loop adapter. Run inside an agentic-sdlc checkout or the installed plugin root so agents/ and scripts/ resolve.
args:
  workId:
    type: string
    required: true
    description: Work id for the artifacts, e.g. 2026-09-20-zcode-adapter.
  requirement:
    type: string
    required: true
    description: The user requirement (WHAT input) the spec and plan must capture. Ignored content-wise for mode=plan, which reviews an existing spec.
  mode:
    type: string
    required: false
    default: both
    description: 'spec, plan or both (default). plan requires an approved spec already on disk.'
*/

interface CriticVerdict {
  verdict: "approve" | "revise";
  findings: string[];
  validated: string;
}

const workId = String(args.workId ?? "").trim();
const requirement = String(args.requirement ?? "").trim();
const mode = String(args.mode ?? "both").trim().toLowerCase();

if (!/^[a-z0-9][a-z0-9._-]{0,63}$/i.test(workId)) {
  throw new Error(`workId must be a short id of letters, digits, dot, dash or underscore (got "${workId}")`);
}
if (mode !== "spec" && mode !== "plan" && mode !== "both") {
  throw new Error(`mode must be spec, plan or both (got "${mode}")`);
}
if (!requirement && mode !== "plan") {
  throw new Error("requirement is required unless mode=plan");
}

const specPath = `docs/agentic-sdlc/specs/${workId}.md`;
const planPath = `docs/agentic-sdlc/plans/${workId}.md`;

if (mode === "plan") {
  try {
    await files.read(specPath);
  } catch {
    return { ok: false, workId, mode, reason: `mode=plan requires an existing spec at ${specPath}` };
  }
}

const validatorLines: string[] = [];
if (mode !== "plan") {
  validatorLines.push(`python3 scripts/validate_artifacts.py --mode spec --file ${specPath}`);
}
if (mode !== "spec") {
  validatorLines.push(`python3 scripts/validate_artifacts.py --mode plan --file ${planPath} --spec ${specPath}`);
}
const scope = mode === "spec" ? specPath : mode === "plan" ? planPath : `${specPath} and ${planPath}`;

phase("Author drafts the artifacts");
const author = agent(
  "spec-author",
  "You are the AGENTIC-SDLC spec-plan author. First read agents/spec-plan-author.md and follow its depth contract: every acceptance criterion is a Given/When/Then check plus the failure it guards, security notes trace input->sink, every plan task names a RED test point and a runnable verification command. Write real files with your tools; never only describe them.",
);

const authorFocus = mode === "plan"
  ? `Draft the plan at ${planPath} from the approved spec already at ${specPath}.`
  : mode === "spec"
    ? `Draft the spec at ${specPath}. Do not write a plan.`
    : `Draft the spec at ${specPath}, then the plan at ${planPath}.`;

await author.ask<string>([
  authorFocus,
  `Requirement:\n${requirement}`,
  "After writing, run each validator and fix every error before reporting:\n" + validatorLines.join("\n"),
  "Report the artifact paths and the validator exit codes.",
].join("\n\n"));

phase("Fresh-context critic reviews");
const critic = agent(
  "spec-critic",
  'You are the AGENTIC-SDLC spec-plan critic. First read agents/spec-plan-critic.md and follow it. You never see the author\'s reasoning - only the artifacts on disk. Be adversarial: reject unfalsifiable acceptance criteria, tasks without runnable verification, and scope creep. Respond with JSON only, shaped {"verdict": "approve" | "revise", "findings": ["..."], "validated": "what you checked"}.',
);

function criticInstruction(): string {
  const targets = mode === "plan"
    ? `the plan at ${planPath}, strictly against the approved spec at ${specPath}`
    : mode === "spec"
      ? `the spec at ${specPath}`
      : `the spec at ${specPath} and the plan at ${planPath}`;
  return [
    `Read ${targets} from disk and review against the AGENTIC-SDLC depth contract.`,
    mode === "plan" ? "" : `The requirement under specification:\n${requirement}`,
    "Return the JSON verdict.",
  ].filter(Boolean).join("\n\n");
}

let verdict: CriticVerdict = await critic.ask<CriticVerdict>(criticInstruction());
let rounds = 0;
while (verdict.verdict === "revise" && rounds < 2) {
  rounds += 1;
  report({ round: rounds, verdict: "revise", findings: verdict.findings });

  phase("Author revision pass");
  await author.ask<string>([
    `Revise ${scope}, addressing every finding.`,
    `Critic findings:\n- ${verdict.findings.join("\n- ")}`,
    "Re-run the validators and fix every error before reporting.",
  ].join("\n\n"));

  phase("Fresh-context critic reviews");
  verdict = await critic.ask<CriticVerdict>(criticInstruction());
}

phase("Deterministic validation gate");
const specGate = mode === "plan"
  ? null
  : await world.run("python3", ["scripts/validate_artifacts.py", "--mode", "spec", "--file", specPath]);
const planGate = mode === "spec"
  ? null
  : await world.run("python3", ["scripts/validate_artifacts.py", "--mode", "plan", "--file", planPath, "--spec", specPath, "--strict"]);

const ok = verdict.verdict === "approve"
  && (specGate === null || specGate.exitCode === 0)
  && (planGate === null || planGate.exitCode === 0);

log(`spec-plan-draft finished: verdict=${verdict.verdict} rounds=${rounds}`);

return {
  ok,
  workId,
  mode,
  rounds,
  finalVerdict: verdict,
  specGate: specGate === null ? "skipped" : specGate.exitCode === 0 ? "passed" : `failed(exit ${specGate.exitCode})`,
  planGate: planGate === null ? "skipped" : planGate.exitCode === 0 ? "passed" : `failed(exit ${planGate.exitCode})`,
  artifacts: { spec: mode === "plan" ? "pre-existing" : specPath, plan: mode === "spec" ? "skipped" : planPath },
};
