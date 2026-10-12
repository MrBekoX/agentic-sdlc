// Shared hook-stdout emitter for the guard scripts.
//
// Why it exists: ZCode parses hook stdout as JSON against its documented key
// set, and the two official sources disagree on strictness. The live hook doc
// (fetched 2026-10-08) says unknown fields are ignored while a known field
// with a wrong type or a mismatched event name fails the run recoverably; the
// bundled zcode-guide skill `diagnosing-hooks` says the schema is strict and
// "any extra key fails validation ... its effect was discarded and the run
// marked failed" (pitfall 8). The advisory top-level `systemMessage` channel
// is a Claude Code convention and is in neither source's documented set, so
// under ZCode it must not be written: at best a no-op key, at worst a failed
// run with a discarded deny — and a warn payload carrying ONLY systemMessage
// loses its entire output. Under ZCode this emitter writes a decision as
// hookSpecificOutput alone and moves warn text into
// hookSpecificOutput.additionalContext, the documented model-visible channel.
// Every other runtime receives the payload unchanged, byte-identical to the
// pre-emitter output.
//
// Detection is doubled over two documented mechanisms so it does not hinge on
// one: ZCode injects ZCODE_PLUGIN_ROOT into plugin hook processes as an
// environment variable ("Plugin processes can read ZCODE_PLUGIN_ROOT ..."),
// and the ZCode wire passes a literal `--zcode-runtime` argv element. No
// other runtime's wire sets either marker.
const ON_ZCODE = process.argv.includes('--zcode-runtime')
  || Boolean(process.env.ZCODE_PLUGIN_ROOT);

export function emitHookResult(payload, wiredEventName) {
  if (!ON_ZCODE) {
    process.stdout.write(JSON.stringify(payload));
    return;
  }
  if (payload.hookSpecificOutput) {
    process.stdout.write(JSON.stringify({ hookSpecificOutput: payload.hookSpecificOutput }));
  } else if (payload.systemMessage) {
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: wiredEventName,
        additionalContext: payload.systemMessage,
      },
    }));
  }
  // Neither channel present: write nothing — empty stdout is "success with no
  // extra effect" on every runtime.
}
