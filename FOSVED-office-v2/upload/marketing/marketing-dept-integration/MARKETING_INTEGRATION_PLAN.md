# MARKETING_INTEGRATION_PLAN.md — Marketing Department Add-on

**Block:** Marketing (Продвижение) Department Integration
**Target:** existing fosved-bot v4.1 + Visual + DDQ departments
**Owner:** @ShkodnikAI (Telegram ID 2044005421)
**Block version:** 1.0
**Date:** 2026-05
**Estimated effort:** 3-4 days focused work
**Risk level:** low (single department, additive, no modification of existing models)

---

## PURPOSE

Adds the Marketing department — market & audience research plus promotion of
products and services. Built per `METHODOLOGY.md`: it is the "Продукт/маркетинг"
department from the psychotype catalogue, psychotype **Эмпат + Экспериментатор**.

Works in two equal client modes: **internal** (Fosved's own bot/miniapp) and
**external** (third-party clients' products). Same methodology and archive;
external research data is reliability-tagged because it comes from the client.

After this block, fosved-bot can research markets and run verifiable promotion
campaigns — every campaign a forecast that gets checked against reality.

---

## PREREQUISITES

- [x] fosved-bot v4.1 deployed
- [x] Visual department deployed
- [x] DDQ departments deployed (or at least the schema/army patterns established)
- [x] `ARCHIVE_CHANNEL_ID` configured

If DDQ is not yet applied, this block still works standalone — it only depends
on v4.1. Apply order is flexible.

---

## WHAT THIS BLOCK ADDS

- 1 profile: `library/marketing.md` (Эмпат + Экспериментатор)
- 11 SKILL.md files (4 Tier 1 + 5 Tier 2 + 2 Tier 3)
- 5 Prisma models (append-only)
- 1 lib module: `lib/marketing.js`
- 8 bot commands
- 3 scheduler tasks
- Yana routing additions

---

## INTEGRATION PHASES

### Phase M1 — Foundation (low risk, < half day)

```bash
cd ~/repos/fosved-bot
git checkout main && git pull origin main
git checkout -b feature/marketing-department
git push -u origin feature/marketing-department
mkdir -p migration_logs/marketing_integration
echo "Marketing integration started $(date)" > migration_logs/marketing_integration/started.md
git add migration_logs/
git commit -m "[Marketing] Foundation: branch created"
git push origin feature/marketing-department
```

**Acceptance:** branch exists.

---

### Phase M2 — Schema (low risk, half day)

5 new models appended to existing schema.

```bash
cp prisma/schema.prisma prisma/schema.prisma.backup_pre_marketing
cat ~/marketing-dept-integration/prisma/marketing-schema.prisma >> prisma/schema.prisma
npx prisma validate
npx prisma migrate dev --name add_marketing_department --create-only
cat prisma/migrations/*_add_marketing_department/migration.sql | head -60
npx prisma migrate deploy
npx prisma generate

# Verify
node -e "
const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
Promise.all([
  p.marketResearch.count(),
  p.audienceSegment.count(),
  p.marketingCampaign.count(),
  p.campaignVerification.count(),
  p.marketingMonthlyReview.count()
]).then(c => { console.log('Marketing tables ready:', c); p.\$disconnect(); });
"
# Expected: [0,0,0,0,0]

git add prisma/
git commit -m "[Marketing] Schema: 5 models"
git push origin feature/marketing-department
```

**Acceptance:** 5 new tables, all empty.
**Rollback:** restore `schema.prisma.backup_pre_marketing`, drop new tables.

---

### Phase M3 — lib module (low risk, few hours)

```bash
cp ~/marketing-dept-integration/lib/marketing.js lib/marketing.js
node -e "const m = require('./lib/marketing.js'); console.log('marketing.js:', Object.keys(m).length, 'exports');"

git add lib/
git commit -m "[Marketing] lib/marketing.js engine"
git push origin feature/marketing-department
```

**Acceptance:** module loads, exports listed.

---

### Phase M4 — Profile + skills (low risk, half day)

```bash
cp ~/marketing-dept-integration/library/marketing.md library/marketing.md
mkdir -p skills/fosved/marketing
cp -r ~/marketing-dept-integration/skills/fosved/marketing/. skills/fosved/marketing/
find skills/fosved/marketing -name SKILL.md | wc -l   # expect 11

git add library/ skills/
git commit -m "[Marketing] profile + 11 skills"
git push origin feature/marketing-department
```

**Acceptance:** profile present, 11 skills in place.

---

### Phase M5 — army.js registration (low risk, few hours)

Apply `patches/army-marketing-patch.js` manually into `army.js` — add the
SPECIALISTS aliases and the 11 SKILLS_MAP entries.

```bash
grep -c "fosved/marketing" army.js   # expect 11
git add army.js
git commit -m "[Marketing] army.js registration"
git push origin feature/marketing-department
```

---

### Phase M6 — Bot commands (medium-low risk, 1 day)

Apply `patches/bot-marketing-handlers.js` into `bot.js` — 8 handlers. Use
anchored regexes so `/campaign-forecast` and `/campaign-verify` are not
captured by `/campaign`.

```bash
node -c bot.js
# Telegram smoke test:
#   /segment            → lists segments (empty initially)
#   /campaign           → lists campaigns (empty initially)
#   /marketing-score    → "no verified campaigns yet"
#   /market-research test topic
git add bot.js
git commit -m "[Marketing] 8 commands"
git push origin feature/marketing-department
```

---

### Phase M7 — Scheduler (low risk, few hours)

Apply `patches/scheduler-marketing-patch.js` — 3 tasks (daily verification-due
check, monthly performance review, quarterly methodology review).

```bash
node -c scheduler.js
git add scheduler.js
git commit -m "[Marketing] 3 scheduler tasks"
git push origin feature/marketing-department
```

---

### Phase M8 — Yana routing (low risk, few hours)

Apply `patches/upravlenie-marketing-routing-patch.md` into
`library/upravlenie.md` — triggers + boundary disambiguation (especially the
ОСП boundary, the most likely confusion).

```bash
git add library/upravlenie.md
git commit -m "[Marketing] Yana routing"
git push origin feature/marketing-department
```

---

### Phase M9 — Smoke test + merge (half day)

Full journey test:

1. `/market-research solo business operators` → research intake works
2. `/segment Fosved miniapp` → segmentation intake works
3. `/competitors business dashboards` → competitive analysis intake works
4. `/campaign promote Fosved miniapp` → campaign created (drafted)
5. `/campaign-forecast <id>` → forecast intake works
6. `/campaign-verify <id>` → verification intake works
7. `/marketing-score` → metrics report works
8. `/marketing-archive` → archive search works
9. Ask Yana a market-research question in natural language → routes to Marketing
10. Ask Yana a strategic-situation question → routes to ОСП (boundary holds)

If all pass:

```bash
git checkout main
git merge feature/marketing-department --no-ff -m "Add Marketing department"
git push origin main
git tag v4.1-marketing
git push origin v4.1-marketing
```

---

## ACCEPTANCE CRITERIA FOR FULL BLOCK

- [ ] 5 new Prisma models created, all empty
- [ ] `library/marketing.md` present
- [ ] 11 SKILL.md files in `skills/fosved/marketing/`
- [ ] `lib/marketing.js` loads
- [ ] 8 bot commands work
- [ ] 3 scheduler tasks registered
- [ ] Yana routes Marketing queries; ОСП boundary holds
- [ ] Archive publishes Marketing milestones (research, launches, verifications)
- [ ] Smoke journey passes
- [ ] Merged to main, tagged `v4.1-marketing`

---

## RISK PROFILE

All phases low risk — this is a single additive department:
- M2 (schema): pure additive, no existing model touched
- M6 (commands): only 8 commands; main caution is regex anchoring
  (`/campaign-forecast` / `/campaign-verify` vs `/campaign`)
- Everything else: additive, isolated

Realistic effort: 3-4 days with a debugging buffer.

---

## AFTER THIS BLOCK

fosved-bot will have 9 departments (OSP, ЛЗ, Expert, Visual, Dev, Design, QA,
Marketing, plus Yana). Several departments now accumulate verified archives —
the methodology's natural next step is the **Кузница кадров (Veteran)**, the
recursive department that creates and re-trains the others.

---

**End of MARKETING_INTEGRATION_PLAN.md**
