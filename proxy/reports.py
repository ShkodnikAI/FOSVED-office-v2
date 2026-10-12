"""FO-008: HTML-билдеры отчётов и служебных страниц (фирменный стиль).

Вырезано из llm_proxy.py вербатим (стренглер, шаг 3; наряд #68, стоп-гейт SG-F2).
"""
import re
import os
import time
import hmac
import hashlib
import html as html_lib
from datetime import datetime, timedelta

from flask import request, jsonify

from proxy.core import (
    log,
    _query,
    DEPT_COLORS,
    DEPT_NAMES,
    DEPT_HASHTAGS,
)

def html_lib_escape(s):
    """Safe HTML escape for report templates."""
    return html_lib.escape(str(s)) if s else ''

# ── #497 A.1: токен документа для action-bar и заметок ──────────────────────
# HMAC от doc_id (+ срок) ключом сервера — по образцу ссылок досье
# /shop/dossier/<id>?t= (proxy/shop_dossier.dossier_token). Кладётся в
# страницу вместо мастер-ключа API_SECRET: страница уходит наружу кнопкой
# «Поделиться» и остаётся в истории браузера — мастер-ключ в ней означал бы
# доступ ко всему защищённому API офиса. Токен действует ТОЛЬКО на свой
# doc_id и только до срока; внутренние вызовы по-прежнему шлют мастер-ключ.
DOC_TOKEN_TTL_SECS = 30 * 24 * 3600  # 30 дней: страница живёт в истории браузера


def doc_action_token(doc_id, now=None):
    """Токен документа: '<exp>.<hmac>' — валиден только для doc_id до exp."""
    exp = int(now if now is not None else time.time()) + DOC_TOKEN_TTL_SECS
    secret = os.environ.get("API_SECRET", "") or "dev-secret"
    sig = hmac.new(secret.encode(), f"miniapp-doc:{doc_id}:{exp}".encode(),
                   hashlib.sha256).hexdigest()[:32]
    return f"{exp}.{sig}"


def doc_token_verify(token, doc_id, now=None):
    """Проверка токена документа для doc_id.

    Возвращает 'ok' | 'mismatch' (токен другого документа) |
    'stale' (срок вышел) | 'bad' (мусор/пусто)."""
    if not token or token.count(".") != 1:
        return "bad"
    exp_s, sig = token.split(".", 1)
    if not (exp_s.isdigit() and re.fullmatch(r"[0-9a-f]{32}", sig)):
        return "bad"
    exp = int(exp_s)
    secret = os.environ.get("API_SECRET", "") or "dev-secret"
    expected = hmac.new(secret.encode(), f"miniapp-doc:{doc_id}:{exp}".encode(),
                        hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expected, sig):
        return "mismatch"
    if (now if now is not None else time.time()) > exp:
        return "stale"
    return "ok"

# ──────────────────────────── HTML STRIP FOR ARCHIVE ────────────────────────────
def strip_html_for_archive(html_content):
    """Convert HTML badges to text markers and strip all tags for Telegram."""
    text = html_content
    # Convert badge spans with known classes to text markers
    badge_map = {
        'badge-fact': '✓',
        'badge-int': '◈',
        'badge-interp': '◈',
        'badge-spec': '⚡',
        'badge-verified': '[FACT verified]',
        'badge-unverified': '[FACT unverified]',
        'badge-conflicting': '[CONFLICT]',
    }
    for cls, marker in badge_map.items():
        # Match <span class="badge badge-xxx">content</span>
        pattern = r'<span[^>]*class="[^"]*\b' + re.escape(cls) + r'\b[^"]*"[^>]*>(.*?)</span>'
        text = re.sub(pattern, marker + r' \1 ', text, flags=re.IGNORECASE | re.DOTALL)
    # Also match class="badge badge-xxx" without space (single class)
    for cls, marker in badge_map.items():
        pattern2 = r'<span[^>]*class="' + re.escape(cls) + r'"[^>]*>(.*?)</span>'
        text = re.sub(pattern2, marker + r' \1 ', text, flags=re.IGNORECASE | re.DOTALL)
    # Remove all remaining HTML tags
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n- ', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '- ', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n[ \t]+', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# ──────────────────────────── HTML HELPERS ────────────────────────────
def _html_base(title, bg="var(--paper)"):
    """FO-045 (наряд #152): база отчётных страниц — токены «Диспетчерской».
    Источник визуального языка один: miniapp/index.html (:root ниже — копия токенов).
    Dark-палитра убрана; .gold/.status-* имена классов сохранены (генераторы
    отчётов ссылаются на них), значения — из токенов.
    """
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,500;0,6..72,600;1,6..72,500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
<title>{title}</title><style>
:root{{--ink:#1C1B18;--paper:#EFEAE0;--paper-raised:#FBF8F2;--line:rgba(28,27,24,.14);--line-strong:rgba(28,27,24,.28);--stamp:#A8321E;--stamp-soft:rgba(168,50,30,.10);--muted:#6B6558;--ok:#3D6B2C;--warn:#9C6B0B;--bad:#A8321E;--d:'Newsreader',Georgia,serif;--b:'IBM Plex Sans',system-ui,sans-serif;--m:'IBM Plex Mono',ui-monospace,monospace;--ok-soft:rgba(61,107,44,.12);--warn-soft:rgba(156,107,11,.12);--bad-soft:rgba(168,50,30,.10)}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:var(--b);background:{bg};color:var(--ink);min-height:100vh}}
h1,h2,h3{{font-family:var(--d);font-weight:600}}
.badge{{font-family:var(--m);font-size:0.85rem;padding:1px 6px;border-radius:4px;display:inline-block;letter-spacing:-1px}}
.badge-fact{{background:var(--ok-soft);color:var(--ok)}} .badge-interp{{background:var(--stamp-soft);color:var(--stamp)}}
.badge-int{{background:var(--stamp-soft);color:var(--stamp)}} .badge-spec{{background:var(--warn-soft);color:var(--warn)}}
.badge-verified{{background:var(--ok-soft);color:var(--ok)}} .badge-unverified{{background:var(--warn-soft);color:var(--warn)}}
.badge-conflicting{{background:var(--bad-soft);color:var(--bad)}}
.card{{background:var(--paper-raised);border:1px solid var(--line);border-radius:12px;padding:20px}}
.kpi{{text-align:center;padding:16px}} .kpi .num{{font-size:2rem;font-weight:700;font-family:var(--m)}}
.kpi .lbl{{font-size:0.75rem;color:var(--muted);margin-top:4px;text-transform:uppercase;letter-spacing:1px}}
.gold{{color:var(--stamp)}} .status-red{{color:var(--bad)}} .status-yellow{{color:var(--warn)}} .status-green{{color:var(--ok)}} .status-blue{{color:var(--stamp)}}
table{{width:100%;border-collapse:collapse;margin:12px 0}} th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);font-size:0.85rem}}
th{{color:var(--muted);font-weight:500;text-transform:uppercase;font-size:0.7rem;letter-spacing:1px}}
a{{color:var(--stamp);text-decoration:none}} a:hover{{text-decoration:underline}}
.grid{{display:grid;gap:16px}} .grid-3{{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}}
.grid-4{{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}}
.header-grad{{padding:32px 40px;border-radius:16px;margin:20px 24px;color:#fff}}
.section{{padding:0 24px;margin-top:24px}} .section h2{{margin-bottom:16px;font-size:1.4rem}}
.mono{{font-family:var(--m)}}
</style></head><body>"""

def _dept_header(dept, title_extra=""):
    c = DEPT_COLORS.get(dept, DEPT_COLORS['admin'])
    name = DEPT_NAMES.get(dept, dept)
    return f'<div class="header-grad" style="background:linear-gradient(135deg,{c["start"]},{c["end"]})">' \
           f'<h1>{name} {title_extra}</h1><p style="color:{c["accent"]};font-size:0.9rem;margin-top:8px">Department Dashboard</p></div>'

def _status_icon(level):
    # FO-045: статусы — токены --ok/--warn/--bad (Диспетчерская)
    colors = {"high": "var(--ok)", "medium": "var(--warn)", "low": "var(--bad)"}
    return f'<span style="color:{colors.get(level,"var(--muted)")};font-size:1.5rem">{"&#x1F7E2;" if level=="high" else "&#x1F7E1;" if level=="medium" else "&#x1F534;"}</span>'

def _dept_kpis(dept):
    now = datetime.utcnow()
    week_ago = (now - timedelta(days=7)).isoformat()
    rows_m = _query("SELECT COUNT(*) as c, COALESCE(AVG(CAST(metric_value AS REAL)),0) as avg_r FROM dept_metrics WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
    rows_t = _query("SELECT COALESCE(SUM(input_tokens),0) as ti, COALESCE(SUM(output_tokens),0) as to2 FROM token_usage WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
    rows_d = _query("SELECT COUNT(*) as c FROM dialog_history WHERE dept=? AND created_at>=?", (dept, week_ago), fetch=True)
    m = rows_m[0] if rows_m else {"c": 0, "avg_r": 0}
    t = rows_t[0] if rows_t else {"ti": 0, "to2": 0}
    d = rows_d[0] if rows_d else {"c": 0}
    return f"""<div class="grid grid-4" style="margin:20px 24px">
<div class="card kpi"><div class="num gold">{m['c']}</div><div class="lbl">Reiting / ned</div></div>
<div class="card kpi"><div class="num" style="color:#16a34a">{m['avg_r']:.1f}</div><div class="lbl">Sr. otsenka</div></div>
<div class="card kpi"><div class="num status-blue">{(t['ti']+t['to2']):,}</div><div class="lbl">Tokeny / ned</div></div>
<div class="card kpi"><div class="num">{d['c']}</div><div class="lbl">Dialogi / ned</div></div></div>"""

def _build_action_bar(dept, doc_id, existing_notes_html=""):
    """Build action bar HTML + JS for Mini App reports."""
    # #497 A.1: в страницу кладётся токен документа (валиден ТОЛЬКО для
    # этого doc_id, doc_action_token), а НЕ мастер-ключ API_SECRET:
    # старый плейсхолдер '{{API_SECRET}}' после f-строки становился
    # литералом '{API_SECRET}' и на подстановку routes_core не отвечал —
    # все кнопки ловили 401. Мастер-ключ в страницу не подставлять
    # («Поделиться» и история браузера).
    doc_token = doc_action_token(doc_id)
    osp_buttons = ""
    osp_menus = ""
    if dept == "osp":
        osp_buttons = '''
<button class="action-btn primary" onclick="doAction('journalist')"><span class="icon">✏️</span>Журналист</button>
<button class="action-btn" onclick="toggleMenu('depthMenu')"><span class="icon">🔍</span>Погружение</button>
<button class="action-btn" onclick="toggleMenu('controlMenu')"><span class="icon">📌</span>На контроль</button>
<button class="action-btn danger" onclick="doAction('counter_forecast')"><span class="icon">⚡</span>Контр-прогноз</button>'''
        osp_menus = '''
<div class="depth-menu" id="depthMenu">
  <div class="depth-option" onclick="doDepth(1)"><div class="depth-dot" style="background:#8A8A8F"></div><div><b>Быстрая оценка</b><br><span style="font-size:11px;color:#8A8A8F">2-3 слоя</span></div></div>
  <div class="depth-option" onclick="doDepth(2)"><div class="depth-dot" style="background:#7ED957"></div><div><b>Стандартный</b><br><span style="font-size:11px;color:#8A8A8F">5-7 слоёв, ACH</span></div></div>
  <div class="depth-option" onclick="doDepth(3)"><div class="depth-dot" style="background:#F5C93E"></div><div><b>Глубокое</b><br><span style="font-size:11px;color:#8A8A8F">8-10 слоёв, premortem</span></div></div>
  <div class="depth-option" onclick="doDepth(4)"><div class="depth-dot" style="background:#E8262E"></div><div><b>Полное + Red Team</b><br><span style="font-size:11px;color:#8A8A8F">12+ слоёв, контр-анализ</span></div></div>
</div>
<div class="control-menu" id="controlMenu">
  <div class="control-option" onclick="doControl('daily')">📅 Ежедневно</div>
  <div class="control-option" onclick="doControl('weekly')">📆 Еженедельно</div>
  <div class="control-option" onclick="doControl('monthly')">🗓 Ежемесячно</div>
</div>'''

    return f'''
{osp_menus}
<div class="action-bar{' osp-bar' if dept == 'osp' else ''}">
{osp_buttons}
<button class="action-btn" onclick="doAction('archive')"><span class="icon">📥</span>В архив</button>
<button class="action-btn" onclick="copyText()"><span class="icon">📋</span>Копировать</button>
<button class="action-btn" onclick="window.print()"><span class="icon">📄</span>PDF</button>
<button class="action-btn" onclick="shareReport()"><span class="icon">📤</span>Поделиться</button>
</div>
<div class="notes-section">
<div class="notes-title">Важные замечания</div>
<div class="notes-list" id="notesList">{existing_notes_html}</div>
<div class="notes-input">
<input type="text" id="noteInput" placeholder="Добавить замечание..." onkeydown="if(event.key==='Enter')addNote()"/>
<button onclick="addNote()">+</button>
</div>
</div>
<script>
var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
var docId = "{doc_id}";
var _docToken = '{doc_token}';
if(tg) tg.ready();

function copyText(){{
  var body = document.querySelector('.report-body');
  if(body) navigator.clipboard.writeText(body.innerText).then(function(){{ alert('Скопировано') }});
}}
function shareReport(){{
  if(navigator.share) navigator.share({{title:document.title, url:location.href}});
  else if(tg) tg.openTelegramLink('https://t.me/share/url?url='+encodeURIComponent(location.href));
  else alert('Ссылка: '+location.href);
}}
function addNote(){{
  var input=document.getElementById('noteInput');
  var text=input.value.trim();
  if(!text)return;
  var list=document.getElementById('notesList');
  var now=new Date().toLocaleTimeString('ru-RU',{{hour:'2-digit',minute:'2-digit'}});
  list.innerHTML+='<div class="note-item"><span>'+text+'</span><span class="note-time">'+now+'</span></div>';
  input.value='';
  fetch('/miniapp/note',{{method:'POST',headers:{{'Content-Type':'application/json','Authorization':'Bearer '+_docToken}},body:JSON.stringify({{doc_id:docId,note_text:text}})}});
}}
function doAction(action){{
  var btn = event && event.target ? event.target.closest('.action-btn') : null;
  if(btn){{ btn.disabled = true; btn.style.opacity = '0.5'; }}
  fetch('/webhook/miniapp-action',{{method:'POST',headers:{{'Content-Type':'application/json','Authorization':'Bearer '+_docToken}},body:JSON.stringify({{action:action,doc_id:docId}})}})
    .then(function(r){{ return r.json().then(function(data){{ return {{ok:r.status, data:data}}; }}); }})
    .then(function(res){{
      if(btn){{ btn.disabled = false; btn.style.opacity = ''; }}
      if(res.ok !== 200){{ alert('Ошибка: ' + (res.data.msg || res.ok)); return; }}
      // Действия вроде archive/control не создают новый отчёт — просто
      // подтверждение. Journalist/deepen/counter_forecast/crisis_protocol
      // создают новую страницу с реальным текстом — открываем её, а не
      // молчим об уже потраченном вызове модели.
      if(res.data.doc_id){{
        location.href = '/miniapp/' + res.data.doc_id;
      }} else {{
        alert(action + ' выполнен');
      }}
    }})
    .catch(function(){{ if(btn){{ btn.disabled = false; btn.style.opacity = ''; }} alert('Сетевая ошибка'); }});
}}
function toggleMenu(id){{
  var m=document.getElementById(id);
  if(m)m.style.display=m.style.display==='none'?'block':'none';
}}
function doDepth(level){{
  document.getElementById('depthMenu').style.display='none';
  doAction('deepen_to_'+level);
}}
function doControl(freq){{
  document.getElementById('controlMenu').style.display='none';
  doAction('control_'+freq);
}}
</script>'''

ARCHIVE_MONTHS_RU = {
    "01": "Январь", "02": "Февраль", "03": "Март", "04": "Апрель",
    "05": "Май", "06": "Июнь", "07": "Июль", "08": "Август",
    "09": "Сентябрь", "10": "Октябрь", "11": "Ноябрь", "12": "Декабрь",
}

def _browse_page(title, crumbs, items, back_href, tg_suffix=""):
    """Render one level of the archive browser.

    tg_suffix is appended to all internal links so tgWebAppData survives
    navigation inside the Telegram Mini App.
    """
    rows = []
    for it in items:
        e_name = html_lib.escape(str(it.get("name", "")))
        e_sub = html_lib.escape(str(it.get("sub", "")))
        raw_href = str(it.get("href", ""))
        # Append tg_suffix: use ? if no query string yet, & otherwise
        if tg_suffix and "?" not in raw_href:
            full_href = raw_href + "?" + tg_suffix
        else:
            full_href = raw_href + ("&" + tg_suffix if tg_suffix else "")
        e_href = html_lib.escape(full_href, quote=True)
        sub = f'<span class="sub">{e_sub}</span>' if it.get("sub") else ""
        rows.append(
            f'<a class="row" href="{e_href}"><span class="name">{e_name}</span>{sub}</a>'
        )
    body = "".join(rows) or '<div class="empty">Пусто</div>'
    # Append tg_suffix to back link too
    if back_href:
        if tg_suffix and "?" not in back_href:
            back_full = back_href + "?" + tg_suffix
        else:
            back_full = back_href + ("&" + tg_suffix if tg_suffix else "")
        back = f'<a class="back" href="{html_lib.escape(back_full, quote=True)}">← Назад</a>'
    else:
        back = ""
    e_title = html_lib.escape(str(title))
    e_crumbs = html_lib.escape(str(crumbs))
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e_title}</title>
<style>
:root{{--ink:#1C1B18;--paper:#EFEAE0;--paper-raised:#FBF8F2;--line:rgba(28,27,24,.14);--stamp:#A8321E;--muted:#6B6558;--b:'IBM Plex Sans',system-ui,sans-serif}}
body{{margin:0;padding:16px;font-family:var(--b);
background:var(--paper);color:var(--ink)}}
h1{{font-size:18px;margin:0 0 4px;font-family:var(--b);font-weight:600}}
.crumbs{{font-size:13px;color:var(--muted);margin-bottom:16px}}
.row{{display:flex;justify-content:space-between;align-items:center;gap:12px;
padding:14px 12px;margin-bottom:8px;background:var(--paper-raised);border:1px solid var(--line);border-radius:10px;
text-decoration:none;color:var(--ink)}}
.row:active{{background:var(--paper)}}
.name{{font-size:15px;overflow:hidden;text-overflow:ellipsis}}
.sub{{font-size:13px;color:var(--muted);white-space:nowrap}}
.empty{{color:var(--muted);padding:20px 0}}
.back{{display:inline-block;margin-bottom:14px;color:var(--stamp);text-decoration:none;font-size:14px}}
</style></head><body>
{back}<h1>{e_title}</h1><div class="crumbs">{e_crumbs}</div>{body}
</body></html>"""

def _evidence_badges_css():
    """CSS бейджей доказательности (verified/unverified) — токены «Диспетчерской» (FO-045)."""
    return """
:root{--ink:#1C1B18;--paper:#EFEAE0;--paper-raised:#FBF8F2;--line:rgba(28,27,24,.14);--stamp:#A8321E;--stamp-soft:rgba(168,50,30,.10);--muted:#6B6558;--ok:#3D6B2C;--warn:#9C6B0B;--bad:#A8321E;--m:'IBM Plex Mono',ui-monospace,monospace;--ok-soft:rgba(61,107,44,.12);--warn-soft:rgba(156,107,11,.12);--bad-soft:rgba(168,50,30,.10)}
.badge-verified{background:var(--ok-soft);color:var(--ok);border:1px solid var(--ok);border-radius:4px;font-family:var(--m);font-size:0.7rem;padding:2px 8px;display:inline-block}
.badge-unverified{background:var(--warn-soft);color:var(--warn);border:1px solid var(--warn);border-radius:4px;font-family:var(--m);font-size:0.7rem;padding:2px 8px;display:inline-block}
.badge-conflicting{background:var(--bad-soft);color:var(--bad);border:1px solid var(--bad);border-radius:4px;font-family:var(--m);font-size:0.7rem;padding:2px 8px;display:inline-block}
.evidence-section{margin:24px 0;padding:20px;background:var(--paper-raised);border:1px solid var(--line);border-radius:12px}
.evidence-stats{display:flex;gap:16px;margin:12px 0}
.ev-stat{text-align:center}
.ev-num{display:block;font-size:24px;font-weight:700;font-family:var(--m);color:var(--ok)}
.ev-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
.ev-item{padding:8px 12px;border-bottom:1px solid var(--line);display:flex;gap:8px;align-items:center;font-size:13px}
.ev-item.verified{border-left:3px solid var(--ok)}
.ev-item.unverified{border-left:3px solid var(--warn)}
.ev-item.conflicting{border-left:3px solid var(--bad)}
.ev-id{font-family:var(--m);color:var(--muted);font-size:0.8rem}
.ev-source{flex:1}
.ev-status{font-size:11px;font-weight:600}
"""
