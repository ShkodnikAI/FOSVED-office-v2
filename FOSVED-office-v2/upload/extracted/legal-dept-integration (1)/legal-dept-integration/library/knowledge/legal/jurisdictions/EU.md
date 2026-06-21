# EU — Евросоюз (юрисдикция, legal knowledge pack)

**Версия:** 0.1 (PLACEHOLDER — структура готова, наполнение требуется)
**Дата:** 2026-05-22
**Status:** structural placeholder

⚠ **EU — не единая юрисдикция.** 27 стран с национальным правом + общеевропейское право (Регламенты — прямое действие, Директивы — имплементация в национальное право). Этот файл — общеевропейская часть, конкретные страны — отдельные файлы (TODO).

---

## Иерархия источников права EU

1. **Учредительные договоры (TEU, TFEU)** — конституционный уровень
2. **Регламенты (Regulations)** — прямое действие во всех 27 странах (GDPR, Rome I/II, и т.д.)
3. **Директивы (Directives)** — имплементация национальным законодательством (срок обычно 2 года)
4. **Решения** — обязательны для адресатов
5. **Прецеденты ECJ** (Европейский суд)

## Главные регламенты (для бизнеса)

### GDPR (Регламент 2016/679)

- **Применяется:** обработка PII резидентов EU независимо от места обработчика
- **Принципы:** lawfulness, fairness, transparency, purpose limitation, data minimisation, accuracy, storage limitation, integrity, accountability
- **Правовые основания обработки:** consent, contract, legal obligation, vital interest, public interest, legitimate interest
- **Права субъекта:** access, rectification, erasure ("right to be forgotten"), restriction, portability, objection
- **DPO (Data Protection Officer):** обязателен для крупных обработчиков
- **DPA (Data Processing Agreement):** обязателен между controller и processor
- **Уведомление инцидентов:** в 72 часа в надзорный орган
- **Штрафы:** до €20 млн или 4% global revenue (whichever higher)

### Rome I (Регламент 593/2008)
- Применимое право к договорным обязательствам
- Party autonomy + защитные нормы

### Rome II (Регламент 864/2007)
- Применимое право к внедоговорным обязательствам (деликты, etc.)

### Brussels I Recast (1215/2012)
- Юрисдикция и признание решений в EU

### Digital Services Act (2065/2022) + Digital Markets Act (1925/2022)
- Регулирование онлайн-платформ и больших игроков

### EU AI Act (1689/2024)
- Регулирование AI-систем по уровню риска
- **Применяется к AI-разработчикам в EU и поставщикам AI в EU**
- Сроки имплементации: 2025-2027 по этапам

## Договорное право — общие принципы

- **Party autonomy** — стороны выбирают применимое право (с защитой потребителей)
- **Существенные условия** — варьируются по странам
- **Form requirements** — обычно письменная для крупных договоров
- **Электронная подпись:** eIDAS Regulation (910/2014) — единый стандарт EU
  - Standard, Advanced, Qualified Electronic Signature (QES)
  - QES = бумажная подпись в ЕС

## Защита потребителей

- **Consumer Rights Directive (2011/83)** + дополнения
- **Право на возврат:** 14 дней для distance/online sales
- **Mandatory consumer law** — независимо от выбора права
- **Unfair Contract Terms Directive (93/13)** — нечестные пункты в B2C договорах ничтожны

## Корпоративное право

- Общеевропейских форм мало (SE — Societas Europaea, но используется редко)
- Большинство компаний регистрируется по национальному праву
- **Cross-border mergers** регулируются Directive (EU) 2017/1132

## Trademark / IP

- **EU Trademark (EUIPO):** единая регистрация на 27 стран
- **Community Design (registered/unregistered)**
- **Authors' rights:** harmonised but national differences
- **SPC (Supplementary Protection Certificate):** для фармы

## Sanctions framework EU

- **Council Regulations** — основная форма
- **Common Foreign and Security Policy decisions**
- **Регулярно обновляются** — проверка counterparty обязательна
- **OFSI (UK)** — отдельно после Brexit

## Cross-jurisdictional с не-EU странами

### EU ↔ US (Data)
- **EU-US Data Privacy Framework (2023)** — после Schrems II
- **Standard Contractual Clauses (SCCs)** — альтернатива для не-DPF компаний
- **Transfer Impact Assessment** обязательная

### EU ↔ UK (post-Brexit)
- **UK GDPR** ≈ EU GDPR (но дрейфуют)
- **Adequacy decision** для transfer (продлевается)
- **Trade and Cooperation Agreement** — основа отношений

### EU ↔ Russia (2022+)
- **Sanctions packages** (на момент написания — 13-й пакет с дополнениями)
- Многие виды операций запрещены или требуют лицензий
- **Frozen assets, asset freezes** для конкретных лиц

## TODO для полной версии

- [ ] Отдельные файлы для DE/FR/PL/NL/IE (топ EU юрисдикции для бизнеса)
- [ ] GDPR — подробный compliance checklist
- [ ] DSA/DMA — обязательства для платформ разного размера
- [ ] AI Act — классификация рисков, обязательства
- [ ] Trademark процедура (EUIPO)
- [ ] eIDAS — практическое применение QES
- [ ] Cross-border insolvency
- [ ] Sanctions matrix (актуальная на дату)
