---
name: nda-msa-sla-templates
description: Применение типовых шаблонов NDA/MSA/SLA с настройками под конкретный кейс. Применяется при стандартных сделках где не нужен полный custom drafting.
tier: 2
---

# NDA/MSA/SLA Templates — типовые договоры с настройками, не слепое копирование

Этот скилл — **каталог трёх самых частых типов договоров** с настройками по юрисдикции и форме бизнеса. Это не замена `contract-drafting-discipline` (который проектирует договор с нуля по карте рисков), а **ускоритель** для типовых ситуаций: «Мне нужен NDA с контрагентом в DE» или «SLA для SaaS-клиента». Шаблон → настройка → review → готово.

## Prerequisites

- Юрисдикция определена
- Бизнес-формы обеих сторон определены
- Тип документа определён (NDA / MSA / SLA)
- Для MSA: применён `risk-mapping-protocol` (даже типовой MSA — риски могут быть нестандартными)
- Для SLA: известны конкретные метрики и targets

## Core principle

> **Шаблон — это 80% готового текста для 80% сделок. Оставшиеся 20% — это то, что делает шаблон опасным, если их пропустить.** Типичная ошибка: взять шаблон, заменить имена, отправить. Каждый из ~20 параметров в шапке шаблона влияет на права сторон. Пропуск хотя бы одного — потенциальная дыра.

**Инверсия интуиции:** NDA — самый «простой» договор, и поэтому самый опасный. MSA — сложный, и поэтому к нему относятся внимательно. Но NDA, подписанный без настройки, может запретить вам использовать **собственные** знания, полученные до подписания (pre-existing know-how), если формулировка определения «конфиденциальной информации» слишком широкая.

## The procedure

### Step 1 — Выбрать тип и загрузить базовый шаблон

| Тип | Когда применяется | Сложность настройки |
|---|---|---|
| **NDA** | До обмена любой нетривиальной информацией | Низкая (5-10 параметров) |
| **MSA** | Долгосрочное сотрудничество, повторные сделки | Высокая (20+ параметров) |
| **SLA** | Приложение к MSA или standalone для SaaS | Средняя (метрики + последствия) |

### Step 2 — NDA: шаблон и настройки

**Базовый NDA содержит 7 блоков:**

1. Определение конфиденциальной информации
2. Обязанности получающей стороны
3. Исключения (что НЕ является конфиденциальным)
4. Срок действия
5. Возврат/уничтожение
6. Ответственность (penalty за нарушение)
7. Применимое право и юрисдикция

**Параметры настройки NDA:**

| # | Параметр | Варианты | Рекомендация |
|---|---|---|---|
| 1 | Тип | Unilateral (односторонний) / Mutual (взаимный) | Mutual по умолчанию — даже если сейчас только вы делитесь, через месяц они тоже будут |
| 2 | Срок действия | 1/2/3/5 лет | 2 года для IT-сделок; 5 лет если manufacturing/trade secrets |
| 3 | Определение CI | Широкое / Узкое | Узкое: «информация, помеченная как конфиденциальная в момент передачи» — защищает от overreach |
| 4 | Pre-existing IP | Включено / Исключено | **Обязательно включить** — без этого ваши знания до NDA могут попасть под NDA |
| 5 | Penalty | Фиксированная сумма / Нет | 1 000-5 000 EUR/USD для B2B NDA — создаёт deterrence без угрозы банкротства |
| 6 | Governing law | BY / RU / DE / Other | Если вы резидент BY — BY. Если контрагент настаивает — нейтральная (DE для EU) |
| 7 | Forum | Местный суд / Арбитраж | Местный суд для простых NDA. ICC/SCC для международных с крупными суммами |

**Формулировка pre-existing IP (критическая):**

```
«Конфиденциальной информацией не считается информация, которая:
(a) была известна получающей стороне до её получения от раскрывающей стороны
    (подтверждается письменными записями получающей стороны, сделанными до даты получения);
(b) является или становится общедоступной без нарушения настоящего Соглашения;
(c) была правомерно получена получающей стороной от третьего лица без ограничения на раскрытие;
(d) была независимо разработана получающей стороной без использования конфиденциальной информации.»
```

Без пункта (a) — контрагент может заявить, что ваши собственные onboarding-документы или код, написанный до NDA, подпадают под NDA.

### Step 3 — MSA: шаблон и настройки

**Базовый MSA — это полный `contract-drafting-discipline` skeleton** (12 разделов), но с предзаполненными формулировками для стандартных IT-сделок. Настройка:

| # | Раздел MSA | Ключевой параметр | Типичные настройки |
|---|---|---|---|
| 1 | Subject | Тип работ | «Разработка ПО / IT-услуги / Консалтинг» |
| 2 | Payment | Аванс / постоплата / milestone | 30% аванс + 70% после acceptance (стандарт) |
| 3 | Term | Срок + автопролонгация | 12 месяцев + auto-renewal 1 месяц notice |
| 4 | Liability cap | % от цены | 100% цены (стандарт для услуг) |
| 5 | Penalty | % за просрочку | 0.1% в день, cap 10% от суммы |
| 6 | IP ownership | Work-for-hire / License | Work-for-hire с момента полной оплаты (см. `ip-clause-discipline`) |
| 7 | Confidentiality | Встроенный NDA или reference | Reference на отдельно подписанный NDA |
| 8 | Governing law | Юрисдикция | По ситуации (см. `cross-jurisdiction-comparison`) |

**MSA для BY ↔ EU типовой кейс (разработка ПО):**

- Payment: 30/70, EUR, безналичная оплата на счёт в BY (проблема: EU sanctions на BY банки — нужно либо BY bank без sanctions, либо RU/EU intermediary bank)
- IP: work-for-hire, права переходят после 100% оплаты
- Liability cap: 100% от цены договора (не более)
- Penalty: 0.1%/day, cap 10%
- Governing law: BY (если исполнитель в BY) или DE (если заказчик настаивает и нейтральная юрисдикция приемлема)
- Force majeure: обновлённый перечень (включая sanctions, cyber attacks)

### Step 4 — SLA: шаблон и настройки

**SLA — это метрики + последствия нарушения.** Шаблон:

```
SERVICE LEVEL AGREEMENT
(Приложение к MSA № ___ от ___)

1. DEFINED SERVICES
<какие услуги покрываются>

2. SERVICE METRICS
| Метрика | Target | Measurement | Frequency |
|---------|--------|-------------|-----------|
| Uptime | 99.5% | (total minutes - downtime) / total minutes | Monthly |
| API response time (p95) | <500ms | Monitoring system measurement | Monthly |
| Support response time (P1) | <2 hours | Ticket system timestamp | Per incident |
| Support resolution time (P1) | <24 hours | Ticket system timestamp | Per incident |

3. SEVERITY LEVELS
| Level | Description | Response | Resolution |
|-------|-------------|----------|------------|
| P1 (Critical) | Service completely down | 2 hours | 24 hours |
| P2 (Major) | Major feature broken | 4 hours | 48 hours |
| P3 (Minor) | Minor issue, workaround exists | 1 business day | 5 business days |
| P4 (Cosmetic) | UI/cosmetic issue | 3 business days | Next release |

4. SERVICE CREDITS
If uptime < 99.5% in a month:
  99.0-99.5%: 10% credit on monthly fee
  95.0-99.0%: 25% credit
 <95.0%:       50% credit

Service credits are the SOLE remedy for SLA breach.
Maximum total credits in any 12-month period: 50% of annual fees.

5. EXCLUSIONS
Downtime caused by:
- Scheduled maintenance (notified 72h in advance)
- Customer's infrastructure/network
- Third-party services (cloud providers, APIs)
- Force majeure

6. REPORTING
Monthly SLA report published by <date> of following month.
Customer may request incident report within 30 days of incident.
```

**Параметры настройки SLA:**

| # | Параметр | Почему важно |
|---|---|---|
| 1 | Uptime target | 99.9% = 8.76 часов downtime/год. 99.5% = 43.8 часов. Разница — 5x. |
| 2 | Credit formula | Credit — это возврат части оплаты. Не penalty — это компенсация. Без credit — SLA необязателен. |
| 3 | Cap on credits | Без cap — 100% credit на все месяцы = бесплатный сервис при системных проблемах. |
| 4 | Exclusions | Если не исключить scheduled maintenance — плановое окно засчитывается как downtime. |

### Step 5 — Проверка на compatibility с юрисдикцией

После настройки — прогнать через checklist:

**NDA checklist:**
- [ ] Pre-existing IP исключение включено
- [ ] Определение CI не захватывает «любую информацию»
- [ ] Срок разумный (не «бессрочно»)
- [ ] Penalty с cap (не «неограниченная ответственность»)
- [ ] Governing law + forum указаны

**MSA checklist (дополнительно к NDA + contract-drafting-discipline checklist):**
- [ ] Payment terms с фиксированными процентами и сроками
- [ ] IP clause проверена через `ip-clause-discipline`
- [ ] Force majeure включает sanctions
- [ ] Liability cap ≠ 0 и ≠ unlimited

**SLA checklist (дополнительно):**
- [ ] Metrics измеримы (не «reasonable efforts»)
- [ ] Credits capped
- [ ] Exclusions покрывают реалистичные сценарии
- [ ] Reporting frequency определена

### Step 6 — Сохранить через `saveResult()`

```javascript
const dept = require('../../../lib/legal');
await dept.saveResult({
  shortTitle: `<TYPE> draft: <party A> ↔ <party B>`,
  fullResult: <полный текст>,
  documentType: 'NDA' | 'MSA' | 'SLA',
  jurisdiction: jurisdiction,
  businessForm: businessForm,
  confidence: 'high', // high для типовых скиллов
  verificationDate: today + 90,
});
```

### Step 7 — Ответить владельцу

Типовой шаблон + список настроек, применённых к данному кейсу. Если обнаружена нестандартная ситуация (например, sanctions risk при BY ↔ EU) — явно указать: «этот кейс выходит за типовой шаблон, рекомендую custom drafting через `contract-drafting-discipline`».

## Worked example

**Запрос:** «Мне нужен взаимный NDA с немецкой GmbH. Мы делимся архитектурой, они — бизнес-требованиями.»

**Контекст:**
- Сторона 1: BY ООО (резидент BY)
- Сторона 2: DE GmbH (резидент DE)
- Тип: Mutual NDA
- Цель: pre-contractual discussions

**Настройки:**
1. Type: Mutual
2. Term: 2 года
3. CI definition: «Information marked confidential at time of disclosure» (узкая)
4. Pre-existing IP: включено (пункт (a)-(d) из шаблона)
5. Penalty: 5 000 EUR
6. Governing law: DE (компромисс — ни BY ни DE не получает home advantage; но DE law более знакомо EU-контрагенту)
7. Forum: Landgericht <город>, DE

**Фрагмент ключевой формулировки (CI definition):**

```
«Конфиденциальная информация» означает любую информацию, раскрытую одной Стороной
(«Раскрывающая Сторона») другой Стороне («Получающая Сторона»), которая:
(a) помечена как «Конфиденциально» или аналогичным обозначением в момент раскрытия; или
(b) если раскрыта устно — идентифицирована как конфиденциальная в момент раскрытия
    и подтверждена письменно в течение 30 дней.

Не является конфиденциальной информацией:
(i) информация, которая была законно в распоряжении Получающей Стороны до раскрытия
    (подтверждается записями, сделанными до даты раскрытия);
(ii) информация, ставшая общедоступной без нарушения настоящего Соглашения;
(iii) информация, правомерно полученная от третьего лица без ограничения;
(iv) информация, независимо разработанная Получающей Стороной.
```

**Обоснование выбора DE governing law:** BY NDA law и DE NDA law оба enforceable. Но DE-контрагент будет чувствовать себя комфортнее с DE law → больше доверия → быстрее подписание. Для BY стороны это не ухудшает позицию (DE law имеет comparable NDA enforcement).

## Anti-patterns

- **Шаблон NDA без настройки CI definition.** Шаблон «вся информация, переданная в ходе сотрудничества» — это захватывает ВСЁ, включая общедоступную информацию, если она была «передана». **Countermeasure:** всегда узкая формулировка с mark-as-confidential requirement.

- **NDA на русском языке для EU-контрагента.** EU-контрагент не подписывает то, не понимает. Бilingual (RU/EN или BY/EN) обязателен при разных языках сторон. **Countermeasure:** bilingual template, с оговоркой «в случае расхождений приоритет имеет английская версия» (или другая по договорённости).

- **SLA без credit mechanism.** «Мы гарантируем 99.9% uptime» без указания, что происходит при 99.8% — это маркетинг, не SLA. SLA без teeth необязателен. **Countermeasure:** credit formula + cap, всегда.

- **MSA «по шаблону» без risk-mapping.** Даже типовой MSA для IT-сделок может не покрывать специфический риск (например, customer data hosting в стране с экспортными ограничениями). **Countermeasure:** quick risk-mapping (3-5 минут) даже для типовых сделок. Если найден нетипичный риск — custom drafting.

- **Односторонний NDA когда нужна взаимная.** «Мы только показываем свой продукт» — но через неделю контрагент начнёт делиться своими требованиями. Тогда понадобится второй NDA. **Countermeasure:** mutual NDA по умолчанию. Unilateral только если контрагент явно отказывается от взаимности (что само по себе — red flag).

- **SLA metrics «reasonable efforts».** «Мы будем прилагать разумные усилия для поддержания доступности» — это не метрика. Нельзя измерить. **Countermeasure:** каждая метрика = число + единица измерения + метод измерения. Без этих трёх — не метрика.

## Output template

```
═══════════════════════════════════════════
<TYPE> TEMPLATE — <Party A> ↔ <Party B>
═══════════════════════════════════════════

Type: <NDA/MSA/SLA>
Jurisdiction: <JX>
Governing law: <selected>
Forum: <selected>

─── APPLIED SETTINGS ───
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| ... | ... | ... |

─── KEY CLAUSES (preview) ───
- CI Definition: <narrow/broad + excerpt>
- Pre-existing IP: <included/excluded>
- Payment: <terms>
- Liability: <cap>
- ...

─── DEVIATIONS FROM TEMPLATE ───
<if any custom changes from base template>

─── RED FLAGS FOR THIS COUNTERPARTY ───
<if any jurisdiction-specific concerns>

⚠ DRAFT — требуется проверка лицензированным юристом перед signing.

📎 В архиве: <archive_link>
[FULL DOCUMENT: see attached file]
```

## When NOT to use this skill

- Когда сделка **нетиповая** (M&A, investment, licensing, cross-border с sanctions risk) — нужен custom drafting через `contract-drafting-discipline`
- Когда нужно **проанализировать чужой договор** — это `red-flag-detection`
- Когда нужен только **IP clause** — это `ip-clause-discipline`
- Когда вопрос про **GDPR** — это `gdpr-compliance-check`

## Integration with Legal

Tier 2, загружается при запросах на NDA/MSA/SLA, `/legal-nda`, `/legal-msa`, `/legal-templates`.

Использует:
- `contract-drafting-discipline` — если настройка шаблона обнаруживает нестандартный риск → переход на custom drafting
- `risk-mapping-protocol` — quick risk check перед применением шаблона (для MSA обязателен)
- `ip-clause-discipline` — настройка IP clause в MSA
- `gdpr-compliance-check` — если MSA/SLA затрагивает personal data processing
- `library/knowledge/legal/jurisdictions/<JX>.md` — governing law specifics