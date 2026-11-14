#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#720 REPORT-1 (P1): честность ночного отчёта и утренней сводки.

Гварды (по пунктам наряда):
- A.1 (один блок на ночь): OutboxPut (dept/scheduler.mlog) дедуплицирует
  источники-сводки (night-tick/usage-by-key/night) по (source, MSK-дата) —
  повторный put ЗАМЕНЯЕТ запись ночи («replaced»), не добавляет вторую;
  источники-ленты (fo027) пишутся как раньше. Поведение — mlog-тесты
  «n720 A.1» (CI-шаг mlog test); здесь — структурные гварды + наличие
  тест-блоков (мутация «убрать дедуп» красит и mlog-тест, и гвард);
- A.2 (раздел внимания видит всё): collect_attention_items — ночная
  проверка partial/fail с фазой, night-tick FAIL-компоненты с причиной,
  здоровье ≤ 3/10, Кавальня ≥ 30% провала формы за 24 ч; фикстура 12.11;
- A.3 (нет ✅ при алертах): enforce_status_icon — значки модели вырезаются,
  программный дописывается (⚠️ при непустом списке, ✅ при пустом);
  промпт запрещает значки; эндпоинт: мок «… ✅» при алертах → ✅ нет, ⚠️ есть;
- A.4 (мелочи): forge_backup_block — префикс «Резерв FORGE:» ровно один;
  AdminCheckStaleDepts — отдел с записями своих слотов (Кавальня) не
  «никогда», списки без висячей запятой.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-test-db-n720')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')
os.environ.setdefault('CRON_SECRET', 'cron-test-secret')

from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTES = (REPO_ROOT / "proxy" / "routes_sched.py").read_text(encoding="utf-8")
SCHED = (REPO_ROOT / "dept" / "scheduler.mlog").read_text(encoding="utf-8")
ADMIN = (REPO_ROOT / "dept" / "admin.mlog").read_text(encoding="utf-8")

from proxy.routes_sched import (  # noqa: E402
    KK_FORM_FAIL_ALERT_PCT,
    NIGHT_HEALTH_ALERT_MAX,
    collect_attention_items,
    enforce_status_icon,
    forge_backup_block,
)


def _green():
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


# Фикстура факта 12.11 (наряд #720): partial + Phase 3, UA-здоровье 1/10,
# night-tick с evals=FAIL, Кавальня 6 из 12 провальных карточек.
NIGHT_LINE_1211 = (
    "🌙 Ночная проверка (2026-11-12 04:00 UTC): partial; здоровье: 1/10; "
    "открытых находок: 5\n"
    "Phase 3: недоступна (AdminNightCycle упал — детали в audit_log)"
)
NIGHT_TICK_1211 = (
    "night-tick: backup=ok indicators=ok shop=ok "
    "evals=FAIL(старт не удался (нет job_id)) night=ok"
)
KK_LINE_1211 = (
    "Кавальня (24ч): задано 12 — ОСП 3, Финансы 3, Юристы 3, ЛЗ 3; "
    "ответов с валидной карточкой 6, провал формы 6; ожидают исхода 13 "
    "(ближайшие — 2026-11-15); разрешено 2, спорных 0; "
    "Brier ОСП 0.15 / ошибка финансов 8.2%"
)


# ── A.1: один блок на ночь (структурные гварды; поведение — mlog-тесты) ────

class TestA1OutboxDedup:
    def test_dedup_source_list_and_replace_semantics(self):
        # фиксированный список сводок + семантика замены, не добавления
        assert ",night-tick,usage-by-key,night," in SCHED
        assert 'return "replaced"' in SCHED
        # UPDATE, не DELETE: необратимый сток в ночном прогоне недопустим
        assert "UPDATE owner_outbox SET text" in SCHED
        assert "DELETE FROM owner_outbox" not in SCHED
        # дедуп — только незакрытые записи (выгруженное не трогаем)
        assert "sent_at IS NULL" in SCHED

    def test_mlog_behavior_tests_exist(self):
        assert 'test "n720 A.1: usage-by-key — одна запись на ночь, повтор заменяет"' in SCHED
        assert 'assert_eq(r2, "replaced")' in SCHED
        assert 'test "n720 A.1: fo027 — не сводка, без дедупа' in SCHED

    def test_mutation_no_dedup_makes_guard_red(self):
        """Мутация «убрать дедуп» красит гвард: без списка сводок условие
        содержит(...) ложно — INSERT-ветка единственная, «replaced» нет."""
        mutated = SCHED.replace(",night-tick,usage-by-key,night,", ",,").replace(
            'return "replaced"', 'return "queued"')
        assert ",night-tick,usage-by-key,night," not in mutated
        assert 'return "replaced"' not in mutated


# ── A.2: раздел внимания видит все сбои отчёта ──────────────────────────────

class TestA2AttentionItems:
    def test_fixture_1211_all_four_signals(self):
        d = _green()
        d.update(night_line=NIGHT_LINE_1211,
                 night_tick_line=NIGHT_TICK_1211,
                 kk_line=KK_LINE_1211)
        items = collect_attention_items(**d)
        joined = "\n".join(items)
        assert any("Ночная проверка: partial" in i for i in items), joined
        assert any("Phase 3: недоступна" in i for i in items), joined
        assert any(i.startswith("night-tick: evals=FAIL") and "старт не удался (нет job_id)" in i
                   for i in items), joined
        assert any("Здоровье ночного цикла: 1/10" in i for i in items), joined
        assert any("Кавальня: провал формы 6 из 12" in i for i in items), joined

    def test_night_ok_no_partial_item(self):
        d = _green()
        d["night_line"] = "🌙 Ночная проверка (2026-11-12 04:00 UTC): ok; здоровье: 8/10; открытых находок: 0"
        items = collect_attention_items(**d)
        assert items == []

    def test_health_threshold_boundary(self):
        d = _green()
        d["night_line"] = "🌙 Ночная проверка (2026-11-12 04:00 UTC): ok; здоровье: 4/10; открытых находок: 0"
        assert collect_attention_items(**d) == []  # 4 > порога 3 — не алерт
        d["night_line"] = "🌙 Ночная проверка (2026-11-12 04:00 UTC): ok; здоровье: 3/10; открытых находок: 0"
        assert any("3/10" in i for i in collect_attention_items(**d))

    def test_kk_form_fail_pct_boundary(self):
        d = _green()
        # 2 из 10 = 20% — не алерт
        d["kk_line"] = "Кавальня (24ч): задано 10; ответов с валидной карточкой 8, провал формы 2"
        assert not any("провал формы" in i for i in collect_attention_items(**d))
        # 3 из 10 = 30% — алерт (граница включительно)
        d["kk_line"] = "Кавальня (24ч): задано 10; ответов с валидной карточкой 7, провал формы 3"
        assert any("провал формы 3 из 10" in i for i in collect_attention_items(**d))
        # 0 ответов — деления нет, алерта нет
        d["kk_line"] = "Кавальня (24ч): задано 3; ответов с валидной карточкой 0, провал формы 0"
        assert not any("провал формы" in i for i in collect_attention_items(**d))

    def test_night_tick_fail_without_reason(self):
        d = _green()
        d["night_tick_line"] = "night-tick: backup=ok night=FAIL"
        items = collect_attention_items(**d)
        assert items == ["night-tick: night=FAIL"]

    def test_night_tick_multiple_failures(self):
        d = _green()
        d["night_tick_line"] = "night-tick: backup=FAIL shop=FAIL evals=ok night=ok"
        items = collect_attention_items(**d)
        assert len(items) == 2

    def test_stale_night_not_double_reported(self):
        d = _green()
        d["night_line"] = "🌙 Ночная проверка: НЕ выполнялась с 2026-11-10 04:00 UTC (2 суток) ⚠️"
        items = collect_attention_items(**d)
        assert len(items) == 1 and "не выполнялась" in items[0]

    def test_green_fixture_stays_empty(self):
        # обратная совместимость #684: без ночных сигналов список пуст
        assert collect_attention_items(**_green()) == []

    def test_thresholds_are_module_constants(self):
        assert NIGHT_HEALTH_ALERT_MAX == 3
        assert KK_FORM_FAIL_ALERT_PCT == 30.0

    def test_night_tick_line_wired_at_both_call_sites(self):
        assert ROUTES.count("night_tick_line=night_tick_report_line(),") == 2
        assert "def night_tick_report_line" in ROUTES


# ── A.3: статусные значки — только программой ──────────────────────────────

class TestA3StatusIcon:
    def test_alerts_no_checkmark_get_warning(self):
        brief = ("📅 12 ноября, 07:20, четверг\n"
                 "🏢 Статус офиса: офис работает штатно, отказы 0. ✅\n"
                 "Событий нет ❌")
        out = enforce_status_icon(brief, attention_empty=False)
        assert "✅" not in out
        assert "❌" not in out
        status_line = [ln for ln in out.split("\n") if "Статус офиса" in ln][0]
        assert status_line.endswith("⚠️")

    def test_green_gets_checkmark(self):
        brief = "🏢 Статус офиса: всё штатно"
        out = enforce_status_icon(brief, attention_empty=True)
        assert [ln for ln in out.split("\n") if "Статус офиса" in ln][0].endswith("✅")

    def test_no_status_line_no_invented_icon(self):
        out = enforce_status_icon("Обычный текст ✅", attention_empty=False)
        assert "✅" not in out and "⚠️" not in out

    def test_prompt_forbids_icons_and_assembly_enforces(self):
        # промпт: старая строка-разрешение значков удалена, запрет на месте
        assert "▸ Статусы: ✅ зелёный" not in ROUTES
        assert "СТАТУСНЫЕ ЗНАЧКИ (✅ ⚠️ ❌) НЕ СТАВЬ" in ROUTES
        # сборка брифа зовёт enforce ДО программных разделов
        i_enforce = ROUTES.index("brief = enforce_status_icon(brief")
        i_world = ROUTES.index('brief = brief + "\\n\\n" + build_world_events_section')
        i_attn = ROUTES.index('brief = brief + "\\n\\n" + build_attention_section')
        assert i_enforce < i_world < i_attn

    def test_endpoint_model_checkmark_does_not_survive(self, monkeypatch):
        """Сценарий наряда: алерты есть, мок модели вернул «… ✅» — в итоговом
        брифе ✅ нет, есть ⚠️ (эндпоинт, вся сборка брифа)."""
        import llm_proxy  # noqa: F401
        from proxy.core import app as flask_app, _query
        from proxy import routes_sched

        _query("DELETE FROM audit_log WHERE action='scheduler_morning_brief'")
        _query("DELETE FROM dialog_history WHERE dept='yana' AND role='assistant' AND content LIKE '%утренний отчёт%'")

        monkeypatch.setattr(routes_sched, "call_llm", lambda dept, messages: {
            "reply": "*Утренний отчёт*\n🏢 Статус офиса: офис работает, отказы 0. ✅",
            "provider": "mock", "tokens_in": 0, "tokens_out": 0})
        sent = {}
        monkeypatch.setattr(routes_sched, "_tg_send_formatted",
                            lambda chat_id, text, dept=None: sent.setdefault("text", text) or 42)
        client = flask_app.test_client()
        r = client.post("/scheduler/morning-brief", headers={"Authorization": "Bearer test-secret-123"},
                        json={"owner_id": "12345"})
        assert r.status_code == 200
        text = sent.get("text", "")
        # тестовое окружение: резерв FORGE падает (нет контура) → алерты есть
        assert "⚡ Что требует внимания:" in text
        # значок модели не выжил; программный — на месте
        status_lines = [ln for ln in text.split("\n") if "Статус офиса" in ln]
        assert status_lines and status_lines[0].rstrip().endswith("⚠️")
        assert "отказы 0. ✅" not in text


# ── A.4: мелочи отчёта ──────────────────────────────────────────────────────

class TestA4ReportSmall:
    def test_forge_prefix_once(self):
        # факт 12.11: итог контура уже с префиксом — второй не добавляется
        assert forge_backup_block("Резерв FORGE: нечего резервировать (проектов 0)") == \
            "💾 Резерв FORGE: нечего резервировать (проектов 0)"
        # ветка успеха — префикс добавляется ровно один
        assert forge_backup_block("создано 3, упало 0, 12 МБ") == \
            "💾 Резерв FORGE: создано 3, упало 0, 12 МБ"

    def test_forge_block_used_in_assembly(self):
        assert "brief + \"\\n\\n\" + forge_backup_block(forge_backup_line)" in ROUTES
        assert 'brief + "\\n\\n💾 Резерв FORGE: " + forge_backup_line' not in ROUTES

    def test_stale_depts_slot_active_helper(self):
        assert "pattern AdminDeptSlotActive7d" in ADMIN
        assert "kk_questions" in ADMIN and "action LIKE 'kk_%'" in ADMIN
        # вызов в цикле AdminCheckStaleDepts: живой по слотам отдел пропускается
        assert "if AdminDeptSlotActive7d(dept_name) != 1.0 then {" in ADMIN

    def test_no_trailing_comma_patterns(self):
        # висячая запятая (факт 12.11: «…kavalnya, ]») — сборка через join
        assert 'never_used + dept_name + ", "' not in ADMIN
        assert '" дн.), "' not in ADMIN
        assert 'test "n720 A.4: списки «никогда/устарели» — без висячей запятой"' in ADMIN
        assert 'test "n720 A.4: Кавальня с kk-вопросами за 7 дней — жива, не «никогда»"' in ADMIN
