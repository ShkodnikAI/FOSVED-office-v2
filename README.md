<div align="center">

# FOSVED Office V2

**AI-native operational office system. 13 departments + Admin agent. Metalogos DSL, 7 LLM providers, Telegram-native, Mini App SPA.**

</div>

---

## Overview

FOSVED Office is a self-optimizing business operating system built entirely on [Metalogos](https://github.com/ShkodnikAI/Metalogos-) — an AI-native Rust DSL. The system runs 13 specialized department agents and 1 system Admin agent, each with its own methodology, LLM-powered analysis, memory, skill index, and per-department metrics. Tasks arrive via Telegram, are routed to the correct department, processed with LLM reasoning, and returned as styled Mini App reports. The system learns from errors (6-type classification), runs scheduled digests, and performs autonomous night audits.

**~4900 lines of code** across Metalogos (.mlog) and Python, **126 patterns** (functions), **98 bot commands**, **21 database tables**, **167/167 stress-test checks passed**.

## Architecture

```
Telegram Bot API
       |
       v
Reverse Proxy (Flask, :10000)
       |
       +---> Metalogos (mlog serve, :10001)
       |       |
       |       +-- app.mlog (1096 lines, routing + commands)
       |       +-- dept/*.mlog (15 modules, 13 departments + utils)
       |       +-- file_cache.mlog (profile caching)
       |       +-- file_cache_skills.mlog (skill caching)
       |       +-- SQLite (21 tables)
       |
       +---> LLM Proxy (Flask, :4000)
               |
               +-- 7 LLM providers (zai, DeepSeek, Groq, Grok, Anthropic, OpenAI, Apodex)
               +-- Failover with priority model/provider config
               +-- 11 API endpoints (dashboard, dept, models, economics, narads, archive, admin)
               +-- TTS (edge-tts), STT (Whisper)
               +-- Mini App SPA static serving (/miniapp-spa)
               +-- Archive, scheduler, learning, audit, search
```

**Startup order** (entrypoint.sh): `llm_proxy (:4000)` → `mlog serve (:10001)` → `reverse_proxy (:10000)`

## 13 Departments + Admin

| Department | Role | Skills | File |
|---|---|---|---|
| **Yana** | Chief of Cabinet, routing, voice | 11 | `dept/yana.mlog` |
| **OSP** | Strategic analysis, planning | 24 | `dept/osp.mlog` |
| **LZ** | Knowledge lab, 9-source deep scan, Apodex research | 12 | `dept/lz.mlog` |
| **Expert** | Technical preparation | 12 | `dept/expert.mlog` |
| **Marketing** | Audience, channels, content | 11 | `dept/marketing.mlog` |
| **Finance** | Cashflow, taxes, economics | 9 | `dept/finance.mlog` |
| **Legal** | NDA, GDPR, risk assessment | 10 | `dept/legal.mlog` |
| **Dev** | Architecture, code generation | 20 | `dept/dev.mlog` |
| **Design** | UI/UX, wireframes, visuals | 12 | `dept/design.mlog` |
| **QA** | Testing, chaos engineering | 11 | `dept/qa.mlog` |
| **Visual** | Infographics, data visualization | 5 | `dept/visual.mlog` |
| **Engineering** | Calculations, loads, technical | 12 | `dept/engineering.mlog` |
| **Kavalnya** | Methodology, standards | 8 | `dept/kavalnya.mlog` |
| **Admin** | System agent, night cycle, knowledge graph, autofix | 12 | `dept/admin.mlog` |

**Total: 173 indexed skills** across 14 agents.

## Key Features

### Multi-Provider LLM with Failover
7 providers (zai, DeepSeek, Groq, Grok, Anthropic, OpenAI, Apodex) with configurable priority. Automatic failover on timeout/error. Per-department model and provider overrides via `config/override_*.txt`.

### Voice (STT/TTS)
- **STT**: Telegram voice messages → Whisper (Groq/OpenAI) → text → department processing
- **TTS**: Text responses → edge-tts → Telegram voice message (male/female, toggleable)

### Learning Loop
- 6-type error classification (factual, methodological, incomplete, contextual, formatting, reasoning)
- `/fix` command captures errors with context
- `/good` records positive examples
- `/debrief` generates LLM analysis of corrections
- Scheduled self-learning integrates corrections into system behavior

### Scheduler (6 cron jobs)
- Morning brief, evening summary, weekly digest, monthly review
- Control check (verifies predictions from system_settings watches)
- Admin night cycle (5-phase: graph → audit → metrics → autofix → proposals)
- All protected by CRON_SECRET, triggered via GET endpoints

### Archive & Search
- Reports auto-archived with HTML stripping and department hashtags
- Daily digests to Telegram channel
- Full-text search across all archived reports

### Cross-Department Chains
`/chain osp+legal` — sequential execution across departments (3-dept limit), with per-step reports and combined summary.

### LZ Deep Scan (9 sources)
Web, YouTube, Reddit, Science, GitHub, Social, Telegram, Darknet, Academic — each scanned via LLM. Apodex provider for verified research with evidence badges (verified/unverified/conflicting). LZ Compare for side-by-side LLM vs Apodex analysis.

### Admin Agent (Night Cycle)
5-phase autonomous cycle: knowledge graph build → code audit → metrics analysis → auto-fix → proposals. Builds knowledge graph from all .mlog files, runs LLM-powered code scanning, generates autofix plans (skips immutable/high-risk), and creates improvement proposals with approve/reject.

### Mini App SPA
9-screen responsive web application for Telegram WebApp integration:
- Dashboard (KPI grid, department status, admin panel)
- Department detail (tasks, skills, corrections)
- Chat (department chips, message bubbles)
- Report viewer, Model status, Economics
- Settings (profile, voice, notifications, security)
- Narads (approve/reject workflow), Archive (search + filter)

Design: Cormorant Garamond + DM Sans + DM Mono, gold `#C9A84C` accent. Phone (bottom nav) + tablet (sidebar) + desktop (3-column). Hash-based SPA routing.

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Initialize dialog |
| `/help` | Command list |
| `/status` | System status |
| `/osp`, `/lz`, `/dev`, ... | Direct to department |
| `/chain osp+legal` | Cross-department chain |
| `/voice on/off/male/female` | Voice settings |
| `/fix <text>` | Report error for learning |
| `/good` | Record positive example |
| `/learning stats` | Learning metrics |
| `/debrief [dept]` | LLM analysis of corrections |
| `/archive [id]` | View archived report |
| `/search <query>` | Full-text search |
| `/audit` | Recent audit log |
| `/factory`, `/factory_review` | Narad factory pipeline |
| `/admin status` | Admin agent status |
| `/lockdown on/off` | Emergency lockdown |
| `/remember key=value` | Persistent memory |

## Project Structure

```
.
├── app.mlog                  # Main router (1096 lines, 98 commands)
├── bin/mlog                  # Metalogos v0.7.10 binary (x86-64, Rust)
├── llm_proxy.py              # LLM proxy + API + SPA serving (1895 lines)
├── reverse_proxy.py          # Request router (108 lines)
├── entrypoint.sh             # Docker startup (3-process)
├── Dockerfile                # ubuntu:24.04
├── requirements.txt          # flask, requests, edge-tts
├── report_css.txt            # Mini App report styles
├── file_cache.mlog           # Profile caching (transliterated keys)
├── file_cache_skills.mlog    # Skill caching
├── dept/
│   ├── yana.mlog             # Chief of Cabinet
│   ├── osp.mlog              # Strategic Analysis
│   ├── lz.mlog               # Knowledge Lab (9-source scan)
│   ├── expert.mlog           # Technical Prep
│   ├── marketing.mlog        # Marketing
│   ├── finance.mlog          # Finance
│   ├── legal.mlog            # Legal
│   ├── dev.mlog              # Development
│   ├── design.mlog           # Design
│   ├── qa.mlog               # QA
│   ├── visual.mlog           # Visual
│   ├── engineering.mlog      # Engineering
│   ├── kavalnya.mlog         # Methodology
│   ├── admin.mlog            # System Agent (night cycle)
│   ├── chain.mlog            # Cross-dept chains
│   ├── scheduler.mlog        # 6 cron schedulers
│   ├── miniapp.mlog          # Report formatting + dept colors
│   ├── utils.mlog            # Shared utilities
│   └── context.mlog          # Context management
├── library/                  # 14 department profiles (.md)
├── skills_index/             # 14 skill indexes (.txt)
├── config/
│   ├── priority_model.txt    # Global model priority
│   ├── priority_provider.txt # Global provider priority
│   └── override_*.txt        # Per-department overrides (14 files)
├── miniapp/                  # Telegram WebApp SPA
│   ├── index.html
│   ├── css/                  # vars, components, screens, responsive
│   └── js/
│       ├── app.js            # Router + init
│       ├── api.js            # API client
│       └── screens/          # 9 screen modules
└── data/                     # SQLite DB, runtime data
```

## Database (21 tables)

`dialog_history`, `adapt_corrections`, `error_patterns`, `miniapp_responses`, `miniapp_notes`, `dept_metrics`, `token_usage`, `audit_log`, `system_settings`, `narads`, `admin_findings`, `admin_proposals`, `knowledge_nodes`, `knowledge_edges`, `lz_channels`, `lz_monitor`, `learning_stats`, `control_watches`, `archive`, `factory_steps`, `factory_deliverables`

## Quick Start

```bash
git clone https://github.com/ShkodnikAI/FOSVED-office-v2.git
cd FOSVED-office-v2
```

Create `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token
OWNER_TELEGRAM_ID=your_telegram_id
LOCKDOWN_PASSWORD=your_password
CRON_SECRET=your_cron_secret
ZAI_API_KEY=your_key
DEEPSEEK_API_KEY=your_key
# ... other provider keys
```

Docker:
```bash
docker build -t fosved .
docker run -p 10000:10000 --env-file .env fosved
```

## Tech Stack

| Component | Technology |
|---|---|
| Core language | Metalogos v0.7.10 (Rust DSL, 113 builtins) |
| Proxy layer | Python 3.12 + Flask |
| Database | SQLite |
| Voice STT | Whisper (Groq/OpenAI) |
| Voice TTS | edge-tts |
| LLM | 7 providers with automatic failover |
| Container | Docker (ubuntu:24.04) |
| Interface | Telegram Bot API + WebApp SPA |

## Quality

Stress test: **167/167 checks passed** (static code analysis across 17 groups: infrastructure, database, dispatchers, handlers, profiles, skills, configs, routing, commands, providers, cron, colors, audit, integrations, regressions, file cache, reverse proxy).

## License

MIT