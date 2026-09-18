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
export const ALLOW_MARKER = /agentic-sdlc:allow-secret|gitleaks:allow/i;

// Published documentation samples, matched EXACTLY. An exact-value allowlist cannot suppress a
// class of tokens the way a substring rule can; this is the mechanism gitleaks uses for the
// octokit README sample and the Stripe docs keys.
export const DOC_SAMPLES = new Set([
  'AKIAIOSFODNN7EXAMPLE',                        // AWS docs
  'AIzaSyDaGmWKa4JsXZ-HjGw7ISLn_3namBGewQe',     // Google docs
  'sk_test_4eC39HqLyjWDarjtT1zdp7dc',            // Stripe docs
]);

// Structural degeneracy: the token is a repeated or sequential run rather than a random one.
// This is what actually separates `ghp_xxxxxxxx…` (a doc placeholder) from a real token — the
// letters inside a token carry no meaning, its DISTRIBUTION does. Meli et al. use a run-length
// threshold of 4; we require the run to DOMINATE so a real token that merely contains a short
// run is untouched. Linear, single pass.
export function isDegenerateToken(token) {
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
  // The `["']?` after the keyword closes SEC-7: a JSON-quoted key (`"Password": "..."`) puts a quote
  // between the keyword and the separator, so the same value was reported in env/YAML spelling and
  // missed in JSON spelling, with json-credential's 16-character floor leaving 6-15 uncovered. It stays
  // one OPTIONAL quote, so `"password_hash": "..."` (a `_` follows the keyword) still does not match.
  { label: 'password-literal', re: /\b(?:password|pwd|passwd|sa_password|mssql_sa_password)["']?\s*[:=]\s*["']?([^;"'\s]{6,})/i, valueGroup: 1 },
  // JSON credential:  "...Key|Secret|Password|Token|Credential...": "long-value" (>=16 chars)
  { label: 'json-credential', re: /"[^"]*(?:password|secret|key|token|credential|signing)[^"]*"\s*:\s*"([^"]{16,})"/i, valueGroup: 1 },
];

// Warning (broader) patterns.
export const BROAD = [
  ...HIGH,
  { label: 'assigned-secret', re: /\b(?:api[_-]?key|apikey|secret|access[_-]?token|client[_-]?secret|auth[_-]?token)\b\s*[:=]\s*["']?([A-Za-z0-9_\-.]{16,})/i, valueGroup: 1 },
];

// Per-match scanning (D22). A suppression hides only the match it judged. Inspecting only each
// pattern's FIRST match was a fail-open: a real value after a suppressed one on the same line
// (separated, glued, or joined by a comma or an ampersand inside one greedy value) was never examined.
//   * A pattern without a value group: every match of a global clone. A token glued directly after
//     another match fails its own left anchor, because the character before it is a letter or digit.
//     So the END of each such match, when a letter or digit follows, is a token boundary where every
//     anchored pattern is tried once more without that anchor. Anywhere else the anchor keeps its
//     meaning, so a prefix inside an ordinary word still never matches.
//   * A valueGroup pattern: every prefix start is examined. Its value runs from the prefix end to the
//     end of the maximal value-class run, computed once per run, so the whole walk stays linear.
// Recorded residuals, not closed here: a real token whose start lies strictly inside a suppressed
// degenerate match of an unbounded pattern is not examined; and the template-word predicates of
// looksPlaceholder end in a word boundary, so a real value that merely starts with such a word stays
// suppressed. Clones are cached per pattern object; `p.re` itself is never used or mutated here.
const PLANS = new WeakMap();
const LEADING_ANCHOR = /^(?:\(\?<!\[A-Za-z0-9\]\)|\\b)/;
const VALUE_GROUP = /\((\[(?:\\.|[^\]\\])+\])\{(\d+),\}\)/g;
const OTHER_CAPTURE = /(?:^|[^\\])\((?!\?)/;
const LETTER_OR_DIGIT = /[A-Za-z0-9]/;

function cloneOf(re, source, flag) {
  return new RegExp(source, re.flags.replace(/[gyd]/g, '') + flag);
}

function planFor(p) {
  let plan = PLANS.get(p);
  if (plan) return plan;
  const source = p.re.source;
  const anchor = LEADING_ANCHOR.exec(source);
  plan = { global: cloneOf(p.re, source, 'g'), sticky: null, value: null };
  const groups = p.valueGroup ? [...source.matchAll(VALUE_GROUP)] : [];
  if (groups.length === 1) {
    const [whole, valueClass, min] = groups[0];
    const prefix = source.slice(0, groups[0].index);
    const tail = source.slice(groups[0].index + whole.length);
    if (!OTHER_CAPTURE.test(prefix) && !OTHER_CAPTURE.test(tail)) {
      plan.value = {
        prefix: cloneOf(p.re, prefix, 'g'),
        stickyPrefix: anchor ? cloneOf(p.re, prefix.slice(anchor[0].length), 'y') : null,
        run: cloneOf(p.re, valueClass + '*', 'y'),
        min: Number(min),
        tail: tail ? cloneOf(p.re, tail, 'y') : null,
      };
    }
  } else if (!p.valueGroup && anchor) {
    plan.sticky = cloneOf(p.re, source.slice(anchor[0].length), 'y');
  }
  PLANS.set(p, plan);
  return plan;
}

// Route by pattern KIND, not by one shared heuristic. A captured value is user-authored, so the
// template heuristic belongs there; the whole match of a vendor-prefix pattern is a structurally
// validated token, so only structural degeneracy or an exact published sample may suppress it.
// Collapsing these two was the fail-open (see the header).
function isSuppressedMatch(p, m) {
  if (p.valueGroup) return looksPlaceholder(m[p.valueGroup]);
  return DOC_SAMPLES.has(m[0]) || isDegenerateToken(m[0]);
}

// The value match whose prefix ends at valueStart, or null. `run` caches the last value-class run
// {from, end}: every character in [from, end) is in the class, so a start inside it shares its end.
function valueMatchAt(line, v, valueStart, run) {
  if (!(valueStart >= run.from && valueStart <= run.end)) {
    v.run.lastIndex = valueStart;
    const r = v.run.exec(line);
    run.from = valueStart;
    run.end = valueStart + (r ? r[0].length : 0);
  }
  if (run.end - valueStart < v.min) return null;
  let end = run.end;
  if (v.tail) {
    v.tail.lastIndex = run.end;
    const t = v.tail.exec(line);
    if (!t) return null;
    end += t[0].length;
  }
  return { end, value: line.slice(valueStart, run.end) };
}

// Every match on one line as { index (pattern), start, end, suppressed }, one per pattern and start.
// Exported so a consumer that must LIST suppressions (the BR22 archive/history bridge) reads the same
// per-match verdicts the guard and durable redaction use, instead of re-walking `p.re` itself (SEC-6).
export function lineMatches(line, patterns) {
  const out = [];
  const seen = new Set();
  const boundaries = [];
  const queued = new Set();
  const runs = patterns.map(() => ({ from: -1, end: -2 }));
  const push = (index, start, end, suppressed) => {
    const key = index + ':' + start;
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ index, start, end, suppressed });
  };
  const boundaryAt = (end) => {
    if (end < line.length && LETTER_OR_DIGIT.test(line[end]) && !queued.has(end)) {
      queued.add(end);
      boundaries.push(end);
    }
  };
  patterns.forEach((p, index) => {
    const plan = planFor(p);
    if (plan.value) {
      const v = plan.value;
      v.prefix.lastIndex = 0;
      for (let m = v.prefix.exec(line); m !== null; m = v.prefix.exec(line)) {
        const hit = valueMatchAt(line, v, m.index + m[0].length, runs[index]);
        if (hit) push(index, m.index, hit.end, looksPlaceholder(hit.value));
        v.prefix.lastIndex = m.index + 1; // every prefix start, not only the one after a whole match
      }
      return;
    }
    plan.global.lastIndex = 0;
    for (let m = plan.global.exec(line); m !== null; m = plan.global.exec(line)) {
      if (m[0].length === 0) { plan.global.lastIndex += 1; continue; }
      push(index, m.index, m.index + m[0].length, isSuppressedMatch(p, m));
      if (!p.valueGroup) boundaryAt(m.index + m[0].length);
    }
  });
  for (let k = 0; k < boundaries.length; k += 1) {
    const at = boundaries[k];
    patterns.forEach((p, index) => {
      const plan = planFor(p);
      if (plan.value && plan.value.stickyPrefix) {
        const v = plan.value;
        v.stickyPrefix.lastIndex = at;
        const m = v.stickyPrefix.exec(line);
        const hit = m ? valueMatchAt(line, v, at + m[0].length, runs[index]) : null;
        if (hit) push(index, at, hit.end, looksPlaceholder(hit.value));
      } else if (plan.sticky) {
        plan.sticky.lastIndex = at;
        const m = plan.sticky.exec(line);
        if (m && m[0].length) {
          push(index, at, at + m[0].length, isSuppressedMatch(p, m));
          boundaryAt(at + m[0].length);
        }
      }
    });
  }
  return out;
}

// Scans text line by line; at most one finding per line. Its label is the first pattern, in array
// order, with an unsuppressed match anywhere on the line.
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
    let first = -1;
    for (const m of lineMatches(line, patterns)) {
      if (!m.suppressed && (first === -1 || m.index < first)) first = m.index;
    }
    if (first !== -1) out.push({ line: i + 1, label: patterns[first].label });
  });
  return out;
}

// Replace high-confidence matches before durable local persistence. Unlike the interactive guard,
// durable redaction deliberately IGNORES per-line allow markers: an annotation may authorize a
// fixture in source control, but it never authorizes copying a secret value into a transcript or
// review artifact. Exact published samples and structural placeholders remain safe to preserve.
// It shares the per-match collector with scanLines (D22), so the guard and durable redaction never
// disagree about which match is suppressed: each pattern pass, in array order, masks that pattern's
// unsuppressed matches in start order and skips a start inside a span it already masked. A later pass
// sees earlier masks, and a line with no hidden match gets exactly the masks a global replace gave.
export function redactSecrets(text, patterns = HIGH) {
  // A line scanner can see only the BEGIN header. Redact the complete PEM block first so neither
  // key material nor the END marker survives. An unterminated block is masked through EOF.
  const pem = /-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----[\s\S]*?(?:-----END \1-----|$)/g;
  const withoutPrivateKeys = String(text ?? '').replace(pem, '***MASKED:private-key***');
  return withoutPrivateKeys.split(/(\r?\n)/).map((line) => {
    if (/^\r?\n$/.test(line)) return line;
    let redacted = line;
    let matches = null; // recomputed only after a pass changed the line
    patterns.forEach((p, index) => {
      if (matches === null) matches = lineMatches(redacted, patterns);
      const hits = matches.filter((m) => m.index === index && !m.suppressed).sort((a, b) => a.start - b.start);
      if (!hits.length) return;
      let rebuilt = '';
      let copied = 0;
      for (const m of hits) {
        if (m.start < copied) { // starts inside a span this pass already masked: extend it over the hit
          copied = Math.max(copied, m.end);
          continue;
        }
        rebuilt += redacted.slice(copied, m.start) + `***MASKED:${p.label}***`;
        copied = m.end;
      }
      redacted = rebuilt + redacted.slice(copied);
      matches = null;
    });
    return redacted;
  }).join('');
}

// Read the full JSON from stdin (hook input).
export async function readStdin() {
  if (process.stdin.isTTY) return '';
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString('utf8');
}
