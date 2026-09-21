// PostToolUse (Write|Edit|MultiEdit) — scans the WRITTEN/CHANGED text for secrets; WARNS (does not block).
// Only scans the new/changed text -> existing secrets don't re-warn on every edit.
import { readFileSync } from 'node:fs';
import { BROAD, scanLines, readStdin } from './secret-patterns.mjs';

// These paths are not scanned (the hooks themselves, vcs internals, deps).
// Path is normalized (backslash -> slash); matches relative and absolute paths via (^|/).
const SKIP = [
  /(^|\/)hooks\//i,
  /(^|\/)\.git\//i,
  /node_modules/i,
];

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { /* ignore */ }
const ti = input?.tool_input || {};
const file = String(ti.file_path || '');
const normFile = file.replace(/\\/g, '/');

if (!file || SKIP.some((re) => re.test(normFile))) process.exit(0);

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
  // Emit on BOTH channels, deliberately. `systemMessage` is shown to the USER; ZCode's hook
  // protocol has no such field and ignores unknown fields, so on ZCode this warning was
  // serialized into nothing — and this is the only PostToolUse hook wired there, so a secret
  // written to disk produced no observable output at all.
  // `hookSpecificOutput.additionalContext` is injected into the MODEL's context (Claude Code
  // documents this for PreToolUse and PostToolUse). That is a real behavior change on Claude
  // Code, not an inert addition: the model now also sees that it wrote a secret, which is the
  // half of the audience that can actually fix it. The deny paths of the sibling command guards
  // already ship this same dual shape.
  // The event name is hard-coded because this guard is wired to exactly one event on every
  // runtime that wires it (PostToolUse, in hooks-claude.json and hooks-zcode.json). Echoing a
  // runtime-supplied string into a field that must match the firing event would turn a constant
  // that is always right into a value that is right only when the payload is honest.
  process.stdout.write(JSON.stringify({
    systemMessage: msg,
    hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: msg },
  }));
}

process.exit(0);
