#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#684 A.4 (аудитор 07.11, доработка): карточка /kk по скриншоту владельца.

Гвардии:
- A.4.1: заглушка -1 (KKWeekAvg, «нет данных») не рисуется как балл —
  в KKSvgRow ветка <0 рисует подпись «нет данных» без полоски; числовая
  подпись стоит только в ветке данных (мутация «вернуть вывод -1» красит
  mlog-тест n684 A.4.1 через отсутствие «>-1<»);
- A.4.2: разбивка 24ч на карточках — из того же KKStats24h, что строка
  брифа; вторая реализация подсчёта запрещена: KKStatsSvg/KKDeptSvg не
  содержат собственных COUNT-запросов, читают KKStats24h/KKDeptLine24h;
- A.4.3: «провалов нет» — только при разрешённых ≥1; при нуле —
  «разрешённых вопросов ещё нет — первые исходы <дата>»;
- app.mlog не тронут (запрет наряда #684), подписи вызова карточек на месте.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-test-db-n684card')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')
os.environ.setdefault('CRON_SECRET', 'cron-test-secret')

from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
KK = (REPO_ROOT / "dept" / "kk_training.mlog").read_text(encoding="utf-8")
APP = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")


def _pattern_src(name: str) -> str:
    """Текст паттерна NAME — до следующего 'pattern ' на границе строки."""
    start = KK.index(f"pattern {name}")
    nxt = KK.find("\npattern ", start + 1)
    return KK[start:nxt if nxt != -1 else len(KK)]


class TestA41NoPlaceholderBars:
    def test_no_data_week_branch_exists(self):
        row = _pattern_src("KKSvgRow")
        assert "if to_float(w) < 0.0 then" in row
        assert "нет данных" in row
        assert "#9AA0A8" in row

    def test_numeric_label_only_in_data_branch(self):
        # мутация «вернуть вывод -1»: числовая подпись — только после guards
        row = _pattern_src("KKSvgRow")
        i_guard = row.index("if to_float(w) < 0.0 then")
        i_nodata = row.index(">нет данных<")
        i_rect = row.index("<rect ")
        i_label = row.index("to_string(KKRound2(to_float(w)))")
        assert i_guard < i_nodata < i_rect < i_label

    def test_weekavg_sentinel_unchanged(self):
        # сам KKWeekAvg не менялся: -1 остаётся служебным признаком «нет данных»
        assert "return -1.0" in _pattern_src("KKWeekAvg")


class TestA42SameCountingFunction:
    def test_stats24h_is_the_single_counter(self):
        src = _pattern_src("KKStats24h")
        assert "SELECT COUNT(*)" in src
        assert "kk_questions" in src
        assert "kk_outcomes" in src
        assert "KKShortfallReason(dept)" in src

    def test_brief_line_formats_only(self):
        core = _pattern_src("KKLine24hCore")
        assert "KKStatsRaw()" in core
        # строка брифа сама не считает — только читает и форматирует
        assert "SELECT COUNT" not in core
        assert "query(" not in core

    def test_stats_svg_has_no_own_counting(self):
        svg = _pattern_src("KKStatsSvg")
        assert "KKStatsRaw()" in svg
        assert "KKDeptLine24h(" in svg
        assert "KKStatVal(" in svg
        for banned in ("SELECT COUNT", "SELECT AVG", "kk_questions", "kk_outcomes", "polygon_results"):
            assert banned not in svg, banned

    def test_dept_svg_has_no_own_counting(self):
        svg = _pattern_src("KKDeptSvg")
        assert "KKStatsRaw()" in svg
        assert "KKDeptLine24h(" in svg
        assert "KKStatVal(" in svg
        for banned in ("SELECT COUNT", "SELECT AVG", "kk_questions", "kk_outcomes", "polygon_results"):
            assert banned not in svg, banned
        # «первые исходы» — отдельный хелпер, не второй подсчёт разбивки
        assert "KKFirstResolveDate(" in svg

    def test_dept_line_reads_only_stats(self):
        src = _pattern_src("KKDeptLine24h")
        assert "KKStatVal(" in src
        assert "query(" not in src

    def test_statval_is_a_reader(self):
        src = _pattern_src("KKStatVal")
        assert "parse_json" in src
        assert "query(" not in src


class TestA43FailsOnlyWhenResolved:
    def test_empty_does_not_look_like_success(self):
        svg = _pattern_src("KKDeptSvg")
        assert "разрешённых вопросов ещё нет" in svg
        assert "первые исходы " in svg
        assert "провалов нет" in svg
        # порядок: проверка разрешённых раньше «провалов нет»
        assert svg.index("resolved28 < 1.0") < svg.index("провалов нет")

    def test_first_resolve_helper_scope(self):
        src = _pattern_src("KKFirstResolveDate")
        assert "status IN ('open', 'answered')" in src
        assert "MIN(resolve_by)" in src


class TestGuards:
    def test_app_mlog_untouched(self):
        # наряд #684 app.mlog не трогает — гвардия по рабочему дереву
        import subprocess
        out = subprocess.run(
            ["git", "diff", "origin/main", "--", "app.mlog"],
            cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert out.stdout.strip() == "", "app.mlog изменён — запрещено нарядом #684"

    def test_call_sites_in_app_mlog_unchanged(self):
        # подписи карточек не менялись — app.mlog зовёт как раньше
        assert "KKStatsSvg()" in APP
        assert "KKDeptSvg(rest)" in APP
