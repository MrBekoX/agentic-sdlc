// Shared secret-scanning utilities (used by the hooks).
// NOTE: No real secret values are EMBEDDED here; only generic patterns.
// Reporting never prints a real value, only a label + line number.

// Placeholder / safe indicators for the value (RHS) — a match is not counted as a finding.
const PLACEHOLDER = /(\*\*\*|masked|example|change[_-]?me|your[_-]|placeholder|dummy|x{4,}|\$\{|<|>|env\(|process\.env|getenv|user-secrets)/i;

export function looksPlaceholder(s) {
  return !s || PLACEHOLDER.test(String(s));
}

// Blocking (high-confidence) patterns.
export const HIGH = [
  { label: 'private-key', re: /-----BEGIN[A-Z0-9 ]*PRIVATE KEY-----/ },
  { label: 'aws-access-key-id', re: /\bAKIA[0-9A-Z]{16}\b/ },
  // Password=...  veya  PASSWORD: "..."  (connection string / compose / env)
  { label: 'password-literal', re: /\b(?:password|pwd|passwd|sa_password|mssql_sa_password)\s*[:=]\s*["']?([^;"'\s]{6,})/i, valueGroup: 1 },
  // JSON credential:  "...Key|Secret|Password|Token|Credential...": "long-value" (>=16 chars)
  { label: 'json-credential', re: /"[^"]*(?:password|secret|key|token|credential|signing)[^"]*"\s*:\s*"([^"]{16,})"/i, valueGroup: 1 },
];

// Warning (broader) patterns.
export const BROAD = [
  ...HIGH,
  { label: 'assigned-secret', re: /\b(?:api[_-]?key|apikey|secret|access[_-]?token|client[_-]?secret|auth[_-]?token)\b\s*[:=]\s*["']?([A-Za-z0-9_\-.]{16,})/i, valueGroup: 1 },
  { label: 'bearer-token', re: /\bbearer\s+[A-Za-z0-9._\-]{20,}/i },
];

// Scans text line by line; at most one finding per line.
export function scanLines(text, patterns) {
  const out = [];
  const lines = String(text ?? '').split(/\r?\n/);
  lines.forEach((line, i) => {
    for (const p of patterns) {
      p.re.lastIndex = 0;
      const m = p.re.exec(line);
      if (!m) continue;
      const val = p.valueGroup ? m[p.valueGroup] : m[0];
      if (looksPlaceholder(val)) continue;
      out.push({ line: i + 1, label: p.label });
      break;
    }
  });
  return out;
}

// Read the full JSON from stdin (hook input).
export async function readStdin() {
  if (process.stdin.isTTY) return '';
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}
