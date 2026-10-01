#!/usr/bin/env python3
"""Гвард наряда #437: главный предмет запроса определяет категорию Onliner,
карта синонимов расширена живыми слагами, проверка соответствия выдачи.

Наряд: https://github.com/ShkodnikAI/FOSVED-office-v2/issues/437
Фактура 2026-09-30: «яна, подбери мне лучший утюг» → «утюг на твое
усмотрение» → 30 отпаривателей. Причина: «утюга» не было в карте синонимов,
а нечёткий скоринг давал «утюг» и «паром» равные 7 очков — побеждала
категория, встреченная раньше в словаре.

A.1 — главный предмет: карта проверяется по нему ПЕРВЫМ; при равенстве
      очков нечёткого скоринга побеждает категория предмета
      (MAIN_SUBJECT_BONUS), а не первая встреченная.
A.2 — карта синонимов бытовой техники: слаги сняты с живого словаря
      /schemas 2026-09-30 (887 схем, 45 страниц, имена подтверждены).
A.3 — relevance_mismatch: доля предложений с главным предметом в названии
      ниже порога → досье «НАЙДЕНО НЕ ТО» без вердикта «Купить».
A.4 — промпт Яны: первым словом маркера [SHOP: …] — предмет в
      именительном падеже.
Запуск: python -m pytest tests/test_n437_dossier_relevance.py -v
"""
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys_path = str(REPO_ROOT)
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)

import os  # noqa: E402

os.environ.setdefault("API_SECRET", "test-secret-123")
os.environ.setdefault("DATABASE_PATH", "/tmp/fosved-n437-test")

from proxy import shop_collectors as sc  # noqa: E402
from proxy.shop_dossier import render_caption, render_text  # noqa: E402

YANA = (REPO_ROOT / "dept" / "yana.mlog").read_text(encoding="utf-8")
DOSSIER = (REPO_ROOT / "proxy" / "shop_dossier.py").read_text(encoding="utf-8")

# ── A.2: карта синонимов из живого словаря ────────────────────────────────


def test_map_has_iron_from_live_catalog():
    # живой словарь 2026-09-30: iron = «Утюги» (проверено запросом
    # /search/iron — schema.key=iron, schema.name=Утюги)
    assert sc.ONLINER_KEYWORD_MAP["утюг"] == "iron"


def test_map_household_appliances():
    # слаги сверены с живым /schemas 2026-09-30 (887 схем):
    # steamcleaner=«Пароочистители и отпариватели», kettles=«Чайники»,
    # microvawe=«Микроволновые печи» (слаг площадки, не наша опечатка),
    # blender=«Блендеры», dishwasher=«Посудомоечные машины»
    assert sc.ONLINER_KEYWORD_MAP["отпаривател"] == "steamcleaner"
    assert sc.ONLINER_KEYWORD_MAP["пароочистител"] == "steamcleaner"
    assert sc.ONLINER_KEYWORD_MAP["чайник"] == "kettles"
    assert sc.ONLINER_KEYWORD_MAP["микроволнов"] == "microvawe"
    assert sc.ONLINER_KEYWORD_MAP["блендер"] == "blender"
    assert sc.ONLINER_KEYWORD_MAP["посудомоечн"] == "dishwasher"


def test_map_headphones_base_form():
    # «наушники» не матчила ед.ч. «наушник» (startswith) — ключ-основа
    assert sc.ONLINER_KEYWORD_MAP["наушник"] == "headphones"
    assert "наушники" not in sc.ONLINER_KEYWORD_MAP


# ── A.1: главный предмет ──────────────────────────────────────────────────


def test_main_subject_is_first_meaningful_word():
    q = "утюг с паром керамическая подошва мощный"
    assert sc._main_subject_word(sc._norm_words(q)) == "утюг"


def test_main_subject_skips_leading_masks():
    assert sc._main_subject_word(sc._norm_words("лучший утюг с паром")) == "утюг"
    assert sc._main_subject_word(sc._norm_words("подбери мне утюг")) == "утюг"
    assert sc._main_subject_word(sc._norm_words("купить чайник электрический")) == "чайник"


def test_main_subject_stopwords_are_exact_words():
    # основы опасны: «сам» съел бы «самовар», «куп» — «купальник»
    assert sc._main_subject_word(sc._norm_words("самовар электрический")) == "самовар"
    assert sc._main_subject_word(sc._norm_words("купальник мужской")) == "купальник"


def test_map_lookup_by_subject_first(monkeypatch):
    # оба слова запроса есть в карте: предмет «утюг» должен выиграть у
    # признака «паром» (который раньше увёл в «Пароочистители»)
    schemas = {"schemas": [{"key": "steamcleaner", "name": "Пароочистители и отпариватели"},
                           {"key": "iron", "name": "Утюги"}],
               "complete": True, "ts": time.time(), "next_page": 2}
    monkeypatch.setattr(sc, "_onliner_schemas_cache_read", lambda: schemas)
    monkeypatch.setattr(sc, "_setting_set", lambda k, v: None)
    got = sc.onliner_resolve_category("утюг с паром керамическая подошва мощный")
    assert got == "iron", got


def test_fuzzy_tie_broken_by_main_subject(monkeypatch):
    # точное воспроизведение фактуры наряда: «утюг» и «паром» дают равные
    # 7 очков против обеих категорий; до #437 побеждала первая встреченная
    assert sc._schema_match_score(
        sc._norm_words("утюг с паром"),
        {"name": "Пароочистители и отпариватели"}) == 7
    assert sc._schema_match_score(
        sc._norm_words("утюг с паром"), {"name": "Утюги"}) == 7
    schemas = {"schemas": [{"key": "steamcleaner", "name": "Пароочистители и отпариватели"},
                           {"key": "iron", "name": "Утюги"}],
               "complete": True, "ts": time.time(), "next_page": 2}
    monkeypatch.setattr(sc, "_onliner_schemas_cache_read", lambda: schemas)
    monkeypatch.setattr(sc, "_setting_set", lambda k, v: None)
    # карту отключаем — проверяем нечёткую ветку с бонусом предмету
    monkeypatch.setattr(sc, "ONLINER_KEYWORD_MAP", {})
    got = sc.onliner_resolve_category("утюг с паром керамическая подошва мощный")
    assert got == "iron", got


def test_fuzzy_without_subject_match_unchanged(monkeypatch):
    # если предмет ни с чем не совпал — поведение прежнее (лучший скор)
    schemas = {"schemas": [{"key": "steamcleaner", "name": "Пароочистители и отпариватели"},
                           {"key": "iron", "name": "Утюги"}],
               "complete": True, "ts": time.time(), "next_page": 2}
    monkeypatch.setattr(sc, "_onliner_schemas_cache_read", lambda: schemas)
    monkeypatch.setattr(sc, "_setting_set", lambda k, v: None)
    monkeypatch.setattr(sc, "ONLINER_KEYWORD_MAP", {})
    got = sc.onliner_resolve_category("отпариватель для одежды ручной")
    assert got == "steamcleaner", got


# ── A.3: проверка соответствия ────────────────────────────────────────────


def test_relevance_mismatch_zero_hits():
    offers = [{"title": f"Отпариватель ручной X{i}"} for i in range(30)]
    m = sc.relevance_mismatch("утюг с паром керамическая подошва мощный", offers)
    assert m and m["subject"] == "утюг" and m["hit_rate"] == 0.0, m


def test_relevance_wordforms_count():
    # «Утюгом Braun IS» — словоформа предмета считается хитом: hit_rate
    # 0.13 (4/30), а не 0.0 — без учёта словоформ было бы нулевым
    offers = [{"title": "Утюгом Braun IS"}] * 4 + \
             [{"title": "Чехол для гладильной доски"}] * 26
    m = sc.relevance_mismatch("утюг", offers)
    assert m and m["hit_rate"] == 0.13, m


def test_relevance_admixture_tolerated():
    # примесь аксессуаров рядом с утюгами — не mismatch
    mixed = [{"title": "Утюг Tefal FV1"}] * 10 + \
            [{"title": "Подошва для утюга Silit"}] * 20
    assert sc.relevance_mismatch("утюг", mixed) is None


def test_relevance_threshold_boundary():
    # 9/30 = 0.30 — на пороге → ок; 8/30 = 0.27 — ниже → mismatch
    on = [{"title": "Утюг Tefal"}] * 9 + [{"title": "Чехол"}] * 21
    assert sc.relevance_mismatch("утюг", on) is None
    off = [{"title": "Утюг Tefal"}] * 8 + [{"title": "Чехол"}] * 22
    m = sc.relevance_mismatch("утюг", off)
    assert m and m["hit_rate"] == 0.27, m


def test_relevance_env_threshold(monkeypatch):
    monkeypatch.setenv("SHOP_RELEVANCE_MIN", "0.9")
    offers = [{"title": "Утюг Tefal"}] * 26 + [{"title": "Чехол"}] * 4
    m = sc.relevance_mismatch("утюг", offers)
    assert m and m["min_rate"] == 0.9, m


def test_relevance_no_subject_no_check():
    # запрос из одних масок — проверка не применяется
    assert sc.relevance_mismatch("лучший", [{"title": "Отпариватель"}]) is None
    assert sc.relevance_mismatch("утюг", []) is None


# ── A.3: досье показывает «найдено не то» и скрывает «Купить» ─────────────


def _snap(rel=None):
    return {
        "product": {"title": "Подборка"},
        "profile": "default",
        "generated_at": "2026-09-30 12:00 UTC",
        "verdict": {"score": 50, "text": "ок", "best_offer_id": "o1"},
        "badges": {},
        "offers": [{"id": "o1", "platform": "onliner", "url": "https://x/1",
                    "rank_price": 142.0, "price_byn": 142.0,
                    "old_price_byn": None, "card_price_byn": None,
                    "in_stock": True, "installment_ok": False,
                    "delivery_days": None, "delivery_cost_byn": None,
                    "rating": None, "reviews_count": 0,
                    "seller_name": None, "image_url": None,
                    "total": 0.0, "group_scores": {},
                    "stop_flags": [], "honest": {}}],
        "unscored": [], "unscored_total": 0, "unscored_offers": [],
        "history_best": [], "median_best": None,
        "relevance_mismatch": rel,
    }


def test_render_text_shows_not_found_note():
    rel = {"subject": "утюг", "category": "Пароочистители и отпариватели",
           "hit_rate": 0.0, "min_rate": 0.3}
    text = render_text(_snap(rel))
    assert "НАЙДЕНО НЕ ТО" in text
    assert "Пароочистители и отпариватели" in text
    assert "утюг" in text


def test_caption_hides_buy_verdict_on_mismatch():
    rel = {"subject": "утюг", "category": "Пароочистители и отпариватели",
           "hit_rate": 0.0, "min_rate": 0.3}
    cap = render_caption(_snap(rel))
    assert "НАЙДЕНО НЕ ТО" in cap
    assert "Купить:" not in cap, "наряд #437: без вердикта «Купить»"


def test_caption_keeps_buy_verdict_when_relevant():
    cap = render_caption(_snap())
    assert "Купить:" in cap
    assert "НАЙДЕНО НЕ ТО" not in cap


def test_build_snapshot_calls_relevance_check():
    # статический гвард: build_snapshot обязан прогонять relevance_mismatch
    assert "relevance_mismatch(product_query, offers)" in DOSSIER


# ── миграция title (A.3: проверка по названию предложения) ────────────────

APP_MLOG = (REPO_ROOT / "app.mlog").read_text(encoding="utf-8")
DOGFOOD = (REPO_ROOT / "dogfood_staging.mlog").read_text(encoding="utf-8")
COLLECTORS_SRC = (REPO_ROOT / "proxy" / "shop_collectors.py").read_text(encoding="utf-8")


def test_shop_offers_title_column_in_creates():
    # свежая схема: title в CREATE обоих входных файлов (app + dogfood)
    for name, src in (("app.mlog", APP_MLOG), ("dogfood_staging.mlog", DOGFOOD)):
        m = [ln for ln in src.splitlines() if "CREATE TABLE IF NOT EXISTS shop_offers" in ln]
        assert m, f"{name}: нет CREATE shop_offers"
        assert "title TEXT" in m[0], f"{name}: в CREATE shop_offers нет title TEXT"


def test_shop_offers_title_idempotent_alter():
    # живая БД: идемпотентный ALTER по паттерну #329
    assert 'ALTER TABLE shop_offers ADD COLUMN title TEXT' in APP_MLOG


def test_title_persisted_on_insert_and_update():
    assert "INSERT INTO shop_offers (product_id, platform, platform_code, url, " in COLLECTORS_SRC
    assert "title, price_byn" in COLLECTORS_SRC
    assert "UPDATE shop_offers SET url=?, title=?" in COLLECTORS_SRC


def test_build_snapshot_reads_title():
    assert "SELECT url, platform, title, price_byn" in DOSSIER


# ── A.4: промпт Яны ───────────────────────────────────────────────────────


def test_yana_prompt_subject_first():
    assert "ГЛАВНЫЙ ПРЕДМЕТ в именительном падеже" in YANA
    assert "[SHOP: утюг с паром" in YANA


def test_yana_prompt_limits_features():
    assert "не более 2-3 ключевых признаков" in YANA
