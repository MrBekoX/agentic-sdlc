// Stdin -> stdout redaction adapter for Python artifact writers. Never prints findings or values.
import { HIGH, readStdin, redactSecrets } from './secret-patterns.mjs';

const input = await readStdin();
if (process.argv.includes('--json')) {
  // Preserve field context for generic JSON credentials and serialize only after
  // redaction. Redacting serialized JSON can replace a whole member with an
  // unquoted marker; redacting detached values misses key-dependent credentials.
  const credentialPatterns = HIGH.filter(pattern => pattern.label === 'json-credential');
  const clean = (value, key) => {
    if (typeof value === 'string') {
      if (key !== undefined) {
        const member = JSON.stringify({ [key]: value });
        if (redactSecrets(member, credentialPatterns) !== member) return '***MASKED:json-credential***';
      }
      return redactSecrets(value);
    }
    if (Array.isArray(value)) return value.map(item => clean(item, key));
    if (value !== null && typeof value === 'object') {
      return Object.fromEntries(Object.entries(value).map(([name, child]) => [redactSecrets(name), clean(child, name)]));
    }
    return value;
  };
  // Malformed input fails closed: emit no partial unredacted output.
  try {
    process.stdout.write(JSON.stringify(clean(JSON.parse(input))));
  } catch {
    process.stderr.write('Invalid JSON redaction input.');
    process.exitCode = 1;
  }
} else {
  process.stdout.write(redactSecrets(input));
}
