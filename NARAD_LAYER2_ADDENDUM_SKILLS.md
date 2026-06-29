# Наряд — Слой 2 дополнение: Размещение SKILL.md

**Проект:** FOSVED Office V2
**Дата:** 2026-06-28
**Версия:** 1.0
**Слой:** 2 (структурные расхождения, дополнение)

## Цель прохода

Разместить 175 готовых SKILL.md файлов из v1-пакетов по пути `skills/<skill-name>/SKILL.md`, где их ожидает `context.mlog:SelectSkillsByKeywords`. После этого система начнёт загружать содержание скиллов при обработке запросов.

## Запреты прохода

- Не менять содержание SKILL.md файлов
- Не менять `context.mlog`, `llm_proxy.py`, `app.mlog`
- Не удалять существующие папки из `skills/` (импортированные Claude-скиллы — pdf, docx и т.д.)
- Не менять `skills_index/*.txt`

## Перед началом

Распаковать все 9 zip-архивов, присланных владельцем. Также распаковать вложенные архивы:
- `Fosved_v4_1_Transition_Pack/fosved-v4.1-transition-pack.zip`
- `visual-dept-integration/visual-dept-integration.zip`

## Блок A. Копирование SKILL.md из v1-пакетов

### A.1. Скрипт размещения

Создать и запустить скрипт `scripts/place_skills.sh`:

```bash
#!/bin/bash
# Place SKILL.md files from v1 packs into skills/<skill-name>/SKILL.md
# Source structure: skills/fosved/<dept>/<skill>/SKILL.md
# Target structure: skills/<skill>/SKILL.md

SRC_ROOT="<путь к распакованным архивам>"
DST_ROOT="skills"
COUNT=0

# Собираем все SKILL.md из всех распакованных пакетов
find "$SRC_ROOT" -name "SKILL.md" -path "*/fosved/*" | while read src; do
  # Извлекаем имя скилла (предпоследняя директория)
  skill_name=$(basename "$(dirname "$src")")
  target_dir="$DST_ROOT/$skill_name"
  
  if [ ! -d "$target_dir" ]; then
    mkdir -p "$target_dir"
  fi
  
  # Копируем только если файла нет или он отличается
  if [ ! -f "$target_dir/SKILL.md" ]; then
    cp "$src" "$target_dir/SKILL.md"
    echo "PLACED: $skill_name"
    COUNT=$((COUNT + 1))
  else
    echo "SKIP (exists): $skill_name"
  fi
done

echo "Total placed: $COUNT"
```

Источники по департаментам:

| Пакет | Департамент | Скиллов |
|---|---|---|
| `dev-design-qa-integration` | dev, design, qa | 20 + 12 + 11 = 43 |
| `engineering-dept-integration` | engineering | 12 |
| `finance-dept-integration` | finance | 9 |
| `legal-dept-integration` | legal | 10 |
| `marketing-dept-integration` | marketing | 11 |
| `kuznitsa-dept-integration` | kavalnya (kk) | 8 |
| `visual-dept-integration` (вложенный zip) | visual | 11 |
| `Fosved_v4_1_Transition_Pack` (вложенный zip) | spd→osp, lz, expert | 24 + 12 + 12 = 48 |
| `Yana_super` | yana | 11 |

**Итого из пакетов: 163**

### A.2. Восстановить 12 admin-скиллов из git-истории

Admin-скиллы были в `upload/fosved-pack/` и удалены при git cleanup. Они recoverable:

```bash
for skill in architecture-reviewer autofix-engine code-audit deploy-pipeline \
  impact-analysis knowledge-graph metrics-analyst narad-builder \
  orphan-hunter proposal-generator rollback-engine security-scanner; do
  mkdir -p "skills/$skill"
  git show 7a60fbc:"upload/fosved-pack/skills/fosved/admin/$skill/SKILL.md" > "skills/$skill/SKILL.md"
  echo "RECOVERED: $skill"
done
```

**Итого admin: 12. Общий итог: 175.**

### A.3. Yana-скиллы из `Yana_super` пакета

Yana-скиллы (11 штук) находятся в `Yana_super` по пути `mnt/user-data/outputs/yana/skills/fosved/yana/<skill>/SKILL.md`. Использовать эту версию (она новее git-истории):

```bash
SRC="<путь к распакованному Yana_super>/mnt/user-data/outputs/yana/skills/fosved/yana"
for skill_dir in "$SRC"/*/; do
  skill_name=$(basename "$skill_dir")
  mkdir -p "skills/$skill_name"
  cp "$skill_dir/SKILL.md" "skills/$skill_name/SKILL.md"
  echo "PLACED: $skill_name (yana)"
done
```

## Блок B. Верификация

### B.1. Подсчёт размещённых скиллов

```bash
# Сколько SKILL.md в skills/
find skills -name "SKILL.md" -maxdepth 2 | wc -l
```
Ожидаемый результат: ≥ 175

### B.2. Сверка с skills_index

```bash
# Для каждого скилла из индексов — проверить, что SKILL.md существует
MISSING=0
for f in skills_index/*.txt; do
  while IFS= read -r skill; do
    skill=$(echo "$skill" | tr -d '\r' | xargs)
    [ -z "$skill" ] && continue
    if [ ! -f "skills/$skill/SKILL.md" ]; then
      echo "MISSING: $skill (from $(basename $f))"
      MISSING=$((MISSING + 1))
    fi
  done < "$f"
done
echo "Total missing: $MISSING"
```
Ожидаемый результат: `Total missing: 0`

### B.3. Проверка что SKILL.md не пустые

```bash
find skills -name "SKILL.md" -maxdepth 2 -empty
```
Ожидаемый результат: пусто (нет пустых файлов).

### B.4. Коммит

```bash
git add skills/*/SKILL.md
git commit -m "Layer 2 addendum: place 175 SKILL.md files from v1 packs"
git push
```

---

## Чек-лист сдачи

- [ ] `find skills -name "SKILL.md" -maxdepth 2 | wc -l` ≥ 175
- [ ] Скрипт сверки B.2 выдаёт `Total missing: 0`
- [ ] Нет пустых SKILL.md (B.3)
- [ ] Изменения закоммичены и запушены
