# Marketing Department Integration Pack — Продвижение

**Block:** Marketing Department for fosved-bot
**Version:** 1.0
**Date:** 2026-05
**Target:** existing fosved-bot v4.1 (+ Visual, + DDQ departments)
**Owner:** @ShkodnikAI (Telegram ID задаётся переменной OWNER_TELEGRAM_ID)

---

## WHAT THIS IS

A self-contained add-on that adds the **Marketing (Продвижение)** department to
fosved-bot: market & audience research plus promotion of products and services.

Built per `METHODOLOGY.md` — this is the "Продукт/маркетинг" department from the
psychotype catalogue, with psychotype **Эмпат + Экспериментатор**.

The department works in two equal client modes:
- **Internal** — promotes Fosved's own products (the bot, the miniapp)
- **External** — promotes third-party clients' products and services

Both modes share one methodology and one archive. The only difference: external
research data arrives from the client and must be reliability-tagged.

---

## CORE IDEA

Every campaign is a **verifiable hypothesis**. Before launch, the department
states a numeric forecast — predicted conversion, CAC, reach. After the
campaign, actuals are reconciled against the forecast and every miss is
diagnosed. This is the same learning loop as the other Fosved departments,
adapted to marketing: forecast → launch → verify → diagnose → lesson → archive.

Marketing without a forecast is gambling. The forecast turns it into a
testable, improvable system.

---

## START HERE

1. Read this README.
2. Read `MARKETING_INTEGRATION_PLAN.md` — the 9-phase integration plan
   (M1–M9) with concrete commands and acceptance criteria.
3. Hand the unpacked folder to Claude Code, proceed phase by phase.

**Prerequisites:** fosved-bot v4.1 deployed, `ARCHIVE_CHANNEL_ID` configured.
The block depends only on v4.1 — it works whether or not DDQ is applied yet.

---

## PACKAGE CONTENTS

```
marketing-dept-integration/
├── README.md                          ← you are here
├── MARKETING_INTEGRATION_PLAN.md       ← 9-phase plan, the operational document
│
├── library/
│   └── marketing.md                    profile — Эмпат + Экспериментатор
│
├── prisma/
│   └── marketing-schema.prisma          5 new models (append-only)
│
├── skills/fosved/marketing/             ← 11 SKILL.md files
│   │  Tier 1 (4):
│   ├── audience-segmentation/
│   ├── forecast-before-launch/
│   ├── campaign-verification/
│   ├── honest-claims-discipline/
│   │  Tier 2 (5):
│   ├── market-research-methods/
│   ├── competitive-analysis/
│   ├── unit-economics-and-cac/
│   ├── positioning-and-messaging/
│   ├── channel-strategy/
│   │  Tier 3 (2):
│   ├── ab-testing-protocol/
│   └── launch-orchestration/
│
├── lib/
│   └── marketing.js                     department engine
│
└── patches/                             ← 4 target-state references
    ├── README.md
    ├── army-marketing-patch.js          SPECIALISTS + SKILLS_MAP
    ├── bot-marketing-handlers.js        8 command handlers
    ├── scheduler-marketing-patch.js     3 scheduled tasks
    └── upravlenie-marketing-routing-patch.md   Yana routing + boundaries
```

---

## THE DEPARTMENT

**Psychotype: Эмпат + Экспериментатор** (straight from the methodology
catalogue). Empathy to read the audience and write messages that land;
experimentation to generate many creative variants and let the data — not
taste — pick the winner.

**Two modes of work:**
- *Research mode* (analytical): segmentation, conversion forecasts, competitive
  analysis, unit economics. Cold, evidence-based.
- *Campaign mode* (creative): positioning, ad copy, channel strategy,
  A/B testing. Empathetic, iterative.

**9 hard rules**, including: no campaign launches without a numeric forecast;
no advertising claim that can't be verified; no manipulative targeting of
vulnerable groups; report results, never vanity metrics.

**Main metric** (from methodology II.3.5): conversion-forecast accuracy
(actual within ±25%), CAC payback accuracy (±30%), overoptimism rate (<15%).

11 skills, 8 commands.

---

## DATABASE — 5 NEW MODELS

Append-only to `schema.prisma`. No existing model modified.

- `MarketResearch` — research with data-source reliability grading
- `AudienceSegment` — concrete target segments, reusable across campaigns
- `MarketingCampaign` — campaigns with forecast + actual reconciliation
- `CampaignVerification` — per-campaign forecast-vs-actual + miss diagnosis
- `MarketingMonthlyReview` — aggregated monthly performance review

---

## COMMANDS (8)

`/market-research` — research a market or audience
`/segment` — define / list target-audience segments
`/competitors` — competitive analysis
`/campaign` — create / list promotion campaigns
`/campaign-forecast` — attach the mandatory pre-launch forecast
`/campaign-verify` — reconcile forecast with actuals after the campaign
`/marketing-score` — department metrics report
`/marketing-archive` — search research + campaign archive

---

## SCHEDULED TASKS (3)

| When | Task |
|------|------|
| daily 09:00 | verification-due check (campaigns ready to verify) |
| 1st 09:30 | monthly performance review |
| Q 1st 10:00 | quarterly methodology review |

These implement the methodology's 3-level learning loop: per-task verification,
monthly aggregation, quarterly methodology evolution.

---

## BOUNDARIES WITH OTHER DEPARTMENTS

Carefully drawn so Marketing doesn't duplicate existing work:
- **vs ОСП** — ОСП analyzes strategic situations; Marketing analyzes
  markets/audiences. (The most likely mis-route — watch this one.)
- **vs ЛЗ** — ЛЗ tracks technologies; Marketing tracks promotion channels.
- **vs Design** — Design makes the product interface; Marketing makes the ad
  creative. Landing pages are shared.
- **vs Visual** — Marketing commissions campaign visuals from Visual.
- **vs Expert** — Expert handles meetings/partnerships; Marketing handles
  audience attraction.
- **vs Finance** — Marketing forecasts CAC/payback, hands it to Finance for
  cash-flow integration.

Full disambiguation in `patches/upravlenie-marketing-routing-patch.md`.

---

## RISK PROFILE

Low across the board — a single additive department, no existing model touched.
Realistic effort: 3-4 days with a debugging buffer.

---

## AFTER THIS BLOCK

fosved-bot will have 9 departments. Several now accumulate verified archives —
the methodology's natural next step is the **Кузница кадров (Veteran)**, the
recursive department that creates and re-trains all the others.

When you return after implementation — report how it went, and we decide next.

---

**End of README.md**
