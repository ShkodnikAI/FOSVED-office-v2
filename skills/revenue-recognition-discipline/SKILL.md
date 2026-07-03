---
name: revenue-recognition-discipline
description: When to recognize revenue (cash vs accrual basis), deferred revenue, prepaid handling. Use for monthly P&L preparation and audit-ready accounting.
tier: 1
---

# Revenue Recognition Discipline — когда выручка «считается» выручкой

Выручка — не то же самое, что деньги на счёте. Если клиент предоплатил 12 000 EUR за годовой контракт — на счёте 12 000 EUR, но выручка за этот месяц = 1 000 EUR, а остальные 11 000 = **deferred revenue** (авансы полученные). Это не accounting pedantry — без правильного recognition бизнес не знает свою реальную прибыльность, и P&L показывает неверную картину.

## Prerequisites

- Юрисдикция определена (определяет применяемый стандарт: IFRS 15 / РСБУ / US GAAP ASC 606)
- Бизнес-форма определена (ИП и самозанятые могут использовать упрощённый учёт)
- Метод учёта определён: cash basis или accrual basis
- Данные по инвойсам, оплатам и договорам доступны

## Core principle

> **Revenue recognition отвечает на вопрос «в каком месяце мы заработали эти деньги»**, не «в каком месяце деньги пришли».** Если ответ на эти два вопроса не совпадает — у вас есть deferred revenue или accrued revenue, и P&L без их разделения врёт. Для малого бизнеса это кажется избыточным, но именно здесь прячутся две самые распространённые ошибки: (1) платить налоги на деньги, которые вы ещё не заработали, и (2) считать бизнес прибыльным, когда он живёт за счёт авансов.

**Инверсия интуиции:** prepaid (предоплата) — это **обязательство**, не выручка. Клиент дал вам 12 000 EUR вперёд — вы **должны** ему 12 месяцев сервиса. Если вы recognise всю сумму в месяце получения — вы показываете прибыль, которой нет, и платите налоги из денег, которые технически принадлежат клиенту (они могут потребовать возврата при non-delivery). Deferred revenue — это liability, не asset.

## The procedure

### Step 1 — Определить метод учёта

| Бизнес-форма | Юрисдикция | Метод по умолчанию | Can use accrual? |
|---|---|---|---|
| ИП | BY/RU | Cash basis | Да, добровольно |
| Самозанятый (Ремесленник) | BY | Cash basis | Нет |
| ИП НПД | RU | Cash basis | Нет |
| ООО | BY/RU | Accrual basis | Обязан |
| GmbH / Ltd | EU/US | Accrual (IFRS 15 / ASC 606) | Обязан |

**Cash basis:** выручка = деньги пришли. Расход = деньги ушли. Простые, но искажает реальную картину при prepayments.

**Accrual basis:** выручка признаватся когда obligation выполнено (service delivered / goods shipped), независимо от оплаты. Для ООО — обязателен.

### Step 2 — Применить 5-step model (IFRS 15 / ASC 606)

Для accrual basis — пять шагов:

**Step 1 — Identify the contract.** Договор подписан? У сторон есть обязательства? Commercial substance?

**Step 2 — Identify performance obligations.** Что именно мы обязаны сделать? Для SaaS с annual prepayment: obligation = доступ к сервису 12 месяцев. Это **одна** performance obligation с 12 monthly deliverables.

**Step 3 — Determine transaction price.** Сколько мы получим? Включая variable consideration (bonuses, penalties, discounts). Для fixed-price contract — просто цена договора.

**Step 4 — Allocate price to obligations.** Если в договоре несколько obligations — распределить цену пропорционально. Для SaaS: вся цена → одна obligation.

**Step 5 — Recognize when obligation satisfied.** Over time (SaaS subscription — каждый месяц) или at a point in time (разработка ПО — при acceptance).

### Step 3 — Классифицировать конкретные ситуации

**Ситуация 1: Annual prepayment (SaaS)**
```
Клиент заплатил 12 000 EUR 01.01 за годовой доступ.
Cash basis: revenue января = 12 000 EUR (всё сразу)
Accrual: revenue каждого месяца = 1 000 EUR
Deferred revenue на 01.01 = 11 000 EUR (liability)
Deferred revenue на 01.02 = 10 000 EUR
...
Deferred revenue на 01.12 = 0 EUR
```

**Ситуация 2: Milestone payment (проект)**
```
Контракт на 80 000 EUR. Milestones: 20% prepayment, 30% при delivery M1, 30% при acceptance M2, 20% после warranty.
Cash basis: revenue = когда деньги пришли
Accrual: revenue = когда milestone выполнен (delivery / acceptance / warranty end)

Пример: client paid 20% prepayment (16 000 EUR) 01.03. M1 delivered 15.03.
Accrual recognition: 16 000 EUR → deferred revenue 01.03 → recognise 16 000 EUR при M1 delivery 15.03
(if 16 000 EUR = price allocated to M1)
```

**Ситуация 3: Invoice sent, not paid**
```
Инвойс 25 000 USD выставлен 15.06, не оплачен к 30.06.
Cash basis: revenue = 0 (деньги не пришли)
Accrual: revenue = 25 000 USD (obligation выполнено — услуга оказана, инвойс = evidence)
Accounts receivable = 25 000 USD (asset)
```

**Ситуация 4: Paid in advance for service not yet delivered**
```
Клиент перевёл 8 000 EUR 28.06. Услуга будет оказана в июле.
Cash basis: revenue июня = 8 000 EUR
Accrual: revenue июня = 0. Deferred revenue = 8 000 EUR (liability). Revenue июля = 8 000 EUR.
```

### Step 4 — Рассчитать P&L с разделением

| Строка | Cash basis | Accrual basis |
|---|---|---|
| Revenue (services rendered) | 52 000 EUR | 38 000 EUR |
| Deferred revenue | N/A | 14 000 EUR (liability) |
| Accounts receivable | N/A | 25 000 USD (asset) |
| Cash received | 52 000 EUR | 52 000 EUR (same) |
| Actual profitability | Overstated if prepaid | Accurate |

**Разница = deferred revenue + accrued revenue (accounts receivable).** Для малых business это может быть 20-40% от «выручки» — слишком много, чтобы игнорировать.

### Step 5 — Граница с MRR/ARR

**Revenue recognition** отвечает: «в каком месяце мы заработали X?»

**MRR/ARR** отвечает: «какова нормализованная стоимость нашей подписочной базы?»

Они оперируют **разными числами**:

| Вопрос | Revenue recognition | MRR/ARR |
|---|---|---|
| Annual prepayment 12 000 EUR | 1 000 EUR/мес revenue | 1 000 EUR MRR contribution |
| Monthly subscription 1 000 EUR, paid this month | 1 000 EUR revenue | 1 000 EUR MRR contribution |
| Monthly subscription 1 000 EUR, NOT paid this month | 1 000 EUR revenue (accrual) | 1 000 EUR MRR contribution |
| One-time setup fee 500 EUR | 500 EUR revenue (at delivery) | 0 EUR (not recurring) |

**Ключевая разница:** revenue recognition обрабатывает **все типы выручки** (recurring, one-time, services, goods). MRR/ARR — только recurring subscription component. Revenue recognition определяет timing; MRR/ARR определяет normalisation.

### Step 6 — Сохранить через `saveResult()`

```js
await finance.saveResult({
  shortTitle: `Revenue recognition: ${month} ${year} (${jurisdiction}/${businessForm})`,
  fullResult: formatRevenueReport(lines, deferred, accrued),
  confidence: 'high',
  verificationDate: monthEnd + 90, // налоговая может потребовать корректировку
  jurisdiction,
  businessForm,
});
```

### Step 7 — Ответить владельцу

```
📊 Revenue Recognition — ООО BY, June 2026

Method: Accrual (IFRS 15)

Revenue this month: 38 000 EUR
  Services delivered: 30 000 EUR
  MRR recognized (from prepaids): 8 000 EUR

Deferred revenue (liability): 14 000 EUR
  From annual prepayments: 11 000 EUR (11 months remaining)
  From project prepayment: 3 000 EUR (delivery in July)

Accounts receivable (asset): 25 000 USD (~80 000 BYN)
  Invoice #INV-042: 25 000 USD (overdue, age 45 days)

P&L impact:
  Gross revenue (accrual): 38 000 EUR
  Cash received: 52 000 EUR
  Difference: 14 000 EUR (deferred) − 80 000 BYN (receivable) = net timing gap

⚠ 注意: 25 000 USD receivable age >30d — collection risk. See cashflow-forecasting.

Verification date: <YYYY-MM-DD>
```

## Worked example

**Контекст:** BY ООО, SaaS + services. Июнь 2026.

**Все транзакции за июнь:**

| Дата | Событие | Сумма | Валюта |
|---|---|---|---|
| 01.06 | Annual subscription from Alpha Corp (prepaid) | 12 000 | EUR |
| 05.06 | Monthly subscription from 8 clients | 4 000 | USD |
| 10.06 | Project milestone M2 delivered to Beta GmbH | 24 000 | EUR (accrued, not yet paid — invoice sent) |
| 15.06 | Invoice #INV-042 sent to Gamma (25 000 USD, service rendered) | — | — |
| 20.06 | One-time setup fee for new client | 500 | USD |
| 28.06 | Prepayment for July project | 3 000 | EUR |

**Accrual recognition:**

```
Revenue (июнь):
  Annual prepaid (Alpha Corp): 12 000 / 12 = 1 000 EUR (1 month of 12)
  Monthly subscriptions: 4 000 USD × 3.20 = 12 800 BYN ≈ 4 000 EUR equivalent
  Project milestone M2 (Beta GmbH): 24 000 EUR (delivered → recognise)
  One-time setup fee: 500 USD × 3.20 = 1 600 BYN ≈ 500 EUR equivalent
  TOTAL revenue: 1 000 + 4 000 + 24 000 + 500 = 29 500 EUR

Deferred revenue (на конец июня):
  Alpha Corp prepaid: 12 000 − 1 000 = 11 000 EUR
  July prepayment: 3 000 EUR (service in July, not June)
  TOTAL deferred: 14 000 EUR

Accounts receivable (на конец июня):
  Beta GmbH M2: 24 000 EUR (invoice sent, not paid)
  Gamma: 25 000 USD (invoice sent, not paid)
  TOTAL AR: 24 000 EUR + 25 000 USD
```

**Cash basis (для сравнения):**
```
Cash received: 12 000 EUR + 4 000 USD + 500 USD + 3 000 EUR = 15 000 EUR + 4 500 USD
Cash basis revenue: everything received = 15 000 EUR + 4 500 USD ≈ 29 400 EUR equivalent
```

В этом конкретном месяце разница мала (29 500 accrual vs 29 400 cash), потому что large items (M2 24 000 EUR, INV-042 25 000 USD) ещё не оплачены. Разница проявится когда (если) они оплатят — cash basis покажет spike, accrual останется flat.

## Anti-patterns

- **Recognize prepaid revenue сразу.** «Клиент заплатил 12 000 — это наша выручка». Нет — это deferred revenue, вы **должны** сервис. Если recognise сразу — P&L показывает прибыль, которой нет, налоги считаются с денег, которые могут быть возвращены. **Countermeasure:** deferred revenue = liability, recognise пропорционально delivery.

- **Не recognize revenue пока не оплачено (cash basis для ООО).** ООО обязан accrual basis. Если service rendered в июне, а деньги пришли в июле — revenue июня, не июля. Иначе июньский P&L занижен, июльский завышен. **Countermeasure:** для ООО всегда accrual. Для ИП/самозанятого — cash по умолчанию, но можно добровольно accrual.

- **Смешивать recurring и one-time в revenue line без разбивки.** «Revenue: 50 000 EUR». Включает ли это setup fee? Prepayment? Это важно для понимания repeatable vs non-repeatable revenue. **Countermeasure:** minimum three lines: recurring revenue, one-time revenue, deferred change.

- **Считать revenue до выполнения obligation.** «Мы подписали контракт на 80 000 EUR — add к revenue». Контракт подписан, но service не rendered — это 0 revenue, 0 deferred. Revenue признаётся при **performance**, не при signature. **Countermeasure:** 5-step model: Step 5 (recognize) только после Step 1-4 complete.

- **Не учитывать returns/refunds в revenue.** «Продали на 10 000 EUR». Если 5% клиентов запрашивают refund (SaaS industry average) — real revenue = 9 500 EUR. **Countermeasure:** allowance for returns (estimation) при significant volume.

## Output template

```
═══════════════════════════════════════════
REVENUE RECOGNITION — <Month> <Year>
═══════════════════════════════════════════

Entity: <BusinessForm> <Jurisdiction>
Method: Cash / Accrual (IFRS 15 / РСБУ)

─── RECOGNIZED REVENUE ───
Recurring revenue: <X> <currency>
One-time revenue: <X> <currency>
TOTAL RECOGNIZED: <X> <currency>

─── DEFERRED REVENUE (liability) ───
| Source | Amount | Months remaining | Monthly recognition |
|--------|--------|-------------------|---------------------|
| ... | ... | ... | ... |
TOTAL DEFERRED: <X> <currency>

─── ACCOUNTS RECEIVABLE (asset) ───
| Invoice | Amount | Age | Expected payment |
|---------|--------|-----|-----------------|
| ... | ... | ... | ... |
TOTAL AR: <X> <currency>

─── CASH RECEIVED (vs recognized) ───
Cash received: <X> <currency>
Revenue recognized: <X> <currency>
Difference: <X> <currency> (deferred − AR)

─── MRR/ARR BOUNDARY NOTE ───
Recurring revenue recognized: <X> <currency>
MRR (from mrr-arr-reporting): <X> <currency>
Difference reason: <prepaids spreading / AR timing / one-time in revenue>

Verification date: <YYYY-MM-DD>
Confidence: <level>

📎 В архиве: <archive_link>
```

## When NOT to use this skill

- Когда нужен **MRR/ARR report** (нормализованная подписочная метрика) — это `mrr-arr-reporting`
- Когда нужен **cashflow прогноз** — это `cashflow-forecasting`
- Когда нужна **налоговая декларация** — Finance готовит данные, подаёт бухгалтер
- Когда бизнес на **чистом cash basis** (самозанятый BY) и вопрос про «сколько денег пришло» — это cashflow, не revenue recognition

## Integration with finance

Tier 1 — загружается **всегда** при обращении к Finance. Revenue recognition — фундамент P&L, а P&L — основа для налоговых расчётов и оценки прибыльности.

Использует:
- `db.invoice` — выставленные инвойсы и их статусы
- `db.subscription` — для расчёта monthly recognition из prepaids
- `mrr-arr-reporting` — recurring component как input
- `cashflow-forecasting` — cash received как cross-check

**Граница с mrr-arr-reporting:** revenue recognition оперирует **всеми** типами выручки и определяет **timing**. MRR/ARR оперирует только **recurring subscription** и определяет **normalised value**. Они не дублируют друг друга. Revenue recognition для SaaS-подписки: «этот месяц recognise 1/12 от annual prepaid». MRR для того же клиента: «его contribution к MRR = monthly price». Числа совпадают, но вопросы разные.

Метрика отдела: revenue recognition accuracy = соответствие признанной выручки фактической после accounting reconciliation (target: 100% при accrual method).