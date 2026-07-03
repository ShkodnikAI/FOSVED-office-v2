---
name: forecast-verification-protocol
description: Compare past forecast against actual reality, calculate MAPE per period, identify systematic forecasting errors. Use at verification date of any forecast.
tier: 1
---

# Forecast Verification Protocol — проверка прогнозов постфактум

Каждый прогноз, который создаёт Finance, имеет `verificationDate`. Когда эта дата наступает — прогноз **обязан быть проверен**. Без проверки прогнозы остаются мнениями, а отдел не учится. Verification — это не «подтверждение что мы были правы», а механизм выявления систематических ошибок (bias), чтобы следующий прогноз был точнее.

## Prerequisites

- Прогноз с `verificationDate` существует в БД (`db.financialForecast`)
- Фактические данные за прогнозный период доступны (банковские выписки, accounting records)
- Юрисдикция и бизнес-форма известны (для корректной классификации отклонений)
- Оригинальный прогноз **не изменён** с момента публикации (см. hard rule #4: не пересчитывать задним числом)

## Core principle

> **Прогноз, который не проверен, — не прогноз, а надежда.** Но проверка имеет контринтуитивное правило: цель verification — не доказать точность, а **найти bias**. MAPE 2% означает не «мы отлично прогнозируем», а «мы не знаем, где именно ошибаемся, потому что 2% может складываться из +15% на одной категории и -13% на другой». Маленький MAPE при маленьком business — статистически meaningless.

**Инверсия интуиции:** если verification показывает, что прогноз «попал» — это **наименее полезный результат**. «Попадание» не говорит, был ли прогноз хорошим или повезло. Самый ценный результат verification — обнаружение систематического bias: «мы систематически переоцениваем inflows на 18% для клиентов с invoice age >30 дней» — это конкретный, исправимый вывод. Идеальный verification — тот, который меняет модель следующего прогноза.

## The procedure

### Step 1 — Извлечь оригинальный прогноз

Из БД: `db.financialForecast` по `verificationDate`.

Критически важно: берётся **оригинальный** прогноз (как был опубликован), не обновлённый. Если прогноз обновлялся после публикации — в БД должно быть versioning. Verification всегда сравнивает с **первой опубликованной версией**.

Если прогноз был `superseded` (заменён более новым на тот же период) — verification сравнивает с **superseded** версией (первой), а superseding версия — отдельный прогноз со своим verification date.

### Step 2 — Собрать фактические данные

Для каждого элемента прогноза — фактическое значение:

| Элемент прогноза | Фактический источник |
|---|---|
| Inflow по каждому инвойсу | Банковская выписка: дата зачисления, сумма |
| Inflow по подпискам | Stripe/Paddle reports: actual collected |
| Outflow по зарплате | Банковская выписка: дата списания, сумма |
| Outflow по налогам | Налоговая квитанция: дата, сумма |
| Outflow по аренде | Банковская выписка |
| Outflow по cloud/SaaS | Billing statements |
| Closing balance | Банковская выписка на последний день периода |

**Правило:** фактические данные берутся в той же валюте, что и прогноз. Если прогноз был в BYN (конвертированный из USD по курсу на дату прогноза) — фактическое значение USD-платежа конвертируется по курсу на дату прогноза, не на дату факта. Это проверяет точность самого прогноза, не курсовую разницу (курсовая разница — domain `multi-currency-handling`).

### Step 3 — Рассчитать отклонения по категориям

Для каждой строки прогноза:

```
Отклонение (абсолютное) = Факт - Прогноз
Отклонение (%) = (Факт - Прогноз) / |Прогноз| × 100
```

Группировать по категориям:
- **Inflows:** по источнику (invoices, subscriptions, other)
- **Outflows:** по категории (salary, tax, rent, cloud, other)
- **Timing:** по неделям/месяцам (попал в правильную неделю или нет)

**Timing deviation — отдельный и важный параметр.** Прогноз: «25 000 USD поступит в W4». Факт: 25 000 USD поступили в W5. Sum deviation = 0%, timing deviation = 1 week. Для cashflow timing deviation **важнее** sum deviation — поздний платёж создаёт cash gap, которого не было бы при точном timing.

### Step 4 — Рассчитать MAPE

**MAPE (Mean Absolute Percentage Error):**

```
MAPE = (1/n) × Σ |Факт_i - Прогноз_i| / |Прогноз_i| × 100
```

Три уровня MAPE:

| MAPE | Оценка | Действие |
|---|---|---|
| ≤ 5% | Отлично | Зафиксировать, continue |
| 5-10% | Приемлемо | Investigate категории с наибольшим отклонением |
| 10-20% | Плохо | Обязательный анализ bias, корректировка модели |
| > 20% | Провал | Root cause analysis, пересмотр методологии прогнозирования |

**MAPE для closing balance** — основной показатель. Также считать MAPE по подгруппам (inflows-only, outflows-only) для выявления, какая сторона хуже прогнозируется.

**Специфично для малых business:** если месячный оборот < 50 000 BYN и прогноз был на 30 дней — MAPE < 5% может быть случайным (один крупный платёж смещает всё). В таких случаях дополнительно считать **WAPE (Weighted Absolute Percentage Error)** — взвешенный по абсолютной величине, чтобы большие суммы имели больший вес.

### Step 5 — Найти систематический bias

Bias — это не «ошибка в одном прогнозе». Bias — это **однонаправленная ошибка в нескольких прогнозах**.

Проверить по истории (последние 3-6 прогнозов):

| Тип bias | Как обнаружить | Типичная причина |
|---|---|---|
| Optimistic inflows | Inflow MAPE систематически отрицательный (факт < прогноз) | Слишком высокие collection coefficients для overdue invoices |
| Pessimistic outflows | Outflow MAPE систематически положительный (факт < прогноз) | Забыты налоговые льготы, or overstated estimates |
| Timing lag | Платежи систематически на 1-2 недели позже прогноза | Исторический lag недооценён |
| Category miss | Одна категория (e.g., cloud) всегда ошибается | Нет actual data для этой категории, используется «прикидка» |
| Seasonal blindspot | Прогнозы в определённые месяцы систематически хуже | Сезонность не учтена (налоги, каникулы, Q4 spike) |

**Для каждого обнаруженного bias — конкретная корректировка в следующем прогнозе.** Это записывается в metadata прогноза как «lessons learned from verification #N».

### Step 6 — Обновить запись прогноза в БД

```js
await finance.saveResult({
  shortTitle: `Verification: ${forecast.shortTitle}`,
  fullResult: formatVerification(verificationData),
  confidence: 'high', // verification — точная операция
  verificationDate: null, // verification itself doesn't need re-verification
  forecastId: forecast.id, // link to original forecast
  mape: calculatedMAPE,
  biasFound: biasList,
  modelAdjustments: adjustmentsList,
  jurisdiction,
  businessForm,
});
```

Статус оригинального прогноза обновляется: `drafted` → `verified` (или `missed` / `partial` по критериям из профиля).

### Step 7 — Ответить владельцу

Формат — сухой, числовой:

```
📊 Verification: Cashflow 30d (01.06 → 01.07)

MAPE: 7.3% (приемлемо)
Closing: прогноз 145 200 BYN, факт 138 400 BYN (−4.7%)

По категориям:
  Inflows MAPE: 9.1% — хуже
  Outflows MAPE: 4.2% — хорошо

Главное отклонение:
  Invoice #INV-2026-042 (25 000 USD): прогноз W4, факт W5+2d → timing lag 9 дней
  Причина: клиент запросил extension платежа на 7 дней

Bias обнаружен: inflows для invoice age >30 дней — систематически позднее на 5-9 дней
Корректировка: в следующем прогнозе для age >30d добавлять +7 дней к ожидаемой дате

Verification #7 за 2026 год
```

## Worked example

**Прогноз:** Cashflow 30d, BY ООО, 01.06.2026 → 01.07.2026. Оригинальный прогноз опубликован 01.06.2026.

**Оригинальный прогноз (из архива):**

| Неделя | Inflows (прогноз) | Outflows (прогноз) | Closing (прогноз) |
|---|---|---|---|
| Opening | — | — | 71 000 BYN |
| W1 | 29 420 BYN | 6 220 BYN | 94 200 BYN |
| W2 | 14 600 BYN | 0 BYN | 108 800 BYN |
| W3 | 3 200 BYN | 19 200 BYN | 92 800 BYN |
| W4 | 59 200 BYN | 6 800 BYN | 145 200 BYN |

**Фактические данные (банковская выписка 01.07.2026):**

| Неделя | Inflows (факт) | Outflows (факт) | Closing (факт) |
|---|---|---|---|
| Opening | — | — | 71 000 BYN |
| W1 | 26 220 BYN (8 000 EUR × 3.45, курс NBRB 01.06 = 3.27, difference: 8 000 × 0.18 = 1 440 BYN) | 6 220 BYN | 91 000 BYN |
| W2 | 11 400 BYN (12 000 BYN × 0.95) | 0 BYN | 102 400 BYN |
| W3 | 3 200 BYN | 19 200 BYN | 86 400 BYN |
| W4 | 56 000 BYN (25 000 USD × 0.70 × 3.20; факт: поступил 09.07, за пределами периода → 0 BYN в W4) | 6 800 BYN | 79 600 BYN |

**Примечание:** 25 000 USD поступили 09.07 — за пределами 30-дневного прогнозного периода. В прогнозе применялся collection coefficient 70% с ожиданием в W4. По факту — delay 9 дней beyond period.

**Расчёт MAPE:**

По closing balance:
```
|79 600 − 145 200| / |145 200| × 100 = 65 600 / 145 200 × 100 = 45.2%
```

**Это BAD (>20%).** Root cause: один крупный платёж задержался за пределы периода.

**MAPE без outlier (исключив delayed invoice):**

Если бы 25 000 USD × 0.70 × 3.20 = 56 000 BYN поступили в W4 как прогнозировалось:
Closing = 79 600 + 56 000 = 135 600 BYN
MAPE = |135 600 − 145 200| / 145 200 × 100 = 6.6% (приемлемо)

**Вывод:** MAPE closing = 45.2%, но driver — один outlier. MAPE excluding outlier = 6.6%. Это указывает не на систематическую ошибку модели, а на single-event timing miss.

**MAPE по категориям (ex-outlier):**
- Inflows (ex INV-042): |(26 220 + 11 400 + 3 200) − (29 420 + 14 600 + 3 200)| / (29 420 + 14 600 + 3 200) = |40 820 − 47 220| / 47 220 = 6 400 / 47 220 = 13.6%
- Outflows: |(6 220 + 0 + 19 200 + 6 800) − (6 220 + 0 + 19 200 + 6 800)| / (6 220 + 0 + 19 200 + 6 800) = 0 / 32 220 = 0%

**Inflow MAPE 13.6% (плохо), Outflow MAPE 0% (отлично).**

**Bias discovered:**
1. **EUR conversion:** прогноз использовал курс 3.45 (NBRB spot), фактическое зачисление — по курсу банка-корреспондента 3.27. Loss 1 440 BYN. **Correction:** использовать банковский курс (NBRB − 0.5-1%) для конвертации в BYN при прогнозе, не официальный NBRB.
2. **Invoice INV-042 timing:** клиент (25 000 USD) платит систематически на 7-14 дней позже ожидаемого (не первый раз). **Correction:** для этого клиента collection coefficient timing += 10 дней.

## Anti-patterns

- **Verification без оригинального прогноза.** «Мы помним, что прогнозировали примерно 140 000». Память искажает в пользу «мы были правы». **Countermeasure:** всегда извлекать оригинальный прогноз из БД/архива, не полагаться на воспоминание.

- **MAPE closing без разбивки по категориям.** «MAPE 4.2% — отлично». Но inflows MAPE = 15% и outflows = -7% — они компенсируют друг друга. Cashflow может быть точным случайно. **Countermeasure:** всегда считать MAPE отдельно для inflows, outflows, и по ключевым подкатегориям.

- **Переписывание прогноза перед verification.** «Ну мы же знали, что клиент задержит — давайте обновим прогноз». Это уничтожает verification. **Countermeasure:** hard rule #4 — оригинальный прогноз неизменяем. Если нужна корректировка — создаётся новый прогноз с новым verification date, старый остаётся для проверки.

- **Игнорирование timing deviation.** «Сумма совпала, closing почти точный». Но если деньги пришли на 2 недели позже — это cash gap, который прогноз не предсказал. **Countermeasure:** timing deviation отдельной строкой в verification, с порогом > 5 дней как trigger для модели.

- **Aggregating MAPE across different forecast types.** «Средний MAPE за квартал: 6%». Но это среднее из 30-day (MAPE 4%), 60-day (MAPE 8%), 90-day (MAPE 12%). 90-day MAPE 12% может быть проблемой. **Countermeasure:** MAPE по горизонту прогноза отдельно, не усреднять.

## Output template

```
═══════════════════════════════════════════
FORECAST VERIFICATION
═══════════════════════════════════════════

Forecast: <shortTitle>
Period: <start> → <end>
Date: <verification date>

─── SUMMARY ───
MAPE (closing): <X>%
MAPE (inflows): <X>%
MAPE (outflows): <X>%
Status: OK / PARTIAL / MISSED

─── ACTUAL vs FORECAST ───
| Item | Forecast | Actual | Dev | Dev% |
|------|----------|--------|-----|------|
| Closing | X | X | X | X% |
| ... | ... | ... | ... | ... |

─── TIMING DEVIATIONS ───
| Item | Forecast date | Actual date | Lag |
|------|---------------|-------------|-----|
| ... | ... | ... | X days |

─── BIAS ANALYSIS ───
[Found / Not found]
If found:
  Bias type: <optimistic inflows / timing lag / ...>
  Evidence: <last N forecasts showing same pattern>
  Correction for next forecast: <specific adjustment>

─── MODEL ADJUSTMENTS ───
1. <adjustment> — <rationale>
2. ...

Verification #<N> for <year>
📎 В архиве: <archive_link>
```

## When NOT to use this skill

- Когда прогноз **ещё не достиг** verification date — рано
- Когда нужен **новый прогноз** — это `cashflow-forecasting` (verification — входные данные для него)
- Когда нужно **верифицировать unit economics** (CAC/LTV) — это другой тип verification, процедура в `unit-economics-calculation`
- Когда нужно **верифицировать MRR** — `mrr-arr-reporting` (верификация churn/renewal predictions)

## Integration with finance

Tier 1 — загружается **всегда** при обращении к Finance. Verification — замыкающий шаг цикла прогнозирования: forecast → publish → wait → verify → learn → forecast (better).

Использует данные из:
- `db.financialForecast` — оригинальный прогноз + предыдущие verification records (для bias detection)
- `db.invoice` — фактические статусы и даты оплат
- Банковские выписки — фактические cash in/out

Метрика отдела: `mape-cashflow` рассчитывается через этот скилл. Target: 30d ≤ 5%, 60d ≤ 10%, 90d ≤ 15%.