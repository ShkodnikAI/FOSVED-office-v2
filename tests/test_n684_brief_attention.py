#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#684 BRIEF-2: раздел внимания утренней сводки — программой, не моделью;
строка Кавальни — дословно, с разбивкой и причинами недоборов.

Гвардии:
- collect_attention_items: все 7 условий наряда + честная пустота;
- build_attention_section: пустой список → «⚡ Внимания не требуется»,
  многострочные алерты — с отступом продолжения;
- filter_model_conclusions: «Вмешательства не требуется» вырезается при
  непустом списке алертов (замечание владельца 07.11), без алертов текст не
  меняется, срабатывания возвращаются вызывающему (идут в audit_log);
- структурные: пункт 6 из задачи модели удалён (мутация «вернуть пункт 6
  модели» красит test_prompt_has_no_attention_item), раздел внимания
  добавляется программой после фильтра, kk_line из промпта убран и
  добавляется дословно, фразы-маркеры без ⚡;
- эндпоинт /scheduler/morning-brief: «успокоительная» фраза мока не доходит
  до отправки при непустом списке алертов, раздел внимания в брифе;
- dept/kk_training.mlog: формат 24ч без «вчера», недобор с причиной
  (KKShortfallReason), накопители kk_rej_flat/kk_ai_fail, итог kk_validate,
  resolve-итог по-русски (разрешено/спорных/отложено).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-test-db-n684')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')
os.environ.setdefault('CRON_SECRET', 'cron-test-secret')

from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTES = (REPO_ROOT / "proxy" / "routes_sched.py").read_text(encoding="utf-8")
KK = (REPO_ROOT / "dept" / "kk_training.mlog").read_text(encoding="utf-8")
SCHED = (REPO_ROOT / "dept" / "scheduler.mlog").read_text(encoding="utf-8")

from proxy.routes_sched import (  # noqa: E402
    _ATTENTION_FILTER_PHRASES,
    build_attention_section,
    collect_attention_items,
    filter_model_conclusions,
)


def _green():
    """Все сигналы зелёные: резерв ок, ключи ок, отказов нет, Кавальня молчит."""
    return dict(
        forge_backup_ok=True,
        forge_backup_line="бэкап FORGE: создано 3 / упало 0 / 12 МБ",
        forge_backup_stale=False,
        keys_line="🔑 Ключи: все 9 — ok (проверка 2026-11-07 03:00 UTC)",
        dept_fail_line="Отказы отделов за сутки: нет",
        kk_line="",
        forge_attention="",
        errors_digest="",
    )


class TestCollectAttentionItems:
    def test_all_green_empty_list(self):
        assert collect_attention_items(**_green()) == []

    def test_backup_failed(self):
        d = _green()
        d["forge_backup_ok"] = False
        d["forge_backup_line"] = "бэкап FORGE: сбой контура (script rc=1)"
        items = collect_attention_items(**d)
        assert len(items) == 1 and "Резерв FORGE не выполнен" in items[0]
        assert "сбой контура" in items[0]  # причина громко, не смягчена

    def test_backup_empty_line(self):
        d = _green()
        d["forge_backup_ok"] = True
        d["forge_backup_line"] = ""
        items = collect_attention_items(**d)
        assert len(items) == 1 and "нет строки итога" in items[0]

    def test_backup_stale(self):
        d = _green()
        d["forge_backup_stale"] = True
        items = collect_attention_items(**d)
        assert len(items) == 1 and "старше суток" in items[0]

    def test_keys_stale_check(self):
        d = _green()
        d["keys_line"] = "🔑 Ключи: проверка НЕ выполнялась с 2026-11-05 21:40 UTC (>26 ч) ⚠️"
        items = collect_attention_items(**d)
        assert len(items) == 1 and "Проверка ключей не выполнялась" in items[0]

    def test_keys_problems(self):
        d = _green()
        d["keys_line"] = "🔑 Ключи: ⚠️ MARKET invalid (401); остальные 8 — ok"
        items = collect_attention_items(**d)
        assert len(items) == 1 and "Проблемы ключей" in items[0] and "MARKET invalid" in items[0]

    def test_keys_ok_no_item(self):
        d = _green()
        d["keys_line"] = "🔑 Ключи: ещё не проверялись (первый ночной цикл после деплоя)"
        assert collect_attention_items(**d) == []

    def test_dept_fails_both_formats(self):
        # формат mlog-слота (DeptFailLine24h) и python-fallback — оба алерт
        d = _green()
        d["dept_fail_line"] = "Отказы отделов за сутки: osp 3, lz 1"
        items = collect_attention_items(**d)
        assert len(items) == 1 and "osp 3" in items[0]
        d["dept_fail_line"] = "Отказы отделов за сутки: qa — 2"
        assert len(collect_attention_items(**d)) == 1

    def test_dept_fails_zero_forms_no_item(self):
        for line in ("Отказы отделов за сутки: нет", "Отказы отделов за сутки: 0",
                     "Отказы отделов: нет данных", ""):
            d = _green()
            d["dept_fail_line"] = line
            assert collect_attention_items(**d) == [], line

    def test_kk_not_working(self):
        for line in ("Кавальня: не работала — выключена (/kk on)",
                     "Кавальня: не работала — сбор строки упал (audit_log)"):
            d = _green()
            d["kk_line"] = line
            items = collect_attention_items(**d)
            assert len(items) == 1 and "Кавальня" in items[0], line

    def test_kk_normal_line_no_item(self):
        d = _green()
        d["kk_line"] = "Кавальня (24ч): задано 12 — ОСП 3, финансы 3, юристы 3, ЛЗ 3"
        assert collect_attention_items(**d) == []

    def test_forge_attention_and_errors(self):
        d = _green()
        d["forge_attention"] = "  - Гейт #12 [release]: ждёт решения"
        d["errors_digest"] = "  - qa/api: 5 раз(а) за сутки"
        items = collect_attention_items(**d)
        assert len(items) == 2
        assert "FORGE требует внимания" in items[0] and "Гейт #12" in items[0]
        assert "Повторяющиеся ошибки офиса" in items[1] and "qa/api" in items[1]


class TestBuildAttentionSection:
    def test_empty_honest_line(self):
        assert build_attention_section([]) == "⚡ Внимания не требуется"

    def test_items_verbatim(self):
        section = build_attention_section(["Резерв FORGE не выполнен (сбой)",
                                           "FORGE требует внимания:\n  - Гейт #12"])
        assert section.startswith("⚡ Что требует внимания:")
        assert "- Резерв FORGE не выполнен (сбой)" in section
        assert "- FORGE требует внимания:" in section
        assert "  - Гейт #12" in section  # продолжение с отступом


class TestFilterModelConclusions:
    def test_cuts_calming_line_when_attention(self):
        text = "*Утренний отчёт*\nВмешательства не требуется.\nОфис работает."
        out, removed = filter_model_conclusions(text, True)
        assert "Вмешательства не требуется" not in out
        assert "Офис работает." in out
        assert len(removed) == 1

    def test_all_phrase_variants_covered(self):
        for phrase in ("всё в порядке", "все в порядке", "не требует внимания",
                       "проблем нет", "внимания не требуется"):
            text = f"Строка: {phrase}."
            out, _ = filter_model_conclusions(text, True)
            assert phrase not in out, phrase

    def test_case_insensitive(self):
        out, removed = filter_model_conclusions("*Всё В Порядке*", True)
        assert removed and out == ""

    def test_no_attention_no_filter(self):
        text = "Всё в порядке, вмешательства не требуется."
        out, removed = filter_model_conclusions(text, False)
        assert out == text and removed == []

    def test_phrases_constant_nonempty(self):
        # список фраз — в коде (наряд #684 A.1.4), не пустой
        assert "вмешательств" in _ATTENTION_FILTER_PHRASES


class TestBriefStructure:
    def test_prompt_has_no_attention_item(self):
        # мутация «вернуть пункт 6 модели» красит этот тест: раздел внимания
        # собирает программа, модели он не поручается (#684 A.1.3)
        assert "6. ⚡ Что требует внимания" not in ROUTES

    def test_prompt_forbids_intervention_conclusions(self):
        assert "ЗАПРЕЩЕНО писать выводы о необходимости вмешательства" in ROUTES

    def test_section_appended_by_program_after_model(self):
        # порядок: ответ модели → фильтр → раздел внимания → дословные строки
        i_call = ROUTES.index('result = call_llm("yana", messages)')
        i_filter = ROUTES.index("filter_model_conclusions(brief, bool(attention_items))")
        i_section = ROUTES.index('build_attention_section(attention_items)')
        i_backup = ROUTES.index('brief = brief + "\\n\\n💾 Резерв FORGE: "')
        assert i_call < i_filter < i_section < i_backup

    def test_filter_trigger_audited(self):
        assert '_log_audit("brief_attention_filter"' in ROUTES

    def test_kk_line_removed_from_prompt(self):
        # #684 A.2: строка Кавальни — дословно в бриф, не в промпт
        assert "{kk_line}" not in ROUTES
        assert 'brief = brief + "\\n\\n" + kk_line' in ROUTES
        # поле payload остаётся (mlog — SSOT строки)
        assert "kk_brief_line(d)" in ROUTES

    def test_emoji_markers_without_attention_bolt(self):
        # ⚡ больше не маркер секций модели — раздел пишет программа;
        # #689 B.1: 🌍 убран из маркеров модели — раздел мировых событий
        # тоже собирает программа (дословно из сборщика)
        assert "(📅🌤🏢🔍)" in ROUTES
        assert "📅🌤🏢🌍🔍⚡" not in ROUTES

    def test_attention_collected_before_model_call(self):
        i_items = ROUTES.index("attention_items = collect_attention_items(")
        i_call = ROUTES.index('result = call_llm("yana", messages)')
        assert i_items < i_call


class TestBriefEndpoint:
    def test_calming_model_reply_cannot_survive_with_alerts(self, monkeypatch):
        """Сценарий замечания владельца 07.11: модель пишет «вмешательства не
        требуется», алерты есть — фраза вырезана, раздел внимания в брифе."""
        import llm_proxy  # noqa: F401
        from proxy.core import app as flask_app, _query
        from proxy import routes_sched

        # BRIEF-1 дедуп: чистим след предыдущего брифа (идиома clean_dialog #588)
        _query("DELETE FROM audit_log WHERE action='scheduler_morning_brief'")
        _query("DELETE FROM dialog_history WHERE dept='yana' AND role='assistant' AND content LIKE '%утренний отчёт%'")

        monkeypatch.setattr(routes_sched, "call_llm", lambda dept, messages: {
            "reply": "*Утренний отчёт*\nВсё в порядке, вмешательства не требуется.",
            "provider": "mock", "tokens_in": 0, "tokens_out": 0})
        sent = {}
        monkeypatch.setattr(routes_sched, "_tg_send_formatted",
                            lambda chat_id, text, dept=None: sent.setdefault("text", text) or 42)
        client = flask_app.test_client()
        r = client.post("/scheduler/morning-brief", headers={"Authorization": "Bearer test-secret-123"},
                        json={"owner_id": "12345"})
        assert r.status_code == 200
        text = sent.get("text", "")
        # в тестовом окружении резерв FORGE падает (нет контура) — алерт есть,
        # значит «успокоительное» вырезано, а раздел внимания добавлен
        assert "Всё в порядке" not in text
        assert "вмешательства не требуется" not in text
        assert "⚡ Что требует внимания:" in text
        assert "⚡ Внимания не требуется" not in text


class TestKkLineMlog:
    def test_line_format_24h_no_vesterday(self):
        assert '"Кавальня (24ч): задано "' in KK
        assert '"Кавальня: вчера "' not in KK

    def test_breakdown_and_states(self):
        assert "ответов с валидной карточкой " in KK
        assert "ожидают исхода " in KK
        assert "(ближайшие — " in KK

    def test_shortfall_reason_chain(self):
        # недобор — с причиной: валидатор → сбой ИИ → запись слота → честная
        assert "pattern KKShortfallReason" in KK
        assert "KKShortfallReason(dept)" in KK
        assert "валидатор отклонил " in KK
        assert "сбой генерации ИИ" in KK
        assert "причина не зафиксирована" in KK

    def test_accumulators_and_audit(self):
        assert "kk_rej_flat:" in KK
        assert "kk_ai_fail:" in KK
        assert '"kk_validate"' in KK
        assert '"kk_ask_dept"' in KK  # маркер отдела (слот kk-ask — в app.mlog)
        assert "AuditLog(\"kk_validate\", a_dept" in KK

    def test_resolve_slot_russian_summary(self):
        assert '"разрешено="' in KK and '" спорных="' in KK and '" отложено="' in KK

    def test_dept_marker_set_in_prompt_builder(self):
        assert 'kv_set("kk_ask_dept", dept)' in KK

    def test_app_mlog_untouched(self):
        # наряд #684 app.mlog не трогает. #687 (NIGHT-1) правит NightSlot
        # легитимно — гвардия отслеживает, что в app.mlog нет правок
        # Кавальни (запрет наряда #684 остаётся в силе).
        import subprocess
        out = subprocess.run(
            ["git", "diff", "origin/main", "--", "app.mlog"],
            cwd=str(REPO_ROOT), capture_output=True, text=True)
        for banned in ("KKAskForDept", "KKResolveSlot", "KKLine24h", "kk_ask", "kk_resolve"):
            assert banned not in out.stdout, f"app.mlog: правка Кавальни ({banned}) запрещена наряду #684"

    def test_scheduler_payload_keeps_kk_field(self):
        # mlog-сторона по-прежнему кладёт строку в payload брифа
        assert "let kk_line_24h = KKLine24h()" in SCHED
        assert "kk_line_24h: kk_line_24h" in SCHED
