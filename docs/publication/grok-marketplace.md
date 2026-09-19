# Grok CLI personal marketplace — how to add this repo (NOT a publish)

Status: adapter infrastructure only. Nothing here has been submitted to an
official xAI plugin directory, and `grok plugin tag` has not been run. This
note records how another person adds this repository as a **personal**
marketplace source, from `~/.grok/docs/user-guide/09-plugins.md` and live
`grok plugin --help` on grok 1.0.34.

Grok CLI is an experimental adapter, not a supported 0.4.3 release target.

## Already prepared locally

- `.grok-plugin/plugin.json` with `name=agentic-sdlc`, `version` pinned to
  `VERSION`, a Grok-facing `description` (not the Claude-only sentence), and
  `hooks` pointing at `./hooks/hooks-grok.json`.
- `.grok-plugin/marketplace.json` (`name=mrbekox`, `plugins[]` entry with
  `name`/`version`/`source="./"`). No zip `sha256` or `_artifact` fields.
- `.grok-plugin/README.md` documenting `marketplace add`, `install --trust`,
  `enable`, `details`, `inspect`, side effects, and Workflow degradation.
- Version binding via `tests/test_grok_packaging.py`.
- Optional catalog `.grok-plugin/plugin-index.json` is **not** shipped;
  `09-plugins.md` says installs work without it.

## Add and install (personal)

From a clone of this repository (public or, with your own git credentials,
private):

```text
grok plugin marketplace add /path/to/agentic-sdlc
grok plugin marketplace list
grok plugin install agentic-sdlc --trust
grok plugin enable agentic-sdlc
grok plugin details agentic-sdlc
grok inspect
```

`--trust` is required. Without it, hooks and skills stay inactive. Plugins
are off by default until enabled.

Observed on grok 1.0.34 (this adapter session): `grok plugin marketplace add .`
registers the folder as a source. Name lookup `grok plugin install agentic-sdlc`
then reported `No marketplace plugin named "agentic-sdlc"` — the local
`source: "./"` entry was not in `grok plugin list --json --available`. The
documented CLI form `grok plugin install <local-path> --trust` is the install
that succeeded. Installing the live git worktree with `grok plugin install .`
hit Windows I/O error 5 (access denied) while copying `.git`; a git-less
snapshot of the same packaging installed, enabled, and appeared in
`grok plugin details` / `grok inspect --json` with 16 skills.

When this repository is public, a GitHub shorthand also works:

```text
grok plugin marketplace add MrBekoX/agentic-sdlc
```

A **private** GitHub URL without credentials returns 404; access uses each
person's own git credentials (`09-plugins.md`). Visibility is a separate
gate from this adapter work.

After install, press `r` in the Plugins tab (`/plugins`) or start a new
session. Invoke `/using-agentic-sdlc` (or `/agentic-sdlc:using-agentic-sdlc`
on collision).

`require_sha` / `GROK_MARKETPLACE_REQUIRE_SHA=1` refuses unpinned **remote**
installs. A local directory source is copied from the checkout; do not
invent a `sha` on `source: "./"`. A binding `strictKnownMarketplaces` list
refuses local-path adds unless an admin pin names that exact path — that is
`BLOCKED`, not a local-validate pass.

## Explicitly out of scope

No `grok plugin tag`, no git commit/push, no official directory submission,
no fabricated zip `sha256`, and no claim that `grok plugin validate .` on
the Claude layout is Grok-native publish.
