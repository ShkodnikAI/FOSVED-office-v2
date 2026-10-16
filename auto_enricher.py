"""
Auto-enricher: превращает plain markdown от LLM в rich HTML.
Не зависит от модели — работает с любым текстом.
Если LLM уже использовал маркеры — пропускает дубликаты.
"""

import re
import html as html_lib


# ═══════════════════════════════════════════
# STEP 1: МЕТРИКИ — числа, проценты, валюты
# ═══════════════════════════════════════════

def extract_metrics(text):
    """
    Ищет паттерны: "$300B+", "40%", "3.3 трлн руб", "+12% г/г"
    Возвращает список {label, value, color}
    """
    metrics = []
    seen = set()

    patterns = [
        # "Дефицит: 3.3 трлн руб"
        r'([А-ЯЁа-яёA-Za-z\s]{3,35}?)[\s:—–\-]+?([\$€₽]?\s*\d[\d.,]*\s*(?:трлн|млрд|млн|тыс|%|руб|долл|\$|€|₽|B\+?|M\+?)[А-Яа-яA-Za-z.]*)',
        # "+12% г/г"
        r'([А-ЯЁа-яёA-Za-z\s]{3,30}?)[\s:—–\-]+?([+-]?\d[\d.,]*\s*%[^.\n]{0,15})',
        # "~$300B+"
        r'([А-ЯЁа-яёA-Za-z\s]{3,30}?)[\s:—–\-]+?(~?\$\d[\d.,]*\s*[BMKТтрлнмлд+]+)',
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text, re.MULTILINE):
            label = match.group(1).strip().lstrip('*•-– ')
            value = match.group(2).strip()
            if len(label) < 3 or len(label) > 40:
                continue
            if label.lower() in seen:
                continue
            seen.add(label.lower())

            # Цвет по контексту
            context = (label + ' ' + value).lower()
            if any(w in context for w in ['дефицит', 'убыт', 'потер', 'снижен', 'упал', 'минус', '-']):
                color = '#A8321E'  # --bad/stamp
            elif any(w in context for w in ['рост', 'прибыл', 'увелич', 'плюс', '+']):
                color = '#3D6B2C'  # --ok
            elif any(w in context for w in ['прогноз', 'ожид', 'план', 'оценк']):
                color = '#9C6B0B'  # --warn
            elif any(w in context for w in ['долг', 'расход', 'затрат', 'стоимост']):
                color = '#9C6B0B'  # --warn (расход/стоимость)
            else:
                color = '#6B6558'  # --muted (по умолчанию)

            metrics.append({'label': label, 'value': value, 'color': color})
            if len(metrics) >= 6:
                break
        if len(metrics) >= 6:
            break

    return metrics


def render_metrics_html(metrics):
    """Рендерит grid метрик-карточек"""
    if len(metrics) < 2:
        return ''

    cards = ''
    for m in metrics:
        cards += f'''<div class="metric-card">
  <div class="metric-value" style="color:{m['color']}">{html_lib.escape(m['value'])}</div>
  <div class="metric-label">{html_lib.escape(m['label'])}</div>
</div>\n'''

    # #512: авто-колонки вместо жёсткого repeat(N,1fr) — inline-грид с min-content
    # шире вьюпорта выталкивал страницу за габариты в Telegram (репродукция:
    # doc.scrollWidth=438 при 320–390px). auto-fit minmax сжимается до 1 колонки.
    return f'<div class="metrics-grid">{cards}</div>\n'


# ═══════════════════════════════════════════
# STEP 2: КАРТОЧКИ из bullet-списков
# ═══════════════════════════════════════════

# Была ротация из 8 разных цветов — та же декоративная радуга, теперь
# один акцент «Диспетчерской», как и везде в этом файле.
CARD_COLORS = ['#A8321E']

def convert_bullet_to_cards(text):
    """
    Находит списки:
      * **Заголовок:** текст
      * Заголовок: текст
    Превращает в цветные card-блоки
    """
    def replace_group(match):
        block = match.group(0).strip()
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 2:
            return block

        cards_html = ''
        for i, line in enumerate(lines):
            clean = re.sub(r'^[*•\-]\s+', '', line)

            # **Bold:** text
            bold = re.match(r'\*\*(.+?)\*\*[:\s]+(.+)', clean)
            # Plain: text
            plain = re.match(r'([А-ЯA-Z][^:]{3,40}):\s*(.+)', clean)

            if bold:
                title, body = bold.group(1), bold.group(2)
            elif plain:
                title, body = plain.group(1), plain.group(2)
            else:
                cards_html += f'<p>{clean}</p>\n'
                continue

            color = CARD_COLORS[i % len(CARD_COLORS)]
            cards_html += f'''<div class="info-card" style="border-left:4px solid {color}">
  <div class="info-card-title" style="color:{color}">{title}</div>
  <div class="info-card-body">{body}</div>
</div>\n'''

        return cards_html

    # Группы из 2+ bullet items
    pattern = r'(?:^[*•\-]\s+.{10,}$\n?){2,}'
    return re.sub(pattern, replace_group, text, flags=re.MULTILINE)


# ═══════════════════════════════════════════
# STEP 3: СРАВНЕНИЯ (vs, нарратив/реальность)
# ═══════════════════════════════════════════

def detect_comparison(text):
    """
    Находит паттерны: "Нарратив: ... Реальность: ..."
    Или: "Плюсы: ... Минусы: ..."
    Превращает в side-by-side блоки
    """
    pairs = [
        (r'[Нн]арратив', r'[Рр]еальность', '✗ Нарратив', '✓ Реальность', 'rgba(168,50,30,.10)', 'rgba(61,107,44,.12)'),  # --bad-soft, --ok-soft
        (r'[Пп]люс[ыы]', r'[Мм]инус[ыы]', '✓ Плюсы', '✗ Минусы', 'rgba(61,107,44,.12)', 'rgba(168,50,30,.10)'),  # --ok-soft, --bad-soft
        (r'[Зз]а\b', r'[Пп]ротив', '✓ За', '✗ Против', 'rgba(61,107,44,.12)', 'rgba(168,50,30,.10)'),  # --ok-soft, --bad-soft
        (r'[Пп]олучи[лт]', r'[Пп]отеря[лт]', 'Получили', 'Потеряли', 'rgba(61,107,44,.12)', 'rgba(168,50,30,.10)'),  # --ok-soft, --bad-soft
    ]

    result = text
    for p_left, p_right, title_left, title_right, bg_left, bg_right in pairs:
        pattern = rf'[*•\-]?\s*\*?\*?{p_left}\*?\*?[:\s]+(.{{10,200}}?)[\n\r]+[*•\-]?\s*\*?\*?{p_right}\*?\*?[:\s]+(.{{10,200}}?)(?:\n|$)'
        match = re.search(pattern, result, re.DOTALL)
        if match:
            left_text = match.group(1).strip()
            right_text = match.group(2).strip()
            compare_html = f'''<div class="compare-grid">
  <div class="compare-box rich" style="background:{bg_left};border:1px solid #3D6B2C">
    <div class="compare-title">{title_left}</div>
    <div class="compare-body">{left_text}</div>
  </div>
  <div class="compare-box rich" style="background:{bg_right};border:1px solid #A8321E">
    <div class="compare-title">{title_right}</div>
    <div class="compare-body">{right_text}</div>
  </div>
</div>\n'''
            result = result[:match.start()] + compare_html + result[match.end():]

    return result


# ═══════════════════════════════════════════
# STEP 4: БЕЙДЖИ
# ═══════════════════════════════════════════

def format_badges(text):
    """Заменяет текстовые маркеры на HTML-бейджи"""
    replacements = [
        # Русские
        ('[ФАКТ]',           '<span class="badge badge-fact">✓ ФАКТ</span>'),
        ('[ИНТЕРПРЕТАЦИЯ]',  '<span class="badge badge-interp">◆ АНАЛИЗ</span>'),
        ('[СПЕКУЛЯЦИЯ]',     '<span class="badge badge-spec">⚡ ГИПОТЕЗА</span>'),
        # Standalone icons REMOVED — they caused double badges when LLM
        # already used [ФАКТ]/[ИНТЕРПРЕТАЦИЯ]/[СПЕКУЛЯЦИЯ] markers.
        # Английские
        ('[FACT]',           '<span class="badge badge-fact">✓ ФАКТ</span>'),
        ('[INTERPRETATION]', '<span class="badge badge-interp">◆ АНАЛИЗ</span>'),
        ('[SPECULATION]',    '<span class="badge badge-spec">⚡ ГИПОТЕЗА</span>'),
        # Verified (Apodex)
        ('[ФАКТ ✓verified]', '<span class="badge badge-verified">✓ ВЕРИФИЦИРОВАНО</span>'),
        ('[ФАКТ ⚠unverified]','<span class="badge badge-unverified">⚠ НЕ ПРОВЕРЕНО</span>'),
    ]
    result = text
    for old, new in replacements:
        result = result.replace(old, new)
    return result


# ═══════════════════════════════════════════
# STEP 5: СЕКЦИИ (## Заголовок → accent border)
# ═══════════════════════════════════════════

def format_sections(text, accent_color):
    """## Слой N — Название → стилизованная секция"""
    def replace_h2(match):
        title = match.group(1).strip()
        return f'<h2 class="section-title" style="border-bottom:2px solid {accent_color}">{title}</h2>'

    def replace_h3(match):
        title = match.group(1).strip()
        return f'<h3 class="subsection-title">{title}</h3>'

    result = re.sub(r'^##\s+(.+)$', replace_h2, text, flags=re.MULTILINE)
    result = re.sub(r'^###\s+(.+)$', replace_h3, result, flags=re.MULTILINE)
    return result


# ═══════════════════════════════════════════
# STEP 6: ВЕРДИКТ (последний значимый абзац)
# ═══════════════════════════════════════════

def format_paragraphs(text):
    """Оборачивает текст в <p> теги. Assumes text is already escaped."""
    paragraphs = text.strip().split('\n\n')
    return '\n'.join(f'<p>{p.strip()}</p>' for p in paragraphs if p.strip())


def wrap_verdict(text):
    """Блок «Вердикт» — только при непустом содержимом (#468 A.3).

    Раздел отчётов ОСП может называться «Вердикт»/«Verdict»/«Итог»/
    «Confidence» (наряд #468: regex обязан находить реальный вердикт
    отчётов ОСП). Заголовок — строка, начинающаяся с метки (опционально
    markdown-заголовок или **bold**), затем двоеточие или конец строки.
    Содержимое — строки непосредственно после заголовка ДО пустой строки,
    следующего заголовка или разделителя «---»: старый regex
    `((?:.+\\n?)+)` глотал всё до конца документа и тянул в «Вердикт»
    чужие секции, а при пустом содержимом рисовал блок с пустым телом.
    """
    head_re = re.compile(
        r'^(?:#{1,4}\s*)?(?:\*\*)?\s*'
        r'(?:Вердикт|Verdict|Итоговый вердикт|Итог|Confidence)'
        r'(?:\*\*)?\s*(?::|$)',
        re.IGNORECASE,
    )
    lines = text.split('\n')
    for idx, line in enumerate(lines):
        m = head_re.match(line.strip())
        if not m:
            continue
        # содержимое может быть в той же строке после двоеточия:
        # «Verdict: keep rates unchanged.» / «**Confidence:** medium»
        tail = line.strip()[m.end():].replace('**', '').strip()
        body_lines = [tail] if tail else []
        j = idx + 1
        while j < len(lines):
            s = lines[j].strip()
            if not s or s == '---' or s.startswith('#') or head_re.match(s):
                break
            body_lines.append(s)
            j += 1
        verdict_text = ' '.join(body_lines).strip()
        # Заголовок без содержимого (или заглушка-тире) — блока нет (#468)
        if not verdict_text or verdict_text in ('—', '-', '–'):
            continue
        verdict_html = f'''<div class="verdict-block">
  <div class="verdict-title">Вердикт</div>
  <div class="verdict-body">{format_paragraphs(verdict_text)}</div>
</div>'''
        return '\n'.join(lines[:idx]).rstrip('\n') + ('\n\n' if idx > 0 else '') + verdict_html + '\n' + '\n'.join(lines[j:])

    # Иначе — последний абзац
    paragraphs = text.strip().split('\n\n')
    if len(paragraphs) < 2:
        return text

    last = paragraphs[-1].strip()
    if len(last) > 50 and not last.startswith('<') and not last.startswith('#'):
        verdict_html = f'''<div class="verdict-block">
  <div class="verdict-title">Вердикт</div>
  <div class="verdict-body">{format_paragraphs(last)}</div>
</div>'''
        return '\n\n'.join(paragraphs[:-1]) + '\n\n' + verdict_html

    return text


# ═══════════════════════════════════════════
# STEP 7: ACH ТАБЛИЦА (если есть)
# ═══════════════════════════════════════════

def format_ach_table(text, accent_color):
    """Находит таблицу гипотез и стилизует"""
    pattern = r'\|[^|]*[Гг]ипотез[^|]*\|.+?\n\|[\s\-:|]+\n((?:\|.+\n)+)'
    match = re.search(pattern, text)
    if not match:
        return text

    table_text = match.group(0)
    rows = [r.strip() for r in table_text.strip().split('\n') if r.strip() and not re.match(r'^\|[\s\-:|]+\|$', r)]

    if len(rows) < 2:
        return text

    # Header
    headers = [c.strip() for c in rows[0].split('|') if c.strip()]
    html_rows = '<tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr>\n'

    # Data rows
    for row in rows[1:]:
        cells = [c.strip() for c in row.split('|') if c.strip()]
        html_cells = ''
        for i, cell in enumerate(cells):
            if i == len(cells) - 1 and re.match(r'\d+%', cell):
                html_cells += f'<td class="ach-prob" style="color:{accent_color}">{cell}</td>'
            else:
                html_cells += f'<td>{cell}</td>'
        html_rows += f'<tr>{html_cells}</tr>\n'

    table_html = f'<table class="ach-table">{html_rows}</table>'
    return text[:match.start()] + table_html + text[match.end():]


# ═══════════════════════════════════════════
# STEP 8: ИНДИКАТОРЫ НАБЛЮДЕНИЯ
# ═══════════════════════════════════════════

def format_indicators(text, accent_color):
    """Секция "Индикаторы для наблюдения" → grid карточек"""
    pattern = r'(?:##?\s*)?[Ии]ндикатор[ыи]\s+(?:для\s+)?наблюдени[яе][:\s]*\n((?:[*•\-]\s+.+\n?)+)'
    match = re.search(pattern, text)
    if not match:
        return text

    items_text = match.group(1)
    items = re.findall(r'[*•\-]\s+(.+)', items_text)
    if not items:
        return text

    cards = ''
    for item in items[:4]:
        cards += f'''<div class="indicator-card">
  <div class="indicator-body">{item.strip()}</div>
</div>\n'''

    grid_html = f'<div class="indicators-grid">{cards}</div>'
    h2 = f'<h2 class="section-title" style="border-bottom:2px solid {accent_color}">Индикаторы для наблюдения</h2>\n'
    return text[:match.start()] + h2 + grid_html + text[match.end():]


# ═══════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════

def format_tables(text, accent_color):
    """Конвертирует markdown pipe-таблицы в HTML <table>.
    Ищет блоки вида:
      | Header1 | Header2 |
      |---------|---------|
      | Cell1   | Cell2   |
    Пропускает таблицы гипотез (format_ach_table уже обработает).
    """
    # Match markdown table blocks: header + separator + 1+ data rows
    pattern = re.compile(
        r'(^|\n)'                        # start of line or newline before table
        r'(\|.+\|)\n'                    # header row
        r'(\|[\s\-:|]+\|)\n'             # separator row (|---|---|)
        r'((?:\|.+\|\n?)*)'              # 1+ data rows
    )

    def _replace_table(m):
        prefix = m.group(1)  # preserve leading newline

        header_line = m.group(2).strip()
        data_lines = m.group(4).strip().split('\n') if m.group(4).strip() else []

        # Skip if no data rows
        if not data_lines:
            return m.group(0)

        headers = [c.strip() for c in header_line.split('|') if c.strip()]

        html = '<div class="table-wrap"><table class="rich-table">'
        # Header
        html += '<thead><tr>'
        for h in headers:
            html += f'<th>{h}</th>'
        html += '</tr></thead>'
        # Body
        html += '<tbody>'
        for row_line in data_lines:
            row_line = row_line.strip()
            if not row_line or re.match(r'^\|[\s\-:|]+\|$', row_line):
                continue
            cells = [c.strip() for c in row_line.split('|') if c.strip()]
            html += '<tr>'
            for cell in cells:
                html += f'<td>{cell}</td>'
            html += '</tr>'
        html += '</tbody></table></div>'

        return prefix + html

    # Run once — handles all tables in the text
    result = pattern.sub(_replace_table, text)

    # Clean up any remaining stray pipe rows that weren't part of a full table
    # (orphan separator lines)
    result = re.sub(r'\n\|[\s\-:|]+\|\n', '\n', result)

    return result


def markdown_to_html(text):
    """Базовая конвертация markdown → HTML"""
    result = text
    # Заголовки — построчно, ДО разбивки на параграфы (иначе <h*> попадёт
    # внутрь <p>, невалидная вложенность). MULTILINE, с якорем на начало
    # строки — иначе '#' внутри обычного текста (хэштеги, число #0) тоже
    # попадёт под замену.
    #
    # ## и ### уже обрабатывает format_sections() (STEP 5, выше по
    # конвейеру auto_enrich, строка ~507) — со своей стилизацией под
    # accent_color отдела. Дублировать здесь нельзя: получится либо
    # двойная обработка, либо (как было при первой попытке фикса)
    # рассинхрон — эта функция ищет чистый '##', а он к этому моменту
    # уже стал '<h2 class="section-title"...>', регулярка не совпадает.
    result = re.sub(r'^###### (.+)$', r'<h6>\1</h6>', result, flags=re.MULTILINE)
    result = re.sub(r'^##### (.+)$', r'<h5>\1</h5>', result, flags=re.MULTILINE)
    result = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', result, flags=re.MULTILINE)
    result = re.sub(r'^# (.+)$', r'<h1>\1</h1>', result, flags=re.MULTILINE)
    # Горизонтальная линия — ровно '---' на отдельной строке (не задеть
    # диапазоны вида "2023---2024" или дефисы внутри текста).
    result = re.sub(r'^---$', r'<hr>', result, flags=re.MULTILINE)
    # Bold
    result = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', result)
    # Italic
    result = re.sub(r'\*(.+?)\*', r'<em>\1</em>', result)
    # Inline code
    result = re.sub(r'`(.+?)`', r'<code>\1</code>', result)
    # Line breaks → paragraphs
    result = re.sub(r'\n\n+', '</p>\n<p>', result)
    result = '<p>' + result + '</p>'
    result = result.replace('<p></p>', '')
    # Заголовки (свои и от format_sections, с атрибутами class/style) и
    # <hr> не должны оказаться внутри <p> — убрать обёртку, если она
    # замкнулась вокруг ровно одного блочного элемента. [^>]* — чтобы
    # совпасть и с голым <h2>, и с <h2 class="..." style="...">.
    result = re.sub(r'<p>\s*(<h[1-6][^>]*>.*?</h[1-6]>)\s*</p>', r'\1', result, flags=re.DOTALL)
    result = re.sub(r'<p>\s*(<hr[^>]*>)\s*</p>', r'\1', result)
    return result


# ═══════════════════════════════════════════
# OSINT RENDERER
# ═══════════════════════════════════════════

def render_osint_results(osint_data):
    """Визуализация OSINT-результатов для Mini App."""
    if not osint_data or 'platforms' not in osint_data:
        return ''

    found = osint_data.get('found', 0)
    maybe = osint_data.get('maybe', 0)
    total = osint_data.get('total_scanned', 0)

    # Metrics
    # #512: авто-колонки — как в render_metrics_html (см. комментарий там)
    metrics_html = f'''<div class="metrics-grid">
  <div class="metric-card"><div class="metric-value" style="color:#3D6B2C">{found}</div><div class="metric-label">Найдено</div></div>
  <div class="metric-card"><div class="metric-value" style="color:#9C6B0B">{maybe}</div><div class="metric-label">Под вопросом</div></div>
  <div class="metric-card"><div class="metric-value" style="color:#6B6558">{total}</div><div class="metric-label">Просканировано</div></div>
</div>\n'''

    # Categorize platforms
    categories = {}
    for p in osint_data.get('platforms', []):
        cat = p.get('category', 'other')
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(p)

    # Та же болезнь, что была в DEPT_COLORS (proxy/core.py) — декоративная
    # радуга по категориям, с «Диспетчерской» не связанная. SPA категории
    # цветом не различает вообще, только текстом — тот же принцип здесь:
    # один акцент, не десять.
    CAT_COLORS = {
        'social': '#A8321E', 'professional': '#A8321E', 'tech': '#A8321E',
        'media': '#A8321E', 'messaging': '#A8321E', 'commerce': '#A8321E',
        'gaming': '#A8321E', 'forum': '#A8321E', 'darknet': '#A8321E', 'other': '#A8321E'
    }
    CAT_NAMES = {
        'social': 'Соцсети', 'professional': 'Проф. сети', 'tech': 'Tech',
        'media': 'Медиа', 'messaging': 'Мессенджеры', 'commerce': 'Маркетплейсы',
        'gaming': 'Игры', 'forum': 'Форумы', 'darknet': 'Даркнет', 'other': 'Другое'
    }

    cats_html = ''
    for cat, platforms in sorted(categories.items(), key=lambda x: -len(x[1])):
        color = CAT_COLORS.get(cat, '#A8321E')
        name = CAT_NAMES.get(cat, cat)
        links = ', '.join([f'<a href="{p["url"]}" style="color:{color}">{p["name"]}</a>' for p in platforms[:5]])
        conf_avg = sum(p.get('confidence', 0) for p in platforms) / len(platforms) if platforms else 0

        cats_html += f'''<div class="info-card" style="border-left:4px solid {color}">
  <div class="info-card-title" style="color:{color}">{name} ({len(platforms)})</div>
  <div class="info-card-body">{links}</div>
  <div style="font-size:11px;color:#6B6558;margin-top:4px">Confidence: {conf_avg:.0f}%</div>
</div>\n'''

    # Uncertain
    uncertain_html = ''
    if osint_data.get('uncertain'):
        uncertain_items = ', '.join([p['name'] for p in osint_data['uncertain'][:10]])
        uncertain_html = f'''<div class="info-card" style="border-left:4px solid #9C6B0B">
  <div class="info-card-title" style="color:#9C6B0B">Под вопросом ({maybe})</div>
  <div class="info-card-body">{uncertain_items}</div>
</div>\n'''

    return f'''<h2 class="section-title" style="border-bottom:2px solid #A8321E">OSINT: 840+ платформ</h2>
{metrics_html}
{cats_html}
{uncertain_html}'''


# ═══════════════════════════════════════════
# ГЛАВНАЯ ФУНКЦИЯ
# ═══════════════════════════════════════════

def auto_enrich(text, dept='yana', accent_color='#A8321E'):
    """
    Полный pipeline обогащения.
    Вход: plain markdown от LLM.
    Выход: rich HTML для Mini App.
    """
    if not text:
        return ''

    # 1. Метрики — extract from RAW text (before any modification)
    metrics = extract_metrics(text)
    metrics_html = render_metrics_html(metrics)

    # 2. Escape plain text FIRST — prevents HTML from enrichment steps
    #    from being destroyed by a later escape pass.
    #    html_lib.escape only affects &, <, >, ", ' —
    #    markdown patterns ([ФАКТ], ##, *, |, -) are NOT affected.
    result = html_lib.escape(text)

    # 3. Structural enrichment on escaped text
    result = format_badges(result)
    result = format_ach_table(result, accent_color)
    result = format_tables(result, accent_color)
    result = format_sections(result, accent_color)
    result = detect_comparison(result)
    result = convert_bullet_to_cards(result)
    result = format_indicators(result, accent_color)
    result = wrap_verdict(result)

    # 4. Markdown formatting (no escape — text already escaped in step 2)
    result = markdown_to_html(result)

    # 5. Insert metrics after first section header
    if metrics_html:
        pos = result.find('</h2>')
        if pos > 0:
            pos += 5
        else:
            # No styled sections — insert after first paragraph
            pos = result.find('</p>')
            if pos > 0:
                pos += 4
            else:
                pos = 0
        result = result[:pos] + '\n' + metrics_html + result[pos:]

    return result