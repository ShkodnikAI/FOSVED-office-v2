---
name: dispute-resolution-strategy
description: Стратегия в случае возникшего спора — оценка перспектив, выбор пути (переговоры/медиация/арбитраж/суд), формирование позиции. Применяется когда спор уже возник.
tier: 3
---

# Dispute Resolution Strategy — не «как выиграть суд», а «какой суд вообще стоит вести»

Спор возник — эмоция (обиду, злость) нужно отделить от экономики. Суд — это **инвестиция с uncertain return**. Legal fees, time, distraction от бизнеса, reputation risk — всё это costs. Единственный вопрос, который определяет стратегию: **NPV (net present value) каждой опции**. Переговоры могут дать 0.60 на каждый вложенный 1.00 (settlement = 60% claim). Суд может дать 1.50 на каждый вложенный 1.00 (judgment + costs) — но с 40% вероятностью 0 (proceedings lost) = expected value 0.60. Математически — одинаково. Но суд занимает 18 месяцев, а переговоры — 2 недели.

## Prerequisites

- Спор уже возник (факт нарушения, disagreement, claim)
- Контрагент известен, позиция контрагента понятна (или можно оценить)
- Сумма спора определена (порядок)
- Договор и все коммуникации доступны
- Юрисдикция и применимое право известны

## Core principle

> **Стратегия разрешения спора определяется не правотой, а economics.** Правота — necessary condition (нет правоты = нет basis для claim), но не sufficient. Решение «идти в суд» должно проходить тот же investment analysis что и любой бизнес-проект: costs vs expected returns, timeline, probability, opportunity cost. Если expected return от settlement выше чем от court (с учётом probability и costs) — settlement = rational choice, не слабость.

**Инверсия интуиции:** лучший исход спора — тот, который **не доходит до суда**. Каждый час, который owner тратит на суд — это час не потраченный на бизнес. Legal fees 15 000 EUR для спора на 50 000 EUR = 30% cost. Если можно settle на 35 000 EUR за 2 недели — owner получает 35 000 EUR за 2 недели vs (potentially) 50 000 EUR за 18 месяцев minus 15 000 EUR legal = 35 000 EUR за 18 месяцев. Settlement: 35 000 EUR now. Court: 35 000 EUR in 18 months (expected). Present value 35 000 EUR now > 35 000 EUR in 18 months. Settlement wins.

## The procedure

### Step 1 — Фактическая база спора

Зафиксировать без эмоций:

```
Что произошло:
  Дата: <date>
  Факт: <description>
  Нарушенный пункт договора: § <X.X>
  Our position: <description>
  Counterparty position: <description>

Сумма спора:
  Our claim: <amount> <currency>
  Counterparty counterclaim (if any): <amount> <currency>
  Net exposure: <amount>

Доказательная база:
  Сильные: <list>
  Слабые: <list>
  Отсутствующие: <list>
```

### Step 2 — Оценка перспектив по каждой опции

**Четыре опции, по порядку escalating:**

**Option 1 — Do nothing (walk away).**
```
Cost: 0
Return: 0
Timeline: 0
Probability: 100% (certain)
Expected value: 0
When appropriate: сумма спора < legal fees для любого other option, или reputation risk от спора > potential recovery
```

**Option 2 — Negotiation / Settlement.**
```
Cost: 0-2 000 EUR (lawyer time for letter)
Return: 30-80% of claim (typical settlement range)
Timeline: 2-8 weeks
Probability of success: depends on counterparty's incentive to settle
Expected value: claim × settlement% × P(success) − cost
```

**Typical settlement ranges:**
- If our case strong: 60-80% of claim
- If our case moderate: 40-60% of claim
- If our case weak: 20-40% (settlement to avoid risk for both sides)

**Option 3 — Mediation.**
```
Cost: 3 000-10 000 EUR (mediator fees + preparation)
Return: similar to negotiation but with neutral facilitator
Timeline: 4-12 weeks
Probability of agreement: 60-80% (higher than pure negotiation)
When: both sides want to settle but cannot agree on number; relationship matters
```

**Option 4 — Arbitration / Court.**
```
Cost: 10 000-100 000+ EUR (depends on forum, amount, duration)
Return: 0-100% of claim (if win) + potentially legal costs recovery
Timeline: 12-36 months
Probability: depends on case strength, jurisdiction, enforcement
Expected value: claim × P(win) × P(enforcement) + costs_recovery × P(win) − total_legal_costs
```

### Step 3 — Посчитать NPV каждой опции

**Формула для court/arbitration:**
```
NPV_court = (Claim × P_win × P_enforce − Legal_costs × (1 − P_cost_recovery × P_win)) / (1 + r)^t
```
Где:
- Claim = сумма claim
- P_win = вероятность выигрыша (assessment)
- P_enforce = вероятность enforcement (если foreign jurisdiction)
- Legal_costs = estimated total legal fees
- P_cost_recovery = вероятность взыскания legal costs с проигравшей стороны (varies by jurisdiction: BY 50-100%, DE typically 100% for winner, US each side bears own)
- r = discount rate (monthly, ~0.5-1% for business)
- t = expected duration in months

**Формула для settlement:**
```
NPV_settlement = Settlement_amount / (1 + r)^t_settlement
```
Где t_settlement = 0-2 месяца (almost immediate)

**Пример расчёта:**

Claim: 50 000 EUR. Legal costs (court DE): 20 000 EUR. Duration: 18 месяцев. P_win: 65%. P_enforce: 80% (BY → DE enforcement). P_cost_recovery: 70%. Discount rate: 0.5%/month.

```
NPV_court = (50 000 × 0.65 × 0.80 − 20 000 × (1 − 0.70 × 0.65)) / (1.005)^18
          = (26 000 − 20 000 × 0.545) / 1.094
          = (26 000 − 10 900) / 1.094
          = 15 100 / 1.094
          = 13 800 EUR

Settlement at 60%: 30 000 EUR, 2 weeks
NPV_settlement = 30 000 / (1.005)^0.5 = 29 925 EUR

Settlement at 40%: 20 000 EUR, 2 weeks
NPV_settlement = 20 000 / (1.005)^0.5 = 19 950 EUR
```

**Вывод:** settlement at 60% (30 000 EUR) >> court (13 800 EUR expected). Even settlement at 40% (19 950 EUR) > court (13 800 EUR). Rational choice: negotiate settlement, target 50-60%.

### Step 4 — Reputation и relationship assessment

Числа — не всё. Дополнительные факторы:

| Фактор | Вопрос | Impact |
|---|---|---|
| Ongoing relationship | Будем ли работать с этим контрагентом? | Если да — court = relationship killer, settlement preferred |
| Public exposure | Будет ли суд публичным? | Court records are public in most jurisdictions |
| Deterrence | Нужно ли показать другим контрагентам, что мы sue? | Sometimes yes — but reputation for litigiousness can also deter good partners |
| Resource drain | Кто будет управлять процессом? | Owner time = opportunity cost. If owner distracted — settlement premium justified |
| Precedent effect | Создаст ли решение прецедент? | Relevant if same issue may recur with other parties |

### Step 5 — Формирование позиции и letter

**Pre-negotiation letter (если выбрана Option 2):**

```
Structure:
1. Fact statement (neutral, dates + references)
2. Our position (what was breached, reference to contract clause)
3. Our ask (specific amount or action)
4. Timeline for response (14-21 business days)
5. Consequence if no response («reserved right to pursue legal remedies»)
```

**Tone:** firm, not aggressive. Цель — дать контрагенту **возможность урегулировать** (face-saving), не запугать. Агрессивный tone → контрагент уходит в defence, не в negotiation.

### Step 6 — Сохранить через `saveResult()`

```javascript
const dept = require('../../../lib/legal');
await dept.saveResult({
  shortTitle: `Dispute strategy: <counterparty> — <topic>`,
  fullResult: formatDisputeStrategy(options, npv, recommendation),
  jurisdiction: jurisdiction,
  businessForm: businessForm,
  confidence: 'medium',
  verificationDate: today + 30, // check: did counterparty respond?
});
```

### Step 7 — Ответить владельцу

```
═══════════════════════════════════════════
DISPUTE RESOLUTION STRATEGY
═══════════════════════════════════════════

Counterparty: <name>
Amount in dispute: <X> <currency>
Date: <date>

─── FACTS ───
<neutral summary>

─── OPTIONS ANALYSIS ───
| Option | Cost (EUR) | Expected return | Timeline | NPV |
|--------|-----------|-----------------|----------|-----|
| Walk away | 0 | 0 | 0 | 0 |
| Negotiation | ~1 000 | 20 000-30 000 | 2-8 weeks | 25 000 |
| Mediation | ~5 000 | 20 000-30 000 | 4-12 weeks | 22 000 |
| Court | ~20 000 | 0-50 000 | 18 months | 13 800 |

─── RECOMMENDATION ───
<Negotiation / Settlement / ...>
Target: <X% of claim>
Rationale: <NPV comparison + qualitative factors>

─── DRAFT LETTER ───
<if negotiation recommended>

─── NON-FINANCIAL FACTORS ───
<relationship, reputation, resource drain>

⚠ DISPUTE STRATEGY — requires licensed lawyer for execution.
📎 В архиве: <archive_link>
```

## Worked example

**Ситуация:** DE GmbH не оплатила milestone M2 (24 000 EUR) по MSA. Причина: «quality не соответствует AC». BY ООО считает, что AC выполнены (acceptance testing пройдено, act signed by their PM). Срок просрочки: 45 дней.

**Оценка:**

**Факты:**
- Act of acceptance signed by DE GmbH PM 15.05.2026
- Payment due: 15.06.2026 (30 days per contract § 4.2)
- DE GmbH: «our internal review found issues» — but contract says acceptance = act signed by PM
- Counterparty has assets in DE

**Options NPV:**

| Option | Cost | Expected return | NPV |
|---|---|---|---|
| Walk away | 0 | 0 | 0 |
| Negotiation | 1 000 EUR | 18 000-22 000 EUR (75-90% — our case strong: signed acceptance) | ~19 000 EUR |
| Court DE | 15 000 EUR (DE legal fees) | 24 000 × 0.80 (strong case) × 0.85 (enforcement) = 16 320, minus costs (15 000 × 0.30 unrecovered) = 11 820, discounted 18 months = ~10 800 EUR | ~10 800 EUR |

**Recommendation:** Negotiation. Target: 20 000-22 000 EUR (83-92%). Rationale: signed acceptance is strong evidence, DE GmbH likely using dispute as cash flow management (common pattern). Settlement = faster and higher NPV.

**Draft letter position:**
1. Fact: acceptance signed 15.05, payment due 15.06
2. Position: § 4.2 MSA — payment due within 30 days of acceptance. § 6 — acceptance = act signed by PM. Internal review is not contractual mechanism.
3. Ask: 22 000 EUR (slightly below full amount, giving face-saving discount)
4. Timeline: 14 business days
5. Consequence: ICC arbitration per § 11 MSA

## Anti-patterns

- **«Они неправы — идём в суд».** Эмоциональное решение без NPV analysis. Суд может стоить больше чем recovery. **Countermeasure:** всегда считать NPV всех четырёх options перед принятием решения.

- **Суд без оценки enforcement.** «Мы выиграем в BY суде». Контрагент — DE GmbH с assets в DE. BY court judgment → enforce в DE via Минская конвенция = 6-18 месяцев, uncertain. **Countermeasure:** enforcement assessment — обязательный шаг до решения «суд».

- **Settlement как поражение.** «Мы не будем уступать — принцип!» Принцип стоит 0 EUR в бизнесе. **Countermeasure:** settlement — это rational investment decision. Если NPV settlement > NPV court — settlement = win.

- **Игнорировать counterclaim.** «Они нам должны 24 000». Но контрагент может заявить counterclaim на 30 000 (quality defects, delay damages). Net exposure: -6 000 EUR. **Countermeasure:** всегда оценивать counterparty's potential counterclaim в NPV analysis.

- **Выбирать forum без cost assessment.** ICC arbitration «потому что в договоре так». ICC для 24 000 EUR dispute = costs may exceed 50% of claim. **Countermeasure:** для сумм < 50 000 EUR рассматривать negotiated settlement или small claims court (если доступен).

## Output template

```
═══════════════════════════════════════════
DISPUTE RESOLUTION STRATEGY
═══════════════════════════════════════════

Counterparty: <name>
Dispute: <one-line description>
Amount: <X> <currency>
Date: <date>

─── FACTUAL BASE ───
<neutral, dated, referenced>

─── EVIDENCE ASSESSMENT ───
Strong: <list>
Weak: <list>
Missing: <list>

─── OPTIONS NPV ANALYSIS ───
| Option | Cost | Expected return | NPV | P(win) | Timeline |
|--------|------|-----------------|-----|--------|----------|
| Walk away | 0 | 0 | 0 | — | 0 |
| Negotiation | X | X-X | X | — | X weeks |
| Mediation | X | X-X | X | — | X weeks |
| Court/Arbitration | X | X-X | X | X% | X months |

─── RECOMMENDATION ───
<primary option> — <rationale>
Target: <if negotiation/settlement>

─── NON-FINANCIAL FACTORS ───
<relationship / reputation / deterrence / resource drain>

─── DRAFT POSITION / LETTER ───
<if applicable>

─── NEXT STEPS ───
1. <action> — <owner / lawyer>
2. <action> — <timeline>

⚠ DISPUTE STRATEGY — requires licensed lawyer for execution.
📎 В архиве: <archive_link>
```

## When NOT to use this skill

- Когда спор **ещё не возник** — это `risk-mapping-protocol` (preventive) или `contract-drafting-discipline` (preventive)
- Когда нужна **оценка перспектив конкретного иска** — `precedent-search-application` (judicial practice)
- Когда вопрос про **cross-jurisdiction choice** (до спора) — `cross-jurisdiction-comparison`

## Integration with Legal

Tier 3 — загружается только когда спор **уже возник**. Это самый expensive skill (по business cost), и по этой причине — Tier 3, не применяется preventively.

Использует:
- `risk-mapping-protocol` — карта рисков сделки (если есть) как контекст для оценки claim strength
- `contract-drafting-discipline` — interpretation of disputed clauses
- `cross-jurisdiction-comparison` — если спор cross-border
- `precedent-search-application` — для оценки P(win) в court option