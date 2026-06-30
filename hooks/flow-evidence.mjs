// Shared evidence engine for the flow-step enforcement hooks (flow-step-guard, flow-order-guard).
//
// Principle: evidence is RE-DERIVED from observable facts, never trusted from the agent's prose.
//   - artifact : the file exists AND validate_artifacts.py re-validates it (Stop, thorough) or
//                merely exists (PreToolUse, cheap). If the validator cannot run, fail-open.
//   - toolUse  : a real tool_use event of the named tool whose input contains the marker.
//   - command  : a real Bash command in the transcript matching the named regex.
// Every reader fails OPEN (treats as allowed / satisfied) on its own error, matching the other guards.
import { readFileSync, readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

export const HOOK_DIR = dirname(fileURLToPath(import.meta.url));

export function loadRequirements() {
  try {
    return JSON.parse(readFileSync(join(HOOK_DIR, 'flow-requirements.json'), 'utf8'));
  } catch {
    return { version: 0, flows: {} };
  }
}

export function blockFlag() {
  return /^(true|1|yes)$/i.test(String(process.env.AGENTIC_FLOW_GATE_BLOCK || ''));
}

// Parse a transcript JSONL into a trace of observable facts. Fail-open to an empty trace.
export function parseTranscript(transcriptPath) {
  const empty = { tools: [], commands: [], edits: [], lastText: '', raw: '' };
  if (!transcriptPath) return empty;
  let raw = '';
  try { raw = readFileSync(transcriptPath, 'utf8'); } catch { return empty; }
  const tools = [];
  const commands = [];
  const edits = [];
  let lastText = '';
  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    let e;
    try { e = JSON.parse(line); } catch { continue; }
    if (e?.type !== 'assistant') continue;
    const content = e?.message?.content;
    if (typeof content === 'string') { if (content) lastText = content; continue; }
    if (!Array.isArray(content)) continue;
    for (const c of content) {
      if (c?.type === 'text' && c.text) lastText = c.text;
      else if (c?.type === 'tool_use') {
        const inputStr = JSON.stringify(c.input || {});
        tools.push({ name: c.name || '', inputStr });
        if (c.name === 'Bash' && c.input?.command) commands.push(String(c.input.command));
        if (['Edit', 'Write', 'MultiEdit'].includes(c.name) && c.input?.file_path) {
          edits.push(String(c.input.file_path));
        }
      }
    }
  }
  return { tools, commands, edits, lastText, raw };
}

function toolUsePresent(trace, tool, contains) {
  return trace.tools.some((t) => t.name === tool && t.inputStr.includes(contains));
}

// Flows whose activeWhen.skill marker appears in a real Skill tool_use.
export function activeFlowNames(trace, req) {
  const out = [];
  for (const [name, flow] of Object.entries(req.flows || {})) {
    const marker = flow?.activeWhen?.skill;
    if (marker && toolUsePresent(trace, 'Skill', marker)) out.push(name);
  }
  return out;
}

// Per-package slug safety (BR2/BR11), shared by every per-package recognizer below. The rule is
// carried in flow-requirements.json (perPackageArtifact) and kept in lock-step with the resolver
// and the offline procedure-eval by tests/test_procedure_eval.py::test_slug_rule_parity_across_sources.
function isValidSlug(slug, pp) {
  if (!slug || !pp) return false;
  let re;
  try { re = new RegExp(pp.slugPattern); } catch { return false; }
  if (!re.test(slug)) return false;
  return !(pp.reservedSlugs || []).includes(slug);
}

// Classify a path as a per-package artifact: docs/agentic-sdlc/<slug>/<subdir>/<basename>.md.
// Returns the role ('spec'|'plan') for a valid, non-reserved slug whose subdir maps to a role;
// the evidence subdir (and any reserved/invalid slug) returns null, so evidence is NEVER a
// trigger or satisfier (AC12) and a reserved slug never shadows the flat roots (AC14/BR11).
function perPackageRole(filePath, req) {
  const pp = req?.perPackageArtifact;
  if (!pp || typeof pp.base !== 'string' || !filePath) return null;
  const norm = String(filePath).replace(/\\/g, '/');
  const marker = `${pp.base}/`;
  let idx = norm.indexOf(marker);
  while (idx !== -1 && !(idx === 0 || norm[idx - 1] === '/')) idx = norm.indexOf(marker, idx + 1);
  if (idx === -1) return null;
  const parts = norm.slice(idx + marker.length).split('/').filter(Boolean);
  if (parts.length !== 3 || !parts[2].endsWith('.md')) return null; // <slug>/<subdir>/<basename>.md
  if (!isValidSlug(parts[0], pp)) return null;
  for (const [role, sub] of Object.entries(pp.subdirs || {})) {
    if (sub === parts[1]) return role;
  }
  return null;
}

// Enumerate artifacts for a role. Flat <root>/*.md FIRST (flat readdir order preserved as a
// prefix so the Stop-path flat spec[0] pairing is unchanged), then per-package
// <base>/<slug>/<subdir>/*.md for every valid, non-reserved slug in sorted order (deterministic).
function listArtifacts(cwd, role, req) {
  const out = [];
  const root = req.artifactRoots?.[role];
  if (root) {
    try {
      for (const f of readdirSync(join(cwd, root))) {
        if (f.endsWith('.md')) out.push(join(cwd, root, f));
      }
    } catch { /* flat root absent -> per-package only */ }
  }
  const pp = req.perPackageArtifact;
  const subdir = pp?.subdirs?.[role];
  if (pp && typeof pp.base === 'string' && subdir) {
    let slugs;
    try { slugs = readdirSync(join(cwd, pp.base)); } catch { slugs = []; }
    for (const slug of slugs.sort()) {
      if (!isValidSlug(slug, pp)) continue;
      let files;
      try { files = readdirSync(join(cwd, pp.base, slug, subdir)); } catch { continue; }
      for (const f of files.sort()) {
        if (f.endsWith('.md')) out.push(join(cwd, pp.base, slug, subdir, f));
      }
    }
  }
  return out;
}

function runValidator(mode, file, specFile, cwd) {
  const candidates = process.platform === 'win32'
    ? [['py', '-3'], ['python'], ['python3']]
    : [['python3'], ['python']];
  const script = join(HOOK_DIR, '..', 'scripts', 'validate_artifacts.py');
  const tail = ['--mode', mode, '--file', file, '--strict'];
  if (mode === 'plan' && specFile) tail.push('--spec', specFile);
  for (const c of candidates) {
    const r = spawnSync(c[0], [...c.slice(1), script, ...tail], { encoding: 'utf8', cwd, timeout: 10000 });
    if (r.error) continue;          // interpreter not found — try next
    if (r.status === null) continue; // spawn failed
    return r.status;                 // 0 = pass, non-zero = fail (e.g. a stub)
  }
  return null; // could not run any interpreter -> caller fails open
}

// Stop-path plan->spec pairing (BR10). A per-package plan pairs ONLY with its co-located
// <base>/<slug>/spec/<basename>.md, and ONLY if that file is present in the enumerated spec
// listing -- membership-key discipline: the returned path is the matching LISTING ENTRY, never a
// reconstructed string. If the co-located spec is absent the plan stays unpaired (null) so it is
// correctly unsatisfied rather than falsely paired with a foreign flat spec (which would pass/fail
// on the wrong spec's AC coverage, since validate_artifacts has no plan<->spec work_id check). A
// flat plan keeps today's behavior: the FIRST flat spec (flat entries are the listing prefix).
function specForPlan(planFile, specs, req) {
  if (!specs || !specs.length) return null;
  if (perPackageRole(planFile, req) === 'plan') {
    const planNorm = String(planFile).replace(/\\/g, '/');
    const want = planNorm.replace(/\/plan\/([^/]+)$/, '/spec/$1');
    if (want === planNorm) return null;
    return specs.find((s) => String(s).replace(/\\/g, '/') === want) || null;
  }
  return specs.find((s) => perPackageRole(s, req) === null) || null; // first FLAT spec, or none
}

function artifactSatisfied(item, trace, ctx) {
  // Ordering (PreToolUse): count only a spec/plan WRITTEN this turn, not a pre-existing file --
  // otherwise any old artifact already in the repo would satisfy the gate and ordering would be a
  // no-op. Stop keeps the thorough existence+re-validate path below.
  if (ctx.sessionScoped) {
    const root = ctx.req.artifactRoots?.[item.role];
    return (trace.edits || []).some((e) => {
      const norm = String(e).replace(/\\/g, '/');
      if (root && norm.includes(root)) return true;            // flat root written this turn
      return perPackageRole(e, ctx.req) === item.role;          // or a per-package <slug>/<role>/ edit
    });
  }
  const files = listArtifacts(ctx.cwd, item.role, ctx.req);
  if (!files.length) return false;
  if (!ctx.validate || !item.validate) return true; // cheap path: existence is enough
  const specs = item.validate.mode === 'plan' ? listArtifacts(ctx.cwd, 'spec', ctx.req) : null;
  for (const f of files) {
    const specFile = item.validate.mode === 'plan' ? specForPlan(f, specs, ctx.req) : null;
    const status = runValidator(item.validate.mode, f, specFile, ctx.cwd);
    if (status === null) return true; // validator unavailable -> fail-open on existence
    if (status === 0) return true;    // a present, valid artifact
  }
  return false; // files exist but none re-validate (a stub is NOT accepted)
}

function evidenceSatisfied(item, trace, ctx) {
  switch (item.kind) {
    case 'artifact':
      return artifactSatisfied(item, trace, ctx);
    case 'toolUse':
      return toolUsePresent(trace, item.tool, item.contains);
    case 'command': {
      const pat = ctx.req[item.matches] || item.matches;
      let re;
      try { re = new RegExp(pat, 'i'); } catch { return false; }
      return trace.commands.some((c) => re.test(c));
    }
    default:
      return false;
  }
}

// A step is satisfied if ANY of its evidence forms is satisfied (re-derived).
export function stepSatisfied(step, trace, ctx) {
  return (step.evidence || []).some((item) => evidenceSatisfied(item, trace, ctx));
}

// A path is a production source file: extension in sourceGlobs, NOT an artifact root, NOT a test.
export function isSourceFile(filePath, req) {
  if (!filePath) return false;
  const norm = String(filePath).replace(/\\/g, '/');
  for (const root of Object.values(req.artifactRoots || {})) {
    if (norm.includes(root)) return false;
  }
  if (/(^|\/)tests?\//.test(norm) || /(^|\/)test_|_test\.|\.test\.|\.spec\./.test(norm)) return false;
  const ext = (norm.split('.').pop() || '').toLowerCase();
  return (req.sourceGlobs || []).includes(ext);
}

export function completionClaimPresent(trace, req) {
  if (!req.completionClaim || !trace.lastText) return false;
  try { return new RegExp(req.completionClaim, 'i').test(trace.lastText); } catch { return false; }
}

// Flush stdout, then exit — avoids truncation on a piped stdout under Windows (same as the other guards).
export function emit(out) {
  if (out && Object.keys(out).length) {
    process.stdout.write(JSON.stringify(out), () => process.exit(0));
  } else {
    process.exit(0);
  }
}
