# ОСП — Проектные Параметры (Enrichment V3.1)

**Дата:** 2026-08-17
**Статус:** Draft → для ревью владельцем
**Базируется на:** osp.md V3.0, osp.mlog ENRICHED v2, deconstruct SKILL.md, METHODOLOGY.md V1.1

---

## 1. Prisma-схема: Analysis (архив препарирований)

```prisma
model Analysis {
  id              String   @id @default(cuid())
  createdAt       DateTime @default(now())
  updatedAt       DateTime @updatedAt

  // ── Идентификация ──
  topic           String                    // точная формулировка темы
  slug            String   @unique          // URL-safe slug (авто из topic)
  depthLevel      Int                       // 0-4 (quick → full)
  domain          String                    // financial | monetary | geopolitical | military | corporate | political | general

  // ── Статус ──
  status          AnalysisStatus @default(DRAFTED)
  // drafted → published → watching → verified | missed | partial | superseded
  publishedAt     DateTime?
  verifiedAt      DateTime?
  supersededById  String?
  supersededBy    Analysis?  @relation("SupersededBy", fields: [supersededById], references: [id])

  // ── Phase 1: Reconnaissance ──
  awarenessFrame  String                    // JSON: awareness-frame output
  subject         String                    // точное определение субъекта
  macroPhase      String                    // долговой цикл / геополит / техно
  eventPhase      String                    // build-up | trigger | acute | resolution | post-event

  // ── Phase 2: Preparation (12 layers + topology) ──
  layers          Json                      // {L1..L12} — каждый слой с [ФАКТ]/[ИНТЕРПРЕТАЦИЯ]/[СПЕКУЛЯЦИЯ] метками
  topology        Json                      // {leaves, branches, stem, roots, fruits, environment}
  rootCauseMap    String                    // root-cause-mapping output

  // ── Phase 3: Staff Block ──
  forcesAndPotentials  Json                 // {forces: [{name,position,A,R,S,L,E,P,notes}], differential, timeEvolution}
  strategicManeuvers   Json                 // {candidates: [{name,type,action,directionShift,cost,risk,trigger}]}
  twoPaths             Json                 // {pathA, pathB, convergent, divergent, synthesis}
  systemHealth         Json?                // если загружен system-health-diagnostics: {healthScore, timeToCollapse, diseases}

  // ── Phase 4: Forecast ──
  decisionTreeForecast  Json                // {roots, stems, branches, fruits, seeds, divergenceBranches, indicators}
  investmentImplications Json               // {highConfidence, asymmetric, seedOpportunities, marketMissing}

  // ── Verification ──
  verificationDate      DateTime            // дата ближайшей проверки
  brierScore            Float?              // после верификации
  actualOutcome         String?             // что реально произошло
  errorCategory         String?             // wrong_scoring | missed_force | missed_time_evolution | wrong_model | other

  // ── Confidence ──
  overallConfidence     ConfidenceLevel     // LOW | MEDIUM | HIGH
  kentProbability       String?             // формулировка по Kent (e.g., "Likely 65-80%")

  // ── Meta ──
  chatSummary           String              // 15-25 line compact for Telegram
  chatSummaryLines      Int                 // для quality gate: ≤25
  sources               Json                // [{tier, type, citation, url, retrievedAt}]
  newsContextUsed       Boolean @default(false)  // были ли использованы свежие новости
  modelUsed             String?             // e.g., "claude-sonnet-4-20250514"
  providerUsed          String?             // e.g., "anthropic"
  tokenBudgetUsed      Int?                // фактический расход токенов
  durationSeconds      Int?                // время выполнения анализа

  // ── Relations ──
  indicators     Indicator[]
  watchlistItems WatchlistItem[]
  linkedArtifacts KnowledgeArtifact[]       // из Лаборатории знаний

  // ── Audit ──
  autoEscalationTriggers Json?             // какие триггеры сработали для auto-escalation
  qualityGatesPassed     Json               // {gate1: true, gate2: true, gate3: false...}
  qualityGatesFailed     Json?              // список failed gates

  @@index([topic])
  @@index([status])
  @@index([domain])
  @@index([verificationDate])
  @@index([createdAt])
}

enum AnalysisStatus {
  DRAFTED
  PUBLISHED
  WATCHING
  VERIFIED
  MISSED
  PARTIAL
  SUPERSEDED
}

enum ConfidenceLevel {
  LOW
  MEDIUM
  HIGH
}

model Indicator {
  id          String   @id @default(cuid())
  analysisId  String
  analysis    Analysis @relation(fields: [analysisId], references: [id])

  description String                    // что проверяем
  verifyDate  DateTime                  // когда проверяем
  isBinary    Boolean  @default(true)   // бинарный индикатор?
  result      Boolean?                  // true = сработал, false = не сработал, null = не проверен
  verifiedAt  DateTime?
  confirmsWhat String                  // какой fruit/seed/root подтверждает

  // Scheduler integration
  preVerifyReminderSent Boolean @default(false)  // за 7 дней до verifyDate
  scheduledJobId        String?                  // ID в scheduler

  @@index([verifyDate])
  @@index([analysisId])
}

model WatchlistItem {
  id          String   @id @default(cuid())
  analysisId  String
  analysis    Analysis @relation(fields: [analysisId], references: [id])

  topic       String                    // тема наблюдения
  frequency   WatchFrequency @default(DAILY)
  lastCheckAt DateTime?
  nextCheckAt DateTime?
  active      Boolean  @default(true)

  // Delta tracking
  lastDelta   String?                   // что изменилось с прошлой проверки
  deltaCount  Int     @default(0)       // сколько раз замечали изменения

  @@index([nextCheckAt])
  @@index([active])
}

enum WatchFrequency {
  DAILY
  WEEKLY
  BIWEEKLY
}

model BrierScoreLog {
  id          String   @id @default(cuid())
  analysisId  String
  date        DateTime @default(now())

  forecastProbability  Float    // заявленная вероятность
  actualOutcome        Float    // 1.0 = сбылось, 0.0 = не сбылось
  brierScore          Float    // (f - a)^2
  cumulativeBrier     Float    // бегущий кумулятив
  totalForecasts      Int      // общее число прогнозов на этот момент

  @@index([analysisId])
  @@index([date])
}

model CalibrationCurvePoint {
  id          String   @id @default(cuid())
  date        DateTime @default(now())

  binLabel    String              // "65-80%" (Kent Likely)
  binCenter   Float               // 0.725
  forecastsInBin Int             // сколько прогнозов в этом бине
  actualRate    Float             // какая доля реально сбылась
  deviation     Float             // |actualRate - binCenter| — мискалибровка

  @@index([date])
}
```

---

## 2. Токен-бюджеты по фазам и глубине

Текущий бюджет: 25000 токенов **общий** (в LoadOSPEnrichedSkills). Это работает для depth 0-1, но на depth 2+ нужен контроль по фазам.

### Per-phase бюджет (рекомендация)

| Глубина | Phase 1 (Awareness) | Phase 2 (12 Layers + Topology) | Phase 3 (Staff Block) | Phase 4 (Forecast) | Output (Chat+Archive) | **Итого** |
|---------|---------------------|-------------------------------|----------------------|--------------------|-----------------------|-----------|
| 0 (Quick) | 500 | 1000 | 800 | 600 | 600 | **3500** |
| 1 (Standard) | 800 | 4000 | 3000 | 2000 | 1200 | **11000** |
| 2 (Wargame) | 1000 | 6000 | 5000 | 3500 | 1500 | **17000** |
| 3 (Deep) | 1200 | 8000 | 7000 | 5000 | 2000 | **23200** |
| 4 (Full) | 1500 | 10000 | 9000 | 7000 | 2500 | **30000** |

**Skill loading бюджет:**
| Tier | Max tokens | Примечание |
|------|-----------|------------|
| Tier 1 (always) | 12000 | 10 скиллов, усреднённо ~1200/скилл |
| Tier 2 (domain) | 6000 | 3-6 скиллов |
| Tier 3 (special) | 3000 | 1-3 скилла |
| Domain KB | 500 | из OSPDomainKB |
| Profile + context | 1500 | osp.md + meta |
| **Итого skills+context** | **23000** | на depth 3-4 |

**Итого total budget per request:**
- Depth 0: skills (8000) + analysis (3500) = **11500**
- Depth 1: skills (12000) + analysis (11000) = **23000**
- Depth 2: skills (18000) + analysis (17000) = **35000**
- Depth 3: skills (20000) + analysis (23200) = **43200** ← нужен Sonnet/Opus
- Depth 4: skills (23000) + analysis (30000) = **53000** ← нужен Opus + multi-turn

---

## 3. Модельные конфигурации

| Глубина | Primary Model | Fallback Model | Reasoning effort | Температура | Обоснование |
|---------|--------------|----------------|-----------------|-------------|-------------|
| 0 (Quick) | claude-3-5-haiku | claude-3-5-haiku | low | 0.0 | Быстрый ответ, стандартный анализ |
| 1 (Standard) | claude-sonnet-4-20250514 | claude-3-5-sonnet | medium | 0.0 | Баланс скорости и глубины |
| 2 (Wargame) | claude-sonnet-4-20250514 | claude-3-5-sonnet | high | 0.0 | Расширенное reasoning для Phase 3 |
| 3 (Deep) | claude-opus-4-20250514 | claude-sonnet-4-20250514 | high | 0.0 | Глубокий анализ, нужны рассуждения |
| 4 (Full) | claude-opus-4-20250514 | claude-opus-4-20250514 | high | 0.0 | Multi-turn, max reasoning |

**Provider priority:** anthropropic > openai (fallback) > local-ollama (offline)

**Config format в mlog:**
```
let depth_model = [
  "claude-3-5-haiku",       // depth 0
  "claude-sonnet-4-20250514", // depth 1
  "claude-sonnet-4-20250514", // depth 2
  "claude-opus-4-20250514",   // depth 3
  "claude-opus-4-20250514"    // depth 4
]
```

---

## 4. Quality Gates (программные, не только промпт-уровень)

Текущие gates описаны в deconstruct SKILL.md (11 правил). Для программного контроля:

```typescript
interface QualityGates {
  // Phase 1
  awarenessFramePresent: boolean;        // Gate 1: frame существует и не пустой
  subjectPreciselyDefined: boolean;      // Gate 1a: subject определён в 1 предложении (не vague)

  // Phase 2
  noEmptyLayers: boolean;                // Gate 2: ни один из 12 слоёв не пустой
  layer8ExplicitComparison: boolean;     // Gate 3: Layer 8 содержит явное сравнение narrative vs flows
  layer11HasNullHypothesis: boolean;     // Gate 4: Layer 11 включает Hanlon/null hypothesis
  topologyHasFruits: boolean;            // Gate 5: топология содержит fruits
  fruitsHaveBeneficiaries: boolean;      // Gate 5a: каждый fruit имеет named beneficiary

  // Phase 3
  forcesTableComplete: boolean;          // Gate 6: 3-8 сил с A,R,S,L,E scored
  differentialComputed: boolean;         // Gate 7: D вычислен
  atLeast2Maneuvers: boolean;            // Gate 8: ≥2 candidate maneuvers
  bothPathsRun: boolean;                 // Gate 9: Path A и Path B оба выполнены
  convergenceDivergenceDiagnosed: boolean; // Gate 9a: для каждого divergent point есть diagnosis

  // Phase 4
  atLeast3FruitsProjected: boolean;      // Gate 10: ≥3 fruits с named beneficiaries
  atLeast5FalsifiableIndicators: boolean; // Gate 11: ≥5 индикаторов с конкретными датами
  divergenceInTree: boolean;             // Gate 12: divergence branches в дереве

  // Output
  chatSummaryUnder25Lines: boolean;      // Gate 13: chat summary ≤25 lines
  archiveEntryComplete: boolean;         // Gate 14: все фазы в archive
}

// Если ЛЮБОЙ gate = false → analysis status = DRAFTED (не PUBLISHED)
// Gates 2-5, 6-9, 10-12 — по фазам. Можно частично публиковать при failed non-critical gates
```

**Gate severity:**
- **BLOCKER** (failed → DRAFTED): 1, 2, 5, 6, 9, 11, 13
- **WARNING** (failed → DRAFTED, но можно override): 3, 4, 7, 8, 10, 12, 14
- **INFO** (failed → пометка, не блокирует): 1a, 5a, 9a

---

## 5. Auto-Escalation Triggers (формализованные)

Текущее описание: «Topic in active I&W watchlist / owner's top-3 / 2+ misses / high stakes». Формализуем:

```typescript
interface AutoEscalationConfig {
  // Trigger: I&W watchlist
  watchlistBoost: {
    enabled: true,
    depthBoost: 1,            // если тема в watchlist → depth +1
    checkFunction: "checkTopicInWatchlist(topic)" // mlog: kv_get("iw_" + slug)
  },

  // Trigger: owner priority
  ownerPriorityBoost: {
    enabled: true,
    depthBoost: 1,            // если в top-3 owner интересов → depth +1
    checkFunction: "checkOwnerPriority(topic)"    // mlog: kv_get("owner_priority_3")
  },

  // Trigger: historical misses
  missEscalation: {
    enabled: true,
    missCountThreshold: 2,    // ≥2 misses на похожую тему
    depthBoost: 1,
    checkFunction: "checkHistoricalMisses(topic)"  // SQL: SELECT COUNT(*) FROM Analysis WHERE topic LIKE %topic% AND status IN ('MISSED','PARTIAL')
  },

  // Trigger: high stakes flag
  highStakesBoost: {
    enabled: true,
    depthBoost: 2,            // high stakes → depth +2 (major jump)
    checkFunction: "checkHighStakes(topic)"        // mlog: contains(t,"критич") or contains(t,"existential") or kv_get("high_stakes_" + slug)
  },

  // Trigger: consecutive low-confidence
  lowConfidenceEscalation: {
    enabled: true,
    threshold: 2,             // 2 подряд LOW confidence анализа
    depthBoost: 1,
    checkFunction: "checkConsecutiveLowConfidence()"  // SQL on recent analyses
  },

  // Hard ceiling
  maxDepth: 4,                // depth не может быть >4 даже с boost'ами
}
```

---

## 6. API Endpoints

### Внутренние (mlog → llm_proxy → Prisma)

| Method | Endpoint | Описание | Params |
|--------|----------|----------|--------|
| POST | `/osp/analyze` | Запустить анализ | `{topic, depth?, domain?}` |
| POST | `/osp/quick` | Quick analysis (depth 0) | `{topic}` |
| POST | `/osp/wargame` | Wargame (depth 2) | `{topic}` |
| POST | `/osp/deep` | Deep (depth 3) | `{topic}` |
| POST | `/osp/full` | Full intel (depth 4) | `{topic, owner_approved: true}` |
| GET | `/osp/archive` | Список анализов | `?status=Published&domain=financial&limit=20` |
| GET | `/osp/archive/:id` | Полный анализ | — |
| POST | `/osp/verify/:id` | Верифицировать прогноз | `{actualOutcome}` |
| GET | `/osp/score` | Brier + calibration | `?period=12m` |
| POST | `/osp/watch/:id` | Поставить на наблюдение | `{frequency?}` |
| DELETE | `/osp/watch/:id` | Снять с наблюдения | — |
| POST | `/osp/bet` | Зарегистрировать ставку | `{thesis, probability, downside, upside}` |
| GET | `/osp/regime` | Macro regime snapshot | — |
| POST | `/osp/redteam/:id` | Red-team анализ | `{focusArea?}` |
| GET | `/osp/indicators/due` | Индикаторы к проверке | `?before=2026-09-01` |

### Telegram posting (auto)

| Trigger | Channel | Format |
|---------|---------|--------|
| analysis PUBLISHED | `ARCHIVE_CHANNEL_ID` | chat summary + #осп #прогноз #YYYY #тема_<slug> |
| indicator DUE in 7d | `OWNER_CHAT_ID` | reminder: «Индикатор X от анализа Y проверяется через 7 дней» |
| analysis VERIFIED | `ARCHIVE_CHANNEL_ID` | result: ✅/❌ + Brier delta + brief diagnosis |
| monthly recalibration | `OWNER_CHAT_ID` | calibration curve summary + top 3 improvements |

**Required env vars:**
```
ARCHIVE_CHANNEL_ID=<telegram_channel_id>
OWNER_CHAT_ID=<owner_telegram_id>
OSP_SCHEDULER_ENABLED=true
```

---

## 7. Scheduler Integration

| Job | Cron | Описание | Implementation |
|-----|------|----------|----------------|
| Daily watch sweep | `0 9 * * *` (09:00 MSK) | Проверка watched indicators | SQL: indicators WHERE verifyDate <= now + 7d AND preVerifyReminderSent = false |
| Indicator pre-verify | `-7d before verifyDate` | Reminder за 7 дней | POST to OWNER_CHAT_ID |
| Indicator verify | `at verifyDate` | Проверить факт vs прогноз | Manual trigger + auto Tavily search |
| Monthly recalibration | `0 10 1 * *` (1-е число, 10:00) | Brier + calibration review | SQL: BrierScoreLog WHERE date within last month |
| Quarterly methodology review | `0 10 1 1,4,7,10 *` | Methodology + skills review | Flag for owner |
| Semi-annual arsenal review | `0 10 1 1,7 *` | Arsenal review | Flag for owner |

---

## 8. Output JSON Schemas

### Chat Summary Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "id": {"type": "string"},
    "topic": {"type": "string"},
    "forecast": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "scenario": {"type": "string"},
          "probability": {"type": "string"},
          "kentLabel": {"type": "string"}
        }
      }
    },
    "fruitsRipening": {
      "type": "object",
      "properties": {
        "near": {"type": "array", "items": {"type": "string"}},
        "far": {"type": "array", "items": {"type": "string"}}
      }
    },
    "costsWhoPays": {
      "type": "object",
      "properties": {
        "near": {"type": "array", "items": {"type": "string"}},
        "far": {"type": "array", "items": {"type": "string"}}
      }
    },
    "indicators": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "date": {"type": "string", "format": "date"},
          "observable": {"type": "string"}
        }
      }
    },
    "confidence": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
    "verifyDate": {"type": "string", "format": "date"}
  }
}
```

### Forces & Potentials Schema

```json
{
  "type": "object",
  "properties": {
    "question": {"type": "string"},
    "forces": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "position": {"type": "string", "enum": ["pro", "anti", "distorts", "tactical_anti", "orthogonal"]},
          "A": {"type": "integer", "minimum": 1, "maximum": 10},
          "R": {"type": "integer", "minimum": 1, "maximum": 10},
          "S": {"type": "integer", "minimum": 1, "maximum": 10},
          "L": {"type": "integer", "minimum": 1, "maximum": 10},
          "E": {"type": "number", "minimum": 0.2, "maximum": 1.5},
          "P": {"type": "number"},
          "notes": {"type": "string"}
        }
      }
    },
    "differential": {
      "type": "object",
      "properties": {
        "pPro": {"type": "number"},
        "pAnti": {"type": "number"},
        "D": {"type": "number"},
        "ratio": {"type": "number"},
        "interpretation": {"type": "string", "enum": ["decisive", "trending", "contested"]}
      }
    }
  }
}
```

---

## 9. Error Categories & Fallback Strategy

### Error taxonomy (при MISS/PARTIAL)

| Category | Код | Описание | Fallback |
|----------|-----|----------|----------|
| Wrong scoring | `WRONG_SCORING` | Компонент A/R/S/L/E оценен неверно | Пересчитать с актуальными данными, добавить в calibration bias log |
| Missed force | `MISSED_FORCE` | Сила не была включена в анализ | Auto-trigger red-team на анализе, обновить domain KB |
| Missed time evolution | `MISSED_TIME_EVOLUTION` | E-modifier не учёл деградацию/усиление | Усилить E projection в методологии, добавить к quarterly review |
| Wrong model | `WRONG_MODEL` | Path A/B обе ошиблись | Фундаментальный пересмотр, bi-annual paradigm review |
| Premature convergence | `PREMATURE_CONVERGENCE` | Paths A и B сошлись, но оба ошиблись | Добавить Path C (adversarial/contrarian), усилить red-team |
| Missed cross-country spillover | `MISSED_SPILLOVER` | Belarus-тип ошибки: не проверены связанные экономики | Авто-активация narrative-vs-flows с cross-country forced |
| Indicator too vague | `VAGUE_INDICATOR` | Индикатор не бинарный или без даты | Пересоздать индикаторы, добавить к methodology review |
| Other | `OTHER` | Не классифицировано | Ручной разбор, добавить к quarterly review |

### Fallback actions при MISS

```
on ANALYSIS_MISSED:
  1. Log error category + diagnosis
  2. If category == MISSED_FORCE or PREMATURE_CONVERGENCE:
       auto-trigger /redteam on this analysis
  3. If category == MISSED_SPILLOVER:
       flag for mandatory cross-country check in future analyses of this domain
  4. Increment miss count for this topic domain
  5. If miss count for domain ≥ 3 in 90 days:
       auto-escalate to quarterly methodology review (early)
  6. Create learning entry in BrierScoreLog
```

---

## 10. Конфигурация окружения

### Required env vars

```env
# LLM
ANTHROPIC_API_KEY=<key>
OPENAI_API_KEY=<key>                    # fallback
OSP_DEFAULT_DEPTH=1                     # если не указан
OSP_MAX_DEPTH=4                         # hard ceiling

# Database
DATABASE_URL=postgresql://...            # Prisma

# Telegram
ARCHIVE_CHANNEL_ID=<channel_id>         # auto-post published analyses
OWNER_CHAT_ID=<owner_id>                # reminders, monthly reports
OSP_TELEGRAM_POSTING=true               # включить auto-post

# Scheduler
OSP_SCHEDULER_ENABLED=true
REDIS_URL=redis://...                    # для scheduler (BullMQ)

# News
TAVILY_API_KEY=<key>                    # для свежих новостей
NEWS_API_KEY=<key>                      # альтернативный источник

# Knowledge Lab integration
KNOWLEDGE_LAB_API=http://127.0.0.1:4000/api/knowledge

# Models
OSP_MODEL_DEPTH_0=claude-3-5-haiku
OSP_MODEL_DEPTH_1=claude-sonnet-4-20250514
OSP_MODEL_DEPTH_2=claude-sonnet-4-20250514
OSP_MODEL_DEPTH_3=claude-opus-4-20250514
OSP_MODEL_DEPTH_4=claude-opus-4-20250514
```

### Prisma migration command
```bash
npx prisma migrate dev --name osp_analysis_enriched
```

---

## 11. Integration points с другими отделами

| Отдел | Integration | Направление | Протокол |
|-------|------------|-------------|----------|
| Яна (Управление) | Routing decisions | Яна → ОСП | Если Яна определяет, что запрос стратегический → route to ОСП |
| Эксперт | Combat questions | Эксперт → ОСП | Эксперт генерирует вопросы для встречи; ОСП обогащает их strategic context |
| Финансы | Cashflow forecasts | ОСП ↔ Финансы | ОСП даёт macro regime; Финансы даёт cashflow constraints |
| Юрист | Risk assessment | ОСП → Юрист | ОСП даёт strategic risks; Юрист даёт legal exposure |
| Лаборатория знаний | Knowledge artifacts | ОСП ↔ ЛЗ | ОСП даёт analysis insights; ЛЗ даёт emerging tech data |
| Scheduler | Cron jobs | ОСП → Scheduler | Регистрация indicator checks, watch sweeps, recalibration |

---

## 12. Контрольный чеклист: все ли проектные параметры покрыты

| # | Параметр | Статус | Где |
|---|----------|--------|-----|
| 1 | Prisma-схема Analysis | ✅ Определена | Секция 1 |
| 2 | Токен-бюджеты per phase | ✅ Определены | Секция 2 |
| 3 | Модельные конфиги per depth | ✅ Определены | Секция 3 |
| 4 | Quality gates (программные) | ✅ Определены | Секция 4 |
| 5 | Auto-escalation triggers | ✅ Формализованы | Секция 5 |
| 6 | API endpoints | ✅ Определены | Секция 6 |
| 7 | Telegram integration | ✅ Определена | Секция 6 |
| 8 | Scheduler integration | ✅ Определена | Секция 7 |
| 9 | JSON schemas (output) | ✅ Определены | Секция 8 |
| 10 | Error categories + fallback | ✅ Определены | Секция 9 |
| 11 | Env vars / конфиг | ✅ Определены | Секция 10 |
| 12 | Cross-dept integration | ✅ Определены | Секция 11 |

---

**Следующий шаг:** внедрить эти параметры в osp.mlog (токен-бюджеты, модельные конфиги, quality gates, auto-escalation) и обновить osp.md профиль.
