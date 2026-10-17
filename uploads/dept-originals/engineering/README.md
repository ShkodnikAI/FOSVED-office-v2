# Engineering Department Integration Pack — Инженерный отдел

**Block:** Engineering Department for fosved-bot
**Version:** 1.0
**Date:** 2026-05
**Target:** existing fosved-bot v4.1 (+ Visual, DDQ, Marketing)
**Owner:** @ShkodnikAI (Telegram ID задаётся переменной OWNER_TELEGRAM_ID)

---

## WHAT THIS IS

A self-contained add-on that adds the **Engineering (Инженерный)** department to
fosved-bot — a department that prepares preliminary engineering calculations in
three disciplines:

- **Structural mechanics** — load-bearing capacity of roofs, greenhouses, frames
- **Hydraulics** — hydraulic lifts and drives
- **Power electronics** — inverters and switching equipment for wind generators
  and solar panels

---

## READ THIS FIRST — what the department is, and is not

The Engineering department is a **project assistant**, not the engineer of
record.

It prepares roughly **80%** of the engineering work — calculations, option
comparisons, load collection, sanity-checks, draft specifications — so that a
licensed engineer's time goes to judgment and sign-off rather than to setup.

It does **not**:
- Sign calculations or design documentation
- Carry legal or insurance responsibility
- Replace the legally-required review by a licensed specialist
- Deliver a result "ready to build"

**Every output carries a disclaimer** stating it is preliminary and requires
review and approval by a licensed engineer of the relevant discipline.

This is not over-caution. Structural, hydraulic and electrical calculations are
areas where an error can cost lives or property — a roof collapse, a lift
failure, a fire from an inverter. A licensed engineer's review and signature is
a legal and engineering requirement, not an optional step. The department is
designed to make that engineer **faster**, never to replace them — the same way
the Fosved Legal department does not replace a lawyer and Finance does not
replace an auditor.

Used as a fast, disciplined assistant to a real engineer, it is valuable. Used
as a substitute for one, it is dangerous. The design — hard rules, the
disclaimer on every output, the engineer-review lifecycle — enforces the former.

---

## START HERE

1. Read this README, especially the section above.
2. Read `ENGINEERING_INTEGRATION_PLAN.md` — the 9-phase integration plan
   (E1–E9) with concrete commands and acceptance criteria.
3. Hand the unpacked folder to Claude Code, proceed phase by phase.

**Prerequisites:** fosved-bot v4.1 deployed, `ARCHIVE_CHANNEL_ID` configured.

---

## PACKAGE CONTENTS

```
engineering-dept-integration/
├── README.md                           ← you are here
├── ENGINEERING_INTEGRATION_PLAN.md      ← 9-phase plan
│
├── library/
│   └── engineering.md                   profile — Параноик + Педант
│
├── prisma/
│   └── engineering-schema.prisma         5 new models (append-only)
│
├── skills/fosved/engineering/            ← 12 SKILL.md files
│   │  Tier 1 — methodological core (5):
│   ├── engineering-disclaimer-discipline/
│   ├── norm-base-fixation/
│   ├── load-case-enumeration/
│   ├── independent-verification/
│   ├── calculation-documentation/
│   │  Tier 2 — discipline blocks (5):
│   ├── structural-load-bearing/          ┐ structural
│   ├── structural-elements-sizing/       ┘
│   ├── hydraulic-drive-design/             hydraulics
│   ├── power-electronics-inverter/       ┐ power
│   ├── renewable-system-matching/        ┘ electronics
│   │  Tier 3 — special techniques (2):
│   ├── feasibility-estimation/
│   └── third-party-calc-review/
│
├── lib/
│   └── engineering.js                    department engine
│
└── patches/                              ← 4 target-state references
    ├── README.md
    ├── army-engineering-patch.js         SPECIALISTS + SKILLS_MAP
    ├── bot-engineering-handlers.js        8 command handlers
    ├── scheduler-engineering-patch.js     3 scheduled tasks
    └── upravlenie-engineering-routing-patch.md   Yana routing + boundaries
```

---

## THE DEPARTMENT

**Psychotype: Параноик + Педант.** Paranoid — systematically asks how a
structure or device will fail, enumerates every load case and failure mode.
Pedant — loses no coefficient, no dimension, no assumption; produces
calculations a reviewing engineer can follow step by step. The same psychotype
as Legal and QA, for the same reason: the cost of a missed error is
catastrophic.

**One department, three discipline blocks.** Tier 1 methodology is shared; Tier
2 skills are grouped by discipline and loaded per task. The department does not
become an "engineer-knows-everything" — each task works only in its block.

**Normative base is a parameter.** Default — Russian Federation
(SP / GOST / PUE). Switchable to international systems (Eurocode / IEC / ISO).
Every calculation fixes its norm base before any number — a calculation without
a stated norm is not permitted.

**10 hard rules**, including: every output carries the preliminary disclaimer;
no calculation without a fixed norm base; no calculation without an enumerated
set of load cases; every result independently verified; assumptions always
conservative; out-of-scope work declined; a "fails" verdict stated plainly.

**Main metric:** engineer-correction rate — the share of calculations in which
the reviewing licensed engineer found a substantive error (target: Year 1 ≤25%,
falling to ≤10%). It measures how clean a basis the department prepares.

12 skills, 8 commands.

---

## DATABASE — 5 NEW MODELS

Append-only to `schema.prisma`. No existing model modified.

- `EngineeringCalculation` — a calculation: discipline, norms, load cases,
  result, the engineer-review lifecycle
- `NormReference` — catalogue of applied norms, with currency tracking
- `DesignReview` — sanity-checks of third-party / internal calculations
- `EngineeringCalculationVerification` — the engineer's review outcome, the
  learning-loop input
- `EngineeringMonthlyReview` — aggregated monthly performance review

---

## COMMANDS (8)

`/calc` — create / list engineering calculations (discipline + task)
`/calc-norms` — fix the normative base (mandatory before calculation)
`/calc-loadcases` — enumerate load cases (mandatory before calculation)
`/calc-verify` — independent verification
`/calc-review` — hand off to / record the licensed engineer's review
`/calc-show` — view a calculation
`/eng-score` — department metrics report
`/eng-archive` — search the calculation archive

---

## SCHEDULED TASKS (3)

| When | Task |
|------|------|
| Thu 10:00 | weekly engineer-correction review |
| 1st 10:30 | monthly performance review |
| Q 1st 11:00 | quarterly methodology review |

---

## BOUNDARIES WITH OTHER DEPARTMENTS

- **vs Dev** — Dev builds software; Engineering calculates physical objects.
- **vs ОСП** — ОСП analyzes situations strategically; Engineering calculates.
- **vs Finance** — Engineering computes technical parameters; Finance prices.
- **vs Expert** — Expert handles external technical relationships; Engineering
  checks the numbers.

Out-of-scope engineering disciplines (foundations in difficult soils, fire
safety, seismic, geotechnical, etc.) are declined — they need a specialist.

Full disambiguation in `patches/upravlenie-engineering-routing-patch.md`.

---

## RISK PROFILE

Integration risk is low — a single additive department. The genuine risk is
*misuse*: a preliminary calculation mistaken for an approved design. The design
mitigates this — the disclaimer on every output, the hard rules, the
engineer-review lifecycle. Realistic effort: 3-4 days.

---

## AFTER THIS BLOCK

fosved-bot will have 10 departments. The methodology's natural next step is the
**Кузница кадров (Veteran)** — the recursive department that creates and
re-trains all the others.

When you return after implementation — report how it went, and we decide next.

---

**End of README.md**
