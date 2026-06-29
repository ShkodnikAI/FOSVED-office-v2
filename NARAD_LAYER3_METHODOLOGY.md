# Наряд — Слой 3: Методологические противоречия

**Проект:** FOSVED Office V2
**Дата:** 2026-06-28
**Версия:** 1.0
**Слой:** 3 (методологические дыры)

## Цель прохода

Устранить шесть методологических противоречий: ограничить FORMAT_INSTRUCTION только аналитическими отделами, разместить METHODOLOGY.md с применённым патчем, добавить owner-feedback для метрик Яны, переформулировать правило Кузницы об anti-patterns, создать структуру library/knowledge/, добавить механизм quarterly review, снять лимиты текста/голоса для Яны и Админа.

## Запреты прохода

- Не менять бизнес-логику LLM-вызовов и маршрутизации
- Не менять содержание скиллов (SKILL.md)
- Не менять app.mlog кроме добавления команды /rate-yana и /quarterly-review
- Не менять схему БД (Слой 1 уже закрыт)
- Не писать содержание knowledge-файлов (это Слой 4)

## Перед началом

Создать `LAYER3_REPORT.md` с блоками A-G.

---

## Блок A. FORMAT_INSTRUCTION — ограничить двумя отделами

### A.1. Изменить `_NO_FORMAT_DEPTS` в `llm_proxy.py`

Где: `llm_proxy.py`, строка ~205
Найти:
```python
_NO_FORMAT_DEPTS = {"yana", "admin"}
```
Заменить на:
```python
# FORMAT_INSTRUCTION (layered analysis with ✓/◈/⚡) only for analytical departments
_ANALYTICAL_DEPTS = {"osp", "expert"}
```

### A.2. Изменить `get_dept_prompt()`

Где: `llm_proxy.py`, функция `get_dept_prompt`
Найти:
```python
fmt = "" if dept in _NO_FORMAT_DEPTS else FORMAT_INSTRUCTION
```
Заменить на:
```python
fmt = FORMAT_INSTRUCTION if dept in _ANALYTICAL_DEPTS else ""
```

Логика инвертирована: раньше все получали FORMAT_INSTRUCTION кроме исключений, теперь только `osp` и `expert` получают.

### A.3. Снять лимит max_tokens для yana и admin

Где: `llm_proxy.py`, функция `_call_llm` (строка ~340)
Найти строку с `"max_tokens": 4096` в теле body.
Заменить на:
```python
body = {"model": use_model, "max_tokens": 16384 if dept in {"yana", "admin"} else 4096, "system": sys_msg, "messages": user_msgs}
```

**Примечание:** `dept` уже доступен в контексте `_call_llm` — проверить, что параметр передаётся. Если нет — добавить.

Как проверить (A.1-A.3):
```bash
grep "_ANALYTICAL_DEPTS\|_NO_FORMAT_DEPTS" llm_proxy.py
# Ожидаемый результат: только _ANALYTICAL_DEPTS, без _NO_FORMAT_DEPTS
python3 -c "import py_compile; py_compile.compile('llm_proxy.py', doraise=True)" && echo "OK"
```

### A.4. Снять TTS-лимит для yana и admin

Где: `dept/utils.mlog`, функция `SendVoiceReply` (строка ~179)
Сейчас: текст >1000 символов обрезается до 500 для всех.
Заменить блок `if len(text) > 1000.0 then {` на:
```
  if dept != "yana" && dept != "admin" && len(text) > 1000.0 then {
    let tts_text = substring(text, 0.0, 500.0) + "... Продолжение в текстовом отчёте."
  }
```

Для yana/admin: полный текст идёт в TTS без обрезки.

Как проверить:
```bash
grep "dept != \"yana\"" dept/utils.mlog
```
Ожидаемый результат: одна строка в SendVoiceReply.

---

## Блок B. METHODOLOGY.md — копирование и merge патча

### B.1. Скопировать базовый документ

Источник: `Fosved_v4_1_Transition_Pack` → вложенный zip → `transition-pack/METHODOLOGY-v1.md` (776 строк)
Либо восстановить из git:
```bash
# Если файл был в upload/
git show 7a60fbc:upload/fosved-pack/METHODOLOGY-v1.md > METHODOLOGY.md 2>/dev/null
# Если нет — из распакованного архива
cp <path-to-transition-pack>/METHODOLOGY-v1.md METHODOLOGY.md
```

### B.2. Применить METHODOLOGY-PATCH-001

Источник: `Yana_super` → `METHODOLOGY-PATCH-001.md` (136 строк)

Действия по merge:
1. После секции `## II.1.7` в METHODOLOGY.md — вставить секцию `## II.1.8. Шеф де кабинет (составной)` из патча
2. После всей Части II (перед Частью III) — вставить секцию `## II.4. Составные архетипы — правило` из патча
3. В таблице II.2 — заменить строку для Управления (Яны) на обновлённую из патча
4. В секции II.3 — заменить `## II.3.8` на обновлённую из патча
5. В секции I.4 (чек-лист) — применить изменения из «Изменения в чек-листе I.4» патча

После merge — удалить секции `## Причина патча` и `## Что делать с этим патчем` (мета-информация патча, не нужна в финальном документе).

### B.3. Добавить версию

В шапку METHODOLOGY.md:
```
**Версия:** 1.1 (v1.0 + PATCH-001)
**Дата:** 2026-06
```

Как проверить:
```bash
test -f METHODOLOGY.md && echo "OK: exists"
grep "II.1.8" METHODOLOGY.md && echo "OK: patch applied"
grep "Версия.*1.1" METHODOLOGY.md && echo "OK: versioned"
wc -l METHODOLOGY.md
```
Ожидаемый результат: файл существует, содержит II.1.8, версия 1.1, ~850-900 строк.

---

## Блок C. Owner-feedback для метрик Яны

### C.1. Добавить команду `/rate-yana` в app.mlog

Где: `app.mlog`, после блока обработки `/rate` (строка ~556)
Добавить:
```
    if starts_with(text, "/rate-yana") then {
      let parts = split(text, " ")
      let score = get(parts, 1.0)
      let comment = join(slice(parts, 2.0, len(parts)), " ")
      db_execute("INSERT INTO dept_metrics (dept, metric_name, metric_value, period, created_at) VALUES ('yana', 'owner_feedback', '" + escape_json(score) + "', 'manual', datetime('now'))")
      if len(comment) > 0.0 then {
        db_execute("INSERT INTO dept_metrics (dept, metric_name, metric_value, period, created_at) VALUES ('yana', 'owner_comment', '" + escape_json(comment) + "', 'manual', datetime('now'))")
      }
      let _ = AuditLog("rate_yana", "owner", "score=" + score)
      let _ = SendTelegramReply(chat_id, "Yana feedback recorded: " + score + "/10")
      return ""
    }
```

### C.2. Обновить метрики в профиле Яны

Где: `library/yana.md`, секция «Ключевые метрики»
После строки `Owner wellbeing trajectory` — добавить пометку:
```
  Верификация: владелец ставит оценку через `/rate-yana <1-10> [комментарий]`. Сравнение самооценки Яны с оценкой владельца — основной индикатор калибровки.
```

Как проверить:
```bash
grep "rate-yana" app.mlog && echo "OK: command added"
grep "rate-yana" library/yana.md && echo "OK: profile updated"
```

---

## Блок D. Переформулировка правила Кузницы

### D.1. Изменить правило 3 в kavalnya.md

Где: `library/kavalnya.md`, строка 17 (правило 3)
Найти:
```
3. Не одобряет скилл без минимум 3 anti-patterns
```
Заменить на:
```
3. Не одобряет **новый** скилл без минимум 3 anti-patterns — для существующих скиллов anti-patterns добавляются итеративно при quarterly review
```

Как проверить:
```bash
grep "новый.*скилл.*anti-pattern" library/kavalnya.md
```
Ожидаемый результат: одна строка.

---

## Блок E. Структура library/knowledge/

### E.1. Создать директории и placeholder-файлы

```bash
# Finance knowledge
mkdir -p library/knowledge/finance/jurisdictions
mkdir -p library/knowledge/finance/business-forms

# Legal knowledge
mkdir -p library/knowledge/legal/jurisdictions
mkdir -p library/knowledge/legal/business-forms

# Placeholder'ы
for jx in BY RU EU US; do
  echo "# Юрисдикция: $jx" > "library/knowledge/finance/jurisdictions/$jx.md"
  echo "TODO: налоговые ставки, дедлайны, особенности" >> "library/knowledge/finance/jurisdictions/$jx.md"
  echo "# Юрисдикция: $jx" > "library/knowledge/legal/jurisdictions/$jx.md"
  echo "TODO: кодекс, ключевые законы, прецеденты" >> "library/knowledge/legal/jurisdictions/$jx.md"
done

for form in IP OOO SELF_EMPLOYED; do
  echo "# Бизнес-форма: $form" > "library/knowledge/finance/business-forms/$form.md"
  echo "TODO: что разрешено форме, какие отчёты" >> "library/knowledge/finance/business-forms/$form.md"
  echo "# Бизнес-форма: $form" > "library/knowledge/legal/business-forms/$form.md"
  echo "TODO: особенности договорных отношений" >> "library/knowledge/legal/business-forms/$form.md"
done

echo "# Cross-jurisdiction compatibility matrix" > library/knowledge/legal/compatibility-matrix.md
echo "TODO: cross-формы и cross-юрисдикционные ситуации" >> library/knowledge/legal/compatibility-matrix.md
```

Содержание — Слой 4. Сейчас только структура с TODO-маркерами.

Как проверить:
```bash
find library/knowledge -name "*.md" | wc -l
```
Ожидаемый результат: 15 файлов (4 finance jx + 3 finance forms + 4 legal jx + 3 legal forms + 1 matrix).

---

## Блок F. Механизм quarterly review

### F.1. Добавить команду `/quarterly-review` в app.mlog

Где: `app.mlog`, после блока `/rate-yana`
Добавить:
```
    if starts_with(text, "/quarterly-review") then {
      let parts = split(text, " ")
      let target_dept = get(parts, 1.0)
      if len(target_dept) < 2.0 then {
        let _ = SendTelegramReply(chat_id, "Usage: /quarterly-review <dept>\nReviews methodology compliance for the department.")
        return ""
      }
      let profile = read_file("library/" + target_dept + ".md")
      let methodology = read_file("METHODOLOGY.md")
      let metrics = query("SELECT metric_name, metric_value, created_at FROM dept_metrics WHERE dept = ? ORDER BY id DESC LIMIT 20", [target_dept])
      let corrections = query("SELECT original_query, correction, created_at FROM adapt_corrections WHERE dept = ? ORDER BY id DESC LIMIT 10", [target_dept])
      let context = "QUARTERLY METHODOLOGY REVIEW for department: " + target_dept + "\n\nMETHODOLOGY.md (relevant sections):\n" + substring(methodology, 0.0, 3000.0) + "\n\nDepartment profile:\n" + profile + "\n\nRecent metrics:\n" + to_string(metrics) + "\n\nRecent corrections:\n" + to_string(corrections) + "\n\nTask: Review this department against the methodology. Check: (1) hard rules compliance, (2) metrics health, (3) anti-patterns, (4) skills coverage. Output a structured review."
      let dept = "kavalnya"
      let _ = HandleDeptQuery(chat_id, dept, context)
      return ""
    }
```

### F.2. Добавить scheduler-задачу (опционально)

Где: `dept/scheduler.mlog`, секция ежемесячных задач
Добавить комментарий-placeholder:
```
// TODO: quarterly review trigger — every 3 months, run /quarterly-review for each active dept
// Trigger: first Monday of Jan/Apr/Jul/Oct
```

Реальный автоматический триггер — после того как команда протестирована вручную.

Как проверить:
```bash
grep "quarterly-review" app.mlog && echo "OK: command"
grep "quarterly" dept/scheduler.mlog && echo "OK: scheduler placeholder"
```

---

## Smoke-test

### S.1. Синтаксис Python
```bash
python3 -c "import py_compile; py_compile.compile('llm_proxy.py', doraise=True)" && echo "OK"
```

### S.2. FORMAT_INSTRUCTION логика
```bash
python3 -c "
_ANALYTICAL_DEPTS = {'osp', 'expert'}
FORMAT = 'ФОРМАТ ОТВЕТА'
for dept in ['yana','admin','dev','design','qa','engineering','finance','legal','visual','marketing','kavalnya','lz']:
    fmt = FORMAT if dept in _ANALYTICAL_DEPTS else ''
    status = 'FORMAT' if fmt else 'no format'
    print(f'{dept}: {status}')
for dept in ['osp','expert']:
    fmt = FORMAT if dept in _ANALYTICAL_DEPTS else ''
    status = 'FORMAT' if fmt else 'no format'
    print(f'{dept}: {status}')
"
```
Ожидаемый результат: только osp и expert — `FORMAT`, все остальные — `no format`.

### S.3. METHODOLOGY.md
```bash
test -f METHODOLOGY.md && grep "II.1.8" METHODOLOGY.md && grep "1.1" METHODOLOGY.md && echo "ALL OK"
```

### S.4. Структура knowledge
```bash
find library/knowledge -name "*.md" | wc -l
```
Ожидаемый результат: 15.

### S.5. Новые команды
```bash
grep "rate-yana" app.mlog | wc -l
grep "quarterly-review" app.mlog | wc -l
```
Ожидаемый результат: ≥1 для обоих.

---

## Чек-лист сдачи

- [ ] `_NO_FORMAT_DEPTS` заменён на `_ANALYTICAL_DEPTS = {"osp", "expert"}`
- [ ] `get_dept_prompt` использует прямую логику (FORMAT только для _ANALYTICAL_DEPTS)
- [ ] max_tokens = 16384 для yana/admin, 4096 для остальных
- [ ] TTS не обрезает текст для yana/admin
- [ ] `METHODOLOGY.md` существует, содержит II.1.8, версия 1.1
- [ ] `/rate-yana` команда добавлена в app.mlog
- [ ] `library/yana.md` содержит ссылку на `/rate-yana` для верификации
- [ ] Правило 3 Кузницы переформулировано («новый скилл»)
- [ ] `library/knowledge/` содержит 15 placeholder-файлов
- [ ] `/quarterly-review` команда добавлена в app.mlog
- [ ] `python3 -c "import py_compile; py_compile.compile('llm_proxy.py', doraise=True)"` — OK
- [ ] `LAYER3_REPORT.md` заполнен
