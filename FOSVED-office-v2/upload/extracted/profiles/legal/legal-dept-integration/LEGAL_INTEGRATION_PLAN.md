# LEGAL_INTEGRATION_PLAN.md

**Department:** Юрист (`legal`)
**Version:** 1.0
**Target:** fosved-bot v4.1+ (after Sweep 0 + v4.1 transition pack + optionally after Finance pack)
**Phases:** L1..L10

---

## Prerequisites — must be true before starting

- [ ] Sweep 0 (расчистка) applied — `lib/departments-registry.js` exists
- [ ] v4.1 transition pack deployed — `lib/archive-publisher.js` exists
- [ ] `ARCHIVE_CHANNEL_ID` configured in `.env`
- [ ] Branch `feature/legal-dept` ready
- [ ] (Recommended) Finance pack already deployed — Legal часто работает в связке с Finance

If any false — STOP and resolve first.

---

## Phase status table

| Phase | Status | Started | Completed |
|---|---|---|---|
| L1 — Setup branch & prerequisites | not started | — | — |
| L2 — Prisma schema (5 models) | not started | — | — |
| L3 — library/legal.md + knowledge packs | not started | — | — |
| L4 — Skills (10 in skills/fosved/legal/) | not started | — | — |
| L5 — lib/legal.js with disclaimer + file publishing | not started | — | — |
| L6 — army.js + departments-registry.js | not started | — | — |
| L7 — bot.js handlers + context flow with counterparty | not started | — | — |
| L8 — Scheduler tasks (daily 9:00, monthly 10:30, quarterly 11:30) | not started | — | — |
| L9 — Yana routing triggers in registry | not started | — | — |
| L10 — Polygon (5 test cases) + acceptance | not started | — | — |

---

## PHASE L1 — Setup branch & prerequisites

### L1.1 Verify prerequisites

```bash
cd <project_root>
git status                              # clean
grep -q "ARCHIVE_CHANNEL_ID" .env       # configured
test -f lib/archive-publisher.js && echo OK
test -f lib/departments-registry.js && echo OK
# Optional Finance check
test -f lib/finance.js && echo "Finance: OK" || echo "Finance: not deployed (Legal can still work)"
```

### L1.2 Create branch

```bash
git checkout -b feature/legal-dept
```

### L1.3 Verify pack contents

```bash
cd <pack>/legal-dept-integration
find . -type f | wc -l    # expect ≥ 27 files
ls library/                # legal.md, knowledge/
ls library/knowledge/legal/jurisdictions/    # BY/RU/EU/US.md
ls library/knowledge/legal/business-forms/   # ooo/ip/selfemployed.md
ls skills/fosved/legal/   # 10 skill folders
ls patches/               # 5 patch files
```

### L1.4 Backup

```bash
cp prisma/schema.prisma prisma/schema.prisma.before-legal
cp army.js army.js.before-legal
cp lib/departments-registry.js lib/departments-registry.js.before-legal
```

### Acceptance L1

- [ ] Branch created
- [ ] Prerequisites verified
- [ ] 27+ pack files present
- [ ] Backups created

### Smoke test L1

```bash
node -c bot.js && echo "L1: bot.js compiles"
node -e "require('./army.js'); console.log('L1: army.js loaded')"
node -e "require('./lib/departments-registry'); console.log('L1: registry loaded')"
node -e "require('./lib/archive-publisher'); console.log('L1: archive-publisher loaded')"
```

### Commit

```bash
git add prisma/schema.prisma.before-legal army.js.before-legal lib/departments-registry.js.before-legal
git commit -m "[Phase L1] Setup branch and backup for Legal integration"
```

---

## PHASE L2 — Prisma schema (5 models)

### L2.1 Append schema

Append `prisma/legal-schema.prisma` to main `prisma/schema.prisma`. Verify no collisions:

```bash
grep "^model " <pack>/prisma/legal-schema.prisma | awk '{print $2}' > /tmp/new_models.txt
grep "^model " prisma/schema.prisma | awk '{print $2}' > /tmp/existing_models.txt
comm -12 <(sort /tmp/new_models.txt) <(sort /tmp/existing_models.txt)
# Should be empty
```

Expected new models:
- `LegalAssessment` (main archive)
- `LegalAssessmentVerification`
- `LegalMonthlyReview`
- `ContractTemplate` (reusable templates)
- `LegalDocument` (concrete document instances)

If existing project has `LegalAssessment` — STOP. Either rename or merge logic carefully.

### L2.2 Generate client

```bash
npx prisma generate
```

### L2.3 Create migration

```bash
npx prisma migrate dev --name "add_legal_department" --create-only
cat prisma/migrations/$(ls -t prisma/migrations | head -1)/migration.sql
```

### L2.4 Apply

```bash
npx prisma migrate dev
```

### L2.5 DB smoke test

```bash
node -e "
const { PrismaClient } = require('@prisma/client');
const db = new PrismaClient();
Promise.all([
  db.legalAssessment.count(),
  db.contractTemplate.count(),
  db.legalDocument.count(),
]).then(counts => { console.log('Counts:', counts); db.\$disconnect(); });
"
```

### Acceptance L2

- [ ] Schema appended, no conflicts
- [ ] Migration applied
- [ ] All 5 tables exist

### Commit

```bash
git add prisma/
git commit -m "[Phase L2] Add Legal Prisma models (5 models)"
```

---

## PHASE L3 — Profile + knowledge packs

### L3.1 Copy profile

```bash
cp <pack>/library/legal.md library/legal.md
```

### L3.2 Verify frontmatter

```bash
head -20 library/legal.md
# Must show: name, title, key, aliases, psychotype, archiveModel, metric, status, version
```

### L3.3 Copy knowledge packs

```bash
mkdir -p library/knowledge/legal/jurisdictions
mkdir -p library/knowledge/legal/business-forms
cp <pack>/library/knowledge/legal/compatibility-matrix.md library/knowledge/legal/
cp <pack>/library/knowledge/legal/jurisdictions/*.md library/knowledge/legal/jurisdictions/
cp <pack>/library/knowledge/legal/business-forms/*.md library/knowledge/legal/business-forms/
```

### L3.4 Verify structure

```bash
ls library/knowledge/legal/jurisdictions/    # BY, RU, EU, US (.md)
ls library/knowledge/legal/business-forms/   # ooo, ip, selfemployed (.md)
```

### Acceptance L3

- [ ] Profile in library/legal.md, frontmatter valid
- [ ] 8 knowledge files: compatibility-matrix + 4 jurisdictions + 3 business-forms
- [ ] BY and ooo full (≥ 150 lines), others placeholders (≥ 60 lines)

### Commit

```bash
git add library/legal.md library/knowledge/legal/
git commit -m "[Phase L3] Add Legal profile + knowledge packs (4 jurisdictions, 3 business forms)"
```

---

## PHASE L4 — Skills

### L4.1 Copy skills

```bash
mkdir -p skills/fosved/legal
cp -r <pack>/skills/fosved/legal/* skills/fosved/legal/
```

### L4.2 Verify count and structure

```bash
find skills/fosved/legal -name "SKILL.md" | wc -l
# Expected: 10

for s in skills/fosved/legal/*/SKILL.md; do
  head -5 "$s" | grep -q "^name:" && echo "OK: $(dirname $s | xargs basename)" || echo "FAIL: $s"
done
```

### L4.3 Full vs placeholder verification

Expected sizes:
- `risk-mapping-protocol/SKILL.md` — full (~250 lines)
- `contract-drafting-discipline/SKILL.md` — full (~313 lines)
- `red-flag-detection/SKILL.md` — full (~323 lines)
- 7 others — placeholders (~64 lines), structurally valid

### Acceptance L4

- [ ] 10 skill folders with SKILL.md
- [ ] All have frontmatter
- [ ] 3 Tier-1 skills full
- [ ] 7 placeholders with TODO markers and clear "intent"

### Commit

```bash
git add skills/fosved/legal/
git commit -m "[Phase L4] Add Legal skills (10 total: 3 full Tier 1, 7 placeholders)"
```

---

## PHASE L5 — lib/legal.js with disclaimer + file publishing

### L5.1 Copy module

```bash
cp <pack>/lib/legal.js lib/legal.js
```

### L5.2 Verify loads

```bash
node -e "
const m = require('./lib/legal');
console.log('Exports:', Object.keys(m));
"
# Required exports:
# saveResult, verifyResult, runDailyCheck, runMonthlyReview,
# runQuarterlyMethodologyReview, searchArchive, getMetricSnapshot,
# listTemplates, getContextForRequest,
# loadJurisdiction, loadBusinessForm, loadCompatibilityMatrix,
# withDisclaimer, DISCLAIMER
```

### L5.3 Test knowledge loading

```bash
node -e "
const l = require('./lib/legal');
console.log('BY length:', l.loadJurisdiction('BY')?.length);
console.log('ooo length:', l.loadBusinessForm('ooo')?.length);
console.log('Disclaimer:', l.DISCLAIMER.substring(0, 50));
"
```

### L5.4 Test disclaimer application

```bash
node -e "
const l = require('./lib/legal');
const result = l.withDisclaimer('Sample legal analysis');
console.log(result.includes('перед подписанием'));  // should print true
"
```

### L5.5 (Optional) LLM bridge для свободного текста

Free-form `/legal <text>` обработка через LLM — это Phase L5.5, может быть отложена:
1. Parse intent (NDA / MSA / review / risk-map / ...)
2. Confirm context via inline keyboard (jurisdiction + form + counterparty)
3. Apply skills
4. Return draft + risk map + disclaimer
5. Save via saveResult()

В v1.0 пака acceptable placeholder responses.

### Acceptance L5

- [ ] Module loads
- [ ] All required exports present
- [ ] Knowledge loading works
- [ ] Disclaimer applied automatically by withDisclaimer()
- [ ] Archive integration uses archive-publisher
- [ ] Long documents published as files (готово к use, требует test в L8)

### Commit

```bash
git add lib/legal.js
git commit -m "[Phase L5] Add Legal business logic with disclaimer and file publishing"
```

---

## PHASE L6 — army.js + departments-registry.js

### L6.1 Apply army patch

Insert SPECIALISTS_ADDITIONS and SKILLS_MAP_ADDITIONS from `patches/army-legal-patch.js` into `army.js`.

Collision check:
```bash
node -e "
const army = require('./army.js');
const p = require('<pack>/patches/army-legal-patch.js');
for (const k of Object.keys(p.SPECIALISTS_ADDITIONS)) {
  if (army.SPECIALISTS[k] && army.SPECIALISTS[k] !== p.SPECIALISTS_ADDITIONS[k]) {
    console.log('COLLISION:', k);
  }
}
"
# Should print nothing (нет коллизий)
```

### L6.2 Apply registry patch

Add JS entry from `patches/registry-legal-patch.md` into `lib/departments-registry.js` (inside `departments: [...]`).

### L6.3 Verify

```bash
node -e "
const r = require('./lib/departments-registry');
const l = r.departments.find(d => d.slug === 'legal');
console.log('Status:', l.status);
console.log('Aliases:', l.aliases.length);
console.log('Triggers:', l.routingTriggers.length);
console.log('Required:', l.requiredContext?.map(c => c.key).join(', '));
console.log('Disclaimer flag:', l.mandatoryDisclaimer);
"
```

### Acceptance L6

- [ ] army.js loads, no collisions
- [ ] registry has legal entry with status: 'active'
- [ ] aliases.length ≥ 6
- [ ] triggers.length ≥ 20
- [ ] mandatoryDisclaimer: true

### Commit

```bash
git add army.js lib/departments-registry.js
git commit -m "[Phase L6] Register Legal in army.js and departments-registry.js"
```

---

## PHASE L7 — bot.js handlers + context flow

### L7.1 Apply handlers patch

Copy each `// === BEGIN ... === ... // === END ===` block from `patches/bot-legal-handlers.js` into `bot.js`.

**Important:** `pendingLegalContext` и `pendingLegalVerifications` — shared state, declare once near top of bot.js.

**Important callback handler:** Legal **расширяет** существующий `bot.on('callback_query', ...)` handler — нужно убедиться что Legal callbacks (`leg_jx`, `leg_bf`, `leg_cp`, `leg_cpjx`, `leg_verify`) добавлены в общий callback dispatcher или есть отдельный handler специально для Legal (предпочтительный путь).

### L7.2 Verify

```bash
node -c bot.js && echo "L7: bot.js compiles"
grep -c "/legal" bot.js   # ≥ 9 handler matches
```

### L7.3 Manual test (после старта bot)

```
/legal
→ shows help with 9 commands

/legal Договор для нового клиента
→ asks "Юрисдикция (наша сторона)?"
→ after BY: asks "Бизнес-форма (наша сторона)?"
→ after ООО: asks "Контрагент в другой юрисдикции?"
→ flow continues, context accumulated

/legal-archive
→ list of archive entries (or empty)

/legal-score
→ metric snapshot (pct-clean-signings)

/legal-verify <id>
→ inline keyboard with Clean/Rewrite/Dispute outcomes

/legal-templates
→ list templates (placeholder until Phase L5.5 loads them)
```

### Acceptance L7

- [ ] bot.js compiles
- [ ] 9 handlers registered
- [ ] /legal shows help
- [ ] Context flow works (4 layers: own JX → own form → cross? → counterparty JX)
- [ ] /legal-score works
- [ ] /legal-verify with inline keyboard works

### Commit

```bash
git add bot.js
git commit -m "[Phase L7] Add Legal bot handlers (9 commands + multi-layer context flow)"
```

---

## PHASE L8 — Scheduler tasks

### L8.1 Apply scheduler patch

Open `patches/scheduler-legal-patch.js`. Insert 3 marked blocks into `scheduler.js`:

- Daily 9:00 — `runDailyCheck` (may need 8:30 if 9:00 collision with v4.1 transition)
- Monthly 1st 10:30 — `runMonthlyReview`
- Quarterly 1st 11:30 (Jan/Apr/Jul/Oct) — `runQuarterlyMethodologyReview`

### L8.2 Collision check

```bash
grep -nE "h === 9|h === 10|h === 11" scheduler.js | sort -u
```

If 9:00 already occupied by other department's daily — change Legal daily to 8:30:
```js
if (m === 30 && h === 8) { ... }
```

### L8.3 Verify

```bash
node -e "require('./scheduler.js'); console.log('L8 OK')"
grep -c "legal" scheduler.js   # ≥ 3 mentions
```

### L8.4 Manual test

Add temporary test command:

```js
bot.onText(/^\/test-legal-monthly$/i, async (msg) => {
  if (msg.from.id !== OWNER_ID) return;
  const r = await dept.runMonthlyReview();
  await bot.sendMessage(msg.chat.id, `Test OK, review id ${r.id}, pctClean: ${r.pctCleanSignings}`);
});
```

Run `/test-legal-monthly`, check ARCHIVE_CHANNEL_ID for published message. Remove test command after verification.

### Acceptance L8

- [ ] scheduler.js loads
- [ ] 3 legal tasks registered
- [ ] No time collisions with other departments
- [ ] Manual test of runMonthlyReview succeeded
- [ ] Archive channel received publication

### Commit

```bash
git add scheduler.js
git commit -m "[Phase L8] Add Legal scheduler tasks (daily 9:00, monthly 10:30, quarterly 11:30)"
```

---

## PHASE L9 — Yana routing triggers

### L9.1 Triggers already in registry from L6

Done in L6.

### L9.2 Optional: update upravlenie.md (informational)

If maintaining human-readable routing docs, add Legal section per `patches/upravlenie-legal-routing-patch.md`.

### L9.3 Test routing (after Sweep 2 — Yana enhancement)

| Owner says | Expected route |
|---|---|
| "Сделай NDA для клиента" | Legal |
| "Прислали MSA, посмотри" | Legal (red-flag-detection) |
| "Можно работать с EU клиентом по GDPR?" | Legal (gdpr-compliance-check) |
| "Договор с самозанятым" | Legal (с предупреждением о risks переквалификации) |
| "Договор на 5000 EUR от Германии" | Legal + Finance |

Deferred verification if Sweep 2 not applied.

### Acceptance L9

- [ ] Triggers in registry (done in L6)
- [ ] Boundaries documented
- [ ] (Optional) upravlenie.md updated
- [ ] (Optional after Sweep 2) routing tested

### Commit

```bash
git add library/upravlenie.md  # if changed
git commit -m "[Phase L9] Register Legal routing in Yana" --allow-empty
```

---

## PHASE L10 — Polygon + acceptance

### L10.1 Polygon test cases

Create `migration_logs/legal_integration/polygon_cases.md`:

```md
# Legal Polygon — 5 Test Cases

## Case 1: NDA between BY ООО and EU GmbH
**Input:** "Сделай взаимное NDA для нового клиента из Германии, на 3 года"
**Expected:**
- Yana asks jurisdiction → BY (наша сторона)
- Yana asks businessForm → ooo
- Yana asks counterparty jurisdiction → EU
- Legal applies risk-mapping-protocol → contract-drafting-discipline → nda-msa-sla-templates
- Result: NDA текст + risk register + disclaimer
- Verification date = today + 90 days
- Archive publication: long document as file, summary as message

## Case 2: Red flag analysis of incoming MSA
**Input:** Прислан текст чужого MSA в /legal-review
**Expected:**
- Yana asks контекст (наша сторона)
- Legal applies red-flag-detection
- Result: CRITICAL/HIGH/MEDIUM/LOW red flags + counter-proposals + recommendation
- Archive publication

## Case 3: GDPR compliance check for SaaS
**Input:** "Можем ли мы продавать SaaS в Германию, какие GDPR требования?"
**Expected:**
- Legal загружает EU jurisdiction knowledge
- Применяет gdpr-compliance-check (placeholder — даёт базовый ответ + рекомендацию detail после наполнения)
- Возвращает list of mandatory items (DPO, DPA, SCC, consent, breach notification)
- Disclaimer: "для production — лицензированный юрист в EU"

## Case 4: Самозанятый contract drafting
**Input:** "Сделай договор с самозанятым из РФ на разработку"
**Expected:**
- Yana asks: своя jurisdiction + форма; counterparty: RU + selfemployed
- Legal загружает RU knowledge + selfemployed (placeholder)
- Применяет contract-drafting-discipline
- Important: WARNING о risk of misclassification + защитные формулировки
- Result: договор ГПХ + warning + disclaimer

## Case 5: Cross-jurisdictional dispute initial assessment
**Input:** "Клиент в US не оплатил, что делать?"
**Expected:**
- Legal asks: договор был? в какой юрисдикции? applicable law?
- Применяет dispute-resolution-strategy (placeholder — базовый ответ)
- Возвращает: 1) попытаться переговоры, 2) escalation procedure, 3) options для legal action в applicable law forum, 4) cost-benefit analysis
- Strong disclaimer
```

### L10.2 Run polygon

Manually run each case. Document results.

### L10.3 Pass-rate calculation

```
pass_rate = passed / total × 100
```

**Acceptance threshold: ≥ 70%** (min 4 из 5).

**Note:** Case 3 и Case 5 используют placeholder skills (gdpr-compliance-check, dispute-resolution-strategy) — для них acceptance criteria снижен: "честный placeholder response с правильным redirect + disclaimer = pass".

### L10.4 Document

`migration_logs/legal_integration/polygon_results.md`:

```md
# Legal Polygon Results

Date: <YYYY-MM-DD>

| Case | Skill applied | Pass/Fail | Notes |
|---|---|---|---|
| 1 NDA BY↔EU | risk-mapping + contract-drafting + nda-msa-sla-templates | PASS | ... |
| 2 Red flag review | red-flag-detection | PASS | ... |
| 3 GDPR | gdpr-compliance-check (placeholder) | PASS | honest placeholder response |
| 4 Самозанятый | contract-drafting + selfemployed knowledge | PASS | warning correctly included |
| 5 Dispute | dispute-resolution-strategy (placeholder) | PASS | base structure delivered |

Pass-rate: 5/5 = 100%

Notes:
- Knowledge gaps in placeholders identified, prioritize: gdpr-compliance-check (high demand)
- Archive file publishing tested successfully
```

### L10.5 Final smoke test

```bash
cd <project_root>
node -c bot.js
node -e "require('./army.js')"
node -e "require('./scheduler.js')"
node -e "require('./lib/legal')"
node -e "require('./lib/departments-registry')"
node scripts/audit_skills_map.js
node scripts/audit_registry.js

# DB check
node -e "
const { PrismaClient } = require('@prisma/client');
const db = new PrismaClient();
Promise.all([
  db.legalAssessment.count(),
  db.contractTemplate.count(),
  db.legalDocument.count(),
]).then(c => { console.log('Counts:', c); db.\$disconnect(); });
"
```

### Acceptance L10

- [ ] 5 polygon cases run
- [ ] Pass-rate ≥ 70%
- [ ] Results documented
- [ ] All smoke tests pass
- [ ] Disclaimer applied in every Legal output

### Final commit & merge

```bash
git add migration_logs/legal_integration/
git commit -m "[Phase L10] Polygon complete, Legal ready for merge"

# Owner reviews. If approved:
git checkout main
git merge --no-ff feature/legal-dept
git push origin main
```

---

## Rollback plan

```bash
# 1. Branch rollback
git checkout main
git branch -D feature/legal-dept

# 2. DB rollback
npx prisma migrate resolve --rolled-back add_legal_department

# 3. Restore from backup
cp prisma/schema.prisma.before-legal prisma/schema.prisma
cp army.js.before-legal army.js
cp lib/departments-registry.js.before-legal lib/departments-registry.js
npx prisma generate

# 4. Clean files if needed
rm -rf library/knowledge/legal/
rm -rf skills/fosved/legal/
rm lib/legal.js
rm library/legal.md
```

---

## Open questions / decisions for owner

- [ ] **Default jurisdiction:** Установить в `.env` `DEFAULT_LEGAL_JURISDICTION=BY` чтобы не спрашивать каждый раз? Cross-border сделки всё равно требуют counterparty явно.
- [ ] **Default businessForm:** аналогично.
- [ ] **External lawyer integration:** хочешь ли поле "lawyer for review" в LegalAssessment? Чтобы помечать кто из юристов уже review'ил.
- [ ] **Templates seeding:** в L5.5 загружать ли starter templates (NDA для BY/RU/EU/US × ooo/ip)? Это ~12 шаблонов, можно отложить.
- [ ] **Disclaimer text customization:** сейчас disclaimer общий, хочешь ли разный для критичных vs обычных сделок?
- [ ] **TODO в knowledge:** RU/EU/US юрисдикции + ИП/самозанятый — фоновое наполнение, без блокировки.
- [ ] **TODO в skills:** 7 placeholder скиллов наполняются по мере появления реальных кейсов.

После L10 successful → Legal готов. Финансы + Юрист — оба собраны. Можно идти к Sweep 0 (расчистка + единый реестр), потом разворачивать всё.
