# KUZNITSA_INTEGRATION_PLAN.md — Kuznitsa Department Add-on

**Block:** Kuznitsa (Кузница кадров / Veteran) Department Integration
**Target:** existing fosved-bot v4.1 + all prior departments
**Owner:** @ShkodnikAI (Telegram ID задаётся переменной OWNER_TELEGRAM_ID)
**Block version:** 1.0
**Date:** 2026-05
**Estimated effort:** 3 days focused work
**Risk level:** low (single department, additive, no modification of existing models)

---

## PURPOSE

Adds the Kuznitsa (Кузница кадров) — the **recursive department whose single
function is to create and re-train all the other departments**. Its specialist
is the Veteran. Built strictly per `METHODOLOGY.md` Part III.

The Kuznitsa is the methodology's capstone. Until now, the methodology
(METHODOLOGY.md) has been a document the owner and Claude applied by hand. The
Kuznitsa is that methodology turned into a working department — it runs the
10-stage checklist, the psychotype catalogue, the polygon, the structural
debrief, as operations of fosved-bot itself.

**The Kuznitsa is recursive** — it is built by the same methodology it teaches.
This is not a paradox; it is validation. If the methodology cannot produce the
Kuznitsa, it cannot produce anything. This package is itself a worked example
of the methodology applied: profile, 8 skills in 3 tiers, archive model,
commands, scheduler, learning loop, explicit psychotype.

Psychotype: **Методист + Параноик** — methodical process (checklists, polygon,
repeatable procedures) plus paranoid hunting of methodology holes.

---

## PREREQUISITES

- [x] fosved-bot v4.1 deployed
- [x] `ARCHIVE_CHANNEL_ID` configured

Depends only on v4.1. It is most *useful* once several departments exist and
accumulate archives (so there is something to debrief and retrain) — but it
integrates regardless of which other department blocks are applied.

---

## WHAT THIS BLOCK ADDS

- 1 profile: `library/kk.md` (Методист + Параноик)
- 8 SKILL.md files (5 Tier 1 + 2 Tier 2 + 1 Tier 3)
- 2 Prisma models (append-only)
- 1 lib module: `lib/kk.js`
- 7 bot commands
- 3 scheduler tasks
- Yana routing additions + the Kuznitsa/Yana boundary

---

## INTEGRATION PHASES

### Phase K1 — Foundation (low risk, < half day)

```bash
cd ~/repos/fosved-bot
git checkout main && git pull origin main
git checkout -b feature/kuznitsa-department
git push -u origin feature/kuznitsa-department
mkdir -p migration_logs/kuznitsa_integration
echo "Kuznitsa integration started $(date)" > migration_logs/kuznitsa_integration/started.md
git add migration_logs/
git commit -m "[Kuznitsa] Foundation: branch created"
git push origin feature/kuznitsa-department
```

**Acceptance:** branch exists.

---

### Phase K2 — Schema (low risk, half day)

2 new models appended to existing schema.

```bash
cp prisma/schema.prisma prisma/schema.prisma.backup_pre_kuznitsa
cat ~/kuznitsa-dept-integration/prisma/kk-schema.prisma >> prisma/schema.prisma
npx prisma validate
npx prisma migrate dev --name add_kuznitsa_department --create-only
cat prisma/migrations/*_add_kuznitsa_department/migration.sql | head -50
npx prisma migrate deploy
npx prisma generate

node -e "
const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
Promise.all([
  p.trainingSession.count(),
  p.kuznitsaMonthlyReview.count()
]).then(c => { console.log('Kuznitsa tables ready:', c); p.\$disconnect(); });
"
# Expected: [0,0]

git add prisma/
git commit -m "[Kuznitsa] Schema: 2 models"
git push origin feature/kuznitsa-department
```

**Acceptance:** 2 new tables, both empty.
**Rollback:** restore `schema.prisma.backup_pre_kuznitsa`, drop new tables.

---

### Phase K3 — lib module (low risk, few hours)

```bash
cp ~/kuznitsa-dept-integration/lib/kk.js lib/kk.js
node -e "const k = require('./lib/kk.js'); console.log('kk.js:', Object.keys(k).length, 'exports');"

git add lib/
git commit -m "[Kuznitsa] lib/kk.js engine"
git push origin feature/kuznitsa-department
```

**Acceptance:** module loads, exports listed.

---

### Phase K4 — Profile + skills (low risk, half day)

```bash
cp ~/kuznitsa-dept-integration/library/kk.md library/kk.md
mkdir -p skills/fosved/kk
cp -r ~/kuznitsa-dept-integration/skills/fosved/kk/. skills/fosved/kk/
find skills/fosved/kk -name SKILL.md | wc -l   # expect 8

git add library/ skills/
git commit -m "[Kuznitsa] profile + 8 skills"
git push origin feature/kuznitsa-department
```

**Acceptance:** profile present, 8 skills in place.

---

### Phase K5 — army.js registration (low risk, few hours)

Apply `patches/army-kk-patch.js` manually into `army.js`.

```bash
grep -c "fosved/kk" army.js   # expect 8
git add army.js
git commit -m "[Kuznitsa] army.js registration"
git push origin feature/kuznitsa-department
```

---

### Phase K6 — Bot commands (medium-low risk, half to 1 day)

Apply `patches/bot-kk-handlers.js` into `bot.js` — 7 handlers, anchored regexes.

```bash
node -c bot.js
# Telegram smoke test:
#   /forge-status                → Kuznitsa status (empty initially)
#   /recruit test-department     → recruit session opened, 10-stage checklist shown
#   /assess osp                  → psychotype assessment vs the II.2 catalogue
#   /debrief test-department     → debrief intake, non-accusatory framing shown
#   /recalibrate-dept test       → session opens "awaiting owner approval"
git add bot.js
git commit -m "[Kuznitsa] 7 commands"
git push origin feature/kuznitsa-department
```

---

### Phase K7 — Scheduler (low risk, few hours)

Apply `patches/scheduler-kk-patch.js` — 3 tasks (daily attention check, weekly
status, monthly aggregated review).

```bash
node -c scheduler.js
git add scheduler.js
git commit -m "[Kuznitsa] 3 scheduler tasks"
git push origin feature/kuznitsa-department
```

---

### Phase K8 — Yana routing + boundary (low risk, few hours)

Apply `patches/upravlenie-kk-routing-patch.md` into `library/upravlenie.md` —
the routing triggers AND the critical Kuznitsa/Yana boundary section.

```bash
git add library/upravlenie.md
git commit -m "[Kuznitsa] Yana routing + Kuznitsa/Yana boundary"
git push origin feature/kuznitsa-department
```

---

### Phase K9 — Smoke test + merge (half day)

Full journey test:

1. `/forge-status` → Kuznitsa status report works
2. `/recruit <test department>` → recruit session, 10-stage checklist initialized
3. `/train <existing department>` → training session opens
4. `/polygon <department>` → polygon intake works
5. `/debrief <department>` → debrief intake, non-accusatory framing
6. `/assess osp` → psychotype assessment against the catalogue (II.2)
7. `/recalibrate-dept <department>` → session opens "AWAITING OWNER APPROVAL"
8. Ask Yana "create a new department for X" → routes to Kuznitsa
9. Ask Yana "do <some work>" → routes to a working department, NOT the Kuznitsa
   (the Kuznitsa/Yana boundary holds)
10. Confirm `/recalibrate-dept` cannot be completed without approval being
    recorded

If all pass:

```bash
git checkout main
git merge feature/kuznitsa-department --no-ff -m "Add Kuznitsa department"
git push origin main
git tag v4.1-kuznitsa
git push origin v4.1-kuznitsa
```

---

## ACCEPTANCE CRITERIA FOR FULL BLOCK

- [ ] 2 new Prisma models created, both empty
- [ ] `library/kk.md` present
- [ ] 8 SKILL.md files in `skills/fosved/kk/`
- [ ] `lib/kk.js` loads
- [ ] 7 bot commands work
- [ ] 3 scheduler tasks registered
- [ ] Yana routes Kuznitsa queries; the Kuznitsa/Yana boundary holds
- [ ] `/recalibrate-dept` is owner-approval-gated
- [ ] Archive publishes Kuznitsa milestones (recruit, polygon, debrief, recalibrate)
- [ ] Smoke journey passes
- [ ] Merged to main, tagged `v4.1-kuznitsa`

---

## RISK PROFILE

All phases low risk — a single additive department, no existing model touched.
- K2 (schema): pure additive (only 2 models)
- K6 (commands): 7 commands, no prefix collisions
- Everything else: additive, isolated

Realistic effort: 3 days with a debugging buffer.

---

## A NOTE ON THE RECURSIVE NATURE

This package is the methodology applied to itself. The Kuznitsa was built by
running `METHODOLOGY.md` Part I's checklist on the Kuznitsa: it has the 7
architecture components, an explicit psychotype, hard rules, a 3-level learning
loop, 8 skills in 3 tiers (within the 8-15 band), an archive model, a numeric
metric. If this package looks like the other department packages — that is the
point. The methodology produced it the same way it produces every department.

The Kuznitsa applies its own skills to itself: `psychotype-assessment` checks
the Kuznitsa's own Методист + Параноик; `skill-quality-review` holds the
Kuznitsa's own 8 skills to the standard; the quarterly review debriefs the
Kuznitsa. A methodology that could not survive being applied to its own
enforcer would not be trustworthy. This one was.

---

## AFTER THIS BLOCK

fosved-bot has the Kuznitsa — and therefore a working mechanism to create and
improve departments as operations, not as manual project work. The natural
use of the Kuznitsa now (METHODOLOGY.md epilogue) is to run it on one existing
department as a pilot — Finance is recommended: clear metrics, transparent
verification, low error risk. That pilot gives the methodology its first real
feedback cycle, and the methodology moves toward version 1.1.

From here, new departments are created through `/recruit` rather than through
hand-built integration packs. The Kuznitsa is the office's capacity to grow
itself.

---

**End of KUZNITSA_INTEGRATION_PLAN.md**
