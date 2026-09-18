// Shared evidence engine for the flow-step enforcement hooks (flow-step-guard, flow-order-guard).
//
// Principle: evidence is RE-DERIVED from observable facts, never trusted from the agent's prose.
//   - artifact : the file exists AND validate_artifacts.py re-validates it (Stop, thorough) or
//                merely exists (PreToolUse, cheap). If the validator cannot run, fail-open.
//   - toolUse  : a real tool_use event of the named tool whose input contains the marker.
//   - command  : a real Bash command in the transcript matching the named regex.
//   - branch   : the Stop-time working-directory branch is not main/master (warn-level step).
//   - reviewResult : a dispatched reviewer returned a correlated non-error tool_result (warn-level).
// Every reader fails OPEN (treats as allowed / satisfied) on its own error, matching the other guards.
import { accessSync, constants as fsConstants, readFileSync, readdirSync, statSync } from 'node:fs';
import { execFileSync, spawnSync } from 'node:child_process';
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

// A2 SHAPE gate (cross-runtime, command-TEXT only): does a command actually INVOKE a test runner,
// as opposed to merely mentioning one? A `{kind:command, matches:testCommand}` step used to be
// satisfied by any command whose text matched the runner regex, so `echo pytest` (and even
// `echo "...5 passed..."`) forged the evidence. Here we require a real invocation: split on shell
// separators, strip a leading env-assignment prefix, and require SOME segment to actually START with
// an allowlisted runner (or be `python[3] -m <runner>`), and to NOT be a no-op printer
// (echo/printf/:/true/cat/head/tail/cd) or a `#` comment. Pure string/regex; every pattern is LINEAR
// (disjoint classes, no nested quantifier) so an adversarial command cannot ReDoS the guard.
const NOOP_FIRST = /^(?:echo|printf|:|true|cat|head|tail|cd)$/;
// python | python3 | python3.11 | py, an optional launcher version flag (`-3`, `-3.11`), then `-m <mod>`.
const PYTHON_DASH_M = /^(?:python[0-9.]*|py)(?:\s+-[0-9.]+)?\s+-m\s+(\S+)/;
// Strip ONE leading `VAR=value` env-assignment (value quoted, or bare WITHOUT shell metacharacters so
// a command-substitution value like `$(echo pytest)` is NOT swallowed). LINEAR (disjoint classes).
const ENV_ASSIGN = /^[A-Za-z_][A-Za-z0-9_]*=(?:"[^"]*"|'[^']*'|[^\s"'$`(){}|&;<>]*)\s+/;
// A segment that (still) STARTS with an assignment is a standalone `NAME=value`, not a command — so a
// bare `pytest=1` must not qualify just because the runner regex matches at the `=` word boundary.
const ASSIGN_START = /^[A-Za-z_][A-Za-z0-9_]*=/;

// Quote-aware split on shell statement/pipe boundaries (&&, ||, ;, |, newline). A separator INSIDE
// single/double quotes is DATA (`echo ';pytest'`), never a boundary, so it cannot spawn a fragment
// that spuriously "starts with a runner". Single linear pass.
function splitSegments(str) {
  const out = [];
  let cur = '';
  let q = ''; // active quote char, '' when unquoted
  for (let i = 0; i < str.length; i++) {
    const c = str[i];
    if (q) { cur += c; if (c === q) q = ''; continue; }
    if (c === "'" || c === '"') { q = c; cur += c; continue; }
    if (c === '\n' || c === ';') { out.push(cur); cur = ''; continue; }
    if (c === '|') { if (str[i + 1] === '|') i++; out.push(cur); cur = ''; continue; }
    if (c === '&' && str[i + 1] === '&') { i++; out.push(cur); cur = ''; continue; }
    cur += c;
  }
  out.push(cur);
  return out;
}

export function isRealRunnerInvocation(command, testRe) {
  if (!testRe) return false;
  const str = String(command || '');
  for (let seg of splitSegments(str)) {                   // quote-aware shell statement/pipe boundaries
    seg = seg.trim();
    if (!seg || seg.startsWith('#')) continue;            // empty or a comment segment
    while (ENV_ASSIGN.test(seg)) seg = seg.replace(ENV_ASSIGN, ''); // drop leading env-assignments
    seg = seg.trim();
    if (!seg || ASSIGN_START.test(seg)) continue;         // empty, or a standalone NAME=value assignment
    const first = seg.split(/\s+/)[0] || '';
    if (NOOP_FIRST.test(first)) continue;                 // echo/printf/cat/... never RUN the tests
    const pym = PYTHON_DASH_M.exec(seg);
    if (pym) { if (testRe.test(pym[1])) return true; continue; } // python -m <runner> (HB7)
    // Otherwise the segment must literally START with an allowlisted runner. testRe is non-global,
    // so exec() is stateless and matches from the front; index 0 == "starts with the runner".
    const m = testRe.exec(seg);
    if (m && m.index === 0) return true;
  }
  return false;
}

// A2 advisory result-signature scanner (DP-A2-SIG). A broad, LINEAR match for the summary line a
// runner prints on completion (pytest/jest/vitest `N passed|failed|...`, mocha `N passing`, cargo
// `test result:`, go/unittest `ok`/`FAILED`, generic PASS/FAIL). The A2 flow-STEP gate does NOT
// require this signature: codex truncates large logs, so a real green run's summary line can be
// missing, and requiring it would false-block those runs (this is why `pytest --version` is accepted
// rather than caught — see codex-flow-evidence.mjs). Exported for review + tests and reserved for a
// future opt-in strict mode; exit0 remains the reliable gate.
const TEST_RESULT_SIGNATURE = new RegExp([
  '\\b\\d+\\s+(?:passed|failed|errors?|skipped)\\b', // pytest / jest / vitest
  '\\b\\d+\\s+passing\\b',                            // mocha
  '\\btest result:',                                 // cargo
  '\\bok\\b',                                         // go / unittest OK
  '\\bfailed\\b',                                     // unittest / go FAILED
  '\\bpass\\b', '\\bfail\\b',                         // go PASS / FAIL (generic)
].join('|'), 'i');

export function outputHasTestSignature(text) {
  return typeof text === 'string' && TEST_RESULT_SIGNATURE.test(text);
}

// Parse a transcript JSONL into a trace of observable facts. Fail-open to an empty trace.
export function parseTranscript(transcriptPath) {
  const empty = { tools: [], commands: [], edits: [], lastText: '', raw: '', results: new Map() };
  if (!transcriptPath) return empty;
  let raw = '';
  try { raw = readFileSync(transcriptPath, 'utf8'); } catch { return empty; }
  const tools = [];
  const commands = [];
  const edits = [];
  const results = new Map(); // tool_use id -> { nonError } from native user tool_result records
  let lastText = '';
  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    let e;
    try { e = JSON.parse(line); } catch { continue; }
    if (e?.type === 'user' && Array.isArray(e?.message?.content)) {
      for (const r of e.message.content) {
        if (r?.type !== 'tool_result' || typeof r.tool_use_id !== 'string') continue;
        // is_error absent counts as non-error; any non-error result for an id marks it non-error.
        const nonError = r.is_error !== true || Boolean(results.get(r.tool_use_id)?.nonError);
        results.set(r.tool_use_id, { nonError });
      }
    }
    if (e?.type !== 'assistant') continue;
    const content = e?.message?.content;
    if (typeof content === 'string') { if (content) lastText = content; continue; }
    if (!Array.isArray(content)) continue;
    for (const c of content) {
      if (c?.type === 'text' && c.text) lastText = c.text;
      else if (c?.type === 'tool_use') {
        const inputStr = JSON.stringify(c.input || {});
        tools.push({ name: c.name || '', inputStr, id: typeof c.id === 'string' ? c.id : null });
        if (c.name === 'Bash' && c.input?.command) commands.push(String(c.input.command));
        if (['Edit', 'Write', 'MultiEdit'].includes(c.name) && c.input?.file_path) {
          edits.push(String(c.input.file_path));
        }
      }
    }
  }
  return { tools, commands, edits, lastText, raw, results };
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
  const configured = String(process.env.AGENTIC_SDLC_PYTHON || '').trim();
  const candidates = (configured ? [[configured]] : []).concat(process.platform === 'win32'
    ? [['python3'], ['python'], ['py', '-3']]
    : [['python3'], ['python']]);
  const script = join(HOOK_DIR, '..', 'scripts', 'validate_artifacts.py');
  const tail = ['--mode', mode, '--file', file, '--strict'];
  if (mode === 'plan' && specFile) tail.push('--spec', specFile);
  for (const c of candidates) {
    const r = spawnSync(c[0], [...c.slice(1), script, ...tail], { encoding: 'utf8', cwd, timeout: 10000 });
    if (r.error) continue;          // interpreter not found — try next
    if (r.status === null) continue; // spawn failed
    if (/unable to create process using/i.test(String(r.stderr || ''))) continue;
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
      // A2 SHAPE gate: a command satisfies a test-run step only if it actually invokes a runner
      // (`echo pytest` / `echo "...5 passed..."` no longer count). Claude's Bash exit/output substrate
      // is unverified (HB4), so only the command TEXT shape is enforced here; the Codex engine
      // additionally checks exit0 from its rollout `Exit code:` carrier (deliberate asymmetry).
      return trace.commands.some((c) => isRealRunnerInvocation(c, re));
    }
    case 'reviewResult':
      // Warn-level only: a reviewer group (control, security) fails when a member was dispatched and no
      // dispatched member has a correlated non-error result. Dispatch matching is toolUsePresent's test.
      return Object.values(item.reviewers || {}).every((members) => {
        const dispatched = trace.tools.filter((t) => (members || []).some((m) => t.name === m.tool && t.inputStr.includes(m.contains)));
        return !dispatched.length || dispatched.some((t) => t.id && trace.results?.get(t.id)?.nonError);
      });
    case 'branch':
      // Warn-level only (flow-requirements.json): satisfied unless the Stop-time cwd is on main/master.
      return resolveBranchState(ctx.cwd) !== 'protected';
    default:
      return false;
  }
}

// Branch state for the warn-level `branch` step (S10). Fixed argv run without a shell; repository-
// configured programs (fsmonitor, hooks, pager) are disabled, optional locks and prompts are off. It
// does not reuse branch-guard.mjs currentBranch, which lacks this hardening (D5). The branch name is
// never returned or logged: only 'protected' | 'ok' | 'unknown'.
export const BRANCH_GIT_ARGV = Object.freeze({
  symbolicRef: Object.freeze(['-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=', '--no-pager',
    'symbolic-ref', '--quiet', '--short', 'HEAD']),
  verifyHead: Object.freeze(['-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=', '--no-pager',
    'rev-parse', '--verify', '--quiet', 'HEAD']),
});

// D25 model (5): a program is started only by an absolute path found in an absolute PATH entry, so
// neither a relative entry nor the win32 cwd-first lookup can reach a program planted in the
// untrusted cwd. On win32 only <name>.exe and <name>.com are tried (PATHEXT is not consulted, so a
// batch file is never a candidate); elsewhere a candidate must be an executable regular file.
function programOnAbsolutePath(name) {
  const win = process.platform === 'win32';
  const absolute = win ? /^(?:[A-Za-z]:[\\/]|\\\\|\/\/)/ : /^\//;
  const names = win ? [`${name}.exe`, `${name}.com`] : [name];
  for (const entry of String(process.env.PATH ?? '').split(win ? ';' : ':')) {
    if (!absolute.test(entry)) continue;
    for (const candidate of names) {
      const full = join(entry, candidate);
      try {
        if (!statSync(full).isFile()) continue;
        if (!win) accessSync(full, fsConstants.X_OK);
        return full;
      } catch {
        // missing or not executable: try the next candidate
      }
    }
  }
  return null;
}

// SEC-5: the repository-selecting keys are DELETED from the child environment, not forwarded. They
// override `cwd` for symbolic-ref/rev-parse, so an inherited GIT_DIR made a repository genuinely on
// `main` report 'ok' — and docs/runtime-adapter.md states the branch is the WORKING-DIRECTORY branch.
// The list mirrors scripts/build_release.py `_GIT_ENV_DROP`, the sibling probe in the same change set.
const BRANCH_GIT_ENV_DROP = Object.freeze([
  'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY',
  'GIT_ALTERNATE_OBJECT_DIRECTORIES',
  'GIT_COMMON_DIR', // redirects refs and objects even when GIT_DIR is dropped (SEC-5 residual)
]);

export function resolveBranchState(cwd) {
  try {
    const git = programOnAbsolutePath('git');
    if (!git) return 'unknown';
    const env = { ...process.env, GIT_OPTIONAL_LOCKS: '0', GIT_TERMINAL_PROMPT: '0', NoDefaultCurrentDirectoryInExePath: '1' };
    for (const key of BRANCH_GIT_ENV_DROP) delete env[key];
    const options = {
      cwd,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
      timeout: 5000,
      env,
    };
    const name = execFileSync(git, BRANCH_GIT_ARGV.symbolicRef, options).trim();
    execFileSync(git, BRANCH_GIT_ARGV.verifyHead, options); // throws when there is no commit yet
    return name === 'main' || name === 'master' ? 'protected' : 'ok';
  } catch {
    return 'unknown'; // git missing, not a repository, detached HEAD, no commits, or a timeout
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
