#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#696 REA-3 A.1: ЛЗ-сенсор WebMCP — драйвер.

Пассивное обнаружение page-declared WebMCP-инструментов по фиксированному
списку доменов через `rea-agents discover-webmcp-tools` (CDP-домен WebMCP).
Выход — дайджест JSON+MD в /tmp и MD в stdout: домен, найденные
tool-декларации (имя/описание/вид), URL, дата (UTC), Evidence-id.

Список доменов — ДЕТЕРМИНИРОВАННЫЙ по правилам ADR-0003 (явный задокументи-
рованный список, сфера tech; расширение — правкой списка с обоснованием,
не молчаливо). Seed ADR-0003 задаёт правила (детерминированность, границы
сфер), не конкретные сайты: arXiv/HN/GitHub-источники ADR к WebMCP-страницам
неприменимы. Конкретный seed — ручной список наряда #696: модельные
провайдеры, agent-платформы, MCP-реестры.

Сенсор — поставщик кандидатов для watchlist-категории #566, НЕ вердикт:
триаж подтверждений по уставу ЛЗ (library/lz.md:31 — disruption alert
только при ≥3 независимых подтверждениях; 2/3 = кандидат, прецедент #566).

A.2 периодичность: еженедельное окно, РУЧНОЙ запуск (владелец/диспетчер):
  bash scripts/lz_webmcp_sensor.sh            # дайджест по 10 доменам
  bash scripts/lz_webmcp_sensor.sh --self-test  # функциональная проверка
Дайджест печатается в stdout и пишется в /tmp/lz_webmcp_<stamp>/digest.{md,json}
+ сырой Evidence по доменам. Автономизация (офисный cron / Actions-lane) —
вне границ наряда: config/waker_windows.txt удалён (a2293d1/#604),
start_crons.py гоняет только HTTP-эндпоинты приложения; вопрос зафиксирован
в отчёте наряда #696.

Робо-этика: только публичные входные страницы; 1 запрос на домен за прогон
(без перехода по ссылкам и без сабмитов); пауза ≥10 с между доменами
(LZ_WEBMCP_DELAY/--delay); таймауты ограничены; честный headless-UA;
без авторизации. invokeTool НЕ вызывается (метаданные тулов недоверенные).

Браузер: нужен CDP-домен WebMCP (Chrome 146+, origin trial с 149).
LZ_WEBMCP_BROWSER — путь к chrome-бинарю; по умолчанию chromium playwright.
Если у ВСЕХ доменов status=unavailable — браузер без WebMCP-домена:
поставьте Chrome for Testing 146+ и укажите LZ_WEBMCP_BROWSER.

Env: LZ_WEBMCP_BROWSER, LZ_WEBMCP_FLAGS (features), LZ_WEBMCP_DELAY (сек),
     LZ_WEBMCP_OUT (базовый каталог выхода, по умолчанию /tmp).
"""
import argparse
import datetime
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

REA_VERSION = "6.8.0"  # пин нарядов #694/#695/#696 — апгрейд осознанным коммитом

DEFAULT_FEATURES = (
    "WebMCP,DeclarativeWebMCP,WebMCPDeclarativeFileInput,"
    "WebMCPFormAssociatedCustomElements"
)

# Детерминированный список (наряд #696 A.1: ручной seed; правки — с обоснованием)
DEFAULT_DOMAINS = [
    # модельные провайдеры
    "openai.com",
    "anthropic.com",
    "mistral.ai",
    # agent-платформы
    "chatgpt.com",
    "claude.ai",
    "gemini.google.com",
    "cursor.com",
    # MCP-реестры
    "mcp.so",
    "smithery.ai",
    "glama.ai",
]

SELF_TEST_PAGE = """<!doctype html>
<html><head><title>webmcp-sensor-self-test</title></head><body>
<form toolname="sensorSelfTest"
      tooldescription="Self-test tool of the LZ WebMCP sensor (#696).">
  <input name="note" title="Note text">
</form>
</body></html>
"""


def utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── Чистые функции разбора/дайджеста (тестируются офлайн, без браузера) ──

def parse_discovery(raw_text):
    """Разбор JSON-конверта discover-webmcp-tools → компактная строка на домен.

    Возвращает dict: status, completeness, tools[], evidence_id, limitations.
    Никогда не бросает исключение на мусор — честная строка parse_error.
    """
    try:
        d = json.loads(raw_text)
    except Exception as e:
        return {"status": "parse_error", "completeness": "parse_error",
                "tools": [], "evidence_id": "",
                "error": f"{type(e).__name__}: {e}"}
    nr = (d or {}).get("normalized_result") or {}
    comp = nr.get("completeness") or {}
    tools_out = []
    for it in (nr.get("tools") or {}).get("items") or []:
        tools_out.append({
            "name": it.get("name"),
            "description": it.get("description"),
            "declaration_kind": it.get("declaration_kind"),
            "frame_url": it.get("frame_url"),
            "input_schema": it.get("input_schema"),
            "trust": it.get("trust"),
        })
    return {
        "status": nr.get("status"),
        "completeness": comp.get("status"),
        "unavailable_reason": ((comp.get("excluded") or [{}])[0].get("reason")
                               if comp.get("excluded") else None),
        "tools": tools_out,
        "evidence_id": d.get("evidence_id", ""),
    }


def find_target_id(list_json, needles):
    """target_id из конверта list-browser-targets.

    needles — список строк (финальный URL страницы и/или домен): ищем первый
    target, чей URL начинается с финального URL (www/редирект внутри домена)
    или содержит домен (кросс-доменный редирект — сканируем итоговую страницу,
    честно фиксируя её URL в дайджесте).
    """
    if isinstance(needles, str):
        needles = [needles]
    try:
        d = json.loads(list_json) if isinstance(list_json, str) else list_json
    except Exception:
        return None
    targets = ((d.get("normalized_result") or {}).get("targets") or [])
    # проход 1: точное начало URL (финальная страница)
    for n in needles:
        if not n or "://" not in n:
            continue
        for t in targets:
            if str(t.get("url", "")).startswith(n):
                return t.get("target_id")
    # проход 2: вхождение домена
    for n in needles:
        if not n or "://" in n:
            continue
        for t in targets:
            if n in str(t.get("url", "")):
                return t.get("target_id")
    return None


def build_digest(rows, meta):
    """Дайджест из строк доменов: (md_text, json_dict). Строки — уже собранные
    dicts: domain, url, final_url, title, http_status, load_error,
    status, completeness, tools[], evidence_id."""
    stamp = meta["stamp"]
    lines = []
    lines.append(f"# ЛЗ-сенсор WebMCP — дайджест {stamp}")
    lines.append("")
    lines.append(f"- Дата (UTC): {stamp}")
    lines.append(f"- Инструмент: rea-agents@{REA_VERSION} discover-webmcp-tools "
                 f"(пассивное наблюдение; invokeTool не вызывается)")
    lines.append(f"- Браузер: {meta.get('browser_version', '?')} — {meta.get('browser_path', '?')}")
    lines.append(f"- Флаги: {meta.get('features', '?')}")
    lines.append(f"- Робо-этика: 1 запрос/домен (только входная страница), "
                 f"пауза {meta.get('delay', '?')} с между доменами, без авторизации, "
                 f"честный headless-UA")
    n_ok = sum(1 for r in rows if not r.get("load_error") and r.get("status") == "available")
    n_err = sum(1 for r in rows if r.get("load_error"))
    n_tools = sum(1 for r in rows if r.get("tools"))
    n_unavail = sum(1 for r in rows
                    if not r.get("load_error") and r.get("status") != "available")
    lines.append(f"- Доменов: {len(rows)} · наблюдение available: {n_ok} · "
                 f"с WebMCP-декларациями: {n_tools} · ошибок загрузки: {n_err} · "
                 f"provider_unavailable: {n_unavail}")
    lines.append("")
    for r in rows:
        lines.append(f"## {r['domain']}")
        lines.append("")
        url = r.get("final_url") or r.get("url") or ""
        if r.get("load_error"):
            lines.append(f"- URL: {r.get('url', '')} — ОШИБКА ЗАГРУЗКИ: "
                         f"{r['load_error'][:200]}")
            lines.append("- Декларации: проверка невозможна (страница не открылась)")
        else:
            if url and url != r.get("url"):
                lines.append(f"- URL: {r.get('url', '')} → {url} "
                             f"(HTTP {r.get('http_status', '?')})")
            else:
                lines.append(f"- URL: {url} (HTTP {r.get('http_status', '?')})")
            if r.get("title"):
                lines.append(f"- Страница: «{r['title'][:120]}»")
            st = r.get("status")
            lines.append(f"- Наблюдение: status={st}, completeness={r.get('completeness')}"
                         + (f" (reason={r.get('unavailable_reason')})" if r.get("unavailable_reason") else ""))
            tools = r.get("tools") or []
            if tools:
                lines.append(f"- Найдено WebMCP-деклараций: {len(tools)}")
                lines.append("")
                lines.append("| Тул | Вид | Описание | frame URL | trust |")
                lines.append("|---|---|---|---|---|")
                for t in tools:
                    desc = (t.get("description") or "")[:140].replace("|", "\\|")
                    lines.append(f"| {t.get('name')} | {t.get('declaration_kind')} "
                                 f"| {desc} | {t.get('frame_url')} | {t.get('trust')} |")
            else:
                lines.append("- Найдено WebMCP-деклараций: 0"
                             + (" — браузер без CDP-домена WebMCP (нужен Chrome 146+)"
                                if st == "unavailable" else ""))
        if r.get("evidence_id"):
            lines.append(f"- Evidence: `{r['evidence_id']}`")
        lines.append("")
    lines.append("---")
    lines.append("Кандидаты в watchlist #566 — только домены с ≥1 декларацией. "
                 "Триаж — по уставу ЛЗ (library/lz.md:31, ≥3 независимых "
                 "подтверждений): сенсор — поставщик фактов, не вердикт.")
    md = "\n".join(lines) + "\n"

    digest_json = {
        "kind": "lz-webmcp-sensor-digest",
        "naryad": 696,
        "stamp_utc": stamp,
        "tool": f"rea-agents@{REA_VERSION} discover-webmcp-tools",
        "browser": {"path": meta.get("browser_path"),
                    "version": meta.get("browser_version"),
                    "features": meta.get("features")},
        "ethics": {"pages_per_domain": 1, "delay_seconds": meta.get("delay"),
                   "auth": "none", "user_agent": "headless-default"},
        "summary": {"domains": len(rows), "observed_available": n_ok,
                    "with_declarations": n_tools, "load_errors": n_err,
                    "provider_unavailable": n_unavail},
        "domains": rows,
    }
    return md, digest_json


# ── Рантайм (браузер/rea) — импорт playwright лениво, только внутри run ──

def resolve_browser():
    """Путь к браузеру: LZ_WEBMCP_BROWSER или chromium playwright."""
    env = os.environ.get("LZ_WEBMCP_BROWSER")
    if env:
        return env, "env:LZ_WEBMCP_BROWSER"
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        return pw.chromium.executable_path, "playwright:chromium"


def wait_cdp(endpoint, timeout_s=30):
    for _ in range(int(timeout_s * 2)):
        try:
            with urllib.request.urlopen(f"{endpoint}/json/version", timeout=2) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(0.5)
    return None


def run_rea(args, timeout=300):
    """Вызов rea-agents CLI. Возвращает (rc, stdout, stderr)."""
    cmd = ["npx", "-y", f"rea-agents@{REA_VERSION}", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def run(domains, out_base, delay_s, observation_ms, settle_ms,
        goto_timeout_ms, command_timeout_ms, self_test=False):
    # Ленивые импорты: модуль должен импортироваться в pytest без playwright
    from playwright.sync_api import sync_playwright

    browser_path, browser_src = resolve_browser()
    if not os.path.exists(browser_path):
        print(f"FAIL: браузер не найден: {browser_path} ({browser_src}). "
              f"Установите (python3 -m playwright install chromium) или задайте "
              f"LZ_WEBMCP_BROWSER=<путь к chrome 146+>", file=sys.stderr)
        return 2

    features = os.environ.get("LZ_WEBMCP_FLAGS", DEFAULT_FEATURES)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(out_base, f"lz_webmcp_{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    raw_dir = os.path.join(out_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    # Локальная страница для --self-test
    local_server = None
    if self_test:
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from threading import Thread

        page_bytes = SELF_TEST_PAGE.encode("utf-8")

        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(page_bytes)

            def log_message(self, *a):
                pass

        local_server = HTTPServer(("127.0.0.1", 0), _H)
        port = local_server.server_address[1]
        import threading
        threading.Thread(target=local_server.serve_forever, daemon=True).start()
        domains = [f"127.0.0.1:{port}"]
        print(f"[self-test] локальная страница с декларацией: "
              f"http://127.0.0.1:{port}/")

    cdp_port = _free_port()
    endpoint = f"http://127.0.0.1:{cdp_port}"
    proc = subprocess.Popen([
        browser_path, "--headless", "--no-sandbox", "--disable-gpu",
        "--disable-dev-shm-usage",
        f"--enable-features={features}",
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={out_dir}/chrome_profile",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    rows = []
    rc = 0
    try:
        ver = wait_cdp(endpoint)
        if not ver:
            print(f"FAIL: CDP-эндпойнт {endpoint} не поднялся", file=sys.stderr)
            return 2
        browser_version = ver.get("Browser", "?")
        print(f"Браузер: {browser_version} ({browser_path}, {browser_src})",
              file=sys.stderr)

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(endpoint)
            ctx = browser.contexts[0]
            for i, domain in enumerate(domains):
                scheme = "http" if domain.startswith("127.0.0.1:") else "https"
                url = f"{scheme}://{domain}/"
                row = {"domain": domain, "url": url, "final_url": None,
                       "title": None, "http_status": None, "load_error": None,
                       "status": None, "completeness": None,
                       "unavailable_reason": None, "tools": [],
                       "evidence_id": "", "observed_at_utc": utc_now_iso()}
                page = ctx.new_page()
                try:
                    resp = page.goto(url, timeout=goto_timeout_ms,
                                     wait_until="domcontentloaded")
                    row["http_status"] = resp.status if resp else None
                    page.wait_for_timeout(settle_ms)
                    row["final_url"] = page.url
                    try:
                        row["title"] = page.title()
                    except Exception as e:
                        row["title"] = f"(title error: {type(e).__name__})"
                except Exception as e:
                    row["load_error"] = f"{type(e).__name__}: {e}"
                finally:
                    pass

                if not row["load_error"]:
                    # targetId через rea list-browser-targets (наряд: «Target ID
                    # from list-browser-targets»)
                    rc_l, out_l, _err_l = run_rea(
                        ["list-browser-targets", endpoint, "--format", "json"])
                    raw_tag = domain.replace(":", "_").replace(".", "_")
                    with open(os.path.join(raw_dir, f"{raw_tag}_targets.json"),
                              "w") as f:
                        f.write(out_l)
                    tid = (find_target_id(out_l, [row["final_url"], domain])
                           if rc_l == 0 else None)
                    if not tid:
                        row["status"] = "no_target"
                        row["completeness"] = "no_target"
                        row["unavailable_reason"] = (
                            "target для домена не найден (редирект на другой "
                            "домен или не-страничный target)")
                    else:
                        rc_d, out_d, _err_d = run_rea(
                            ["discover-webmcp-tools", endpoint, tid,
                             "--observation-ms", str(observation_ms),
                             "--command-timeout-ms", str(command_timeout_ms),
                             "--format", "json"])
                        with open(os.path.join(raw_dir, f"{raw_tag}_webmcp.json"),
                                  "w") as f:
                            f.write(out_d)
                        parsed = parse_discovery(out_d if rc_d == 0 else "{}")
                        row.update(parsed)
                        if rc_d != 0 and parsed["status"] == "parse_error":
                            row["load_error"] = (
                                f"discover-webmcp-tools rc={rc_d}")
                rows.append(row)
                n_tools = len(row.get("tools") or [])
                note = (f"{n_tools} декл." if not row["load_error"]
                        else f"ошибка: {row['load_error'][:60]}")
                print(f"[{i + 1}/{len(domains)}] {domain} — {note}",
                      file=sys.stderr)
                try:
                    page.close()
                except Exception:
                    pass
                if i < len(domains) - 1 and delay_s > 0:
                    time.sleep(delay_s)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        if local_server:
            local_server.shutdown()

    meta = {"stamp": utc_now_iso(), "browser_path": browser_path,
            "browser_version": browser_version if rows else "?",
            "features": features, "delay": delay_s}
    md, digest_json = build_digest(rows, meta)

    md_path = os.path.join(out_dir, "digest.md")
    json_path = os.path.join(out_dir, "digest.json")
    with open(md_path, "w") as f:
        f.write(md)
    with open(json_path, "w") as f:
        json.dump(digest_json, f, ensure_ascii=False, indent=1)

    print(f"\nДайджест: {md_path}\nJSON: {json_path}\nСырой Evidence: {raw_dir}/\n",
          file=sys.stderr)
    print(md)

    # Подсказка при тотальном provider_unavailable (браузер без CDP WebMCP)
    if rows and all(r.get("status") in ("unavailable", None) or r.get("load_error")
                    for r in rows):
        print("ВНИМАНИЕ: ни один домен не дал status=available — вероятно, "
              "браузер без CDP-домена WebMCP (нужен Chrome 146+/149+; "
              "задайте LZ_WEBMCP_BROWSER). См. сырой Evidence в raw/.",
              file=sys.stderr)

    if self_test:
        ok = rows and len(rows[0].get("tools") or []) >= 1
        print(f"[self-test] {'OK — декларация обнаружена' if ok else 'FAIL — декларация НЕ обнаружена'}",
              file=sys.stderr)
        return 0 if ok else 1
    return rc


def main(argv=None):
    p = argparse.ArgumentParser(
        description="ЛЗ-сенсор WebMCP (#696 REA-3): пассивное обнаружение "
                    "page-declared WebMCP-инструментов")
    p.add_argument("--domains", help="список доменов через запятую "
                                     "(по умолчанию — детерминированный список наряда)")
    p.add_argument("--self-test", action="store_true",
                   help="функциональная проверка на локальной странице "
                        "с WebMCP-декларацией (без внешней сети)")
    p.add_argument("--delay", type=int,
                   default=int(os.environ.get("LZ_WEBMCP_DELAY", "10")),
                   help="пауза между доменами, сек (default: 10, робо-этика)")
    p.add_argument("--observation-ms", type=int, default=3000)
    p.add_argument("--settle-ms", type=int, default=2500)
    p.add_argument("--goto-timeout-ms", type=int, default=45000)
    p.add_argument("--command-timeout-ms", type=int, default=60000)
    p.add_argument("--out", default=os.environ.get("LZ_WEBMCP_OUT", "/tmp"),
                   help="базовый каталог выхода (default: /tmp)")
    args = p.parse_args(argv)

    if args.self_test and args.domains:
        print("FAIL: --self-test и --domains несовместимы", file=sys.stderr)
        return 2
    domains = ([d.strip() for d in args.domains.split(",") if d.strip()]
               if args.domains else list(DEFAULT_DOMAINS))
    if not domains:
        print("FAIL: пустой список доменов", file=sys.stderr)
        return 2

    return run(domains, args.out, args.delay, args.observation_ms,
               args.settle_ms, args.goto_timeout_ms, args.command_timeout_ms,
               self_test=args.self_test)


if __name__ == "__main__":
    sys.exit(main())
