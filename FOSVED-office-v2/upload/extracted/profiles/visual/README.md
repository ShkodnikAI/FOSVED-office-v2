# Visual Department Integration — Add-on Block

**Block:** Visual Department for fosved-bot
**Version:** 1.0
**Target:** fosved-bot v4.1 (already deployed and running)
**Owner:** @ShkodnikAI (Telegram ID 2044005421)

---

## What this block is

This is a **self-contained additive block** that adds a Visual Department to an already-running fosved-bot v4.1. It does not modify existing v4.1 architecture — it sits on top.

After applying this block, fosved-bot will:
- Auto-generate visual cards for every analysis/briefing/artifact (Type 3)
- Provide on-demand compression visuals, memorable infographics, reference sheets (Types 1, 2, 4)
- Generate premium spec JSON for manual Midjourney+Figma production (Type 5)
- Maintain visual archive with style evolution tracking
- Run quarterly style reviews with pattern discovery

---

## The five types of visuals

1. **Compression (Type 1)** — multi-page report → one image (auto for deepexpert, full analysis)
2. **Memorable (Type 2)** — applies modern best-practices for memorability (on request)
3. **Analysis Card (Type 3)** — systematized templated card, AUTO for every analysis/briefing/artifact
4. **Reference Sheet (Type 4)** — dense one-page reference for Client/Project/Technology (on request)
5. **Premium Spec (Type 5)** — JSON spec for manual production using Midjourney + Figma (on request)

---

## Prerequisites

Before applying this block, fosved-bot must have:

- [x] v4.1 migration complete (all 10 phases of MIGRATION_PLAN.md from previous transition pack)
- [x] OSP V2, ЛЗ, Expert departments working with archive data
- [x] ARCHIVE_CHANNEL_ID configured
- [x] lib/archive-publisher.js working
- [x] Branch `feature/visual-dept` ready to create

If any of these is missing — STOP. Apply previous transition pack first.

---

## Pack structure

```
visual-dept-integration/
├── README.md                          ← you are here
├── VISUAL_DEPT_INTEGRATION_PLAN.md    ← 11-phase plan with commands
│
├── library/
│   └── visual.md                       ← profile (Visual Department)
│
├── prisma/
│   └── visual-dept-schema.prisma       ← 3 new models (APPEND to schema)
│
├── lib/
│   └── visual.js                       ← generation engine (~700 lines)
│
├── skills/fosved/visual/               ← 11 SKILL.md files
│   ├── visual-grammar/                 (T1)
│   ├── infographic-templates/          (T1)
│   ├── data-to-visual-mapping/         (T1)
│   ├── compression-principle/          (T1)
│   ├── style-evolution-discipline/     (T1)
│   ├── svg-generation/                 (T2)
│   ├── memorable-design-techniques/    (T2)
│   ├── reference-sheet-composition/    (T2)
│   ├── premium-spec-generation/        (T2)
│   ├── type-system-application/        (T2)
│   └── visual-pattern-discovery/       (T3)
│
└── patches/                            ← target-state references for code edits
    ├── army-visual-patch.js             — army.js additions
    ├── bot-visual-handlers.js           — bot.js handlers (8 new commands)
    ├── upravlenie-visual-routing-patch.md — Yana routing additions
    ├── miniapp-visuals-route.ts         — /api/visuals endpoint (miniapp)
    └── miniapp-visuals-screen.tsx       — gallery screen (miniapp, optional)
```

---

## How to apply

If you are Claude Code reading this:

1. **Verify prerequisites** — bot v4.1 must be deployed and stable
2. **Read VISUAL_DEPT_INTEGRATION_PLAN.md** completely — 11 phases with commands
3. **Follow phases X1–X11 in order** — each phase has acceptance criteria
4. **Smoke test after each phase** — don't proceed if previous phase failed
5. **Final phase X11** is smoke test + merge to main

Total estimated effort: 5-7 days of focused work.

If owner is reading this: hand the ZIP to Claude Code with instruction "Apply VISUAL_DEPT_INTEGRATION_PLAN.md — this is an additive block to existing v4.1 fosved-bot."

---

## Risk profile

**Overall: low-medium**

Risks per phase:
- X1 (Foundation): very low
- X2 (Schema, additive): low
- X3 (lib/visual.js): low
- X4 (Templates): low
- X5 (Skills + profile): low
- X6 (Bot commands): medium (handler integration risk)
- X7 (Auto-hooks): medium (touches existing /analyze /expert /scan)
- X8 (Scheduler): low
- X9 (Yana routing): low
- X10 (Miniapp, optional): medium
- X11 (Smoke test + merge): medium

**Highest-risk phase: X7** — hooks added to existing handlers. Implementation discipline: wrap in try/catch, non-blocking, fallback gracefully. Emergency disable available via env `VISUAL_AUTO_GENERATION=false`.

---

## What's locked in (don't reopen)

These decisions are settled:

- **5 types only** (no creep to 6+)
- **Brand palette FIXED** — 7 colors, semantic meaning
- **Typography FIXED** — Inter Tight + Inter + IBM Plex Mono
- **SVG-first output** (not PNG or HTML)
- **Bot API for delivery** (50MB limit accepted)
- **Type 5 manual production** — Midjourney + Figma, no full automation
- **Quarterly evolution cadence** — not weekly tweaks
- **Recall test as quality metric** — subjective but valuable

---

## After applying

Owner gets:
- Every analysis/briefing/artifact comes with an SVG card
- Visual archive accessible via `/visual-archive` and (optionally) miniapp gallery
- Weekly recall tests prompting owner
- Quarterly style evolution reports
- Premium spec generation for important publications

Department self-improves:
- Daily lightweight pattern scan
- Weekly observation aggregation
- Quarterly template version bumps based on recall data + pattern adoption

---

## Block dependency graph

```
v4.1 architecture (must be complete)
       │
       ▼
Phase X1: Foundation
       │
       ▼
Phase X2: Schema additions ──┐
       │                     │ (provides VisualArtifact, VisualTemplate, StyleEvolution)
       ▼                     │
Phase X3: lib/visual.js ─────┤
       │                     │
       ▼                     │
Phase X4: Templates seeded ──┘
       │
       ▼
Phase X5: Skills + profile
       │
       ▼
Phase X6: Bot commands
       │
       ▼
Phase X7: Auto-hooks (touches existing handlers)
       │
       ▼
Phase X8: Scheduler tasks
       │
       ▼
Phase X9: Yana routing
       │
       ▼
Phase X10: Miniapp gallery (optional, can be deferred)
       │
       ▼
Phase X11: Smoke test + merge to main
       │
       ▼
TAG: v4.1-visual
```

---

## Final note

This block makes the fosved-bot output VISUAL by default. Every analysis becomes scannable. The archive becomes browseable. Comparing 50 analyses becomes feasible.

The Visual Department doesn't replace any existing department — it amplifies them by making their outputs comprehensible at a glance.

After applying, the bot you've built becomes not just analytically powerful but also visually navigable. That's the systematization you described.

Good luck.

— Planning session, 2026-05-13
