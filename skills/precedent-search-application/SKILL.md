---
name: precedent-search-application
description: Поиск прецедентов по типу спора в юрисдикции и применение к текущей ситуации. Применяется когда нужна оценка перспектив судебного спора или толкования спорной нормы.
tier: 1
---

# Precedent Search & Application — судебная практика как карта, не как ответ

Прецедент не «решает» спор — он показывает, **как суды в этой юрисдикции обычно решают** подобные споры. Гражданское право (BY/RU/EU civil law) не binding precedent в англосаксонском смысле, но де-факто: суды низших инстанций следуют практике высших (BY — Верховный суд, RU — Верховный суд, EU — ECJ/CJEU, US — binding stare decisis). Игнорировать судебную практику = писать договор не зная как его будут толковать.

## Prerequisites

- Юрисдикция определена
- Тип спора или вопрос конкретизирован (не «что говорит закон про IP», а «является ли implicit licence достаточной при отсутствии explicit assignment в DE»)
- Норма(ы) права, подлежащие толкованию, известны
- Доступ к судебным базам (для BY/RU — базы открыты; EU — CURIA; US — public federal/state databases)

## Core principle

> **Один прецедент — anecdote. Три+ прецедента по одному вопросу — trend. Десять+ — jurisdictional practice.** Юридический анализ на одном судебном решении — как финансовый прогноз на одном datapoint. Судебная практика имеет noise (судья ошибся, unique facts, overturned later), и полезность зависит от **sample size и consistency**. Если 8 из 10 решений по penalty clauses в DE говорят «0.5%/день = potentially abusive» — это practice, не coincidence.

**Инверсия интуиции:** в civil law jurisdictions (BY/RU/EU) precedent «не binding» de jure. Но de facto: решение appellate/Supreme court создаёт interpretive framework, который lower courts follow. «Прецедент не binding» — технически верно, но практически useless observation. Юрист, который говорит «в BY нет precedent, только кодекс» — либо не pratique, либо лукавит. Верховный суд BY публикует обзоры практики именно для того, чтобы lower courts следовали.

## The procedure

### Step 1 — Сформулировать search query

Не абстрактный, а конкретный legal question:

**Плохо:** «precedents про IP в IT контрактах»

**Хорошо:**
- BY: «право собственности на результат подрядных работ по ГК ст. 708 при отсутствии explicit IP clause»
- DE: «validity of liability cap in B2B SaaS contract under § 307 BGB»
- EU: «whether GDPR right to erasure applies to data processed by AI model training (Art. 17 vs Art. 22)»
- US: «enforceability of non-compete clause in California for tech employee»

### Step 2 — Search по иерархии судов

**BY (по убыванию авторитетности):**
1. Обзоры судебной практики Верховного суда (публикуются ежеквартально, cover все области)
2. Постановления Пленума Верховного суда (разъяснения по конкретным вопросам права)
3. Решения Верховного суда (кассационная инстанция — rare, но binding effect)
4. Решения областных/Минского городского судов (appellate — indicative, не binding)

**Источники:** court.gov.by (база решений Верховного суда), pravo.by (законодательство + практика)

**RU:**
1. Обзоры судебной практики Верховного суда РФ
2. Постановления Пленума Верховного суда РФ
3. Информационные письма Президиума ВАС РФ (arbitration — для коммерческих споров)
4. Решения судов округов (КАС/ФАС)

**Источники:** sudact.ru, pravo.ru, garant.ru

**EU:**
1. CJEU (Court of Justice of the EU) — binding для всех member states
2. National supreme courts (BGH для DE, Cour de cassation для FR, etc.)
3. National appellate courts

**Источники:** CURIA (curia.europa.eu), national court databases

**US:**
1. US Supreme Court — binding nationally
2. Federal Circuit Courts of Appeals — binding within circuit
3. State Supreme Courts — binding within state
4. Federal District Courts — persuasive, not binding

**Источники:** courtlistener.com, justia.com, lexisnexis (paid)

### Step 3 — Оценить relevance каждого найденного решения

Для каждого precedent — cheклист:

```
1. Факты схожи с нашим кейсом? (Y/N/partial)
   - Если partial: какие отличия критичны?
2. Суд того же уровня или выше? (Y/N)
   - Supreme/appellate = high authority
   - District/first instance = low authority
3. Решение не overturned? (Y/N/unknown)
4. Год решения: < 5 лет (current) / 5-10 лет (relevant) / > 10 лет (potentially outdated)
5. Ratio decidendi (правило из решения) применимо к нашему вопросу?
6. Obiter dicta (попутные замечания) — не binding, но indicative
```

**Критическая ошибка:** cherry-picking. Найти один precedent, который поддерживает нашу позицию, игнорируя пять противоречащих. **Countermeasure:** search должен быть balanced — найти precedent(s) supporting our position AND precedent(s) contradicting it.

### Step 4 — Свести в analysis matrix

```
| # | Case | Court | Year | Facts match | Ratio | Supports our position? | Authority |
|---|------|-------|------|-------------|-------|----------------------|-----------|
| 1 | Name v Name | Supreme BY | 2024 | High | «Without explicit assignment, client owns» | YES | High |
| 2 | Name v Name | Minsk City | 2023 | Partial | «Contractor retained IP due to ambiguous clause» | NO | Low |
| 3 | ... | ... | ... | ... | ... | ... | ... |
```

**Взвешивание:** High authority + YES = strong support. Low authority + NO = weak counter. High authority + NO = strong counter (needs addressing).

### Step 5 — Application к текущей ситуации

На основе matrix — **assessment**:

```
Jurisdictional practice: <тенденция>
  Supporting: N cases (M high authority)
  Contradicting: N cases (M high authority)
  Net assessment: <favourable / unfavourable / unclear>

Risk areas:
  <specific legal questions where practice is inconsistent>

Recommendation for contract drafting / dispute strategy:
  <concrete action based on precedent analysis>
```

### Step 6 — Сохранить через `saveResult()`

```javascript
const dept = require('../../../lib/legal');
await dept.saveResult({
  shortTitle: `Precedent analysis: <legal question> (${jurisdiction})`,
  fullResult: formatPrecedentAnalysis(matrix, assessment, recommendation),
  jurisdiction: jurisdiction,
  businessForm: businessForm,
  confidence: 'medium', // precedent analysis = medium by default (sample may be incomplete)
  verificationDate: today + 180, // practice evolves
});
```

### Step 7 — Ответить владельцу

```
═══════════════════════════════════════════
PRECEDENT ANALYSIS
═══════════════════════════════════════════

Legal question: <specific question>
Jurisdiction: <JX>
Date: <date>

─── FOUND PRECEDENTS ───
| # | Case | Court | Year | Key holding | Supports us? |
|---|------|-------|------|-------------|-------------|
| 1 | ... | ... | ... | «...» | YES/NO/PARTIAL |
| ... | ... | ... | ... | ... | ... |

─── PRACTICE ASSESSMENT ───
Trend: <favourable / unfavourable / split>
Supporting: <N> cases (<M> high authority)
Contradicting: <N> cases (<M> high authority)
Confidence in assessment: <high/medium/low>

─── APPLICATION ───
How this affects our position:
  <specific impact>

Recommended action:
  <for drafting: clause recommendation>
  <for dispute: P(win) adjustment>

─── GAPS ───
<questions where no precedent found — higher uncertainty>

⚠ PRECEDENT ANALYSIS — requires licensed lawyer verification.
📎 В архиве: <archive_link>
```

## Worked example

**Запрос:** «DE контрагент не хочет explicit IP assignment — говорит "DE standard is sufficient". Какие прецеденты?»

**Legal question:** «Is an implied licence sufficient to transfer IP rights from contractor to client in DE, or is explicit assignment required?»

**Search (DE):**

| # | Case | Court | Year | Facts | Holding | Supports? | Authority |
|---|---|---|---|---|---|---|---|
| 1 | BGB § 631 interpretation | BGH | 2020 | Software development contract without IP clause | «Without explicit agreement on IP transfer, UrhG § 43 applies: contractor retains copyright» | NO (need explicit) | **High** |
| 2 | Website development | OLG Düsseldorf | 2022 | Agency created website, contract silent on IP | «Client has implied licence to use, but not ownership. Contractor retains right to license to third parties» | NO (licence ≠ ownership) | Medium |
| 3 | SaaS platform development | LG Berlin | 2021 | Contract with «results belong to client» clause | Court upheld — but clause was explicit in contract | YES (if explicit clause exists) | Low-Medium |
| 4 | Freelancer vs GmbH | BGH | 2019 | Written IP assignment after delivery | «Assignment must be in writing (§ 31 UrhG) and explicitly identify the works» | YES (shows how to do it right) | **High** |

**Practice assessment:**
- **Clear trend:** 4/4 cases confirm: in DE, explicit IP assignment is required. Without it — contractor retains copyright, client gets implied licence only.
- **High authority support:** BGH (cases #1, #4) — highest DE civil court.
- **No contradicting cases found** (for this specific question).
- **Confidence: HIGH** — practice is consistent.

**Application:**
- Our position (need explicit IP assignment) is supported by DE practice.
- Counterparty's argument ("DE standard is sufficient") contradicts BGH precedent.
- Drafting recommendation: use § 31 UrhG-compliant assignment clause (see `ip-clause-discipline`).
- If counterparty refuses: our P(win) in IP ownership dispute ≈ 85% (based on practice), but litigation in DE = 12-24 months.

## Anti-patterns

- **Cherry-picking precedent.** Найти один case, который поддерживает позицию, и проигнорировать пять противоречащих. **Countermeasure:** balanced search: min 3-5 cases, explicitly search for both supporting AND contradicting. В analysis matrix — оба столбца.

- **Equating ratio decidendi и obiter dicta.** Суд в passing упомянул «penalty clauses are generally suspect» — это obiter dicta, не binding rule. Но inexperienced юрист может процитировать как precedent. **Countermeasure:** для каждого cited case — separate ratio (binding rule) from obiter (persuasive comment).

- **US precedent для civil law jurisdiction.** «В US такой случай решили так». US — common law, binding precedent system. BY/RU/EU — civil law. US precedent может быть persuasive, но не apply. **Countermeasure:** US cases — как "comparative reference" только, не как authority для BY/RU/EU questions.

- **Outdated precedent.** «Верховный суд BY в 2012 году решил...». Если с 2012 изменился закон (или вышел новый обзор практики) — старый precedent может быть outdated. **Countermeasure:** проверять status: не изменён ли закон, не вышел ли новый обзор практики, не overturned ли кейс.

- **One precedent = practice.** Один case — anecdote. Три+ consistent = practice. **Countermeasure:** min 3 cases для формулировки "jurisdictional practice". Если <3 — "indicative, not conclusive".

- **Ignorе hierarchy.** Решение районного суда (first instance) цитируется как "прецедент" наравне с Верховным судом. **Countermeasure:** всегда указывать court level в analysis matrix. Low authority cases — indicative only.

## Output template

```
═══════════════════════════════════════════
PRECEDENT ANALYSIS
═══════════════════════════════════════════

Legal question: <specific>
Jurisdiction: <JX>
Date: <date>

─── PRECEDENT MATRIX ───
| # | Case citation | Court | Year | Facts match | Key holding (ratio) | Supports? | Authority |
|---|---------------|-------|------|-------------|-------------------|-----------|-----------|
| 1 | ... | ... | ... | H/M/L | «...» | YES/NO | H/M/L |
| ... | ... | ... | ... | ... | ... | ... | ... |

─── PRACTICE ASSESSMENT ───
Trend: <favourable / unfavourable / split / unclear>
Supporting (our position): <N> cases (<M> high authority)
Contradicting: <N> cases (<M> high authority)
Unresolved: <questions with no clear practice>
Confidence: <high/medium/low>

─── APPLICATION TO OUR CASE ───
Impact: <how this affects our position>
P(win) adjustment: <if applicable, new probability>
Drafting recommendation: <if applicable>
Risk areas: <where practice is inconsistent or absent>

─── SEARCH METHODOLOGY ───
Sources searched: <list>
Date range: <from - to>
Keywords: <list>
Exclusions: <if any>

⚠ PRECEDENT ANALYSIS — requires licensed lawyer verification.
📎 В архиве: <archive_link>
```

## When NOT to use this skill

- Когда нужно **написать договор** — это `contract-drafting-discipline` (precedent analysis может быть input, но не output)
- Когда спор **уже идёт** и нужна стратегия — это `dispute-resolution-strategy` (precedent analysis → P(win) adjustment)
- Когда вопрос **чисто теоретический** («что говорит кодекс») — read the code, не precedent

**Граница с ip-clause-discipline:** precedent-search-application ищет **судебные решения** по конкретному вопросу. ip-clause-discipline оперирует **нормами права** (кодекс, закон) и drafting templates. Прецеденты могут быть input для IP clause, но IP clause skill = output (формулировки), precedent skill = output (analysis of how courts interpret such formulations).

## Integration with Legal

Tier 1, загружается при запросах про судебную практику, оценку перспектив спора, толкование норм.

Использует:
- `risk-mapping-protocol` — спорные вопросы из risk map как search queries
- `dispute-resolution-strategy` — precedent analysis → P(win) для NPV calculation
- `contract-drafting-discipline` — precedent findings как input для drafting decisions
- `cross-jurisdiction-comparison` — practice differences between jurisdictions
- `library/knowledge/legal/jurisdictions/<JX>.md` — court hierarchy и sources