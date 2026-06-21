# US — Соединённые Штаты (юрисдикция, financial knowledge pack)

**Версия:** 0.1 (PLACEHOLDER — структура готова, наполнение требуется)
**Дата:** 2026-05-22
**Status:** structural placeholder

⚠ **Двойная сложность.** В US налоги собираются **на двух уровнях**: федеральный (IRS) + штатный (State). 50 штатов с разными правилами. Этот файл описывает базу + ключевые особенности, но конкретный штат — отдельная сверка.

⚠ **TODO для полной версии.** Каркас готов, конкретики требуется добавить.

---

## Общие сведения

- **Валюта:** US Dollar (USD)
- **Налоговые органы:** IRS (federal), State Tax Department (each state)
- **Налоговый кодекс:** Internal Revenue Code (IRC, Title 26 of US Code)
- **Курс валют:** Federal Reserve (для информации, отчётность в USD)

## Federal taxes

### Corporate Income Tax (для C-Corp / LLC taxed as corp)

- **Стандартная:** 21% (с Tax Cuts and Jobs Act 2017)
- **Период:** год, авансы поквартально
- **Дедлайн уплаты:** 15 апреля (для календарного года)

### Personal Income Tax (для individual / pass-through от LLC / sole prop)

Прогрессивная шкала 2026 (married filing jointly):

| Bracket | Marginal rate |
|---|---|
| $0 – $23,200 | 10% |
| $23,200 – $94,300 | 12% |
| $94,300 – $201,050 | 22% |
| $201,050 – $383,900 | 24% |
| $383,900 – $487,450 | 32% |
| $487,450 – $731,200 | 35% |
| $731,200+ | 37% |

(ставки могут отличаться, требуется проверка на 2026)

### Self-Employment Tax

Самозанятые и ИП-эквивалент платят **за себя** Social Security + Medicare:
- **15.3%** (Social Security 12.4% + Medicare 2.9%)
- На доход до $168 600 (2024 cap для SS, ежегодно растёт) — полностью
- На доход свыше — только Medicare 2.9% + 0.9% Additional Medicare для high earners

### Federal Insurance Contributions Act (FICA) — для employees

Для нанятых работников:
- **6.2%** Social Security (employee) + 6.2% employer
- **1.45%** Medicare (employee) + 1.45% employer
- **0.9%** Additional Medicare для income > $200 000

### Withholding Tax (для нерезидентов)

- **30%** на пассивный доход (дивиденды, проценты, royalties) — если не снижено tax treaty
- **0%** на business income (для нерезидентов без US PE)

## State taxes

Различаются существенно:

### No income tax states (9 штатов)
- **Florida, Texas, Nevada, Washington, Wyoming, South Dakota, Alaska, Tennessee, New Hampshire**
- Популярны для regustration of online businesses

### Low-tax states
- **Delaware** — 0% sales tax, корпоративная гавань (LLC + C-Corp); годовой franchise tax
- **Wyoming** — 0% personal income tax, LLC anonymity
- **Nevada** — 0% income tax

### High-tax states
- **California:** до 13.3% personal income tax, 8.84% corporate
- **New York:** до 10.9% personal, 7.25% corporate

### Sales Tax

**Нет federal sales tax**, каждый штат свой:
- **0%** — Delaware, Montana, Oregon, New Hampshire, Alaska
- **2-5%** — большинство штатов с местными доплатами
- **7-10%** — California (с местными доплатами), Tennessee, Texas

**Wayfair decision (2018):** удалённые продавцы (e-commerce, SaaS) платят sales tax, если превышают **economic nexus** в штате — обычно $100 000 продаж или 200 транзакций в год.

## Business forms

### Sole Proprietorship
- Простейшая форма, нет регистрации юр. лица
- Доход в Schedule C (personal tax return Form 1040)
- 1099-NEC от клиентов при доходе ≥ $600 от одного клиента
- SE Tax 15.3%
- Personal liability (риск личным имуществом)

### LLC (Limited Liability Company)

**Single-member LLC (SMLLC):**
- По умолчанию — "disregarded entity" — налогообложение как Sole Prop
- Можно выбрать налогообложение как C-Corp или S-Corp (Form 8832 / 2553)

**Multi-member LLC:**
- По умолчанию — partnership (Form 1065)
- Можно выбрать корпорацию

### C-Corporation
- Double taxation: налог 21% на корп. прибыль + dividend tax при выплате shareholders
- Удобен для привлечения инвесторов (можно выпускать акции)

### S-Corporation
- Pass-through (доход в personal tax)
- Ограничения: до 100 shareholders, только US citizens/residents
- Помогает экономить на SE Tax (распределение прибыли как salary vs distribution)

## EIN (Employer Identification Number)

- Налоговый идентификатор компании / sole prop с работниками
- Бесплатно через IRS website
- Обязателен для: LLC, Corp, payroll, банковский счёт юр. лица
- Опционально: для sole prop (можно использовать SSN, но EIN отделяет личные финансы)

## 1099 forms (для контрактных платежей)

- **1099-NEC** — за работу подрядчика (выписывается клиентом при выплате ≥ $600/год одному подрядчику)
- **1099-K** — от платёжных систем (Stripe, PayPal) при ≥ $600/год обороте через них (с 2026, snizhili threshold)
- **1099-MISC** — для прочих случаев (royalties, rents)

## Налоговый календарь (federal)

| Действие | Период | Дедлайн |
|---|---|---|
| Quarterly estimated taxes (sole prop, LLC) | квартал | 15 апр / 15 июня / 15 сент / 15 янв |
| Annual return (1040, Schedule C) | год | 15 апреля |
| Corporate return (1120, C-Corp) | год | 15 апреля |
| Partnership return (1065) | год | 15 марта |
| S-Corp return (1120-S) | год | 15 марта |
| Employer payroll (941) | квартал | конец след. месяца |
| Annual W-2 / 1099 to recipients | год | 31 января |

State дедлайны обычно близкие к federal.

## Особенности для IT/SaaS

- **R&D credit:** federal credit за исследования и разработку (ограничение)
- **Section 174** (с 2022): R&D расходы должны капитализироваться (5 лет US R&D, 15 лет foreign) — это **большая проблема** для IT-стартапов
- **QSBS (Section 1202):** освобождение от capital gains для qualified small business stock при удержании 5+ лет (до $10M или 10x basis)

## Cross-border ситуации

### BY/RU/EU-резидент работает с US-клиентами

- **Form W-8BEN / W-8BEN-E** — заявляет статус нерезидента
- **No tax treaty:** 30% withholding на дивиденды/royalties; 0% на business income
- **With tax treaty:** BY—US (нет действующего), RU—US (есть, но статус 2022+ неопределённый); EU—US (есть для большинства стран)
- **1099 не выпускается** для иностранных подрядчиков (если правильно заполнен W-8BEN)

### US-резидент работает с международными клиентами

- **Foreign Tax Credit:** если платил налоги в другой стране, можно зачесть против US tax
- **FBAR (FinCEN 114):** обязательное декларирование иностранных счетов с балансом > $10 000
- **Form 8938:** дополнительное декларирование для крупных foreign assets

## Платёжные системы

- **Stripe** — основной для онлайн-инвойсов
- **PayPal** — для физлиц и малого бизнеса
- **Wise (formerly TransferWise)** — мультивалютные транзакции
- **ACH (Automated Clearing House)** — стандартные банковские переводы US
- **Wire transfer** — быстрые крупные платежи

## TODO для полной версии

- [ ] Конкретные knowledge файлы для популярных штатов (DE, CA, NY, FL, TX, WY)
- [ ] Sales tax economic nexus — подробная таблица по штатам
- [ ] Form 1040 schedules (B, C, D, E, SE) — когда какие нужны
- [ ] Estimated tax расчёты (Safe Harbor rules)
- [ ] Налоговые treaties детально для BY/RU/EU стран
- [ ] R&D credit формулы и расчёты
- [ ] Section 174 capitalization — конкретные расчёты
- [ ] PPP, ERC и другие COVID-era программы (если ещё актуально)

**Для конкретных US-операций — обязательная сверка с CPA или EA (Enrolled Agent) в США. Этот knowledge — справочный, не консультация.**
