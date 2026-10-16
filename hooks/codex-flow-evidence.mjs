// Codex flow-evidence engine (AP2b). Session-scoped, evidence-only port of the Claude flow-step
// backstop: it re-derives whether an artifact-bearing SDLC flow finished THIS rollout with a required
// step lacking observable evidence. It reuses the Claude engine's read-only helpers
// (loadRequirements / blockFlag / isSourceFile / runValidator) and the additive rollout-signal reader.
// Pure derivation + a bounded read-only validator subprocess. Fail-open everywhere (BR8).
//
// Divergences from the Claude engine, all deliberate (see the spec):
//   - Active-flow detection is by an IN-SESSION spec/plan WRITE (BR4), never on-disk presence -> a
//     committed prior-session artifact does NOT activate a flow (cross-session false-positive fix).
//   - Only `artifact` and `command` evidence are observable on Codex; `toolUse` steps are dropped (BR11).
//   - A plan is paired with the spec of the SAME work-id with NO fallback to listArtifacts('spec')[0]
//     (BR2); if no same-work-id spec exists on disk, the plan step is reported missing.
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { loadRequirements, blockFlag, isSourceFile, isRealRunnerInvocation, resolveBranchState, runValidator } from './flow-evidence.mjs';
import {
  readRolloutSignals, readRolloutRuns, splitBr6Statements, trailingOrRun, isVersionOrHelpOnly, hasUnquotedPipe,
  hasUnquotedBackground, inSafeBr6Grammar, hasUnmodeledShellSyntax, isBr6RunnerStatement, readRollout,
  readOwnerSignals, COMPLETION_CLAIM, COMPLETION_NEGATED,
} from './codex-rollout.mjs';

export const HOOK_DIR = dirname(fileURLToPath(import.meta.url));
export { blockFlag };

// Opt-in strict evidence (AGENTIC_FLOW_STRICT_EVIDENCE), read at call time. Default off: with the flag
// unset the tests step keeps the default shape + exit0 + BR6-attribution path below.
export function strictFlag() {
  return /^(true|1|yes)$/i.test(String(process.env.AGENTIC_FLOW_STRICT_EVIDENCE || ''));
}

// The shared BR6 table's strictAttributable rule (D3), a cross-slice contract: exactly one call event
// and one output record, a numeric exit code, a command inside the D23 safe shell grammar (with the DP39
// operand rule), and a trailing `||` run (a single last statement without `||`) whose EVERY operand runs a
// test runner under the grammar-derived DP39 runner rule (isBr6RunnerStatement), is not version/help-only, not
// piped and not a background job (D21, D23, D27). Accepts a readRolloutRuns record directly.
export function isStrictlyAttributable({ command, callEvents, outputRecords, exitCode }, re) {
  if (callEvents !== 1 || outputRecords !== 1 || typeof exitCode !== 'number') return false;
  if (!inSafeBr6Grammar(command)) return false;
  const run = trailingOrRun(command);
  return run.length > 0
    && run.every((s) => isBr6RunnerStatement(s, re) && !isVersionOrHelpOnly(s, re) && !hasUnquotedPipe(s)
      && !hasUnquotedBackground(s));
}

const ORDER = ['spec', 'plan', 'tests']; // canonical fixed emission order (DP-ORDER, AC25/AC30)

// A2 flow-STEP GREEN test: exit0 is the reliable additive gate. The result-signature
// (outputHasTestSignature) is scanned advisory-only and is NOT required here - codex truncates large
// logs, so a genuine green run's summary line can be missing, and requiring it would false-block those
// runs (DP-A2-SIG: this is why `pytest --version` is accepted rather than caught). A nonzero exit is a
// RED run and never counts (AC4, deliberately reversing AP2b's "exit code never inspected"). No
// correlated exit code -> substrate absent -> FAIL-OPEN (shape already closed the echo forgery).
function runIsGreen(r) {
  if (typeof r.exitCode === 'number') return r.exitCode === 0;
  return true; // substrate absent: fail-open to shape-only-satisfied
}

// Per-package slug safety (BR2/BR11), mirroring hooks/flow-evidence.mjs. The rule is carried in
// flow-requirements.json (perPackageArtifact) and kept in lock-step across the resolver, both JS
// engines, and the offline procedure-eval by test_procedure_eval::test_slug_rule_parity_across_sources.
function isValidSlug(slug, pp) {
  if (!slug || !pp) return false;
  let re;
  try { re = new RegExp(pp.slugPattern); } catch { return false; }
  if (!re.test(slug)) return false;
  return !(pp.reservedSlugs || []).includes(slug);
}

// Classify a per-package artifact path docs/agentic-sdlc/<slug>/<subdir>/<basename>.md -> role
// ('spec'|'plan') for a valid, non-reserved slug; the evidence subdir and any reserved/invalid slug
// return null, so evidence is never a trigger (AC12) and a reserved slug never shadows a flat root.
export function perPackageRole(filePath, req) {
  const pp = req?.perPackageArtifact;
  if (!pp || typeof pp.base !== 'string' || !filePath) return null;
  const norm = String(filePath).replace(/\\/g, '/');
  const marker = `${pp.base}/`;
  let idx = norm.indexOf(marker);
  while (idx !== -1 && !(idx === 0 || norm[idx - 1] === '/')) idx = norm.indexOf(marker, idx + 1);
  if (idx === -1) return null;
  const parts = norm.slice(idx + marker.length).split('/').filter(Boolean);
  if (parts.length !== 3 || !parts[2].endsWith('.md')) return null;
  if (!isValidSlug(parts[0], pp)) return null;
  for (const [role, sub] of Object.entries(pp.subdirs || {})) {
    if (sub === parts[1]) return role;
  }
  return null;
}

// Sink-B artifact lookup (spec §6 mandated mechanism): the sanitized work-id is used ONLY as a
// membership key against the trusted readdirSync listing; the path handed to the validator is joined
// from the matched LISTING ENTRY, never from a work-id-constructed string. A crafted/traversing
// work-id reduces to a bare token that matches no entry -> null -> step unsatisfied, no path escape.
// After the flat root miss, the per-package roots <base>/<slug>/<subdir>/<workId>.md are searched in
// SORTED slug order. When two slug dirs both hold <workId>.md (a malformed/duplicate state) the pick
// is deterministic-but-arbitrary by design: the RESOLVER is the ambiguity authority (it reports
// malformed_package/ambiguous_plan, AC20/AC10); this guard is detection-only and fail-open, so it
// must only be deterministic, not adjudicate ambiguity.
export function findArtifactFile(cwd, role, req, workId) {
  const want = workId + '.md';
  const root = req.artifactRoots?.[role];
  if (root) {
    try {
      const entries = readdirSync(join(cwd, root));
      const match = entries.find((e) => e === want);
      if (match) return join(cwd, root, match);
    } catch { /* flat root absent -> per-package fallback */ }
  }
  const pp = req.perPackageArtifact;
  const subdir = pp?.subdirs?.[role];
  if (pp && typeof pp.base === 'string' && subdir) {
    let slugs;
    try { slugs = readdirSync(join(cwd, pp.base)); } catch { return null; }
    for (const slug of slugs.sort()) {
      if (!isValidSlug(slug, pp)) continue;
      let entries;
      try { entries = readdirSync(join(cwd, pp.base, slug, subdir)); } catch { continue; }
      const match = entries.find((e) => e === want);
      if (match) return join(cwd, pp.base, slug, subdir, match);
    }
  }
  return null;
}

// Reduce a rollout edit-target path to a bare work-id base-name; reject traversal/empty.
export function workIdOf(target) {
  const id = String(target).replace(/\\/g, '/').split('/').pop()
    .replace(/\.md$/i, '')
    .replace(/[^A-Za-z0-9._-]/g, '');
  if (!id || id.includes('..')) return null;
  return id;
}

// The merged Codex-observable stop:block step set across artifact-bearing flows (BR4a): a flow
// qualifies if it has at least one `artifact` evidence step; from each qualifier take stop==="block"
// steps that carry an `artifact` or `command` evidence form, deduplicated by step id. Result is
// {spec(artifact), plan(artifact), tests(command)}; toolUse-only control/dispatch/security and
// the artifact-less safe-refactor flow are excluded (BR11/DP-C/DP-G).
function mergedBlockSteps(req) {
  const byId = new Map();
  for (const flow of Object.values(req.flows || {})) {
    const steps = flow?.steps || [];
    const hasArtifact = steps.some((s) => (s.evidence || []).some((e) => e.kind === 'artifact'));
    if (!hasArtifact) continue;
    for (const step of steps) {
      if (step.stop !== 'block' || byId.has(step.id)) continue;
      const artifactForm = (step.evidence || []).find((e) => e.kind === 'artifact');
      const commandForm = (step.evidence || []).find((e) => e.kind === 'command');
      if (artifactForm) byId.set(step.id, { id: step.id, role: artifactForm.role });
      else if (commandForm) byId.set(step.id, { id: step.id, command: true });
    }
  }
  return [...byId.values()];
}

function stepMissing(step, workId, signals, req, cwd, runs) {
  if (step.role === 'spec') {
    const f = findArtifactFile(cwd, 'spec', req, workId);
    if (!f) return true;
    const s = runValidator('spec', f, null, cwd);
    return !(s === 0 || s === null); // satisfied iff validates or validator unavailable (fail-open)
  }
  if (step.role === 'plan') {
    const specF = findArtifactFile(cwd, 'spec', req, workId); // strict same-work-id pairing, NO fallback
    if (!specF) return true;
    const planF = findArtifactFile(cwd, 'plan', req, workId);
    if (!planF) return true;
    const s = runValidator('plan', planF, specF, cwd);
    return !(s === 0 || s === null);
  }
  // command (tests): A2 SHAPE gate (always-on, command TEXT) + additive exit0 (fail-open on absent
  // substrate). Only the trusted static testCommand is ever compiled (Sink C, ReDoS-safe).
  if (typeof req.testCommand !== 'string') return true;
  let re;
  try { re = new RegExp(req.testCommand, 'i'); } catch { return true; }
  // STRICT (opt-in): only an attributable, single-counted run that exited 0 satisfies tests. Absent or
  // unreadable run records fail CLOSED under the flag, and only under the flag.
  if (strictFlag()) {
    return !(runs && runs.readable && runs.runs.some((r) => r.exitCode === 0 && isStrictlyAttributable(r, re)));
  }
  // SHAPE floor: a run that actually STARTS with a runner (closes `echo pytest` and a forged
  // `echo "...5 passed..."` before any output is read).
  const shaped = (signals.commandRuns || []).filter((r) => isRealRunnerInvocation(r.command, re));
  if (!shaped.length) return true; // no real runner invocation -> tests step missing
  // ADDITIVE exit0: a shaped run GREENs iff it exited 0 (correlated by call_id from the codex
  // `Exit code:` line, or the exec_command_end fallback). When NO shaped run has a correlated exit
  // (older codex / a runtime that omits the carrier), runIsGreen fails open -> shape-only-satisfied.
  // BR6 closure (default-on): the exit code must also be ATTRIBUTABLE to the runner.
  return !shaped.some((r) => runIsGreen(r) && attributable(r, re));
}

// BR6: a correlated exit code belongs to the command's LAST statement (split on unquoted `;`, newline
// and `||`), so `pytest; echo EXIT=$?` no longer lends echo's exit 0 to pytest. In order (DP39):
//   1. no correlated exit code: attributable (fail-open, as at 5801cb9);
//   2. no `;`, newline or `||` in the command: attributable (the 5801cb9 outcome, kept explicitly);
//   3. outside the D23 safe shell grammar: not attributable (checked before the single-statement step,
//      because a hidden separator can collapse the split);
//   4. at most one statement: attributable only when it runs a runner under the grammar-derived DP39 rule
//      and is not version/help-only (so `echo \; pytest` and `pytest --version;` are not);
//   5. otherwise only when every operand of the trailing `||` run runs a runner under that rule and is not
//      version/help-only, and every operand except the last has no pipe or background `&` (a head
//      operand's own exit decides whether the runner after it runs).
function attributable(r, re) {
  if (typeof r.exitCode !== 'number') return true;
  const command = String(r.command || '');
  if (!(command.includes(';') || command.includes('\n') || command.includes('||'))) return true;
  if (hasUnmodeledShellSyntax(command)) return false;
  if (splitBr6Statements(command).length <= 1) {
    return isBr6RunnerStatement(command, re) && !isVersionOrHelpOnly(command, re);
  }
  const run = trailingOrRun(command);
  return run.every((s, i) => isBr6RunnerStatement(s, re) && !isVersionOrHelpOnly(s, re)
    && (i === run.length - 1 || (!hasUnquotedPipe(s) && !hasUnquotedBackground(s))));
}

// Active-flow detection (BR4): only an in-session WRITE under the spec/plan artifactRoots, or a
// per-package <slug>/{spec,plan}/ write (AC15), activates a flow; each write contributes its work id.
function activeWorkIds(signals, req) {
  const specRoot = req.artifactRoots?.spec;
  const planRoot = req.artifactRoots?.plan;
  const workIds = [];
  for (const t of signals.editTargets) {
    const norm = String(t).replace(/\\/g, '/');
    const isArtifactWrite = (specRoot && norm.includes(specRoot)) || (planRoot && norm.includes(planRoot))
      || perPackageRole(t, req) !== null;
    if (!isArtifactWrite) continue;
    const id = workIdOf(t);
    if (id && !workIds.includes(id)) workIds.push(id);
  }
  return workIds;
}

export function deriveFlowEvidenceWith(signals, req, cwd, runs) {
  try {
    if (!signals || !signals.readable) return { flow: false, workIds: [], missingBlockSteps: [] };

    const workIds = activeWorkIds(signals, req);
    if (!workIds.length) return { flow: false, workIds: [], missingBlockSteps: [] };

    // Obligation gate (BR5): no in-session NON-test source edit -> active flow, no step obligation.
    const sourceEdited = signals.editTargets.some((t) => isSourceFile(t, req));
    if (!sourceEdited) return { flow: true, workIds, missingBlockSteps: [] };

    const steps = mergedBlockSteps(req);
    const missing = new Set();
    for (const workId of workIds) {
      for (const step of steps) {
        if (stepMissing(step, workId, signals, req, cwd, runs)) missing.add(step.id);
      }
    }
    // Union across work-ids, deduped by id, emitted in canonical fixed order (BR4a/BR4b/AC25/AC30).
    const ordered = steps.map((s) => s.id).filter((id) => missing.has(id));
    const tail = [...missing].filter((id) => !ordered.includes(id));
    const missingBlockSteps = [...ORDER.filter((id) => ordered.includes(id)),
      ...ordered.filter((id) => !ORDER.includes(id)), ...tail];
    return { flow: true, workIds, missingBlockSteps };
  } catch {
    return { flow: false, workIds: [], missingBlockSteps: [] }; // BR8 fail-open
  }
}

export function deriveFlowEvidence(transcriptPath, cwd) {
  const runs = strictFlag() ? readRolloutRuns(transcriptPath) : undefined; // second read only under strict
  return deriveFlowEvidenceWith(readRolloutSignals(transcriptPath), loadRequirements(), cwd, runs);
}

// ---------------------------------------------------------------------------
// Offline strict evaluation for scripts/strict_flow_evidence.py (publication-readiness 0.4.3; AC43,
// AC44, AC119, AC120). The live hooks never call it. Returns {error:true} when a rollout scan is
// unreadable, otherwise {evidence, completion, branch}:
//   evidence   'missing' without an active flow, or with a source edit but no real runner invocation;
//              'green' when every work id's spec and same-work-id plan validate strictly (an unavailable
//              validator does not count) and, when a source edit exists, a strictly attributable RED run
//              precedes a strictly attributable GREEN run; otherwise 'partial'.
//   completion 'n/a' without an active flow or an un-negated completion claim in the final message;
//              House needs the gate marker, Superpowers the marker or a verification delivery, and an
//              Ambiguous phase is always 'unsatisfied'.
//   branch     'ok' without a source edit, else resolveBranchState(cwd); report-only, never the verdict.
function validatesStrictly(role, workId, req, cwd) {
  const specFile = findArtifactFile(cwd, 'spec', req, workId);
  if (!specFile) return false;
  if (role === 'spec') return runValidator('spec', specFile, null, cwd) === 0;
  const planFile = findArtifactFile(cwd, 'plan', req, workId);
  return Boolean(planFile) && runValidator('plan', planFile, specFile, cwd) === 0;
}

export function deriveStrictEvidence(rolloutPath, cwd) {
  const signals = readRolloutSignals(rolloutPath);
  const runs = readRolloutRuns(rolloutPath);
  const roll = readRollout(rolloutPath);
  const owner = readOwnerSignals(rolloutPath, cwd);
  if (!signals.readable || !runs.readable || !roll.readable || !owner.readable) return { error: true };
  const req = loadRequirements();
  let re = null;
  try { if (typeof req.testCommand === 'string') re = new RegExp(req.testCommand, 'i'); } catch { re = null; }

  const workIds = activeWorkIds(signals, req);
  const sourceEdited = signals.editTargets.some((t) => isSourceFile(t, req));

  let evidence;
  if (!workIds.length || (sourceEdited && !(re && signals.commands.some((c) => isRealRunnerInvocation(c, re))))) {
    evidence = 'missing';
  } else {
    const validated = workIds.every((id) => validatesStrictly('spec', id, req, cwd) && validatesStrictly('plan', id, req, cwd));
    let redBeforeGreen = true;
    if (sourceEdited) {
      const attributable = runs.runs.filter((r) => isStrictlyAttributable(r, re)); // ordered by first call event
      const reds = attributable.filter((r) => r.exitCode !== 0);
      redBeforeGreen = reds.length > 0 && attributable.some((r) => r.exitCode === 0 && r.seq > reds[0].seq);
    }
    evidence = validated && redBeforeGreen ? 'green' : 'partial';
  }

  let completion = 'n/a';
  if (workIds.length && COMPLETION_CLAIM.test(roll.finalMessage) && !COMPLETION_NEGATED.test(roll.finalMessage)) {
    if (owner.phase === 'house') completion = roll.gateMarkerPresent ? 'satisfied' : 'unsatisfied';
    else if (owner.phase === 'superpowers') completion = roll.gateMarkerPresent || owner.verificationDelivered ? 'satisfied' : 'unsatisfied';
    else completion = 'unsatisfied';
  }

  const branch = sourceEdited ? resolveBranchState(cwd) : 'ok';
  return { evidence, completion, branch };
}
