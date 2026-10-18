#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наряд #552: отчёты из Mini App открываются полной страницей; поля разнесены.

Гварды (по наряду):
- A.3.1: /api/archive отдаёт id у каждой записи (он же doc_id страницы);
- A.3.2: шаблоны Mini App («Последние отчёты» на главной + «Архив») открывают
  отчёт через data-doc, заглушка data-body="Полный отчёт — в архиве..." и
  обработчик data-report удалены; ветка data-doc стоит ПОСЛЕ data-aredit —
  кнопка «изменить» перехватывает клик раньше (запрет прохода);
- A.3.3: /miniapp/<id> с валидной подписью tgWebAppData → 200; с чужой
  подписью → 403 (SEC-4). Подпись — по алгоритму _verify_init_data:
  HMAC(secret_key, check_string), secret_key = HMAC(b"WebAppData", token);
- A.3.4: HTML страницы отчёта — два подписанных блока, кнопки текстом
  «Сохранить»/«Пересчитать», отступ между блоками ≥ 16 px и цели 44 px
  (проверка CSS report_css.txt);
- A.1: на странице отчёта есть возврат в Mini App (BackButton + «← К отчётам»).
"""
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from urllib.parse import urlencode

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['API_SECRET'] = 'test-secret-123'
os.environ['TELEGRAM_WEBHOOK_SECRET'] = 'tg-wh-secret'
os.environ['OWNER_TELEGRAM_ID'] = '12345'
os.environ['DATABASE_PATH'] = '/tmp/fosved-n552-test'
os.environ['ZAI_API_KEY'] = 'fake-key'
# TELEGRAM_BOT_TOKEN глобально НЕ задаётся: require_telegram без токена
# пропускает. Тест A.3.3 ставит токен локально (monkeypatch) и подписывает
# initData по алгоритму SEC-4.

import llm_proxy  # noqa: E402,F401 — конвенция тестов Flask: импорт до прокси-роутов
from proxy.core import app as flask_app  # noqa: E402
from proxy import routes_core  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(REPO_ROOT, 'miniapp', 'index.html'), encoding='utf-8') as f:
    MINIAPP_HTML = f.read()
with open(os.path.join(REPO_ROOT, 'report_css.txt'), encoding='utf-8') as f:
    REPORT_CSS = f.read()

MASTER = 'test-secret-123'
API_AUTH = {'Authorization': f'Bearer {MASTER}'}

RAW = ("[ФАКТ] Курс стабилен.\n[ИНТЕРПРЕТАЦИЯ] Волатильность снизится.\n"
       "Вердикт: наблюдать.\n\nВероятности: база 0.6 / риск 0.3 / хвост 0.1. "
       "Дополнительный контекст отчёта для обогащённого рендера страницы.")


def _client():
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture()
def client():
    return _client()


def _make_doc(dept='osp', title='Отчёт #552'):
    cid = f"doc-n552-{uuid.uuid4().hex[:8]}"
    routes_core._query(
        "INSERT INTO miniapp_responses (id,dept,title,query,raw_text,html,confidence,created_at) "
        "VALUES (?,?,?,?,?,?,?,datetime('now'))",
        (cid, dept, title, 'вопрос теста #552', RAW, '', 'medium'))
    return cid


def _del_doc(cid):
    routes_core._query("DELETE FROM miniapp_responses WHERE id=?", (cid,))
    routes_core._query("DELETE FROM miniapp_notes WHERE doc_id=?", (cid,))


def _sign_init_data(bot_token, user_id=12345):
    """Подпись initData по алгоритму SEC-4 (proxy/core._verify_init_data)."""
    params = {
        'auth_date': str(int(time.time())),
        'query_id': 'AAG552test',
        'user': json.dumps({'id': user_id, 'first_name': 'Owner'},
                           separators=(',', ':')),
    }
    check_string = '\n'.join(f'{k}={params[k]}' for k in sorted(params))
    secret_key = hmac.new(b'WebAppData', bot_token.encode(),
                          hashlib.sha256).digest()
    sig = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(params) + f'&hash={sig}'


# ── A.3.1: /api/archive — у каждой записи есть id ──────────────────────────

def test_archive_results_have_id(client):
    d1 = _make_doc('osp', 'Отчёт 552-a')
    d2 = _make_doc('finance', 'Отчёт 552-b')
    try:
        r = client.get('/api/archive', headers=API_AUTH)
        assert r.status_code == 200
        results = r.get_json()['results']
        assert results, 'свежие записи не видны в /api/archive'
        assert all('id' in row for row in results), 'запись без id — открыть нечего'
        ids = {row['id'] for row in results}
        assert d1 in ids and d2 in ids
    finally:
        _del_doc(d1)
        _del_doc(d2)


# ── A.3.2: шаблоны Mini App открывают отчёт (data-doc) ─────────────────────

def test_miniapp_templates_use_data_doc():
    # главная: элемент «Последних отчётов» — data-doc вместо data-go="archive"
    assert 'data-doc="\'+esc(r.id)+\'"' in MINIAPP_HTML
    assert 'data-go="archive"><div class="report-dot"' not in MINIAPP_HTML, \
        'главная по-прежнему только переключает вкладку архива'
    # архив: строка — data-doc, заглушка data-body удалена
    assert 'class="arow" type="button" data-doc=' in MINIAPP_HTML
    assert 'data-body="Полный отчёт — в архиве' not in MINIAPP_HTML
    # обработчик data-report удалён вместе с заглушкой
    assert 'hasAttribute("data-report")' not in MINIAPP_HTML
    # [data-doc] в делегировании кликов
    assert '[data-doc]' in MINIAPP_HTML
    # ветка data-doc после data-aredit: «изменить» перехватывает клик раньше
    idx_aredit = MINIAPP_HTML.index('hasAttribute("data-aredit")')
    idx_doc = MINIAPP_HTML.index('hasAttribute("data-doc")')
    assert idx_aredit < idx_doc, 'клик по «изменить» попадёт в открытие отчёта'
    # переход с initData в query; при пустом — bootstrap-страница SEC-4
    assert '"/miniapp/"+did' in MINIAPP_HTML
    assert '(tg&&tg.initData)?tg.initData:""' in MINIAPP_HTML
    assert 'encodeURIComponent(idata)' in MINIAPP_HTML


# ── A.3.3: доступ к странице отчёта по подписи Telegram ────────────────────

def test_miniapp_page_access_signed(client, monkeypatch):
    from proxy import core as _core
    token = 'test-bot-token-552'
    monkeypatch.setattr(_core, 'TELEGRAM_BOT_TOKEN', token)
    doc = _make_doc('osp', 'Отчёт 552-sec')
    good = _sign_init_data(token, user_id=12345)
    bad = _sign_init_data('attacker-bot-token', user_id=12345)
    try:
        r_ok = client.get(f'/miniapp/{doc}', query_string={'tgWebAppData': good})
        assert r_ok.status_code == 200, 'валидная подпись отклонена'
        r_bad = client.get(f'/miniapp/{doc}', query_string={'tgWebAppData': bad})
        assert r_bad.status_code == 403, 'чужая подпись пропущена (SEC-4)'
    finally:
        _del_doc(doc)


# ── A.3.4 + A.1: страница отчёта — подписанные поля, кнопки текстом, возврат ──

@pytest.fixture()
def _no_bot_token(monkeypatch):
    from proxy import core as _core
    monkeypatch.setattr(_core, "TELEGRAM_BOT_TOKEN", "")
    yield


def test_report_page_fields_and_back_bar(client, _no_bot_token):
    doc = _make_doc('osp', 'Отчёт 552-fields')
    try:
        r = client.get(f'/miniapp/{doc}', headers=API_AUTH)
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        # два подписанных блока
        assert 'Заметка для себя (отдел не перезапускается)' in html
        assert 'Уточнить и пересчитать отчёт' in html
        # кнопки текстом, не значки
        assert '>Сохранить</button>' in html
        assert '>Пересчитать</button>' in html
        assert "addNote()\">+<" not in html
        assert "addRefine()\">↻<" not in html
        assert "btn.textContent='↻'" not in html, 'иконка возвращается в кнопку после сбоя'
        # возврат в Mini App: BackButton + явная ссылка
        assert '← К отчётам' in html
        assert 'BackButton' in html
        assert '/miniapp-spa' in html
    finally:
        _del_doc(doc)


def test_report_css_44px_and_gap():
    # A.3.4: цели пальца и разнос блоков — в CSS страницы отчёта
    assert 'min-height:44px' in REPORT_CSS
    assert '.notes-label' in REPORT_CSS
    assert 'margin:16px 0 6px' in REPORT_CSS, 'отступ между блоками < 16 px'
    assert '.notes-label.accent' in REPORT_CSS
