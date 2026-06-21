# patches/upravlenie-finance-routing-patch.md

## Purpose

This patch registers Finance routing in Yana's knowledge. The **actual** registration happens via `registry-finance-patch.md` (single source of truth `lib/departments-registry.js`).

This document is **informational** — for human owners and AI agents reading the pack.

---

## Triggers (Russian) — phrases that route to Finance

```
счёт, инвойс, оплата, выручка, бюджет, MRR, ARR, cashflow,
налог, ндс, налоговая, прогноз поступлений, CAC, LTV, маржа,
прибыль, доход, расход, ROI, payback, runway, burn rate,
сколько денег, хватит ли денег, окупаемость, payment, invoice,
revenue, profit, margin, tax, VAT
```

---

## Short description (for Yana's system prompt)

```
Finance (ФИН) — финансовый учёт, прогнозирование cashflow, инвойсы, unit economics, налоги в 4 юрисдикциях (BY/RU/EU/US).
Психотип: Педант + Методист
Команды: /finance, /finance-forecast, /finance-invoice, /finance-tax, /finance-verify, /finance-archive, /finance-score
Особенность: при каждом запросе требует определения юрисдикции (BY/RU/EU/US) и бизнес-формы (ООО/ИП/самозанятый).
```

---

## Boundaries (когда NOT route to Finance)

- **Бухгалтерская отчётность по форме** (баланс, отчёт о прибылях по местным стандартам) — это работа бухгалтера, Finance готовит данные но не подменяет
- **Юридическая трактовка налогового кодекса** — спорные случаи → Legal
- **Инвестиционные решения** ("куда вложить", "стоит ли") → OSP или Expert
- **Маркетинговые ROI** ("окупается ли эта кампания") — частично Marketing, Finance даёт входные данные
- **Аудит финансовой отчётности** → QA или внешний аудитор

---

## Multi-department patterns

Some requests involve Finance + другой отдел. Examples:

- **«Подсчитай ROI кампании X для клиента Y»** → Marketing считает конверсии и затраты, Finance верифицирует через unit-economics
- **«Подготовь договор + расчёт оплаты по нему»** → Legal составляет договор, Finance считает суммы и налоги
- **«Финансовый прогноз для инвестора»** → OSP делает стратегический сценарий, Finance подсчитывает unit economics + cashflow для модели

Яна orchestrates: вызывает каждый отдел последовательно, собирает ответ.

---

## Test phrases after Sweep 2 (Yana enhancement) applied

| Owner says | Expected: Yana routes to |
|---|---|
| "Сколько денег будет к концу июня?" | Finance (cashflow forecast) |
| "Просроченные инвойсы" | Finance (invoice-lifecycle-management) |
| "Какой VAT в Германии?" | Finance (tax-compliance-multi-jurisdiction) |
| "Окупается ли реклама?" | Finance + Marketing |
| "Договор на 5000 EUR от клиента из EU" | Legal + Finance (договор + расчёт налогов) |
| "Сколько стоит привлечь клиента?" | Finance (unit-economics-calculation CAC) |

---

## Yana's question-asking protocol for Finance

Когда Yana маршрутизирует запрос в Finance, она **должна сначала** запросить контекст:

1. **Если юрисдикция не указана в запросе** — задать вопрос: «Какая юрисдикция? BY/RU/EU/US»
2. **Если бизнес-форма не указана** — спросить: «Какая бизнес-форма? ООО/ИП/самозанятый»

Это **не отговорки** — без этих двух параметров финансовый расчёт может быть систематически неверным.

Исключение: если у владельца в БД сохранён `defaultJurisdiction` и `defaultBusinessForm` — использовать их без вопроса (но при cross-jurisdictional ситуациях всё равно уточнить).
