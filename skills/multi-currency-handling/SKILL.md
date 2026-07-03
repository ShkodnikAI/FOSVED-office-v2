---
name: multi-currency-handling
description: Convert between currencies using historical rates, manage exchange rate risk, hedging basics. Use when transactions span multiple currencies.
tier: 2
---

# Multi-Currency Handling — мультивалюта как риск, не как конвертация

Бизнес, который получает оплату в USD/EUR и платит зарплату в BYN, аренду в BYN, cloud в USD — это **не «бизнес в нескольких валютах»**, это бизнес, у которого каждый месяц часть выручки проходит через currency conversion с непредсказуемым результатом. Курсовая разница — не комиссия банка (ту можно посчитать), а unplanned gain/loss между датой выставления инвойса и датой получения денег.

## Prerequisites

- Юрисдикция определена (определяет, какой rate — официальный или банковский — применяется по закону)
- Список валют, в которых бизнес получает/платит, известен
- Текущие остатки по счетам в каждой валюте
- Knowledge-файл юрисдикции подгружен (содержит правила валютных операций)

## Core principle

> **Курс на день прогноза и курс на день фактической операции — это два разных числа.** Разница между ними — это не «ошибка прогноза», а currency risk, и он должен быть посчитан отдельно, не замешан в MAPE cashflow forecast. Конвертация для налоговых целей — по официальному курсу (NBRB/ЦБ); конвертация для cashflow — по банковскому курсу (который всегда хуже).

**Инверсия интуиции:** бизнес в BY, получающий 100% выручки в USD и платящий 100% расходов в BYN, не имеет «валютного риска» только если курс стационарен. Курс не стационарен. За 2024 USD/BYN колебался от 3.10 до 3.35 — диапазон 8%. На обороте 100 000 USD/год это 25 000 BYN unplanned variance. «Мы работаем в USD» не означает «мы защищены от валютного риска» — это означает «весь валютный риск концентрируется в одной паре».

## The procedure

### Step 1 — Картировать валютные потоки

Для каждого регулярного платежа (in и out):

| Поток | Валюта | Периодичность | Сумма | Counterparty |
|---|---|---|---|---|
| Subscription revenue | USD | Monthly | ~4 000 USD | Stripe |
| Client invoices | EUR | Per project | 8 000-50 000 EUR | EU clients |
| Salary | BYN | Monthly | 15 000 BYN | Employees |
| ФСЗН | BYN | Monthly | 4 200 BYN | Tax authority |
| Rent | BYN | Monthly | 3 500 BYN | Landlord |
| Cloud (AWS/Stripe fees) | USD | Monthly | 850 USD | AWS |
| SaaS subscriptions | USD | Monthly | 200 USD | Various |

**Natural hedge check:** если inflows в USD и outflows в USD — эта часть self-hedged. Проблема только в «перетоке» между валютами (USD → BYN для зарплат и налогов).

### Step 2 — ОпределитьExposed position

**Net currency exposure** по каждой валюте за месяц:

```
Exposed (валюта X) = Sum(inflows в X) − Sum(outflows в X)
```

Если positive — у вас избыток валюты X (нужно конвертировать в другую для расходов). Если negative — дефицит (нужно купить).

**Пример:**
```
USD: inflows 4 000 (subs) + 0 (cloud — это outflow) = net outflows 1 050 USD
     Но subs 4 000 — это gross inflows. Net: 4 000 − 1 050 = +2 950 USD/мес
     Нужно конвертировать ~2 950 USD → BYN для зарплат и налогов

EUR: inflows 8 000 (invoice) − 0 = +8 000 EUR/мес (когда есть invoices)
     Converting to BYN

BYN: inflows 0 − outflows 22 700 (salary 15 000 + ФСЗН 4 200 + rent 3 500) = −22 700 BYN/мес
     Fully funded by conversion from USD/EUR
```

**Exposed amount:** ~22 700 BYN/мес = ~7 100 USD/мес (at 3.20). Это сумма, подверженная currency risk каждый месяц.

### Step 3 — Рассчитать курсовую разницу для налогов и учёта

**Налоговый учёт — официальный курс.** В BY — NBRB на дату операции. В RU — ЦБ РФ. В EU — ECB. В US — неактуально (USD = functional currency).

**Два типа курсовой разницы:**

1. **Transaction exchange difference** — между датой выставления инвойса и датой получения оплаты.

```
Инвойс: 10 000 EUR, выставлен 01.06, курс NBRB 01.06 = 3.45 → 34 500 BYN
Оплата: 10 000 EUR, получена 15.07, курс NBRB 15.07 = 3.50 → 35 000 BYN
Курсовая разница: 35 000 − 34 500 = +500 BYN (gain)
```

Для BY ООО: курсовая разница — прочие доходы/расходы (не операционные), облагаются налогом на прибыль.

2. **Balance sheet revaluation** — на отчётную дату пересчитываются остатки в foreign currency.

```
Остаток на счёте: 25 000 USD, 30.06
Курс NBRB 30.06 = 3.25 → 81 250 BYN
Курс NBRB 31.05 (предыдущий month-end) = 3.20 → 80 000 BYN
Курсовая разница: 81 250 − 80 000 = +1 250 BYN (unrealized gain)
```

**Для cashflow forecast:** использовать **банковский курс** (NBRB − spread), не официальный. Банк покупает USD по NBRB − 0.02-0.05, продаёт по NBRB + 0.02-0.05. Spread = 0.04-0.10 BYN на 1 USD. На 10 000 USD это 400-1 000 BYN «невидимой» потери.

### Step 4 — Оценить risk для прогнозного периода

**Для cashflow forecast — консервативная оценка:**

```
Консервативный курс для outflows (покупка BYN за USD):
  = NBRB today + 0.05 (пессимистичный, assuming BYN weakens)

Консервативный курс для inflows (продажа USD/EUR за BYN):
  = NBRB today − 0.05 (пессимистичный для нас)
```

**Для бюджета на квартал — sensitivity analysis:**

| Сценарий | USD/BYN | EUR/BYN | Impact на monthly cash (BYN) |
|---|---|---|---|
| Оптимистичный | 3.10 | 3.30 | +4 200 |
| Базовый | 3.20 | 3.45 | 0 |
| Пессимистичный | 3.35 | 3.60 | −4 800 |

Impact рассчитывается: `exposed_amount × (scenario_rate − base_rate)`. Если exposed = 7 100 USD, base = 3.20, pessimistic = 3.35: 7 100 × 0.15 = 1 065 BYN/мес. На квартал: 3 195 BYN.

### Step 5 — Хеджирование (базовое)

Для малого бизнеса full hedging (forwards, options) — overkill. Практические меры:

**1. Currency buffer (резерв).** Profile рекомендует 10-15% от месячного оборота. Для exposed 7 100 USD/мес — держать 700-1 050 USD дополнительного резерва. При укреплении BYN — этот резерв покрывает разницу.

**2. Natual hedging через timing.** Если нужно платить зарплату 15-го в BYN, а USD поступление ожидается 20-го — конвертировать часть остатка заранее (10-го), не ждать 20-го. Риск: если курс улучшится 15-го — вы «потеряли». Но это не потеря, это цена предсказуемости.

**3. Currency diversification клиентов.** Если 100% revenue в USD — весь risk на одной паре. Если 60% USD + 40% EUR — корреляция USD/EUR к BYN не идентична, variance снижается.

**4. Fix-price контракты в валюте клиента.** Не пересчитывать USD-контракт в BYN для клиента — billed in USD, paid in USD. Client не заботится о вашем currency risk, и пересчёт создаёт double-risk (вы принимаете price risk и currency risk).

**Что НЕ делать:**
- Forward contracts для сумм < 50 000 USD — комиссия съест benefit
- Crypto hedging — volatility BTC/EUR выше чем EUR/BYN
- «Подождём пока курс улучшится» — это не стратегия, это hope

### Step 6 — Сохранить через `saveResult()`

```js
await finance.saveResult({
  shortTitle: `Currency exposure: ${jurisdiction}/${businessForm}`,
  fullResult: formatCurrencyReport(exposureMap, sensitivity, hedgingPlan),
  confidence: 'medium',
  verificationDate: today + 30, // курс меняется — re-check monthly
  jurisdiction,
  businessForm,
});
```

### Step 7 — Ответить владельцу

```
📊 Currency Exposure — ООО BY

Exposed monthly: ~22 700 BYN (~7 100 USD equivalent)
Sources: 2 950 USD subs + variable EUR invoices → BYN for salaries/taxes

Current rates (NBRB):
  USD/BYN: 3.20 (bank sell: 3.25, bank buy: 3.15)
  EUR/BYN: 3.45 (bank sell: 3.50, bank buy: 3.40)

Sensitivity (monthly):
  Optimistic (BYN strengthens): +4 200 BYN
  Base: 0
  Pessimistic (BYN weakens −5%): −4 800 BYN

Hedging status: currency buffer 800 USD (11% of exposed) — adequate
Recommendation: none

Verification date: <today+30>
```

## Worked example

**Контекст:** BY ООО, receives revenue in USD (Stripe subscriptions) and EUR (project invoices), pays all expenses in BYN.

**Month:** July 2026.

**Flows:**

| Flow | Currency | Amount | Direction |
|---|---|---|---|
| Stripe subscriptions | USD | 4 000 | Inflow |
| Client invoice (GmbH) | EUR | 12 000 | Inflow |
| Salary (6 employees) | BYN | 15 000 | Outflow |
| ФСЗН | BYN | 4 200 | Outflow |
| Rent | BYN | 3 500 | Outflow |
| AWS + SaaS | USD | 1 050 | Outflow |
| Tax payment (VAT) | BYN | 6 800 | Outflow |

**Step 1 — Exposure:**
```
USD net: +4 000 − 1 050 = +2 950 USD (to convert to BYN)
EUR net: +12 000 − 0 = +12 000 EUR (to convert to BYN)
BYN net: 0 − 29 500 = −29 500 BYN (needed)
```

**Step 2 — Conversion at bank rates (NBRB 01.07: USD 3.20, EUR 3.45):**
```
2 950 USD × 3.15 (bank buy) = 9 292.50 BYN
12 000 EUR × 3.40 (bank buy) = 40 800 BYN
Total BYN from conversion: 50 092.50 BYN
Needed: 29 500 BYN
Surplus: 20 592.50 BYN → stays in USD/EUR accounts or converts to BYN reserve
```

**Step 3 — Transaction exchange difference (если EUR invoice выставлен 01.06):**
```
Invoice 12 000 EUR at NBRB 01.06 = 3.42 → 41 040 BYN
Payment 12 000 EUR at NBRB 15.07 = 3.45 → 41 400 BYN
Gain: 360 BYN (taxable as other income)
But bank rate: 3.40 (buy) → 40 800 BYN actual received
Real gain vs original estimate at bank rate (3.37 on 01.06): 12 000 × 0.03 = 360 BYN
```

**Step 4 — Sensitivity:**
```
Exposed to BYN: 29 500 BYN/month
If USD/BYN moves to 3.30 (+3.1%): impact on USD portion = 2 950 × 0.10 × (3.30−3.20) ≈ +295 BYN gain (less BYN needed per USD)
If USD/BYN moves to 3.10 (−3.1%): impact = 2 950 × 0.10 × (3.10−3.20) ≈ −295 BYN loss
EUR portion: 12 000 EUR, range 3.35-3.55 → impact ±1 200 BYN

Total range: ±1 500 BYN/month (±5% of BYN expenses)
```

**Step 5 — Hedging recommendation:** currency buffer of 1 500 USD currently held. Sufficient for ±5% monthly swing. No forward contracts needed at this scale.

## Anti-patterns

- **Конвертировать по NBRB в cashflow.** NBRB — официальный курс для налогов. Банк конвертирует по NBRB ± spread (0.02-0.10 BYN). На 10 000 USD это 200-1 000 BYN разницы. **Countermeasure:** в cashflow всегда использовать банковский курс (buy/sell в зависимости от direction), не официальный.

- **Игнорировать timing курсовой разницы.** «Мы получили 10 000 EUR — конвертируем по сегодняшнему курсу». Но инвойс был выставлен месяц назад по другому курсу. Разница — transaction exchange difference, taxable event. **Countermeasure:** для каждого cross-currency invoice отслеживать both dates и both rates.

- **Валютный буфер = 0.** «Мы конвертим по мере необходимости». Если курс резко изменится за 2-3 дня — зарплата может не поместиться в бюджет. **Countermeasure:** минимум 10% месячного exposed amount в reserve. Profile рекомендует 10-15%.

- **Forward contract на маленькие суммы.** Forward на 5 000 USD с комиссией 150 USD = 3% cost. Если курс изменится на 2% — вы заплатили за хедж больше, чем риск. **Countermeasure:** forwards только при exposed > 50 000 USD/мес или при single transaction > 100 000 USD. Для малого бизнеса — currency buffer.

- **Считать выручку в USD «надёжнее» BYN.** USD/BYN volatile. «Мы заработали 50 000 USD» — хорошо, но если курс упал на 10% с момента выставления инвойса — реальный BYN-equivalent income на 10% меньше. **Countermeasure:** always report currency exposure alongside revenue.

## Output template

```
═══════════════════════════════════════════
CURRENCY EXPOSURE REPORT
═══════════════════════════════════════════

Entity: <BusinessForm> <Jurisdiction>
Date: <date>

─── CURRENCY FLOWS (monthly) ───
| Flow | Currency | Amount | Net in currency |
|------|----------|--------|-----------------|
| ... | ... | ... | ... |

─── EXPOSURE ───
| Currency | Net position | To convert | Bank rate (buy/sell) |
|----------|-------------|------------|---------------------|
| USD | +X / -X | X USD → BYN | X.XX / X.XX |
| EUR | +X / -X | X EUR → BYN | X.XX / X.XX |

─── SENSITIVITY ───
| Scenario | USD/BYN | EUR/BYN | Monthly impact (BYN) |
|----------|---------|---------|---------------------|
| Optimistic | X.XX | X.XX | +X |
| Base | X.XX | X.XX | 0 |
| Pessimistic | X.XX | X.XX | −X |

─── HEDGING STATUS ───
Currency buffer: X <currency> (X% of monthly exposure)
Forward contracts: none / X at rate X.XX
Recommendation: <none / specific action>

─── TRANSACTION EXCHANGE DIFFERENCES (this month) ───
| Invoice | Currency | Amount | Invoice rate | Payment rate | Diff (BYN) |
|---------|----------|--------|-------------|-------------|------------|
| ... | ... | ... | ... | ... | ... |

Verification date: <YYYY-MM-DD>
Confidence: <level>

📎 В архиве: <archive_link>
```

## When NOT to use this skill

- Когда все транзакции в одной валюте — нет currency risk
- Когда нужен **налоговый расчёт** курсовой разницы (для декларации) — это работа бухгалтера, Finance готовит данные
- Когда нужен **cashflow прогноз** — это `cashflow-forecasting` (multi-currency — входные данные)
- Когда нужен **hedging strategy** для enterprise — это CFO / treasury, не Finance

## Integration with finance

Tier 2, загружается при обнаружении мультивалютных потоков в запросе (упоминание USD/EUR/RUB при BY юрисдикции, или любой не-functional currency).

Использует:
- `cashflow-forecasting` — currency exposure как input в прогноз
- `forecast-verification-protocol` — курсовая разница как компонент deviation analysis
- `library/knowledge/finance/jurisdictions/<JX>.md` — правила валютных операций юрисдикции

Метрика отдела: currency forecast accuracy = MAPE conversion rate predictions (target: ≤ 2% monthly).