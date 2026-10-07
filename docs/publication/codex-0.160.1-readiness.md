# Codex 0.160.1 preparation evidence

This preparation concerns repository compatibility and public package contents. It does not upload or publish the plugin, grant hook trust, modify the user's Codex profile, commit, push, open a PR or merge. Historical release/eval decisions retain their original source identities and versions.

## Official requirements checked on 2026-10-06

- [Codex changelog](https://learn.chatgpt.com/docs/changelog#october-2026): 0.160.1 released 2026-10-05; the installed Windows binary reports `codex-cli 0.160.1`.
- [Package guide](https://developers.openai.com/plugins/build/plugins): standalone `.codex-plugin/plugin.json` is supported; explicit local hook paths remain supported and require user trust. No root-manifest migration is necessary for this repository.
- [Claude conversion guide](https://developers.openai.com/plugins/guides/submit-claude-plugin): remove lifecycle hooks for public submission and merge reusable commands/agent procedures into skills. The public projection places these procedures in skill references; native registries/workflows remain in the manual distribution.
- [Submission reference](https://developers.openai.com/plugins/deploy/submission): retain required Codex metadata/icons; the four product/support/privacy/terms URLs are required for MCP review, not all skills-only metadata. This plugin has no MCP server. Identity verification, Apps Management Write and portal review remain external requirements.
- [Hooks](https://learn.chatgpt.com/docs/hooks): untrusted plugin hooks are skipped; pre-tool denial uses `hookSpecificOutput.permissionDecision`, Stop block requests continuation, and `stop_hook_active` prevents repeated continuation. Transcript wire format is not a stable hook interface.

## Architecture and preservation

Source behavior remains router -> focused skills -> full pipeline where required. Claude retains native Skill/Workflow/Agent phases, dynamic author/critic loops and Claude transcript/write adapters. Codex retains its embedded author/critic adapter and existing local command hooks. All source skill routing fields, agent/workflow/command files, local manifests and lifecycle hook files remain unchanged.

The general archive still selects committed source with the existing exclusion/safety rules. The public archive deterministically projects that source: sixteen skill entrypoints, three stdlib runtime helpers, contracts/assets/license, nine role bodies and six runtime/documentation references merged under `skills/using-agentic-sdlc/references/`, a read-only git review procedure and a public dispatch guide. Public metadata removes hook registration and private-source optional URLs, and states its procedural enforcement limits.

## Recorded observations

- Initial public regression: `Ran 10 tests`, `FAILED (failures=12, errors=1)` against the previous selector. Missing roles/runtime docs/command and shipped hooks were reproduced.
- First fix: `Ran 10 tests`, `OK`. Independent reviewers then found missing-manifest, empty-role, UTF-8 diagnostic, reference-link, generated-target overwrite and unsafe output cases.
- Review regression: `Ran 15 tests`, `FAILED (failures=5, errors=3)`, then `Ran 15 tests`, `OK` after fixing those cases. General/release distribution regression: `Ran 125 tests`, `OK` at the first implementation checkpoint.
- Initial native 0.160.1 local discovery: sixteen skills/eight hook declarations; `hooks/list` exposes eight `untrusted` entries and no errors. Initial public discovery: sixteen skills/zero hook declarations. These initial probes used clean base-source extractions; final artifacts must bind the final source snapshot and repeat discovery.
- Initial full worktree run was not green: WSL had no Node on `PATH`, producing missing-node errors/skips. Subsequent gates explicitly use the already installed nvm Node; no dependency installation is performed. This failed environment attempt is not a release baseline or current success claim.
- The requested evaluation model is [`gpt-5.6-luna`](https://developers.openai.com/api/docs/models/gpt-5.6-luna) with reasoning effort `low`. A single tools-free `codex exec --model gpt-5.6-luna -c 'model_reasoning_effort="low"'` preflight returned READY. This is access/request evidence only, not plugin evaluation or a response-side model attestation.
- The first complete correct-environment suite ran 1472 tests and reported five failures/six skips. The failures identified missing explicit UTF-8 in the new test, documentation-version/schema drift, and two non-hermetic inventory/home-cache fixtures. The fixes preserve source runtime semantics and add positive/negative fixture controls. This failed checkpoint is retained, never labelled release approval.

## Reproducible preparation commands

Use Python 3 and Node on `PATH` for the source gate:

```bash
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
python3 scripts/bump_version.py --check
python3 scripts/build_release.py --output dist/general.zip
python3 scripts/build_release.py --verify dist/general.zip
python3 scripts/build_release.py --output dist/public.zip --skills-only
python3 scripts/build_release.py --verify dist/public.zip
```

The builder reads committed source, not uncommitted working-tree bytes. For a preparation-only run, retain a labelled isolated Git source snapshot of the complete changed source and record its SHA in both archive logs. Rebuild from the intended repository commit before actual release. Preserve source snapshot and logs for verifier reconstruction. Public extraction requires Python 3; Git is required when resolving a target project's work package. Optional skill-authoring toolkits/evals are discovered explicitly rather than assumed installed.

Current native schema generation: `codex app-server generate-json-schema --out <task-local-schema-directory>`. The isolated stdio probe sends `initialize` (`experimentalApi=false`), `initialized`, `plugin/read`, `plugin/install`, `plugin/read`, `hooks/list`; it uses a task-local catalog/cache/CODEX_HOME and never calls trust-writing methods. The expected final inventory is local 16/8 untrusted and public 16/0. Skill reference/helper existence must be checked from the actual installed cache, not only from archive names.

## Remaining external verification and publication boundaries

- Two bounded `gpt-5.6-luna`/Low component cases completed on 2026-10-07 after scoped transmission approval. The original file-reading case was infrastructure-inconclusive: read-only/never policy blocked shell reads before process creation. The prepared public case received the four authorized package files from the trusted harness with hash receipts, then used a real generic native fresh-context critic and consumed its completed result. Parent and child native contexts both recorded `gpt-5.6-luna`, `low`, `read-only`, `never`; no model shell/file-write/trust/publication calls occurred.
- The public input-based component check supports packaged critic-instruction delivery and native delegation. It does not establish equal-harness A/B improvement, model-side file reading, installed Skill activation, automatic triggers, full-pipeline reliability or public-host behavior. Exact role prose was preserved, with a PLAN bullet layout merge rather than byte-identical prompt copying. Keep actual transcripts, four input hashes and native parent/child/tool receipts in the companion evidence.
- Current trusted installed-hook lifecycle/carrier execution remains unverified; the public directory package ships no hooks and claims no hook enforcement. Historical 0.154.0 lifecycle captures remain historical. Manual hook-enabled installs require separate native review/trust and effect verification; this preparation grants none.
- Verified publisher identity, account permission, portal skill scans/review and publication approval cannot be supplied by repository edits. No portal draft/upload/submit/publish is created here.
- Source repository visibility/public links remain maintainer choices. The public package omits private optional links and does not require making the source repository public for its skills-only format.
- Final source-gate, artifact, snapshot and native results are separate companion verification records delivered with the preparation handoff. Keep those result records outside the payload they identify, so they do not change their own source hash. The checkpoints above preserve the observed development history; use the handoff's exact final logs and source identity when reviewing an artifact. Neither the records nor this guide constitute portal approval.
