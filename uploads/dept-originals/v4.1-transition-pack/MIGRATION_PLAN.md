# MIGRATION_PLAN.md — Fosved Office v4.1 Migration

**Project:** ShkodnikAI/fosved-bot + ShkodnikAI/fosved-miniapp
**Target version:** v4.1 (Fosved Office full architecture)
**Owner:** @ShkodnikAI (Telegram ID задаётся переменной OWNER_TELEGRAM_ID)
**Plan author:** Claude Opus (planning session)
**Plan version:** 1.0
**Plan date:** 2026-05-09
**Estimated duration:** 14-22 days of focused work, realistic ~3-4 weeks with buffers

---

## PURPOSE OF THIS DOCUMENT

This document is the operational plan for migrating fosved-bot from its current state to v4.1 architecture. It is written for Claude Code (the agent operating in the repository with shell + filesystem + git + render access).

**Read order for Claude Code at start of every session:**

1. This document (`MIGRATION_PLAN.md`) — the plan
2. `CLAUDE_CODE_BRIEF.md` — operational discipline
3. `CONTEXT_HANDOFF.md` — why decisions are what they are
4. Then execute the current Phase

**Phase status tracking:** maintained at the bottom of this document. Update after each completed Phase.

---

## CORE PRINCIPLES (non-negotiable)

1. **Branch discipline:** all migration work happens on `feature/v4.1-migration` branch. Never push to `main` until full Phase 10 sign-off from owner.
2. **One Phase = one or more commits** with clear `[Phase N]` prefix in commit message.
3. **Smoke test after every Phase** before moving to the next. If smoke test fails — fix or rollback that Phase, do not proceed.
4. **No silent decisions on architecture.** If the plan is ambiguous or doesn't cover a case — stop, ask the owner. Do not guess.
5. **Preserve existing methodology files.** The 47 SKILL.md files, 5 library profiles, Prisma schema patches in the transition pack are the source of truth — copy verbatim, do not rewrite.
6. **Scheduler & cron jobs:** never test cron triggers in production by waiting for them. Always trigger manually via test commands.
7. **API keys never committed.** All sensitive values stay in Render env vars or `.env` (which is .gitignored).
8. **Database migrations are one-way unless explicitly designed otherwise.** Plan migrations carefully, test on local DB first.

---

## ARCHITECTURE OVERVIEW (target state)

After this migration, fosved-bot will have:

**5 working departments:**
- **Управление (Yana)** — coordinator, routes between departments (existing, gets v2.1 update)
- **ОСП V2** — Strategic Intelligence (replaces V1 with 5-level topology)
- **Лаборатория знаний (ЛЗ)** — Technology Intelligence (new, full implementation)
- **Эксперт** — Technical Due Diligence Preparation (new, with LDR-inspired research engine)
- **Кузница (Veteran)** — Methodology Forge (placeholder; will be activated in future)

**Other 5 specialists** (Разработка, Юрист, Финансы, Продукт, Операции, AI Studio) remain at current state — handlers exist, will be deepened in future migration v4.2+.

**Key infrastructure additions:**
- ResearchSource model + lib/research.js (knowledge base for Expert + ОСП)
- Telegram Archive Channel + lib/archive-publisher.js (auto-publish summaries)
- Drive-screen redesigned in Telegram-Drive style (Bot API backend, no MTProto)
- Voice mode in miniapp (chat-overlay connected to /api/chat + voice pipeline)
- Multi-user readiness: `userId` field everywhere with default OWNER_ID

**Total scope:** 47 new SKILL.md files, 1 new (iterative-research-loop), schema with 35+ models (15 new), ~20 new bot commands, miniapp connection to backend, drive UX overhaul.

---

# PHASE 0 — Foundation (preparation, nothing destructive yet)

**Goal:** prepare environment, create branch, smoke test current state, ensure rollback is possible.

**Estimated duration:** half a day

**Risk level:** very low

## Tasks

### 0.1 Create migration branch

```bash
cd ~/repos/fosved-bot   # or wherever fosved-bot is cloned
git checkout main
git pull origin main
git checkout -b feature/v4.1-migration
git push -u origin feature/v4.1-migration
```

For miniapp:

```bash
cd ~/repos/fosved-miniapp
git checkout main
git pull origin main
git checkout -b feature/v4.1-migration
git push -u origin feature/v4.1-migration
```

### 0.2 Smoke test current production

Document current working state. Run these commands and confirm each works:

```
# In Telegram with bot:
/start          → expect welcome message
/status         → expect specialist list
/tasks          → expect task list (or empty)
/projects       → expect project list (or empty)
/analyze тест   → expect 12-layer V1 analysis (this will be replaced)
/score          → expect Brier calibration report
/voice          → expect STT/TTS provider status
```

Save output to `migration_logs/phase0_smoke_test.md`. This is the **before** state.

### 0.3 Backup production database

```bash
# Get DATABASE_URL from Render env vars (for fosved-bot service)
# Use pg_dump to create complete backup:
pg_dump "$DATABASE_URL" > migration_logs/db_backup_pre_v4.1_$(date +%Y%m%d).sql

# Verify backup is non-empty:
ls -lh migration_logs/db_backup_pre_v4.1_*.sql
head -50 migration_logs/db_backup_pre_v4.1_*.sql
```

If backup fails — STOP. Do not proceed without backup.

### 0.4 Note: tables to be dropped in Phase 1

Owner confirmed all data in current `analysis`, `analysis_indicators`, `analysis_verifications`, `monthly_reviews`, `quarterly_methodology_reviews`, `watch_topics`, `tasks`, `projects`, `invoices`, `documents`, `clients`, `client_timeline`, `entity_links`, `team_members`, `drive_files`, `search_logs`, `job_queue`, `project_messages`, `conversations` is placeholder/test data and can be dropped.

`settings` (with STT/TTS keys) — preserved.

### 0.5 Prepare environment variables for new features

Add to Render env vars (fosved-bot service) — placeholders, will fill values later:

```
ARCHIVE_CHANNEL_ID=        # to be set in Phase 6
LDR_ENABLED=false          # research engine — enable later
EXPERT_KB_ENABLED=true     # knowledge base for Expert
TELEGRAM_API_ID=           # not used in v4.1 (was for MTProto, decided against)
TELEGRAM_API_HASH=         # same
```

For miniapp service — placeholders for upcoming endpoints:

```
NEXT_PUBLIC_BOT_API_URL=https://fosved-bot.onrender.com  # if bot exposes API
                                                          # else this is unused
```

### 0.6 Verify v4.1 transition pack files

```bash
# After unpacking transition_pack.zip into ~/transition_pack/:
ls -la ~/transition_pack/
# Expected:
#   MIGRATION_PLAN.md (this file)
#   CLAUDE_CODE_BRIEF.md
#   CONTEXT_HANDOFF.md
#   METHODOLOGY-v1.md
#   ARCHITECTURE.md
#   AGENT_INSTRUCTIONS-v3.md
#   README.md
#   library/  (5 profile files: osp.md v3, lz.md, expert.md, upravlenie.md v2.1, kk.md)
#   skills/fosved/spd/  (24 OSP V2 skill files)
#   skills/fosved/lz/   (12 ЛЗ skill files)
#   skills/fosved/expert/  (12 Expert skill files: 11 v4.1 + iterative-research-loop)
#   prisma/schema-v4.1.prisma  (full target schema)
#   patches/   (bot.js handlers, scheduler additions, library updates)
#   lib/research.js
#   lib/archive-publisher.js
```

### 0.7 Commit Phase 0

```bash
git add migration_logs/
git commit -m "[Phase 0] Foundation: branch created, smoke test logged, backup taken"
git push origin feature/v4.1-migration
```

## Acceptance criteria for Phase 0

- [ ] `feature/v4.1-migration` branch exists in both repos
- [ ] `migration_logs/phase0_smoke_test.md` captured before-state
- [ ] `migration_logs/db_backup_pre_v4.1_<date>.sql` exists and is non-empty
- [ ] Transition pack fully unpacked and verified
- [ ] All env vars present in Render config

---

# PHASE 1 — Schema migration (highest risk; do carefully)

**Goal:** replace existing Prisma schema with v4.1 schema, including dropping placeholder data and creating 15 new models, plus `userId` field everywhere.

**Estimated duration:** 1 day

**Risk level:** HIGH (database changes are destructive in this phase)

## Tasks

### 1.1 Inspect current schema

```bash
cd ~/repos/fosved-bot
cat prisma/schema.prisma | wc -l          # current size
cat prisma/migrations/                    # existing migrations list
```

Note current state for reference.

### 1.2 Replace schema with v4.1

```bash
# Backup current schema:
cp prisma/schema.prisma prisma/schema.prisma.backup_v3

# Replace with v4.1:
cp ~/transition_pack/prisma/schema-v4.1.prisma prisma/schema.prisma

# Inspect new schema:
wc -l prisma/schema.prisma                # expect ~700-900 lines
grep "^model " prisma/schema.prisma | wc -l  # expect 35+ models
```

### 1.3 Generate Prisma client (validation step)

```bash
npx prisma generate
# If there are syntax errors or model issues — fix in schema, do not proceed
```

If generation fails — STOP, ask owner. Do not push broken schema.

### 1.4 Create migration

```bash
# Name the migration explicitly:
npx prisma migrate dev --name v4_1_full_migration --create-only

# This creates a new migration file in prisma/migrations/<timestamp>_v4_1_full_migration/migration.sql
# Inspect the migration SQL:
cat prisma/migrations/*_v4_1_full_migration/migration.sql
```

### 1.5 Apply migration to development database first

If you have a local Postgres or Supabase dev branch:

```bash
# Set DATABASE_URL to dev database temporarily:
export DATABASE_URL="<dev_url>"
npx prisma migrate deploy

# Verify schema applied:
npx prisma db pull --print
```

If dev migration succeeds without data loss issues you don't expect — proceed to production.

### 1.6 Apply migration to production database

**WARNING: this is the destructive step.** Owner has confirmed all data in target tables is placeholder.

```bash
# Set DATABASE_URL back to production (Supabase pooler):
export DATABASE_URL="<production_url>"

# Apply migration:
npx prisma migrate deploy

# Verify:
npx prisma db pull --print | head -100
```

### 1.7 Re-generate Prisma client for production

```bash
npx prisma generate
```

### 1.8 Smoke test bot still starts (with empty new schema)

Don't push to Render yet. Run locally:

```bash
node -e "const { PrismaClient } = require('@prisma/client'); const p = new PrismaClient(); p.\$connect().then(() => { console.log('DB connection OK'); p.\$disconnect(); });"
```

Should output `DB connection OK`. If not — debug.

### 1.9 Commit Phase 1

```bash
git add prisma/schema.prisma prisma/migrations/
git commit -m "[Phase 1] Schema v4.1: 35+ models, full migration applied"
git push origin feature/v4.1-migration
```

### 1.10 Document Phase 1 outcome

Add entry to `migration_logs/phase1_schema.md`:

```
- Migration name: v4_1_full_migration
- Models added: <list>
- Models dropped: <list>
- Models modified: <list>
- userId field added to: <list of tables>
- Production DB state: <verified clean>
```

## Acceptance criteria for Phase 1

- [ ] `prisma/schema.prisma` matches v4.1 spec from transition pack
- [ ] Migration `v4_1_full_migration` applied to production DB
- [ ] `npx prisma generate` runs cleanly
- [ ] DB connection from bot succeeds
- [ ] Existing bot handlers do not crash on startup (will fail on missing logic, but should not fail on schema mismatch)
- [ ] `migration_logs/phase1_schema.md` documents outcome

## Rollback plan for Phase 1

If something is broken:

```bash
# Restore previous schema:
cp prisma/schema.prisma.backup_v3 prisma/schema.prisma
npx prisma generate

# Restore database from backup:
psql "$DATABASE_URL" < migration_logs/db_backup_pre_v4.1_*.sql

# Revert commits:
git revert HEAD
git push origin feature/v4.1-migration
```

---

# PHASE 2 — ОСП V2 in code

**Goal:** replace V1 ОСП (12-layer protocol) with V2 (5-level topology, 24 skills, force differentials, fruits, two-paths-synthesis).

**Estimated duration:** 2-3 days

**Risk level:** medium (replaces working subsystem; old V1 commands break and are replaced with V2 equivalents)

## Tasks

### 2.1 Replace V1 skill files with V2

```bash
cd ~/repos/fosved-bot

# Backup current V1 skills:
cp -r skills/fosved/spd skills/fosved/spd.backup_v1

# Remove V1 skills:
rm -rf skills/fosved/spd/

# Copy V2 skills:
cp -r ~/transition_pack/skills/fosved/spd/ skills/fosved/spd/

# Verify count: expect 24 SKILL.md files
find skills/fosved/spd/ -name SKILL.md | wc -l
```

### 2.2 Update OSP profile

```bash
# Backup V2 of profile:
cp library/osp.md library/osp.md.backup_v2

# Replace with V3 profile from transition pack:
cp ~/transition_pack/library/osp.md library/osp.md
```

### 2.3 Update army.js SKILLS_MAP

The current `army.js` has SKILLS_MAP with 11 V1 skills under `'deconstruct'`, `'ach'`, etc. Replace with 24 V2 keys.

```bash
# Apply patch from transition pack:
cp ~/transition_pack/patches/army.js patches/army.js
# Then merge manually — patches/army.js shows the target state of SPECIALISTS + SKILLS_MAP
# Apply changes by hand (not blind copy) since current army.js may have manual additions
diff army.js ~/transition_pack/patches/army.js > /tmp/army_diff.txt
cat /tmp/army_diff.txt
# Review, then apply:
cp ~/transition_pack/patches/army.js army.js
```

Verify SKILLS_MAP has the 24 V2 OSP entries:

```bash
grep "fosved/spd/" army.js | wc -l   # expect 24
```

### 2.4 Replace spd.js business logic

V2 protocol changes the analysis structure significantly. spd.js needs major rewrite:
- Old: 12-layer deconstruction
- New: 5-level topology (leaves/branches/stem/roots/fruits) + Force differentials (P=A×R×S×L×E) + two-paths-synthesis

```bash
cp spd.js spd.js.backup_v1
cp ~/transition_pack/patches/spd.js spd.js
```

Inspect:

```bash
wc -l spd.js   # expect ~800-1000 lines (V2 is more elaborate)
grep "^function\|^async function\|exports" spd.js | head -30
```

### 2.5 Update bot.js OSP command handlers

Current handlers `/analyze`, `/quickanalyze`, `/watch`, `/verify`, `/score`, `/redteam`, `/recalibrate`, `/archive` use V1 logic. Update to call V2 functions from new spd.js.

```bash
# Inspect current handler section:
grep -n "/analyze\|/quickanalyze\|/watch\|/verify\|/score\|/redteam\|/recalibrate\|/archive" bot.js

# Apply patches from transition pack manually:
cat ~/transition_pack/patches/bot_osp_handlers.js
# Replace OSP handler section in bot.js with this
```

### 2.6 Update scheduler.js for V2 cycles

V2 has different self-improvement cadence:
- Daily watch sweep (similar to V1)
- Monthly review (similar to V1, different metrics)
- Quarterly review (similar to V1)
- **NEW:** Semi-annual arsenal review (V2 specific)
- **NEW:** Bi-annual paradigm review (V2 specific)

```bash
cp scheduler.js scheduler.js.backup_v1
# Apply scheduler patch:
cat ~/transition_pack/patches/scheduler_osp_v2.js
# Merge into scheduler.js
```

### 2.7 Run Prisma generate (schema fits V2 already from Phase 1)

```bash
npx prisma generate
```

### 2.8 Local smoke test

Before pushing to Render:

```bash
# Start bot locally:
node bot.js
# In another terminal — simulate a /analyze command via Prisma directly:

node -e "
const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
p.analysis.create({
  data: {
    topic: 'test_v2_smoke',
    mode: 'full',
    status: 'drafted',
    sources: '[]',
    skillsLoaded: '[]'
  }
}).then(a => { console.log('Created Analysis:', a.id); p.\$disconnect(); });
"
```

If creation works — schema is fine and OSP V2 can write. Stop bot.

### 2.9 Push to Render

```bash
git add skills/fosved/spd/ library/osp.md army.js spd.js bot.js scheduler.js
git commit -m "[Phase 2] OSP V2: 24 skills, 5-level topology, two-paths-synthesis, force differentials"
git push origin feature/v4.1-migration
```

Render will auto-deploy from `feature/v4.1-migration` if branch deploys are configured. If not — temporarily change Render service branch to `feature/v4.1-migration`, deploy, switch back if needed.

### 2.10 Production smoke test

```
# In Telegram:
/analyze экспансия Китая в редкоземельные металлы
# Expect output following V2 protocol — leaves, branches, stem, roots, fruits, scenarios with probabilities, indicators, premortem
```

If output looks correct — Phase 2 done. If not — debug from spd.js logs.

### 2.11 Commit final state

```bash
git add migration_logs/
git commit -m "[Phase 2] Smoke test passed; OSP V2 production ready"
git push origin feature/v4.1-migration
```

## Acceptance criteria for Phase 2

- [ ] 24 V2 skill files in `skills/fosved/spd/`
- [ ] `library/osp.md` is V3 (5-level topology profile)
- [ ] `spd.js` rewritten to V2 protocol
- [ ] All OSP commands (`/analyze`, etc.) work with V2
- [ ] One real `/analyze` command produces V2-shaped output
- [ ] V1 skills backup preserved at `skills/fosved/spd.backup_v1/` (delete after Phase 10 final sign-off)

## Rollback plan for Phase 2

```bash
# Restore V1 files:
rm -rf skills/fosved/spd/
mv skills/fosved/spd.backup_v1 skills/fosved/spd/
cp library/osp.md.backup_v2 library/osp.md
cp army.js.backup army.js
cp spd.js.backup_v1 spd.js
cp scheduler.js.backup_v1 scheduler.js

git revert HEAD~3..HEAD   # revert last 3 commits
git push origin feature/v4.1-migration
```

---

# PHASE 3 — Лаборатория знаний (full new department)

**Goal:** add ЛЗ as fully working department — profile, 12 skills, KnowledgeArtifact + supporting models, scheduler tasks for continuous monitoring, commands.

**Estimated duration:** 2-3 days

**Risk level:** low-medium (additive, new department, doesn't break existing)

## Tasks

### 3.1 Add ЛЗ profile

```bash
cp ~/transition_pack/library/lz.md library/lz.md
```

Verify profile is well-formed (length ~200 lines, includes psychotype, hard rules, skills tier list).

### 3.2 Add 12 ЛЗ skills

```bash
cp -r ~/transition_pack/skills/fosved/lz/ skills/fosved/lz/
find skills/fosved/lz -name SKILL.md | wc -l   # expect 12
```

### 3.3 Update army.js — register ЛЗ specialist + skills

Apply ЛЗ entries from transition pack patches/army.js:

```javascript
// In SPECIALISTS — add:
'лз': 'lz.md',
'лаборатория знаний': 'lz.md',
'lab': 'lz.md',
// ... aliases per profile

// In SKILLS_MAP — add 12 ЛЗ skills with tier-aware paths
```

### 3.4 Add ЛЗ commands to bot.js

The transition pack provides handlers in `patches/bot_lz_handlers.js`. Apply:

- `/scan <тема>` — start a new technology scan
- `/track <topic>` — add topic to watchlist
- `/disrupt <industry>` — assess disruption probability
- `/artifact <id>` — view knowledge artifact
- `/lzinventory` — list all tracked technologies
- `/lzscore` — ЛЗ department metrics
- `/talent <field>` — talent flow query
- `/vc <industry>` — VC funding tracker

### 3.5 Add scheduler tasks for ЛЗ

ЛЗ runs continuous monitoring tasks:
- **Daily** (08:00) — scan watchlist for new arXiv papers, news mentions, talent moves
- **Weekly** (Monday 09:00) — disruption probability recalculation for tracked technologies
- **Monthly** (1st, 09:30) — ЛЗ performance review (similar to OSP)
- **Quarterly** (Jan/Apr/Jul/Oct 1st, 10:00) — ЛЗ methodology review

Apply from `patches/scheduler_lz.js`.

### 3.6 Update Yana routing for ЛЗ triggers

`library/upravlenie.md` needs additions for ЛЗ routing keywords:

```bash
# Apply updated upravlenie profile from transition pack:
cp ~/transition_pack/library/upravlenie.md library/upravlenie.md
```

### 3.7 Run prisma generate (KnowledgeArtifact already in schema from Phase 1)

```bash
npx prisma generate
```

### 3.8 Local test

```bash
node bot.js
# In Telegram:
/scan квантовые вычисления
# Expect: ЛЗ specialist activates, runs scan protocol, produces KnowledgeArtifact
```

### 3.9 Commit Phase 3

```bash
git add library/lz.md library/upravlenie.md skills/fosved/lz/ army.js bot.js scheduler.js
git commit -m "[Phase 3] ЛЗ Knowledge Lab: full implementation, 12 skills, continuous monitoring"
git push origin feature/v4.1-migration
```

### 3.10 Production smoke test

```
/scan ИИ-агенты для разработки кода
/track квантовые вычисления
/lzinventory
/disrupt автомобильная промышленность
```

## Acceptance criteria for Phase 3

- [ ] `library/lz.md` profile present and parseable
- [ ] 12 SKILL.md files in `skills/fosved/lz/`
- [ ] `/scan`, `/track`, `/disrupt`, `/artifact`, `/lzinventory`, `/lzscore` commands work
- [ ] Scheduler tasks for ЛЗ registered
- [ ] Yana routes ЛЗ-trigger queries to ЛЗ
- [ ] One real `/scan` produces a KnowledgeArtifact in DB

## Rollback plan for Phase 3

Easy — ЛЗ is purely additive.

```bash
rm -rf skills/fosved/lz/
rm library/lz.md
git checkout main -- library/upravlenie.md army.js bot.js scheduler.js
# (or git revert the Phase 3 commits)
```

---

# PHASE 4 — Эксперт + LDR-inspired research

**Goal:** add Эксперт department (full v4.1) plus the LDR-inspired research engine (iterative-research-loop skill, ResearchSource model, lib/research.js, knowledge base, citation discipline).

**Estimated duration:** 2-3 days

**Risk level:** medium (sizable new module with research logic)

## Tasks

### 4.1 Add Эксперт profile

```bash
cp ~/transition_pack/library/expert.md library/expert.md
```

### 4.2 Add 12 Эксперт skills (11 v4.1 + 1 new iterative-research-loop)

```bash
cp -r ~/transition_pack/skills/fosved/expert/ skills/fosved/expert/
find skills/fosved/expert -name SKILL.md | wc -l   # expect 12
```

The 12 skills are:

**Tier 1 (6):**
- rapid-domain-immersion (with citation discipline + KB integration)
- project-deconstruction
- failure-modes-mapping
- combat-questions-design
- bullshit-detection
- **iterative-research-loop (NEW from LDR ideas)**

**Tier 2 (4):**
- technical-economics-validation
- peer-review-simulation (with source tier hierarchy)
- adjacent-field-cross-check
- competing-claims-comparison

**Tier 3 (2):**
- pre-meeting-intel
- tactical-meeting-protocol

### 4.3 Update OSP source-triangulation skill (citation discipline + source tier hierarchy)

```bash
cp ~/transition_pack/skills/fosved/spd/source-triangulation/SKILL.md skills/fosved/spd/source-triangulation/SKILL.md
```

### 4.4 Add lib/research.js (the research engine)

```bash
mkdir -p lib
cp ~/transition_pack/lib/research.js lib/research.js
```

The module exports:

- `iterativeResearch(topic, options)` — main 3-iteration research loop
- `searchKnowledgeBase(query, sourceTypes)` — search ResearchSource for prior research
- `addResearchSource(briefingId, source)` — add source to KB
- `linkSourceToAnalysis(analysisId, sourceId)` — cross-link OSP analysis to source
- `formatCitation(source)` — produces inline citation `[Source: Title, Type, Date]`
- `validateCitations(text)` — checks every numerical anchor + Layer 2 SOA claim has citation
- `tierSource(source)` — returns 1-5 tier (peer_review > government > industry > news > blog)

The iterative research uses Grok web search + Claude API for synthesis. No external services.

### 4.5 Add Expert commands to bot.js

From `patches/bot_expert_handlers.js`:

- `/expert <topic with meeting context>` — Level 2 default
- `/quickexpert <topic>` — Level 1 (30 min analysis)
- `/deepexpert <topic>` + `/confirm-deepexpert <topic>` — Level 3
- `/expert-update <id> <new info>` — add context to briefing
- `/expert-followup <id> <question>` — add a question post-briefing
- `/expert-debrief <id> <notes>` — post-meeting debrief
- `/expert-rate <id>` — owner self-rating prompt
- `/expert-scores <id> <understanding> <confidence> <hit_rate> <bullshit yes/no>` — record scores
- `/expert-archive [id]` — list/view briefings
- `/expert-stats` — department metrics
- `/expert-source <id>` — view a research source from KB
- `/expert-sources [filter]` — list sources in KB

### 4.6 Update Yana for Expert routing

Yana profile already updated in Phase 3 with all v4.1 changes. Verify Expert triggers are present:

```bash
grep -A 5 "Эксперт\|expert" library/upravlenie.md
```

### 4.7 Update OSP analysis to use research engine (knowledge base scope b)

`spd.js` needs to call `lib/research.js` functions during Layer 2 (SOA) population. Apply patch:

```bash
cat ~/transition_pack/patches/spd_research_integration.js
# Merge into spd.js
```

This means: when OSP runs `/analyze`, it now also accumulates ResearchSource entries linked to that Analysis. Future analyses can search the KB for prior research on related topics.

### 4.8 Run prisma generate (ExpertBriefing + ResearchSource already in schema from Phase 1)

```bash
npx prisma generate
```

### 4.9 Local smoke test

```bash
node bot.js
# In Telegram:
/expert компактный термоядерный реактор FusionCorp, встреча через 4 часа в академии наук, рассматриваю инвестицию

# Expect:
# - Briefing created with id
# - Iterative research kicks in (3 iterations)
# - Domain immersion done
# - Project deconstruction
# - Failure modes mapped
# - Combat questions generated with response patterns
# - Citations on every numerical anchor and Layer 2 claim
# - Sources saved to ResearchSource (linked to briefingId)
```

### 4.10 Commit Phase 4

```bash
git add library/expert.md skills/fosved/expert/ skills/fosved/spd/source-triangulation/ \
        lib/research.js bot.js spd.js
git commit -m "[Phase 4] Expert + research engine: 12 skills, iterative research, knowledge base, citation discipline"
git push origin feature/v4.1-migration
```

### 4.11 Production smoke test

```
/quickexpert разобраться в технологии mRNA-вакцин
/expert встреча с разработчиком ИИ-СУБД через 24 часа, технологическая компания, $50M вложение
/deepexpert + /confirm-deepexpert ...
/expert-archive
/expert-stats
```

## Acceptance criteria for Phase 4

- [ ] `library/expert.md` present
- [ ] 12 SKILL.md files in `skills/fosved/expert/` (including iterative-research-loop)
- [ ] `lib/research.js` exports the listed functions; runs without error
- [ ] All Expert commands work
- [ ] One `/expert` produces a briefing with citations and KB sources
- [ ] OSP `/analyze` now also writes to ResearchSource

## Rollback plan for Phase 4

```bash
rm -rf skills/fosved/expert/ lib/research.js
rm library/expert.md
# Revert source-triangulation:
git checkout main -- skills/fosved/spd/source-triangulation/SKILL.md
# Revert bot.js + spd.js Phase 4 changes (Phase 2 changes preserved):
git revert <Phase 4 commit hashes>
```

---

# PHASE 9 — Voice + chat-overlay in miniapp (REORDERED — owner choice for early UI feedback)

**Goal:** connect existing miniapp chat-overlay (981 lines) to bot's askAI() pipeline + voice STT/TTS chain, making miniapp a fully working alternative to Telegram interface.

**Estimated duration:** 1-2 days

**Risk level:** medium (cross-service integration)

## Why Phase 9 here (after Phase 4)

Owner explicitly chose to do Phase 9 right after Phase 4 (instead of after Phase 8) for early UI feedback. The reasoning: by the end of Phase 4 the bot has 3 fully working departments (OSP V2 + ЛЗ + Expert). Connecting the miniapp chat to use these immediately gives a working web/mobile alternative to Telegram, which is testable for UX.

## Tasks

### 9.1 Audit existing /api/chat endpoint in miniapp

```bash
cd ~/repos/fosved-miniapp
cat src/app/api/chat/route.ts
```

Determine: what does it currently do? Is it stubbed? Does it use Prisma? Does it call Claude/Grok?

### 9.2 Implement /api/chat to mirror bot's askAI()

Bot's askAI() takes a message, applies system prompt, includes 20-message history, routes to active model (Claude/Grok), saves to Conversation table.

Replicate this in `src/app/api/chat/route.ts`:

```typescript
// POST /api/chat
// Body: { userId: number, message: string, mode?: 'text' | 'voice' }
// Response: { text: string, audioUrl?: string }

import { PrismaClient } from '@prisma/client';
import Anthropic from '@anthropic-ai/sdk';
import OpenAI from 'openai';

const prisma = new PrismaClient();
const claude = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const grok = new OpenAI({ apiKey: process.env.GROK_API_KEY, baseURL: 'https://api.x.ai/v1' });

// (full implementation in transition pack patches/miniapp_chat_route.ts)
```

Apply:

```bash
cp ~/transition_pack/patches/miniapp_chat_route.ts src/app/api/chat/route.ts
```

### 9.3 Implement voice endpoints in miniapp

Add `/api/voice/stt` and `/api/voice/tts`:

- STT: receives audio blob, runs through 4-provider chain (same as bot's voice.js logic), returns text
- TTS: receives text, synthesizes via MiniMax, returns audio URL or buffer

```bash
mkdir -p src/app/api/voice/stt src/app/api/voice/tts
cp ~/transition_pack/patches/miniapp_stt_route.ts src/app/api/voice/stt/route.ts
cp ~/transition_pack/patches/miniapp_tts_route.ts src/app/api/voice/tts/route.ts
```

These reuse the same provider chain logic from `voice.js`. To avoid duplication, extract shared logic into `lib/voice-providers.ts` shared between bot and miniapp:

```bash
mkdir -p src/lib
cp ~/transition_pack/patches/lib_voice_providers.ts src/lib/voice-providers.ts
```

Wait — bot is in different repo. So duplicate logic in miniapp's lib. Acceptable for v4.1.

### 9.4 Update chat-overlay.tsx to call /api/chat

The 981-line chat-overlay currently has demo/mock data. Replace with real API calls:

```typescript
// In handleSendMessage:
const response = await fetch('/api/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ userId: currentUser.id, message: text })
});
const data = await response.json();
// Display data.text in chat
```

For voice:

```typescript
// On microphone stop:
const formData = new FormData();
formData.append('audio', audioBlob);
const sttResponse = await fetch('/api/voice/stt', { method: 'POST', body: formData });
const { text } = await sttResponse.json();
// Then send text via /api/chat
// Receive response.text
// Optionally request TTS:
if (voiceMode) {
  const ttsResponse = await fetch('/api/voice/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: response.text })
  });
  const audioBlob = await ttsResponse.blob();
  // Play audio
}
```

Apply patch:

```bash
cp ~/transition_pack/patches/miniapp_chat_overlay.tsx src/components/chat-overlay.tsx
```

### 9.5 Add Telegram WebApp initData verification

Miniapp needs to know who the user is. Use Telegram WebApp `initData`:

```typescript
// src/lib/auth.ts
export function verifyTelegramAuth(initData: string): { userId: number } | null {
  // HMAC verification using BOT_TOKEN
  // Returns userId if valid
}
```

```bash
cp ~/transition_pack/patches/miniapp_auth.ts src/lib/auth.ts
```

In `/api/chat/route.ts` and other API routes — call `verifyTelegramAuth(request.headers.get('x-telegram-initdata'))`. Reject if invalid.

### 9.6 Test locally

```bash
cd ~/repos/fosved-miniapp
npm run dev  # starts at localhost:3000
# Open localhost:3000 in browser
# (won't have Telegram auth in dev — set DEV_BYPASS_AUTH=true env temporarily)
# Click chat-overlay button, send a message
# Verify response from Claude/Grok comes through
```

### 9.7 Push to Render

```bash
git add src/
git commit -m "[Phase 9] Voice + chat-overlay in miniapp: connected to /api/chat, /api/voice/*, Telegram auth"
git push origin feature/v4.1-migration
```

Render miniapp service auto-deploys.

### 9.8 Production smoke test

In Telegram:
1. Open Fosved Office menu button (opens miniapp)
2. Click chat-overlay
3. Type "Тестовое сообщение"
4. Verify response comes through

Then:
1. Click microphone, record voice
2. Verify STT transcribes
3. Verify response comes back as both text + voice (if voice mode toggled)

## Acceptance criteria for Phase 9

- [ ] `/api/chat` endpoint works with real Claude/Grok
- [ ] `/api/voice/stt` works with 4-provider chain
- [ ] `/api/voice/tts` works with MiniMax
- [ ] chat-overlay sends real messages to bot's AI pipeline
- [ ] Voice mode toggleable; STT and TTS work end-to-end in miniapp
- [ ] Telegram WebApp auth verified
- [ ] Production miniapp shows live chat working

## Rollback plan for Phase 9

```bash
git revert <Phase 9 commits>
git push origin feature/v4.1-migration
# Miniapp falls back to mock data
```

---

# PHASE 5 — Yana coordinator update (compact phase)

**Goal:** finalize Yana (Управление) routing logic across all current departments (OSP V2, ЛЗ, Expert), plus orchestration patterns for multi-department queries.

**Estimated duration:** half day

**Risk level:** low

## Tasks

### 5.1 Apply final Yana profile

If not already done in Phase 3 fully — apply now:

```bash
cp ~/transition_pack/library/upravlenie.md library/upravlenie.md
```

This profile covers:
- Routing triggers for OSP V2 (analyze, watch, score)
- Routing triggers for ЛЗ (scan, track, disrupt)
- Routing triggers for Expert (expert, quickexpert, deepexpert + meeting context)
- Multi-department orchestration (Investment decision: OSP + ЛЗ + Expert all)
- Boundary clarification (Expert vs OSP, Expert vs ЛЗ, etc.)

### 5.2 Verify Yana behavior

In Telegram:
```
Привет, я думаю инвестировать в FusionCorp, что скажешь?
# Expect: Yana clarifies — meeting? deadline? then routes to Expert + OSP simultaneously

Что нового в квантовых вычислениях?
# Expect: Yana routes to ЛЗ

Сценарии для биткоина в 2026?
# Expect: Yana routes to OSP V2 (forecast)
```

### 5.3 Commit

```bash
git add library/upravlenie.md
git commit -m "[Phase 5] Yana v2.1: routing for OSP V2 + ЛЗ + Expert, multi-dept orchestration"
git push origin feature/v4.1-migration
```

## Acceptance criteria for Phase 5

- [ ] Yana correctly routes OSP/ЛЗ/Expert queries
- [ ] Multi-department orchestration works for compound queries

---

# PHASE 6 — Telegram archive auto-publication

**Goal:** create dedicated Telegram channel "Fosved Archive", auto-publish summaries of every Analysis, ExpertBriefing, verified forecast with hashtags. Add `/find <query>` command searching channel + DB.

**Estimated duration:** 1 day

**Risk level:** low

## Tasks

### 6.1 Create Fosved Archive Telegram channel manually

In Telegram:
1. Create new channel "Fosved Archive" (private, only owner initially)
2. Add bot as admin with post permissions
3. Get channel ID:

```bash
# In Telegram, post a message in the channel.
# Then run:
node -e "
const TelegramBot = require('node-telegram-bot-api');
const bot = new TelegramBot(process.env.TELEGRAM_TOKEN);
bot.getUpdates().then(updates => {
  updates.forEach(u => {
    if (u.channel_post) console.log('Channel ID:', u.channel_post.chat.id);
  });
});
"
```

Set in Render env: `ARCHIVE_CHANNEL_ID=<id>`

### 6.2 Add lib/archive-publisher.js

```bash
cp ~/transition_pack/lib/archive-publisher.js lib/archive-publisher.js
```

The module exports:
- `publishAnalysisSummary(analysisId)` — formats Analysis as a structured post and sends to channel
- `publishExpertBriefing(briefingId)` — same for ExpertBriefing
- `publishVerifiedForecast(verificationId)` — when /verify completes, publish outcome
- `searchArchiveChannel(query)` — searches recent channel posts (uses Telegram's search via getChatHistory)
- `searchUnified(query)` — combines DB search + channel search

Hashtag conventions:
- Department: `#осп #эксперт #лз`
- Status: `#прогноз #прогноз_сбылся #прогноз_провалился #брифинг`
- Year: `#2026`
- Topic slug: `#fusion #квант #биткоин`

### 6.3 Hook auto-publication into existing handlers

In bot.js (apply from `patches/bot_archive_hooks.js`):

```javascript
// After /analyze success:
await publishAnalysisSummary(analysis.id);

// After /expert success:
await publishExpertBriefing(briefing.id);

// After /verify completes:
await publishVerifiedForecast(verification.id);
```

### 6.4 Add /find command

```javascript
bot.onText(/\/find (.+)/, async (msg, match) => {
  const query = match[1];
  const results = await searchUnified(query);
  // Format and send
});
```

### 6.5 Test

```bash
# In Telegram:
/analyze тестовая тема
# Wait for OSP completion
# Check Fosved Archive channel — should see new post with summary + hashtags

/find термояд
# Should return: matches from DB analyses + matches from channel posts
```

### 6.6 Commit

```bash
git add lib/archive-publisher.js bot.js
git commit -m "[Phase 6] Telegram Archive: auto-publish summaries, /find unified search"
git push origin feature/v4.1-migration
```

## Acceptance criteria for Phase 6

- [ ] Fosved Archive channel exists and bot can post
- [ ] /analyze, /expert, /verify each trigger auto-publish
- [ ] Posts have proper hashtags
- [ ] /find searches DB + channel together
- [ ] Channel chronology is readable as a timeline

---

# PHASE 7 — Miniapp connect to backend

**Goal:** wire the 11 miniapp screens to the 17 API endpoints, replacing mock data with live data.

**Estimated duration:** 2-3 days

**Risk level:** medium

## Tasks

### 7.1 Audit current API endpoints

```bash
cd ~/repos/fosved-miniapp
ls src/app/api/
```

For each endpoint — verify it's implemented (not stubbed) and uses Prisma. List them as **complete** / **stub** / **missing**.

### 7.2 Implement missing/stub endpoints

For each, refer to the spec in transition pack `patches/miniapp_api_specs.md`:

- `/api/alerts` — feeds home-screen alerts (overdue tasks + Watch indicators triggered + ExpertBriefing meetings today)
- `/api/projects` — CRUD
- `/api/clients` — CRUD + timeline
- `/api/invoices` — CRUD + finreport
- `/api/documents` — CRUD
- `/api/drive` — file listing (will be expanded in Phase 8)
- `/api/archive` — searches Analysis + ExpertBriefing + Conversations
- `/api/search` — unified search across all entities
- `/api/graph` — Knowledge Graph data for graph-screen
- `/api/jobs` — JobQueue inspection
- `/api/enrich` — Client profile enrichment trigger
- `/api/telegram/send` — proxy for sending Telegram messages from miniapp
- `/api/settings` — user preferences
- `/api/tasks` — CRUD

### 7.3 Connect each screen

For each of 11 screens, replace mock data with `useEffect` + `fetch('/api/...')`:

- home-screen.tsx → /api/alerts + /api/projects + /api/jobs
- projects-screen.tsx → /api/projects (with filtering)
- clients-screen.tsx → /api/clients (+ timeline drilldown)
- finance-screen.tsx → /api/invoices
- docs-screen.tsx → /api/documents
- drive-screen.tsx → /api/drive (will be expanded Phase 8)
- archive-screen.tsx → /api/archive
- models-screen.tsx → /api/settings (model usage stats)
- offices-screen.tsx → /api/projects (project-as-office view)
- team-screen.tsx → /api/clients/team (specialists list from library)
- settings-screen.tsx → /api/settings

### 7.4 Add Telegram auth on every API endpoint

Apply `lib/auth.ts` (from Phase 9.5) to every route's POST/PUT/DELETE.

### 7.5 Test each screen

Open miniapp through bot. Click through each screen. Verify data is live.

### 7.6 Commit

```bash
git add src/
git commit -m "[Phase 7] Miniapp connected: 11 screens use live API data, auth verified"
git push origin feature/v4.1-migration
```

## Acceptance criteria for Phase 7

- [ ] All 11 screens display live data from Prisma
- [ ] All API endpoints verify Telegram auth
- [ ] No screen shows mock/placeholder data
- [ ] CRUD operations work where applicable

---

# PHASE 8 — Drive-screen Telegram-Drive style

**Goal:** redesign drive-screen as full file explorer in Telegram-Drive UX (virtual scrolling, drag & drop, PDF viewer, image previews, folder structure).

**Estimated duration:** 1-2 days

**Risk level:** low

## Tasks

### 8.1 Extend DriveFile model

Schema update in Phase 1 should already include:

```prisma
model DriveFile {
  // ... existing fields
  tags          String[]   // tags for filtering
  parentFolder  String?    // folder path
  thumbnailUrl  String?
  linkedAnalysisId Int?
  linkedBriefingId Int?
}
```

If not — add migration:

```bash
npx prisma migrate dev --name extend_drive_file
```

### 8.2 Implement drive-screen in TG-Drive style

Apply patch:

```bash
cp ~/transition_pack/patches/miniapp_drive_screen.tsx src/components/screens/drive-screen.tsx
```

Features:
- File explorer grid with virtual scrolling (use react-window)
- Folder navigation (breadcrumbs)
- Drag & drop upload (Telegram WebApp's MainButton + file input)
- PDF viewer modal (react-pdf)
- Image preview modal
- Tag filtering
- Search within Drive

### 8.3 Update /api/drive

```typescript
GET /api/drive?folder=...&tag=...&search=...&page=1
POST /api/drive  // upload (multipart/form-data)
DELETE /api/drive?id=...
PATCH /api/drive  // update tags, folder
```

### 8.4 Test

In miniapp:
- Navigate to Drive screen
- Upload a PDF — verify it appears
- Click PDF — viewer opens
- Tag the file — filter by tag works
- Move to folder — folder navigation works

### 8.5 Commit

```bash
git add src/components/screens/drive-screen.tsx src/app/api/drive/route.ts prisma/
git commit -m "[Phase 8] Drive-screen: Telegram-Drive UX, PDF viewer, drag&drop, tags"
git push origin feature/v4.1-migration
```

## Acceptance criteria for Phase 8

- [ ] Drive screen has TG-Drive-like UX
- [ ] Drag & drop upload works
- [ ] PDF viewer renders
- [ ] Image previews show
- [ ] Tag filtering works
- [ ] Folders navigable

---

# PHASE 10 — Final wiring + end-to-end smoke tests

**Goal:** comprehensive smoke testing of all integrated features, fixes, then merge to main.

**Estimated duration:** 1 day

**Risk level:** medium (last chance before merge)

## Tasks

### 10.1 End-to-end user journeys

Test each:

**Journey A — Investment decision:**
1. `/expert встреча с FusionCorp завтра, рассматриваю $5M инвестицию`
2. Verify Expert briefing created with 7 combat questions, citations, KB sources
3. Verify Yana also triggered OSP analysis on fusion industry
4. Verify Expert briefing summary auto-published in Archive channel
5. Open miniapp → archive-screen shows the briefing
6. After meeting: `/expert-debrief <id> поговорил с командой, они подтвердили tritium gap`
7. `/expert-rate <id>` → record scores
8. Verify ExpertBriefing record updated with debrief + scores

**Journey B — Strategic forecast:**
1. `/analyze политическая ситуация в Грузии`
2. Verify OSP V2 produces 5-level analysis with scenarios + indicators
3. Verify auto-published to Archive
4. `/watch <id>`
5. Wait for next morning — verify daily watch sweep notifications
6. Manually `/verify <id>` after 1 month — verify Brier score calculated
7. `/score` — verify calibration metrics

**Journey C — Technology tracking:**
1. `/scan ИИ-агенты для разработки кода`
2. Verify ЛЗ produces KnowledgeArtifact with disruption score
3. `/track ИИ-агенты` to add to watchlist
4. `/lzinventory` shows the topic
5. Verify weekly recalculation runs (manual trigger via test command)

**Journey D — Voice via miniapp:**
1. Open miniapp through bot menu
2. Click chat-overlay
3. Voice message: "Какие сейчас активные прогнозы?"
4. Verify STT works
5. Verify response from Yana routing to OSP archive
6. Verify TTS plays response back

**Journey E — Drive workflow:**
1. Receive contract.pdf via Telegram
2. Upload to Drive via miniapp drag & drop
3. Tag #договор #2026
4. Open in PDF viewer
5. Verify it links to project (manual link)

### 10.2 Fix any bugs found

For each bug — separate commit `[Phase 10 fix] <description>`.

### 10.3 Performance check

```bash
# Render bot logs:
# Verify response times for /analyze, /expert acceptable (< 2 min for full)
# Verify miniapp page load < 3 sec
# Verify scheduler tasks complete without errors
```

### 10.4 Update README

```bash
cp ~/transition_pack/README.md README.md
git add README.md
```

### 10.5 Final commit

```bash
git add migration_logs/
git commit -m "[Phase 10] v4.1 migration complete: all phases verified, end-to-end tests passed"
git push origin feature/v4.1-migration
```

### 10.6 Owner sign-off

Send owner a summary message:

```
v4.1 migration ready for review. Branch: feature/v4.1-migration
Tested journeys: A (Investment), B (Forecast), C (Tech tracking), D (Voice miniapp), E (Drive)
Issues found and fixed: <list>
Ready to merge to main? Confirm.
```

After owner confirms:

```bash
git checkout main
git merge feature/v4.1-migration --no-ff -m "Merge v4.1 architecture migration"
git push origin main
git tag v4.1.0
git push origin v4.1.0
```

### 10.7 Clean up backup files

```bash
rm -rf skills/fosved/spd.backup_v1
rm -f library/osp.md.backup_v2 library/upravlenie.md.backup_*
rm -f spd.js.backup_v1 army.js.backup scheduler.js.backup_v1
rm -f prisma/schema.prisma.backup_v3

git add -A
git commit -m "[Phase 10] Cleanup: remove pre-migration backups"
git push origin main
```

## Acceptance criteria for Phase 10

- [ ] All 5 journeys pass end-to-end
- [ ] No critical bugs remain
- [ ] Performance acceptable
- [ ] Owner signed off
- [ ] Merge to main complete
- [ ] Tag v4.1.0 created
- [ ] Backups cleaned up

---

# PHASE STATUS TRACKING

Update after each Phase completed:

| Phase | Name | Status | Completed | Notes |
|-------|------|--------|-----------|-------|
| 0 | Foundation | ⏳ Pending | — | |
| 1 | Schema migration | ⏳ Pending | — | |
| 2 | OSP V2 | ⏳ Pending | — | |
| 3 | ЛЗ Knowledge Lab | ⏳ Pending | — | |
| 4 | Expert + Research | ⏳ Pending | — | |
| 9 | Voice/Chat miniapp | ⏳ Pending | — | (reordered: after 4) |
| 5 | Yana finalization | ⏳ Pending | — | |
| 6 | Archive auto-publish | ⏳ Pending | — | |
| 7 | Miniapp connect | ⏳ Pending | — | |
| 8 | Drive-screen redesign | ⏳ Pending | — | |
| 10 | Final + merge | ⏳ Pending | — | |

Status legend: ⏳ Pending | 🔄 In progress | ✅ Complete | ⚠️ Blocked | ❌ Failed

---

# AFTER MIGRATION — what's next

This migration brings fosved-bot to v4.1. Future versions:

**v4.2 candidates** (post-v4.1):
- Deepen Юрист, Финансы, Разработка, Продукт, Операции specialists with full skill packs
- Add Cowork-style desktop app (native Windows/macOS for power users)
- pgvector for semantic search across full archive
- Subagents in chat-overlay for complex multi-step queries

**v5.0 candidates** (months out):
- Multi-user support (foundation already in `userId` fields)
- AI Studio specialist activated
- Кузница (Veteran) self-improvement engine activated

These are not part of this migration. Mentioned for context only.

---

**End of MIGRATION_PLAN.md**
