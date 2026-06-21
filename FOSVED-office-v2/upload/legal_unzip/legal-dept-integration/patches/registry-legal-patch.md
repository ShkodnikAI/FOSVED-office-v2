# patches/registry-legal-patch.md

## Purpose

Add Legal to `lib/departments-registry.js`.

---

## Entry to add

Open `lib/departments-registry.js`. Inside `departments: [...]` array, add:

```js
{
  slug: 'legal',
  title: 'Юрист',
  shortName: 'ЮР',
  status: 'active',  // change to 'future' if integrating in placeholder mode

  // File system paths
  profilePath: 'library/legal.md',
  libModule: 'lib/legal.js',
  skillsDir: 'skills/fosved/legal/',
  knowledgePath: 'library/knowledge/legal/',

  // Database
  archiveModel: 'LegalAssessment',
  verificationModel: 'LegalAssessmentVerification',
  monthlyReviewModel: 'LegalMonthlyReview',
  additionalModels: ['ContractTemplate', 'LegalDocument'],

  // Identity
  psychotype: {
    primary: 'Параноик',
    secondary: 'Педант',
  },
  metric: {
    name: 'pct-clean-signings',
    unit: '%',
    targets: {
      y1: '≥ 80%',
      y2: '≥ 90%',
    },
    description: '% сделок без post-signing rewrites',
  },

  // Yana routing
  aliases: [
    'юрист',
    'юр',
    'юриспруденция',
    'право',
    'legal',
    'lawyer',
  ],
  routingTriggers: [
    'договор', 'NDA', 'MSA', 'SLA', 'TZ', 'оферта', 'контракт', 'соглашение',
    'правовые риски', 'регуляторика', 'GDPR', 'комплаенс', 'подписать',
    'юридическая экспертиза', 'юридический анализ',
    'конфиденциальность', 'intellectual property', 'IP', 'авторское право',
    'торговая марка', 'лицензия', 'terms of service', 'privacy policy',
    'политика конфиденциальности', 'претензия', 'иск', 'спор', 'арбитраж',
  ],

  // Boundaries
  notMyScope: [
    { pattern: 'налоговая декларация', routeTo: 'finance' },
    { pattern: 'судебное представительство', routeTo: 'external-lawyer' },
    { pattern: 'уголовное', routeTo: 'external-lawyer' },
    { pattern: 'регистрация юр. лица', routeTo: 'operations' },
    { pattern: 'бухгалтерская отчётность', routeTo: 'finance' },
  ],

  // Required context
  requiredContext: [
    { key: 'jurisdiction', enum: ['BY', 'RU', 'EU', 'US'] },
    { key: 'businessForm', enum: ['ooo', 'ip', 'selfemployed'] },
  ],
  optionalContext: [
    { key: 'counterpartyJurisdiction', enum: ['BY', 'RU', 'EU', 'US'] },
    { key: 'counterpartyForm', enum: ['ooo', 'ip', 'selfemployed'] },
    { key: 'documentType', enum: ['NDA', 'MSA', 'SLA', 'TZ', 'other'] },
    { key: 'positionInDeal', enum: ['buyer', 'seller', 'client', 'contractor', 'partner'] },
  ],

  // Mandatory disclaimer (applied automatically by lib/legal.js)
  mandatoryDisclaimer: true,

  // Telegram commands
  commands: [
    '/legal',
    '/legal-nda',
    '/legal-msa',
    '/legal-review',
    '/legal-risk-map',
    '/legal-verify',
    '/legal-archive',
    '/legal-score',
    '/legal-templates',
  ],

  // Scheduler timing (avoiding Finance 8:00/10:00/11:00)
  schedule: {
    dailyHour: 9,         // alternative 8:30 if 9 taken
    monthlyHour: 10,
    monthlyMinute: 30,    // 10:30
    quarterlyHour: 11,
    quarterlyMinute: 30,  // 11:30
  },
},
```

---

## If applying as `future` (not yet built)

```js
{
  slug: 'legal',
  title: 'Юрист',
  shortName: 'ЮР',
  status: 'future',
  profilePath: null,
  libModule: null,
  skillsDir: null,
  archiveModel: null,
  psychotype: { primary: 'Параноик', secondary: 'Педант' },
  metric: { name: 'pct-clean-signings' },
  aliases: ['юрист', 'юр', 'право', 'legal'],
  routingTriggers: [],  // empty for future
  commands: [],
  schedule: null,
  plannedActivation: '2026-Q3',
}
```

When Yana receives matching alias for `future`:
> «Отдел Юрист запланирован, но пока не активирован. Зафиксирую запрос для будущей обработки.»

---

## Conditions for `future` → `active`

- [x] Profile `library/legal.md` (159 строк)
- [x] Lib module `lib/legal.js` (~330 строк, with archive + disclaimer)
- [x] Prisma models: LegalAssessment + Verification + MonthlyReview + ContractTemplate + LegalDocument
- [x] 10 skills in `skills/fosved/legal/` (3 Tier 1 full, 7 placeholders)
- [x] Knowledge: BY + ooo полные; RU/EU/US/ИП/самозанятый — placeholders
- [x] Compatibility matrix
- [ ] Bot handlers tested (Phase L7)
- [ ] Scheduler tested (Phase L8)
- [ ] Polygon pass-rate ≥ 70% (Phase L10)

---

## Verification after applying

```bash
node -e "
const r = require('./lib/departments-registry');
const l = r.departments.find(d => d.slug === 'legal');
console.log('Status:', l.status);
console.log('Aliases:', l.aliases.length);
console.log('Triggers:', l.routingTriggers.length);
console.log('Required context:', l.requiredContext?.map(c => c.key).join(', '));
console.log('Mandatory disclaimer:', l.mandatoryDisclaimer);
"

node scripts/audit_registry.js
```
