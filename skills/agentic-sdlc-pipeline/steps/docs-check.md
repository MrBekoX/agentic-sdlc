# Docs check

Before implementation, verify every third-party API the plan uses against the current documentation for the version the project uses. Never invent an API, and never trust an old answer over the verified docs.

In the commands below, `<python>` is the interpreter that starts the card's `then=` line and `<root>` is the card's `root=` value. Run them with `-B`, as the `then=` line does: it keeps `__pycache__` out of the plugin folder. `<slug>` is the last part of the card's `package=` value.

## 1. List what to verify
- Read the plan named on the card's `inputs=` line and list each third-party library, framework or service whose API the work calls, configures or upgrades.
- Find the version in use in the manifest and the lock file. The start probe lists the manifests under `probes.details.deps` in `<package>/state.json`.
- Always verify: a new package; an existing package's API used in a new way; a framework upgrade; a native mobile change; a backend service's auth, row-level security, edge functions, realtime or storage; ORM migrations and queries; framework and build config; JWT, OAuth, session and cookie handling; any security-sensitive dependency.
- When the plan uses no third-party API, the report says `Libraries: none` and why.

## 2. Verify, as the card's mechanism line says
- `main`: check each library yourself.
- `subagent`: give each library to a fresh sub-agent, all started in one message, and merge their findings yourself.
- When the sub-agent tool is missing or refused, record it and check inline: `"<python>" -B "<root>/scripts/sdlc.py" note --slug <slug> --degraded subagent --reason missing|denied|unavailable`.

Sources, in order:
1. A documentation tool (such as Context7) when the session has one.
2. When it is missing, failing or out of quota: the web search and fetch tools, against the library's official, version-matched docs or its repository. Not blogs, not Q&A sites. Note the fallback in the report.

Check: method and option names, parameter order, async behaviour, return types, deprecations and removals, breaking changes, security notes, env var and config names, platform splits (Android and iOS), and server/client splits.

## 3. When the docs disagree with the plan
Do not edit the approved spec or plan in this step. Write the difference under `Impact on implementation`.

When following the verified API would change behaviour or scope, or needs a dependency the plan does not name, ask the user first: `"<python>" -B "<root>/scripts/sdlc.py" ask --slug <slug> --kind consent --question "<question>"`, then end your turn. The runner waits for the answer and prints how to record it.

Never install, add or upgrade a dependency in this step.

## 4. Write the report
Write the file the card's `outputs=` line names, one block per library:

```md
# Docs check
## <library> <version in use> (<manifest>)
Source: <documentation tool> | <official docs via web search, fallback because ...>
Verified topics:
Findings:
Impact on implementation: none | <what the implementation must do differently>
```

The line `# Docs check` must appear exactly like that, on its own line. Write the report in this visit: a file left from an earlier visit, or rewritten byte for byte, does not count.

## Finish
Write the report, then run the card's `then=` command.
