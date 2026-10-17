#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #524: гейт деплоя — не зеленеть без деплоя; деплоить проверенный коммит.

Дефекты (прод/Actions, 15–16.10):
1. Пустой секрет RENDER_DEPLOY_HOOK → warning + exit 0 → зелёная «Deploy gate»
   без деплоя — прод стоял на 9212d77 с 13.10 по 16.10 незамеченным.
2. Хук вызывался без указания коммита → Render деплоил HEAD ветки на момент
   вызова, а не github.sha, прошедший проверки (16.10: прогон по 7a70c5a —
   задеплоен 453e793).

Гварды (статические, по .github/workflows/ci.yml — джоба в PR-прогонах не
исполняется: deploy только на push в main; живая проверка — следующий мерж:
в Render deploy trigger=deploy_hook с commit.id == github.sha, сверка аудитором).
"""
import os
import re

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CI = os.path.join(ROOT, ".github", "workflows", "ci.yml")

with open(CI, encoding="utf-8") as f:
    WF = yaml.safe_load(f)
DEPLOY_RUN = WF["jobs"]["deploy"]["steps"][0]["run"]
NOTIFY_NEEDS = WF["jobs"]["notify-red"]["needs"]


def test_no_exit0_on_empty_secret():
    assert 'RENDER_DEPLOY_HOOK' in DEPLOY_RUN
    m = re.search(r'if \[ -z "\$RENDER_DEPLOY_HOOK" \]; then(.*?)fi', DEPLOY_RUN, re.S)
    assert m, "нет ветки пустого секрета"
    assert "exit 0" not in m.group(1), "#524 A.1: пустой секрет — зелёный гейт без деплоя"
    assert "exit 1" in m.group(1), "пустой секрет обязан ронять джобу"


def test_hook_pinned_to_commit_sha():
    assert "&ref=${COMMIT_SHA}" in DEPLOY_RUN or "&ref=$COMMIT_SHA" in DEPLOY_RUN, \
        "#524 A.2: хук без ref= — Render деплоит HEAD, а не проверенный коммит"
    assert "docs.render.com/deploy-hooks" in DEPLOY_RUN or "Deploying a specific Git commit" in DEPLOY_RUN, \
        "ссылка на документацию Render должна быть в комментарии джобы (требование A.2)"


def test_deploy_id_verified_in_response():
    assert "deploy" in DEPLOY_RUN and ("DEPLOY_ID" in DEPLOY_RUN), "#524 A.3: id деплоя не проверяется"
    assert "Ответ хука без deploy.id" in DEPLOY_RUN, "нет гейта на отсутствие id"


def test_notify_red_covers_deploy_failure():
    assert "deploy" in NOTIFY_NEEDS, "notify-red не узнает о падении deploy-джобы"


def test_workflow_yaml_parses():
    assert WF["jobs"]["deploy"]["name"].startswith("Deploy gate")
