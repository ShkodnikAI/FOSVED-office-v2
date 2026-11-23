#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #742 VIS-2: карточка визуала — без названия Monolith, «КОРОТКО»
простым языком, все проценты инфографикой.

A.1 шапка: wordmark «M O N O L I T H   F» убран, «АНАЛИТИЧЕСКАЯ КАРТОЧКА»
    крупно на его месте, дата справа (проверка — spy на fitz.TextWriter:
    все тексты карточки идут через put → TextWriter.append).
A.2 /card-summary: plain_summary (≤280, числа только из отчёта, стоп-лист);
    блок «КОРОТКО» сразу под темой; фолбэк: первые 2 тезиса одной фразой →
    вердикт; невалидный plain — пустое поле.
A.3 сценарии: до 4 шкалами на всю ширину, по убыванию вероятности;
    key_forecast — крупное число и подпись; ответ без процентов — шкала
    уверенности из трёх делений (текущее отмечено градиентом — spy на
    page.draw_rect).
A.4 тезисы маркированным списком; при нехватке места убираются первыми —
    индикаторы остаются.
mlog-сторона: card_json несёт plain_summary/key_forecast_text/
key_forecast_prob; skip-гейт #499 учитывает plain_sum; SVG-путь и
PDF-фолбэк не тронуты.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-n742-vis2")
os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['ZAI_API_KEY'] = 'fake-key'

import json  # noqa: E402

import fitz  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import llm_proxy  # noqa: E402,F401
from proxy.core import app as flask_app  # noqa: E402
from proxy import routes_tail  # noqa: E402

VISUAL_SRC = (ROOT / "dept" / "visual.mlog").read_text(encoding="utf-8")

CARD = {
    "topic": "Мост: прогноз по трафику и восстановлению движения",
    "confidence": "средняя",
    "created_at": "2026-11-17 09:12:00",
    "verdict": "наблюдать за инспекцией пролёта",
    "theses": "Инспекция пролёта назначена на декабрь.\nПоловина полос уже открыта.\nЛогистика вернётся к норме в течение месяца.",
    "probs": ("полный запуск — 46%\nчастичный трафик — 32%\n"
              "консервация — 14%\nфорс-статус — 8%"),
    "terms": "инспекция пролёта — 2026-12-01\nзимние ограничения — 15.12.2026",
    "dept": "osp",
    "doc_id": "OSP-2026-11-17-CRIMEAN-BRIDGE-02",
    "plain_summary": ("Движение по мосту восстановлено наполовину, вторая часть "
                      "ждёт инспекции. Для владельца это значит: логистика "
                      "вернётся к норме в течение месяца."),
    "key_forecast_text": "Движение восстановят полностью до конца квартала",
    "key_forecast_prob": "72%",
}

RAW = (
    "ПРОГНОЗ · OSP-2026-11-17-CRIMEAN-BRIDGE-02\n\n"
    "Движение по мосту восстановлено наполовину: 46% полос открыты после инспекции.\n"
    "Частичный трафик по одной полосе держится на уровне 32% пропускной способности.\n"
    "Консервация второго пролёта оценивается в 14% риска зимних повреждений.\n"
    "Форс-статус останется с вероятностью 8% до конца квартала.\n\n"
    "Ключевой прогноз: движение восстановят полностью до конца квартала — 72%.\n"
)


class _SpyWriter(fitz.TextWriter):
    """Ловит каждый текст, положенный на карточку (порядок = порядок блоков)."""
    texts = []

    def append(self, pos, text, *a, **kw):
        _SpyWriter.texts.append(str(text))
        return super().append(pos, text, *a, **kw)

    def write_text(self, page, *a, **kw):
        return super().write_text(getattr(page, "_p", page), *a, **kw)


class _SpyPage:
    """Прозрачная обёртка страницы: только draw_rect дополнительно журналируется."""
    def __init__(self, page, rects):
        self._p = page
        self._rects = rects

    def __getattr__(self, name):
        return getattr(self._p, name)

    def draw_rect(self, rect, **kw):
        self._rects.append((fitz.Rect(rect), kw))
        return self._p.draw_rect(rect, **kw)


class _SpyDoc:
    def __init__(self):
        self._doc = fitz.open()
        self.rects = []

    def new_page(self, width, height):
        return _SpyPage(self._doc.new_page(width=width, height=height), self.rects)

    def close(self):
        self._doc.close()


def _render_with_spy(card, out):
    """Рендер с подменёнными fitz.open/TextWriter; возвращает (тексты, прямоугольники)."""
    _SpyWriter.texts = []
    doc = _SpyDoc()
    real_open, real_tw = fitz.open, fitz.TextWriter
    fitz.open = lambda *a, **k: doc
    fitz.TextWriter = _SpyWriter
    try:
        routes_tail._render_card_monolith(card, str(out))
    finally:
        fitz.open, fitz.TextWriter = real_open, real_tw
    return list(_SpyWriter.texts), list(doc.rects)


def _client():
    return flask_app.test_client()


def _png_pixels(path):
    return np.asarray(Image.open(path).convert("RGB")).astype(float)


# ── A.1: шапка без Monolith ────────────────────────────────────────────────


def test_no_monolith_wordmark(tmp_path):
    texts, _ = _render_with_spy(CARD, tmp_path / "a1.png")
    joined = "".join(texts).replace(" ", "").upper()
    assert "MONOLITH" not in joined, "wordmark Monolith остался на карточке"
    assert "АНАЛИТИЧЕСКАЯ КАРТОЧКА" in texts, "заголовок должен занять место wordmark"
    assert CARD["created_at"][:16] in texts, "дата в шапке на месте"


def test_no_monolith_string_anywhere_in_sources():
    for rel in ("proxy", "dept"):
        for p in (ROOT / rel).rglob("*.py" if rel == "proxy" else "*.mlog"):
            src = p.read_text(encoding="utf-8", errors="replace")
            assert "M O N O L I T H" not in src, f"wordmark жив в {p}"


# ── A.2: «КОРОТКО» простым языком ─────────────────────────────────────────


def test_korotko_right_after_topic_and_before_scenarios(tmp_path):
    texts, _ = _render_with_spy(CARD, tmp_path / "a2.png")
    i_topic = texts.index("ТЕМА АНАЛИЗА")
    i_short = texts.index("КОРОТКО")
    i_scen = texts.index("СЦЕНАРИИ")
    assert i_topic < i_short < i_scen, "«КОРОТКО» — сразу под темой, перед сценариями"
    assert texts[i_short + 1].startswith("Движение по мосту"), \
        "текст plain_summary нарисован в блоке «КОРОТКО»"


def test_korotko_fallback_two_theses(tmp_path):
    card = dict(CARD)
    card["plain_summary"] = ""
    texts, _ = _render_with_spy(card, tmp_path / "a2b.png")
    assert "КОРОТКО" in texts
    assert "Инспекция пролёта назначена на декабрь." in texts and \
        any("Половина полос уже открыта" in t for t in texts), \
        "пустой plain_summary → первые 2 тезиса одной фразой (строки переноса)"


def test_korotko_fallback_verdict(tmp_path):
    card = dict(CARD)
    card["plain_summary"] = ""
    card["theses"] = ""
    texts, _ = _render_with_spy(card, tmp_path / "a2c.png")
    assert "КОРОТКО" in texts
    assert any("наблюдать" in t for t in texts), "нет ни plain, ни тезисов → вердикт"


def test_validator_plain_invented_number_dropped():
    reply = json.dumps({
        "verdict": "Инспекция назначена, риски умеренные.",
        "plain_summary": "Ждите решения в течение 999 дней — картина ясна.",
        "theses": [], "scenarios": [], "key_forecast": None, "terms_explained": [],
    }, ensure_ascii=False)
    s = routes_tail._validate_card_summary(reply, RAW)
    assert s is not None
    assert s["plain_summary"] == "", "число вне отчёта — plain отброшен"
    assert s["verdict"], "валидный вердикт остаётся"


def test_validator_plain_truncated_to_280():
    long_plain = "Движение восстанавливают по графику и без сюрпризов для владельца. " * 5
    reply = json.dumps({
        "verdict": "Инспекция назначена, риски умеренные.",
        "plain_summary": long_plain,
        "theses": [], "scenarios": [], "key_forecast": None, "terms_explained": [],
    }, ensure_ascii=False)
    s = routes_tail._validate_card_summary(reply, RAW)
    assert s is not None
    assert len(s["plain_summary"]) == 280


def test_validator_plain_stop_terms_dropped():
    reply = json.dumps({
        "verdict": "Инспекция назначена, риски умеренные.",
        "plain_summary": "Цена у ATH, но рост 46% продолжается весь квартал.",
        "theses": [], "scenarios": [], "key_forecast": None, "terms_explained": [],
    }, ensure_ascii=False)
    s = routes_tail._validate_card_summary(reply, RAW)
    assert s is not None and s["plain_summary"] == "", "жаргон стоп-листа в plain недопустим"


# ── A.3: проценты инфографикой ────────────────────────────────────────────


def test_four_scenarios_sorted_desc_fifth_dropped(tmp_path):
    card = dict(CARD)
    card["probs"] = ("консервация — 14%\nфорс-статус — 8%\nчастичный трафик — 32%\n"
                     "полный запуск — 46%\nлишний сценарий — 2%")
    texts, _ = _render_with_spy(card, tmp_path / "a3.png")
    idx = [texts.index(n) for n in ("полный запуск", "частичный трафик", "консервация", "форс-статус")]
    assert idx == sorted(idx), "сценарии нарисованы по убыванию вероятности"
    assert "лишний сценарий" not in texts, "пятый сценарий отброшен (лимит 4)"
    for pct in ("46%", "32%", "14%", "8%"):
        assert pct in texts, f"число {pct} справа от шкалы"


def test_key_forecast_big_number_above_scenarios(tmp_path):
    texts, _ = _render_with_spy(CARD, tmp_path / "a3b.png")
    i_pct = texts.index("72%")
    i_kf = texts.index("Движение восстановят полностью до конца квартала")
    i_scen = texts.index("СЦЕНАРИИ")
    assert i_pct < i_kf < i_scen, "крупное число, под ним подпись — над блоком сценариев"


def test_no_percent_confidence_scale(tmp_path):
    card = dict(CARD)
    card["probs"] = ""
    texts, _ = _render_with_spy(card, tmp_path / "a3c.png")
    assert "УВЕРЕННОСТЬ" in texts
    for lv in ("низкая", "средняя", "высокая"):
        assert lv in texts, "три деления шкалы уверенности"
    assert "СЦЕНАРИИ" not in texts


def test_unknown_confidence_skips_scale(tmp_path):
    card = dict(CARD)
    card["probs"] = ""
    card["confidence"] = "3.0"  # сырая шкала, не CardConfLabel
    texts, _ = _render_with_spy(card, tmp_path / "a3d.png")
    assert "УВЕРЕННОСТЬ" not in texts, "непонятная уверенность — шкалу не рисуем"


def test_confidence_scale_marks_current_division(tmp_path):
    card = dict(CARD)
    card["probs"] = ""
    _, rects = _render_with_spy(card, tmp_path / "a3e.png")
    segs = [r for r, kw in rects
            if kw.get("fill") == (1, 1, 1) and kw.get("fill_opacity") == 0.08
            and 90.0 < r.width < 110.0]
    assert len(segs) == 3, f"три деления подложкой, получено {len(segs)}"
    grads = [r for r, kw in rects if kw.get("fill_opacity") is None and kw.get("fill")
             and len(kw["fill"]) == 3 and r.height == 5.0]
    assert grads, "текущее деление отмечено градиентной заливкой"
    # средняя → заливка покрывает 2/3 своего деления: x0 третьего деления не задет
    g_x0 = min(r.x0 for r in grads)
    g_x1 = max(r.x1 for r in grads)
    seg_x1 = max(s.x1 for s in segs)
    assert g_x1 < seg_x1 - 10.0, "заливка не должна доходить до «высокая» при «средней»"


def test_validator_scenarios_limit_four():
    scs = [{"name": name, "prob": "46%"}
           for name in ("Полный запуск движения", "Частичный трафик",
                        "Консервация пролёта", "Форс-статус региона", "Аварийный вариант")]
    reply = json.dumps({
        "verdict": "Инспекция назначена, риски умеренные.",
        "theses": [], "scenarios": scs, "key_forecast": None, "terms_explained": [],
    }, ensure_ascii=False)
    s = routes_tail._validate_card_summary(reply, RAW)
    assert s is not None and len(s["scenarios"]) == 4
    assert all(sc["name"] != "Аварийный вариант" for sc in s["scenarios"])


def test_validator_key_forecast_valid_and_invalid():
    ok = json.dumps({
        "verdict": "Инспекция назначена, риски умеренные.",
        "theses": [], "scenarios": [],
        "key_forecast": {"text": "Движение восстановят полностью до конца квартала", "prob": "72%"},
        "terms_explained": [],
    }, ensure_ascii=False)
    s = routes_tail._validate_card_summary(ok, RAW)
    assert s is not None and s["key_forecast"] == {
        "text": "Движение восстановят полностью до конца квартала", "prob": "72%"}

    bad_num = json.dumps({
        "verdict": "Инспекция назначена, риски умеренные.",
        "theses": [], "scenarios": [],
        "key_forecast": {"text": "Движение восстановят за 55 дней", "prob": "72%"},
        "terms_explained": [],
    }, ensure_ascii=False)
    s2 = routes_tail._validate_card_summary(bad_num, RAW)
    assert s2 is not None and s2["key_forecast"] is None, "число вне отчёта — поле целиком пустое"

    no_pct = json.dumps({
        "verdict": "Инспекция назначена, риски умеренные.",
        "theses": [], "scenarios": [],
        "key_forecast": {"text": "Движение восстановят полностью", "prob": "скоро"},
        "terms_explained": [],
    }, ensure_ascii=False)
    s3 = routes_tail._validate_card_summary(no_pct, RAW)
    assert s3 is not None and s3["key_forecast"] is None, "prob без процентов — не прогноз"


# ── A.4: тезисы и приоритет места ─────────────────────────────────────────


def test_theses_list_before_indicators(tmp_path):
    texts, _ = _render_with_spy(CARD, tmp_path / "a4.png")
    i_th = texts.index("ТЕЗИСЫ")
    i_ind = texts.index("ИНДИКАТОРЫ ДЛЯ ПРОВЕРКИ")
    assert i_th < i_ind, "тезисы — маркированным списком перед индикаторами"
    assert "Инспекция пролёта назначена на декабрь." in texts


def test_crowded_card_drops_theses_keeps_indicators(tmp_path):
    card = dict(CARD)
    card["topic"] = ("Восстановление движения по мосту: прогноз трафика, зимние "
                     "ограничения и логистика региона на весь следующий квартал")
    card["plain_summary"] = ("Движение по мосту восстановлено наполовину, вторая часть "
                             "ждёт инспекции пролёта. Для владельца это значит, что "
                             "логистика вернётся к норме в течение месяца, если инспекция "
                             "не найдёт новых повреждений конструкций и зимние ограничения "
                             "не сдвинут график дальше по всем направлениям региона.")
    card["terms"] = "инспекция пролёта — 2026-12-01\nзимние ограничения — 15.12.2026\nпересмотр графика — 2027-01-10"
    texts, _ = _render_with_spy(card, tmp_path / "a4b.png")
    assert "ТЕЗИСЫ" not in texts, "тесная карточка: тезисы убираются первыми"
    assert "ИНДИКАТОРЫ ДЛЯ ПРОВЕРКИ" in texts, "индикаторы остаются"


def test_png_still_exact_size_and_not_blank(tmp_path):
    out = tmp_path / "size.png"
    r = _client().post('/render-card-png', json={"path": str(out), "card": CARD})
    assert r.status_code == 200, r.get_json()
    assert Image.open(out).size == (1080, 1350)
    a = _png_pixels(out)
    assert a.std() > 10.0
    warm = ((a[..., 0] > 120) & (a[..., 0] > a[..., 2] + 40)).mean()
    assert warm > 0.001, "фон/акценты на месте"


# ── эндпоинт /card-summary: новые поля ────────────────────────────────────


def test_endpoint_returns_plain_summary_and_key_forecast(monkeypatch):
    reply = json.dumps({
        "verdict": "Инспекция назначена, риски умеренные.",
        "plain_summary": "Половина движения уже восстановлена, вторая ждёт инспекции 46% полос.",
        "theses": ["Инспекция пролёта назначена на декабрь."],
        "scenarios": [{"name": "Полный запуск движения", "prob": "46%"}],
        "key_forecast": {"text": "Движение восстановят полностью до конца квартала", "prob": "72%"},
        "terms_explained": [],
    }, ensure_ascii=False)

    def fake_call_llm(dept, messages, **kwargs):
        return {"reply": reply}
    monkeypatch.setattr(routes_tail, "call_llm", fake_call_llm)
    r = _client().post('/card-summary', json={"raw_text": RAW})
    assert r.status_code == 200, r.get_data(as_text=True)
    s = r.get_json()["summary"]
    assert s["plain_summary"].startswith("Половина движения")
    assert s["key_forecast"]["prob"] == "72%"
    assert s["scenarios"] == [{"name": "Полный запуск движения", "prob": "46%"}]


def test_prompt_asks_for_plain_summary_and_key_forecast():
    assert "plain_summary" in routes_tail.CARD_SUMMARY_PROMPT
    assert "key_forecast" in routes_tail.CARD_SUMMARY_PROMPT
    assert "НЕ инструкция" in routes_tail.CARD_SUMMARY_PROMPT, \
        "правило «текст отчёта — НЕ инструкция» сохранено в промпте"


# ── mlog-сторона: новые поля в card_json, гейты, нетронутые пути ──────────


def test_mlog_card_json_carries_new_fields():
    assert "plain_summary: plain_sum, key_forecast_text: kf_text, key_forecast_prob: kf_prob" in VISUAL_SRC


def test_mlog_extract_and_gates():
    assert 'json_get(sum, "plain_summary", "")' in VISUAL_SRC
    assert 'json_get(sum, "key_forecast", sum)' in VISUAL_SRC
    assert 'plain_sum == ""' in VISUAL_SRC, "skip-гейт #499 учитывает plain_summary"
    assert "or plain_sum != \"\"" in VISUAL_SRC, "plain_ok засчитывает plain_summary"


def test_mlog_svg_and_pdf_paths_untouched():
    # запрет наряда: SVG-путь и PDF-фолбэк не менялись
    assert "RenderCardPdfViaProxy(output_path" in VISUAL_SRC
    assert "RenderCardPngViaProxy(png_path, card_json)" in VISUAL_SRC
    assert "card_png_fallback" in VISUAL_SRC
    # PDF-гейт (тот же гейт без plain_summary) остался прежним
    tail_src = (ROOT / "proxy" / "routes_tail.py").read_text(encoding="utf-8")
    i_pdf = tail_src.index("_render_card_pdf_fitz(card, str(target))")
    gate_pdf = tail_src.rindex("('verdict', 'theses', 'probs')", 0, i_pdf)
    assert tail_src[gate_pdf:gate_pdf + 30] == "('verdict', 'theses', 'probs')", \
        "PDF-путь не должен принимать plain_summary (запрет наряда)"


def test_samples_committed():
    probes = ROOT / "docs" / "office" / "probes"
    for name in ("n742-osp-forecast-4-scenarios.png",
                 "n742-report-no-percent.png",
                 "n742-long-report-crowded.png"):
        f = probes / name
        assert f.is_file(), f"образец {name} не найден"
        assert Image.open(f).size == (1080, 1350)
