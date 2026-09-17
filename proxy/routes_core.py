"""FO-008: транспорт ч.1 — оригинальные эндпоинты прокси (health..extract-document).

Вырезано из llm_proxy.py вербатим (стренглер, шаг 4a; наряд #68, стоп-гейт SG-F2).
"""
import os
import re
import json
import time
import uuid
import hashlib
import html as html_lib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import doc_extract

from flask import request, jsonify, Response

from proxy.core import (
    app, log, http_requests,
    _query, _log_audit, _log_error, _write_llm_trace, _get_setting,
    get_secret, set_secret, delete_secret, _has_db_override, INTEGRATIONS_REGISTRY,
    DB_PATH, DB_FILE, BASE_DIR, LIB_DIR, CFG_DIR, API_SECRET,
    TELEGRAM_BOT_TOKEN, TELEGRAM_ARCHIVE_CHANNEL_ID,
    memory, require_telegram, _TG_BOOTSTRAP_PAGE, _verify_init_data, _verify_webhook_secret,
    auto_enrich, _has_enricher, _auto_enrich_fn,
    detect_dept, get_dept_prompt, CONDENSED_PROMPTS, FORMAT_INSTRUCTION, COMMAND_DEPT,
    DEPT_COLORS, DEPT_NAMES, DEPT_HASHTAGS,
)
from proxy.providers import (
    PROVIDERS, TOKEN_COSTS, PROVIDER_MAX_TOKENS, COMBO_CHAINS,
    _breaker, _cfg_cache, call_llm, _call_single_provider, _generate_image,
    _IMG_DIR, _ALLOWED_SIZES,
)
from proxy.telegram import (
    tg_status, tg_send_long, tg_split_long,
    _MARKER_EMOJI, _ALL_EMOJI, _escape_mdv2, _tg_send_formatted,
    _tg_send_message, _tg_send_voice, _tg_send_report_with_button,
    _tg_get_file, _tg_download_file, _tg_send_photo, _tg_send_document,
    _safe_filename_part, _send_chat_action_loop, _tg_send_chat_action,
)
from proxy.reports import (
    html_lib_escape, strip_html_for_archive, _html_base, _dept_header,
    _status_icon, _dept_kpis, _build_action_bar, ARCHIVE_MONTHS_RU,
    _browse_page, _evidence_badges_css,
)

# ══════════════════════════════════════════════════════════════════════
#  ROUTES — ORIGINAL ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    # FO-022: failure buckets за 24 ч (из трейсов FO-004, переживают рестарт)
    # + активные квотные кулдауны 429 + long-cooldown (notFound/forbidden).
    from proxy.resilience import buckets_last_24h, quota_status, provider_long_cooldown
    from proxy.providers import PROVIDERS as _PROV_ALL
    cooldowns = {}
    for p in _PROV_ALL:
        reason = provider_long_cooldown(p)
        if reason:
            cooldowns[p] = reason
    return jsonify({
        "status": "ok",
        "circuit_breaker": _breaker.status(),
        "combos": list(COMBO_CHAINS.keys()),
        "failure_buckets_24h": buckets_last_24h(),
        "quota_cooldowns": quota_status(),
        "provider_cooldowns": cooldowns,
    })

# ── FO-037 C.1: статическое превью (файлы из репозитория напрямую, без процессов) ──
# Query-роут (§9 ТЗ: path-стиль /preview/<project>/<repo>/<path> не работает
# на exact-match диспетчере mlog — v1 query-эквивалент, перевод после №283).
_PREVIEW_MIME = {
    "html": "text/html; charset=utf-8", "htm": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8", "js": "application/javascript; charset=utf-8",
    "mjs": "application/javascript; charset=utf-8", "json": "application/json; charset=utf-8",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "svg": "image/svg+xml", "ico": "image/x-icon", "txt": "text/plain; charset=utf-8",
    "md": "text/plain; charset=utf-8", "pdf": "application/pdf", "webp": "image/webp",
}
_PREVIEW_PATH_RE = re.compile(r"^[a-zA-Z0-9._/-]+$")

@app.get("/preview")
def preview_file():
    """Статическое превью файла из FORGE-репозитория: git show из bare,
    без процессов, без сети. Protected (C.2). Контент-Type по расширению."""
    import subprocess
    project = request.args.get("project", "")
    repo = request.args.get("repo", "")
    path = request.args.get("path", "")
    ref = request.args.get("ref", "main")
    if not re.match(r"^[a-z0-9-]{2,40}$", project) or not re.match(r"^[a-z0-9-]{2,40}$", repo):
        return jsonify({"error": "invalid project/repo"}), 400
    if not path or len(path) > 400 or path.startswith("/") or ".." in path or not _PREVIEW_PATH_RE.match(path):
        return jsonify({"error": "invalid path"}), 400
    if not re.match(r"^[a-zA-Z0-9._/~^-]{1,120}$", ref) or ref.startswith("-"):
        return jsonify({"error": "invalid ref"}), 400
    repos_dir = os.environ.get("FORGE_REPOS_DIR", "/var/forge/repos")
    bare = os.path.join(repos_dir, "forge", "repos", f"{repo}.git")
    if not os.path.isdir(bare):
        return jsonify({"error": "repo not found"}), 404
    try:
        res = subprocess.run(
            ["git", "-C", bare, "show", f"{ref}:{path}"],
            capture_output=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "git timeout"}), 504
    if res.returncode != 0:
        return jsonify({"error": "file not found"}), 404
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    mime = _PREVIEW_MIME.get(ext, "application/octet-stream")
    return Response(res.stdout, mimetype=mime.split(";")[0], headers={"Content-Type": mime})

@app.get("/now-time")
def now_time_endpoint():
    """Return current date/time in human-readable form for Yana prompt injection.
    Timezone: Europe/Minsk (UTC+3 year-round) — configured via TZ env var."""
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo("Europe/Minsk")
    except Exception:
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    weekdays_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    months_ru = ["января", "февраля", "марта", "апреля", "мая", "июня",
                  "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    human = (f"{now.day} {months_ru[now.month-1]} {now.year}, "
             f"{weekdays_ru[now.weekday()]}, "
             f"{now.strftime('%H:%M')}")
    return jsonify({"time": human, "iso": now.isoformat(), "unix": now.timestamp()})

# ── Weather cache (30 min) ──
_weather_cache = {"text": "", "ts": 0.0}

@app.get("/now-weather")
def now_weather_endpoint():
    """Return current weather for Minsk. Cached 30 min."""
    import time as _time
    now = _time.time()
    if _weather_cache["text"] and (now - _weather_cache["ts"]) < 1800:
        return jsonify({"weather": _weather_cache["text"]})
    try:
        r1 = http_requests.get("https://wttr.in/Minsk?format=%C+%t+%w+%h&lang=ru", timeout=10)
        r2 = http_requests.get("https://wttr.in/Minsk?format=3&lang=ru", timeout=10)
        parts = []
        if r1.ok:
            parts.append(r1.text.strip())
        if r2.ok:
            parts.append(r2.text.strip())
        weather = " | ".join(parts) if parts else "Погода недоступна"
    except Exception:
        weather = "Погода недоступна"
    _weather_cache["text"] = weather
    _weather_cache["ts"] = now
    return jsonify({"weather": weather})

@app.post("/detect-dept")
def detect_dept_endpoint():
    d = request.get_json(force=True)
    text = d.get("text", "")
    dept = detect_dept(text)
    return jsonify({"dept": dept})

@app.post("/ask")
def ask():
    d = request.get_json(force=True)
    dept = d.get("dept", "yana")
    messages = d.get("messages", [])
    model_ov = d.get("model")
    # DEBUG: log system prompt to find FORMAT_INSTRUCTION source
    for m in messages:
        if m.get("role") == "system":
            sys_text = m.get("content", "")
            has_format = "ФОРМАТ ОТВЕТА" in sys_text or "Слой 1" in sys_text
            log.info(f"ASK dept={dept} sys_len={len(sys_text)} has_format={has_format} first200={sys_text[:200]}")
            if has_format:
                # Find exactly where FORMAT_INSTRUCTION appears
                idx = sys_text.find("ФОРМАТ ОТВЕТА")
                if idx < 0: idx = sys_text.find("Слой 1")
                log.info(f"FORMAT found at char {idx}, context: ...{sys_text[max(0,idx-50):idx+100]}...")
    if not messages:
        return jsonify({"reply": "[Oshibka] Net soobshenii", "provider": None, "model": None, "tokens_in": 0, "tokens_out": 0}), 400

    # FO-013 фаза 1: жизнь в чате в первые 2 секунды — typing сразу после
    # приёма задачи + статус маршрутизации (анти-спам внутри tg_status).
    chat_id = d.get("chat_id") or d.get("user_id") or ""
    stop_typing = None
    if chat_id:
        try:
            stop_typing = _send_chat_action_loop(str(chat_id))
        except Exception as e:
            _log_error(f"typing loop start failed: {e}", source="ask", kind="external")
        tg_status(chat_id, f"Маршрутизирую в {DEPT_NAMES.get(dept, dept)}…", dept=dept)

    try:
        # FO-016: chat_id пробрасывается — компакция пишет запись-заготовку
        # Part #83 ({"part_type":"compaction"}) в dialog_history
        result = call_llm(dept, messages, model_ov, chat_id=chat_id)
    finally:
        if stop_typing is not None:
            stop_typing.set()
    if dept == "osp" and "reply" in result:
        import re as _re
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        try:
            _tz = _ZI("Europe/Minsk")
        except Exception:
            _tz = _ZI("UTC")
        _today = _dt.now(_tz).strftime("%Y-%m-%d")
        _reply = result["reply"]
        _reply = _re.sub(
            r'(Дата препарирования:\s*)\d{4}-\d{2}-\d{2}',
            r'\g<1>' + _today, _reply
        )
        _reply = _re.sub(
            r'(Сейчас:\s*)\d{4}-\d{2}-\d{2}',
            r'\g<1>' + _today, _reply
        )
        _reply = _re.sub(
            r'(Темпоральная якорная точка:\s*Сейчас:\s*)\d{4}-\d{2}-\d{2}',
            r'\g<1>' + _today, _reply
        )
        result["reply"] = _reply
    return jsonify(result)

@app.post("/rate_cmd")
def rate_cmd():
    d = request.get_json(force=True)
    dept, rating = d.get("dept", "yana"), d.get("rating", 0)
    _query("INSERT INTO dept_metrics (dept,metric_name,metric_value,period,created_at) VALUES (?,'satisfaction',?,?,?)", (dept, str(rating), 'daily', datetime.utcnow().isoformat()))
    return jsonify({"status": "ok"})

@app.post("/context_cmd")
def context_cmd():
    d = request.get_json(force=True)
    dept, chat_id = d.get("dept", "yana"), d.get("chat_id", "0")
    rows = _query("SELECT role,content,created_at FROM dialog_history WHERE dept=? AND chat_id=? ORDER BY id DESC LIMIT 20", (dept, chat_id), fetch=True)
    corrs = _query("SELECT original_query,correction,created_at FROM adapt_corrections WHERE dept=? ORDER BY id DESC LIMIT 10", (dept,), fetch=True)
    # FO-006: консолидированные факты — первичный источник памяти (журнал — для связности диалога)
    fact_rows = _query("SELECT content, confidence, updated_at FROM facts WHERE dept=? AND status='active' ORDER BY updated_at DESC LIMIT 15", (dept,), fetch=True)
    ctx = {"dialog": [{"role": r["role"], "content": r["content"], "ts": r["created_at"]} for r in reversed(rows)]}
    ctx["corrections"] = [{"original": r["original_query"], "corrected": r["correction"], "ts": r["created_at"]} for r in corrs]
    ctx["facts"] = [{"content": r["content"], "confidence": r["confidence"], "ts": r["updated_at"]} for r in fact_rows]
    return jsonify(ctx)

@app.post("/voice-set")
def voice_set():
    d = request.get_json(force=True)
    _log_audit("voice_set", d)
    return jsonify({"status": "ok"})

@app.post("/archive/digest")
def archive_digest():
    d = request.get_json(force=True)
    _log_audit("digest", d)
    return jsonify({"status": "ok", "digest_id": hashlib.md5(json.dumps(d).encode()).hexdigest()[:8]})



@app.get("/miniapp/<doc_id>")
@app.get("/miniapp/<doc_id>/")
@require_telegram
def miniapp_get(doc_id):
    try:
        return _miniapp_get_inner(doc_id)
    except Exception as e:
        log.error(f"miniapp_get crash for {doc_id}: {e}", exc_info=True)
        return f"<h1>Ошибка рендеринга</h1><p>{html_lib_escape(str(e))}</p><p>ID: {html_lib_escape(doc_id)}</p>", 500

def _miniapp_get_inner(doc_id):
    rows = _query("SELECT html,title,created_at,dept,raw_text FROM miniapp_responses WHERE id=?", (doc_id,), fetch=True)
    if not rows:
        return "<h1>Not found</h1>", 404
    r = rows[0]
    dept = r["dept"] or "admin"
    # Load notes for this doc
    notes_rows = _query("SELECT note_text, created_at FROM miniapp_notes WHERE doc_id=? ORDER BY id", (doc_id,), fetch=True) or []
    notes_html = "".join(f'<div class="note-item"><span>{html_lib_escape(n["note_text"])}</span><span class="note-time">{(n["created_at"] or "")[-8:-3]}</span></div>' for n in notes_rows)
    action_bar = _build_action_bar(dept, doc_id, notes_html)
    # Rich post-processor: enrich any non-trivial raw_text
    raw = r["raw_text"] or ""
    # GRAPH-1: вынимаем блок графика ДО auto_enrich — html_lib.escape внутри
    # него экранирует сырой SVG (< > становятся видимым текстом). Ставим
    # маркер-заглушку, который переживёт экранирование и обогащение
    # (буквы/цифры не трогаются), потом вернём настоящий SVG на его место.
    _chart_placeholder = None
    if "[[CHART]]" in raw and "[[/CHART]]" in raw:
        _cs = raw.index("[[CHART]]")
        _ce = raw.index("[[/CHART]]") + len("[[/CHART]]")
        _chart_placeholder = raw[_cs:_ce]
        raw = raw[:_cs] + "GRAPHONECHARTPLACEHOLDER" + raw[_ce:]
    if raw and len(raw) > 100 and _has_enricher:
        accent = DEPT_COLORS.get(dept, {}).get("accent", "#A8321E")
        try:
            enriched_body = auto_enrich(raw, dept=dept, accent_color=accent)
            if _chart_placeholder:
                enriched_body = enriched_body.replace("GRAPHONECHARTPLACEHOLDER", _chart_placeholder)
        except Exception as e:
            log.warning(f"miniapp enrich failed for {doc_id}: {e}")
            enriched_body = None
        if enriched_body and len(enriched_body) > len(raw) * 0.5:
            # Rebuild full HTML with enriched body
            css_path = BASE_DIR / "report_css.txt"
            css = css_path.read_text() if css_path.exists() else ""
            c = DEPT_COLORS.get(dept, DEPT_COLORS["admin"])
            name = DEPT_NAMES.get(dept, dept)
            title = r["title"] or doc_id
            created = r["created_at"] or ""
            disclaimer = ""
            if dept == "finance":
                disclaimer = '<div class="disclaimer-rich">Не является финансовой консультацией. Обратитесь к лицензированному специалисту.</div>'
            elif dept == "legal":
                disclaimer = '<div class="disclaimer-rich">Не является юридической консультацией. Обратитесь к лицензированному юристу.</div>'
            elif dept == "engineering":
                disclaimer = '<div class="disclaimer-rich">Требует review лицензированного инженера. Не использовать для строительства без проверки.</div>'
            # GRAPH-1: replace [[CHART]]/[[/CHART]] markers with styled div
            enriched_body = enriched_body.replace('[[CHART]]', '<div class="report-chart">').replace('[[/CHART]]', '</div>')
            html = f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>{css}
body {{ font-family:var(--b,'IBM Plex Sans',system-ui,sans-serif); color:var(--ink,#1C1B18); background:var(--paper,#EFEAE0); margin:0; }}
</style></head><body>
<div class="report-container">
<div class="report-header" style="background:linear-gradient(135deg,{c['start']},{c['end']})">
  <h1>{html_lib_escape(name)}</h1>
  <div class="subtitle">{html_lib_escape(title)}</div>
</div>
<div class="report-meta"><span>ID: {html_lib_escape(doc_id)}</span><span>{html_lib_escape(created)}</span></div>
<div class="report-body">{enriched_body}</div>
{disclaimer}
{action_bar}
</div></body></html>'''
            html = html.replace('{{API_SECRET}}', API_SECRET)
            return Response(html, mimetype="text/html")
    # Fallback: return stored HTML with action bar injected
    stored_html = r["html"] or ""
    if not stored_html:
        # No stored HTML at all — render raw_text as plain HTML
        raw_fallback = r["raw_text"] or "Отчёт пуст"
        stored_html = f'''<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://telegram.org/js/telegram-web-app.js"></script></head><body>
<div style="padding:16px;font-family:sans-serif;color:#1C1B18;white-space:pre-wrap">{html_lib_escape(raw_fallback)}</div>
{action_bar}</body></html>'''
    # GRAPH-1: replace [[CHART]]/[[/CHART]] markers in stored HTML too
    stored_html = stored_html.replace('[[CHART]]', '<div class="report-chart">').replace('[[/CHART]]', '</div>')
    if "</body>" in stored_html:
        stored_html = stored_html.replace("</body>", f"{action_bar}</body>")
    stored_html = stored_html.replace('{{API_SECRET}}', API_SECRET)
    return Response(stored_html, mimetype="text/html")




@app.get("/archive/browse")
@require_telegram
def archive_browse():
    """Browse archived reports: year -> month -> dept -> documents."""
    year = (request.args.get("year") or "").strip()
    month = (request.args.get("month") or "").strip()
    dept = (request.args.get("dept") or "").strip()
    # Preserve tgWebAppData across navigation inside Mini App
    tg = request.args.get("tgWebAppData", "")
    tg_suffix = ("tgWebAppData=" + html_lib.escape(tg, quote=True)) if tg else ""
    try:
        if not year:
            rows = _query(
                "SELECT substr(created_at,1,4) AS y, COUNT(*) AS n FROM miniapp_responses "
                "WHERE created_at IS NOT NULL AND created_at != '' GROUP BY y ORDER BY y DESC",
                (), fetch=True) or []
            items = [{"name": r["y"], "sub": f'{r["n"]} шт.',
                      "href": f'/archive/browse?year={r["y"]}'} for r in rows]
            return _browse_page("Архив", "Годы", items, "", tg_suffix)

        if not month:
            rows = _query(
                "SELECT substr(created_at,6,2) AS m, COUNT(*) AS n FROM miniapp_responses "
                "WHERE substr(created_at,1,4) = ? GROUP BY m ORDER BY m DESC",
                (year,), fetch=True) or []
            items = [{"name": ARCHIVE_MONTHS_RU.get(r["m"], r["m"]), "sub": f'{r["n"]} шт.',
                      "href": f'/archive/browse?year={year}&month={r["m"]}'} for r in rows]
            return _browse_page(year, "Месяцы", items, "/archive/browse", tg_suffix)

        if not dept:
            rows = _query(
                "SELECT dept, COUNT(*) AS n FROM miniapp_responses "
                "WHERE substr(created_at,1,4) = ? AND substr(created_at,6,2) = ? "
                "GROUP BY dept ORDER BY n DESC",
                (year, month), fetch=True) or []
            items = [{"name": r["dept"] or "—", "sub": f'{r["n"]} шт.',
                      "href": f'/archive/browse?year={year}&month={month}&dept={r["dept"]}'}
                     for r in rows]
            return _browse_page(f'{ARCHIVE_MONTHS_RU.get(month, month)} {year}', "Отделы",
                                items, f"/archive/browse?year={year}", tg_suffix)

        rows = _query(
            "SELECT id, title, created_at FROM miniapp_responses "
            "WHERE substr(created_at,1,4) = ? AND substr(created_at,6,2) = ? AND dept = ? "
            "ORDER BY created_at DESC",
            (year, month, dept), fetch=True) or []
        items = [{"name": (r["title"] or r["id"])[:80], "sub": (r["created_at"] or "")[:10],
                  "href": f'/miniapp/{r["id"]}'} for r in rows]
        return _browse_page(f'{dept} · {ARCHIVE_MONTHS_RU.get(month, month)} {year}',
                            "Отчёты", items,
                            f"/archive/browse?year={year}&month={month}", tg_suffix)
    except Exception as e:
        log.error(f"archive_browse error: {e}")
        return _browse_page("Архив", "Ошибка", [], "/archive/browse", tg_suffix), 500


@app.post("/miniapp/note")
def miniapp_note():
    d = request.get_json(force=True)
    _query("INSERT INTO miniapp_notes (doc_id,note_text,created_at) VALUES (?,?,?)",
           (d.get("doc_id", ""), d.get("note_text", ""), datetime.utcnow().isoformat()))
    return jsonify({"status": "ok"})

def _save_generated_report(dept, title, query, raw_text):
    """Создаёт новую запись miniapp_responses для результата кнопки action-bar
    (Журналист/Погружение/Контр-прогноз/Кризис-протокол). html оставляем
    пустым — _miniapp_get_inner сам обогатит raw_text через auto_enrich
    при первом открытии, тем же путём, что и обычные отчёты."""
    new_doc_id = f"doc-{time.time()}"
    _query(
        "INSERT INTO miniapp_responses (id, dept, title, query, raw_text, html, confidence, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (new_doc_id, dept, title, query, raw_text, "", "medium", datetime.utcnow().isoformat())
    )
    return new_doc_id


@app.post("/webhook/miniapp-action")
def miniapp_action():
    """Handle Mini App action bar button clicks (Journalist, Depth, Control, Counter)."""
    d = request.get_json(force=True)
    action = d.get("action", "")
    doc_id = d.get("doc_id", "")
    if not doc_id:
        return jsonify({"status": "error", "msg": "no doc_id"}), 400
    
    rows = _query("SELECT raw_text, title, dept FROM miniapp_responses WHERE id=?", (doc_id,), fetch=True)
    if not rows:
        return jsonify({"status": "error", "msg": "doc not found"}), 404
    r = rows[0]
    raw = r["raw_text"] or ""
    title = r["title"] or ""
    dept = r["dept"] or "osp"
    
    if action == "journalist":
        prompt = f"""Ты — журналист-аналитик. Перепиши следующий аналитический отчёт в формат журналистской статьи.
Без служебных реквизитов, без бейджей [ФАКТ]/[ИНТЕРПРЕТАЦИЯ]/[СПЕКУЛЯЦИЯ].
Живой язык, понятный обычному читателю. Лид-абзац + контекст + основная часть + вывод.
1000-1500 слов. Заголовок — яркий, журналистский."""
        messages = [{"role": "system", "content": get_dept_prompt("osp")}, {"role": "user", "content": prompt + "\n\nИсходный отчёт:\n" + raw}]
        result = call_llm("osp", messages)
        reply = result.get("reply", "")
        new_id = _save_generated_report(dept, f"Журналистская версия: {title}", "journalist", reply)
        return jsonify({"status": "ok", "reply": reply, "action": "journalist", "doc_id": new_id})
    
    elif action.startswith("deepen_to_"):
        level = action.split("_")[-1]
        depth_map = {"1": "Быстрая оценка. 2-3 слоя.", "2": "Стандартный анализ. 5-7 слоёв. ACH 3 гипотезы.",
                     "3": "Глубокое. 8-10 слоёв. ACH 5 гипотез. Premortem. Кантильоновский анализ.",
                     "4": "Полное + Red Team. 12+ слоёв. ACH, premortem, кантильон, source triangulation. Контраргументы."}
        instruction = depth_map.get(level, "Стандартный анализ.")
        messages = [{"role": "system", "content": get_dept_prompt("osp")}, {"role": "user", "content": instruction + "\n\nПредыдущий анализ:\n" + raw + "\n\nУглуби до уровня " + level}]
        result = call_llm("osp", messages)
        reply = result.get("reply", "")
        new_id = _save_generated_report(dept, f"Углублено (ур. {level}): {title}", "deepen", reply)
        return jsonify({"status": "ok", "reply": reply, "action": "deepen", "level": level, "doc_id": new_id})
    
    elif action.startswith("control_"):
        freq = action.split("_", 1)[1]
        _query("INSERT INTO dept_metrics (dept,metric_name,metric_value,period,created_at) VALUES ('osp','control_watch',?,?,?)",
               (doc_id, freq, datetime.utcnow().isoformat()))
        return jsonify({"status": "ok", "action": "control", "frequency": freq, "doc_id": doc_id})
    
    elif action == "counter_forecast":
        prompt = """Ты — контр-аналитик. Построй максимально противоположный прогноз:
- Найди слабые места исходного прогноза
- Построй альтернативный сценарий
- Используй те же факты, но с противоположной интерпретацией
- Оцени вероятность контр-сценария
- Укажи индикаторы реализации контр-сценария
- Формат: ACH с минимум 3 контр-гипотезами"""
        messages = [{"role": "system", "content": get_dept_prompt("osp")}, {"role": "user", "content": prompt + "\n\nИсходный анализ:\n" + raw}]
        result = call_llm("osp", messages)
        reply = result.get("reply", "")
        new_id = _save_generated_report(dept, f"Контр-прогноз: {title}", "counter_forecast", reply)
        return jsonify({"status": "ok", "reply": reply, "action": "counter_forecast", "doc_id": new_id})
    
    elif action == "archive":
        _query("UPDATE miniapp_responses SET archived=1 WHERE id=?", (doc_id,))
        return jsonify({"status": "ok", "action": "archive", "doc_id": doc_id})
    
    elif action == "crisis_protocol":
        prompt = """Ты — кризис-аналитик. Проанализируй данный отчёт с точки зрения кризисных рисков:
- Выдели все потенциальные кризисы и точки перелома
- Оцени вероятность и сроки наступления каждого (30/60/90/180 дней)
- Для каждого кризиса укажи индикаторы-предвестники
- Построй дерево решений: что делать при реализации каждого сценария
- Выдели критический путь: какой кризис наиболее вероятен и наиболее опасен
- Формат: структурированный отчёт с заголовками"""
        messages = [{"role": "system", "content": get_dept_prompt("osp")}, {"role": "user", "content": prompt + "\n\nОтчёт:\n" + raw}]
        result = call_llm("osp", messages)
        reply = result.get("reply", "")
        new_id = _save_generated_report(dept, f"Кризис-протокол: {title}", "crisis_protocol", reply)
        return jsonify({"status": "ok", "reply": reply, "action": "crisis_protocol", "doc_id": new_id})
    
    return jsonify({"status": "error", "msg": f"unknown action: {action}"}), 400

@app.post("/enrich")
def enrich_endpoint():
    """Rich post-processor endpoint for Metalogos. Accepts raw markdown, returns enriched HTML."""
    d = request.get_json(force=True)
    raw_text = d.get("text", "")
    dept = d.get("dept", "admin")
    accent = DEPT_COLORS.get(dept, {}).get("accent", "#A8321E")
    enriched = auto_enrich(raw_text, dept=dept, accent_color=accent)
    return jsonify({"enriched": enriched, "has_metrics": "metric-card" in enriched})

@app.post("/tg-send")
def tg_send():
    """Send Telegram message with auto-split for texts >4096 chars."""
    d = request.get_json(force=True)
    chat_id = d.get("chat_id", "")
    text = d.get("text", "")
    if not chat_id or not text:
        return jsonify({"status": "error", "msg": "missing chat_id or text"})
    TG_MAX = 4096
    if len(text) <= TG_MAX:
        msg_id = _tg_send_message(chat_id, text)
        return jsonify({"status": "ok", "msg_id": msg_id, "parts": 1})
    # Split at last newline before 4096
    parts = []
    while len(text) > TG_MAX:
        cut = text.rfind("\n", 0, TG_MAX)
        if cut < TG_MAX // 2:
            cut = TG_MAX
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    msg_ids = []
    for i, part in enumerate(parts):
        mid = _tg_send_message(chat_id, part)
        if mid:
            msg_ids.append(mid)
    return jsonify({"status": "ok", "msg_ids": msg_ids, "parts": len(parts)})

# ── FO-013 фаза 1: промежуточный статус с анти-спамом ──
@app.post("/tg-status")
def tg_status_endpoint():
    """Промежуточный статус в чат («маршрутизирую», «OSP анализирует»).

    Rate-limit: не чаще 1 сообщения в 10с на чат (force=true — вопреки лимиту).
    """
    d = request.get_json(force=True)
    chat_id = d.get("chat_id", "")
    text = d.get("text", "")
    if not chat_id or not text:
        return jsonify({"status": "error", "message": "chat_id and text are required"}), 400
    sent = tg_status(chat_id, text[:500], dept=d.get("dept"), force=bool(d.get("force")))
    return jsonify({"status": "ok", "sent": sent})


# ── FO-013 фаза 2: длинный ответ кусками по мере готовности ──
@app.post("/tg-send-long")
def tg_send_long_endpoint():
    """Резать длинный текст на смысловые куски и отправлять последовательно."""
    d = request.get_json(force=True)
    chat_id = d.get("chat_id", "")
    text = d.get("text", "")
    if not chat_id or not text:
        return jsonify({"status": "error", "message": "chat_id and text are required"}), 400
    limit = int(d.get("limit", 3800))
    ids = tg_send_long(chat_id, text, dept=d.get("dept"), limit=limit)
    return jsonify({"status": "ok", "messages_sent": len(ids), "message_ids": ids})


@app.post("/tg-send-report-file")
def tg_send_report_file():
    """Send a stored report as an .html document to the owner chat."""
    d = request.get_json(force=True)
    doc_id = d.get("doc_id", "")
    chat_id = d.get("chat_id", "")
    caption = d.get("caption", "")
    if not doc_id or not chat_id:
        return jsonify({"status": "error", "message": "doc_id and chat_id are required"}), 400
    try:
        rows = _query("SELECT dept, title, html, created_at FROM miniapp_responses WHERE id = ?",
                      (doc_id,), fetch=True)
        if not rows:
            return jsonify({"status": "error", "message": "doc not found"}), 404
        r = rows[0]
        html = r["html"] or ""
        dept = r["dept"] or "report"
        title = r["title"] or ""
        created = (r["created_at"] or "")[:10] or datetime.utcnow().strftime("%Y-%m-%d")
        fname = f"{created}_{_safe_filename_part(dept, 20)}_{_safe_filename_part(title)}.html"
        fpath = os.path.join("/tmp", fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(html)
        msg_id = _tg_send_document(chat_id, fpath, caption)
        try:
            os.remove(fpath)
        except Exception as e:
            log.warning(f"[cleanup] temp document remove failed: {e}")
        if not msg_id:
            # Attachment failed: fall back to plain text so the owner is not left with silence
            fallback_text = caption or f"Отчёт готов: {title or doc_id}"
            text_msg_id = _tg_send_message(chat_id, fallback_text)
            _log_audit("report_file_fallback", {"doc_id": doc_id, "dept": dept,
                                                "msg_id": text_msg_id})
            if text_msg_id:
                return jsonify({"status": "ok", "msg_id": text_msg_id, "mode": "text"})
            return jsonify({"status": "error", "message": "sendDocument and sendMessage failed"}), 502
        _log_audit("report_file_sent", {"doc_id": doc_id, "dept": dept, "msg_id": msg_id})
        return jsonify({"status": "ok", "msg_id": msg_id})
    except Exception as e:
        log.error(f"tg_send_report_file error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.get("/dept-dashboard/<slug>")
@require_telegram
def dept_dashboard(slug):
    dept = slug.lower()
    if dept not in DEPT_NAMES:
        return "<h1>Unknown department</h1>", 404
    rows_corr = _query("SELECT original_query,correction,created_at FROM adapt_corrections WHERE dept=? ORDER BY id DESC LIMIT 5", (dept,), fetch=True)
    override = _cfg_cache["overrides"].get(dept, "default")
    html = _html_base(f"Dashboard — {DEPT_NAMES[dept]}")
    html += _dept_header(dept)
    html += _dept_kpis(dept)
    html += '<div class="section"><h2>Poslednie korrektirovki</h2>'
    if rows_corr:
        html += '<table><tr><th>Original</th><th>Korrektirovka</th><th>Data</th></tr>'
        for r in rows_corr:
            html += f'<tr><td>{r["original_query"][:80]}</td><td>{r["correction"][:80]}</td><td class="mono">{r["created_at"][:16]}</td></tr>'
        html += '</table>'
    else:
        html += '<p style="color:#666">Net korrektirovok</p>'
    html += '</div>'
    html += '<div class="section"><h2>Konfiguratsiya</h2>'
    html += f'<div class="card"><p>Model: <span class="mono gold">{override}</span></p>'
    html += f'<p>Provider: <span class="mono gold">{_cfg_cache["priority_provider"]}</span></p></div></div>'
    html += '</body></html>'
    return Response(html, mimetype="text/html")

@app.get("/office-dashboard")
@require_telegram
def office_dashboard():
    now = datetime.utcnow()
    today = now.isoformat()[:10]
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()
    r_today = _query("SELECT COUNT(*) as c FROM token_usage WHERE created_at>=?", (today,), fetch=True)
    r_week = _query("SELECT COUNT(*) as c FROM token_usage WHERE created_at>=?", (week_ago,), fetch=True)
    r_month = _query("SELECT COUNT(*) as c FROM token_usage WHERE created_at>=?", (month_ago,), fetch=True)
    r_cost = _query("SELECT COALESCE(SUM(cost_usd),0) as t FROM token_usage WHERE created_at>=?", (month_ago,), fetch=True)
    n_today = r_today[0]["c"] if r_today else 0
    n_week = r_week[0]["c"] if r_week else 0
    n_month = r_month[0]["c"] if r_month else 0
    cost_month = r_cost[0]["t"] if r_cost else 0

    html = _html_base("Fosved Office — Panel upravleniya")
    html += '<div class="header-grad" style="background:linear-gradient(135deg,#1a1a2e,#16213e)"><h1>Fosved Office v2</h1>'
    html += f'<p style="color:var(--stamp,#A8321E);margin-top:8px">Obzor za {today} &nbsp;|&nbsp; Provider: <span class="mono">{_cfg_cache["priority_provider"]}</span> &nbsp;|&nbsp; Model: <span class="mono">{_cfg_cache["priority_model"] or "auto"}</span></p></div>'
    html += f"""<div class="grid grid-4" style="margin:20px 24px">
<div class="card kpi"><div class="num gold">{n_today}</div><div class="lbl">Vyzovov segodnya</div></div>
<div class="card kpi"><div class="num status-blue">{n_week}</div><div class="lbl">Za nedelyu</div></div>
<div class="card kpi"><div class="num">{n_month}</div><div class="lbl">Za mesyats</div></div>
<div class="card kpi"><div class="num status-green">${cost_month:.2f}</div><div class="lbl">Stoimost / mes</div></div></div>"""

    html += '<div class="section"><h2>Departamenty</h2><div class="grid grid-3">'
    depts = [d for d in DEPT_NAMES if d != "admin"]
    for dept in depts:
        c = DEPT_COLORS[dept]
        r_d = _query("SELECT COUNT(*) as c FROM token_usage WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
        r_m = _query("SELECT COALESCE(AVG(CAST(metric_value AS REAL)),0) as a FROM dept_metrics WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
        calls = r_d[0]["c"] if r_d else 0
        rating = r_m[0]["a"] if r_m else 0
        level = "high" if calls > 10 else "medium" if calls > 0 else "low"
        ov = _cfg_cache["overrides"].get(dept)
        html += f"""<div class="card" style="border-left:4px solid {c['accent']}">
<h3 style="font-size:1rem">{_status_icon(level)} {DEPT_NAMES[dept]}</h3>
<p class="mono" style="margin-top:8px;font-size:0.8rem;color:#999">Vyzovy: {calls} &nbsp; Otsenka: {rating:.1f}/5</p>
<p class="mono" style="font-size:0.7rem;color:#666;margin-top:4px">Model: {ov or 'default'}</p>
<a href="/dept-dashboard/{dept}" style="font-size:0.75rem;display:inline-block;margin-top:8px">Otkryt -&gt;</a></div>"""
    html += '</div></div>'

    audit_rows = _query("SELECT action,details,timestamp FROM audit_log ORDER BY id DESC LIMIT 10", fetch=True)
    html += '<div class="section"><h2>Zhurnal</h2><table><tr><th>Deistvie</th><th>Detali</th><th>Vremya</th></tr>'
    for r in audit_rows:
        det = r["details"][:100] if r["details"] else ""
        html += f'<tr><td class="mono">{r["action"]}</td><td style="color:#999;font-size:0.8rem">{det}</td><td class="mono" style="font-size:0.8rem">{r["timestamp"][:19]}</td></tr>'
    html += '</table></div>'

    prov_rows = _query("SELECT provider,COUNT(*) as c,COALESCE(SUM(cost_usd),0) as cost FROM token_usage WHERE created_at>=? GROUP BY provider", (month_ago,), fetch=True)
    html += '<div class="section"><h2>Providery (mesyats)</h2><table><tr><th>Provider</th><th>Vyzovy</th><th>Stoimost</th></tr>'
    for r in prov_rows:
        html += f'<tr><td class="mono gold">{r["provider"]}</td><td>{r["c"]}</td><td class="mono">${r["cost"]:.2f}</td></tr>'
    html += '</table></div></body></html>'
    return Response(html, mimetype="text/html")



@app.post("/extract-document")
def extract_document():
    """Download a Telegram document and return its plain text."""
    d = request.get_json(force=True)
    file_id = d.get("file_id", "")
    file_name = d.get("file_name", "")
    if not file_id:
        return jsonify({"status": "error", "message": "file_id is required"}), 400
    tmp = None
    try:
        file_path = _tg_get_file(file_id)
        if not file_path:
            return jsonify({"status": "error",
                            "message": "не удалось получить файл из Telegram"}), 200
        blob = _tg_download_file(file_path)
        if not blob:
            return jsonify({"status": "error",
                            "message": "не удалось скачать файл (возможно, больше 20 МБ)"}), 200
        suffix = os.path.splitext(file_name or file_path)[1] or ""
        tmp = os.path.join("/tmp", f"doc_{int(time.time() * 1000)}{suffix}")
        with open(tmp, "wb") as f:
            f.write(blob)
        text, truncated = doc_extract.extract_text(tmp, file_name)
        _log_audit("document_extracted", {"file_name": file_name,
                                          "chars": len(text), "truncated": truncated})
        return jsonify({"status": "ok", "text": text,
                        "chars": len(text), "truncated": truncated})
    except ValueError as e:
        _log_audit("document_extract_error", {"file_name": file_name, "error": str(e)[:200]})
        return jsonify({"status": "error", "message": str(e)}), 200
    except Exception as e:
        log.error(f"extract_document failed: {e}")
        return jsonify({"status": "error", "message": "внутренняя ошибка извлечения"}), 500
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except Exception as e:
                log.warning(f"[cleanup] temp file remove failed: {e}")
