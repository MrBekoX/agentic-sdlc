// Shared secret-scanning utilities (used by the hooks).
// NOTE: No real secret values are EMBEDDED here; only generic patterns.
// Reporting never prints a real value, only a label + line number.

// ---------------------------------------------------------------------------------------------
// Placeholder handling. Two DIFFERENT problems, so two different mechanisms.
//
// The old code had one substring regex applied to whatever the pattern matched:
//   /(\*\*\*|masked|example|change[_-]?me|your[_-]|placeholder|dummy|x{4,}|\$\{|<|>|...)/i
// Nine of the eleven HIGH patterns carry no `valueGroup`, so the "value" it inspected was the
// ENTIRE vendor-shaped token — one that had already passed a strict, vendor-published shape test.
// Any such token containing `xxxx`, `example`, or a single `<` was discarded. Verified bypasses:
//   sk_test_xxxx…  ghp_xxxx…  password=MyRealSecretExample8412  "api_secret": "q7<Wm4…"   (agentic-sdlc:allow-secret)
//
// No mainstream scanner does this. gitleaks attaches its stopword list ONLY to the generic
// `generic-api-key` rule, never to the vendor rules in github.go / stripe.go, which gate on
// entropy instead; detect-secrets hard-disables its context heuristic for RegexBasedDetector
// plugins and anchors its template test to the first/last character; trufflehog applies keyword
// false-positive matching only to results it could NOT verify as live.
//
// So:
//  * captured values (password-literal / json-credential / assigned-secret) keep a placeholder
//    heuristic, but as ANCHORED whole-value predicates rather than substring probes;
//  * vendor-shaped tokens are never keyword-filtered. They are suppressed only when the token is
//    structurally DEGENERATE (a repeated or sequential run), which is the "pattern filter" from
//    Meli et al., "How Bad Can It Git?" (NDSS 2019), or when it is a known published doc sample.
// ---------------------------------------------------------------------------------------------

// A captured value that is wholly a template. Anchored on purpose: `<` occurring somewhere inside
// a real value must not suppress it, only a value that IS `<...>`.
const TEMPLATE_VALUE = [
  /^["']?<[^<>]*>["']?$/,                       // <your-password-here>
  /^["']?\$\{[^{}]*\}["']?$/,                   // ${DB_PASSWORD}
  /^["']?\$[A-Za-z_]\w*["']?$/,                 // $DB_PASSWORD
  /^["']?%[A-Za-z_]\w*%["']?$/,                 // %DB_PASSWORD%
  /^\*+$/,                                       // ******
  /^\*\*\*MASKED\*\*\*$/,
  /^["']?(?:process\.env|os\.environ|System\.getenv|getenv|env)\b/i,
  /^["']?(?:change[_-]?me|placeholder|dummy|todo|fixme|redacted|masked|secret_here)\b/i,
  /^["']?your[_-]?\w*\b/i,                      // your-client-secret-goes-here
  /^["']?x+["']?$/i,                            // xxxxxxxx
];

// Applies ONLY to a captured (user-authored) value. Never call this on a vendor-shaped token.
export function looksPlaceholder(s) {
  if (!s) return true;
  const v = String(s).trim();
  return TEMPLATE_VALUE.some((re) => re.test(v));
}

// Inline, per-line suppression. `gitleaks:allow` is honoured too so a repo already using that
// convention needs no second annotation.
const ALLOW_MARKER = /agentic-sdlc:allow-secret|gitleaks:allow/i;

// Published documentation samples, matched EXACTLY. An exact-value allowlist cannot suppress a
// class of tokens the way a substring rule can; this is the mechanism gitleaks uses for the
// octokit README sample and the Stripe docs keys.
const DOC_SAMPLES = new Set([
  'AKIAIOSFODNN7EXAMPLE',                        // AWS docs
  'AIzaSyDaGmWKa4JsXZ-HjGw7ISLn_3namBGewQe',     // Google docs
  'sk_test_4eC39HqLyjWDarjtT1zdp7dc',            // Stripe docs
]);

// Structural degeneracy: the token is a repeated or sequential run rather than a random one.
// This is what actually separates `ghp_xxxxxxxx…` (a doc placeholder) from a real token — the
// letters inside a token carry no meaning, its DISTRIBUTION does. Meli et al. use a run-length
// threshold of 4; we require the run to DOMINATE so a real token that merely contains a short
// run is untouched. Linear, single pass.
function isDegenerateToken(token) {
  const t = String(token);
  if (t.length < 12) return false;
  const freq = new Map();
  for (const c of t) freq.set(c, (freq.get(c) || 0) + 1);
  let max = 0;
  for (const n of freq.values()) if (n > max) max = n;
  if (max / t.length >= 0.7) return true;        // one character dominates (ghp_xxxx…, AKIAXXXX…)
  if (freq.size <= 2) return true;               // ABABAB…, 010101…
  let run = 1;
  let best = 1;
  for (let i = 1; i < t.length; i += 1) {
    const d = t.charCodeAt(i) - t.charCodeAt(i - 1);
    run = (d === 1 || d === -1) ? run + 1 : 1;   // ascending or descending
    if (run > best) best = run;
  }
  return best / t.length >= 0.6;                 // ABCDEFGHIJ… / ZYXWVUTS…
}

// Blocking (high-confidence) patterns. Provider-prefix tokens are recognized by their fixed,
// vendor-published shapes (not a keyword on the line), so a bare `TOKEN = ghp_...` is blocked
// even with no password/secret keyword and no JSON wrapper.
export const HIGH = [
  { label: 'private-key', re: /-----BEGIN[A-Z0-9 ]*PRIVATE KEY-----/ },
  // Vendor-prefix tokens: the LEFT anchor is `(?<![A-Za-z0-9])`, not `\b`, and there is no right
  // anchor. `\b` is a \w boundary and `_` is a \w character, so `\bghp_` never fires on the very
  // common `MYAPP_ghp_…` / `TOKEN_sk_live_…` env-var shape, and a trailing `\b` after a FIXED
  // length ({36}/{16}/{35}) drops the token whenever one more word character follows it — both
  // verified misses. gitleaks' vendor rules carry no boundary anchors at all for this reason;
  // the lookbehind is kept only to stop `sk-` matching inside a word such as `task-…`.
  { label: 'aws-access-key-id', re: /(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}/ },
  // GitHub: classic PAT/OAuth (ghp_/gho_/ghu_/ghs_/ghr_ + 36) and fine-grained (github_pat_ + 40+).
  { label: 'github-token', re: /(?<![A-Za-z0-9])(?:gh[posru]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,})/ },
  // Slack bot/user/app/refresh and app-level tokens.
  { label: 'slack-token', re: /(?<![A-Za-z0-9])(?:xox[baprs]|xapp)-[A-Za-z0-9-]{10,}/i },
  // Stripe secret / restricted keys (publishable pk_ is not a secret, so excluded).
  { label: 'stripe-key', re: /(?<![A-Za-z0-9])(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}/ },
  // Google API key.
  { label: 'google-api-key', re: /(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{35}/ },
  // OpenAI secret / project key.
  { label: 'openai-key', re: /(?<![A-Za-z0-9])sk-(?:proj-)?[A-Za-z0-9]{20,}/ },
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
    // Explicit per-line escape hatch. Documenting a bypass means writing the shape you are
    // documenting, so a scanner with no hatch fires on the very files that explain it — and a
    // guard that flags ordinary work gets switched off, which costs more than it saves. This is
    // the mechanism the mature scanners ship (detect-secrets `pragma: allowlist secret`, gitleaks
    // `gitleaks:allow`): one line, visible in the diff, auditable in review. Deliberately NOT a
    // broadened pattern — that would silence a whole token class invisibly.
    if (ALLOW_MARKER.test(line)) return;
    for (const p of patterns) {
      p.re.lastIndex = 0;
      const m = p.re.exec(line);
      if (!m) continue;
      // Route by pattern KIND, not by one shared heuristic. A captured value is user-authored, so
      // the template heuristic belongs there; the whole match of a vendor-prefix pattern is a
      // structurally validated token, so only structural degeneracy or an exact published sample
      // may suppress it. Collapsing these two was the fail-open (see the header).
      if (p.valueGroup) {
        if (looksPlaceholder(m[p.valueGroup])) continue;
      } else {
        const token = m[0];
        if (DOC_SAMPLES.has(token) || isDegenerateToken(token)) continue;
      }
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
