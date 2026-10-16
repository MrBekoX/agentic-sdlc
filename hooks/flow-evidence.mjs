// Shared evidence engine for the flow-step enforcement hooks (flow-step-guard, flow-order-guard).
//
// Principle: evidence is RE-DERIVED from observable facts, never trusted from the agent's prose.
//   - artifact : the file exists AND validate_artifacts.py re-validates it (Stop, thorough) or
//                merely exists (PreToolUse, cheap). If the validator cannot run, fail-open.
//   - toolUse  : a real tool_use event of the named tool whose input contains the marker (`contains`),
//                or whose skill / subagent_type IS the named component (`exactName`).
//   - command  : a real Bash or PowerShell command in the transcript matching the named regex.
//   - branch   : the Stop-time working-directory branch is not main/master (warn-level step).
//   - reviewResult : a dispatched reviewer returned a correlated non-error tool_result (warn-level).
// Every reader fails OPEN (treats as allowed / satisfied) on its own error, matching the other guards.
import { readFileSync, readdirSync } from 'node:fs';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve as resolvePath } from 'node:path';
import { programOnAbsolutePath } from './git-exec.mjs';

export const HOOK_DIR = dirname(fileURLToPath(import.meta.url));
const PLUGIN_ROOT = dirname(HOOK_DIR);

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
const RECEIPT_STATUSES = new Set(['async_launched', 'remote_launched']);
const HEADER_TAGS = ['task-id', 'tool-use-id', 'output-file', 'status'];
const MAX_HEADER_VALUE = 256;

function userRecordText(e) {
  const content = e?.message?.content;
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  let out = '';
  for (const c of content) {
    if (c?.type === 'text' && typeof c.text === 'string') out += c.text;
  }
  return out;
}

// C14 turn boundary: a GENUINE user prompt is a `type:"user"` record whose content is a string or text
// blocks, never a tool_result. System-generated user records are not prompts: the isMeta record Claude
// Code writes after every Skill tool_use (it carries the skill body), a background-task notification
// (origin.kind task-notification, or string content that starts with <task-notification>), and the
// isCompactSummary record a compaction writes (C16 item 9).
function isGenuinePrompt(e) {
  if (e.isMeta === true || e.isCompactSummary === true || e.origin?.kind === 'task-notification') return false;
  const content = e.message?.content;
  if (typeof content === 'string') return !content.startsWith('<task-notification>');
  return Array.isArray(content)
    && content.some((c) => c?.type === 'text')
    && !content.some((c) => c?.type === 'tool_result');
}

// C14 top-level: no parent_tool_use_id and not a sidechain record (a sub-agent's own calls).
function isTopLevel(e) {
  return !e.isSidechain && e.parent_tool_use_id == null;
}

// The text of one assistant record: string content, or its text blocks joined by newlines - the same
// reading completion-claim-guard uses for its transcript fallback.
function assistantRecordText(content) {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  return content.filter((c) => c?.type === 'text').map((c) => c.text || '').join('\n');
}

// BR8/BR9: index-based header walk. Stops at <summary>/<result>; never scans a padded body.
export function parseTaskNotificationHeader(text) {
  if (typeof text !== 'string' || !text) return null;
  const start = text.indexOf('<task-notification>');
  if (start === -1) return null;
  let i = start + '<task-notification>'.length;
  const seen = Object.create(null);
  let toolUseId = null;
  let status = null;
  while (i < text.length) {
    while (i < text.length) {
      const ch = text.charCodeAt(i);
      if (ch === 32 || ch === 9 || ch === 10 || ch === 13) i += 1;
      else break;
    }
    if (text.startsWith('<summary>', i) || text.startsWith('<result>', i)) {
      return toolUseId && status ? { toolUseId, status } : null;
    }
    let matched = false;
    for (const tag of HEADER_TAGS) {
      const open = `<${tag}>`;
      const close = `</${tag}>`;
      if (!text.startsWith(open, i)) continue;
      if (seen[tag]) return null;
      const valStart = i + open.length;
      const valEnd = text.indexOf(close, valStart);
      if (valEnd === -1 || (valEnd - valStart) > MAX_HEADER_VALUE) return null;
      const value = text.slice(valStart, valEnd);
      if (value.includes('<')) return null;
      seen[tag] = true;
      if (tag === 'tool-use-id') toolUseId = value;
      if (tag === 'status') status = value;
      i = valEnd + close.length;
      matched = true;
      break;
    }
    if (!matched) return null;
  }
  return null;
}

// C16 item 11: a tool entry keeps only the exact-name fields of its input (string input.skill /
// input.subagent_type, the only fields toolMatches reads). The rest of the parsed input object - a Write
// body, a long prompt - is dropped; `inputStr` still carries the full serialized input for `contains`.
function exactNameFields(input) {
  const kept = {};
  if (typeof input?.skill === 'string') kept.skill = input.skill;
  if (typeof input?.subagent_type === 'string') kept.subagent_type = input.subagent_type;
  return kept;
}

export function parseTranscript(transcriptPath) {
  const empty = {
    tools: [], commands: [], edits: [], lastText: '', raw: '',
    results: new Map(), receipts: new Map(), completions: new Map(),
    turnTools: [], lastRecordText: '', resultPos: new Map(), lastTopTextPos: -1,
  };
  if (!transcriptPath) return empty;
  let raw = '';
  try { raw = readFileSync(transcriptPath, 'utf8'); } catch { return empty; }
  const tools = [];
  const commands = [];
  const edits = [];
  const results = new Map(); // tool_use id -> { nonError } from native user tool_result records
  const receipts = new Map(); // tool_use id -> { status, error } for a single-result user record
  const completions = new Map(); // tool_use id -> Set of BR8 notification statuses
  let lastText = '';
  let turnTools = []; // top-level tool_uses since the last top-level genuine user prompt (C14 turn)
  let lastRecordText = ''; // text of the last assistant record that has any (completion-claim-guard reading)
  // C16 item 10 (O4 caught-up guard): record positions, so Stop can tell whether a top-level assistant
  // text record landed after a call's result.
  const resultPos = new Map(); // tool_use id -> position of the latest record carrying its tool_result
  let lastTopTextPos = -1; // position of the last top-level assistant record that has text
  let pos = -1;
  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    let e;
    try { e = JSON.parse(line); } catch { continue; }
    pos += 1;
    if (e?.type === 'user') {
      const origin = e.origin;
      if (origin && origin.kind === 'task-notification' && origin.subkind == null) {
        const header = parseTaskNotificationHeader(userRecordText(e));
        if (header) {
          let set = completions.get(header.toolUseId);
          if (!set) { set = new Set(); completions.set(header.toolUseId, set); }
          set.add(header.status);
        }
      }
      const content = e?.message?.content;
      const resultItems = Array.isArray(content)
        ? content.filter((r) => r?.type === 'tool_result' && typeof r.tool_use_id === 'string')
        : [];
      const tus = e.toolUseResult;
      if (resultItems.length === 1 && tus && typeof tus === 'object') {
        const id = resultItems[0].tool_use_id;
        const status = tus.status;
        const error = tus.error;
        if (RECEIPT_STATUSES.has(status) || (error != null && error !== '')) {
          receipts.set(id, { status, error });
        }
      }
      for (const r of resultItems) {
        resultPos.set(r.tool_use_id, pos);
        if (RECEIPT_STATUSES.has(receipts.get(r.tool_use_id)?.status)) continue;
        // is_error absent counts as non-error; any non-error result for an id marks it non-error.
        const nonError = r.is_error !== true || Boolean(results.get(r.tool_use_id)?.nonError);
        results.set(r.tool_use_id, { nonError });
      }
      // A new user turn starts here. C16 item 9: only a TOP-LEVEL genuine prompt opens one; a sidechain
      // or parent_tool_use_id user record is a sub-agent's prompt.
      if (isTopLevel(e) && isGenuinePrompt(e)) turnTools = [];
    }
    if (e?.type !== 'assistant') continue;
    const content = e?.message?.content;
    const recordText = assistantRecordText(content);
    if (recordText) lastRecordText = recordText;
    const topLevel = isTopLevel(e);
    if (recordText && topLevel) lastTopTextPos = pos;
    if (typeof content === 'string') { if (content) lastText = content; continue; }
    if (!Array.isArray(content)) continue;
    for (const c of content) {
      if (c?.type === 'text' && c.text) lastText = c.text;
      else if (c?.type === 'tool_use') {
        const inputStr = JSON.stringify(c.input || {});
        const tool = {
          name: c.name || '', inputStr, input: exactNameFields(c.input), id: typeof c.id === 'string' ? c.id : null,
        };
        tools.push(tool);
        if (topLevel) turnTools.push(tool);
        if ((c.name === 'Bash' || c.name === 'PowerShell') && c.input?.command) {
          commands.push(String(c.input.command));
        }
        if (['Edit', 'Write', 'MultiEdit'].includes(c.name) && c.input?.file_path) {
          edits.push(String(c.input.file_path));
        }
      }
    }
  }
  return {
    tools, commands, edits, lastText, raw, results, receipts, completions, turnTools, lastRecordText,
    resultPos, lastTopTextPos,
  };
}

function receiptHasError(trace, id) {
  const rec = trace.receipts?.get(id);
  return rec != null && rec.error != null && rec.error !== '';
}

function notificationCompleted(trace, id) {
  return Boolean(trace.completions?.get(id)?.has('completed'));
}

// C6 exact names. An `exactName` item is satisfied only by a tool_use that CALLS that component: its
// input.skill (Skill) or input.subagent_type (Agent) equals X or agentic-sdlc:X. The name appearing
// elsewhere in the input (args, a prompt), a lookalike (X-extra) or a foreign prefix (other:X) does not
// count. Exact names are defined for Skill and Agent only. A `contains` item keeps the substring match
// over the serialized input.
const EXACT_NAME_FIELD = { Skill: 'skill', Agent: 'subagent_type' };

function isExactName(value, name) {
  return typeof value === 'string' && (value === name || value === `agentic-sdlc:${name}`);
}

// Does tool_use `t` match an evidence item or reviewer member { tool, exactName | contains }?
function toolMatches(t, m) {
  if (t.name !== m.tool) return false;
  if (typeof m.exactName === 'string') {
    const field = EXACT_NAME_FIELD[m.tool];
    return Boolean(field) && isExactName(t.input?.[field], m.exactName);
  }
  return t.inputStr.includes(m.contains);
}

function inFlightReviewer(ctx, members) {
  const tasks = ctx.backgroundTasks;
  if (!Array.isArray(tasks)) return false;
  return tasks.some((task) => {
    if (task?.type !== 'subagent') return false;
    const agentType = String(task.agent_type || '');
    return (members || []).some((m) => (typeof m.exactName === 'string'
      ? isExactName(agentType, m.exactName)
      : agentType.includes(m.contains)));
  });
}

function toolUsePresent(trace, item, tools = trace.tools) {
  return tools.some((t) => {
    if (!toolMatches(t, item)) return false;
    if (t.id && receiptHasError(trace, t.id)) return false;
    return true;
  });
}

// Flows whose activeWhen.skill marker IS the skill of a real Skill tool_use (exact name, C6): a
// dispatch-strategy call whose args mention feature-build activates nothing. An errored call
// (receiptHasError) still activates nothing; a call with no id or no result still counts.
export function activeFlowNames(trace, req) {
  const out = [];
  for (const [name, flow] of Object.entries(req.flows || {})) {
    const marker = flow?.activeWhen?.skill;
    if (marker && toolUsePresent(trace, { tool: 'Skill', exactName: marker })) out.push(name);
  }
  return out;
}

// O4 dispatch-terminal check (pipeline v2.1 C6/C14), read by flow-step-guard on Stop: is the LAST
// top-level tool_use of the current turn a Skill call to `name` (exact name)? The turn starts after the
// last genuine user prompt, so a call from an earlier turn never counts.
export function turnEndsOnSkill(trace, name) {
  const tools = trace.turnTools || [];
  const last = tools[tools.length - 1];
  return Boolean(last) && toolMatches(last, { tool: 'Skill', exactName: name });
}

// C16 item 8: does the current turn itself contain a top-level, non-error Skill call to `name` (exact
// name, the activeFlowNames rule)? A flow activated in an earlier turn does not count.
export function turnInvokesSkill(trace, name) {
  return toolUsePresent(trace, { tool: 'Skill', exactName: name }, trace.turnTools || []);
}

// C16 item 10: has a top-level assistant text record landed after the result of the turn's last
// top-level tool_use? Without that, a transcript read at Stop may not have caught up: its last text can
// predate the call. A call with no id or no recorded result has nothing to be after -> false.
export function turnTextAfterLastResult(trace) {
  const tools = trace.turnTools || [];
  const last = tools[tools.length - 1];
  if (!last?.id) return false;
  const at = trace.resultPos?.get(last.id);
  return at != null && trace.lastTopTextPos > at;
}

// The final assistant text: last_assistant_message when it is a string, otherwise the transcript's last
// assistant text - completion-claim-guard's precedence and fallback.
export function finalAssistantText(trace, lastAssistantMessage) {
  return typeof lastAssistantMessage === 'string' ? lastAssistantMessage : (trace.lastRecordText || '');
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

// The first candidate that really is Python 3.8+, cached for this hook process (null = none).
// A candidate qualifies only when its `-c` probe prints 1: the Microsoft Store alias (`python3.exe`
// exits 9009 without running anything), a `py` launcher pointing at an uninstalled Python, and a
// Python 2 `python` all used to be taken as the interpreter, and their non-zero exit then read as a
// FAILED validation - fail-closed on exactly the machines the fail-open contract exists for.
// A real interpreter answers the probe in well under a second; the 3 s cap bounds a hung candidate.
// If probes plus validator runs ever exceed a hook's runtime timeout, the runtime kills the hook,
// which fails open like an unavailable interpreter.
let validatorPython;
function findPython() {
  if (validatorPython !== undefined) return validatorPython;
  const configured = String(process.env.AGENTIC_SDLC_PYTHON || '').trim();
  const candidates = (configured ? [[configured]] : []).concat(process.platform === 'win32'
    ? [['python3'], ['python'], ['py', '-3']]
    : [['python3'], ['python']]);
  validatorPython = null;
  for (const [name, ...args] of candidates) {
    const program = programOnAbsolutePath(name);
    if (!program) continue;
    const r = spawnSync(program, [...args, '-I', '-c', 'import sys; print(int(sys.version_info >= (3, 8)))'],
      { encoding: 'utf8', timeout: 3000, stdio: ['ignore', 'pipe', 'ignore'], cwd: PLUGIN_ROOT });
    if (!r.error && r.status === 0 && String(r.stdout || '').trim() === '1') {
      validatorPython = [program, ...args];
      break;
    }
  }
  return validatorPython;
}

// Runs validate_artifacts.py on one artifact. Read-only subprocess: the artifact path is a SEPARATE
// argv (no shell). Returns the exit code, or null when no Python 3 can run -> caller fails open.
// Shared by the Codex engines (codex-flow-evidence.mjs, flow-order-guard-codex.mjs).
// The probe and the validator run with `-I` from the plugin root, never the user's project: a
// project `sitecustomize.py` (reached through an empty PYTHONPATH entry) or a version-shim file
// (`.python-version` naming a missing version) must not run code or flip the gate to fail-open.
export function runValidator(mode, file, specFile, cwd) {
  const python = findPython();
  if (!python) return null;
  const script = join(PLUGIN_ROOT, 'scripts', 'validate_artifacts.py');
  const tail = ['--mode', mode, '--file', resolvePath(cwd || '.', file), '--strict'];
  if (mode === 'plan' && specFile) tail.push('--spec', resolvePath(cwd || '.', specFile));
  const r = spawnSync(python[0], [...python.slice(1), '-I', script, ...tail],
    { encoding: 'utf8', cwd: PLUGIN_ROOT, timeout: 10000 });
  if (r.error || r.status === null) return null; // interpreter vanished or timed out -> fail open
  return r.status;                               // 0 = pass, non-zero = fail (e.g. a stub artifact)
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
      return toolUsePresent(trace, item);
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
      // Warn-level only: a reviewer group fails when a member was dispatched and no dispatched
      // member has a completed result. Launch receipts stay pending; a BR8 completed notification
      // or an in-flight background_tasks subagent naming the reviewer is not missing.
      return Object.values(item.reviewers || {}).every((members) => {
        const dispatched = trace.tools.filter((t) => (members || []).some((m) => toolMatches(t, m)));
        if (!dispatched.length) return true;
        if (dispatched.some((t) => t.id && notificationCompleted(trace, t.id))) return true;
        if (dispatched.some((t) => t.id && trace.results?.get(t.id)?.nonError)) return true;
        return inFlightReviewer(ctx, members);
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

// D25 model (5): a program is started only by an absolute path found in an absolute PATH entry
// (programOnAbsolutePath, shared from git-exec.mjs), so neither a relative entry nor the win32
// cwd-first lookup can reach a program planted in the untrusted cwd. On win32 only <name>.exe and
// <name>.com are tried; elsewhere a candidate must be an executable regular file.

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

export function completionClaimPresent(trace, req, lastAssistantMessage) {
  const text = typeof lastAssistantMessage === 'string' ? lastAssistantMessage : (trace.lastText || '');
  if (!req.completionClaim || !text) return false;
  try { return new RegExp(req.completionClaim, 'i').test(text); } catch { return false; }
}

// Flush stdout, then exit — avoids truncation on a piped stdout under Windows (same as the other guards).
export function emit(out) {
  if (out && Object.keys(out).length) {
    process.stdout.write(JSON.stringify(out), () => process.exit(0));
  } else {
    process.exit(0);
  }
}
