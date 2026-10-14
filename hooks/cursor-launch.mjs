// Cursor hook adapter. Shared guard scripts keep their Claude/Codex stdin and stdout.
// This process is the only Cursor-specific translation: it locates a sibling handler
// from its own file URL, maps Cursor's documented hook payload onto the fields those
// handlers already read, and maps their result onto Cursor's documented output.
//
// The installed directory is this file's parent, not the process cwd. Cursor's stop
// hook runs in the project, and other plugin hooks may run in the plugin directory
// (Cursor staff, forum, 2026-04-13). CURSOR_PLUGIN_ROOT is only how the manifest
// finds this file; handler paths are not taken from the shell command.
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const HANDLERS = new Set([
  'scan-commit.mjs',
  'destructive-command-guard.mjs',
  'branch-guard.mjs',
  'scan-write.mjs',
  'flow-order-guard.mjs',
  'session-start.mjs',
  'worktree-scan.mjs',
]);

const CURSOR_NOTE = [
  'Cursor adapter: invoke a house skill with /<skill-name> or by reading the installed skills/<skill-name>/SKILL.md.',
  'There is no Claude Workflow tool. Spec and plan use the author -> critic -> revise adapter and the roles in agents/.',
  'Start with /using-agentic-sdlc. Use /agentic-sdlc-pipeline only for the full SDLC envelope.',
].join(' ');

function flag(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? String(process.argv[index + 1] || '') : '';
}

function readStdin() {
  return readFileSync(0, 'utf8');
}

function projectCwd(input) {
  if (typeof input.cwd === 'string' && input.cwd) return input.cwd;
  if (typeof process.env.CURSOR_PROJECT_DIR === 'string' && process.env.CURSOR_PROJECT_DIR) {
    return process.env.CURSOR_PROJECT_DIR;
  }
  const roots = input.workspace_roots;
  if (Array.isArray(roots) && typeof roots[0] === 'string' && roots[0]) return roots[0];
  return process.cwd();
}

function toolInput(input) {
  return input.tool_input && typeof input.tool_input === 'object' ? input.tool_input : {};
}

function filePath(input) {
  const nested = toolInput(input);
  return String(nested.file_path || nested.path || nested.target_file || input.file_path || '');
}

function translateIn(event, input) {
  const cwd = projectCwd(input);
  if (event === 'beforeShellExecution') {
    // Bash selects the shared guard's union of POSIX and PowerShell readings.
    return {
      tool_name: 'Bash',
      tool_input: { command: String(input.command || '') },
      cwd,
    };
  }
  if (event === 'preToolUse') {
    const nested = toolInput(input);
    const edits = Array.isArray(nested.edits) ? nested.edits : (Array.isArray(input.edits) ? input.edits : undefined);
    const content = typeof nested.content === 'string'
      ? nested.content
      : (typeof nested.contents === 'string' ? nested.contents : undefined);
    return {
      tool_name: String(input.tool_name || 'Write'),
      tool_input: { ...nested, file_path: filePath(input), content, new_string: nested.new_string, edits },
      cwd,
      transcript_path: input.transcript_path,
    };
  }
  if (event === 'stop') {
    return {
      ...input,
      cwd,
      session_id: input.session_id || input.conversation_id || '',
    };
  }
  return { ...input, cwd };
}

function messageOf(payload) {
  const specific = payload.hookSpecificOutput || {};
  return String(
    specific.permissionDecisionReason
    || specific.additionalContext
    || payload.systemMessage
    || payload.reason
    || '',
  );
}

function permission(decision, message) {
  const out = { permission: decision };
  if (message) {
    out.user_message = message;
    out.agent_message = message;
  }
  return out;
}

function translateOut(event, handler, payload) {
  if (!payload || typeof payload !== 'object') return event === 'sessionStart' ? { additional_context: CURSOR_NOTE } : {};
  const specific = payload.hookSpecificOutput || {};
  const decision = specific.permissionDecision || payload.decision || '';
  const message = messageOf(payload);
  if (event === 'sessionStart') {
    const text = String(specific.additionalContext || payload.additional_context || '');
    return { additional_context: text ? `${text}\n${CURSOR_NOTE}` : CURSOR_NOTE };
  }
  if (event === 'stop') {
    // Cursor's documented stop output is followup_message only. An advisory
    // systemMessage must not become a follow-up, or the agent turn restarts.
    if (decision === 'block' && message) return { followup_message: message };
    return {};
  }
  if (event === 'beforeShellExecution' || event === 'preToolUse') {
    if (decision === 'deny') return permission('deny', message);
    // The shared write scanner only warns. Cursor's preToolUse channel that
    // reaches the agent is permission, and afterFileEdit documents no output.
    if (event === 'preToolUse' && handler === 'scan-write.mjs' && message) return permission('deny', message);
    if (event === 'beforeShellExecution' && message) return permission('ask', message);
    return permission('allow', '');
  }
  return {};
}

function allow(event) {
  if (event === 'beforeShellExecution' || event === 'preToolUse') return permission('allow', '');
  if (event === 'sessionStart') return { additional_context: CURSOR_NOTE };
  return {};
}

function emit(value) {
  process.stdout.write(JSON.stringify(value));
}

function runHandler(handler, event, payload, cwd) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [join(HERE, handler)], {
      cwd,
      env: process.env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('error', (error) => {
      resolve({ code: 1, stdout: '', stderr: String(error && error.message || error) });
    });
    child.on('close', (code) => resolve({ code: code == null ? 1 : code, stdout, stderr }));
    child.stdin.end(JSON.stringify(payload));
  });
}

const event = flag('--event');
const handler = flag('--handler');
let input = {};
try {
  const raw = readStdin();
  input = raw.trim() ? JSON.parse(raw) : {};
} catch {
  process.stderr.write('error=cursor_hook_input_invalid\n');
  emit(allow(event));
  process.exit(0);
}

if (!HANDLERS.has(handler)) {
  process.stderr.write('error=cursor_handler_rejected\n');
  emit(allow(event));
  process.exit(0);
}

const translated = translateIn(event, input);
const result = await runHandler(handler, event, translated, projectCwd(input));
if (result.stderr) process.stderr.write(result.stderr.endsWith('\n') ? result.stderr : `${result.stderr}\n`);
if (result.code !== 0) {
  process.stderr.write(`error=cursor_handler_failed:${handler}\n`);
  emit(allow(event));
  process.exit(0);
}
if (!result.stdout.trim()) {
  emit(allow(event));
  process.exit(0);
}
try {
  emit(translateOut(event, handler, JSON.parse(result.stdout)));
} catch {
  process.stderr.write('error=cursor_handler_output_invalid\n');
  emit(allow(event));
}
process.exit(0);
