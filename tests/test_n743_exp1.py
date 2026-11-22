#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#743 EXP-1: Эксперт — профессионал мирового уровня в любой отрасли, без
формата подготовок к переговорам; «шкурки» отраслей; шаблон отчёта с
«Только для профи» и «Отрицательные нюансы».

Запреты: код dept/expert.mlog не тронут (EXP-2); содержимое шкурок —
только auto (перенесено из ExpertAutomotiveKB/SkillSet); в профиле
не обещаются источники, которых нет в EXP-2.
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

os_env_note = None  # noqa: F841 — маркер чтения файла без импорта proxy-приложения
from proxy.expert_skins import ALLOWED_TOOLS, list_skins, validate_skin  # noqa: E402

PROFILE = (REPO / "library" / "expert.md").read_text(encoding="utf-8")
TEMPLATE = (REPO / "library" / "expert_report_template.md").read_text(encoding="utf-8")
SKIN_AUTO = REPO / "skills" / "expert" / "skins" / "auto" / "SKIN.md"
SKINS_README = (REPO / "skills" / "expert" / "skins" / "README.md").read_text(encoding="utf-8")
EXPERT_MLOG = (REPO / "dept" / "expert.mlog").read_text(encoding="utf-8")


# ─────────────── A.1: профиль ───────────────

def test_a1_no_meeting_words():
    """НАРЯД A.1: grep -i 'встреч|дедлайн|брифинг|meeting' → 0."""
    hits = re.findall(r"встреч|дедлайн|брифинг|meeting", PROFILE, re.I)
    assert not hits, f"запрещённые слова в профиле: {set(hits)}"


def test_a1_frontmatter_new_role():
    """Title новой роли; нет archiveModel ExpertBriefing и meeting-метрик."""
    assert "title: Эксперт · Профессионал в любой отрасли" in PROFILE
    assert "ExpertBriefing" not in PROFILE
    assert "meeting_understanding_score" not in PROFILE
    assert "archiveModel" not in PROFILE
    assert "skillsDir: skills/expert/skins/" in PROFILE


def test_a1_hard_rules_new():
    """Новые жёсткие правила: механизм+источник или «опыт практиков»;
    запрет фраз без содержания; «надеваю»."""
    assert "опыт практиков, документально не подтверждено" in PROFILE
    assert "«в целом», «как правило», «существуют риски»" in PROFILE, \
        "запрет фраз без содержания"
    assert "надеваю" in PROFILE.lower()
    assert "механизм" in PROFILE and "источником" in PROFILE


def test_a1_saved_rules_semantics():
    """По смыслу сохранены прежние правила 2, 5, 6: без искажающих
    упрощений; независимые источники; каждое утверждение проверяемо."""
    assert "исказят суть" in PROFILE or "исказят суть" in PROFILE.lower()
    assert "Независимые источники" in PROFILE or "независимые источники" in PROFILE.lower()
    assert "проверяем" in PROFILE.lower() or "проверяемо" in PROFILE.lower()


def test_a1_depth_and_rival_review():
    """Глубина: до 12 поисков обычный, до 25 /deepexpert; разбор черновика
    «конкурирующим профессионалом» — EXP-2."""
    assert "12 поисков" in PROFILE
    assert "25 поисков" in PROFILE
    assert "конкурирующим профессионалом" in PROFILE and "EXP-2" in PROFILE


def test_a1_metrics_real():
    """Метрики: оценка владельца кнопками (RatingRowCreate); доля нюансов
    с источником; число нюансов, подтверждённых позже (Кавальня)."""
    assert "RatingRowCreate" in PROFILE
    assert "Доля нюансов с источником" in PROFILE
    assert "подтверждённых позже" in PROFILE and "Кавальня" in PROFILE


def test_a1_sources_only_real():
    """Запрет обещаний: источники — только подключённые; неподключённые
    (PubMed и др.) помечены «не подключены» и «не обещаются»."""
    assert "| Живой поиск Tavily" in PROFILE and "подключён" in PROFILE
    assert "до подключения не обещаются" in PROFILE
    # каждое упоминание неподключённого источника — только в строке таблицы
    # со статусом «не подключены» (обещание вне пометки — брак профиля)
    for banned in ("PubMed", "FDA", "EMA", "NIH RePORTER"):
        for line in PROFILE.splitlines():
            if banned in line:
                assert "не подключены" in line, \
                    f"{banned} упомянут вне строки «не подключены»: {line[:80]}"


def test_a1_no_skins_content_but_auto():
    """Запрет: содержимое шкурок кроме авто не пишется — каталог skins
    содержит README и только auto/SKIN.md."""
    skins = sorted((REPO / "skills" / "expert" / "skins").glob("*/SKIN.md"))
    assert [str(s.relative_to(REPO / "skills" / "expert" / "skins")) for s in skins] == \
        ["auto/SKIN.md"]


# ─────────────── A.2: шаблон отчёта ───────────────

def test_a2_nine_sections_in_order():
    """НАРЯД A.2: 9 обязательных разделов в фиксированном порядке."""
    heads = ["## 1. Надеваю", "## 2. Коротко", "## 3. Очевидное",
             "## 4. Только для профи", "## 5. Отрицательные нюансы и подводные камни",
             "## 6. Вопросы, которыми проверить собеседника или продавца",
             "## 7. Цифры", "## 8. Что не удалось проверить", "## 9. Источники"]
    pos = [TEMPLATE.index(h) for h in heads]
    assert pos == sorted(pos), "порядок разделов нарушен"


def test_a2_table_structures():
    """«Только для профи» — «Как говорят → Что это значит на деле»;
    нюансы — что/механизм/серьёзность/распознать/источник; вопросы —
    вопрос/хороший/уклончивый; цифры — с источником."""
    assert "Как говорят → Что это значит на деле" in TEMPLATE
    for req in ("**Что:**", "**Механизм:**", "низко / средне / критично",
                "**Как распознать:**", "опыт практиков, документально не подтверждено"):
        assert req in TEMPLATE
    assert "хороший ответ → уклончивый ответ" in TEMPLATE
    assert "каждая с источником" in TEMPLATE.lower() or "Каждая цифра с источником" in TEMPLATE


def test_a2_disclaimer_line():
    """Медицина/право/финансы: строка «информационный разбор, не
    консультация специалиста» без сокращения глубины."""
    assert "информационный разбор, не консультация специалиста" in TEMPLATE
    assert "без сокращения глубины" in TEMPLATE


# ─────────────── A.3: формат шкурок и auto ───────────────

def test_a3_skin_format_fields():
    """README описывает формат: domain, professions, triggers, standards,
    failure_catalog, insider_glossary, sources, tools."""
    for field in ("domain", "professions", "triggers", "standards",
                  "Failure catalog", "Insider glossary", "sources", "tools"):
        assert field in SKINS_README, field


def test_a3_auto_skin_valid_by_validator():
    """НАРЯД A.3: валидатор формата (EXP-2 его использует) принимает
    auto/SKIN.md."""
    ok, errors = validate_skin(SKIN_AUTO)
    assert ok, errors


def test_a3_validator_rejects_broken(tmp_path):
    """Валидатор отклоняет: без frontmatter, с пустыми полями, чужим
    domain, tools вне белого списка, без разделов тела."""
    cases = [
        (tmp_path / "x1" / "SKIN.md", "тело без фронта\n"),
        (tmp_path / "x2" / "SKIN.md", "---\ndomain: x2\n---\n\n## Failure catalog\n## Insider glossary\n"),
        (tmp_path / "auto" / "SKIN.md", "---\ndomain: wrong\nprofessions: [a]\ntriggers: [t]\nstandards: [s]\nsources: [s]\ntools: [chart]\n---\n\n## Failure catalog\n## Insider glossary\n"),
        (tmp_path / "x3" / "SKIN.md", "---\ndomain: x3\nprofessions: [a]\ntriggers: [t]\nstandards: [s]\nsources: [s]\ntools: [magic]\n---\n\n## Failure catalog\n## Insider glossary\n"),
    ]
    for path, content in cases:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        ok, errors = validate_skin(path)
        assert not ok, f"{path} не должен проходить"
    # чужой домен и bad tools — конкретные ошибки
    ok, errors = validate_skin(tmp_path / "auto" / "SKIN.md")
    assert any("не совпадает" in e for e in errors)
    ok, errors = validate_skin(tmp_path / "x3" / "SKIN.md")
    assert any("белого списка" in e for e in errors)


def test_a3_auto_skin_transferred_kb():
    """Перенос знаний: SKIN.md auto содержит данные ExpertAutomotiveKB
    (остаточная стоимость, стоимость владения, бренды, размерности) и
    ExpertAutomotiveSkillSet (красные флаги, методика сравнения, TCO)."""
    skin = SKIN_AUTO.read_text(encoding="utf-8")
    for kb_line in ("| Эконом/компакт | 78 | 65 | 55 | 40 | 28 |",
                    "| Премиум/люкс | 65 | 50 | 42 | 28 | 18 |",
                    "| Электро | 50 | 15 | 30 | 250 | ~345 |",
                    "GAZelle NEXT", "Zeekr 001", "Chery Tiggo 7 Pro"):
        assert kb_line in skin, kb_line
    for kb_item in ("10-мерное пространство" if False else "Размерности для сравнительного анализа",
                    "нормализация по лучшему в категории",
                    "полная стоимость владения = цена покупки",
                    "нет истории остаточной стоимости старше 3 лет",
                    "деградация батареи не гарантирована" if False else "не гарантирована гарантией производителя",
                    "параллельный импорт — без заводской гарантии"):
        assert kb_item in skin, kb_item


def test_a3_tools_real_in_code():
    """tools[] шкурки — только реально существующие функции: avby_listings,
    residual_value, operation_cost, chart есть в dept/expert.mlog."""
    skin_meta, _ = __import__("proxy.expert_skins", fromlist=["parse_skin"]).parse_skin(SKIN_AUTO)
    assert set(skin_meta["tools"]) == ALLOWED_TOOLS
    # швы в коде
    assert "ExpertAvByListings" in EXPERT_MLOG
    assert "search_avby" in EXPERT_MLOG
    assert "ExpertResidualValueData" in EXPERT_MLOG
    assert "ExpertGenerateChart" in EXPERT_MLOG
    assert '"operation_cost"' in EXPERT_MLOG or "operation_cost" in EXPERT_MLOG


def test_a3_expert_mlog_kb_transferred():
    """EXP-1: перенос знаний в шкурку. После EXP-2 (#744 A.3) KB-паттерны
    удалены из кода (перенос завершён — шкурка auto живёт в файле);
    живой поиск и инструменты остаются."""
    assert "pattern ExpertAutomotiveKB(" not in EXPERT_MLOG
    assert "pattern ExpertAutomotiveSkillSet(" not in EXPERT_MLOG
    assert "pattern ExpertTavilySearch(" in EXPERT_MLOG
    assert "pattern ExpertAvByListings(" in EXPERT_MLOG
    # знания живы в шкурке auto
    skin = SKIN_AUTO.read_text(encoding="utf-8")
    assert "| Эконом/компакт | 78 | 65 | 55 | 40 | 28 |" in skin


def test_a3_list_skins_catalog():
    """list_skins: валидная шкурка видна в каталоге (EXP-2 подгружает)."""
    entries = list_skins(REPO / "skills" / "expert" / "skins")
    domains = [e[0] for e in entries]
    assert "auto" in domains
    auto_entry = next(e for e in entries if e[0] == "auto")
    assert auto_entry[1].endswith("auto/SKIN.md")


def test_a1_profile_skinned_command_model():
    """Шкурка — не подкоманда: в профиле нет /expert-auto; команды —
    /expert и /deepexpert."""
    assert "/expert-auto" not in PROFILE
    assert "/expert <тема>" in PROFILE and "/deepexpert <тема>" in PROFILE
    assert "Отдельных подкоманд доменов нет" in PROFILE
