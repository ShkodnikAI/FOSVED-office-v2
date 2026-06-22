<div align="center">

# Fosved Office v2

**Personal AI office with 14 specialized agents.
Built on Metalogos. Managed via Telegram.**

</div>

---

## What it is

Fosved Office is an operational system for business: 13 departments + system Admin agent, each with its own methodology, memory, skills, and metrics. The office receives tasks via Telegram, routes them to the right department, responds with styled Mini App reports, learns from errors, and optimizes itself at night.

## 14 personas

| Persona | Role | Skills |
|---|---|---|
| **Yana** | Chief of Cabinet | 11 |
| **OSP** | Strategic Analysis | 24 |
| **LZ** | Knowledge Lab | 12 |
| **Expert** | Technical Prep | 12 |
| **Marketing** | Audience, channels | 11 |
| **Finance** | Cashflow, taxes | 9 |
| **Legal** | NDA, GDPR, risk | 10 |
| **Dev** | Architecture, code | 20 |
| **Design** | UI/UX, wireframes | 12 |
| **QA** | Testing, chaos eng | 11 |
| **Visual** | Infographics | 5 |
| **Engineering** | Calculations, loads | 12 |
| **Kavalnya** | Methodology | 8 |
| **Admin** | System agent | 12 |

## Architecture

```
Telegram -> Reverse Proxy (10000) -> Metalogos (10001) <-> LLM Proxy (4000)
                                       |                     |
                                  app.mlog              7 LLM providers
                                  14 departments         Mini App HTML
                                  SQLite (20 tables)     Dashboards
```

## Quick Start

```bash
git clone https://github.com/ShkodnikAI/FOSVED-office-v2.git
cd FOSVED-office-v2
# Fill .env (TELEGRAM_BOT_TOKEN, OWNER_TELEGRAM_ID, LOCKDOWN_PASSWORD, CRON_SECRET, + LLM key)
docker build -t fosved .
docker run -p 10000:10000 --env-file .env fosved
```

## Stack

Metalogos (Rust, 66 builtins) - Python (Flask) - SQLite - Docker (ubuntu:24.04) - Render - Telegram Bot API

## License

MIT
