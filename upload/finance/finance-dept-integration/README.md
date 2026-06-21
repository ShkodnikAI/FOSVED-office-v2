# Finance Department Integration Pack

**Block:** Finance (`finance`) Department for fosved-bot
**Version:** 1.0
**Date:** 2026-05-22
**Target:** existing fosved-bot v4.1+
**Owner:** @ShkodnikAI

---

## WHAT THIS IS

A self-contained add-on that adds the **Finance** department to fosved-bot. Function: cashflow forecasting, invoice/payment management, unit economics, tax compliance across 4 jurisdictions (BY, RU, EU, US) and 3 business forms (ООО, ИП, самозанятый).

The pack is **additive** — does not modify existing department code.

---

## DEPARTMENT IDENTITY

- **Title:** Finance
- **Slug:** `finance`
- **Short name:** `ФИН`
- **Function:** Финансовый учёт, прогнозирование cashflow, инвойсинг, unit economics, налоговый комплаенс в 4 юрисдикциях
- **Base principle:** Числа должны сходиться, прогнозы должны иметь verification date, юрисдикция всегда явная.
- **Psychotype primary:** Педант (точность важнее скорости)
- **Psychotype secondary:** Методист (повторяемые процедуры)
- **Main metric:** `mape-cashflow` — Mean Absolute Percentage Error прогнозов cashflow на 30/60/90 дней
- **Targets:** Year 1 — 30d ≤ 5%, 60d ≤ 10%, 90d ≤ 15%
- **Archive Prisma model:** `FinancialForecast`

---

## SUPPORTED JURISDICTIONS & BUSINESS FORMS

### Jurisdictions (knowledge packs in `library/knowledge/finance/jurisdictions/`)
- **BY** — Беларусь (primary, полное наполнение в v1.0)
- **RU** — Россия (полное наполнение в v1.0)
- **EU** — Евросоюз (полное наполнение в v1.0)
- **US** — США (полное наполнение в v1.0)

### Business forms (knowledge packs in `library/knowledge/finance/business-forms/`)
- **ooo** — ООО (Общество с ограниченной ответственностью / LLC)
- **ip** — ИП (Индивидуальный предприниматель / Sole proprietor)
- **selfemployed** — Самозанятый (НПД в RU, ремесленник в BY, freelancer в EU/US)

### Compatibility matrix
`library/knowledge/finance/compatibility-matrix.md` — какие комбинации валидны:
- Самозанятый BY → ремесленник или ремесленная деятельность
- Самозанятый RU → НПД (налог на профессиональный доход)
- Самозанятый EU → нет единой формы, эквивалент — sole trader по странам
- Самозанятый US → schedule C / 1099 contractor

---

## BOUNDARIES (что НЕ делает Finance)

- **Бухгалтерский учёт по форме** — это работа бухгалтера, мы готовим данные для него
- **Налоговая декларация** — генерируем расчёт, но не подаём декларацию (мы не имеем полномочий)
- **Аудит** — проверка фин. отчётности по стандартам — это QA или внешний аудитор
- **Юридические консультации по налогам** — спорные кейсы → Legal
- **Инвестиционные решения** — куда вложить — ОСП или Эксперт

---

## ROUTING TRIGGERS (для Яны)

```
счёт, инвойс, оплата, выручка, бюджет, MRR, ARR, cashflow,
налог, ндс, налоговая, прогноз поступлений, CAC, LTV, маржа,
прибыль, доход, расход, ROI, payback, runway, burn rate
```

---

## METHODOLOGY CHECKLIST (10 stages)

- [x] Stage 1 — Function/boundaries/psychotype/metric defined
- [x] Stage 2 — Profile `library/finance.md` ready
- [x] Stage 3 — Skills `skills/fosved/finance/` (12 planned, 3 full in v1.0)
- [x] Stage 4 — Prisma models (FinancialForecast + Verification + MonthlyReview + Invoice)
- [x] Stage 5 — Commands in `patches/bot-finance-handlers.js`
- [x] Stage 6 — Scheduler (`patches/scheduler-finance-patch.js`)
- [x] Stage 7 — Registration `patches/army-finance-patch.js` + `registry-finance-patch.md`
- [x] Stage 8 — Yana routing `patches/upravlenie-finance-routing-patch.md`
- [ ] Stage 9 — Polygon test cases (5 cases — to be added in integration)
- [ ] Stage 10 — Pass-rate ≥ 70% (verify after integration)

---

## ARCHIVE INTEGRATION

Все результаты публикуются в Telegram канал `ARCHIVE_CHANNEL_ID` через `lib/archive-publisher.js`. Каждая запись в `FinancialForecast` имеет поля `archiveMessageId` + `archiveChannelId`.

---

## PACKAGE CONTENTS

```
finance-dept-integration/
├── README.md                          ← this file
├── FINANCE_INTEGRATION_PLAN.md         ← 10-phase plan (F1..F10)
│
├── library/
│   ├── finance.md                      ← profile with frontmatter
│   └── knowledge/finance/              ← jurisdiction + business-form knowledge
│       ├── compatibility-matrix.md
│       ├── jurisdictions/
│       │   ├── BY.md                   ← полное наполнение
│       │   ├── RU.md                   ← плейсхолдер с явной структурой
│       │   ├── EU.md                   ← плейсхолдер
│       │   └── US.md                   ← плейсхолдер
│       └── business-forms/
│           ├── ooo.md                  ← полное наполнение
│           ├── ip.md                   ← плейсхолдер
│           └── selfemployed.md         ← плейсхолдер
│
├── lib/
│   └── finance.js                      ← business logic
│
├── prisma/
│   └── finance-schema.prisma           ← 5 models
│
├── patches/
│   ├── army-finance-patch.js
│   ├── bot-finance-handlers.js
│   ├── scheduler-finance-patch.js
│   ├── upravlenie-finance-routing-patch.md
│   └── registry-finance-patch.md
│
└── skills/fosved/finance/
    ├── cashflow-forecasting/SKILL.md         ← Tier 1, FULL
    ├── invoice-lifecycle-management/SKILL.md ← Tier 1, FULL
    ├── unit-economics-calculation/SKILL.md   ← Tier 1, FULL
    ├── revenue-recognition-discipline/SKILL.md ← Tier 1, PLACEHOLDER
    ├── forecast-verification-protocol/SKILL.md ← Tier 1, PLACEHOLDER
    ├── tax-compliance-multi-jurisdiction/SKILL.md ← Tier 2, PLACEHOLDER
    ├── multi-currency-handling/SKILL.md      ← Tier 2, PLACEHOLDER
    ├── mrr-arr-reporting/SKILL.md            ← Tier 2, PLACEHOLDER
    └── runway-and-burn-analysis/SKILL.md     ← Tier 3, PLACEHOLDER
```

---

## WHAT'S COMPLETE IN v1.0 vs PLACEHOLDER

**Complete (ready for production use):**
- Profile + all patches + lib + Prisma — full
- 3 Tier 1 skills written in full depth
- BY jurisdiction knowledge — full
- ООО business-form knowledge — full
- Compatibility matrix — full

**Placeholders (structured, ready to fill):**
- 6 remaining skills — have frontmatter + section structure + clear TODO for content
- RU/EU/US jurisdictions — have structure (same template as BY) + TODO content
- ИП/самозанятый business forms — same

Placeholders are **structurally valid**: they have frontmatter, the right sections, and explicit "TODO: fill" markers. They will not crash anything if loaded. They will return a stub response "Скилл в процессе наполнения, базовая методология применима, для специфики см. полные скиллы" — which is honest, not silent failure.

---

## START HERE

1. Read this README.
2. Read `FINANCE_INTEGRATION_PLAN.md` — F1..F10 phases.
3. Apply phases.
4. After Sweep 0 (registry) is done — change Finance entry from `status: 'future'` to `status: 'active'`.

**Prerequisites:**
- fosved-bot Sweep 0 complete (departments-registry.js exists)
- `ARCHIVE_CHANNEL_ID` configured
- `lib/archive-publisher.js` present (from v4.1 transition pack)
