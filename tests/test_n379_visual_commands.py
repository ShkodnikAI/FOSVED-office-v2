"""Наряд №379: гварды Visual — 8 слэш-команд промпта, auto-hook Type 3,
доставка PDF в TG (не регрессировала), README-каталог.

Факт наряда: dept/visual.mlog был keyword-only (8 команд промпта не мапились);
auto-hook Type 3 (карточка при completion анализа) не подключён; PDF-доставка
в TG была сделана нарядом-361 — гвард не даёт ей регрессировать.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VISUAL = (REPO_ROOT / "dept" / "visual.mlog").read_text(encoding="utf-8")
MINIAPP = (REPO_ROOT / "dept" / "miniapp.mlog").read_text(encoding="utf-8")
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
README_GUARD = (REPO_ROOT / "tests" / "test_readme_commands.py").read_text(encoding="utf-8")

# 8 команд из промпта отдела (uploads/dept-originals/visual/library/visual.md «Команды»)
COMMANDS = [
    'starts_with(t, "/visual ") or t == "/visual"',
    'starts_with(t, "/visual-card")',
    'starts_with(t, "/visual-archive")',
    'starts_with(t, "/visual-show")',
    'starts_with(t, "/visual-template")',
    't == "/visual-style"',
    'starts_with(t, "/visual-spec")',
    'starts_with(t, "/visual-recall")',
]


def test_eight_slash_commands_routed():
    """Все 8 команд промпта мапятся в HandleVisual ПЕРЕД keyword-routing."""
    handle_seg = VISUAL[VISUAL.index("pattern HandleVisual"):]
    for cond in COMMANDS:
        assert cond in handle_seg, f"нет ветки команды: {cond}"
    # команды стоят до keyword-routing (приоритет слэша над ключевиками)
    first_cmd_pos = handle_seg.index('starts_with(t, "/visual ")')
    keyword_pos = handle_seg.index('if contains(q, "карточк")')
    assert first_cmd_pos < keyword_pos, "слэш-команды должны парситься раньше ключевиков"


def test_command_handlers_wired():
    """Команды ведут к генераторам/хелперам, а не заглушкам."""
    assert "pattern VisualAutoDetectSource" in VISUAL
    assert "pattern VisualTemplateInfo" in VISUAL
    assert "pattern VisualStyleGuide" in VISUAL
    assert "pattern VisualRecallTest" in VISUAL
    # генераторы вызываются из командного блока
    for gen in ("GenerateAnalysisCard", "GenerateCompressionVisual",
                "GenerateMemorableInfographic", "GenerateReferenceSheet",
                "GeneratePremiumSpec"):
        assert gen in VISUAL[VISUAL.index("pattern HandleVisual"):], f"{gen} не вызывается из HandleVisual"
    # style guide строится из реальных палитр color_palette, не выдуманных хексов
    assert 'color_palette("authority", "light")' in VISUAL[VISUAL.index("pattern VisualStyleGuide"):]
    assert 'color_palette("energy", "light")' in VISUAL[VISUAL.index("pattern VisualStyleGuide"):]


def test_auto_hook_type3_wired():
    """Auto-hook Type 3: SendReport аналитиков → карточка отчёта, fire-and-forget."""
    assert "pattern VisualAutoCardFromReport" in VISUAL
    hook_seg = MINIAPP[MINIAPP.index("AUTO-HOOK Type 3"):]
    hook_seg = hook_seg[:hook_seg.index("return short")]
    assert "VisualAutoCardFromReport(dept, doc_id, chat_id)" in hook_seg
    # только аналитические отделы
    assert 'dept == "osp" or dept == "expert" or dept == "lz" or dept == "finance" or dept == "legal"' in hook_seg
    # fire-and-forget: отказ визуала не ломает доставку отчёта
    assert "TryVal(try VisualAutoCardFromReport" in hook_seg
    # hook стоит ПОСЛЕ доставки отчёта (после AUTO-ARCHIVE блока)
    assert MINIAPP.index("AUTO-ARCHIVE") < MINIAPP.index("AUTO-HOOK Type 3")
    # miniapp импортирует visual
    assert "import dept/visual" in MINIAPP


def test_report_source_branch():
    """GenerateAnalysisCard читает источник 'report' (miniapp_responses) + бейдж ОТЧЁТ."""
    assert 'if src_type == "report" then {' in VISUAL
    assert "FROM miniapp_responses WHERE id = ?" in VISUAL
    assert 'let badge = "ОТЧЁТ"' in VISUAL


def test_pdf_delivery_not_regressed():
    """Наряд-361: все 4 генератора шлют PDF документом в TG (не путём строкой)."""
    for gen in ("GenerateAnalysisCard", "GenerateCompressionVisual",
                "GenerateMemorableInfographic", "GenerateReferenceSheet"):
        seg = VISUAL[VISUAL.index(f"pattern {gen}"):]
        seg = seg[:seg.index("\npattern ", 10)] if "\npattern " in seg[10:] else seg
        assert "SendVisualDocument(chat_id, output_path" in seg, f"{gen} не шлёт документ"
    # питон-сторона: /send-document жив (routes_core.py)
    routes = (REPO_ROOT / "proxy" / "routes_core.py").read_text(encoding="utf-8")
    assert "_tg_send_document(chat_id, fpath, caption)" in routes


def test_visual_commands_documented():
    """8 команд в README-каталоге; гвард live-vs-docs знает dept-команды."""
    for cmd in ("visual", "visual-card", "visual-archive", "visual-show",
                "visual-template", "visual-style", "visual-spec", "visual-recall"):
        assert f"`/{cmd}`" in README, f"/{cmd} не задокументирован в README"
    assert "DEPT_LIVE_COMMANDS" in README_GUARD
    assert '"visual-recall"' in README_GUARD


def test_keyword_fallback_intact():
    """Границы: LLM-fallback и LLM-Verifier визуала не тронуты."""
    assert 'contains(q, "карточк") or contains(q, "card")' in VISUAL
    assert 'contains(q, "компресси") or contains(q, "compression")' in VISUAL
    assert 'call_python("llm_verifier", "score"' in VISUAL
    # дисклеймер на raw-LLM выводе сохранён
    assert "VisualWrapWithDisclaimer" in VISUAL or "VisualDisclaimer()" in VISUAL
