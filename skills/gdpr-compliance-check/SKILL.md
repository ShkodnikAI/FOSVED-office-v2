---
name: gdpr-compliance-check
description: Проверка соответствия проекта/продукта/процесса требованиям GDPR, CCPA, ФЗ-152 и аналогов. Применяется при работе с PII.
tier: 2
---

# GDPR/Privacy Compliance Check — не checkbox-лист, а карта processing activities

GDPR compliance — это не «поставить cookie banner». Это **документирование каждого instance обработки персональных данных**, с обоснованием lawful basis, оценкой necessity, и механизмами для exercise of data subject rights. Checkbox-лист даёт ложную уверенность: «у нас есть consent form — значит GDPR соблюдён». Нет — consent form нужна, но это ~10% compliance.

## Prerequisites

- Юрисдикция(и)数据处理 определена(ы)
- Список processing activities собран (что данные, от кого, для чего, куда, сколько хранятся)
- Тип проекта определён (SaaS / web app / Telegram bot / data processing for third party)
- Если есть DPA (Data Processing Agreement) с subprocessors — подгружен

## Core principle

> **GDPR compliance — это Documentation + Lawful Basis + Data Subject Rights.** Если вы не можете за 5 минут ответить «какие персональные данные мы обрабатываем, на каком основании, и как субъект может их удалить» — вы не compliant. Формально может быть ничего не нарушено, но inability to demonstrate compliance = non-compliance (Art. 5(2): «The controller shall be able to demonstrate compliance»).

**Инверсия интуиции:** «Мы не храним никаких личных данных — у нас только email для логина». Email — это персональные данные (PII). IP address — PII (Court of Justice of EU, 2016). Cookie ID — потенциально PII (если можно связать с личностью). Если вы не понимаете, какие данные у вас есть, вы гарантированно non-compliant, потому что не можете demonstrate compliance.

## The procedure

### Step 1 — Карта processing activities (ROPA)

ROPA (Record of Processing Activities) — обязательный документ по Art. 30. Таблица:

| Processing activity | Категория данных | Lawful basis | Source | Recipients | Retention | DPO needed |
|---|---|---|---|---|---|---|
| User registration (email, name) | Identity data | Consent (Art. 6(1)(a)) | Data subject directly | DB only | Until account deletion | No |
| Payment processing (card, address) | Financial data | Contract (Art. 6(1)(b)) | Data subject | Payment provider (Stripe) | 7 years (tax) | No |
| Usage analytics (pages, clicks) | Behavioural data | Legitimate interest (Art. 6(1)(f)) | Data subject | Analytics provider | 26 months | No |
| Marketing emails | Contact data | Consent (Art. 6(1)(a)) | Data subject | Email provider | Until withdrawal | No |
| AI model training on user data | All user data | — | — | — | — | **Yes** |

**Ключевой столбец — Lawful basis.** Шесть вариантов (Art. 6(1)):

1. **Consent** — субъект дал конкретное, информированное, withdrawable согласие. Для marketing, newsletters, non-essential cookies.
2. **Contract** — обработка необходима для исполнения договора. Для доставки заказа, предоставления услуги.
3. **Legal obligation** — обработка необходима по закону. Для налоговых записей, KYC.
4. **Vital interests** — защита жизни. Редко применимо в IT.
5. **Public task** — деятельность в общественном интересе. Не применимо для коммерческих.
6. **Legitimate interest** — баланс интересов controller и data subject. Для аналитики, security, fraud prevention.

**Если ни один не подходит — processing незаконен.** AI training на пользовательских данных без отдельного consent — это именно эта ситуация (пока нет case law, но риск регуляторного действия высок).

### Step 2 — Проверить lawful basis для каждого activity

**Тест на lawful basis:**

Для consent: «Может ли субъект отозвать согласие без ущерба для себя?» Если нет — это не consent, это contract/coercion. Example: «Примите cookie consent или покиньте сайт» — валидно. «Примите обработку данных для предоставления услуги или не получите услугу» — если обработка действительно необходима для услуги, basis = contract, не consent. Но если обработка избыточна — invalid.

Для legitimate interest: **LIA (Legitimate Interest Assessment)** обязателен. Три вопроса:
1. Какой legitimate interest мы преследуем?
2. Насколько это необходимо (есть ли менее invasive способ)?
3. Какой вред субъекту, и перевешивает ли наш интерес этот вред?

Example: «Мы анализируем usage для улучшения продукта» — интерес есть, но нужен ли analytics для этого? Можно ли использовать anonymised data? Если да — legitimate interest слабее. Вред: profiling, loss of control. Баланс: для SaaS с B2B клиентами — обычно в пользу controller. Для B2C с children — почти всегда в пользу data subject.

### Step 3 — Privacy notices (Art. 13-14)

Каждый data collection point (signup form, contact form, cookie banner) должен вести к privacy notice содержащему:

```
WHO we are (controller identity + contact)
WHAT we collect (categories of data)
WHY we collect (purposes for each category)
LEGAL BASIS for each purpose
WHO receives the data (third parties, countries)
HOW LONG we keep it (retention periods)
WHAT RIGHTS the data subject has (list all 8)
HOW to exercise rights (contact method)
RIGHT TO COMPLAIN to supervisory authority
```

**Anti-pattern:** «Подробности см. в нашей Privacy Policy на /privacy». Ссылка недостаточна — при первичной сборе данных нужно дать **суммарную** информацию (Art. 13(1)). Privacy policy даёт детализацию, но не заменяет notice.

### Step 4 — Data subject rights — механизм исполнения

8 прав (Art. 15-22). Для каждого — проверка: **можем ли мы исполнить за 30 дней?**

| Право | Что требует | Типичная реализация |
|---|---|---|
| Right of access (15) | Выдать все данные субъекта | «Download my data» button → JSON/CSV export |
| Right to rectification (16) | Исправить неверные данные | Profile edit page |
| Right to erasure (17) | Удалить все данные | «Delete account» → cascade delete (или anonymise) |
| Right to restriction (18) | Ограничить обработку | Flag account: «processing restricted» |
| Right to data portability (20) | Выдать в machine-readable формате | JSON export |
| Right to object (21) | Прекратить processing (для LI) | Opt-out mechanism |
| Right re: automated decisions (22) | Не быть субъектом automated decision-making | Human review option |
| Right to withdraw consent | Отозвать consent | Unsubscribe/opt-out button |

**Самое сложное — erasure (right to be forgotten).** Каскадное удаление:
- Primary DB: delete user row
- Analytics: delete/anonymise events
- Backups: flag for deletion on next backup rotation
- Logs: delete from access logs (if contain PII)
- Subprocessors: notify Stripe/etc. to delete

**Retention exceptions (Art. 17(3)):** можно не удалять если:
- Legal obligation (налоговые записи — 7 лет)
- Establishment/defence of legal claims
- Public interest

Практически: если субъект просит удаление, а у вас есть неоплаченный инвойс — хранить данные до истечения исковой давности (3 года в BY/RU), потом удалить.

### Step 5 — Cross-border data transfers

Если данные передаются за пределы EEA:

**Option A — Adequacy decision.** EU Commission признала adequate: JP, KR, UK, CH, и др. Для этих стран — transfers свободные.

**Option B — Standard Contractual Clauses (SCC).** Для остальных стран (включая BY, RU, US без DPF) — SCC обязательны. Новые SCC (2021) — модульная система (4 модуля: C2C, C2P, P2C, P2P).

**Для BY/RU — SCC обязательны** если данные EU граждан обрабатываются. Если данные BY граждан обрабатываются BY-резидентом для BY-клиентов — GDPR не применим, но ФЗ-152 (RU) или Закон о защите персональных данных (BY) — применимы.

**Option C — DPF (Data Privacy Framework).** Для US — если компания self-certified under EU-US DPF. Проверять на dataprivacyframework.gov.

### Step 6 — DPA (Data Processing Agreement) с subprocessors

Если вы processor (обрабатываете данные для кого-то) или controller с subprocessors (Stripe, AWS, Cloudflare) — DPA обязателен (Art. 28).

**DPA содержит:**
- Subject matter + duration
- Nature and purpose of processing
- Type of data + categories of data subjects
- Obligations and rights of controller
- Requirements for subprocessor approval
- Assistance obligations
- Security measures
- Return/deletion of data on termination

**Практика:** крупные providers (AWS, Stripe, Cloudflare) имеют стандартные DPA. Получить и сохранить.

### Step 7 — DPIA (Data Protection Impact Assessment)

Обязательна для processing с «high risk» (Art. 35):
- Systematic profiling с significant effects
- Large-scale processing of special categories (health, political opinions)
- Public area monitoring (CCTV)
- Use of new technologies

**DPIA процедура:**
1. Описание processing (что, как, зачем)
2. Assessment of necessity + proportionality
3. Assessment of risks to data subjects
4. Measures to mitigate risks
5. DPO consultation
6. Supervisory authority consultation (если residual risk high)

**Для AI-продуктов:** DPIA почти всегда обязательна (systematic profiling + new technology).

### Step 8 — Проверка на ФЗ-152 (RU) и BY law

Если обработка затрагивает RU/BY субъектов — параллельно проверить:

**ФЗ-152 (RU):**
- Consent form по утверждённой форме (Постановление Правительства №1119)
- Согласие на cross-border transfer (с 2024 — уведомительный порядок)
- Уведомление в Роскомнадзор (при обработке >100 000 субъектов)
- DPO обязателен при обработке биометрии, health, large-scale

**Закон о защите персональных данных (BY):**
- Registration в Реестр операторов (Минюст) — для всех, обрабатывающих данные BY граждан
- Consent по форме (утверждён Постановлением)
- DPO обязателен для госорганов и при обработке special categories

### Step 9 — Сохранить через `saveResult()`

```javascript
const dept = require('../../../lib/legal');
await dept.saveResult({
  shortTitle: `GDPR/Privacy compliance check: <project/product>`,
  fullResult: formatComplianceReport(ropa, gaps, recommendations),
  jurisdiction: jurisdiction,
  businessForm: businessForm,
  confidence: 'medium', // compliance check всегда medium — requires legal review
  verificationDate: today + 90,
});
```

### Step 10 — Ответить владельцу

Формат: ROPA table + список gaps (что отсутствует) + приоритеты (что закрывать первым). Не «всё плохо» или «всё хорошо» — конкретный список действий.

## Worked example

**Запрос:** «Мы запускаем SaaS-продукт для EU клиентов. Telegram-бот как onboarding, веб-приложение как основной продукт.»

**Контекст:**
- BY ООО (controller)
- EU пользователи (data subjects)
- Data: email, name, company, usage analytics, payment data (через Stripe)
- Subprocessors: Telegram, Stripe, AWS (hosting), Cloudflare (CDN)

**ROPA:**

| Activity | Data | Basis | Recipients | Retention |
|---|---|---|---|---|
| Registration (email, name) | Identity | Consent | DB | Until deletion |
| Payment (card, billing address) | Financial | Contract | Stripe (US, DPF) | 7 years (tax) |
| Usage analytics | Behavioural | Legitimate interest | AWS (US, SCC) | 26 months |
| Customer support (Telegram) | Communication | Contract | Telegram (RU, NO SCC — **GAP**) | 3 years |
| Marketing (email) | Contact | Consent | Email provider | Until withdrawal |

**Identified gaps:**

1. **Telegram → data transfer to RU without SCC.** Telegram stores data on servers in RU (partially). Transfer of EU data subjects' communication to RU = non-adequate country + no SCC. **Fix:** либо исключить PII из Telegram общения (только session tokens, не личные данные), либо добавить SCC с Telegram (не practically feasible — Telegram не подписывает SCC с individual controllers), либо ограничить Telegram-support для EU клиентов к email-only.

2. **No cookie consent banner.** Если веб-приложение использует cookies (analytics, auth) — consent required. **Fix:** implement cookie banner с reject option для non-essential cookies.

3. **Privacy notice отсутствует.** **Fix:** draft privacy notice по Art. 13 checklist.

4. **No DPA with Cloudflare.** **Fix:** получить стандартный DPA cloudflare.com/dpa.

5. **No DPIA for analytics profiling.** If analytics creates user profiles (behavioural segments) — DPIA needed. **Fix:** conduct DPIA or anonymise analytics data (no user IDs).

**Priority:** Gap #1 (Telegram) критический — potential regulatory violation. Gap #2-5 — стандартные, закрываемые за 1-2 недели.

## Anti-patterns

- **«У нас есть privacy policy — значит compliant».** Privacy policy — это одно из требований, не единственное. ROPA, DPA, consent mechanisms, rights mechanisms, DPIA — всё это отдельно. **Countermeasure:** compliance check проверяет все 7 компонентов, не только документ.

- **Consent как pre-ticked checkbox.** «[✓] Я согласен на обработку» — невалидный consent по GDPR (Art. 4(11): consent должен быть «unambiguous indication»). Pre-ticked = ambiguous. **Countermeasure:** empty checkbox, active opt-in.

- **«Legitimate interest» без LIA.** «Мы используем LI для аналитики» — но LIA не проведён. В случае complaint — cannot demonstrate. **Countermeasure:** LIA document для каждого LI-based processing, even brief (3 paragraphs).

- **Забыть subprocessors в DPA.** «У нас DPA с клиентом» — но вы используете AWS, Stripe, Cloudflare, SendGrid. Каждый subprocessor требует DPA (Art. 28(2)). **Countermeasure:** список всех subprocessors + DPA для каждого. Standard DPAs от крупных providers — получать и хранить.

- **Right to erasure = DELETE FROM users WHERE id = X.** Но данные дублируются в analytics, logs, backups, email history, third-party services. Каскадное удаление — engineering task. Без него — right to erasure не исполнен. **Countermeasure:** data map (где именно хранятся данные субъекта) + deletion procedure covering all locations.

- **ФЗ-152/ФЗ-BY как «то же самое что GDPR».** Нет. Разные требования к форме consent, разные пороги для уведомления в надзорный орган, разные правила cross-border transfer. **Countermeasure:** при обработке данных BY/RU субъектов — отдельная проверка по национальному закону, не только GDPR.

## Output template

```
═══════════════════════════════════════════
GDPR/PRIVACY COMPLIANCE CHECK
═══════════════════════════════════════════

Project: <name>
Controller: <entity> (<jurisdiction>)
Data subjects: <jurisdictions>
Date: <date>

─── PROCESSING ACTIVITIES (ROPA) ───
| Activity | Data | Basis | Recipients | Retention | Status |
|----------|------|-------|------------|-----------|--------|
| ... | ... | ... | ... | ... | OK/GAP |

─── IDENTIFIED GAPS ───
Priority | Gap | Fix | Effort
CRITICAL | ... | ... | <S/M/L>
HIGH     | ... | ... | ...
MEDIUM   | ... | ... | ...

─── COMPLIANCE COMPONENTS ───
[✓/✗] Privacy notice (Art. 13-14)
[✓/✗] Consent mechanisms
[✓/✗] Data subject rights (all 8)
[✓/✗] DPA with subprocessors
[✓/✗] Cross-border transfer mechanism (SCC/adequacy/DPF)
[✓/✗] DPIA (if required)
[✓/✗] National law check (ФЗ-152/BY law)

─── ACTION ITEMS ───
1. <action> — <deadline> — <owner>
2. ...

⚠ COMPLIANCE CHECK — требуется проверка лицензированным юристом и DPO.
📎 В архиве: <archive_link>
```

## When NOT to use this skill

- Когда вопрос про **анализ договора** (не про compliance продукта) — это `red-flag-detection`
- Когда вопрос про **tax implications** — это Finance
- Когда нужен **IP analysis** — это `ip-clause-discipline`

## Integration with Legal

Tier 2, загружается при запросах про GDPR, privacy, ФЗ-152, PII, consent, cookie compliance, data protection.

Использует:
- `risk-mapping-protocol` — compliance gaps как риски
- `contract-drafting-discipline` — drafting DPA, privacy notice
- `nda-msa-sla-templates` — DPA clause в MSA
- `library/knowledge/legal/jurisdictions/<JX>.md` — национальные privacy laws