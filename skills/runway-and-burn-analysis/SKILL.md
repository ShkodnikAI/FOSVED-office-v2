---
name: runway-and-burn-analysis
description: Calculate runway, burn rate, breakeven point. Use when cash is tight, before fundraising, or for strategic planning of cost cuts.
tier: 3
---

# Runway and Burn Analysis — сколько месяцев до нуля

Runway — это не «сколько денег осталось, делённое на расходы». Это **динамический прогноз**, потому что burn rate меняется каждый месяц (новые наймы, сезонные расходы, переменные косты). Статический runway («у нас 8 месяцев») — это мнение. Этот скилл делает runway в связке с `cashflow-forecasting`, который уже считает еженедельный closing balance.

## Prerequisites

- Актуальный cashflow forecast (от `cashflow-forecasting`) на ≥3 месяца
- Или: текущий cash balance + список обязательных расходов (fixed + variable)
- Юрисдикция определена (от этого зависят налоги как обязательные outflows)
- Цель анализа: runway до X, или «сколько runway при текущем burn», или breakeven при росте

## Core principle

> **Runway — это количество месяцев до cash = 0 при условии, что NOTHING changes: ни один клиент не уйдёт, ни один новый не придёт, расходы не сократятся.** Реальный runway всегда больше расчётного, потому что что-то изменится. Но планировать нужно по пессимистичному сценарию (no new revenue), а оптимистичный — для morale, не для решений.

**Инверсия интуиции:** сокращение расходов удваивает runway только если burn rate линейный. Если основная часть burn — зарплаты (fixed), то увольнение 1 из 5 сотрудников сокращает burn на 20%, но runway растёт на 25% (потому что 20% экономии → 20/80 = 25% длиннее). Но если уволить последнего non-essential — эффект ещё сильнее, потому что пропорционально больше от remaining burn. Математика runway нелинейна.

## The procedure

### Step 1 — Получить текущий cash position

Точный cash balance (не «приблизительно»):
- Остатки на всех расчётных счетах
- Минус незавершённые платежи (queued)
- Плюс ожидаемые поступления в ближайшие 7 дней (confirmed)

Если нет актуального cashflow forecast — текущий cash из банка/счёта.

### Step 2 — Разделить расходы на fixed и variable

**Fixed (ежемесячные, не зависят от выручки):**
- Зарплаты (net + gross + social)
- Аренда
- Подписки SaaS, cloud, infrastructure
- Страховки
- Кредитные платежи

**Variable (зависят от объёма):**
- Маркетинг
- Переменная часть cloud (usage-based)
- Командировки
- Contract work / freelancers

**Semi-fixed (ежемесячные, но можно сократить с notice period):**
- Contractors (с notice 1 месяц)
- Office (с notice 2-3 месяца)
- SaaS subscriptions (можно отменить в конце billing cycle)

**Полная классификация нужна для Step 4 (сценарии сокращения).**

### Step 3 — Рассчитать burn rate

```
Gross burn = все расходы за месяц (fixed + variable)
Net burn = gross burn - revenue за месяц
```

**Для runway используется net burn** (если есть recurring revenue). Если revenue = 0 (pre-revenue) — net burn = gross burn.

**Monthly burn rate** — среднее за последние 3 месяца (не один месяц, один месяц может быть аномальным из-за разовых расходов).

### Step 4 — Рассчитать runway по трём сценариям

**Scenario A — Status quo (no changes):**
```
runway_months = current_cash / avg_monthly_net_burn
```

Если net burn отрицательный (прибыль) — runway = ∞ (cash растёт).

**Scenario B — Optimistic (existing revenue continues, some new revenue):**
```
runway = current_cash / (avg_monthly_net_burn × 0.85)
```
85% = предполагаемое снижение net burn на 15% за счёт нового revenue. Коэффициент подбирается по pipeline.

**Scenario C — Pessimistic (no new revenue, variable costs cut to zero):**
```
runway = current_cash / fixed_burn_only
```
Это «сколько мы продержимся если перестанём тратить на всё кроме обязательного». Минимальный runway — максимально информативный.

### Step 5 — Breakeven analysis (если запрошен)

Breakeven — revenue при котором net burn = 0:

```
breakeven_monthly_revenue = gross_burn
breakeven_customers = gross_burn / ARPU
```

Если ARPU = $79/mo, gross burn = $15 000/mo:
- Breakeven: 15 000 / 79 = **190 клиентов**

**Breakeven runway:** сколько месяцев до breakeven при текущем growth rate:
```
months_to_breakeven = log(breakeven_mrr / current_mrr) / log(1 + monthly_growth_rate)
```

Если current MRR = $5 000, breakeven = $15 000, growth = 8%/mo:
```
months = log(15 000 / 5 000) / log(1.08) = log(3) / log(1.08) = 1.099 / 0.077 = 14.3 months
```

**Требуемый runway:** 14.3 months + safety buffer (3 months) = **17.3 months**. Если текущий runway < 17.3 — нужно или ускорить growth, или сократить burn, или привлечь funding.

### Step 6 — Сценарии сокращения burn

Если runway < target — построить таблицу:

| Действие | Экономия/мес | Notice period | New burn | New runway |
|---|---|---|---|---|
| Cut marketing 50% | $2 000 | Immediately | $13 000 | X months |
| Cancel contractor A | $3 000 | 1 month | $10 000 | Y months |
| Downgrade office | $1 500 | 3 months | $8 500 | Z months |
| All above | $6 500 | 3 months | $8 500 | Z months |

**Правило:** всегда показывать notice period. «Сократить аренду» нельзя завтра — нужен notice. Реальный эффект отсрочен.

### Step 7 — Сохранить через `saveResult()`

```js
await finance.saveResult({
  shortTitle: `Runway analysis (${jurisdiction}/${businessForm})`,
  fullResult: formatRunwayReport(scenarios),
  confidence: 'high',
  verificationDate: today + 30, // проверять: изменился ли burn
  jurisdiction,
  businessForm,
});
```

### Step 8 — Ответить владельцу

Тон — прямой, без утешений. «At current burn rate you have X months of runway. This is [below/above] the Y-month threshold needed for [breakeven/fundraising].»

## Worked example

**Запрос владельца:** «Сколько runway у нас осталось?»

**Контекст:**
- BY ООО
- Cash: 92 000 BYN (на всех счетах, BYN + USD × 3.20)
- Месячные расходы (последние 3 месяца, среднее):
  - Зарплаты (6 чел): 15 000 BYN net + 4 200 ФСЗН = 19 200
  - Аренда: 3 500
  - Cloud: 2 720 (850 USD)
  - Маркетинг: 3 000
  - Прочие: 1 500
  - **Gross burn: 29 920 BYN/mo**
- Revenue: subscription MRR $2 000 = 6 400 BYN/mo (2 клиента annual, 4 monthly)
- **Net burn: 29 920 - 6 400 = 23 520 BYN/mo**

**Расчёт:**

**Scenario A (status quo):**
- Runway = 92 000 / 23 520 = **3.9 месяцев** (конец сентября — начало октября)

**Scenario C (pessimistic, no revenue):**
- Fixed burn = 19 200 + 3 500 + 2 720 + 1 500 = 26 920
- Runway = 92 000 / 26 920 = **3.4 месяца**

**Breakeven:**
- Breakeven revenue = gross burn = 29 920 BYN/mo = ~$9 350/mo = ~118 клиентов на плане $79
- Current MRR: $2 000
- At 8% monthly growth: months to breakeven = log(9 350/2 000) / log(1.08) = 1.548/0.077 = **20 months**
- Required runway: 20 + 3 = **23 months**
- Gap: 23 - 3.9 = **19 months** shortfall

**Сценарии сокращения:**

| Действие | Экономия | Notice | New burn | New runway |
|---|---|---|---|---|
| Marketing → 0 | 3 000 | Сразу | 26 920 | 3.4 mo |
| + Cancel 1 contractor | 2 500 | 1 mo | 24 420 | 3.8 mo |
| + Downgrade office | 1 200 | 3 mo | 23 220 | 4.0 mo |

**Вывод для владельца:** при текущем burn runway 3.9 месяцев, breakeven при 8% growth — через 20 месяцев. Gap критический. Даже с полным сокращением дискреционных расходов runway < 5 месяцев. Опции: (1) ускорить revenue growth до 20%+/mo (тогда breakeven за 9 месяцев при runway 4 — не хватает), (2) привлечь funding, (3) сократить зарплатный фонд (снижение headcount).

## Anti-patterns

- **Runway без сценарного анализа.** «У нас 6 месяцев runway» — а если уйдёт крупнейший клиент? А если cloud cost удвоится? Одно число без сценариев — бесполезно для решений. **Countermeasure:** минимум три сценария (status quo / optimistic / pessimistic), как в cashflow-forecasting.

- **Считать gross burn как runway divisor.** Если есть recurring revenue — runway считается по **net burn** (gross - revenue). Считать по gross — систематически занижать runway. **Countermeasure:** runway = cash / net_burn; если revenue = 0 — тогда net = gross.

- **Забывать налоги в burn rate.** «Зарплаты 15 000, аренда 3 500, cloud 2 720 — burn 21 220». ФСЗН (28%) на зарплаты = 4 200. Налог на прибыль если есть прибыль = ещё. Налоги — часть burn. **Countermeasure:** burn rate включает все обязательные outflows, включая налоги и соц. взносы.

- **Breakeven без учёта growth rate.** «Нам нужно 190 клиентов для breakeven». Ок, а за сколько месяцев мы наберём 190? Без growth rate — это не plan, это wish. **Countermeasure:** breakeven runway = months to breakeven at current growth, с формулой логарифмического расчёта.

- **Runway как мотивация.** «У нас 4 месяца — надо быстрее работать». Это эмоция, не анализ. Четыре месяца — это число, из которого следуют конкретные действия (сократить burn или привлечь деньги). **Countermeasure:** runway → decision tree, не чувство срочности.

- **Игнорировать notice periods при планировании сокращения.** «Сократим аренду — сэкономим 3 500». Но договор аренды — notice 3 месяца. Реальная экономия начнётся через 3 месяца. **Countermeasure:** каждый cost cut с notice period, реальный runway учитывает задержку.

## Output template

```
═══════════════════════════════════════════
RUNWAY ANALYSIS — <Jurisdiction> <BusinessForm>
═══════════════════════════════════════════

Cash position: <X> <currency> (<date>)
Gross burn: <X> <currency>/mo (3-month avg)
Revenue: <X> <currency>/mo (MRR)
Net burn: <X> <currency>/mo

─── RUNWAY SCENARIOS ───
Status quo (current net burn):  <X> months (until <date>)
Optimistic (85% net burn):      <X> months (until <date>)
Pessimistic (fixed burn only):  <X> months (until <date>)

─── BURN BREAKDOWN ───
Fixed:    <X> (<items>)
Variable: <X> (<items>)
Total:    <X>

─── BREAKEVEN ───
Monthly revenue needed: <X> <currency>
Customers needed: <X> (at ARPU $<X>)
Months to breakeven (at X% growth): <X>
Required runway for breakeven: <X> months
Gap: <X> months [ABOVE/BELOW THRESHOLD]

─── COST CUT SCENARIOS ───
| Action | Savings | Notice | New burn | New runway |
|--------|---------|--------|----------|------------|
| ...    | ...     | ...    | ...      | ...        |

─── RECOMMENDATION ───
<specific actionable recommendation>

Verification date: <YYYY-MM-DD>
Confidence: <level>

📎 В архиве: <archive_link>
```

## When NOT to use this skill

- Когда бизнес стабильно прибыльный (net burn < 0) — runway = ∞, анализ не нужен
- Когда нужен **детальный cashflow прогноз** — это `cashflow-forecasting` (runway использует его данные, но не заменяет)
- Когда нужен **unit economics** — это `unit-economics-calculation`

## Integration with finance

Tier 3, загружается по явному запросу (runway, burn, breakeven, «сколько нас хватит»).

Использует данные из:
- `cashflow-forecasting` — прогноз closing balance как более точный runway
- `db.invoice` — revenue данные для net burn
- `mrr-arr-reporting` — MRR как revenue source
- `library/knowledge/finance/jurisdictions/<JX>.md` — налоги в burn
- `library/knowledge/finance/business-forms/<FORM>.md` — соц. обязательства

Метрика отдела: `runway-months` — runway в месяцах. Target: ≥6 months всегда. Red flag: < 3 months.