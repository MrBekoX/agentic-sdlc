# Testing and Evaluation Strategy

> How the `agentic-sdlc` project is tested, what the local gate proves, and how to run live evals. Written for developers and eval runners.

This project uses a **deterministic-gates-first** model. Deterministic tests are cheap, repeatable, and run without API keys; they prove the *substrate* is healthy. Live evals (Claude Code and Codex) provide optional, higher-cost evidence that skills actually trigger and that the model follows the intended procedure.

> **Never claim a skill "works" or "triggers" without running the relevant eval and capturing its output or a transcript.** (Contract `00` — evidence before claim.)

For runtime-specific behavior see the [Claude Code README](../.claude-plugin/README.md) and [Codex README](../.codex-plugin/README.md). For the component reference see [`plugin-readme.md`](./plugin-readme.md); for skill responsibilities see [`skill-boundaries.md`](./skill-boundaries.md).

---

## Testing philosophy

1. **Fast local checks prove** that skill frontmatter, cross-references, fixtures, scripts, and hook/workflow syntax are healthy.
2. **Live evals provide** optional, higher-cost evidence that skills trigger and that the model follows the intended procedure.

Deterministic tests verify **wiring and fixture health** — they do **not** prove live model obedience. Use live evals for those claims.

---

## Fast local gate

Run these commands before claiming the repo is healthy:

```bash
python3 scripts/bump_version.py --check
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
```

Use the repository-mandated `python3` entry point on both platforms; verify it is on `PATH` before running the gate. Hook-internal interpreter fallbacks are separate from these contributor commands.

**All four, in full.** `check_all.py` runs the frontmatter lint and the validator suites it names, and nothing else — it prints `suites_not_run_here` pointing at the fourth command for exactly that reason. It used to run the whole suite itself, which made a gate run collect ~1300 tests twice (440 s against 3 s here) and made `validator_tests=` report something far wider than it named. The fourth command is what runs everything; no other command is a substitute for it.

### What each command proves

| Command | Proves |
|---|---|
| `python3 scripts/bump_version.py --check` | `VERSION`, all shipped plugin manifests, and every `agentic-sdlc` entry of each marketplace catalog agree (another plugin's entry is neither checked nor bumped), and so do the visible version declarations: the README `Version` token and README current-version sentence, the `docs/plugin-readme.md` version line, the `docs/release-readiness.md` publish-gate sentence and verdict-template `version=` line, and the supported `X.Y.x` line in `SECURITY.md`. |
| `python3 scripts/check_all.py` | A regex-based frontmatter check, not a full YAML parser or Agent Skills specification validator. Official Agent Skills fields: only the six keys `name`, `description`, `license`, `allowed-tools`, `metadata` and `compatibility` may appear, and `name` matches the directory. House-only rules, checked separately: third-person description framing, enforced only as rejection of the known leading-Use imperative regression (description meaning and trigger intent still need review); the angle-bracket ban; and a description length check. It also runs the four validator suites named in `VALIDATOR_TEST_PATTERNS`, and no other suite. |
| `python3 tests/skills/harness.py` | Skill/agent/workflow/hook/skill-contract references resolve; golden cross-references have not drifted; safety-fixture evidence is wired to real files; `${CLAUDE_PLUGIN_ROOT}` and `${PLUGIN_ROOT}` paths plus Claude/Codex hook configs resolve. Each of those checks is demonstrated to FIRE by a negative control in `tests/test_harness_negative_controls.py` — before those existed, a check in this file was found unreachable by construction and had passed every gate run since it was written. It also fails on any TRACKED file carrying an unresolved conflict marker — added after two such markers reached a commit and survived a full 1445-test gate run, one of them in this very file, whose suite-map test read it and passed. What the pass line still does NOT prove: that a shipped artifact is CORRECT, only that the references it names resolve. |
| `python3 -m unittest discover -s tests -v` | The whole local unittest layer — more than seventy suites, enumerated in the **Test suite map** below, which a test keeps complete. Among them: `detect_context.py` classifies workspaces correctly; `validate_artifacts.py` enforces spec/plan structure and scans for placeholders/secrets; the secret, commit, branch and destructive-command guards are driven through their confirmed bypass shapes; the Codex adapters are driven through real rollout records; and hook and workflow JavaScript parses under `node --check` (skipped, never passed, if `node` is missing). Read the map rather than this cell for the inventory. |

### What the gate does NOT prove

- Claude Code actually chose the right skill in a live session.
- The model followed every step in a skill body or workflow.
- A human-facing end-to-end workflow succeeded without runtime errors or permission denials.
- Guardrails are obeyed when the model is under pressure.

Use live evals for those claims.

---

## Automation / CI policy

`.github/workflows/ci.yml` runs on `pull_request`, and on `push` **only to `main`** (`workflow_dispatch` also allows a manual run), across `ubuntu-latest`, `windows-latest` and `macos-15-intel`. The standard Intel macOS image preserves this OS coverage after hosted ARM capacity left `macos-latest` jobs unacquired. It does not establish ARM coverage. The macOS entry is preparation until a job result is recorded. A push to a feature branch therefore gets no CI until a pull request exists for it — open the PR early if you want the matrix to run. The source steps run:

```bash
python3 scripts/bump_version.py --check
python3 scripts/bump_version.py --audit
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
```

`python3 scripts/bump_version.py --release-check` (the `Release consistency` step, and `Archive gate: release check` below) runs only for a release: a pull request or a push to `main` whose change touches `VERSION` (the `Detect a VERSION change` step compares the merge commit with its first parent, or a push with the previous tip; a base the clone does not hold counts as a change), a pull request from a `chore/release-*` branch, or a manual run on such a branch or on a tag (pushing a tag starts no CI). It also requires an empty `## Unreleased` and a dated `CHANGELOG.md` section for `VERSION`. A feature pull request writes its notes under `## Unreleased` and passes with `--check`; the release pull request moves them under the dated heading. A push to `main` that leaves `VERSION` alone runs `--check` only.

The archive steps (DP16) then run under the same triggers (pull requests, and pushes to `main`). They build the release archive with `python3 scripts/build_release.py --output`, verify it with `python3 scripts/build_release.py --verify`, extract it to a clean directory without creating a commit, and run the local gate commands there, starting with `python3 scripts/bump_version.py --check` (the release check only under the condition above). A coverage comparison against the source run counts named skips, and the archive-run logs are named `archive-*`. That comparison executes the full source suite again, so each OS job has three suite passes under a finite job limit of 150 minutes; the individual grammar performance assertion remains 5 seconds.

Publishing, release creation, pushing generated commits, and marketplace/plugin publication must remain **manual and explicitly requested**. Do not automate those steps from an eval or a script.

### Pre-push checklist

```bash
git status --short --branch
python3 scripts/bump_version.py --check
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
python3 scripts/run_behavior_eval.py --eval-set tests/skills/behavior/completion-claim-gate.json --dry-run
python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --dry-run
python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --transcript tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-pass.jsonl
python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --transcript tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-codex-adapter-pass.jsonl
```

Optional: `pre-commit run --all-files` (wired in `.pre-commit-config.yaml` to run `check_all.py` + the harness).

That pair is the **fast subset**, not the gate: together they finish in seconds and cover the frontmatter lint, the reference/golden/safety-wiring checks and the validator suites. They do not run the unit-test layer. Before claiming the repo is healthy, run all four commands above — `pre-commit` passing is not the same claim. (It used to run the full suite on every commit, which took about eight minutes; a guard that blocks routine safe work that long is one that gets switched off. If you want the suite on every commit anyway, add it to `.pre-commit-config.yaml` deliberately.)

---

## Test suite map

The local unittest layer is organized into coverage **matrices** so each concern has a dedicated suite.

| File | Matrix | What it verifies |
|---|---|---|
| `tests/test_skill_structure.py` | A | Every skill has valid frontmatter, a kebab-case name matching its directory, a present description without angle brackets, and only allowed frontmatter keys. Every agent has a name matching its filename and a description. |
| `tests/test_skill_integration.py` | F | Golden `must_reference` entries appear in `SKILL.md` and resolve to real skills/agents/workflows/commands/scripts/files/contracts/hooks; plugin-root references exist; Claude and Codex hook configs are valid JSON and each referenced `.mjs` exists; workflow `agentType` values resolve to real agents; README/hooks-README claims match the tree. |
| `tests/test_skill_fixtures.py` | B / D / G | Every skill has a golden entry; golden description keywords still appear in live descriptions; safety scenarios are well-formed and their guardrail evidence exists in the cited repo files; every `tests/skills/evals/<skill>.json` is well-formed, targets a real skill, and contains both positive and negative queries. |
| `tests/test_detect_context.py` | script unit | `detect_context.py` classifies empty dirs as greenfield, counts source files, detects one vs. multiple architectural layers, ignores noise dirs, probes dependency manifests, probes toolchains, and always exits 0 even on hostile paths. |
| `tests/test_validate_artifacts.py` | script unit | `validate_artifacts.py` detects missing spec sections, thin sections, untestable acceptance criteria, placeholder tokens, secrets (masked), AC coverage gaps, task-block ordering, missing task verification, deferrals, and security hand-waves; `--strict` promotes warnings to errors. The hybrid spec/plan path adds a `design` mode (four sections, decisions with an id and an owner tag, a duplicate id an error), a `--sources` flag that requires each spec criterion to name a request, decision, question or gate feedback source, and spec-less plans: a `spec: none` plan of the `bugfix`, `feature` or `plan` flow takes its own `## Acceptance Criteria` with request, decision or gate feedback sources, a feature plan needs no `## Bug`, and `spec: none` with any other flow reports `spec_none_requires_specless_flow`. With `--sources`, every criterion id the coverage counts needs a top-level bullet that names its source: criteria under a sub-heading of the section are still read, and an id in a table, a heading, a nested bullet or another section of the spec is `ac_no_source`. An id of more than six digits (task, criterion, decision, question or feedback record) is no id and is reported, never raised. A criterion added or changed on a gate's change request cites `F<n>`, the `reject` record whose `seq` is n in `feedback.jsonl` (`--feedback`, `--feedback-gate`): a record at another gate, a record of another kind, an unknown seq and a missing or unreadable log make it an unknown source, a malformed line is skipped, and the log is split on line feeds only, as the runner reads it, so a quote with a Unicode line break keeps its record. `criterion_sources` lists the criteria the source check reads, with their tokens as written, for the runner's gate card. |
| `tests/test_work_package_resolution.py` | script unit | `resolve_work_package.py` resolves canonical `docs/agentic-sdlc/specs/` + `docs/agentic-sdlc/plans/` pairs by explicit path, branch, or changed plan, and rejects ambiguity, bad metadata, path traversal, missing specs, and timestamp fallback. A `spec: none` plan of the bugfix, feature or plan flow resolves without a spec, a plan of another flow with `spec: none` is refused, and a spec-less plan in a package that holds a spec fails. |
| `tests/test_static_node.py` | E | Every hook `.mjs` and every workflow `.js` passes `node --check` (workflows are wrapped the same way the Workflow runtime wraps them). Skipped if `node` is absent. |
| `tests/test_trigger_eval.py` | eval-runner unit | The Claude trigger eval runner parses fixtures, builds command shims, and detects trigger outcomes correctly. |
| `tests/test_codex_trigger_eval.py` | eval-runner unit | The Codex route-classifier trigger runner parses fixtures and classifies routes correctly. |
| `tests/test_routing_eval.py` | eval-runner unit | The router eval runner handles Claude/Codex command construction, model aliases, error extraction, and route classification. |
| `tests/test_behavior_eval.py` | eval-runner unit | The behavior eval runner validates fixture shape and matches required/forbidden patterns. |
| `tests/test_procedure_eval.py` | eval-runner unit | The procedure evaluator parses stream-json transcripts and enforces required/forbidden skills, workflows, commands, artifacts, adapter evidence, artifact depth, and patterns; under `--strict-evidence` it also grades the strict case keys (including the zero-delegation keys and the `core-read` order id), the gate-stop eval set and the per-case acceptance lines, against positive and negative transcript fixtures. |
| `tests/test_flow_requirements.py` | hook policy unit | `hooks/flow-requirements.json` parses and every named skill, workflow, agent, validator, and command regex resolves; each `toolUse` item carries exactly one of `contains` and `exactName`. |
| `tests/test_flow_guards.py` | hook policy unit | `flow-order-guard.mjs` and `flow-step-guard.mjs` re-derive evidence, fail open outside active flows, and warn/block according to `AGENTIC_FLOW_GATE_BLOCK`; exact-name matching for flow activation and the pipeline's `dispatch`, `security` and `control` steps, the pipeline `red-first` step, the dispatch-terminal Stop warning, and exact-output pins for `flow-step-guard.mjs` in place of its released byte lock. |
| `tests/test_hooks_policy.py` | policy unit | Hook wiring policy (block vs warn, fail-open, secret-pattern coverage, Claude/Codex hook-config separation). The destructive guard denies cmd.exe's tree deletes (`rd`, `rmdir`, `del`, `erase` with `/s`) at the top level and inside `cmd /c`, `/k` or `/r` payloads with `^` escapes and `&`, `&&`, `||`, including Git Bash's `//c` and `//s`, glued switches, `@` and `call` prefixes and cmd named as `%COMSPEC%` or `$env:ComSpec`. It allows `dir /s`, `rmdir build`, `findstr /s`, `xcopy /s`, `robocopy /s`, `rd /?` and an `echo` of such a command. |
| `tests/test_protected_push_destinations.py` | guard regression | Protected push destinations from caller/configured refspecs, aliases and repository context; explicit/implicit patterns, upstream defaults, matching/all and possible mirror/prune deletion. Includes option/tag/feature controls, unknown versus known-empty state and a long read-only directory chain. No remote push runs. |
| `tests/test_packaging_metadata.py` | metadata unit | Plugin manifests, publishable Codex schema keys, marketplace version consistency, and `bump_version.py` behavior. |
| `tests/test_public_plugin_projection.py` | public packaging regression | Public lifecycle exclusion, role/command/doc dependency closure, clean helper invocation, unchanged routing/source bytes, CRLF redaction instructions, missing/empty/invalid dependencies, generated-target collisions, resolved local links and tamper rejection. The scripts set is exact: the three helpers, `scripts/sdlc.py` and the named runner modules. A loop role the projection does not copy to the public role folder, an unreadable loop definition and a loop definition whose roles cannot be read each stop the build. |
| `tests/test_release_readiness_docs.py` | doc consistency unit | Release-readiness docs and documented helper counts match the repository. |
| `tests/test_house_voice.py` | product-surface unit | Runtime scope, house-voice markers, depth-forcing blocks, and maintenance files remain present. |
| `tests/test_skill_creator_resolver.py` | helper unit | Official toolkit identity, requested capabilities, candidate fallback, and explicit-path trust diagnostics without hidden installs. |
| `tests/test_runtime_documentation.py` | doc consistency unit | Current runtime evidence limits, test-result versus ordering semantics, coexistence restoration, and installed-trust proof requirements. |
| `tests/test_native_distribution_lifecycle.py` | native local lifecycle | `scripts/check_native_lifecycle.py`: the exit rule, reason slugs without paths or identity, absolute-PATH resolution (simulated Windows `.cmd`/`.bat`/`.ps1` refusal), the allowlisted child environment, and full runs against fail-closed fake `claude`/`codex`/`grok`/`kimi`/`agy` programs on a PATH holding only the fakes (POSIX): package-derived discovery counts per platform, refresh byte replacement, record removal, sentinel survival, too-old and absent CLIs, a hanging CLI, Kimi server termination, temporary-root cleanup, and SIGTERM stopping the running CLI and still removing the root (SIGHUP and Windows SIGBREAK map to the same exit). Real-CLI tests run only where the vendor CLI resolves, assert `native_<platform>=passed` and that the real profile's plugin files are untouched; a missing, shim or too-old CLI is a skip. No trust, auth or model turn; this does not certify remote publication, hook execution or skill behavior. The direct layer (no checker) also has Codex install, recopy and remove a relocated source in a disposable profile, keeps the Kimi loopback client off proxies and redirects, and runs optional Kimi/Grok checks (including a Grok moving-Git-branch update) only with explicit `AGENTIC_NATIVE_TRUST_SMOKE=1`; missing CLIs or prerequisites are named skips. The Antigravity recipe probes only `agy plugin --help` (agy acts on a trailing `--help` of a subcommand), and `native_antigravity=not-run:agy_missing` without `agy`; the manual `.github/workflows/native-lifecycle-linux-agy.yml` is pinned to `workflow_dispatch`, read-only permissions and the shared action SHAs, and stays out of `ci.yml`. |
| `tests/test_marketplace_release.py` | publication staging boundaries | Committed-source byte identity/preservation, secret/path/dependency rejection before writes, new-only destination, deterministic catalog/README projection and tamper verification; the Grok package carries the runner's Grok engine byte for byte. Official tools and native clients require separate receipts. |
| `tests/test_handoff_scripts.py` | script unit | `task_brief.py` extracts a single plan task into a handoff file. |
| `tests/test_secret_guard_bypasses.py` | guard regression | RED regression coverage for every confirmed bypass of the secret, commit and branch guards - prefix and wrapper forms, inner shell payloads, git aliases, statement splitting, and the cost bounds that keep a guard inside its hook budget. Each closed bypass is paired with a control case proving the guard did not simply start blocking everything. |
| `tests/test_codex_write_guard.py` | Codex adapter | The Codex secret-write guard: which write forms it recognizes (apply_patch, printf/echo redirects, literal heredocs), which it documents as out of reach, and an LF-normalized sha256 lock on the Claude-side files the slice must not touch. |
| `tests/test_codex_flow_step_guard.py` | Codex adapter | The Codex evidence-only Stop adapter: active-flow derivation from in-session artifact writes, runner/exit correlation, same-work-id spec/plan pairing, warn-default vs flag-block, and the wiring this slice must leave alone. |
| `tests/test_codex_flow_order_guard.py` | Codex adapter | The Codex env-gated pre-edit ordering gate: recognized edit forms, the evidence it accepts before a source edit, default silence, and the byte-locked regression surface. |
| `tests/test_codex_completion_claim_guard.py` | Codex adapter | The Codex completion-claim guard and its marker mechanism, including parity of the claim/negation patterns with the Claude guard and the exact house message bytes. |
| `tests/test_codex_current_rollout.py` | Codex adapter | Parsing of real Codex rollout records captured from a native WSL run - success and denial carriers - so the evidence readers are pinned against actual transcripts rather than synthetic ones. |
| `tests/test_check_codex_hook_trust.py` | Codex adapter | The hook-trust checker: hermetic tests for its probe, its timeout and process-tree kill path, and the reports it produces for a trusted and an untrusted profile. |
| `tests/test_codex_hook_trust_docs.py` | docs | That the per-environment Codex hook-trust steps are documented where an operator will find them. |
| `tests/test_codex_hook_portability.py` | Codex packaging | Serialized hook commands run from a relocated package and unrelated cwd, preserve startup/deny behavior, read installed-root bytes as data, and retain the handler/import/requirements/validator dependency closure. Real shell replays, not native hook trust or lifecycle evidence. |
| `tests/test_effect_layer_guards.py` | guard regression | Effect-layer enforcement: the repo git hooks the installer writes (prevention) and the Stop-time working-tree scan (detection), which sees the bytes that landed regardless of the write form used. |
| `tests/test_commit_message_retention.py` | guard regression | Raw-message hash-line retention in both Git message modes, including LF/CRLF, installed nonedited/cleanup/custom-marker commits and edits after prepare-commit-msg. Preserves harmless templates/samples/same-line suppression and explicit missing-input warnings; real commits are disposable fixtures only. |
| `tests/test_install_git_hooks.py` | script unit | The git-hook installer: the hook body names no plugin path (the same bytes for any plugin location; the scanner is found from `$0`), a modified managed hook is never overwritten or deleted, installs are idempotent and reversible, a foreign hook is left alone, an external hooksPath needs explicit opt-in, a `~/`-prefixed hooksPath resolves to the user's home as git resolves it, a relative hooksPath resolves from the top of the working tree even for a subdirectory `--repo`, a fixed global hooksPath counts as external even inside the checkout while a relative global one stays each repository's own folder, and an install from a linked worktree lands in the shared hooks folder git actually runs (one ownership record per repository). |
| `tests/test_flow_validator_interpreter.py` | hook portability | The flow hooks' validator interpreter: a Microsoft Store alias, a launcher without an installed Python, Python 2 or a configured stub fail open instead of reading as a failed validation; an interpreter planted in the project directory is never run; a real Python 3 still decides the verdict. The PATH resolver test runs on every OS; the fake-interpreter cases are POSIX-only (Node cannot start `.cmd` fakes). |
| `tests/test_hook_spawn_hardening.py` | hook security | Hooks inside a hostile project: a planted `git` is never run (SessionStart, commit, branch and Stop hooks); forced colour (`color.ui`, `color.diff`, `diff.color`), a `-diff` attribute, `diff.relative` or a diff over 1 MiB cannot hide added lines from the commit scanners; added lines whose content starts with `++` are scanned; a type change still reveals a credential file name; read-only scans never run repository hooks and disable hook lookup inside the plugin rather than at the filesystem root; the Stop scan reads untracked files from a subdirectory, splits its file and byte budgets between ignored and new files (so neither a large untracked tree, a deep ignored cache, large ignored logs or coverage HTML can keep a top-level `.env` or the last file of a new multi-file feature from being content-scanned), and a large `node_modules` cannot overflow the ignored listing; quoted Windows `PATH` entries resolve; padded credential names still match and control characters are escaped in output; workflow `pluginRoot` accepts only plain absolute paths, every Claude Workflow call passes it, and a missing root defers to the role files; the flow validator runs with `-I` from the plugin root. |
| `tests/test_helper_encoding_portability.py` | script portability | User-facing helpers ignore a UTF-8 byte-order mark (validator, resolver, dependency probe) and keep their exit codes on a cp1252 console while printing non-ASCII values (a branch name, a manifest file name, an echoed frontmatter status). |
| `tests/test_helper_python_floor.py` | script portability | Helpers that run in the user's environment, `build_release.py` and `eval_safety.py` included (the Cursor installer imports them), parse with the Python 3.8 grammar, defer any PEP 604 union annotation and call no 3.9+ method (`removeprefix`, `removesuffix`, `is_relative_to`), so they import and run on stock macOS and older Linux interpreters; includes negative controls for both detectors. |
| `tests/test_byte_lock_integrity.py` | meta | The byte locks themselves: no live test may resolve an expected value from `git show HEAD:`, and every locked path's expected value must be a literal in the test source - a digest recomputed at run time is a tautology wearing a hash. |
| `tests/test_testing_doc_map.py` | meta | This map: every suite has a row, no row names a deleted file, and every deliberate exclusion carries a reason. A drift gate, not a truth gate - it cannot judge whether a row's description is accurate. |
| `tests/test_subprocess_encoding.py` | house rule | Every text-mode subprocess call in tests and scripts pins `encoding='utf-8'`, so a locale does not decide what a test reads. |
| `tests/test_repo_scripts_no_deprecated_utcnow.py` | house rule | No shipped Python script calls the deprecated `datetime.utcnow()`. |
| `tests/test_shared_skill_contract.py` | harness unit | The shared skill contract, driven through the harness with deliberately broken fixture skills - the only negative controls the harness currently has. |
| `tests/test_sensitive_redaction.py` | safety | Redaction: vendor tokens and private-key blocks are masked in both plain text and JSON, the structure and key context survive, an unterminated key block is masked through end-of-file, and no path echoes the secret it masked. |
| `tests/test_review_package.py` | script unit | The review-package builder: refs that start with a dash or contain a separator cannot inject a file or create a directory, and a persisted diff has high-confidence secrets redacted. |
| `tests/test_eval_path_safety.py` | safety | Path traversal across the eval runners: slugs, fixture trees and frontmatter names reject parent and separator forms, absolute paths, and nested symlinks. |
| `tests/test_release_distribution.py` | release | General committed-source archives and deterministic public projections: members, byte/mode/rebuild verification, archive gate logs, golden general digest, preserved identity/listing rules, and public lifecycle exclusion. |
| `tests/test_release_ledger_docs.py` | release | The release-evidence ledger format and the historical rows it must keep byte-exact (skipped where the historical blob is absent, as in a shallow clone). |
| `tests/test_multi_platform_portability.py` | portability | All-five manifests, source/archive hook dependency checks with negative controls, and real Grok/Kimi/ZCode relocated handler execution; native lifecycle remains separate. |
| `tests/test_kimi_packaging.py` | runtime adapter | Kimi manifest, custom marketplace schema, inline hooks and runtime boundaries. The skill instructions name plugin skills `agentic-sdlc:<skill>` (Kimi Code 2.3.0) and send each runner role card to a new `Agent` by its bare role name, never resumed or forked. |
| `tests/test_grok_packaging.py` | runtime adapter | The experimental Grok CLI adapter: manifest, local marketplace entry, and hook wiring narrow enough that a failure cannot silently widen; the runner's Grok engine is a tracked file. When `grok` resolves, `grok plugin validate` runs in a disposable profile (temporary `GROK_HOME`/`HOME`/`USERPROFILE`, allowlisted environment, working directory outside every repository). |
| `tests/test_zcode_packaging.py` | runtime adapter | The experimental ZCode adapter: manifest, root marketplace entry, and hook wiring, including the claims its README is allowed to make. The workflow launch tool is named where the runner's card prints it and in the adapter docs, with the explicit-request and Auto-mode rules. |
| `tests/test_loop_engine_parity.py` | engine parity | What the three native engines of the spec/plan loop must agree on with `flows/loops/spec-plan.json`. The Claude and Grok engines run the rounds themselves: every mode with its roles and author modes, the default 3 and hard cap 5 rounds, the runner's file names, `draft-check` before the critic and `ingest-draft --assemble` at the end, the issue key target, category and where, and an engine id the runner knows. The ZCode script drives the runner's own loop (`next --engine zcode-dwf --json`, `loop-record`) and runs neither `draft-check` nor `ingest-draft`. The Claude and ZCode slug checks are the resolver's `SLUG_RE`, and the Grok check also takes a trailing hyphen (`demo-`). The harness resolves every role the JS and Rhai engines dispatch, and each loop role's file exists. |
| `tests/test_zcode_driver.py` | engine | The ZCode driver of the spec/plan loop (`workflows/zcode/spec-plan-draft.dwf.ts`). Static pins: the header declares `slug`, `pluginRoot` and `python` as required and `maxRounds` as optional, the runner runs by argv through `world.run` (`next --engine zcode-dwf --json`, then `loop-record`), a new actor is made inside the card loop and is the only `agent()` call, phase names are literals, and no file is written. Under a type-stripping `node` (22.18 or later) the driver runs against the real runner: a clean loop and a revised one are ingested by the runner with a new actor per card, a refused critic answer is asked again until the runner halts and nothing is ingested, and invalid args throw before the runner runs. Skipped without such a `node`. |
| `tests/test_cursor_adapter.py` | runtime adapter | Cursor manifest, portable copy/update/uninstall, and relocated hook replay. The manifest's agents are `cursor/agents/`, one mirror per shared role with the same body, name and description, `model: inherit`, and `readonly: true` with `permissionMode: readonly` exactly on the roles without a writing or shell tool, and the mirror equals the `scripts/project_roles.py --target cursor` projection byte for byte (drift gate). Before a shell command the launcher denies when the guard crashes or answers with anything but a JSON object, allows on empty output, keeps other events failing open, runs the guard from its own folder when the project folder is gone (so `cd ..` is not locked out), and denies cmd.exe tree deletes through the real guard. It does not start the Cursor IDE. |
| `tests/test_antigravity_packaging.py` | runtime adapter | The experimental Google Antigravity adapter: the manifest against the agy plugin schema (documented keys only, `version` equal to `VERSION`, `logo` present), the `build_release.py --antigravity` package (manifest and root `hooks.json` from `.antigravity-plugin/`, the hook launcher and its closure only, agy agents equal to the generated projection, no `commands/`, Cursor files or other runtime manifests, `--verify` infers the kind, byte-identical rebuild), `<runtime-root>` resolution across every skill and contract file of the extracted package, and the date-free adapter wording in the docs and skills. |
| `tests/test_agy_adapter.py` | runtime adapter | The Antigravity hook launcher `hooks/agy-launch.mjs` and `.antigravity-plugin/hooks.json`, replayed with sanitized payloads from a live agy 1.5.14 session (`tests/fixtures/agy/`): a destructive `run_command` is denied, a write or edit carrying a secret is allowed with a reason, SessionStart injects the bootstrap as `injectSteps`, Stop continues only under `AGENTIC_WORKTREE_SCAN_BLOCK` with a finding and no active continuation; a crashed, hanging or non-JSON guard and an unreadable tool call deny on PreToolUse and answer `{}` elsewhere; payload text never reaches a shell; the fixtures hold no local path, id or environment name. It does not start agy. |
| `tests/test_project_roles.py` | runtime adapter | `scripts/project_roles.py`: the Cursor projection reproduces the committed `cursor/agents/` byte for byte and `--check` fails on a drifted, missing or extra mirror; the Antigravity projection emits YAML-list agy tool names in a fixed order, `inheritMcp: false` on read-only roles and the body unchanged, and refuses an unknown Claude tool. |
| `tests/test_zcode_hook_output.py` | runtime adapter | ZCode-mode hook output for every wired script: under the runtime's two documented detection mechanisms (injected `ZCODE_PLUGIN_ROOT` env var, literal `--zcode-runtime` argv marker) each emission path carries only documented keys — decisions as `hookSpecificOutput`, warns as `additionalContext` — with Claude-mode pins that the advisory `systemMessage` channel survives on every other runtime. |
| `tests/test_process_owner_policy.py` | process | The coexistence context actually delivered to a session - not model compliance and not hook installation, which are separate concerns. It also pins the SessionStart line that the pipeline owns every step inside an active run, and the once-per-run `dispatch-strategy` row. |
| `tests/test_evidence_persist.py` | process | Where the Final Implementation Report is persisted for a per-package work item, and that a re-run resolves to the same single canonical path. |
| `tests/test_evidence_tracking_gate.py` | process | The evidence-tracking gate and the filesystem detectability of a new per-package plan, which `git status` alone cannot show for a gitignored artifact tree. |
| `tests/test_artifact_path_prose.py` | docs | That the doc set describes the dual artifact layout and the evidence role consistently, and claims no detection route that does not exist. |
| `tests/test_harness_negative_controls.py` | meta | Every failure key the skill harness can emit is shown to FIRE: a fixture tree with one deliberate defect produces that key, and the same validator on a clean fixture produces nothing. A key with neither a control nor a recorded reason fails the inventory gate. |
| `tests/test_gate_composition.py` | meta | Each suite runs once in a gate run and each reported key names what was measured: `check_all.py` collects only the validator suites it names, those patterns match real files, and every `tests/test_*.py` is still covered by a documented gate command - so narrowing one command can never orphan a file. |
| `tests/test_validator_resolver_parity.py` | meta | The two tools that validate a work package agree on what a valid one is: `validate_artifacts.py` (the gate the skills run) and `resolve_work_package.py` (which rejects the artifact later) must require the same frontmatter keys and accept the same statuses, and report the same plan-kind codes, `spec_none_requires_specless_flow` included. The validator mirrors rather than imports the resolver, so this test is what stops the two copies drifting. |
| `tests/test_validator_cli_unchanged.py` | script unit | Characterization of the validator CLI: two specs with equal content under different layouts must produce the same verdict. |
| `tests/test_strict_flow_evidence.py` | flow evidence | Offline strict flow-evidence derivation: what counts as a step having run, and the characterization pairs that separate a real signal from a jointly-empty comparison. |
| `tests/test_br6_case_table.py` | guard regression | The shared shell-attribution case table: schema, row coverage, and parity between the Node and Python implementations that read it. |
| `tests/test_grok_rhai_workflows.py` | runtime adapter | Structural checks of the experimental Grok Rhai scripts' metadata, referenced agent types and completion accounting. Short verification coverage is counted before confirmed/dropped classification. The runner's Grok engine (`workflows/grok/spec-plan-draft.rhai`) is pinned to the Claude engine's behaviour: its meta name is its file stem, it reads every launch arg, its author and critic run read-only and its scribe executes, every agent result is checked for `success` (no `== ()` checks), `draft-check` runs before the critic and `ingest-draft --assemble` ends it, the stop rules and issue keys follow the runner (Python whitespace and casefold, no upper-casing), a refused critic answer is asked for once more, its modes table equals `flows/loops/spec-plan.json`, its result is small, and no Rhai reserved word is used as a name. These checks do not execute the scripts in a native Rhai runtime. |
| `tests/test_multi_lens_review_workflow.py` | workflow behaviour | Runs `workflows/multi-lens-review.js` under the runtime wrapper with stubbed agents: missing finder/verifier answers remain incomplete or unverified. Majority-dropped findings retain their classification but missing requested votes keep complete=false in both presets; all requested valid votes restore completeness. Skipped if `node` is absent. |
| `tests/test_light_flow_audit.py` | skill contract | The `safe-refactor` audit path: `implementation-control` and `implementation-auditor` grade the Goal Lock for that one flow, and every other flow without a spec/plan keeps the block. |
| `tests/test_pipeline_zero_delegation.py` | skill contract | Pipeline v2.1 zero-skill delegation: the four work-type `references/core.md` files copy their skill's depth blocks byte-identical, keep the moved core steps and sections, and hold none of the envelope; both entry points load them; the pipeline names no focused skill as a call target, dispatches `security-reviewer` and `implementation-auditor` directly, calls `dispatch-strategy` once and records an approval receipt; a literal sweep bans stale delegation wording from the pipeline, its read set and the docs. Static text checks: a drift gate, not proof that a model follows the text. |
| `tests/test_pipeline_eval_regressions.py` | skill contract | The text fixes from the first live 0.6.0 run (52a2ad1). The `spec-plan-author` and `spec-plan-critic` roles name every heading in `validate_artifacts.REQUIRED_SPEC_SECTIONS`, and the spec and plan templates open with the keys in `FRONTMATTER_REQUIRED`; both expectations come from the validator's own constants. The pipeline states how the artifact is saved: frontmatter, `reviewed`, and the file-edit tool. The call-order guards of the pipeline and of six focused skills name the activation for a runtime without a `Skill` tool. A missing mechanism continues on the degraded path, and an instruction not to publish does not forbid the work branch. Static text checks: a drift gate, not proof that a model follows the text. |
| `tests/test_sdlc_foundation.py` | runner unit | The `sdlc` runner's base modules (`scripts/sdlc_runner/`). Atomic LF/UTF-8 writes that fail with a named error instead of hanging or leaking a raw `OSError`; strict UTF-8 reads; slug and work-id rules, including Windows device names; program resolution that takes only absolute `PATH` entries outside the project; the package lock (exclusive, stale-break, a hashed host, pid reuse; the lock records its holder's PID space, and a recent lock whose holder died in this runner's own PID space is broken at once, while a lock from another host or PID space, or one that records no space, waits for its age); hash-chained logs that detect an edited, reordered or truncated line; a frontmatter reader that reads a 25-file corpus exactly like `validate_artifacts.py`; and the JSON Schema subset with ECMA-262 `pattern` semantics. |
| `tests/test_sdlc_mask_parity.py` | runner unit | The runner's stdlib masker (`sdlc_runner/mask.py`) is a faithful port of `hooks/secret-patterns.mjs`. Labels, order, regex sources and value groups are pinned against the `.mjs` text. Every pattern family masks its sample from `tests/fixtures/mask-samples.json` and leaves benign text alone, including the environment passwords `DB_PASSWORD=` (also behind a prefix such as `MYAPP_`), `PGPASSWORD=`, `MYSQL_PWD=` and `AWS_SECRET_ACCESS_KEY=`, and credentials in a URL's userinfo (an empty user included). Code identifiers such as `hashed_password = ...`, `POSTGRES_PASSWORD: postgres`, a templated URL password, a user-only URL, a host and port, an `@` in a URL's query or fragment, and a `_HASH` key stay unchanged. When `node` is present, the output is byte-equal to `redactSecrets`; without `node` those two tests are skipped, never passed. A growth-ratio test keeps masking linear. Long lines with many prefix hits sharing one value run are covered by `tests/test_audit_residuals_r2.py` (R2-e), which also checks them against Node. |
| `tests/test_sdlc_git_fingerprint.py` | runner unit | The runner's git facts, fingerprints and probes. `git` runs hardened (no hooks, fsmonitor or inherited `GIT_DIR`, and never a `git` planted inside the project). Changed paths list renames, copies and untracked files, and leave out the package folder in any ASCII case. Fingerprints are equal across CRLF/BOM, never follow a symlink, and tell undecodable bytes apart. The glob translator and test classification are covered, the no-git walk enters no symlink or junction, and probes survive a failing detector. Real temp repositories; the junction case runs on Windows only. |
| `tests/test_sdlc_manifest.py` | runner unit | The runner's JSON flows (`flows/`). `_shared.json`, every flow, the spec/plan loop definition and the seven schemas validate, and the schemas stay inside the runner's schema subset. Every flow starts `strategy` then `context`, and the step orders match a literal table of the design. The drafting steps match the hybrid spec/plan design step by step (the intent step and its design check, the spec with sources, the one fresh reader of the spec, the spec and plan gates, the plan with or without a spec, the bug plan), no drafting step but the loop's draft reads `feedback.jsonl`, and the loop's draft and review gate run only under `--option loop`. The validator rejects each malformed manifest at the exact pointer, and each rejection has a clean twin. The run allowlist admits and refuses a fixed set of argv lists. The escalation lattice has no cycle and carries work types. The real manifests name no missing step file (the explicit list is empty since the step files exist). |
| `tests/test_step_files.py` | step files | The step files the manifests name (`skills/*/steps/*.md`), which every card prints after its header. Each one exists and is named by a manifest, names no skill and no flow, has no runtime-specific branch, stays at most 120 lines, and carries every report header, verdict line and run label its checks need. Rendered with the real card header of every flow and work type, each card fits the 8000-byte budget without a cut. |
| `tests/test_sdlc_run.py` | runner unit | `sdlc run` (`sdlc_runner/runexec.py`) drives a fake allowlisted test runner in temp git repos; no real test runner and no paid CLI. Commands are resolved and unwrapped against the allowlist; shell syntax, denied flags (abbreviations included), `@` files and denylisted `--env` keys are refused; Windows `.cmd` shims run quoted through `cmd.exe /d /s /c`. A RED is valid only when no source changed since start and a test actually failed; launcher failures and zero-test runs are invalid. The masked output tail is capped. The lock is released while the child runs. A timeout kills the whole process tree. `started` precedes `finished`. Signal handling is POSIX-only, so two tests skip on Windows. |
| `tests/test_sdlc_engine.py` | runner unit | The runner's state, checks, `next`/`card` engine and flow operations (`sdlc_runner/{state,checks,engine,flowops}.py`) on a fixture flow (`tests/fixtures/sdlc/engine.json`) in temp git repos, through the in-process CLI; the only program started is the guarded fake `pytest`. `start` needs `--risk` and `--form`, refuses light with high risk or for `full`, needs `--risk-reason` when the request names a high-risk surface, refuses a second flow on a slug, and records `dirty.json`, or a walk `baseline.json` without git. Steps advance when their checks pass, are skipped once with a reason, freeze `applies_when`, go stale when an input changes (never a run_once step) and count again only on new evidence. The visit, transition, no-progress and fix-round caps halt; waits and `card` count for nothing, and `card` writes nothing. The runner stamps the spec and plan frontmatter before validating and again at the end of the call, and a status it did not write fails the check. A corrupt `state.json` exits 2. `escalate` moves only up the lattice and keeps `strategy.json` and the transition counter; `halt`, `resume` (raising a cap needs the user's quote) and `abandon` work; `external` is limited to the intent and draft steps, and an external draft needs the package's `spec/<id>.md` and `plan/<id>.md` (`external_artifacts_missing`); a full run ends `state=complete`. A card's command lines (`then=`, `confirm=`, `launch=`) read back raw with a Windows interpreter path, so the tests read cards the same way on every OS. The wave B handoffs are pinned too: the `plan` flow imports only an approved spec, a check outside its `work_types` passes, `resolver_ok` without a plan resolves by branch, the run's state merger writes only `red`, and the fix-round cap counts in-visit re-reviews and stale re-entries. The real flows ask first: the feature flow writes a spec, its reader and its gate only with `--option spec` (a light run keeps no reader and no gate), the plan flow runs its intent step only without an imported spec and then plans spec-less (`spec: none`, `flow: plan`), a loop run without a spec is refused, the bugfix flow plans the bug with its own criteria, `--option loop` keeps the loop's draft and review in place of the new steps, a design change reopens the spec, its reader and its gate (or a spec-less plan), a plan reject leaves the spec alone, and escalating a spec run to feature keeps its approved spec, check and gate. |
| `tests/test_sdlc_cli.py` | runner unit | The runner's command line and cards (`sdlc_runner/{cli,card}.py`). A usage error exits 2 with one `error=` line; every command ends with `state=<state> chain=<12 hex>`; the loop commands refuse on a flow without a loop step; a `run` that cannot be recorded prints its error, and a signalled run's exit propagates. A copy of the runner in a folder named `plug in ğ` prints a `then=` command that runs as printed. A 20 KB step file is cut to the 8000-byte budget with the path to the rest, and a header that alone is over the budget keeps the card's frame and says where to read the step. Decision points, critic notes and a user's halt reason appear only after the data line. `status --json` has a fixed shape and `status --brief` prints one line per active package. Optional imports: an import marked optional may be left out at `start`, one that is given is read like a required one and its status is still checked, a required import is still refused when missing, an optional import is refused when an applying step needs it and not needed when the reading step is skipped, and a step that reads it as optional needs no file. Two-gate cards: a wait gate card names its gate and its artifacts, and the claim card lists the author's calls. A gate over the spec, or over a spec-less plan written with sources, lists a `criterion` item for each acceptance criterion with its sources as written (none for an untagged one) after the reader's items, and its first line names them; a long list is cut inside the data budget after those items; the gate of a plan with a spec, of a bug plan and of the loop lists none and keeps its card byte for byte. |
| `tests/test_sdlc_strategy.py` | runner unit | The strategy step (`sdlc_runner/strategy.py`). The default map follows the runtime rows of `flows/_shared.json`: no runtime defaults to a workflow engine for the spec and plan keys, every one gets the runner loop, and an engine override needs a reason on every runtime (an engine runs only on the user's explicit request), on every key of ZCode's `explicit-request` row; a runtime without sub-agents degrades the fresh-context gates, and only the keys of steps that apply are covered (the spec reader's key only where the reader runs, the loop's draft keys only under `--option loop`). `strategy_ok` needs a reason for every override, keeps every mechanism within the declared capabilities, never lets a mandated fresh-context key run in the main loop, and allows an inline fallback only when sub-agents are declared `no` or `denied`. `strategy confirm` writes `strategy.json` and logs it, refuses an invalid map and a second confirm; the step never goes stale; cards print the resolved mechanism and its degradation; `escalate` adds only the missing keys, each within the declared capabilities. |
| `tests/test_sdlc_gates.py` | runner unit | Gates, questions and notes (`sdlc_runner/gates.py`) on the fixture flow's review gate, and on a two-gate fixture where each document has its own gate (`spec-review`, `plan-review`) and its own lifecycle: `approve` re-validates the drafting steps, pre-approval is refused while a reader question is unsettled and allowed with author's calls, a quote approves each gate once, and a reject at the spec gate reopens the spec, not its reader. The gate card prints the fingerprint and reply commands that run as printed. `approve` refuses a wrong fingerprint and a reply with no recorded wait, and pre-approval needs a quote of at least 8 characters that occurs as whole words in the stored request (NFC, case-folded, whitespace-collapsed; a UTF-8 quote file works) with no blocking residual note and no decision point without a recommendation; a degraded critic is allowed and recorded. An edited approved spec reopens the gate, and halts the run once implement started; tasks appended to a pre-approved plan continue, a replied approval does not. `reject` reopens the draft with the feedback; `ask` is limited to the step's `may_ask` and waits until `answer`; `note` records a degraded capability and a background task. On the real flows `reject` prints `feedback=F<n>` (the record's `seq`), and a criterion of the spec or of a spec-less plan added on that change request cites it: an unknown record fails the step and the re-check at `approve`, and the spec and plan checks know only the reject records of the gates over their file. |
| `tests/test_sdlc_speccheck.py` | runner unit | The fresh reader of a spec (`sdlc_runner/speccheck.py`, the `settled` check, `flows/schemas/check.schema.json`, `agents/spec-builder-check.md`) on the fixture flow `tests/fixtures/sdlc/flows/speccheck.json`; no paid CLI. A step with a `role` prints a staged card (role, role file, prompt, write path, the runtime's freshness rule, the inline rule when the mechanism is degraded), and the read-only `card` stages nothing. `check-record` runs only in the `spec-check` step, validates the reader's JSON, writes `spec/<id>.check.json` with the spec body fingerprint and the reader's freshness, may replace the record within one visit until the first resolve (then `check_already_resolving`), numbers every record after the highest id the file ever held (`issued`), and starts a new record in a new visit (a changed `design.md`, even with the same answer) that keeps the earlier visits' settled questions with their settlement; a check file written without `issued` and per-question `visit` still reads, settles and carries. `check-resolve` settles `answered`, `minor` and `theirs` (exactly one of an answer of a question asked during `spec-check`, or an author's call), and refuses an unknown or settled id, an empty resolution and an answer from another step. A hand-edited settlement that `check-resolve` would not record (no resolution, `theirs` without exactly one of an answer and an author's call, `minor` that is no author's call) is `check_invalid`. The reader's questions and each resolution are masked in the file and on the cards. An empty question list is settled, and editing the spec after the check keeps it settled. |
| `tests/test_sdlc_loop.py` | runner unit | The runner-driven spec/plan loop (`sdlc_runner/loop.py`) on the real `feature` and `bugfix` flows under `--option loop` (after the intent step's design, which reaches the brief): the brief and role prompts are staged inside the package (for a Claude or Grok workflow every prompt of the visit, again after an escalation that changes the loop mode; for the runner-driven loop and the ZCode launch only the current card's), the critic card reads the brief before the drafts and the validator file, role files fall back to the public layout, and each runtime gets its card (Claude `Workflow`, a staged Grok script with its sha256, the ZCode workflow launch by path, role cards with the runtime's freshness rule, a JSON machine card). On every runtime row a role card fits the 8000-byte budget and names that row's freshness rule; an author card names a decisions path and asks the caller to save the draft's decision points there, and those points reach the sidecar. Roles run author-spec, author-plan, critic, revise in round order (bugfix: plan only); `draft-check` runs before each critic; the loop stops clean only with a clean critic and a clean validator, on repeated issue keys, or after the final critic at the round cap, and halts after two malformed critic files. `loop-record` validates the critic JSON and the current role; `ingest-draft` writes the frontmatter, the body and the sidecars the resolver accepts, refuses an invalid or mismatched result, a result its round files do not back, an engine the loop does not run, a fresh critic claim for a critic the runner recorded as degraded (an honest degraded claim is kept), a second ingest in one visit and a package that is not active, and assembles a native engine's files only when they show the stop its `loop.json` claims; a linked `draft/` folder is refused; a reject starts a new loop visit. |
| `tests/test_sdlc_flows.py` | runner end-to-end and packaging | The real `feature` and `bugfix` flows run from `start` to `state=complete` through the in-process CLI in temp git repos. The test plays the model: the context report, each loop role's file, the gate reply, a work branch, RED and GREEN through `sdlc run` with the guarded fake test runner, then the security, audit and claim reports. The runner stops the loop and ingests its own `loop.json` and `result.json`, decision point included; a hand-written result after that is refused. Every step is entered and done once, in order, and the logs verify. A second plan in the package makes the real resolver refuse it, and the audit waits on `resolver_ok` until it is gone. The bugfix flow drafts only a plan (`spec: none`, `flow: bugfix`), which the real resolver accepts. A security review that keeps failing halts at the fix-round cap; the same failing report read twice is not a re-review. The audit step completes only when the one line under `## Final Decision` is `allow-final`. A Codex run without sub-agents is refused until each fresh-context key has its inline fallback, refuses a hand-written result that calls the inline critic fresh, records the degraded critic up to the approval, and still completes. Without the loop, the feature flow runs its main-loop path to `state=complete` with and without a spec (the design, the spec and its fresh reader with a settled question, the spec and plan gates, a plan with its own sourced criteria when there is no spec), the real resolver accepts both packages, and the claim card lists every author's call; the `full`, `spec` and `plan` flows run to `state=complete` on the same path. An intent given to another plugin (`sdlc external intent`) does not block the spec gate, which still checks the spec, and an intent redone in the package after that is checked again at `approve`. After a design change the reader's earlier settled question keeps its id and settlement while the new question takes the next id, and a question still open when the design changed is dropped without its id being reused. A guard on `subprocess.Popen` lets only git, the fake test runner (through `cmd.exe` on Windows) and runexec's `taskkill` start, and a test proves it refuses anything else. The release archive and the public skills-only archive, both built from HEAD, carry `scripts/sdlc.py`, every `scripts/sdlc_runner/` module and every `flows/` file with the committed bytes, plus the helpers and contract excerpts the runner reads. Each loop role's file is in `agents/` in the release archive and in `skills/using-agentic-sdlc/references/roles/` in the public one, which has no `agents/`. The extracted runner loads every flow and loop definition from its own root, resolves each role file in that package's layout, and `status` runs. The public projection leaves plugin-root references and links to `flows/` and the runner unchanged, still marks a source-only path, and its runtime guide names the runner and `flows/`. |
| `tests/test_sdlc_roles.py` | role contract | The spec/plan loop's roles are read against the files they serve. `spec-plan-author` has one section per author mode of `flows/loops/spec-plan.json` (`spec`, `plan`, `bugfix-plan`, `revise`). Plan mode derives every task from the spec, which in the joint loop is not yet approved; revise mode names its inputs, and every mode addresses gate feedback. Decision points use the runner's fields, come before the first task and are listed again every round. `spec-plan-critic` has a non-empty audit section for each loop mode, checks the fit between spec and plan, reads the brief, and repeats the validator's errors and strict warnings. Its output lists the fields of `flows/schemas/critic.schema.json`, and each field's own line names that field's values; the verdict line names the runner's blocking severities and kinds, `coverageCheck` is one string, and a mode without a spec targets only the plan. The headings that bugfix-plan mode names pass the validator's own bugfix-plan checks, and the critic reads a bugfix plan's criteria from the plan. Both roles say their last message is the result, write it to the card's write path when they can write files, keep an unresolved plugin root out of the result and keep only read-only tools. `draft-scribe` has exactly Read, Write, Bash and PowerShell and allows exactly the subcommands that `sdlc_runner/loop.py` registers. The auditor grades a spec-less plan of a bugfix, feature or plan run against its own criteria (only a bugfix plan states a bug), its Cursor mirror says the same, and the audit step file names the drafting rows and the `N/A (criteria in the plan)` Spec row. Contracts 02, 03 and 07 describe the hybrid path: the spec follows the intent step with criterion sources and its own gate (`spec-review`), the plan has its own gate (`plan-review`), the joint loop is the opt-in path, and a spec-less plan of the bugfix, feature or plan flow carries `spec: none` and its flow, with no pipeline step number. |
| `tests/test_spec_plan_draft_workflow.py` | engine | The Claude Code engine of the spec/plan loop (`workflows/spec-plan-draft.js`) on the runner's launch args. Static pins: the launch name, every launch arg, the author, critic and scribe agent types (the scribe at low effort), `draft-check` before the critic, `ingest-draft --assemble`, the engine id, the loop caps and the label prefixes; its modes table equals `flows/loops/spec-plan.json`. Dry runs under `node` with a stubbed `agent()`: the clean, no-progress and max-rounds stops with a final critic (clean and no-progress win at the round cap), `maxRounds` from the args with the loop default, each mode's authors, each reviser's draft written before the next role reads it, a blocking validator or a blocking issue is never clean, issue keys compare as a set and equal the runner's `issue_key` on Turkish, German and Greek letters and Python's whitespace, a critic answer the runner would refuse is asked for once more and a second one throws, the decision points of the ingested drafts reach `loop.json`, every call has a schema and only the scribe runs at low effort, role prompts name the staged prompt files, commands run the plugin root's runner on the package's project (a drive root as `D:/`), paths with characters a double quote keeps literal pass, the scribe gets the exact text behind a marker the text does not contain, a null agent, an empty draft, a scribe refusal or a failed `draft-check` throws a named error, the ingest's exit code decides `ingested`, invalid args throw before any agent, and the Grok launch's `agent_budget` equals the number of agent calls of the longest loop for every mode and round cap. Against the real runner: every prompt the engine names was staged, and its clean, no-progress and max-rounds loops are ingested. Skipped without `node`. |
| `tests/test_audit_cg.py` | guard regression | The command-guard findings CG-1 to CG-11 of the 2026-11-18 bug audit, each hook run as a subprocess in a temporary repository with the system and global git config switched off. `scan-commit.mjs` scans what the same command stages (`git add f && git commit`, `-a` inside a `bash -c` payload, commit pathspecs, `-o`, untracked files an `add` stages), a top-level `git apply` patch and a `-F -` heredoc message, and an oversized staged file is skipped and named while the others are still scanned. The destructive guard denies unique option prefixes, `clean.requireForce=false` (also when it is unknown or read from another config), inline and stored git aliases, `env -S`, brace expansion, `exec -a`, here-strings and the PowerShell forms. Every heredoc body line is a command again (base behavior): only the exact whole-command shapes (`cat > PATH <<'D'`, `cat >> PATH <<'D'`, `cat <<'D' > PATH`, `tee PATH <<'D'`, and `git commit -F - <<'D'`, whose body is still scanned as the message) keep their body out, never for PowerShell, never inside a `bash -c`/`eval` payload or a `!` alias text, and never when an earlier body line starts with the delimiter or the command holds `\r` or `\0`; the `git commit -m "$(cat <<'D' … D)"` idiom is read line by line, and the git guards read the other bodies as commands. A quote inside a bash or PowerShell comment (`#`, `<#…#>`) cannot hide the next line, and a quoted `$(…)` inside a `{…}` word is still inspected. The three guards share one wrapper table (`env -u`, `timeout --kill-after`, `xargs -L`). `branch-guard.mjs` reads through redirections, command substitution and function bodies and protects `heads/main`; past the alias cap a commit is scanned as `commit -a` and the push is still judged. `scan-commit.mjs` reads the commit repositories' staged diffs first and reports their findings before anything else, denies when a staged read is cut, skips staging directories that do not exist, merges staging reads within its process, time, text and untracked-file budgets, scans an unresolved alias's target repository as `commit -a`, reads a named file only as a regular file and only up to 5 MiB (never a FIFO, a device or an endless procfs file), does not read the paths of `rm`, `mv` or `restore --staged`, and does not crash on huge word lists. Brace expansion, the wrapper walk, the resolver budget, the option checks and the shared lexer (a CR is no blank before `#`) stay linear or bounded. Skipped without `node` or `git`. |
| `tests/test_audit_sw.py` | guard regression | The secret, write and git-hook findings SW-1 to SW-6 and SW-8 to SW-10. Anthropic, OpenAI project/service/admin, GitLab, npm and Hugging Face keys, `ASIA` key ids, prefixed `*_API_KEY=` assignments and PGP private key blocks are found and redacted by the Node patterns and `mask.py` alike, with clean controls; the patterns and the Codex write guard stay linear on long single lines. A JWT after a bare `-` or a long chain of dashed words is found by the single `jwt` entry, a key followed by padding is not read as degenerate, a real key inside a degenerate span of its own kind is found, and the glued-token boundary re-scans and new shapes stay linear in Node and Python. Raw-mode redaction decodes JSONL lines, leaves unchanged lines byte-identical, masks a numeric value and a shadowed duplicate key, keeps a number's source text when a line is rewritten, masks `$…` and `%…%` passphrases but keeps placeholders under a password key, and falls back to text redaction for a deeply nested line. `prepare-commit-msg` ignores only the old side of git's own `git commit -v` diff below the scissors line (typed diff-like lines are scanned), honours a custom comment character and names the bypass that works. An oversized file is skipped and named by the pre-commit hook and the Stop scan; the fallback stops at its deadline, names the rest and keeps unmerged paths. The write scanner reads `NotebookEdit`, never rescans the old file before a Cursor write or on a delete, and the advisory Stop scan runs when `stop_hook_active` is set. Credential-shaped values are built at run time. |
| `tests/test_audit_fh.py` | guard regression | The flow, evidence and claim-hook findings FH-1 to FH-10, SW-7, the SW-9 wiring and SK-10, over synthetic Claude transcripts and Codex rollouts. Claude flow guards see Bash and PowerShell source writes, and the current call is never its own evidence; test paths are classified relative to the project; a project named through a symlink is gated pre-edit and at Stop, with a linked, resolved or missing payload `cwd`, a link into `tests/` hides no source edit, a test file reached through a link stays exempt, and a very long path is classified within the timeout (the symlink cases skip on Windows); a heredoc body or a comment is no test run; Claude Stop validates only this session's spec and plan work ids; Codex readers recognise quoted and leading redirect targets, `*** Move to:`, a Bash `apply_patch` heredoc and quoted, escaped and CRLF heredocs; the completion-claim gate counts only an exact, non-errored `Skill` call, and the claim patterns read inflections, Turkish phrases, questions, conditionals and scoped negation alike in both guards; wrapped and launched test runners count; a sidechain `Skill` call activates no flow. Round-two rows: pathological redirect, heredoc and pipe shapes keep both flow guards fast and the shell readers linear, and a prior command over the analysis cap is never evidence; a CR line does not end an LF heredoc nor a plain line a CRLF one; `..` paths are resolved before they are classified; a claim is hypothetical only through its own clause, and a `;` or `:` ends the reach of an `If …` opener; a shell command over the analysis cap is never test evidence but keeps the Stop obligations as a possible source edit, while a short command that writes nothing stays silent. Skipped without `node`. |
| `tests/test_audit_rn.py` | runner unit | The runner and loop-engine findings RN-1 to RN-10, SK-5 and SK-11, on the harness of the engine, loop and flow tests. A security report completes only with exactly one `Verdict:` line reading `Verdict: pass`; a loop that stops with failing drafts halts and `resume` opens a new visit; `ingest-draft --assemble` refuses another engine's `loop.json` and never upgrades a degraded critic; malformed decision points are dropped; an external draft needs its spec and plan; a content-free commit leaves the security step done, while moving a submodule changes the source fingerprint; `branch_ok` fails on a detached HEAD; the ZCode driver takes a trailing-hyphen slug; a dead lock holder in this runner's PID space is broken at once, while a fresh lock from another PID space or with no space is kept until its age, and the lock records the runner's space; where the platform gives no PID space (macOS, simulated), an old lock that names one is broken by its age even when its pid is alive here, and an old live lock that names none is kept, and the dead-holder tests skip on macOS; the implement flows' audit needs `allow-final` under `## Final Decision`; the engines' smoke plans pass the strict plan gate. |
| `tests/test_audit_va.py` | script unit | The validator, resolver, context-probe and eval-grader findings VA-1 to VA-18. A task block ends at the next heading of the same or higher level; fenced headings are ignored and a section runs to the next same-or-higher heading; prose labels such as `Password:` are no secret, while assignments, quoted values, mixed-case values, passphrases of four or more parts, YAML block values and the hooks' new provider formats are; `AC1.1` and `AC1.2` are separate obligations and a duplicate id is an error; a spec without criterion ids fails the `--sources` gate; `## Task N` headings are ordered and `## Task list` is no task; `--mode all` checks the frontmatter; a deep check file is invalid JSON, not a traceback. The resolver survives stray files and refuses nested plans; `detect_context.py` exits 0 on unexpected JSON shapes; a failed `Read` or write is no required artifact; a quoted `status: "approved"` is read; another skill's args do not trigger the target; routing needs the expected skill first; failed behavior, Codex and GLM runs are unmeasured (stub CLIs only). The new regexes stay linear on long lines. The behavior-eval seed's forbidden phrases count only in a sentence that does not negate them, so a correct refusal passes. |
| `tests/test_audit_rl.py` | release | The release and packaging findings RL-1 to RL-10 and the trust-check default id, against temporary package and destination folders only. The Cursor installer refuses a non-empty destination without its receipt and a new path holding a user's file, writes the receipt before copying and rejects drive-letter and symlinked receipt paths; it refuses a managed path replaced by a symlink, and its uninstall does not follow a folder swapped after the check; Cursor and native-lifecycle copies take only committed, shippable files (`CLAUDE.local.md` is private), and a checkout git cannot list fails closed; exclusion class 8 keeps local-only roots out of a build; the release scan decodes UTF-16 and UTF-32 text and always reads UTF-8 too, also behind a UTF-16 mark; the skills-only archive points `agents/` references at its role folder; CI runs `--release-check` only for release branches, tags and a change of `VERSION`; `bump_version.py` versions the `SECURITY.md` line and reads only this plugin's catalog entries. |
| `tests/test_audit_sk.py` | skill contract | The skill-text findings SK-1 to SK-4 and SK-6 to SK-9. Each test reads the text and, where it names a command, runs that command against the real validator or resolver: every spec validation command is `--strict`; feature-build and root-cause-fix save and validate their spec and plan where the resolver looks; contracts 02 and 03 scope their runner-only paragraphs; the pipeline's security lenses are direct `Agent(security-reviewer)` calls; no whitespace check is called a secret scan and `git-safety-check` covers index, worktree and untracked files with exactly pre-approved commands; the router checks the high-risk surface before the focused routes; mind-spark runs after kickoff and the branch checkpoint; plan-authoring documents a spec-less plan command. Static text checks plus real command runs, not proof that a model follows the text. |
| `tests/test_audit_residuals_r1.py` | guard regression | Round 1 of the residuals the f430715 audit left as known limitations (plan `docs/agentic-sdlc/plans/audit-residuals.md`). The Stop worktree scan opens only regular files: a FIFO, a socket or a device reached through a link, named by the untracked listing (a `git` shim adds one) or sitting at the dedup state path is skipped unread and the other files are still scanned; links to regular files are still read. FIFO tests are skipped where `os.mkfifo` is missing (Windows). A literal here-document piped into `git commit -F -` (`--file=-`, `--file -`; quoted, unquoted and `<<-` delimiters), also inside a `bash -c` payload, is scanned as the message; a clean body, `cat -`, `/bin/cat`, a `cat` with a redirect, `echo`, `printf` and the PowerShell tool stay silent. The validator flags an Authorization Bearer token, a URL with a password in its userinfo and a JSON- or Python-quoted `api_key`/`secret`/`password` key, masks the value and exits 1; templates, masks and (D15) lowercase type names or prose words stay clean, the scan stays linear, its bearer, URL and template sources equal `hooks/secret-patterns.mjs` (a drifted literal fails) and compile exactly as `mask._translate` does, and the tracked `docs/agentic-sdlc` artifacts hold no finding. A git call the resolver drops at a budget (past 128 payload statements, four shells deep, past the 64-step alias walk) is reported instead of skipped silently: `scan-commit.mjs` says a commit was NOT scanned and `branch-guard.mjs` says a commit or push was not checked, never as a deny on its own, in exactly one JSON object (also with an unresolved-alias report, and as `additionalContext` on ZCode) that quotes none of the command; within the budgets, and for a long payload without git, nothing new is said. Follow-ups of the round's security review: a commit's own here-document is still scanned when a piped one is attached; the dedup state file is never followed through a link and a linked default state folder is not used; in URL userinfo a lowercase password fires while placeholder words do not; the branch-guard notice maps to `additionalContext` on ZCode. Later review rounds: a piped body rides on its statement (no second queue item; a repeated `git commit -F -` keeps each body), adds no resolver budget (63 piped pairs, a piped shell consumer, a long piped consumer, and a `;`-versus-`|` comparison of what the resolver reaches), reaches a consumer holding a `$(…)`; the skipped-read probe is capped (the cap test fails when the cap is removed) and stops at its first hit (that test fails when the first-hit stop is removed); a repeated piped commit reads its `-F` file once (under a 64 MB heap; it fails when the read-once check is removed); a file used both as the `-F` message and as the `git apply --cached` patch is still denied; and a hard-linked state file is not truncated. Credential-shaped values are built at run time. |
| `tests/test_audit_residuals_r2.py` | guard regression | Round 2 of the audit residuals. Under the PowerShell tool, an apostrophe inside a single-quoted here-string (`@'` ... `'@`, LF or CRLF, blanks before `'@`) no longer hides the next line: the destructive guard denies a recursive `Remove-Item` after it, `branch-guard.mjs` denies a push to `main` under the block flag, and `scan-commit.mjs` scans a commit message after it; the here-string followed by a harmless command stays silent. The Codex write guard's shared heredoc grammar reads a bash delimiter word (`<<EOF-1`, `<<'EOF-1'`, `<<"END.1"`, `<<1EOF`), so the written token is denied, and a body line `EOF` does not end an `EOF-1` body; the grammar stays linear on 24 openers and a 400,000-character run. A push or commit nested in 9 or 64 spaced subshells is read (the wrapper strip has no round limit, equals the old loop's fixed point and stays linear on 512 KiB). `git -C sub -C sub commit` is scanned in `sub/sub`, where real git runs it, and its `-F` file is read there; `-C a -C ../b`, an absolute `-C` and `-C ''` resolve as git does, a payload `-C` redirects no read, and the collected `dirs` stay de-duplicated. `mask.py` checks a value by index, so many prefix hits sharing one long value run stay linear (16 times the line under 40 times the time), and its output still equals Node's `redactSecrets` on those lines. Adversarial pins: the here-string view reaches `pwsh -Command` and `-EncodedCommand` payloads, an `<<EOF-1` source write counts for the Codex flow-order guard, the here-string scan is linear, a payload `-C` never redirects a read, and masked long-hit lines keep no 8-character part of a value. The docs test checks that the Round 2 limitations left the CHANGELOG and `hooks/README.md`. Review follow-ups: a commit run by a shell inside a `!` alias is scanned in the call's `-C` repository, and a nested `!` alias with its own `-C` too, and a write after a heredoc whose delimiter word bash reads differently (an escaped quote or a `$(` in a double-quoted word, `<<-` with a tab-indented terminator, a here-string, a CR in the word) is still seen: the grammar leaves every delimiter word outside its small set unread. An empty quote pair after the word (`<<EOF''`) is still read, so a secret written through it is denied, and an escaped `\<<` opens no heredoc. Audit follow-ups: a secret after an opener the grammar leaves unread (`<<'EOF'X`, `<<EOF$x`, `<<EOF+`, `<<'E F'`) or past the opener cap is denied, a clean one is not, a `pytest` line after such an opener is not a test run while runs before it, after a read heredoc, after a here-string and after `\<<` still count, and both checks stay linear. A secret written on a later line (after `true`, `cd`, `<<<`, `\<<` or a dotted delimiter's body), after `\\<<`, through `<<EOF''` with a `$` in the body, by a second opener on a read opener's line, or by a command after a read opener on its line is denied, clean multi-line commands are not, and `\\<<` or a second opener stops the test-run check. Both readings (the current grammar and 1905c15's): six writes 1905c15 denied (after `<<<`, `\<<`, `<<<<`, a dotted delimiter, a quoted `<<1`, and `\\<<` before an escaped printf) are denied, two runs 1905c15 did not count are not counted, and a write target 1905c15 saw after a quoted `<<1` is kept. The linear checks time the second (1905c15) test-run reading too, and a 500 KiB worst-case command finishes the Codex write scan in under 5 s. Credential-shaped values are built at run time. |
| `tests/test_git_hook_portability.py` | git hooks | The portable git-hook install (R1-e of the audit-residuals plan). The installer writes every file through one LF helper (`open(..., newline="\n")`): no `Path.write_text`, which takes `newline=` only from Python 3.10, and no write-mode open without `newline="\n"` (an AST rule with a negative control); the generated hooks and the ownership manifest hold no CR. Hooks find the vendored scanner (the import closure of `git-hook-scan.mjs`, copied to `agentic-sdlc-scanner/`) from `$0`: after the plugin copy and the repository are both renamed, a staged token is still blocked from the top, a subfolder and (POSIX) a symlinked path, and a clean commit passes; a missing `node` or scanner fails open with a warning that names the cause. The vendored files have their own ownership states (`--check` prints `vendored/<name>=` and a `scanner=` summary: missing, unclaimed, current, stale after a plugin update and refreshed by `--install`, modified, foreign); a modified, symlinked or unknown entry (a planted `no-repository-hooks/`) refuses the install before any write, and a name a later release retires is removed. A lost manifest, an unbound or moved record and a moved repository are adopted; the manifest (version 2) binds the hooks folder relative to the git common folder with POSIX separators, so `--check` and `--uninstall` still work after a move. A recorded hook is replaceable only when it is generator output, so a manifest naming a user's own hook cannot make `--install` overwrite it; 0.7.0's digest bodies and the legacy bodies migrate, and (D2) generator output naming another plugin path is adopted while a one-byte variant stays foreign. `TestLiveWslInterop` runs only inside WSL with `AGENTIC_LIVE_WSL=1` and Windows git, node and Python 3.10+: installs from WSL and from Windows, then WSL `git` and `git.exe` both block a staged token on one `/mnt/c` checkout. Review follow-ups: a crafted manifest makes neither `--install` overwrite nor `--uninstall` delete a user's hook, a version 1 manifest is still read (0.7.0 hooks are recorded and removed by `--uninstall`), a hard-linked hook target is not written through, a FIFO named like a hook does not hang `--check`, a hook run without a folder in `$0` runs no scanner from the current directory, the warnings survive a `\c` in the path, a legacy body whose path runs shell code is not adopted, and an interrupted write's leftover does not block the next install. A hook gets its execute bit before it replaces the old one. Skipped without `git` or `node` where a repository is needed. |

Source inventory tests must exclude generated `dist/`/`build/` archive and installed-cache copies while retaining controls for accidental source copies. External-toolkit negative fixtures must isolate the user's home: a legitimate already-installed fallback is runtime behavior, not a failed identity check. The source gate never installs a toolkit to make a fixture pass.

---

## Skill harness

`tests/skills/harness.py` is the **deterministic, stdlib-only** validation library behind the structure, integration, and fixture tests. It is **read-only**: it parses artifacts and checks wiring, but it never writes files, shells out, or calls a model.

It is the static counterpart to live evals — proving the substrate underneath the skills is intact: frontmatter is parseable, names are consistent, every cross-reference resolves, and every safety guardrail is wired to a real contract/skill/hook text.

### Harness coverage matrix

| Layer | Checked deterministically | Verified only live |
|---|---|---|
| **Structure (A)** | Frontmatter keys, name/dir match, description shape, body length | — |
| **Trigger (B)** | Eval-set well-formedness, target skill exists, positive + negative queries present | Whether the model actually triggers the skill |
| **Procedure (C)** | Core flow skills reference their steps/workflows via golden `must_reference` | Step ordering and runtime obedience |
| **Safety (D)** | Each scenario's guardrail text is wired in a contract/skill/hook | Whether the model obeys the guardrail |
| **Tool-use (E)** | Hook `.mjs` + workflow `.js` parse with `node --check`; Claude/Codex hook configs reference real scripts | Runtime tool decisions |
| **Integration (F)** | Every cross-reference plus `${CLAUDE_PLUGIN_ROOT}` and `${PLUGIN_ROOT}` path reference resolves | — |
| **Regression (G)** | Golden baseline: name + description keywords + `must_reference` | — |

Run the harness standalone:

```bash
python3 tests/skills/harness.py
```

It prints sorted `key=value` lines and exits `1` if any error is found.

---

## Golden references and fixtures

The deterministic layer is driven by checked-in references and fixtures under `tests/skills/`.

| File | Purpose | Format highlights |
|---|---|---|
| `tests/skills/golden/skills.json` | Per-skill regression baseline. `description_must_include` lists trigger keywords that must survive edits; `must_reference` lists cross-references that must appear and resolve. | `{ "skills": { "<name>": { "description_must_include": [...], "must_reference": [{"ref": "...", "kind": "skill\|agent\|workflow\|command\|script\|file\|contract\|hook"}] } } }` |
| `tests/skills/fixtures/safety.json` | Seven unsafe-instruction scenarios. Each points to `guardrail_evidence`: repo files + substrings that prove the guardrail is wired. | `{ "scenarios": [{ "id", "prompt", "category", "expected_behavior", "guardrail_evidence": [{"file": "...", "contains": "..."}] }] }` |
| `tests/skills/evals/<skill>.json` | Live trigger eval fixtures shared by the Claude and Codex runners. | `{ "queries": [{ "query": "...", "should_trigger": true\|false }] }` |
| `tests/skills/routing/using-agentic-sdlc.json` | Router eval scenarios for smallest-sufficient-skill selection. | `{ "scenarios": [{ "prompt", "expected", "escalation" }] }` |
| `tests/skills/behavior/<case>.json` | Behavior eval seeds. Each case gives a prompt and required/forbidden regex patterns. | `{ "cases": [{ "id", "prompt", "required_patterns": [...], "forbidden_patterns": [...] }] }` |
| `tests/skills/procedure/<case>.json` | Procedure eval seeds, including `agentic-sdlc-pipeline.json`, the strict-only `agentic-sdlc-pipeline-gate-stop.json` and `skill-depth.json` (see format below). | `{ "cases": [{ "id", "prompt", "fixture_dir?", "check_artifact_depth?", "required_skills": [...], "required_workflows": [...], "required_runtime_adapters": [...], "required_commands": [...], "required_artifacts": [...], "forbidden_commands": [...], "required_patterns": [...], "forbidden_patterns": [...], "strict?": {...} }] }` |
| `tests/fixtures/transcripts/*.jsonl` | Sample Claude Code stream-json transcripts for deterministic procedure-eval testing. | One JSON object per line — typically `assistant`, `stream_event`, and `result` events. |

---

## Router evals

`scripts/run_routing_eval.py` evaluates `using-agentic-sdlc` as a router, not as a child skill trigger. It checks whether the prompt routes to the smallest sufficient skill and whether only full-envelope/high-risk prompts escalate to `agentic-sdlc-pipeline`.

Live processes use an ephemeral empty working directory by default; `--plugin-dir` selects the
plugin source independently. Running against a real checkout requires both
`--project-root <path>` and `--allow-writable-project`. Persisted transcripts are secret-redacted.

Claude and Codex use different evidence sources, so read the runtime label on every result:

```bash
python3 scripts/run_routing_eval.py \
  --eval-set tests/skills/routing/using-agentic-sdlc.json \
  --runtime claude \
  --runs 3

python3 scripts/run_routing_eval.py \
  --eval-set tests/skills/routing/using-agentic-sdlc.json \
  --runtime codex \
  --reasoning-effort high \
  --runs 3
```

`--reasoning-effort` (default `high`) goes to both runtimes: Codex `model_reasoning_effort` and Claude Code `--effort`, so the profile's own `effortLevel` never decides the measurement; the output prints it as `reasoning_effort=`. `--smoke` runs only the first scenario, so read `scenarios_run=<ran>/<total>` next to `scenarios_passed`: a smoke run reports `scenarios_run=1/15`, not a full sweep.

The fixture format is:

```json
{
  "scenarios": [
    {"prompt": "...", "expected": "root-cause-fix", "escalation": false}
  ]
}
```

A scenario passes only when the expected skill is the FIRST focused route the run reached. A wrong route followed by the expected one fails as `expected_not_first`, and a pipeline route on a non-escalation scenario fails as `over_escalated_to_pipeline`.

Do not combine routing eval results with trigger eval results as if they measure the same thing. Routing evals score the router's classification decision; trigger evals score runtime activation for a target skill.

---

## Trigger evals

Trigger evals measure whether a user prompt causes the runtime to select the intended skill. The fixture JSON is **shared**, but Claude Code and Codex use different runners because their runtime evidence differs.

### Claude Code: `run_trigger_eval.py`

`scripts/run_trigger_eval.py` is a Windows-safe replacement for the external `skill-creator`'s `run_eval.py`. It plants a temporary `.claude/commands/<skill>-skill-<uuid>.md` shim for the query, removes that file and any directory the run created, runs `claude -p <query> --output-format stream-json --verbose --include-partial-messages`, and detects whether the first tool action is a `Skill` or `Read` invocation of the target skill. A `Skill` call counts only by its `skill` field, on the streamed path as on the full-message path: another skill whose `args` mention the target is no trigger. `--plugin-dir` disables the shim and the output reports `command_shim=disabled:plugin-dir`. `--bare` exits 2 before any `claude` process (`error=bare_rejected`), because since 2.1.286 bare mode sends no skill listing ([headless](https://code.claude.com/docs/en/headless), fetched 2026-10-07). The runner also drops `CLAUDE_CODE_SIMPLE` from the child environment.

Default run:

```bash
python3 scripts/run_trigger_eval.py \
  --skill-path skills/agentic-sdlc-pipeline \
  --eval-set tests/skills/evals/agentic-sdlc-pipeline.json \
  --runs 3
```

Safe smoke run (one query, capped timeout, kills the process tree as soon as the trigger decision is known):

```bash
python3 scripts/run_trigger_eval.py \
  --skill-path skills/spec-authoring \
  --eval-set tests/skills/evals/spec-authoring.json \
  --smoke \
  --model haiku \
  --max-budget-usd 0.10 \
  --timeout 60 \
  --plugin-dir . \
  --transcript-dir tests/artifacts/trigger
```

`--bare` is rejected with exit 2 and does not start `claude`. Use real plugin skills only (no command shim): `--no-command-shim`, or pass `--plugin-dir` so the shim stays off.

`--effort <level>` passes Claude Code `--effort`. Without it the profile's `settings.json` `effortLevel` decides, and the output says `effort=profile-default` so such a run is not mistaken for a pinned one.

**Exit codes and the unmeasured outcome.** `0` every query met its expectation; `1` a measured query missed it (`trigger_eval=failed`); `2` `--bare` was rejected; `3` at least one run produced no measurement and no measured query failed (`trigger_eval=unmeasured`). "The skill did not trigger" is a measurement: the model answered, or took another action first. A missing or failing `claude`, a non-zero exit, a stream that ends without a verdict, an `is_error` result or a timeout is not, so such a run is never counted as "did not trigger" and a negative query can no longer pass on it. The output names the query and the reason (`error=q0_unmeasured:runs=2,reason=exit_1`). When a measured query also missed its expectation, `failed` and exit 1 win. The batch wrapper `run_all_trigger_evals.py` labels such a skill `status=unmeasured`, prints `trigger_matrix=unmeasured` when nothing worse happened, and exits 3.

The Claude trigger runner uses a fresh temporary project by default. Running against a real writable
checkout requires both `--project-root <path>` and `--allow-writable-project`. Relative
`--plugin-dir .` is resolved before switching to the temporary project.

### Codex: `run_codex_trigger_eval.py`

Codex does not expose a Claude-style `Skill` tool event in `codex exec --json`, so `scripts/run_codex_trigger_eval.py` checks Codex's route decision as a **local classifier**. It builds a prompt listing every skill name + description, asks the model to return JSON `{"skill":"<name>","needs_dev_flow":true|false}`, and compares the selected skill to the target.

```bash
python3 scripts/run_codex_trigger_eval.py \
  --skill-path skills/spec-authoring \
  --eval-set tests/skills/evals/spec-authoring.json \
  --smoke \
  --model gpt-5.6-luna \
  --reasoning-effort low \
  --transcript-dir tests/artifacts/codex-trigger
```

A run that measured nothing (`codex` missing, a non-zero exit, a `turn.failed` event, no agent message, a timeout) is never graded as "did not trigger": the query reports `unmeasured`, and the runner prints `codex_trigger_eval=unmeasured` and exits 3 when no measured query failed, as the Claude runner does. The experimental `run_glm_trigger_eval.py` follows the same rule (`glm_trigger_eval=unmeasured`).

The Codex classifier uses a fresh temporary project by default so ignored/local checkout files are
not exposed to the model. Selecting a real checkout requires both `--project-root <path>` and
`--allow-writable-project`; the authorization is about project-context exposure, while Codex itself
still runs with `-s read-only`.

### Batch: `run_all_trigger_evals.py`

`scripts/run_all_trigger_evals.py` runs the trigger fixtures for **every skill** in a single matrix and continues after failures so one run returns the full picture.

```bash
python3 scripts/run_all_trigger_evals.py --runtime claude --smoke          # all skills, Claude
python3 scripts/run_all_trigger_evals.py --runtime both   --smoke          # both runtimes
python3 scripts/run_all_trigger_evals.py --runtime both --skill spec-authoring --smoke  # single skill
```

The batch pins model and effort for every row: Claude `--claude-model` (default `haiku`), Codex `--codex-model` (default `gpt-5.6-luna`), and `--reasoning-effort` (default `low`), which goes to Claude Code as `--effort` and to Codex as `model_reasoning_effort`.

#### Runs and majority voting

`--runs` defaults to **3**: each query is sampled three times and `rate = matches / runs` is compared to `--threshold` (0.5), so a positive needs ≥2/3 and a negative needs ≤1/3. This is deliberate — trigger selection is **nondeterministic**, and a single sample (`--runs 1`) reports a noisy 0/1 that hides run-to-run flakiness. Use `--runs 1` (or `--smoke`, which forces 1) only for cheap probes, not for evidence you intend to publish.

#### Reading the matrix honestly (single-run vs best-of-N)

The matrix continues after failures so one invocation returns the **full** picture — read `matrix_passed=N/16` and the per-query `rate` lines, not just the final `trigger_matrix=` flag. Two anti-patterns to avoid when summarizing results:

- **Best-of-N / "run until green".** Re-running only the failing skills and then stitching each skill's best-passing round into one "16/16" summary is **selection bias**: with single-sample queries and enough reruns it converges to all-green even on a noisy classifier. If you assemble a summary across reruns, state that it is a composite and from which rounds, and also report the **single-run** matrix result.
- **Cross-runtime comparison.** Claude and Codex numbers are **not** on the same scale. The Claude runner measures real `Skill`/`Read` tool activation in a live session; the Codex runner is a route-classifier proxy (Codex exposes no comparable Skill-tool event). Compare each runtime against itself over time, not against the other.

### Trigger fixture format

```json
{
  "queries": [
    {"query": "...", "should_trigger": true},
    {"query": "...", "should_trigger": false}
  ]
}
```

Best practice: include **near-miss negatives** (requests that sound related but should route elsewhere) and realistic positives written as natural user prompts.

---

## Behavior evals

`scripts/run_behavior_eval.py` is the layer above trigger evals. It runs a prompt against Claude Code and checks the transcript for required and forbidden regex patterns.

Validate fixture shape without a live model:

```bash
python3 scripts/run_behavior_eval.py --eval-set tests/skills/behavior/completion-claim-gate.json --dry-run
```

Run live when the Claude CLI/runtime is available:

```bash
python3 scripts/run_behavior_eval.py --eval-set tests/skills/behavior/completion-claim-gate.json
```

`--model` and `--effort` pin the Claude Code model and `--effort` level. Without `--effort` the profile's `settings.json` `effortLevel` decides, and the output says `effort=profile-default`.

A run with no answer to grade (a non-zero CLI exit, an `is_error` result, a timeout, a CLI that could not start) is unmeasured, never passed or failed: an "Invalid API key" result once satisfied a required pattern. The output ends with `behavior_eval=passed|failed|unmeasured`; exit 0 passed, 1 a measured case failed, 2 `claude` missing (without `--allow-missing-claude`), 3 some case unmeasured and no measured case failed.

If `claude` is missing, allow the eval to skip instead of fail:

```bash
python3 scripts/run_behavior_eval.py --eval-set tests/skills/behavior/completion-claim-gate.json --allow-missing-claude
```

### Behavior fixture format

```json
{
  "cases": [
    {
      "id": "short-id",
      "prompt": "user prompt",
      "required_patterns": ["regex"],
      "forbidden_patterns": ["regex"]
    }
  ]
}
```

Behavior evals should move toward **transcript JSONL** checks for evidence such as: the intended skill was invoked · the agent did not claim success without verification · required subagents/workflows were dispatched · tests/security/other gates were actually run or explicitly skipped with reason. Do not trust final prose alone; parse transcript/tool evidence where possible.

---

## Procedure evals

`scripts/run_procedure_eval.py` checks more than "did the skill trigger?" It inspects stream-json tool use and optional filesystem artifacts to verify that a workflow used required skills, commands, workflows, and artifacts and did **not** run forbidden commands. For Codex and deferred adapter targets, a fixture can also provide runtime-adapter evidence patterns proving equivalent author -> critic -> revise behavior, artifact save, validator execution, and the adapted gates (for the pipeline: the work-type core read and the `security-reviewer` and `implementation-auditor` roles). The parser accepts Claude stream-json and current `codex exec --json` events (`command_execution`, `file_change`, `todo_list`, `agent_message`), including UTF-16 transcript files produced by some Windows capture paths.

### Modes

| Mode | Command | Use |
|---|---|---|
| Dry-run / schema | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --dry-run` | Validate the eval fixture without running a model. |
| Transcript | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --transcript tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-pass.jsonl` | Evaluate a captured transcript deterministically. |
| Live | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --live --allow-fixture-commit --max-budget-usd 5.00` | Run the prompt through Claude Code in an isolated copied fixture and evaluate the resulting transcript. |

Live mode passes `--effort <level>` to Claude Code when given; without it the profile's `settings.json` `effortLevel` decides. The Claude stream does not record effort, so the evidence packet's `effort` stays `unrecorded` either way: name the level on the command line and in the ledger row.

Live mode defaults to `--permission-mode auto` so safe headless commands can run without an interactive prompt. Override it only when intentionally auditing permission behavior. In `-p`, that mode still launches subagents in the background ([sub-agents](https://code.claude.com/docs/en/sub-agents), fetched 2026-10-07). Since 2.1.271 the strict grader reads an implementation-auditor verdict from a parsed `SubagentHandback` whose parent is that auditor, not from the main loop's later text ([tools-reference](https://code.claude.com/docs/en/tools-reference), fetched 2026-10-07). A launch receipt is not a verdict; with none, the grader reports `strict_auditor_verdict_unobservable`. A `Skill`, test run, or spec write that carries `parent_tool_use_id` does not satisfy a main-loop requirement. The runner drops `CLAUDE_CODE_SIMPLE` from the Claude child environment. `python3 scripts/run_procedure_eval.py --live` now requires `--allow-fixture-commit`, the consent for the baseline commit the harness creates inside the isolated fixture copy; without it the eval exits 2 before creating a temporary directory, running Git or starting a model.

Live mode starts the agent CLI only from an absolute path found on an absolute `PATH` entry, the same rule `git` and `node` already follow (D25 model (5)), so a `claude` planted in the checked-out project is never run. When the CLI sits outside any absolute `PATH` entry — a WSL or nvm layout — name it explicitly with `--claude <path>`; an unresolvable CLI still fails with `claude CLI missing`.

### What it checks

For each case, the evaluator parses the transcript into a trace and checks:

| Check | Mechanism |
|---|---|
| Required skills | A `Skill` tool invocation whose payload contains the expected skill name, a mapped specialist `Agent`/`Task`, or a `required_runtime_adapters[].satisfies` entry with all adapter patterns present. This payload match is a substring match, so a `Skill` call whose arguments mention the name also satisfies it; the strict `skill_call_counts` and `forbid_skills_anywhere` keys below use exact names. |
| Required workflows | A `Workflow` tool invocation whose payload contains the expected workflow name, or a `required_runtime_adapters[].satisfies` entry with all adapter patterns present. |
| Runtime adapter evidence | Regex patterns in `required_runtime_adapters[].required_patterns` proving the runtime-equivalent path, such as `Workflow unavailable`, `Codex Adapter Gate`, `spec-plan-author`, `spec-plan-critic`, `docs/agentic-sdlc/specs/`, `docs/agentic-sdlc/plans/`, and, for the pipeline, the `work-type core`, `security-reviewer` and `implementation-auditor` gate markers. |
| Required commands | A regex match against the `command` field of any tool invocation recorded in the trace. |
| Required artifacts | Either a write tool's `file_path` matching the pattern whose result is not an error (a `Read` of the path does not count), or an existing file glob under the case working directory. |
| Artifact depth | When `check_artifact_depth` is true, written spec/plan artifacts are re-run through `validate_artifacts.py`; literal stubs such as `spec` or `plan` fail as `shallow_artifact:<path>`. |
| Forbidden commands | A regex match against recorded `command` fields; if any match, the case fails. |
| Required patterns | A regex match anywhere in the serialized trace haystack. |
| Forbidden patterns | A regex match anywhere in the serialized trace haystack. The pipeline cases use three: a `Skill` call to a focused skill, a focused skill's `SKILL.md` path in either separator style, and an `Adapter Gate:` marker that names a focused skill. |
| Runtime errors | `result` events with `is_error` true or a subtype starting with `error`. |
| Permission denials | Recorded `permission_denials` in `result` events, or Codex `command_execution` items with `status:"declined"`. |

### Procedure fixture format

```json
{
  "cases": [
    {
      "id": "short-id",
      "fixture_dir": "tests/fixtures/some-fixture",
      "prompt": "user prompt",
      "required_skills": ["agentic-sdlc:agentic-sdlc-pipeline"],
      "required_workflows": ["agentic-sdlc:spec-plan-draft"],
      "required_runtime_adapters": [
        {
          "runtime": "non-claude",
          "capability": "spec-plan-author-critic",
          "satisfies": ["workflow:agentic-sdlc:spec-plan-draft"],
          "required_patterns": ["Workflow unavailable|embedded author/critic adapter", "spec-plan-author", "spec-plan-critic"]
        }
      ],
      "required_commands": ["detect_context\\.py", "validate_artifacts\\.py"],
      "required_artifacts": ["docs/agentic-sdlc/specs/", "docs/agentic-sdlc/plans/"],
      "check_artifact_depth": true,
      "forbidden_commands": ["\\bgit\\s+commit\\b", "\\bgit\\s+push\\b", "\\bgit\\s+merge\\b"],
      "required_patterns": [],
      "forbidden_patterns": [],
      "fail_on_runtime_errors": true,
      "fail_on_permission_denials": true
    }
  ]
}
```

`fixture_dir` is optional for dry-run/transcript analysis and required for `--live`. Live mode copies
every fixture into a fresh temporary git repo; it never falls back to the real plugin checkout.

### Strict evidence keys

A case's optional `strict` object is graded only with `--strict-evidence`; without the flag every `strict` key is inert. `validate_strict_config` rejects an unknown key or a wrong value type as `case <id> invalid strict.<key>`. Besides `require_red_green`, `check_artifact_depth`, `reviewers` and `required_order`, it accepts six keys that check the pipeline's zero-skill delegation:

| Key | Value | Fails when | Error id |
|---|---|---|---|
| `red_before_source_edit` | bool | No attributable test run with a non-zero exit falls strictly between the first top-level test-file write and the first production-source write. With no production-source write at all, the check reports `strict_source_edit_unobserved` instead, and only when `require_red_green` is true. | `strict_red_not_before_source_edit` |
| `skill_call_counts` | `{name: [min, max]}` | The number of main-loop `Skill` calls with exactly that name (on Codex, of distinct assistant messages carrying `Codex Adapter Gate: <name>`) is outside the bounds. A `Skill` call whose only result is an error is not counted. A counted name gets no agent-delegation credit. | `strict_skill_call_count:<name>=<n>` |
| `forbid_skills_anywhere` | list of names | A timeline tool call, sub-agent calls included, is a `Skill` call with a listed name, or a `path`, `pattern`, `glob`, `file_path`, `notebook_path` or `command` input names a listed skill's `SKILL.md` in either separator style. | `strict_forbidden_skill:<name>` |
| `reviewers_after_last_source_edit` | bool | The dispatch call of the last `security` or `control` reviewer whose result clears comes before the last top-level production-source write. The call is compared, not its result, so a reviewer dispatched before an edit never covers it. A missing result is reported by `strict_reviewer_result_missing` instead. | `strict_reviewer_before_last_edit:<step>` |
| `evidence_file_before_control` | bool | No top-level write to a `.tdd.md` path under `docs/agentic-sdlc/` comes before the dispatch call of the first `control` reviewer whose result clears. | `strict_missing_tdd_evidence` |
| `stop_at_gate` | `"spec-review"` | A write outside `docs/agentic-sdlc/` anywhere in the run, before or after the spec write and sub-agent writes included (paths are compared after collapsing `.` and `..`; a Codex rename counts at both paths); after the first spec write, a plan write or a spec status of `approved` or later (quoted or not); or the final assistant text does not name the spec review. | `strict_edit_after_spec_gate:<path>`, `strict_plan_after_spec_gate`, `strict_spec_status_without_approval`, `strict_missing_gate_stop` |

A failed write (a Claude write whose every correlated result is an error) is no write for any of these keys. Paths are compared relative to the fixture root, the init `cwd` or the Codex rollout `cwd`, and an error id never carries an absolute path. `check_artifact_depth` relativizes each spec and plan path against the same roots before its depth check, so a spec saved through an absolute Claude path is depth-checked; only a path no root can relativize still yields `unsafe_artifact_path`.

`required_order` also accepts the step id `core-read`: on Claude, a top-level `Read` of a `skills/<skill>/references/core.md` file of `feature-build`, `root-cause-fix`, `safe-refactor` or `test-authoring`, in either separator style; on Codex, a command that names such a file or the `Codex Adapter Gate: work-type core <type>` marker. The pipeline cases order it after `plan-written` and before `red-run`. `core-skill` stays a valid id, but no pipeline case uses it.

`tests/skills/procedure/agentic-sdlc-pipeline-gate-stop.json` holds the strict-only gate-stop case: no pre-approval in the prompt, `stop_at_gate: "spec-review"`, exactly one `dispatch-strategy` call, no focused skill, and the order `dispatch-strategy` → `spec-written`. It is a separate file because a strict replay grades every case of an eval set unless `--case-id` narrows it, and a pre-approved full-run transcript fails every `stop_at_gate` rule.

With `--strict-evidence`, the runner prints `case_<id>_acceptance=pass|fail` and `case_<id>_acceptance_excluded=<comma list>` next to the unchanged `case_<id>=passed|failed` line. Acceptance counts every error except those starting with `strict_critical_audit:` (the auditor verdict, which is reported in its own column) and those containing `unsafe_artifact_path`; the excluded list names the errors it set aside. On real Codex transcripts the red/green keys cannot pass, because test runs wrapped in `/bin/bash -lc` or `powershell -Command` are not attributed (see [strict evidence limits](runtime-adapter.md#limits-of-branch-review-result-and-strict-evidence)).

---

## Artifact validation

`scripts/validate_artifacts.py` is the deterministic spec/plan gate. It validates markdown artifacts and emits sorted flat `key=value` lines. It is pure stdlib, **read-only**, and masks any secret-shaped value as `***MASKED***`.

```bash
# Validate a spec
python3 scripts/validate_artifacts.py --mode spec --file docs/agentic-sdlc/specs/example.md

# Validate a plan against its spec
python3 scripts/validate_artifacts.py --mode plan --file docs/agentic-sdlc/plans/example.md --spec docs/agentic-sdlc/specs/example.md

# Run both spec and plan checks together (the frontmatter must carry work_id, status, spec and branch)
python3 scripts/validate_artifacts.py --mode all --file docs/agentic-sdlc/plans/example.md --spec docs/agentic-sdlc/specs/example.md

# Promote every warning to a gating error
python3 scripts/validate_artifacts.py --mode plan --file docs/agentic-sdlc/plans/example.md --spec docs/agentic-sdlc/specs/example.md --strict
```

`scripts/resolve_work_package.py` is the deterministic identity gate for implementation audits. It resolves the active `docs/agentic-sdlc/specs/<work_id>.md` + `docs/agentic-sdlc/plans/<work_id>.md` pair from an explicit path, unique branch match, or unique changed canonical plan. It never chooses by newest timestamp.

```bash
python3 scripts/resolve_work_package.py --plan docs/agentic-sdlc/plans/example.md
python3 scripts/resolve_work_package.py
```

### What it checks

Headings inside fenced code are ignored, and a section runs to the next heading of the same or higher level, so its own sub-headings stay inside it.

**For specs:**

- Required sections present: Problem, Business rules, Acceptance criteria, Edge cases, Definition of done, Must-not-change.
- Each present section has enough content (non-gating warning if thin).
- Acceptance-criteria bullets contain a testable marker (`Given`, `When`, `Then`, `returns`, `exit`, `->`, `=>`).
- A top-level acceptance-criteria bullet with a testable marker carries an id: `AC1`, `AC-1` or a grouped `AC-A1`. One without an id warns as `ac_missing_id:<n>`, numbered like `untestable_criterion:<n>`. Nested bullets and bullets with no testable marker (a bold group heading, a "Guards:" line) are not checked for an id. A dotted sub-id (`AC1.2`) is a criterion of its own, not a spelling of `AC1`.
- An id that labels two top-level criteria is an error, `ac_duplicate_id:<id>`.
- A criteria section that holds no id at all is `ac_none`: an error with `--sources`, a warning (promoted by `--strict`) without.
- Security sections cannot be bare dismissals; `security_handwave` warns on claims such as "safe string handling only" without an input-to-sink explanation.
- No `TODO`/`TBD`/`FIXME`/`XXX` placeholders remain in prose (fenced code and inline code are skipped).
- No secret-shaped content (explicit narrow patterns only; no entropy detector). A `password`, `secret` or `api_key` label fires with any value after `=`. After `:` it fires with a quoted value of 6 or more characters, a YAML block opener (`|`, `>`, `|-`, `>+`, `|2`) with nothing else on the line, or an unquoted run of 6 or more characters that is not one prose word. A prose word is at most three hyphen-joined parts, each lowercase or Capitalized and at most 24 letters, with optional `.`, `,`, `:` or `)` after it. So "Password: must be non-empty", "Secret: per-tenant" and "api_key: `X-Api-Key` header" pass, while a mixed-case or all-caps value, a passphrase of four or more parts and a `password: |` block fire. The provider formats follow the hooks (`ASIA`, `glpat-`, `npm_`, `hf_`, `sk-ant-…`, OpenAI project, service-account and admin keys), and a PGP `PRIVATE KEY BLOCK` or a key header with digits is a private key.

**For plans:**

- Task blocks start with `## Task N` headings or line-leading `TN` markers. A heading such as `## Task list` or `## Task overview` names a section, not a task. A task block covers only its own body: a heading task ends at the next heading of the same or higher level, a bullet or `TN` task at the next heading, and a section after the tasks belongs to none of them.
- Each task references a file to create or modify and mentions TDD or a failing test.
- Each task includes runnable verification; missing commands or expected signals warn as `task_no_verification`.
- Deferral hand-waves such as "Non-task step" or "executed later after gates" warn as `deferred_work`.
- Tasks are ordered with strictly increasing numbers, read from a `## Task N` heading or a `TN` id (`tasks_unordered`).
- The plan has at least one task block; a plan with none warns as `plan_no_tasks`.
- Every acceptance-criterion id from the spec is cited inside at least one task block; a coverage table above the first task does not count. `AC1` and `AC-1` name the same criterion, so either spelling covers it.
- Coverage cannot pass with nothing to check: a spec that yields no id warns as `ac_source_empty`. The pipeline runs the plan check with `--strict`, so `plan_no_tasks`, `ac_source_empty` and `ac_not_covered:<id>` block the Plan Review gate.
- The plan check does not report a single unlabelled criterion: that is the spec check's `ac_missing_id:<n>`, a warning that the pipeline's spec gate, which runs with `--strict`, turns into an error.

> The validator is **structural only** — it cannot tell whether the spec is *about the requested work*. At the Spec Review gate also confirm the spec's topic matches the requested task (a mis-carried workflow context can yield a structurally-valid but **off-target** spec).

**For work-package identity:**

- `resolve_work_package.py` requires spec frontmatter (`work_id`, `status`) and plan frontmatter (`work_id`, `spec`, `branch`, `status`).
- It accepts only `docs/agentic-sdlc/specs/<id>.md`, `docs/agentic-sdlc/plans/<id>.md` and the per-package `docs/agentic-sdlc/<slug>/<role>/<id>.md`; a file nested deeper is `spec_outside_root` or `plan_outside_root`.
- A file under those roots that is not UTF-8 text, or a directory named `*.md`, is `spec_unreadable` or `plan_unreadable` when it is selected and is skipped otherwise; it never ends the run with a traceback.
- It resolves from explicit path first, then a unique branch match, then a unique changed canonical plan.
- It rejects ambiguous plans, missing specs, bad status values, work-id mismatches, and path traversal; it never selects by newest timestamp.

---

## Context detection

`scripts/detect_context.py` is the deterministic workspace probe used by `agentic-sdlc-pipeline` to decide whether a workspace is greenfield or brownfield, how many architectural layers it has, whether external dependencies are present, and what toolchains are available. It is a **classifier, not a gate** — it always exits 0.

```bash
python3 scripts/detect_context.py --path .               # Step 3 — workspace + explore_mode
python3 scripts/detect_context.py --path . --probe deps   # Step 6 — dependency probe
python3 scripts/detect_context.py --path . --probe toolchain  # Step 15 — toolchain probe
```

The pipeline uses its output to choose an exploration strategy and to avoid guessing about dependency/toolchain state (e.g. `explore_mode=parallel` fans out `context-analyst` per layer; `deps_probe=stdlib_only` skips Context7; `toolchain_probe=absent` marks quality gates N/A).

A manifest that is valid JSON of an unexpected shape (`"require": []`, `"scripts": null`, a top-level array) declares nothing; the probe still exits 0.

In tests, `detect_context.py` is exercised through `tests/test_detect_context.py`, which asserts both in-process function results and subprocess CLI output.

---

## Installed-runtime and coexistence evidence

Keep these evidence classes separate:

| Claim | Required observation |
|---|---|
| Metadata or handler correctness | Native manifest validation or direct deterministic handler tests, with exact files and versions |
| Model access | Successful response on the requested model/effort; no substitution |
| Installed hook delivery | Discovered plugin and hook definitions, reviewed trust state, real event output and observed effect |
| Process ownership | Selected owner plus actual skill invocation/read, with no stacked counterpart for that phase |
| Session restoration | Real persisted-session resume/compact and delivered bootstrap/owner context |
| Procedure completion | Commands, outputs, resulting artifacts, and an independent final review scoped to that procedure |

Record the binary version, plugin/reference hashes, requested and effective model/effort, fixture, trust state, transcript, and terminal result. For paired coexistence comparisons, freeze old/new snapshots and use the same prompts and model settings. Cover explicit house selection, explicit reference selection, inherited owner after resume, and an unqualified house entry; keep held-out phrasing out of the editing loop. An old baseline may pass. Generate the review viewer before judging the comparison. A classifier's JSON answer is route-classification evidence, not native activation evidence.

For the 2026-09-12 remediation, the requested settings are `gpt-5.3-codex-spark` with `model_reasoning_effort="low"` and `claude-sonnet-5 --effort low`. Inspect Claude `modelUsage` as well as the assistant model: the CLI can invoke background or subagent models independently. Its documented child-environment controls include `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`, and `CLAUDE_CODE_EFFORT_LEVEL`; pin them to the requested model/effort when every evaluation call must use it, and verify the observed usage. Never silently substitute a model when access fails. [Claude model configuration](https://code.claude.com/docs/en/model-config)

A trust bypass may demonstrate execution of reviewed hook code but cannot establish ordinary persisted trust. Capture pending/untrusted discovery, native review of the exact current definition, and trusted delivery without bypass for that claim. Do not use Codex `--ephemeral` or Claude `--no-session-persistence` for resume/compact proof; existing trigger runners use those flags intentionally for disposable classifier/activation tests. Do not use Claude bare/safe mode for hook-delivery claims. Keep real credentials in the runtime's auth store rather than copying them into fixtures or evidence.

A live hook test must inspect pre-tool denial and absence of the intended effect, or a Stop block followed by continuation and `stop_hook_active` loop protection. Calling the handler directly proves only its response to the supplied payload. Current rollout/cwd compatibility requires an installed-runtime sample because the transcript schema is unstable. See [runtime proof scope](runtime-adapter.md#current-binary-and-historical-hook-evidence).

### Native install lifecycle check

```bash
python3 scripts/check_native_lifecycle.py --package <extracted-package-or-checkout> [--platform claude|codex|grok|kimi|zcode|all] [--require <platform>]
```

For each platform it copies the package (without `.git`; from a checkout only the committed files, and a checkout git cannot list reports `failed:package_unreadable`) below a temporary path with a space and non-ASCII characters, points every profile variable of that CLI into the temporary root, and drives the vendor's own plugin manager: install, component discovery, refresh from the copy with a bumped manifest version and a changed marker file, uninstall. It prints one `native_<platform>=passed|failed:<reason>|not-run:<reason>` line per platform and exits 1 when any line is `failed` or a `--require`d platform did not pass. A pass needs discovery to report the package's own skill count (skill directories, plus `commands/*.md` where the platform turns commands into skills), the refreshed bytes and version in the installed copy, the plugin record gone after uninstall, and an unrelated sentinel setting intact after every step.

Recipes: Claude Code `claude plugin marketplace add|install|list|details|update|uninstall`; Codex a personal catalog under the isolated `HOME`, `codex plugin add|list|remove` and the read-only `skills/list` request of `codex app-server --stdio`; Grok `grok plugin install|list|uninstall` and `grok inspect --json`; Kimi Code the local `kimi web` REST API on 127.0.0.1 with the bearer token from its startup banner (or the token file it keeps in the isolated profile); the server is stopped with its process tree afterwards. ZCode has no headless installer and always reports `not-run:no_headless_installer`. On macOS, the manual workflow `.github/workflows/native-lifecycle-macos.yml` (`workflow_dispatch` only, read-only token) builds and verifies the package on a GitHub-hosted runner, installs the pinned Claude Code, Codex, Kimi and Grok CLIs, and runs the checker with every platform `--require`d. Its last step mounts the official ZCode desktop DMG read-only, requires its code signature to verify, and runs `.github/scripts/zcode_agent_lifecycle.mjs`: the app binary in Electron's Node mode drives the bundled agent CLI's `plugins` subcommands (validate, marketplace add, install, list, update, uninstall) with every home, data and provider path isolated and the caller's real ZCode settings compared before and after. The same script produced the Windows ZCode evidence from the signed Windows installer unpacked with 7-Zip. On Linux, the manual workflow `.github/workflows/native-lifecycle-linux-zcode.yml` (Ubuntu 24.04 runner) installs the Electron runtime libraries, checks the official ZCode AppImage against a pinned sha256 (the macOS job pins the DMG's hash too), unpacks it with `--appimage-extract` (nothing is installed), fails if `ldd` still reports a missing library, and runs the same script. The child environment is an allowlist (no provider key, cloud credential or CI token), every subcommand is probed with `--help` before use, a `.cmd`/`.bat` shim is refused, and no argv outside the plugin-management allowlist (never `claude -p`, `codex exec`, `kimi -p` or a Grok prompt) is ever sent. It proves local install/refresh/uninstall through the native manager; it does not prove remote marketplace publication, hook trust or execution, or live skill behavior.

## Live eval safety

Live evals spend real tokens and time. Apply these controls:

- Set `--max-budget-usd` to a small value for smoke runs (e.g. `0.10` for trigger evals, `2.00` for procedure evals).
- Use `--timeout` to cap wall-clock time; `run_trigger_eval.py` defaults to 180 s and `--smoke` caps it at 90.
- Use `--smoke` for one-query, one-run probes before running a full eval.
- Capture transcripts explicitly with `--transcript-dir` when failures must be replayed. Persisted
  transcripts are passed through the canonical high-confidence secret redactor first.
- The Claude trigger runner kills the process tree as soon as a trigger decision is detected or the timeout expires.
- The Codex runner and behavior/procedure runners also terminate the subprocess on timeout.
- Run live evals only when `claude` or `codex` CLI and auth are available; if the CLI is missing, treat the result as **skipped, not passed**.
- Never leave eval artifacts containing secrets. Procedure transcripts are ephemeral by default;
  caller-selected transcript paths are redacted before persistence.

---

## Live eval findings (2026-06-18 — Haiku + Sonnet sweep)

This historical sweep used Claude Code (`claude -p`, OAuth/subscription auth) over the then-current skill catalog and pipeline runtime. It does not establish current binary or revised-skill behavior. Detailed transcripts live under `tests/artifacts/` (gitignored); this section is
the **durable summary** plus the eval-infrastructure fixes it motivated.

### Headline lesson: separate model-capacity floor from description/skill debt

Haiku triggers/routes **abstract, meta, gate, and audit** skills unreliably and with high run-to-run
variance (a skill left **untouched** swung 0.40↔1.00 across N=5/10/20). The **same descriptions** score
**0.80–1.00 on Sonnet**. Before "fixing" a low Haiku number, re-run on Sonnet: if Sonnet is high, it is
the model floor — document it, do not inflate the description. Use `--runs ≥3` so variance is measured,
not masked by a lucky single draw.

### Router + focused-skill routing (`run_routing_eval.py --runtime claude --model haiku`)

| Finding | Result | Action |
|---|---|---|
| `implementation-control` skipped its `Skill` call (~20%), diving into `git diff` or deferring to the user | first-tool **0.80 → 1.00** (N=10) | call-order guard added to skill + router (genuine bug, fixed) |
| Routing eval scored a correct route as a timeout when its skill ran a long auditor pass | fixed | `run_routing_eval.py` early-stops once the route is observed |
| `runs=1` is unreliable on Haiku — two full sweeps gave 15/15 (q11 outlier) and 14/15 (q13 outlier) from variance alone | n/a | `run_routing_eval.py` default `--runs 1 → 3` (strict threshold kept) |
| Router trigger eval-set asked the router to route to a child skill (structurally under-credits it) | **Sonnet 6/6** after rework | `tests/skills/evals/using-agentic-sdlc.json` reworked to test the router's own "which skill owns this?" surface |

### Full 16-skill trigger matrix (`run_all_trigger_evals.py`, command-shim smoke + real-plugin re-check)

- **10/16 clean** on the command-shim smoke. Flagged skills were re-checked with `--no-command-shim --plugin-dir .` (real plugin) before any conclusion.
- `feature-build` q1: command-shim 0.00 but **real-plugin 1.00** → command-shim artifact, not a defect.
- `safe-refactor`, `skill-authoring`, `completion-claim-gate`: added activation guards ("first action; announcing/inlining is not invoking"). Marginal lift on Haiku; **Sonnet 0.80–1.00** confirms the descriptions are sound.
- `completion-claim-gate` is weakest on Haiku (~0.13); under weak models it relies on the deterministic Stop hook `hooks/completion-claim-guard.mjs` backstop (12 policy tests in `tests/test_hooks_policy.py` at the time of this 2026-06-18 finding; that file now holds 45, of which 5 are the completion-claim class — the figure is left as the snapshot it was rather than re-pointed).

### Pipeline run-time procedure (`run_procedure_eval.py --live`, `bypassPermissions`, isolated fixture)

Question: do the pipeline's feeder skills fire at the right step, and does it run as designed?

| Model / budget | Result | Notes |
|---|---|---|
| Haiku N=3 @ `$2` | **1/3** full PASS | core gates 3/3 (detect_context, validate_artifacts, feature-build, security-audit, implementation-control); each run drops a different gate — variance/floor. Haiku-only deviations SKILL.md already forbids: ad hoc `Workflow({script})` instead of named `spec-plan-draft`; shell/branch before the `dispatch-strategy` call-order guard. |
| Sonnet N=3 @ `$2` | 0/3 (artifact) | all hit `Reached maximum budget ($2)` mid-run — $2 cut off a strong-model pipeline and masked late gates. |
| Sonnet N=2 @ `$6` | **2/2** full PASS | all 8 gates each run, named workflow, call-order respected, no forbidden git, no budget hit. |

**Both success criteria met:** feeder skills fire at the right step (Sonnet 8/8 gates 2/2; Haiku core 3/3 + dispatch 3/3), and the pipeline runs as designed (Sonnet 2/2 in correct phase order). The Haiku 1/3 is the model floor, not a pipeline defect — SKILL.md guards (call-order, named-workflow-only) hold on a capable model.

**Eval-infra fix:** `run_procedure_eval.py` default `--max-budget-usd` raised `2.00 → 5.00` so a strong-model Full-mode pipeline is not cut off mid-run (Haiku finishes under $2, unaffected). Verify the pipeline on Sonnet at budget ≥5, not Haiku at $2.

---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `check_all=failed` with `validator_tests_failed` | One of the validator suites named in `check_all.py` (`VALIDATOR_TEST_PATTERNS`) is failing. | The failing test name is printed to stderr; re-run that suite with `python3 -m unittest discover -s tests -p <file> -v`. A failure elsewhere in `tests/` surfaces in the gate's fourth command, not here. |
| `name_dir_mismatch` or `name_not_kebab` | A skill directory name does not match the `name:` frontmatter value, or the name is not kebab-case. | Rename the directory or edit `SKILL.md` frontmatter. |
| `dangling_reference` | A skill's `must_reference` entry points to a missing component. | Add the missing skill/agent/workflow/etc., or update the golden entry. |
| `safety_evidence_absent` | A safety scenario's `guardrail_evidence` substring is not found in the cited file. | Restore the guardrail text in the cited contract/skill/hook, or update the fixture if the guardrail moved. |
| `missing_section:must-not-change` | A spec is missing the Must-not-change section. | Add a `## Must-not-change (regression surface)` section to the spec. |
| `ac_not_covered:AC2` | The plan does not reference acceptance criterion `AC2`. | Add `AC2` to a task block, or adjust the spec's AC ids. |
| `ac_missing_id:2`, `ac_none` or `ac_source_empty` | The second acceptance criterion has no `AC<n>` id, or the spec has no id at all (`ac_none` in spec mode, `ac_source_empty` in plan mode), so plan coverage cannot be checked. | Label each criterion in the spec (`- AC2: Given …`), then cite the id in the task that covers it. |
| `plan_no_tasks` | The plan has no `## Task N` heading or line-leading `TN` marker. | Write the tasks in one of those two forms. |
| `placeholder:` | A markdown artifact still contains `TODO`/`TBD`/`FIXME`/`XXX` in prose. | Resolve the placeholder or move it into inline/fenced code if it is illustrative. |
| `possible_secret:` | A secret-shaped pattern was detected. | Remove or mask the value; never commit real credentials. |
| Trigger eval reports `q0_mismatch` | The model did not select the target skill at or above the threshold. | Inspect the transcript; tune the skill description or add near-miss negatives to the eval set. |
| Procedure eval reports `missing_skill` | The transcript does not show an invocation of the expected skill. | Check whether the skill name is correct and whether the model actually routed to it. |
| Procedure eval reports `forbidden_command` | A recorded command matched a forbidden regex. | Review the transcript; if the command was intentional, tighten the regex or update the eval expectations. |
| `runtime_error:error_max_budget_usd` | The live run hit its budget cap. | Expected protection, not a bug. Raise `--max-budget-usd` only if the task genuinely needs more spend. |
| `permission_denied` in procedure eval | A safe-looking command was denied by the runtime. | The eval treats denials as failures for executed procedure steps. Check whether `--permission-mode auto` is appropriate or whether the command needs broader permissions. |
| `node not available` | `node` is not on PATH. | Install Node.js to enable `test_static_node.py`; the test skips rather than passes. |
| `claude=missing` | The `claude` CLI is not installed or not on PATH. | Install/authenticate Claude Code to run live evals; deterministic checks still pass. |
| Codex transcripts contain plugin/skill warnings | Any loaded plugin can produce a warning; its source must be identified from the actual path/plugin metadata. | Record the warning and determine whether it affects the tested plugin. The inline route classifier can run without plugin discovery, so its result cannot excuse an installed-plugin warning or prove hook delivery. |

---

## Artifact layouts and per-package evidence

Work-package artifacts resolve in two layouts: the legacy flat `docs/agentic-sdlc/{specs,plans}/<id>.md` (back-compat, unchanged) and the per-package canonical `docs/agentic-sdlc/<slug>/{spec,plan,evidence}/<work_id>.md`, where `<slug>` is lowercase kebab-case `^[a-z0-9][a-z0-9-]{0,63}$` and never a reserved name (`specs`, `plans`, `evidence`, `notes`, `spec`, `plan`).

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no Finalize evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

From Step 8 the pipeline's main loop also writes a TDD evidence file, `docs/agentic-sdlc/<slug>/evidence/<work_id>.tdd.md` per-package or `docs/agentic-sdlc/evidence/<work_id>.tdd.md` flat, with every test run until `implementation-auditor` is dispatched; it is git-ignored, has no validator and never gates resolution.

Per-package plan change-detection runs as a filesystem scan, not a `git status` query: new generated plans can be git-ignored, so the resolver scans the filesystem; published plugin documentation is tracked separately.

## Cross-references

The native Codex 0.154.0 fixture `tests/fixtures/transcripts/codex-0.154.0-native-tool-carriers.jsonl` retains six redacted WSL success/denial records. Its tests cover actual current carriers, output correlation, and forged headers inside denied/tool-output text. The live source capture proves runtime effects; replaying the reader against that capture proves parser compatibility, not a second model execution.

- [README.md](../README.md) — project overview, install model, and quality gate.
- [Claude Code runtime README](../.claude-plugin/README.md) — Claude plugin loading, hooks, and native transcript gates.
- [Codex runtime README](../.codex-plugin/README.md) — Codex personal-marketplace loading, publishable manifest shape, and embedded adapter behavior.
- [docs/plugin-readme.md](plugin-readme.md) — component-by-component plugin documentation, pre-push checklist, and known limitations.
- [docs/skill-boundaries.md](skill-boundaries.md) — ownership map for every skill and layer.
- [contracts/skills/05-testing.md](../contracts/skills/05-testing.md) — the testing behavior contract (test-first, show output, no coverage theater).
- [tests/skills/README.md](../tests/skills/README.md) — focused guide to the skill harness and how to extend it.
