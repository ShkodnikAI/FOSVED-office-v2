"""dept_dashboard.py — Fosved Office v2 Department & Office Dashboard HTML Generator.

Provides self-contained HTML renderers for department dashboards,
the office overview panel, and miniapp document pages.
Imported by llm_proxy.py; all functions accept an sqlite3.Connection.
"""

from datetime import datetime, timedelta

# ──────────────────────────── DESIGN TOKENS ────────────────────────────

DEPT_COLORS = {
    'yana': {'start': '#293133', 'end': '#1a2024', 'accent': '#3d4a4d'},
    'osp': {'start': '#b91c1c', 'end': '#7f1d1d', 'accent': '#dc2626'},
    'lz': {'start': '#0e7490', 'end': '#164e63', 'accent': '#0891b2'},
    'expert': {'start': '#3730a3', 'end': '#1e1b4b', 'accent': '#4f46e5'},
    'marketing': {'start': '#c2410c', 'end': '#7c2d12', 'accent': '#ea580c'},
    'finance': {'start': '#15803d', 'end': '#14532d', 'accent': '#16a34a'},
    'legal': {'start': '#475569', 'end': '#1e293b', 'accent': '#64748b'},
    'dev': {'start': '#1d4ed8', 'end': '#1e3a8a', 'accent': '#2563eb'},
    'design': {'start': '#be185d', 'end': '#831843', 'accent': '#ec4899'},
    'qa': {'start': '#4d7c0f', 'end': '#365314', 'accent': '#65a30d'},
    'visual': {'start': '#7e22ce', 'end': '#581c87', 'accent': '#a855f7'},
    'engineering': {'start': '#44403c', 'end': '#292524', 'accent': '#78716c'},
    'kavalnya': {'start': '#b45309', 'end': '#78350f', 'accent': '#d97706'},
    'admin': {'start': '#1e40af', 'end': '#1e3a5f', 'accent': '#3b82f6'},
}

DEPT_NAMES = {
    'yana': 'Яна — Шеф де кабинет', 'osp': 'ОСП — Стратегический анализ',
    'lz': 'ЛЗ — Лаборатория знаний', 'expert': 'Эксперт — Технический препаратор',
    'marketing': 'Маркетинг', 'finance': 'Финансы', 'legal': 'Юрист',
    'dev': 'Dev — Разработка', 'design': 'Design — UI/UX', 'qa': 'QA — Тестирование',
    'visual': 'Visual — Визуализация', 'engineering': 'Engineering — Инженерный',
    'kavalnya': 'Кавальня — Методология', 'admin': 'Админ — Системный агент',
}

# ──────────────────────────── CSS FRAGMENTS ────────────────────────────

_FONTS = ("https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700"
          "&family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap")

_DEPT_CSS = """\
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',system-ui,sans-serif;background:#F8F7F4;color:#1a1a1a;min-height:100vh}
.wrap{max-width:640px;margin:0 auto;padding:16px}
h1,h2,h3{font-family:'Cormorant Garamond',serif;font-weight:700}
.mono{font-family:'DM Mono',monospace}
.badge{font-family:'DM Mono',monospace;font-size:.7rem;padding:2px 8px;border-radius:4px;
  display:inline-block;background:#0008;color:#555}
.card{background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 4px #0000000a}
.kpi{text-align:center;padding:16px}
.kpi .num{font-size:2rem;font-weight:700;font-family:'DM Mono',monospace}
.kpi .lbl{font-size:.72rem;color:#888;margin-top:4px;text-transform:uppercase;letter-spacing:1px}
.grid{display:grid;gap:14px}.grid-3{grid-template-columns:repeat(3,1fr)}
.grid-2{grid-template-columns:repeat(2,1fr)}
table{width:100%;border-collapse:collapse;margin:10px 0}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #eee;font-size:.84rem}
th{color:#999;font-weight:500;text-transform:uppercase;font-size:.68rem;letter-spacing:1px}
.header-grad{padding:28px 32px;border-radius:14px;color:#fff;margin-bottom:20px}
.section{margin-top:22px}.section h2{margin-bottom:12px;font-size:1.3rem;color:#333}
.btn{display:inline-block;padding:8px 18px;border-radius:8px;font-size:.82rem;font-weight:600;
  cursor:pointer;border:none;transition:opacity .15s}
.btn:hover{opacity:.85}
.status-dot{width:8px;height:8px;border-radius:50%;display:inline-block}
@media(max-width:480px){.grid-3{grid-template-columns:1fr}.wrap{padding:10px}}"""

_OFFICE_CSS = """\
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',system-ui,sans-serif;background:#0F0F0F;color:#F8F7F4;min-height:100vh}
.wrap{max-width:1200px;margin:0 auto;padding:20px 24px}
h1,h2,h3{font-family:'Cormorant Garamond',serif;font-weight:700}
.mono{font-family:'DM Mono',monospace}
.card{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:12px;padding:20px}
.kpi{text-align:center;padding:16px}
.kpi .num{font-size:2rem;font-weight:700;font-family:'DM Mono',monospace}
.kpi .lbl{font-size:.72rem;color:#999;margin-top:4px;text-transform:uppercase;letter-spacing:1px}
.grid{display:grid;gap:16px}
.grid-4{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}
.grid-3{grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
table{width:100%;border-collapse:collapse;margin:12px 0}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid #2a2a2a;font-size:.85rem}
th{color:#999;font-weight:500;text-transform:uppercase;font-size:.7rem;letter-spacing:1px}
.header-grad{padding:32px 40px;border-radius:16px;color:#fff;margin-bottom:24px}
.section{margin-top:24px}.section h2{margin-bottom:14px;font-size:1.4rem}
.gold{color:#C9A84C}a{color:#C9A84C;text-decoration:none}a:hover{text-decoration:underline}
.status-dot{width:8px;height:8px;border-radius:50%;display:inline-block;vertical-align:middle}
@media(max-width:768px){.grid-4,.grid-3{grid-template-columns:1fr}}"""

# ──────────────────────────── HELPERS ────────────────────────────

def _q(db, sql, params=()):
    """Shorthand for fetchall on the passed connection."""
    try:
        return db.execute(sql, params).fetchall()
    except Exception:
        return []

def _row(db, sql, params=()):
    """Shorthand for fetchone returning a dict-like Row or empty dict."""
    try:
        r = db.execute(sql, params).fetchone()
        return dict(r) if r else {}
    except Exception:
        return {}

def _status_color(calls):
    if calls > 10:
        return '#639922'
    if calls > 0:
        return '#EF9F27'
    return '#E24B4A'

def _esc(s):
    """Minimal HTML escape."""
    if not s:
        return ''
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

# ──────────────────────────── DEPT DASHBOARD ────────────────────────────

def generate_dept_dashboard(db, slug):
    """Return a complete HTML string for a single-department dashboard page."""
    slug = slug.lower()
    if slug not in DEPT_NAMES:
        return '<h1>404 — Department not found</h1>', 404
    c = DEPT_COLORS[slug]
    name = DEPT_NAMES[slug]
    now = datetime.utcnow()
    week_ago = (now - timedelta(days=7)).isoformat()

    # ── data queries ──
    corr = _q(db, "SELECT original,corrected,created FROM adapt_corrections WHERE dept=? ORDER BY id DESC LIMIT 8",
              (slug,))
    dialogs = _q(db, "SELECT role,content,created FROM dialog_history WHERE dept=? ORDER BY id DESC LIMIT 5",
                 (slug,))
    metrics = _row(db, "SELECT COUNT(*) as cnt, COALESCE(AVG(rating),0) as avg_r FROM dept_metrics WHERE dept=? AND created>=?",
                   (slug, week_ago))
    tasks = metrics.get('cnt', 0)
    rating = metrics.get('avg_r', 0)
    corrs_count = len(_q(db, "SELECT id FROM adapt_corrections WHERE dept=? AND created>=?", (slug, week_ago)))

    # model from config (caller should pass via closure or we read file)
    model_label = slug  # placeholder — caller can override in route

    # ── build html ──
    h = (f'<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">'
         f'<meta name="viewport" content="width=device-width,initial-scale=1">'
         f'<link href="{_FONTS}" rel="stylesheet">'
         f'<title>{_esc(name)} — Dashboard</title><style>{_DEPT_CSS}</style></head><body>'
         f'<div class="wrap">')

    # header
    h += (f'<div class="header-grad" style="background:linear-gradient(135deg,{c["start"]},{c["end"]})">'
          f'<h1>{_esc(name)}</h1>'
          f'<p style="color:{c["accent"]};font-size:.88rem;margin-top:6px;font-family:\'DM Mono\',monospace">'
          f'Model: {model_label}</p></div>')

    # kpi cards
    h += (f'<div class="grid grid-3">'
          f'<div class="card kpi"><div class="num" style="color:{c["accent"]}">{tasks}</div><div class="lbl">Tasks / week</div></div>'
          f'<div class="card kpi"><div class="num" style="color:#639922">{rating:.1f}</div><div class="lbl">Satisfaction</div></div>'
          f'<div class="card kpi"><div class="num" style="color:#E24B4A">{corrs_count}</div><div class="lbl">Corrections</div></div></div>')

    # recent corrections
    h += '<div class="section"><h2>Recent Corrections</h2>'
    if corr:
        h += '<table><tr><th>Original</th><th>Corrected</th><th>Date</th></tr>'
        for r in corr:
            h += (f'<tr><td>{_esc(r[0][:80])}</td><td>{_esc(r[1][:80])}</td>'
                  f'<td class="mono" style="font-size:.78rem;color:#aaa">{_esc(str(r[2])[:16])}</td></tr>')
        h += '</table>'
    else:
        h += '<p style="color:#aaa;font-size:.88rem">No corrections recorded.</p>'
    h += '</div>'

    # recent dialog samples
    h += '<div class="section"><h2>Recent Dialogs</h2>'
    if dialogs:
        for r in reversed(dialogs):
            role_style = 'font-weight:600;color:{0}'.format(c['accent'] if r[0] == 'user' else '#888')
            h += (f'<div class="card" style="margin-bottom:10px;padding:14px 18px">'
                  f'<span class="badge" style="{role_style}">{_esc(r[0])}</span> '
                  f'<span class="mono" style="float:right;font-size:.7rem;color:#bbb">{_esc(str(r[2])[:16])}</span>'
                  f'<p style="margin-top:8px;font-size:.88rem;line-height:1.5">{_esc(r[1][:200])}</p></div>')
    else:
        h += '<p style="color:#aaa;font-size:.88rem">No dialog history.</p>'
    h += '</div>'

    # quick actions
    h += (f'<div class="section"><h2>Quick Actions</h2><div style="display:flex;flex-wrap:wrap;gap:10px">'
          f'<button class="btn" style="background:{c["accent"]};color:#fff" onclick="alert(\'Reset context — NYI\')">Reset Context</button>'
          f'<button class="btn" style="background:#eee;color:#333" onclick="alert(\'Export — NYI\')">Export Data</button>'
          f'<button class="btn" style="background:#eee;color:#333" onclick="alert(\'Config — NYI\')">Config</button>'
          f'</div></div>')

    h += '</div></body></html>'
    return h, 200

# ──────────────────────────── OFFICE DASHBOARD ────────────────────────────

def generate_office_dashboard(db):
    """Return a complete HTML string for the office overview panel."""
    now = datetime.utcnow()
    today = now.isoformat()[:10]
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    # overview kpis
    r_dialogs_today = _row(db, "SELECT COUNT(*) as c FROM dialog_history WHERE created>=?", (today,))
    r_tokens_week = _row(db, "SELECT COALESCE(SUM(tokens_in),0)+COALESCE(SUM(tokens_out),0) as t FROM token_usage WHERE created>=?", (week_ago,))
    r_avg_rating = _row(db, "SELECT COALESCE(AVG(rating),0) as a FROM dept_metrics WHERE created>=?", (week_ago,))
    r_cost_month = _row(db, "SELECT COALESCE(SUM(cost),0) as t FROM token_usage WHERE created>=?", (month_ago,))
    d_today = r_dialogs_today.get('c', 0)
    t_week = r_tokens_week.get('t', 0)
    a_rating = r_avg_rating.get('a', 0)
    cost = r_cost_month.get('t', 0)

    h = (f'<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">'
         f'<meta name="viewport" content="width=device-width,initial-scale=1">'
         f'<link href="{_FONTS}" rel="stylesheet">'
         f'<title>Fosved Office v2</title><style>{_OFFICE_CSS}</style></head><body>'
         f'<div class="wrap">')

    # header
    h += (f'<div class="header-grad" style="background:linear-gradient(135deg,#1a1a2e,#16213e)">'
          f'<h1>Fosved Office v2</h1>'
          f'<p class="gold" style="margin-top:8px;font-size:.9rem">{_esc(today)} &nbsp;|&nbsp; '
          f'Average Rating: {a_rating:.1f}/5</p></div>')

    # overview kpis
    h += (f'<div class="grid grid-4">'
          f'<div class="card kpi"><div class="num gold">{d_today}</div><div class="lbl">Dialogues Today</div></div>'
          f'<div class="card kpi"><div class="num" style="color:#185FA5">{t_week:,}</div><div class="lbl">Weekly Tokens</div></div>'
          f'<div class="card kpi"><div class="num" style="color:#639922">{a_rating:.1f}</div><div class="lbl">Avg Rating</div></div>'
          f'<div class="card kpi"><div class="num" style="color:#EF9F27">${cost:.2f}</div><div class="lbl">Budget / Month</div></div></div>')

    # department cards
    h += '<div class="section"><h2>Departments</h2><div class="grid grid-3">'
    for slug, name in DEPT_NAMES.items():
        dc = DEPT_COLORS[slug]
        r_calls = _row(db, "SELECT COUNT(*) as c FROM token_usage WHERE dept=? AND created>=?", (slug, week_ago))
        r_rate = _row(db, "SELECT COALESCE(AVG(rating),0) as a FROM dept_metrics WHERE dept=? AND created>=?", (slug, week_ago))
        calls = r_calls.get('c', 0)
        rate = r_rate.get('a', 0)
        dot_c = _status_color(calls)
        h += (f'<div class="card" style="border-left:4px solid {dc["accent"]}">'
              f'<div style="display:flex;align-items:center;gap:8px">'
              f'<span class="status-dot" style="background:{dot_c}"></span>'
              f'<h3 style="font-size:.95rem">{_esc(name)}</h3></div>'
              f'<p class="mono" style="margin-top:10px;font-size:.8rem;color:#999">'
              f'Calls: {calls} &nbsp;|&nbsp; Rating: {rate:.1f}/5</p>'
              f'<a href="/dept-dashboard/{slug}" style="font-size:.75rem;display:inline-block;margin-top:8px">Open →</a></div>')
    h += '</div></div>'

    # provider costs
    provs = _q(db, "SELECT provider,COUNT(*) as c,COALESCE(SUM(cost),0) as cost FROM token_usage WHERE created>=? GROUP BY provider", (month_ago,))
    h += '<div class="section"><h2>Provider Costs (30d)</h2><table><tr><th>Provider</th><th>Calls</th><th>Cost</th></tr>'
    for r in provs:
        h += f'<tr><td class="mono gold">{_esc(r[0])}</td><td>{r[1]}</td><td class="mono">${r[2]:.2f}</td></tr>'
    if not provs:
        h += '<tr><td colspan="3" style="color:#666">No usage data</td></tr>'
    h += '</table></div>'

    # audit log
    audits = _q(db, "SELECT action,details,created FROM audit_log ORDER BY id DESC LIMIT 10")
    h += '<div class="section"><h2>Audit Log</h2><table><tr><th>Action</th><th>Details</th><th>Time</th></tr>'
    for r in audits:
        det = _esc(str(r[1])[:100]) if r[1] else ''
        h += (f'<tr><td class="mono">{_esc(r[0])}</td>'
              f'<td style="color:#999;font-size:.8rem">{det}</td>'
              f'<td class="mono" style="font-size:.8rem">{_esc(str(r[2])[:19])}</td></tr>')
    if not audits:
        h += '<tr><td colspan="3" style="color:#666">No audit entries</td></tr>'
    h += '</table></div>'

    h += '</div></body></html>'
    return h, 200

# ──────────────────────────── MINIAPP ────────────────────────────

def generate_miniapp_html(db, doc_id):
    """Return HTML from miniapp_responses table, or a 404 page."""
    row = _row(db, "SELECT html,title,created FROM miniapp_responses WHERE id=?", (doc_id,))
    if not row:
        return ('<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>404</title><style>body{font-family:system-ui;display:flex;'
                'align-items:center;justify-content:center;min-height:100vh;background:#F8F7F4;color:#333}'
                '.box{text-align:center;padding:40px}h1{font-size:3rem;color:#ccc}'
                'p{color:#999;margin-top:8px}a{color:#C9A84C}</style></head>'
                '<body><div class="box"><h1>404</h1>'
                f'<p>Document <span class="mono">{_esc(doc_id)}</span> not found.</p>'
                '<a href="/office-dashboard">← Office</a></div></body></html>'), 404
    html = row.get('html', '')
    return html, 200