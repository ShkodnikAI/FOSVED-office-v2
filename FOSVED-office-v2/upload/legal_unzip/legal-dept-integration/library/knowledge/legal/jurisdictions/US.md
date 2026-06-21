# US — Соединённые Штаты (юрисдикция, legal knowledge pack)

**Версия:** 0.1 (PLACEHOLDER — структура готова, наполнение требуется)
**Дата:** 2026-05-22
**Status:** structural placeholder

⚠ **US — это 50+ юрисдикций.** Federal law + state law + local. Этот файл — federal базис + ключевые штаты для бизнеса (Delaware, California, New York).

---

## Правовая система

- **Common law** (за исключением Louisiana — civil law влияние)
- **Двухуровневая система:** Federal + State
- **Иерархия:** US Constitution → Federal law (USC, CFR) → State Constitution → State law → Local
- **Прецеденты** имеют силу нормы (stare decisis)
- **Главные источники:** USC, CFR, Westlaw, LexisNexis, Cornell LII (бесплатно)

## Federal contract law principles

- **No federal "contract law"** — договорное право в основном на уровне штатов
- **Uniform Commercial Code (UCC):** принят всеми штатами в той или иной форме — регулирует sales of goods, secured transactions
- **Restatement (Second) of Contracts** — авторитетная "summary" — не обязательна, но часто цитируется

## Договорное право — общие принципы

- **Offer + acceptance + consideration** = валидный договор
- **Statute of Frauds** — некоторые договоры требуют письменной формы (real estate, > 1 year, > $500 goods, marriage, etc.)
- **Choice of law / choice of forum:** обычно действуют, кроме mandatory consumer protections
- **Liquidated damages** — допустимы если разумные, не penalty
- **Indemnification** — широко используется, часто без cap

## Ключевые штаты для бизнеса

### Delaware
- **Корпоративное право убежище:** > 60% Fortune 500 зарегистрированы в DE
- **Court of Chancery** — специализированный суд для корпоративных споров
- **DGCL** (Delaware General Corporation Law)
- Для LLC: **DLLCA**
- **Annual franchise tax** обязателен

### California
- **Высокая защита потребителей** (CCPA — California Consumer Privacy Act)
- **CCPA/CPRA** — закон о приватности (похож на GDPR)
- **Employment law:** одно из самых жёстких в мире (no at-will exceptions, mandatory breaks, итд.)
- **Non-compete agreements:** запрещены (за редкими исключениями)

### New York
- **Финансовый центр:** большинство финансовых договоров используют NY law
- **NY UCC:** широко применяется
- **NY courts:** хорошая инфраструктура для коммерческих споров

### Texas/Florida/Wyoming
- **Low-tax, business-friendly** альтернативы DE/NY/CA

## Privacy laws

### Federal (нет одного закона)
- **HIPAA** — health data
- **GLBA** — financial
- **COPPA** — детские данные (<13)
- **CAN-SPAM** — email

### State (фрагментированно)
- **California (CCPA/CPRA):** comprehensive
- **Virginia (VCDPA):** comprehensive
- **Colorado (CPA):** comprehensive
- **Washington, Connecticut, Utah** — adopting

### При работе с US-клиентами + PII
- Если California резидент → CCPA (даже если ты вне California)
- DPA (Data Processing Agreement) обычно нужен для B2B SaaS

## IP law

### Trademark
- **USPTO (US Patent and Trademark Office)** — federal registration
- **State trademark** — отдельная регистрация (редко используется)
- **Use-based:** trademark возникает с момента использования (даже без регистрации) — но registration даёт сильную защиту

### Copyright
- **Automatic:** возникает в момент создания
- **Registration** обязательна для подачи иска в federal court
- **Work for hire doctrine:** работа сотрудника принадлежит работодателю; работа подрядчика — только если письменно оформлено как WFH в определённых категориях

### Patent
- **Utility patents** (20 лет), **design patents** (15), **plant patents**
- **First-to-file** (с 2013, AIA)
- Дорого: $5,000 - $20,000+ для качественной заявки

## Sanctions framework US

- **OFAC (Office of Foreign Assets Control):** SDN list, Sectoral Sanctions
- **BIS (Bureau of Industry and Security):** export controls
- **OFSI:** UK (post-Brexit independent)
- **Проверка counterparty:** обязательная для каждой международной сделки

## Litigation

### Federal courts vs State courts
- **Federal jurisdiction:** diversity (different states + >$75K), federal question, etc.
- **State courts:** general jurisdiction по штату
- **Discovery** — широкий процесс (depositions, interrogatories)
- **Jury trials** — для большинства гражданских дел право на jury (хотя waivable)

### Arbitration
- **Federal Arbitration Act** — сильная поддержка
- **AAA (American Arbitration Association)**, **JAMS** — крупные провайдеры
- **Class action waivers** — допустимы в большинстве штатов

### Statute of limitations
- Варьируется по штату и причине иска
- **Contract:** обычно 4-6 лет
- **Tort:** обычно 2-3 года

## Employment law

- **At-will employment** — стандарт (можно уволить в любой момент, кроме защищённых категорий)
- **Title VII, ADA, ADEA, FMLA** — federal protections
- **California:** усиленная защита (см. выше)

## Tax aspects of contracts

- **W-9** (для US persons) / **W-8BEN / W-8BEN-E** (для non-US)
- **1099-NEC** при выплате подрядчику ≥ $600/year
- **Withholding tax 30%** на пассивный доход non-residents (если нет treaty reduction)

## Cross-jurisdictional с EU

- **EU-US Data Privacy Framework (2023)** — после Schrems II
- **Standard Contractual Clauses** alt
- **AML/KYC:** US имеет жёсткие правила (Patriot Act, BSA)

## Cross-jurisdictional с RU/BY (2024+)

- **Sanctions:** OFAC SDN list широкий, нужно проверять
- **Some operations require licenses** даже для не-SDN counterparties
- **Recognition of judgments:** RU-судебные решения обычно не признаются в US без re-litigation

## TODO для полной версии

- [ ] Отдельные файлы DE/CA/NY/TX/FL legal specifics
- [ ] CCPA/CPRA compliance checklist
- [ ] Trademark procedure step-by-step
- [ ] Work-for-hire doctrine — детально (что покрывается, что нет)
- [ ] Sanctions matrix (SDN, sectoral, BIS)
- [ ] DPA templates US-style (vs EU-style)
- [ ] Class action mechanics — когда волноваться
- [ ] Discovery — что готовиться к раскрытию
