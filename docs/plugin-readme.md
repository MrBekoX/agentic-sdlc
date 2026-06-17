# AGENTIC-SDLC Claude Code / Codex Plugin README

## Kısa Tanım

AGENTIC-SDLC, Claude Code ve Codex için geliştirilmiş yerel/geliştirme amaçlı bir skill pluginidir. Amacı, üretim etkisi olan işleri rastgele edit akışından çıkarıp disiplinli bir **spec -> plan -> TDD -> security -> review** yaşam döngüsüne bağlamaktır.

Bu plugin şu an Claude Code ve Codex manifestleriyle çalışacak şekilde modellenmiştir. Cursor, Kimi, OpenCode, Gemini, Pi ve diğer harness entegrasyonları bilinçli olarak ertelenmiştir.

Önemli sınır: Bu repo bir yayınlama pipeline'ı değildir. `.claude-plugin/` metadata'sı lokal geliştirme ve doğrulama içindir. Şimdilik CI workflow yoktur; plugin yayınlama, release oluşturma, commit/push otomasyonu ve marketplace yayını yalnızca açık kullanıcı isteğiyle manuel yapılır.

## Ne Sağlar?

Plugin, Claude Code içinde tekrarlanabilir agentic SDLC davranışı üretmek için katmanlı bir kontrol sistemi kurar:

| Katman | Rol |
|---|---|
| `skills/` | İş akışlarının prosedürleri ve trigger yüzeyi. |
| `agents/` | Fresh-context uzman rolleri: analiz, test, security, audit, review. |
| `workflows/` | Tekrarlanabilir author/critic multi-agent döngüleri. |
| `hooks/` | Deterministik güvenlik ve runtime guardrail'leri. |
| `contracts/skills/` | Skill davranış sözleşmeleri. |
| `commands/` | Manuel çağrılan kontrol komutları. |
| `scripts/` | Makineyle doğrulanabilir yardımcılar ve eval runner'ları. |
| `tests/` | Deterministik test, fixture, golden ve procedure eval altyapısı. |
| `.claude-plugin/` | Claude Code plugin metadata ve local marketplace tanımı. |
| `.codex-plugin/` | Codex plugin metadata ve hook tanımı. |

## Kurulum Modeli

Plugin metadata:

- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
- `.codex-plugin/plugin.json`

`marketplace.json`, plugin kaynağını repo root'u olarak tanımlar:

```json
"source": "./"
```

Claude Code tarafında bu repo lokal marketplace/plugin source olarak eklenir. Codex tarafında `.codex-plugin/plugin.json` root `skills/` ve `hooks/hooks-codex.json` dosyalarını işaret eder. Skill'ler root `skills/` altındadır; `.claude/skills/` veya `.codex/skills/` kullanılmaz.

Claude runtime path'leri `${CLAUDE_PLUGIN_ROOT}`, Codex runtime path'leri `${PLUGIN_ROOT}` üzerinden çözülür. Bu yüzden hook'ların beklenen çalışma modeli, repo'nun plugin olarak yüklenmesidir.

## Runtime Gereksinimleri

| Gereksinim | Neden Gerekli? |
|---|---|
| Claude Code / Codex | Desteklenen runtime'lar. |
| Node.js | Hook scriptleri `.mjs` olarak çalışır. |
| Python | Test, validator ve eval helper scriptleri için. |
| Git | Branch guard, diff review, review package, commit/PR akışları için. |

Non-git workspace içinde bazı akışlar çalışmaya devam eder, ancak branch, commit, PR, worktree ve release adımları açık notla skip edilmelidir.

## Ana Kullanım Akışları

### `using-agentic-sdlc`

Plugin'in session-local router girişidir. Her kullanıcı prompt'unda en küçük yeterli skill'i seçer, konuşma içindeki aktif intent/artifact/scope shift sinyalini takip eder ve yalnızca full-envelope end-to-end SDLC gerektiğinde `agentic-sdlc-pipeline`'a yükseltir.

Router ilkesi:

- fikir / belirsiz tasarım -> `mind-spark`
- sadece spec -> `spec-authoring`
- sadece plan -> `plan-authoring`
- yeni feature -> `feature-build`
- bug fix -> `root-cause-fix`
- sadece test -> `test-authoring`
- refactor -> `safe-refactor`
- review/security/final claim -> ilgili focused skill
- end-to-end production-ready SDLC -> `agentic-sdlc-pipeline`

### `agentic-sdlc-pipeline`

Full-envelope escalation path'tir. Üretim etkisi olan işleri ancak uçtan uca spec, plan, TDD, security, review ve final audit gerektiğinde yönetir.

Full Mode akışı:

1. `dispatch-strategy` ile yürütme mekanizmasını seçer.
2. `detect_context.py` ile workspace'i deterministik sınıflandırır.
3. Claude Code'da `spec-plan-draft` workflow ile, Codex'te agentic-sdlc-pipeline embedded author/critic adapter ile spec taslağı üretir.
4. Spec'i `validate_artifacts.py` ile doğrular.
5. Claude Code'da `spec-plan-draft` workflow ile, Codex'te agentic-sdlc-pipeline embedded author/critic adapter ile plan üretir.
6. Planı strict mode'da doğrular.
7. Uygulama çekirdeğini uygun flow skill'e delege eder.
8. Security review gate'lerini çalıştırır.
9. Quality gate ve `/git-safety-check` çalıştırır.
10. `implementasyon-control` ile pre-final audit yapar.
11. Final başarı iddiasından hemen önce `completion-claim-gate` çalıştırır.

`agentic-sdlc-pipeline` outer envelope sahibidir. Uygulamanın çekirdeğini kendisi yapmaz; işi şu skill'lerden birine devreder:

- `root-cause-fix`
- `feature-build`
- `safe-refactor`
- `test-authoring`

`spec-authoring` ve `plan-authoring` sadece bağımsız prompt girişleri içindir. `agentic-sdlc-pipeline`, kendi step 4-5 fazlarında bu iki skill'i çağırmaz.

### Dar Kapsamlı Skill'ler

| Skill | Ne Zaman Kullanılır? |
|---|---|
| `spec-authoring` | Sadece WHAT/spec, acceptance criteria veya requirements contract istendiğinde. |
| `plan-authoring` | Sadece HOW/implementation plan, task breakdown veya sequencing istendiğinde. |
| `root-cause-fix` | Bug, prod issue, broken behavior, failing test. |
| `feature-build` | Yeni feature, endpoint, capability. |
| `safe-refactor` | Davranış değişmeden yeniden yapılandırma. |
| `test-authoring` | Test-only çalışma, regression/e2e/unit/integration testleri. |
| `security-audit` | Security lens: auth, IDOR, injection, secrets, data exposure. |
| `code-quality-review` | Fresh-context kalite review'u. |
| `feedback-triage` | Alınmış PR/MR/bot review yorumlarını doğrulayıp uygulama. |
| `mind-spark` | Belirsiz build/design isteği öncesi intent netleştirme. |
| `skill-authoring` | Skill yazma, düzenleme, eval, packaging. |
| `implementasyon-control` | Final öncesi akışın gerçekten izlendiğini audit etme. |
| `completion-claim-gate` | "done/fixed/passing/ready" demeden önce kanıt kontrolü. |
| `dispatch-strategy` | Main loop/subagent/workflow/agent-team karar otoritesi. |

Gerçek skill adı `implementasyon-control` olarak kalmıştır. İsim karışık dilli olsa da mevcut invocation ve testler bu adı kullanır.

## Agents

`agents/` altındaki dosyalar Claude Code sub-agent rol kontratlarıdır:

- `context-analyst`
- `debugger`
- `code-reviewer`
- `security-reviewer`
- `implementation-auditor`
- `software-architect`
- `test-engineer`
- `spec-plan-author`
- `spec-plan-critic`

Bu roller ana context'i kirletmeden bağımsız analiz, review, audit veya draft işlerini yürütmek için kullanılır.

## Workflows

`workflows/` altında Claude Code için iki deterministic multi-agent workflow vardır:

| Workflow | Görev |
|---|---|
| `spec-plan-draft.js` | Spec/plan için author -> critic -> revise döngüsü. |
| `skill-draft.js` | Skill yazımı için author/critic döngüsü. |

`spec-plan-draft.js`, eksik context durumunda fail-loud davranır ve Claude Code işlerinde ad hoc workflow yerine bu named workflow kullanılmalıdır. Codex'te Claude Workflow runtime yoktur; aynı author/critic disiplin agentic-sdlc-pipeline'un embedded adapter'ı ile uygulanır.

## Commands

`commands/git-safety-check.md`, read-only bir güvenlik kontrol komutudur. Commit öncesi şu sinyalleri kontrol eder:

- `git status`
- diff/stat
- staged secret pattern'leri
- branch safety
- commit readiness

Komut commit/push yapmaz.

## Hooks ve Guardrail'ler

Runtime hook'ları [hooks/hooks.json](../hooks/hooks.json) üzerinden bağlanır.

| Hook | Davranış |
|---|---|
| `scan-commit.mjs` | `git commit` sırasında added diff içinde high-confidence secret bulursa commit'i block eder. |
| `scan-write.mjs` | Write/Edit/MultiEdit sonrası secret-shaped içerik için uyarır; block etmez. |
| `branch-guard.mjs` | `main`/`master` commit/push için uyarır; `AGENTIC_BRANCH_GUARD_BLOCK=true` ise block eder. |
| `destructive-command-guard.mjs` | `git reset --hard`, forceful `git clean`, `rm -rf`, `Remove-Item -Recurse -Force` gibi komutları block eder. |
| `session-start.mjs` | Git status ve AGENTIC-SDLC bootstrap context'i session'a enjekte eder. |
| `secret-patterns.mjs` | Ortak scanner; secret değerini yazmaz, sadece label ve line bilgisi verir. |

Judgment gerektiren guardrail'ler hook scriptleriyle değil, skill contract ve skill gate'leriyle uygulanır:

- `contracts/skills/05-testing.md`
- `contracts/skills/06-security.md`
- `contracts/skills/08-git-safety.md`
- `skills/completion-claim-gate/SKILL.md`
- `skills/implementasyon-control/SKILL.md`

## Deterministik Scriptler

| Script | Amaç |
|---|---|
| `check_all.py` | Repo gate: skill frontmatter + unittest discovery. |
| `validate_artifacts.py` | Spec/plan yapı doğrulama, placeholder/secret scan, AC coverage. |
| `detect_context.py` | Workspace sınıflandırma, dependency/toolchain probe. |
| `run_trigger_eval.py` | Windows-safe live Claude trigger eval runner. |
| `run_codex_trigger_eval.py` | Codex route-classifier trigger eval runner. |
| `run_behavior_eval.py` | Behavior fixture dry-run/live validator. |
| `run_procedure_eval.py` | Transcript/live procedure evaluator. |
| `bump_version.py` | `VERSION`, plugin manifest ve marketplace version senkronizasyonu. |
| `task_brief.py` | Plan içinden tek task brief çıkarıp sub-agent handoff dosyası üretir. |
| `review_package.py` | Git diff review package üretir. |

## Test ve Eval Katmanları

Yerel deterministik test stack'i şunları kapsar:

- Skill frontmatter ve isim uyumu
- Agent/workflow/hook/skill contract/script referansları
- Golden description drift
- Safety fixture evidence
- Hook/workflow JavaScript syntax
- Plugin metadata/version consistency
- Artifact validator testleri
- Procedure evaluator fixture testleri

Normal local gate:

```powershell
python scripts\check_all.py
python tests\skills\harness.py
python -m unittest discover -s tests -v
```

Version check:

```powershell
python scripts\bump_version.py --check
```

Behavior/procedure dry-run:

```powershell
python scripts\run_behavior_eval.py --eval-set tests\skills\behavior\completion-claim-gate.json --dry-run
python scripts\run_procedure_eval.py --eval-set tests\skills\procedure\agentic-sdlc-pipeline.json --dry-run
python scripts\run_procedure_eval.py --eval-set tests\skills\procedure\agentic-sdlc-pipeline.json --transcript tests\fixtures\transcripts\agentic-sdlc-pipeline-procedure-pass.jsonl
```

Live eval'lar Claude CLI/auth/runtime gerektirir ve normal lokal gate'in parçası değildir.

## Otomasyon Politikası

Şimdilik CI workflow yoktur. Sağlık kontrolü lokal komutlarla yapılır:

- `python scripts/check_all.py`
- `python tests/skills/harness.py`
- `python -m unittest discover -s tests -v`

Yayınlama, release, otomatik commit/push ve marketplace/plugin publication bu repo içinde otomatikleşmemiştir. Bunlar yalnızca açık kullanıcı isteğiyle, ayrı ve manuel bir işlem olarak yapılmalıdır.

## Push Öncesi Kontrol Listesi

GitHub'a push etmeden önce önerilen komutlar:

```powershell
git status --short --branch
python scripts\bump_version.py --check
python scripts\check_all.py
python tests\skills\harness.py
python -m unittest discover -s tests -v
python scripts\run_behavior_eval.py --eval-set tests\skills\behavior\completion-claim-gate.json --dry-run
python scripts\run_procedure_eval.py --eval-set tests\skills\procedure\agentic-sdlc-pipeline.json --dry-run
python scripts\run_procedure_eval.py --eval-set tests\skills\procedure\agentic-sdlc-pipeline.json --transcript tests\fixtures\transcripts\agentic-sdlc-pipeline-procedure-pass.jsonl
```

Opsiyonel:

```powershell
pre-commit run --all-files
```

Claude CLI/auth varsa opsiyonel live check:

```powershell
python scripts\run_trigger_eval.py --skill-path skills\agentic-sdlc-pipeline --eval-set tests\skills\evals\agentic-sdlc-pipeline.json --runs 3
python scripts\run_procedure_eval.py --eval-set tests\skills\procedure\agentic-sdlc-pipeline.json --live --max-budget-usd 2.00
```

Codex auth varsa opsiyonel route-classifier check:

```powershell
python scripts\run_codex_trigger_eval.py --skill-path skills\spec-authoring --eval-set tests\skills\evals\spec-authoring.json --smoke --model gpt-5.4-mini --reasoning-effort low
```

## Bilinen Sınırlar

- Plugin şu an `0.1.0` ve unreleased durumdadır.
- CI workflow yoktur; publish ayrı ve explicit bir manuel release fazı olmalıdır.
- Hook çalışması Claude Code'un `${CLAUDE_PLUGIN_ROOT}` çözmesine ve Node.js'in PATH'te olmasına bağlıdır.
- Bazı hook'lar hata durumunda fail-open davranır.
- `scan-write` uyarır ama block etmez.
- `branch-guard` sadece strict mode'da block eder.
- `validate_artifacts.py` yapısal doğrulama yapar; semantik olarak doğru spec yazıldığını kanıtlamaz.
- Deterministik testler wiring ve fixture sağlığını kanıtlar; canlı model obedience kanıtı değildir.
- Repo gate bazı Claude Code frontmatter alanlarını kabul eder; harici packaging validator'ları daha dar şema isteyebilir.

## Sonuç

AGENTIC-SDLC plugin'i, Claude Code içinde production-impacting değişiklikleri kontrollü SDLC akışına bağlamak için tasarlanmıştır. En güçlü tarafları:

- Enforced secret/destructive-command guardrail'leri
- Spec/plan/TDD/security/review omurgası
- Fresh-context agent ve workflow ayrımı
- Deterministik test ve eval altyapısı
- Lokal gate ve manuel yayınlama ayrımı

Bu dosya GitHub'a push öncesi plugin'in ne olduğunu, ne olmadığını ve hangi bileşenlerden oluştuğunu hızlıca anlamak için ana teknik referanstır.
