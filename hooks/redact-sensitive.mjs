// Stdin -> stdout redaction adapter for Python artifact writers. Never prints findings or values.
import { HIGH, lineMatches, looksPlaceholder, readStdin, redactPrivateKeyBlocks, redactSecrets } from './secret-patterns.mjs';

// The key-dependent families. A string under a credential key is masked whole when the member
// `{"<key>": "<value>"}` matches one of them. password-literal is here because json-credential alone
// starts at 16 characters, so a 6-15 character password under a `password` key was kept (SW-4).
const credentialPatterns = ['json-credential', 'password-literal']
  .map(label => HIGH.find(pattern => pattern.label === label));

// Preserve field context for generic JSON credentials and serialize only after redaction. Redacting
// serialized JSON can replace a whole member with an unquoted marker; redacting detached values misses
// key-dependent credentials.
// The credential family the member `{"<key>": "<text>"}` matches, if any. The member only decides
// whether the whole value is masked. A `"` would end json-credential's value class early (SEC-14), and
// `;`, `'` or a blank would end password-literal's, so each becomes `_` there. Whether the value is a
// placeholder is judged on the original text (R3-SW-1): with `_` for its blanks, `$uper Secret Holiday`
// read as the `$NAME` template and `%Secret Value%` as `%NAME%`, and both were kept in plaintext.
const credentialHit = (key, text) => {
  if (looksPlaceholder(text)) return undefined;
  const member = JSON.stringify({ [key]: text.replace(/[;"'\s]/g, '_') });
  return credentialPatterns.find(pattern => lineMatches(member, [pattern]).length > 0);
};

// JSON.parse with each number kept as its source text (JSON.rawJSON, Node 21+), so a rewritten line
// keeps `0.0000001` and a 20-digit id exactly as written, and a numeric password is judged on its text
// (R3-SW-1). Older Node parses plain numbers.
const KEEPS_NUMBER_TEXT = typeof JSON.rawJSON === 'function' && typeof JSON.isRawJSON === 'function';
const parseJson = (text) => JSON.parse(text, KEEPS_NUMBER_TEXT
  ? (_key, value, context) => (typeof value === 'number' && context && typeof context.source === 'string'
    ? JSON.rawJSON(context.source) : value)
  : undefined);

const clean = (value, key) => {
  if (typeof value === 'string') {
    const hit = key !== undefined && credentialHit(key, value);
    return hit ? `***MASKED:${hit.label}***` : redactSecrets(value);
  }
  // A number or boolean under a credential key (a numeric password) is a credential too (R2-SW-2).
  const number = KEEPS_NUMBER_TEXT && JSON.isRawJSON(value);
  if (key !== undefined && (number || typeof value === 'number' || typeof value === 'boolean')) {
    const hit = credentialHit(key, number ? value.rawJSON : String(value));
    return hit ? `***MASKED:${hit.label}***` : value;
  }
  if (number) return value;
  if (Array.isArray(value)) return value.map(item => clean(item, key));
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([name, child]) => [redactSecrets(name), clean(child, name)]));
  }
  return value;
};

// Raw text. A JSONL line (one JSON object or array, such as a stream-json transcript record) holds its
// strings JSON-escaped: an escaped `\"` ended password-literal's value after one character and hid the
// key of json-credential, so both kept their plaintext (SW-4). Such a line is decoded, cleaned exactly
// like --json input and serialized again. It is kept byte for byte only when neither the decoded values
// nor the raw text hold anything to mask: JSON.parse keeps the LAST of two equal keys, so a secret under
// an earlier one is visible only to the raw scan, and the serialized form then drops it (R2-SW-2). When
// the raw scan masked something, the serialized form is redacted as text as well, so nothing the raw scan
// saw can survive the rewrite; a mask already written there reads as a placeholder (R3-SW-1). A line
// too deeply nested to clean or serialize is redacted as text (R2-SW-8), as is every non-JSON line.
// Private key blocks are masked over the whole input first, as before, because a PEM block spans lines.
function redactRaw(text) {
  return redactPrivateKeyBlocks(text).split(/(\r?\n)/).map((line) => {
    if (line === '\n' || line === '\r\n') return line;
    const head = line.trimStart()[0];
    if (head === '{' || head === '[') {
      try {
        const parsed = parseJson(line);
        if (parsed !== null && typeof parsed === 'object' && !(KEEPS_NUMBER_TEXT && JSON.isRawJSON(parsed))) {
          const cleaned = JSON.stringify(clean(parsed));
          if (redactSecrets(line) !== line) return redactSecrets(cleaned);
          return cleaned === JSON.stringify(parsed) ? line : cleaned;
        }
      } catch {
        // not JSON, or nested past the stack: redacted as text below
      }
    }
    return redactSecrets(line);
  }).join('');
}

const input = await readStdin();
if (process.argv.includes('--json')) {
  // Malformed input fails closed: emit no partial unredacted output.
  try {
    process.stdout.write(JSON.stringify(clean(parseJson(input))));
  } catch {
    process.stderr.write('Invalid JSON redaction input.');
    process.exitCode = 1;
  }
} else {
  process.stdout.write(redactRaw(input));
}
