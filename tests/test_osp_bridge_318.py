"""Гвард наряда №318: LZ→OSP мост — POST /osp/analyze.

Роут обещан LZ Native v2.0 (dept/lz.mlog:129,288), ранее не существовал:
обе стороны глотали 404 через TryVal, OSP-обогащение молча отсутствовало.

Контракт (доказан пробой scripts/probe318qp.{mlog,sh} на живом 0.21):
- auth — secret в query, hash-compare по конвенции /schedules/create (№327);
- вызывающая сторона энкодит секрет replace('+'→%2B, ' '→%20): 0.21 декодирует
  query ('+'→пробел, url_decode_fallback), прокси перекодирует request.args —
  сырому '+' через цепочку mlang→прокси→mlog не выжить (raw+'=403, %2B=200);
- query="ping" — проба живости без LLM-расхода;
- fire-and-forget: таймаут 5.0 на вызывающей стороне, доставка — TG владельцу.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
LZ = (REPO_ROOT / "dept" / "lz.mlog").read_text(encoding="utf-8")

ROUTE_DECL = 'route "/osp/analyze" method=POST'


def _route_block() -> str:
    start = APP.index(ROUTE_DECL)
    # блок до следующего объявления роута
    next_route = APP.index("\n  route ", start + len(ROUTE_DECL))
    return APP[start:next_route]


def test_route_exists_exactly_once():
    assert APP.count(ROUTE_DECL) == 1, "роут /osp/analyze должен быть ровно один"


def test_auth_is_query_secret_hash_compare():
    block = _route_block()
    # №376: предварительный redact("all") сохранён — требование taint-валидатора
    # (untrusted query_param не решает 'if' без one-way-redact, Wave 15).
    assert 'redact(query_param("secret"), "all")' in block, \
        "one-way-redact query_param перед решением if — конвенция №327 + taint Wave 15"
    # №327: ожидание строится как redact-hash секрета (ОДИН hash)
    assert 'let expected = to_string(redact(cron_secret, "hash_only"))' in block, \
        "ожидание строится как redact-hash секрета"
    # №376: сравнение против ОДНОГО H(secret), обе формы:
    # hash-form дословно (мост LZ №318) ИЛИ hash(received)==H(secret) (raw, cron-стиль).
    # Исторический паттерн 'redact(expected, "hash_only")' (двойной хэш) запрещён —
    # при неидемпотентном redact (0.24/0.25) он делал raw-форму всегда 403.
    assert 'if received != expected and redact(received, "hash_only") != expected then { return respond("403 Forbidden") }' in block, \
        "№376: приём обеих форм секрета против одного H(secret)"
    assert 'redact(expected, "hash_only")' not in block, \
        "№376: двойной хэш ожидания запрещён (raw-форма непроходима при неидемпотентном redact)"
    assert 'if cron_secret == "" then { return respond("403 Forbidden") }' in block, \
        "пустой env-секрет = 403 (fail-closed)"


def test_ping_probe_present_no_llm():
    block = _route_block()
    assert '"ping"' in block, "ping-проба обязательна (проверка живости без LLM)"
    assert '"200 osp-analyze: ok"' in block


def test_route_dispatches_handle_osp_and_tg():
    block = _route_block()
    assert "HandleOSP(" in block, "анализ должен идти через HandleOSP"
    assert "SendTelegramReply(" in block, "результат доставляется владельцу в TG"
    assert "InitDB()" in block, "AuditLog/RecordAssistantMessage требуют контур БД"


def test_lz_bridge_has_exactly_two_sites():
    # naryad-355: роут /osp/analyze — нативный serve (:10001), не Flask (:4000);
    # прежний адрес :4000/osp/analyze был 404 на каждый вызов
    assert LZ.count("127.0.0.1:10001/osp/analyze?secret=") == 2, \
        "мост LZ→OSP: ровно 2 вызывающих сайта на serve :10001 (LZGateOSPReferral + HandleLZ)"
    assert LZ.count("127.0.0.1:4000/osp/analyze") == 0, \
        "мёртвый Flask-адрес должен исчезнуть полностью"


def test_lz_bridge_sends_one_way_hash_not_secret():
    # в query — redact-hash секрета (public-метка: нет private-egress;
    # hex — URL-safe: нет '+'/' ', не ломается на декоде 0.21/прокси)
    assert LZ.count('?secret=" + redact(env("CRON_SECRET"), "hash_only")') == 2, \
        "оба сайта обязаны слать redact-hash, не сам секрет"
    for tail in LZ.split("127.0.0.1:10001/osp/analyze?secret=")[1:]:
        chunk = tail[:600]
        assert '"application/json", 5.0))' in chunk, \
            "короткий таймаут 5.0 обязателен (fire-and-forget, UX интерактива)"


def test_lz_bridge_body_carries_no_secret():
    # секрет в query (аргумент 0), НЕ в теле: env-значение в data-аргументе
    # http_post даёт taint private → Category-A private-egress (аудит №312)
    for tail in LZ.split("127.0.0.1:10001/osp/analyze?secret=")[1:]:
        chunk = tail[:400]
        assert "secret:" not in chunk.split("json_encode")[1].split("}")[0], \
            "тело вызова не должно нести секрет (private-egress аудит)"
