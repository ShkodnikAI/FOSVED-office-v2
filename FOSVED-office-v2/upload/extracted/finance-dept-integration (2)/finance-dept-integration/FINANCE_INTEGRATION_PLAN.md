# FINANCE_INTEGRATION_PLAN.md

**Department:** Финансы (`finance`)
**Version:** 1.0
**Target:** fosved-bot v4.1+ (после Sweep 0 + transition pack)
**Phases:** F1..F10

---

## Prerequisites — must be true before starting

- [ ] Sweep 0 (расчистка) применён — есть `lib/departments-registry.js`
- [ ] v4.1 transition pack развёрнут — есть `lib/archive-publisher.js`
- [ ] `ARCHIVE_CHANNEL_ID` сконфигурирован в `.env`
- [ ] Branch `feature/finance-dept` готов к созданию
- [ ] Бэкап `prisma/schema.prisma` сделан

If any of these are false — STOP and resolve first.

---

## Phase status table

| Phase | Status | Started | Completed |
|---|---|---|---|
| F1 — Setup branch & prerequisites | not started | — | — |
| F2 — Prisma schema (5 models) | not started | — | — |
| F3 — library/finance.md + knowledge packs | not started | — | — |
| F4 — Skills (9 in skills/fosved/finance/) | not started | — | — |
| F5 — lib/finance.js + processQuery LLM logic | not started | — | — |
| F6 — army.js + departments-registry.js | not started | — | — |
| F7 — bot.js handlers + jurisdictionа/form context flow | not started | — | — |
| F8 — Scheduler tasks (daily 8:00, monthly 10:00, quarterly 11:00) | not started | — | — |
| F9 — Yana routing triggers in registry | not started | — | — |
| F10 — Polygon (5 test cases) + acceptance | not started | — | — |

---

## PHASE F1 — Setup branch & prerequisites

### F1.1 Verify prerequisites

```bash
cd <project_root>
git status                              # clean
grep -q "ARCHIVE_CHANNEL_ID" .env       # configured
test -f lib/archive-publisher.js && echo OK   # exists
test -f lib/departments-registry.js && echo OK # exists (from Sweep 0)
```

### F1.2 Create branch

```bash
git checkout -b feature/finance-dept
```

### F1.3 Verify pack contents

```bash
cd <path_to_pack>/finance-dept-integration
find . -type f | wc -l    # expect 24+ files
ls library/                # finance.md, knowledge/
ls library/knowledge/finance/jurisdictions/    # BY/RU/EU/US
ls library/knowledge/finance/business-forms/   # ooo/ip/selfemployed
ls skills/fosved/finance/  # 9 skill folders
ls patches/                # 5 patch files
```

### F1.4 Backup

```bash
cp prisma/schema.prisma prisma/schema.prisma.before-finance
cp army.js army.js.before-finance
cp lib/departments-registry.js lib/departments-registry.js.before-finance
```

### Acceptance F1

- [ ] Branch created
- [ ] All prerequisites verified
- [ ] All 24+ pack files present
- [ ] Backups created

### Smoke test F1

```bash
node -c bot.js && echo "F1: bot.js compiles"
node -e "require('./army.js'); console.log('F1: army.js loaded')"
node -e "require('./lib/departments-registry'); console.log('F1: registry loaded')"
```

### Commit

```bash
git add prisma/schema.prisma.before-finance army.js.before-finance lib/departments-registry.js.before-finance
git commit -m "[Phase F1] Setup branch and backup for Finance integration"
```

---

## PHASE F2 — Prisma schema (5 models)

### F2.1 Append schema

Append contents of `prisma/finance-schema.prisma` to main `prisma/schema.prisma`. Verify no collisions:

```bash
grep "^model " <pack>/prisma/finance-schema.prisma | awk '{print $2}' > /tmp/new_models.txt
grep "^model " prisma/schema.prisma | awk '{print $2}' > /tmp/existing_models.txt
comm -12 <(sort /tmp/new_models.txt) <(sort /tmp/existing_models.txt)
# Should be empty
```

Expected new models:
- `FinancialForecast` (main archive)
- `FinancialForecastVerification`
- `FinanceMonthlyReview`
- `Invoice`
- `Payment`

If existing project already has `Invoice` model — STOP. Merge logic carefully (Finance Invoice has direction field for AR/AP).

### F2.2 Generate client

```bash
npx prisma generate
```

### F2.3 Create migration (review before apply)

```bash
npx prisma migrate dev --name "add_finance_department" --create-only
cat prisma/migrations/$(ls -t prisma/migrations | head -1)/migration.sql
```

### F2.4 Apply

```bash
npx prisma migrate dev
```

### F2.5 DB smoke test

```bash
node -e "
const { PrismaClient } = require('@prisma/client');
const db = new PrismaClient();
Promise.all([
  db.financialForecast.count(),
  db.invoice.count(),
  db.payment.count(),
]).then(counts => { console.log('Counts:', counts); db.\$disconnect(); });
"
```

### Acceptance F2

- [ ] Schema appended without conflicts
- [ ] Migration created and reviewed
- [ ] Migration applied
- [ ] DB connection works, all 5 tables exist

### Commit

```bash
git add prisma/
git commit -m "[Phase F2] Add Finance Prisma models (5 models)"
```

---

## PHASE F3 — library/finance.md + knowledge packs

### F3.1 Copy profile

```bash
cp <pack>/library/finance.md library/finance.md
```

### F3.2 Verify frontmatter

```bash
head -20 library/finance.md
# Must show YAML with: name, title, key, aliases, psychotype, archiveModel, metric, status, version
```

### F3.3 Copy knowledge packs

```bash
mkdir -p library/knowledge/finance/jurisdictions
mkdir -p library/knowledge/finance/business-forms
cp <pack>/library/knowledge/finance/compatibility-matrix.md library/knowledge/finance/
cp <pack>/library/knowledge/finance/jurisdictions/*.md library/knowledge/finance/jurisdictions/
cp <pack>/library/knowledge/finance/business-forms/*.md library/knowledge/finance/business-forms/
```

### F3.4 Verify structure

```bash
ls library/knowledge/finance/
ls library/knowledge/finance/jurisdictions/    # BY, RU, EU, US (.md)
ls library/knowledge/finance/business-forms/   # ooo, ip, selfemployed (.md)
```

### Acceptance F3

- [ ] Profile in library/finance.md, frontmatter valid
- [ ] 7 knowledge files: compatibility-matrix + 4 jurisdictions + 3 business-forms
- [ ] BY и ooo полные (>150 строк каждый), остальные плейсхолдеры (>90 строк)

### Commit

```bash
git add library/finance.md library/knowledge/finance/
git commit -m "[Phase F3] Add Finance profile + knowledge packs (4 jurisdictions, 3 business forms)"
```

---

## PHASE F4 — Skills (9 skills in skills/fosved/finance/)

### F4.1 Copy skills

```bash
mkdir -p skills/fosved/finance
cp -r <pack>/skills/fosved/finance/* skills/fosved/finance/
```

### F4.2 Verify count and structure

```bash
find skills/fosved/finance -name "SKILL.md" | wc -l
# Expected: 9

for s in skills/fosved/finance/*/SKILL.md; do
  head -5 "$s" | grep -q "^name:" && echo "OK: $(dirname $s | xargs basename)" || echo "FAIL: $s"
done
```

### F4.3 Verify full vs placeholder

Expected:
- `cashflow-forecasting/SKILL.md` — full (~275 lines)
- `invoice-lifecycle-management/SKILL.md` — full (~260 lines)
- `unit-economics-calculation/SKILL.md` — full (~290 lines)
- 6 others — placeholders (~85 lines each), structurally valid

### Acceptance F4

- [ ] 9 skill folders with SKILL.md
- [ ] All have frontmatter (name, description, tier)
- [ ] 3 Tier-1 skills full, 6 others placeholders with TODO markers

### Commit

```bash
git add skills/fosved/finance/
git commit -m "[Phase F4] Add Finance skills (9 total: 3 full Tier 1, 6 placeholders)"
```

---

## PHASE F5 — lib/finance.js

### F5.1 Copy module

```bash
cp <pack>/lib/finance.js lib/finance.js
```

### F5.2 Verify loads

```bash
node -e "
const m = require('./lib/finance');
console.log('Exports:', Object.keys(m));
"
# Required exports:
# saveResult, verifyResult, runDailyCheck, runMonthlyReview,
# runQuarterlyMethodologyReview, searchArchive, getMetricSnapshot,
# getContextForRequest, loadJurisdiction, loadBusinessForm,
# loadCompatibilityMatrix
```

### F5.3 Test knowledge loading

```bash
node -e "
const f = require('./lib/finance');
console.log('BY length:', f.loadJurisdiction('BY')?.length);
console.log('ooo length:', f.loadBusinessForm('ooo')?.length);
"
# Both should print non-null numbers
```

### F5.4 (Optional) Implement processQuery LLM bridge

The free-form `/finance <text>` handler needs LLM bridging:
1. Parse intent (cashflow / invoice / tax / unit-economics)
2. Confirm jurisdiction + businessForm via inline keyboard
3. Apply appropriate skill
4. Save result

This logic can be added in F5.4 or postponed to a later iteration — placeholder responses are acceptable for v1.

### Acceptance F5

- [ ] Module loads
- [ ] All required exports present
- [ ] Knowledge loading works
- [ ] Archive integration uses `archive-publisher`

### Commit

```bash
git add lib/finance.js
git commit -m "[Phase F5] Add Finance business logic (lib/finance.js)"
```

---

## PHASE F6 — army.js + departments-registry.js

### F6.1 Apply army patch

Open `patches/army-finance-patch.js`. Insert `SPECIALISTS_ADDITIONS` and `SKILLS_MAP_ADDITIONS` into `army.js`. After:

```bash
# Collision check
node -e "
const army = require('./army.js');
const p = require('<pack>/patches/army-finance-patch.js');
for (const k of Object.keys(p.SPECIALISTS_ADDITIONS)) {
  if (army.SPECIALISTS[k] && army.SPECIALISTS[k] !== p.SPECIALISTS_ADDITIONS[k]) {
    console.log('COLLISION:', k, '->', army.SPECIALISTS[k]);
  }
}
"
# Should print nothing
```

### F6.2 Apply registry patch

Open `patches/registry-finance-patch.md`. Add the JS entry to `lib/departments-registry.js` (inside `departments: [...]` array).

### F6.3 Verify

```bash
node -e "
const r = require('./lib/departments-registry');
const f = r.departments.find(d => d.slug === 'finance');
console.log('Status:', f.status);
console.log('Aliases:', f.aliases.length);
console.log('Triggers:', f.routingTriggers.length);
"
```

### Acceptance F6

- [ ] army.js loads, no collisions
- [ ] registry has finance entry with status: 'active'
- [ ] aliases.length ≥ 5, triggers.length ≥ 15

### Commit

```bash
git add army.js lib/departments-registry.js
git commit -m "[Phase F6] Register Finance in army.js and departments-registry.js"
```

---

## PHASE F7 — bot.js handlers + context flow

### F7.1 Apply handlers patch

Open `patches/bot-finance-handlers.js`. Copy each `// === BEGIN ... === ... // === END ===` block into `bot.js`. Each handler has its own block.

Important: `pendingFinanceContext` and `pendingVerifications` are **shared state** — declare them once near top of bot.js (or use existing pattern from current handlers).

### F7.2 Verify

```bash
node -c bot.js && echo "F7: bot.js compiles"
grep -c "/finance" bot.js   # Several handler matches
```

### F7.3 Manual test

After starting the bot:

```
/finance
→ should show help text

/finance Сколько денег к концу июня?
→ should ask jurisdiction (BY/RU/EU/US)
→ after selecting BY, should ask businessForm
→ after selecting ooo, should acknowledge context

/finance-invoice
→ list of invoices (or empty if none)

/finance-score
→ metric snapshot (mape-cashflow)

/finance-archive
→ archive search
```

### Acceptance F7

- [ ] bot.js compiles
- [ ] All 7+ handlers registered
- [ ] /finance shows help
- [ ] Context flow (jurisdiction → businessForm) works
- [ ] /finance-score works

### Commit

```bash
git add bot.js
git commit -m "[Phase F7] Add Finance bot handlers (7 commands + context flow)"
```

---

## PHASE F8 — Scheduler tasks

### F8.1 Apply scheduler patch

Open `patches/scheduler-finance-patch.js`. Insert 3 marked blocks into `scheduler.js`:

- Daily 8:00 — `runDailyCheck`
- Monthly 1st 10:00 — `runMonthlyReview`
- Quarterly 1st 11:00 (Jan/Apr/Jul/Oct) — `runQuarterlyMethodologyReview`

### F8.2 Verify

```bash
node -e "require('./scheduler.js'); console.log('F8 OK')"
grep -c "finance" scheduler.js   # ≥ 3 mentions
```

### F8.3 Manual test

Temporarily add a test command to trigger monthly review without waiting:

```js
bot.onText(/^\/test-finance-monthly$/i, async (msg) => {
  if (msg.from.id !== OWNER_ID) return;
  const r = await dept.runMonthlyReview();
  await bot.sendMessage(msg.chat.id, `Test OK, review id ${r.id}`);
});
```

Run `/test-finance-monthly` → check ARCHIVE_CHANNEL_ID for published message. Remove test command after verification.

### Acceptance F8

- [ ] scheduler.js loads
- [ ] 3 finance tasks registered
- [ ] Manual test of runMonthlyReview succeeded
- [ ] Archive channel received the test publication

### Commit

```bash
git add scheduler.js
git commit -m "[Phase F8] Add Finance scheduler tasks (daily 8:00, monthly 10:00, quarterly 11:00)"
```

---

## PHASE F9 — Yana routing triggers

### F9.1 Triggers already in registry from F6

Phase F6 already added `routingTriggers` to registry entry. Yana picks them up automatically.

### F9.2 Optional: update upravlenie.md

If you maintain human-readable routing docs in `library/upravlenie.md`, add a Finance section per `patches/upravlenie-finance-routing-patch.md`.

### F9.3 Test routing (after Sweep 2 — Yana enhancement)

| Owner says | Expected route |
|---|---|
| "Сколько денег к концу июня?" | Finance |
| "Просроченные инвойсы" | Finance |
| "VAT в Германии?" | Finance |
| "Окупается ли реклама на 5000?" | Finance + Marketing |

If Sweep 2 not yet applied — mark this phase as "deferred verification".

### Acceptance F9

- [ ] Routing triggers in registry (done in F6)
- [ ] Boundaries documented
- [ ] (Optional) upravlenie.md updated
- [ ] (Optional after Sweep 2) routing tested

### Commit

```bash
git add library/upravlenie.md  # if changed
git commit -m "[Phase F9] Register Finance routing in Yana"
```

---

## PHASE F10 — Polygon + acceptance

### F10.1 Polygon test cases

Create `migration_logs/finance_integration/polygon_cases.md`:

```md
# Finance Polygon — 5 Test Cases

## Case 1: Cashflow forecast — BY ООО, 30 days
**Input:** "Прогноз cashflow на 30 дней, ООО, BYN"
**Expected:**
- Yana asks jurisdiction → BY
- Yana asks businessForm → ooo
- Finance applies cashflow-forecasting skill
- Result has verification date = today + 30 days
- Archive publication succeeds

## Case 2: Invoice listing
**Input:** "Покажи просроченные инвойсы"
**Expected:**
- Finance returns list, sorted by dueDate
- Each item shows: id, status, amount, currency, overdue days

## Case 3: Tax calculation — RU ООО НДС
**Input:** "НДС на 100 000 рублей в РФ"
**Expected:**
- Finance loads RU jurisdiction
- Returns: 20 000 ₽ (20% от чистой суммы 100 000) OR 16 666.67 ₽ (20% / 120% от суммы с НДС)
- Asks clarification: "включая НДС или без?"

## Case 4: Unit economics CAC — недостаточно данных
**Input:** "CAC за последний месяц"
**Expected:**
- Finance checks: есть ли marketing_spend и new_customers за период?
- If нет → честно отвечает "недостаточно данных, нужны marketing_spend и new_customers за месяц"

## Case 5: Cross-jurisdictional — BY-резидент с EU-клиентами
**Input:** "Я BY-резидент, выставил инвойс на 5000 EUR клиенту в Германии. Какие налоги?"
**Expected:**
- Finance подгружает BY (юрисдикция продавца) + EU (юрисдикция покупателя)
- Reverse charge B2B → VAT 0% в инвойсе
- BY: валютный контроль + 18% налог на прибыль (или 9% ПВТ)
- Подсказывает: "уточните был ли договор зарегистрирован в банке"
```

### F10.2 Run polygon

Manually run each case through Finance department. Note results.

### F10.3 Pass-rate calculation

```
pass_rate = passed / total × 100
```

Acceptance threshold: **≥ 70%** (минимум 4 из 5).

### F10.4 Document

Create `migration_logs/finance_integration/polygon_results.md` with case-by-case results.

### F10.5 Final smoke test

```bash
cd <project_root>
node -c bot.js
node -e "require('./army.js')"
node -e "require('./scheduler.js')"
node -e "require('./lib/finance')"
node -e "require('./lib/departments-registry')"
node scripts/audit_skills_map.js
node scripts/audit_registry.js

# DB check
node -e "
const { PrismaClient } = require('@prisma/client');
const db = new PrismaClient();
db.financialForecast.count().then(c => { console.log('FinancialForecast rows:', c); db.\$disconnect(); });
"
```

### Acceptance F10

- [ ] 5 polygon cases run
- [ ] Pass-rate ≥ 70%
- [ ] Results documented in migration_logs/
- [ ] All smoke tests pass

### Final commit & merge

```bash
git add migration_logs/finance_integration/
git commit -m "[Phase F10] Polygon complete, Finance ready for merge"

# Owner reviews. If approved:
git checkout main
git merge --no-ff feature/finance-dept
git push origin main
```

---

## Rollback plan (master)

If integration must be rolled back:

```bash
# 1. Roll back branch
git checkout main
git branch -D feature/finance-dept

# 2. Roll back DB
npx prisma migrate resolve --rolled-back add_finance_department
# Note: this marks rolled-back but doesn't drop tables.
# For full rollback, restore schema from backup and regenerate.

# 3. Restore from backup
cp prisma/schema.prisma.before-finance prisma/schema.prisma
cp army.js.before-finance army.js
cp lib/departments-registry.js.before-finance lib/departments-registry.js
npx prisma generate

# 4. Remove copied files (if branch was deleted but files committed elsewhere)
rm -rf library/knowledge/finance/
rm -rf skills/fosved/finance/
rm lib/finance.js
rm library/finance.md
```

---

## Open questions / decisions for owner

- [ ] **Default jurisdiction:** хочешь ли установить дефолт (например, BY) чтобы Yana не спрашивала каждый раз? Если да — добавить в `.env` `DEFAULT_JURISDICTION=BY`.
- [ ] **Default businessForm:** аналогично.
- [ ] **Knowledge updates:** кто отвечает за обновление налоговых ставок? (RU/EU/US часто меняются)
- [ ] **TODO в skills:** 6 плейсхолдер-скиллов нужны к когда? — фоновая задача без блокировки.
- [ ] **TODO в knowledge:** RU/EU/US/ИП/самозанятый — наполнение фоновое, без блокировки.

После F10 successful — Finance готов. Закрываем интеграцию, переходим к Legal pack.
