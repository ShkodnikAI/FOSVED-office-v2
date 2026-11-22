#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#734 REPORT-2: ночной отчёт не больше 3 сообщений, старый хвост сворачивается.

Факт (аудитор 20.11): ночи 12.11–19.11 не завершались; первый OutboxFlush
20.11 выгрузил ~30 сообщений «🌙 Ночной отчёт (часть N)» — ни лимита числа
сообщений, ни отсечки по возрасту строки.

A.1 Строки старше 48 ч не идут текстом — один блок «— архив —» с n/min/max
и счётом source×k (SQL-агрегаты: строковых < в mlog нет).
A.2 OUTBOX_MAX_PARTS = 3 (паттерн OutboxMaxParts): части 1–2 текстом,
третья — «Отчёт не поместился: ещё N частей» с кнопкой «Открыть отчёт»
(SendReportMiniAppMessage, dept night); полный текст (свежие + старые
строки ЦЕЛИКОМ) — в miniapp_responses; AuditLog: capped=1 archived_rows=N.
A.3 Регрессия: 1–3 части — байт в байт (python-эмуляция прежней сборки).

Живые прогоны — фикстура test_n734v1.mlog (генератор scripts/n734_fixture.py
вырезает сегменты из актуального dept/scheduler.mlog; транспорт — заглушки
tg_calls). Запреты: OutboxPut, дедуп, OutboxSplitChunks, NightReportSlot,
утренний бриф — гварды на неизменность.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

os.environ.setdefault("OWNER_TELEGRAM_ID", "12345")
os.environ.setdefault("ZAI_API_KEY", "fake-key")
os.environ.setdefault("API_SECRET", "test-secret-123")

SCHED = (REPO / "dept" / "scheduler.mlog").read_text(encoding="utf-8")
MINIAPP = (REPO / "dept" / "miniapp.mlog").read_text(encoding="utf-8")


def _segment(src: str, decl: str) -> str:
    start = src.index(decl)
    rest = src[start + len(decl):]
    nxt = rest.find("\npattern ")
    return (decl + rest[:nxt]) if nxt != -1 else (decl + rest)


FLUSH_SEG = _segment(SCHED, "pattern OutboxFlush(")
SPLIT_SEG = _segment(SCHED, "pattern OutboxSplitChunks(")
MAXPARTS_SEG = _segment(SCHED, "pattern OutboxMaxParts(")


# ─────────────── статические гварды ───────────────

def test_a1_stale_cutoff_and_archive_block():
    """НАРЯД A.1: строки старше 48 ч не идут текстом — блок «— архив —».
    DDL owner_outbox содержит created_at (правило при затруднении не
    сработало). n/min/max и счёт source — SQL-агрегатами."""
    assert "-48 hours" in FLUSH_SEG, "отсечка 48 ч отсутствует"
    assert "— архив —" in FLUSH_SEG
    assert "старых записей за" in FLUSH_SEG
    assert "GROUP BY source" in FLUSH_SEG, "счёт source×k"
    assert "AS mn" in FLUSH_SEG and "AS mx" in FLUSH_SEG, "min/max дат"
    assert "created_at IS NOT NULL AND created_at < datetime('now','-48 hours')" in FLUSH_SEG
    # DDL: created_at есть в обоих местах (scheduler и core.py)
    ddl = "CREATE TABLE IF NOT EXISTS owner_outbox"
    assert ddl + " (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT" in SCHED
    core = (REPO / "proxy" / "core.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS owner_outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT" in core
    # старые строки не режутся текстом: stale-ветка не вызывает SplitChunks
    stale_branch = FLUSH_SEG[FLUSH_SEG.index('stale == "1"'):FLUSH_SEG.index("} else {")]
    assert "OutboxSplitChunks" not in stale_branch, "старые строки не идут в куски"


def test_a1_full_text_keeps_old_rows_whole():
    """Полный текст для Mini App содержит старые строки ЦЕЛИКОМ (не архивную
    строку): stale-ветка пишет source, created_at, text."""
    stale_branch = FLUSH_SEG[FLUSH_SEG.index('stale == "1"'):FLUSH_SEG.index("} else {")]
    assert '"— " + src + " — (" + cat + ")\\n" + txt' in stale_branch


def test_a2_max_parts_constant():
    """НАРЯД A.2: OUTBOX_MAX_PARTS = 3 — паттерн-константа OutboxMaxParts."""
    assert "return 3.0" in MAXPARTS_SEG
    assert "pattern OutboxMaxParts() -> Float" in MAXPARTS_SEG
    assert "OutboxMaxParts()" in FLUSH_SEG, "лимит используется в flush"


def test_a2_capped_message_and_miniapp_seam():
    """Третья часть — «Отчёт не поместился: ещё N частей» с кнопкой; полный
    текст в miniapp_responses (dept night) тем же путём, что SendReport."""
    assert "Отчёт не поместился: ещё " in FLUSH_SEG
    assert 'INSERT INTO miniapp_responses' in FLUSH_SEG
    assert '"night"' in FLUSH_SEG, "dept night в INSERT"
    assert "SendReportMiniAppMessage(TgToken(), env(\"OWNER_TELEGRAM_ID\"), capped_text, miniapp_url, \"night\", doc_id)" in FLUSH_SEG
    # шов SendReportMiniAppMessage с кнопкой «Открыть отчёт» (miniapp.mlog:173)
    seam = _segment(MINIAPP, "pattern SendReportMiniAppMessage(")
    assert '"Открыть отчёт"' in seam and "web_app" in seam
    # audit дополнен capped=1 archived_rows=N
    assert "capped=1 archived_rows=" in FLUSH_SEG


def test_a3_regression_shape_untouched():
    """НАРЯД A.3: разбиение по 3500 и заголовки частей — как раньше;
    OutboxSplitChunks не тронут (гвард сигнатуры и констант); OutboxPut,
    дедуп «already delivered today», NightReportSlot — вне правки."""
    assert "3500.0" in FLUSH_SEG and "🌙 Ночной отчёт" in FLUSH_SEG
    assert "(часть " in FLUSH_SEG
    assert "pattern OutboxSplitChunks(text: String, max_len: Float) -> String" in SCHED
    assert "outbox: already delivered today" in SCHED
    assert "pattern NightReportSlot(" in SCHED


# ─────────────── python-эмуляция сборки (A.3 / подсчёт N) ───────────────

def _split_chunks(text: str, max_len: int = 3400):
    """Точная эмуляция OutboxSplitChunks (scheduler.mlog): резка по абзацам
    "\\n\\n"; абзац длиннее max_len режется жёстко по max_len."""
    parts = []
    cur = ""
    for par in text.split("\n\n"):
        if len(par) == 0:
            continue
        if len(par) > max_len:
            if cur:
                parts.append(cur)
                cur = ""
            off = 0
            while off < len(par):
                piece = par[off:off + max_len]
                if piece:
                    parts.append(piece)
                off += max_len
        else:
            if len(cur) + len(par) + 2 > max_len:
                if cur:
                    parts.append(cur)
                cur = par
            else:
                cur = cur + "\n\n" + par if cur else par
    if cur:
        parts.append(cur)
    return parts


def _emulate_messages(blocks: list):
    """Эмуляция прежней сборки сообщений (куски → части по 3500, заголовки
    «🌙 Ночной отчёт» / «(часть N)») — эталон регрессии байт в байт."""
    all_json = []
    for src_name, text in blocks:
        block = f"— {src_name} —\n{text}"
        all_json.extend(_split_chunks(block, 3400))
    msgs = []
    part_no = 1
    cur = ""
    for piece in all_json:
        if len(cur) + len(piece) + 2 > 3500:
            if cur:
                header = "🌙 Ночной отчёт" if part_no == 1 else f"🌙 Ночной отчёт (часть {part_no})"
                msgs.append(header + "\n" + cur)
                part_no += 1
            cur = piece
        else:
            cur = cur + "\n\n" + piece if cur else piece
    if cur:
        header = "🌙 Ночной отчёт" if part_no == 1 else f"🌙 Ночной отчёт (часть {part_no})"
        msgs.append(header + "\n" + cur)
    return msgs


# ─────────────── живой прогон фикстуры ───────────────

def _run_fixture(scenario: str, dbname: str):
    """Генерация фикстуры из актуального scheduler.mlog + mlog run."""
    subprocess.run([sys.executable, str(REPO / "scripts" / "n734_fixture.py"),
                    str(REPO / "test_n734v1.mlog")], check=True, cwd=REPO)
    db = Path(f"/tmp/n734/{dbname}")
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    env = dict(os.environ, N734_SCENARIO=scenario,
               DATABASE_URL=f"sqlite:{db}", OWNER_TELEGRAM_ID="12345")
    r = subprocess.run([str(REPO / "bin" / "mlog"), "run", "test_n734v1.mlog"],
                       capture_output=True, text=True, timeout=300, env=env, cwd=REPO)
    assert "delivered" in (r.stdout + r.stderr), \
        f"flush не отработал: {r.stdout[-400:]} {r.stderr[-400:]}"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    return conn


class TestLiveFixture:
    """Живые прогоны OutboxFlush на реальном сегменте scheduler.mlog."""

    def test_a1_arch_scenario(self):
        """НАРЯД A.1-тест: 10 строк возрастом 5 сут + 2 свежих → в
        отправленном тексте 2 свежих блока и одна строка «архив» с
        usage-by-key×…; старые строки не идут текстом."""
        conn = _run_fixture("arch", "t_arch.db")
        calls = conn.execute("SELECT kind, text FROM tg_calls ORDER BY id").fetchall()
        assert len(calls) == 1, f"arch: 1 часть, получили {len(calls)}"
        text = calls[0]["text"]
        assert "— SourceC —" in text and "свежий блок C1" in text and "свежий блок C2" in text
        assert "— архив —" in text, "одна строка «архив»"
        assert "10 старых записей за" in text
        assert "SourceA×8, SourceB×2" in text, "usage-by-key×…"
        for i in range(1, 11):
            assert f"старый блок {i}" not in text, "старые строки не идут текстом"
        # даты min/max в строке архива (формат YYYY-MM-DD HH:MM)
        import re
        assert re.search(r"за \d{4}-\d{2}-\d{2} \d{2}:\d{2}–\d{4}-\d{2}-\d{2} \d{2}:\d{2}", text)
        # не capped: miniapp-доков нет, audit без capped, sent_at все
        assert conn.execute("SELECT COUNT(*) c FROM miniapp_responses").fetchone()["c"] == 0
        audit = conn.execute("SELECT details FROM audit_log WHERE action='owner_outbox_flush'").fetchone()["details"]
        assert "capped" not in audit
        assert conn.execute("SELECT COUNT(*) c FROM owner_outbox WHERE sent_at IS NULL").fetchone()["c"] == 0

    def test_a2_cap_scenario(self):
        """НАРЯД A.2-тест: очередь на 10 частей → SendMessage-вызовов ровно 3,
        третий с кнопкой (miniapp-шов), запись miniapp_responses содержит
        весь текст; audit capped=1 archived_rows=0."""
        conn = _run_fixture("cap", "t_cap.db")
        calls = conn.execute("SELECT kind, text, url FROM tg_calls ORDER BY id").fetchall()
        assert len(calls) == 3, f"cap: ровно 3 вызова, получили {len(calls)}"
        assert [c["kind"] for c in calls] == ["tg", "tg", "miniapp"]
        # части 1–2 — обычные заголовки
        assert calls[0]["text"].startswith("🌙 Ночной отчёт\n")
        assert calls[1]["text"].startswith("🌙 Ночной отчёт (часть 2)\n")
        # третий — capped-пометка + кнопка «Открыть отчёт» (web_app в шве)
        assert "🌙 Ночной отчёт (часть 3)" in calls[2]["text"]
        assert "Отчёт не поместился: ещё " in calls[2]["text"]
        assert "/miniapp/doc-night-" in calls[2]["url"]
        # N в capped-пометке == число неотправленных частей (msgs − 2):
        # python-эмуляция сборки по тем же блокам
        blocks = [("ФинОтдел", f"Блок {i}: " + "x" * 460) for i in range(30)]
        msgs = _emulate_messages(blocks)
        assert len(msgs) > 3, "сценарий должен давать больше 3 частей"
        expected = f"🌙 Ночной отчёт (часть 3)\nОтчёт не поместился: ещё {len(msgs) - 2} частей"
        assert calls[2]["text"] == expected, (calls[2]["text"], expected)
        # полный текст (свежие строки целиком) в miniapp_responses, dept night
        doc = conn.execute("SELECT id, dept, title, raw_text FROM miniapp_responses").fetchone()
        assert doc["dept"] == "night" and doc["title"] == "Ночной отчёт"
        for i in range(30):
            assert f"Блок {i}: " in doc["raw_text"], "полный текст потерял блок"
        # audit: capped=1 archived_rows=0; sent_at у всех
        audit = conn.execute("SELECT details FROM audit_log WHERE action='owner_outbox_flush'").fetchone()["details"]
        assert "capped=1 archived_rows=0" in audit
        assert conn.execute("SELECT COUNT(*) c FROM owner_outbox WHERE sent_at IS NULL").fetchone()["c"] == 0

    def test_a3_reg_scenario_byte_identical(self):
        """НАРЯД A.3-тест: очередь на 1–3 части отправляется как сейчас,
        байт в байт (сравнение с python-эмуляцией прежней сборки)."""
        conn = _run_fixture("reg", "t_reg.db")
        calls = conn.execute("SELECT kind, text FROM tg_calls ORDER BY id").fetchall()
        blocks = [("S1", "текст 1"), ("S2", "текст 2"), ("S3", "текст 3"),
                  ("S4", "текст 4"), ("S5", "текст 5")]
        msgs = _emulate_messages(blocks)
        assert len(msgs) == 1
        assert len(calls) == 1
        assert calls[0]["text"] == msgs[0], "байт в байт с прежней сборкой"


class TestRestrictions:
    """Запреты наряда: содержание блоков, OutboxPut, дедуп, резка,
    NightReportSlot, утренний бриф."""

    def test_outbox_put_and_dedup_untouched(self):
        seg = _segment(SCHED, "pattern OutboxPut(")
        assert "INSERT INTO owner_outbox" in seg
        assert "already delivered today" in SCHED
        # дедуп-строка не изменилась (SQL как был)
        assert "WHERE sent_at IS NOT NULL AND date(sent_at) = date('now')" in SCHED

    def test_split_chunks_body_untouched(self):
        """OutboxSplitChunks: тело совпадает с эталонными строками (лимиты
        3400/3500 не переехали, резка по абзацам сохранена)."""
        assert 'split(text, "\\n\\n")' in SPLIT_SEG
        assert "max_len" in SPLIT_SEG
        # flush использует те же константы, что раньше
        assert "OutboxSplitChunks(block, 3400.0)" in FLUSH_SEG
        assert "3500.0" in FLUSH_SEG

    def test_morning_slot_untouched(self):
        seg = _segment(SCHED, "pattern MorningSlot(")
        assert "OutboxFlush" not in seg, "утренний бриф не вызывает flush"
