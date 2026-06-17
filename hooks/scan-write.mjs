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
  process.stdout.write(JSON.stringify({
    systemMessage: `⚠️ secret scan: possible secret written → ${file} (${labels}). Mask the value / move it to env (contract 06 — security).`,
  }));
}

process.exit(0);
