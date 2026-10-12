# Security Policy

## Supported versions

Security fixes are provided for the latest `0.4.x` release. Older releases are unsupported; verify
the current version in `VERSION` before reporting.

## Reporting a vulnerability

Use GitHub's private vulnerability-reporting form for this repository:
<https://github.com/MrBekoX/agentic-sdlc/security/advisories/new>.

If private reporting is unavailable, open an issue that contains no secret, exploit payload, or
sensitive machine data and ask the maintainer for a private contact channel. Do not publish a proof
of concept before the maintainer has had a reasonable opportunity to investigate and release a fix.

Include the affected version, runtime (Claude Code, Codex, Kimi Code, Grok CLI or ZCode), operating
system, minimal sanitized reproduction, observed impact, and whether the behavior requires a
non-default environment flag.

## Security boundaries

This plugin executes local Node.js hooks and Python validators. Its command and write parsers are
bounded backstops, not complete shell interpreters. Several error paths intentionally fail open;
Stop hooks can request another model turn but cannot undo an earlier filesystem effect. Installation
therefore requires reviewing the bundled hook commands and retaining normal repository permissions,
diff review, CI, and secret scanning.

Never include a live credential in an issue, transcript, eval fixture, or reproduction. Replace
secret values with `***MASKED***` and rotate any credential that may have been exposed.
