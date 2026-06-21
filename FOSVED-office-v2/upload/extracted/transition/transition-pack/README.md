# Fosved Office v4.1 — Transition Pack

**Version:** 1.0
**Date:** 2026-05-09
**For:** Migration of `ShkodnikAI/fosved-bot` + `ShkodnikAI/fosved-miniapp` to v4.1 architecture
**Owner:** @ShkodnikAI (Telegram ID 2044005421)

---

## What this pack contains

This pack is the **complete handoff** from the planning session (Claude Opus on claude.ai) to Claude Code (operating in the actual repositories with shell + filesystem + git + Render access).

It contains:
- **Migration plan** with 10 phases, concrete bash/git/prisma commands, acceptance criteria, rollback plans
- **Operational discipline** for Claude Code (when to ask, what to never do)
- **Concentrated context** — why decisions were made, what was rejected, owner profile
- **Methodology source** — full v4.1 architecture and methodology documents
- **Ready-to-use files** — Prisma schema, 5 specialist profiles, 48 SKILL.md files, 2 lib modules
- **Patches** — target-state files for bot.js, scheduler.js, army.js modifications

After unpacking and following the plan, Claude Code can execute the migration in ~3-4 weeks of focused work.

---

## How to use this pack — ABSOLUTE FIRST STEPS

If you are Claude Code reading this for the first time:

### Step 1 — Read these documents IN ORDER

```
1. README.md          (this file — orientation)
2. MIGRATION_PLAN.md   (the operational plan)
3. CLAUDE_CODE_BRIEF.md (your operational discipline)
4. CONTEXT_HANDOFF.md  (why decisions are what they are)
5. METHODOLOGY-v1.md   (skim if methodology basics already familiar)
6. ARCHITECTURE.md     (skim — full v4.1 architecture overview)
```

Do not skip. Each document fills different gaps. Reading all four (1-4) takes about 30 minutes and is required for working competently.

### Step 2 — Verify pack integrity

```bash
cd ~/transition_pack
ls -la

# Should see:
# README.md, MIGRATION_PLAN.md, CLAUDE_CODE_BRIEF.md, CONTEXT_HANDOFF.md
# METHODOLOGY-v1.md, ARCHITECTURE.md, AGENT_INSTRUCTIONS-v3.md
# schema-v4.1.prisma
# library/ (5 .md files)
# skills/fosved/ (3 dirs: spd, lz, expert)
# lib/ (research.js, archive-publisher.js)
# patches/ (6 .js files + README.md)
# migration_logs/ (empty — populated during work)

# Skill counts (verify):
find skills/fosved/spd -name SKILL.md | wc -l   # 24
find skills/fosved/lz -name SKILL.md | wc -l    # 12
find skills/fosved/expert -name SKILL.md | wc -l # 12
```

If any of these fail — pack is incomplete, ask owner for re-export.

### Step 3 — Confirm with owner before any work

Send to owner:
```
Готов к началу v4.1 миграции.
Pack распакован, 48 скиллов на месте, методология прочитана.
Начинаю с Phase 0 (Foundation).
Подтверди старт.
```

Wait for confirmation. Then proceed to Phase 0 in MIGRATION_PLAN.md.

---

## Pack structure

```
transition-pack/
├── README.md              ← you are here
├── MIGRATION_PLAN.md      ← 10-phase plan with commands
├── CLAUDE_CODE_BRIEF.md   ← operational discipline
├── CONTEXT_HANDOFF.md     ← why decisions are what they are
├── METHODOLOGY-v1.md      ← v4.1 methodology source
├── ARCHITECTURE.md        ← v4.1 architecture overview
├── AGENT_INSTRUCTIONS-v3.md ← Yana operational instructions
│
├── schema-v4.1.prisma     ← target Prisma schema (Phase 1)
│
├── library/               ← 5 specialist profiles
│   ├── osp.md             (V3 — OSP V2 with 5-level topology)
│   ├── lz.md              (Knowledge Lab — new dept)
│   ├── expert.md          (Expert — new dept)
│   ├── upravlenie.md      (Yana coordinator v2.1)
│   └── kk.md              (Veteran/Forge — placeholder)
│
├── skills/fosved/         ← 48 SKILL.md files (verbatim copies)
│   ├── spd/               ← 24 OSP V2 skills (10 T1 + 10 T2 + 4 T3)
│   ├── lz/                ← 12 ЛЗ skills (5 T1 + 4 T2 + 3 T3)
│   └── expert/            ← 12 Expert skills (6 T1 + 4 T2 + 2 T3)
│
├── lib/                   ← Node.js modules to copy into bot
│   ├── research.js        ← LDR-inspired iterative research engine
│   └── archive-publisher.js  ← Telegram Archive auto-publication
│
├── patches/               ← target-state references for code changes
│   ├── README.md          ← explains how to use these
│   ├── army-patches.js
│   ├── bot-commands-patches.js
│   ├── expert-army-patch.js
│   ├── expert-bot-commands.js
│   ├── handlers-patches.js
│   └── scheduler-patches.js
│
└── migration_logs/        ← populated by Claude Code during work
    └── (smoke tests, db backups, phase reports)
```

---

## Phase summary (full details in MIGRATION_PLAN.md)

| Phase | Name | Duration | Risk |
|-------|------|----------|------|
| 0 | Foundation (branch, backup, smoke test) | 0.5 day | very low |
| 1 | Schema migration (Prisma v4.1) | 1 day | HIGH |
| 2 | OSP V2 in code (24 skills, new spd.js) | 2-3 days | medium |
| 3 | ЛЗ Knowledge Lab (full new dept) | 2-3 days | low-medium |
| 4 | Эксперт + LDR research engine | 2-3 days | medium |
| 9 | Voice + chat-overlay in miniapp* | 1-2 days | medium |
| 5 | Yana coordinator finalization | 0.5 day | low |
| 6 | Telegram Archive auto-publication | 1 day | low |
| 7 | Miniapp connect to backend (11 screens, 17 endpoints) | 2-3 days | medium |
| 8 | Drive-screen redesign (TG-Drive UX) | 1-2 days | low |
| 10 | Final E2E tests + merge to main | 1 day | medium |

*Phase 9 reordered after Phase 4 (per owner request) for early UI feedback.

**Total:** ~14-22 days of focused work, realistic 3-4 weeks with buffers.

---

## Key architecture decisions (settled — DO NOT REOPEN)

These are decisions from planning. Do not propose alternatives — they were considered.

- **OSP V2 replaces V1** completely (V1 archive empty, drop&recreate)
- **No external services** — all in fosved-bot Node.js, all data in same Postgres
- **No Python, no MTProto, no Tauri** — Node.js / TypeScript only
- **Bot API for files** — accept 50MB limit
- **Single-user logic** but `userId` field everywhere for multi-user readiness
- **Drop placeholder data** — owner confirmed all current data is test/placeholder
- **LDR ideas, not LDR service** — implement core in Node.js (lib/research.js)
- **Separate Archive Channel** from Drive Channel
- **Citation discipline mandatory** for OSP Layer 2 + Expert numerical anchors

Full reasoning in CONTEXT_HANDOFF.md, "KEY DESIGN DECISIONS" section.

---

## What you build (target architecture)

After v4.1 migration, fosved-bot will have:

**Working departments (5):**
- **Управление (Yana)** — coordinator with multi-dept routing
- **ОСП V2** — Strategic Intelligence (5-level topology + forces + bifurcations + 24 skills)
- **ЛЗ** — Knowledge Lab (continuous tech scanning + 12 skills)
- **Эксперт** — Technical due diligence (12 skills + iterative research)
- **Кузница (Veteran)** — placeholder (activated future)

**Other 5 specialists** (Разработка, Юрист, Финансы, Продукт, Операции, AI Studio) preserve current state — handlers exist, deepening planned for v4.2+.

**Infrastructure additions:**
- ResearchSource model + lib/research.js (LDR-inspired)
- ARCHIVE_CHANNEL_ID + lib/archive-publisher.js
- Drive-screen Telegram-Drive UX
- Voice + chat-overlay in miniapp
- 11 miniapp screens connected to live data
- Multi-user readiness (userId fields)

---

## When you're stuck

In order of preference:

1. **Re-read MIGRATION_PLAN.md** — phase you're on may have answer
2. **Re-read CONTEXT_HANDOFF.md** — decisions section may explain
3. **Re-read CLAUDE_CODE_BRIEF.md "Red Flags"** — may match your situation
4. **Check migration_logs/** — prior session may have left notes
5. **Ask owner** with [BLOCKER] format from CLAUDE_CODE_BRIEF.md

Never:
- Invent architecture decisions
- Skip ahead in phases
- "Improve" methodology files
- Push to main without sign-off

---

## Final note from planning session

Owner is non-coder, methodologically sharp, time-constrained. He is trusting you to execute what was carefully designed. The architecture is **fixed**. Your job is implementation, not redesign.

The methodology in skills/ and library/ is dense by design — it encodes professional practice, not chat conversation. Preserve it.

The plan is iterative — each phase has a smoke test gate. Don't proceed if a phase fails. Fix it or rollback.

You have everything you need. Read the four core documents, confirm with owner, start Phase 0.

Good luck.

---

*— Planning session, 2026-05-09*
