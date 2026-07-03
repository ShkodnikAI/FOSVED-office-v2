---
name: consumer-protection-check
description: Проверка договоров с потребителями (B2C) на соответствие consumer protection laws. Применяется для terms of service, оферт, договоров с физлицами.
tier: 2
---

# Consumer Protection Check — B2C-договоры как поле мин, не как сокращённая версия B2B

B2C contract — это не «B2B договор, но короче». Consumer protection laws делают **порядка 15-20% стандартных B2B-формулировок автоматически ничтожными** (void) в B2C контексте. Penalty clause «0.5% за каждый день просрочки» для потребителя — potentially unfair, может быть снижена судом. «Все права передаются нам» — void если не выделена и не понятна. Разница не в деталях, а в базовой логике: consumer protection law предполагает, что потребитель — слабая сторона и нуждается в защите от стандартных формулировок.

## Prerequisites

- Юрисдикция определена (consumer protection laws сильно отличаются: EU — самый строгий, BY/RU — средний, US — фрагментированный по штатам)
- Договор/оферта/ToS доступен для анализа
- Определено: B2C или B2B2C (если B2B2C — consumer protection может не применяться к business-потребителю)
- Применён `risk-mapping-protocol` (consumer protection violations = regulatory risk)

## Core principle

> **В B2C договоре каждая формулировка, создающая обязанность для потребителя или ограничивающая его права, по умолчанию suspect.** Нагрузка доказывания (burden of proof) что она fair — на бизнесе, не на потребителе. Если вы не можете обосновать, почему limitation liability до 100 EUR для SaaS-продукта за 10 EUR/мес — reasonable — суд может признать её unfair и полностью её удалить (не снизить, а удалить).

**Инверсия интуиции:** более детальный договор не значит более надёжный в B2C. Каждый дополнительный пункт, ограничивающий права потребителя — потенциальная мишень для regulator. Минималистичный ToS с 5 пунктами, где consumer rights очевидны, часто безопаснее 30-страничного с 10 protective clauses. В B2B — наоборот: чем детальнее, тем лучше. В B2C — each clause is a liability.

## The procedure

### Step 1 — Определить применимый consumer protection law

| Юрисдикция | Основной акт | Scope |
|---|---|---|
| EU | Directive 1999/44/EC (goods), Directive 2011/83/EU (digital), Unfair Terms Directive 93/13/EEC | Все B2C в EU, независимо от юрисдикции продавца (если target = EU consumers) |
| BY | Закон «О защите прав потребителей» от 09.01.2002 | B2C на территории BY |
| RU | Закон «О защите прав потребителей» от 07.02.1992 (с amendments) | B2C на территории RU |
| US | State-level (UCC Article 2 + state consumer acts) + FTC Act Section 5 | Фрагментированный, по штатам |

**Ключевой вопрос для cross-border:** если BY-компания продаёт SaaS EU-потребителю — применимы EU consumer directives. Consumer protection follows the consumer's jurisdiction, not the seller's. Это принцип **destination approach** — в отличие от tax (source approach для VAT).

### Step 2 — Проверить unfair terms (Directive 93/13/EU logic)

В EU (и аналогично в BY/RU с вариациями) — **indicative list of unfair terms**. Формулировки из этого списка **пresumptive unfair** — business должен доказать fairness (rebuttable presumption).

**Группы potentially unfair terms:**

**1. Excluding/limiting liability:**
- «Мы не несём ответственности за любые убытки» — presumptive unfair
- «Максимальная ответственность = цена подписки за 1 месяц» — potentially unfair если consumer loss может быть больше
- «Мы не гарантируем работоспособность сервиса» — unfair if service is paid

**2. One-sided termination:**
- «Мы можем расторгнуть договор в любое время без причины» — unfair unless consumer can also terminate anytime
- «При нарушении условий договор расторгается без возврата» — unfair unless proportional

**3. Changing terms unilaterally:**
- «Мы оставляем за собой право изменять ToS в любое время» — unfair unless: (a) consumer has right to terminate without penalty, (b) changes are communicated reasonably, (c) reason is legitimate

**4. Automatic renewal / hidden subscriptions:**
- «Подписка автоматически продлевается» — must be: (a) clearly communicated before subscription, (b) reminder before renewal, (c) easy cancellation

**5. Jurisdiction / dispute resolution:**
- «Все споры рассматриваются в суде г. Минск» — potentially unfair if consumer is in another jurisdiction
- «Mandatory arbitration» — EU: can be unfair. US: generally enforceable (FAA), but some states limit.

### Step 3 — Проверить mandatory consumer rights

**В EU (Directive 2011/83/EU for digital services):**

| Право | Суть | Exception |
|---|---|---|
| Right of withdrawal | 14 days, no reason needed | Digital content if consumer consented and acknowledged loss of right |
| Right to information | Pre-contract information: price, main characteristics, total cost, cancellation rights | — |
| Right to performance | Service must be provided within reasonable time / agreed deadline | — |
| Right to remedy | If defective: repair/replacement → price reduction → termination | — |

**В BY (Закон о защите прав потребителей):**

| Право | Суть | Особенности |
|---|---|---|
| Информация о товаре/услуге | Полная и достоверная до заключения договора | Штраф за ненадлежащую информацию: 5-15 БВ (170-510 BYN) |
| Качество | Соответствие договору и стандартам | Для услуг — в течение гарантийного срока или 2 лет |
| Возврат товара | 14 дней для удалённой торговли | Если сохранены товарный вид и потребительские свойства |
| Возмещение убытков | Включая моральный вред | Размер морального вреда — суд определяет |

**В RU (аналогично BY с ключевыми отличиями):**
- Право на возврат товара: 14 дней для distant trade (п. 4 ст. 26.1)
- Штраф за неудовлетворение требований: 50% от суммы (п. 6 ст. 13)
-途 Consumers могут подавать иски по месту жительства, не по месту нахождения продавца

### Step 4 — Проверить specific clauses в анализируемом документе

Для каждого clause в договоре/ToS:

```
1. Это ограничивает права потребителя? → Y/N
2. Это создаёт обязательство для потребителя? → Y/N
3. Формулировка выделена (bold/larger font)? → Y/N (если N и ответ 1=Y или 2=Y → potential unfairness indicator)
4. Потребитель имел возможность отказаться от этого пункта (opt-out)? → Y/N
5. Пункт пропорционален риску? → Y/N
```

Если (1 или 2) + (3=N) + (4=N) + (5=N) → **HIGH RISK unfair term**.

### Step 5 — Сохранить через `saveResult()`

```javascript
const dept = require('../../../lib/legal');
await dept.saveResult({
  shortTitle: `Consumer protection check: <document name>`,
  fullResult: formatConsumerCheck(clauses, risks, recommendations),
  jurisdiction: jurisdiction,
  businessForm: businessForm,
  confidence: 'medium',
  verificationDate: today + 90,
});
```

### Step 6 — Ответить владельцу

```
═══════════════════════════════════════════
CONSUMER PROTECTION CHECK
═══════════════════════════════════════════

Document: <ToS / Offer / Contract name>
Jurisdiction: <JX> (consumer protection law applied)
Date: <date>

─── MANDATORY RIGHTS CHECK ───
[✓/✗] Pre-contract information
[✓/✗] Right of withdrawal (14 days)
[✓/✗] Cancellation mechanism
[✓/✗] Refund policy
[✓/✗] Warranty / guarantee terms

─── UNFAIR TERMS (HIGH RISK) ───
1. § X.X "<формулировка>"
   Risk: <description>
   Recommendation: <rewrite / remove / add opt-out>

─── UNFAIR TERMS (MEDIUM RISK) ───
N. § X.X "<формулировка>"
   Risk: <description>
   Recommendation: ...

─── COMPLIANCE NOTES ───
<auto-renewal, jurisdiction clause, etc.>

⚠ REQUIRES REVIEW by licensed lawyer for consumer-facing product.
📎 В архиве: <archive_link>
```

## Worked example

**Запрос:** «У нас ToS для SaaS-продукта. Проверь на consumer protection — мы продаём EU и BY потребителям».

**Контекст:**
- SaaS-продукт, subscription 10-50 EUR/month
- ToS на английском, 4 страницы
- Target: EU + BY consumers (B2C)
- ToS содержит: liability limitation, automatic renewal, jurisdiction clause

**Выявленные проблемы:**

**1. § 8.1 — Liability limitation:**
> «Company's total liability shall not exceed the total fees paid by Customer in the 12 months preceding the claim.»

**Assessment:** EU — potentially unfair under Unfair Terms Directive. The 12-month cap may be disproportionate if consumer suffers data loss. However, for SaaS at 10-50 EUR/month, 12-month cap = 120-600 EUR — courts may consider this reasonable given the service price. **Risk: MEDIUM.**

**Recommendation:** add carve-out for consumer personal data loss: «except for claims arising from Company's breach of data protection obligations, where liability is not limited».

**2. § 5.3 — Automatic renewal:**
> «Subscription automatically renews for successive 12-month periods unless Customer cancels at least 30 days before renewal date.»

**Assessment:** EU Directive 2011/83/EU Art. 16(m): auto-renewal allowed only if consumer informed before renewal and has reasonable deadline to opt out. 30 days notice is reasonable. But — is the consumer **clearly informed** at the time of subscription? ToS says so, but is it in the checkout flow? **Risk: LOW if implemented in UI, MEDIUM if ToS-only.**

**Recommendation:** ensure checkout flow shows: «This subscription auto-renews annually. We will remind you 30 days before renewal.» + email reminder implementation.

**3. § 12.1 — Jurisdiction:**
> «All disputes shall be resolved in the courts of Minsk, Belarus.»

**Assessment:** For EU consumers — presumptive unfair. EU consumer has right to sue in their home jurisdiction (Brussels I Regulation Art. 18). BY jurisdiction clause for EU consumer = void. **Risk: HIGH for EU consumers.**

**Recommendation:** split jurisdiction clause: «For EU consumers: courts of consumer's habitual residence. For consumers in Belarus: courts of Minsk, Belarus.»

**4. § 9.2 — Changes to ToS:**
> «Company may modify these Terms at any time. Continued use after modification constitutes acceptance.»

**Assessment:** EU — potentially unfair (one-sided change without explicit consent). Consumer must have: (a) notice of changes, (b) reasonable time to review, (c) right to terminate without penalty if disagreeing. **Risk: HIGH.**

**Recommendation:** rewrite: «Company will notify Customer of material changes at least 30 days before effective date. Customer may terminate without penalty within 30 days of notice if Customer disagrees with changes.»

## Anti-patterns

- **Применять B2B liability logic к B2C.** «Мы ограничили ответственность до цены контракта — это стандартная практика». Стандартная для B2B. В B2C — presumptively unfair, burden on business to justify. **Countermeasure:** для каждого liability limitation в B2C — проверка на proportionality и наличие carve-outs (data protection, personal injury, intent).

- **ToS на английском для BY-потребителей.** BY consumer protection law требует, что договор должен быть на языке, понятном потребителю. Если target включает BY — ToS на русском (или BY) обязателен. **Countermeasure:** для каждой юрисдикции target — версия ToS на языке этой юрисдикции.

- **Jurisdiction clause без split.** «Все споры в Минске» для EU-потребителя — void. Не «может быть оспорен», а void ab initio. **Countermeasure:** jurisdiction по consumer's habitual residence (EU) или по месту нахождения продавца (BY/RU) — по юрисдикции потребителя.

- **Automatic renewal без reminder mechanism.** «В ToS написано про auto-renewal» — недостаточно. EU требует **proactive** reminder (email, in-app notification). «Consumer должен был знать» не работает. **Countermeasure:** reminder system + evidence of delivery (email log, read receipt).

- **Скрытые fees в checkout flow.** Цена показана без tax, без renewal price, без add-ons. EU Directive 2011/83/EU Art. 6: total price including tax must be clear before consumer is bound. **Countermeasure:** pre-contract information checklist (total price, tax, billing cycle, cancellation right).

## Output template

```
═══════════════════════════════════════════
CONSUMER PROTECTION CHECK
═══════════════════════════════════════════

Document: <name>
Consumer jurisdiction(s): <JX list>
Date: <date>

─── MANDATORY RIGHTS COMPLIANCE ───
[✓/✗] Pre-contract information (Art. 6/Art. 8)
[✓/✗] Right of withdrawal (14 days)
[✓/✗] Cancellation mechanism (easy, free)
[✓/✗] Refund policy (clear timeline)
[✓/✗] Warranty / quality guarantee
[✓/✗] ToS in consumer's language

─── UNFAIR TERMS ASSESSMENT ───
| Clause | Content excerpt | Risk | Recommendation |
|--------|-----------------|------|----------------|
| § X.X | "..." | HIGH/MED/LOW | <rewrite/remove/add> |

─── SPECIFIC JURISDICTION NOTES ───
<EU-specific / BY-specific / RU-specific findings>

─── CHECKOUT FLOW REQUIREMENTS ───
[✓/✗] Total price including tax shown
[✓/✗] Billing cycle clearly stated
[✓/✗] Auto-renewal disclosed + reminder mechanism
[✓/✗] Cancellation option visible

⚠ CONSUMER PROTECTION CHECK — требуется проверка лицензированным юристом.
📎 В архиве: <archive_link>
```

## When NOT to use this skill

- Когда договор **B2B** (между бизнесами) — consumer protection не применяется, используйте `contract-drafting-discipline`
- Когда вопрос про **только privacy/data protection** — это `gdpr-compliance-check`
- Когда вопрос про **анализ конкретного пункта** (не的全ом document) — `red-flag-detection`

**Граница с gdpr-compliance-check:** consumer protection = unfair terms, mandatory rights (withdrawal, refund, warranty), contract fairness. GDPR = data processing, consent, data subject rights, DPA. Пересечение: privacy policy — может проверяться обоими скиллами, но consumer protection смотрит на fairness/透明ность, а GDPR — на lawful basis/demonstrability.

## Integration with Legal

Tier 2, загружается при B2C-контексте (ToS, offer, consumer contract, subscription terms для физических лиц).

Использует:
- `risk-mapping-protocol` — consumer protection violations как regulatory risks
- `contract-drafting-discipline` — drafting compliant B2C clauses
- `gdpr-compliance-check` — privacy section of ToS
- `library/knowledge/legal/jurisdictions/<JX>.md` — consumer protection law specifics