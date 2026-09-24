# Yana Routing Additions for Visual Department

**Target file:** `library/upravlenie.md`
**Type:** APPEND new section before "Multi-department orchestration" section.
**Don't replace existing routing.** Add this new department block.

---

## Section to add — Visual Department routing

### → Визуальный отдел (Визуал)

**Прямые триггеры:**
- "сделай инфографику", "сделай карточку", "визуализируй", "нарисуй"
- "/visual", "/visual-card", "/visual-archive", "/visual-show"
- "/visual-spec", "/visual-template", "/visual-style", "/visual-recall"
- "/visual reference", "/visual compression", "/visual memorable"

**Контекстные триггеры:**
- "покажи визуально", "покажи на схеме"
- "хочу посмотреть как это выглядит"
- "premium инфографика", "для публикации", "для печати"
- "сравни эти анализы визуально" (multi-source visual)
- "карточка проекта", "справка о клиенте"

**Auto-routing:**
- При завершении любого `/analyze`, `/expert`, `/scan` Yana **не маршрутизирует явно** — auto-hook в коде сам вызывает Визуал на генерацию Type 3 карточки.

**Граница с другими отделами:**

- **Визуал vs ОСП:** ОСП производит текстовый Analysis, Визуал делает к нему карточку. Запрос "проанализируй и сделай инфографику" — сначала ОСП, потом Визуал.
- **Визуал vs Эксперт:** Эксперт производит briefing, Визуал делает к нему briefing card.
- **Визуал vs ЛЗ:** ЛЗ создаёт KnowledgeArtifact, Визуал делает hype cycle card.
- **Визуал vs Drive:** "сохрани файл" → Drive. "сделай инфографику и сохрани" → Визуал (он сам сохранит в архив).

**Adaptive type selection:**

При неявном запросе "сделай инфографику для анализа #42" — определять тип:
- По умолчанию → Type 3 Analysis Card (быстро, шаблон)
- Если "запоминающаяся" / "для презентации" → Type 2 Memorable
- Если "вся информация в одном" / "не хочу читать длинный текст" → Type 1 Compression
- Если "справка" / "reference" → Type 4 Reference Sheet
- Если "для публикации" / "premium" → Type 5 Premium Spec

Если двусмысленно — спросить владельца коротко: "card / compression / memorable / reference / premium?"

**Multi-department orchestration (новый сценарий):**

### Сценарий — Investment decision with visual deliverables

Owner: "Завтра встреча с FusionCorp, рассматриваю инвестицию $5M. Нужна полная подготовка с инфографикой."

Маршрутизация:
1. → Эксперт: briefing к встрече
2. → ОСП: контекст fusion industry
3. → ЛЗ: текущий disruption status fusion
4. → Визуал: автоматически Type 3 cards для каждого выше + Type 1 compression для main briefing

Visual deliverables идут в конце pipeline, после готовности текстовых outputs.

---

## Section additions for "Multi-department orchestration" examples

Add this example to existing orchestration scenarios:

### Сценарий — Quarterly portfolio review

Owner: "Сделай мне сводку моих анализов за квартал в visualform."

Маршрутизация:
1. → ОСП: aggregate analysis archive за квартал, identify top 10
2. → Визуал: Type 2 memorable for each top analysis, then Type 1 compression as portfolio overview
3. → Визуал также подготовит Type 5 spec для premium poster (для печати/публикации)

---

## Updated command list reference

Add to "Команды для пользователя" section:

```
Визуальный отдел:
/visual <type> <source_type> <source_id>  — генерация визуала
/visual-card <source_id>                   — быстрая Type 3 карточка
/visual-archive [filter]                   — список визуалов
/visual-show <id>                          — просмотр артефакта
/visual-template <type>                    — шаблон типа
/visual-style                              — стилистический guide
/visual-spec <source_id>                   — Type 5 premium спецификация
/visual-recall <id> <answer>               — recall test
```
