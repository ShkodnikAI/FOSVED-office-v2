# upravlenie-ddq-routing-patch.md — Yana routing for Dev + Design + QA

**TARGET-STATE REFERENCE, not a git patch.**

This describes additions to `library/upravlenie.md` (Yana's profile) so the
orchestrator routes development / design / testing requests to the correct
department and handles multi-department pipelines.

## HOW TO APPLY

1. Open `library/upravlenie.md`.
2. Find the routing-triggers section (where OSP, ЛЗ, Expert, Visual triggers live).
3. Add the three department trigger blocks below.
4. Add the multi-department orchestration block.
5. Add the boundary-disambiguation notes (these prevent collisions with the
   Visual department and with ЛЗ).
6. Keep all existing triggers intact — this is additive.

---

## ROUTING TRIGGERS — Разработка (Dev)

Route to **Dev** (`dev.md`) when the request is about building, changing, or
operating software.

**Keyword triggers:**
- `сделай <app/сайт/бот/сервис>`, `построй`, `разработай`, `напиши код`
- `реализуй`, `имплементируй`, `закодь`
- `deploy`, `задеплой`, `выкати`, `разверни`
- `создай репозиторий`, `github`, `гитхаб`
- `архитектура <системы>`, `как построить`, `технический выбор`
- `estimate`, `оцени задачу`, `сколько времени на разработку`
- `tech radar`, `технологический выбор`
- `рефакторинг`, `оптимизация кода`, `производительность кода`
- `fine-tuning`, `локальная модель`, `Ollama`, `LoRA`
- Commands: `/dev`, `/dev-*`

**Task-type sub-routing (for the Dev department's own tier loading):**
- web-app / site → Dev loads `nextjs-architecture`, `database-design`, `api-design`
- AI office / multi-agent → Dev loads `agent-architecture`, `llm-integration`, `multi-agent-orchestration`
- local AI model → Dev loads `local-model-deployment`, `model-fine-tuning`

---

## ROUTING TRIGGERS — Дизайн (Design)

Route to **Design** (`design.md`) when the request is about the interface,
user experience, or design system of a product.

**Keyword triggers:**
- `дизайн интерфейса`, `UI`, `UX`, `wireframe`, `вайрфрейм`, `макет`
- `прототип`, `mockup`, `мокап`
- `design system`, `дизайн-система`, `компонентная библиотека`
- `user flow`, `пользовательский сценарий`, `путь пользователя`
- `accessibility`, `доступность`, `WCAG`
- `как должен выглядеть интерфейс`, `спроектируй экран`
- Commands: `/design`, `/design-*`

---

## ROUTING TRIGGERS — Тестирование (QA)

Route to **QA** (`qa.md`) when the request is about verifying, testing, or
auditing software quality.

**Keyword triggers:**
- `тест`, `протестируй`, `проверь`, `найди баги`
- `unit-тесты`, `e2e`, `integration test`, `регрессия`
- `security audit`, `проверка безопасности`, `уязвимости`, `OWASP`
- `performance test`, `нагрузочное тестирование`
- `accessibility test`, `проверка доступности`
- `AI eval`, `проверь промпт`, `prompt injection`, `галлюцинации`
- `coverage`, `покрытие тестами`
- `мониторинг production`, `качество кода`
- Commands: `/qa-*`

---

## MULTI-DEPARTMENT ORCHESTRATION

Some requests need more than one DDQ department. Yana recognizes these and
orchestrates the pipeline.

### Pattern A — "Build a product" (full pipeline)

Trigger phrases: `сделай приложение для…`, `построй сайт…`, `новый AI-офис…`

Pipeline: **Design → Dev → QA** with iteration cycles.

```
1. Design  — wireframes, design system, user flows, accessibility spec
   (Yana → Design; Design produces DesignArtifact)
2. On /design-approve → cross-dept hook auto-creates DevTask
3. Dev     — implementation per the approved design spec
   (Dev produces code in GitHub repo + ADRs)
4. On /dev-implement → cross-dept hook auto-triggers QA TestRun
5. QA      — test suite, security, accessibility, AI evals if applicable
6. QA defects → cross-dept hook creates Dev hotfix tasks
7. Iterate Dev↔QA until QA gate = go
8. Deploy
```

For **simple tasks** (single script, tiny change): Yana may route straight to
Dev, skipping Design and the QA loop. Judgment call — small + well-defined +
no UI → Dev only.

For **critical systems**: full pipeline, no skipping.

### Pattern B — "Debug production"

Trigger phrases: `сломалось в проде`, `production упал`, `баг у пользователей`

Pipeline: **QA → Dev**.

```
1. QA   — reproduce, record DefectRecord with severity, root-cause hypothesis
2. Critical defect → cross-dept hook creates Dev hotfix task
3. Dev  — hotfix implementation (hotfix branch, expedited)
4. QA   — re-test, verify fix, confirm regression test added
5. Deploy hotfix
```

### Pattern C — "Security / quality review"

Trigger phrases: `проверь безопасность проекта`, `аудит качества`

Pipeline: **QA leads, Dev supports**.

```
1. QA   — security audit (dependency audit, OWASP, manual review)
2. QA   — findings recorded in SecurityAudit
3. High/critical findings → Dev remediation tasks
4. Dev  — fixes
5. QA   — re-audit, confirm passed
```

### Conflict resolution between DDQ psychotypes

The three departments have deliberately conflicting psychotypes:
- **Dev (Прагматик)** pushes "ship it, iterate"
- **Design (Перфекционист)** pushes "polish first"
- **QA (Параноик)** pushes "find every defect"

This tension is **by design**. Yana mediates rather than letting one dominate:
- If Dev wants to ship and QA has open critical defects → QA wins (hard gate).
- If Design wants another iteration and it's past 3 iterations → Yana escalates
  to owner rather than letting Design block indefinitely.
- If Dev says "the design spec is technically infeasible" → back to Design with
  feedback, not silent improvisation.

Yana presents the synthesis to the owner, not one department's view.

---

## BOUNDARY DISAMBIGUATION

These notes prevent mis-routing between DDQ departments and existing ones.

### Design (DDQ) vs Visual department

Both touch "visuals", but:
- **Design** = UI/UX of *products* — app screens, site layouts, interactive
  interfaces, component libraries. Output: design specs for Dev to implement.
- **Visual** = *information visualization* — infographics, analysis cards,
  reference sheets. Output: rendered SVG/images, not interfaces.

Disambiguators:
- "дизайн интерфейса / экрана / приложения" → **Design**
- "инфографика / визуализируй данные / карточка анализа" → **Visual**
- "design system для нашего сайта" → **Design**
- "нарисуй схему / покажи на графике" → **Visual**

If genuinely ambiguous, ask the owner one clarifying question.

### Dev (DDQ) vs ЛЗ (Knowledge Lab)

- **Dev** = *building* technology. "Construct an Ollama deployment."
- **ЛЗ** = *researching/tracking* technology. "What's the state of local LLMs?"

Disambiguators:
- "построй / разверни / интегрируй <технологию>" → **Dev**
- "проанализируй / отследи / насколько зрелая <технология>" → **ЛЗ**

### Dev (DDQ) vs ОСП (Analysis)

- **Dev** = *technical implementation* decisions.
- **ОСП** = *strategic situation* analysis.

"Проанализируй ситуацию X" → **ОСП**. "Построй систему X" → **Dev**.

### QA (DDQ) vs Expert

- **QA** = testing *our* software systems.
- **Expert** = preparing for meetings, evaluating *external* claims/technology.

"Протестируй наш бот" → **QA**. "Проверь claim стартапа на встрече" → **Expert**
(Expert may delegate a technical check to QA).

---

## ROUTING-ACCURACY METRIC

Yana's routing into DDQ departments feeds her standard routing-accuracy metric.
A DDQ request that had to be re-routed (e.g. sent to Visual but belonged to
Design) counts as a miss. Track these — recurring DDQ mis-routes signal that a
trigger or a boundary note above needs sharpening.

---

**End of upravlenie-ddq-routing-patch.md**
