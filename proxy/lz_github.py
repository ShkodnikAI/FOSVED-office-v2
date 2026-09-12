"""FO-008: транспорт ч.3 — GitHub-watch, LZ-сканеры, OSINT, github push, news-роуты.

Вырезано из llm_proxy.py вербатим (стренглер, шаг 4c; наряд #68, стоп-гейт SG-F2).
"""
import os
import re
import json
import time
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests as http_requests

from flask import request, jsonify

from proxy.core import (
    app, log, http_requests,
    _query, _log_audit, _log_error, _get_setting, get_secret,
    _collect_metrics_for_period, _format_metrics_text,
    memory, DB_PATH, DB_FILE, BASE_DIR, LIB_DIR,
    require_telegram, detect_dept, get_dept_prompt, CONDENSED_PROMPTS,
    DEPT_NAMES, DEPT_HASHTAGS,
)
from proxy.providers import (
    PROVIDERS, COMBO_CHAINS, _breaker, call_llm, _cfg_cache, _generate_image,
)
from proxy.telegram import (
    _tg_send_formatted, _tg_send_message, _tg_send_document, _tg_send_photo,
    _safe_filename_part, _send_chat_action_loop,
)
from proxy.reports import _evidence_badges_css, html_lib_escape
from proxy.lz_sources import arxiv_search, hn_search, github_repo_search, lz_api_scan
from proxy.news import (
    collect_tavily, collect_rss, collect_gdelt, get_fresh_news,
    get_night_news_digest,
)

# ──────────────────────────── OSINT (Aliens Eye) ────────────────────────────
OSINT_DISCLAIMER = "⚠ OSINT-данные собраны из открытых источников. Результаты не гарантируют принадлежность аккаунтов конкретному лицу. Используйте для легитимных целей в рамках законодательства."
_osint_last_time = {}  # rate limiting: chat_id -> timestamp
OSINT_RATE_LIMIT = 60  # seconds between scans

def categorize_platform(site_name):
    """Категоризация платформы по типу."""
    categories = {
        'social': ['twitter', 'facebook', 'instagram', 'tiktok', 'snapchat', 'threads', 'mastodon', 'bluesky', 'x.com'],
        'professional': ['linkedin', 'xing', 'angellist', 'crunchbase'],
        'tech': ['github', 'gitlab', 'bitbucket', 'stackoverflow', 'hackernews', 'dev.to', 'codepen'],
        'media': ['youtube', 'twitch', 'vimeo', 'soundcloud', 'spotify', 'medium', 'substack'],
        'messaging': ['telegram', 'discord', 'slack', 'signal', 'whatsapp'],
        'commerce': ['amazon', 'ebay', 'etsy', 'shopify', 'aliexpress'],
        'gaming': ['steam', 'xbox', 'playstation', 'epic', 'roblox', 'minecraft'],
        'forum': ['reddit', 'quora', '4chan', 'hackforums'],
        'dating': ['tinder', 'bumble', 'okcupid'],
        'darknet': ['onion', 'tor', 'i2p'],
    }
    site_lower = site_name.lower()
    for category, platforms in categories.items():
        if any(p in site_lower for p in platforms):
            return category
    return 'other'


def scan_osint(username, level='basic', timeout=120, tor=False, sites=None):
    """Scan username across 840+ platforms via Aliens Eye."""
    cmd = ['aliens_eye', username, '--format', 'json', '--plain', '-l', level]
    if tor:
        cmd.extend(['--tor'])
    if sites:
        cmd.extend(['--site', ','.join(sites)])
    cmd.extend(['--no-nsfw'])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, 'NO_COLOR': '1'}
        )
        if result.returncode != 0:
            return {'error': f'Aliens Eye exited with code {result.returncode}', 'stderr': result.stderr[:500]}

        data = json.loads(result.stdout)
        results_list = data.get('results', [])
        found = [p for p in results_list if p.get('status') == 'Found']
        maybe = [p for p in results_list if p.get('status') == 'Maybe']

        return {
            'username': username,
            'found': len(found),
            'maybe': len(maybe),
            'total_scanned': len(results_list),
            'scan_time': data.get('elapsed', '?'),
            'platforms': [{
                'name': p.get('site', ''),
                'url': p.get('url', ''),
                'confidence': p.get('confidence', 0),
                'category': categorize_platform(p.get('site', ''))
            } for p in found],
            'uncertain': [{
                'name': p.get('site', ''),
                'url': p.get('url', ''),
                'confidence': p.get('confidence', 0)
            } for p in maybe],
        }
    except subprocess.TimeoutExpired:
        return {'error': f'Timeout after {timeout}s', 'username': username}
    except json.JSONDecodeError:
        return {'error': 'Failed to parse Aliens Eye output', 'raw': result.stdout[:500]}
    except FileNotFoundError:
        return {'error': 'aliens_eye binary not found. Install: pip3 install aliens-eye'}
    except Exception as e:
        return {'error': str(e)}

# ══════════════════════════════════════════════════════════════════════

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN_METALOGOS", "")
GITHUB_HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GITHUB_TOKEN:
    GITHUB_HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

# Queries for GitHub scanning — tuned to Fosved's tech stack
# Dates are dynamic: search repos updated/created in last 14 days
def _build_github_queries():
    """Build GitHub search queries for Fosved's tech stack."""
    return [
        "LLM agent framework language:python stars:>10",
        "telegram bot AI assistant python stars:>5",
        "Rust DSL parser interpreter stars:>5",
        "multi-agent LLM office automation stars:>3",
        "RAG retrieval augmented python stars:>10",
        "mcp model context protocol tool stars:>5",
        "mem0 mem0ai agent memory stars:>5",
        "Flask LLM proxy failover stars:>3",
    ]

# Repos to watch for new releases
GITHUB_WATCH_RELEASES = [
    "moorcheh-ai/memanto",
    "langchain-ai/langchain",
    "openai/openai-python",
    "anthropics/anthropic-sdk-python",
]


def _github_search(query, sort="updated", per_page=5):
    """Search GitHub repos, return list of dicts. Works without token (public API)."""
    try:
        params = {"q": query, "sort": sort, "order": "desc", "per_page": per_page}
        headers = {"Accept": "application/vnd.github.v3+json"}
        if GITHUB_TOKEN and not GITHUB_TOKEN.startswith("["):
            headers["Authorization"] = f"token {GITHUB_TOKEN}"
        resp = http_requests.get(
            "https://api.github.com/search/repositories",
            headers=headers, params=params, timeout=15
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            return [{
                "name": r["full_name"],
                "desc": (r.get("description") or "")[:120],
                "stars": r.get("stargazers_count", 0),
                "lang": r.get("language", ""),
                "updated": r.get("updated_at", "")[:10],
                "url": r.get("html_url", ""),
                "created": r.get("created_at", "")[:10],
            } for r in items]
        elif resp.status_code == 403:
            log.warning(f"GitHub API rate limited: {query[:50]}")
            return []
        else:
            log.warning(f"GitHub search {resp.status_code}: {query[:50]}")
            return []
    except Exception as e:
        log.error(f"GitHub search error: {e}")
        return []


def _github_releases(repo_full_name):
    """Get latest 3 releases for a repo. Works without token."""
    try:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if GITHUB_TOKEN and not GITHUB_TOKEN.startswith("["):
            headers["Authorization"] = f"token {GITHUB_TOKEN}"
        resp = http_requests.get(
            f"https://api.github.com/repos/{repo_full_name}/releases?per_page=3",
            headers=headers, timeout=10
        )
        if resp.status_code == 200:
            return [{
                "repo": repo_full_name,
                "tag": r.get("tag_name", ""),
                "name": r.get("name", ""),
                "body": (r.get("body") or "")[:200],
                "date": r.get("published_at", "")[:10],
                "url": r.get("html_url", ""),
            } for r in resp.json() if not r.get("draft", False)]
        return []
    except Exception as e:
        log.error(f"GitHub releases error for {repo_full_name}: {e}")
        return []


@app.get("/scheduler/lz-daily-test")
def scheduler_lz_daily_test():
    """Безопасная проверка через обычную ссылку в браузере — GET, по умолчанию
    dry_run=True принудительно, никаких побочных эффектов. Добавь
    ?really_write=yes_i_mean_it к ссылке, чтобы один раз проверить настоящую
    запись в память — так же, как это делает реальный cron (dry_run=False),
    но с основного веб-сервиса, а не с отдельного Cron Job сервиса Render.
    Так можно отличить 'фикс не сработал' от 'cron-сервис не задеплоил новый код'."""
    really_write = request.args.get("really_write") == "yes_i_mean_it"
    return scheduler_lz_daily_core(dry_run=not really_write, owner_id=os.environ.get("OWNER_TELEGRAM_ID", ""))


@app.post("/scheduler/lz-daily")
def scheduler_lz_daily():
    """
    LZ Daily Report: scan GitHub → LLM analysis → save to memory → return report.
    Called by /cron/lz-daily or manually.
    """
    d = request.get_json(force=True) or {}
    owner_id = d.get("owner_id", os.environ.get("OWNER_TELEGRAM_ID", ""))
    dry_run = d.get("dry_run", False)
    return scheduler_lz_daily_core(dry_run=dry_run, owner_id=owner_id)


def scheduler_lz_daily_core(dry_run, owner_id):
    try:
        # ── Phase 1: GitHub Scan (direct API) ─────────────────
        log.info("LZ Daily: starting GitHub scan")
        all_repos = []
        seen = set()
        for q in _build_github_queries():
            repos = _github_search(q, per_page=3)
            time.sleep(1)
            for r in repos:
                if r["name"] not in seen:
                    seen.add(r["name"])
                    all_repos.append(r)

        # Check watched repos for new releases
        all_releases = []
        seen_release_keys = set()  # dedup by (repo, tag) across runs
        for repo in GITHUB_WATCH_RELEASES:
            releases = _github_releases(repo)
            time.sleep(1)
            for r in releases:
                rkey = f"{r['repo']}@{r['tag']}"
                if rkey not in seen_release_keys:
                    seen_release_keys.add(rkey)
                    all_releases.append(r)

        github_ok = bool(all_repos or all_releases)
        if not github_ok:
            log.warning("LZ Daily: GitHub API returned 0 results, will use LLM fallback")

        # Also check lz_monitors table for custom topics
        monitor_topics = []
        try:
            monitors = _query("SELECT query FROM lz_monitors WHERE frequency = 'daily'", fetch=True)
            monitor_topics = [m["query"] for m in monitors] if monitors else []
        except Exception:
            pass  # Table may not exist yet (created by mlog InitDB)

        scan_summary = {
            "repos_found": len(all_repos),
            "releases_found": len(all_releases),
            "monitors_active": len(monitor_topics),
            "github_api_ok": github_ok,
        }

        # ── Phase 1.5: Collect world news from news_cache (RSS + Tavily + GDELT) ──
        world_news_text = ""
        try:
            news_rows = _query("""SELECT source, title, summary, url, category, published
                                  FROM news_cache
                                  WHERE collected > datetime('now', '-24 hours')
                                  ORDER BY published DESC LIMIT 20""", fetch=True)
            if news_rows:
                cats_order = {"tech": 0, "science": 1, "geopolitics": 2, "news_ru": 3, "news_en": 4, "finance": 5}
                news_rows.sort(key=lambda r: (cats_order.get(r[4], 9), r[5] or ""))
                world_news_text = f"=== МИРОВЫЕ НОВОСТИ И СОБЫТИЯ ({len(news_rows)} за 24ч) ===\n\n"
                for nr in news_rows:
                    src, title, summary, url, cat, pub = nr
                    entry = f"[{src}] {title}\n"
                    if url:
                        entry += f"  Ссылка: {url}\n"
                    if summary and summary != title:
                        entry += f"  {summary[:200]}\n"
                    if pub:
                        entry += f"  Дата: {pub[:10]}\n"
                    world_news_text += entry + "\n"
        except Exception as e:
            log.warning(f"LZ Daily: world news query failed: {e}")

        # Count world news items
        news_count = len(world_news_text.split("[")) - 1 if world_news_text else 0

        # Update scan_summary with news count
        scan_summary["world_news"] = news_count

        # ── Phase 2: LLM Analysis ─────────────────────────────
        lz_prompt = get_dept_prompt("lz")

        if github_ok or world_news_text:
            # Direct API worked — analyze the data we collected
            repos_text = ""
            for i, r in enumerate(all_repos[:15], 1):
                repos_text += f"{i}. {r['name']} ({r['stars']}★, {r['lang']}) — {r['desc']}\n   {r['url']}\n"
            releases_text = ""
            for r in all_releases:
                releases_text += f"- {r['repo']} {r['tag']}: {r['name']} ({r['date']})\n  {r['body']}\n  {r['url']}\n"
            monitors_text = ""
            if monitor_topics:
                monitors_text = "Custom monitors: " + ", ".join(monitor_topics)

            # Build world news section for prompt
            news_section = ""
            if world_news_text:
                news_section = f"\n{world_news_text}\n"

            analysis_messages = [
                {"role": "system", "content": lz_prompt + "\n\n"
                 "Ты — Лаборатория Загадок Фосвед Офиса. Задача: проанализировать ежедневный скан мира.\n\n"
                 "ТВОЯ КЛЮЧЕВАЯ РОЛЬ: отобрать НОВИНКИ и СОБЫТИЯ, которые Админ должен знать.\n\n"
                 "Структура отчёта:\n"
                 "1. 🔥 Тренды и находки дня (технологии, наука, геополитика) — с disrupting potential 1-10\n"
                 "2. 📦 Новые релизы и обновления — что вышло\n"
                 "3. 🌍 Ключевые мировые события — экономика, политика, breakthrough\n"
                 "4. 💡 Рекомендации — что Админу стоит изучить и почему\n"
                 "5. 📊 Статистика скана\n\n"
                 "ПРАВИЛО ССЫЛОК: для КАЖДОГО упомянутого проекта/события ОБЯЗАТЕЛЬНО включай прямую ссылку на источник в формате: https://...\n"
                 "Используй ТОЛЬКО ссылки из предоставленных данных. Не придумывай ссылки.\n\n"
                 "Фильтруй: релевантное для AI-офиса, технологий, мировых событий.\n"
                 "Язык: русский."},
                {"role": "user", "content": f"Данные скана за {datetime.utcnow().isoformat()[:10]}:\n\n"
                 f"=== НОВЫЕ РЕПОЗИТОРИИ ({len(all_repos)} найдено) ===\n"
                 f"{repos_text}\n\n"
                 f"=== НОВЫЕ РЕЛИЗЫ ({len(all_releases)}) ===\n"
                 f"{releases_text}\n\n"
                 f"{news_section}"
                 f"{monitors_text}"}
            ]
        else:
            # GitHub API failed — but we may have world news from news_cache
            log.info("LZ Daily: GitHub API failed, using available data")
            news_section = ""
            if world_news_text:
                news_section = f"\n{world_news_text}\n"
            analysis_messages = [
                {"role": "system", "content": lz_prompt + "\n\n"
                 "Ты — Лаборатория Загадок Фосвед Офиса. Проведи ежедневный обзор новинок и событий.\n\n"
                 "Структура отчёта:\n"
                 "1. 🔥 Тренды и находки дня (технологии, наука, геополитика) — с disrupting potential 1-10\n"
                 "2. 🌍 Ключевые мировые события — экономика, политика, breakthrough\n"
                 "3. 💡 Рекомендации Админу\n\n"
                 "ПРАВИЛО ССЫЛОК: для КАЖДОГО упомянутого проекта/события ОБЯЗАТЕЛЬНО включай прямую ссылку на источник.\n"
                 "Используй ТОЛЬКО ссылки из предоставленных данных. Если данных нет — укажи поисковый запрос.\n\n"
                 "Язык: русский."},
                {"role": "user", "content": f"Сделай ежедневный обзор новинок и событий за {datetime.utcnow().isoformat()[:10]}.\n\n"
                 f"{news_section}"
                 f"Фокус: AI, технологии, мировые события, breakthrough.\n\n"
                 f"Для каждого пункта укажи: название, прямую ссылку на источник, что нового, почему важно."}
            ]

        result = call_llm("lz", analysis_messages)
        analysis = result.get("reply", "Analysis failed.")

        # ── Phase 3: Save to DB + Memory (with cross-run dedup) ───────────
        if not dry_run:
            # LZ Dedup: save releases & repos to lz_telegram_posts with update_id
            # update_id format: "gh:{repo}:{tag}" for releases, "gh:repo:{name}" for repos
            # UNIQUE constraint on update_id prevents duplicate entries across scans
            for r in all_releases:
                try:
                    _query(
                        "INSERT OR IGNORE INTO lz_telegram_posts (update_id, channel_id, channel_name, text, date) VALUES (?, ?, ?, ?, ?)",
                        (f"gh:{r.get('repo','')}:{r.get('tag','')}", r.get('repo',''), r.get('repo',''), r.get('body','')[:500], r.get('date',''))
                    )
                except Exception:
                    pass  # update_id column may not exist yet (pre-ALTER TABLE state)
            for r in all_repos:
                try:
                    _query(
                        "INSERT OR IGNORE INTO lz_telegram_posts (update_id, channel_id, channel_name, text, date) VALUES (?, ?, ?, ?, datetime('now'))",
                        (f"gh:repo:{r.get('name','')}", "github", r.get('lang',''), r.get('desc','')[:300])
                    )
                except Exception as e:
                    _log_error(f"lz_telegram_posts insert failed: {e}", source="lz_github", dept="lz", kind="data_loss")

            today_key = f"LZ Daily {datetime.utcnow().isoformat()[:10]}"
            # Check if we already stored today's scan summary
            existing = memory.recall_by_source("lz_daily", limit=5)
            already_today = any(today_key in (e.get("content") or "") for e in existing)
            if not already_today:
                memory.remember(
                    f"{today_key}: {len(all_repos)} repos, {len(all_releases)} releases scanned",
                    "observation", 0.7, "lz_daily"
                )
            # Save top findings as individual memories (dedup by content prefix)
            recent_findings = memory.recall_by_source("lz_daily", limit=100)
            for line in analysis.split("\n"):
                line = line.strip()
                if line.startswith(("1.", "2.", "3.")) and len(line) > 20:
                    prefix = line[:60]
                    already_saved = any(prefix in (e.get("content") or "") for e in recent_findings)
                    if not already_saved:
                        memory.remember(
                            f"LZ находка: {line[:200]}",
                            "observation", 0.8, "lz_daily"
                        )

        # ── Phase 4: Build Report ─────────────────────────────
        report = f"🔍 LZ DAILY REPORT — {datetime.utcnow().isoformat()[:10]}\n"
        report += f"{'=' * 40}\n\n"
        report += analysis
        report += f"\n\n{'─' * 40}\n"
        report += f"Скан: {len(all_repos)} repos, {len(all_releases)} releases, {news_count} новостей, {len(monitor_topics)} monitors\n"
        report += f"Provider: {result.get('provider', '?')} | Tokens: {result.get('tokens_in', 0)}+{result.get('tokens_out', 0)}"

        # ── Phase 5: Send to Owner (Admin) ────────────────────
        msg_id = None
        if owner_id and not dry_run:
            if len(report) > 1500:
                msg_id = _tg_send_report_with_button(owner_id, report)
            else:
                msg_id = _tg_send_message(owner_id, report)

        _log_audit("lz_daily_report", {
            "repos": len(all_repos), "releases": len(all_releases),
            "world_news": news_count, "monitors": len(monitor_topics),
            "provider": result.get("provider"),
            "msg_id": msg_id, "dry_run": dry_run
        })

        return jsonify({
            "status": "ok",
            "report": report,
            "scan": scan_summary,
            "msg_id": msg_id,
            "sent_to": owner_id if not dry_run else None,
        })

    except Exception as e:
        log.error(f"lz_daily_report error: {e}")
        _log_audit("lz_daily_report_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500


@app.post("/scheduler/admin-daily")
def scheduler_admin_daily():
    """
    Admin Daily Report: comprehensive report combining:
    - Night cycle results (from kv)
    - Memory maintenance summary
    - LZ daily findings
    - System health
    Sent to owner.
    """
    d = request.get_json(force=True) or {}
    owner_id = d.get("owner_id", os.environ.get("OWNER_TELEGRAM_ID", ""))

    if not owner_id:
        return jsonify({"status": "error", "message": "owner_id is required"}), 400

    try:
        now = datetime.utcnow()
        today = now.isoformat()[:10]
        parts = []

        # 1. Night cycle summary (if available)
        night_summary = ""  # Would need to read from mlog kv — call mlog internal
        parts.append(f"📅 АДМИН ДAILY REPORT — {today}")
        parts.append("=" * 40)

        # 2. Memory stats
        mem_stats = memory.stats()
        parts.append(f"\n🧠 ПАМЯТЬ: {mem_stats['total_active']} активных записей")
        for t, info in sorted(mem_stats['by_type'].items(), key=lambda x: -x[1]['count'])[:5]:
            parts.append(f"  {t}: {info['count']} (avg conf {info['avg_confidence']})")

        # 3. Memory conflicts
        conflicts = memory.detect_conflicts()
        if conflicts:
            parts.append(f"\n⚠️ КОНФЛИКТЫ: {len(conflicts)}")
            for c in conflicts[:3]:
                parts.append(f"  [{c['type']}] {c['memory_a']['content'][:50]} vs {c['memory_b']['content'][:50]}")

        # 4. Memory maintenance
        maint = memory.nightly_maintenance()
        parts.append(f"\n🔧 MEMORY MAINTENANCE:\n{maint}")

        # 5. LZ daily findings
        lz_findings = memory.recall("LZ Daily", type_filter="observation", limit=3)
        if lz_findings:
            parts.append(f"\n🔍 LZ ПОСЛЕДНИЕ НАХОДКИ:")
            for f in lz_findings:
                ts = time.strftime('%m-%d', time.localtime(f['created_at']))
                parts.append(f"  [{ts}] {f['content'][:100]}")

        # 6. System metrics
        yesterday = (now - timedelta(days=1)).isoformat()[:10] + "T00:00:00"
        metrics = _collect_metrics_for_period(yesterday, today + "T00:00:00")
        parts.append(f"\n📊 МЕТРИКИ (вчера):")
        tasks_total = sum(metrics.get("tasks", {}).values())
        reports_total = sum(metrics.get("reports", {}).values())
        parts.append(f"  Tasks: {tasks_total} | Reports: {reports_total}")

        # 7. Open issues from night cycle
        f_cnt, p_cnt = 0, 0
        try:
            findings = _query(
                "SELECT COUNT(*) as cnt FROM admin_findings WHERE status = 'open'", fetch=True
            )
            proposals = _query(
                "SELECT COUNT(*) as cnt FROM admin_proposals WHERE status = 'pending'", fetch=True
            )
            if findings and proposals:
                f_cnt = findings[0].get("cnt", 0) if isinstance(findings[0], dict) else 0
                p_cnt = proposals[0].get("cnt", 0) if isinstance(proposals[0], dict) else 0
        except Exception:
            pass  # Tables may not exist yet (created by mlog InitDB)
        if f_cnt or p_cnt:
            parts.append(f"\n📋 АДМИН: {f_cnt} open issues, {p_cnt} pending proposals")

        report = "\n".join(parts)

        # Send to owner
        if len(report) > 2000:
            msg_id = _tg_send_report_with_button(owner_id, report)
        else:
            msg_id = _tg_send_message(owner_id, report)

        _log_audit("admin_daily_report", {"owner_id": owner_id, "msg_id": msg_id, "chars": len(report)})

        return jsonify({"status": "ok", "report": report, "msg_id": msg_id})

    except Exception as e:
        log.error(f"admin_daily_report error: {e}")
        _log_audit("admin_daily_report_error", {"error": str(e)[:500]})
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════════════
#  GITHUB FILE PUSH ENDPOINT — for project pipeline
# ══════════════════════════════════════════════════════════════════════

_GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
_GITHUB_HEADERS = {'Authorization': f'token {_GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json'} if _GITHUB_TOKEN else {}


def _parse_github_repo(repo_url):
    """Extract owner/repo from GitHub URL or 'owner/repo' string."""
    repo_url = repo_url.strip().rstrip('/')
    # Handle 'https://github.com/owner/repo' or 'github.com/owner/repo'
    if 'github.com/' in repo_url:
        parts = repo_url.split('github.com/')[-1].split('/')
        if len(parts) >= 2:
            return parts[0], parts[1]
    # Handle 'owner/repo' format
    parts = repo_url.split('/')
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, None


@app.route('/github/push-file', methods=['POST'])
def github_push_file():
    """Push a single file to GitHub repo via Contents API.
    Request: {repo, path, content, message?, branch?}
    Returns: {status, sha?, url?, error?}"""
    if not _GITHUB_TOKEN:
        return jsonify({'status': 'error', 'error': 'GITHUB_TOKEN not set'}), 400
    d = request.get_json(force=True) or {}
    repo = d.get('repo', '').strip()
    path = d.get('path', '').strip()
    content = d.get('content', '')
    message = d.get('message', f'Add {path}').strip()
    branch = d.get('branch', 'main').strip()
    if not repo or not path or content is None:
        return jsonify({'status': 'error', 'error': 'repo, path, content required'}), 400
    owner, repo_name = _parse_github_repo(repo)
    if not owner:
        return jsonify({'status': 'error', 'error': f'Cannot parse repo: {repo}'}), 400
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/contents/{path}'
    # Check if file exists (need SHA for update)
    sha = None
    try:
        check = http_requests.get(api_url, headers=_GITHUB_HEADERS, params={'ref': branch}, timeout=15)
        if check.status_code == 200:
            sha = check.json().get('sha')
    except Exception as e:
        _log_error(f"github pre-check for branch {branch} failed: {e}", source="lz_push", dept="lz", kind="external")
    # Create/update file
    import base64
    payload = {
        'message': message,
        'content': base64.b64encode(content.encode('utf-8')).decode('ascii'),
        'branch': branch,
    }
    if sha:
        payload['sha'] = sha
    try:
        resp = http_requests.put(api_url, json=payload, headers=_GITHUB_HEADERS, timeout=30)
        data = resp.json()
        if resp.status_code in (200, 201):
            log.info(f'GitHub push OK: {owner}/{repo_name}/{path}')
            return jsonify({'status': 'ok', 'sha': data.get('content', {}).get('sha'), 'url': data.get('content', {}).get('html_url')})
        else:
            log.error(f'GitHub push failed: {resp.status_code} {data}')
            return jsonify({'status': 'error', 'error': data.get('message', f'HTTP {resp.status_code}')})
    except Exception as e:
        log.error(f'GitHub push error: {e}')
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════════════
#  OSINT ENDPOINT — Aliens Eye 840+ platforms
# ══════════════════════════════════════════════════════════════════════

@app.route('/lz/osint', methods=['POST'])
def lz_osint():
    """OSINT scan via Aliens Eye. Owner-only, rate-limited."""
    import time as _time
    d = request.get_json(force=True) or {}
    username = d.get('username', '').strip()
    level = d.get('level', 'basic')
    tor = d.get('tor', False)
    sites = d.get('sites', None)
    chat_id = str(d.get('chat_id', ''))
    caller_id = str(d.get('caller_id', ''))

    if not username:
        return jsonify({'error': 'Username required'}), 400

    # Owner-only check
    owner_id = os.environ.get('OWNER_TELEGRAM_ID', '')
    if owner_id and caller_id and caller_id != owner_id:
        _log_audit('lz_osint_denied', {'caller_id': caller_id, 'username': username}, 'lz')
        return jsonify({'error': 'OSINT доступен только владельцу'}), 403

    # Rate limit
    now = _time.time()
    last = _osint_last_time.get(chat_id, 0)
    if now - last < OSINT_RATE_LIMIT:
        wait = int(OSINT_RATE_LIMIT - (now - last))
        return jsonify({'error': f'Rate limit: подождите {wait} сек между сканами'}), 429
    _osint_last_time[chat_id] = now

    # Typing indicator
    try:
        _tg_send_message(chat_id, f"🔍 Сканирую {username} по 840+ платформам... (30-120 сек)")
    except Exception as e:
        _log_error(f"osint notice send failed: {e}", source="osint", dept="system", kind="external")

    # Scan
    result = scan_osint(username, level=level, tor=tor, sites=sites)

    if 'error' in result:
        _log_audit('lz_osint_error', {'username': username, 'error': result['error']}, 'lz')
        return jsonify({'response': f"Ошибка OSINT: {result['error']}\n\n{OSINT_DISCLAIMER}", 'osint_data': result, 'dept': 'lz'}), 500

    # LLM analysis
    lz_profile = CONDENSED_PROMPTS.get('lz', '')
    analysis_prompt = f"""{lz_profile}

Проанализируй результаты OSINT-сканирования username "{username}":

Найдено: {result['found']} платформ
Под вопросом: {result['maybe']} платформ
Просканировано: {result['total_scanned']} платформ
Время: {result['scan_time']}

Платформы где найден:
{json.dumps(result['platforms'], indent=2, ensure_ascii=False)}

Под вопросом:
{json.dumps(result['uncertain'], indent=2, ensure_ascii=False)}

Анализируй:
1. Цифровой профиль — кто этот человек судя по платформам?
2. Категоризация активности (tech/social/professional/media)
3. Аномалии — отсутствие на ожидаемых платформах
4. Противоречия между профилями
5. Уровень цифровой гигиены (много следов = низкая, мало = высокая)
6. [ФАКТ] для подтверждённых находок, [ИНТЕРПРЕТАЦИЯ] для выводов

{OSINT_DISCLAIMER}"""

    llm_result = _call_llm_with_failover(analysis_prompt, 'lz')
    analysis = llm_result.get('reply', 'Ошибка LLM-анализа') if isinstance(llm_result, dict) else str(llm_result)

    # Token tracking
    t_in = llm_result.get('tokens_in', 0) if isinstance(llm_result, dict) else 0
    t_out = llm_result.get('tokens_out', 0) if isinstance(llm_result, dict) else 0
    prov = llm_result.get('provider', '?') if isinstance(llm_result, dict) else '?'
    now_iso = datetime.utcnow().isoformat()
    _query("INSERT INTO token_usage (provider,model,input_tokens,output_tokens,cost_usd,dept,created_at) VALUES (?,?,?,?,?,?,?)",
           (prov, 'osint-analysis', t_in, t_out, 0, 'lz', now_iso))

    _log_audit('lz_osint', {
        'username': username, 'found': result['found'], 'maybe': result['maybe'],
        'total': result['total_scanned'], 'scan_time': result['scan_time']
    }, 'lz')

    return jsonify({
        'response': analysis,
        'osint_data': result,
        'dept': 'lz',
        'disclaimer': OSINT_DISCLAIMER
    })

# ── Fresh news for mlog BuildContext ──
@app.route("/news/fresh", methods=["POST"])
def news_fresh():
    d = request.get_json(force=True)
    query = d.get("query", "")
    dept = d.get("dept", "")
    limit = int(d.get("limit", 5))
    news = get_fresh_news(query, dept=dept, limit=limit)
    return jsonify({"news": news})


# ── /lz/github-scan endpoint (used by ScanGitHub in lz.mlog) ──
@app.route("/lz/github-scan", methods=["POST"])
def lz_github_scan():
    """Search GitHub repos for LZ. Thin wrapper around _github_search."""
    d = request.get_json(force=True)
    query = d.get("query", "")
    limit = int(d.get("limit", 5))
    if not query:
        return jsonify({"repos": [], "total": 0})
    repos = _github_search(query, per_page=limit)
    text = "\n".join([f"- {r['name']} ({r['stars']}★, {r['lang']}) — {r['desc']}\n  {r['url']}" for r in repos])
    return jsonify({"repos": repos, "total": len(repos), "text": text})


# ── FO-010: /lz/api-scan — детерминированные arXiv/HN/GitHub источники ──
@app.route("/lz/api-scan", methods=["POST"])
def lz_api_scan_endpoint():
    """Детерминированный скан источников (без LLM). LLM — только синтез сверху.

    Body: {"topics": ["solid state batteries", ...], "max_per_source": 6}
    Метрика скана пишется в FO-004 трейсы (trace_type=lz_api_scan).
    """
    d = request.get_json(force=True)
    topics = d.get("topics") or ([d.get("query", "")] if d.get("query") else [])
    max_per_source = int(d.get("max_per_source", 6))
    if not topics or not [t for t in topics if str(t).strip()]:
        return jsonify({"error": "topics required"}), 400
    res = lz_api_scan([str(t).strip() for t in topics if str(t).strip()],
                      max_per_source=max_per_source, dept=d.get("dept", "lz"))
    return jsonify({"items": res["items"], "text": res["text"], "counts": res["counts"],
                    "latency_ms": res["latency_ms"], "est_tokens_saved": res["est_tokens_saved"],
                    "trace_id": res["trace_id"], "total": len(res["items"])})


# ── /lz news endpoint ──
@app.route("/lz/diagnose", methods=["GET"])
def lz_diagnose():
    """Честная проверка каждого заявленного источника ЛЗ по отдельности.
    Не переиспользует mlog-паттерны — бьёт напрямую в тот же механизм,
    чтобы результат не зависел от состояния dept/lz.mlog."""
    report = []

    # 1. news_cache — что реально в основе Web/YouTube/Reddit/Science/Social/Telegram
    try:
        rows = _query("SELECT COUNT(*), MAX(collected) FROM news_cache WHERE collected > datetime('now', '-48 hours')", fetch=True)
        cnt = rows[0][0] if rows else 0
        last = rows[0][1] if rows else None
        report.append({
            "source": "news_cache (основа Web/YouTube/Reddit/Science/Social/Telegram-скана)",
            "ok": cnt > 0,
            "detail": f"{cnt} записей за 48ч, последняя: {last or 'нет'}" if cnt else "пусто — сборщик RSS/GDELT не наполнял кэш последние 48ч",
        })
    except Exception as e:
        report.append({"source": "news_cache", "ok": False, "detail": f"ошибка БД: {e}"})

    report.append({
        "source": "YouTube / Reddit / Social (Twitter, TikTok, Instagram) / Telegram-web-поиск",
        "ok": False,
        "detail": "АРХИТЕКТУРНО НЕ РАБОТАЮТ: реализованы как SQL-поиск по news_cache (см. выше), не как обращение к самим платформам. Приписка 'site:reddit.com'/'tiktok' к запросу ищется как слово в заголовках новостных статей — таких статей с этих платформ в кэше нет физически.",
    })

    # 2. GitHub — реальный API
    try:
        gh_token = os.environ.get("GITHUB_TOKEN_METALOGOS", "")
        repos = _github_search("test", per_page=1)
        report.append({
            "source": "GitHub (/lz/github-scan)",
            "ok": isinstance(repos, list),
            "detail": f"токен {'задан' if gh_token else 'НЕ задан (работает по анонимному лимиту 60/час)'}, тестовый запрос вернул {len(repos)} результатов" if isinstance(repos, list) else "функция вернула не список",
        })
    except Exception as e:
        report.append({"source": "GitHub", "ok": False, "detail": f"ошибка: {e}"})

    # 3. Tavily — реальный внешний веб-поиск
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if not tavily_key:
        report.append({"source": "Tavily (живой веб-поиск)", "ok": False, "detail": "TAVILY_API_KEY не задан в окружении"})
    else:
        try:
            r = http_requests.post("https://api.tavily.com/search", json={"api_key": tavily_key, "query": "test", "max_results": 1}, timeout=15)
            report.append({"source": "Tavily (живой веб-поиск)", "ok": r.status_code == 200, "detail": f"HTTP {r.status_code}"})
        except Exception as e:
            report.append({"source": "Tavily (живой веб-поиск)", "ok": False, "detail": f"сеть недоступна или таймаут: {e}"})
        report.append({
            "source": "Tavily — ВАЖНО про LZTavilySearch в dept/lz.mlog",
            "ok": False,
            "detail": "текущая реализация в mlog зовёт api.tavily.com НАПРЯМУЮ, в обход внутреннего прокси 127.0.0.1:4000, которым пользуется весь остальной код — это может быть заблокировано сетевой политикой окружения независимо от валидности ключа. Плюс вызов без try — при любом сбое падает целиком, не отвечает мягко.",
        })

    # 4. Telegram-мониторинг каналов
    try:
        rows = _query("SELECT COUNT(*) FROM lz_channels WHERE status='active'", fetch=True)
        cnt = rows[0][0] if rows else 0
        report.append({"source": "lz_channels (список отслеживаемых Telegram-каналов)", "ok": cnt > 0, "detail": f"{cnt} активных каналов" if cnt else "таблица пуста или не существует — каналов не добавлено ни одного"})
    except Exception as e:
        report.append({"source": "lz_channels", "ok": False, "detail": f"таблица недоступна: {e}"})
    report.append({
        "source": "LZTelegramSearch — ВАЖНО",
        "ok": False,
        "detail": "гарантированно падает при каждом вызове: использует db_execute() для SELECT-запроса вместо query(), без try — 'Execute returned results, did you mean to call query?'. Даже после починки — нет реального механизма чтения постов из Telegram-каналов, модель получит пустой список и будет придумывать анализ несуществующих постов.",
    })

    # 5. scan_logs — используется LZTavilySearch для логирования
    try:
        _query("SELECT COUNT(*) FROM scan_logs", fetch=True)
        report.append({"source": "scan_logs", "ok": True, "detail": "таблица существует"})
    except Exception as e:
        report.append({"source": "scan_logs", "ok": False, "detail": f"таблица не создана нигде в app.mlog — INSERT в LZTavilySearch падает: {e}"})

    # 6. Darknet — честно заявлен недоступным в самом коде
    report.append({"source": "Darknet", "ok": None, "detail": "код сам честно возвращает '[unavailable — no anonymous access infrastructure]', не пытается притворяться рабочим"})

    # 7. Свежесть памяти LZ Daily — та самая, что попадает в утренний бриф
    try:
        recent = memory.recall_by_source("lz_daily", limit=5)
        if recent:
            dates = [e.get("content", "")[:40] for e in recent]
            report.append({"source": "lz_daily память (последние 5 записей)", "ok": True, "detail": " | ".join(dates)})
        else:
            report.append({"source": "lz_daily память", "ok": False, "detail": "записей нет вообще"})
    except Exception as e:
        report.append({"source": "lz_daily память", "ok": False, "detail": f"ошибка чтения: {e}"})

    ok_count = sum(1 for r in report if r["ok"] is True)
    fail_count = sum(1 for r in report if r["ok"] is False)
    return jsonify({"status": "ok", "working": ok_count, "broken": fail_count, "report": report})


@app.route("/lz/news", methods=["POST"])
def lz_news():
    d = request.get_json(force=True)
    query = d.get("query", "")
    category = d.get("category", None)
    limit = int(d.get("limit", 15))
    if query:
        news = get_fresh_news(query, dept="lz", limit=limit)
    elif category:
        rows = _query("""SELECT source, title, summary, url, published FROM news_cache
                         WHERE category = ? ORDER BY published DESC LIMIT ?""", (category, limit), fetch=True)
        news = "\n".join(f"[{r[0]}] {r[1]}\n  {r[2] or ''}\n  {r[3] or ''}" for r in rows) if rows else "Нет событий"
    else:
        rows = _query("""SELECT source, title, summary, url, published FROM news_cache
                         ORDER BY published DESC LIMIT ?""", (limit,), fetch=True)
        news = "\n".join(f"[{r[0]}] {r[1]}\n  {r[2] or ''}\n  {r[3] or ''}" for r in rows) if rows else "Нет событий"

    lz_prompt = get_dept_prompt("lz")
    analysis_prompt = lz_prompt + "\n\nПроанализируй свежие события. Выдели тренды, аномалии, сигналы. Маркируй [ФАКТ], [ИНТЕРПРЕТАЦИЯ], [СПЕКУЛЯЦИЯ].\n\nПРАВИЛО ССЫЛОК: для КАЖДОГО упомянутого события/факта ОБЯЗАТЕЛЬНО включай прямую ссылку на источник в формате: Ссылка: https://...\nИспользуй ТОЛЬКО ссылки из предоставленных данных (строка Ссылка: ...). Если ссылка отсутствует в данных — не придумывай, просто укажи источник в квадратных скобках.\n\n" + news
    try:
        result = call_llm("lz", [{"role": "user", "content": analysis_prompt}])
        analysis = result.get("reply", "Ошибка анализа")
    except Exception as e:
        analysis = f"Ошибка: {e}"
    return jsonify({"response": analysis, "news_count": news.count("\n")})


# ── News stats ──
@app.route("/news/stats", methods=["GET"])
@require_telegram
def news_stats():
    total = _query("SELECT COUNT(*) FROM news_cache", fetch=True)[0][0]
    last_24h = _query("SELECT COUNT(*) FROM news_cache WHERE collected > datetime('now', '-24 hours')", fetch=True)[0][0]
    by_source = _query("SELECT source, COUNT(*) as c FROM news_cache GROUP BY source ORDER BY c DESC LIMIT 10", fetch=True)
    by_category = _query("SELECT category, COUNT(*) as c FROM news_cache GROUP BY category ORDER BY c DESC", fetch=True)
    return jsonify({"total": total, "last_24h": last_24h,
                    "by_source": {r[0]: r[1] for r in by_source},
                    "by_category": {r[0]: r[1] for r in by_category}})
