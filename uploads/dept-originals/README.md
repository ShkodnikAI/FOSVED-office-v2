# dept-originals/ — исходные материалы по созданию отделов

Загружено владельцем 2026-09-24. Это оригинальные наряды/планы
интеграции каждого отдела — часть писалась ещё под платформу ДО
Metalogos (v4.1, JS/Prisma/Postgres), часть — уже нативные Metalogos-
наряды. Не часть рантайма офиса, справочный материал для наряда
«переосмысление отделов под нативный Metalogos».

## Состав

| Папка | Что внутри | Эпоха |
|---|---|---|
| `admin/` | НАРЯД №28 (концепция Админа), НАРЯД про Understand Anything (6 суб-агентов анализа кода) | Нативный Metalogos — ссылается на METALOGOS_REFERENCE.md и текущий репозиторий |
| `yana/` | yana.md (профиль), SKILL.md, METHODOLOGY-PATCH-001.md | Смешанная — сверить отдельно |
| `kavalnya/` | KUZNITSA_INTEGRATION_PLAN.md, README.md — Кавальня изначально называлась «Кузница кадров» | v4.1 — "Target: existing fosved-bot v4.1", датирован 2026-05 |
| `engineering/` | ENGINEERING_INTEGRATION_PLAN.md, README.md | Сверить отдельно |
| `marketing/` | MARKETING_INTEGRATION_PLAN.md, README.md | Сверить отдельно |
| `dev-design-qa/` | DDQ_INTEGRATION_PLAN.md, README.md — три отдела одним пакетом | Сверить отдельно |
| `visual/` | Самый полный пакет — план интеграции, 12 SKILL.md, `library/visual.md`, `lib/visual.js`, `prisma/visual-dept-schema.prisma`, `patches/` (включая `.ts`/`.tsx` — подтверждает старый Node/TypeScript стек) | v4.1 — Prisma-схема прямое доказательство |
| `legal/` | LEGAL_INTEGRATION_PLAN.md, README.md | Сверить отдельно |
| `finance/` | FINANCE_INTEGRATION_PLAN.md, README.md | Сверить отдельно |
| `v4.1-transition-pack/` | Полный исходный пакет v4.1 — `library/*.md` (5 отделов: expert, kk, lz, osp, upravlenie), `lib/research.js`, `lib/archive-publisher.js`, `skills/fosved/*/`, `migration_logs/`, `patches/` | v4.1, уже разбирался раньше (находки: `ResearchSource`/`lib/research.js` у ОСП) |

## Как этим пользоваться

Для каждого отдела — сверять три вещи:
1. Что обещает исходный план/наряд (этот материал)
2. Что заявляет нынешний `library/<dept>.md`
3. Что реально делает `dept/<dept>.mlog`

Находки и решения по каждому отделу — в `docs/departments/<dept>.md`
(отдельная директория, не эта — та для финальных, согласованных
выводов, эта — для сырых исходников).

Известный класс находок по опыту Finance/OSP: разделы, описывающие
интеграцию через `.js`-библиотеки (`lib/archive-publisher.js`,
`lib/research.js`, `lib/visual.js`) — язык старой платформы,
Metalogos это не исполняет. Проверять каждое такое упоминание на
живое соответствие в `dept/<dept>.mlog`, не принимать на веру.
