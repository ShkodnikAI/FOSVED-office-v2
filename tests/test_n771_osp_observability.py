#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#771 A/B/C: тихий отказ ОСП 23.11 — наблюдаемость + гварды.

Инцидент (владелец, 23.11 ~19:0x Minsk): `/osp …` → «ОСП: не удалось
получить ответ» — исключение внутри HandleOSP глоталось try, причина не
оставляла следов в audit_log/БД (только stderr). Попутно доказан класс
краша: голый env("RENDER_URL") → ENV_NOT_FOUND → 500 маршрута; to_float
на не-числе → TYPE_MISMATCH (№514) → тот же тихий отказ.

A: маркер osp_empty_reply в обеих точках ответа ОСП + гвард авто-маршрута
   (было: исключение роняло весь маршрут 500, владелец не получал ничего).
B: RenderUrl() → env_or с явным фолбэком reverse-proxy.
C: извлечение p из CARD — to_float_or (мусор → -1, карточка в гейт).

Статические гварды — по исходникам (идиома test_n474); исполнение
mlog-тест-блоков — как в test_mlog_test_blocks_n474_pass.
"""
import os
import re
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_MLOG = os.path.join(REPO_ROOT, "app.mlog")
OSP_MLOG = os.path.join(REPO_ROOT, "dept", "osp.mlog")
UTILS_MLOG = os.path.join(REPO_ROOT, "dept", "utils.mlog")

APP = open(APP_MLOG, encoding="utf-8").read()
OSP = open(OSP_MLOG, encoding="utf-8").read()
UTILS = open(UTILS_MLOG, encoding="utf-8").read()
YANA = open(os.path.join(REPO_ROOT, "dept", "yana.mlog"), encoding="utf-8").read()


# ── A: наблюдаемость тихого отказа ────────────────────────────────────────

def test_a_direct_osp_branch_logs_marker():
    """Прямой /osp-маршрут: перед «не удалось получить ответ» — AuditLog-маркер."""
    needle = 'let _ = SendTelegramReply(chat_id, "ОСП: не удалось получить ответ. Попробуйте позже.")'
    assert needle in APP, "ветка отказа прямого маршрута не найдена"
    marker = 'AuditLog("osp_empty_reply", "osp",'
    assert APP.count(marker) >= 2, (
        f"маркер osp_empty_reply должен стоять в обеих точках, найдено {APP.count(marker)}")
    # маркер стоит ДО сообщения владельцу в каждой точке
    pos_msg = APP.index(needle)
    pos_marker = APP.index(marker)
    assert pos_marker < pos_msg, "маркер аудита должен писаться до SendTelegramReply"


def test_a_auto_route_osp_guarded():
    """Авто-маршрут dept==osp: HandleOSP под try, пустой ответ — честный отказ, не 500."""
    # авто-маршрут отличаем от моста /osp/analyze по SendVoiceReply рядом с гвардом
    anchor = "let mut reply = TryVal(try HandleOSP(query, chat_id))"
    idxs = [i for i in range(len(APP)) if APP.startswith(anchor, i)]
    assert len(idxs) == 2, (
        f"ожидаются 2 query-точки (мост + авто-маршрут), найдено {len(idxs)}")
    auto = [i for i in idxs if "SendVoiceReply" in APP[i:i + 1800]]
    assert len(auto) == 1, "не найден гвард авто-маршрута ОСП (с SendVoiceReply)"
    block = APP[auto[0] - 1200:auto[0] + 1600]
    assert 'if dept == "osp" then {' in block, "якорь вне блока авто-маршрута ОСП"
    assert 'SendTelegramReply(chat_id, "ОСП: не удалось получить ответ' in block, (
        "у авто-маршрута нет честного отказа владельцу при пустом ответе")
    # SendVoiceReply/SendReport — только в непустой ветке
    empty_branch = block[block.index('if to_string(reply) == "()" or reply == ""'):]
    empty_branch = empty_branch[:empty_branch.index("} else {")]
    assert "SendVoiceReply" not in empty_branch and "SendReport" not in empty_branch, (
        "пустой ответ не должен уходить в голосовой канал/отчёт")


def test_a_bridge_route_guarded_and_logged():
    """Мост /osp/analyze: HandleOSP под try, пустой ответ — 500 с маркером аудита."""
    idx = APP.index('route "/osp/analyze"')
    block = APP[idx:idx + 3200]
    assert "TryVal(try HandleOSP(query, chat_id))" in block, "HandleOSP моста не под гвардом"
    assert 'AuditLog("osp_empty_reply"' in block, "у моста нет маркера при пустом ответе"
    assert 'respond("500 osp bridge: empty reply")' in block, "мост должен честно отказывать 500"


def test_d_empty_strip_guard_all_three_osp_sites():
    """#771 D: пустой CardTailStrip не применяется — все 3 OSP-точки."""
    guard = "let stripped = CardTailStrip(to_string(reply))"
    assert APP.count(guard) == 3, (
        f"ожидаются 3 OSP-точки (мост, прямой /osp, авто-маршрут), найдено {APP.count(guard)}")
    for m in re.finditer(re.escape(guard), APP):
        follow = APP[m.end():m.end() + 200]
        assert 'if stripped != ""' in follow, "нет проверки пустоты после strip"


# ── B: RenderUrl без ENV_NOT_FOUND ────────────────────────────────────────

def test_b_renderurl_env_or_fallback():
    """RenderUrl — env_or с явным дефолтом, голого env() нет."""
    start = UTILS.index("pattern RenderUrl()")
    body = UTILS[start:UTILS.index("}", start) + 1]
    assert 'env_or("RENDER_URL"' in body, "RenderUrl не использует env_or"
    assert 'env("RENDER_URL")' not in body, "в RenderUrl остался голый env()"


# ── C: извлечение p из CARD без TYPE_MISMATCH ─────────────────────────────

def test_c_p_extraction_uses_to_float_or():
    """Обе точки извлечения p — to_float_or, не бросающий to_float."""
    assert 'to_float(to_string(json_get(cj, "p", "-1")))' not in OSP, (
        "остался незагороженный to_float на p из CARD — №514, класс тихого отказа")
    # 2 точки кода (Deep/Full) + вхождения в собственных mlog-тест-блоках
    assert OSP.count('to_float_or(to_string(json_get(cj, "p", "-1")), -1.0)') >= 2, (
        "ожидаются обе точки: OSPDeepAnalyze и OSPFullAnalyze")


# ── Исполнение mlog-тест-блоков (идиома n474) ─────────────────────────────

def test_mlog_test_blocks_n771_osp_pass():
    proc = subprocess.run(
        ["./bin/mlog", "test", "dept/osp.mlog"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
    combined = (proc.stdout + proc.stderr)
    assert proc.returncode == 0, combined
    assert "❌" not in combined, combined
    for name in (
        "n771 карточка: строковое p — гейт схемы отклоняет (FAIL, не краш)",
        "n771 карточка: валидное числовое p — OK",
        "n771 извлечение p: мусор в json — дефолт -1 через to_float_or, не TYPE_MISMATCH",
        "n771 извлечение p: число-строкой — парсится",
    ):
        assert name in combined, f"test-блок #771 не найден: {name}"


def test_mlog_test_blocks_n771_utils_pass():
    proc = subprocess.run(
        ["./bin/mlog", "test", "dept/utils.mlog"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
    combined = (proc.stdout + proc.stderr)
    assert proc.returncode == 0, combined
    assert "❌" not in combined, combined
    assert "n771 RenderUrl: env не задан — фолбэк reverse-proxy, не ENV_NOT_FOUND" in combined


# ── E: Яна молчала при мёртвом llm_proxy (воспроизведено на живом стеке) ──

def test_e_yana_route_guarded():
    """#771 E: авто-маршрут Яны — HandleYana и DispatchYanaDelegation под try,
    бросок = честный отказ + маркер, а не 500-тишина «Яна не отвечает»."""
    anchor = "let reply = TryVal(try HandleYana(yana_query, chat_id))"
    assert APP.count(anchor) == 1, "HandleYana маршрута не под гвардом"
    idx = APP.index(anchor)
    block = APP[idx:idx + 2600]
    assert 'AuditLog("yana_empty_reply"' in block, "нет маркера при броске HandleYana"
    assert "TryVal(try DispatchYanaDelegation(reply, query, chat_id))" in block, (
        "делегирование не под гвардом — бросок отдела ронял маршрут")
    assert 'AuditLog("yana_dispatch_fail"' in block, "нет маркера при броске делегирования"
    assert APP.count('"Яна: не удалось получить ответ. Попробуйте позже."') == 2, (
        "честный отказ должен стоять в обеих точках (HandleYana, делегирование)")


def test_e_yana_dead_proxy_check_fixed():
    """CallLLMProxy при мёртвом прокси возвращает \"\" — HandleYana теперь
    проверяет ОБА маркера (было только \"()\" — проверка проходила мимо),
    parse_json под гвардом: пустой/битый body → фолбэк, не краш маршрута."""
    start = YANA.index("let proxy_result = CallLLMProxy(dept, messages)")
    seg = YANA[start:start + 1200]
    assert 'proxy_result == ""' in seg, (
        "проверка мёртвого прокси не дополнена — parse_json(\"\") ронял маршрут")
    assert "TryVal(try parse_json(proxy_result))" in seg, "parse_json не под гвардом"
    assert seg.count('"Сервис временно недоступен. Попробуйте позже."') >= 2, (
        "оба отказных пути (пустой ответ прокси, битый JSON) должны давать фолбэк")
