# ОСП как обучающийся прогнозёр: архитектура, данные, гейты, калибровка, план

**Кому:** владельцу Fosved Office
**От:** агента-архитектора (дизайн, не реализация — код в репозиториях не менялся)
**Дата:** 02.11.2026
**Основание:** наряд `OSP_DESIGN_TASK.md` от 01.11.2026

**Как это проверено.** Каждое утверждение о коде получено `grep`-ом и чтением файлов
`FOSVED-office-v2` (main) и `Metalogos-` (v0.38.0). Каждый пример `.mlog` **исполнен**
на двух рантаймах: `bin/mlog 0.34.1` (прод офиса) и официальном `mlog 0.38.0`
(SHA256 `da714fd5…` сверен) — 54 теста × 2 рантайма, все зелёные, `mlog check`
без ошибок. Журнал с выводами команд: `deliverable/VERIFICATION.md`, прогон —
`deliverable/examples/run_all.sh`.

| Артефакт | Путь |
|---|---|
| Этот документ | `deliverable/OSP_DESIGN.md` |
| Пример 1 — карточка, гейты, clip, Кент, бакет | `deliverable/examples/01_osp_card.mlog` (9/9) |
| Пример 2 — ансамбль, агрегация, бюджет | `deliverable/examples/02_osp_ensemble.mlog` (7/7) |
| Пример 3 — Brier, skill score, Platt, `/osp score` | `deliverable/examples/03_osp_scoring.mlog` (10/10) |
| Пример 4 — жизненный цикл, события, вахта, Entity/Rule/Flow | `deliverable/examples/04_osp_lifecycle.mlog` (12/12) |
| Пример 5 — ForecastBench: утечка, стоимость, разрешение, экспорт | `deliverable/examples/05_osp_bench.mlog` (16/16) |

---

## 0. Резюме (полстраницы)

**Центральная идея.** Прогноз — это **запись (карточка) с жизненным циклом и числовой
уверенностью**, а ответ владельцу в Telegram — только её представление. Отсюда следует
всё остальное: гейты — свойства записи, а не свойства текста; калибровка — запрос к
архиву записей, а не сочинение модели; «учится» — значит «пишет и перечитывает».

**Диагноз по коду (перепроверен).** Контур обучения разомкнут не из-за отсутствия
методологий, а из-за отсутствия **записи**:

- в репозитории **ноль** `UPDATE analysis …` — статус навсегда `drafted`
  (единственный писатель: `dept/osp.mlog:266`, только deep/full);
- **пять таблиц цикла обучения не имеют ни одного писателя**: `brier_score_log`
  (`app.mlog:277`), `indicator` (`:267`), `watchlist_item` (`:272`),
  `analysis_verifications` (`:399`), `research_source` (`:264`, писатели только в
  `archive/dead-mlog/` и `dogfood_staging.mlog`);
- поэтому `OSPVerify` (`osp.mlog:1038`) всегда отвечает «Нет анализов для верификации»,
  а `OSPCalibrationScore` (`:1052`) — «Avg Brier: N/A», после чего **модель сочиняет
  калибровку** — прямое нарушение ограничения 6 задания;
- единственный писатель `monthly_reviews` — `OSPRecalibrate` (`:1078`) с
  `to_char(datetime('now'),'YYYY-MM')`: в SQLite `to_char` нет (проверено исполнением:
  `[SQL_ERROR]`, работает `strftime`) → запись молча падает каждый месяц;
- `/osp watch` (`:1121`) пишет строку без порогов, окон и связи с анализом;
- 12 «гейтов качества» `OSPCheckQualityGates` (`:275-329`) — поиск подстрок в прозе.

**Две поправки к постановке задачи** (подробно §1.4):

1. **«≥50 разрешённых прогнозов за 2 месяца» недостижимо из контура владельца.**
   1–3 вопроса в неделю × горизонт месяцы = 8–24 записи, из них разрешённых за
   2 месяца — единицы. Единственный способ выполнить критерий успеха — внешний поток
   с короткими горизонтами: **ForecastBench** (500 вопросов раз в 2 недели; в раунде
   2026-10-11 — 496 строк исходов, 265 разрешено). Metaculus API отпадает: ToU
   запрещает использование в обучении/оценке моделей без письменного разрешения,
   все запросы требуют токен, а `Community Prediction` вне выданных проектов — `null`.
2. **«Brier ≤ 0.25» выполняется монеткой.** Константа `p = 0.5` даёт ровно 0.25
   (тест в примере 3). Цель года 1 должна быть переформулирована как **skill score
   против трёх базовых линий** (0.25 / частота исходов / толпа-рынок), иначе отдел
   «выполнит план», ничего не утверждая.

**Что предлагается.** Вариант **A «Карточка»**: одна таблица `osp_forecast` +
журнал событий + базовые частоты + bench-раунды (6 новых таблиц, 6 существующих
наконец получают писателей). Конвейер — **диспетчер состояний** (программа решает,
какой шаблон вызвать следующим), а не «спросим модель, что дальше». Гейты:
**G1–G6 блокирующие** и **W1–W5 предупреждающие**, все — по структуре и числам.
Platt включается, только если улучшает Brier на **отложенной выборке** (≥0.005 при
n≥30), иначе идентичность. Числа считает программа, модель — текст и первичную оценку.

**Цена.** Раунд ForecastBench (≈1500 строк прогноза = 500 вопросов × горизонты) на
дешёвой тройке (groq $0, cerebras $0, deepseek $0.14/$0.28 за 1M токенов —
`proxy/providers.py:74-84`) = **0.252 USD**; обучающая выборка 40 строк = **0.007 USD**.
Прогноз владельца (5 прогонов ансамбля + 1 дорогой прогон на прозу) ≈ **0.02–0.05 USD**.
Потолок — ключ `daily_budget_osp`, который прокси уже читает (`proxy/budget.py:99-108`).

**План.** 4 волны (§10): 0 — починка загрузчика скиллов (сейчас из 20 подключённых
загружается **один**: `deconstruct` = 15 640 символов против бюджета 12 000,
`osp.mlog:836` жёстко зовёт `OSPSkillBudget(1)`); 1 — карточка и жизненный цикл;
2 — числа и `/osp score`; 3 — внешний поток и cron-слоты; 4 — Platt, A/B методологий,
калибровочная кривая. У каждой волны — проверяемое «готово, когда» и тест-мутация.

**Критерий успеха через 2 месяца** (честная формулировка): `/osp score` показывает
настоящий Brier по ≥50 разрешённым прогнозам, **из них ≥25 в контуре владельца** —
иначе цифра есть, а решения владельца ею не покрыты.

---

## 1. Центральная идея

### 1.1 Формулировка

> **Прогноз — это запись. Ответ — её представление. Обучение — перечитывание записей.**

Три следствия, из которых выводится весь проект:

1. **Единственная точка записи.** Карточка создаётся до ответа владельцу и обновляется
   после. «Не записалось» больше не может означать «ответили, а в архиве дыра» —
   ответ собирается из строки БД (пример 1, `OSPSaveCard`).
2. **Состояние, а не текст.** У карточки есть статус из конечного автомата
   (`drafted → gated → published → watching → resolved | expired | superseded`)
   и журнал переходов с причиной. Пропустить гейты нельзя технически: перехода
   `drafted → published` нет в карте (пример 4, `OSPCanTransition`).
3. **Число и слово разделены.** Программа считает `p_ensemble`, `p_spread`, `p_final`,
   `cal_bucket`, `brier`, skill score, долю покрытия; модель пишет прозу и предлагает
   `p_raw`. Там, где число может посчитать программа, модель не вызывается вовсе.

### 1.2 Что это меняет в существующем коде

| Сейчас | Становится | Почему |
|---|---|---|
| `HandleOSP` (`osp.mlog:375`) → один `call_llm` → текст | `HandleOSP` → карточка → ансамбль → рендер карточки | ответ становится представлением записи |
| `OSPValidateProbability` (`:88`) ищет слова «likely/вероятно/%» | `json_validate` по схеме + `to_float` | поиск слов в прозе — не проверка числа |
| `OSPCheckQualityGates` g1–g12 (`:275-329`) — подстроки, результат в журнал | G1–G6 блокирующие по структуре, W1–W5 предупреждающие | профиль утверждает «BLOCKER», а блокировки нет |
| `OSPComputeBrier` (`:256`) не вызывается | `OSPBrier` + запись в `osp_forecast.brier` и `brier_score_log` | ограничение 6 задания |
| `OSPShermanKent` (`:70`) метка→число, не вызывается | `OSPKentOf` число→метка для отображения (пример 1) | число первично, слово — его представление |
| `OSPRecalibrate` (`:1071`) — модель сочиняет изменения | `OSPPlattAdopt` + `OSPScoreBlock` (пример 3) | рекалибровка — это коэффициент, а не эссе |
| `/osp watch` пишет строку без порогов | `OSPWatchDue`/`OSPArchiveExpired` с окном и громкой архивацией | вахта без даты и порога не проверяется |
| `analysis_verifications` никто не пишет | `OSPVerifyCard` пишет исход, Brier, событие | без писателя таблица — декорация |

Существующее сильное **переиспользуется, а не переписывается**: гейт #469
(`OSPScenarioGateCheck`, `osp.mlog:138-219` — сумма вероятностей ≈100%,
непересечение диапазонов, один повтор) становится образцом для G-гейтов; живой поиск
(`OSPLiveSearchBlock:566`), рыночные данные (`OSPMarketDataBlock:666`), гейт свежести
(`OSPFreshnessGate:606`), якорь даты (#474) и фильтр инвестсоветов остаются на месте
и попадают в карточку как поля `sources_json`, `market_json`, `as_of`.

### 1.3 Три контура — и почему метрики не смешиваются

| Контур | `kind` | Источник вопроса | Горизонт | Зачем |
|---|---|---|---|---|
| Владелец | `owner` | `/osp …` в Telegram | дни–годы | польза здесь и сейчас; n мал |
| Бенчмарк | `bench` | ForecastBench, раунд раз в 2 недели | 7–1095 дней | **даёт n** для Brier, кривой и Platt |
| Команда | `team` | наряды/задачи офиса | дни | качество суждений отдела (существующий `ScoreDept`, `app.mlog:1304`) |

Все метрики (`/osp score`, калибровочная кривая, Platt) считаются **с фильтром по
`kind`**. Тест «контуры не смешиваются» есть в примере 3: строки `bench` не попадают
в метрику `owner`. Это же защищает от соблазна выдать тренировочные прогнозы за
прогнозы для владельца.

### 1.4 Поправки к постановке задачи (задание просит сказать первым)

**(1) Критерий «≥50 разрешённых за 2 месяца» требует внешнего потока.**
Арифметика: владелец задаёт 1–3 вопроса в неделю → 8–24 карточки за 2 месяца;
из них к 60-му дню разрешится только часть (горизонты «конец 2026», «к 31.12.2027»).
Реалистично: 3–8 разрешённых записей `owner`. ForecastBench даёт 265 разрешений
в одном раунде (проверено по `2026-10-11_resolution_set.json`), то есть ≥50 — за
**один** раунд. Вывод: внешний поток — не «идея владельца, которую нужно проработать»,
а **единственный** способ выполнить критерий успеха. Он и спроектирован как основной
источник n (§6), а контур владельца — как основной источник пользы.

**(2) «Brier ≤ 0.25/0.20/0.18» — не цель, а порог тривиальности.**
Константа 0.5 даёт 0.25; константа, равная частоте исходов, обычно даёт 0.15–0.20.
Правильная цель: **skill score** `1 − Brier/Baseline` против трёх линий (0.25,
частота исходов архива, толпа/рынок из `crowd_p`). Цель года 1 предлагается такая:
`skill vs 0.25 ≥ +0.10` при n≥50 **и** `Brier ≤ Brier толпы` на тех же вопросах.
ForecastBench с 06.06.2026 считает не абсолютный Brier, а **difficulty-adjusted
Brier Index** — абсолютные пороги там просто не сравниваются (см. допущение A.4).

**(3) «Уверенность» — не одно число.** У карточки их четыре, и они отвечают на разные
вопросы: `p_final` (вероятность исхода), `p_spread` (согласие ансамбля — мета-уверенность),
`n_runs` (сколько независимых прогонов), `cal_bucket` + состояние калибровки
(насколько этому числу можно верить исторически). Fluid-значение «вероятность, которая
знает свою калибровку» (§1.6) в рантайме 0.34/0.38 не собирается — поэтому уверенность
хранится полями, а не типом (заявка C.2).

**(4) Формулировка «жизненный цикл `drafted → published → watching → verified/missed/
partial/superseded`»** (замысел v4.1) содержит исход (`verified/missed/partial`) в
статусе. Это ошибка моделирования: статус — позиция в конвейере, исход — данные
(`outcome ∈ [0,1]`). Иначе карточка с дробным исходом (`resolved_to = 0.5`, такие есть
в ForecastBench) не помещается ни в один статус. Предлагаемый автомат:
`drafted → gated → published → watching → resolved | expired | superseded` +
поля `outcome`, `brier`.

### 1.5 Варианты реализации (задание просило несколько)

**Вариант A — «Карточка» (рекомендую).**
Новая таблица `osp_forecast` — сущность прогноза; `analysis` остаётся таблицей
**документов** (проза для владельца и для `dept/visual.mlog`), карточка ссылается на
неё через `analysis_id`. Всё числовое — в карточке.
*Плюсы:* одно новое понятие; миграция аддитивна (`analysis` не ломается,
`visual.mlog` продолжает читать `full_result`, которое наконец начнут писать);
метрики — один `SELECT` с фильтром по `kind`; состояния проверяются тестами.
*Минусы:* две таблицы вместо одной (join в отчётах); нужно дисциплинированно
писать `analysis.full_result` из карточки.

**Вариант B — «Расширить `analysis`» (отклонён).**
Добавить `p_raw/p_ensemble/p_final/outcome/brier/status` в `analysis` через
`AlterColIfMissing` и писать всё туда.
*Почему отклонён:* `analysis` — документ («тема + проза»), а прогноз — запись с
числовым жизненным циклом и несколькими горизонтами. Один документ может нести
несколько прогнозов (сценарии #469: 3–4 диапазона вероятностей), а один прогноз
бенчмарка — 5 горизонтов. Смешение даёт god-table и повторяет урок v4.1 (§3.4):
25 полей Prisma-модели `Analysis` схлопнулись в 7 колонок SQLite (`app.mlog:263`),
и хвост `AlterColIfMissing` (`:455-459`) до сих пор догоняет дрейф.

**Вариант C — «Сначала бенчмарк, потом владелец» (отклонён как порядок, принят как
последовательность включения метрик внутри A).**
*Почему не порядок:* владелец 2 месяца не получает ничего нового, а риск
(стоимость, cron-слоты, внешняя зависимость) максимальный. Но **метрики** включаются
именно в этом порядке: bench-контур даёт n для Platt и кривой, owner-контур
публикуется в `/osp score` отдельной строкой с честным «недостаточно данных»
(пол n≥10, стиль Narad 8 — `ComputeFinanceMAPE`, `app.mlog:1259`).

**Вариант D — «Flow-first»: описать конвейер декларациями `flow` + `rule`** (отклонён).
Проверено исполнением: `rule` видит **только поля верхнеуровневых entity**, не читает
БД, не может вызывать шаблоны (`[UNDEFINED_VARIABLE] VM rule: undefined variable
'FnCall{…}'`) и **не исполняется в test-блоках**; `flow` исполняется на `mlog run`,
но `mlog test` его не покрывает. Конвейер, который нельзя проверить тестом, —
это возвращение к «профиль утверждает, код не делает».
*Принято частично:* `flow` — тонкая обёртка ночной вахты с `checkpoint` (пример 4),
вся логика — в шаблонах, которые покрыты тестами.

### 1.6 Семь опор Metalogos: что реально умеет рантайм

Проверено исполнением на 0.34.1 и 0.38.0; «—» значит «заявка в Metalogos» (§Приложение C).

| Опора | Как выражена в ОСП | Что рантайм умеет (проверено) | Чего не умеет |
|---|---|---|---|
| **Entity** | тип `ForecastCard` + таблицы `osp_forecast`, `osp_forecast_events`, `osp_base_rates` | `entity Type {…}` и инстансы читаются в `run` и в `test`; поля доступны как `card.status` | в test-блоках значения по умолчанию не материализуются (`()`), поэтому **источник истины — БД**, entity — контракт/тип |
| **Pattern** | вся логика: гейты, агрегация, Brier, автомат состояний | 36 существующих + новые; `while`, `each`, `match`, `try`; `mutate`-метрики | — |
| **Flow** | ночная вахта `ForecastAdvance`, план раунда `BenchRound` | исполняется на `mlog run`, печатает `output`, `checkpoint("name")` работает | `mlog test` flow не покрывает → логика обязана жить в шаблонах |
| **Memory** | архив (БД), счётчики бюджета и дней (kv), поиск похожих решённых вопросов | `kv_set/kv_get` с персистенцией (`app.mlog:36 memory { persist: … }`); FTS5 в bundled SQLite работает | `memorize/recall` — эфемерный `Vec` ВМ (не персистентно); `vec_*` не входит в default-сборку (Cargo features) → похожие вопросы ищем FTS5, не эмбеддингами |
| **Rule** | дублирующий сигнал тревоги (`alert.level`) | работает над полем entity-структуры во время исполнения flow; приоритет first-wins | не читает БД, не вызывает шаблоны, не исполняется в тестах, над простой `entity s: String` падает в run (`contains: both sides must be String`), а `check` молчит → **переходы статусов — только шаблонами** |
| **Learn** | `learnable pattern` для классификации домена/типа ошибки | `learnable pattern` + `context: recall/auto/none`, кэш и `cache_semantic` | `METRIC_REGISTRY` = accuracy / macro_f1 / min_class_recall — **Brier и log-loss нет**, поэтому «обучение» калибровки живёт в шаблонах (заявка C.1) |
| **Adapt** | Platt с правилом включения; A/B методологий через `methods_json`; пересмотр арсенала | `mutate`, `system_settings`, таблицы `skill_reviews` (`app.mlog:447`) и `arsenal_reviews` (`:401`) уже созданы | адаптация не может менять собственные пороги без записи решения → все изменения коэффициентов пишутся в `system_settings` с пометкой `ADOPTED/REJECTED` |
| **Fluid** | «вероятность, которая знает свою калибровку» | `fluid x = …` на верхнем уровне компилируется | внутри тела шаблона — `[UNDEFINED_VARIABLE]`; персистентной формы нет → уверенность храним полями `p_final/p_spread/n_runs/cal_bucket/cal_note` (заявка C.2) |

**Вывод по §6.1 задания:** язык уже даёт Entity/Pattern/Flow/Memory/Rule/Learn/Adapt
в объёме, достаточном для карточки и архива. Двух вещей он не даёт: (а) `Rule` как
механизма переходов состояния по данным БД и (б) `Fluid` как типа значения вероятности
внутри шаблона. Поэтому **статусы живут в БД и меняются шаблонами**, а уверенность —
набор полей, а не тип. Это не «обёртка как в Python»: новая способность (проверяемая
калибровка) получается из существующих опор — Entity (карточка) + Pattern (числа) +
Memory (архив) + Adapt (Platt по правилу), а не из нового понятия.

---

## 2. Сквозной поток

### 2.1 Диаграмма

```
 ВОПРОС ВЛАДЕЛЬЦА                     ВНЕШНИЙ ПОТОК (ForecastBench, раунд/2 нед)
 "/osp deep ставка ФРС…"              OSPBenchFetchSet → OSPBenchIngest
        │                             (защита от утечки: 3 слоя, §6.3)
        ▼                                        │
 ┌─────────────────────┐                         ▼
 │ 1. КАРТОЧКА ВОПРОСА │  OSPCardGates: G2 критерий исхода ≥20 симв.,
 │  критерий, дата,    │  G2b resolve_by в будущем, G2c as_of не в будущем
 │  «на момент»        │  (пример 1)                     │
 └─────────┬───────────┘                                 │
           ▼                                             ▼
 ┌─────────────────────┐   живой поиск OSPLiveSearchBlock:566, рынки
 │ 2. ИССЛЕДОВАНИЕ     │   OSPMarketDataBlock:666, гейт свежести :606
 │  источники → строки │   → запись в research_source (сегодня: 0 писателей)
 └─────────┬───────────┘   → карантин источников ПОСЛЕ as_of (#474, §6.3)
           ▼
 ┌─────────────────────┐   OSPBaseRateOf + OSPPriorWeight(n)=n/(n+10)
 │ 3. БАЗОВАЯ ЧАСТОТА  │   → OSPBlendPrior (пример 4)
 └─────────┬───────────┘   похожие решённые вопросы: FTS5 по question/criteria
           ▼
 ┌─────────────────────┐   OSPEnsemble: 3–7 независимых прогонов, разные
 │ 4. АНСАМБЛЬ         │   семейства (groq/cerebras $0, deepseek, zai, kimi)
 │  n прогонов         │   структурный ответ → OSPParseRun: PASS-число | FAIL
 └─────────┬───────────┘   бюджет: kv-счётчик на UTC-день (пример 2)
           ▼
 ┌─────────────────────┐   OSPAggregate: mean (основной) + median + logit-pool
 │ 5. АГРЕГАЦИЯ        │   + p_spread (population stdev) + range — всё в строку
 └─────────┬───────────┘
           ▼
 ┌─────────────────────┐   OSPClip: clamp(p, 0.02, 0.98)
 │ 6. CLIP КРАЙНИХ     │   (порог — константа, не «на глаз модели»)
 └─────────┬───────────┘
           ▼
 ┌─────────────────────┐   OSPCrowdCompare: |p_final − crowd_p| →
 │ 7. СВЕРКА С РЫНКОМ  │   W3 >0.15 предупреждение, G6 >0.35 блокировка
 └─────────┬───────────┘   + аудит отклонения от базовой частоты
           ▼
 ┌─────────────────────┐   G1 shape, G2 критерий, G3 разброс, G4 сценарии
 │ 8. ГЕЙТЫ            │   (#469 переиспользуется), G5 as_of, G6 рынок
 │  PASS / FAIL        │   FAIL → ОДИН повтор модели с причиной → gated
 └─────────┬───────────┘   W1–W5 → в gate_report, ответ не блокируют
           ▼
 ┌─────────────────────┐   OSPSaveCard / OSPPublishCard → status published,
 │ 9. АРХИВ (запись)   │   analysis.full_result ← проза, research_source ← URL,
 │                     │   osp_forecast_events ← переход + причина
 └─────────┬───────────┘
           ▼
 ┌─────────────────────┐   ночной слот: OSPWatchDue / OSPWatchOpen /
 │ 10. ВАХТА           │   OSPArchiveExpired (громко: expired + событие +
 │  (cron)             │   строка в отчёте + счётчик kv) — flow ForecastAdvance
 └─────────┬───────────┘
           ▼
 ┌─────────────────────┐   OSPParseOutcome (yes/no/доля — программа),
 │ 11. ПРОВЕРКА        │   подтверждение исхода — владелец или bench-раунд
 │                     │   → OSPVerifyCard / OSPBenchResolve
 └─────────┬───────────┘
           ▼
 ┌─────────────────────┐   OSPBrier = (p − y)² → osp_forecast.brier,
 │ 12. BRIER           │   brier_score_log (писатель наконец появляется),
 │                     │   analysis_verifications.brier_total
 └─────────┬───────────┘
           ▼
 ┌─────────────────────┐   ежемесячно: OSPScoreBlock + OSPCalibrationCurve
 │ 13. РЕКАЛИБРОВКА    │   → monthly_reviews (brier_average, hit_rate_high_conf,
 │                     │   surprise_index, calibration_curve)
 │                     │   OSPPlattAdopt: отложка = хвост архива (30),
 │                     │   включение только при выигрыше ≥0.005 и n≥30
 └─────────────────────┘   → system_settings: osp_cal_a / osp_cal_b / osp_cal_note
```

### 2.2 Где живёт каждое звено

| № | Звено | Шаблон (новый) | Существующий код, который переиспользуется | Пример |
|---|---|---|---|---|
| 1 | Карточка вопроса | `OSPCardGates`, `OSPSaveCard` | `OSPDraftAnalysis:264` (остаётся писателем `analysis`) | 01 |
| 2 | Исследование | `OSPResearchRefs` | `OSPLiveSearchBlock:566`, `OSPMarketDataBlock:666`, `OSPFreshnessGate:606`, `OSPTavilySearch:1159` | 01, 02 |
| 3 | Базовая частота | `OSPBaseRateOf`, `OSPPriorWeight`, `OSPBlendPrior` | — (новая таблица `osp_base_rates`) | 04 |
| 4 | Ансамбль | `OSPEnsemble`, `OSPParseRun`, бюджет в kv | `OSPEnsembleModels` ← `COMBO_CHAINS` (`osp_fusion`, `counter_forecast`) | 02 |
| 5 | Агрегация | `OSPAggregate` | — | 02 |
| 6 | Clip | `OSPClip` | — | 01, 02 |
| 7 | Сверка с рынком | `OSPCrowdCompare` | `OSPMarketDataBlock:666`, `OSPMarketAsset:624` | 02 |
| 8 | Гейты | `OSPCardGates` (G1–G6, W1–W5) | **`OSPScenarioGateCheck:138` (наряд #469) — без изменений** | 01, 02 |
| 9 | Архив | `OSPSaveCard`, `OSPTransition`, `OSPPublishCard` | `AuditLog`, `RecordAssistantMessage` | 01, 04 |
| 10 | Вахта | `OSPWatchDue`, `OSPWatchOpen`, `OSPArchiveExpired`, flow `ForecastAdvance` | `dept/schedules.mlog` (реестр слотов), `OutboxPut`/`OutboxFlush` 07:15 | 04 |
| 11 | Проверка | `OSPParseOutcome`, `OSPVerifyCard`, `OSPBenchResolve` | `OSPVerify:1038` (переписывается: число вместо прозы) | 04, 05 |
| 12 | Brier | `OSPBrier`, `OSPSkillScore`, `OSPLogLoss` | `OSPComputeBrier:256` (мёртвый код → удаляется, §7.3) | 03 |
| 13 | Рекалибровка | `OSPPlattFit`, `OSPPlattAdopt`, `OSPCalibrationCurve`, `OSPScoreBlock` | `monthly_reviews` (`app.mlog:440` — все поля уже есть), `OSPCalibrationScore:1052` (заменяется) | 03 |

**Точка входа остаётся прежней:** `HandleOSP` (`osp.mlog:375`) и маршруты
`/osp/analyze` (`app.mlog:1994`) не меняют ни команд, ни форматов ответа —
владелец видит тот же текст, но собранный из карточки, с числовым хвостом
(§9.5). Это требование ограничения 8 задания.

---

## 3. Модель данных

### 3.1 Что уже есть (и кто в это пишет)

Проверено `grep -rn "INSERT INTO <table>"` по всем `.mlog`/`.py` репозитория.

| Таблица | Где создана | Ключевые поля | Писателей сегодня | Вердикт |
|---|---|---|---|---|
| `analysis` | `app.mlog:263` + ALTER-хвост `:455-459` | `topic, full_result, status, verification_date, confidence, mode, published_at, superseded_by_id, topic_slug, watch_until` | 1 (`OSPDraftAnalysis`, только deep/full, без `full_result`) | оставить как **документ**; карточка ссылается на него |
| `analysis_verifications` | `:399` | `scenario_outcomes, brier_scores, brier_total, error_category, error_note, improvements_for_next, biases_active_in_analysis, indicators_triggered/total, verified_by` | **0** | поля подходят — добавить писателя `OSPVerifyCard` |
| `brier_score_log` | `:277` | `forecast_probability, actual_outcome, brier_score, cumulative_brier, total_forecasts` | **0** | оставить как ряд cumul-динамики; писатель — `OSPVerifyCard` |
| `indicator` | `:267` | `description, verify_date, is_binary, result, confirms_what, pre_verify_reminder_sent, scheduled_job_id` | **0** | писать из сценариев #469 (I&W); вахта читает `verify_date` |
| `watchlist_item` | `:272` | `frequency, last_check_at, next_check_at, last_delta, delta_count` | **0** | вахта по темам (не по прогнозам) |
| `watchlist_scenarios` | `:452` | `scenario_label, description, observable_source, threshold, window_start, window_end, status, triggered_at` | 1 (`/osp watch`, `osp.mlog:1121`, **без порогов и окон**) | дописать `threshold/window_*` — гейт #469 уже их требует |
| `research_source` | `:264` | `analysis_id, url, title, tier, claim` | **0 в проде** (только `archive/dead-mlog`, `dogfood_staging`) | писать из живого поиска + карантин по `as_of` |
| `monthly_reviews` | `:440` | `forecasts_verified, brier_average, brier_trend, hit_rate_high_conf, surprise_index, calibration_curve, error_clusters, dominant_error, improvements, improvements_applied` | 1 (`OSPRecalibrate:1078`) — **падает** на `to_char` | все нужные поля уже есть; писатель — `OSPMonthlyReview` |
| `skill_reviews` | `:447` | `skill_name, usage_count, success_rate, anti_patterns, status` | 0 | A/B методологий (§7.4) |
| `arsenal_reviews` | `:401` | `skills_in_use/underused/obsolete/to_add, tooling_changes` | 0 | полугодовой пересмотр методики |
| `system_settings` | `:235` | `key, value` | много | коэффициенты Platt, потолок `daily_budget_osp` |

**Вывод:** схема на 80% уже спроектирована под цикл обучения — её никто не заполняет.
Поэтому проект **не greenfield**: 6 новых таблиц и 6 существующих, которые наконец
получают писателей.

### 3.2 Новые таблицы (6)

```sql
-- Сущность прогноза. Одна строка = один прогноз = один (вопрос, горизонт).
CREATE TABLE IF NOT EXISTS osp_forecast (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL DEFAULT 'owner',      -- owner | bench | team: метрики не смешиваются
  question TEXT NOT NULL,
  resolution_criteria TEXT,                -- G2: ≥20 символов, наблюдаемо
  as_of TEXT,                              -- якорь «на момент» (#474)
  resolve_by TEXT,                         -- ISO-дата разрешения
  status TEXT NOT NULL DEFAULT 'drafted',  -- drafted|gated|published|watching|resolved|expired|superseded
  p_raw REAL,                              -- оценка ОДНОГО прогона (модель)
  p_ensemble REAL,                         -- среднее N прогонов (программа)
  p_median REAL, p_logit REAL,             -- альтернативные агрегаторы — для честного сравнения
  p_spread REAL,                           -- population stdev ансамбля (мета-уверенность)
  n_runs INTEGER DEFAULT 0,
  p_final REAL,                            -- clip + Platt (программа)
  crowd_p REAL,                            -- рынок/толпа на as_of (-1 = нет линии)
  prior_rate REAL, prior_n INTEGER,        -- базовая частота и её вес
  outcome REAL,                            -- [0,1]: дробные исходы бенчмарка допустимы
  brier REAL, brier_base REAL, brier_crowd REAL,
  cal_bucket INTEGER,                      -- дециль для калибровочной кривой
  kent_label TEXT,                         -- представление числа словом (Шерман Кент)
  analysis_id INTEGER,                     -- ссылка на документ (проза) — вариант A
  bench_qid TEXT, resolution_date TEXT,    -- внешний контур
  methods_json TEXT DEFAULT '[]',          -- какие методики/скиллы применены (A/B, §7.4)
  gate_report TEXT,                        -- G/W-гейты структурированно, не «BLOCKER» в прозе
  models_json TEXT,                        -- состав ансамбля и стоимость прогона
  sources_json TEXT,                       -- источники с меткой «до/после as_of» (карантин)
  published_at TEXT, verified_at TEXT, updated_at TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ospf_kind_status ON osp_forecast(kind, status);
CREATE INDEX IF NOT EXISTS idx_ospf_resolve ON osp_forecast(status, resolve_by);

-- Журнал переходов: «почему» хранится рядом с «что».
CREATE TABLE IF NOT EXISTS osp_forecast_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, forecast_id INTEGER NOT NULL,
  from_status TEXT, to_status TEXT, reason TEXT,
  actor TEXT DEFAULT 'osp', created_at TEXT,
  FOREIGN KEY(forecast_id) REFERENCES osp_forecast(id)
);

-- Базовые частоты по темам (свой архив + внешние данные).
CREATE TABLE IF NOT EXISTS osp_base_rates (
  topic TEXT PRIMARY KEY, n INTEGER, base_rate REAL, source TEXT, updated_at TEXT
);

-- Внешний поток (3 таблицы): раунд, вопрос, отказ защиты от утечки.
CREATE TABLE IF NOT EXISTS osp_bench_rounds (
  due_date TEXT PRIMARY KEY, question_set TEXT, n_questions INTEGER, n_market INTEGER,
  n_dataset INTEGER, n_blocked INTEGER, n_rows INTEGER,
  license TEXT DEFAULT 'CC BY-SA 4.0 · forecastingresearch/forecastbench-datasets',
  ingested_at TEXT);
CREATE TABLE IF NOT EXISTS osp_bench_questions (
  qid TEXT PRIMARY KEY, due_date TEXT, source TEXT, question TEXT, freeze_datetime TEXT,
  crowd_p REAL, horizons INTEGER, model_payload TEXT);   -- ТОЛЬКО белый список полей
CREATE TABLE IF NOT EXISTS osp_bench_blocked (
  qid TEXT PRIMARY KEY, due_date TEXT, source TEXT, reason TEXT, checked_at TEXT);
```

Итого **6 новых таблиц** (критерий элегантности задания: «15 таблиц — идея не найдена»).
`osp_forecast_events` и `osp_base_rates` — спутники карточки, три `osp_bench_*` —
внешний контур, который можно удалить целиком, не тронув контур владельца.

### 3.3 Миграция существующих таблиц (аддитивно, идемпотентно)

Идиома уже в проде: один грант на всю миграционную часть + гвардованный ALTER
(`app.mlog:157`, `dept/utils.mlog:382-395`).

```mlog
let mig = grant_issue("db:alter:*", 120, "n", 45 + 6)   // +6: наши колонки (§3.2 примечание)
let _ = AlterColIfMissing(mig, "analysis",              "osp_forecast_id", "ALTER TABLE analysis ADD COLUMN osp_forecast_id INTEGER")
let _ = AlterColIfMissing(mig, "analysis_verifications","osp_forecast_id", "ALTER TABLE analysis_verifications ADD COLUMN osp_forecast_id INTEGER")
let _ = AlterColIfMissing(mig, "watchlist_scenarios",   "osp_forecast_id", "ALTER TABLE watchlist_scenarios ADD COLUMN osp_forecast_id INTEGER")
let _ = AlterColIfMissing(mig, "watchlist_scenarios",   "threshold_json",  "ALTER TABLE watchlist_scenarios ADD COLUMN threshold_json TEXT")
let _ = AlterColIfMissing(mig, "indicator",             "osp_forecast_id", "ALTER TABLE indicator ADD COLUMN osp_forecast_id INTEGER")
let _ = AlterColIfMissing(mig, "research_source",       "as_of",           "ALTER TABLE research_source ADD COLUMN as_of TEXT")
```

Маппинг при переносе (заполняется один раз скриптом миграции, не моделью):

| Было | Стало | Правило |
|---|---|---|
| `analysis.topic` | `osp_forecast.question` | только для строк, где `mode IN ('deep','full')` |
| `analysis.status='drafted'` | `status='drafted'` | без изменения |
| `analysis.verification_date` | `resolve_by` | если дата распознана; иначе `NULL` + событие «дата не найдена» |
| `analysis.confidence` (текст) | `kent_label` + `p_final=NULL` | **слово не конвертируется в число задним числом**: `p_final` остаётся `NULL`, запись не участвует в Brier |
| `analysis_verifications.brier_total` | `brier` | если не `NULL` (сегодня таких строк нет) |
| `watchlist_scenarios.*` | `osp_forecast_events` + вахта | сценарии остаются сценариями; карточка — отдельная сущность |

Старые строки **не удаляются**: `DELETE` в `db_execute` — это
`[IRREVERSIBLE_NO_GRANT]` (проверено на обоих рантаймах), и это правильно. Автомат
состояний делает удаление ненужным: ненужное уходит в `superseded`/`expired`.

### 3.4 Урок v4.1 (почему миграция, а не новая схема)

В пакете v4.1 (`uploads/dept-originals/v4.1-transition-pack/schema-v4.1.prisma:344-432`)
модель `Analysis` содержит ~25 полей: `probabilities`, `scenarioCount`,
`verificationStatus`, `brierScore`, `indicatorsTriggered`, `researchSources`,
`supersededBy`, `watchUntil`, `publishedAt`, `methodologyVersion`… В SQLite
(`app.mlog:263`) их осталось **7**. Потерянные поля — это ровно те, без которых
цикл обучения не замыкается: вероятности, статус верификации, Brier, индикаторы,
источники. Хвост `AlterColIfMissing` (`:455-459`) вернул пять из них (`mode`,
`published_at`, `superseded_by_id`, `topic_slug`, `watch_until`) — но **писать**
в них некому.

Правило, которое предлагается закрепить в `AGENTS.md` офиса: **любое поле схемы
должно иметь писателя и читателя, названных в том же наряде.** Таблица без писателя —
это не схема, а обещание. (Проверяется тестом-мутацией: §10, «готово, когда».)

### 3.5 Инварианты (что гарантирует программа)

1. `p_final IS NOT NULL` ⇒ `status IN ('published','watching','resolved')` и
   `gate_report` начинается с `PASS`. Достигается картой переходов: `drafted →
   published` отсутствует (пример 4, тест «публикация мимо гейтов невозможна»).
2. `status='resolved'` ⇒ `outcome IS NOT NULL AND brier IS NOT NULL AND verified_at
   IS NOT NULL`. Пишется одним `OSPVerifyCard`/`OSPBenchResolve`.
3. `0.02 ≤ p_final ≤ 0.98` (`OSPClip`, пример 1).
4. Каждый переход имеет строку в `osp_forecast_events` с причиной; отказ перехода —
   тоже строка (`REFUSED>…`). Аудит не зависит от памяти модели.
5. `kind` не меняется после создания; метрики считаются с фильтром по `kind`.
6. `resolve_by > as_of` и `as_of ≤ now` (гейты G2b/G2c, пример 1) — прогноз не
   публикуется задним числом.
7. В `osp_bench_questions.model_payload` нет ни одного поля из `OSPBenchForbidden()`
   (тест примера 5 проверяет это перечислением, а не «на глаз»).
8. Числа в ответе владельцу — из строки БД; модель не имеет права приводить свои
   (`OSPScoreBlock` вставляется в ответ до прозы, §5.4).

---

## 4. Гейты

### 4.1 Принцип

**Никакого поиска слов.** Сегодня `OSPCheckQualityGates` (`osp.mlog:275-329`) — это
12 проверок `contains(output, "AWARENESS")`, `contains(output, "P =")`,
`contains(output, "Leaves")`… Два гейта всегда `true`, результат уходит только в
журнал, а профиль отдела утверждает «BLOCKER». Подстрока «нет числа» ловится внутри
«вероятность 0.5»; «Leaves» — внутри «Leaves no trace». Поиск слов проверяет
**присутствие буквы**, а не свойство прогноза.

Правильный объект проверки — **структура и числа**:
- число берётся из структурного ответа (`call_llm_schema` / `call_llm` + `json_validate`),
  а не регуляркой из прозы;
- проза проверяется на то, что проверяется программно: длина, наличие даты,
  количество элементов списка, суммы, пересечения диапазонов;
- всё, что требует суждения («правдоподобна ли причина»), остаётся **предупреждением**,
  а не блокировкой, и решается моделью только там, где программа бессильна.

Единственный настоящий гейт в отделе — `OSPScenarioGateCheck` (наряд #469,
`osp.mlog:138-219`): сумма вероятностей ≈100%, диапазоны не пересекаются, один
повтор модели с причиной, иначе «не принят к верификации». **Он сохраняется без
изменений** и становится гейтом G4.

### 4.2 Блокирующие (G1–G6) — прогноз не публикуется

| Гейт | Что проверяет | Чем (программа) | При провале |
|---|---|---|---|
| **G1 Shape** | ответ модели — JSON по схеме `{p, base_rate_hint, why}` | `json_validate(schema, payload)`; `json_validate` на не-JSON **громко падает**, поэтому обёрнут в `TryVal(try …)`: «не JSON» = провал прогона, а не 0.5 молча | FAIL-строка в `models_json`, прогон не учитывается в среднем |
| **G2 Критерий исхода** | `length(resolution_criteria) ≥ 20`, есть `resolve_by` (ISO, в будущем), есть `as_of` (ISO, не в будущем) | `OSPCardGates`, `OSPEpochOf` (`date_parse_iso`) | один повтор модели с точной причиной → `status='gated'`, `p_final` не пишется |
| **G3 Разброс ансамбля** | `p_spread ≤ 0.25` и `n_runs ≥ 3` | `OSPAggregate` (population stdev) | «модели отвечают на разные вопросы» → повтор с уточнением формулировки |
| **G4 Сценарии (#469)** | сумма вероятностей ≈100%, диапазоны не пересекаются | `OSPScenarioGateCheck` — **без изменений** | существующее поведение: один повтор, иначе «не принят к верификации» |
| **G5 Исход наблюдаем** | `resolve_by` достижим по данным: есть `observable_source` (рынок/FRED/ACLED/официальный источник) | поле `sources_json` непустое и `OSPFreshnessGate:606` PASS | «прогноз непроверяем» → не публикуется |
| **G6 Расхождение с рынком** | `|p_final − crowd_p| ≤ 0.35` при `crowd_p ≥ 0` | `OSPCrowdCompare` | блокировка + требование явного обоснования отклонения (аудит, как в `open-superforecaster`) |

### 4.3 Предупреждающие (W1–W5) — ответ уходит, пометка в `gate_report`

| | Что | Порог | Зачем |
|---|---|---|---|
| **W1** | отклонение от базовой частоты | `|p_final − prior_rate| > 0.3` при `prior_n ≥ 10` | ловит «историю вместо прогноза» |
| **W2** | низкая мета-уверенность | `n_runs < 5` или деградация ансамбля из-за бюджета | честно помечает «оценка по одному прогону» |
| **W3** | расхождение с рынком | `0.15 < |p_final − crowd_p| ≤ 0.35` | повод пересмотреть, но не повод молчать |
| **W4** | короткий горизонт | `resolve_by − as_of < 7 дней` | высокая чувствительность к шуму |
| **W5** | источники после `as_of` | в `sources_json` есть запись с датой > `as_of` | карантин утечки (#474): источник помечается, в промпт следующего прогона не попадает |

### 4.4 Что происходит при провале (дискретно, без «BLOCKER» в прозе)

```
FAIL: G3 разброс ансамбля 0.31 > 0.25 — прогон 2 (glm-4.6) ответил 0.78,
      прогон 4 (kimi-k3) — 0.11; модели отвечают на разные вопросы
```

- строка причины пишется в `gate_report` (структурированно: `{"g3":"FAIL","spread":0.31}`);
- **один** повтор модели с этой причиной (дисциплина #469, не бесконечный цикл);
- повтор не помог → `OSPTransition(id, "gated", <причина>)`, ответ владельцу:
  «не принят к верификации» + причина + что нужно уточнить (критерий/дату/источник);
- `p_final` остаётся `NULL` ⇒ запись никогда не попадёт в Brier ⇒ метрика не
  засоряется непроверенными прогнозами (инвариант 1, §3.5).

### 4.5 Антипаттерн, который не возвращается

`ControlCheck` в легаси-планировщике (`proxy/routes_sched.py`) просит **модель**
решить, «выполнено ли условие». Это та же ошибка, что и `OSPCalibrationScore`:
суждение модели там, где программа может прочитать данные. В новом контуре
планировщик вызывает `OSPWatchDue(now_iso)` и получает список строк; решение
«что делать» — это `OSPNextAction(status)` (таблица), а не проза.

---

## 5. Калибровка

### 5.1 Метрики (всё — программа, примеры 3 и 5)

| Метрика | Формула | Где | Пол |
|---|---|---|---|
| Brier | `(p − y)²`, `y ∈ [0,1]` (обобщённый: дробные исходы бенчмарка допустимы) | `OSPBrier` | n≥10 |
| Log-loss | `−(y·ln p + (1−y)·ln(1−p))`, `p` клиппингован в `[1e-4, 1−1e-4]` | `OSPLogLoss` | n≥10 |
| Skill score | `1 − Brier/Baseline`; три линии: 0.25, частота исходов архива, `crowd_p` | `OSPSkillScore` | n≥10 и baseline > 0 |
| Hit-rate высокой уверенности | `AVG(outcome) WHERE p_final ≥ 0.8` | `OSPScoreBlock` | n≥10 в бакете |
| Surprise index | `AVG(1 − outcome) WHERE p_final ≥ 0.8` | `OSPScoreBlock` | n≥10 |
| Калибровочная кривая | `GROUP BY cal_bucket` → `{bucket, n, mean_p, mean_y}` | `OSPCalibrationCurve` | ≥3 бакета с n≥5 |
| Покрытие бенчмарка | `matched / planned`; пропуск = 0.5 ⇒ `+0.25/строку` к Brier | `OSPBenchResolve` | всегда |

Пол выборки — **одна константа на отдел** (`OSPMinN() = 10`, стиль Narad 8:
`ComputeFinanceMAPE`, `app.mlog:1259`). Ниже пола метрика **не публикуется**:
«недостаточно данных для калибровки (7/10 записей)», а не выдуманное число.

### 5.2 Platt: когда включается

`p' = sigmoid(a · logit(p) + b)`, обучение — градиентный спуск по log-loss
(400 итераций, `lr = 0.05`, только `ln/exp/sigmoid/clamp` из `registry.rs:166-174` —
никаких внешних зависимостей).

**Разделение по времени, а не случайно:** отложенная выборка = **хвост архива**
(последние 30 разрешённых строк по `verified_at`), обучение = всё, что старше.
«Подсмотреть ответ» невозможно конструкцией: отложка всегда новее обучения.

**Правило включения (единственное):**

```
ADOPTED,  если n_train ≥ 60 AND n_hold ≥ 30 AND Brier_hold(a,b) ≤ Brier_hold(1,0) − 0.005
REJECTED  иначе → a=1, b=0 (идентичность), p_final = clip(p_ensemble)
```

Коэффициенты и вердикт пишутся в `system_settings` (`osp_cal_a`, `osp_cal_b`,
`osp_cal_note = "ADOPTED gain=0.017 holdout_n=30"`), поэтому «почему сегодня
сжато/не сжато» видно запросом к БД. Ожидаемый эффект по литературе: Platt даёт
около −0.016 Brier на бинарных вопросах — но **включается только тогда, когда это
подтверждено на нашем архиве**, а не потому, что так написано в разборе турниров.

### 5.3 Clip

`clamp(p, 0.02, 0.98)` — константа отдела (`OSPClipLo/Hi`), применяется **после**
агрегации и **до** Platt, одинаково в обоих контурах. Обоснование: ни один прогноз
не бывает 0 или 1 до разрешения; крайние значения дают непропорционально большой
Brier на единственной ошибке (0.98 при исходе 0 ⇒ 0.96).

### 5.4 Как метрики попадают в `/osp score`

`OSPScoreBlock(kind)` возвращает **фиксированный программный текст** — модель не
имеет права приводить свои числа, её абзац идёт **после** блока:

```
📐 ОСП · точность (owner)
Прогнозов всего: 41 · разрешено: 27
Brier: 0.183
Skill vs «всегда 50%» (0.25): 0.268
Skill vs базовая частота: 0.114
Brier толпы/рынка: 0.201 · skill vs толпа: 0.09
Hit-rate при p ≥ 80%: 0.85 · surprise index: 0.15
Калибровка Platt: ADOPTED gain=0.017 holdout_n=30
```

Формат числа — 3 знака (`OSPFmt`): `1.0 − 0.41/0.25` печатается как
`-0.6399999999999999`, а в Telegram такое отправлять нельзя (проверено исполнением).
Команды `/osp score` и `/osp recalibrate` сохраняются, меняются их внутренности:
`OSPCalibrationScore:1052` (модель сочиняет оценку) и `OSPRecalibrate:1071`
(`to_char` → молчаливый провал) заменяются на `OSPScoreBlock` + `OSPPlattAdopt` +
`OSPMonthlyReview`, который пишет `monthly_reviews` через `strftime('%Y-%m', 'now')`.

Калибровочная кривая — `OSPCalibrationCurve(kind)` → JSON → `monthly_reviews.
calibration_curve` (поле уже существует, `app.mlog:440`) и `chart_line` с
`diagram_style({paper, ink, accent, muted, rule})` для картинки в Telegram
(`chart_line` требует `List<Struct{label,value}>` — проверено).

---

## 6. Тренировочный поток: Metaculus/ForecastBench

### 6.1 Почему ForecastBench, а не API Metaculus

| | Metaculus API | ForecastBench datasets |
|---|---|---|
| Условия | ToU: использование для обучения/оценки моделей — **только с письменного разрешения**; санкционированный путь — Bot Benchmarking tier (проект 32979) | `LICENSE` = **CC BY-SA 4.0**, файлы лежат на raw GitHub **без авторизации** |
| Доступ | все запросы требуют токен | GET, проверено загрузкой 02.11.2026 |
| Базовая линия толпы | `Community Prediction` = `null` вне выданных проектов | `freeze_datetime_value` — вероятность сообщества **на момент freeze** (для рыночных источников) |
| Исходы | нужно опрашивать каждый вопрос | `resolution_sets/<due>_resolution_set.json`: готовые `resolved_to ∈ [0,1]` |
| Риск | юридический + зависимость от токена | только атрибуция (и SA при републикации производных наборов) |

**Решение:** Metaculus как источник вопросов для обучения **отклонён**;ForecastBench —
основной поток. Отдельные вопросы Metaculus попадают к нам **через** ForecastBench
(в раунде 2026-10-25 их 42 из 500) — легально и без токена.

### 6.2 Что именно берём (проверено загрузкой)

Репозиторий `forecastingresearch/forecastbench-datasets`, ветка `main`:

| Файл | URL | Что даёт |
|---|---|---|
| Набор вопросов | `…/datasets/question_sets/<due>-llm.json` | 500 вопросов, `id, source, question, resolution_criteria, background, market_info_*, url, freeze_datetime, freeze_datetime_value, source_intro, resolution_dates` |
| «Свежий» набор | `…/datasets/question_sets/latest-llm.json` | тот же формат, без указания даты |
| Исходы | `…/datasets/resolution_sets/<due>_resolution_set.json` | `id, source, direction, resolution_date, resolved_to, resolved` |
| Сложность | `…/datasets/question_fixed_effects/question_fixed_effects.tournament_leaderboard.json` | `{forecast_due_date, source, id, horizon, leaderboard_type, question_fixed_effect}` (41 990 строк) |
| Люди-эталон | `…/datasets/forecast_sets/2024-07-21/2024-07-21.ForecastBench.human_super_individual.json` | формат сдачи + 7 693 прогноза суперпрогнозистов |
| Формат сдачи | тот же | `{organization, model, question_set, forecast_due_date, forecasts:[{id, source, forecast, resolution_date, reasoning, direction}]}` |

Раунд 2026-10-25 (проверено по файлу, 1 473 008 байт): **500 вопросов** —
kalshi 104, polymarket 104, serpapi 75, acled 50, fred 50, yfinance 50,
metaculus 42, dbnomics 25. Рыночных (kalshi+polymarket+metaculus) = 250,
dataset-вопросов = 250. Раунд 2026-10-11: 496 строк исходов, **265 разрешено**.

Две особенности формата, которые ломают наивную реализацию (проверено по данным):

1. `resolution_dates` — **либо** список ISO-дат (dataset-вопросы: 5 дат
   `2026-11-01, 2026-11-24, 2027-01-23, 2027-04-23, 2027-10-25`), **либо** строка
   `"N/A"` (рыночные вопросы: одно разрешение на закрытии рынка). Поэтому один
   вопрос даёт от 1 до 5 строк прогноза: 500 вопросов ⇒ **≈1500 строк** на раунд.
2. `freeze_datetime_value` — **строка**, и её смысл зависит от источника:
   у kalshi `"0.61"` и у metaculus `"0.1"` — это вероятность сообщества,
   а у fred `"103.8443465423"` и у yfinance `"LDOS: 119.22 (-7.8% over the last
   30 days); MRVL: 274.66 (+21.8% …)"` — это **уровень ряда**. Принять второе за
   вероятность — значит получить Brier ≈ 10 000 и ложный вывод «мы лучше толпы».
   В примере 5 `OSPBenchCrowd` возвращает вероятность только для
   `["kalshi","manifold","metaculus","polymarket"]`, иначе `-1.0` («нет линии»),
   и skill score против толпы для таких вопросов не считается.

### 6.3 Защита от утечки — три слоя + два правила

**Слой 1. Белый список полей (конструкция, а не фильтр).**
Полезная нагрузка для модели **собирается заново** из белого списка
`OSPBenchWhitelist()` = `question, resolution_criteria, background, source_intro,
url, freeze_datetime_value, resolution_dates, market_info_resolution_criteria`.
Поля исхода не могут в неё попасть, потому что их нет в списке. Дополнительно
`OSPBenchHasForbidden` проверяет точное присутствие ключей
`resolved_to, resolved, direction, outcome, actual_value, resolution_value` в
**вопросе**: если они там есть — файл перепутан (взяли `resolution_set` вместо
`question_set`), раунд останавливается. Это сравнение **точных имён ключей**
через `json_get` с sentinel-значением, а не поиск подстроки в тексте.

**Слой 2. Временной заслон.** Прогноз не принимается, если
`freeze_datetime` уже прошёл или рынок закрылся (`market_info_close_datetime`).
Сравнение — по epoch (`date_parse_iso`), потому что лексикографического сравнения
строк в Metalogos **нет** (`"2026-10-09" < "2026-11-02"` → `[TYPE_MISMATCH]
String Lt String`, проверено на обоих рантаймах). Внутри SQL строковые ISO-даты
сравнивать можно — это делает SQLite (пример 4).

**Слой 3. Разделение контуров.** `kind='bench'` и `kind='owner'` не смешиваются ни
в одной метрике (тест в примере 3), а bench-прогнозы не показываются владельцу как
«наши прогнозы» — только как калибровочный материал.

**Правило А (карантин источников).** В карточке `as_of` — момент среза. Источники,
опубликованные **после** `as_of`, помечаются в `sources_json` и в следующий прогон
не попадают (W5). Это прямое требование литературы: «бэктест на событиях, которые
модель уже знает» — утечка. Для bench-вопросов `as_of` = `freeze_datetime`.

**Правило Б (никаких ответов в промпте).** Resolution-файл читает только
`OSPBenchResolve`, который никогда не вызывается до того, как все прогнозы раунда
записаны. Порядок enforced программно: `OSPBenchResolve` обновляет строки со
`status <> 'resolved'` и считает покрытие по `osp_bench_rounds.n_rows`, записанному
на этапе ingest.

### 6.4 Сколько это стоит

Прайс — зеркало `proxy/providers.py:74-84` ($ за 1M токенов, input|output):
groq `0|0`, cerebras `0|0`, nvidia `0|0`, deepseek `0.14|0.28`, qwen `0.4|1.2`,
zai `0.5|1.5`, kimi `0.6|2.5`, openai `2.5|10`, anthropic `3|15`.

Бюджет токенов на прогон: 900 in / 150 out (вопрос + критерий + справка; структурный
ответ `{p, why}`). Стоимость строки прогноза = `Σ (900·in + 150·out)/1e6` по моделям.

| Состав | $/строка | Раунд 1500 строк | Обучающая выборка 40 строк |
|---|---|---|---|
| groq + cerebras (бесплатные) | 0.000000 | **0.00** | 0.00 |
| + deepseek («дешёвая тройка») | 0.000168 | **0.252** | 0.007 |
| + zai + kimi (полный ансамбль 5) | 0.001758 | **2.637** | 0.070 |
| один дорогой прогон (anthropic) | 0.004950 | 7.425 | 0.198 |

Раунды идут раз в 2 недели ⇒ **≈0.5 USD/мес** на дешёвой тройке или **≈5.3 USD/мес**
на полном ансамбле. Контур владельца: 5 прогонов ансамбля + 1 дорогой прогон на прозу
≈ 0.02–0.05 USD на прогноз ⇒ 30 прогнозов/мес ≈ **1.5 USD/мес**.

**Ворота бюджета** (`OSPBenchBudgetGate`) читают тот же ключ, что и прокси офиса —
`daily_budget_osp` из `system_settings` (`proxy/budget.py:99-108`), поэтому
«экономим» и «тратим» не разъезжаются. Вердикт — один из трёх:
`OK` / `OVER` (с точным числом строк, которые можно пройти: `cap / cost_per_row`) /
`UNLIMITED` (лимит не установлен — enforcement не активен, это видно в отчёте).

**Режимы:**
- *обучающий* — детерминированная стратифицированная выборка `OSPBenchSample(per_source)`
  (по N вопросов с источника, порядок по `qid`, **без `random()`** — иначе раунд
  невоспроизводим и сравнение методологий бессмысленно);
- *сдающий* — все 500 вопросов × все горизонты, ≥95% покрытия (требование лидерборда),
  включается только решением владельца (вопрос B.2).

### 6.5 Покрытие и цена пропуска

Правило бенчмарка: пропущенный прогноз импутируется `0.5` ⇒ вклад `(0.5 − y)² = 0.25`
в Brier за строку. `OSPBenchResolve` считает это явно и печатает:

```
RESOLVE|due=2026-10-25|строк_исходов=5|разрешено_наших=3|ещё_не_разрешено=1|
нет_нашего_прогноза=1|Brier_покрытых=0.06|покрытие=3/12|штраф_за_пропуски(импутация 0.5)=+0.188
```

Отсюда прямое следствие для политики: **лучше ответить на все 1500 строк дешёвой
тройкой (0.252 USD), чем на 500 строк дорогим ансамблем** — пропуск стоит дороже
прогона. Это аргумент против «экономии на покрытии».

### 6.6 Difficulty-adjusted index — честно о границе наших данных

С 06.06.2026 ForecastBench считает **difficulty-adjusted Brier Index (%)**, а не
сырой Brier; файл `question_fixed_effects` (41 990 строк: `{id, source, horizon,
question_fixed_effect}`) мы загружаем и храним, но **формулу индекса не
реконструируем по догадке** — она берётся из кода скоринга бенчмарка до первой
публикации на лидерборд (допущение A.4, вопрос B.2). До этого все внутренние отчёты
ведутся в сыром Brier + skill score, а `question_fixed_effect` используется как
**страта** для честного сравнения методологий (сравниваем только вопросы одной
сложности).

### 6.7 Атрибуция и лицензия

Каждая строка `osp_bench_rounds.license` = `CC BY-SA 4.0 ·
forecastingresearch/forecastbench-datasets`; `OSPBenchAttribution()` вставляется в
экспорт и в месячный обзор. Внутреннее использование атрибуцией и покрывается.
**ShareAlike срабатывает только при републикации производного набора** (например,
если выложить наши прогнозы как датасет) — это помечено как вопрос к Legal (B.2).

---

## 7. Методологии: что добавить, в какой форме, что убрать

### 7.1 Принцип выбора формы

> Если результат методики — **число или структура**, которая потом проверяется
> программой и участвует в метрике, это **структура данных** (поля карточки /
> JSON-узел). Если результат — **ход мысли**, который нельзя проверить иначе чем
> качеством текста, это **скилл-промпт**. Если результат методики можно посчитать —
> это **код**, и модель его считать не должна.

### 7.2 Семь методик из §4 задания

| Методика | Форма | Где живёт | Что проверяет программа | Что даёт в метрику |
|---|---|---|---|---|
| **Key Assumptions Check** | скилл-промпт **+ структура** | `osp_forecast.assumptions_json`: `[{text, confidence, evidence_url, if_wrong}]` | ≥3 допущения; у каждого есть `evidence_url` **или** метка `[СПЕКУЛЯЦИЯ]`; `confidence` — число, а не слово | `analysis_verifications.error_category` = «ошибка допущения», когда сбывшееся `if_wrong` совпало с исходом |
| **Deception Detection** | скилл-промпт | проза + `sources_json.tier` | W-гейт: если единственный источник имеет `tier='primary'` и автор — заинтересованная сторона (помечено структурой `{interested:true}`) | предупреждение в `gate_report`, не блокировка |
| **Центр тяжести по Стрейнджу (CG→CC→CR→CV)** | **структура** | `methods_json.cg_chain = {cg, cc, cr, cv}` | если методика заявлена — все 4 элемента непустые (иначе «заявлено, но не построено») | частота незавершённых цепочек → `skill_reviews.anti_patterns` |
| **PMESII-PT** | **структура** (замена g1/g2) | `methods_json.frame = {P,M,E,S,I,IT,PH,T}` | при depth≥2 заполнено ≥6 из 8 слотов | покрывает «полноту разбора» числом, а не поиском слова «AWARENESS» |
| **Cross-Impact Matrix / Balance** | **структура + код** | `methods_json.matrix = [{a, b, sign, weight}]` | программа считает итоги по строкам/столбцам и ловит противоречия (`A→B +`, `B→A −` без пометки `feedback`); **`OSPComputePotential` возвращается как программа**: `P = A×R×S×L×E×E_mod` считается из матрицы, а не из прозы | объясняет расхождение с базовой частотой (W1) |
| **Условные деревья прогнозов (FRI)** | **Entity/структура, не абзац** | `methods_json.tree = [{node, parent, question, p_cond}]` | программа перемножает вероятности вдоль ветвей и сверяет с `p_final`; сумма терминальных ≤ 1; расхождение > 0.15 → G-гейт «дерево не сходится с ответом» | главный кандидат на измеряемый выигрыш: A/B «дерево есть / дерева нет» (§7.4) |
| **Contrasting Narratives / Red Hat** | скилл-промпт **+ структура** | `methods_json.narratives = [{name, if_true_indicators:[…]}]` | ровно 2 нарратива; у каждого ≥2 индикатора **с датой** → индикаторы становятся строками `indicator` (таблица `app.mlog:267`, сегодня 0 писателей) с `verify_date` и `confirms_what` | `indicators_triggered/indicators_total` в `analysis_verifications` — реальная, а не декларируемая, обучаемость |

Ни одна из семи не требует новой таблицы: всё ложится в `methods_json`/
`assumptions_json` карточки и в уже существующие `indicator`,
`analysis_verifications`, `skill_reviews`.

### 7.3 Что убрать

| Убрать | Почему (проверено) |
|---|---|
| `OSPComputeBrier` (`osp.mlog:256`), `OSPComputePotential` (`:249`), `OSPShermanKent` (`:70`) в текущем виде | мёртвый код: не вызывается нигде. Brier → `OSPBrier` (пример 3), потенциал → программа поверх матрицы (§7.2), Кент → `OSPKentOf` число→метка (пример 1) |
| g1–g12 `OSPCheckQualityGates` (`:275-329`) | поиск подстрок в прозе; два гейта всегда `true`; результат только в журнал. Замена: G1–G6/W1–W5 (§4) + структурные проверки PMESII/дерева |
| `OSPValidateProbability` (`:88`) | «валидация вероятности» поиском слов `likely/вероятно/%`: строка «вероятность не определена» проходит как PASS. Замена: `json_validate` по схеме |
| `OSPRecalibrate` (`:1071`) в текущем виде | модель сочиняет «3 изменения» + `to_char` роняет запись в `monthly_reviews`. Замена: `OSPPlattAdopt` + `OSPMonthlyReview` |
| «Postgres» в тексте `skills/deconstruct/SKILL.md` (2 упоминания) | рантайм — SQLite; текст скилла обещает архив «in Postgres» |
| Обещание «BLOCKER» в профиле `library/osp.md` | блокировки нет: гейты пишут только в журнал. Либо блокировка (G1–G6), либо слово «BLOCKER» из профиля убрать |

**Что НЕ убираем** (проверено grep'ом по 24 скиллам): «мульти-персоны» и слово
«Bayesian» в скиллах **отсутствуют** — то есть два известных вредителя из литературного обзора к нам не завезены. Совпадений по «persona» — ложные (`personal connections`,
`personally`).

### 7.4 A/B методологий: как измеряем «какие скиллы реально помогают»

Каждый прогон ансамбля пишет в `methods_json` **состав** (какие методики/скиллы были
в промпте) и свою оценку `p_i`. После разрешения исхода программа группирует архив:

```sql
SELECT method, COUNT(*) n, AVG((p_i - outcome)*(p_i - outcome)) brier
FROM osp_forecast_method_runs WHERE status = 'resolved' GROUP BY method
```

(одна плоская таблица `osp_forecast_method_runs(forecast_id, method, p_i, family)` —
**седьмая** таблица, добавляется только в волне 4, когда есть что сравнивать;
до этого `methods_json` хватает.) Пол — тот же n≥10 на методику, иначе
«недостаточно данных». Результат пишется в `skill_reviews.success_rate` и
`arsenal_reviews.skills_underused/obsolete` — таблицы уже созданы (`app.mlog:447`,
`:401`).

### 7.5 Загрузчик скиллов — волна 0 (блокирует всё остальное)

`LoadOSPEnrichedSkills` (`osp.mlog:833-901`) проверяет бюджет **до** добавления, но
не проверяет, влезет ли **сам** скилл:

```mlog
let budget = OSPSkillBudget(1)                     // ← depth игнорируется: всегда 12000
let s = read_file_or("skills/deconstruct/SKILL.md","")
if s != "" and length(result) < budget then { result = result + … }   // 15 640 символов
```

`deconstruct` = **15 640** символов > бюджета **12 000** ⇒ после первого же скилла
`length(result) < budget` становится ложью, и **остальные 19 подключённых скиллов не
загружаются никогда**. Дополнительно:

- `OSPSkillBudget(depth)` вызывается с константой `1` (`:836`) — бюджеты 18 000/
  20 000/23 000 для depth 2/3/4 недостижимы;
- в `skills_index/osp.txt` **24** скилла, в загрузчике — **20**; никогда не
  подключаются `antifragility-design`, `phase-transition-detection`,
  `schelling-points`, `source-triangulation`;
- при этом `deconstruct/SKILL.md` в разделе Prerequisites **требует**
  `source-triangulation` («All Tier 1 skills available: … source-triangulation») —
  мастер-протокол ссылается на скилл, которого загрузчик не подключает;
- весь корпус 24 скиллов = **349 761** символов (~87k токенов): загрузить всё
  нельзя ни при каком бюджете, отбор обязателен.

**Починка (волна 0):** (1) передавать реальный `depth`; (2) проверять
`length(result) + length(s) ≤ budget`, а не `length(result) < budget`;
(3) вместо «всё подряд» — индекс скиллов с приоритетом по домену и типу вопроса
(`skills_index/osp.txt` + `skill_reviews.usage_count`); (4) разрезать `deconstruct`
на ядро (2–3 тыс. символов) и приложения, которые подгружаются по требованию;
(5) подключить `source-triangulation` — он нужен гейту G5 и правилу карантина W5.

---

## 8. Примеры кода `.mlog`

Пять файлов в `deliverable/examples/`. Каждый самодостаточен (собственный `schema`-блок,
собственные тесты), каждый проверен тремя командами на **двух** рантаймах:

```sh
export DATABASE_URL="sqlite::memory:"
bin/mlog check deliverable/examples/0N_….mlog   # статика: Category-A/B, taint, sink clearance
bin/mlog test  deliverable/examples/0N_….mlog   # исполнение тестов
bin/mlog run   deliverable/examples/0N_….mlog   # для 04 и 05: исполняет flow
sh deliverable/examples/run_all.sh              # всё сразу на 0.34.1 и 0.38.0
```

| Файл | Что доказывает | Тесты | `check` |
|---|---|---|---|
| `01_osp_card.mlog` | карточка как сущность; G1–G3/G5 гейты по числам и датам; clip `[0.02,0.98]`; Кент число→метка; бакет децилей; **единственная точка записи** (`OSPSaveCard`): PASS ⇒ `published` + `p_final`, FAIL ⇒ `gated` + `p_final IS NULL` | 9/9 | 2 warn (`db_insert` experimental) |
| `02_osp_ensemble.mlog` | ансамбль из 5 семейств (groq/cerebras $0, deepseek, zai, kimi); `OSPParseRun` = PASS-число или FAIL-причина; агрегация mean/median/logit-pool + population stdev + range; **квота бюджета** в kv на UTC-день; сверка с рынком; карантин по порядку вызовов | 7/7 | `OK: no issues found` |
| `03_osp_scoring.mlog` | `OSPBrier`, `OSPLogLoss`, `OSPSkillScore`; тест «монетка даёт ровно 0.25»; Platt градиентным спуском (`while`, 400 итераций); разделение обучение/отложка **по времени**; правило включения `ADOPTED/REJECTED/SKIP`; `OSPScoreBlock` с полом n≥10; калибровочная кривая одним литеральным SQL | 10/10 | `OK: no issues found` |
| `04_osp_lifecycle.mlog` | карта состояний (публикация мимо гейтов невозможна); `OSPTransition` = запись + событие + отказ-как-событие; базовая частота и сжатие `w=n/(n+10)`; вахта (`OSPWatchDue/Open`); **громкая** архивация просрочки; `OSPParseOutcome` (проза исходом не считается); Entity + Rule + Flow (`mlog run` печатает отчёт вахты) | 12/12 | 3 warn |
| `05_osp_bench.mlog` | адреса набора/исходов/QFE; три слоя защиты от утечки; crowd-линия только для рыночных источников; горизонты 1 vs 5; идемпотентный ingest (`SKIP` при повторе — деньги второй раз не тратятся); прайс из `proxy/providers.py`; ворота бюджета по `daily_budget_osp`; детерминированная стратифицированная выборка; обобщённый Brier + штраф за пропуски; экспорт в формате бенчмарка | 16/16 | 4 warn |

**Итого: 54 теста × 2 рантайма = 108 зелёных прогонов, 0 ошибок `check`.**
Единственные предупреждения — `[BUILTIN_EXPERIMENTAL] db_insert` (неизбежно: `INSERT`
через `db_insert` помечен experimental в `registry.rs`; альтернатива — `db_execute`
с литеральным SQL, что и сделано для `UPDATE`).

### 8.1 Ловушки рантайма, найденные исполнением (все — на обоих версиях)

Эта таблица — практический выход аудита: каждая строка стоила прогона и каждая
способна молча сломать прод.

| № | Ловушка | Симптом | Как обходим |
|---|---|---|---|
| 1 | Вывод LLM/HTTP — недоверенный; решение по нему = Category-A | `mlog check`: `[UNTRUSTED_DECISION]` | домовая идиома `redact(to_string(TryVal(try call_llm(…))), "all")` — **сначала `to_string`, потом `redact`** (redact на числе/Unit — ошибка исполнения, №422) |
| 2 | `json_validate` на не-JSON **падает**, а не возвращает `valid=false` | исключение наружу | `TryVal(try json_validate(…))`; `"()"` = FAIL прогона |
| 3 | `call_llm_schema` **не имеет** аргумента модели: формы `(prompt,schema)` и `(prompt,input,schema)`; у `call_llm(prompt,input,model)` модели есть, структуры нет | нельзя одновременно выбрать семейство и получить структуру | `call_llm` (3 арг.) + `json_validate` вручную (пример 2); заявка C.3 |
| 4 | `to_int` возвращает **Float** | warn-only `[n486]` + сравнение `1 == 1.0` | объявляем `-> Float`, в тестах литералы `0.0/3.0/9.0` |
| 5 | `days_between(a,b)` — **модуль** (симметричен) | «дата в прошлом» неотличима от «в будущем» | `(date_parse_iso(iso) − now_unix())/86400.0` |
| 6 | Лексикографики строк **нет** | `"2026-10-09" < "2026-11-02"` → `[TYPE_MISMATCH] String Lt String` | даты сравниваем как epoch; внутри SQL — можно (это делает SQLite) |
| 7 | `reduce(list,"sum",0.0)` не суммирует | тихий ноль | явные циклы `each`/`while` |
| 8 | `make_list(3.0)` = `[3]` (обёртка аргументов), не заполнение | неожиданный список | `[]` + `push(list, v)` |
| 9 | `filter` требует **3** аргумента | ошибка арности | `each` + условие |
| 10 | `fluid x = …` только на верхнем уровне | в теле шаблона `[UNDEFINED_VARIABLE]` | Fluid не используем; уверенность — полями (заявка C.2) |
| 11 | `rule` не исполняется в `test`-блоках; не читает БД; не вызывает шаблоны | `rule If(Fn() …)` → run: `[UNDEFINED_VARIABLE] VM rule: … 'FnCall{…}'` | правило — только над полем entity-структуры; переходы статусов — шаблонами |
| 12 | `rule` над простой `entity s: String = "expired"` | run: `contains: both sides must be String`, **`check` молчит** | entity-структуры (`AlertState{level,note}`) |
| 13 | `db { url: env_or(…) }` | `mlog run`: «VM compiles only db { url: "literal" } or db { url: env("NAME") }» | прод-форма `env("DATABASE_URL")` (`app.mlog:29`), в тестах — `DATABASE_URL=sqlite::memory:` |
| 14 | `DELETE`/`DROP`/`ALTER` в `db_execute` | `[IRREVERSIBLE_NO_GRANT]` (Category-A) | `UPDATE`/`INSERT` — без гранта; миграции — `AlterColIfMissing(mig,…)` + `db_execute_with_grant` |
| 15 | `to_char()` не существует в SQLite | `[SQL_ERROR]` внутри `let _ =` — **молча** | `strftime('%Y-%m','now')`; именно так сегодня падает `OSPRecalibrate:1078` |
| 16 | `to_string(Json-узла)` — это Rust Debug (`Json {a: [1, 2]}`), не JSON | битый JSON на выходе | наружу — только `json_encode` (экранирует кавычки/переводы строк, UTF-8) |
| 17 | `kv_get` на отсутствующем ключе | `""` или `"()"` → `to_float` падает | `length(raw)>0 and raw != "()"` → `to_float_or(raw, 0.0)` |
| 18 | IEEE-754 в тестах | `(0.3+0.4+0.5)/3 = 0.39999999999999997` | `abs(a-b) < 0.0000001`; для человека — `OSPFmt` (`round(x*1000)/1000`) |
| 19 | `source` — ключевое слово (`source <origin>`, ADR-0164) | `if x == source then` читается как построение хендла из ориджина `then` → `media_source_capture: unknown origin 'then'`, **`check` молчит** | переменные называем `src`; `"source"` — только как строковый ключ |
| 20 | `mlog test` **не** подразумевает `mlog check` | тесты зелёные, а taint-анализ красный | всегда обе команды (+ `--root` для dept-файлов) |
| 21 | Все `test`-блоки файла делят **одно** подключение к БД | строки предыдущих тестов видны | тесты ищут свои строки, а не берут «первую»; часы — аргументом (`now_iso`) |
| 22 | `query(format(…))` — compile error; только литеральный SQL | `[SQL_DYNAMIC]` / parse error | все SQL — литералы, параметры — `?` |

### 8.2 Состояние прод-кода сегодня (для честности картины)

`mlog check app.mlog --root app.mlog` (идентично на 0.34.1 и 0.38.0):
**103 ошибки, 32 предупреждения**. Из ошибок **66** — артефакт двойного разбора
(`duplicate pattern`: файл разбирается и как цель, и как корень; `InitDB` объявлен
один раз — проверено). Содержательных **37**, все класса sink-clearance:
`SECRET_EGRESS_NETWORK` 9 (в т.ч. **`OSPTelegramSearch`, `osp.mlog:1169`** —
`http_post` с меткой `private`), `UNTRUSTED_EGRESS_NETWORK` 8, `PII_EGRESS_NETWORK` 8,
`SINK_CLEARANCE` 6 (все в `InitDB`), `HTML_INJECTION` 3 (`GET /`, `/health`,
`/version`), `IRREVERSIBLE_NO_GRANT` 2 (`RecordRateLimitCall`), `PII_EGRESS_OUTPUT` 1.
Из предупреждений к ОСП относятся два `[n486]`: `OSPSkillBudget:64` и
`OSPAutoEscalate:353`. Это не предмет данного наряда, но волна 0 обязана не
**ухудшить** счётчик: критерий приёмки — «не больше 37 содержательных находок».

---

## 9. Сквозной пример: «Будет ли ключевая ставка ФРС на конец 2026 ниже 3.5%?»

Владелец пишет: `/osp deep ставка ФРС конец 2026 ниже 3.5%`.

Контекст на момент прогона (открытые источники, 29–30.10.2026 — в проде
перепроверяется живым поиском): эффективная ставка FED ≈ **3.88%**; OIS закладывает
≈**85%** вероятности **повышения** на 25 б.п. на заседании 09.12.2026; ранее в 2026
диапазон цели был 3.50–3.75%. То есть вопрос «ниже 3.5% к 31.12.2026» требует двух
снижений подряд — и наивная модель, обученная на нарративе «ФРС снижает», здесь
систематически ошибается вверх. Именно такой вопрос полезен: он показывает работу
гейтов, базовой частоты и сверки с рынком. *(Числа прогонов ниже — иллюстративные;
в проде их дают ансамбль и живой поиск.)*

### 9.1 Шаг 1. Карточка вопроса (до ответа владельцу)

`OSPSaveCard` пишет **одну** строку (`kind='owner'`):

```
osp_forecast
  id                  = 147
  kind                = 'owner'
  question            = 'Ключевая ставка ФРС будет ниже 3.5% на 31.12.2026?'
  resolution_criteria = 'Верхняя граница целевого диапазона FOMC по итогам
                         заседания 09.12.2026 (или последнего в 2026 году) < 3.50%.
                         Источник: federalreserve.gov, FOMC target range.'
  as_of               = '2026-11-02'          -- якорь (#474)
  resolve_by          = '2026-12-31'
  status              = 'drafted'
  analysis_id         = 88                    -- OSPDraftAnalysis (:264) как раньше
```

`OSPCardGates`: G2 — критерий 213 символов ≥ 20 ✓, `resolve_by` в будущем
(+59 дней) ✓, `as_of` не в будущем ✓. `analysis` получает ту же строку, что и
сегодня, плюс `osp_forecast_id = 147` (§3.3) — **ничего не сломано**.

### 9.2 Шаг 2. Исследование → источники с карантином

Живой поиск и рынки (существующие `OSPLiveSearchBlock:566`,
`OSPMarketDataBlock:666`, `OSPFreshnessGate:606`) пишут в `research_source`
(таблица существует с `app.mlog:264`, писателей сегодня нет) и в `sources_json`:

```
research_source
  147 | https://www.federalreserve.gov/…  | 'FOMC target range'   | tier='primary'   | as_of='2026-11-02'
  147 | https://rateprobability.com/fed   | 'OIS: ~85% hike 12/2026' | tier='secondary' | as_of='2026-11-02'
  147 | https://streetstats.finance/…     | 'EFF ≈ 3.88%'         | tier='secondary' | as_of='2026-11-02'
osp_forecast.market_json = '{"kalshi":"FED-2026-DEC<3.5","p":0.03,"as_of":"2026-11-02"}'
```

Правило карантина: всё, что опубликовано после `as_of`, в следующие прогоны не
попадает (W5). `crowd_p = 0.03` — линия рынка для skill score.

### 9.3 Шаг 3. Базовая частота и сжатие

```
osp_base_rates: topic='fed_rate', n=8, base_rate=0.35, source='own_archive+FRED'
OSPPriorWeight(8) = 8/(8+10) = 0.4444
```

### 9.4 Шаги 4–6. Ансамбль → агрегация → clip

Пять прогонов на разных семействах (пример 2), структурный ответ `{p, base_rate_hint, why}`:

| Прогон | Семейство (цена $/1M in\|out) | `p_i` |
|---|---|---|
| 1 | groq `openai/gpt-oss-20b` (0\|0) | 0.12 |
| 2 | cerebras `gpt-oss-120b` (0\|0) | 0.08 |
| 3 | deepseek `deepseek-chat` (0.14\|0.28) | 0.05 |
| 4 | zai `glm-4.6` (0.5\|1.5) | 0.10 |
| 5 | kimi `kimi-k3` (0.6\|2.5) | 0.07 |

Программа (`OSPAggregate`): `p_ensemble = mean = 0.084`; `p_median = 0.08`;
`p_logit = sigmoid(mean(logit)) = 0.0807`; `p_spread = 0.024` (population stdev);
`range = 0.05…0.12`. G3: `0.024 ≤ 0.25` ✓, `n_runs = 5 ≥ 3` ✓.

Сжатие к базовой частоте: `p = 0.4444·0.35 + 0.5556·0.084 = 0.2022`.
Clip: `0.202 ∈ [0.02, 0.98]` ⇒ без изменения. **`p_final = 0.202`**,
`cal_bucket = 2`, `kent_label = 'unlikely (20-35%)'`.

Стоимость шага: 5 × (900·in + 150·out) ⇒ groq/cerebras 0 + deepseek 0.000168 +
zai 0.000675 + kimi 0.000915 = **0.001758 USD**; отдельный дорогой прогон на прозу
для владельца (anthropic) — **0.00495 USD**. Итого карточка ≈ **0.007 USD**.

### 9.5 Шаг 7. Сверка с рынком → срабатывает предупреждение W3

`|0.202 − 0.03| = 0.172` ⇒ G6 (≤0.35) проходит, **W3 (>0.15) срабатывает**: наша
оценка в 6.7 раза выше рыночной. Это не блокировка, а требование обоснования —
и ровно тот случай, ради которого W3 существует: базовая частота темы
(`prior = 0.35`, n=8) тянет оценку вверх, а рынок говорит «почти наверняка нет».
В `gate_report` уходит `{"w3":"WARN расхождение с рынком 0.172; причина: prior_rate
0.35 при n=8"}`, а в ответе владельцу — строка про расхождение (§9.6).

Для масштаба: если бы априорное было 0.5 (устаревший нарратив «ФРС всегда
снижает»), `p_final` = 0.269, расхождение 0.239 ⇒ то же W3; при априорном 0.8 —
`p_final` = 0.402, расхождение 0.372 ⇒ **G6 блокирует публикацию** до явного
обоснования отклонения от рынка.

### 9.6 Шаги 8–9. Гейты и архив

```
gate_report = {"g1":"PASS","g2":"PASS","g3":"PASS","g4":"n/a (один сценарий)",
               "g5":"PASS","g6":"PASS","w1":"PASS","w2":"PASS",
               "w3":"WARN расхождение с рынком 0.172 (prior_rate 0.35, n=8)",
               "w4":"WARN горизонт 59 дней","w5":"PASS"}
status: drafted → gated → published → watching
osp_forecast_events
  147 | drafted   → REFUSED>published | 'попытка прыгнуть через гейты' | 2026-11-02T09:14Z
  147 | drafted   → gated             | 'G1–G6 PASS'                   | 2026-11-02T09:14Z
  147 | gated     → published         | 'гейты пройдены, p_final=0.202' | 2026-11-02T09:15Z
  147 | published → watching          | 'вахта: ждём разрешения до 2026-12-31' | …
analysis.full_result ← проза дорогого прогона (dept/visual.mlog наконец получает данные)
```

**Что видит владелец в Telegram** (формат команды не меняется, добавляется числовой
хвост — блок собирается программой):

```
🎯 ОСП · прогноз #147 · 02.11.2026
Ключевая ставка ФРС будет ниже 3.5% на 31.12.2026?
Вероятность: 20.2% — unlikely (20–35%)
Основание: OIS закладывает ~85% повышения на 25 б.п. 09.12.2026; EFF 3.88%;
для «ниже 3.5%» нужны два снижения подряд до конца года.
Ансамбль: 5 прогонов, среднее 0.084, медиана 0.080, разброс 0.024
Базовая частота темы fed_rate: 0.35 (n=8) → сжатие к априорному w=0.44
Рынок (Kalshi): 0.03 · ⚠️ расхождение 0.172 — мы выше рынка, причина: априорное
Проверка: 31.12.2026 · критерий: верхняя граница диапазона FOMC < 3.50%
Гейты: G1–G6 PASS · W3: расхождение с рынком · W4: горизонт 59 дней
⚠️ Не является инвестиционной рекомендацией.
```

### 9.7 День проверки (31.12.2026 → ночной слот 02.01.2027)

Вахта (`flow ForecastAdvance` в ночном слоте, `dept/schedules.mlog` +
`OutboxPut`/`OutboxFlush` 07:15):

```
OSPWatchDue('2027-01-02')  → [#147]
OSPParseOutcome('no')      → y = 0.0        (подтверждение исхода — владелец или
                                             официальный источник, не модель)
OSPVerifyCard(147, 'no', '2027-01-02')
  brier = (0.202 − 0)² = 0.0408
  status: watching → resolved
osp_forecast        : outcome=0, brier=0.0408, brier_base=0.25, brier_crowd=0.0009,
                      verified_at='2027-01-02'
brier_score_log     : 147 | 0.202 | 0 | 0.0408 | cumulative_brier | total_forecasts  ← писатель появился
analysis_verifications : osp_forecast_id=147, brier_total=0.0408,
                      error_category='overconfidence_vs_market', error_note='W3 сработал и оказался прав',
                      indicators_triggered=1, indicators_total=3                    ← писатель появился
osp_forecast_events : 147 | watching → resolved | 'исход=0 подтверждён, Brier=0.041'

Чему учит эта запись (числа, а не проза):
  skill vs «всегда 50%» : 1 − 0.0408/0.25    = +0.837  (выглядит отлично)
  skill vs рынок        : 1 − 0.0408/0.0009  = −44.3   (рынок знал лучше)
Именно поэтому в /osp score обе линии печатаются рядом: абсолютный Brier
легко льстит, а предупреждение W3 сработало ДО разрешения — и его стоит
посчитать как «гейт, который поймал ошибку».
```

Если бы исход не подтвердили до 31.01.2027, сработала бы **громкая** архивация:
`status='expired'` + событие + строка в утреннем отчёте + счётчик в kv
(`OSPArchiveExpired`, пример 4). «Тихо исчезло» больше невозможно.

### 9.8 Месячный обзор (01.02.2027)

```
monthly_reviews (поля уже существуют, app.mlog:440)
  year_month='2027-01', forecasts_verified=27, brier_average=0.183,
  brier_trend='-0.011', hit_rate_high_conf=0.85, surprise_index=0.15,
  calibration_curve='[{"bucket":1,"n":6,"mean_p":0.14,"mean_y":0.17}, …]',
  error_clusters='[{"kind":"overconfidence_high_p","n":4}]',
  dominant_error='переупоренность при p≥0.8', improvements='[…]', improvements_applied=1
OSPPlattAdopt('owner') → 'SKIP|рекалибровка: n=27 < 90 — коэффициенты не обучаются,
                          p_final = p_ensemble'   (честно, а не «модель придумала»)
system_settings: osp_cal_a=1, osp_cal_b=0, osp_cal_note='не обучалась (мало данных)'
```

`/osp score` показывает блок из §5.4 — числа из БД, проза модели **после** блока.
Через 2 месяца после включения bench-контура n≥50 набирается за один раунд, и
`OSPPlattAdopt` начинает возвращать `ADOPTED`/`REJECTED` с реальным выигрышем.

---

## 10. План: нулевая волна + 4 волны нарядов

Оценка стоимости — две цифры: **runtime** (токены/доллары в месяц после внедрения) и
**dev** (токены агента-исполнителя; оценка грубая, ±50%). «Готово, когда» — всегда
проверяемый факт: команда, запрос к БД или **тест-мутация** (ломаете строку — тест
краснеет).

### Волна 0 — предусловие (1–2 дня). Загрузчик скиллов и базовая линия `check`

| | |
|---|---|
| Задачи | (1) `LoadOSPEnrichedSkills`: передавать реальный `depth`, проверять `length(result)+length(s) ≤ budget`; (2) подключить `source-triangulation` (требуется самим `deconstruct`); (3) разрезать `deconstruct` на ядро + приложения; (4) убрать «Postgres» из текста скилла; (5) зафиксировать базовую линию `mlog check app.mlog --root app.mlog` = 37 содержательных находок |
| Готово, когда | `length(LoadOSPEnrichedSkills("ставка ФРС","monetary")) > 30000` при depth=2 и в логе промпта видно ≥6 скиллов; **тест-мутация**: вернуть проверку `length(result) < budget` → тест на число загруженных скиллов краснеет; `mlog check` не хуже 37 |
| Стоимость | runtime: +8–12k токенов на прогон deep/full (скиллов грузится больше) ⇒ **+0.02–0.05 USD** на запрос при ценах anthropic/openai, ~0 на бесплатных семействах. dev: ~1.5M токенов |
| Риск | Больше токенов в промпте ⇒ дороже и медленнее. Митигация: бюджет по depth и отбор по домену, а не «всё подряд» |
| Зависимости | нет. **Блокирует волны 1–4**: бессмысленно мерить выигрыш методологий, если загружается один скилл из 20 |

### Волна 1 — Карточка и жизненный цикл (1–2 недели)

| | |
|---|---|
| Задачи | таблицы `osp_forecast`, `osp_forecast_events` + ALTER-хвост (§3.3); `OSPSaveCard`, `OSPCardGates` (G1–G3, G5), `OSPClip`, `OSPKentOf`, `OSPBucketOf`; `OSPCanTransition`/`OSPTransition`/`OSPNextAction`; запись `analysis.full_result` и `research_source` (первые писатели); `/osp deep|full` пишут карточку, команды и форматы **не меняются** |
| Готово, когда | после `/osp deep …` в БД есть строка `osp_forecast` с `p_final IS NOT NULL` и ≥2 строки в `osp_forecast_events`; `SELECT COUNT(*) FROM analysis WHERE full_result IS NOT NULL` растёт; **тест-мутации**: убрать `osp_forecast_events`-вставку → тест «переход пишет событие» краснеет; добавить `"drafted>published"` в карту → тест «публикация мимо гейтов невозможна» краснеет |
| Стоимость | runtime: 0 новых вызовов LLM (карточка заполняется из уже существующего прогона) ⇒ **±0 USD**. dev: ~3M токенов |
| Риск | Двойная запись (`analysis` + `osp_forecast`) разъедется. Митигация: один шаблон-писатель, `analysis_id` в карточке, инвариант 1 (§3.5) |
| Зависимости | волна 0 |

### Волна 2 — Числа: ансамбль, Brier, `/osp score` (2 недели)

| | |
|---|---|
| Задачи | `OSPEnsemble` + `OSPParseRun` + `OSPAggregate` (пример 2); kv-счётчик бюджета на UTC-день; `OSPCrowdCompare` (W1/W3/G6); `OSPVerifyCard`/`OSPParseOutcome`; `OSPBrier`/`OSPSkillScore`/`OSPLogLoss`; `OSPScoreBlock` + пол n≥10; писатели `brier_score_log`, `analysis_verifications`, `monthly_reviews` (через `strftime`, не `to_char`) |
| Готово, когда | `/osp score` печатает блок §5.4 с числами из БД (при n<10 — «недостаточно данных (7/10)»); после подтверждения исхода `brier_score_log` получает строку; **тест-мутации**: заменить `OSPBrier` на `abs(p−y)` → тест `(0.7−1)²=0.09` краснеет; подставить `p=0.5` константой → тест «монетка даёт 0.25» доказывает, что цель года 1 тривиальна |
| Стоимость | runtime: 5 прогонов на прогноз владельца ⇒ **+0.002–0.02 USD** на прогноз (дешёвые семейства) и до +0.05 при полном ансамбле; 30 прогнозов/мес ⇒ **0.1–1.5 USD/мес**. dev: ~4M токенов |
| Риск | Ансамбль умножает стоимость и латентность (5 последовательных вызовов). Митигация: дешёвые семейства первыми, потолок вызовов в kv, деградация до одного прогона с честной пометкой W2 |
| Зависимости | волна 1 |

### Волна 3 — Внешний поток и вахта (2–3 недели)

| | |
|---|---|
| Задачи | `OSPBenchFetchSet/Ingest/LeakGuard/Strip/Crowd/Horizons` (пример 5); таблицы `osp_bench_*`; `OSPBenchResolve` + обобщённый Brier + штраф за пропуски; `OSPBenchBudgetGate` по `daily_budget_osp`; `OSPBenchSample` (детерминированная стратификация); cron-слоты: ночная вахта (`ForecastAdvance`) + раунд по вторникам/субботам; `OSPArchiveExpired` в утренний `OutboxFlush` 07:15 |
| Готово, когда | после ingest раунда `SELECT n_rows FROM osp_bench_rounds` = ожидаемому (для 2026-10-25 — 1500±10%); повторный ingest того же due возвращает `SKIP`; **тест-мутации**: подменить `question_set` на `resolution_set` → тест «поле исхода в вопросе → BLOCK» краснеет; сдвинуть `now_iso` за `freeze_datetime` → тест «прогноз задним числом не принимается» краснеет; убрать белый список → тест «в payload нет `resolved_to`» краснеет |
| Стоимость | runtime: **0.25 USD/раунд** (дешёвая тройка, 1500 строк) ⇒ ~0.5 USD/мес; обучающая выборка 40 строк — 0.007 USD. `http_get` гранта не требует (в отличие от `http_post`/`send_message`/`exec` — `registry.rs:281`, наряд #620). dev: ~4M токенов |
| Риск | (а) 1.47 MB JSON в одной строке — память/время разбора; митигация: `http_download` в файл + разбор, замер на первом реальном раунде (допущение A.6); (б) `cron_run` в 0.38 требует мандат человека ⇒ слоты регистрируем существующим механизмом `dept/schedules.mlog` + маршруты `/cron/...` с `SecretMatches` (`app.mlog:1996`), а не `cron_run` |
| Зависимости | волны 1–2 (нужны `OSPBrier`, `OSPTransition`) |

### Волна 4 — Обучение: Platt, A/B методологий, кривая (2 недели)

| | |
|---|---|
| Задачи | `OSPPlattFit/Adopt/Apply` + правило включения (§5.2); `OSPCalibrationCurve` → `monthly_reviews.calibration_curve` + `chart_line`; `methods_json` и таблица `osp_forecast_method_runs`; семь методик §7.2 в виде структур + проверки; `OSPBenchExport` + загрузка `question_fixed_effects` как страты; запись `skill_reviews`/`arsenal_reviews` |
| Готово, когда | `system_settings.osp_cal_note` содержит `ADOPTED gain=…` **или** `REJECTED gain=…` (не пусто); при `REJECTED` `p_final = clip(p_ensemble)` побитово; **тест-мутации**: снизить порог выигрыша до 0 → тест «нет выигрыша на отложке → REJECTED» краснеет; обучить на отложке вместо обучения → выигрыш станет отрицательным и тест это поймает |
| Стоимость | runtime: ~0 (Platt — арифметика; A/B — один `GROUP BY`). dev: ~3M токенов |
| Риск | Переобучение на малом n. Митигация: пороги n≥60/n≥30 и выигрыш ≥0.005, разделение по времени, идентичность по умолчанию |
| Зависимости | волна 3 (без bench-контура n не наберётся) |

### Контрольные точки критерия успеха

| Срок | Что должно быть видно |
|---|---|
| +2 недели | `/osp deep` пишет карточку и события; `analysis.full_result` непустое; `dept/visual.mlog` снова имеет данные |
| +1 месяц | `/osp score` показывает Brier по bench-раунду (n≥100 разрешённых строк), owner-контур — «недостаточно данных (k/10)» честно |
| +2 месяца | **≥50 разрешённых прогнозов с реальным Brier** (критерий задания), из них ≥25 `owner` — при 1–3 вопросах в неделю это требует вахты без потерь; `OSPPlattAdopt` = `ADOPTED`/`REJECTED` с числом; калибровочная кривая в `monthly_reviews` |
| +3 месяца | A/B методологий: у ≥3 методик n≥10 и виден знак эффекта; `skill_reviews.success_rate` заполнен |

---

## 11. Компромиссы и отвергнутые варианты

### 11.1 Отвергнуто

| Вариант | Почему отвергнут |
|---|---|
| **Metaculus API как тренировочный поток** | ToU: обучение/оценка моделей — только с письменного разрешения; нужен токен; `Community Prediction` = `null` вне выданных проектов. ForecastBench даёт то же легально и без ключей |
| **God-table: всё в `analysis`** | Документ и запись с числовым жизненным циклом — разные сущности; один документ несёт несколько сценариев (#469), один bench-вопрос — 5 горизонтов. Повторяет урок v4.1 (§3.4) |
| **`flow` + `rule` как каркас конвейера** | `rule` не читает БД, не зовёт шаблоны, не исполняется в тестах; `flow` не покрывается `mlog test`. Конвейер стал бы непроверяемым — ровно та болезнь, которую лечим |
| **Векторный поиск похожих вопросов (`vec_*`)** | Фича `vec` не входит в default-сборку Cargo (проверено); `memorize/recall` — эфемерный `Vec` ВМ. Берём FTS5 (работает в bundled SQLite — проверено) |
| **Гейты, которые судит модель (`ControlCheck`)** | Нарушение ограничения 6 задания: суждение там, где программа может прочитать данные |
| **Brier/калибровка «силами модели»** | То же; плюс `OSPCalibrationScore` сегодня именно так и делает — и возвращает выдуманную оценку |
| **Случайная выборка вопросов бенчмарка** | Невоспроизводимо ⇒ нельзя сравнить методики между раундами. Только детерминированная стратификация |
| **Сразу публиковаться на лидерборде ForecastBench** | Требует ≥95% покрытия, регистрации через `register.forecastbench.org` (GCP-бакет) и знания формулы difficulty-adjusted index (у нас её нет). Сначала внутренний контур |
| **Удалять устаревшие строки (`DELETE`)** | `[IRREVERSIBLE_NO_GRANT]` — и правильно: автомат состояний (`expired`/`superseded`) делает удаление ненужным |
| **Переезд на Prisma/Postgres** | Задание: SQLite. `schema-v4.1.prisma` — исторический артефакт, а не цель |
| **Переписать ОСП целиком** | 36 рабочих шаблонов, гейт #469, живой поиск, рынки, 17 команд — переписывание ломает ограничение 8 и теряет месяцы |
| **`Fluid` как тип вероятности** | `fluid` только на верхнем уровне, в теле шаблона `[UNDEFINED_VARIABLE]`, персистентности нет. Уверенность — полями (заявка C.2) |
| **Абсолютная цель «Brier ≤ 0.25»** | Выполняется константой 0.5. Цель — skill score против трёх линий |
| **Реконструкция difficulty-adjusted index по догадке** | Формула должна браться из кода скоринга бенчмарка; иначе цифра несопоставима (допущение A.4) |

### 11.2 Компромиссы, на которые идём осознанно

| Решение | Что теряем | Почему приемлемо |
|---|---|---|
| Две таблицы (`analysis` + `osp_forecast`) вместо одной | join в отчётах, риск рассинхрона | `analysis` остаётся документом для прозы и визуализаций; карточка — числовой сущностью; связка `analysis_id`/`osp_forecast_id` + один писатель |
| Шесть новых таблиц | больше схемы | три из них (`osp_bench_*`) — внешний контур, удаляется целиком; критерий «15 таблиц» не нарушен |
| Ансамбль из 5 прогонов | ×5 токенов и латентность | 86% победителей турниров — ансамбль со средним; на дешёвых семействах это 0.0018 USD; есть потолок и деградация до одного прогона |
| Среднее как основной агрегатор | медиана устойчивее к выбросам | медиана и logit-pool **сохраняются в строке** — ежемесячный обзор честно сравнивает агрегаторы на нашем архиве, и переключение — одна константа |
| Отложенная выборка = хвост архива по времени | меньше данных на обучение | исключает утечку «подсмотрел ответ»; случайное разбиение на временных рядах оптимистично смещает оценку |
| `kind='bench'` в той же таблице | риск смешения контуров | все метрики с фильтром по `kind` + тест «контуры не смешиваются»; одна схема вместо двух |
| Исход подтверждает человек (owner-контур) | скорость, человеческий фактор | иначе «модель судит свой прогноз» — конфликт интересов; в bench-контуре исход берётся из `resolution_set` автоматически |
| `db_insert` помечен experimental | предупреждения в `check`, риск изменения API | альтернатива — литеральный `INSERT` в `db_execute`; оставляем `db_insert` там, где он уже в проде, и фиксируем в заявках (C.6) |
| Отказ от `cron_run` в 0.38 | меньше «родного» планирования | `cron_run` требует мандат человека; существующие `/cron/*`-маршруты с `SecretMatches` уже работают |

---

## Приложение A. Допущения, которые я не смог проверить

| № | Допущение | Как проверить | Что ломается, если неверно |
|---|---|---|---|
| A.1 | Снимок `skills-snapshot-2026-10-05` (24 скилла, 349 761 символ) побайтно равен тому, что разворачивает `scripts/bootstrap_skills.sh` в контейнере | `md5sum skills/*/SKILL.md` в живом контейнере против манифеста | цифры §7.5 (15 640 против 12 000) сдвинутся, но характер бага (проверка **до** добавления) не изменится |
| A.2 | `bin/mlog 0.34.1` из репозитория идентичен бинарнику прода | `mlog --version` + `sha256sum` в контейнере | выводы о поведении 0.34.1 могут отличаться; 0.38.0 проверен официальным релизом (SHA256 `da714fd5…`) |
| A.3 | Ночной слот под вахту свободен и `dept/schedules.mlog` допускает добавление задания без `cron_run` | чтение реестра слотов + `proxy/routes_sched.py` в проде; реестр по умолчанию выключен | волну 3 придётся вешать на существующий `/cron/*`-маршрут вручную (это и есть план Б) |
| A.4 | Формула difficulty-adjusted Brier Index | код скоринга ForecastBench / wiki «How to submit» | наши цифры несопоставимы с лидербордом; на внутренние отчёты не влияет |
| A.5 | Каденция раундов (раз в 2 недели) и имена файлов сохранятся | мониторинг `datasets/question_sets/` (43 набора на 02.11.2026) | `OSPBenchSetUrl` потребует правки; URLs вынесены в один шаблон |
| A.6 | 900 токенов на вход и 150 на выход достаточно для одного bench-прогона; 1.47 MB JSON разбирается в памяти ВМ | `token_count` на реальном payload + замер времени `parse_json` | стоимость раунда вырастет (линейно), возможен таймаут разбора ⇒ переход на `http_download` + построчный разбор |
| A.7 | Порог `p_spread ≤ 0.25` (G3) и выигрыш Platt ≥0.005 разумны | после набора n≥100: распределение разброса и фактический выигрыш | пороги — константы в одном месте (`OSPCardGates`, `OSPAdoptGain`), правятся одним нарядом |
| A.8 | Базовые частоты по темам на старте пусты (`prior_n = 0`) | `SELECT COUNT(*) FROM osp_base_rates` после волны 1 | при n=0 вес априорного 0 ⇒ сжатия нет (это корректное поведение, не баг) |
| A.9 | Рыночные цены (Kalshi/Polymarket) доступны существующим `OSPMarketDataBlock` без новых ключей | живой прогон `/osp deep` по вопросу с рыночным аналогом | `crowd_p = -1` ⇒ skill против толпы не считается, G6/W3 молчат |
| A.10 | В проде используется `mlogserver`-маршруты, а не `mlog run`; значит `flow` в проде может не исполняться вовсе | `entrypoint.sh` + процесс-лист контейнера | поэтому **вся** логика — в шаблонах, `flow` остаётся необязательной обёрткой |

## Приложение B. Вопросы владельцу (не больше пяти) — с рекомендациями

**B.1. Признаём ли ForecastBench официальным тренировочным потоком ОСП?**
*Рекомендация: да.* Это единственный проверенный легальный источник с готовыми
исходами и короткими горизонтами; без него критерий «≥50 разрешённых за 2 месяца»
не выполняется (арифметика в §1.4). Metaculus — только через ForecastBench
(42 вопроса в раунде) и только после письменного разрешения, если когда-нибудь
понадобится прямой API.

**B.2. Публикуем ли мы прогнозы на лидерборд ForecastBench (и кого просим
посмотреть лицензию)?**
*Рекомендация: первые 3 месяца — нет, только внутренний контур.* Публикация требует
≥95% покрытия, регистрации через `register.forecastbench.org` и сопоставимой формулы
индекса (A.4). Лицензия CC BY-SA 4.0: внутреннее использование покрывается атрибуцией;
ShareAlike включится, только если мы **републикуем** производный набор (наши прогнозы
как датасет) — это стоит показать юристу до публикации, не до разработки.

**B.3. Какой потолок бюджета ставим в `daily_budget_osp`?**
*Рекомендация: 1.00 USD/день.* Покрывает раунд бенчмарка (0.25 USD) и 30 прогнозов
владельца с полным ансамблем (~0.05 USD каждый) с трёхкратным запасом; ниже 0.30
придётся резать покрытие, а пропуск стоит дороже прогона (§6.5). Ключ уже читает
прокси (`proxy/budget.py:99`), менять инфраструктуру не нужно.

**B.4. Кто подтверждает исход в контуре владельца — человек или модель?**
*Рекомендация: человек (одно касание в Telegram), модель — только готовит вопрос.*
Иначе отдел сам себе выставляет оценки, и Brier теряет смысл. Для bench-контура
подтверждение автоматическое — из `resolution_set`. Компромисс по скорости:
карточка уходит в `expired` через 30 дней без подтверждения, **громко**
(строка в утреннем отчёте), а не тихо.

**B.5. Меняем ли цели «Brier ≤ 0.25 / 0.20 / 0.18» на skill score?**
*Рекомендация: да.* Год 1: `skill vs 0.25 ≥ +0.10` при n≥50 **и** `Brier ≤ Brier
толпы/рынка` на тех же вопросах; год 2: `skill ≥ +0.15` и `Brier ≤ Brier
суперпрогнозистов ForecastBench` (их прогнозы лежат в том же репозитории). Абсолютный
порог 0.25 выполняется константой и не защищает от регрессии (тест в примере 3).

## Приложение C. Заявки в Metalogos

| № | Заявка | Зачем ОСП | Обход сегодня |
|---|---|---|---|
| C.1 | `brier` и `log_loss` в `METRIC_REGISTRY` (`mutate`) | калибровка стала бы «обучением» на опоре Learn, а не самодельным градиентным спуском | `OSPPlattFit` на `while` + `ln/exp/sigmoid` (пример 3) |
| C.2 | Персистентный `Fluid` внутри тел шаблонов (ADR-0006) | «вероятность, которая знает свою калибровку» — буквально опора Fluid | `fluid` только на верхнем уровне; уверенность — полями `p_final/p_spread/n_runs/cal_bucket` |
| C.3 | `call_llm_schema(prompt, input, schema, model)` | ансамблю нужны **разные семейства** и структурный ответ одновременно | `call_llm(prompt,input,model)` + `json_validate` вручную (пример 2) |
| C.4 | `rule`, читающий строки БД и исполняющийся в `test` | переходы статусов стали бы декларативными и проверяемыми | переходы — шаблонами + `osp_forecast_events` (пример 4) |
| C.5 | Лексикографическое сравнение строк (или `str_cmp`) | ISO-даты сравниваются в языке, а не только в SQL | `date_parse_iso` → epoch; внутри SQL — строковое сравнение |
| C.6 | Снять `experimental` с `db_insert` или дать стабильный аналог | единственные предупреждения `check` в наших примерах — про него | `INSERT` литералом в `db_execute` там, где нужен `ON CONFLICT` |
| C.7 | Правка ADR-0060 («VM: no-op» для schema) и docs | таблица устарела: `schema`-блок на VM **применяется** (`vm.rs:357/365`), проверено исполнением | ссылаемся на исполнение, а не на ADR |

## Приложение D. Как воспроизвести проверку

```sh
# 1. Рантаймы
work/office/bin/mlog --version      # mlog 0.34.1  (прод офиса)
work/mlog-038 --version             # mlog 0.38.0  (SHA256 da714fd5… — официальный релиз)

# 2. Все примеры на обоих рантаймах: check + test + run(flow)
sh deliverable/examples/run_all.sh

# 3. Состояние прод-кода сегодня
cd work/office
DATABASE_URL="sqlite::memory:" bin/mlog check app.mlog --root app.mlog   # 103 ошибки (66 — артефакт дубля), 32 предупреждения

# 4. Факты о внешнем потоке (без авторизации)
curl -sS https://raw.githubusercontent.com/forecastingresearch/forecastbench-datasets/main/datasets/question_sets/latest-llm.json | head -c 300
```

Логи всех прогонов — `deliverable/VERIFICATION.md` (108 зелёных тестов, 0 ошибок
`check`, идентичные выводы обоих рантаймов).

---

*Документ подготовлен как дизайн-предложение: код в `FOSVED-office-v2` и `Metalogos-`
не изменялся. Все утверждения о коде получены чтением файлов и `grep`, все утверждения
о языке — исполнением на двух рантаймах. Прогнозы и метрики ОСП не являются
инвестиционной рекомендацией (существующий фильтр сохраняется).*
