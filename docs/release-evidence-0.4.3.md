# Release evidence — 0.4.3

Status: release preparation. The current publish verdict is **do-not-publish** until every required result below is complete and independently reviewed. This public ledger deliberately preserves missing results instead of treating the earlier remediation audit as the full release gate.

## Scope and required results

The supported runtimes are Claude Code and Codex. The historical 2026-09-13 batch recorded below used `claude-sonnet-5` with Low effort and `gpt-5.3-codex-spark` with Low reasoning. The current batch uses `claude-sonnet-5`/Low and `gpt-5.5`/Low, a new Codex baseline that is not comparable to the Spark results. Native execution uses WSL with isolated copies of the development plugin, preserving existing authentication in native stores. Model-access checks and deterministic replay do not substitute for live behavior.

| Release requirement | Current result | Passing criterion |
|---|---|---|
| Shared structure, harness and full tests | PASS on corrective payload144ca634: all five gates exit zero in worktree and clean archive; 684 worktree tests, 677 archive passes and one expected skip | Record the exact test scope and skip reason below |
| Version/changelog consistency | PASS: all declarations are 0.4.3 and both version/release checks exit zero | VERSION, README and both plugin manifests/marketplace agree; release check passes |
| Claude standalone routing | PASS: 45/45 on payload9978383c, independently reviewed successful qualified Skill delivery and complete body receipts | Fifteen cases, three correct observations per case, threshold 1.0, no hard error or prohibited escalation |
| Codex standalone routing | PASS: 45/45 on payload9978383c, independently reviewed native model/Low metadata and expected JSON route | Same fifteen-by-three criterion; explicitly a description classifier |
| Claude flat-layout pipeline | FAIL: corrective smoke entered feature-build without loading the pipeline, wrote on main, hid RED's shell exit and replaced an auditor PARTIAL with implementer PASS | Existing smoke/procedure case and observed fixture effects pass |
| Claude per-package pipeline | FAIL after controller-assisted implementation: nine tests pass, but required core activation, RED shell status, review fan-out and inspectable audit evidence are missing | Existing normal per-package case and observed fixture effects pass |
| Codex adapter procedure replay | PASS: current replay reports both cases passed and procedure_eval=passed | Current parser/eval/fixture identities bound to runtime input 9978383c; deterministic evidence only |
| Distribution and native manifests | PASS for corrective payload144ca634: 201 source members, sixteen skill archives, both native manifest validations successful | Rebuild the final ZIP after this result ledger is completed |
| Public source and artifact scans | Prepared source/archive scan passes: three inspected synthetic/documentation matches, zero unresolved findings or private host paths | Scan generated live artifacts after execution too |
| Independent release review | Assessment complete: do-not-publish; required procedure findings remain open | Every required result above has inspected evidence and no unresolved in-scope finding |

### Annotations to historical rows (2026-09-15)

- **Version/changelog consistency**: contradicted by F5 (`README.md:250` read `0.4.2`); the current result is row `current_version_declarations` (AC85).
- **Public source and artifact scans**: scope was source and archive only, not Git history; the F4 finding is held by row `history_private_path_finding` (AC125).
- **Source-archive recipe (paragraph at line 60)**: its reviewed-new-file packaging recipe is superseded for the 0.4.3 final archive by commit-tree-only builds (BR13).

Required commands and measurement boundaries are in [Release Readiness](release-readiness.md). Use the existing three-observation threshold; a single successful routing response cannot satisfy it. The original native batch completed ninety routing sessions and both Claude procedure cases, with no automatic retry. All92 CLI invocations are terminal. The routing verdict covers initial selection/delivery, not execution of every focused procedure.

The maintainer has approved this batch and explicitly requested no monetary ceiling for Claude. Its reviewed native `claude -p` commands therefore omit `--max-budget-usd`; the public runner examples have their own defaults and are not the executor of this uncapped batch. The fixed session count and recorded timeouts remain in force. Two separately authorized harness baseline commits occur only in the isolated test repositories; project publishing is outside this preparation.

Independent procedure review overrides the broad automated score: the flat smoke modified code on main, attempted to install pytest without approval (pip was absent, so no package was installed), and loaded security-audit without completing its mandatory independent reviewer procedure. Assertions genuinely failed before implementation and passed afterward, but the custom runner swallowed exceptions and returned exit zero. The normal per-package case created its work branch and correctly requested Spec approval; an interactive gate cannot be completed by treating a one-shot headless response as a finished implementation. These records remain retained failures/limits, not retroactive passes.

The maintainer subsequently approved four additional Claude CLI invocations, each Low, at most900seconds and without a monetary ceiling. All four slots were consumed: a fresh smoke observation, normal Plan drafting, an interrupted Plan-correction turn, and the final implementation continuation. No automatic retry or additional commit occurred. Across the original and corrective scopes,96CLI invocations started;95 have terminal captures and one remains explicitly interrupted with unknown exit status. Native helper inference requests are not counted as separate CLI invocations.

The interrupted correction never produced a controller capture or revised saved Plan. Its native conversation content was not copied during recovery; only allowlisted event metadata, source hashes and four fixed fixture artifacts were recovered. The original source/tests and approved Spec were unchanged. The controller corrected the rejected Plan, obtained independent exact-byte approval and strict validation, and used the remaining invocation through a separately tested interruption transition. The old invocation was never assigned a fabricated successful exit or completion marker. This is controller-assisted continuation, not an autonomous Plan-revision success.

The final per-package continuation preserved the exact approved Spec and Plan, retained the work branch and baseline, and produced the additive farewell function with all nine tests passing. It nevertheless omitted feature-build activation, appended an echo that hid the RED runner's failing shell status, and used one security reviewer rather than the prescribed lens fan-out. The parent told its auditor that no echo masked RED, contradicting the native command. The auditor actually returned PASS while marking missing process receipts partial; this differs from the smoke's implementer override of an overall PARTIAL. Neither an overall PASS sentence nor completion-claim-gate activation closes these evidence gaps.

The controller's reload prefix requested a direct Read of the pipeline while the approved Plan requested native Skill activation. That inconsistency confounds attributing the missing native pipeline Skill solely to the model. The missing feature-build call and contradicted RED/audit evidence remain unambiguous. The smoke never loaded the repaired pipeline body, so it cannot establish whether that body's changes improved its procedure. These limits are retained rather than relabeling transport success as process compliance.

The source worktree suite reports `Ran 684 tests in 188.760s`, `OK`, with no skips. It includes six private maintainer prompt-contract tests that are deliberately absent from distribution. The independently extracted source archive reports `Ran 678 tests in 186.543s`, `OK (skipped=1)`: 677 passed; the sole skip is `TestRepoWorkPackageArtifacts.test_canonical_work_package_artifacts_are_well_formed`, because generated local work-package plans are intentionally absent from a clean clone. This expected local-plan skip is not hidden in the published count. All archive source bytes remained unchanged after its checks.

After the pipeline instruction correction, the worktree suite reports `Ran 684 tests in 134.570s`, `OK`, with no skips; check_all, skill harness, version and release checks also exit zero. This run binds corrective payload `144ca634c0803a9af7f8ddd5c1c4ccbc9895547dd819c5944edec04d7ce93437`. Its procedure observations and clean archive gate are tracked separately from the original payload above.

The corrective clean archive also passes all five gates: `Ran 678 tests in 116.744s`, `OK (skipped=1)`, or677passed plus the same expected absent-local-plan skip. Source bytes remain unchanged after execution. This tested archive has SHA-256 `f263e4ebe3a97b97232b9b7bc76168f8996675f992dcabc3491ba69a72cdadc7`; later result-ledger-only packaging receives a separate archive hash while retaining the runtime identity.

Native WSL validation of the extracted Claude plugin and marketplace manifests reports success with zero errors or warnings. The distribution checks cover complete member sets, bytes, CRCs, executable modes and repeat-build equality. The source scan covers 197 text members; its three matches are inspected baseline-identical examples in the secret-check instructions and validator tests, not identified credentials.

## Completed remediation evidence inherited by this candidate

The preceding repair package passed its four repository gates with 681 tests and no reported skips. Its independent audit closed eight remediation criteria. That checkpoint predates this release's metadata/documentation changes and is not substituted for the final 0.4.3 gate above.

On Codex 0.154.0 and Claude Code 2.1.269, twenty-one bounded WSL coexistence calls produced twelve successful latest owner/loading observations: eight paired owner conditions, two direct-entry regressions and two reserved delegation checks. Across all historical attempts, eighteen passed and three failed; the failures and their later corrections were retained. These observations cover actual selected-procedure loading and absence of a competing phase, rather than the fifteen-scenario standalone release routing matrix.

Separate native lifecycle captures established startup, resume, manual compaction, permitted fixture effects, production guard denial and finite Stop continuation. Codex captures include pending trust, exact-definition trust and persisted trust after restart. The corrected parser was then replayed against the unchanged real capture to verify native custom patch and exit-code recognition. Native execution and parser replay remain distinct, as described in [Runtime Adapter](runtime-adapter.md).

## Source identity and reproducibility

The original evaluated runtime input SHA-256 is `9978383c0bd22fe6ca0c71bfc0c8138f403b958cd824f847b5e05de67600c699`. Its90 routing results pass; its two procedure outcomes are detailed above. Release artifacts bind two inventories: all distributed source files, and the runtime payload excluding only this result ledger. This avoids claiming that report text written after evaluation was itself evaluated, or requiring a document to contain its own hash. Runtime instructions, fixtures, manifests, tests and other documentation remain part of that identity. Changed runtime inputs require renewed applicable checks. Full source and ZIP hashes are recorded separately with the generated distribution inventory.

The corrective runtime input is `144ca634c0803a9af7f8ddd5c1c4ccbc9895547dd819c5944edec04d7ce93437`. All sixteen skill names/descriptions remain byte-equivalent in their routing fields; pipeline, feature-build and implementation-control bodies, the pipeline playbook, auditor role and changelog changed. All28 shipped hook files remain byte-identical to9978383c. Codex's earlier classifier measures the unchanged routing fields; Claude's earlier full-body receipts remain evidence of the original bodies. New procedure captures must identify the corrected input and preserve this boundary.

A subsequent merge-CI correction normalizes expected resolver paths while temporary fixtures exist, adds a canonical-path regression and records that lesson. It changes tests/documentation, not the evaluated runtime instructions. The archive hashes and test counts above identify their original snapshots; they are not relabeled as a new live evaluation of this CI-only correction.

The release source excludes private audit writeups, maintainer prompts, credentials, local agent configuration, runtime caches and raw transcripts. A verified worktree package includes explicitly reviewed new source files; archiving the old HEAD would omit those fixes. After the reviewed release commit exists, its source ZIP can be reproduced with Git:

```bash
mkdir -p dist
git archive --format=zip --prefix=agentic-sdlc/ --output=dist/agentic-sdlc-0.4.3.zip <reviewed-release-commit>
```

This source-archive recipe has not created a commit or published a release. Archive compression/timestamps may differ from the normalized review package. Git can also normalize text line endings at commit/checkout; compare the complete member set, Git-normalized text and unchanged binary bytes, while using each recorded raw hash only for its exact built artifact. Skill archives use the capability-checked official packager described in [skill authoring](../skills/skill-authoring/SKILL.md).

## Limits retained in the release decision

- Codex Low is visible in native turn metadata; Claude Low configuration is inspectable, but response-side effective effort may not be exposed. Verify all observed helper model identities too.
- A Claude delegation response in the earlier coexistence sample incorrectly described three items as below an approximately-three-or-more threshold and offered future delegation without proving available tools. The owner/loading result does not certify every sentence or full procedure compliance.
- The inherited design results use several immutable repair snapshots. They are not an all-case native run of the final release package.
- One fixture requests smoke drafts and the other requests normal per-package work; actual phase execution must be checked independently. The corrective smoke did not activate the pipeline, and the normal case required controller correction after an interrupted native turn.
- Guard coverage is bounded, some checks are advisory or opt-in, and missing/unrecognized transcript evidence can fail open. These local checks complement human review; they do not provide universal security enforcement or model reliability.

## Identity definitions

- **Historical runtime input identity** (`9978383c0bd22fe6ca0c71bfc0c8138f403b958cd824f847b5e05de67600c699` original, `144ca634c0803a9af7f8ddd5c1c4ccbc9895547dd819c5944edec04d7ce93437` corrective), `definition: excludes only this result ledger`. It is the identity recorded for the 2026-09-13 batch above.
- **BR20 runtime payload identity**: the SHA-256 of the sha256sum-manifest form of the release archive members, one `<member sha256>  <path>` line per member sorted by UTF-8 path, excluding `docs/release-evidence-0.4.3.md` and `docs/release-readiness.md` (`scripts/build_release.py` `payload_identity` with `RUNTIME_PAYLOAD_EXCLUDE`). It excludes one more file than the historical identity, so the two are not comparable.
- **Skills-only payload identity**: the same manifest form over every member of the BR24 skills-only archive, with no exclusion.
- **Archive hash**: the SHA-256 of the archive file bytes.

## Release identity check

- 2026-09-14T19:56:26Z: `git ls-remote --tags origin` listed 0 remote tags, so neither `v0.4.3` nor `agentic-sdlc--v0.4.3` (the intended form, DP9) exists; the GitHub release `0.4.3` does not exist; the OpenAI portal version is BLOCKED on portal access. No collision was found, so no stop was recorded.
- 2026-09-15 re-check: not run in the slice F worktree, which runs without network access (`git ls-remote` and the GitHub API need it). The release identity check is repeated before any tag, release or portal version is created.

## Required release rows

Row states are PASS, FAIL, BLOCKED, not-run or GAP. Cells of rows not yet measured read `not recorded (not-run)`; model/effort is `n/a` for static gate and deterministic replay rows. The release envelope fills measured values in place.

| Row id | BR3 required | State | Identity (definition) | Git commit | CLI version | OS | Model/effort | Measurement type | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| `local_gate` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | n/a | static gate | not recorded (not-run) |
| `claude_routing_eval` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `codex_routing_eval` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | description classifier | not recorded (not-run) |
| `claude_pipeline_procedure` | yes | FAIL | runtime input 144ca634… (definition: excludes only this result ledger) | not recorded (historical batch) | Claude Code 2.1.269 | WSL Ubuntu | claude-sonnet-5/Low | native live | Historical rows "Claude flat-layout pipeline" and "Claude per-package pipeline" in the result table above |
| `codex_pipeline_procedure` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `secret_scan` | yes | BLOCKED: F4 history finding unresolved | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | n/a | static gate | not recorded (not-run); see row `history_private_path_finding` |
| `clean_package_native_validation` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `codex_discovery_16_8` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `hook_trust_untrusted` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `hook_trust_exact_definition` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `hook_trust_retained_after_restart` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `hook_trust_rereview_after_change` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `hook_effects_allowed_denied` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `hook_native_resume_compact` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `hook_trust_list_records` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `archive_verify` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | n/a | static gate | not recorded (not-run) |
| `archive_reproducibility` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | n/a | static gate | not recorded (not-run) |
| `pr_text_actions_review` | yes | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | n/a | static gate | not recorded (not-run) |
| `owner_skill_injection` | yes | BLOCKED: pending native capture | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `owner_resume` | yes | BLOCKED: pending native capture | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `owner_compaction` | yes | BLOCKED: pending native capture | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `current_version_declarations` | no | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | n/a | static gate | Bound to `python3 scripts/bump_version.py --check` on the integrated tree (AC85) |
| `history_private_path_finding` | no | BLOCKED | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | n/a | static gate | `audit-docs/codex-audit-docs.md`, a class 6 audit dump, added in c173b99 on 2026-09-02 and deleted in 4d88cd7, reachable from `main` and `origin/main`; the authoritative scan result and the reviewed findings record SHA-256 are recorded by the history scan (D14) |
| `security_report_mechanism` | no | GAP | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | n/a | static gate | The GitHub private vulnerability reporting API returns 404 while the repository is private; `LICENSE` and `SECURITY.md` are unchanged since 5801cb9 |
| `skills_only_archive` | no | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | n/a | static gate | not recorded (not-run) |
| `portal_normalized_manifest` | no | BLOCKED: needs a maintainer-approved portal upload | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | n/a | static gate | not recorded (not-run) |
| `skill_archives` | no | BLOCKED: skill-creator toolkit not reviewed | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | n/a | static gate | not recorded (not-run); see [release readiness](release-readiness.md) |
| `submission_cases_group` | no | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `coexistence_group` | no | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | native live | not recorded (not-run) |
| `path_verdicts` | no | not-run | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | not recorded (not-run) | n/a | static gate | See `### Path verdicts` |

## Publication decision

```text
version=0.4.3
scope=Claude Code, Codex
local_gate=not-run
claude_routing_eval=not-run
codex_routing_eval=not-run
claude_pipeline_procedure=failed
codex_pipeline_procedure=not-run
secret_scan=blocked
known_limitations_acknowledged=yes
verdict=do-not-publish
```

| Key | Bound row |
|---|---|
| local_gate | `local_gate` |
| claude_routing_eval | `claude_routing_eval` |
| codex_routing_eval | `codex_routing_eval` |
| claude_pipeline_procedure | `claude_pipeline_procedure` |
| codex_pipeline_procedure | `codex_pipeline_procedure` |
| secret_scan | `secret_scan` |
| known_limitations_acknowledged | [docs/runtime-adapter.md#limits-of-branch-review-result-and-strict-evidence](runtime-adapter.md#limits-of-branch-review-result-and-strict-evidence) |

Required procedure repairs remain in the result table. Repeated prompt-level corrections did not close the observed execution/evidence failures. The next repair must address trusted runtime receipts, activation/order checks and audit acceptance, then receive fresh runtime validation. No further paid trial is implied by this ledger and no publication was performed.

### Path verdicts

- Claude own marketplace: maintainer review pending -> no-go
- Claude community marketplace submission: maintainer review pending -> no-go
- Codex personal marketplace: maintainer review pending -> no-go
- OpenAI public directory: maintainer review pending -> no-go
