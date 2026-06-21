# НАРЯД №30: Apodex — верифицированный deep research для ЛЗ

**Репо:** https://github.com/ShkodnikAI/FOSVED-office-v2
**Справочник:** METALOGOS_REFERENCE.md
**Результат:** `/lz deep <запрос>` → Apodex верифицированный анализ с графом доказательств

---

## ЧТО ТАКОЕ APODEX

Apodex 1.0 — verification-centric deep research агент от Apodex AI:
- Оркестрирует до 150 суб-агентов параллельно
- Каждый факт верифицируется перед включением в ответ
- Аудитируемый граф доказательств (evidence graph)
- OpenAI-совместимый API (chat-completions)
- Платформа: https://platform.apodex.ai

---

## ЧАСТЬ 1: Добавить Apodex как 7-й провайдер

### 1.1. В маршрутизатор моделей

Обновить таблицу провайдеров:

| # | Провайдер | Модели | Endpoint | Env key |
|---|---|---|---|---|
| 1 | Z.ai (GLM) | glm-4.6, glm-5.1 | https://api.z.ai/api/coding/paas/v4 | ZAI_API_KEY |
| 2 | DeepSeek | deepseek-chat, deepseek-reasoner | https://api.deepseek.com/v1 | DEEPSEEK_API_KEY |
| 3 | Groq | llama-3.3-70b-versatile | https://api.groq.com/openai/v1 | GROQ_API_KEY |
| 4 | xAI (Grok) | grok-3, grok-3-mini | https://api.x.ai/v1 | GROK_API_KEY |
| 5 | Anthropic | claude-sonnet-4-20250514 | https://api.anthropic.com/v1/messages | ANTHROPIC_API_KEY |
| 6 | OpenAI | gpt-4o, gpt-4o-mini | https://api.openai.com/v1 | OPENAI_API_KEY |
| **7** | **Apodex** | **apodex-1.0-mini, apodex-1.0** | **https://platform.apodex.ai/v1** | **APODEX_API_KEY** |

### 1.2. В proxy (llm_proxy.py)

Apodex использует OpenAI-совместимый формат. Добавить в provider routing:

```python
PROVIDER_CONFIG = {
    # ... существующие ...
    'apodex': {
        'base_url': 'https://platform.apodex.ai/v1',
        'key_env': 'APODEX_API_KEY',
        'format': 'openai',  # OpenAI-compatible
        'default_model': 'apodex-1.0-mini',
        'max_tokens': 16384,  # Apodex может генерировать длинные ответы
        'timeout': 300,  # 5 минут — deep research долгий
    }
}
```

### 1.3. В Metalogos call_llm (если напрямую)

В builtins.rs, секция OpenAI-compatible providers, добавить:

```rust
"apodex" => "https://platform.apodex.ai/v1",
```

Timeout увеличить до 300 секунд для apodex (deep research может занимать 2-5 минут).

### 1.4. Env

```
APODEX_API_KEY=...   # Получить на https://platform.apodex.ai
```

---

## ЧАСТЬ 2: Интеграция в ЛЗ

### 2.1. Три режима ЛЗ

```
/lz <запрос>          → обычный LLM (GLM/Claude) — быстрый ответ, 10 сек
/lz scan <запрос>     → DeepScan (9 источников) + LLM анализ — 30 сек
/lz deep <запрос>     → Apodex verified research — 2-5 мин, каждый факт проверен
```

### 2.2. Обработчик `/lz deep`

```mlog
if starts_with(text, "/lz deep ") then {
  let query = substring(text, 9, len(text))
  send_message(chat_id, "Запускаю deep research через Apodex. Это займёт 2-5 минут. Каждый факт будет верифицирован.")

  // Отправить typing indicator
  let token = env("TELEGRAM_BOT_TOKEN")
  http_post("https://api.telegram.org/bot" + token + "/sendChatAction",
    json_encode({ chat_id: to_float(chat_id), action: "typing" }),
    "application/json")

  // Построить промпт для Apodex
  let lz_profile = read_file("library/lz.md")
  let research_prompt = lz_profile + "\n\n"
    + "Ты работаешь в режиме deep research. Требования:\n"
    + "1. Найди минимум 10 независимых источников\n"
    + "2. Каждый факт верифицируй — укажи источник и степень доверия\n"
    + "3. Маркируй: [ФАКТ ✓verified], [ФАКТ ⚠unverified], [ИНТЕРПРЕТАЦИЯ], [СПЕКУЛЯЦИЯ]\n"
    + "4. Выяви противоречия между источниками\n"
    + "5. Построй timeline если применимо\n"
    + "6. Оцени disruption potential (1-10)\n"
    + "7. Укажи что НЕ удалось найти/проверить\n"
    + "8. Язык: русский\n"
    + "9. Формат: слои (как ОСП), с графом доказательств в конце"

  // Вызов Apodex (через провайдер)
  let apodex_key = env("APODEX_API_KEY")
  let result = call_llm_provider("apodex", apodex_key, "apodex-1.0-mini", research_prompt, query)

  // Отправить результат
  let _ = SendReport(result, "lz", "Deep Research: " + query, 4.0, chat_id)

  // Audit
  let _ = AuditLog("lz_deep_research", "system", "lz", query, "ok")
  return respond("200 ok")
}
```

### 2.3. Через proxy (альтернативный вариант)

Если call_llm_provider ещё не поддерживает Apodex — вызвать через proxy:

```mlog
if starts_with(text, "/lz deep ") then {
  let query = substring(text, 9, len(text))
  send_message(chat_id, "Запускаю Apodex deep research (2-5 мин)...")

  let body = json_encode({
    query: query,
    dept: "lz",
    provider: "apodex",
    model: "apodex-1.0-mini",
    max_tokens: 16384,
    chat_id: chat_id
  })
  let result = http_post("http://127.0.0.1:4000/lz/deep-research", body, "application/json")

  let parsed = parse_json(result)
  let answer = json_get(parsed, "response", "Ошибка deep research")
  let _ = SendReport(answer, "lz", "Deep Research: " + query, 4.0, chat_id)
  return respond("200 ok")
}
```

В proxy добавить endpoint:

```python
@app.route('/lz/deep-research', methods=['POST'])
def lz_deep_research():
    data = request.json
    query = data.get('query', '')
    chat_id = data.get('chat_id', '')

    # Typing indicator refresh (каждые 5 сек)
    import threading
    stop_typing = threading.Event()
    def typing_loop():
        while not stop_typing.is_set():
            send_chat_action(chat_id, 'typing')
            stop_typing.wait(5)
    t = threading.Thread(target=typing_loop, daemon=True)
    t.start()

    try:
        # Apodex API call
        apodex_key = os.environ.get('APODEX_API_KEY', '')
        lz_profile = load_library_prompt('lz')

        research_prompt = f"""{lz_profile}

Режим: deep research с верификацией.
1. Минимум 10 независимых источников
2. Каждый факт: [ФАКТ ✓verified] или [ФАКТ ⚠unverified]
3. Противоречия между источниками
4. Disruption potential (1-10)
5. Что НЕ удалось проверить
6. Язык: русский
"""

        response = requests.post(
            'https://platform.apodex.ai/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {apodex_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'apodex-1.0-mini',
                'max_tokens': 16384,
                'messages': [
                    {'role': 'system', 'content': research_prompt},
                    {'role': 'user', 'content': query}
                ]
            },
            timeout=300  # 5 минут
        )

        result = response.json()
        answer = result['choices'][0]['message']['content']

        # Audit
        log_audit('lz_deep_research', 'apodex', 'lz', query, 'ok')

        return jsonify({'response': answer, 'provider': 'apodex', 'verified': True})

    finally:
        stop_typing.set()
```

### 2.4. Typing indicator refresh

Deep research занимает 2-5 минут. Telegram убирает typing indicator через 5 секунд. Нужен periodic refresh:

**В proxy** (см. выше): threading loop с `sendChatAction` каждые 5 секунд.

**Или в app.mlog** (если proxy не используется): перед вызовом Apodex отправить промежуточное сообщение:

```mlog
send_message(chat_id, "Apodex исследует... Суб-агенты развёрнуты. Ожидайте 2-5 минут.")
```

---

## ЧАСТЬ 3: Формат ответа Apodex в Mini App

Ответ Apodex отличается от обычного LLM — он содержит evidence chain. Нужно отобразить:

### 3.1. Дополнительные бейджи

```css
.badge-verified { background: #059669; color: #fff; }  /* ✓ verified */
.badge-unverified { background: #d97706; color: #fff; } /* ⚠ unverified */
.badge-conflicting { background: #dc2626; color: #fff; } /* ✗ conflicting */
```

В FormatReportBody добавить парсинг:
```
[ФАКТ ✓verified]   → <span class="badge badge-verified">ФАКТ ✓</span>
[ФАКТ ⚠unverified] → <span class="badge badge-unverified">ФАКТ ⚠</span>
[КОНФЛИКТ]          → <span class="badge badge-conflicting">КОНФЛИКТ</span>
```

### 3.2. Секция "Граф доказательств" в отчёте

```html
<div class="evidence-section">
  <h2>Граф доказательств</h2>
  <div class="evidence-stats">
    <div class="ev-stat"><span class="ev-num">47</span><span class="ev-label">источников</span></div>
    <div class="ev-stat"><span class="ev-num">12</span><span class="ev-label">verified</span></div>
    <div class="ev-stat"><span class="ev-num">3</span><span class="ev-label">конфликты</span></div>
  </div>
  <div class="evidence-list">
    <div class="ev-item verified">
      <span class="ev-id">[S1]</span>
      <span class="ev-source">Nature, 2026</span>
      <span class="ev-status">✓ verified</span>
    </div>
    <div class="ev-item unverified">
      <span class="ev-id">[S2]</span>
      <span class="ev-source">Reddit r/quantum, user claim</span>
      <span class="ev-status">⚠ unverified</span>
    </div>
  </div>
</div>
```

CSS:
```css
.evidence-section { margin: 24px 0; }
.evidence-stats { display: flex; gap: 16px; margin: 12px 0; }
.ev-stat { text-align: center; }
.ev-num { display: block; font-size: 24px; font-weight: 700; color: #059669; }
.ev-label { font-size: 11px; color: #64748b; }
.ev-item { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; display: flex; gap: 8px; align-items: center; font-size: 13px; }
.ev-item.verified { border-left: 3px solid #059669; }
.ev-item.unverified { border-left: 3px solid #d97706; }
.ev-id { font-family: 'DM Mono', monospace; color: #94a3b8; }
.ev-source { flex: 1; }
.ev-status { font-size: 11px; font-weight: 600; }
```

### 3.3. Дополнительная кнопка для ЛЗ

В action bar отчёта ЛЗ (аналог ОСП-специфичных кнопок):

```html
<button class="action-btn primary" onclick="doAction('deeper_research')">Углубить Apodex</button>
<button class="action-btn" onclick="doAction('verify_source')">Перепроверить источник</button>
<button class="action-btn" onclick="doAction('track_topic')">На мониторинг</button>
```

**Углубить Apodex** — запускает Apodex повторно с предыдущим результатом как контекстом (refinement).

**Перепроверить источник** — владелец указывает какой факт перепроверить → Apodex фокусируется на одном утверждении.

**На мониторинг** — добавляет тему в `/lz_monitor` (ежедневный скан).

---

## ЧАСТЬ 4: Режим сравнения (LLM vs Apodex)

Для калибровки — можно запустить оба и сравнить:

```
/lz compare <запрос>

→ Параллельно:
  1. Обычный LLM (GLM/Claude) → быстрый ответ
  2. Apodex → верифицированный ответ

→ Результат: side-by-side в Mini App
  [LLM]                    [Apodex]
  3 факта без проверки     12 фактов, 10 verified
  Нет источников           47 источников
  10 секунд                3 минуты
```

```mlog
if starts_with(text, "/lz compare ") then {
  let query = substring(text, 12, len(text))
  send_message(chat_id, "Запускаю сравнение LLM vs Apodex...")

  // 1. Быстрый LLM
  let lz_profile = read_file("library/lz.md")
  let fast_result = TrackedLLM("lz", "dept", lz_profile, query)

  // 2. Apodex deep
  let apodex_key = env("APODEX_API_KEY")
  let deep_prompt = lz_profile + "\n\nDeep research с верификацией. Каждый факт: [ФАКТ ✓verified] или [ФАКТ ⚠unverified]."
  let deep_result = call_llm_provider("apodex", apodex_key, "apodex-1.0-mini", deep_prompt, query)

  // 3. Сравнение
  let comparison = "=== БЫСТРЫЙ LLM ===\n" + fast_result + "\n\n=== APODEX VERIFIED ===\n" + deep_result
  let _ = SendReport(comparison, "lz", "Compare: " + query, 3.0, chat_id)
  return respond("200 ok")
}
```

---

## ЧАСТЬ 5: Apodex для других отделов (опционально)

Apodex полезен не только ЛЗ:

| Отдел | Применение | Команда |
|---|---|---|
| ОСП | Верификация фактов в анализе | `/osp verify <doc_id>` |
| Эксперт | Проверка утверждений перед встречей | `/expert factcheck <текст>` |
| Юрист | Поиск прецедентов с верификацией | `/legal research <тема>` |
| Финансы | Проверка рыночных данных | `/finance verify <утверждение>` |

Реализуется аналогично ЛЗ — вызов Apodex с профилем конкретного отдела.

---

## ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ

```
APODEX_API_KEY=...   # platform.apodex.ai
```

---

## КОМАНДЫ ЛЗ (обновлённые)

```
/lz <запрос>              → обычный LLM ответ (10 сек)
/lz scan <запрос>         → DeepScan 9 источников (30 сек)
/lz deep <запрос>         → Apodex verified research (2-5 мин)
/lz compare <запрос>      → side-by-side LLM vs Apodex
/lz all <запрос>          → scan + deep (полный)
/lz_channel add <канал>   → мониторинг Telegram-канала
/lz_channels              → список каналов
/lz_monitor <тема>        → ежедневный мониторинг
```

---

## ЛОКАЛЬНАЯ ПРОВЕРКА

```bash
export APODEX_API_KEY=fake
bin/mlog serve app.mlog &
sleep 2

echo "=== T1: /lz deep test ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/lz deep квантовые вычисления 2026","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 2

echo "=== T2: /lz compare test ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/lz compare графеновые батареи","from":{"id":2044005421},"chat":{"id":2044005421}}}'
sleep 2

echo "=== T3: обычный /lz не сломан ==="
curl -s -X POST http://localhost:10000/webhook/telegram \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/lz AI тренды","from":{"id":2044005421},"chat":{"id":2044005421}}}'

kill %1
```

---

## КОММИТ

```bash
git commit -m "Apodex integration: 7th provider, /lz deep verified research, /lz compare, evidence graph in reports"
git push origin main
```

---

## ОТЧЁТ

```
### Результат Наряда №30

1. Apodex как 7-й провайдер: [✅/❌]
2. APODEX_API_KEY env: [✅/❌]
3. /lz deep через Apodex: [✅/❌]
4. Typing indicator refresh (5 сек): [✅/❌]
5. Бейджи verified/unverified/conflicting: [✅/❌]
6. Evidence graph секция в отчёте: [✅/❌]
7. /lz compare (LLM vs Apodex): [✅/❌]
8. Кнопки ЛЗ (Углубить Apodex, Перепроверить, Мониторинг): [✅/❌]
9. Timeout 300 сек для Apodex: [✅/❌]
10. T1-T3 проверки: [✅/❌]
11. git push: [✅/❌] [хэш]
12. Проблемы: [если есть]
```
