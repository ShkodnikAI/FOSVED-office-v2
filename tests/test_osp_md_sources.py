#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#253 (вариант 1, решение владельца): library/osp.md — вычищены ссылки на стек
v4.1 (ResearchSource, lib/research.js), заменены на текущий источник-контур.

Гварды:
- в osp.md не осталось ссылок на несуществующие сущности v4.1;
- документ ссылается только на реально существующие каналы: /osp tavily,
  /osp tg, RSS-новости и FRED (секции контекста), архив Analysis (sources);
- двусторонняя сверка с кодом: OSPTavilySearch / OSPTelegramSearch /
  OSPSourcesFooter существуют в dept/osp.mlog.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSP_MD = open(os.path.join(REPO_ROOT, "library", "osp.md"), encoding="utf-8").read()
OSP_MLOG = open(os.path.join(REPO_ROOT, "dept", "osp.mlog"), encoding="utf-8").read()


def test_no_v41_ghost_references():
    # стек v4.1 (JS/Prisma) не существует в репо — ссылки не должны вернуться
    assert "ResearchSource" not in OSP_MD
    assert "lib/research" not in OSP_MD
    assert "research.js" not in OSP_MD


def test_doc_references_real_channels_only():
    # текущий контур, который документ называет, реально существует
    assert "/osp tavily" in OSP_MD
    assert "/osp tg" in OSP_MD
    assert "Analysis" in OSP_MD  # архив препарирований


def test_doc_code_two_way_consistency():
    # каждый канал из документа живёт в коде отдела
    assert "pattern OSPTavilySearch" in OSP_MLOG          # Tavily (/osp tavily)
    assert "pattern OSPTelegramSearch" in OSP_MLOG        # Telegram-поиск (/osp tg)
    assert "pattern OSPSourcesFooter" in OSP_MLOG         # подвал «Источники»
    # реальные секции контекста, из которых собирается подвал источников
    assert "=== News ===" in OSP_MLOG                     # RSS-новости
    assert "=== FRED (макроданные) ===" in OSP_MLOG       # FRED-макроданные
    # архив Analysis с колонкой sources (накопление находок)
    assert "sources TEXT DEFAULT '[]'" in OSP_MLOG
