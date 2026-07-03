---
name: mrr-arr-reporting
description: Calculate MRR, ARR, expansion revenue, contraction, churn for subscription products. Use for SaaS monthly reports or fundraising prep.
tier: 2
---

# MRR/ARR Reporting — подписочная выручка как система, не как одно число

MRR (Monthly Recurring Revenue) — это **не «сколько мы заработали в этом месяце»**. Это нормализованная оценка того, **сколько мы будем зарабатывать каждый месяц**, если ни один клиент не отвалится и не изменит план. Разница между «фактическое поступление» и MRR — это почему cashflow forecast и MRR report показывают разные числа.

## Prerequisites

- Доступ к данным подписок (база клиентов + планы + статусы)
- Известен расчётный месяц (отчёт всегда за конкретный месяц)
- Валюта отчёта определена (если клиенты в разных валютах — нужна единая для консолидации)

## Core principle

> **MRR — это фотография подписочной базы, замороженная на последний день месяца.** Вся хитрость — что считать за «фотографию». Клиент, который downgrade'ил план 15-го числа, в этом месяце вносит меньшую сумму — но его MRR contribution рассчитывается **по новому (ниже) плану** для всего месяца, потому что это его состояние на конец месяца. Один клиент, два числа: фактическое поступление (по старому плану за 15 дней + новому за 15 дней) ≠ MRR contribution (по новому плану × 1 месяц).

**Инверсия интуиции:** рост MRR на 10% не означает, что в следующем месяце поступит на 10% больше денег. MRR — это потенциаль, не прогноз. Клиент с годовой предоплатой вносит 12× в первый месяц и 0× в следующие 11 — MRR при этом растёт каждый месяц, потому что подсчитываются **активные подписки**, не **поступления**.

## The procedure

### Step 1 — Список всех активных подписок на последний день месяца

Для каждого клиента: план, цена, дата начала, дата конца (если есть), статус (active/churned/paused), billing cycle (monthly/annual).

**Исключить из MRR:**
- Churned клиенты (даже если churn был 30-го числа — уже не active на конец месяца)
- Paused подписки (не платят — не в MRR)
- Free tier (не приносят выручки — не в MRR)
- One-time покупки (не recurring — не в MRR)

**Включить в MRR:**
- Annual prepaid — разделить годовую сумму на 12, включать 1/12 в MRR каждого месяца
- Trials (если trial платный) — включать
- Discounts — MRR по фактической цене после скидки, не по list price

### Step 2 — Рассчитать MRR по компонентам

MRR = New MRR + Expansion MRR - Contraction MRR - Churn MRR + Reactivation MRR

| Компонент | Что считается | Пример |
|---|---|---|
| **New MRR** | MRR от клиентов, впервые платящих в этом месяце | 3 новых клиента × $50 = $150 |
| **Expansion MRR** | Увеличение MRR от существующих клиентов (upgrade плана, доп. seats, add-ons) | 2 клиента upgrade с $50→$100 = +$100 |
| **Contraction MRR** | Уменьшение MRR (downgrade плана, удаление seats) | 1 клиент downgrade $100→$50 = -$50 |
| **Churn MRR** | Потеря MRR от отвалившихся клиентов | 1 клиент ушёл с $50 = -$50 |
| **Reactivation MRR** | Возврат ранее churned клиента | 1 клиент вернулся на $50 = +$50 |

**Net New MRR** = New + Expansion - Contraction - Churn + Reactivation

**Ending MRR** = Beginning MRR + Net New MRR

### Step 3 — Рассчитать ARR

ARR = Ending MRR × 12

Это **annualized** MRR, не фактическая годовая выручка. Для annual prepaid клиентов это может сильно отличаться от факта (если все на годовом биллинге — ARR = MRR×12, но фактическое поступление в первом месяце = ARR, а в остальных = 0).

### Step 4 — Считать churn rate

Два способа — выбирать один и придерживаться:

**Customer churn rate** (по клиентам):
```
churned_customers_this_month / active_customers_beginning_of_month
```

**Revenue churn rate** (по MRR — более информативен):
```
churn_mrr / beginning_mrr
```

**Почему revenue churn ≠ customer churn:** если уходит один enterprise-клиент на $500, а приходит 10 мелких на $50 — customer churn = 1/many (низкий), revenue churn = 500/many (может быть высоким). Enterprise-отток опаснее.

**Target:** revenue churn ≤ 3% в месяц (36% годовых — уже катастрофа; ≤ 3% в месяц = ≤ 31% годовых).

### Step 5 — Проверить на аномалии

- **MRR вырос, но cash не изменился.** Обычно означает: новые клиенты на annual prepaid (деньги уже пришли, но MRR «размазан»). Нормально.
- **MRR упал, но cash вырос.** Обычно означает: многие месячные клиенты оплатили, но несколько annual prepaid не продлились. Проверить renewal rate.
- **Expansion MRR > New MRR.** Хороший знак — существующие клиенты растут. Типично для product-led growth с upsell.
- **Contraction MRR растёт.** Плохой знак — клиенты downgrad'ят. Обычно предшествует churn. Исследовать причины.

### Step 6 — Сохранить через `saveResult()`

```js
await finance.saveResult({
  shortTitle: `MRR Report ${month} ${year}`,
  fullResult: formatMRRReport(data),
  confidence: 'high', // high при полных данных, medium если часть manual
  verificationDate: lastDayOfMonth + 30, // верифицировать: были ли deferred churn/renewal
  jurisdiction,
  businessForm,
});
```

### Step 7 — Ответить владельцу

```
MRR: $X (↑/↓ $Y от прошлого месяца, Z%)
ARR: $A

New: $N | Expansion: $E | Contraction: $C | Churn: $CH | Reactivation: $R
Net New MRR: $NN

Customer churn: X% | Revenue churn: Y%
```

ЕслиAsked для fundraising — добавить:
- Net Revenue Retention (NRR)
- LTV (если есть CAC из Marketing)
- Payback period

## Worked example

**Контекст:** SaaS-продукт, 3 плана: Starter $29/mo, Pro $79/mo, Enterprise $299/mo. Отчёт за июнь 2026.

**Beginning MRR (1 июня):** $4,560 (52 активных клиента)

**Движения за июнь:**

| Событие | Клиент | План | MRR Impact |
|---|---|---|---|
| Новый клиент | Alpha Corp | Pro | +$79 |
| Новый клиент | Beta LLC | Starter | +$29 |
| Новый клиент | Gamma Inc | Enterprise | +$299 |
| Upgrade | Delta Co | Starter→Pro | +$50 |
| Upgrade | Epsilon Ltd | Pro→Enterprise | +$220 |
| Downgrade | Zeta Group | Enterprise→Pro | -$220 |
| Добавил seat | Eta Corp | Pro +1 seat ($30) | +$30 |
| Churn | Theta SA | Pro | -$79 |
| Reactivation | Iota GmbH | Starter | +$29 |

**Расчёт:**
- New MRR: 79 + 29 + 299 = **$407**
- Expansion MRR: 50 + 220 + 30 = **$300**
- Contraction MRR: **-$220**
- Churn MRR: **-$79**
- Reactivation MRR: **$29**
- Net New MRR: 407 + 300 - 220 - 79 + 29 = **$437**
- Ending MRR: 4 560 + 437 = **$4,997**
- ARR: 4 997 × 12 = **$59,964**

**Churn:**
- Customer churn: 1/52 = 1.9% (хорошо)
- Revenue churn: 79/4 560 = 1.7% (хорошо)

**Аномалия:** Contraction MRR -$220 от одного клиента (Zeta Group downgrade). Проверить: downgrade или предвестник churn? Если downgrade из-за budget — мониторить в июле.

## Anti-patterns

- **Считать MRR как «поступления за месяц».** Фактическое поступление включает one-time, prepayments, partial payments, refunds. MRR — только нормализованная recurring component. **Countermeasure:** MRR считается по активным подпискам на конец месяца, не по транзакциям.

- **Включать one-time в MRR.** Setup fee $500, migration service $1 000 — это не recurring revenue. **Countermeasure:** one-time — в P&L, не в MRR. MRR только от recurring (monthly/annual subscription).

- **Забывать annual prepaid при расчёте cash.** MRR = $5 000, но если 80% клиентов на annual prepaid — реальное поступление в первом месяце = $5 000 × 12 × 0.80 + $5 000 × 0.20 = $50 000. А в следующем месяце = $5 000 × 0.20 = $1 000. **Countermeasure:** всегда отдельно показывать split monthly/annual и cash impact.

- **Не разделять customer churn и revenue churn.** «Churn 2%» звучит отлично, пока не выяснится, что это 2% клиентов, но 15% revenue (ушёл один enterprise). **Countermeasure:** оба показателя, всегда. Revenue churn — primary для бизнеса, customer churn — для product.

- **Игнорировать contraction как «не churn».** Downgrade — это не churn (клиент остался), но это потеря revenue. Систематические downgrade'ы = клиенты не находят ценность в дорогом плане = будущий churn. **Countermeasure:** contraction rate как отдельный KPI, target ≤ 1% revenue/month. Rupture contraction → investigate.

- **ARR = MRR × 12 без дисклеймера.** Для steady-state бизнеса с monthly billing — корректно. Для бизнеса с seasonal sales или annual prepayments — misleading. **Countermeasure:** явно указывать «ARR is annualized MRR, not actual trailing 12-month revenue».

## Output template

```
═══════════════════════════════════════════
MRR/ARR REPORT — <Month> <Year>
═══════════════════════════════════════════

MRR: $<X> (↑/↓ $<Y> from <prev_month>, <Z>%)
ARR: $<A> (annualized MRR)

─── MRR MOVEMENTS ───
New MRR:         +$<N>  (<X> customers)
Expansion MRR:   +$<E>  (<X> upgrades/add-ons)
Contraction MRR: -$<C>  (<X> downgrades)
Churn MRR:       -$<CH> (<X> customers lost)
Reactivation MRR:+$<R>  (<X> returned)
Net New MRR:     $<NN>

─── CHURN ───
Customer churn: <X>% (<X>/<Y> customers)
Revenue churn:  <X>% ($<X>/$<Y> MRR)

─── PLAN DISTRIBUTION ───
<Plan>: <X> customers, $<MRR> MRR (X%)
...

─── BILLING SPLIT ───
Monthly: <X>% ($<MRR>)
Annual:  <X>% ($<MRR>)

─── NOTES ───
<anomalies, observations>

Verification date: <YYYY-MM-DD>
Confidence: <level>

📎 В архиве: <archive_link>
```

## When NOT to use this skill

- Когда бизнес не subscription-based — MRR неприменим
- Когда нужен **cashflow прогноз** — это `cashflow-forecasting` (MRR — входные данные для него, но не замена)
- Когда нужен **unit economics** (CAC/LTV) — это `unit-economics-calculation` (использует MRR как input)

## Integration with finance

Tier 2, загружается при запросах про MRR, ARR, churn, subscription metrics, fundraising prep.

Использует данные из:
- `db.subscription` — список активных подписок
- `db.invoice` — фактические поступления (для cross-check MRR vs cash)
- `cashflow-forecasting` — MRR как recurring inflow в прогнозе
- `unit-economics-calculation` — MRR на клиента → LTV

Метрика отдела: MRR growth rate = Net New MRR / Beginning MRR. Target: ≥5% месяц (для early stage), ≥3% (для growth stage).