# ══════════════════════════════════════════════════════════════════════════
#  FOSVED OFFICE v2 — ПОШАГОВАЯ НАСТРОЙКА КЛЮЧЕЙ
#  Версия: 2026-08-14
# ══════════════════════════════════════════════════════════════════════════

## ДИАГНОЗ: почему отчёт Яны пустой

| Секция | Почему пусто | Решение |
|--------|-------------|---------|
| Мировые события | Cron `/cron/collect-news` ни разу не вызывался — новости не собраны | Запустить крон (RSS+GDELT — бесплатно, без ключей) |
| ЛЗ находки | Cron `/scheduler/lz-daily` ни разу не вызывался — GitHub не просканирован | Запустить крон (GitHub API работает без токена) |

**НОВОСТИ И ЛЗ РАБОТАЮТ БЕЗ ПЛАТНЫХ КЛЮЧЕЙ.**
RSS фиды (РИА, ТАСС, РБК, BBC, TechCrunch…) и GDELT API — бесплатные.
GitHub Search API — работает без токена (60 запр/час).

---

## ЧТО НУЖНО ЗАПОЛНИТЬ В .env (по приоритету)

### ── КЛЮЧ 1: TELEGRAM_BOT_TOKEN (ОБЯЗАТЕЛЬНО) ──

Яна отправляет отчёты через Telegram бота. Без этого токена — некому доставлять.

**Как получить (3 минуты):**

1. Откройте Telegram, найдите **@BotFather**
2. Отправьте команду: `/newbot`
3. BotFather спросит:
   - **Имя бота** (отображаемое): например `Яна Фосвед`
   - **Username бота** (заканчивается на `_bot`): например `yana_fosved_bot`
4. BotFather ответит:
   ```
   Done! Congratulations on your new bot...
   Use this token to access the HTTP API:
   7123456789:AAH_abcDefGhiJklMnoPqrStUvWxYz
   ```
5. Скопируйте токен → вставьте в `.env`:
   ```
   TELEGRAM_BOT_TOKEN=7123456789:AAH_abcDefGhiJklMnoPqrStUvWxYz
   ```

Если бот уже существует: `/mybots` → выберите бота → API Token

---

### ── КЛЮЧ 2: LLM API KEY (ОБЯЗАТЕЛЬНО — минимум один) ──

Яна использует LLM для: анализа новостей, ЛЗ отчётов, ответов на вопросы,
самообучения. Без хотя бы одного ключа — LLM-функции мертвы.

**Рекомендации для работы из-под санкций:**

| Провайдер | Регистрация | Работает? | Цена |
|-----------|------------|-----------|------|
| **DeepSeek** ⭐ | https://platform.deepseek.com | ✅ Да (Китай) | ~$0.14/1M tokens |
| **Groq** ⭐ | https://console.groq.com | ✅ Да | Бесплатный tier |
| **ZAI (z.ai)** | https://bigmodel.cn | ✅ Да (Китай) | Дешёвый |
| Anthropic | https://console.anthropic.com | ❌ Блокировка | $3/1M input |
| OpenAI | https://platform.openai.com | ❌ Блокировка | $5/1M input |

**Пошагово DeepSeek (рекомендую — дешёвый и работает):**

1. Откройте https://platform.deepseek.com
2. Зарегистрируйтесь (email или GitHub login)
3. Перейдите в **API Keys** → **Create API Key**
4. Скопируйте ключ (вида `sk-xxxxxxxxxxxxxxxx`)
5. Вставьте в `.env`:
   ```
   DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
   ```

**Пошагово Groq (бесплатный вариант):**

1. Откройте https://console.groq.com
2. Зарегистрируйтесь (GitHub login работает)
3. Перейдите в **API Keys** → **Create API Key**
4. Скопируйте ключ (вида `gsk_xxxxxxxxxxxxxxxx`)
5. Вставьте в `.env`:
   ```
   GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxx
   ```

---

### ── КЛЮЧ 3: CRON_SECRET (ОБЯЗАТЕЛЬНО для кронов) ──

Защищает эндпоинт `/cron/collect-news` от вызова посторонними.

**Как получить (10 секунд):**

Выполните в терминале:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```
Скопируйте результат → вставьте в `.env`:
```
CRON_SECRET=aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789
```

---

### ── КЛЮЧ 4: GITHUB_TOKEN_METALOGOS (ЖЕЛАТЕЛЬНО, не обязательно) ──

Увеличивает GitHub API лимит: 60 → 5000 запросов/час.
Без токена ЛЗ всё равно работает — просто с лимитом 60/час.

**Как получить (2 минуты):**

1. Откройте https://github.com/settings/tokens
2. Нажмите **Generate new token (classic)**
3. Note: `fosved-lz-scan`
4. Scopes: отметьте только **public_repo** (читать публичные репо)
5. Нажмите **Generate token**
6. Скопируйте токен (вида `ghp_xxxxxxxxxxxxxxxxxxxx`)
7. Вставьте в `.env`:
   ```
   GITHUB_TOKEN_METALOGOS=ghp_xxxxxxxxxxxxxxxxxxxx
   ```

⚠️ GitHub API НЕ санкционирован — работает из РФ/РБ.

---

### ── ЧТО НЕ НУЖНО ──

| Ключ | Почему не нужен |
|------|----------------|
| SERPAPI_KEY | ❌ Под санкциями. RSS + GDELT полностью заменяют |
| YOUTUBE_API_KEY | Опционально, для YouTube-транскрипции |
| ANTHROPIC_API_KEY | Блокируется из-под санкций |
| OPENAI_API_KEY | Блокируется из-под санкций |

---

## ЗАПУСК (после заполнения .env)

### Шаг 1: Запустить сервер
```bash
cd /home/z/my-project/FOSVED-office-v2
source .env  # загрузить переменные в окружение
python3 llm_proxy.py
```

### Шаг 2: Запустить кроны (в другом терминале)
```bash
# Один раз — собрать новости + ЛЗ скан:
python3 start_crons.py

# Или постоянно — каждые 30 минут:
python3 start_crons.py --loop

# Или каждые 60 минут:
python3 start_crons.py --loop --interval 60
```

### Шаг 3: Проверить что работает
```bash
# Статистика новостей:
curl http://localhost:10000/news/stats

# Свежие новости:
curl -X POST http://localhost:10000/news/fresh \
  -H "Content-Type: application/json" \
  -d '{"dept":"osp","limit":5}'
```

После первого запуска кронов — отчёт Яны будет содержать:
- 📌 Мировые события (из РИА, ТАСС, РБК, BBC, GDELT)
- 🔍 ЛЗ находки (из GitHub scan)
