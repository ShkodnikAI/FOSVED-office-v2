# Legal Department Integration Pack

**Block:** Legal (`legal`) Department for fosved-bot
**Version:** 1.0
**Date:** 2026-05-22
**Target:** existing fosved-bot v4.1+
**Owner:** @ShkodnikAI

---

## WHAT THIS IS

Self-contained add-on adding **Legal** department. Function: договорная работа (NDA/MSA/SLA/TZ), оценка правовых рисков сделок, GDPR/комплаенс, регуляторика по 4 юрисдикциям (BY, RU, EU, US) и 3 бизнес-формам (ООО, ИП, самозанятый).

Additive — не модифицирует существующий код других отделов.

---

## DEPARTMENT IDENTITY

- **Title:** Legal
- **Slug:** `legal`
- **Short name:** `ЮР`
- **Function:** Договорная работа, оценка правовых рисков, GDPR/комплаенс, регуляторика в 4 юрисдикциях
- **Base principle:** Договор — это карта рисков. Каждая формулировка либо защищает от риска, либо создаёт его. Не бывает «нейтральных» формулировок.
- **Psychotype primary:** Параноик (ищет дыры там, где другие видят решения)
- **Psychotype secondary:** Педант (формулировки точные, ссылки на нормы)
- **Main metric:** `pct-clean-signings` — % сделок без post-signing rewrites
- **Targets:** Year 1 ≥ 80%, Year 2 ≥ 90%
- **Archive Prisma model:** `LegalAssessment`

---

## SUPPORTED JURISDICTIONS & BUSINESS FORMS

### Jurisdictions (`library/knowledge/legal/jurisdictions/`)
- **BY** — Беларусь (primary, полное наполнение в v1.0)
- **RU** — Россия (плейсхолдер со структурой)
- **EU** — Евросоюз (плейсхолдер: GDPR + Digital Services Act базис)
- **US** — США (плейсхолдер)

### Business forms (`library/knowledge/legal/business-forms/`)
- **ooo** — ООО (primary, полное наполнение)
- **ip** — ИП (плейсхолдер)
- **selfemployed** — Самозанятый (плейсхолдер)

### Compatibility — те же правила что в Finance:
- Самозанятый BY → ремесленник или ИП-эквивалент
- Самозанятый RU → НПД, договоры на профессиональный доход
- Самозанятый EU → varies by country
- Самозанятый US → Sole Proprietorship + Schedule C

---

## BOUNDARIES (что НЕ делает Legal)

- **Судебное представительство** — Legal готовит позицию, но в суд идёт лицензированный адвокат
- **Регистрация юр. лица** — это операционная процедура, не наша
- **Криминальные дела** — Legal не работает с уголовкой
- **Налоговые декларации** — это Finance
- **Финансовые расчёты** в договорах — Finance ставит суммы, Legal проверяет формулировки
- **Споры о фактах** — мы анализируем нормы и риски, не доказываем факты в суде

---

## ROUTING TRIGGERS (для Яны)

```
договор, NDA, MSA, SLA, TZ, оферта, контракт, соглашение,
правовые риски, регуляторика, GDPR, комплаенс, подписать, signing,
юридическая экспертиза, юридический анализ, due diligence правовое,
конфиденциальность, intellectual property, IP, авторское право,
торговая марка, лицензия, лицензионное соглашение, terms of service,
privacy policy, политика конфиденциальности, согласие на обработку
```

---

## METHODOLOGY CHECKLIST (10 stages)

- [x] Stage 1 — Function/boundaries/psychotype/metric defined
- [x] Stage 2 — Profile `library/legal.md`
- [x] Stage 3 — Skills `skills/fosved/legal/` (10 planned: 3 Tier 1 full, 7 placeholders)
- [x] Stage 4 — Prisma models (LegalAssessment + Verification + MonthlyReview + ContractTemplate + LegalDocument)
- [x] Stage 5 — Commands in `patches/bot-legal-handlers.js`
- [x] Stage 6 — Scheduler tasks (`patches/scheduler-legal-patch.js`)
- [x] Stage 7 — Registration `patches/army-legal-patch.js` + `registry-legal-patch.md`
- [x] Stage 8 — Yana routing `patches/upravlenie-legal-routing-patch.md`
- [ ] Stage 9 — Polygon test cases (5 — added in integration)
- [ ] Stage 10 — Pass-rate ≥ 70% (verify after integration)

---

## ARCHIVE INTEGRATION

All Legal results published to `ARCHIVE_CHANNEL_ID` via `lib/archive-publisher.js`. Each `LegalAssessment` row has `archiveMessageId` + `archiveChannelId`.

Special note for Legal: **полные тексты договоров публикуются как файлы, не как сообщения** — Telegram сообщение имеет лимит 4096 символов, договоры обычно длиннее. Используется `bot.sendDocument()` с генерируемым `.md` файлом, а в архив идёт metadata + ссылка на документ.

---

## PACKAGE CONTENTS

```
legal-dept-integration/
├── README.md
├── LEGAL_INTEGRATION_PLAN.md           ← phases L1..L10
│
├── library/
│   ├── legal.md
│   └── knowledge/legal/
│       ├── compatibility-matrix.md
│       ├── jurisdictions/
│       │   ├── BY.md                   ← full (primary)
│       │   ├── RU.md                   ← placeholder
│       │   ├── EU.md                   ← placeholder
│       │   └── US.md                   ← placeholder
│       └── business-forms/
│           ├── ooo.md                  ← full (primary)
│           ├── ip.md                   ← placeholder
│           └── selfemployed.md         ← placeholder
│
├── lib/
│   └── legal.js
│
├── prisma/
│   └── legal-schema.prisma             ← 5 models
│
├── patches/
│   ├── army-legal-patch.js
│   ├── bot-legal-handlers.js
│   ├── scheduler-legal-patch.js
│   ├── upravlenie-legal-routing-patch.md
│   └── registry-legal-patch.md
│
└── skills/fosved/legal/
    ├── risk-mapping-protocol/SKILL.md         ← Tier 1, FULL
    ├── contract-drafting-discipline/SKILL.md  ← Tier 1, FULL
    ├── red-flag-detection/SKILL.md            ← Tier 1, FULL
    ├── cross-jurisdiction-comparison/SKILL.md ← Tier 1, PLACEHOLDER
    ├── precedent-search-application/SKILL.md  ← Tier 1, PLACEHOLDER
    ├── nda-msa-sla-templates/SKILL.md         ← Tier 2, PLACEHOLDER
    ├── gdpr-compliance-check/SKILL.md         ← Tier 2, PLACEHOLDER
    ├── ip-clause-discipline/SKILL.md          ← Tier 2, PLACEHOLDER
    ├── consumer-protection-check/SKILL.md     ← Tier 2, PLACEHOLDER
    └── dispute-resolution-strategy/SKILL.md   ← Tier 3, PLACEHOLDER
```

---

## START HERE

1. Read this README
2. Read `LEGAL_INTEGRATION_PLAN.md` — phases L1..L10
3. Apply phases
4. After Sweep 0 (registry) — flip Legal entry from `status: 'future'` to `status: 'active'`

**Prerequisites:** Same as Finance pack (Sweep 0 done, archive-publisher.js exists, ARCHIVE_CHANNEL_ID configured)

---

## ⚠ CRITICAL DISCLAIMER

**Legal department — это вспомогательный инструмент, не замена юриста.** Все результаты должны быть:
1. Проверены лицензированным юристом перед подписанием договоров на критичные суммы
2. Сверены с актуальной нормативной базой (законы меняются)
3. Использованы как **draft + risk map**, не финальный документ

Knowledge packs могут устареть. Перед применением сверяться с официальными источниками (Pravo.by, КонсультантПлюс, EUR-Lex, и т.д.).

Этот disclaimer **обязательно** выводится в каждом ответе Legal через `lib/legal.js`.
