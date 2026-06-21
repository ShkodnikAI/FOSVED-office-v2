# VISUAL_DEPT_INTEGRATION_PLAN.md — Visual Department Add-on

**Block:** Visual Department Integration
**Target:** existing fosved-bot v4.1 (post-migration)
**Owner:** @ShkodnikAI (Telegram ID 2044005421)
**Block version:** 1.0
**Date:** 2026-05-13
**Estimated duration:** 5-7 days of focused work
**Risk level:** low-medium (additive, doesn't break existing)

---

## PURPOSE OF THIS BLOCK

This block adds the **Visual Department** to an already-running v4.1 fosved-bot. It is **additive only** — does not modify existing departments' core logic. After this block, every analysis/briefing/artifact will auto-receive a structured visual card, and on-demand commands will produce four other types of visualization.

**Prerequisites — must be done before applying this block:**

- ✅ fosved-bot v4.1 migration complete (all 10 phases of MIGRATION_PLAN.md)
- ✅ OSP V2, ЛЗ, Expert departments working with archive data
- ✅ ARCHIVE_CHANNEL_ID configured and lib/archive-publisher.js working
- ✅ Branch `feature/visual-dept` created from main (or current stable)

If these are not in place — STOP. Do not apply this block.

---

## WHAT THIS BLOCK ADDS

### Five types of visual output

1. **Compression Visual (Type 1)** — multi-page report → one image
2. **Memorable Infographic (Type 2)** — applies modern infographic best practices for memorability
3. **Analysis Card (Type 3)** — strict template per analysis type, comparable side-by-side
4. **Reference Sheet (Type 4)** — one-page reference card for product/project/system
5. **Premium Art (Type 5)** — premium publication-quality infographic (semi-manual)

### New components

**Profile:** `library/visual.md` — Visual Department profile (Designer-Methodist + Perfectionist + Curator)
**Skills:** 11 SKILL.md files in `skills/fosved/visual/` (5 Tier 1 + 5 Tier 2 + 1 Tier 3)
**Prisma models:** VisualArtifact, VisualTemplate, StyleEvolution (3 new models)
**Library module:** `lib/visual.js` (~600 lines)
**Bot commands:** 8 new commands (`/visual`, `/visual-archive`, `/visual-template`, etc.)
**Scheduler tasks:** 3 new (daily archive scan, weekly recall tests, quarterly style evolution)
**Hooks into existing departments:** OSP/Expert/ЛЗ auto-generate Type 3 cards on completion

### What this block does NOT change

- Existing handlers in bot.js for /analyze, /expert, /scan — only adds hook AFTER completion
- Existing skills of OSP/Expert/ЛЗ — unchanged
- Existing Prisma models — unchanged (only adds new tables)
- Yana coordinator — only adds 4-5 routing triggers, doesn't refactor
- miniapp — only adds visual-gallery component, doesn't modify existing screens (Phase X9 optional adds gallery to drive-screen)

---

## INTEGRATION PHASES

### Phase X1 — Foundation (very low risk)

**Duration:** half day

```bash
cd ~/repos/fosved-bot
git checkout main
git pull origin main
git checkout -b feature/visual-dept
git push -u origin feature/visual-dept

# Verify prerequisites
ls library/expert.md library/lz.md library/osp.md   # all 3 must exist (v4.1 done)
ls lib/archive-publisher.js lib/research.js          # both must exist
npx prisma db pull --print | grep -i "expertbriefing\|knowledgeartifact" | head -5  # tables exist?

# Create migration_logs directory for this block
mkdir -p migration_logs/visual_integration
echo "Visual Dept integration started $(date)" > migration_logs/visual_integration/started.md

git add migration_logs/
git commit -m "[Visual Dept] Foundation: branch created, prerequisites verified"
git push origin feature/visual-dept
```

**Acceptance:** branch exists, prerequisites confirmed.

---

### Phase X2 — Schema additions (low risk, additive only)

**Duration:** half day

Apply schema additions from `prisma/visual-dept-schema.prisma`. This adds 3 new models without touching existing ones.

```bash
cd ~/repos/fosved-bot

# Backup current schema
cp prisma/schema.prisma prisma/schema.prisma.backup_pre_visual

# Append visual-dept models to existing schema
# (Don't replace — append. Use editor to add models from
#  visual-dept-integration/prisma/visual-dept-schema.prisma at end of file)

cat ~/visual-dept-integration/prisma/visual-dept-schema.prisma >> prisma/schema.prisma

# Validate syntax
npx prisma validate

# Generate migration
npx prisma migrate dev --name add_visual_department --create-only

# Inspect generated SQL
cat prisma/migrations/*_add_visual_department/migration.sql

# Should only show CREATE TABLE for 3 new tables (visual_artifacts, visual_templates, style_evolutions)
# If you see ALTER TABLE or DROP anywhere - STOP, investigate

# Apply migration
npx prisma migrate deploy

# Regenerate client
npx prisma generate

# Verify
node -e "
const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
Promise.all([
  p.visualArtifact.count(),
  p.visualTemplate.count(),
  p.styleEvolution.count()
]).then(([a, t, e]) => {
  console.log('VisualArtifact:', a, 'VisualTemplate:', t, 'StyleEvolution:', e);
  p.\$disconnect();
});
"
# Expected: 0 0 0 (empty tables)
```

```bash
git add prisma/
git commit -m "[Visual Dept] Schema: VisualArtifact, VisualTemplate, StyleEvolution models"
git push origin feature/visual-dept
```

**Acceptance:** 3 new tables exist, empty, Prisma client regenerated, existing tables untouched.

**Rollback:** restore `schema.prisma.backup_pre_visual`, drop new tables manually if needed.

---

### Phase X3 — Library module lib/visual.js (low risk)

**Duration:** half day

```bash
cd ~/repos/fosved-bot
cp ~/visual-dept-integration/lib/visual.js lib/visual.js

# Quick syntax check
node -c lib/visual.js

# Module exports check
node -e "const v = require('./lib/visual.js'); console.log(Object.keys(v));"
# Expected: generateAnalysisCard, generateCompressionVisual, generateReferenceSheet,
#           generateMemorableInfographic, generatePremiumSpec, listTemplates,
#           seedDefaultTemplates, computeContentHash, ...
```

```bash
git add lib/visual.js
git commit -m "[Visual Dept] Add lib/visual.js — generation engine"
git push origin feature/visual-dept
```

**Acceptance:** module loads without error, exports listed functions.

---

### Phase X4 — Default templates seeding (low risk)

**Duration:** few hours

Seed initial VisualTemplate records — one per type of visual:

```bash
cd ~/repos/fosved-bot

# Run seed script (lib/visual.js has seedDefaultTemplates function)
node -e "
const visual = require('./lib/visual.js');
visual.seedDefaultTemplates().then(count => {
  console.log('Seeded', count, 'templates');
  process.exit(0);
});
"
```

Templates seeded:
- `osp_analysis_card` (Type 3 for OSP Analysis)
- `expert_briefing_card` (Type 3 for ExpertBriefing)
- `lz_artifact_card` (Type 3 for KnowledgeArtifact)
- `verification_dashboard` (Type 2 for AnalysisVerification)
- `client_reference_sheet` (Type 4 for Client)
- `project_reference_sheet` (Type 4 for Project)
- `compression_visual_long` (Type 1 for any source)
- `premium_spec_template` (Type 5 spec format)

```bash
# Verify
node -e "
const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
p.visualTemplate.findMany().then(t => {
  console.log('Templates:', t.map(x => x.type));
  p.\$disconnect();
});
"
```

**Acceptance:** 8 templates seeded.

---

### Phase X5 — Skills + profile (low risk)

**Duration:** 1 day

```bash
cd ~/repos/fosved-bot

# Add profile
cp ~/visual-dept-integration/library/visual.md library/visual.md

# Add skills
mkdir -p skills/fosved/visual
cp -r ~/visual-dept-integration/skills/fosved/visual/. skills/fosved/visual/
find skills/fosved/visual -name SKILL.md | wc -l   # expect 11
```

Update `army.js` — add Visual specialist:

```bash
# Apply army.js patch from integration pack
# (see patches/army-visual-patch.js — append entries to SPECIALISTS and SKILLS_MAP)

# Verify
grep -A 3 "visual" army.js | head -10
```

```bash
git add library/visual.md skills/fosved/visual/ army.js
git commit -m "[Visual Dept] Profile + 11 skills + army.js registration"
git push origin feature/visual-dept
```

**Acceptance:** profile present, 11 skills present, army.js registers visual.

---

### Phase X6 — Bot commands (medium risk)

**Duration:** 1 day

Apply bot command handlers for Visual Department:

```bash
cd ~/repos/fosved-bot

# Read the bot commands patch:
cat ~/visual-dept-integration/patches/bot-visual-handlers.js

# Manually integrate handlers into bot.js (don't blind-copy — bot.js has other handlers)
# Add at end of handler section, before module.exports if any

# Commands to add:
# /visual <type> <source_id>     - generate specific visual for existing source
# /visual-card <source_id>       - generate Type 3 analysis card (default)
# /visual-archive [filter]        - list visual artifacts
# /visual-show <id>              - retrieve and display specific artifact
# /visual-template <type>        - inspect template for type
# /visual-style                  - show current style guide
# /visual-spec <source_id>       - generate Type 5 premium spec for manual production
# /visual-recall <id>            - run visual recall test on artifact
```

Verify syntax:
```bash
node -c bot.js
```

Local smoke test:
```bash
node bot.js &
# In Telegram:
/visual-template osp_analysis_card
# Expect: template spec returned

/visual-archive
# Expect: "No visuals yet" or list

kill %1
```

```bash
git add bot.js
git commit -m "[Visual Dept] Bot commands: /visual, /visual-archive, /visual-show, etc."
git push origin feature/visual-dept
```

**Acceptance:** commands registered, none crash, /visual-template returns seeded template.

---

### Phase X7 — Hooks into existing departments (medium risk)

**Duration:** 1 day

This is the **most important phase** — hooks the auto-generation of Type 3 cards after each /analyze, /expert, /scan.

```bash
cd ~/repos/fosved-bot

# Inspect existing handler completion points:
grep -n "Analysis created\|analysis.id\|ExpertBriefing.*create\|KnowledgeArtifact.*create" bot.js | head -10
```

Add hooks **AFTER** the existing success message but **BEFORE** the response is sent:

```javascript
// In /analyze handler completion, after analysis is saved:
const visual = require('./lib/visual.js');
const visualArtifact = await visual.generateAnalysisCard({
  sourceType: 'analysis',
  sourceId: analysis.id,
  templateType: 'osp_analysis_card'
});
if (visualArtifact && process.env.ARCHIVE_CHANNEL_ID) {
  await visual.publishToArchive(visualArtifact);
}
```

Similarly for /expert and /scan handlers.

**Critical:** wrap in try/catch — visual generation failure should NOT fail the underlying analysis.

```javascript
try {
  const visualArtifact = await visual.generateAnalysisCard({...});
  // ...
} catch (e) {
  console.error('[visual] Auto-generation failed (non-blocking):', e.message);
  // Continue without failing the analysis
}
```

Test:
```bash
node bot.js &
# In Telegram:
/analyze тест визуальной генерации
# Expect: analysis completes normally
# Then: visual card appears in archive channel within ~5-10 seconds
# Check DB:
node -e "
const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
p.visualArtifact.findMany({ orderBy: { createdAt: 'desc' }, take: 3 }).then(v => {
  console.log(v.map(x => ({ id: x.id, type: x.type, tier: x.tier, sourceType: x.sourceType, sourceId: x.sourceId })));
  p.\$disconnect();
});
"
```

```bash
git add bot.js
git commit -m "[Visual Dept] Auto-generation hooks in /analyze, /expert, /scan"
git push origin feature/visual-dept
```

**Acceptance:** /analyze auto-generates a VisualArtifact, publishes to channel. /expert and /scan same. Failures are non-blocking.

---

### Phase X8 — Scheduler tasks (low risk)

**Duration:** half day

Add scheduler tasks for Visual Department lifecycle:

```bash
cd ~/repos/fosved-bot

# Inspect scheduler.js:
grep -n "cron.schedule" scheduler.js | head -10
```

Add three tasks:

```javascript
// Daily pattern scan — 03:00 — looks for new infographic patterns in the world
cron.schedule('0 3 * * *', async () => {
  try {
    const visual = require('./lib/visual.js');
    await visual.dailyPatternScan();
  } catch (e) {
    console.error('[visual daily scan]', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// Weekly recall test — Sunday 19:00 — prompts owner to test recall on random old artifact
cron.schedule('0 19 * * 0', async () => {
  try {
    const visual = require('./lib/visual.js');
    await visual.weeklyRecallPrompt();
  } catch (e) {
    console.error('[visual recall prompt]', e.message);
  }
}, { timezone: 'Europe/Moscow' });

// Quarterly style evolution — Jan/Apr/Jul/Oct 1st 10:30 — review and update templates
cron.schedule('30 10 1 1,4,7,10 *', async () => {
  try {
    const visual = require('./lib/visual.js');
    await visual.quarterlyStyleEvolution();
  } catch (e) {
    console.error('[visual quarterly]', e.message);
  }
}, { timezone: 'Europe/Moscow' });
```

```bash
git add scheduler.js
git commit -m "[Visual Dept] Scheduler: daily pattern scan, weekly recall, quarterly evolution"
git push origin feature/visual-dept
```

**Acceptance:** scheduler tasks registered, no crash on bot startup.

---

### Phase X9 — Yana routing (low risk)

**Duration:** few hours

Update Yana profile to route visual-related queries:

```bash
cd ~/repos/fosved-bot

# Add routing block to library/upravlenie.md
# (See patches/upravlenie-visual-routing-patch.md for additions)
```

Triggers:
- "сделай инфографику", "визуализируй", "нарисуй карточку"
- "/visual", "/visual-card"
- "покажи визуально", "покажи на схеме"
- "premium инфографика", "для публикации"

```bash
git add library/upravlenie.md
git commit -m "[Visual Dept] Yana routing for visual queries"
git push origin feature/visual-dept
```

**Acceptance:** Yana correctly routes visual queries to Visual department.

---

### Phase X10 — Optional miniapp gallery (medium risk, can be deferred)

**Duration:** 1 day (skip if no capacity)

Add a `/visuals` route in miniapp that shows visual artifacts grid:

```bash
cd ~/repos/fosved-miniapp
git checkout -b feature/visual-dept

# Add API endpoint
mkdir -p src/app/api/visuals
cp ~/visual-dept-integration/patches/miniapp-visuals-route.ts src/app/api/visuals/route.ts

# Add screen
cp ~/visual-dept-integration/patches/miniapp-visuals-screen.tsx src/components/screens/visuals-screen.tsx

# Register screen in fosved-app.tsx navigation
# (Manual edit — add nav item and route)

# Test locally
npm run dev
# Open localhost:3000, navigate to /visuals
# Verify grid renders

git add src/
git commit -m "[Visual Dept] Miniapp visual gallery screen"
git push origin feature/visual-dept
```

**Acceptance:** miniapp has visuals-screen showing artifacts grid, click opens artifact.

---

### Phase X11 — Final smoke test + merge (medium risk)

**Duration:** half day

End-to-end test:

```
# In Telegram with bot:

1. /analyze экспансия Китая в редкоземельные металлы
   Expect: Analysis created → VisualArtifact (Type 3) auto-generated → published in archive channel

2. /expert встреча с биотех стартапом через 24 часа, $5M вложение, мРНК-вакцина
   Expect: ExpertBriefing → VisualArtifact (Type 3 expert card) → published

3. /visual compression osp 1
   Expect: Type 1 compression visual for Analysis #1 generated

4. /visual reference client 1
   Expect: Type 4 reference sheet for Client #1

5. /visual-spec expert 1
   Expect: Type 5 premium spec (JSON) for ExpertBriefing #1

6. /visual-archive
   Expect: list of all generated visuals

7. /visual-recall <id>
   Expect: prompt to recall what artifact shows
```

If all pass:

```bash
cd ~/repos/fosved-bot
git checkout main
git merge feature/visual-dept --no-ff -m "Add Visual Department (5-type infographic system)"
git push origin main
git tag v4.1-visual
git push origin v4.1-visual

# Same for miniapp if Phase X10 done:
cd ~/repos/fosved-miniapp
git checkout main
git merge feature/visual-dept --no-ff -m "Add Visual Department gallery to miniapp"
git push origin main
git tag v4.1-visual
git push origin v4.1-visual
```

**Acceptance:** all 6 smoke tests pass, merged to main, tagged.

---

## TYPES OF VISUAL OUTPUT — full reference

### Type 1 — Compression Visual

**Purpose:** multi-page report → single image
**Trigger:** `/visual compression <source_type> <source_id>` or auto for deepexpert/full-analysis
**Format:** SVG (vector, scales to any size)
**Generation:** Claude generates SVG directly with structured layout (header, 4-6 sections, footer)
**Time:** 10-30 seconds
**Cost:** ~5-10K tokens Claude
**Storage:** SVG string in VisualArtifact.content
**Examples of content:** full 5-level OSP topology with all scenarios, forces, bifurcations on one page; full deepexpert briefing with all combat questions, failure modes, citations on one page

### Type 2 — Memorable Infographic

**Purpose:** apply modern infographic best practices for max memorability
**Trigger:** `/visual memorable <source_id>` (explicit request)
**Format:** SVG with rich visual elements (icons, color-coded sections, scale comparisons, faces if relevant, motion implied)
**Generation:** Claude generates SVG applying:
- Golden ratio proportions
- F-pattern or Z-pattern reading flow
- Color psychology (Brand palette)
- Visual hierarchy through size and contrast
- Emotional hooks (faces, scale comparisons, surprise)
- Gestalt principles (proximity, similarity, closure)
**Time:** 30-60 seconds
**Cost:** ~10-20K tokens
**Storage:** SVG in content
**Examples:** "Why this technology will disrupt by 2028" with visual scale comparison, before/after panels, recognizable icons

### Type 3 — Analysis Card

**Purpose:** standardized card per analysis type for side-by-side comparison
**Trigger:** AUTOMATIC for every /analyze, /expert, /scan (via hooks)
**Format:** SVG, strict template, same proportions for all instances of same type
**Generation:** template-driven — load template, fill fields from source data, render
**Time:** 2-5 seconds (templated)
**Cost:** ~2-5K tokens
**Storage:** SVG in content; same template_version across cards
**Examples:**
- All OSP Analysis cards have header (topic/date/confidence), 5-level topology block, scenarios block, verification date — always same positions
- All Expert briefing cards have header, combat questions block (top 5), failure modes block, red flags block
- All ЛЗ artifact cards have header, hype position indicator, disruption probability gauge, technology profile block

**This is the systematization function — most important type for daily use.**

### Type 4 — Reference Sheet

**Purpose:** one-page reference card about a product/project/system/company
**Trigger:** `/visual reference <entity_type> <entity_id>`
**Format:** Dense single-page layout — like military reference card, like Wikipedia infobox but visual
**Generation:** template + data aggregation across entity (timeline + key params + history + risks + contacts)
**Time:** 30-60 seconds
**Cost:** ~10-20K tokens
**Storage:** SVG in content
**Examples:**
- Client reference sheet: contact, tier, timeline events count, financial summary, current projects, status
- Project reference sheet: name, dates, team, budget, deadlines, status, related analyses, related documents
- Technology reference sheet: from KnowledgeArtifact — full profile, key players, disruption probability, watchlist status

### Type 5 — Premium Art

**Purpose:** publication-quality infographic (like provided BMW/SR-71/cake examples)
**Trigger:** `/visual-spec <source_id>` (generates spec for manual production)
**Format:** JSON spec — describes what should be in the image, what Midjourney prompt to use, what overlays to add in Figma
**Generation:** Claude generates structured spec, NOT the image itself
**Time:** 1-2 minutes for spec, then 1-2 hours your work in Midjourney + Figma
**Cost:** ~5-10K tokens + your time + Midjourney subscription ($30/mo) + Figma (free)
**Storage:** spec JSON in content, final image manually uploaded to drive-screen with tag #premium
**Examples:** quarterly portfolio infographic, "best analyses of the year", representative artifacts for sharing

---

## STYLE EVOLUTION — how the department self-improves

### Daily pattern scan (automated, 03:00)

The department uses web search + image search to find recent high-quality infographics (Reddit r/DataIsBeautiful trends, IMa Studio releases, Information is Beautiful Awards). For each:
- Analyzes what works (color, layout, hook, density)
- Stores observations
- Once per week, summarizes for owner

### Weekly recall test (Sunday 19:00)

Picks a random VisualArtifact from 1-3 months ago. Asks you:
"Без чтения текста — что эта инфографика говорит? Один-два предложения."

Records your answer + actual content. If recall poor — template needs revision.

### Quarterly style evolution (Jan/Apr/Jul/Oct)

Comprehensive review:
- Coverage rate (% analyses with visuals)
- Recall success rate
- Template usage distribution
- New patterns from world-scan worth adopting
- Old patterns to retire
- Generates StyleEvolution record
- Updates template versions if needed

After update, all NEW visuals use new template version. Existing visuals keep their template_version label so you can see evolution.

### Visual portfolio review (annual, late December)

Best of year. Top 30 visuals by recall + relevance. Compiled as premium summary. Optionally manually produced as Type 5 portfolio piece.

---

## INTEGRATION WITH ARCHIVE CHANNEL

After Phase X7, the auto-published Telegram messages in ARCHIVE_CHANNEL_ID will include the visual artifact attached:

```
📊 Препарирование ОСП V2 #42
[VISUAL: Type 3 analysis card attached]
Тема: Экспансия Китая в редкоземельные металлы
...
#осп #прогноз #2026 #визуал_card
```

Hashtag `#визуал_<type>` allows filtering by visual type in channel.

For Type 5 premium artifacts manually produced — owner uploads to drive-screen, system creates VisualArtifact record with `generationMethod: 'midjourney_figma'` and publishes to channel separately.

---

## ROLLBACK PROTOCOL

If something goes wrong:

```bash
cd ~/repos/fosved-bot
git log --oneline | head -20  # find last good commit
git revert <visual-commit-hash>  # revert visual changes
git push origin feature/visual-dept
```

For schema rollback:
```bash
psql "$DATABASE_URL" -c "DROP TABLE visual_artifacts, visual_templates, style_evolutions CASCADE;"
```

For deactivating auto-hooks without removing code:
```bash
# Set in Render env:
VISUAL_AUTO_GENERATION=false
```

Hooks check `process.env.VISUAL_AUTO_GENERATION` and skip if false — emergency disable without code change.

---

## ACCEPTANCE CRITERIA FOR FULL BLOCK

- [ ] 3 new tables in DB (visual_artifacts, visual_templates, style_evolutions)
- [ ] 8 default templates seeded
- [ ] library/visual.md profile present
- [ ] 11 SKILL.md files in skills/fosved/visual/
- [ ] lib/visual.js module loads, exports all listed functions
- [ ] 8 visual commands work in Telegram
- [ ] Auto-hooks in /analyze, /expert, /scan trigger VisualArtifact creation
- [ ] Generated visuals appear in ARCHIVE_CHANNEL_ID
- [ ] 3 scheduler tasks registered
- [ ] Yana routes visual queries correctly
- [ ] Smoke tests for all 5 types pass
- [ ] Merged to main, tagged v4.1-visual
- [ ] migration_logs/visual_integration/ has phase-by-phase notes

---

## ESTIMATED TOTAL EFFORT

- Backend (X1-X8): 3-4 days
- Yana update (X9): few hours
- Miniapp gallery (X10): 1 day (optional)
- Smoke test + merge (X11): half day

**Total: 4-6 days focused work, 5-7 days with buffer.**

---

**End of VISUAL_DEPT_INTEGRATION_PLAN.md**
