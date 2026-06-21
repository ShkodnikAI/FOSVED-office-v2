# Kuznitsa Department Integration Pack — Кузница кадров

**Block:** Kuznitsa (Кузница кадров / Veteran) Department for fosved-bot
**Version:** 1.0
**Date:** 2026-05
**Target:** existing fosved-bot v4.1 (+ all prior departments)
**Owner:** @ShkodnikAI (Telegram ID 2044005421)

---

## WHAT THIS IS

A self-contained add-on that adds the **Kuznitsa (Кузница кадров)** — the
department whose single function is to **create and re-train all the other
departments**. Its specialist is the Veteran.

Built strictly per `METHODOLOGY.md` Part III.

---

## THE RECURSIVE NATURE — read this first

Every other department does *work*. The Kuznitsa does *departments* — it
creates them, trains them, debriefs them, retrains them.

And the Kuznitsa is **recursive**: it is built by the same methodology it
teaches. This package is the methodology applied to itself. The Kuznitsa has
the 7 architecture components, an explicit psychotype, hard rules, a 3-level
learning loop, 8 skills in 3 tiers, an archive model, a numeric metric — because
it was run through the same 10-stage checklist as every other department.

This is not a paradox. It is validation. A methodology that could not produce
its own enforcer would not be trustworthy. If this package looks like the other
department packages — that is exactly the point.

The Kuznitsa even applies its skills to itself: `psychotype-assessment` checks
the Kuznitsa's own Методист + Параноик; `skill-quality-review` holds the
Kuznitsa's own skills to the standard; the quarterly review debriefs the
Kuznitsa.

---

## START HERE

1. Read this README.
2. Read `KUZNITSA_INTEGRATION_PLAN.md` — the 9-phase integration plan
   (K1–K9) with concrete commands and acceptance criteria.
3. Hand the unpacked folder to Claude Code, proceed phase by phase.

**Prerequisites:** fosved-bot v4.1 deployed, `ARCHIVE_CHANNEL_ID` configured.

---

## PACKAGE CONTENTS

```
kuznitsa-dept-integration/
├── README.md                          ← you are here
├── KUZNITSA_INTEGRATION_PLAN.md        ← 9-phase plan
│
├── library/
│   └── kk.md                            profile — Методист + Параноик (the Veteran)
│
├── prisma/
│   └── kk-schema.prisma                  2 new models (append-only)
│
├── skills/fosved/kk/                     ← 8 SKILL.md files
│   │  Tier 1 — methodological core (5):
│   ├── methodology-application/          run a department through the 10-stage checklist
│   ├── specialist-creation/              build a department from nothing
│   ├── psychotype-assessment/            choose / check a psychotype
│   ├── skill-quality-review/             hold skills to the standard
│   ├── debrief-protocol/                 structural, non-accusatory error analysis
│   │  Tier 2 — domain depth (2):
│   ├── training-program-design/          design a specialist's learning curriculum
│   ├── polygon-test-design/              build the 5-10 task polygon
│   │  Tier 3 — special techniques (1):
│   └── recalibration-orchestration/      full retraining (owner-approval-gated)
│
├── lib/
│   └── kk.js                             department engine
│
└── patches/                              ← 4 target-state references
    ├── README.md
    ├── army-kk-patch.js                  SPECIALISTS + SKILLS_MAP
    ├── bot-kk-handlers.js                 7 command handlers
    ├── scheduler-kk-patch.js              3 scheduled tasks
    └── upravlenie-kk-routing-patch.md     Yana routing + the Kuznitsa/Yana boundary
```

---

## THE DEPARTMENT

**Psychotype: Методист + Параноик.** Methodist — process over inspiration,
repeatability over brilliance; the Kuznitsa runs every department through the
same checklist, the same polygon, the same structural debrief. Paranoid — hunts
methodology holes where others see a finished department; catches the 6
methodology antipatterns before they harden.

The Veteran is a strict instructor — structural, unsentimental — but never
cruel. Debriefs diagnose the methodology, never blame the specialist.

**8 hard rules**, including: no department created without all 10 checklist
stages; no specialist released without a polygon pass-rate ≥ 70%; no skill
without ≥ 3 anti-patterns; debriefs are structural, never accusatory; a
department is not retrained on one bad month (two is a pattern, one is noise);
`/recalibrate-dept` requires explicit owner approval.

**Main metric** (METHODOLOGY.md II.3.9): new-specialist polygon pass-rate
(target ≥ 70%); retrained-department improvement (≥ 15% per quarter);
re-work rate (< 20%).

8 skills, 7 commands.

---

## THE KUZNITSA / YANA BOUNDARY

Both the Kuznitsa and Yana sit "above" the working departments — the boundary
matters:

- **Yana** decides who gets a task **right now** — operational, real-time.
- **The Kuznitsa** decides what a department **should be** — methodological,
  long-horizon.

Yana is "what to do now". The Kuznitsa is "what to be". They exchange signals:
Yana tells the Kuznitsa when a department keeps missing; the Kuznitsa tells Yana
when a department has been retrained and now behaves differently. Full detail in
`patches/upravlenie-kk-routing-patch.md`.

---

## DATABASE — 2 NEW MODELS

Append-only to `schema.prisma`. No existing model modified.

- `TrainingSession` — one record per Kuznitsa operation (recruit / train /
  polygon / debrief / assess / recalibrate); holds the 10-stage checklist, the
  polygon results, the owner-approval gate for recalibration
- `KuznitsaMonthlyReview` — aggregated monthly review across all departments,
  surfacing which departments need the Veteran's attention

---

## COMMANDS (7)

`/recruit` — create a new department from scratch (the 10-stage checklist)
`/train` — assemble a learning curriculum for a specialist
`/polygon` — run a department through training tasks; pass-rate
`/debrief` — structural error analysis of a struggling department
`/assess` — assess a psychotype and its fit to the function
`/recalibrate-dept` — full retraining (heavy; requires owner approval)
`/forge-status` — overall Kuznitsa status

---

## SCHEDULED TASKS (3)

| When | Task |
|------|------|
| daily 07:30 | departments-needing-attention check |
| Mon 08:00 | weekly Kuznitsa status for the owner |
| 1st 09:00 | monthly aggregated review across all departments |

---

## RISK PROFILE

Low across the board — a single additive department, no existing model touched,
only 2 new models. Realistic effort: 3 days with a debugging buffer.

---

## AFTER THIS BLOCK — what the Kuznitsa is for

With the Kuznitsa in place, fosved-bot has a working mechanism to create and
improve departments as *operations*, not as hand-built integration packs.

The recommended first real use (METHODOLOGY.md epilogue): run the Kuznitsa on
one existing department as a pilot — **Finance** is the suggested target (clear
metrics, transparent verification, low error risk). Use `/debrief` on it, see
what the structural analysis surfaces, let it drive a skill improvement. That
pilot gives the methodology its first genuine feedback cycle.

From there, new departments are born through `/recruit`. The Kuznitsa is the
office's capacity to grow and correct itself.

When you return after implementation — report how it went, and we decide the
pilot together.

---

**End of README.md**
