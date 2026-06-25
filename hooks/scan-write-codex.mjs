// PreToolUse (Codex: Bash + apply_patch) — blocks a high-confidence secret in newly written file
// content BEFORE the write lands. Codex has no Claude Write/Edit field shape; the write payload is
// in tool_input.command (a shell command or a V4A patch). We extract the literal added content from
// the recognized write forms and scan it. Fail-open on anything we can't reliably read.
// On error/unrecognized -> allow (emit nothing). The matched value is never available to this hook
// (scanLines returns only {line,label}), so it is never printed.
import { HIGH, scanLines, readStdin } from './secret-patterns.mjs';
import { extractWrittenContent } from './codex-write-signal.mjs';

const raw = await readStdin();
let input = {};
try { input = JSON.parse(raw || '{}'); } catch { process.exit(0); /* fail open */ }

try {
  const toolName = String(input?.tool_name || '');
  const command = input?.tool_input?.command;
  if (typeof command !== 'string' || !command) process.exit(0);

  const { addedContent, targets } = extractWrittenContent(toolName, command);
  // Scan whatever LITERAL content was extracted. Per-segment: a compound command with an
  // expansion-dependent sibling (parsed:false) still has its literal write segments scanned, so a
  // secret in a literal sibling is not waved through. Empty content (nothing literal to read,
  // unrecognized, over-cap, or a pure-expansion write) -> fail open.
  if (!addedContent) process.exit(0);

  const findings = scanLines(addedContent, HIGH);
  if (!findings.length) process.exit(0);

  const labels = [...new Set(findings.map((f) => f.label))].join(', ');
  const paths = (targets || []).filter(Boolean).slice(0, 5).join(', ');
  // Reason carries finding LABELS (+ optional target paths) only — never the matched value, and no
  // absolute source line (the only index is blob-relative, which would mislead).
  const reason =
    'Write blocked: possible secret in newly written content (values masked).\n' +
    `  • ${labels}` +
    (paths ? `\n  • target(s): ${paths}` : '') +
    '\n→ Move it to env / secret store and remove it from the write. If intentional/false-positive, disable temporarily via Codex hook controls.';

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: reason,
    },
    systemMessage: '🔒 secret scan: write blocked (possible secret).',
  }));
} catch {
  /* fail open: never block on an unexpected error */
}

process.exit(0);
