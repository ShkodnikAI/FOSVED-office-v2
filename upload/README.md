<div align="center">

# φ Fosved Office v2

**Персональный AI-офис из 14 специализированных агентов.
Построен на Metalogos. Управляется через Telegram.**

</div>

---

## Что это

Fosved Office — не чатбот и не ассистент. Это **операционная система для бизнеса**: 13 отделов + системный агент Админ, каждый со своей методологией, памятью, скиллами и метриками. Офис принимает задачи через Telegram, маршрутизирует их нужному отделу, отвечает стилизованными отчётами в Mini App, учится на ошибках и оптимизирует себя по ночам.

## 14 персон · 164 скилла

| Персона | Роль | Скиллов |
|---|---|---|
| **Яна** | Шеф де кабинет — маршрутизация, brief, эмпатия | 11 |
| **ОСП** | Стратегический анализ — ACH, Кантильон, Red Team | 24 |
| **ЛЗ** | Лаборатория знаний — технологии, disruption, deep scan | 12 |
| **Эксперт** | Технический препаратор — брифинги, BS-detection | 12 |
| **Маркетинг** | Аудитория, позиционирование, каналы | 11 |
| **Финансы** | Cashflow, налоги, unit economics | 9 |
| **Юрист** | NDA, GDPR, риск-маппинг | 10 |
| **Dev** | Архитектура, код, ADR, деплой | 20 |
| **Design** | UI/UX, wireframes, design system | 12 |
| **QA** | Тест-планы, chaos engineering, AI evals | 11 |
| **Visual** | Инфографика, визуализация данных | 5 |
| **Engineering** | Расчёты, нагрузки, СНиП | 12 |
| **Кавальня** | Методология — создание и обучение отделов | 8 |
| **Админ** | Системный агент — код, оптимизация, ночной цикл | 12 |

## Архитектура

```
Telegram → Reverse Proxy (10000) → Metalogos (10001) ←→ LLM Proxy (4000)
                                         │                    │
                                    app.mlog              7 LLM провайдеров
                                    14 отделов             Mini App HTML
                                    SQLite (20 таблиц)     Dashboards
```

## Ключевые возможности

- **Маршрутизация** — 13 slug-команд + русские ключевые слова + /chain цепочки
- **Mini App отчёты** — gradient-шапки, бейджи ФАКТ/ИНТЕРПРЕТАЦИЯ/СПЕКУЛЯЦИЯ, 4 уровня глубины
- **7 LLM-провайдеров** — Z.ai, DeepSeek, Groq, Grok, Anthropic, OpenAI, Apodex (failover)
- **Память** — /fix коррекции, /good подкрепление, /remember факты, диалоги, сжатие
- **Голос** — STT (Whisper) + TTS (Edge TTS)
- **Админ** — ночной цикл: knowledge graph, аудит кода, автофиксы, предложения
- **Scheduler** — утренний brief, вечерний свод, weekly/monthly/quarterly
- **Экономика** — /cost расход по отделам, /budget лимиты
- **Фабрика** — /factory создаёт клиентские офисы

## Quick Start

```bash
git clone https://github.com/ShkodnikAI/FOSVED-office-v2.git
cd FOSVED-office-v2
# Заполнить .env (TELEGRAM_BOT_TOKEN, OWNER_TELEGRAM_ID, LOCKDOWN_PASSWORD, CRON_SECRET, + LLM ключ)
docker build -t fosved .
docker run -p 10000:10000 --env-file .env fosved
```

## Стек

Metalogos (Rust, 66 builtins) · Python (Flask) · SQLite · Docker (ubuntu:24.04) · Render · Telegram Bot API · Whisper · Edge TTS

## Лицензия

MIT

---

*Built with Metalogos. Designed by AI. For AI.*
