#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #587: кнопки «+»/«−» под ответами и отчётами.

Гварды:
- A.1: таблица reply_ratings (InitDB app.mlog); строка создаётся на отправке с vote NULL;
  callback_data rt:+:<id>/rt:-:<id> ≤ 64 байт, текст ответа в callback_data не кладётся;
- A.2: owner_rate_markup/owner_rate_attach (telegram.py) — kv rate_buttons=off → кнопок нет;
  _tg_send_report_with_button(rate_dept=…) добавляет ряд вторым на последней части;
  точки отправки проводены (бриф, ответ Админа, вечерняя сводка, дайджест, lz-daily);
- A.3: вебхук app.mlog — ветка rt:, только владелец, force_reply для «−» (текстовые гварды);
- A.4: _ratings_counts_line — строка «+N / −M» по отделам из reply_ratings (SQL, не LLM);
  Mini App: переключатель в Настройках + счётчики в карточке отдела (UI-гварды).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-n587-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-zai-key')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', '12345:test-token')

import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app, _query  # noqa: E402
from proxy import telegram as tg_mod, routes_sched  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_AUTH = {'Authorization': 'Bearer test-secret-123'}


def _client():
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def clean_ratings():
    # kv_store — схема бинаря (#268), как в test_lockdown_kvstore/test_forge_ui14_voice
    _query("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)")
    _query("DELETE FROM reply_ratings")
    _query("DELETE FROM kv_store WHERE key='rate_buttons'")
    yield
    _query("DELETE FROM reply_ratings")
    _query("DELETE FROM kv_store WHERE key='rate_buttons'")


# ──────────────────────────── A.1 хранение ────────────────────────────

def test_a1_ddl_in_initdb():
    src = open(os.path.join(REPO_ROOT, "app.mlog"), encoding="utf-8").read()
    assert "CREATE TABLE IF NOT EXISTS reply_ratings" in src
    assert "prompt_message_id" in src  # для force_reply-потока «−»


def test_a1_row_created_vote_null_and_short_callback_data():
    rid, markup = tg_mod._owner_rate_row("lz", "report", "doc-1", "12345")
    assert rid is not None and markup is not None
    rows = _query("SELECT dept, kind, ref, chat_id, vote FROM reply_ratings WHERE id=?", (rid,), fetch=True)
    assert rows and rows[0]["dept"] == "lz" and rows[0]["vote"] is None
    for btn in markup["inline_keyboard"][0]:
        assert len(btn["callback_data"].encode()) <= 64
        assert btn["callback_data"].endswith(f":{rid}")
        assert "doc-1" not in btn["callback_data"]  # текст ответа не в callback_data


# ──────────────────────────── A.2 отправка ────────────────────────────

def test_a2_off_switch_no_markup():
    _query("INSERT OR REPLACE INTO kv_store (key, value) VALUES ('rate_buttons', 'off')")
    assert tg_mod._rate_buttons_enabled() is False
    assert tg_mod.owner_rate_markup("lz") is None
    assert tg_mod.owner_rate_attach("12345", 42, "lz") is None
    # включение обратно через API
    r = _client().post("/api/rate_buttons", headers=API_AUTH, json={"enabled": True})
    assert r.get_json()["enabled"] is True
    assert tg_mod._rate_buttons_enabled() is True


def test_a2_report_with_button_appends_second_row(monkeypatch):
    # строку оценки создаёт сама функция отправки (rid внутри callback_data)
    captured = {}
    def _fake_one(chat_id, text, btn, extra_rows=None):
        captured["rows"] = extra_rows
        return 77
    monkeypatch.setattr(tg_mod, "_tg_send_one_with_button", _fake_one)
    monkeypatch.setattr(tg_mod, "_tg_split_report", lambda text, limit=4000: ["часть-1"])
    monkeypatch.setattr(tg_mod, "_rate_note_message", lambda rid, mid: None)
    mid = tg_mod._tg_send_report_with_button("12345", "текст отчёта", rate_dept="lz")
    assert mid == 77
    assert captured["rows"], "ряд оценки не передан последней части"
    cb_plus = captured["rows"][0][0]["callback_data"]
    cb_minus = captured["rows"][0][1]["callback_data"]
    assert cb_plus.startswith("rt:+:") and cb_minus.startswith("rt:-:")
    rid = int(cb_plus.split(":")[2])
    row = _query("SELECT dept, kind FROM reply_ratings WHERE id=?", (rid,), fetch=True)
    assert row and row[0]["dept"] == "lz" and row[0]["kind"] == "report"


def test_a2_send_sites_wired():
    sched = open(os.path.join(REPO_ROOT, "proxy", "routes_sched.py"), encoding="utf-8").read()
    assert 'owner_rate_attach(owner_id, msg_id, "yana", kind="brief")' in sched
    assert 'owner_rate_attach(owner_id, msg_id, "admin", kind="reply")' in sched
    assert 'owner_rate_attach(owner_id, msg_id, "yana", kind="digest")' in sched
    assert "_tg_send_report_with_button(owner_id, digest, rate_dept=" in sched
    lz = open(os.path.join(REPO_ROOT, "proxy", "lz_github.py"), encoding="utf-8").read()
    assert 'rate_dept="lz"' in lz
    mini = open(os.path.join(REPO_ROOT, "dept", "miniapp.mlog"), encoding="utf-8").read()
    assert "SendTelegramReplyRatings(chat_id, reply, dept)" in mini
    assert "AttachRatingRow(chat_id, mdv2_mid, dept" in mini
    assert "SendReportMiniAppMessage(token, chat_id, short_with_dept, miniapp_url, dept, doc_id)" in mini


# ──────────────────────────── A.3 обработчик ────────────────────────────

def test_a3_webhook_guards_text():
    app = open(os.path.join(REPO_ROOT, "app.mlog"), encoding="utf-8").read()
    assert 'starts_with(cb_data, "rt:")' in app
    assert "callback_query.from.id" in app  # только владелец
    assert "force_reply: true" in app       # «−» → фраза «что не так»
    assert "editMessageReplyMarkup" in app  # [✓ +][−]
    assert "RecordPositiveExample(rt_dept, pos_query, pos_reply)" in app
    assert "INSERT INTO adapt_corrections" in app and "corr_type) VALUES (?1, ?2, ?3, ?4, 'manual')" in app
    assert 'starts_with(text, "/rate_buttons")' in app  # выключатель командой


def test_a3_rating_keyboard_labels():
    rid, kb = tg_mod._owner_rate_row("lz", "report", "", "12345")
    assert rid is not None
    assert kb["inline_keyboard"][0][0]["callback_data"] == f"rt:+:{rid}"
    assert kb["inline_keyboard"][0][1]["callback_data"] == f"rt:-:{rid}"


# ──────────────────────────── A.4 счётчики ────────────────────────────

def test_a4_ratings_counts_line():
    _query("INSERT INTO reply_ratings (dept, kind, vote, voted_at) VALUES ('lz','report',1,datetime('now'))")
    _query("INSERT INTO reply_ratings (dept, kind, vote, voted_at) VALUES ('lz','report',1,datetime('now'))")
    _query("INSERT INTO reply_ratings (dept, kind, vote, voted_at) VALUES ('lz','report',-1,datetime('now'))")
    _query("INSERT INTO reply_ratings (dept, kind, vote, voted_at) VALUES ('osp','reply',-1,datetime('now'))")
    # вне окна 7 дней — не считается
    _query("INSERT INTO reply_ratings (dept, kind, vote, voted_at) VALUES ('qa','report',1,datetime('now','-20 days'))")
    line = routes_sched._ratings_counts_line(days=7)
    assert "lz +2 / −1" in line
    assert "osp +0 / −1" in line
    assert "qa" not in line  # старая оценка за окном
    assert "📊 Оценки владельца (7 дн.)" in line


def test_a4_empty_when_no_votes():
    assert routes_sched._ratings_counts_line(days=7) == ""


def test_a4_dept_card_counters_api():
    _query("INSERT INTO reply_ratings (dept, kind, vote, voted_at) VALUES ('lz','report',1,datetime('now'))")
    # минус внутри 30 дней, но вне 7 дней
    _query("INSERT INTO reply_ratings (dept, kind, vote, voted_at) VALUES ('lz','report',-1,datetime('now','-20 days'))")
    r = _client().get("/api/depts/chat", headers=API_AUTH)
    d = r.get_json()
    lz = next(x for x in d["depts"] if x["id"] == "lz")
    assert lz["ratings"]["p7"] == 1 and lz["ratings"]["m7"] == 0
    assert lz["ratings"]["p30"] == 1 and lz["ratings"]["m30"] == 1


# ──────────────────────────── UI-гварды ────────────────────────────

def test_ui_settings_toggle_and_card_counters():
    idx = open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8").read()
    assert 'id="rateSeg"' in idx and 'data-rate="1"' in idx
    assert '"/api/rate_buttons"' in idx
    assert "chat-ratings" in idx
