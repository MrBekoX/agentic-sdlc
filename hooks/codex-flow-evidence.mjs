// Codex flow-evidence engine (AP2b). Session-scoped, evidence-only port of the Claude flow-step
// backstop: it re-derives whether an artifact-bearing SDLC flow finished THIS rollout with a required
// step lacking observable evidence. It reuses the byte-locked Claude engine's read-only helpers
// (loadRequirements / blockFlag / isSourceFile) and the additive rollout-signal reader, never editing
// either. Pure derivation + a bounded read-only validator subprocess. Fail-open everywhere (BR8).
//
// Divergences from the Claude engine, all deliberate (see the spec):
//   - Active-flow detection is by an IN-SESSION spec/plan WRITE (BR4), never on-disk presence -> a
//     committed prior-session artifact does NOT activate a flow (cross-session false-positive fix).
//   - Only `artifact` and `command` evidence are observable on Codex; `toolUse` steps are dropped (BR11).
//   - A plan is paired with the spec of the SAME work-id with NO fallback to listArtifacts('spec')[0]
//     (BR2); if no same-work-id spec exists on disk, the plan step is reported missing.
import { readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { loadRequirements, blockFlag, isSourceFile } from './flow-evidence.mjs';
import { readRolloutSignals } from './codex-rollout.mjs';

export const HOOK_DIR = dirname(fileURLToPath(import.meta.url));
export { blockFlag };

const ORDER = ['spec', 'plan', 'tests']; // canonical fixed emission order (DP-ORDER, AC25/AC30)

// Local re-implementation of the Claude engine's private runValidator (it is not exported, and the
// byte-locked file must not change). Read-only subprocess: the artifact path is a SEPARATE argv (no
// shell). Returns the exit code, or null when no interpreter can run -> caller fails open (BR2 exception).
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

// Sink-B artifact lookup (spec §6 mandated mechanism): the sanitized work-id is used ONLY as a
// membership key against the trusted readdirSync listing; the path handed to the validator is joined
// from the matched LISTING ENTRY, never from a work-id-constructed string. A crafted/traversing
// work-id reduces to a bare token that matches no entry -> null -> step unsatisfied, no path escape.
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

// The merged Codex-observable stop:block step set across artifact-bearing flows (BR4a): a flow
// qualifies if it has at least one `artifact` evidence step; from each qualifier take stop==="block"
// steps that carry an `artifact` or `command` evidence form, deduplicated by step id. Result is
// {spec(artifact), plan(artifact), tests(command)}; toolUse-only control/dispatch/core/security and
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

function stepMissing(step, workId, signals, req, cwd) {
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
  // command (tests): only the trusted static testCommand is ever compiled (Sink C, ReDoS-safe).
  if (typeof req.testCommand !== 'string') return true;
  let re;
  try { re = new RegExp(req.testCommand, 'i'); } catch { return true; }
  return !signals.commands.some((c) => re.test(c)); // BR3: exit code never inspected
}

export function deriveFlowEvidenceWith(signals, req, cwd) {
  try {
    if (!signals || !signals.readable) return { flow: false, workIds: [], missingBlockSteps: [] };

    // Active-flow detection (BR4): only an in-session WRITE under spec/plan artifactRoots activates.
    const specRoot = req.artifactRoots?.spec;
    const planRoot = req.artifactRoots?.plan;
    const workIds = [];
    for (const t of signals.editTargets) {
      const norm = String(t).replace(/\\/g, '/');
      const isArtifactWrite = (specRoot && norm.includes(specRoot)) || (planRoot && norm.includes(planRoot));
      if (!isArtifactWrite) continue;
      const id = workIdOf(t);
      if (id && !workIds.includes(id)) workIds.push(id);
    }
    if (!workIds.length) return { flow: false, workIds: [], missingBlockSteps: [] };

    // Obligation gate (BR5): no in-session NON-test source edit -> active flow, no step obligation.
    const sourceEdited = signals.editTargets.some((t) => isSourceFile(t, req));
    if (!sourceEdited) return { flow: true, workIds, missingBlockSteps: [] };

    const steps = mergedBlockSteps(req);
    const missing = new Set();
    for (const workId of workIds) {
      for (const step of steps) {
        if (stepMissing(step, workId, signals, req, cwd)) missing.add(step.id);
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
  return deriveFlowEvidenceWith(readRolloutSignals(transcriptPath), loadRequirements(), cwd);
}
