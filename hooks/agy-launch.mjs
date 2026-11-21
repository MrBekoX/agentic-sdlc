// Google Antigravity (agy) hook adapter. Shared guard scripts keep their Claude/Codex stdin and
// stdout; this process is the only agy-specific translation. It locates a sibling handler from its
// own file URL, maps agy's hook payload (`toolCall.name` / `toolCall.args`, agy 1.5.14 live capture
// 2026-11-21) onto the fields those handlers read, and maps their answer onto agy's hook output.
//
// agy runs the wired command with `sh -c` (`cmd /c` on Windows) in the folder holding hooks.json,
// which is the package root, so the wire names this file as `./hooks/agy-launch.mjs`. The handler
// path is never taken from the payload, and payload text never reaches a shell: the handler is
// started with process.execPath and an argv array, and the payload travels on its stdin.
//
// Output contract: exactly one JSON object on stdout and exit code 0, always. A PreToolUse guard
// that cannot answer (crash, timeout, unreadable answer, unreadable tool call) denies the tool call.
// agy blocked the call on exit status 2 and on invalid JSON from a PreToolUse hook (one probe each,
// 2026-11-21; other exit codes are unverified), but that is not relied on here. A PreToolUse answer
// always names a decision: agy 1.5.14 denied a call whose hook printed `{}` (probe 2026-11-21), so
// "nothing to say" is `{"decision":"allow"}`. SessionStart and Stop failures answer `{}`.
import { spawn } from 'node:child_process';
import { readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
// Handler -> the agy tool names it guards. The matchers in hooks.json select the same tools.
const HANDLER_TOOLS = {
  'scan-commit.mjs': ['run_command'],
  'destructive-command-guard.mjs': ['run_command'],
  'branch-guard.mjs': ['run_command'],
  'scan-write.mjs': ['write_file', 'edit_file'],
};
const EVENT_HANDLERS = {
  PreToolUse: new Set(Object.keys(HANDLER_TOOLS)),
  SessionStart: new Set(['session-start.mjs']),
  Stop: new Set(['worktree-scan.mjs']),
};
const DEFAULT_HANDLER_TIMEOUT_SECONDS = 18;
const BLOCK = /^(true|1|yes)$/i.test(String(process.env.AGENTIC_WORKTREE_SCAN_BLOCK || ''));

const AGY_NOTE = [
  'Antigravity adapter: there is no Skill tool and no Claude Workflow tool.',
  'Activate a house skill with /<skill-name> or by reading its installed skills/<skill-name>/SKILL.md with read_file.',
  'Delegate a named role to the bundled agents of this plugin with invoke_subagent. agy has no grep or glob tool,',
  'so give a read-only role the explicit list of files it must read.',
  'Start with /using-agentic-sdlc. Use /agentic-sdlc-pipeline only for the full SDLC envelope.',
].join(' ');

class Unreadable extends Error {}

function flag(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? String(process.argv[index + 1] || '') : '';
}

function handlerTimeoutMs() {
  const seconds = Number(flag('--handler-timeout'));
  return (Number.isFinite(seconds) && seconds > 0 ? seconds : DEFAULT_HANDLER_TIMEOUT_SECONDS) * 1000;
}

function text(value) {
  return typeof value === 'string' ? value : '';
}

// The payload `cwd` is the agent's working directory, where its commands run by default; the first
// workspace path stands in when it is missing. With neither, the hook's own folder (the plugin root)
// is all that is left: SessionStart and Stop may use it, but a tool call judged there would be judged
// in the wrong folder, so commandCwd makes it Unreadable.
function payloadCwd(input) {
  if (text(input.cwd)) return input.cwd;
  const roots = input.workspacePaths;
  if (Array.isArray(roots) && text(roots[0])) return roots[0];
  return '';
}

function projectCwd(input) {
  return payloadCwd(input) || process.cwd();
}

// The folder a run_command runs in. The live capture sent no `Cwd` argument (CommandLine,
// WaitMsBeforeAsync, toolSummary; agy 1.5.14, 2026-11-21), but the web docs list one. When it is
// sent the command runs there, so the guards check that folder: a relative one resolves against the
// payload `cwd`, and one that is not a string or names no folder is Unreadable (the call is denied)
// rather than judged in another folder.
function commandCwd(input, call) {
  const base = payloadCwd(input);
  if (!base) throw new Unreadable('the hook payload names no working directory');
  const args = call.args;
  if (call.name !== 'run_command' || !Object.prototype.hasOwnProperty.call(args, 'Cwd')) return base;
  if (typeof args.Cwd !== 'string' || !args.Cwd) throw new Unreadable('run_command Cwd is not a folder name');
  const target = resolve(base, args.Cwd);
  let folder = false;
  try {
    folder = statSync(target).isDirectory();
  } catch {
    folder = false;
  }
  if (!folder) throw new Unreadable('run_command Cwd names no folder');
  return target;
}

// A folder that no longer exists would make the spawn itself fail and lock every command out, so
// the launcher's own folder stands in for it.
function runnableCwd(cwd) {
  try {
    if (statSync(cwd).isDirectory()) return cwd;
  } catch {
    // fall through
  }
  return process.cwd();
}

// The tool call of a PreToolUse payload, or Unreadable. A matched hook with no readable tool call
// cannot be checked, so it must not be allowed by default.
function toolCallOf(input) {
  const call = input.toolCall;
  if (!call || typeof call !== 'object' || Array.isArray(call) || !text(call.name)) {
    throw new Unreadable('the hook payload has no readable toolCall');
  }
  const args = call.args === undefined ? {} : call.args;
  if (!args || typeof args !== 'object' || Array.isArray(args)) {
    throw new Unreadable('the tool call arguments are not an object');
  }
  return { name: call.name, args };
}

// The argument a guard must read, or Unreadable: a missing or non-string value cannot be checked,
// so it must not reach the guard as an empty string and be allowed.
function stringArg(args, key, tool) {
  if (typeof args[key] !== 'string') throw new Unreadable(`the ${tool} argument ${key} is not a string`);
  return args[key];
}

function translateTool(call, cwd) {
  const { name, args } = call;
  if (name === 'run_command') {
    // Bash selects the shared guards' union of POSIX and PowerShell readings.
    const command = stringArg(args, 'CommandLine', name);
    return { hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command }, cwd };
  }
  if (name === 'write_file') {
    const tool_input = { file_path: stringArg(args, 'Path', name), content: stringArg(args, 'Content', name) };
    return { hook_event_name: 'PreToolUse', tool_name: 'Write', tool_input, cwd };
  }
  if (name === 'edit_file') {
    const tool_input = { file_path: stringArg(args, 'Path', name), new_string: stringArg(args, 'Replacement', name) };
    return { hook_event_name: 'PreToolUse', tool_name: 'Edit', tool_input, cwd };
  }
  return undefined;
}

function messageOf(payload) {
  const specific = payload.hookSpecificOutput && typeof payload.hookSpecificOutput === 'object'
    ? payload.hookSpecificOutput : {};
  return text(specific.permissionDecisionReason) || text(payload.reason) || text(payload.systemMessage)
    || text(specific.additionalContext);
}

function denied(handler, why) {
  return { decision: 'deny', reason: `agentic-sdlc: the ${handler} guard could not check this tool call (${why}); it was not run.` };
}

function translatePreToolUse(handler, payload) {
  const specific = payload.hookSpecificOutput && typeof payload.hookSpecificOutput === 'object'
    ? payload.hookSpecificOutput : {};
  const decision = text(specific.permissionDecision) || text(payload.decision);
  const message = messageOf(payload);
  if (decision === 'deny' || decision === 'block') {
    return { decision: 'deny', reason: message || `agentic-sdlc: ${handler} denied this tool call.` };
  }
  // A warning (the write scanner, a skipped-scan notice) lets the call run and tells the agent why.
  // agy documents "allow" as auto-approving the call; in agy 1.5.14 probes (2026-11-21) it did not
  // override a user `permissions.ask` or `permissions.deny` rule, and `{}` is not neutral (it denies).
  return message ? { decision: 'allow', reason: message } : { decision: 'allow' };
}

function translateSessionStart(payload) {
  const specific = payload.hookSpecificOutput && typeof payload.hookSpecificOutput === 'object'
    ? payload.hookSpecificOutput : {};
  const context = text(specific.additionalContext);
  const message = context ? `${context}\n${AGY_NOTE}` : AGY_NOTE;
  return { injectSteps: [{ systemMessage: { systemMessage: message } }] };
}

function translateStop(input, payload) {
  // Only a blocking scan with a finding keeps the agent going, and never twice in one turn.
  if (!BLOCK || input.continuationActive === true) return {};
  if (text(payload.decision) !== 'block') return {};
  return { decision: 'continue', reason: messageOf(payload) || 'agentic-sdlc: the worktree scan found a problem.' };
}

function runHandler(handler, payload, cwd) {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(process.execPath, [join(HERE, handler)], {
        cwd, env: process.env, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true,
      });
    } catch (error) {
      resolve({ code: 1, stdout: '', stderr: String((error && error.message) || error), timedOut: false });
      return;
    }
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, handlerTimeoutMs());
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.stdin.on('error', () => {});
    child.on('error', (error) => {
      clearTimeout(timer);
      resolve({ code: 1, stdout: '', stderr: String((error && error.message) || error), timedOut });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ code: code == null ? 1 : code, stdout, stderr, timedOut });
    });
    child.stdin.end(JSON.stringify(payload));
  });
}

function emit(value) {
  process.stdout.write(JSON.stringify(value));
}

function fallback(event, handler, why) {
  return event === 'PreToolUse' ? denied(handler || 'agy hook', why) : {};
}

async function main() {
  const event = flag('--event');
  const handler = flag('--handler');
  if (!EVENT_HANDLERS[event]) {
    process.stderr.write('error=agy_event_unwired\n');
    return {};
  }
  if (!EVENT_HANDLERS[event].has(handler)) {
    process.stderr.write('error=agy_handler_rejected\n');
    return fallback(event, 'agy hook', 'handler not allowed');
  }
  let input;
  try {
    const raw = readFileSync(0, 'utf8');
    input = raw.trim() ? JSON.parse(raw) : {};
  } catch {
    input = undefined;
  }
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    process.stderr.write('error=agy_hook_input_invalid\n');
    return fallback(event, handler, 'unreadable hook input');
  }

  let translated;
  let cwd;
  if (event === 'PreToolUse') {
    let call;
    try {
      call = toolCallOf(input);
    } catch (error) {
      if (!(error instanceof Unreadable)) throw error;
      return denied(handler, error.message);
    }
    if (!HANDLER_TOOLS[handler].includes(call.name)) return { decision: 'allow' };
    try {
      cwd = commandCwd(input, call);
      translated = translateTool(call, cwd);
    } catch (error) {
      if (!(error instanceof Unreadable)) throw error;
      return denied(handler, error.message);
    }
  } else {
    cwd = projectCwd(input);
    translated = event === 'Stop'
      // The conversation id is the worktree scan's session key for its per-session dedup.
      ? { hook_event_name: 'Stop', cwd, stop_hook_active: input.continuationActive === true,
        session_id: text(input.conversationId) }
      : { hook_event_name: 'SessionStart', cwd };
  }

  const result = await runHandler(handler, translated, runnableCwd(cwd));
  if (result.stderr) process.stderr.write(result.stderr.endsWith('\n') ? result.stderr : `${result.stderr}\n`);
  if (result.timedOut) {
    process.stderr.write(`error=agy_handler_timeout:${handler}\n`);
    return fallback(event, handler, 'timed out');
  }
  if (result.code !== 0) {
    process.stderr.write(`error=agy_handler_failed:${handler}\n`);
    return fallback(event, handler, `exit ${result.code}`);
  }
  if (!result.stdout.trim()) {
    // Empty output is the guards' normal "nothing to say".
    if (event === 'PreToolUse') return { decision: 'allow' };
    return event === 'SessionStart' ? translateSessionStart({}) : {};
  }
  let answer;
  try {
    answer = JSON.parse(result.stdout);
  } catch {
    answer = undefined;
  }
  if (!answer || typeof answer !== 'object' || Array.isArray(answer)) {
    process.stderr.write(`error=agy_handler_output_invalid:${handler}\n`);
    return fallback(event, handler, 'unreadable answer');
  }
  if (event === 'PreToolUse') return translatePreToolUse(handler, answer);
  if (event === 'SessionStart') return translateSessionStart(answer);
  return translateStop(input, answer);
}

let out;
try {
  out = await main();
} catch {
  process.stderr.write('error=agy_launcher_failed\n');
  out = fallback(flag('--event'), flag('--handler'), 'launcher error');
}
emit(out);
process.exit(0);
