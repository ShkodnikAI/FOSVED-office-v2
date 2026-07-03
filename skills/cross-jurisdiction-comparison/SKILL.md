---
name: cross-jurisdiction-comparison
description: Сравнение норм 2+ юрисдикций для одной сделки. Применяется при сделках где стороны из разных стран или предмет затрагивает несколько правовых систем.
tier: 1
---

# Cross-Jurisdiction Comparison — не «какой закон лучше», а «где наша слабая точка»

Когда стороны из разных стран — каждая хочет apply своё право. Но «выбрать лучшую юрисдикцию» — не значит «выбрать ту где законы благоприятнее». Это значит «выбрать ту, где суд будет рассматривать дело, и наш contractual position максимально защищена этим судом». Закон, который благоприятен на бумаге, бесполезен если вы не можете enforce его в суде другой страны (enforcement of foreign judgments — отдельная проблема, часто решающая).

## Prerequisites

- Юрисдикции всех сторон известны
- Тип сделки определён
- Предмет сравнения конкретен (IP transfer, dispute resolution, tax, data protection, limitation periods)
- Применён `risk-mapping-protocol` (cross-jurisdiction = всегда regulatory risk)

## Core principle

> **Выбор applicable law определяет не «кто прав», а «по каким правилам суд решит кто прав».** К同一ое contractual term может быть valid в BY и void в EU. Penalty clause 0.5%/день в BY — valid (в пределах cap), в DE — potentially abusive (§ 307 BGB: «unreasonable disadvantage»), в UK — depends on reasonableness. Вы не выбираете «добро» или «зло» — вы выбираете **predictability** в суде, который реально будет рассматривать спор.

**Инверсия интуиции:** нейтральная юрисдикция (e.g., «шведское право») не нейтральна. Шведский суд будет применять шведские нормы, которые вы (и, возможно, контрагент) не знаете. Это — risk, не safety. «Нейтральная» = «обе стороны equally uninformed». Лучше выбрать юрисдикцию одной из сторон — хотя бы одна сторона знает terrain.

## The procedure

### Step 1 — Зафиксировать параметры сравнения

Для каждой юрисдикции в сделке:

```
Юрисдикция: BY / RU / EU (member state) / US (state)
Тип сделки: <MSA / NDA / SLA / service contract>
Предмет сравнения: <что конкретно сравниваем>
Позиция владельца: <кто наша сторона>
```

### Step 2 — Сравнить по конкретному вопросу (comparison matrix)

Структура сравнения — не абстрактный «обзор», а **конкретный вопрос**. Примеры вопросов:

**Пример 1: IP assignment в IT-контракте**

| Параметр | BY (ГК) | DE (UrhG) | US (Copyright Act) |
|---|---|---|---|
| Default owner (contractor work) | Заказчик (ст. 708 ГК) | Подрядчик (§ 43 UrhG) | Подрядчик (§ 201(b)) |
| Explicit assignment needed? | Рекомендуется | Обязательно | Обязательно |
| Moral rights | Ст. 146 ГК (личные неимущественные) | § 29 UrhG (неотчуждаемые) | § 106 (waivable) |
| Work-for-hire for employees? | Да (ст. 708) | Да (§ 43) | Да (§ 201(a)) |
| AI-generated work | Silent | § 2 UrhG (personal creation only) | Not copyrightable (USCO guidance) |

**Вывод:** если контрагент в DE или US — без explicit IP assignment clause заказчик **не владеет** кодом. Если в BY — default в пользу заказчика, но explicit clause recommended для clarity.

**Пример 2: Dispute resolution enforcement**

| Параметр | BY | RU | DE | US (NY) |
|---|---|---|---|---|
| Recognition of foreign judgments | Минская конвенция, Hague | Минская конвенция | Brussels I (EU), Lugano | Условный reciprocity |
| Enforcement of BY judgment in EU | Возможна (длительная, ~1-2 года) | Сложно (санкции) | Brussels I regime | Possible, complex |
| Enforcement of DE judgment in BY | Via Минская конвенция | Нет | — | Possible |
| Arbitration enforcement | NYC 1958 (BY ратифицировал) | NYC 1958 (ratified) | NYC 1958 | FAA + NYC |
| Typical duration (court) | 6-18 месяцев | 6-24 месяца | 12-24 месяца | 12-36 месяцев |

**Вывод:** если стороны BY + EU — arbitration (ICC/SCC) с seat в Stockholm = enforceable в обеих юрисдикциях под NYC. Court judgment BY → enforceable в EU, но медленно. Court judgment DE → enforceable в BY via Минская конвенция.

**Пример 3: Data transfer (GDPR relevance)**

| Параметр | BY | EU | US |
|---|---|---|---|
| GDPR applicable? | Нет (BY не EEA) | Да | Нет (но DPF для transfers from EU) |
| Transfer EU→BY | Requires SCC (no adequacy) | — | — |
| Transfer BY→EU | BY law: notification required | — | — |
| Transfer EU→US | Via DPF (self-certified) or SCC | — | — |
| Penalties for non-compliance | BY: 1-5 БВ (34-170 BYN) | EU: up to 4% global turnover | US: FTC action (varies) |

### Step 3 — Оценить enforceability

Самый важный и недооценённый вопрос. Contract может быть perfect по applicable law — но если суд другой юрисдикции не будет его enforce, это бумага.

**Enforcement цепочка:**
1. Суд в юрисдикции A выносит решение
2. Ответчик не исполняет добровольно
3. Истец подаёт на enforcement в юрисдикции B (где assets ответчика)
4. Суд юрисдикции B проверяет: (a) есть ли договор об enforcement (Минская конвенция, Brussels I, NYC), (b) не противоречит ли public policy

**Практические scenarios:**

| Стороны | Оптимальный dispute mechanism | Почему |
|---|---|---|
| BY ↔ EU | ICC arbitration, seat Stockholm, applicable law BY or EU | NYC enforcement в обеих, нейтральный |
| BY ↔ RU | Минская конвенция (court) или arbitration | Минская конвенция cover обе, но RU sanctions risk |
| BY ↔ US | SCC arbitration (Stockholm) | NYC + DPF considerations |
| EU ↔ US | ICC arbitration, seat EU | NYC enforcement, EU consumer protection |

### Step 4 — Recommendation с explicit trade-offs

Для каждого варианта — не «лучший», а **«лучший при условии X»**:

```
Option A: Applicable law BY, court BY
  Pro: мы знаем terrain, low legal costs
  Contra: контрагент может не признать, enforcement в EU долго
  Best when: наша сторона сильнее, контрагент имеет assets в BY

Option B: Applicable law DE, ICC arbitration Stockholm
  Pro: enforceable under NYC, neutral, DE law is well-developed
  Contra: arbitration costs (ICC: ~15 000-50 000 EUR for mid-size dispute)
  Best when: balanced parties, significant amount, need enforceability

Option C: Applicable law BY, arbitration Minsk
  Pro: lowest cost
  Contra: BY arbitration enforceability in EU = questionable
  Best when: small amounts, both parties in BY/RU
```

### Step 5 — Сохранить через `saveResult()`

```javascript
const dept = require('../../../lib/legal');
await dept.saveResult({
  shortTitle: `Cross-JX comparison: <topic> (${jx1} vs ${jx2})`,
  fullResult: formatComparison(matrix, enforceability, recommendation),
  jurisdiction: jurisdiction,
  businessForm: businessForm,
  confidence: 'medium',
  verificationDate: today + 180, // cross-jurisdiction = long-term
});
```

### Step 6 — Ответить владельцу

```
═══════════════════════════════════════════
CROSS-JURISDICTION COMPARISON
═══════════════════════════════════════════

Topic: <IP transfer / dispute resolution / data transfer / ...>
Jurisdictions: <JX1> vs <JX2>
Deal context: <type, amount, parties>

─── COMPARISON MATRIX ───
| Parameter | <JX1> | <JX2> | Difference |
|-----------|-------|-------|------------|
| ... | ... | ... | ... |

─── ENFORCEABILITY ASSESSMENT ───
<JX1> → <JX2>: <mechanism, duration, risk>
<JX2> → <JX1>: <mechanism, duration, risk>

─── RECOMMENDATION ───
Primary: <option with rationale>
Fallback: <if primary not accepted by counterparty>

⚠ LEGAL ANALYSIS — requires licensed lawyer for final decision.
📎 В архиве: <archive_link>
```

## Worked example

**Запрос:** «Мы (BY ООО) подписываем MSA с DE GmbH. Сумма 80 000 EUR. Что с IP и dispute resolution?»

**Comparison matrix: IP ownership**

| Параметр | BY (ГК) | DE (UrhG/BGB) |
|---|---|---|
| Default IP owner | Заказчик (ст. 708) | Подрядчик (§ 43 UrhG) |
| Explicit assignment | Recommended | Required |
| Moral rights | Limited (waivable) | § 29 — inalienable |
| AI-generated | Silent | Not personal creation (§ 2) |
| Pre-existing IP carve-out | Implicit (ст. 985) | Must be explicit |

**Key difference:** DE default = contractor owns. Without explicit IP assignment in the contract — DE GmbH **не получает** ownership of the code. BY ООО loses nothing, but DE GmbH loses the IP they paid for.

**Recommendation:** explicit IP assignment clause (DE-compliant) — see `ip-clause-discipline` for template.

**Comparison matrix: Dispute resolution**

| Параметр | BY court | DE court | ICC Stockholm |
|---|---|---|---|
| Applicable law | BY (близко к нам) | DE (familiar to counterparty) | Either (by agreement) |
| Duration | 6-18 мес | 12-24 мес | 12-18 мес |
| Cost | Низкий (court fees ~100-500 EUR) | Средний (~500-2000 EUR) | Высокий (~15 000-50 000 EUR) |
| Enforcement in other JX | Минская конвенция | Brussels I (EU) | NYC (international) |
| Language | BY/RU | DE/EN | EN (default) |

**Trade-off:** court BY — cheapest but DE GmbH unlikely to accept (home court advantage for BY). Court DE — balanced but our team less familiar. ICC Stockholm — expensive but both parties equally uncomfortable (neutral).

**Recommendation:** for 80 000 EUR — ICC Stockholm is proportional (costs ~5-8% of dispute amount). For < 30 000 EUR — recommend court with minority protection (e.g., court in DE with BY applicable law).

## Anti-patterns

- **«Выбираем английское право — оно универсальное».** English law не универсальное — это право Англии и Уэльса. It is well-developed for commercial contracts, но enforcement в BY или RU может быть проблематичным (no bilateral enforcement treaty UK-BY post-Brexit). **Countermeasure:** выбирать право одной из сторон (или нейтральное с enforcement treaty coverage).

- **Сравнение по абстрактным «уровням защиты».** «EU имеет сильнее IP protection чем BY». Это true в общем, но irrelevant для конкретного контракта. Вопрос не «где защита сильнее», а «где наш конкретный clause будет enforce». **Countermeasure:** сравнение всегда по конкретному contractual question, не по «уровню защиты».

- **Игнорировать enforcement при выборе юрисдикции.** «DE law, суд DE» — отлично, DE law protects our position. Но если контрагент в BY и assets в BY — DE court judgment будет enforce в BY через Минскую конвенцию (6-18 месяцев, uncertain outcome). **Countermeasure:** всегда включать enforceability assessment в comparison.

- **«Нейтральный арбитраж» без понимания cost.** ICC arbitration для спора 20 000 EUR = disproportionate (арбитражные издержки могут превысить сумму спора). **Countermeasure:** cost-benefit: если сумма спора < 50 000 EUR — рассмотреть court с оговоркой о применимом праве. Если > 100 000 EUR — arbitration оправдан.

- **Забыть Rome I / Rome II Regulation.** В EU — choice of law governed by Rome I Regulation (contracts). Ограничения: consumer contracts — choice cannot deprive consumer of mandatory protection. Employment contracts — employee protection cannot be waived. **Countermeasure:** если хотя бы одна сторона — EU consumer — Rome I Art. 6 ограничивает freedom of choice.

## Output template

```
═══════════════════════════════════════════
CROSS-JURISDICTION COMPARISON
═══════════════════════════════════════════

Topic: <specific question>
Jurisdictions: <JX1> / <JX2> [/ <JX3>]
Deal: <type, amount, parties>
Date: <date>

─── COMPARISON MATRIX ───
| Parameter | <JX1> | <JX2> | Key difference |
|-----------|-------|-------|----------------|
| ... | ... | ... | ... |

─── ENFORCEMENT ASSESSMENT ───
| Direction | Mechanism | Duration | Risk |
|-----------|-----------|----------|------|
| <JX1> → <JX2> | <treaty/court/arbitration> | <months> | <L/M/H> |
| <JX2> → <JX1> | ... | ... | ... |

─── RECOMMENDATIONS ───
Option A: <description>
  Pros: ...
  Cons: ...
  Best when: ...
Option B: <description>
  ...

─── TRADE-OFFS ───
<explicit: what we gain, what we lose with each option>

⚠ LEGAL ANALYSIS — requires licensed lawyer for final decision.
📎 В архиве: <archive_link>
```

## When NOT to use this skill

- Когда обе стороны из одной юрисдикции — нет cross-jurisdiction issue
- Когда вопрос про **конкретный draft clause** — это `contract-drafting-discipline`
- Когда нужен **consumer protection check** — это `consumer-protection-check`
- Когда нужен **IP clause** — это `ip-clause-discipline` (cross-jurisdiction comparison может быть input для него, но IP clause — выходной документ)

## Integration with Legal

Tier 1, загружается при multi-jurisdiction контексте (стороны из разных стран, enforcement вопрос, choice of law discussion).

Использует:
- `risk-mapping-protocol` — cross-jurisdiction risks
- `contract-drafting-discipline` — drafting jurisdiction clause
- `ip-clause-discipline` — cross-border IP (work-for-hire differences)
- `dispute-resolution-strategy` — если спор уже возник, cross-jurisdiction = input для стратегии
- `library/knowledge/legal/jurisdictions/<JX>.md` — specifics каждой юрисдикции