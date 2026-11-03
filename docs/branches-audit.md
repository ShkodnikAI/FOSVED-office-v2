# Аудит веток FOSVED-office-v2

Дата: 2026-08-09
Всего веток: 50 (main исключён)

## Сводка

| Группа | Количество |
|---|---|
| Старше 2 месяцев (кандидаты на удаление) | 0 |
| 1-2 месяца (проверить диффом) | 7 |
| Менее 1 месяца (оставить) | 42 |
| Слитые (0 коммитов) | 1 |
| **Итого** | **50** |

## УСТАРЕВШИЕ (1-2 мес) — проверить диффом

| Ветка | Коммитов | Дата | Область |
|---|---|---|---|
| `fix/l1-1-initdb` | 123 | 2026-07-05 | bugfix |
| `fix/l1-v2-mlog089` | 124 | 2026-07-05 | bugfix |
| `fix/main-reconcile` | 124 | 2026-07-05 | bugfix |
| `fix/L4.3-miniapp-osp-actions` | 152 | 2026-07-06 | bugfix |
| `fix/l4-0-spa-wire` | 145 | 2026-07-06 | bugfix |
| `hotfix/inject-date-context` | 150 | 2026-07-06 | hotfix |
| `fix/l3-1-methodology` | 192 | 2026-07-09 | bugfix |

## СВЕЖИЕ (<1 мес) — оставить

| Ветка | Коммитов | Дата | Область |
|---|---|---|---|
| `backup-ea96949` | 202 | 2026-07-10 | backup-ea96949 |
| `fix/l4-12b-query-guard` | 204 | 2026-07-11 | bugfix |
| `fix/l4-13-api-auth-header` | 206 | 2026-07-11 | bugfix |
| `fix/l4-14-date-postprocess` | 207 | 2026-07-11 | bugfix |
| `fix/l4-15-no-double-dispatch` | 208 | 2026-07-11 | bugfix |
| `fix/l4-16-webhook-date-injection` | 209 | 2026-07-11 | bugfix |
| `fix/l4-17-nvidia-cerebras` | 210 | 2026-07-11 | bugfix |
| `fix/l4-18-b-rollback-kv-race` | 214 | 2026-07-12 | bugfix |
| `fix/l4-18-webhook-python-to-mlog` | 212 | 2026-07-12 | bugfix |
| `fix/l1-5-calendar-null` | 282 | 2026-07-19 | bugfix |
| `fix/l1-7-version` | 289 | 2026-07-21 | bugfix |
| `fix/l2-0-hygiene` | 287 | 2026-07-21 | bugfix |
| `feat/f1-remind-storage` | 293 | 2026-07-22 | feature |
| `fix/l3-1-honest-reminders` | 291 | 2026-07-22 | bugfix |
| `chore/mlog-0.9.5` | 293 | 2026-07-23 | maintenance |
| `feat/f2-reminder-delivery` | 298 | 2026-07-23 | feature |
| `feat/f3-natural-reminders` | 300 | 2026-07-23 | feature |
| `feat/o1-mlog095-hostbind` | 294 | 2026-07-23 | feature |
| `fix/f1-2-remind-parser` | 296 | 2026-07-23 | bugfix |
| `chore/p3-binary-acceptance` | 301 | 2026-07-24 | maintenance |
| `fix/m1-report-mutability` | 302 | 2026-07-24 | bugfix |
| `fix/m2-parameterized-insert` | 303 | 2026-07-24 | bugfix |
| `fix/m3-publish-msgid` | 304 | 2026-07-24 | bugfix |
| `fix/m4-report-buttons` | 304 | 2026-07-24 | bugfix |
| `fix/l2-model-help` | 307 | 2026-07-25 | bugfix |
| `fix/pr1-providers` | 305 | 2026-07-25 | bugfix |
| `feat/arch1-report-file` | 310 | 2026-07-26 | feature |
| `feat/arch2-archive-record` | 311 | 2026-07-26 | feature |
| `feat/arch3-browse` | 313 | 2026-07-26 | feature |
| `fix/hotfix3-dispatch` | 308 | 2026-07-26 | bugfix |
| `fix/hotfix4-dedup` | 309 | 2026-07-26 | bugfix |
| `fix/arch4-chat-miniapp` | 314 | 2026-07-27 | bugfix |
| `fix/log1-checkpoint-spam` | 315 | 2026-07-27 | bugfix |
| `fix/miniapp1-action-route` | 315 | 2026-07-27 | bugfix |
| `feat/doc1-file-tasks` | 308 | 2026-07-28 | feature |
| `feature/office-v2-redesign` | 319 | 2026-07-28 | feature |
| `fix/news1-dead-zone-endpoints` | 306 | 2026-07-28 | bugfix |
| `fix/spa-api-init` | 320 | 2026-07-28 | bugfix |
| `feat/models2-kimi` | 323 | 2026-07-30 | feature |
| `fix/sec1-internal-only` | 321 | 2026-07-30 | bugfix |
| `fix/wh1-checkpoint-sql` | 4 | 2026-08-05 | bugfix |
| `fix/wh3-dedup-window` | 3 | 2026-08-08 | bugfix |

## СЛИТЫЕ (0 коммитов сверх main)

| Ветка | Коммитов | Дата | Область |
|---|---|---|---|
| `naryad-56-release-build` | 0 | 2026-08-08 | naryad-56-release-build |

---

## Примечания

- **Коммиты** — уникальные коммиты сверх `origin/main`
- 14 нулевых веток и 3 слитых наряда удалены ранее
- Ветки из группы "старше 2 мес" — кандидаты на удаление после проверки владельцем
- Ветки из группы "1-2 мес" — возможно содержимое влито другим коммитом
- Не удалять без решения владельца

---

## Политика веток (дополнение FO-012, 2026-09-12)

Политика закреплена в [docs/repo-hygiene.md](repo-hygiene.md):

1. Ветка живёт ≤ 30 дней с последнего коммита, если не влитая.
2. Влитая ветка удаляется сразу после мержа PR.
3. Ежемесячная сверка `git branch -r --merged origin/main`: смерженное старше
   7 дней — удалить.

## Разовая чистка 2026-09-12 (FO-012)

Удалены все 8 веток вне main — все полностью влиты:

| Ветка | Судьба |
|---|---|
| fo-001/backup-persistence | мерж PR #79 — удалена |
| fo-002/github-actions-ci | мерж PR #81 — удалена |
| fo-003/version-hygiene | мерж PR #83 — удалена |
| fo-004/llm-traces | мерж PR #80 — удалена |
| fo-005/golden-evals | мерж PR #92 — удалена |
| fo-006/memory-consolidation | мерж PR #91 — удалена |
| fo-007/error-hygiene | мерж PR #90 — удалена |
| fix/vm-serve-compat | влит в main — удалена |

**После чистки: 0 веток вне main.**

## Разовая чистка 2026-11-03 (приказ владельца: «должна остаться только одна main»)

Перед удалением каждая ветка проверена: squash-коммит наряда найден в логе
`origin/main`, содержимое сверено tree-diff'ом по затронутым путям от
merge-base. Наряд #633 (PR #642) и флейк-фикс (PR #643) были влиты ранее;
незавершённая работа #636 (A2c) долита в main коммитом `bbf2839` после
верификации: `mlog check` rc=0, гейт #633 GREEN 37/37 + selftest OK,
mlog-тесты n636 2/2, pytest 108 passed. Удалены 14 локальных веток и 1 remote:

| Ветка | Судьба |
|---|---|
| `naryad/561-webapp-button` | наряд #561 — мерж PR #564 (03833bc) — удалена |
| `naryad/567-tg-token-log` | наряд #567 — мерж PR #568 (aaebe39) — удалена |
| `naryad/569-night-lock` | наряд #569 — мерж PR #570 (14b6ac4) — удалена |
| `naryad/571-mlog-0331` | наряд #571 — мерж PR #572 (69fe37f) — удалена |
| `naryad/588-night-delivery` | наряд #588 — мерж PR #592 (7ec82ab) — удалена |
| `naryad/596-night-timeouts-lz-once` | наряд #596 — мерж PR #599 (dc1b675) — удалена |
| `naryad/597-no-daily-repeats` | наряд #597 — мерж PR #600 (b8b13f7) — удалена |
| `naryad/598-supply-followup` | наряд #598 — мерж PR #601 (ec3960e) — удалена |
| `naryad/604-staging-lz-seam` | наряд #604 — мерж PR #605 (7b7fdea) — удалена |
| `naryad/633-a0-ci-baseline-gate` | наряд #633 — мерж PR #642 (7bb84e3), tree идентичен — удалена |
| `naryad/636-a2c-loud-dept-failures` | наряд #636 — работа долита в main (bbf2839) после верификации — удалена |
| `naryad/fix-n598-night-flake` | инфра-фикс — мерж PR #643 (b200ca9) — удалена |
| `naryad/a0-check-censor-633` | указатель на старый main (e6d4577), ancestor origin/main — удалена локально и на origin |
| `pin/metalogos-0340` | пин v0.34.0 устарел: main на v0.38.0 (линия ADR-0018/0203) — удалена |

**После чистки: 0 веток вне main — локально и на origin.**
