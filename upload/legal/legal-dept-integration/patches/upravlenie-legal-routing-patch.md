# patches/upravlenie-legal-routing-patch.md

## Purpose

Registers Legal routing in Yana's knowledge. Actual registration via `registry-legal-patch.md` (single source of truth).

This file is informational.

---

## Triggers (Russian) — phrases that route to Legal

```
договор, NDA, MSA, SLA, TZ, оферта, контракт, соглашение,
правовые риски, регуляторика, GDPR, комплаенс, подписать, signing,
юридическая экспертиза, юридический анализ, due diligence правовое,
конфиденциальность, intellectual property, IP, авторское право,
торговая марка, лицензия, лицензионное соглашение, terms of service,
privacy policy, политика конфиденциальности, согласие на обработку,
юрист, право, права, обязанности, претензия, иск, спор, арбитраж
```

---

## Short description (для системного промпта Yana)

```
Legal (ЮР) — договорная работа, оценка правовых рисков, GDPR/комплаенс, регуляторика в 4 юрисдикциях (BY/RU/EU/US).
Психотип: Параноик + Педант
Команды: /legal, /legal-nda, /legal-msa, /legal-review, /legal-risk-map, /legal-verify, /legal-archive, /legal-score, /legal-templates
Особенность: при каждом запросе требует юрисдикцию (BY/RU/EU/US), бизнес-форму (ООО/ИП/самозанятый), при cross-border — обе стороны.
ВСЕ ответы заканчиваются disclaimer: "draft + risk map, не финальный документ, перед signing — лицензированный юрист".
```

---

## Boundaries (когда NOT route to Legal)

- **Финансовые расчёты** в договорах (суммы, налоги) — Finance ставит цифры, Legal проверяет формулировки
- **Налоговая декларация / подача** — Finance
- **Бухгалтерский учёт** — Finance
- **Судебное представительство** — лицензированный адвокат
- **Уголовные дела** — лицензированный адвокат
- **Регистрация юр. лица** — операционная процедура
- **Сами факты в споре** (доказательство) — операционная процедура / адвокат

---

## Multi-department patterns

- **«Договор + расчёт оплаты»** → Legal составляет договор, Finance считает суммы и налоги
- **«Юридическая экспертиза технологии»** → Legal + Expert (техническая часть)
- **«Стратегическая сделка / M&A»** → OSP стратегия + Legal договорная часть + Finance unit economics
- **«Terms of Service для продукта»** → Legal (договорная часть) + Dev (техническая часть) + Design (UX)
- **«Privacy policy для приложения»** → Legal (нормы GDPR/CCPA/ФЗ-152) + Dev/Design (имплементация)

---

## Test phrases after Sweep 2

| Owner says | Expected route |
|---|---|
| "Сделай NDA для нового клиента" | Legal |
| "Прислали MSA, посмотри" | Legal (red-flag-detection) |
| "Можно работать с EU-клиентом по GDPR?" | Legal (gdpr-compliance-check) |
| "Договор с самозанятым" | Legal (с предупреждением о risks переквалификации) |
| "Договор на 5000 EUR от клиента из Германии" | Legal + Finance |
| "Privacy policy для нашего приложения" | Legal + Dev (если технические аспекты) |

---

## Yana's question-asking protocol для Legal

Когда Yana маршрутизирует в Legal, она **должна сначала** запросить:

1. **Юрисдикция нашей стороны** — BY/RU/EU/US
2. **Бизнес-форма нашей стороны** — ООО/ИП/самозанятый
3. **(если cross-border)** Юрисдикция контрагента
4. **(если cross-form)** Бизнес-форма контрагента

Без этих 2-4 параметров — Legal **не может работать корректно**, нормы зависят от юрисдикции.

Опциональные параметры (запрашивает Legal в процессе работы, не Яна заранее):
- Тип документа (NDA / MSA / SLA / TZ / прочее)
- Позиция в сделке (заказчик / исполнитель / партнёр)
- Критичность сделки (для определения уровня detail в analysis)
