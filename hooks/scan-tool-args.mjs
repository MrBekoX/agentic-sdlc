// PreToolUse (any tool) — scans every string in a tool call's arguments for a high-confidence secret
// and DENIES the call on a finding. Wired on Google Antigravity (agy) through agy-launch.mjs for the
// tools that neither run a command nor write a file (send_message, invoke_subagent, define_subagent,
// schedule, swarm, call_mcp_tool, search_web, ask_question and any tool agy adds later); the command
// guards and scan-write.mjs cover the others. A secret in such an argument leaves the machine (a
// message, a subagent prompt, an MCP server, a web query) or is stored in a definition, and agy
// records it in the transcript either way.
//
// Input: {tool_name, tool_input} on stdin, as the other shared guards read it. Output: nothing when
// clean; otherwise a PreToolUse deny naming the rule labels and the argument paths, never the value
// (a key that is not a plain name is reported by its position, `<key N>`).
// Arguments over MAX_TEXT characters or nested deeper than MAX_DEPTH cannot be scanned in bounded
// time and are denied too. The per-line `agentic-sdlc:allow-secret` marker is honoured, as in every
// other scan.
import { HIGH, scanLines, readStdin } from './secret-patterns.mjs';
import { emitHookResult } from './hook-output.mjs';

const MAX_TEXT = 4 * 1024 * 1024;
const MAX_DEPTH = 64;

class TooLarge extends Error {}

// The path segment reported for an object key. A key is printed only when it is a plain short name
// that no HIGH rule matches; any other key (a token used as a key, or odd text) is reported by its
// position, so a deny reason never echoes a secret.
function segment(key, index) {
  if (/^[A-Za-z_][A-Za-z0-9_-]{0,63}$/.test(key) && scanLines(key, HIGH).length === 0) return key;
  return `<key ${index + 1}>`;
}

// Every string leaf as { path, text }. Each object key is a leaf of its own whatever its value type,
// and a key also travels with its string value as `"key": "value"`, so the JSON credential rule sees
// the key name, and the bare value is scanned too.
function leaves(value, path, depth, out, budget) {
  if (depth > MAX_DEPTH) throw new TooLarge('nested too deeply');
  if (typeof value === 'string') {
    budget.left -= value.length;
    if (budget.left < 0) throw new TooLarge('too large');
    out.push({ path, text: value });
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, i) => leaves(item, `${path}[${i}]`, depth + 1, out, budget));
    return;
  }
  if (value && typeof value === 'object') {
    Object.entries(value).forEach(([key, item], index) => {
      budget.left -= key.length;
      if (budget.left < 0) throw new TooLarge('too large');
      const name = segment(key, index);
      const at = path ? `${path}.${name}` : name;
      out.push({ path: at, text: key });
      if (typeof item === 'string') {
        budget.left -= key.length + item.length;
        if (budget.left < 0) throw new TooLarge('too large');
        out.push({ path: at, text: `"${key}": "${item}"` });
      }
      leaves(item, at, depth + 1, out, budget);
    });
  }
}

function deny(reason) {
  emitHookResult({
    systemMessage: reason,
    hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: reason },
  }, 'PreToolUse');
}

const raw = await readStdin();
let input;
try { input = JSON.parse(raw || '{}'); } catch { input = undefined; }
if (!input || typeof input !== 'object' || Array.isArray(input)) {
  deny('agentic-sdlc: the tool-argument secret scan could not read the hook input; the call was not run.');
  process.exit(0);
}
const tool = typeof input.tool_name === 'string' && input.tool_name ? input.tool_name : 'tool';
const found = [];
try {
  leaves(input.tool_input === undefined ? {} : input.tool_input, '', 0, found, { left: MAX_TEXT });
} catch (error) {
  if (!(error instanceof TooLarge)) throw error;
  deny(`agentic-sdlc: the ${tool} arguments are ${error.message} to scan for secrets; the call was not run.`);
  process.exit(0);
}
const labels = new Set();
const paths = new Set();
for (const leaf of found) {
  for (const finding of scanLines(leaf.text, HIGH)) {
    labels.add(finding.label);
    paths.add(leaf.path || '(value)');
  }
}
if (labels.size) {
  deny(`⚠️ secret scan: possible secret in the ${tool} arguments (${[...labels].join(', ')}; at ${[...paths].join(', ')}). `
    + 'The call was not run. Do not paste the value; refer to it by name (an environment variable) instead (contract 06 — security).');
}
process.exit(0);
