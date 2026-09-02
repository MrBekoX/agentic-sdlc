// Stdin -> stdout redaction adapter for Python artifact writers. Never prints findings or values.
import { readStdin, redactSecrets } from './secret-patterns.mjs';

process.stdout.write(redactSecrets(await readStdin()));
