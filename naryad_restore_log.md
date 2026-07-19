# Наряд L4.R — Лог восстановления

## Бэкап
- `backup-ea96949` → запушен в origin ДО начала работ ✓

## Cherry-pick результаты

| Блок | Коммит | Результат | Примечание |
|------|--------|-----------|------------|
| A.1 L4.10 | 6568878 | SKIP (already present) | css=4, js=2 |
| A.2 L4.6  | 44764fa | SKIP (already present) | miniapp-spa=1 |
| A.3 L4.5  | 347e8fe | SKIP (already present) | web_app_data < guard: OK |
| A.4 L4.8  | ea031b0 | CONFLICT → resolved | HEAD имел L4.8+L4.11+жёсткую дату; ea031b0 имел L4.8 без L4.11. Решение: HEAD-версия с L4.8+L4.11, жёсткая дата 2026-07-10 удалена |
| A.5 L4.11 | 24c3a13 | SKIP (merged into A.4) | ПОСИМВОЛЬНО=1 |

## Контроль целостности

| Проверка | Ожидание | Факт | Статус |
|----------|----------|------|--------|
| B.1a L4.12 (no such table) | ≥1 | 1 | ✓ |
| B.1b image-gen | ≥1 | 5 | ✓ |
| B.2a ast.parse | ok | ok | ✓ |
| B.2b mlog app.mlog parse errors | 0 | 0 | ✓ |
| B.2c mlog miniapp.mlog parse errors | 0 | 0 | ✓ |

## Итог
- main = 438c8c2 (содержит: e10aa90 → 9195ae6 [image-gen, yana-fixes, archive-bugs, OSP-tables] → 438c8c2 [L4.8+L4.11 restored])
- L4.5, L4.6, L4.10 — были в параллельной линии 9195ae6, cherry-pick skip
- L4.12 (_query guard) — код присутствует в 9195ae6
- Бэкап: origin/backup-ea96949
- Откат: `git push --force origin backup-ea96949:main`
