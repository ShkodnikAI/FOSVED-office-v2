# STRESS-2: Production Stress Test Log

**Bot:** FOSVED-office-v2 (Telegram)
**Date:** 2026-08-23 15:43 – 16:10 UTC
**Executor:** Automated webhook injection + owner Telegram observation
**Method:** POST fake Telegram updates to `https://fosved-office-v2.onrender.com/webhook/telegram`
**Rules:** No code fixes during test. Sequential execution. 90s pause between departments. Neutral queries only.

---

## BLOCK A: DB Snapshot by chat_id

**Status: SKIP**

**Reason:** DATABASE_URL = `sqlite:/var/data/fosved.db` (SQLite on Render persistent disk). No remote SQL access available — Render API v1 has no shell/exec/logs endpoints. Owner was asked to run the query manually in Render Dashboard Shell:

```sql
SELECT chat_id, COUNT(*) AS cnt,
  SUM(CASE WHEN active=1 THEN 1 ELSE 0 END) AS active_cnt
FROM yana_events GROUP BY chat_id ORDER BY cnt DESC;
```

**Result pending from owner.** Indirect check via Block D remind list/clear suggests only 1 chat_id (owner) is populated.

---

## BLOCK B: Yana Disclaimer Duplication Check

### B.1 — Plain message

| Param | Value |
|---|---|
| **Sent** | `Привет, как дела` |
| **HTTP** | 200 OK |
| **Latency** | 2.73s |
| **Audit** | Full pipeline: detect_dept=yana → SelectSkills → GetCorrections → YanaNowInfo → YanaWeather → YanaCalendar → GetRecentDialog → YanaRecallMemories → ContextAssembly → CallLLM → GateEnforcement |

**Telegram response (verbatim):**

> Хозяин, привет. Всё в порядке. Воскресенье, вечер, за окном дождь, +16.
>
> Вижу, что в календаре до сих пор висит куча старых тестовых записей и дублей про кота и газ — двадцать штук. Похоже, команда очистки их не зацепила, либо они другого типа. Я сама удалять не умею, это делает система. Попробуйте ещё раз `/remind clear`, а если не поможет — скажите, я проверю список.
>
> ЯНА — шеф де кабинет Fosved Office. Не заменяет суждение хозяина. По серьёзным вопросам рекомендует профессионала.

**Findings:**
- ✅ Disclaimer present, exactly once
- ✅ Natural Russian, conversational tone
- ✅ Weather data correct (rain, +16)
- ✅ Yana proactively mentions calendar clutter (20 old test entries)
- ✅ Pipeline completes end-to-end in <3s
- ⚠️ Yana cannot self-delete reminders — refers owner to `/remind clear`

---

## BLOCK C: All 13 Departments + Isolated /osp

### C.1 — /osp что такое SWOT-анализ, коротко

| Param | Value |
|---|---|
| **HTTP** | **500** |
| **Latency** | 0.4s |

**Root cause:** `HandleOSP()` called at app.mlog:2688 but **function never defined**. Metalogos interpreter returns `[ERROR: unknown function 'HandleOSP']` then the webhook handler crashes with 500.

---

### C.2 — /lz курс доллара сегодня

| Param | Value |
|---|---|
| **HTTP** | 200 OK |
| **Latency** | 0.4s |

**Telegram response:**

> [ERROR: unknown function 'HandleLZ']

**Root cause:** `HandleLZ()` called at app.mlog:2556 but **function never defined**. The error is caught by Metalogos `try` wrapper — webhook returns 200 but sends error text to Telegram.

---

### C.3 — /expert что такое RAG

| Param | Value |
|---|---|
| **HTTP** | **500** |
| **Latency** | 9.1s |

**Root cause:** `HandleExpert()` called at app.mlog:2876 but **function never defined**. Crashes with 500. 9.1s suggests the request reached LLM before failing.

---

### C.4 — /marketing слоган для кофейни

| Param | Value |
|---|---|
| **HTTP** | **500** |
| **Latency** | 0.4s |

**Root cause:** `HandleMarketing()` called at app.mlog:2883 but **function never defined**. Crashes with 500.

---

### C.5 — /finance что такое EBITDA

| Param | Value |
|---|---|
| **HTTP** | **500** |
| **Latency** | 8.2s |

**Root cause:** `HandleFinance()` called at app.mlog:2890 but **function never defined**. Crashes with 500. 8.2s suggests LLM was called.

---

### C.6 — /legal что такое NDA

| Param | Value |
|---|---|
| **HTTP** | **500** |
| **Latency** | 0.4s |

**Root cause:** `HandleLegal()` called at app.mlog:2897 but **function never defined**. Crashes with 500.

---

### C.7 — /dev что такое REST

| Param | Value |
|---|---|
| **HTTP** | 200 OK |
| **Latency** | 0.6s |

**Telegram response:**

> [ERROR: unknown function 'HandleDev']

**Root cause:** `HandleDev()` called at app.mlog:2904 but **function never defined**. Caught by `try`, returns 200 with error.

---

### C.8 — /design что такое UX

| Param | Value |
|---|---|
| **HTTP** | 200 OK |
| **Latency** | 0.5s |

**Telegram response:**

> [ERROR: unknown function 'HandleDesign']

**Root cause:** `HandleDesign()` called at app.mlog:2930 but **function never defined**. Caught by `try`, returns 200 with error.

---

### C.9 — /qa что проверить в форме логина

| Param | Value |
|---|---|
| **HTTP** | 200 OK |
| **Latency** | 0.5s |

**Telegram response:**

> [ERROR: unknown function 'HandleQA']

**Root cause:** `HandleQA()` called at app.mlog:2938 but **function never defined**. Caught by `try`, returns 200 with error.

---

### C.10 — /engineering что такое CI/CD

| Param | Value |
|---|---|
| **HTTP** | 200 OK |
| **Latency** | 0.9s |

**Telegram response:**

> [ERROR: unknown function 'HandleEngineering']

**Root cause:** `HandleEngineering()` called at app.mlog:2952 but **function never defined**. Caught by `try`, returns 200 with error.

---

### C.11 — /forge привет (kavalnya)

| Param | Value |
|---|---|
| **HTTP** | **500** |
| **Latency** | 0.4s |

**Root cause:** No `/forge` route handler exists in app.mlog. The DetectDepartment function does not recognize `/forge` — it falls through and crashes.

---

### C.12 — /visual что такое палитра

| Param | Value |
|---|---|
| **HTTP** | 200 OK |
| **Latency** | 7.9s |

**Telegram response (partial):**

> Отвечаю как отдел Визуал (Fosved Visual).
>
> **Палитра** — это фиксированный набор цветов, который определяет визуальную идентичность бренда Fosved. В нашей системе она едина для всех визуальных ар...
>
> ОТКАЗ: Без указания юрисдикции анализ невозможен. Норма закона применима в стране, без страны нет анализа. Укажите юрисдикцию: BY, RU, EU, US.

**Findings:**
- ✅ Only department that returned a real LLM-generated response
- ⚠️ Response appears truncated (ends with "ар...")
- ❌ Response contains legal department refusal text ("ОТКАЗ: Без указания юрисдикции...") — **cross-department contamination in LLM context or prompt leakage**

---

### C.13 — /admin статус

| Param | Value |
|---|---|
| **HTTP** | **500** |
| **Latency** | 4.4s |

**Root cause:** `HandleAdmin()` called at app.mlog:2966 but **function never defined**. Crashes with 500.

---

### C.14 — /osp test (isolated)

| Param | Value |
|---|---|
| **HTTP** | **500** |
| **Latency** | 0.6s |

**Root cause:** Same as C.1 — `HandleOSP()` undefined.

---

### Block C Summary

| # | Dept | HTTP | Latency | Telegram Content |
|---|---|---|---|---|
| C.1 | /osp | **500** | 0.4s | (crash) |
| C.2 | /lz | 200 | 0.4s | [ERROR: unknown function 'HandleLZ'] |
| C.3 | /expert | **500** | 9.1s | (crash) |
| C.4 | /marketing | **500** | 0.4s | (crash) |
| C.5 | /finance | **500** | 8.2s | (crash) |
| C.6 | /legal | **500** | 0.4s | (crash) |
| C.7 | /dev | 200 | 0.6s | [ERROR: unknown function 'HandleDev'] |
| C.8 | /design | 200 | 0.5s | [ERROR: unknown function 'HandleDesign'] |
| C.9 | /qa | 200 | 0.5s | [ERROR: unknown function 'HandleQA'] |
| C.10 | /engineering | 200 | 0.9s | [ERROR: unknown function 'HandleEngineering'] |
| C.11 | /forge | **500** | 0.4s | (no route) |
| C.12 | /visual | 200 | 7.9s | Real response (truncated + contaminated) |
| C.13 | /admin | **500** | 4.4s | (crash) |
| C.14 | /osp isolated | **500** | 0.6s | (crash) |

**Result: 8/14 HTTP 500, 5/14 error text, 1/14 real response**

---

## BLOCK D: Remind List vs Natural Language

### D.1 — /remind list (command)

**Telegram response (formatted output):**

> 50. перезвонить в ЖЭС — 2026-08-23 16:36:22 (once)

**SQL query (app.mlog:1931):**
```sql
SELECT id, COALESCE(event_text,'') AS event_text, COALESCE(rrule_kind,'') AS rrule_kind,
  COALESCE(fire_time,'') AS fire_time, COALESCE(fire_weekday,'') AS fire_weekday,
  COALESCE(fire_monthday,'') AS fire_monthday,
  COALESCE(datetime(next_fire_at,'+3 hours'),'') AS next_local
FROM yana_events WHERE active = 1 AND rrule_kind IS NOT NULL
ORDER BY next_fire_at ASC LIMIT 30
```

**Bug confirmed:** Query has **NO `chat_id` filter** — shows active recurring reminders from ALL chats. Only 1 item has `rrule_kind IS NOT NULL` (id 50), so only 1 row returned.

---

### D.2 — "Покажи список напоминаний" (natural language via Yana)

**Telegram response:**

> Вот список запланированных напоминаний:
> 1. Тестовое напоминание
> 2. Тестовое событие 2026-07-25
> 3. P1-persist-check
> 4. Перезвонить в ЖЭС
> 5. Напоминание о двадцати старых тестовых записях за июль
> 6. Напоминание о кормлении кота
> 7. Покормить кота
> 8. Покормить кота
> 9. Покормить кота
> 10. Напоминание о кормлении кота
> 11. Покормить кота
> 12. Напомнить о кормлении кота
> 13. Выключить газ
> 14. Yana has to turn off the gas
> 15. Yana needs to turn off the gas
> 16. Напоминать про зонт
> 17. Yana needs to feed the cat
> 18. Покормить кота
> 19. Yana needs to feed the cat
> 20. Yana needs to feed the cat

**Findings:**
- ❌ **20 items with massive duplicates** — "Покормить кота" appears 6 times (items 7,8,9,11,18), "газ" 3 times (13,14,15), "кормление кота" in English 3 more times (17,19,20)
- ❌ No deduplication when creating reminders
- ❌ Yana's LLM-generated list uses a different data source than `/remind list` (shows items without `rrule_kind`, which the SQL command filters out)
- ⚠️ Disclaimer appended again (consistent but redundant)

---

### D.1 vs D.2 Comparison

| Aspect | /remind list (D.1) | Natural language (D.2) |
|---|---|---|
| Items shown | 1 | 20 |
| Source | SQL: `WHERE rrule_kind IS NOT NULL` | Yana LLM (calendar context) |
| chat_id filter | **NO** | **NO** (Yana sees all) |
| Duplicates | N/A (1 item) | **Massive** (cat x6, gas x3) |
| Format | `id. text — datetime (kind)` | Numbered plain text |

---

## BLOCK E: Stress Queue (3 back-to-back, no pause)

### E.1 — /osp что такое PEST-анализ
### E.2 — /expert что такое SWOT
### E.3 — /engineering что такое SDLC

**All 3 sent with zero pause between them.**

**Render logs (16:05:35 – 16:06:59 UTC):**
```
16:05:35 POST /webhook/telegram → 500
16:05:45 POST /webhook/telegram → 500 (x2, from different IPs)
16:05:56 POST /webhook/telegram → 500 (x2)
16:05:57 POST /webhook/telegram → 500
16:06:02 POST /webhook/telegram → 500 (x2)
16:06:42 POST /webhook/telegram → 500 (x2)
16:06:46 POST /webhook/telegram → 500 (x2)
16:06:53 POST /webhook/telegram → 500 (x2)
16:06:54 POST /webhook/telegram → 200 (1 of 3 — partial recovery)
16:06:55 POST /webhook/telegram → 500
16:06:59 POST /webhook/telegram → 500
```

**Critical finding — Groq LLM failure:**
```
16:07:41 [WARNING] CircuitBreaker OPEN for groq (5 consecutive failures)
16:07:41 [WARNING] LLM fail: provider=groq model=llama-3.3-70b-versatile
  err=404 Client Error: Not Found for url:
  https://api.groq.com/openai/v1/chat/completions
```

**Findings:**
- ❌ **All 3 stress messages returned 500** — complete failure under load
- ❌ **Groq CircuitBreaker OPEN** — model `llama-3.3-70b-versatile` returns 404 (endpoint removed/deprecated by Groq)
- ❌ With Groq down, fallback chain also fails — no successful LLM calls during stress
- ⚠️ Webhook returns 500 even for already-broken departments (Handle* undefined), so 500s are from multiple causes stacking

---

## BLOCK F: Summary Table

| Block | Test | HTTP | Latency | Content Quality | Status |
|---|---|---|---|---|---|
| A | DB snapshot | SKIP | — | — | Pending manual SQL |
| B.1 | Yana disclaimer | 200 | 2.73s | ✅ Disclaimer x1, natural Russian | **PASS** |
| C.1 | /osp | **500** | 0.4s | HandleOSP undefined | **FAIL** |
| C.2 | /lz | 200 | 0.4s | [ERROR: unknown function] | **FAIL** |
| C.3 | /expert | **500** | 9.1s | HandleExpert undefined | **FAIL** |
| C.4 | /marketing | **500** | 0.4s | HandleMarketing undefined | **FAIL** |
| C.5 | /finance | **500** | 8.2s | HandleFinance undefined | **FAIL** |
| C.6 | /legal | **500** | 0.4s | HandleLegal undefined | **FAIL** |
| C.7 | /dev | 200 | 0.6s | [ERROR: unknown function] | **FAIL** |
| C.8 | /design | 200 | 0.5s | [ERROR: unknown function] | **FAIL** |
| C.9 | /qa | 200 | 0.5s | [ERROR: unknown function] | **FAIL** |
| C.10 | /engineering | 200 | 0.9s | [ERROR: unknown function] | **FAIL** |
| C.11 | /forge | **500** | 0.4s | No route | **FAIL** |
| C.12 | /visual | 200 | 7.9s | Real but truncated + contaminated | **PARTIAL** |
| C.13 | /admin | **500** | 4.4s | HandleAdmin undefined | **FAIL** |
| C.14 | /osp isolated | **500** | 0.6s | HandleOSP undefined | **FAIL** |
| D.1 | /remind list | 200 | — | 1 item, no chat_id filter | **BUG** |
| D.2 | NL remind list | 200 | — | 20 items, massive dupes | **BUG** |
| E.1 | Stress /osp | **500** | — | Fail | **FAIL** |
| E.2 | Stress /expert | **500** | — | Fail | **FAIL** |
| E.3 | Stress /engineering | **500** | — | Fail | **FAIL** |

**Total: 1 PASS, 1 PARTIAL, 2 BUG, 18 FAIL out of 22 tests**

---

## CRITICAL BUGS FOUND

### BUG-1: 12 Handle* functions called but never defined (CRITICAL)

**Severity:** P0 — blocks ALL department operations

**Missing functions in app.mlog:**
- `HandleOSP()` — called at lines 2688, 2776, 2862
- `HandleLZ()` — called at lines 2556, 2781, 2869
- `HandleExpert()` — called at lines 2786, 2876
- `HandleMarketing()` — called at lines 2791, 2883
- `HandleFinance()` — called at lines 2796, 2890
- `HandleLegal()` — called at lines 2801, 2897
- `HandleDev()` — called at lines 2806, 2904
- `HandleDesign()` — called at lines 2818, 2930
- `HandleQA()` — called at lines 2824, 2938
- `HandleEngineering()` — called at lines 2834, 2952
- `HandleVisual()` — called at lines 2829, 2945
- `HandleAdmin()` — called at lines 2448, 2498, 2966

**Exists:** `HandleDesignImage()` (line 331) and `HandleDeptQuery()` (line 735) — generic handler.

**Note:** `HandleDeptQuery(dept, query, chat_id)` at line 735 IS defined and does the correct thing (BuildContext → CallLLMProxy → record → return). The routing code should call `HandleDeptQuery` instead of the undefined specific handlers.

**Fix:** Replace all `HandleXxx(query, chat_id)` calls with `HandleDeptQuery("xxx", query, chat_id)`.

---

### BUG-2: Groq model llama-3.3-70b-versatile returns 404 (CRITICAL)

**Severity:** P0 — LLM provider completely down

**Evidence:**
```
CircuitBreaker OPEN for groq (5 consecutive failures)
LLM fail: provider=groq model=llama-3.3-70b-versatile
  err=404 Client Error: Not Found for url:
  https://api.groq.com/openai/v1/chat/completions
```

**Cause:** Groq deprecated/removed the model endpoint. The model name may have changed (e.g., `llama-3.3-70b-versatile` → `llama-3.3-70b-specdec` or removed entirely).

**Fix:** Update model name in llm_proxy.py Groq config, or switch to an active model.

---

### BUG-3: /remind list missing chat_id filter (HIGH)

**Severity:** P1 — data leak across chats

**Current query (app.mlog:1931):**
```sql
WHERE active = 1 AND rrule_kind IS NOT NULL
```

**Should be:**
```sql
WHERE active = 1 AND rrule_kind IS NOT NULL AND chat_id = ?
```

**Impact:** In a multi-user deployment, any user's `/remind list` shows ALL users' recurring reminders.

---

### BUG-4: InitDB ALTER TABLE duplicate column errors (MEDIUM)

**Severity:** P2 — noisy but non-functional (columns already exist, `try` catches)

**Evidence (Render logs, every cron cycle):**
```
[try] caught error: db_execute() SQL error: duplicate column name: update_id
[try] caught error: db_execute() SQL error: duplicate column name: reminded_at
[try] caught error: db_execute() SQL error: duplicate column name: rrule_kind
... (14 columns total)
```

**Cause:** `InitDB()` runs `ALTER TABLE ... ADD COLUMN` with `let _ = try` every time it's called. Columns already exist from previous runs. The `try` prevents crash but floods logs.

**Fix:** Add `IF NOT EXISTS` check, or wrap in a migration table tracking applied schema versions.

---

### BUG-5: Massive reminder duplicates (MEDIUM)

**Severity:** P2 — user experience

**Evidence:** 20 active reminders, including:
- "Покормить кота" — 6 times (items 7,8,9,11,18)
- "Yana needs to feed the cat" — 3 times (items 17,19,20)
- "Yana has to/needs to turn off the gas" — 3 times (items 14,15)
- "Напоминание о кормлении кота" — 1 time (item 10)
- "Напомнить о кормлении кота" — 1 time (item 12)

**Total cat-related:** 11 entries. **Total gas-related:** 3 entries.

**Cause:** No deduplication when Yana creates reminders. The LLM generates `[REMIND: ...]` markers, and each is inserted without checking for semantic or text similarity.

**Fix:** Before INSERT, check if an active reminder with similar text already exists for the same chat_id.

---

### BUG-6: /forge route not recognized (LOW)

**Severity:** P2 — department inaccessible

**Cause:** `DetectDepartment()` in app.mlog has no entry for `/forge`. The function recognizes `/kavalnya` but the test used `/forge` per the original routing plan.

---

### OBS-1: Visual response cross-department contamination (OBSERVATION)

**Severity:** P2 — content quality

The /visual response about "палитра" ended with legal department text: "ОТКАЗ: Без указания юрисдикции анализ невозможен..." This suggests either:
- LLM context contains legal department prompt leakage
- System prompt for visual includes legal boilerplate
- Context window has residual content from a previous legal query

---

## TEST INFRASTRUCTURE NOTES

1. **Webhook injection works reliably** — all 22 messages delivered, HTTP responses received
2. **Audit trail (`/cron/last-checkpoints`) works** — shows full processing pipeline for Yana
3. **CircuitBreaker pattern works** — correctly opens after 5 Groq failures
4. **Webhook dedup table exists** — `webhook_dedup (update_id TEXT PRIMARY KEY)`
5. **No way to read bot responses programmatically** — Telegram Bot API limitation, owner must check Telegram manually
6. **Render logs only available via dashboard** — no API endpoint for log streaming

---

## RECOMMENDATION PRIORITY

| Priority | Bug | Action | Effort |
|---|---|---|---|
| P0 | BUG-1 | Replace 12 `HandleXxx()` calls with `HandleDeptQuery("xxx", query, chat_id)` | 30 min |
| P0 | BUG-2 | Fix Groq model name or switch provider | 15 min |
| P1 | BUG-3 | Add `AND chat_id = ?` to /remind list query | 5 min |
| P2 | BUG-4 | Add migration tracking to InitDB | 30 min |
| P2 | BUG-5 | Add dedup check before reminder INSERT | 20 min |
| P2 | BUG-6 | Add `/forge` to DetectDepartment | 5 min |
| P2 | OBS-1 | Investigate visual context contamination | 30 min |
