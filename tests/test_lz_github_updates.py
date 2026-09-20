#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#252: гвард переименования lz_telegram_posts → lz_github_updates.

Таблица хранит GitHub-релизы/репо из lz_github.py (channel_id="github") —
старое имя врало о содержимом (источник: аудит #244, блок A).

Гварды:
- CREATE lz_github_updates есть в обеих точках входа (app.mlog, dogfood_staging.mlog);
- старый CREATE lz_telegram_posts из обеих точек входа удалён;
- идемпотентная миграция (копия данных + DROP) присутствует — данные прода
  переносятся при первом буте после деплоя;
- proxy/lz_github.py пишет только в новое имя (0 INSERT INTO lz_telegram_posts).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "app.mlog").read_text(encoding="utf-8")
STAGING = (ROOT / "dogfood_staging.mlog").read_text(encoding="utf-8")
LZ_GH = (ROOT / "proxy" / "lz_github.py").read_text(encoding="utf-8")


def test_create_present_in_both_entries():
    for name, src in (("app.mlog", APP), ("dogfood_staging.mlog", STAGING)):
        assert "CREATE TABLE IF NOT EXISTS lz_github_updates" in src, name


def test_old_create_removed_from_entries():
    for name, src in (("app.mlog", APP), ("dogfood_staging.mlog", STAGING)):
        assert "CREATE TABLE IF NOT EXISTS lz_telegram_posts" not in src, name


def test_migration_copies_and_drops_old_table():
    for name, src in (("app.mlog", APP), ("dogfood_staging.mlog", STAGING)):
        assert "FROM sqlite_master WHERE type='table' AND name='lz_telegram_posts'" in src, name
        assert "INSERT OR IGNORE INTO lz_github_updates" in src, name
        assert "DROP TABLE lz_telegram_posts" in src, name


def test_writer_uses_new_name_only():
    assert "INTO lz_github_updates" in LZ_GH
    assert "INTO lz_telegram_posts" not in LZ_GH
    assert LZ_GH.count("INSERT OR IGNORE INTO lz_github_updates") == 2
