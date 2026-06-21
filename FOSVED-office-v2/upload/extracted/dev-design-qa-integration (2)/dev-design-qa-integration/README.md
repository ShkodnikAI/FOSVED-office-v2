# DDQ Integration Pack — Dev + Design + QA Departments

**Block:** Three-Department Integration for fosved-bot
**Version:** 1.0
**Date:** 2026-05-16
**Target:** existing fosved-bot v4.1 + Visual Department (both deployed)
**Owner:** @ShkodnikAI (Telegram ID 2044005421)

---

## WHAT THIS IS

A self-contained add-on that adds three production-grade technical departments
to the running fosved-bot:

- **Разработка (Dev)** — full-stack engineering: web apps, sites, AI offices, local AI models
- **Дизайн (Design)** — UI/UX design, design systems, prototypes, accessibility
- **Тестирование (QA)** — comprehensive testing including AI-specific evals

After applying this block, fosved-bot can execute software projects
end-to-end: design → build → test → ship → monitor. Code lives in real GitHub
repositories, milestone snapshots are archived in Telegram, and on-demand sync
to a local server is wired for future activation.

This is the **second major architectural block** after the v4.1 transition
pack — comparable in scope.

---

## START HERE

1. Read this README.
2. Read `DDQ_INTEGRATION_PLAN.md` — the 12-phase integration plan (Y1–Y12)
   with concrete bash/git/prisma commands and acceptance criteria.
3. Hand the unpacked folder to Claude Code and proceed phase by phase.

**Prerequisites (must already be true):**
- fosved-bot v4.1 deployed (OSP V2, ЛЗ, Expert, Yana, archive channel)
- Visual Department deployed (`v4.1-visual` tag)
- `GITHUB_TOKEN` in Render env with `repo` + `workflow` scopes
- `ARCHIVE_CHANNEL_ID` configured

If any prerequisite is missing — STOP and apply the earlier packs first.

---

## PACKAGE CONTENTS

```
dev-design-qa-integration/
├── README.md                      ← you are here
├── DDQ_INTEGRATION_PLAN.md         ← 12-phase plan, the operational document
│
├── library/                       ← 3 specialist profiles
│   ├── dev.md                      Прагматик + Методист
│   ├── design.md                   Эмпат + Перфекционист
│   └── qa.md                       Параноик + Педант (with AI-testing)
│
├── prisma/
│   └── ddq-schema.prisma           11 new models (append-only)
│
├── skills/fosved/                  ← 43 SKILL.md files
│   ├── dev/                        20 skills (5 T1 + 12 T2 + 3 T3)
│   ├── design/                     12 skills (5 T1 + 5 T2 + 2 T3)
│   └── qa/                         11 skills (4 T1 + 5 T2 + 2 T3)
│
├── lib/                            ← 4 functional modules
│   ├── github-client.js            Octokit wrapper (repos, files, branches, PRs)
│   ├── dev.js                      Dev engine (estimation, ADR, repos, tech radar)
│   ├── design.js                   Design engine (artifacts, design system, a11y)
│   └── qa.js                       QA engine (test runs, defects, AI evals, audits)
│
└── patches/                        ← 5 target-state references
    ├── README.md                   how to apply patches
    ├── army-ddq-patch.js            SPECIALISTS + SKILLS_MAP additions
    ├── bot-ddq-handlers.js          31 command handlers
    ├── scheduler-ddq-patch.js       6 scheduled tasks
    ├── bot-cross-dept-hooks.js      cross-department auto-hooks
    └── upravlenie-ddq-routing-patch.md   Yana routing + orchestration
```

---

## THE THREE DEPARTMENTS

### Разработка (Dev) — Прагматик + Методист

Builds four project classes: web apps, sites, AI offices (multi-agent Telegram
bots + miniapps + desktop apps), and local AI models (Ollama, fine-tuning).

Distinctive disciplines:
- **ADR** — every architectural decision recorded with alternatives + retrospective
- **Range estimation** — never point estimates; low/expected/high + confidence
- **Tech Radar** — living catalog of tech in 4 states (adopt/trial/assess/hold)
- **Triple storage** — GitHub primary, Telegram archive snapshots, local server (deferred)

20 skills, 14 commands.

### Дизайн (Design) — Эмпат + Перфекционист

UI/UX for products. Disciplines: user-task analysis before pixels, design
systems with tokens, WCAG AA accessibility, explicit interaction states, dev
handoff specs with implementation-drift tracking.

12 skills, 8 commands.

### Тестирование (QA) — Параноик + Педант

Quality gates across the full spectrum, with a distinctive **AI-testing**
competency: Promptfoo-style evals, prompt injection resistance, hallucination
detection, output quality metrics (groundedness / relevance / faithfulness /
coherence), cost monitoring, prompt regression.

11 skills, 9 commands.

---

## HOW THE DEPARTMENTS WORK TOGETHER

They form a production pipeline:

```
Design → Dev → QA → (deploy) → QA monitor
        ↕        ↕
    iteration  iteration
```

Cross-department auto-hooks wire it:
- Design artifact approved → Dev task auto-created
- Dev implementation done → QA test run auto-triggered
- QA critical defect → Dev hotfix task auto-created
- Dev task done → Yana notified for next-step routing

The three psychotypes **conflict by design** — Dev wants to ship, Design wants
to polish, QA wants to find every defect. Yana mediates. The tension produces
robust outcomes; without it you'd get buggy code, or paralysis, or ugly code.

Kill-switch: `DDQ_AUTO_HOOKS=false` disables all hooks instantly.

---

## STORAGE ARCHITECTURE (code triple-storage)

1. **GitHub (primary)** — real repositories via Octokit. PR-based workflow,
   CI/CD, branch protection. Default org: `ShkodnikAI`.
2. **Telegram Archive (secondary)** — code snapshots at milestones, published
   as summary post + zip (up to 50MB) with hashtags.
3. **Local server (tertiary, deferred)** — `/dev-local-sync <repo>` pulls from
   GitHub to a local server. Placeholder ready; activates when the owner sets
   `LOCAL_SERVER_URL`.

---

## DATABASE — 11 NEW MODELS

Append-only to existing `schema.prisma`. No existing model is modified.

- **Dev (4):** `DevTask`, `ArchitectureDecision`, `TechRadarEntry`, `CodeRepository`
- **Design (3):** `DesignArtifact`, `DesignDecision`, `UserResearchSession`
- **QA (4):** `TestRun`, `DefectRecord`, `SecurityAudit`, `AIEvalRun`

---

## COMMANDS (31 total)

**Dev (14):** `/dev`, `/dev-estimate`, `/dev-decide`, `/dev-implement`,
`/dev-task`, `/dev-tasks`, `/dev-repos`, `/dev-repo`, `/dev-create-repo`,
`/dev-radar`, `/dev-radar-add`, `/dev-deploy`, `/dev-archive`, `/dev-local-sync`

**Design (8):** `/design`, `/design-spec`, `/design-system`, `/design-show`,
`/design-artifacts`, `/design-research`, `/design-iterate`, `/design-approve`

**QA (9):** `/qa-strategy`, `/qa-test`, `/qa-defect`, `/qa-defects`,
`/qa-eval`, `/qa-security-audit`, `/qa-coverage`, `/qa-runs`, `/qa-monitor`

---

## SCHEDULED TASKS (6)

| When | Task |
|------|------|
| Wed 04:00 | Dev — weekly tech radar scan |
| 1st 11:00 | Dev — monthly estimate calibration |
| daily 08:00 | QA — production monitor |
| Sun 05:00 | QA — weekly security scan |
| 15th 12:00 | Design — monthly design system audit |
| Q 1st 11:30 | All three — quarterly methodology review |

---

## RISK PROFILE

- **Y2 (schema):** low — pure additive
- **Y6 (31 commands):** highest — integrate one department at a time
- **Y9 (cross-dept hooks):** medium — non-blocking try/catch + kill-switch
- **Y11 (miniapp):** optional — backend works without it

Realistic effort: ~11.5 days minimum, 14–16 days with debugging buffer.

---

## ESTIMATED TIMELINE

Backend (Y1–Y10): ~9.5 days focused work. Optional miniapp (Y11): +2 days.
Smoke test + merge (Y12): +1 day. With a 30–40% buffer: roughly 3 weeks.

---

## AFTER THIS BLOCK

fosved-bot will have 8 working departments (OSP, ЛЗ, Expert, Visual, Dev,
Design, QA, plus Yana orchestrating). With four+ departments accumulating
archives, the natural next step is activating the **Кузница кадров (Veteran
department)** — the recursive department that creates and trains the others,
per the methodology document.

When you return after implementation — report how it went, and we decide next steps.

---

**End of README.md**
