# patches/registry-finance-patch.md

## Purpose

Add Finance to `lib/departments-registry.js` — the single source of truth.

After applying, Finance is visible to: army.js, lib/yana-agent.js, mini-app (when synced).

---

## Entry to add

Open `lib/departments-registry.js`. Inside the `departments: [...]` array, add this entry:

```js
{
  slug: 'finance',
  title: 'Финансы',
  shortName: 'ФИН',
  status: 'active',  // change to 'future' if integrating in placeholder mode

  // File system paths
  profilePath: 'library/finance.md',
  libModule: 'lib/finance.js',
  skillsDir: 'skills/fosved/finance/',
  knowledgePath: 'library/knowledge/finance/',  // jurisdictions + business-forms

  // Database
  archiveModel: 'FinancialForecast',
  verificationModel: 'FinancialForecastVerification',
  monthlyReviewModel: 'FinanceMonthlyReview',

  // Identity
  psychotype: {
    primary: 'Педант',
    secondary: 'Методист',
  },
  metric: {
    name: 'mape-cashflow',
    unit: '%',
    targets: {
      y1: '30d ≤ 5%, 60d ≤ 10%, 90d ≤ 15%',
      y2: '30d ≤ 3%, 60d ≤ 7%, 90d ≤ 12%',
    },
    description: 'Mean Absolute Percentage Error прогнозов cashflow на 30/60/90 дней',
  },

  // Yana routing
  aliases: [
    'финансы',
    'финанс',
    'фин',
    'бухгалтерия',
    'finance',
  ],
  routingTriggers: [
    'счёт', 'инвойс', 'оплата', 'выручка', 'бюджет',
    'MRR', 'ARR', 'cashflow', 'налог', 'ндс', 'налоговая',
    'прогноз поступлений', 'CAC', 'LTV', 'маржа',
    'прибыль', 'доход', 'расход', 'ROI', 'payback', 'runway', 'burn rate',
    'сколько денег', 'хватит ли денег', 'окупаемость',
  ],

  // Boundaries
  notMyScope: [
    { pattern: 'инвестиционное решение', routeTo: 'osp' },
    { pattern: 'правовая трактовка налога', routeTo: 'legal' },
    { pattern: 'ROI кампании', routeTo: 'marketing' },
    { pattern: 'аудит отчётности', routeTo: 'qa' },
  ],

  // Required context (Finance unique — нужны до начала работы)
  requiredContext: [
    { key: 'jurisdiction', enum: ['BY', 'RU', 'EU', 'US'] },
    { key: 'businessForm', enum: ['ooo', 'ip', 'selfemployed'] },
  ],

  // Telegram commands
  commands: [
    '/finance',
    '/finance-forecast',
    '/finance-invoice',
    '/finance-tax',
    '/finance-verify',
    '/finance-archive',
    '/finance-score',
    '/finance-runway',
    '/finance-unit',
  ],

  // Scheduler timing
  schedule: {
    dailyHour: 8,
    monthlyHour: 10,
    quarterlyHour: 11,
  },
},
```

---

## If applying as `future` (not yet built)

```js
{
  slug: 'finance',
  title: 'Финансы',
  shortName: 'ФИН',
  status: 'future',  // <-- key difference

  profilePath: null,
  libModule: null,
  skillsDir: null,
  archiveModel: null,

  psychotype: { primary: 'Педант', secondary: 'Методист' },
  metric: { name: 'mape-cashflow' },
  aliases: ['финансы', 'финанс', 'фин', 'finance'],
  routingTriggers: [],  // empty — Yana acknowledges but doesn't route
  commands: [],
  schedule: null,
  plannedActivation: '2026-Q3',
}
```

When Yana receives matching alias for `future` department:
> «Отдел Финансы запланирован, но пока не активирован. Зафиксирую запрос для будущей обработки.»

---

## Conditions for flipping `future` → `active`

- [x] Profile `library/finance.md` exists (203 строки)
- [x] Lib module `lib/finance.js` exists with required exports (491 строка)
- [x] Prisma models in `prisma/schema.prisma` (FinancialForecast + Verification + MonthlyReview + Invoice + Payment)
- [x] At least 8 skills in `skills/fosved/finance/` (9 skills total)
- [x] At least 3 Tier-1 skills full (cashflow, invoice, unit-economics)
- [x] Knowledge packs for primary jurisdiction (BY) and business form (ооо) full
- [x] Knowledge packs for secondary jurisdictions (RU/EU/US) — structural placeholders
- [x] Knowledge packs for ИП и самозанятый — structural placeholders
- [ ] At least one bot.js handler tested (done in Phase F7)
- [ ] Scheduler tasks registered (done in Phase F8)
- [ ] Polygon test cases with pass-rate ≥ 70% (done in Phase F10)

When all checked — `status: 'active'`. Yana starts routing from next message.

---

## Verification after applying

```bash
node -e "
const r = require('./lib/departments-registry');
const f = r.departments.find(d => d.slug === 'finance');
console.log('Status:', f.status);
console.log('Aliases:', f.aliases.length);
console.log('Triggers:', f.routingTriggers.length);
console.log('Required context:', f.requiredContext?.map(c => c.key).join(', '));
"

node scripts/audit_registry.js
```
