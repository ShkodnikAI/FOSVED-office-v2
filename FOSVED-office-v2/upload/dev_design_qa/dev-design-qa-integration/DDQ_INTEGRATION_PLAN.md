# DDQ_INTEGRATION_PLAN.md — Dev + Design + QA Departments Add-on

**Block:** Three-Department Integration (Разработка, Дизайн, Тестирование)
**Target:** existing fosved-bot v4.1 + Visual Department already deployed
**Owner:** @ShkodnikAI (Telegram ID 2044005421)
**Block version:** 1.0
**Date:** 2026-05-15
**Estimated duration:** 12-16 days of focused work, realistic 4-5 weeks with buffers
**Risk level:** medium (3 new departments, GitHub/file integration, significant scope)

---

## PURPOSE OF THIS BLOCK

This block adds three production-grade technical departments to the running fosved-bot:

1. **Разработка (Dev)** — full-stack engineering: web apps, sites, AI offices, local AI models
2. **Дизайн (Design)** — UI/UX design, design systems, prototypes, accessibility
3. **Тестирование (QA)** — comprehensive testing including AI-specific evals

After this block, fosved-bot will be able to **execute software projects end-to-end** — design, build, test, ship, monitor. Code lives in real GitHub repos. Critical artifacts archived in Telegram. On-demand sync to local server (when available).

---

## PREREQUISITES

Before applying this block, fosved-bot must have:

- [x] v4.1 migration complete (OSP V2, ЛЗ, Expert, Yana, archive channel)
- [x] Visual Department deployed (v4.1-visual tag)
- [x] GITHUB_TOKEN configured in Render env with `repo` and `workflow` scopes
- [x] ARCHIVE_CHANNEL_ID configured
- [x] Branch `feature/ddq-departments` ready to create

If any of these missing — STOP. Apply previous packs first.

---

## WHAT THIS BLOCK ADDS

### Departments (3)

**Разработка (Dev) — full profile:**
- Profile: `library/dev.md`
- 20 SKILL.md files (5 Tier 1 + 12 Tier 2 + 3 Tier 3)
- Психотип: Прагматик + Методист
- Архив: DevTask, ArchitectureDecision, TechRadarEntry, CodeRepository
- Commands: 14 new
- Self-improvement: tech radar quarterly review + estimate calibration

**Дизайн (Design):**
- Profile: `library/design.md`
- 11 SKILL.md files (4 Tier 1 + 5 Tier 2 + 2 Tier 3)
- Психотип: Эмпат + Перфекционист
- Архив: DesignArtifact, DesignDecision, UserResearchSession
- Commands: 8 new

**Тестирование (QA):**
- Profile: `library/qa.md`
- 11 SKILL.md files (4 Tier 1 + 5 Tier 2 + 2 Tier 3) — including AI-specific testing
- Психотип: Параноик + Педант
- Архив: TestRun, DefectRecord, SecurityAudit, AIEvalRun
- Commands: 9 new

### Storage architecture (code triple-storage)

**Primary: GitHub.** Real repositories. Created and maintained via Octokit. Each project = own repo. CI/CD via GitHub Actions where applicable. PR-based review workflow even for one-owner setup (creates discipline + paper trail).

**Secondary: Telegram Archive.** Code snapshots at major milestones (initial commit, v1.0 release, post-bugfix milestones) pushed as documents to ARCHIVE_CHANNEL_ID with hashtags. Acts as immutable historical record + offline browsable archive.

**Tertiary (deferred): Local server.** When owner sets up local server, command `/dev-sync local <repo>` downloads from GitHub to local server folder. This is on-demand only — automatic sync when owner has connection. Not part of v1.0; placeholder hook ready for activation.

### Department interaction patterns

Three departments work as production pipeline:

```
[Concept] → Design → Dev → QA → [Production] → QA monitor
                    ↑ ↓        ↑ ↓
                    iteration  iteration
```

For simple tasks: Yana may skip Design and/or QA based on task class.
For critical projects: full pipeline with iteration cycles.

### Tension by design

Three departments have **deliberately conflicting psychotypes**:
- Dev (Прагматик): "ship it, iterate"
- Design (Перфекционист): "polish first"
- QA (Параноик): "find every defect"

Yana mediates. This tension is feature not bug — it produces robust outcomes.

---

## INTEGRATION PHASES

### Phase Y1 — Foundation (very low risk, half day)

```bash
cd ~/repos/fosved-bot
git checkout main
git pull origin main
git checkout -b feature/ddq-departments
git push -u origin feature/ddq-departments

# Verify prerequisites
ls library/expert.md library/visual.md library/lz.md  # all 3 must exist
ls lib/research.js lib/visual.js lib/archive-publisher.js
echo "$GITHUB_TOKEN" | head -c 10  # verify token set in env

mkdir -p migration_logs/ddq_integration
echo "DDQ integration started $(date)" > migration_logs/ddq_integration/started.md

git add migration_logs/
git commit -m "[DDQ] Foundation: branch created"
git push origin feature/ddq-departments
```

**Acceptance:** branch exists, prereqs confirmed.

---

### Phase Y2 — Schema additions (low risk, half day)

10+ new models appended to existing schema:

```bash
cd ~/repos/fosved-bot
cp prisma/schema.prisma prisma/schema.prisma.backup_pre_ddq
cat ~/dev-design-qa-integration/prisma/ddq-schema.prisma >> prisma/schema.prisma
npx prisma validate
npx prisma migrate dev --name add_ddq_departments --create-only
cat prisma/migrations/*_add_ddq_departments/migration.sql | head -100
npx prisma migrate deploy
npx prisma generate

# Verify new tables
node -e "
const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
Promise.all([
  p.devTask.count(),
  p.architectureDecision.count(),
  p.techRadarEntry.count(),
  p.codeRepository.count(),
  p.designArtifact.count(),
  p.designDecision.count(),
  p.userResearchSession.count(),
  p.testRun.count(),
  p.defectRecord.count(),
  p.securityAudit.count(),
  p.aiEvalRun.count()
]).then(counts => {
  console.log('Tables ready:', counts);
  p.\$disconnect();
});
"
# Expected: all zeros (empty tables)

git add prisma/
git commit -m "[DDQ] Schema: 11 new models for Dev + Design + QA"
git push origin feature/ddq-departments
```

**Acceptance:** 11 new tables, all empty, Prisma client regenerates.
**Rollback:** restore schema.prisma.backup_pre_ddq, drop new tables.

---

### Phase Y3 — Library modules (1 day)

```bash
cd ~/repos/fosved-bot
cp ~/dev-design-qa-integration/lib/dev.js lib/dev.js
cp ~/dev-design-qa-integration/lib/design.js lib/design.js
cp ~/dev-design-qa-integration/lib/qa.js lib/qa.js
cp ~/dev-design-qa-integration/lib/github-client.js lib/github-client.js

# Verify modules load
node -e "
const dev = require('./lib/dev.js');
const design = require('./lib/design.js');
const qa = require('./lib/qa.js');
const gh = require('./lib/github-client.js');
console.log('dev:', Object.keys(dev).length, 'exports');
console.log('design:', Object.keys(design).length, 'exports');
console.log('qa:', Object.keys(qa).length, 'exports');
console.log('github:', Object.keys(gh).length, 'exports');
"

git add lib/
git commit -m "[DDQ] lib modules: dev.js, design.js, qa.js, github-client.js"
git push origin feature/ddq-departments
```

**Acceptance:** all 4 modules load without errors, exports listed.

---

### Phase Y4 — Profiles + skills (1.5 days)

```bash
cd ~/repos/fosved-bot

# Profiles
cp ~/dev-design-qa-integration/library/dev.md library/dev.md
cp ~/dev-design-qa-integration/library/design.md library/design.md
cp ~/dev-design-qa-integration/library/qa.md library/qa.md

# Dev skills (20)
mkdir -p skills/fosved/dev
cp -r ~/dev-design-qa-integration/skills/fosved/dev/. skills/fosved/dev/
find skills/fosved/dev -name SKILL.md | wc -l   # expect 20

# Design skills (11)
mkdir -p skills/fosved/design
cp -r ~/dev-design-qa-integration/skills/fosved/design/. skills/fosved/design/
find skills/fosved/design -name SKILL.md | wc -l   # expect 11

# QA skills (11)
mkdir -p skills/fosved/qa
cp -r ~/dev-design-qa-integration/skills/fosved/qa/. skills/fosved/qa/
find skills/fosved/qa -name SKILL.md | wc -l   # expect 11

git add library/ skills/
git commit -m "[DDQ] 3 profiles + 42 SKILL.md files"
git push origin feature/ddq-departments
```

**Acceptance:** 3 profiles present, 42 skills total in correct directories.

---

### Phase Y5 — Army.js registration (low risk, few hours)

```bash
cd ~/repos/fosved-bot

# Apply patches from
cat ~/dev-design-qa-integration/patches/army-ddq-patch.js

# Edit army.js manually adding:
# - SPECIALISTS entries (dev/design/qa aliases)
# - SKILLS_MAP entries (42 skill paths)

# Verify
grep -c "fosved/dev\|fosved/design\|fosved/qa" army.js   # expect 42+

git add army.js
git commit -m "[DDQ] army.js registration"
git push origin feature/ddq-departments
```

---

### Phase Y6 — Bot commands (medium risk, 2 days)

Apply handlers from patches/bot-ddq-handlers.js. Manual integration into bot.js — do not blind copy (bot.js has many existing handlers).

**Commands added (31 total):**

Dev (14):
- `/dev <task description>` — create dev task with auto-estimation
- `/dev-estimate <task_id>` — refine estimate
- `/dev-decide <task_id> <decision>` — record architecture decision (ADR)
- `/dev-implement <task_id>` — execute implementation
- `/dev-task <id>` — view task details
- `/dev-tasks [filter]` — list dev tasks
- `/dev-repos` — list managed GitHub repos
- `/dev-repo <name>` — view repo details
- `/dev-create-repo <name> <description>` — create new GitHub repo
- `/dev-radar` — show current tech radar
- `/dev-radar-add <tech> <state>` — add tech to radar
- `/dev-deploy <repo> <target>` — trigger deployment
- `/dev-archive <task_id>` — archive completed task snapshot
- `/dev-local-sync <repo>` — sync repo to local server (when ready)

Design (8):
- `/design <brief>` — create design artifact
- `/design-spec <project>` — generate design spec for dev
- `/design-system <project>` — show/create design system
- `/design-show <id>` — view artifact
- `/design-artifacts [filter]` — list
- `/design-research <topic>` — initiate user research session
- `/design-iterate <id> <feedback>` — iterate on design
- `/design-approve <id>` — mark approved, ready for dev

QA (9):
- `/qa-strategy <project>` — generate test strategy
- `/qa-test <type> <target>` — run tests (unit/integration/e2e/security/perf/a11y)
- `/qa-defect <description>` — record defect
- `/qa-defects [filter]` — list defects
- `/qa-eval <ai-system>` — run AI evals (LLM eval suite)
- `/qa-security-audit <target>` — security audit
- `/qa-coverage <project>` — coverage report
- `/qa-runs [filter]` — list test runs
- `/qa-monitor <project>` — production monitoring summary

Test:
```bash
node bot.js &
# Telegram:
/dev test task estimate this
/design wireframe simple landing page
/qa-strategy fosved-bot
kill %1
```

```bash
git add bot.js
git commit -m "[DDQ] 31 commands across 3 departments"
git push origin feature/ddq-departments
```

---

### Phase Y7 — Scheduler tasks (low risk, half day)

Add scheduler tasks for self-improvement loops:

```javascript
// Dev: weekly tech radar check (Wednesday 04:00)
cron.schedule('0 4 * * 3', async () => {
  const dev = require('./lib/dev.js');
  await dev.weeklyTechRadarScan();
}, { timezone: 'Europe/Moscow' });

// Dev: monthly estimate calibration (1st 11:00)
cron.schedule('0 11 1 * *', async () => {
  const dev = require('./lib/dev.js');
  await dev.monthlyEstimateCalibration();
}, { timezone: 'Europe/Moscow' });

// QA: daily production monitoring (08:00)
cron.schedule('0 8 * * *', async () => {
  const qa = require('./lib/qa.js');
  await qa.dailyProductionMonitor();
}, { timezone: 'Europe/Moscow' });

// QA: weekly security scan (Sunday 05:00)
cron.schedule('0 5 * * 0', async () => {
  const qa = require('./lib/qa.js');
  await qa.weeklySecurityScan();
}, { timezone: 'Europe/Moscow' });

// Design: monthly design system audit (15th 12:00)
cron.schedule('0 12 15 * *', async () => {
  const design = require('./lib/design.js');
  await design.monthlyDesignSystemAudit();
}, { timezone: 'Europe/Moscow' });

// Quarterly methodology review for all 3 (1 Jan/Apr/Jul/Oct 11:30)
cron.schedule('30 11 1 1,4,7,10 *', async () => {
  const dev = require('./lib/dev.js');
  const design = require('./lib/design.js');
  const qa = require('./lib/qa.js');
  await dev.quarterlyMethodologyReview();
  await design.quarterlyMethodologyReview();
  await qa.quarterlyMethodologyReview();
}, { timezone: 'Europe/Moscow' });
```

```bash
git add scheduler.js
git commit -m "[DDQ] 6 scheduler tasks for self-improvement"
git push origin feature/ddq-departments
```

---

### Phase Y8 — Yana routing update (low risk, few hours)

Apply routing patch from `patches/upravlenie-ddq-routing-patch.md`. Adds:

- Triggers for Dev (build, code, implement, deploy, github)
- Triggers for Design (wireframe, mockup, design system, UX, prototype)
- Triggers for QA (test, audit, security, performance, accessibility, e2e)
- Multi-department orchestration patterns (build project, debug production, security review)

```bash
git add library/upravlenie.md
git commit -m "[DDQ] Yana routing for Dev + Design + QA"
git push origin feature/ddq-departments
```

---

### Phase Y9 — Auto-hooks integration (medium risk, 1 day)

Add hooks for cross-department flows:

- After Dev creates task → notify Yana for Design/QA loop decision
- After Design approves → auto-create Dev task with reference
- After Dev completes task → auto-trigger QA test run for that target
- After QA defect critical → auto-create Dev hotfix task

Apply from `patches/bot-cross-dept-hooks.js`. Wrapped in try/catch (non-blocking).

```bash
git add bot.js
git commit -m "[DDQ] Cross-department auto-hooks"
git push origin feature/ddq-departments
```

---

### Phase Y10 — Archive integration (low risk, half day)

Hook auto-publication for major DDQ milestones:

- DevTask completed with significant code → publish summary + code snapshot zip
- ArchitectureDecision recorded → publish ADR summary
- AIEvalRun with poor score → publish alert
- SecurityAudit with high-severity findings → publish alert
- DesignArtifact approved → publish thumbnail + spec link

Reuses existing `lib/archive-publisher.js` pattern, adds new publish functions.

```bash
git add lib/archive-publisher.js bot.js
git commit -m "[DDQ] Telegram Archive publication for DDQ milestones"
git push origin feature/ddq-departments
```

---

### Phase Y11 — Miniapp screens (medium risk, 2 days, OPTIONAL)

Add three new screens:

- `dev-screen.tsx` — Kanban dev tasks, estimate accuracy chart, tech radar visual
- `design-screen.tsx` — Design artifacts gallery, design system viewer
- `qa-screen.tsx` — Test run dashboards, defect trends, AI eval scores, security audit results

Plus API endpoints:
- `/api/dev/tasks`, `/api/dev/radar`, `/api/dev/repos`
- `/api/design/artifacts`, `/api/design/system`
- `/api/qa/runs`, `/api/qa/defects`, `/api/qa/evals`

Can be deferred. Backend works without miniapp.

```bash
cd ~/repos/fosved-miniapp
git checkout -b feature/ddq-departments
# Add screens and routes from patches/
git add src/
git commit -m "[DDQ] Miniapp screens for Dev + Design + QA"
git push origin feature/ddq-departments
```

---

### Phase Y12 — End-to-end smoke test + merge (1 day)

Test full pipeline:

**Journey A — Build a small landing page:**
1. `/design wireframe landing page for SaaS product Acme`
2. Verify DesignArtifact created
3. `/design-approve <id>`
4. Auto-creates DevTask referencing approved design
5. `/dev-implement <task_id>`
6. Verify GitHub repo created with code
7. `/qa-test e2e fosved-acme-landing`
8. Verify TestRun executed with results
9. Verify archive publication of milestones

**Journey B — AI office build:**
1. `/dev новый AI-офис для финансовой компании`
2. Multi-department orchestration kicks in
3. Design produces wireframes
4. Dev produces architecture decisions + initial code
5. QA defines AI eval strategy
6. Full project lifecycle visible in archive

**Journey C — Defect → hotfix flow:**
1. `/qa-defect critical: login broken on Safari`
2. Auto-creates Dev hotfix task
3. `/dev-implement <task_id>`
4. `/qa-test integration fosved-bot login`
5. Defect status updated to resolved

If all pass:

```bash
git checkout main
git merge feature/ddq-departments --no-ff -m "Add Dev + Design + QA departments"
git push origin main
git tag v4.1-ddq
git push origin v4.1-ddq
```

---

## ACCEPTANCE CRITERIA FOR FULL BLOCK

- [ ] 11 new Prisma models created
- [ ] 3 profiles in library/
- [ ] 42 SKILL.md files in skills/fosved/{dev,design,qa}/
- [ ] 4 lib modules (dev.js, design.js, qa.js, github-client.js)
- [ ] 31 new bot commands working
- [ ] 6 scheduler tasks registered
- [ ] Yana routes DDQ queries correctly
- [ ] GitHub integration creates real repos
- [ ] Telegram archive publishes DDQ milestones
- [ ] Cross-department auto-hooks work
- [ ] (Optional) miniapp 3 screens functional
- [ ] 3 end-to-end journeys pass
- [ ] Merged to main, tagged v4.1-ddq

---

## ESTIMATED EFFORT

- Y1-Y2 (Foundation + Schema): 1 day
- Y3 (lib modules): 1 day
- Y4 (Profiles + 42 skills): 1.5 days
- Y5-Y6 (Army + Commands): 2.5 days
- Y7-Y8 (Scheduler + Yana): 1 day
- Y9-Y10 (Hooks + Archive): 1.5 days
- Y11 (Miniapp, optional): 2 days
- Y12 (Smoke test + merge): 1 day

**Total: 11.5 days minimum, realistic 14-16 days with debugging buffer.**

---

## RISK PROFILE

**Highest risk: Phase Y6 (commands integration)** — 31 commands touching many parts of bot.js. Discipline: add one department's commands at a time, test, then next.

**Medium risk: Phase Y9 (cross-dept hooks)** — modifies existing handlers. Non-blocking try/catch wrappers required.

**Lower risk: Y11 (miniapp)** — additive, optional, can be deferred.

**Low risk: Y2 (schema)** — pure additive, no modifications to existing tables.

Emergency disable for cross-department flows: env `DDQ_AUTO_HOOKS=false`.

---

**End of DDQ_INTEGRATION_PLAN.md**
