#!/usr/bin/env python3
"""
FOSVED Office v2 — Cron Starter
Запускает новостной сбор и ЛЗ-скан вручную или по расписанию.

Использование:
  python3 start_crons.py              # один раз: собрать новости + ЛЗ скан
  python3 start_crons.py --loop       # бесконечный цикл каждые 30 мин
  python3 start_crons.py --interval 60  # каждые 60 минут
  python3 start_crons.py --news-only  # только новости (без ЛЗ)
  python3 start_crons.py --lz-only    # только ЛЗ скан
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
import urllib.parse
import argparse

# ── Конфигурация ──────────────────────────────────────────────────────────
# Если llm_proxy.py запущен локально:
BASE_URL = os.environ.get("FOSVED_URL", "http://localhost:10000")
CRON_SECRET = os.environ.get("CRON_SECRET", "")

# Таймауты
NEWS_TIMEOUT = 30   # секунд на сбор RSS+GDELT
LZ_TIMEOUT = 120    # секунд на ЛЗ скан + LLM анализ


def call_endpoint(url, timeout, label):
    """Вызвать эндпоинт и вернуть результат."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            print(f"  ✅ {label}: {json.dumps(data, ensure_ascii=False)[:200]}")
            return data
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200] if e.fp else ""
        print(f"  ❌ {label}: HTTP {e.code} — {body}")
        return None
    except urllib.error.URLError as e:
        print(f"  ❌ {label}: {e.reason}")
        return None
    except Exception as e:
        print(f"  ❌ {label}: {e}")
        return None


def run_news():
    """Собрать новости: RSS + GDELT (бесплатно, без ключей)."""
    print("\n📡 Сбор новостей (RSS + GDELT)...")
    # №425: секрет может содержать '+'/%XX — в URL только percent-кодировкой
    # (Flask и mlog 0.21 декодируют query; сырая вставка ломает сравнение)
    url = f"{BASE_URL}/cron/collect-news?secret={urllib.parse.quote(CRON_SECRET, safe='')}"
    return call_endpoint(url, NEWS_TIMEOUT, "News collect")


def run_lz():
    """Запустить ЛЗ daily: GitHub scan + LLM анализ."""
    print("\n🔍 ЛЗ Daily Report (GitHub scan)...")
    # /scheduler/lz-daily — POST, нужен JSON body
    url = f"{BASE_URL}/scheduler/lz-daily"
    try:
        body = json.dumps({"dry_run": False}).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=LZ_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            print(f"  ✅ LZ Daily: {json.dumps(data, ensure_ascii=False)[:300]}")
            return data
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200] if e.fp else ""
        print(f"  ❌ LZ Daily: HTTP {e.code} — {body}")
        return None
    except Exception as e:
        print(f"  ❌ LZ Daily: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="FOSVED Cron Starter")
    parser.add_argument("--loop", action="store_true", help="Бесконечный цикл")
    parser.add_argument("--interval", type=int, default=30, help="Интервал в минутах (default: 30)")
    parser.add_argument("--news-only", action="store_true", help="Только новости")
    parser.add_argument("--lz-only", action="store_true", help="Только ЛЗ скан")
    parser.add_argument("--url", type=str, help="Base URL (default: http://localhost:10000)")
    args = parser.parse_args()

    global BASE_URL
    if args.url:
        BASE_URL = args.url

    run_once = not args.loop

    iteration = 0
    while True:
        iteration += 1
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'═' * 60}")
        print(f"  FOSVED Cron — итерация {iteration}  [{ts}]")
        print(f"  URL: {BASE_URL}")
        print(f"{'═' * 60}")

        if not args.lz_only:
            run_news()

        if not args.news_only:
            run_lz()

        if run_once:
            break

        print(f"\n⏳ Следующий запуск через {args.interval} мин...")
        try:
            time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            print("\n\n🛑 Остановлено пользователем.")
            break


if __name__ == "__main__":
    main()
