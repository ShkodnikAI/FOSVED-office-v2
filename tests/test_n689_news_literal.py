#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#689 NEWS-1: ЛЗ получает заголовок и источник новости (не только URL);
подвал отчёта ЛЗ считает вошло/не вошло; мировые события в брифе — дословно
из сборщика, не пересказ модели.

Гвардии (по наряду):
- A.1: в analysis_messages новость — строкой «[<source>] <title> — <url>»
  (+ summary до 300 символов); мутация «вернуть только URL» красит
  поведенческий и структурный тесты;
- A.2: подвал отчёта «Новостей на входе N, в отчёт вошло M, не вошло K» —
  программой, по URL входных новостей против текста отчёта;
- B.1: раздел «🌍 Важные мировые события» собирает программа из
  night_news_keys (до 5 пунктов «📌 <title> (<source>)» в порядке сборщика),
  пункт 4 из задачи модели удалён, данные событий из промпта убраны;
  мок модели с выдуманной деталью («партия налоговой реформы» — инцидент
  брифа 08.11) в итоговый текст не попадает.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-test-db-n689')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')
os.environ.setdefault('CRON_SECRET', 'cron-test-secret')

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTES = (REPO_ROOT / "proxy" / "routes_sched.py").read_text(encoding="utf-8")
LZ_SRC = (REPO_ROOT / "proxy" / "lz_github.py").read_text(encoding="utf-8")

import llm_proxy  # noqa: F402,E402
from proxy.core import app as flask_app, _query  # noqa: E402
from proxy import lz_github as lz  # noqa: E402
import proxy.routes_sched as rs  # noqa: E402

CLIENT = flask_app.test_client()

KOMM_URL = "https://www.kommersant.ru/doc/1234567"


def _seed_news(source, title, url, hash_, summary="s", category="news_ru"):
    _query("INSERT INTO news_cache (source, title, summary, url, category, published, collected, hash) "
           "VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?)",
           (source, title, summary, url, category, hash_))


def _clear_fresh_news():
    # чужие тесты сеют свежие строки в общую тест-БД — изолируем свои прогоны
    _query("DELETE FROM news_cache WHERE collected > datetime('now', '-24 hours')")


@pytest.fixture()
def n689_isolated():
    """Чистые свежие новости + реестр сообщённого под наши каналы."""
    _clear_fresh_news()
    _query("DELETE FROM reported_items WHERE channel IN ('lz_daily', 'brief_events')")
    _query("DELETE FROM audit_log WHERE action IN ('scheduler_morning_brief', 'lz_daily_report')")
    yield
    _clear_fresh_news()
    _query("DELETE FROM reported_items WHERE channel IN ('lz_daily', 'brief_events')")
    _query("DELETE FROM audit_log WHERE action IN ('scheduler_morning_brief', 'lz_daily_report')")


def _lz_scan_mocks(monkeypatch, llm_reply="1. 🔥 тест"):
    """GitHub-скан пуст (только новости), модель — заглушка с захватом промпта."""
    captured = {}
    monkeypatch.setattr(lz, "_github_search", lambda q, per_page=3: [])
    monkeypatch.setattr(lz, "_github_releases", lambda repo: [])
    monkeypatch.setattr(lz, "_build_github_queries", lambda: ["q"])

    def _stub_llm(dept, messages):
        captured["messages"] = messages
        return {"reply": llm_reply, "provider": "stub"}

    monkeypatch.setattr(lz, "call_llm", _stub_llm)
    monkeypatch.setattr(lz, "_tg_send_message", lambda owner_id, text, **kw: 77)
    return captured


# ──────────────────────────── A.1: заголовок и источник ────────────────────────────

class TestLzNewsTitleSource:
    def test_prompt_carries_title_and_source(self, n689_isolated, monkeypatch):
        """A.1 по букве наряда: для новости с адресом kommersant.ru/doc/…
        в analysis_messages есть её заголовок и источник (не только URL)."""
        _seed_news("kommersant", "ЦБ поднял ставку", KOMM_URL, "h-n689-a1")
        captured = _lz_scan_mocks(monkeypatch)
        r = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
        assert r.status_code == 200, r.get_data(as_text=True)
        user_msg = captured["messages"][1]["content"]
        assert f"[kommersant] ЦБ поднял ставку — {KOMM_URL}" in user_msg, user_msg[-800:]

    def test_prompt_carries_summary(self, n689_isolated, monkeypatch):
        """A.1: summary непустой — в промпте (до 300 символов)."""
        long_summary = "С" * 500
        _seed_news("tass", "Заголовок", "https://n689.example/sum", "h-n689-sum", summary=long_summary)
        captured = _lz_scan_mocks(monkeypatch)
        CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
        user_msg = captured["messages"][1]["content"]
        assert "С" * 300 in user_msg, "summary обрезан до 300 символов"
        assert "С" * 301 not in user_msg, "summary длиннее 300 не проходит"

    def test_news_line_format_in_source(self):
        """Структурный гвард: строка новости — «[<источник>] <заголовок> — <URL>»
        (мутация «вернуть только URL» красит и этот, и поведенческий тест)."""
        assert 'line = f"[{src}] {title} — {u}\\n"' in LZ_SRC

    def test_lz_items_carry_source_and_summary(self):
        assert '"source": nr[0] or "", "summary": nr[2] or ""' in LZ_SRC


# ──────────────────────────── A.2: учёт пропущенного ────────────────────────────

class TestLzNewsFooter:
    def test_footer_counts_in_out(self, n689_isolated, monkeypatch):
        """A.2 по букве: 10 новостей на входе, модель упомянула 6 →
        подвал «на входе 10, вошло 6, не вошло 4»."""
        urls = [f"https://n689.example/item-{i:02d}" for i in range(1, 11)]
        for i, u in enumerate(urls, 1):
            _seed_news("src689", f"Новость {i}", u, f"h-n689-c{i:02d}")
        reply = "\n".join(f"{i}. 🔥 событие {u}" for i, u in enumerate(urls[:6], 1))
        _lz_scan_mocks(monkeypatch, llm_reply=reply)
        r = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
        assert r.status_code == 200, r.get_data(as_text=True)
        report = r.get_json()["report"]
        assert "Новостей на входе 10, в отчёт вошло 6, не вошло 4" in report, report[-400:]

    def test_footer_absent_without_news(self, n689_isolated, monkeypatch):
        """Новостей на входе нет — подвала учёта нет (модель не вызывалась:
        GitHub-скан пуст и новостей нет → «новых находок нет»)."""
        _lz_scan_mocks(monkeypatch)
        r = CLIENT.post("/scheduler/lz-daily", json={"owner_id": "12345", "deliver": "telegram"})
        assert r.status_code == 200, r.get_data(as_text=True)
        report = r.get_json()["report"]
        assert "Новостей на входе" not in report
        assert "новых находок нет" in report

    def test_footer_computed_in_source(self):
        assert '"Новостей на входе {n_in}, в отчёт вошло {n_hit}, "' in LZ_SRC


# ──────────────────────────── B.1: мировые события — дословно ────────────────────────────

class TestBuildWorldEventsSection:
    def test_verbatim_titles_with_source(self):
        items = [
            {"key": "k1", "title": "New Zealand election too close to call", "source": "guardian"},
            {"key": "k2", "title": "ЦБ сохранил ставку", "source": "tass"},
        ]
        out = rs.build_world_events_section(items)
        assert "🌍 Важные мировые события:" in out
        assert "📌 New Zealand election too close to call (guardian)" in out
        assert "📌 ЦБ сохранил ставку (tass)" in out
        assert out.index("New Zealand") < out.index("ЦБ сохранил"), "порядок сборщика"

    def test_capped_at_five(self):
        items = [{"key": f"k{i}", "title": f"t{i}", "source": "s"} for i in range(8)]
        out = rs.build_world_events_section(items)
        assert out.count("📌") == 5
        assert "📌 t0" in out and "📌 t5" not in out

    def test_empty_honest_line(self):
        assert "За ночь значимых событий не зафиксировано" in rs.build_world_events_section([])

    def test_no_source_no_parens(self):
        out = rs.build_world_events_section([{"key": "k", "title": "T", "source": ""}])
        assert "📌 T\n" in out or out.endswith("📌 T")


class TestStripModelWorldEvents:
    def test_invented_detail_dropped(self):
        """Инцидент брифа 08.11: модель дописала «партию налоговой реформы» —
        раздел из ответа модели вырезается целиком."""
        text = ("*Утренний отчёт*\n"
                "3. 🏢 Офис работает штатно.\n"
                "4. 🌍 Важные мировые события\n"
                "В Новой Зеландии проходят выборы, где решает партия налоговой реформы.\n"
                "5. 🔍 Находки ЛЗ: нет\n")
        out = rs.strip_model_world_events(text)
        assert "партия налоговой реформы" not in out
        assert "Офис работает штатно" in out
        assert "Находки ЛЗ: нет" in out

    def test_plain_marker_without_emoji(self):
        text = "Мировые события: что-то произошло\nПродолжение выдумки\n1. 🔍 Далее"
        out = rs.strip_model_world_events(text)
        assert "что-то произошло" not in out
        assert "Выдумка" not in out
        assert "1. 🔍 Далее" in out

    def test_text_without_markers_untouched(self):
        text = "1. 📅 Понедельник\n2. 🌤 Дождь\n3. 🏢 Офис работает"
        assert rs.strip_model_world_events(text) == text


class TestBriefStructure:
    def test_prompt_has_no_world_events_item(self):
        """Мутация «вернуть пункт 4 модели» красит тест: раздел мировых
        событий модели не поручается (#689 B.1)."""
        assert "4. 🌍 Важные мировые события" not in ROUTES
        assert "ЗАПРЕЩЕНО придумывать события" not in ROUTES

    def test_night_news_data_removed_from_prompt(self):
        # данные событий в промпт не идут — только программная секция после
        assert "{night_news}" not in ROUTES
        assert "Топ события за ночь" not in ROUTES

    def test_world_events_appended_by_program_after_model(self):
        # порядок: ответ модели → вырезка раздела модели → программная секция
        i_call = ROUTES.index('result = call_llm("yana", messages)')
        i_strip = ROUTES.index("strip_model_world_events(brief)")
        i_world = ROUTES.index("build_world_events_section(night_news_keys)")
        i_attention = ROUTES.index("build_attention_section(attention_items)")
        assert i_call < i_strip < i_world < i_attention

    def test_model_task_mentions_programmatic_section(self):
        assert "РАЗДЕЛ «🌍 ВАЖНЫЕ МИРОВЫЕ СОБЫТИЯ» ТЫ НЕ ПИШЕШЬ" in ROUTES


class TestGetNightNewsItemsSource:
    def test_items_carry_source(self, n689_isolated):
        from proxy.news import get_night_news_items
        _seed_news("guardian", "NZ election", "https://n689.example/nz", "h-n689-nzitems")
        _text, items = get_night_news_items()
        assert items and items[0]["source"] == "guardian"
        assert items[0]["title"] == "NZ election"


class TestBriefEndpoint:
    def test_world_events_verbatim_model_invention_dropped(self, n689_isolated, monkeypatch):
        """B.1 по букве: заголовок «New Zealand election too close to call»
        в данных → в брифе ровно он, с источником; выдумка мока
        («партия налоговой реформы») в итоговый текст не попадает."""
        _seed_news("guardian", "New Zealand election too close to call",
                   "https://n689.example/nz-real", "h-n689-nz")
        monkeypatch.setattr(rs, "call_llm", lambda dept, messages: {
            "reply": ("*Утренний отчёт*\n"
                      "3. 🏢 Офис работает штатно.\n"
                      "4. 🌍 Важные мировые события\n"
                      "В Новой Зеландии проходят выборы, где решает партия налоговой реформы.\n"
                      "5. 🔍 Находки ЛЗ: нет"),
            "provider": "mock", "tokens_in": 0, "tokens_out": 0})
        sent = {}
        monkeypatch.setattr(rs, "_tg_send_formatted",
                            lambda chat_id, text, dept=None: sent.setdefault("text", text) or 42)
        r = CLIENT.post("/scheduler/morning-brief", json={"owner_id": "12345"})
        assert r.status_code == 200, r.get_data(as_text=True)
        text = sent.get("text", "")
        assert "📌 New Zealand election too close to call (guardian)" in text, text[-500:]
        assert "партия налоговой реформы" not in text
        assert "В Новой Зеландии проходят выборы" not in text

    def test_no_news_honest_line(self, n689_isolated, monkeypatch):
        monkeypatch.setattr(rs, "call_llm", lambda dept, messages: {
            "reply": "*Утренний отчёт*\n3. 🏢 Офис работает.",
            "provider": "mock", "tokens_in": 0, "tokens_out": 0})
        sent = {}
        monkeypatch.setattr(rs, "_tg_send_formatted",
                            lambda chat_id, text, dept=None: sent.setdefault("text", text) or 42)
        r = CLIENT.post("/scheduler/morning-brief", json={"owner_id": "12345"})
        assert r.status_code == 200, r.get_data(as_text=True)
        text = sent.get("text", "")
        assert "За ночь значимых событий не зафиксировано" in text, text[-500:]

    def test_model_never_sees_news_data(self, n689_isolated, monkeypatch):
        """Данные событий из промпта убраны: мок-модель не получает ни
        заголовков, ни дайджеста «Топ события за ночь»."""
        _seed_news("guardian", "Secret headline xyz", "https://n689.example/secret", "h-n689-secret")
        captured = {}
        monkeypatch.setattr(rs, "call_llm", lambda dept, messages: (
            captured.update(user=messages[1]["content"], system=messages[0]["content"])
            or {"reply": "*Утренний отчёт*", "provider": "mock", "tokens_in": 0, "tokens_out": 0}))
        monkeypatch.setattr(rs, "_tg_send_formatted",
                            lambda chat_id, text, dept=None: 42)
        r = CLIENT.post("/scheduler/morning-brief", json={"owner_id": "12345"})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert "Secret headline xyz" not in captured["user"], "заголовок не должен попадать в промпт"
        assert "Топ события за ночь" not in captured["user"]
