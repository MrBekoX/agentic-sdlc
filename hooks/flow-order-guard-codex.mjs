// PreToolUse (Codex: Bash + apply_patch) - env-gated pre-edit ORDERING gate (AP2c). The pre-edit
// counterpart to the AP2b flow-step Stop backstop: it DENIES a production-source edit attempted
// before THIS session has produced a validated spec AND a matching plan (same work id, BOTH written
// this session via a recognized apply_patch artifact write, each re-validating strict). Default
// SILENT - inert unless AGENTIC_FLOW_ORDER_BLOCK is truthy (BR1; its own switch, A2/DP-ENV), because Codex emits no
// active-flow signal and a default-on gate would false-positive on every ordinary source edit.
//
// Why this does NOT reuse codex-flow-evidence.mjs deriveFlowEvidence (DP-EVID/BR3): that engine
// derives one work-id set from ANY in-session artifact write and then validates each role from
// ON-DISK presence, so it would wrongly ACCEPT a partner that exists only as a committed prior-
// session file. The "both halves in-session" rule requires deriving the spec-write set and the
// plan-write set SEPARATELY (each from this rollout's editTargets) and treating ordering as
// satisfied only when a single work id W appears in BOTH in-session sets and both files re-validate.
// So the mixed-origin pair (in-session spec write + committed-only plan) DENIES naming the half not
// written this session (AC17).
//
// Fail-open (allow, emit nothing) ONLY on positively-detected unconfirmable states (BR4): an
// unreadable/missing/oversized rollout, malformed stdin, an absent/non-string command, an
// unrecognized edit form, no source-file target, corrupt requirements, or an internal error.
// "No in-session validated spec+plan pair found" is the DENY trigger, NOT a fail-open state (BR4) -
// and an unresolvable artifact root (wrong/absent cwd) likewise DENIES (BR4b).
//
// runValidator/findArtifactFile/workIdOf are re-implemented locally (about 30 lines) because the
// byte-locked codex-flow-evidence.mjs does not export them - exactly how codex-flow-evidence.mjs
// itself re-implemented the byte-locked flow-evidence.mjs private runValidator. Everything else is
// imported read-only.
import { readdirSync, realpathSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';
import { readStdin } from './secret-patterns.mjs';
import { extractWrittenContent } from './codex-write-signal.mjs';
import { readRolloutSignals } from './codex-rollout.mjs';
import { loadRequirements, isSourceFile, isRealRunnerInvocation } from './flow-evidence.mjs';

const HOOK_DIR = dirname(fileURLToPath(import.meta.url));

// A2/DP-ENV decouple: flow-order has its OWN opt-in switch, independent of the flow-step Stop guard's
// AGENTIC_FLOW_GATE_BLOCK. Setting AGENTIC_FLOW_GATE_BLOCK alone (to harden flow-step warn->block) no
// longer silently turns this pre-edit gate on; an operator opts into ordering enforcement explicitly.
const ORDER_BLOCK = /^(true|1|yes)$/i.test(String(process.env.AGENTIC_FLOW_ORDER_BLOCK || ''));

// Local re-implementation of the byte-locked engines' private runValidator. Read-only subprocess:
// the artifact path is a SEPARATE argv (no shell). Returns the exit code, or null when no
// interpreter can run -> caller fails open (BR3a/AC19).
function runValidator(mode, file, specFile, cwd) {
  const candidates = process.platform === 'win32'
    ? [['py', '-3'], ['python'], ['python3']]
    : [['python3'], ['python']];
  const script = join(HOOK_DIR, '..', 'scripts', 'validate_artifacts.py');
  const tail = ['--mode', mode, '--file', file, '--strict'];
  if (mode === 'plan' && specFile) tail.push('--spec', specFile);
  for (const c of candidates) {
    const r = spawnSync(c[0], [...c.slice(1), script, ...tail], { encoding: 'utf8', cwd, timeout: 10000 });
    if (r.error) continue;           // interpreter not found -> try next
    if (r.status === null) continue; // spawn failed
    return r.status;                 // 0 = pass, non-zero = fail (e.g. a stub)
  }
  return null; // could not run any interpreter -> caller fails open
}

// Sink-B artifact lookup (spec §6): the sanitized work-id is ONLY a membership key against the
// trusted readdirSync listing; the path handed to the validator is joined from the matched LISTING
// ENTRY, never from a work-id-constructed string. A crafted/traversing work-id reduces to a bare
// token that matches no entry -> null -> step unsatisfied, no path escape.
function findArtifactFile(cwd, role, req, workId) {
  const root = req.artifactRoots?.[role];
  if (!root) return null;
  let entries;
  try { entries = readdirSync(join(cwd, root)); } catch { return null; }
  const want = workId + '.md';
  const match = entries.find((e) => e === want);
  return match ? join(cwd, root, match) : null;
}

// Reduce a rollout edit-target path to a bare work-id base-name; reject traversal/empty.
function workIdOf(target) {
  const id = String(target).replace(/\\/g, '/').split('/').pop()
    .replace(/\.md$/i, '')
    .replace(/[^A-Za-z0-9._-]/g, '');
  if (!id || id.includes('..')) return null;
  return id;
}

// A same-work-id spec exists on disk AND re-validates strict (or no interpreter -> fail-open).
function specValidates(workId, req, cwd) {
  const specF = findArtifactFile(cwd, 'spec', req, workId);
  if (!specF) return false;
  const s = runValidator('spec', specF, null, cwd);
  return s === 0 || s === null;
}

// A same-work-id plan exists on disk AND re-validates strict against its SAME-work-id spec
// (strict pairing, NO fallback) - or no interpreter -> fail-open.
function planPairValidates(workId, req, cwd) {
  const specF = findArtifactFile(cwd, 'spec', req, workId);
  if (!specF) return false;
  const planF = findArtifactFile(cwd, 'plan', req, workId);
  if (!planF) return false;
  const s = runValidator('plan', planF, specF, cwd);
  return s === 0 || s === null;
}

// PURE ordering decision. Returns one of:
//   { unconfirmable: true }            -> fail-open (allow): unreadable rollout or corrupt req (BR4)
//   { satisfied: true }                -> allow: a shared-W in-session validated spec+plan pair
//   { satisfied: false, missing: [..] } -> DENY: the missing of {spec, plan} (BR4/BR4b deny trigger)
export function orderDecision(signals, req, cwd) {
  if (!signals || !signals.readable) return { unconfirmable: true };
  const specRoot = req.artifactRoots?.spec;
  const planRoot = req.artifactRoots?.plan;
  if (!specRoot || !planRoot) return { unconfirmable: true }; // corrupt/empty requirements (BR4)

  // In-session SPEC writes and PLAN writes, derived SEPARATELY from this rollout's edit targets.
  const specIds = [];
  const planIds = [];
  for (const t of signals.editTargets) {
    const norm = String(t).replace(/\\/g, '/');
    if (norm.includes(specRoot)) {
      const id = workIdOf(t);
      if (id && !specIds.includes(id)) specIds.push(id);
    }
    if (norm.includes(planRoot)) {
      const id = workIdOf(t);
      if (id && !planIds.includes(id)) planIds.push(id);
    }
  }

  // DP-SCOPE-FLOW (B2): safe-refactor's before-source-edit obligation is a characterization-test run,
  // NOT a spec/plan pair (and TDD flows write a failing test before the edit). flow-order cannot detect
  // the active flow on Codex (DP1), so it accepts EITHER before-source-edit evidence: a validated
  // spec+plan pair OR a recorded test run this session. So a safe-refactor (or a test-first edit) that
  // ran tests before editing source is no longer falsely denied. Bad/absent testCommand -> skip (no throw).
  //
  // A2/HB6: the acceptance is the always-on SHAPE gate (isRealRunnerInvocation), so `echo pytest` no
  // longer forges before-edit evidence. It stays EXIT-AGNOSTIC on purpose: a TDD RED run (a failing
  // test written first) MUST still count as ordering evidence, so exit0 is NOT required here (only the
  // flow-STEP Stop gate requires exit0).
  let testRe = null;
  try { if (req.testCommand) testRe = new RegExp(req.testCommand); } catch { testRe = null; }
  if (testRe && signals.commands.some((c) => isRealRunnerInvocation(c, testRe))) return { satisfied: true };

  // SATISFIED iff a single work id W has BOTH an in-session spec write AND an in-session plan write,
  // and both re-validate strict (the plan paired with the SAME-W spec, no fallback).
  for (const W of specIds) {
    if (planIds.includes(W) && specValidates(W, req, cwd) && planPairValidates(W, req, cwd)) {
      return { satisfied: true };
    }
  }

  // Name the missing role(s) for the deny reason. A role is "have" only if an in-session write of it
  // re-validates; the on-disk-only partner never counts (that is exactly the AC17 mixed-origin deny).
  const haveSpec = specIds.some((W) => specValidates(W, req, cwd));
  const havePlan = planIds.some((W) => planPairValidates(W, req, cwd));
  const missing = [];
  if (!haveSpec) missing.push('spec'); // FIXED order: spec before plan
  if (!havePlan) missing.push('plan');
  if (!missing.length) missing.push('spec', 'plan'); // independently-ok but no shared-W corner
  return { satisfied: false, missing };
}

// Deny payload: the same live-verified Codex shape scan-write-codex.mjs uses (confirmed to block on
// codex-cli 0.142.0). The reason is a FIXED preamble + a SINGLE bracketed `Missing this session`
// clause that is the ONLY place the dynamic roles appear (drawn solely from {spec, plan}); it
// carries no rollout/command/path/work-id byte (BR6/AC12).
function denyPayload(missing) {
  const reason =
    'Flow ordering enforcement (AGENTIC_FLOW_ORDER_BLOCK): editing source requires a validated '
    + 'spec and matching plan authored this session for this work item. '
    + `Missing this session: [${missing.join(', ')}]. `
    + 'Author the listed artifact(s) as validated artifacts before editing source.';
  return {
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: reason,
    },
    systemMessage: 'flow-order-guard (codex): a validated spec+plan pair is required before source edits.',
  };
}

// True only when this module is the process entry point (`node hooks/flow-order-guard-codex.mjs`),
// so a test that `await import`s the module to drive the pure orderDecision does NOT fire main()
// (and its top-level stdin read). Any throw (e.g. argv[1] absent) -> false.
function isEntrypoint() {
  try {
    return import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href;
  } catch {
    return false;
  }
}

async function main() {
  const raw = await readStdin();
  let input = {};
  try { input = JSON.parse(raw || '{}'); } catch { process.exit(0); } // AC8 malformed -> fail open
  if (!ORDER_BLOCK) process.exit(0); // BR1/AC2: opt-in only (dedicated AGENTIC_FLOW_ORDER_BLOCK, A2)
  try {
    const command = input?.tool_input?.command;
    if (typeof command !== 'string' || !command) process.exit(0); // AC8 absent/non-string command
    const { targets } = extractWrittenContent(String(input?.tool_name || ''), command);
    const req = loadRequirements();
    if (!targets.some((t) => isSourceFile(t, req))) process.exit(0); // BR2/AC6/AC9 no source target
    const cwd = (typeof input?.cwd === 'string' && input.cwd) ? input.cwd : process.cwd(); // DP-CWD
    const signals = readRolloutSignals(input?.transcript_path);
    const d = orderDecision(signals, req, cwd);
    if (d.unconfirmable || d.satisfied) process.exit(0);
    process.stdout.write(JSON.stringify(denyPayload(d.missing)), () => process.exit(0));
  } catch {
    /* BR4 internal-error fail-open */
  } finally {
    process.exit(0);
  }
}

if (isEntrypoint()) {
  await main();
}
