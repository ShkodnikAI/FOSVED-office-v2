#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FORGE-UI-6 tests (#199): страница отчёта — перевод на тёмную систему UI-0.

Гварды:
- report_css.txt использует токены FORGE-UI-0 (--bg/--surface/--red/--green/--yellow)
  из miniapp/index.html; бумажные значения (--paper:#EFEAE0 и др.) не возвращаются
  как основные (legacy-алиасы разрешены — на них ссылаются внешние var(--...));
- красный не хардкодится там, где приходит акцент отдела (accent_color передаётся
  auto_enricher параметром; .action-btn.primary/.notes-input используют var(--accent));
- бейджи ФАКТ (зелёный) / ИНТЕРПРЕТАЦИЯ (жёлтый) — токены;
- карточки метрик — градиентное число с background-clip:text;
- инфо-карточки — тёмная поверхность (accent border приходит inline от обогатителя);
- вердикт — тёмная карточка с явной рамкой;
- action-bar остаётся sticky, кнопки на surface2, логика классов не менялась;
- печать: @media print переключает на светлые значения (Smoke-6).
"""
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = open(os.path.join(REPO_ROOT, "report_css.txt"), encoding="utf-8").read()
INDEX = open(os.path.join(REPO_ROOT, "miniapp", "index.html"), encoding="utf-8").read()


def test_tokens_match_ui0_values():
    # значения токенов совпадают с miniapp (источник истины FORGE-UI-0)
    for token in ("--bg:#0A0A0C", "--surface:#151517", "--surface2:#1C1C1F",
                  "--red:#E8262E", "--red-light:#FF8A8F", "--ink:#EDEDED",
                  "--muted:#8A8A8F", "--green:#7ED957", "--yellow:#F5C93E",
                  "--line:#232326"):
        assert token in CSS, token
        assert token in INDEX, token


def test_paper_values_not_primary():
    # старые бумажные значения не возвращаются как токены темы
    assert "--paper:#EFEAE0" not in CSS
    assert "--ink:#1C1B18" not in CSS


def test_legacy_aliases_point_to_new_tokens():
    # внешние var(--paper)/var(--stamp)/var(--ok) ссылки продолжают работать
    assert "--paper:var(--bg)" in CSS
    assert "--paper-raised:var(--surface)" in CSS
    assert "--stamp:var(--red)" in CSS
    assert "--ok:var(--green)" in CSS
    assert "--warn:var(--yellow)" in CSS


def test_accent_not_hardcoded_where_dept_accent_applies():
    # акцент приходит параметром (auto_enricher → inline) и через --accent
    assert "background:var(--accent,var(--red))" in CSS
    assert "border-color:var(--accent,var(--red))" in CSS
    # в info-card CSS не задаёт цвет границы (inline от обогатителя приоритетен)
    info = [l for l in CSS.splitlines() if l.startswith(".info-card {")][0]
    assert "border-left" not in info


def test_badges_fact_green_interp_yellow():
    assert ".badge-fact { background: var(--ok-soft); color: var(--green); }" in CSS
    assert ".badge-interp { background: var(--warn-soft); color: var(--yellow); }" in CSS


def test_metric_value_gradient_number():
    assert ".metric-value" in CSS
    assert "background:linear-gradient(135deg,var(--red),var(--red-light))" in CSS
    assert "-webkit-background-clip:text" in CSS
    assert "background-clip:text" in CSS
    assert "color:transparent" in CSS


def test_info_cards_dark_surface():
    assert ".info-card { background:var(--surface)" in CSS
    assert "border:1px solid var(--line)" in CSS


def test_verdict_dark_card_with_frame():
    assert ".verdict-block { background:var(--surface); border:1.5px solid var(--red)" in CSS


def test_action_bar_sticky_and_surface2_buttons():
    assert ".action-bar{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;padding:12px 16px;border-top:1px solid var(--line);background:var(--surface);position:sticky;bottom:0;z-index:10}" in CSS
    assert ".action-btn.rich{padding:10px 4px;border:1px solid var(--line);border-radius:8px;background:var(--surface2)" in CSS


def test_print_light_media():
    # Smoke-6: печать остаётся читаемой — светлые значения в @media print
    m = re.search(r"@media print \{(.*?)\}\n?$", CSS, re.S)
    assert m, "@media print отсутствует"
    block = m.group(1)
    assert "--bg:#FFFFFF" in block and "--ink:#1A1A1C" in block
    assert ".action-bar{display:none}" in block


def test_class_names_preserved():
    # генераторы отчётов ссылаются на эти классы — переименовывать нельзя
    for cls in (".report-header", ".report-meta", ".report-body", ".badge-fact",
                ".badge-interp", ".badge-spec", ".metric-card", ".info-card",
                ".verdict-block", ".action-bar", ".action-btn", ".depth-menu",
                ".control-menu", ".notes-section", ".note-item", ".disclaimer-rich",
                ".report-chart", ".ach-table", ".indicator-card", ".compare-grid"):
        assert cls in CSS, cls


def test_action_bar_hex_swaps_dark_readable():
    # depth-dot литералы шаблона переведены на тёмно-читаемые значения
    src = open(os.path.join(REPO_ROOT, "proxy", "reports.py"), encoding="utf-8").read()
    assert 'background:#7ED957' in src and 'background:#F5C93E' in src
    assert 'background:#3D6B2C' not in src  # старый тёмно-зелёный на тёмном фоне
