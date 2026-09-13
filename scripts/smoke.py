#!/usr/bin/env python3
"""Автоматический смок-тест офиса.

Отправляет боту сообщения через вебхук, читает журнал офиса и печатает
таблицу результатов. Ничего не требует от владельца.

Запуск:
    BASE_URL=https://fosved-office-v2.onrender.com \
    OWNER_ID=<telegram id> \
    BOT_TOKEN=<токен бота> \
    WEBHOOK_SECRET=<секрет вебхука, если задан> \
    CRON_SECRET=<секрет cron> \
    python3 scripts/smoke.py
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

BASE = os.environ.get("BASE_URL", "https://fosved-office-v2.onrender.com").rstrip("/")
OWNER = os.environ.get("OWNER_ID", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")
WAIT_SECONDS = int(os.environ.get("WAIT_SECONDS", "120"))
# SMOKE_LOCAL=1 — режим доступности для CI: офис поднят локально (llm_proxy.py
# с тестовыми env), реальные LLM-сценарии и cron новостей невозможны —
# проверяются только живость фасада и SEC-4 защита журнала.
SMOKE_LOCAL = os.environ.get("SMOKE_LOCAL", "") == "1"

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"  [{'ПРОЙДЕНО' if ok else 'НЕ ПРОЙДЕНО'}] {name}" + (f" — {detail}" if detail else ""))


def make_init_data():
    """Собрать подписанную initData — так же, как это делает Telegram."""
    if not BOT_TOKEN or not OWNER:
        return ""
    data = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": int(OWNER), "first_name": "Smoke"}, separators=(",", ":")),
        "query_id": "SMOKE",
    }
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


INIT_DATA = make_init_data()


def http(method, path, body=None, headers=None, timeout=180, signed=False):
    url = path if path.startswith("http") else BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if signed and INIT_DATA:
        req.add_header("X-Telegram-Init-Data", INIT_DATA)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def audit(limit=60):
    code, body = http("GET", f"/audit/recent?limit={limit}", signed=True)
    if code != 200:
        return []
    try:
        return json.loads(body).get("entries", [])
    except Exception:
        return []


def send_message(text, update_id):
    payload = {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": int(time.time()),
            "chat": {"id": int(OWNER), "type": "private"},
            "from": {"id": int(OWNER), "is_bot": False, "first_name": "Smoke"},
            "text": text,
        },
    }
    headers = {}
    if WEBHOOK_SECRET:
        headers["X-Telegram-Bot-Api-Secret-Token"] = WEBHOOK_SECRET
    return http("POST", "/webhook/telegram", payload, headers, timeout=300)


def raw_of(entry):
    d = entry.get("details") or {}
    return str(d.get("raw", "")) if isinstance(d, dict) else str(d)


def wait_for(predicate, seconds, since_id):
    deadline = time.time() + seconds
    while time.time() < deadline:
        for e in audit():
            if e.get("id", 0) > since_id and predicate(e):
                return e
        time.sleep(5)
    return None


def check_sec4_no_data_without_signature():
    """SEC-4 инвариант: без валидной подписи данные журнала не отдаются.

    Фасад отвечает либо 403 (подпись есть, но невалидна), либо 200 с
    bootstrap-страницей (подписи нет вообще, SEC-4 отдаёт JS-заглушку).
    Инвариант один: в ответе НЕТ записей аудита.
    """
    code, body = http("GET", "/audit/recent?limit=1")
    leaked = '"entries"' in body
    ok = (code == 403 or (code == 200 and not leaked))
    record("журнал закрыт без подписи", ok and not leaked,
           f"код {code}" + (", данные НЕ утекли" if not leaked else ", УТЕЧКА данных"))

    code, body = http("GET", "/audit/recent?limit=1",
                      headers={"X-Telegram-Init-Data": "hash=deadbeef&auth_date=123"})
    record("журнал закрыт битой подписью", code == 403,
           f"код {code} (ожидался 403)")


def main_local():
    """Режим доступности для CI: офис поднят локально без реальных LLM/бота."""
    if not OWNER or not BOT_TOKEN:
        print("ОШИБКА: нужны OWNER_ID и BOT_TOKEN (совпадают с env фасада)")
        return 2

    print(f"Офис: {BASE} (локальный подъём, режим доступности)")
    print(f"Подпись initData: {'собрана' if INIT_DATA else 'НЕТ'}\n")

    print("Доступность:")
    code, _ = http("GET", "/health")
    record("/health отвечает", code == 200, f"код {code}")

    code, body = http("GET", "/audit/recent?limit=5", signed=True)
    entries_ok = code == 200 and '"entries"' in body
    record("журнал читается с подписью", entries_ok,
           f"код {code}" + ("" if entries_ok else ", JSON без entries"))

    check_sec4_no_data_without_signature()

    code, _ = http("GET", "/news/stats", signed=True)
    record("/news/stats отвечает", code == 200, f"код {code}")

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"ИТОГ: {passed} из {total} проверок пройдено")
    if passed < total:
        print("\nНе пройдено:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}: {detail}")
    print("=" * 60)
    return 0 if passed == total else 1


def scenario(title, text, stamp, suffix, base_id):
    print(f"\n{title}:")
    code, _ = send_message(text, stamp * 10 + suffix)
    record("вебхук принял сообщение", code == 200, f"код {code}")
    hit = wait_for(lambda e: e.get("action") == "dept_query" and f"smoke {stamp}" in raw_of(e),
                   WAIT_SECONDS, base_id)
    record("запрос дошёл до модели", hit is not None,
           raw_of(hit)[:70] if hit else "записи dept_query не появилось")


def main():
    if SMOKE_LOCAL:
        return main_local()

    if not OWNER or not BOT_TOKEN:
        print("ОШИБКА: нужны OWNER_ID и BOT_TOKEN")
        return 2

    print(f"Офис: {BASE}")
    print(f"Подпись initData: {'собрана' if INIT_DATA else 'НЕТ'}")
    print(f"Секрет вебхука: {'задан' if WEBHOOK_SECRET else 'не задан'}\n")

    print("Доступность:")
    code, _ = http("GET", "/health")
    record("/health отвечает", code == 200, f"код {code}")

    code, _ = http("GET", "/audit/recent?limit=1", signed=True)
    record("журнал читается с подписью", code == 200, f"код {code}")
    if code != 200:
        print("\nБез доступа к журналу проверки сценариев невозможны.")
        print("Проверь OWNER_ID и BOT_TOKEN — они должны совпадать с настройками офиса.")
        return 1

    # SEC-4: без подписи фасад отдаёт bootstrap-страницу (200), с битой — 403;
    # инвариант безопасности один: данные журнала не отдаются.
    check_sec4_no_data_without_signature()

    code, _ = http("GET", "/news/stats", signed=True)
    record("/news/stats отвечает", code == 200, f"код {code}")

    base_id = max([e.get("id", 0) for e in audit()] or [0])
    stamp = int(time.time())

    scenario("Сценарий 1 — простой вопрос ассистенту",
             f"Привет, как дела? (smoke {stamp})", stamp, 1, base_id)

    base_id2 = max([e.get("id", 0) for e in audit()] or [base_id])
    scenario("Сценарий 2 — запрос в отдел",
             f"Сделай краткий обзор рынка труда (smoke {stamp})", stamp, 2, base_id2)

    print("\nНовостная подсистема:")
    if CRON_SECRET:
        code, body = http("GET", f"/cron/collect-news?secret={CRON_SECRET}", timeout=240)
        record("сбор новостей отработал", code == 200, f"код {code}, ответ {body[:80]}")
    else:
        record("сбор новостей", False, "пропущено: не задан CRON_SECRET")

    print("\nОшибки в журнале:")
    errs = [e for e in audit(80)
            if e.get("id", 0) > base_id and "error" in str(e.get("action", "")).lower()]
    record("новых ошибок нет", not errs,
           "; ".join(f"{e['action']}: {raw_of(e)[:60]}" for e in errs[:3]) if errs else "")

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"ИТОГ: {passed} из {total} проверок пройдено")
    if passed < total:
        print("\nНе пройдено:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}: {detail}")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
