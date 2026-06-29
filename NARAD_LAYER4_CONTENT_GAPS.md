# Наряд — Слой 4: Содержательные пробелы

**Проект:** FOSVED Office V2
**Дата:** 2026-06-29
**Версия:** 1.0
**Слой:** 4 (содержательные пробелы)

## Цель прохода

Закрыть блокирующие и критические содержательные пробелы: создать `.env.example`, удалить регрессию `spd.txt`, удалить пустые секции-заглушки из профилей, наполнить knowledge-base для основной юрисдикции (BY).

## Запреты прохода

- Не менять логику Python/mlog кода
- Не менять структуру БД
- Не менять METHODOLOGY.md
- Не дописывать скиллы (SKILL.md) — итеративно, не в этом наряде
- Не наполнять knowledge для всех юрисдикций — только BY в этом проходе

## Перед началом

Создать `LAYER4_REPORT.md`.

---

## Блок A. Блокирующие пробелы

### A.1. Создать `.env.example`

Где: новый файл `.env.example` в корне
Что не так: 15 env-переменных требуются для запуска, каноничного списка нет. Новый исполнитель или деплой не знает, что настраивать.

Содержание:
```bash
# === Required ===
TELEGRAM_BOT_TOKEN=your_bot_token
OWNER_TELEGRAM_ID=your_telegram_id
LOCKDOWN_PASSWORD=your_lockdown_password

# === LLM Providers (at least one required) ===
ZAI_API_KEY=
DEEPSEEK_API_KEY=
GROQ_API_KEY=
GROK_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
APODEX_API_KEY=

# === Voice (STT) ===
WHISPER_API_KEY=your_whisper_key
WHISPER_PROVIDER=groq

# === Optional ===
TELEGRAM_ARCHIVE_CHANNEL_ID=
GITHUB_TOKEN_METALOGOS=
CRON_SECRET=your_cron_secret
DATABASE_PATH=./data
PORT_PROXY=4000
```

Как проверить:
```bash
test -f .env.example && echo "OK"
grep -c "=" .env.example
```
Ожидаемый результат: файл существует, ~17 строк с `=`.

### A.2. Удалить регрессию `skills_index/spd.txt`

Где: `skills_index/spd.txt`
Что не так: удалён в Слое 2, вернулся при Слое 2-дополнении. Дубль `osp.txt`.
```bash
git rm skills_index/spd.txt
```
Как проверить: `test ! -f skills_index/spd.txt && echo "OK"`

---

## Блок B. Пустые секции в профилях — удаление заглушек

23 секции в 10 профилях имеют заголовок, но пустое тело. Это не «контент, который надо дописать» — это заголовки-заглушки из шаблона, которые так и не были заполнены. Они создают ложное ожидание «здесь что-то будет».

Решение: удалить пустые заголовки. Если секция когда-нибудь понадобится — её добавят с содержанием, а не с пустотой.

### B.1. Удалить пустые секции

Для каждого профиля — удалить заголовки без тела. Список:

**admin.md** (3 пустых):
- `### Триггеры маршрутизации в детали` (строка — найти `grep -n`)
- `### Cross-departmental reports (Daily / Weekly / Monthly)`
- `### Триггеры маршрутизации DDQ (Разработка / Дизайн / QA)`

**design.md** (2):
- `## Архитектура отдела`
- `## Скиллы (12 скиллов в 3 tier'ах)`

**dev.md** (3):
- `## Архитектура отдела`
- `## Скиллы (20 скиллов в 3 tier'ах)`
- `## Команды (14 команд)`

**engineering.md** (2):
- `## Архитектура отдела`
- `## Скиллы (12 скиллов в 3 tier'ах)`

**finance.md** (1):
- `## Рекомендуемые скиллы` (содержание уже есть в основном тексте через Tier 1/2/3)

**kavalnya.md** (3):
- `## Архитектура отдела`
- `## Скиллы (8 скиллов в 3 tier'ах) — METHODOLOGY.md III.2`
- `## Протокол работы`

**legal.md** (1):
- `## Рекомендуемые скиллы`

**marketing.md** (4):
- `## Архитектура отдела`
- `## Скиллы (11 скиллов в 3 tier'ах)`
- `## Команды (8 команд)`
- `## Протокол работы`

**qa.md** (3):
- `## Архитектура отдела`
- `## Скиллы (11 скиллов в 3 tier'ах)`
- `## Протокол работы`

**visual.md** (1):
- `## Пять типов output'а`

**Важно:** удалять ТОЛЬКО заголовок + пустую строку после него. Не трогать предшествующий `---` разделитель если он отделяет другую секцию.

Как проверить:
```bash
python3 -c "
import os, re
total = 0
for f in sorted(os.listdir('library')):
    if not f.endswith('.md') or f.endswith('.bak'): continue
    text = open(f'library/{f}').read()
    sections = re.split(r'^##+ ', text, flags=re.M)
    for s in sections[1:]:
        lines = s.strip().split('\n')
        body = '\n'.join(lines[1:]).strip()
        if len(body) < 20: total += 1; print(f'library/{f}: {lines[0][:50]}')
print(f'Total empty: {total}')
"
```
Ожидаемый результат: `Total empty: 0`

---

## Блок C. Knowledge-base: юрисдикция BY

Первый проход — только BY (Беларусь), основная юрисдикция владельца. Остальные (RU, EU, US) — следующие итерации.

### C.1. `library/knowledge/finance/jurisdictions/BY.md`

Заполнить:
- Налоговые ставки (НДС, налог на прибыль, подоходный, единый для ИП/самозанятых)
- Ключевые дедлайны (квартальные, годовые)
- Особенности: ЕРИП, валютный контроль, упрощённая система
- Источник: Налоговый кодекс РБ, сайт МНС

### C.2. `library/knowledge/finance/business-forms/IP.md`

Заполнить:
- Что разрешено ИП в BY
- Какие отчёты (декларация, КУДиР)
- Ограничения по видам деятельности
- Налоговые режимы (УСН, ОСН)

### C.3. `library/knowledge/finance/business-forms/SELF_EMPLOYED.md`

Заполнить:
- Самозанятые в BY (налог на профессиональный доход)
- Виды деятельности
- Ограничения по выручке
- Отчётность

### C.4. `library/knowledge/finance/business-forms/OOO.md`

Заполнить:
- ООО/ОДО в BY
- Бухгалтерский учёт, аудит
- Налоговые режимы
- Обязательная отчётность

### C.5. `library/knowledge/legal/jurisdictions/BY.md`

Заполнить:
- Гражданский кодекс РБ — ключевые разделы для договорной работы
- Хозяйственный процессуальный кодекс — базовое
- GDPR-аналог (Закон о персональных данных)
- Особенности: язык договоров, валюта расчётов, арбитраж

### C.6. `library/knowledge/legal/business-forms/IP.md`, `SELF_EMPLOYED.md`, `OOO.md`

Заполнить для каждой формы:
- Особенности договорных отношений
- Обязательные реквизиты в договорах
- Ответственность

### C.7. `library/knowledge/legal/compatibility-matrix.md`

Заполнить хотя бы для пары BY-RU:
- Cross-border договоры
- Валютное регулирование
- Применимое право

Как проверить весь блок:
```bash
# Ни одного TODO в BY файлах
grep -l "TODO" library/knowledge/*/jurisdictions/BY.md library/knowledge/*/business-forms/*.md library/knowledge/legal/compatibility-matrix.md 2>/dev/null | wc -l
```
Ожидаемый результат: `0` (или только RU/EU/US файлы).

**Примечание:** содержание должно быть фактически корректным на 2025-2026 год. Если исполнитель не уверен в ставке/дедлайне — пометить `[VERIFY]` с указанием источника, а не пропускать.

---

## Блок D. Остаточные TODO-маркеры

### D.1. Оставить TODO в RU/EU/US файлах

Не трогать — это следующие итерации.

### D.2. Scheduler TODO

Где: `dept/scheduler.mlog`, строка 161
Оставить как есть — quarterly review будет автоматизирован после ручного тестирования.

---

## Что НЕ входит в этот наряд (осознанный долг)

1. **12 admin stub-скиллов** (7 строк каждый) — функциональность admin целиком в `admin.mlog` + `library/admin.md`, стабы не блокируют. Дописать итеративно.
2. **Knowledge для RU/EU/US** — следующие итерации по мере появления задач в этих юрисдикциях.
3. **Тесты** — отсутствуют полностью. Не блокирующее для текущей стадии, но долг.
4. **`except: pass` блоки** — 8 штук в llm_proxy.py, все в config-loading. Приемлемо.
5. **Changelog** — нет формального механизма. Используется git log.

---

## Smoke-test

```bash
# .env.example
test -f .env.example && echo "S1: OK"
# spd.txt
test ! -f skills_index/spd.txt && echo "S2: OK"
# Empty sections
python3 -c "
import os, re
for f in sorted(os.listdir('library')):
    if not f.endswith('.md') or f.endswith('.bak'): continue
    text = open(f'library/{f}').read()
    for s in re.split(r'^##+ ', text, flags=re.M)[1:]:
        lines = s.strip().split('\n')
        if len('\n'.join(lines[1:]).strip()) < 20: print(f'EMPTY: library/{f}: {lines[0][:40]}'); exit(1)
print('S3: OK')
"
# BY knowledge has no TODO
grep -rl "TODO" library/knowledge/finance/jurisdictions/BY.md library/knowledge/legal/jurisdictions/BY.md 2>/dev/null | wc -l | grep -q "^0$" && echo "S4: OK"
```

---

## Чек-лист сдачи

- [ ] `.env.example` существует, содержит все 15 env-переменных
- [ ] `skills_index/spd.txt` не существует
- [ ] 0 пустых секций в `library/*.md`
- [ ] `library/knowledge/finance/jurisdictions/BY.md` — без TODO, с налоговыми ставками
- [ ] `library/knowledge/finance/business-forms/IP.md` — без TODO
- [ ] `library/knowledge/finance/business-forms/SELF_EMPLOYED.md` — без TODO
- [ ] `library/knowledge/finance/business-forms/OOO.md` — без TODO
- [ ] `library/knowledge/legal/jurisdictions/BY.md` — без TODO, с ГК РБ
- [ ] `library/knowledge/legal/business-forms/*.md` — без TODO
- [ ] `library/knowledge/legal/compatibility-matrix.md` — хотя бы BY-RU
- [ ] Smoke-test S1-S4 пройдены
- [ ] `LAYER4_REPORT.md` заполнен
