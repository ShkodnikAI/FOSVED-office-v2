# ENGINEERING_INTEGRATION_PLAN.md — Engineering Department Add-on

**Block:** Engineering (Инженерный) Department Integration
**Target:** existing fosved-bot v4.1 + Visual + DDQ + Marketing departments
**Owner:** @ShkodnikAI (Telegram ID задаётся переменной OWNER_TELEGRAM_ID)
**Block version:** 1.0
**Date:** 2026-05
**Estimated effort:** 3-4 days focused work
**Risk level:** low (single department, additive, no modification of existing models)

---

## PURPOSE

Adds the Engineering department — a **project assistant** that prepares
preliminary engineering calculations in three disciplines: structural mechanics
(load-bearing capacity of roofs, greenhouses, frames), hydraulics (hydraulic
lifts and drives), and power electronics (inverters and switching equipment for
wind generators and solar panels).

**Critical nature of this department.** It is an *assistant*, not the engineer
of record. It prepares roughly 80% of the engineering work — calculations,
option comparisons, load collection, sanity-checks, draft specifications — so
that a licensed engineer's time goes to judgment and sign-off. Every output
carries a disclaimer: the calculation is preliminary and requires review and
approval by a licensed engineer of the relevant discipline. The department
never signs, never carries responsibility, never delivers "ready to build".

This boundary is the same one Legal keeps (does not replace a lawyer) and
Finance keeps (does not replace an auditor). It is built into the hard rules,
the skills, the lifecycle, and the disclaimer applied to every output.

Psychotype: **Параноик + Педант** — paranoid search for failure modes and load
cases, pedantic precision with numbers, coefficients, dimensions, assumptions.

---

## PREREQUISITES

- [x] fosved-bot v4.1 deployed
- [x] `ARCHIVE_CHANNEL_ID` configured

Depends only on v4.1. Works whether or not Visual / DDQ / Marketing are applied.

---

## WHAT THIS BLOCK ADDS

- 1 profile: `library/engineering.md` (Параноик + Педант)
- 12 SKILL.md files (5 Tier 1 + 5 Tier 2 + 2 Tier 3)
- 5 Prisma models (append-only)
- 1 lib module: `lib/engineering.js`
- 8 bot commands
- 3 scheduler tasks
- Yana routing additions

---

## INTEGRATION PHASES

### Phase E1 — Foundation (low risk, < half day)

```bash
cd ~/repos/fosved-bot
git checkout main && git pull origin main
git checkout -b feature/engineering-department
git push -u origin feature/engineering-department
mkdir -p migration_logs/engineering_integration
echo "Engineering integration started $(date)" > migration_logs/engineering_integration/started.md
git add migration_logs/
git commit -m "[Engineering] Foundation: branch created"
git push origin feature/engineering-department
```

**Acceptance:** branch exists.

---

### Phase E2 — Schema (low risk, half day)

5 new models appended to existing schema.

```bash
cp prisma/schema.prisma prisma/schema.prisma.backup_pre_engineering
cat ~/engineering-dept-integration/prisma/engineering-schema.prisma >> prisma/schema.prisma
npx prisma validate
npx prisma migrate dev --name add_engineering_department --create-only
cat prisma/migrations/*_add_engineering_department/migration.sql | head -60
npx prisma migrate deploy
npx prisma generate

node -e "
const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
Promise.all([
  p.engineeringCalculation.count(),
  p.normReference.count(),
  p.designReview.count(),
  p.engineeringCalculationVerification.count(),
  p.engineeringMonthlyReview.count()
]).then(c => { console.log('Engineering tables ready:', c); p.\$disconnect(); });
"
# Expected: [0,0,0,0,0]

git add prisma/
git commit -m "[Engineering] Schema: 5 models"
git push origin feature/engineering-department
```

**Acceptance:** 5 new tables, all empty.
**Rollback:** restore `schema.prisma.backup_pre_engineering`, drop new tables.

---

### Phase E3 — lib module (low risk, few hours)

```bash
cp ~/engineering-dept-integration/lib/engineering.js lib/engineering.js
node -e "const e = require('./lib/engineering.js'); console.log('engineering.js:', Object.keys(e).length, 'exports');"

git add lib/
git commit -m "[Engineering] lib/engineering.js engine"
git push origin feature/engineering-department
```

**Acceptance:** module loads, exports listed.

---

### Phase E4 — Profile + skills (low risk, half day)

```bash
cp ~/engineering-dept-integration/library/engineering.md library/engineering.md
mkdir -p skills/fosved/engineering
cp -r ~/engineering-dept-integration/skills/fosved/engineering/. skills/fosved/engineering/
find skills/fosved/engineering -name SKILL.md | wc -l   # expect 12

git add library/ skills/
git commit -m "[Engineering] profile + 12 skills"
git push origin feature/engineering-department
```

**Acceptance:** profile present, 12 skills in place.

---

### Phase E5 — army.js registration (low risk, few hours)

Apply `patches/army-engineering-patch.js` manually into `army.js`.

```bash
grep -c "fosved/engineering" army.js   # expect 12
git add army.js
git commit -m "[Engineering] army.js registration"
git push origin feature/engineering-department
```

---

### Phase E6 — Bot commands (medium-low risk, 1 day)

Apply `patches/bot-engineering-handlers.js` into `bot.js` — 8 handlers. Use
anchored regexes so `/calc-norms`, `/calc-loadcases`, `/calc-verify`,
`/calc-review`, `/calc-show` are not captured by `/calc`.

```bash
node -c bot.js
# Telegram smoke test:
#   /calc                          → lists calculations (empty)
#   /calc строймеханика test roof  → calculation created, disclaimer shown
#   /eng-score                     → "no engineer-reviewed calculations yet"
#   /calc <bad-discipline> ...      → declines, explains the 3-discipline scope
git add bot.js
git commit -m "[Engineering] 8 commands"
git push origin feature/engineering-department
```

---

### Phase E7 — Scheduler (low risk, few hours)

Apply `patches/scheduler-engineering-patch.js` — 3 tasks.

```bash
node -c scheduler.js
git add scheduler.js
git commit -m "[Engineering] 3 scheduler tasks"
git push origin feature/engineering-department
```

---

### Phase E8 — Yana routing (low risk, few hours)

Apply `patches/upravlenie-engineering-routing-patch.md` into
`library/upravlenie.md` — triggers, the scope/responsibility note, boundary
disambiguation.

```bash
git add library/upravlenie.md
git commit -m "[Engineering] Yana routing"
git push origin feature/engineering-department
```

---

### Phase E9 — Smoke test + merge (half day)

Full journey test:

1. `/calc строймеханика greenhouse roof` → calculation created, disclaimer in the reply
2. `/calc-norms <id> ...` → norm-base intake works
3. `/calc-loadcases <id>` → load-case intake works
4. `/calc-verify <id>` → verification intake works
5. `/calc-review <id>` → engineer-review handoff works
6. `/calc-show <id>` → shows status, norms, disclaimer flag
7. `/eng-score` → metrics report works
8. `/eng-archive строймеханика` → archive filtered by discipline
9. Ask Yana "will this roof hold the snow" → routes to Engineering
10. Ask Yana an out-of-scope engineering request (e.g. a fire-safety
    calculation) → Yana / the department declines and explains the 3-discipline
    scope, rather than producing a result
11. Confirm every engineering reply carries the preliminary disclaimer

If all pass:

```bash
git checkout main
git merge feature/engineering-department --no-ff -m "Add Engineering department"
git push origin main
git tag v4.1-engineering
git push origin v4.1-engineering
```

---

## ACCEPTANCE CRITERIA FOR FULL BLOCK

- [ ] 5 new Prisma models created, all empty
- [ ] `library/engineering.md` present
- [ ] 12 SKILL.md files in `skills/fosved/engineering/`
- [ ] `lib/engineering.js` loads
- [ ] 8 bot commands work
- [ ] 3 scheduler tasks registered
- [ ] Yana routes engineering queries; out-of-scope requests declined
- [ ] **Every engineering output carries the preliminary disclaimer**
- [ ] Archive publishes engineering milestones with the preliminary marker
- [ ] Smoke journey passes
- [ ] Merged to main, tagged `v4.1-engineering`

---

## RISK PROFILE

All phases low risk — a single additive department, no existing model touched.
- E2 (schema): pure additive
- E6 (commands): 8 commands; main caution is regex anchoring
  (`/calc-*` vs `/calc`)
- Everything else: additive, isolated

The genuine risk in this department is not integration — it is *misuse*: a
preliminary calculation being mistaken for an approved design. That risk is
mitigated in the design itself (the disclaimer on every output, the
"assistant not engineer of record" hard rules, the engineer-review lifecycle).
The acceptance criteria require confirming the disclaimer is present and intact.

Realistic effort: 3-4 days with a debugging buffer.

---

## A NOTE ON USING THIS DEPARTMENT

The Engineering department makes a licensed engineer faster — it prepares the
groundwork. It does not remove the need for one. Any calculation that will
inform a real build, installation, or manufacture must be reviewed, approved,
and signed by a licensed engineer of the relevant discipline. The department's
outputs are explicitly preliminary, by design and by disclaimer. Used that
way — as a fast, disciplined assistant to a real engineer — it is valuable.
Used as a replacement for one, it is dangerous. The design enforces the former.

---

## AFTER THIS BLOCK

fosved-bot will have 10 departments (OSP, ЛЗ, Expert, Visual, Dev, Design, QA,
Marketing, Engineering, plus Yana). With many departments now accumulating
verified archives, the methodology's natural next step is the **Кузница кадров
(Veteran)** — the recursive department that creates and re-trains all the
others.

---

**End of ENGINEERING_INTEGRATION_PLAN.md**
