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

### What each command proves

| Command | Proves |
|---|---|
| `python3 scripts/bump_version.py --check` | `VERSION`, Claude plugin metadata, Claude marketplace metadata, and Codex plugin metadata agree. |
| `python3 scripts/check_all.py` | Every `skills/<name>/SKILL.md` has valid frontmatter; name matches the directory; only allowed keys; description present and free of angle brackets; the discovered `tests/test_*.py` suites pass. |
| `python3 tests/skills/harness.py` | Skill/agent/workflow/hook/skill-contract references resolve; golden cross-references have not drifted; safety-fixture evidence is wired to real files; `${CLAUDE_PLUGIN_ROOT}` paths and `hooks.json` references resolve. |
| `python3 -m unittest discover -s tests -v` | `detect_context.py` classifies workspaces correctly; `validate_artifacts.py` enforces spec/plan structure and scans for placeholders/secrets; hook and workflow JavaScript parses under `node --check` (skipped if `node` is missing). |

### What the gate does NOT prove

- Claude Code actually chose the right skill in a live session.
- The model followed every step in a skill body or workflow.
- A human-facing end-to-end workflow succeeded without runtime errors or permission denials.
- Guardrails are obeyed when the model is under pressure.

Use live evals for those claims.

---

## Automation / CI policy

**No CI workflow is configured.** The local gate is the default health check (GitHub Actions CI was intentionally removed — see CHANGELOG `0.2.0`).

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
| `tests/test_skill_integration.py` | F | Golden `must_reference` entries appear in `SKILL.md` and resolve to real skills/agents/workflows/commands/scripts/files/contracts/hooks; plugin-root references exist; `hooks.json` is valid JSON and each referenced `.mjs` exists; workflow `agentType` values resolve to real agents; README/hooks-README claims match the tree. |
| `tests/test_skill_fixtures.py` | B / D / G | Every skill has a golden entry; golden description keywords still appear in live descriptions; safety scenarios are well-formed and their guardrail evidence exists in the cited repo files; every `tests/skills/evals/<skill>.json` is well-formed, targets a real skill, and contains both positive and negative queries. |
| `tests/test_detect_context.py` | script unit | `detect_context.py` classifies empty dirs as greenfield, counts source files, detects one vs. multiple architectural layers, ignores noise dirs, probes dependency manifests, probes toolchains, and always exits 0 even on hostile paths. |
| `tests/test_validate_artifacts.py` | script unit | `validate_artifacts.py` detects missing spec sections, thin sections, untestable acceptance criteria, placeholder tokens, secrets (masked), AC coverage gaps, and task-block ordering; `--strict` promotes warnings to errors. |
| `tests/test_static_node.py` | E | Every hook `.mjs` and every workflow `.js` passes `node --check` (workflows are wrapped the same way the Workflow runtime wraps them). Skipped if `node` is absent. |
| `tests/test_trigger_eval.py` | eval-runner unit | The Claude trigger eval runner parses fixtures, builds command shims, and detects trigger outcomes correctly. |
| `tests/test_codex_trigger_eval.py` | eval-runner unit | The Codex route-classifier trigger runner parses fixtures and classifies routes correctly. |
| `tests/test_behavior_eval.py` | eval-runner unit | The behavior eval runner validates fixture shape and matches required/forbidden patterns. |
| `tests/test_procedure_eval.py` | eval-runner unit | The procedure evaluator parses stream-json transcripts and enforces required/forbidden skills, workflows, commands, artifacts, and patterns. |
| `tests/test_hooks_policy.py` | policy unit | Hook wiring policy (block vs warn, fail-open, secret-pattern coverage). |
| `tests/test_packaging_metadata.py` | metadata unit | Plugin manifests, publishable Codex schema keys, marketplace version consistency, and `bump_version.py` behavior. |
| `tests/test_handoff_scripts.py` | script unit | `task_brief.py` and `review_package.py` CLI behavior. |

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
| **Tool-use (E)** | Hook `.mjs` + workflow `.js` parse with `node --check` | Runtime tool decisions |
| **Integration (F)** | Every cross-reference + `${CLAUDE_PLUGIN_ROOT}` path resolves | — |
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
| `tests/skills/behavior/<case>.json` | Behavior eval seeds. Each case gives a prompt and required/forbidden regex patterns. | `{ "cases": [{ "id", "prompt", "required_patterns": [...], "forbidden_patterns": [...] }] }` |
| `tests/skills/procedure/<case>.json` | Procedure eval seeds (see format below). | `{ "cases": [{ "id", "prompt", "fixture_dir?", "required_skills": [...], "required_workflows": [...], "required_runtime_adapters": [...], "required_commands": [...], "required_artifacts": [...], "forbidden_commands": [...], "required_patterns": [...], "forbidden_patterns": [...] }] }` |
| `tests/fixtures/transcripts/*.jsonl` | Sample Claude Code stream-json transcripts for deterministic procedure-eval testing. | One JSON object per line — typically `assistant`, `stream_event`, and `result` events. |

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

Isolate plugin-trigger behavior from project context such as `AGENTS.md` (`--bare` does not use OAuth/keychain auth — it requires `ANTHROPIC_API_KEY` or an `apiKeyHelper`-backed setting):

```bash
python3 scripts/run_trigger_eval.py \
  --skill-path skills/spec-authoring \
  --eval-set tests/skills/evals/spec-authoring.json \
  --smoke --bare --model haiku --max-budget-usd 0.10 --timeout 60 \
  --plugin-dir . --transcript-dir tests/artifacts/trigger
```

Use real plugin skills only (no command shim): `--no-command-shim`.

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

`scripts/run_procedure_eval.py` checks more than "did the skill trigger?" It inspects stream-json tool use and optional filesystem artifacts to verify that a workflow used required skills, commands, workflows, and artifacts and did **not** run forbidden commands. For Codex and deferred adapter targets, a fixture can also provide runtime-adapter evidence patterns proving equivalent author -> critic -> revise behavior, artifact save, validator execution, and delegate-skill activation.

### Modes

| Mode | Command | Use |
|---|---|---|
| Dry-run / schema | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --dry-run` | Validate the eval fixture without running a model. |
| Transcript | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --transcript tests/fixtures/transcripts/agentic-sdlc-pipeline-procedure-pass.jsonl` | Evaluate a captured transcript deterministically. |
| Live | `python3 scripts/run_procedure_eval.py --eval-set tests/skills/procedure/agentic-sdlc-pipeline.json --live --max-budget-usd 2.00` | Run the prompt through Claude Code in an isolated copied fixture and evaluate the resulting transcript. |

Live mode defaults to `--permission-mode auto` so safe headless commands can run without an interactive prompt. Override it only when intentionally auditing permission behavior.

### What it checks

For each case, the evaluator parses the transcript into a trace and checks:

| Check | Mechanism |
|---|---|
| Required skills | A `Skill` tool invocation whose payload contains the expected skill name, a mapped specialist `Agent`/`Task`, or a `required_runtime_adapters[].satisfies` entry with all adapter patterns present. |
| Required workflows | A `Workflow` tool invocation whose payload contains the expected workflow name, or a `required_runtime_adapters[].satisfies` entry with all adapter patterns present. |
| Runtime adapter evidence | Regex patterns in `required_runtime_adapters[].required_patterns` proving the runtime-equivalent path, such as `Workflow unavailable`, `spec-plan-author`, `spec-plan-critic`, `docs/specs/`, `docs/plans/`, and activated delegate-skill instructions. |
| Required commands | A regex match against the `command` field of any tool invocation recorded in the trace. |
| Required artifacts | Either a `Write` tool `file_path` matching the pattern, or an existing file glob under the case working directory. |
| Forbidden commands | A regex match against recorded `command` fields; if any match, the case fails. |
| Required patterns | A regex match anywhere in the serialized trace haystack. |
| Forbidden patterns | A regex match anywhere in the serialized trace haystack. |
| Runtime errors | `result` events with `is_error` true or a subtype starting with `error`. |
| Permission denials | Recorded `permission_denials` in `result` events. |

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
      "required_artifacts": ["docs/specs/", "docs/plans/"],
      "forbidden_commands": ["\\bgit\\s+commit\\b", "\\bgit\\s+push\\b", "\\bgit\\s+merge\\b"],
      "required_patterns": [],
      "forbidden_patterns": [],
      "fail_on_runtime_errors": true,
      "fail_on_permission_denials": true
    }
  ]
}
```

`fixture_dir` is optional. When present, the eval copies the fixture into a fresh temporary git repo so live runs do not mutate the real tree.

---

## Artifact validation

`scripts/validate_artifacts.py` is the deterministic spec/plan gate. It validates markdown artifacts and emits sorted flat `key=value` lines. It is pure stdlib, **read-only**, and masks any secret-shaped value as `***MASKED***`.

```bash
# Validate a spec
python3 scripts/validate_artifacts.py --mode spec --file docs/specs/example.md

# Validate a plan against its spec
python3 scripts/validate_artifacts.py --mode plan --file docs/plans/example.md --spec docs/specs/example.md

# Run both spec and plan checks together
python3 scripts/validate_artifacts.py --mode all --file docs/plans/example.md --spec docs/specs/example.md

# Promote every warning to a gating error
python3 scripts/validate_artifacts.py --mode plan --file docs/plans/example.md --spec docs/specs/example.md --strict
```

### What it checks

**For specs:**

- Required sections present: Problem, Business rules, Acceptance criteria, Edge cases, Definition of done, Must-not-change.
- Each present section has enough content (non-gating warning if thin).
- Acceptance-criteria bullets contain a testable marker (`Given`, `When`, `Then`, `returns`, `exit`, `->`, `=>`).
- No `TODO`/`TBD`/`FIXME`/`XXX` placeholders remain in prose (fenced code and inline code are skipped).
- No secret-shaped content (explicit narrow patterns only; no entropy detector).

**For plans:**

- Task blocks start with `## Task N` headings or line-leading `TN` markers.
- Each task references a file to create or modify and mentions TDD or a failing test.
- Tasks are ordered with strictly increasing numbers.
- Every acceptance-criterion id (`AC1`, `AC2`, …) from the spec is covered by at least one task block.

> The validator is **structural only** — it cannot tell whether the spec is *about the requested work*. At the Spec Review gate also confirm the spec's topic matches the requested task (a mis-carried workflow context can yield a structurally-valid but **off-target** spec).

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

## Live eval safety

Live evals spend real tokens and time. Apply these controls:

- Set `--max-budget-usd` to a small value for smoke runs (e.g. `0.10` for trigger evals, `2.00` for procedure evals).
- Use `--timeout` to cap wall-clock time; `run_trigger_eval.py` defaults to 180 s and `--smoke` caps it at 90.
- Use `--smoke` for one-query, one-run probes before running a full eval.
- Capture transcripts with `--transcript-dir` so failures can be replayed and reviewed.
- The Claude trigger runner kills the process tree as soon as a trigger decision is detected or the timeout expires.
- The Codex runner and behavior/procedure runners also terminate the subprocess on timeout.
- Run live evals only when `claude` or `codex` CLI and auth are available; if the CLI is missing, treat the result as **skipped, not passed**.
- Never leave eval artifacts containing secrets. The procedure eval copies fixtures into temporary directories and writes transcripts under `tests/artifacts/` (gitignored).

---

## Live eval findings (2026-06-18 — Haiku + Sonnet sweep)

A full live sweep on Claude Code (`claude -p`, OAuth/subscription auth) over every skill and the
pipeline run-time. Detailed transcripts live under `tests/artifacts/` (gitignored); this section is
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
| `implementasyon-control` skipped its `Skill` call (~20%), diving into `git diff` or deferring to the user | first-tool **0.80 → 1.00** (N=10) | call-order guard added to skill + router (genuine bug, fixed) |
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
| Haiku N=3 @ `$2` | **1/3** full PASS | core gates 3/3 (detect_context, validate_artifacts, feature-build, security-audit, implementasyon-control); each run drops a different gate — variance/floor. Haiku-only deviations SKILL.md already forbids: ad hoc `Workflow({script})` instead of named `spec-plan-draft`; shell/branch before the `dispatch-strategy` call-order guard. |
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
| Codex transcripts contain `WARN codex_core_plugins`/`codex_core_skills` lines (`defaultPrompt[0] must be at most 128 characters`, `icon path with '..'`) | `codex exec` loads **all** plugins installed in your user environment; these warnings come from **other** plugins (e.g. `ngs-analysis`, `chatgpt-apps`), not this repo — its `.codex-plugin/plugin.json` uses short `defaultPrompt` strings and declares no icon paths. | Harmless noise; ignore for trigger-eval results. The Codex route classifier passes skill names+descriptions inline in the prompt, so it does not depend on this repo's plugin actually loading. |

---

## Cross-references

- [README.md](../README.md) — project overview, install model, and quality gate.
- [Claude Code runtime README](../.claude-plugin/README.md) — Claude plugin loading, hooks, and native transcript gates.
- [Codex runtime README](../.codex-plugin/README.md) — Codex personal-marketplace loading, publishable manifest shape, and embedded adapter behavior.
- [docs/plugin-readme.md](plugin-readme.md) — component-by-component plugin documentation, pre-push checklist, and known limitations.
- [docs/skill-boundaries.md](skill-boundaries.md) — ownership map for every skill and layer.
- [AGENTS.md](../AGENTS.md) — operating model, evidence rules, sub-agent/workflow policy, and skill-development workflow.
- [contracts/skills/05-testing.md](../contracts/skills/05-testing.md) — the testing behavior contract (test-first, show output, no coverage theater).
- [tests/skills/README.md](../tests/skills/README.md) — focused guide to the skill harness and how to extend it.
