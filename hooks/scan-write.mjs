// PostToolUse (Write|Edit|MultiEdit) — scans the WRITTEN/CHANGED text for secrets; WARNS (does not block).
// Only scans the new/changed text -> existing secrets don't re-warn on every edit.
import { readFileSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { BROAD, scanLines, readStdin } from './secret-patterns.mjs';
import { emitHookResult } from './hook-output.mjs';

// These paths are not scanned (vcs internals, deps).
// Path is normalized (backslash -> slash); matches relative and absolute paths via (^|/).
const SKIP = [
  /(^|\/)\.git\//i,
  /node_modules/i,
];

// This plugin's own guard sources carry secret-shaped pattern text, so they are exempt - but only
// THIS directory, resolved from the module location. A name match on `hooks/` also exempted every
// user folder called hooks (React `src/hooks/`, deploy hooks, webhooks/hooks).
const OWN_HOOKS = dirname(fileURLToPath(import.meta.url));
function isOwnHookSource(file, cwd) {
  const rel = relative(OWN_HOOKS, resolve(cwd, file));
  return rel !== '' && !rel.startsWith('..') && !isAbsolute(rel);
}

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { /* ignore */ }
const ti = input?.tool_input || {};
const file = String(ti.file_path || '');
const normFile = file.replace(/\\/g, '/');
const cwd = typeof input?.cwd === 'string' && input.cwd ? input.cwd : process.cwd();

if (!file || SKIP.some((re) => re.test(normFile)) || isOwnHookSource(file, cwd)) process.exit(0);

// Collect only the new/changed text.
let text = '';
if (typeof ti.new_string === 'string') text = ti.new_string;              // Edit
else if (Array.isArray(ti.edits)) text = ti.edits.map((e) => e?.new_string || '').join('\n'); // MultiEdit
else if (typeof ti.content === 'string') text = ti.content;              // Write
else {
  try { text = readFileSync(file, 'utf8'); } catch { /* ignore */ }      // fallback
}

const findings = scanLines(text, BROAD);
if (findings.length) {
  const labels = [...new Set(findings.map((f) => f.label))].join(', ');
  const msg = `⚠️ secret scan: possible secret written → ${file} (${labels}). Mask the value / move it to env (contract 06 — security).`;
  // Emit on BOTH channels, deliberately. `systemMessage` is shown to the USER on Claude Code;
  // `hookSpecificOutput.additionalContext` is injected into the MODEL's context (Claude Code
  // documents this for PreToolUse and PostToolUse) — a deliberate behavior change there, not an
  // inert addition: the model now also sees that it wrote a secret, which is the half of the
  // audience that can actually fix it. The deny paths of the sibling command guards already ship
  // this same dual shape. Which channels reach a runtime is decided by emitHookResult
  // (hook-output.mjs): under ZCode only the documented hookSpecificOutput key is written, so the
  // payload is safe under either the lenient ("unknown fields are ignored", live 2026-10-08 doc)
  // or the strict ("any extra key fails validation", bundled diagnosing-hooks skill) reading.
  // The event name is hard-coded because this guard is wired to exactly one event on every
  // runtime that wires it (PostToolUse, in hooks-claude.json and hooks-zcode.json). Echoing a
  // runtime-supplied string into a field that must match the firing event would turn a constant
  // that is always right into a value that is right only when the payload is honest.
  emitHookResult({
    systemMessage: msg,
    hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: msg },
  }, 'PostToolUse');
}

process.exit(0);
