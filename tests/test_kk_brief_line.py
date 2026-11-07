"""#671 KK-1: строка тренировочного контура Кавальни в утренней сводке.

SSOT строки — mlog (KKLine24h в dept/kk_training.mlog, поле kk_line_24h
payload MorningBriefPayload); python-сторона (proxy/routes_sched.py) берёт
поле из payload без собственного пересчёта. Гварды: поле доходит до шаблона
брифа, реестр слотов kk-ask/kk-resolve зарегистрирован, выключатель честный.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-test-db-kk'
os.environ['ZAI_API_KEY'] = 'fake-key'
os.environ['CRON_SECRET'] = 'cron-test-secret'

from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHED = (REPO_ROOT / "dept" / "scheduler.mlog").read_text(encoding="utf-8")
SCHEDULES = (REPO_ROOT / "dept" / "schedules.mlog").read_text(encoding="utf-8")
KK = (REPO_ROOT / "dept" / "kk_training.mlog").read_text(encoding="utf-8")
ROUTES = (REPO_ROOT / "proxy" / "routes_sched.py").read_text(encoding="utf-8")

from proxy.routes_sched import kk_brief_line  # noqa: E402


class TestKkBriefLine:
    def test_empty_payload_no_line(self):
        # нет поля — строки в брифе нет (fallback-расчёта нет)
        assert kk_brief_line({}) == ""
        assert kk_brief_line({"kk_line_24h": None}) == ""
        assert kk_brief_line({"kk_line_24h": "   "}) == ""

    def test_line_from_payload_passes_through(self):
        line = "Кавальня: вчера 3 вопросов, разрешено 2, спорных 1; Brier ОСП 0.13 / ошибка финансов 4.2%"
        assert kk_brief_line({"kk_line_24h": line}) == line

    def test_mlog_payload_has_kk_field(self):
        # MorningBriefPayload кладёт поле (как dept_fails_24h — образец #636)
        assert "kk_line_24h: kk_line_24h" in SCHED
        assert "let kk_line_24h = KKLine24h()" in SCHED

    def test_template_renders_kk_line(self):
        # #684 BRIEF-2: строка Кавальни — дословно после ответа модели, из
        # промпта убрана (цифры не искажаются пересказом)
        assert "{kk_line}" not in ROUTES
        assert 'brief = brief + "\\n\\n" + kk_line' in ROUTES
        assert "kk_brief_line(d)" in ROUTES

    def test_kkline24h_sources_in_kk_module(self):
        assert "pattern KKLine24h() -> String" in KK
        # выключатель честный: нет ключа = off (наряд E)
        assert "KKEnabled() == false then { return \"Кавальня: не работала — выключена (/kk on)\" }" in KK
        # тест F наряда: пустая база — «нет данных»
        assert "нет данных" in KK


class TestKkSlotsRegistry:
    def test_slots_registered_with_msk_cron(self):
        # smoke наряда: kk-ask, kk-resolve зарегистрированы (06:10 и 07:00 МСК)
        assert 'name: "kk-ask"' in SCHEDULES
        assert 'cron: "10 6 * * *"' in SCHEDULES
        assert 'name: "kk-resolve"' in SCHEDULES
        assert 'cron: "0 7 * * *"' in SCHEDULES
        assert 'target: "KKAskSlot"' in SCHEDULES
        assert 'target: "KKResolveSlot"' in SCHEDULES

    def test_ask_slot_is_optional_target(self):
        # kk-ask живёт в app.mlog (боевые сборщики) — dogfood даёт NO-TARGET
        line = [l for l in SCHEDULES.splitlines() if 'name: "kk-ask"' in l][0]
        assert "optional: true" in line

    def test_slots_imported_by_both_entrypoints(self):
        app = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
        dog = (REPO_ROOT / "dogfood_staging.mlog").read_text(encoding="utf-8")
        assert "import dept/kk_training" in app
        assert "import dept/kk_training" in dog
