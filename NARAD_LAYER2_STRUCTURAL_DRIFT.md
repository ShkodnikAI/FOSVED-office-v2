# Наряд — Слой 2: Структурные расхождения

**Проект:** FOSVED Office V2
**Дата:** 2026-06-28
**Версия:** 1.0
**Слой:** 2 (структурные расхождения)

## Цель прохода

Устранить расхождения между тремя источниками правды (документация, реестры, диск): удалить сироту `spd`, починить повреждённый `visual.txt`, деактивировать ошибочный профиль engineering, синхронизировать цвета департаментов в `miniapp.mlog`, привести числа в README/PROJECT_CONTEXT к факту, вычистить из git файлы, уже занесённые в `.gitignore`.

## Запреты прохода

- Не менять логику маршрутизации, LLM-вызовов, обработки команд
- Не менять `llm_proxy.py` (кроме числовых правок в комментариях, если есть)
- Не писать содержание скиллов (это Слой 4)
- Не удалять папки из `skills/` — они не мешают, их разбор будет отдельно
- Не менять `app.mlog`

## Перед началом

Создать файл `LAYER2_REPORT.md` в корне проекта:

```markdown
# Layer 2 Report — Structural Drift
Date: <дата>
## Блок A — Сироты и повреждения
## Блок B — Профиль engineering
## Блок C — Цвета департаментов
## Блок D — Числа в документации
## Блок E — Git cleanup
## Smoke-test
## Чек-лист сдачи
```

**Правило при затруднении:** если `git rm --cached` вызывает ошибку — записать в отчёт, перейти дальше.

---

## Блок A. Сироты и повреждения в skills_index

### A.1. Удалить `skills_index/spd.txt`

Где: `skills_index/spd.txt`
Что не так: департамент `spd` не существует. Нет в `DEPT_NAMES`, нет `dept/spd.mlog`, нет `library/spd.md`, нет `config/override_spd.txt`, нет `file_cache_skills.mlog` паттерна для `spd`. Файл — сирота, оставшийся от переименования. 24 фантомных скилла завышают общий счёт.
Что сделать:
```bash
git rm skills_index/spd.txt
```
Как проверить:
```bash
ls skills_index/spd.txt 2>&1
```
Ожидаемый результат: `No such file or directory`

### A.2. Добавить trailing newline в `skills_index/visual.txt`

Где: `skills_index/visual.txt`, последняя строка
Что не так: файл не заканчивается символом `\n`. При `cat skills_index/*.txt` последний скилл visual (`visual-pattern-discovery`) склеивается с первым скиллом yana (`anticipation-protocol`) → `visual-pattern-discoveryanticipation-protocol`. Оба имени искажаются.
Что сделать:
```bash
echo "" >> skills_index/visual.txt
```
Как проверить:
```bash
tail -c1 skills_index/visual.txt | wc -l
```
Ожидаемый результат: `1` (есть trailing newline)

Дополнительная проверка:
```bash
cat skills_index/visual.txt skills_index/yana.txt | head -12 | grep "discoveryanticipation"
```
Ожидаемый результат: пусто (склейки больше нет).

### A.3. Пересчитать итого скиллов

После удаления `spd.txt` и починки `visual.txt`:
```bash
cat skills_index/*.txt | wc -l
```
Записать результат в отчёт. Ожидаемое: **175** (было 198, минус 24 из spd, плюс 1 из visual newline fix).

---

## Блок B. Профили engineering и finance

### B.1. Заменить ошибочный профиль engineering

Где: `library/engineering.md`
Что не так: заголовок «Специалист: Продукт и маркетинг», содержание — Figma, SEO, A/B тесты. Это маркетинговый профиль, попавший в файл engineering при миграции v1→v2. Правильный профиль (263 строки, «Инженерный отдел — проектный ассистент», строительная механика, гидравлика, силовая электроника) сохранился в v1-пакете `engineering-dept-integration`.
Что сделать:
```bash
mv library/engineering.md library/engineering.md.bak
cp <путь к распакованному>/engineering-dept-integration/library/engineering.md library/engineering.md
```
(Если v1-пакет распакован владельцем — использовать его путь. Если нет — распаковать `engineering-dept-integration.zip`, извлечь `library/engineering.md`.)

Как проверить:
```bash
head -1 library/engineering.md | grep -q "Инженерный отдел" && echo "OK" || echo "FAIL: wrong profile"
wc -l library/engineering.md
```
Ожидаемый результат: `OK`, 263 строки.

### B.2. Заменить обрезанный профиль finance

Где: `library/finance.md`
Что не так: текущий файл — stub из 43 строк. Полный профиль (153 строки, с frontmatter, жёсткими правилами, психотипом) сохранился в v1-пакете `finance-dept-integration`.
Что сделать:
```bash
mv library/finance.md library/finance.md.bak
cp <путь к распакованному>/finance-dept-integration/library/finance.md library/finance.md
```

Как проверить:
```bash
wc -l library/finance.md
head -3 library/finance.md | grep -q "name: finance" && echo "OK: has frontmatter" || echo "WARN: no frontmatter"
```
Ожидаемый результат: 153 строки, `OK: has frontmatter`.

---

## Блок C. Синхронизация цветов департаментов

### C.1. Обновить DeptColorStart в `dept/miniapp.mlog`

Где: `dept/miniapp.mlog`, строки 7-20 (функция `DeptColorStart`)
Что не так: 9 из 14 start-цветов отличаются от `DEPT_COLORS` в `llm_proxy.py` и `miniapp/css/vars.css`. Python + CSS согласованы (2 из 3) → они канон, mlog — выбивается.
Что сделать: заменить значения в `DeptColorStart`:

| dept | было (mlog) | стало (Python/CSS) |
|---|---|---|
| expert | `#312e81` | `#3730a3` |
| finance | `#166534` | `#15803d` |
| legal | `#334155` | `#475569` |
| dev | `#1e40af` | `#1d4ed8` |
| design | `#9d174d` | `#be185d` |
| qa | `#3f6212` | `#4d7c0f` |
| visual | `#6b21a8` | `#7e22ce` |
| kavalnya | `#92400e` | `#b45309` |
| admin | `#1e3a5f` | `#1e40af` |

Конкретно — найти и заменить каждую строку:
```
grep -n "312e81\|166534\|334155\|9d174d\|3f6212\|6b21a8\|92400e" dept/miniapp.mlog
```

И отдельно admin (start был равен end, что убивало градиент):
```
# Строка с admin в DeptColorStart — заменить #1e3a5f на #1e40af
# НЕ менять строку в DeptColorEnd — там #1e3a5f правильный
```

Как проверить:
```bash
python3 -c "
import re
text = open('dept/miniapp.mlog').read()
start = text.split('DeptColorStart')[1].split('DeptColorEnd')[0]
end = text.split('DeptColorEnd')[1].split('pattern')[0]
ss = dict(re.findall(r'\"(\w+)\" then \{ return \"(#[0-9a-f]+)\"', start))
ee = dict(re.findall(r'\"(\w+)\" then \{ return \"(#[0-9a-f]+)\"', end))
errors = []
expect = {'expert':'#3730a3','finance':'#15803d','legal':'#475569','dev':'#1d4ed8',
          'design':'#be185d','qa':'#4d7c0f','visual':'#7e22ce','kavalnya':'#b45309','admin':'#1e40af'}
for d,c in expect.items():
    if ss.get(d) != c: errors.append(f'{d}: expected {c}, got {ss.get(d)}')
# admin start != admin end
if ss.get('admin') == ee.get('admin'): errors.append('admin: start==end (no gradient)')
if errors:
    for e in errors: print('FAIL:', e)
else:
    print('ALL COLORS OK')
"
```
Ожидаемый результат: `ALL COLORS OK`

---

## Блок D. Числа в документации

### D.1. Обновить README.md

Где: `README.md`
Что не так: 8 числовых утверждений не соответствуют факту.

Найти и заменить каждое:

| Найти (grep) | Заменить |
|---|---|
| `~4900 строк кода` | `~7700 строк кода` |
| `126 паттернов` | `110 паттернов` |
| `98 бот-команд` | `68 бот-команд` |
| `21 таблица БД` | `22 таблицы БД` |
| `167/167 стресс-тестов` | удалить или пометить `(static analysis only)` |
| `198 индексированных скиллов` | `175 индексированных скиллов` |
| `app.mlog (1096 строк` | `app.mlog (1302 строки` |
| `llm_proxy.py              # LLM-прокси + API + SPA-сервер (1895 строк)` | `(2737 строк)` |
| `(21 таблица)` в архитектуре | `(22 таблицы)` |
| visual: `11` | `11` (оставить — после newline fix это корректно) |

Также: в таблице департаментов обновить итого:
```
**Итого: 198 индексированных скиллов** → **Итого: 175 индексированных скиллов**
```

Как проверить:
```bash
grep -cE "4900|1895|1096 строк|126 паттерн|98 бот|21 таблиц|198 " README.md
```
Ожидаемый результат: `0`

### D.2. Обновить PROJECT_CONTEXT.md

Где: `PROJECT_CONTEXT.md`
Аналогичные замены:

| Найти | Заменить |
|---|---|
| `SQLite (21 таблица)` | `SQLite (22 таблицы)` |
| `app.mlog (1096 строк)` | `app.mlog (1302 строки)` |
| `llm_proxy.py (1895 строк)` | `llm_proxy.py (2737 строк)` |
| `198 скиллов` | `175 скиллов` |
| `67 команд` | `68 команд` |
| `admin.mlog (538 строк)` | `admin.mlog (570 строк)` |

Как проверить:
```bash
grep -cE "1895|1096|21 таблиц|198 скилл|67 команд|538 строк" PROJECT_CONTEXT.md
```
Ожидаемый результат: `0`

---

## Блок E. Git cleanup

### E.1. Удалить `dept_dashboard.py` — файл-сирота

Где: `dept_dashboard.py` (295 строк), `__pycache__/dept_dashboard.cpython-312.pyc`
Что не так: файл не импортируется ни из одного модуля. Dashboard-функциональность реализована inline в `llm_proxy.py:665`. Файл — мёртвый остаток рефакторинга.
Что сделать:
```bash
git rm dept_dashboard.py
rm -f __pycache__/dept_dashboard.cpython-312.pyc
```
Как проверить:
```bash
grep -rn "dept_dashboard" *.py 2>/dev/null | grep -v "^dept_dashboard.py"
```
Ожидаемый результат: пусто (никто его не импортирует).

### E.2. Удалить из git отслеживаемые файлы, перечисленные в `.gitignore`

Что не так: `.gitignore` содержит `__pycache__/`, `tool-results/`, `stress_test_result.json`, `worklog.md`, `upload/`, `scripts/` (кроме `seed_memory.py`). Но все эти файлы были закоммичены до создания `.gitignore` и по-прежнему отслеживаются.
Что сделать:
```bash
# Убрать из tracking, оставить на диске
git rm --cached -r __pycache__/
git rm --cached -r tool-results/
git rm --cached stress_test_result.json
git rm --cached stress_test_detailed.json
git rm --cached worklog.md
git rm --cached scripts/stress_test.py
git rm --cached -r upload/
git rm --cached -r skills/quiz-mastery/src/quiz_mastery/__pycache__/
```
Как проверить:
```bash
git ls-files | grep -E "__pycache__|tool-results|stress_test|worklog\.md|upload/" | wc -l
```
Ожидаемый результат: `0`

### E.3. Добавить `stress_test_detailed.json` в `.gitignore`

Где: `.gitignore`
Что не так: `stress_test_result.json` в gitignore, но его компаньон `stress_test_detailed.json` (56KB) — нет.
Что сделать: добавить строку `stress_test_detailed.json` после строки `stress_test_result.json` в `.gitignore`.
Как проверить:
```bash
grep "stress_test_detailed" .gitignore
```
Ожидаемый результат: одна строка.

### E.4. Закоммитить cleanup

```bash
git add -A
git commit -m "Layer 2: structural drift cleanup — remove orphans, fix colors, update docs, git hygiene"
```

---

## Smoke-test после всего

### S.1. Структурная целостность skills_index

```bash
# Нет spd.txt
test ! -f skills_index/spd.txt && echo "OK: no spd" || echo "FAIL"
# Все dept в skills_index имеют соответствие в DEPT_NAMES
for f in skills_index/*.txt; do
  d=$(basename "$f" .txt)
  grep -q "'$d'" llm_proxy.py && echo "OK: $d" || echo "ORPHAN: $d"
done
# Нет склеенных строк
cat skills_index/*.txt | grep -E ".{60,}" | head -5
```
Ожидаемый результат: `OK: no spd`, 14 строк `OK: <dept>`, пусто на третьей команде.

### S.2. Профили engineering и finance

```bash
head -1 library/engineering.md | grep -q "Инженерный отдел" && echo "OK: engineering" || echo "FAIL"
wc -l library/engineering.md | grep -q "263" && echo "OK: 263 lines" || echo "FAIL"
wc -l library/finance.md | grep -q "153" && echo "OK: 153 lines" || echo "FAIL"
test -f library/engineering.md.bak && echo "OK: eng backup" || echo "WARN"
test -f library/finance.md.bak && echo "OK: fin backup" || echo "WARN"
```

### S.3. Цвета синхронны

Скрипт проверки из C.1 выше.

### S.4. Документация не содержит старых чисел

```bash
grep -cE "4900|1895 строк|1096 строк|126 паттерн|98 бот|21 таблиц|198 скилл" README.md PROJECT_CONTEXT.md
```
Ожидаемый результат: `0` для обоих файлов.

### S.5. Git чист

```bash
git ls-files | grep -E "__pycache__|tool-results|stress_test|worklog\.md|upload/" | wc -l
git status --short | head -5
```
Ожидаемый результат: `0` на первой команде. Вторая — чистый working tree (или только untracked).

---

## Структура финального отчёта исполнителя

Файл `LAYER2_REPORT.md`:

```markdown
# Layer 2 Report — Structural Drift
Date: <дата>

## Блок A — Сироты и повреждения
- A.1: spd.txt удалён: да/нет
- A.2: visual.txt newline добавлен: да/нет
- A.3: итого скиллов после правок: <число>

## Блок B — Профили engineering и finance
- B.1: engineering.md заменён из v1 пакета: да/нет, строк: <число>
- B.2: finance.md заменён из v1 пакета: да/нет, строк: <число>
- Бэкапы .bak сохранены: да/нет

## Блок C — Цвета
- C.1: 9 start-цветов обновлены: да/нет
- Admin gradient: start != end: да/нет
- Проверочный скрипт: PASSED/FAILED

## Блок D — Числа в документации
- D.1: README обновлён: да/нет, <сколько замен>
- D.2: PROJECT_CONTEXT обновлён: да/нет, <сколько замен>

## Блок E — Git cleanup
- E.1: dept_dashboard.py удалён: да/нет
- E.2: git rm --cached выполнен: да/нет, <сколько файлов>
- E.3: stress_test_detailed.json в gitignore: да/нет
- E.4: commit: да/нет, <hash>

## Smoke-test
- S.1 skills_index: PASSED/FAILED
- S.2 engineering fallback: PASSED/FAILED
- S.3 цвета: PASSED/FAILED
- S.4 документация: PASSED/FAILED
- S.5 git: PASSED/FAILED

## Примечания
<любые проблемы, находки, блокеры>
```

---

## Чек-лист сдачи

- [ ] `skills_index/spd.txt` не существует
- [ ] `skills_index/visual.txt` заканчивается newline
- [ ] `cat skills_index/*.txt | wc -l` = 175
- [ ] `library/engineering.md` содержит «Инженерный отдел», 263 строки; `.bak` существует
- [ ] `library/finance.md` содержит frontmatter `name: finance`, 153 строки; `.bak` существует
- [ ] 9 start-цветов в `dept/miniapp.mlog` совпадают с `llm_proxy.py` DEPT_COLORS
- [ ] admin start != admin end в `dept/miniapp.mlog`
- [ ] README.md не содержит чисел 4900, 1895, 1096, 126, 98, 21, 198 в контексте метрик проекта
- [ ] PROJECT_CONTEXT.md не содержит устаревших чисел
- [ ] `dept_dashboard.py` удалён из проекта
- [ ] `git ls-files | grep -E "__pycache__|tool-results|stress_test|worklog|upload/" | wc -l` = 0
- [ ] `.gitignore` содержит `stress_test_detailed.json`
- [ ] Smoke-test S.1-S.5 пройдены
- [ ] `LAYER2_REPORT.md` заполнен
