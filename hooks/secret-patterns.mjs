// Shared secret-scanning utilities (used by the hooks).
// NOTE: No real secret values are EMBEDDED here; only generic patterns.
// Reporting never prints a real value, only a label + line number.

// Placeholder / safe indicators for the value (RHS) — a match is not counted as a finding.
const PLACEHOLDER = /(\*\*\*|masked|example|change[_-]?me|your[_-]|placeholder|dummy|x{4,}|\$\{|<|>|env\(|process\.env|getenv|user-secrets)/i;

export function looksPlaceholder(s) {
  return !s || PLACEHOLDER.test(String(s));
}

// Blocking (high-confidence) patterns. Provider-prefix tokens are recognized by their fixed,
// vendor-published shapes (not a keyword on the line), so a bare `TOKEN = ghp_...` is blocked
// even with no password/secret keyword and no JSON wrapper.
export const HIGH = [
  { label: 'private-key', re: /-----BEGIN[A-Z0-9 ]*PRIVATE KEY-----/ },
  { label: 'aws-access-key-id', re: /\bAKIA[0-9A-Z]{16}\b/ },
  // GitHub: classic PAT/OAuth (ghp_/gho_/ghu_/ghs_/ghr_ + 36) and fine-grained (github_pat_ + 40+).
  { label: 'github-token', re: /\b(?:gh[posru]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,})\b/ },
  // Slack bot/user/app/refresh and app-level tokens.
  { label: 'slack-token', re: /\b(?:xox[baprs]|xapp)-[A-Za-z0-9-]{10,}/i },
  // Stripe secret / restricted keys (publishable pk_ is not a secret, so excluded).
  { label: 'stripe-key', re: /\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b/ },
  // Google API key.
  { label: 'google-api-key', re: /\bAIza[0-9A-Za-z_\-]{35}\b/ },
  // OpenAI secret / project key.
  { label: 'openai-key', re: /\bsk-(?:proj-)?[A-Za-z0-9]{20,}\b/ },
  // JWT: header.payload.signature, header+payload are base64url-encoded JSON objects -> 'eyJ'.
  { label: 'jwt', re: /\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/ },
  // Authorization: Bearer <token>. In HIGH (not just BROAD) so commits are blocked, not only warned.
  { label: 'bearer-token', re: /\bbearer\s+[A-Za-z0-9._\-]{20,}/i },
  // Password=...  veya  PASSWORD: "..."  (connection string / compose / env)
  { label: 'password-literal', re: /\b(?:password|pwd|passwd|sa_password|mssql_sa_password)\s*[:=]\s*["']?([^;"'\s]{6,})/i, valueGroup: 1 },
  // JSON credential:  "...Key|Secret|Password|Token|Credential...": "long-value" (>=16 chars)
  { label: 'json-credential', re: /"[^"]*(?:password|secret|key|token|credential|signing)[^"]*"\s*:\s*"([^"]{16,})"/i, valueGroup: 1 },
];

// Warning (broader) patterns.
export const BROAD = [
  ...HIGH,
  { label: 'assigned-secret', re: /\b(?:api[_-]?key|apikey|secret|access[_-]?token|client[_-]?secret|auth[_-]?token)\b\s*[:=]\s*["']?([A-Za-z0-9_\-.]{16,})/i, valueGroup: 1 },
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
