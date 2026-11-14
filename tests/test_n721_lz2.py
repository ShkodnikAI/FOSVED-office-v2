#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#721 LZ-2 (P2): ЛЗ не приписывает офису стек, которого у него нет.

Гварды (по пунктам наряда + решение владельца 12.11 по A.3):
- A.1: блок «=== СТЕК ОФИСА (факт) ===» — программно: версия Python
  рантайма, пакеты из requirements.txt (фикстура), версия Metalogos из
  пина Dockerfile; блок в user-content analysis_messages, правило стека —
  в системном промпте;
- A.2: annotate_foreign_stack_claims — абзац «Пакет N.N» + «наш/офис» без
  пакета в requirements → пометка в конец абзаца, счётчик; сценарий
  наряда: «LangChain 1.5.0 — breaking для всех наших пайплайнов» →
  пометка есть, подвал «пометок стека: 1»; флора: свой пакет — без
  пометки, абзац без «наш» — без пометки; подключение в конвейер и
  подвал — структурно (мутация «без проверки» красит);
- A.3 (решение владельца 12.11): баллов 1–10 нет — в промпте структура
  без «disrupting potential 1-10», есть «Почему важно для офиса:» и
  «Первая по важности:»; strip_disrupting_scores вырезает «N/10» рядом с
  potential/потенциал (мок «disrupting potential: 9/10» → числа нет),
  число срабатываний — в подвал.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('API_SECRET', 'test-secret-123')
os.environ.setdefault('TELEGRAM_WEBHOOK_SECRET', 'tg-wh-secret')
os.environ.setdefault('OWNER_TELEGRAM_ID', '12345')
os.environ.setdefault('DATABASE_PATH', '/tmp/fosved-test-db-n721')
os.environ.setdefault('ZAI_API_KEY', 'fake-key')

from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
LZ_SRC = (REPO_ROOT / "proxy" / "lz_github.py").read_text(encoding="utf-8")

import llm_proxy  # noqa: F401,E402
from proxy import lz_github  # noqa: E402
from proxy.lz_github import (  # noqa: E402
    annotate_foreign_stack_claims,
    office_stack_block,
    strip_disrupting_scores,
)

FIXTURE_REQ = """flask>=3.0,<4.0
requests>=2.31,<3.0
# комментарий
edge-tts>=6.1,<7.0
Pillow>=10.0
"""

FIXTURE_DOCKERFILE = """FROM ubuntu:24.04
# Metalogos v0.39.0 — прод-бинарь
RUN apt-get update
"""


# ── A.1: факты стека — в промпт ─────────────────────────────────────────────

class TestA1StackBlock:
    def test_block_has_python_packages_metalogos(self, monkeypatch, tmp_path):
        (tmp_path / "requirements.txt").write_text(FIXTURE_REQ, encoding="utf-8")
        (tmp_path / "Dockerfile").write_text(FIXTURE_DOCKERFILE, encoding="utf-8")
        monkeypatch.setattr(lz_github, "BASE_DIR", tmp_path)
        block = office_stack_block()
        assert block.startswith("=== СТЕК ОФИСА (факт, собран программой) ===")
        # версия Python фактического рантайма
        m = re.search(r"Python рантайма: (\d+\.\d+\.\d+)", block)
        assert m and m.group(1) == "{}.{}.{}".format(*sys.version_info[:3])
        # пакеты из фикстуры requirements.txt — с версионными спеками не путаются
        for pkg in ("flask", "requests", "edge-tts", "Pillow"):
            assert pkg in block, block
        assert "langchain" not in block.lower()
        # Metalogos — из пина Dockerfile
        assert "Metalogos (язык сценариев офиса, bin/mlog): 0.39.0" in block

    def test_block_wired_into_user_content(self):
        assert 'f"{office_stack_block()}\\n\\n"' in LZ_SRC

    def test_stack_rule_in_system_prompt(self):
        assert "ПРАВИЛО СТЕКА (#721)" in LZ_SRC
        assert "в стеке офиса не используется" in LZ_SRC
        # правило адресовано утверждениям о влиянии на офис
        assert "наши пайплайны" in LZ_SRC


# ── A.2: программная проверка после модели ─────────────────────────────────

class TestA2ForeignStackClaims:
    def test_scenario_of_the_order(self):
        """Сценарий наряда: LangChain нет в фикстуре → пометка, счётчик 1."""
        text = "🔥 LangChain 1.5.0 — breaking для всех наших пайплайнов.\nhttps://github.com/langchain-ai/langchain"
        out, marks = annotate_foreign_stack_claims(
            text, known_packages=["flask", "requests", "edge-tts", "Pillow"])
        assert marks == 1
        assert "⚠️ пакет в стеке офиса не используется (проверено по requirements.txt)" in out

    def test_own_package_no_mark(self):
        text = "Flask 3.1 вышла — обновим наши сервисы.\nhttps://example.com"
        out, marks = annotate_foreign_stack_claims(text, known_packages=["flask"])
        assert marks == 0
        assert "не используется" not in out

    def test_python_metalogos_are_known_base(self):
        text = "Python 3.12 и Metalogos 0.40.0 — обновления важны для нашего офиса."
        out, marks = annotate_foreign_stack_claims(text, known_packages=[])
        assert marks == 0

    def test_no_claim_words_no_mark(self):
        text = "LangChain 1.5.0 — крупный релиз экосистемы."
        out, marks = annotate_foreign_stack_claims(text, known_packages=["flask"])
        assert marks == 0

    def test_multiple_paragraphs_counted(self):
        # имена пакетов — латиница (PyPI-класс); кириллическое слово не
        # распознаётся как «пакет+версия» и пометку не рождает
        text = ("LangChain 1.5.0 — важно для наших пайплайнов.\n\n"
                "SomeFramework 2.0 — обновим наш стек.\n\n"
                "Обычный абзац без пакетов.")
        out, marks = annotate_foreign_stack_claims(text, known_packages=["flask"])
        assert marks == 2

    def test_wired_into_pipeline_and_footer(self):
        """Мутация «без проверки» (убрать вызов/подвал) красит гвард."""
        assert "analysis, stack_marks = annotate_foreign_stack_claims(analysis)" in LZ_SRC
        assert 'report += f"пометок стека: {stack_marks}\\n"' in LZ_SRC
        # сбой проверки не роняет отчёт (как у №597 A.3)
        assert "stack-claim annotate failed (non-fatal)" in LZ_SRC


# ── A.3: баллы 1–10 убрать (решение владельца 12.11) ───────────────────────

class TestA3NoScores:
    def test_prompt_structure_without_scores(self):
        assert "с disrupting potential 1-10" not in LZ_SRC
        assert "Почему важно для офиса:" in LZ_SRC
        assert "Первая по важности: <тема>" in LZ_SRC
        assert "Баллы важности (N/10) НЕ ставь" in LZ_SRC

    def test_strip_disrupting_scores(self):
        text = ("🔥 LangChain 1.5.0 — disrupting potential: 9/10\n"
                "Почему важно для офиса: в стеке офиса не используется\n"
                "Оценка команды 8/10")  # без «potential» — не трогаем
        out, n = strip_disrupting_scores(text)
        assert n == 1
        assert "9/10" not in out
        assert "disrupting potential:" in out  # слова остаются, число — нет
        assert "8/10" in out  # не рядом с potential — не вырезано

    def test_strip_russian_potential(self):
        out, n = strip_disrupting_scores("Тема с потенциалом 10/10 для офиса")
        assert n == 1 and "10/10" not in out

    def test_wired_into_pipeline_and_footer(self):
        assert "analysis, dp_removed = strip_disrupting_scores(analysis)" in LZ_SRC
        assert 'report += f"вырезано баллов disrupting potential: {dp_removed}\\n"' in LZ_SRC


# ── Запреты прохода не нарушены ─────────────────────────────────────────────

class TestOrderBoundaries:
    def test_watch_list_untouched(self):
        """Список наблюдения не менялся (запрет прохода)."""
        assert '"langchain-ai/langchain",' in LZ_SRC
        assert '"moorcheh-ai/memanto",' in LZ_SRC
        assert '"openai/openai-python",' in LZ_SRC
        assert '"anthropics/anthropic-sdk-python",' in LZ_SRC

    def test_app_mlog_untouched(self):
        import subprocess
        out = subprocess.run(["git", "diff", "origin/main", "--", "app.mlog"],
                             cwd=str(REPO_ROOT), capture_output=True, text=True)
        assert out.stdout.strip() == "", "наряд #721 не правит app.mlog"

    def test_search_queries_untouched(self):
        """Поисковые запросы (GITHUB_SEARCH_QUERIES) не менялись."""
        assert '"mem0 mem0ai agent memory stars:>5",' in LZ_SRC
        assert '"Flask LLM proxy failover stars:>3",' in LZ_SRC
