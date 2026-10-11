# Marketplace preparation — 2026-10-11

This is a local preparation record. The packages are **not published** and no
vendor submission, catalog PR, tag, source commit/push/merge or visibility change
was performed in this phase. The immutable [0.4.3 ledger](../release-evidence-0.4.3.md)
retains its historical verdicts.

## Source and projection identity

The native lifecycle fixture uses committed source
`3bcbf7b9b4ae7688c8017756086f9128240b64f3` (release version `0.4.3`). Its full
archive SHA-256 is `aba71273c0a8fe78e902af4c9b6fd139b937e24d7e5392064874db8d2d5a866b`.
Intentional marketplace layouts/README translations are producer projections,
not bytes falsely attributed to that source commit. The staging receipt records
per-path source/output digests and actual producer digests separately.

`scripts/prepare_marketplace_release.py` exports only a validated committed byte
map into a new directory. It prepares `clean-source/`, a Grok vendored catalog
and a ZCode `plugins/agentic-sdlc` catalog with equivalent root README translations.
It scans source and projected content before writing, rejects unsafe paths/Git
metadata/overlapping or existing destinations, and verifies the resulting bytes.
It performs no download, Git mutation or external write.

```text
python3 scripts/prepare_marketplace_release.py --source-root . --source-commit 3bcbf7b9b4ae7688c8017756086f9128240b64f3 --output build/marketplace-preparation
python3 scripts/prepare_marketplace_release.py --source-root . --source-commit 3bcbf7b9b4ae7688c8017756086f9128240b64f3 --verify build/marketplace-preparation
```

Use a new destination each time; existing outputs are preserved. Final release
preparation must use the intended reviewed committed revision and matching
producer version. No uncommitted source bytes are smuggled into the export.

The clean export has no original history. It can seed a separate new public
repository after maintainer review and authorization. It does **not** close the
private-path finding in the original history, rewrite it or make the original
private repository safe to expose. Anonymous reachability of a future source URL
must be checked after that source actually exists.

## Native Windows evidence

| Runtime | Observed boundary | Remaining boundary |
|---|---|---|
| Claude Code 2.1.296 | Previous committed-tree strict validation and isolated install/versioned update/remove | No new live model evaluation in this phase |
| Codex 0.162.1 | Native local install/recopy/remove; eight untrusted→exact-hash trusted hooks in a temporary profile; native `SessionStart` completed and bootstrap context observed | PreToolUse/Stop native delivery and live skill behavior require separate evidence |
| Kimi Code 2.1.1 | Authenticated loopback native API; install, managed-copy refresh, remove record while retaining bytes; unrelated plugin/config preserved; 16 skills/one command/three hook declarations | Hook execution and live skill behavior were not exercised by the management API |
| Grok CLI 1.0.50 | Directory validation/install/remove with authorized temporary trust; moving-branch offline Git update changed installed bytes and HEAD; unrelated plugin/config preserved | Native hook execution, session reload and live skill behavior remain unverified |
| ZCode desktop bundle 3.14.5 / agent CLI 0.16.9 | Signed extracted native manager validated/installed/discovered 16 skills and five hook declarations; versioned update and confirmed uninstall preserved unrelated state | Desktop GUI, actual hook delivery and model behavior remain separate unverified paths |

Kimi's server kept bearer authentication enabled; tokens were used only in memory
and were not copied into receipts. Model/session/account endpoints were not called.
Grok local `plugin update` returned success without refreshing copied bytes; a
same-source reinstall reported already installed. An absolute source containing
`#` was rejected by its source grammar; changing into the directory and installing
`.` succeeded. The moving-branch test used only a disposable local Git repository.

Codex used its supported config writer and native `hooks/list` hashes to persist
reviewed trust in a fresh profile. No hook-trust/approval/sandbox bypass flag was
used. The event check used one native turn and a rejecting loopback provider, so
the turn failed as expected after startup delivery; no live model inference occurred.
The local provider request contained the bootstrap context; it is not a successful model eval.
Personal config/auth hashes were preserved and no personal credentials were copied.

ZCode's extracted bundled agent ran in Electron's Node mode with native home/data
and provider paths explicitly isolated. Local source edits did not update its
cached copy; marketplace refresh plus a disposable `0.4.4` fixture update did.
Uninstall required confirmation, removed the selected updated cache/data, and
retained the old `0.4.3` cache. This does not bump the source release version.
An initial whole-profile metadata comparison was inconclusive because the
personal desktop client was already running and writing logs/caches. Targeted
settings/registration content checks establish the relevant preservation boundary;
no probe-caused personal mutation or credential copy was established.

## Official catalog fixture checks

Grok tooling is pinned to `xai-org/plugin-marketplace`
`3852296d0c7caca966c5b5f32f1d66ea6247a9d5`; ZCode tooling is pinned to
`zai-org/zcode-plugins` `8b8c69c1b73be497d0e4865e6b74b5c05898d5d7`.
Run these stdlib tools only on separate copies of the prepared one-plugin packets:

```text
# Grok fixture root
python3 scripts/generate-plugin-index.py
python3 scripts/validate-catalog.py
python3 scripts/generate-plugin-index.py --check
# ZCode fixture root
python3 scripts/validate.py
python3 scripts/build_dist.py
```

Grok's expected inventory is version `0.4.3`, 16 skills, one command, nine agents,
one hook event group containing three handlers, no MCP/LSP. ZCode requires exact
`./plugins/agentic-sdlc`, matching en/zh-CN metadata and release versions, root
equivalent README pair, license and truthful prerequisites/side effects/attribution.
All five pinned official-tool commands returned exit 0 in separate one-plugin
fixtures. The Grok index reported exactly the expected component inventory;
ZCode produced a 277-member ZIP with verified manifest/index digest agreement.
Generated ZIP/index hashes are fixture outputs; no generated CDN URL is claimed
reachable. Official validation does not prove README equivalence, native effects
or catalog acceptance. Final fixture outcomes are recorded in task evidence.

## Remaining decisions

- macOS is **skipped** at the user's explicit request; the manual CI matrix remains.
- OpenAI publisher identity and Apps Management Write are **unknown** from this
  workspace. Verify them in the maintainer portal before a requested submission.
- Claude public source/form access, a new clean source repository and anonymous
  URL reachability remain maintainer prerequisites. The original repository stays private.
- Vendor review/acceptance and any immutable published-version decision are external.
  A local single-plugin fixture is not a reserved or approved listing.
- Live model routing/procedure batches were not run. Short lifecycle/event checks
  do not replace the release ledger's three-observation live evaluation requirements.
- Kimi's official/curated listing has no verified self-service submission contract.

The OpenAI public archive remains the separate deterministic skills-only
projection, without lifecycle hooks. Full manual Claude/Codex distributions keep
their shared behavior. Review all final identities/checks, then obtain explicit
publication approval; preparation itself grants no publication permission.

Primary contracts: [OpenAI submission](https://developers.openai.com/plugins/deploy/submission),
[Codex hook trust/events](https://learn.chatgpt.com/docs/hooks),
[Kimi server API](https://www.kimi.com/code/docs/en/kimi-code-cli/reference/server-api.html),
[Grok contribution contract](https://github.com/xai-org/plugin-marketplace/blob/3852296d0c7caca966c5b5f32f1d66ea6247a9d5/CONTRIBUTING.md),
[ZCode contribution contract](https://github.com/zai-org/zcode-plugins/blob/8b8c69c1b73be497d0e4865e6b74b5c05898d5d7/CONTRIBUTING.md).
