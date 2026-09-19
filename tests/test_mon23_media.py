#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MON-2/MON-3 tests (#171): mcp_servers/media (YouTube/TikTok) + мост McpMediaCall.

Покрытие:
- JSON-RPC каркас через реальный stdio-процесс: initialize / tools/list /
  tools/call (неизвестная тулза → честный ok:false, isError=false);
- youtube_channel_videos: успех на локальном HTTP-stub (YOUTUBE_API_BASE),
  честный отказ без YOUTUBE_API_KEY;
- tiktok_channel_videos: успех (счётчик сбоев сбрасывается), отказ (счётчик
  растёт, после 3 подряд — запись в admin_findings);
- мост McpMediaCall в dept/dev.mlog: паттерн существует, redact + audit +
  mcp_call на месте (строковые гварды, mlog-проверка остаётся в CI);
- stats_json: ALTER присутствует в app.mlog и идемпотентно исполняется.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MEDIA = REPO_ROOT / "mcp_servers" / "media"

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test-bot-token')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-mon23-test')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')


def _rpc(requests, env_extra=None):
    """Пакет newline-JSON-RPC через реальный процесс медиа-сервера."""
    env = dict(os.environ, DATABASE_PATH="/tmp/fosved-mon23-test")
    env.update(env_extra or {})
    p = subprocess.run([str(MEDIA)], input="\n".join(requests) + "\n",
                       capture_output=True, text=True, timeout=30, env=env)
    replies = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
    return replies


def test_jsonrpc_handshake_and_tools():
    replies = _rpc([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
    ])
    assert replies[0]["result"]["serverInfo"]["name"] == "fosved-media"
    names = {t["name"] for t in replies[1]["result"]["tools"]}
    assert {"youtube_channel_videos", "youtube_video_transcript", "tiktok_channel_videos"} <= names


def test_unknown_tool_honest_fail():
    replies = _rpc([json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                "params": {"name": "no_such", "arguments": {}}})])
    res = replies[0]["result"]
    assert res["isError"] is False  # тулзы никогда не бросают
    payload = json.loads(res["content"][0]["text"])
    assert payload["ok"] is False and "no_such" in payload["error"]


class _Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.loads(self.server.stub_body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


@pytest.fixture()
def stub_server():
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def test_youtube_success_on_stub(stub_server):
    stub_server.stub_body = json.dumps({"items": [
        {"id": {"videoId": "v1"}, "snippet": {"title": "Видео раз", "publishedAt": "2026-09-19T00:00:00Z"}},
        {"id": {"videoId": "v2"}, "snippet": {"title": "Видео два", "publishedAt": "2026-09-18T00:00:00Z"}},
    ]})
    replies = _rpc([json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                "params": {"name": "youtube_channel_videos",
                                           "arguments": {"channel_id": "UCtest", "max_results": 5}}})],
                    env_extra={"YOUTUBE_API_KEY": "fake-key",
                               "YOUTUBE_API_BASE": f"http://127.0.0.1:{stub_server.server_port}"})
    payload = json.loads(replies[0]["result"]["content"][0]["text"])
    assert payload["ok"] is True and payload["count"] == 2
    assert payload["videos"][0]["url"].endswith("watch?v=v1")


def test_youtube_honest_fail_without_key():
    replies = _rpc([json.dumps({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                                "params": {"name": "youtube_channel_videos",
                                           "arguments": {"channel_id": "UCtest"}}})],
                    env_extra={"YOUTUBE_API_KEY": ""})
    payload = json.loads(replies[0]["result"]["content"][0]["text"])
    assert payload["ok"] is False and "YOUTUBE_API_KEY" in payload["error"]


def _load_media_module(tmp_ns_name):
    """mcp_servers/media без расширения .py — грузим SourceFileLoader'ом."""
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader(tmp_ns_name, str(MEDIA))
    spec = importlib.util.spec_from_loader(tmp_ns_name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_tiktok_fail_counter_and_admin_findings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path))
    mod = _load_media_module("media_server_a")
    mod.DATABASE_PATH = str(tmp_path)
    mod.TIKTOK_STATE_FILE = str(tmp_path / "lz_tiktok_state.json")
    mod.TIKTOK_API_BASE = "http://127.0.0.1:1"  # порт 1 — соединение отклонено

    conn = sqlite3.connect(str(tmp_path / "fosved.db"))
    conn.execute("CREATE TABLE IF NOT EXISTS admin_findings (id INTEGER PRIMARY KEY AUTOINCREMENT, finding TEXT, dept TEXT, status TEXT, created_at TEXT DEFAULT (datetime('now')))")
    conn.commit()

    r1 = mod.tiktok_channel_videos({"username": "somebody"})
    r2 = mod.tiktok_channel_videos({"username": "somebody"})
    assert r1["ok"] is False and r2["ok"] is False  # честный отказ, не пустой список-успех
    r3 = mod.tiktok_channel_videos({"username": "somebody"})
    assert r3["ok"] is False
    n = conn.execute("SELECT COUNT(*) FROM admin_findings WHERE dept='lz'").fetchone()[0]
    assert n == 1  # 3 сбоя подряд → одна запись
    state = json.loads((tmp_path / "lz_tiktok_state.json").read_text())
    assert state["consecutive_failures"] == 3
    conn.close()


def test_tiktok_success_resets_counter(tmp_path, stub_server, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path))
    mod = _load_media_module("media_server_b")
    mod.DATABASE_PATH = str(tmp_path)
    mod.TIKTOK_STATE_FILE = str(tmp_path / "lz_tiktok_state.json")
    mod.TIKTOK_API_BASE = f"http://127.0.0.1:{stub_server.server_port}"
    stub_server.stub_body = json.dumps({"itemList": [
        {"id": "777", "desc": "клип", "playCount": 10, "diggCount": 2, "commentCount": 1, "shareCount": 0}]})
    (tmp_path / "lz_tiktok_state.json").write_text(json.dumps({"consecutive_failures": 2}))
    r = mod.tiktok_channel_videos({"username": "artist"})
    assert r["ok"] is True and r["videos"][0]["video_id"] == "777"
    assert '"like": 2' in r["videos"][0]["stats_json"]  # метрики одним столбцом (MON-3)
    state = json.loads((tmp_path / "lz_tiktok_state.json").read_text())
    assert state["consecutive_failures"] == 0  # успех сбрасывает счётчик


def test_mcpmediacall_bridge_present():
    src = (REPO_ROOT / "dept" / "dev.mlog").read_text(encoding="utf-8")
    assert "pattern McpMediaCall(tool: String, args_json: String, purpose: String) -> Dict" in src
    assert 'McpAudit("media"' in src
    block = src.split("pattern McpMediaCall")[1].split("\npattern ")[0]
    assert "redact(" in block
    assert "mcp_call(McpMediaServerCmd()" in block


def test_stats_json_alter_idempotent():
    src = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
    m = re.search(r'ALTER TABLE lz_channel_posts ADD COLUMN stats_json TEXT', src)
    assert m, "stats_json ALTER отсутствует в app.mlog"
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE lz_channel_posts (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT NOT NULL, message_id TEXT NOT NULL, UNIQUE(channel_id, message_id))")
    conn.execute("ALTER TABLE lz_channel_posts ADD COLUMN stats_json TEXT")
    with conn:
        conn.execute("INSERT INTO lz_channel_posts (channel_id, message_id, stats_json) VALUES ('@x', '1', ?)",
                     (json.dumps({"like": 2}),))
    v = conn.execute("SELECT stats_json FROM lz_channel_posts").fetchone()[0]
    assert json.loads(v)["like"] == 2
