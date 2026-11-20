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
import { readFileSync, readdirSync, realpathSync } from 'node:fs';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve as resolvePath } from 'node:path';
import { programOnAbsolutePath } from './git-exec.mjs';
import { blankHeredocBodies, firstUnreadHeredoc, legacyHeredocPattern } from './codex-write-signal.mjs';
import { splitBr6StatementJoins, currentEditTargets } from './codex-rollout.mjs';

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
// `echo "...5 passed..."`) forged the evidence. Here we require a real invocation: some simple command
// must START with an allowlisted runner (or be `python[3] -m <runner>`), after its leading env
// assignments, and must NOT be a no-op printer (echo/printf/:/true/cat/head/tail/cd).
//   FH-3: heredoc BODIES are dropped first (shared heredoc grammar) and statements come from the BR6
//   splitter, which skips `#` comments, so `cat > Makefile <<'EOF' ... pytest ... EOF` and `ls # ; pytest`
//   run nothing.
//   FH-9 / SK-10: a runner behind `time`, `timeout N`, `env`, `nice`, a path (`.venv/bin/pytest`,
//   `./gradlew`), a launcher (`uv|poetry|pipenv run`, `npx`, `bunx`, `pnpm exec`), python interpreter
//   flags (`python -I -X dev -m pytest`), or a shell wrapper (`bash -lc '...'`, `sh -c`,
//   `powershell|pwsh -Command ...`, `cmd /c ...`) counts; the wrapped command is checked the same way.
// Pure string work; every pass is linear and every regex is linear (disjoint classes, no nested
// quantifier), and wrapper recursion is depth-bounded, so an adversarial command cannot ReDoS the guard.
const NOOP_FIRST = /^(?:echo|printf|:|true|cat|head|tail|cd)$/;
// A word that is a `NAME=value` assignment. Its value is stripped only when it is quoted or bare WITHOUT
// shell metacharacters, so a command-substitution value like `$(echo pytest)` is NOT swallowed and the
// segment is then a standalone assignment, not a command (a bare `pytest=1` never qualifies).
const ASSIGN_START = /^[A-Za-z_][A-Za-z0-9_]*=/;
const SAFE_ASSIGN_VALUE = /^(?:"[^"]*"|'[^']*'|[^\s"'$`(){}|&;<>]*)$/;
const PYTHON_WORD = /^(?:python[0-9.]*|py)$/;
const PY_SELECTOR = /^-[0-9.]+$/;                 // launcher version flag (`py -3`, `python -3.11`)
const PY_FLAGS = /^-[bBdEIOPqRsSuv]+$/;            // interpreter flags without an argument (`-I`, `-B`, `-OO`)
const PY_ARG_FLAG = /^-[WX]$/;                     // `-W arg`, `-X opt`
const PY_GLUED_ARG_FLAG = /^-[WX]./;               // `-Wdefault`, `-Xdev`
const SHELLS = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh']);
const POWERSHELLS = new Set(['powershell', 'pwsh']);
const PS_COMMAND = /^[-/]c(?:o(?:m(?:m(?:a(?:n(?:d)?)?)?)?)?)?$/i;
const PS_VALUE_OPTION = /^[-/](?:executionpolicy|ex|ep|windowstyle|w|inputformat|inp|if|outputformat|o|of|version|v|configurationname|config|workingdirectory|wd|settingsfile|settings|custompipename)$/i;
const RUN_LAUNCHERS = new Set(['uv', 'poetry', 'pipenv']); // `<launcher> run <command>`
const EXEC_LAUNCHERS = new Set(['npx', 'bunx']);            // `<launcher> <command>`
const DURATION = /^[0-9]+(?:\.[0-9]+)?[smhd]?$/;
const MAX_WRAPPER_DEPTH = 3;

// Quote-aware split of one BR6 statement into simple commands at `&&`, `|`, `|&` and a background `&`
// (not the `&` of `>&`, `<&` or `&>`). A backslash escapes the next character. Single linear pass.
function splitSimpleCommands(str) {
  const out = [];
  let cur = '';
  let q = null;
  for (let i = 0; i < str.length; i += 1) {
    const c = str[i];
    if (q === "'") { cur += c; if (c === q) q = null; continue; }
    if (c === '\\') { cur += c; if (i + 1 < str.length) { cur += str[i + 1]; i += 1; } continue; }
    if (q) { cur += c; if (c === q) q = null; continue; }
    if (c === "'" || c === '"') { q = c; cur += c; continue; }
    if (c === '|') { if (str[i + 1] === '&' || str[i + 1] === '|') i += 1; out.push(cur); cur = ''; continue; }
    if (c === '&') {
      if (str[i + 1] === '&') { i += 1; out.push(cur); cur = ''; continue; }
      const prev = cur[cur.length - 1];
      if (prev === '>' || prev === '<' || str[i + 1] === '>') { cur += c; continue; }
      out.push(cur); cur = ''; continue;
    }
    cur += c;
  }
  out.push(cur);
  return out;
}

// Shell words of one simple command: {raw, value, quoted}. Blanks separate words outside quotes; quotes
// are removed from `value`; backslashes are kept (a Windows path survives) except before a character
// double quotes escape. Single linear pass.
function shellWords(str) {
  const words = [];
  let raw = null;
  let value = '';
  let quoted = false;
  let q = null;
  const flush = () => { if (raw !== null) words.push({ raw, value, quoted }); raw = null; value = ''; quoted = false; };
  for (let i = 0; i < str.length; i += 1) {
    const c = str[i];
    if (q === "'") { raw += c; if (c === "'") q = null; else value += c; continue; }
    if (q === '"') {
      raw += c;
      if (c === '\\' && i + 1 < str.length && '"\\$`'.includes(str[i + 1])) { raw += str[i + 1]; value += str[i + 1]; i += 1; continue; }
      if (c === '"') q = null; else value += c;
      continue;
    }
    if (c === ' ' || c === '\t' || c === '\n' || c === '\r') { flush(); continue; }
    if (raw === null) raw = '';
    if (c === "'" || c === '"') { q = c; quoted = true; raw += c; continue; }
    if (c === '\\' && i + 1 < str.length) { raw += c + str[i + 1]; value += c + str[i + 1]; i += 1; continue; }
    raw += c;
    value += c;
  }
  flush();
  return words;
}

// The program name of a command word: its basename (either slash), without a Windows launcher suffix.
function programName(value) {
  const base = String(value).split(/[\\/]/).pop() || '';
  return base.replace(/\.(?:exe|cmd|bat|com)$/i, '');
}

function skipTimeoutPrefix(words, j) {
  while (j < words.length && words[j].value.startsWith('-')) {
    const v = words[j].value;
    j += (v === '-k' || v === '-s') ? 2 : 1; // -k DURATION / -s SIGNAL take a value; long forms use `=`
  }
  return j < words.length && DURATION.test(words[j].value) ? j + 1 : -1;
}

function skipEnvPrefix(words, j) {
  while (j < words.length && words[j].value.startsWith('-')) {
    const v = words[j].value;
    if (v === '-S' || v.startsWith('--split-string') || v.startsWith('-S')) return -1; // a split string: not read
    j += (v === '-u' || v === '-C') ? 2 : 1;
  }
  return j;
}

function skipNicePrefix(words, j) {
  if (j < words.length && words[j].value === '-n') return j + 2;
  if (j < words.length && /^(?:-n?-?[0-9]+|--adjustment=.*)$/.test(words[j].value)) return j + 1;
  return j;
}

function shellWrapperRuns(words, j, testRe, depth) {
  let sawC = false;
  for (; j < words.length; j += 1) {
    const v = words[j].value;
    if (v === '--') { j += 1; break; }
    if (/^[-+]O$|^[-+]o$|^--(?:rcfile|init-file)$/.test(v)) { j += 1; continue; } // option with a value
    if (/^--[a-z-]+$/.test(v)) continue;                                          // --login, --noprofile ...
    if (/^[-+][A-Za-z]+$/.test(v)) { if (v[0] === '-' && v.includes('c')) sawC = true; continue; }
    break;
  }
  if (!sawC || j >= words.length) return false; // `bash script.sh` runs a file this check cannot read
  // `bash -lc 'pytest -q'` carries the command in one word. A Codex argv array is recorded joined by
  // spaces, so an UNQUOTED command word is read together with the words after it.
  const script = words[j].quoted ? words[j].value : words.slice(j).map((w) => w.value).join(' ');
  return runnerIn(script, testRe, depth + 1);
}

function powershellWrapperRuns(words, j, testRe, depth) {
  for (; j < words.length; j += 1) {
    const v = words[j].value;
    if (PS_COMMAND.test(v)) return runnerIn(words.slice(j + 1).map((w) => w.value).join(' '), testRe, depth + 1);
    if (PS_VALUE_OPTION.test(v)) { j += 1; continue; }
    if (/^[-/][A-Za-z]+$/.test(v) && !/^[-/](?:f|fi|fil|file|e|ec|en|enc|encodedcommand)$/i.test(v)) continue;
    return false; // -File, -EncodedCommand or a positional argument: not a readable command
  }
  return false;
}

function cmdWrapperRuns(words, j, testRe, depth) {
  for (; j < words.length; j += 1) {
    const v = words[j].value.toLowerCase();
    if (v === '/c' || v === '/k') return runnerIn(words.slice(j + 1).map((w) => w.value).join(' '), testRe, depth + 1);
    if (!/^\/[a-z]$/.test(v)) return false;
  }
  return false;
}

function pythonModuleRuns(words, j, testRe) {
  if (j < words.length && PY_SELECTOR.test(words[j].value)) j += 1;
  while (j < words.length) {
    const v = words[j].value;
    if (PY_FLAGS.test(v) || PY_GLUED_ARG_FLAG.test(v)) j += 1;
    else if (PY_ARG_FLAG.test(v)) j += 2;
    else break;
  }
  return j + 1 < words.length && words[j].value === '-m' && testRe.test(words[j + 1].value); // HB7
}

// Does this simple command (its words) run a test runner?
function simpleCommandRuns(words, testRe, depth) {
  let i = 0;
  for (;;) {
    while (i < words.length && ASSIGN_START.test(words[i].raw)) {
      const raw = words[i].raw;
      if (!SAFE_ASSIGN_VALUE.test(raw.slice(raw.indexOf('=') + 1))) return false; // a standalone assignment
      i += 1;
    }
    if (i >= words.length) return false;
    const name = programName(words[i].value).toLowerCase();
    let next = -1;
    if (name === 'time') { next = i + 1; while (next < words.length && /^-p$|^--$/.test(words[next].value)) next += 1; }
    else if (name === 'timeout') next = skipTimeoutPrefix(words, i + 1);
    else if (name === 'env') next = skipEnvPrefix(words, i + 1);
    else if (name === 'nice') next = skipNicePrefix(words, i + 1);
    else if (RUN_LAUNCHERS.has(name) && words[i + 1]?.value === 'run') next = i + 2;
    else if (EXEC_LAUNCHERS.has(name)) next = i + 1;
    else if (name === 'pnpm' && words[i + 1]?.value === 'exec') next = i + 2;
    else break;
    if (next < 0) return false;
    i = next; // every prefix consumes at least one word, so this loop is linear
  }
  const program = programName(words[i].value);
  const lower = program.toLowerCase();
  if (NOOP_FIRST.test(program)) return false;                 // echo/printf/cat/... never RUN the tests
  if (depth < MAX_WRAPPER_DEPTH) {
    if (SHELLS.has(lower)) return shellWrapperRuns(words, i + 1, testRe, depth);
    if (POWERSHELLS.has(lower)) return powershellWrapperRuns(words, i + 1, testRe, depth);
    if (lower === 'cmd') return cmdWrapperRuns(words, i + 1, testRe, depth);
  }
  if (PYTHON_WORD.test(program)) return pythonModuleRuns(words, i + 1, testRe);
  // Otherwise the command must START with an allowlisted runner. testRe is non-global, so exec() is
  // stateless and matches from the front; index 0 == "starts with the runner".
  const text = [program].concat(words.slice(i + 1).map((w) => w.value)).join(' ');
  const m = testRe.exec(text);
  // A runner name followed by `.` inside the program word is a file name (`pytest.ini`, `tox.ini`).
  return Boolean(m) && m.index === 0 && program[m[0].length] !== '.';
}

// The test-run check counts a run only when BOTH heredoc readings count it, the current grammar and
// 1905c15's (codex-write-signal.mjs), so a grammar change cannot count a run the earlier reading did not.
// Missing evidence is the safe side here. Set only inside isRealRunnerInvocation (synchronous).
let legacyReading = false;
function runnerIn(command, testRe, depth) {
  // A heredoc the grammar leaves unread has a body of unknown length, so no line after its opener's
  // line is read as a command: a body line never counts as a test run (missing evidence is the safe side).
  let raw = String(command || '');
  if (!legacyReading) {
    const unread = firstUnreadHeredoc(raw);
    if (unread >= 0) { const end = raw.indexOf('\n', unread); if (end >= 0) raw = raw.slice(0, end); }
  }
  // FH-3: a heredoc body is data, not commands.
  const str = legacyReading ? blankHeredocBodies(raw, legacyHeredocPattern) : blankHeredocBodies(raw);
  for (const { text } of splitBr6StatementJoins(str)) {   // `;`, newline, `||`; comments skipped (FH-3)
    for (const seg of splitSimpleCommands(text)) {
      const words = shellWords(seg);
      if (words.length && simpleCommandRuns(words, testRe, depth)) return true;
    }
  }
  return false;
}

// R2-FH-1: the most bytes of one shell command the flow hooks analyse. A longer command is never evidence
// (no test run, no write target): it is not read at all, so no shape of it can hold a hook past its
// timeout, where it would fail open for the rest of the session. The current call of the flow-order
// guard is the one exception (shellWriteTargets with no cap, bounded by the recognizer's own 512 KiB cap).
export const SHELL_ANALYSIS_MAX = 128 * 1024;

export function isRealRunnerInvocation(command, testRe) {
  if (!testRe) return false;
  const str = String(command || '');
  if (str.length > SHELL_ANALYSIS_MAX) return false;
  if (!runnerIn(str, testRe, 0)) return false;
  legacyReading = true;
  try { return runnerIn(str, testRe, 0); } finally { legacyReading = false; }
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

// D7 slash-command start. Claude Code records `/name args` typed by the user as a genuine top-level user
// prompt whose content holds <command-name>/name</command-name> (captured in headless `claude -p` on
// 2.1.302, 2026-10-17: `/agentic-sdlc-pipeline` and `/agentic-sdlc:agentic-sdlc-pipeline` both record the
// namespaced name, after <command-message>name</command-message>). The record must open, after optional
// whitespace, with <command-message> or <command-name>, so a prose mention or a quoted tool output starts
// nothing; a prompt the user opens with those tags does. Only the first 4 KiB are searched and the name is
// bounded, so the scan is linear (TestSlashCommandFlowActivation times it).
const SLASH_HEADER = /^\s*<command-(?:message|name)>/;
const SLASH_NAME = /<command-name>\/([A-Za-z0-9:_-]{1,200})<\/command-name>/;

function slashCommandName(e) {
  const text = userRecordText(e);
  if (!SLASH_HEADER.test(text)) return null;
  const match = SLASH_NAME.exec(text.slice(0, 4096));
  return match ? match[1] : null;
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

// FH-1: the files a Bash or PowerShell command writes, read by the ONE shared write-target recognizer
// (codex-rollout.mjs currentEditTargets: extractWrittenContent plus the precise sed/tee/redirect reader)
// that the Codex flow-order gate uses, so both runtimes see the same shell write forms. Fail-open: [].
// A transcript command over SHELL_ANALYSIS_MAX yields no write target (R2-FH-1; parseTranscript records it as
// a possible source edit instead, R3-FH-2); pass maxBytes = Infinity for the current call only.
export function shellWriteTargets(command, maxBytes = SHELL_ANALYSIS_MAX) {
  try {
    const str = String(command || '');
    if (str.length > maxBytes) return [];
    return currentEditTargets('Bash', str);
  } catch {
    return [];
  }
}

// A copy of `trace` without the given tool_use ids (their tools, commands and edits). A PreToolUse guard
// drops the current call, which can already sit in the transcript but has not run yet (FH-1, the FH-6
// shape). R2-FH-1: this filters the one parse instead of parsing (and analysing every command) again.
export function withoutCalls(trace, ids) {
  if (!ids || !ids.size) return trace;
  const keep = (id) => !(typeof id === 'string' && ids.has(id));
  const commandIds = trace.commandIds || [];
  const editIds = trace.editIds || [];
  return {
    ...trace,
    tools: (trace.tools || []).filter((t) => keep(t.id)),
    turnTools: (trace.turnTools || []).filter((t) => keep(t.id)),
    commands: (trace.commands || []).filter((_c, i) => keep(commandIds[i])),
    commandIds: commandIds.filter((id) => keep(id)),
    edits: (trace.edits || []).filter((_e, i) => keep(editIds[i])),
    editIds: editIds.filter((id) => keep(id)),
    opaqueShellIds: (trace.opaqueShellIds || []).filter((id) => keep(id)),
    runnerCache: undefined,
  };
}

// Each tool call is analysed once per parse (R2-FH-1): its shell write targets here, its runner shape once
// per test pattern (evidenceSatisfied caches it on the trace). `commandIds`/`editIds` run parallel to
// `commands`/`edits` so withoutCalls can drop a call without re-parsing. R3-FH-2: `opaqueShellIds` lists the
// shell calls over SHELL_ANALYSIS_MAX; they are not read, so each may have written a source file.
export function parseTranscript(transcriptPath) {
  const empty = {
    tools: [], commands: [], commandIds: [], edits: [], editIds: [], opaqueShellIds: [], lastText: '', raw: '',
    results: new Map(), receipts: new Map(), stringResults: new Set(), completions: new Map(),
    turnTools: [], lastRecordText: '', resultPos: new Map(), lastTopTextPos: -1,
    slashCommands: [], turnSlashCommands: [],
  };
  if (!transcriptPath) return empty;
  let raw = '';
  try { raw = readFileSync(transcriptPath, 'utf8'); } catch { return empty; }
  const tools = [];
  const commands = [];
  const commandIds = [];
  const edits = [];
  const editIds = [];
  const opaqueShellIds = [];
  const results = new Map(); // tool_use id -> { nonError } from native user tool_result records
  const receipts = new Map(); // tool_use id -> { status, error } for a single-result user record
  const stringResults = new Set(); // tool_use ids whose single-result user record has a string toolUseResult
  const completions = new Map(); // tool_use id -> Set of BR8 notification statuses
  let lastText = '';
  let turnTools = []; // top-level tool_uses since the last top-level genuine user prompt (C14 turn)
  const slashCommands = []; // D7: command names of every top-level slash-command start
  let turnSlashCommands = []; // D7: the current turn's slash-command start, if its prompt was one
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
      } else if (resultItems.length === 1 && typeof tus === 'string') {
        stringResults.add(resultItems[0].tool_use_id); // C17 item 6: the real Claude Code error shape
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
      if (isTopLevel(e) && isGenuinePrompt(e)) {
        turnTools = [];
        turnSlashCommands = [];
        const slash = slashCommandName(e);
        if (slash) {
          slashCommands.push(slash);
          turnSlashCommands.push(slash);
        }
      }
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
          topLevel, // FH-10: a sub-agent's (sidechain) call never activates the parent's flow
        };
        tools.push(tool);
        if (topLevel) turnTools.push(tool);
        if ((c.name === 'Bash' || c.name === 'PowerShell') && c.input?.command) {
          const command = String(c.input.command);
          commands.push(command);
          commandIds.push(tool.id);
          if (command.length > SHELL_ANALYSIS_MAX) opaqueShellIds.push(tool.id); // R3-FH-2: unread, may write
          else for (const target of shellWriteTargets(command)) { edits.push(target); editIds.push(tool.id); } // FH-1
        }
        if (['Edit', 'Write', 'MultiEdit'].includes(c.name) && c.input?.file_path) {
          edits.push(String(c.input.file_path));
          editIds.push(tool.id);
        }
      }
    }
  }
  return {
    tools, commands, commandIds, edits, editIds, opaqueShellIds, lastText, raw, results, receipts, stringResults,
    completions, turnTools, lastRecordText, resultPos, lastTopTextPos, slashCommands, turnSlashCommands,
  };
}

// Did this session (possibly) edit a production source file? A recognised write of one, or (R3-FH-2) a shell
// command too long to read, which is never evidence but may have written source, so Stop keeps the flow's
// obligations for it.
export function sourceEdited(trace, req, cwd) {
  return anySourceFile(trace.edits, req, cwd) || (trace.opaqueShellIds || []).length > 0;
}

// Did the call with this tool_use id fail? Three shapes count (C6, amended by C17 item 6):
//   - an object toolUseResult with a non-empty `error` (the launch-receipt shape);
//   - a string toolUseResult: the shape real Claude Code session files record for a failed call (a
//     successful Skill, Agent or Workflow result has an object toolUseResult, or none);
//   - every correlated tool_result has is_error true (one non-error result clears it).
// A call with no id, or with no recorded result, is not errored: it still counts.
function receiptHasError(trace, id) {
  const rec = trace.receipts?.get(id);
  if (rec != null && rec.error != null && rec.error !== '') return true;
  if (trace.stringResults?.has(id)) return true;
  const res = trace.results?.get(id);
  return res != null && !res.nonError;
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

// D7: did a slash-command start in `names` name the skill exactly (X or agentic-sdlc:X)?
function slashStarted(names, marker) {
  return (names || []).some((name) => isExactName(name, marker));
}

// Flows whose activeWhen.skill marker IS the skill of a real Skill tool_use (exact name, C6): a
// dispatch-strategy call whose args mention feature-build activates nothing. An errored call
// (receiptHasError) still activates nothing; a call with no id or no result still counts. A slash-command
// start of that skill (D7) activates the flow the same way.
// FH-10: only a TOP-LEVEL Skill call activates a flow, the same scope as a slash-command start; a
// sub-agent's (sidechain or parent_tool_use_id) Skill call belongs to that sub-agent.
export function activeFlowNames(trace, req) {
  const out = [];
  const topTools = (trace.tools || []).filter((t) => t.topLevel !== false);
  for (const [name, flow] of Object.entries(req.flows || {})) {
    const marker = flow?.activeWhen?.skill;
    if (marker && (toolUsePresent(trace, { tool: 'Skill', exactName: marker }, topTools)
      || slashStarted(trace.slashCommands, marker))) out.push(name);
  }
  return out;
}

// FH-7: did a non-errored Skill call to `name` (exact name, X or agentic-sdlc:X) run in this transcript?
// The name inside another skill's args, an errored call, or a look-alike skill does not count.
export function skillInvoked(trace, name) {
  return toolUsePresent(trace, { tool: 'Skill', exactName: name });
}

// Ids of calls with this exact input that have no recorded result yet: at PreToolUse that is the current
// call when the runtime did not pass its tool_use_id (FH-1).
export function pendingCallIds(trace, toolInput) {
  const want = JSON.stringify(toolInput || {});
  const ids = new Set();
  for (const t of trace.tools || []) {
    if (t.id && t.inputStr === want && !trace.results?.has(t.id) && !trace.receipts?.has(t.id)) ids.add(t.id);
  }
  return ids;
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
// name, the activeFlowNames rule), or did its prompt start `name` as a slash command (D7)? A flow
// activated in an earlier turn does not count.
export function turnInvokesSkill(trace, name) {
  return toolUsePresent(trace, { tool: 'Skill', exactName: name }, trace.turnTools || [])
    || slashStarted(trace.turnSlashCommands, name);
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
  // FH-4: a flat plan pairs with the flat spec of the SAME work id (basename), never the first flat spec
  // in directory order; without one it stays unpaired and the validator resolves its own `spec:` link.
  const id = workIdOf(planFile);
  return specs.find((s) => perPackageRole(s, req) === null && workIdOf(s) === id) || null;
}

// Reduce an artifact path to a bare work-id base-name; reject traversal/empty. Shared with the Codex
// engine (codex-flow-evidence.mjs re-exports it), so both runtimes key work by the same id.
export function workIdOf(target) {
  const id = String(target).replace(/\\/g, '/').split('/').pop()
    .replace(/\.md$/i, '')
    .replace(/[^A-Za-z0-9._-]/g, '');
  if (!id || id.includes('..')) return null;
  return id;
}

// The role of a spec/plan artifact path ('spec' | 'plan'), flat root or per-package, else null.
function artifactRoleOf(path, req) {
  const norm = String(path).replace(/\\/g, '/');
  for (const role of ['spec', 'plan']) {
    const root = req.artifactRoots?.[role];
    if (root && norm.includes(root)) return role;
  }
  return perPackageRole(path, req);
}

// FH-4: this session's work ids - the base-name of every spec or plan this transcript wrote (by a
// Write/Edit tool or a shell write), the same rule as the Codex engine's activeWorkIds.
function sessionWorkIds(trace, req) {
  const ids = new Set();
  for (const e of trace.edits || []) {
    if (artifactRoleOf(e, req) === null) continue;
    const id = workIdOf(e);
    if (id) ids.add(id);
  }
  return ids;
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
  // FH-4: Stop validates only the artifacts of THIS session's work ids. An older valid package on disk
  // neither satisfies a session that wrote none nor hides this session's stub spec/plan.
  const ids = sessionWorkIds(trace, ctx.req);
  const files = listArtifacts(ctx.cwd, item.role, ctx.req).filter((f) => ids.has(workIdOf(f)));
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
      // R2-FH-1: one shape check per command per pattern, however many steps and flows ask.
      if (!(trace.runnerCache instanceof Map)) trace.runnerCache = new Map();
      const key = `${re.flags}/${re.source}`;
      if (!trace.runnerCache.has(key)) {
        trace.runnerCache.set(key, (trace.commands || []).some((c) => isRealRunnerInvocation(c, re)));
      }
      return trace.runnerCache.get(key);
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

// FH-2: a path inside the project is classified on its project-relative form, so a project that itself
// lives under a `tests/` or `test_*` folder is still gated. A path outside `cwd` (or no `cwd`) is used as is;
// `isSourceFile` may retry it with both sides resolved through links (`resolvedThroughLinks`).
function projectRelative(norm, cwd) {
  if (typeof cwd !== 'string' || !cwd) return norm;
  let base = cwd.replace(/\\/g, '/');
  while (base.length > 1 && base.endsWith('/')) base = base.slice(0, -1); // a loop, not a `/+$` regex
  const prefix = base.endsWith('/') ? base : `${base}/`;
  const fold = /^[A-Za-z]:/.test(base) ? (s) => s.toLowerCase() : (s) => s;
  return fold(norm).startsWith(fold(prefix)) ? norm.slice(prefix.length) : norm;
}

// R2-FH-4: `.` and `..` segments resolved lexically, so `tests/../src/app.py` (or a path that walks out of
// an artifact root) is classified as the file it names. A leading `..` that climbs above the start is
// kept, and an absolute path stays absolute. One pass over the segments.
function resolveDotSegments(norm) {
  const absolute = norm.startsWith('/');
  const out = [];
  for (const seg of norm.split('/')) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') {
      if (out.length && out[out.length - 1] !== '..') out.pop();
      else if (!absolute) out.push('..');
      continue;
    }
    out.push(seg);
  }
  return (absolute ? '/' : '') + out.join('/');
}

// FH-2: one folder can be named through a link (macOS `/var` is `/private/var`), and a runtime that sends
// no `cwd` leaves the hook's own working directory, which the OS gives resolved. A folder is resolved
// through its nearest existing ancestor, because the folder of a file about to be written may not exist
// yet. The work is bounded, because a hook that runs past its timeout is cancelled and the call goes
// ahead: a folder of more than LINK_MAX_SEGMENTS segments or LINK_MAX_LENGTH characters is not resolved,
// at most LINK_MAX_ANCESTORS folders are tried, and one process resolves at most LINK_MAX_RESOLVES
// folders. A lookup that stalls in the filesystem (a dead network mount) is not bounded, which is why
// `anySourceFile` reads every path as written before it resolves any (the byte-locked Claude pre-edit
// guard still checks its targets one by one). Null when nothing resolves.
const LINK_MAX_SEGMENTS = 128;
const LINK_MAX_LENGTH = 4096;
const LINK_MAX_ANCESTORS = 32;
const LINK_MAX_RESOLVES = 64;
const resolvedFolders = new Map();

function resolvedThroughLinks(folder) {
  if (resolvedFolders.has(folder)) return resolvedFolders.get(folder);
  const segs = folder.split('/');
  if (resolvedFolders.size >= LINK_MAX_RESOLVES || segs.length > LINK_MAX_SEGMENTS
      || folder.length > LINK_MAX_LENGTH) return null;
  let found = null;
  for (let keep = segs.length; keep > Math.max(0, segs.length - LINK_MAX_ANCESTORS); keep -= 1) {
    let head = segs.slice(0, keep).join('/');
    if (head === '') head = '/';
    else if (/^[A-Za-z]:$/.test(head)) head += '/';
    let real;
    try { real = realpathSync.native(head).replace(/\\/g, '/'); } catch { continue; }
    const rest = segs.slice(keep).join('/');
    found = rest ? `${real.endsWith('/') ? real.slice(0, -1) : real}/${rest}` : real;
    break;
  }
  resolvedFolders.set(folder, found);
  return found;
}

const isAbsolutePath = (norm) => norm.startsWith('/') || /^[A-Za-z]:\//.test(norm);

const hasSourceExtension = (norm, req) =>
  (req.sourceGlobs || []).includes((norm.split('.').pop() || '').toLowerCase());

function classifiedAsSource(norm, req) {
  for (const root of Object.values(req.artifactRoots || {})) {
    if (norm.includes(root)) return false;
  }
  if (/(^|\/)tests?\//.test(norm) || /(^|\/)test_|_test\.|\.test\.|\.spec\./.test(norm)) return false;
  return hasSourceExtension(norm, req);
}

// A path is a production source file: extension in sourceGlobs, NOT an artifact root, NOT a test.
// `resolveLinks: false` reads the path only as written.
export function isSourceFile(filePath, req, cwd, resolveLinks = true) {
  if (!filePath) return false;
  const base = typeof cwd === 'string' && cwd ? resolveDotSegments(cwd.replace(/\\/g, '/')) : null;
  const path = resolveDotSegments(String(filePath).replace(/\\/g, '/'));
  const norm = projectRelative(path, base);
  if (classifiedAsSource(norm, req)) return true;
  if (!resolveLinks) return false;
  // FH-2: a path that is not under `cwd` as written, and reads as a test or an artifact on its absolute
  // form, is retried with its folder and `cwd` resolved through links. The retry can only make a path a
  // source file, never the reverse, so a link cannot hide a source edit; the file name is kept as written.
  if (norm !== path || !base || !isAbsolutePath(path) || !hasSourceExtension(path, req)) return false;
  const cut = path.lastIndexOf('/');
  const realBase = resolvedThroughLinks(base);
  const realFolder = realBase && resolvedThroughLinks(path.slice(0, cut) || '/');
  if (!realFolder) return false;
  const realPath = `${realFolder.endsWith('/') ? realFolder.slice(0, -1) : realFolder}/${path.slice(cut + 1)}`;
  const relative = projectRelative(realPath, realBase);
  return relative !== realPath && classifiedAsSource(relative, req);
}

// Any of `paths` is a production source file. Every path is read as written before any link is
// resolved, so a lookup that stalls on one path cannot keep a later source path from being found.
export function anySourceFile(paths, req, cwd) {
  const list = paths || [];
  return list.some((p) => isSourceFile(p, req, cwd, false)) || list.some((p) => isSourceFile(p, req, cwd));
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
