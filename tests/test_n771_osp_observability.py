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
    """#771 E: обе ветки Яны (dept=="yana" и по умолчанию) — HandleYana и
    делегирование через ретрай-хварды #771 F, бросок = честный отказ + маркер."""
    anchor = "let reply = HandleYanaRetry(yana_query, chat_id)"
    assert APP.count(anchor) == 1, "HandleYanaRetry маршрута (ветка dept==yana) не подключён"
    assert APP.count("let reply = HandleYanaRetry(text, chat_id)") == 1, (
        "HandleYanaRetry ветки по умолчанию не подключён — тот же вектор тишины")
    idx = APP.index(anchor)
    block = APP[idx:idx + 2600]
    assert 'AuditLog("yana_empty_reply"' in block, "нет маркера при броске HandleYana"
    assert "DispatchYanaDelegationRetry(reply, query, chat_id)" in block, (
        "делегирование не под ретрай-гвардом — бросок отдела ронял маршрут")
    assert 'AuditLog("yana_dispatch_fail"' in block, "нет маркера при броске делегирования"
    assert APP.count('"Яна: не удалось получить ответ. Попробуйте позже."') == 4, (
        "честный отказ должен стоять в 4 точках (2 ветки × 2 гварда)")


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


# ── F: ретрай при транзиентном write-локе БД (инцидент 24.11 13:26) ───────

def test_f_retry_helpers_exist():
    """#771 F: HandleYanaRetry/HandleOSPRetry/DispatchYanaDelegationRetry —
    один ретрай после sleep(8) на бросок db_execute «database is locked»
    (движок: WAL, busy_timeout ≈5 с, доказано пробой n771f)."""
    for name, src, wrapped in (
        ("HandleYanaRetry", YANA, "HandleYana(query, chat_id)"),
        ("HandleOSPRetry", OSP, "HandleOSP(query, chat_id)"),
        ("DispatchYanaDelegationRetry", APP, "DispatchYanaDelegation(reply, query, chat_id)"),
    ):
        idx = src.index(f"pattern {name}(")
        seg = src[idx:src.index("}", src.index("return \"THROW|", idx)) + 1]
        # #771 G: сырой try-результат (Struct{ok, value, error}), TryVal достаёт
        # .value, причина — .error.message (идиом admin.mlog:491)
        assert seg.count(f"try {wrapped}") == 2, f"{name}: ровно один ретрай"
        assert seg.count("= TryVal(tr") == 2, f"{name}: значение через TryVal(tr)"
        assert seg.count("to_string(tr.error.message)") == 1 and seg.count("to_string(tr2.error.message)") == 1, \
            f"{name}: обе причины броска должны захватываться"
        assert "sleep(8.0)" in seg, f"{name} без паузы — ретрай в лоб не покрывает окно лока"
        assert 'return "THROW|' in seg, f"{name}: двойной бросок возвращает THROW| с причиной"


def test_f_route_call_sites_use_retry():
    """Все 5 точек маршрута зовут ретрай-хелперы: прямой /osp, обе ветки
    Яны (HandleYana + делегирование)."""
    assert APP.count("let mut reply = HandleOSPRetry(text, chat_id)") == 1
    assert APP.count("let reply = HandleYanaRetry(yana_query, chat_id)") == 1
    assert APP.count("let reply = HandleYanaRetry(text, chat_id)") == 1
    assert APP.count("DispatchYanaDelegationRetry(reply, query, chat_id)") == 1
    assert APP.count("DispatchYanaDelegationRetry(reply, text, chat_id)") == 1
    # прямые (безретрайные) вызовы в маршруте больше не живут
    assert "TryVal(try HandleOSP(text, chat_id))" not in APP
    assert "TryVal(try HandleYana(" not in APP


# ── G: отказ само-диагностирующийся — причина владельцу и в маркер ────────

def test_g_throw_causes_reach_owner_and_audit():
    """#771 G: THROW| от ретрай-хелпера → причина (TryResult.error.message)
    попадает и в сообщение владельцу («Причина: …»), и в маркер audit_log.
    Третий повтор инцидента показал: без причины в сообщении владелец
    не может передать диагностику, а stderr прода недоступен."""
    # каждая точка различает THROW| дважды: в условии гварда и при выборе
    # текста отказа (с причиной / общий)
    assert APP.count('starts_with(reply, "THROW|")') == 6, "3 точки × (гвард + выбор сообщения)"
    assert APP.count('starts_with(del, "THROW|")') == 4, "2 гварда делегирования × (гвард + выбор)"
    idx = APP.index("let mut reply = HandleOSPRetry(text, chat_id)")
    osp_block = APP[idx:idx + 2200]
    assert 'starts_with(reply, "THROW|")' in osp_block, "прямой /osp не различает THROW|"
    assert osp_block.count('Причина: ') == 1, "прямой /osp: причина должна быть в сообщении владельцу"
    assert 'substring(reply, 6.0, 240.0)' in osp_block, "причина должна вырезаться из THROW|"
    # маркеры несут причину (детали = query + substring(reply/del))
    assert 'AuditLog("osp_empty_reply", "osp", "query=" + substring(text, 0.0, 80.0) + " seam=" + substring(seam, 0.0, 40.0) + " len=" + to_string(length(to_string(reply))) + " " + cause)' in APP
    assert APP.count('substring(reply, 0.0, 300.0)') == 2, "оба маркера yana_empty_reply несут причину"
    assert APP.count('substring(del, 0.0, 300.0)') == 2, "оба маркера yana_dispatch_fail несут причину"
    # plain-отказы остаются для пустого ответа (не броска)
    assert APP.count('"Яна: не удалось получить ответ. Попробуйте позже."') == 4
    assert APP.count('"ОСП: не удалось получить ответ. Попробуйте позже."') == 2


# ── H: корень инцидентов 23-24.11 — гейт serve-чтений vs внешний DATA_DIR ──

REPO_H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_h_entrypoint_forces_data_dir_to_app_root():
    """Корень трёх отказов (23.11, 24.11 ×2): гейт serve-чтений (№455)
    ограничивает пути METALOGOS_DATA_DIR; дефолт entrypoint '.' перебивался
    внешним env Render — корпус (skills/, library/, config/) оказывался вне
    сандбокса, каждый запрос отдела падал с SANDBOX_VIOLATION. ADR-0009:
    корень containment = корень приложения — entrypoint форсирует его
    АБСОЛЮТНЫМ значением с громким бут-логом. БД не подчинена DATA_DIR
    (db { url: env(DATABASE_URL) }); kv-кэш (data/metalogos_kv.db) при смене
    локации пересобирается сам — это кэш."""
    ep = open(os.path.join(REPO_H, "entrypoint.sh"), encoding="utf-8").read()
    assert 'export METALOGOS_DATA_DIR="$(pwd)"' in ep, "DATA_DIR не форсируется в корень приложения"
    assert "№771H" in ep, "нет громкого бут-лога с прежним значением env"
    # мягкий дефолт, который молча перебивался снаружи, не должен жить
    assert 'METALOGOS_DATA_DIR="${METALOGOS_DATA_DIR:-.}"' not in ep


def test_h_no_ungated_corpus_reads_in_dept():
    """Все чтения корпуса в dept/*.mlog — через SkillFileRead (try-грейс,
    «громкий пропуск» #623 W0) или явный try. Голый read_file/read_file_or —
    красный: одно чтение роняет весь запрос/слот (класс 24.11)."""
    import re
    bad = []
    import glob
    for f in sorted(glob.glob(os.path.join(REPO_H, "dept", "*.mlog"))):
        src = open(f, encoding="utf-8").read()
        for m in re.finditer(r"read_file(?:_or)?\(", src):
            pre = src[max(0, m.start() - 80):m.start()]
            if "try " in pre or "SkillFileRead" in pre:
                continue
            line = src[:m.start()].count("\n") + 1
            bad.append(f"{os.path.basename(f)}:{line}")
    assert not bad, f"незащищённые чтения корпуса: {bad}"


def test_h_skill_file_read_normalizes():
    """SkillFileRead — единая точка чтений корпуса: try + нормализация
    «()»/пустоты + redact внутри; бросок гейта превращается в «громкий
    пропуск», ответ уходит без скилла (доказано пробой n771h V3)."""
    skills = open(os.path.join(REPO_H, "dept", "skills.mlog"), encoding="utf-8").read()
    assert "pattern SkillFileRead(path: String) -> String" in skills
    assert 'TryVal(try read_file_or(path, ""))' in skills
    assert 'if raw == "()" or raw == "" then' in skills
    ctx = open(os.path.join(REPO_H, "dept", "context.mlog"), encoding="utf-8").read()
    assert ctx.count("SkillFileRead(") == 25, "24 скилла Tier1-3 + ReadDeptProfile"
    assert 'SkillFileRead("library/" + dept + ".md")' in ctx
