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

function listArtifacts(cwd, role, req) {
  const root = req.artifactRoots?.[role];
  if (!root) return [];
  try {
    return readdirSync(join(cwd, root))
      .filter((f) => f.endsWith('.md'))
      .map((f) => join(cwd, root, f));
  } catch {
    return [];
  }
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

function artifactSatisfied(item, trace, ctx) {
  // Ordering (PreToolUse): count only a spec/plan WRITTEN this turn, not a pre-existing file --
  // otherwise any old artifact already in the repo would satisfy the gate and ordering would be a
  // no-op. Stop keeps the thorough existence+re-validate path below.
  if (ctx.sessionScoped) {
    const root = ctx.req.artifactRoots?.[item.role];
    if (!root) return false;
    return (trace.edits || []).some((e) => String(e).replace(/\\/g, '/').includes(root));
  }
  const files = listArtifacts(ctx.cwd, item.role, ctx.req);
  if (!files.length) return false;
  if (!ctx.validate || !item.validate) return true; // cheap path: existence is enough
  for (const f of files) {
    const specFile = item.validate.mode === 'plan' ? (listArtifacts(ctx.cwd, 'spec', ctx.req)[0] || null) : null;
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
