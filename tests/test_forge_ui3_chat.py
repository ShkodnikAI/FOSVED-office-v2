#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-3 tests (#196): экран «Чат».

Гварды чек-листа:
- поиск глобальный (svg-лупа, /api/dialog/search), не только текущий отдел;
- овальные кнопки отделов: порядок (Яна первая, далее dept_activity), цвета
  из DEPT_COLORS через /api/depts/chat (без дублей палитры во фронте),
  бейдж непрочитанных ровно #FF4B52;
- лента переписки (msg-row), не список диалогов; свои — справа градиент,
  отдел — слева тёмная карточка; история из dialog_history;
- шапка активного отдела с инициалами и реальной активностью;
- compose: «+», авто-рост до 6 строк (132px = 6×22px), круглая градиентная «→»;
- превью вложений над полем, крестик убирает из очереди, видео-бейдж с длительностью;
- микрофон: только иконка, .active на удержании записи (реального STT нет —
  визуальное поведение по наряду).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-ui3-test'
os.environ['ZAI_API_KEY'] = 'fake-key'

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query, DEPT_COLORS  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8") as _f:
    INDEX = _f.read()

API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def chat_schema():
    _query("CREATE TABLE IF NOT EXISTS dialog_history (id INTEGER PRIMARY KEY AUTOINCREMENT, "
           "chat_id TEXT, role TEXT, dept TEXT, content TEXT, created_at TEXT DEFAULT (datetime('now')))")
    _query("CREATE TABLE IF NOT EXISTS dept_activity (dept TEXT PRIMARY KEY, last_used_at TEXT, "
           "use_count INTEGER DEFAULT 0)")
    _query("DELETE FROM dialog_history")
    _query("DELETE FROM dept_activity")
    yield
    _query("DELETE FROM dialog_history")
    _query("DELETE FROM dept_activity")


# ── A.1 Поиск ────────────────────────────────────────────────────────────

def test_search_global_with_lens_icon():
    assert '<div class="search">' in INDEX
    assert '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>' in INDEX
    assert 'placeholder="Найти по отделу или тексту"' in INDEX
    # глобальный поиск по всем перепискам — отдельный эндпоинт, не фильтр текущей ленты
    assert 'api("/api/dialog/search?q="+encodeURIComponent(q))' in INDEX
    assert 'data-srdept' in INDEX  # клик по находке открывает переписку отдела


# ── A.2 Кнопки отделов ───────────────────────────────────────────────────

def test_quickrow_colors_from_api_not_hardcoded():
    # градиент собирается из цветов, пришедших из API (DEPT_COLORS proxy/core.py)
    assert 'background:linear-gradient(135deg,\'+esc(x.color||"#555555")+\',\'+esc(x.color2||"#333333")+\')' in INDEX
    # во фронте нет захардкоженных цветов отделов вида #1F5C8B (они приходят из API)
    assert '#1F5C8B' not in INDEX


def test_unread_badge_exact_red():
    assert 'background:#FF4B52' in INDEX  # отдельно уточнено владельцем
    assert "qpill-badge\">'+x.unread+\"</span>" in INDEX


def test_order_yana_first_from_backend():
    # порядок рендерится как пришёл из /api/depts/chat — там Яна закреплена первой;
    # сам порядок (yana → свежие по use_count → старые → никогда) проверяет
    # поведенческий test_api_depts_chat_order_and_unread
    assert "chatDepts.map(function(x){" in INDEX


# ── B.1 Лента переписки ──────────────────────────────────────────────────

def test_bubble_styles_per_naryad():
    assert '.msg-row.me .bubble{background:linear-gradient(135deg,#E8262E,#B4151C);color:#fff;border-bottom-right-radius:4px}' in INDEX
    assert '.msg-row.dept .bubble{background:var(--surface);border:1px solid var(--line);color:var(--ink);border-bottom-left-radius:4px}' in INDEX


def test_thread_not_dialog_list():
    # лента грузится из dialog_history по отделу
    assert 'api("/api/depts/"+encodeURIComponent(id)+"/dialog")' in INDEX
    assert "msg-row '+(me?\"me\":\"dept\")" in INDEX
    # это НЕ список карточек-превью: нет превью-структур в ленте
    feed_js = INDEX.split('async function openChatDept(')[1].split('var searchTimer=null;')[0]
    assert 'data-report' not in feed_js


# ── B.2 Шапка активного отдела ───────────────────────────────────────────

def test_chat_head_avatar_name_sub():
    assert 'chat-head-avatar' in INDEX and 'chat-head-name' in INDEX and 'chat-head-sub' in INDEX
    assert 'slice(0,2).toUpperCase()' in INDEX  # инициалы
    # sub — реальная активность из dept_activity, не выдуманное «отвечает обычно быстро»
    assert 'активность: "+relTime(meta.last_used)' in INDEX
    assert 'отвечает обычно быстро' not in INDEX


# ── C. Строка ввода ──────────────────────────────────────────────────────

def test_compose_layout():
    assert '<button class="icon-btn" type="button" id="btnAttach" aria-label="прикрепить файл">+</button>' in INDEX
    assert '<textarea class="compose-input" id="composeInput" rows="1" placeholder="Сообщение отделу…"' in INDEX
    assert '<button class="send-btn" type="submit" aria-label="отправить">→</button>' in INDEX
    assert '.send-btn{flex:0 0 38px;width:38px;height:38px;border-radius:50%;background:linear-gradient(135deg,#E8262E,#B4151C);color:#fff' in INDEX


def test_autogrow_132_six_lines():
    # константа 132px = 6 строк × line-height 22px (пересчитана, не «на глаз»)
    assert 'Math.min(taUI3.scrollHeight,132)+"px"' in INDEX
    assert '.compose-input{flex:1;min-width:0;resize:none;height:40px;border-radius:12px;border:1px solid var(--line);background:var(--surface);padding:9px 12px;font-size:15px;line-height:22px;outline:none;color:var(--ink)}' in INDEX
    assert 'resize:none' in INDEX


def test_attach_preview_above_compose_with_remove():
    # превью появляется НАД строкой ввода
    assert INDEX.index('id="attachPreview"') < INDEX.index('id="chatForm"')
    assert 'data-rmfile' in INDEX
    assert 'pendingFiles.splice(ri,1)[0]' in INDEX  # убирает из очереди, файл ещё не отправлен
    assert 'URL.revokeObjectURL(rf._url)' in INDEX
    # видео: затемнённая миниатюра + ▶ + длительность из метаданных
    assert 'filter:brightness(.7)' in INDEX
    assert '.attach-video-badge' in INDEX
    assert 'Math.floor(v.duration/60)+":"+String(Math.floor(v.duration%60)).padStart(2,"0")' in INDEX


def test_mic_button_visual_only():
    assert '.yana-btn{width:100%;border:2px solid var(--red);border-radius:14px;padding:13px;background:#000;display:grid;place-items:center}' in INDEX
    assert '.yana-btn svg{stroke:var(--red)}' in INDEX
    assert '.yana-btn.active{background:var(--red);box-shadow:0 0 0 5px rgba(232,38,46,.2)}' in INDEX
    assert '.yana-btn.active svg{stroke:#fff}' in INDEX
    btn_html = INDEX.split('id="micBtn"')[1].split("</button>")[0]
    assert "Яна" not in btn_html  # только иконка микрофона, без подписи
    # №589 A.2: .active — на удержании ЗАПИСИ (micStart/micStop), не по клику
    assert 'micBtn.addEventListener("pointerdown",function(e){e.preventDefault();micStart()})' in INDEX
    assert '["pointerup","pointercancel","pointerleave"].forEach(function(ev){micBtn.addEventListener(ev,function(){micStop()})})' in INDEX
    assert 'micBtn.addEventListener("click"' not in INDEX


# ── Backend: чтение существующих таблиц ──────────────────────────────────

def test_api_depts_chat_order_and_unread():
    _query("INSERT INTO dept_activity (dept, last_used_at, use_count) VALUES "
           "('osp','2026-09-18 10:00:00',10),('lz','2026-09-17 09:00:00',3),"
           "('expert','2026-07-01 09:00:00',99)")
    _query("INSERT INTO dialog_history (chat_id, role, dept, content, created_at) VALUES "
           "('111','user','osp','вопрос','2026-09-18 10:00:00'),"
           "('111','assistant','osp','ответ','2026-09-18 10:01:00'),"
           "('111','assistant','osp','ответ2','2026-09-18 10:02:00')")
    with _client() as c:
        resp = c.get("/api/depts/chat?seen=osp:1", headers=API_AUTH)
    body = resp.get_json()
    ids = [d["id"] for d in body["depts"]]
    assert ids[0] == "yana"          # Яна всегда первая
    assert ids[1:4] == ["osp", "lz", "expert"]  # свежие по use_count, потом старые
    assert ids[-1] == "yana" or "yana" not in ids[1:]
    osp = [d for d in body["depts"] if d["id"] == "osp"][0]
    assert osp["color"] == DEPT_COLORS["osp"]["start"]     # цвета из DEPT_COLORS
    max_id = _query("SELECT MAX(id) AS m FROM dialog_history WHERE dept='osp'", fetch=True)[0]["m"]
    assert osp["last_msg_id"] == max_id
    cnt_after_seen = _query("SELECT COUNT(*) AS c FROM dialog_history WHERE dept='osp' AND id>1",
                            fetch=True)[0]["c"]
    assert osp["unread"] == cnt_after_seen  # сообщения после отметки seen=1
    lz = [d for d in body["depts"] if d["id"] == "lz"][0]
    assert lz["unread"] == 0        # нет отметки — бейдж не спамим


def test_api_dept_dialog_latest_chat_thread():
    _query("INSERT INTO dialog_history (chat_id, role, dept, content, created_at) VALUES "
           "('999','user','qa','старый чат','2026-08-01 10:00:00'),"
           "('111','user','qa','вопрос 1','2026-09-18 10:00:00'),"
           "('111','assistant','qa','ответ 1','2026-09-18 10:01:00')")
    with _client() as c:
        resp = c.get("/api/depts/qa/dialog", headers=API_AUTH)
    msgs = resp.get_json()["messages"]
    assert len(msgs) == 2  # только последний chat_id
    assert msgs[0]["role"] == "user" and msgs[1]["role"] == "assistant"  # хронология
    assert msgs[0]["content"] == "вопрос 1"


def test_api_dialog_search_global():
    _query("INSERT INTO dialog_history (chat_id, role, dept, content, created_at) VALUES "
           "('111','user','finance','купили абонемент на океанариум','2026-09-18 10:00:00'),"
           "('111','user','dev','билд сломался','2026-09-18 11:00:00')")
    with _client() as c:
        hit = c.get("/api/dialog/search?q=океанариум", headers=API_AUTH)
        short = c.get("/api/dialog/search?q=о", headers=API_AUTH)
    results = hit.get_json()["results"]
    assert len(results) == 1 and results[0]["dept"] == "finance"
    assert short.get_json()["results"] == []  # <2 символов — не греем LIKE
