# НАРЯД №27: Финальные исправления по результатам стресс-теста

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Результат стресс-теста:** 48/85. После исправлений — целевой результат 80+/85.

---

## КРИТИЧЕСКИЕ (7 проблем → 7 исправлений)

### K1. Добавить алиасы команд: /osp, /marketing, /engineering

Три отдела недоступны по прямой команде. Добавить в оба места:

**В app.mlog, `detect_dept()` или обработчик webhook:**

```mlog
if starts_with(text, "/osp") then { ... обработать как osp ... }
if starts_with(text, "/marketing") then { ... обработать как marketing ... }
if starts_with(text, "/engineering") then { ... обработать как engineering ... }
```

**В llm_proxy.py, `COMMAND_DEPT` dict:**

```python
'/osp': 'osp',
'/marketing': 'marketing',
'/engineering': 'engineering',
```

**Также добавить полный набор алиасов для единообразия:**

```python
# В COMMAND_DEPT добавить:
'/osp': 'osp',
'/lz': 'lz',
'/expert': 'expert',
'/marketing': 'marketing',
'/finance': 'finance',
'/legal': 'legal',
'/dev': 'dev',
'/design': 'design',
'/qa': 'qa',
'/visual': 'visual',
'/engineering': 'engineering',
'/forge': 'kavalnya',
'/yana': 'yana',
```

Все 13 slug-команд должны работать наравне с расширенными (`/analyze`, `/calc` и т.д.).

### K2. Русская keyword-маршрутизация

Добавить в `detect_dept()` (proxy) проверки по русским ключевым словам:

```python
# В detect_dept(), после проверки команд, перед return 'yana':

RUSSIAN_KEYWORDS = {
    'osp': ['проанализируй', 'прогноз', 'что будет если', 'стратегия', 'геополитик'],
    'lz': ['технолог', 'мониторь', 'disruption', 'тренд', 'прорыв'],
    'expert': ['встреч', 'брифинг', 'подготовь к', 'подготовь меня'],
    'marketing': ['реклам', 'аудитория', 'конверсия', 'продвижени', 'маркетинг'],
    'finance': ['бюджет', 'cashflow', 'налог', 'расход', 'доход', 'финанс'],
    'legal': ['договор', 'иск', 'GDPR', 'юридическ', 'NDA', 'правов'],
    'dev': ['код', 'репозиторий', 'deploy', 'архитектур', 'API', 'программ'],
    'design': ['дизайн', 'wireframe', 'макет', 'UI', 'UX', 'интерфейс'],
    'qa': ['тест', 'баг', 'security', 'качеств', 'проверк'],
    'visual': ['инфографик', 'визуализац', 'график', 'диаграмм'],
    'engineering': ['расчёт', 'нагрузк', 'конструкци', 'инвертор', 'инженер'],
    'kavalnya': ['новый отдел', 'полигон', 'методолог', 'debrief', 'обучени'],
}

text_lower = text.lower()
for dept, keywords in RUSSIAN_KEYWORDS.items():
    for kw in keywords:
        if kw.lower() in text_lower:
            return dept
```

### K3. Создать report_css.txt

Создать файл `report_css.txt` с CSS из утверждённого шаблона:

```css
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;color:#1e293b;background:#f8fafc}
.header{padding:28px 24px 20px;color:#fff}
.header h1{font-size:22px;font-weight:700}
.header .subtitle{font-size:15px;color:rgba(255,255,255,.85);margin-top:6px}
.header .meta{font-size:12px;color:rgba(255,255,255,.6);margin-top:8px}
.content{padding:20px 24px;max-width:720px;margin:0 auto}
.content p{line-height:1.7;margin-bottom:12px;font-size:15px}
.content h2{font-size:18px;font-weight:700;margin:28px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--accent)}
.content h3{font-size:16px;font-weight:600;margin:20px 0 8px;color:#334155}
.badge{display:inline-block;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;color:#fff;margin-right:6px}
.badge-fact{background:#16a34a}
.badge-interp{background:#2563eb}
.badge-spec{background:#ca8a04;color:#1c1917}
.card-block{background:#fff;border-left:4px solid var(--accent);border-radius:0 8px 8px 0;padding:16px 20px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.verdict{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:20px;margin:24px 0}
.disclaimer{background:#fef3cd;border-left:4px solid #f59e0b;padding:14px 18px;margin:24px 0;font-size:13px;border-radius:0 4px 4px 0}
.action-bar{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;padding:12px 16px;border-top:1px solid #e2e8f0;background:#fff;position:sticky;bottom:0}
.action-btn{padding:10px 4px;border:1px solid #e2e8f0;border-radius:8px;background:#fff;font-size:11px;cursor:pointer;text-align:center}
@media print{.action-bar{display:none}.header{-webkit-print-color-adjust:exact;print-color-adjust:exact}body{background:#fff}}
```

### K4. Заменить 14 placeholder-скиллов

14 скиллов в file_cache_skills.mlog содержат TODO вместо контента. Реальные SKILL.md существуют в `skills/fosved/`. Перегенерировать:

```bash
# Для каждого placeholder:
for f in $(grep -l "TODO" skills/fosved/*/SKILL.md); do
  echo "Replacing placeholder: $f"
done

# Или перегенерировать весь file_cache_skills.mlog:
python3 generate_file_cache.py skills/fosved/ > file_cache_skills.mlog
```

Если generate_file_cache.py не существует — создать скрипт:

```python
import os, re

def transliterate(text):
    # ... транслитерация кириллицы ...
    pass

output = ""
for dept_dir in sorted(os.listdir("skills/fosved/")):
    dept_path = f"skills/fosved/{dept_dir}"
    if not os.path.isdir(dept_path):
        continue
    for skill_dir in sorted(os.listdir(dept_path)):
        skill_file = f"{dept_path}/{skill_dir}/SKILL.md"
        if os.path.exists(skill_file):
            content = open(skill_file).read()
            safe = transliterate(content)
            fn_name = f"fc_skills_fosved_{dept_dir}_{skill_dir}_SKILL_md"
            fn_name = re.sub(r'[^a-zA-Z0-9_]', '_', fn_name)
            output += f'pattern {fn_name}() -> String {{\n  return "{safe}"\n}}\n\n'

open("file_cache_skills.mlog", "w").write(output)
```

### K5. Добавить /digest команду

```mlog
match text {
  "/digest" then {
    let result = http_post("http://127.0.0.1:4000/archive/digest", "{}", "application/json")
    send_message(chat_id, "Daydzhest otpravlen")
    let _ = AuditLog("digest", "owner", "yana", "", "ok")
    return respond("200 ok")
  }
}
```

### K6. Добавить /remember команду

```mlog
match text {
  starts_with "/remember " then {
    let fact = substring(text, 10, len(text))
    kv_set("pinned_" + to_string(to_int(now())), fact)
    let _ = memorize("pinned_fact: " + fact, 1.0)
    send_message(chat_id, "Zapomnila: " + fact)
    let _ = AuditLog("remember", "owner", "", fact, "ok")
    return respond("200 ok")
  }
}
```

### K7. Исправить __replace → replace

`__replace()` undefined — заменить на `replace()` (стандартный builtin) во всех местах:

```bash
# Найти и заменить
grep -rn "__replace" *.mlog dept/*.mlog
# Заменить __replace( на replace(
sed -i 's/__replace(/replace(/g' app.mlog dept/*.mlog
```

Аналогично `__split` → `split`, `__contains` → `contains` если найдутся.

---

## НЕКРИТИЧЕСКИЕ (9 проблем)

### N1. Переписать DeptName/DeptColor — убрать race condition

Заменить write_file/read_file workaround на прямой return:

```mlog
pattern DeptName(slug: String) -> String {
  let result = if slug == "osp" then "OSP"
    else if slug == "lz" then "LZ"
    else if slug == "expert" then "Expert"
    else if slug == "marketing" then "Marketing"
    else if slug == "finance" then "Finance"
    else if slug == "legal" then "Legal"
    else if slug == "dev" then "Dev"
    else if slug == "design" then "Design"
    else if slug == "qa" then "QA"
    else if slug == "visual" then "Visual"
    else if slug == "engineering" then "Engineering"
    else if slug == "kavalnya" then "Kavalnya"
    else if slug == "yana" then "Yana"
    else slug
  return result
}
```

Аналогично DeptColor — через if-else цепочку или make_list.

### N2. Переписать legal.mlog и visual.mlog

Оба используют inline English-промпты. Заменить на загрузку из file_cache:

```mlog
pattern HandleLegal(text: String, chat_id: String) -> String {
  let profile = fc_library_legal_md()
  let context = profile
  let reply = ask_llm(context, text)
  return reply
}
```

### N3. Перевести системные сообщения на кириллицу

Заменить транслит на русский:

```
"Zapusk cepi" → "Запуск цепи"
"Korrekcija sohranena" → "Коррекция сохранена"
"Naryad sozdan" → "Наряд создан"
"Ofis zablokirovan" → "Офис заблокирован"
```

**Если парсер mlog не поддерживает кириллицу в строках** — оставить транслит. Проверить: `mlog check` на файле с кириллическими строками.

### N4. Исправить /voice-set в proxy

```python
# В proxy, обработка /voice-set:
# Было:
if str(data.get("enabled")) == "1":
# Стало:
if data.get("enabled") in (True, "true", "1", 1):
```

### N5. Удалить мёртвый код

- `context.mlog` — orphaned, никем не импортируется. Если функции нужны — импортировать в app.mlog. Если нет — удалить.
- Unused skill functions в dept/*.mlog (11 штук) — удалить или закомментировать.

### N6. Исправить miniapp.mlog — deepen/redteam для всех отделов

Сейчас deepen/redteam всегда маршрутизируют в OSP. Читать dept из miniapp_responses:

```mlog
// В HandleMiniAppAction:
let dept = query("SELECT dept FROM miniapp_responses WHERE id = $1", [doc_id])
// Использовать dept для BuildContext, а не хардкод "osp"
```

### N7. file_cache.mlog — заполнить скелетные профили

Секции «Психотип», «Метрики», «Скиллы» пустые. Заполнить из library/*.md.

### N8. forget() — проверить доступность

Стресс-тест показал что `forget()` может быть undefined. Проверить:

```bash
strings bin/mlog | grep "forget"
```

Если нет — `/unlock` не работает. Заменить на `kv_delete("system_lockdown")`.

### N9. Cron endpoints — добавить CRON_SECRET

```mlog
route "/cron/morning" method=GET {
  let secret = query_param("secret")
  let expected = env("CRON_SECRET")
  if secret != expected then { return respond("403 Forbidden") }
  // ... остальная логика
}
```

Добавить для всех 5 cron endpoints.

---

## ПОРЯДОК ВЫПОЛНЕНИЯ

```
1. K1: Алиасы команд (app.mlog + proxy)           — 10 мин
2. K2: Русская keyword-маршрутизация (proxy)       — 15 мин
3. K3: report_css.txt                              — 5 мин
4. K7: __replace → replace                        — 5 мин
5. K5: /digest команда                            — 5 мин
6. K6: /remember команда                          — 5 мин
7. N1: DeptName/DeptColor race condition           — 15 мин
8. N2: legal.mlog + visual.mlog                    — 10 мин
9. N3: Кириллица в сообщениях                      — 10 мин
10. N4: /voice-set fix                             — 5 мин
11. N5: Удалить мёртвый код                        — 5 мин
12. N6: deepen/redteam для всех отделов             — 5 мин
13. N8: forget() → kv_delete                       — 5 мин
14. N9: CRON_SECRET                                — 10 мин
15. K4: Перегенерировать file_cache_skills.mlog     — 20 мин
16. mlog check                                     — 5 мин
17. Smoke test (24 теста из Наряда 25)              — 10 мин
```

**Общее время: ~2.5 часа**

---

## КОММИТ

```bash
git add .
git commit -m "Final fixes: 7 critical + 9 non-critical from stress test. Target: 80+/85"
git push origin main
```

---

## ПОСЛЕ ФИКСОВ — ПОВТОРНЫЙ СТРЕСС-ТЕСТ

Прогнать те же 85 тестов. Ожидаемый результат:

```
Отделы: 60+/65 (keyword routing поднимет все T2/T3)
Интеграция: 15/15 (/digest + /remember добавлены)
Mini App: 4+/5
ИТОГО: 80+/85
```

Оставшиеся ⚠️ — зависят от LLM (недетерминировано), не от кода.

---

## ОТЧЁТ

```
### Результат Наряда №27

КРИТИЧЕСКИЕ:
1. K1 алиасы /osp /marketing /engineering: [✅/❌]
2. K2 русская keyword-маршрутизация: [✅/❌] [сколько слов]
3. K3 report_css.txt: [✅/❌]
4. K4 14 placeholder-скиллов: [✅/❌]
5. K5 /digest: [✅/❌]
6. K6 /remember: [✅/❌]
7. K7 __replace → replace: [✅/❌] [сколько замен]

НЕКРИТИЧЕСКИЕ:
8. N1 DeptName/DeptColor: [✅/❌]
9. N2 legal.mlog + visual.mlog: [✅/❌]
10. N3 кириллица: [✅/❌]
11. N4 /voice-set: [✅/❌]
12. N5 мёртвый код: [✅/❌]
13. N6 deepen/redteam: [✅/❌]
14. N8 forget → kv_delete: [✅/❌]
15. N9 CRON_SECRET: [✅/❌]

ТЕСТЫ:
16. mlog check: [✅/❌]
17. Smoke test: [XX/24]
18. git push: [✅/❌] [хэш]
19. Render deploy: [✅/❌]

ПОВТОРНЫЙ СТРЕСС-ТЕСТ: [XX/85]
```
