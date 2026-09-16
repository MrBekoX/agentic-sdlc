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

### What each command proves

| Command | Proves |
|---|---|
| `python3 scripts/bump_version.py --check` | `VERSION`, all shipped plugin manifests, and Claude marketplace metadata agree, and so do the visible version declarations: the README `Version` token and README current-version sentence, the `docs/plugin-readme.md` version line, and the `docs/release-readiness.md` publish-gate sentence and verdict-template `version=` line. |
| `python3 scripts/check_all.py` | A regex-based frontmatter check, not a full YAML parser or Agent Skills specification validator. Official Agent Skills fields: only the six keys `name`, `description`, `license`, `allowed-tools`, `metadata` and `compatibility` may appear, and `name` matches the directory. House-only rules, checked separately: third-person description framing, enforced only as rejection of the known leading-Use imperative regression (description meaning and trigger intent still need review); the angle-bracket ban; and a description length check. It also runs the discovered `tests/test_*.py` suites. |
| `python3 tests/skills/harness.py` | Skill/agent/workflow/hook/skill-contract references resolve; golden cross-references have not drifted; safety-fixture evidence is wired to real files; `${CLAUDE_PLUGIN_ROOT}` and `${PLUGIN_ROOT}` paths plus Claude/Codex hook configs resolve. |
| `python3 -m unittest discover -s tests -v` | `detect_context.py` classifies workspaces correctly; `validate_artifacts.py` enforces spec/plan structure and scans for placeholders/secrets; hook and workflow JavaScript parses under `node --check` (skipped if `node` is missing). |

### What the gate does NOT prove

- Claude Code actually chose the right skill in a live session.
- The model followed every step in a skill body or workflow.
- A human-facing end-to-end workflow succeeded without runtime errors or permission denials.
- Guardrails are obeyed when the model is under pressure.

Use live evals for those claims.

---

## Automation / CI policy

`.github/workflows/ci.yml` runs on `push` and `pull_request`, on `ubuntu-latest` and `windows-latest`. The source steps run:

```bash
python3 scripts/bump_version.py --release-check
python3 scripts/check_all.py
python3 tests/skills/harness.py
python3 -m unittest discover -s tests -v
```

The archive steps (DP16) then run on every push and pull request. They build the release archive with `python3 scripts/build_release.py --output`, verify it with `python3 scripts/build_release.py --verify`, extract it to a clean directory without creating a commit, and run all five local gate commands there, including `python3 scripts/bump_version.py --check`. A coverage comparison against the source run counts named skips, and the archive-run logs are named `archive-*`.

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

---

## Test suite map

The local unittest layer is organized into coverage **matrices** so each concern has a dedicated suite.

| File | Matrix | What it verifies |
|---|---|---|
| `tests/test_skill_structure.py` | A | Every skill has valid frontmatter, a kebab-case name matching its directory, a present description without angle brackets, and only allowed frontmatter keys. Every agent has a name matching its filename and a description. |
| `tests/test_skill_integration.py` | F | Golden `must_reference` entries appear in `SKILL.md` and resolve to real skills/agents/workflows/commands/scripts/files/contracts/hooks; plugin-root references exist; Claude and Codex hook configs are valid JSON and each referenced `.mjs` exists; workflow `agentType` values resolve to real agents; README/hooks-README claims match the tree. |
| `tests/test_skill_fixtures.py` | B / D / G | Every skill has a golden entry; golden description keywords still appear in live descriptions; safety scenarios are well-formed and their guardrail evidence exists in the cited repo files; every `tests/skills/evals/<skill>.json` is well-formed, targets a real skill, and contains both positive and negative queries. |
| `tests/test_detect_context.py` | script unit | `detect_context.py` classifies empty dirs as greenfield, counts source files, detects one vs. multiple architectural layers, ignores noise dirs, probes dependency manifests, probes toolchains, and always exits 0 even on hostile paths. |
| `tests/test_validate_artifacts.py` | script unit | `validate_artifacts.py` detects missing spec sections, thin sections, untestable acceptance criteria, placeholder tokens, secrets (masked), AC coverage gaps, task-block ordering, missing task verification, deferrals, and security hand-waves; `--strict` promotes warnings to errors. |
| `tests/test_work_package_resolution.py` | script unit | `resolve_work_package.py` resolves canonical `docs/agentic-sdlc/specs/` + `docs/agentic-sdlc/plans/` pairs by explicit path, branch, or changed plan, and rejects ambiguity, bad metadata, path traversal, missing specs, and timestamp fallback. |
| `tests/test_static_node.py` | E | Every hook `.mjs` and every workflow `.js` passes `node --check` (workflows are wrapped the same way the Workflow runtime wraps them). Skipped if `node` is absent. |
| `tests/test_trigger_eval.py` | eval-runner unit | The Claude trigger eval runner parses fixtures, builds command shims, and detects trigger outcomes correctly. |
| `tests/test_codex_trigger_eval.py` | eval-runner unit | The Codex route-classifier trigger runner parses fixtures and classifies routes correctly. |
| `tests/test_routing_eval.py` | eval-runner unit | The router eval runner handles Claude/Codex command construction, model aliases, error extraction, and route classification. |
| `tests/test_behavior_eval.py` | eval-runner unit | The behavior eval runner validates fixture shape and matches required/forbidden patterns. |
| `tests/test_procedure_eval.py` | eval-runner unit | The procedure evaluator parses stream-json transcripts and enforces required/forbidden skills, workflows, commands, artifacts, adapter evidence, artifact depth, and patterns. |
| `tests/test_flow_requirements.py` | hook policy unit | `hooks/flow-requirements.json` parses and every named skill, workflow, agent, validator, and command regex resolves. |
| `tests/test_flow_guards.py` | hook policy unit | `flow-order-guard.mjs` and `flow-step-guard.mjs` re-derive evidence, fail open outside active flows, and warn/block according to `AGENTIC_FLOW_GATE_BLOCK`. |
| `tests/test_hooks_policy.py` | policy unit | Hook wiring policy (block vs warn, fail-open, secret-pattern coverage, Claude/Codex hook-config separation). |
| `tests/test_packaging_metadata.py` | metadata unit | Plugin manifests, publishable Codex schema keys, marketplace version consistency, and `bump_version.py` behavior. |
| `tests/test_release_readiness_docs.py` | doc consistency unit | Release-readiness docs and documented helper counts match the repository. |
| `tests/test_house_voice.py` | product-surface unit | Runtime scope, house-voice markers, depth-forcing blocks, and maintenance files remain present. |
| `tests/test_skill_creator_resolver.py` | helper unit | Official toolkit identity, requested capabilities, candidate fallback, and explicit-path trust diagnostics without hidden installs. |
| `tests/test_runtime_documentation.py` | doc consistency unit | Current runtime evidence limits, test-result versus ordering semantics, coexistence restoration, and installed-trust proof requirements. |
| `tests/test_handoff_scripts.py` | script unit | `task_brief.py` extracts a single plan task into a handoff file. |

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
| `tests/skills/procedure/<case>.json` | Procedure eval seeds, including `agentic-sdlc-pipeline.json` and `skill-depth.json` (see format below). | `{ "cases": [{ "id", "prompt", "fixture_dir?", "check_artifact_depth?", "required_skills": [...], "required_workflows": [...], "required_runtime_adapters": [...], "required_commands": [...], "required_artifacts": [...], "forbidden_commands": [...], "required_patterns": [...], "forbidden_patterns": [...] }] }` |
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

The fixture format is:

```json
{
  "scenarios": [
    {"prompt": "...", "expected": "root-cause-fix", "escalation": false}
  ]
}
```

Do not combine routing eval results with trigger eval results as if they measure the same thing. Routing evals score the router's classification decision; trigger evals score runtime activation for a target skill.

---

## Trigger evals

Trigger evals measure whether a user prompt causes the runtime to select the intended skill. The fixture JSON is **shared**, but Claude Code and Codex use different runners because their runtime evidence differs.

### Claude Code: `run_trigger_eval.py`

`scripts/run_trigger_eval.py` is a Windows-safe replacement for the external `skill-creator`'s `run_eval.py`. It plants a temporary `commands/<skill>-skill-<uuid>.md` command shim (unless disabled), runs `claude -p <query> --output-format stream-json --verbose --include-partial-messages`, and detects whether the first tool action is a `Skill` or `Read` invocation of the target skill.

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

Isolate plugin-trigger behavior from project-level agent instructions (`--bare` does not use OAuth/keychain auth — it requires `ANTHROPIC_API_KEY` or an `apiKeyHelper`-backed setting):

```bash
python3 scripts/run_trigger_eval.py \
  --skill-path skills/spec-authoring \
  --eval-set tests/skills/evals/spec-authoring.json \
  --smoke --bare --model haiku --max-budget-usd 0.10 --timeout 60 \
  --plugin-dir . --transcript-dir tests/artifacts/trigger
```

Use real plugin skills only (no command shim): `--no-command-shim`.

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
  --model gpt-5.4-mini \
  --reasoning-effort low \
  --transcript-dir tests/artifacts/codex-trigger
```

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

`scripts/run_procedure_eval.py` checks more than "did the skill trigger?" It inspects stream-json tool use and optional filesystem artifacts to verify that a workflow used required skills, commands, workflows, and artifacts and did **not** run forbidden commands. For Codex and deferred adapter targets, a fixture can also provide runtime-adapter evidence patterns proving equivalent author -> critic -> revise behavior, artifact save, validator execution, and delegate-skill activation. The parser accepts Claude stream-json and current `codex exec --json` events (`command_execution`, `file_change`, `todo_list`, `agent_message`), including UTF-16 transcript files produced by some Windows capture paths.

### Modes

| Mode | Command | Use |
|---|---|---|
| Dry-run / schema | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --dry-run` | Validate the eval fixture without running a model. |
| Transcript | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --transcript tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-pass.jsonl` | Evaluate a captured transcript deterministically. |
| Live | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --live --allow-fixture-commit --max-budget-usd 5.00` | Run the prompt through Claude Code in an isolated copied fixture and evaluate the resulting transcript. |

Live mode defaults to `--permission-mode auto` so safe headless commands can run without an interactive prompt. Override it only when intentionally auditing permission behavior. `python3 scripts/run_procedure_eval.py --live` now requires `--allow-fixture-commit`, the consent for the baseline commit the harness creates inside the isolated fixture copy; without it the eval exits 2 before creating a temporary directory, running Git or starting a model.

### What it checks

For each case, the evaluator parses the transcript into a trace and checks:

| Check | Mechanism |
|---|---|
| Required skills | A `Skill` tool invocation whose payload contains the expected skill name, a mapped specialist `Agent`/`Task`, or a `required_runtime_adapters[].satisfies` entry with all adapter patterns present. |
| Required workflows | A `Workflow` tool invocation whose payload contains the expected workflow name, or a `required_runtime_adapters[].satisfies` entry with all adapter patterns present. |
| Runtime adapter evidence | Regex patterns in `required_runtime_adapters[].required_patterns` proving the runtime-equivalent path, such as `Workflow unavailable`, `Codex Adapter Gate`, `spec-plan-author`, `spec-plan-critic`, `docs/agentic-sdlc/specs/`, `docs/agentic-sdlc/plans/`, and activated delegate-skill instructions. |
| Required commands | A regex match against the `command` field of any tool invocation recorded in the trace. |
| Required artifacts | Either a `Write` tool `file_path` matching the pattern, or an existing file glob under the case working directory. |
| Artifact depth | When `check_artifact_depth` is true, written spec/plan artifacts are re-run through `validate_artifacts.py`; literal stubs such as `spec` or `plan` fail as `shallow_artifact:<path>`. |
| Forbidden commands | A regex match against recorded `command` fields; if any match, the case fails. |
| Required patterns | A regex match anywhere in the serialized trace haystack. |
| Forbidden patterns | A regex match anywhere in the serialized trace haystack. |
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

---

## Artifact validation

`scripts/validate_artifacts.py` is the deterministic spec/plan gate. It validates markdown artifacts and emits sorted flat `key=value` lines. It is pure stdlib, **read-only**, and masks any secret-shaped value as `***MASKED***`.

```bash
# Validate a spec
python3 scripts/validate_artifacts.py --mode spec --file docs/agentic-sdlc/specs/example.md

# Validate a plan against its spec
python3 scripts/validate_artifacts.py --mode plan --file docs/agentic-sdlc/plans/example.md --spec docs/agentic-sdlc/specs/example.md

# Run both spec and plan checks together
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

**For specs:**

- Required sections present: Problem, Business rules, Acceptance criteria, Edge cases, Definition of done, Must-not-change.
- Each present section has enough content (non-gating warning if thin).
- Acceptance-criteria bullets contain a testable marker (`Given`, `When`, `Then`, `returns`, `exit`, `->`, `=>`).
- Security sections cannot be bare dismissals; `security_handwave` warns on claims such as "safe string handling only" without an input-to-sink explanation.
- No `TODO`/`TBD`/`FIXME`/`XXX` placeholders remain in prose (fenced code and inline code are skipped).
- No secret-shaped content (explicit narrow patterns only; no entropy detector).

**For plans:**

- Task blocks start with `## Task N` headings or line-leading `TN` markers.
- Each task references a file to create or modify and mentions TDD or a failing test.
- Each task includes runnable verification; missing commands or expected signals warn as `task_no_verification`.
- Deferral hand-waves such as "Non-task step" or "executed later after gates" warn as `deferred_work`.
- Tasks are ordered with strictly increasing numbers.
- Every acceptance-criterion id (`AC1`, `AC2`, …) from the spec is covered by at least one task block.

> The validator is **structural only** — it cannot tell whether the spec is *about the requested work*. At the Spec Review gate also confirm the spec's topic matches the requested task (a mis-carried workflow context can yield a structurally-valid but **off-target** spec).

**For work-package identity:**

- `resolve_work_package.py` requires spec frontmatter (`work_id`, `status`) and plan frontmatter (`work_id`, `spec`, `branch`, `status`).
- It accepts only canonical roots under `docs/agentic-sdlc/specs/` and `docs/agentic-sdlc/plans/`.
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
- `completion-claim-gate` is weakest on Haiku (~0.13); under weak models it relies on the deterministic Stop hook `hooks/completion-claim-guard.mjs` backstop (12 policy tests).

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
| `check_all=failed` with `validator_tests_failed` | A unit test in `tests/` is failing. | Run `python3 -m unittest discover -s tests -v` to see the failing test. |
| `name_dir_mismatch` or `name_not_kebab` | A skill directory name does not match the `name:` frontmatter value, or the name is not kebab-case. | Rename the directory or edit `SKILL.md` frontmatter. |
| `dangling_reference` | A skill's `must_reference` entry points to a missing component. | Add the missing skill/agent/workflow/etc., or update the golden entry. |
| `safety_evidence_absent` | A safety scenario's `guardrail_evidence` substring is not found in the cited file. | Restore the guardrail text in the cited contract/skill/hook, or update the fixture if the guardrail moved. |
| `missing_section:must-not-change` | A spec is missing the Must-not-change section. | Add a `## Must-not-change (regression surface)` section to the spec. |
| `ac_not_covered:AC2` | The plan does not reference acceptance criterion `AC2`. | Add `AC2` to a task block, or adjust the spec's AC ids. |
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

Per-package evidence persists to `docs/agentic-sdlc/<slug>/evidence/<work_id>.md` — per-package only (flat packages get no evidence), overwritten in place per run (single canonical file, last run wins), git-ignored, and with no validator (it never gates resolution). That evidence write is performed by the main pipeline finalize step, not the read-only `implementation-auditor` sub-agent.

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
