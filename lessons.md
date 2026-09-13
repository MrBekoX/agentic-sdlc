# lessons.md — verified, durable lessons for agentic-sdlc

Append a lesson only after a **verified** failure or wrong solution that you have reproduced, fixed, and root-caused — and only when the lesson is general enough to prevent similar mistakes in future work. Prefer enforcing each rule with a test, schema, linter, or hook over relying on this prose.

Review relevant entries before starting similar work. Keep newest entries at the top.

**Do not record:** transient network/tool errors, unverified guesses, secrets or machine-specific data, or duplicates of an existing lesson.

## Entry schema

Each entry includes:

- **Date** — `YYYY-MM-DD`
- **Task / context** — what was being done
- **Symptom** — the observable failure
- **Root cause** — the underlying reason
- **Correct fix** — what actually resolved it
- **Preventive rule / automated check** — what stops recurrence (ideally enforced)
- **Related files & tests** — paths to the change and its coverage

---

## 2026-09-12 — Toolkit identity does not establish capability compatibility

- **Task / context:** Repair the shared Claude Code/Codex authoring workflow after the dual-runtime audit.
- **Symptom:** Discovery selected the official Codex skill-creator even though its required benchmark, viewer, schema, and packaging resources were absent; a complete official Claude toolkit was installed alongside it.
- **Root cause:** The resolver checked the skill name and directory shape, then stopped at the first candidate. Same-named runtime toolkits do not necessarily expose the same operations.
- **Correct fix:** Resolve requested capability files and companion assets before selecting a candidate; report missing resources and retain explicit trust boundaries. Document native runtime eval commands separately from external toolkit operations.
- **Preventive rule / automated check:** Test an incomplete high-priority candidate with a complete official fallback, narrow validation-only selection, missing companion resources, and post-install capability revalidation.
- **Related files & tests:** `skills/skill-authoring/scripts/resolve_skill_creator.py`, `tests/test_skill_creator_resolver.py`, `skills/skill-authoring/SKILL.md`.

## 2026-09-12 — Verify component delivery before adopting a newer manifest format

- **Task / context:** Evaluate the portable manifest recommended by current OpenAI packaging documentation.
- **Symptom:** Codex 0.154.0 accepted the package and discovered all 16 skills, but returned zero hooks; identical files in the supported compatibility format returned eight hooks.
- **Root cause:** The released native loader explicitly suppresses hook loading for the portable AgentPlugin format. Successful metadata parsing and current documentation did not establish runtime component delivery.
- **Correct fix:** Retain the hook-capable compatibility manifest; record the pinned loader source and native side-by-side comparison. Keep the portable candidate only as diagnostic evidence.
- **Preventive rule / automated check:** Require native component inventory and execution proof before changing manifest precedence. A schema-valid manifest cannot stand in for hook delivery.
- **Related files & tests:** `.codex-plugin/README.md`, `docs/runtime-adapter.md`, `tests/test_packaging_metadata.py::TestPackagingMetadata.test_shipping_format_keeps_codex_hooks_loadable`.

## 2026-09-12 — Redact structured evidence before serialization without losing field context

- **Task / context:** Persist native plugin/hook probe responses and their console summaries.
- **Symptom:** Raw JSON text replacement produced invalid JSON; detached-value redaction missed an opaque credential identified by its field name. An early vendor-match return also left a second opaque credential in the same field.
- **Root cause:** Redaction ran at the wrong representation boundary and treated one detector's match as completion of all detection. File output and console/error output were not handled consistently.
- **Correct fix:** Apply the canonical credential-member detector to the original field/value, redact remaining text and property names, then serialize. Route every output sink through the same helper; keep native trust operations on fresh unredacted in-memory metadata.
- **Preventive rule / automated check:** Regression tests cover parseable JSON, nested credentials, mixed opaque/vendor values, secret-shaped property names, and unchanged plain-text behavior; independent review also checks console and exception sinks.
- **Related files & tests:** `scripts/sensitive_redaction.py`, `hooks/redact-sensitive.mjs`, `tests/test_sensitive_redaction.py`.

## 2026-09-12 — Reload procedures at restoration boundaries and separate competing process bodies

- **Task / context:** Evaluate direct entry and restored phase ownership with both plugins installed on native Claude Code and Codex.
- **Symptom:** A focused design entry announced the foreign owner but continued with inline house design content. A later Codex summary-continuation case produced design output without loading the retained owner's procedure.
- **Root cause:** The focused entry exposed the complete competing process before ownership was selected; the restored-context shortcut then treated a summary of prior work as evidence that the actual instruction body remained available.
- **Correct fix:** Keep owner selection and loading in the entrypoint, move the complete house process behind a conditional reference, and reload the selected procedure after resume/compaction/supplied summaries while preserving saved progress and completed approvals.
- **Preventive rule / automated check:** Test the loading boundary structurally and grade actual native Skill/read output before substantive phase content. Retain failed candidates and repeat the exact failed case; an owner announcement alone is not a handoff.
- **Related files & tests:** `skills/mind-spark/SKILL.md`, `skills/mind-spark/references/design-process.md`, both SessionStart hooks, `tests/test_process_owner_policy.py`; native direct-entry and restored-owner regression captures under `tests/artifacts/dual-runtime-remediation/`.

## 2026-09-12 — Separate native status metadata from echoed tool content

- **Task / context:** Update the rollout reader using actual Codex 0.154.0 successful patch and shell output records.
- **Symptom:** Historical carriers missed real successful edits and exit statuses. The first compatibility fix then accepted success headers echoed inside a denied patch as evidence of a write.
- **Root cause:** Correlating a response with its call proves identity, not success. Searching the whole response body for native-looking headers lets rejected input manufacture execution evidence.
- **Correct fix:** Parse only leading native metadata, stop at the output boundary or unknown text, and require the correlated custom-tool output's actual success body. Reject conflicting and mismatched carrier records.
- **Preventive rule / automated check:** Preserve real carrier provenance, mutate the captured denial envelope, and check the downstream ordering decision as well as the parser. Keep replay verification distinct from native execution of the final source.
- **Related files & tests:** `hooks/codex-rollout.mjs`, `tests/test_codex_current_rollout.py`, `tests/fixtures/transcripts/codex-0.154.0-native-tool-carriers.jsonl`, `tests/artifacts/dual-runtime-remediation/native-parser-review.md`.

## 2026-08-23 — When a layer is provably incomplete, add a layer; do not keep patching it

- **Task / context:** After ten adversarial rounds hardened the PreToolUse command guards, the loop was still producing real findings. The remaining gaps were not bugs — they were the layer's definition.
- **Symptom:** Every surviving bypass shared one shape: something the SHELL resolves after the hook has already decided. A shell function named `gc` wrapping `git commit`; `eval "$(printf 'git com'; printf 'mit')"`; `C=commit; git $C`; and writes through `tee`, `base64 -d` or `python -c` — none of which a command-string reader can see, and no amount of parser work changes that. Patching harder was producing narrower and narrower fixes (a mid-name `.pub.`, a `printf` octal escape) while the structural hole stayed open.
- **Root cause:** The guard was installed at the wrong altitude. A PreToolUse hook receives a STRING and must predict an EFFECT; deciding what an arbitrary shell command does is undecidable, so the layer can only ever be a probabilistic backstop. Ten rounds of fixes raised its recall — they could not change its category.
- **Correct fix:** Add layers that observe the effect instead of predicting it. Git runs `pre-commit` / `pre-merge-commit` / `commit-msg` / `prepare-commit-msg` on the OPERATION, after it has resolved its own alias table and the shell has done quote removal and `$PATH` lookup; a Stop-time scan reads bytes on disk, so the write form is irrelevant. Both reuse the SAME hardened detection primitives, so the ten rounds' work carries over untouched — the new layers add reach, not a second scanner to keep in sync. Measured result: 12/12 of the previously-unreachable techniques are now caught, controls still clean.
- **Preventive rule / automated check:** Before hardening a guard for another round, ask what LAYER it sits at and whether the residuals are bugs or definitional. If the residual list is "everything the runtime resolves after we decide", stop patching and add an observation point lower down. Then state each layer's limit in its own file header — `--no-verify`, `core.hooksPath=/dev/null`, `Stop` not firing on user interrupt — and pin them with tests, so the layering is never mistaken for completeness. Two details that only showed up by reading the primary docs and testing: `prepare-commit-msg` is the one commit-path hook `--no-verify` does NOT suppress (so it is the strongest client-side slot, not `pre-commit`), and `git ls-files --others --exclude-standard` hides gitignored files — which is exactly where `.env` lives.
- **Related files & tests:** `hooks/git-hook-scan.mjs`, `hooks/worktree-scan.mjs`, `scripts/install_git_hooks.py`; `tests/test_effect_layer_guards.py`.

---

## 2026-08-23 — Enumerate the decoding layers between the string you inspect and the bytes that land

- **Task / context:** Rounds 5–9 of the adversarial loop over the PreToolUse guards. The loop ran until each round's findings were exotic rather than routine; 22 distinct defects were closed across nine rounds.
- **Symptom:** After the obvious bypasses were closed, every remaining one was a TRANSFORMATION the guard did not model — the command string it reads is not the bytes that reach the sink:
  - `git commit -m $'\x73\x6b...'` — bash ANSI-C quoting is decoded by the shell; history records `sk-...` while the guard reads `$'\x73...'`.
  - `$'\x67\x69\x74' commit` — the same trick applied to the COMMAND NAME, which slipped past the cheap `\bgit\b` pre-filter that ran before decoding.
  - `printf '\163\153\137...' > f` — POSIX printf decodes backslash escapes in its FORMAT string unconditionally (no `-e` needed), and `echo -e` does the same; the file gets `sk_live_...` while the extractor saw `163153137...` and still reported `parsed:true`.
  - `git commit -am"<secret>"` — git bundles short options, so the message token starts with `-a`, not `-m`.
- **Root cause:** A guard that reads `tool_input.command` sits ABOVE several independent decoders — the shell's quoting rules, git's own option bundling and alias table, and the invoked program's own escape processing (printf's format string). Each is a separate layer, and modelling one says nothing about the others. Closing "the quoting bug" three times in three different layers is the symptom of not having enumerated them.
- **Correct fix:** Decode what is decodable and scan a UNION rather than a replacement — the raw text AND its decoded form, so a decoder that is wrong or incomplete can only add detections, never remove one. `hooks/shell-quoting.mjs` centralises ANSI-C decoding; `payloadText` + `stripQuoteDelimiters` keep a backslash-preserving copy so escape decoding still has something to work on; the commit-message reader models git's actual short-option bundling.
- **Preventive rule / automated check:** Before shipping a guard that inspects a command string, write down every layer that transforms it between inspection and effect — shell quoting forms (`'...'`, `"..."`, `$'...'`, backslash), shell alias/function tables, the tool's own option grammar, and the invoked program's escape processing. Decode the ones you can and DECLARE the rest unread. When in doubt, scan the union of interpretations: over-approximating what you scan is safe, under-approximating is a bypass. And run the adversarial loop until the findings stop being routine — rounds 7, 8 and 9 each found a real defect that the previous round's fix had introduced.
- **Related files & tests:** `hooks/shell-quoting.mjs` (new), `hooks/codex-write-signal.mjs` (`stripQuoteDelimiters`, union push), `hooks/git-invocation.mjs` (`commitMessages`, `commitSweepsUnstaged`, `targetCwdsFor`), `hooks/scan-commit-names.mjs` (terminal-only `.pub`), `hooks/scan-commit.mjs`, `hooks/branch-guard.mjs`; `tests/test_secret_guard_bypasses.py::TestRoundFiveResiduals` through `::TestRoundNineResiduals`.

---

## 2026-08-23 — A new component must re-ask every question its neighbours already answered

- **Task / context:** Rounds 3 and 4 of an adversarial review loop over the guard fixes. Each round audited the previous round's output; the loop only stopped finding real defects after round 5.
- **Symptom:** Six further defects, and they share one shape. `hooks/git-invocation.mjs` was written as the new, correct way to decide "is this a git commit?" — and it independently re-lost capabilities the sibling guard `destructive-command-guard.mjs` had carried for months:
  - `(git commit -am x)` and `{ git commit -am x; }` were **completely invisible** (severity: critical). The first token is `(git`, whose basename is not `git`, so the resolver returned nothing and BOTH guards exited. The sibling guard has stripped subshell wrappers all along.
  - `git -C /tmp status; git commit -am '<token>'` redirected the COMMIT's diff read to `/tmp`, because every `-C` on the line was collected into one shared array instead of being scoped to the call that carried it.
  - `alias.ci = "commit -a"` meant `git ci` really swept unstaged tracked files, but the `-a` widening test still ran against the RAW typed string — the resolver's expansion was sitting one line away, already used for message scanning.
  - `cat <<-EOF > f` (tab-stripping heredoc) was neither read nor flagged, so `parsed:true` came back on an unread write — the third instance of the same CWE-636 shape in one work package.
  - `id_rsa.pub` was denied. The public half of a keypair is exactly what you are meant to commit; a guard that blocks routine safe work is the fastest way to get itself switched off.
- **Root cause:** Writing a focused new module makes it feel finished when it handles the case that motivated it. But a guard's real contract is the union of every evasion its neighbours already handle, plus every spelling of the operation it claims to recognize. Nothing in the codebase forced the new resolver to inherit the old one's wrapper stripping, and nothing forced the `-a`/heredoc/`.pub` paths to be re-derived from the new resolver instead of from the raw string.
- **Correct fix:** Strip group wrappers linearly before tokenizing; scope `-C` per statement and expose `targetCwdFor(info, subcommand, baseCwd)` so a consumer asks for the cwd of the call it actually cares about; test the RESOLVED texts everywhere the raw command was tested; accept `<<-` and mark any surviving `<<` as unread; carve `.pub` out of the credential-filename rule.
- **Preventive rule / automated check:** When you add a component that answers a question an existing component already answers, diff their capability lists before shipping — and port the old one's evasion handling deliberately, not by luck. When a fix introduces a resolver, grep the same file for every OTHER place that still tests the raw input the resolver was built to replace; those are the next bugs. And keep the adversarial loop running until a round comes back empty: rounds 2, 3 and 4 each found defects the previous round's fix had introduced, including one worse than anything in the original code.
- **Related files & tests:** `hooks/git-invocation.mjs` (`stripGroupWrappers`, per-statement `calls[]`, `targetCwdFor`), `hooks/scan-commit.mjs`, `hooks/branch-guard.mjs`, `hooks/codex-write-signal.mjs`, `hooks/scan-commit-names.mjs`; `tests/test_secret_guard_bypasses.py::TestRoundThreeResiduals`, `::TestRoundFourResiduals`.

---

## 2026-08-22 — Re-review the FIX: closing six bypasses introduced five more, one of them worse

- **Task / context:** After closing six verified fail-open bypasses in the PreToolUse guards, the same adversarial multi-lens review was pointed at the fix itself instead of at the original code.
- **Symptom:** Five real defects, all reproduced by execution. Ranked by what they teach:
  1. **The fix introduced a catastrophic ReDoS.** Supporting derived credential names added `(?:\.[A-Za-z0-9]{1,8}|~)*$` — an AMBIGUOUS REPEATED GROUP in front of an end anchor. Measured on `id_rsa` + `.a`xN + `!`: 459 ms at N=8, 1.16 s at N=10, **20.6 s at N=12**. A staged filename is agent-influenced, so the commit guard would blow past its 20 s budget and the runtime then fails open — the hardening became the bypass.
  2. **A cheap pre-filter silently undid the expensive resolver behind it.** Both guards gained `if (!/git/i.test(cmd)) exit;` in front of a new quote-aware tokenizer written precisely to handle `g'i't commit` — which contains no contiguous `git`, so the tokenizer never ran.
  3. Syntactic parsing without propagation: `-C <dir>` was parsed to find the subcommand but never passed to the git subprocesses, so alias lookup and `git diff` read the wrong repository.
  4. Resolution that discards its own intermediate result: the alias expansion was used to detect a commit and then thrown away, so a secret inside the ALIAS DEFINITION's `-m` was never scanned.
  5. A denylist extended for one spelling only: `UNREAD_WRITE` matched `sed -i` but not `sed --in-place`, restoring the parsed:true-on-an-unread-write shape the same commit claimed to have removed.
- **Root cause:** Each is the same failure at a different layer — a new component was added without re-asking the question the component was there to answer. The ReDoS specifically is the previously-recorded `/\s*\)$/` lesson in a new shape: the trap is not "greedy whitespace", it is **any ambiguous quantifier that can be split many ways sitting before an anchor that may fail**.
- **Correct fix:** Replace the suffix regex with a linear split-and-check function (20.6 s → 0.01 ms, flat across a 16x input range); strip quote/backslash delimiters before any cheap pre-filter so it can never be narrower than the resolver it guards; propagate `-C`/payload `cwd` into every git subprocess; return alias expansion TEXTS from the resolver and scan messages from all of them; cover both option spellings.
- **Preventive rule / automated check:** (a) A security fix is not done until the fix itself has been adversarially reviewed — the round that audits the patch found a worse defect than the round that audited the original. (b) Never place an ambiguous repeated group before an anchor in a scanner on agent-influenced input; measure at 8/10/12 repetitions before shipping, because the curve is invisible at small N. (c) A cheap pre-filter in front of a precise resolver must be a strict SUPERSET of it. (d) If you parse an option to make a decision, propagate it to every side effect that decision drives.
- **Related files & tests:** `hooks/scan-commit-names.mjs` (new, linear), `hooks/git-invocation.mjs` (`resolveGitCommands`, per-call alias-lookup cwd), `hooks/scan-commit.mjs`, `hooks/branch-guard.mjs`, `hooks/codex-write-signal.mjs`; `tests/test_secret_guard_bypasses.py::TestFixResiduals`.

---

## 2026-08-22 — A recognition flag must default to FALSE ("I parsed it" vs "I saw no `$`")

- **Task / context:** Closing a fail-open in `hooks/codex-write-signal.mjs`, the pure write-content extractor behind the Codex pre-write secret guard.
- **Symptom:** `echo "" <github-token> > notes.txt` reached the guard as `addedContent: ""`, `targets: ["notes.txt"]`, **`parsed: true`** — the guard scanned an empty string, allowed the write, and the shell wrote the token to disk. The same `parsed: true` came back for `tee`, `dd`, `sed -i`, `cp`, `>|` and `&>` — every form the file's own header comment claimed was reported `parsed:false`.
- **Root cause:** Two independent optimistic defaults. (1) `parsed` was computed as `!hasExpansion`, and `hasExpansion` was set on only two code paths, so it meant "I saw no `$` or backtick", never "I accounted for this command"; every "I do not recognize this form" path was a bare `continue` that left the flag true. (2) `extractLiteral()` returned only the text between the FIRST pair of quotes (or a bare word with no whitespace) and dropped the rest of the payload, so a multi-token `echo`/`printf` argument list was silently truncated. This is OWASP "fail securely" / CWE-636: an optimistic initial value that survives every path that failed to disprove it.
- **Correct fix:** Under-approximate RECOGNITION and over-approximate CONTENT — they must go in opposite directions. `parsed` now starts from an explicit `unreadWrite = false` that any unrecognized write form flips; the payload scanner reads the WHOLE argument list (quote delimiters stripped) instead of its first literal token, because the byte set scanned must be a superset of what lands on disk while the DENY decision stays exact (a HIGH pattern is a vendor-shaped token that neighbouring text cannot manufacture).
- **Preventive rule / automated check:** In any scanner or guard, a flag that answers "did I understand this input?" is initialised to the unsafe-to-assume value (`false`) and set true only on the specific paths that produced a complete reading; never derive it from the absence of one particular hazard. Assert it: a test must show that a payload the extractor drops cannot also come back with the flag set (`test_parser_never_claims_parsed_while_dropping_payload`).
- **Related files & tests:** `hooks/codex-write-signal.mjs` (`parseBash`, `payloadText`, `UNREAD_WRITE`); `tests/test_secret_guard_bypasses.py::TestCodexWriteLiteralTruncation`.

---

## 2026-08-22 — Never apply a "probably not real" heuristic to a value that already passed a structural test

- **Task / context:** Closing a false-negative class in `hooks/secret-patterns.mjs`, the shared secret scanner used by both runtimes' commit and write guards.
- **Symptom:** Verified by execution (agentic-sdlc:allow-secret) — `sk_test_xxxx…`, `ghp_xxxx…`, `password=MyRealSecretExample8412`, and a JSON credential value containing a single `<` were all reported clean and committed unblocked.
- **Root cause:** One unanchored substring regex (`…|example|x{4,}|\$\{|<|>|…`) was applied to whatever the pattern matched. Nine of the eleven HIGH patterns carry no `valueGroup`, so the "value" it inspected was the ENTIRE vendor-shaped token — one that had already passed a strict, vendor-published shape test. A placeholder heuristic designed for a user-authored right-hand side was silently deciding the fate of issued credentials.
- **Correct fix:** Route by pattern KIND. Captured (user-authored) values keep the heuristic, but as ANCHORED whole-value predicates (`^<…>$`, `^\$\{…\}$`, `^process\.env`) instead of substring probes. Vendor-shaped tokens are never keyword-filtered: they are suppressed only when structurally degenerate (one character dominating, or a monotonic run — the pattern filter from Meli et al., NDSS 2019) or when they match a published doc sample EXACTLY. This is what the mature scanners do: gitleaks attaches its stopword list only to the generic rule and gates vendor rules on entropy; detect-secrets hard-disables its context heuristic for regex-based detectors; trufflehog applies keyword filtering only to results it could not verify as live.
- **Preventive rule / automated check:** A suppression rule must be scoped to the detector it was designed for, and stated as an anchored predicate over the whole value — a substring probe in a security filter suppresses a class, not an instance. Any new suppression needs a paired test: the bypass it must NOT create, and the false positive it must still prevent.
- **Related files & tests:** `hooks/secret-patterns.mjs` (`TEMPLATE_VALUE`, `DOC_SAMPLES`, `isDegenerateToken`, `scanLines`); `tests/test_secret_guard_bypasses.py::TestPlaceholderFilterOnVendorTokens`, `::TestTokenBoundaryAnchoring`.

---

## 2026-08-22 — A guard gated on a raw command substring is defeated by aliasing; a narrowing wiring filter disables it outright

- **Task / context:** Closing two bypasses of `hooks/scan-commit.mjs` and `hooks/branch-guard.mjs`.
- **Symptom:** `git config alias.ci 'commit -a'` followed by `git ci -m x` performed a real commit — sweeping unstaged changes — with both guards completely silent. Separately, on a Windows host without Git Bash no command guard fires at all.
- **Root cause:** Three layers of the same mistake. (1) Each guard gated its whole logic on `/git[\s\S]*commit/` over the raw command; an alias carries neither word. (2) `hooks/hooks-claude.json` narrowed the hooks with `"if": "Bash(git commit*)"`, so for `git ci` the hook PROCESS never started and no internal fix could have helped — and the runtime documents `if` as best-effort, recommending the permission system for a hard allow/deny. (3) `matcher: "Bash"` — Claude Code does not register the Bash tool on Windows without Git Bash, so a Bash-only matcher is inert there.
- **Correct fix:** Move the decision into the guard and make it resolve what git will ACTUALLY run: `hooks/git-invocation.mjs` expands git aliases the way git does (chains, `!shell` aliases, `-c alias.x=y`), skipping global options and wrappers, over a quote-aware tokenizer. Wiring matches `Bash|PowerShell` with no `if` filter; each guard self-gates cheaply on `git` first.
- **Second instance, found four rounds later:** bash's ANSI-C quoting `$'...'` is decoded by the SHELL before the command runs, so `git commit -m $'\x73\x6b\x2dlive\x2d...'` records `sk-live-...` in permanent history while the raw token the hook reads contains no vendor-shaped text at all. The write extractor had the same blind spot AND returned `parsed:true` over content that was never going to be written. The general rule: enumerate every transformation the shell applies between the string your hook receives and the bytes that actually land — quoting forms, alias tables, expansion — and either decode the ones you can (ANSI-C quoting, git aliases) or declare the rest unread. `hooks/shell-quoting.mjs` decodes the first class; the second stays documented as out of reach.
- **Preventive rule / automated check:** Never let a wiring-level filter be the security boundary — it can only ever remove your guard, never add safety. And a pre-execution string gate cannot be alias-proof by construction: shell aliases/functions, `$PATH` shadowing and `eval` resolve AFTER the hook decides. Resolve what is resolvable (git's own alias table), state the residual in the file header, and treat the hook as a backstop rather than an enforcement boundary. Assert the wiring itself in a test (`TestGuardWiring`), not just the script.
- **Related files & tests:** `hooks/git-invocation.mjs` (new), `hooks/scan-commit.mjs`, `hooks/branch-guard.mjs`, `hooks/hooks-claude.json`; `tests/test_secret_guard_bypasses.py::TestGitAliasGuardBypass`, `::TestGuardWiring`, `::TestCommitMessageScan`.

---

## 2026-07-01 — A greedy `\s*`/`\s+` before a `$` end-anchor is O(n²) (ReDoS in command parsers)

- **Task / context:** B5 (#5) closing the Codex flow-order write-form bypass — new `preciseWriteTargetsOf` in `hooks/codex-rollout.mjs` re-implemented a subshell-strip helper as `seg.trim().replace(/^\(\s*/, '').replace(/\s*\)$/, '')`, mirroring the existing `parseBash` in `hooks/codex-write-signal.mjs`.
- **Symptom:** Security review measured the strip at ~1.1 s (40 KiB) → ~4.3 s (80 KiB) → ~17.6 s (160 KiB) on `"echo" + " ".repeat(N) + "x"` — a clean 4×-per-2× quadratic. At the 512 KiB command cap that hangs the PreToolUse hook for minutes; under `AGENTIC_FLOW_ORDER_BLOCK` the timeout then fail-opens → the hardening becomes a self-inflicted DoS/bypass. Triggered by ANY long internal whitespace run with no trailing `)` (not just a write).
- **Root cause:** `/\s*\)$/` is unanchored at the start, so the engine retries from every index in the whitespace run; each retry's greedy `\s*` scans to end then backtracks to find the required `)`+`$` — O(n) work × O(n) start positions = O(n²). The `$`-anchored greedy-whitespace shape is the trap, independent of the `g` flag.
- **Correct fix:** Replace with linear string ops — `trim()`, then single-char `slice` for a leading `(` / trailing `)`, then `trim()` again. No regex with a start-unanchored greedy `\s*` before `$`.
- **Preventive rule / automated check:** Never put a greedy `\s*`/`\s+` (or `[\s\S]*`) immediately before a `$` end-anchor in a scanner that runs on attacker/agent-influenced input; prefer `trim()`/two-pointer strips. A "linear (BR10)" claim in a comment is not evidence — add a timing regression test on a long internal-whitespace input (see `test_precise_scan_linear_internal_whitespace`). **Known residual:** the identical twin at `hooks/codex-write-signal.mjs:69` (`parseBash`) is byte-locked and pre-existing; it is reachable by default via the always-on `scan-write-codex.mjs` secret guard on every Bash command — a separate follow-up (needs a byte-lock rebaseline), not fixed in #5.
- **Related files & tests:** `hooks/codex-rollout.mjs` (`stripWrappingSubshell`); `tests/test_codex_flow_order_guard.py` (`test_precise_scan_linear_internal_whitespace`, `test_precise_scan_linear`, `test_raw_scan_linear_flood`).

---

## 2026-06-21 — Python interpreter is `python3`, not `python`

- **Task / context:** Running the quality gate (`scripts/check_all.py`, `tests/skills/harness.py`, the unittest suite).
- **Symptom:** Commands invoked as `python ...` fail or select the wrong interpreter where `python` is Python 2 or absent.
- **Root cause:** The project standardizes on `python3`; bare `python` is not guaranteed to exist or resolve to Python 3.
- **Correct fix:** Invoke every gate command and script with `python3`.
- **Preventive rule / automated check:** The gate commands in `AGENTS.md` and `CLAUDE.md` pin `python3`; keep new docs and scripts consistent. (This entry documents an existing repo convention rather than a new incident.)
- **Related files & tests:** `AGENTS.md`, `CLAUDE.md`, `scripts/check_all.py`, `tests/skills/harness.py`.
