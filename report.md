# Отчёт: L2 структурный дрейф
Дата: 2026-07-06
Ветка: fix/l2-structural → main
База: 61453eb
Коммит: adfde13 → merge fd38d4b

## A.1: aliens-eye в requirements.txt

До: `audit_deps.py` → exit 1, «В Dockerfile, но не в requirements.txt: ['aliens-eye']»
После: `audit_deps.py` → exit 0, «В Dockerfile, но не в requirements.txt: []»

## B.1: мёртвые прокси-роуты

Удалены из MLOG_ROUTES_PREFIXES: `"/status"`, `"/dept/"`, `"/office"` (3 строки)
Не задеты: `/dept-dashboard` (×2 в LLM_ROUTES_PREFIXES)
Проверки: `grep -cE '"/status"|"/office"|"/dept/"' reverse_proxy.py` → 0; `grep -c 'dept-dashboard' reverse_proxy.py` → 2; `ast.parse` → ok

## C.1: счётчики PROJECT_CONTEXT.md

| Число | Было | Стало | Команда подсчёта |
|---|---|---|---|
| Скиллы | 176 | 240 | `ls -d skills/*/ \| wc -l` → 240 |
| Cron-роуты | 11 | 8 | `grep -c 'route "/cron/' app.mlog` → 8 |
| Команды | 68 | 68+ | Автоподсчёт невозможен, «68+» |
| OSP скиллы | 24 | 24 | `awk '/LoadOspSkills/,/^}$/' app.mlog \| grep -c read_file` → 24 (не менялось, уточнён комментарий) |
| Dev скиллы | 20 | 20 | `wc -l skills_index/dev.txt` → 20 (не менялось) |

## D.1

`scripts/audit_deps.py` в репозитории, README.md строка добавлена в раздел «Качество».

## Smoke

```
python3 scripts/audit_deps.py          → exit 0
grep -cE '"/status"|"/office"|"/dept/"' reverse_proxy.py  → 0
grep -c 'dept-dashboard' reverse_proxy.py                  → 2
python3 -c "import ast; ast.parse(open('reverse_proxy.py').read())"  → ok
grep -c 'aliens-eye' requirements.txt                       → 1
```

## Затруднения

Нет