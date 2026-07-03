---
name: ip-clause-discipline
description: Дисциплина IP-формулировок: work-for-hire, license, assignment, derivative works, pre-existing IP. Применяется при договорах создающих или передающих IP.
tier: 2
---

# IP Clause Discipline — кто владеет кодом, дизайном и текстом

IP clause — это **самый технически сложный раздел договора**, потому что оперирует понятиями, которые кодеры и дизайнеры используют каждый день, но юридически понимают неправильно. «Я написал этот код → я владею им» — неверно в большинстве юрисдикций при работе по договору (work-for-hire). «Мы купили логотип → мы можем делать с ним что угодно» — зависит от того, что именно купили (assignment vs license, exclusive vs non-exclusive, с передачей прав на derivative works или без).

## Prerequisites

- Тип договора определён (MSA, TZ, contract for services)
- Тип IP определён (code, design, text, logo, brand, data, methodology)
- Применён `risk-mapping-protocol` (IP — всегда критический риск в IT-сделках)
- Юрисдикция определена (work-for-hire правила кардинально отличаются)

## Core principle

> **IP clause отвечает на три вопроса: (1) кто владеет существующим IP до сделки, (2) кто будет владеть новым IP, созданным в рамках сделки, (3) кто может использовать что после terminate.** Если хотя бы один из трёх не отвечает явно — у каждой стороны есть аргумент в свою пользу, и спор будет решаться в суде по «наиболее выгодному для каждой» чтению.

**Инверсия интуиции:** work-for-hire в US и work-for-hire в BY/RU — это **разные правовые конструкции**. В US, если вы наняли freelancer для написания кода, и в договоре нет explicit IP assignment — **freelancer владеет кодом**, а вы имеете только licence (implicit, по условиям оплаты). В BY/RU — по ГК (ст. 708 BY, ст. 1296 RU) — если не указано иное, **заказчик** (client) владеет результатами работ. Инверсия: BY/RU default в пользу заказчика, US default — в пользу исполнителя.

## The procedure

### Step 1 — Картировать IP по трём категориям

Перед drafting — составить таблицу всех IP, затрагиваемого сделкой:

| IP | Тип | Текущий владелец | До сделки | В рамках сделки | После terminate |
|---|---|---|---|---|---|
| Fosved-bot кодовая база | Code | Fosved (BY ООО) | Pre-existing | — | Fosved сохраняет |
| Fosved-office UI дизайн | Design | Fosved | Pre-existing | — | Fosved сохраняет |
| Custom module для клиента X | Code | Будет создан | — | Client заказал | Client владеет после оплаты |
| Fosved framework (переиспользуемый) | Code | Fosved | Pre-existing | Используется | Fosved сохраняет |
| Client's brand assets | Trademark | Client | Pre-existing | Предоставлен для интеграции | Client сохраняет |

**Три категории:**

1. **Pre-existing IP** — существовал до сделки. Каждый участник сохраняет. Другая сторона получает licence (scope = нужно для исполнения договора).

2. **New IP (Deliverables)** — создаётся в рамках сделки. Владение определяет IP clause (work-for-hire / assignment / license).

3. **Derivative Works** — основан на pre-existing IP одной из сторон. Самый сложный случай. Производная работа на базе чужого IP — право на производную работу принадлежит автору производной, НО использование оригинала требует licence от владельца оригинала.

### Step 2 — Выбрать модель передачи new IP

| Модель | Что даёт | Когда применять |
|---|---|---|
| **Work-for-hire (BY/RU)** | Заказчик автоматически владеет результатами работ по умолчанию (ст. 708 ГК BY, ст. 1296 ГК RU). Явное указание в договоре — не обязательно, но рекомендуется для ясности. | BY/RU юрисдикция, услуги |
| **IP Assignment** | Explicit передача прав от исполнителя заказчику. Required в US (нет automatic work-for-hire для independent contractors). В BY/RU — усиление default. | US юрисдикция, либо BY/RU когда нужнаbelt-and-suspenders |
| **Exclusive License** | Заказчик получает исключительную лицензию (даже автор не может использовать). Передаётся право использования, не право собственности. | Когда исполнитель хочет сохранить ownership (например, для resale) |
| **Non-exclusive License** | Заказчик получает право использования. Исполнитель может лицензировать другим. | Когда deliverables основаны на reusable framework |

**Выбор зависит от юрисдикции:**

**BY (ГК ст. 708):** default = заказчик владеет. Явный work-for-hire clause — подтверждение default. Если хотите обратное (исполнитель сохраняет) — нужно **явное** указание в договоре (rare, обычно при разработке generic tools).

**RU (ГК ст. 1296):** аналогично BY. Default = заказчик.

**US (Copyright Act § 201(b)):** work-for-hire applies только если: (a) employee (не independent contractor) OR (b) explicit written agreement stating it's work-for-hire. Для 1099 contractors — пункт (b) обязателен. Без него — contractor владеет кодом, клиент получает только implicit licence.

**EU:** no EU-wide work-for-hire. Depends on member state. DE (UrhG § 43): default = contractor owns, unless explicitly assigned. Similar to US.

### Step 3 — Draft IP clause — базовая структура

```
X.1. INTELLECTUAL PROPERTY OWNERSHIP

X.1.1. Pre-existing IP. Каждая Сторона сохраняет все права на
интеллектуальную собственность, которой она владела до даты
настоящего Договора («Pre-existing IP»). Другая Сторона получает
ненамёрное, неисключительное, безотзывное право использования
Pre-existing IP исключительно в целях исполнения настоящего Договора.

X.1.2. New IP (Deliverables). Все результаты интеллектуальной
деятельности, созданные Исполнителем в ходе исполнения настоящего
Договора («Deliverables»), принадлежат Заказчику с момента полной
оплаты соответствующего этапа работ. До момента полной оплаты —
Исполнитель.

X.1.3. Исполнитель сохраняет право использовать общие методики,
библиотеки, framework и know-how, применённые при создании
Deliverables («Background IP»). Background IP не включает
специфичные элементы Deliverables.

X.1.4. Заказчик получает право создавать derivative works на
основе Deliverables без ограничений.

X.1.5. Исполнитель имеет право использовать описание и
иллюстрации Deliverables в своём портфолио, при условии
предварительного письменного согласования с Заказчиком объёма
раскрытия и только после публичного запуска соответствующего
продукта Заказчиком.
```

**Критические пункты и почему они сформулированы именно так:**

**X.1.1 — Scope limitation.** Licence на pre-existing IP — «исключительно в целях исполнения». Без этого ограничения — заказчик может использовать ваш framework для других проектов. **BY-specific:** ст. 985 ГК BY (licence scope).

**X.1.2 — Условие оплаты.** «С момента полной оплаты» — protects contractor: если заказчик не платит, contractor сохраняет IP. Это leverage для обеспечения оплаты. **Без этого пункта:** заказчик владеет IP до оплаты = contractor потерял единственный рычаг.

**X.1.3 — Background IP carve-out.** Защищает contractor от claims, что весь reusable framework теперь принадлежит заказчику. Разграничение: общие методики = contractor; специфические элементы deliverable = заказчик. **Без этого пункта:** спор о том, является ли utility function частью deliverable или background IP.

**X.1.4 — Derivative works.** Заказчик может модифицировать deliverables. Без этого — каждая модификация создаёт derivative work, права на которую неясны. **С практической точки зрения:** заказчик купил код — он должен иметь возможность его менять.

**X.1.5 — Portfolio rights.** Contractor хочет show their work. Но не до public launch — чтобы не leak незапущенный продукт. Reasonable compromise.

### Step 4 — Проверить на cross-border ловушки

**Ловушка 1 — US contractor для BY client.** BY default: client owns. US default: contractor owns. Конфликт юрисдикций. **Fix:** explicit IP assignment clause с указанием governing law.

**Ловушка 2 — Open-source в deliverables.** Если contractor использовал MIT-licensed library в deliverable — заказчик получает deliverable с MIT-licensed dependency. Это нормально, но заказчик должен знать: MIT requires attribution. **Fix:** clause обязывающий contractor предоставить список all third-party licenses.

**Ловушка 3 — AI-generated content.** Код, написанный AI (Copilot, ChatGPT) — copyright status неясен (2026: no definitive case law). US Copyright Office: AI-generated = not copyrightable. EU: pending. BY/RU: silent. **Fix:** clause explicitly addressing AI-generated components — either exclude from IP transfer (contractor guarantees to replace with human-written) or accept risk.

### Step 5 — Сохранить через `saveResult()`

```javascript
const dept = require('../../../lib/legal');
await dept.saveResult({
  shortTitle: `IP analysis: <deal/project>`,
  fullResult: formatIPReport(ipMap, clauseDraft, crossBorderIssues),
  jurisdiction: jurisdiction,
  businessForm: businessForm,
  confidence: 'high',
  verificationDate: today + 90,
});
```

## Worked example

**Запрос:** «MSA с DE GmbH — мы (BY ООО) разрабатываем SaaS-платформу. Что с IP?»

**Контекст:**
- Исполнитель: BY ООО (Fosved)
- Заказчик: DE GmbH
- Deliverables: custom SaaS platform (code + UI + documentation)
- Framework: Fosved использует свой internal framework (pre-existing)
- Governing law: DE (по договорённости)

**IP map:**

| IP | Category | Owner | Clause |
|---|---|---|---|
| Fosved framework | Pre-existing | Fosved | Non-exclusive licence to client for running the platform |
| Custom platform code | New IP | Client (after payment) | Work-for-hire + explicit assignment (DE law requires explicit) |
| UI design | New IP | Client (after payment) | Same as code |
| Client's business requirements doc | Pre-existing | Client | Not touched |
| Third-party libraries (MIT/Apache) | Licensed | Third parties | Clause: list of all licenses provided |

**Key drafting decisions:**

1. **DE governing law → explicit assignment required.** DE UrhG § 43: contractor owns by default. Without explicit assignment clause — client doesn't own the platform. **Action:** include explicit IP assignment (X.1.2 from template).

2. **Framework carve-out.** Fosved uses internal framework. Without X.1.3 — client can claim framework is part of deliverables. **Action:** explicit Background IP clause.

3. **AI-generated code.** Fosved uses AI tools. Under DE law (UrhG § 2) — only «personal intellectual creations» are copyrightable. AI output may not qualify. **Action:** clause stating «Contractor warrants that all Deliverables are original human-authored works, except for components explicitly identified as AI-assisted, for which Contractor provides no copyright warranty».

**Фрагмент key clause (DE-specific):**

```
X.1.2. IP Assignment. Contractor hereby assigns to Client all rights,
title, and interest in and to the Deliverables, including all
copyrights, patent rights, and other intellectual property rights
therein, effective upon full payment of the corresponding milestone.
This assignment is made pursuant to § 31 UrhG and constitutes a
schuldrechtliche Einräumung von Nutzungsrechten combined with
dingliche Übertragung where applicable.

Contractor waives any moral rights (Urheberpersönlichkeitsrechte)
in the Deliverables to the extent permitted by applicable law.
```

**Примечание:** Urheberpersönlichkeitsrechte (moral rights) в DE неотчуждаемы по закону (§ 29 UrhG). Пункт о waiver — максимально допустимое: Contractor обещает не exercise moral rights. Это **не full waiver** (невозможно в DE), но практически — контрактный commitment.

## Anti-patterns

- **«Все права передаются Заказчику» без условия оплаты.** Заказчик получает IP и не платит — contractor потерял единственный рычаг давления. **Countermeasure:** «права переходят с момента полной оплаты соответствующего этапа» — стандартная и справедливая формулировка.

- **Не разграничить pre-existing и new IP.** Контрактор использовал свой 2-летний framework — но в договоре написано «все результаты работ принадлежат заказчику». Включает ли это framework? Без явного carve-out — спор. **Countermeasure:** X.1.3 (Background IP) обязательно.

- **AI-generated code без disclosure.** Если deliverable содержит AI-generated фрагменты, а заказчик expects human-authored — это misrepresentation. В случае copyright dispute — AI-generated parts могут быть unprotectable. **Countermeasure:** disclosure clause + warrant of human authorship (or explicit risk acceptance).

- **Moral rights waiver в DE без ограничения.** «Contractor waives all moral rights» — в DE это юридически бессмысленно (§ 29 UrhG: moral rights inalienable). Суд может проигнорировать этот пункт. **Countermeasure:** «to the extent permitted by applicable law» + contractual commitment not to exercise.

- **Licence на pre-existing IP без scope ограничения.** «Client may use contractor's pre-existing IP» — для чего? На каком устройстве? На сколько пользователей? Без ограничения — можно интерпретировать как worldwide perpetual licence. **Countermeasure:** «exclusively for the purpose of operating the Deliverables, limited to <N> users / <N> instances».

- **Забыть third-party license list.** Deliverable содержит 15 npm packages (MIT, Apache, GPL). GPL — copyleft: если deliverable содержит GPL code, весь deliverable может стать GPL. **Countermeasure:** clause обязывающий contractor предоставить SPDX-format list of all third-party licenses + warrant that no GPL components are included without prior written approval.

## Output template

```
═══════════════════════════════════════════
IP ANALYSIS — <Deal/Project>
═══════════════════════════════════════════

Jurisdiction: <JX> (governing law)
Default IP rule: <contractor/client owns by default>

─── IP MAP ───
| IP | Category | Owner | Clause | Risk |
|----|----------|-------|--------|------|
| ... | ... | ... | ... | ... |

─── KEY CLAUSE DRAFT ───
X.1.1 Pre-existing IP: <formulation excerpt>
X.1.2 New IP / Assignment: <formulation excerpt>
X.1.3 Background IP carve-out: <formulation excerpt>
X.1.4 Derivative works: <formulation excerpt>
X.1.5 Portfolio rights: <formulation excerpt>

─── CROSS-BORDER ISSUES ───
<if any>

─── AI-GENERATED COMPONENTS ───
<disclosure or warrant>

─── THIRD-PARTY LICENSES ───
<list or requirement>

─── MORAL RIGHTS ───
<jurisdiction-specific note>

⚠ DRAFT — требуется проверка лицензированным юристом.
📎 В архиве: <archive_link>
```

## When NOT to use this skill

- Когда вопрос про **целый договор** — это `contract-drafting-discipline` (IP — один раздел)
- Когда вопрос про **GDPR/data protection** — это `gdpr-compliance-check`
- Когда вопрос про **trademark registration** — вне компетенции (this is about contractual IP, not registration)

## Integration with Legal

Tier 2, загружается при обнаружении IP-компонента в сделке (всегда при IT/дизайн/контент-договорах).

Использует:
- `risk-mapping-protocol` — IP как критический риск
- `contract-drafting-discipline` — IP clause как раздел X договора
- `nda-msa-sla-templates` — IP section в MSA template
- `cross-jurisdiction-comparison` — если стороны из разных юрисдикций с разными default IP rules
- `library/knowledge/legal/jurisdictions/<JX>.md` — work-for-hire / moral rights specifics