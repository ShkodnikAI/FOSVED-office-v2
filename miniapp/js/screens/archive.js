/**
 * Fosved Office Mini App — Archive Screen (Screen 9)
 * Search and browse reports with Russian department filtering and date grouping.
 */

import { esc } from '../app.js';
import { createTopBar } from '../components/card.js';

/**
 * Department color mapping for archive card border-left.
 */
const DEPT_COLORS = {
  osp:         '#b91c1c',
  lz:          '#0e7490',
  expert:      '#3730a3',
  marketing:   '#c2410c',
  finance:     '#15803d',
  legal:       '#475569',
  dev:         '#1d4ed8',
  design:      '#be185d',
  qa:          '#4d7c0f',
  visual:      '#7e22ce',
  engineering: '#44403c',
  kavalnya:    '#b45309',
  yana:        '#293133',
  admin:       '#1e40af',
};

/**
 * Department filter chips: label → slug mapping.
 */
const DEPT_CHIPS = [
  { label: 'Все',       slug: '' },
  { label: 'ОСП',       slug: 'osp' },
  { label: 'ЛЗ',        slug: 'lz' },
  { label: 'Dev',       slug: 'dev' },
  { label: 'Expert',    slug: 'expert' },
  { label: 'Маркетинг', slug: 'marketing' },
  { label: 'Финансы',   slug: 'finance' },
  { label: 'Юрист',     slug: 'legal' },
  { label: 'Design',    slug: 'design' },
  { label: 'QA',        slug: 'qa' },
  { label: 'Visual',    slug: 'visual' },
  { label: 'Eng',       slug: 'engineering' },
  { label: 'Кавальня',  slug: 'kavalnya' },
  { label: 'Яна',       slug: 'yana' },
  { label: 'Админ',     slug: 'admin' },
];

export async function render(container) {
  let html = '';

  // ── Top Bar ──
  html += createTopBar('Архив');

  html += '<div class="screen-scroll">';

  // ── Search Bar ──
  html += `
    <div class="search-bar" style="padding:12px 16px;position:relative">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#aaa" stroke-width="2"
           style="position:absolute;left:28px;top:50%;transform:translateY(-50%)">
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
      <input class="search-input" id="archive-search"
             placeholder="Поиск по отчётам..."
             autocomplete="off">
    </div>`;

  // ── Department Filter Chips ──
  html += `<div class="archive-filters" style="display:flex;gap:6px;padding:0 16px 12px;overflow-x:auto;scrollbar-width:none">`;
  for (const chip of DEPT_CHIPS) {
    const isActive = chip.slug === '';
    const color = DEPT_COLORS[chip.slug] || '#888';
    html += `
      <span class="chip${isActive ? ' active' : ''}"
            data-dept="${esc(chip.slug)}"
            data-nav=""
            style="white-space:nowrap;${isActive ? '' : `border-color:${color};color:${color}`}">${esc(chip.label)}</span>`;
  }
  html += `</div>`;

  // ── Results Container ──
  html += `<div id="arc-results" style="padding:0 16px 16px"></div>`;

  html += '</div>'; // .screen-scroll

  container.innerHTML = html;

  // ── State ──
  let activeDept = '';
  let debounceTimer = null;

  // ── Load Results ──
  async function loadResults() {
    const searchEl = document.getElementById('archive-search');
    const query = searchEl ? searchEl.value.trim() : '';
    const resultsEl = document.getElementById('arc-results');

    if (!resultsEl) return;

    resultsEl.innerHTML = '<div style="text-align:center;padding:24px;color:#aaa;font-size:13px">Загрузка...</div>';

    try {
      const data = await API.archive(query, activeDept);
      const results = data.results || [];

      if (!results.length) {
        resultsEl.innerHTML = `
          <div class="empty-state">
            <div style="font-size:36px;margin-bottom:12px">&#128196;</div>
            ${query ? 'Отчёты не найдены' : 'Нет отчётов'}
          </div>`;
        return;
      }

      // Group by date
      const grouped = groupByDate(results);

      let out = '';
      for (const [dateLabel, items] of grouped) {
        out += `<div class="date-group-label" style="font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin:16px 0 6px">${esc(dateLabel)}</div>`;
        for (const item of items) {
          const borderColor = DEPT_COLORS[item.dept] || '#888';
          const time = extractTime(item.created);
          out += `
            <div class="archive-card"
                 style="border-left:3px solid ${borderColor};padding:10px 12px;margin-bottom:6px;cursor:pointer"
                 data-nav="/report/${esc(item.id)}">
              <div class="archive-dept-line" style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
                <span style="font-family:'DM Mono',monospace;font-size:11px;font-weight:500;color:${borderColor}">${esc((item.dept || '').toUpperCase())}</span>
                <span style="font-size:11px;color:#aaa">${esc(time)}</span>
              </div>
              <div class="archive-title" style="font-size:13px;line-height:1.4">${esc(item.title)}</div>
            </div>`;
        }
      }

      resultsEl.innerHTML = out;
    } catch (e) {
      console.error('[Archive] Load error:', e);
      resultsEl.innerHTML = '<div style="text-align:center;padding:24px;color:#E24B4A;font-size:13px">Не удалось загрузить</div>';
    }
  }

  // ── Event: Search Input (debounced 400ms) ──
  const searchEl = document.getElementById('archive-search');
  if (searchEl) {
    searchEl.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => loadResults(), 400);
    });
    searchEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        clearTimeout(debounceTimer);
        loadResults();
      }
    });
  }

  // ── Event: Chip Filter ──
  const filtersContainer = container.querySelector('.archive-filters');
  if (filtersContainer) {
    filtersContainer.addEventListener('click', (e) => {
      const chip = e.target.closest('[data-dept]');
      if (!chip) return;
      e.preventDefault();
      e.stopPropagation();
      activeDept = chip.dataset.dept;

      // Update chip active states
      filtersContainer.querySelectorAll('.chip').forEach(c => {
        const slug = c.dataset.dept;
        const isActive = slug === activeDept;
        c.classList.toggle('active', isActive);
        if (isActive) {
          c.style.borderColor = '';
          c.style.color = '';
        } else {
          const color = DEPT_COLORS[slug] || '#888';
          c.style.borderColor = color;
          c.style.color = color;
        }
      });

      loadResults();
    });
  }

  // ── Initial Load ──
  loadResults();
}

/**
 * Extract the time portion from a datetime string.
 * @param {string} datetime - e.g. "2026-06-26 14:32"
 * @returns {string} - e.g. "14:32"
 */
function extractTime(datetime) {
  if (!datetime) return '';
  const parts = datetime.split(' ');
  return parts.length > 1 ? parts[parts.length - 1] : datetime;
}

/**
 * Group items by date string and return sorted groups with friendly labels.
 * "СЕГОДНЯ" for today, "ВЧЕРА" for yesterday, otherwise the date string.
 * Groups are sorted descending by date.
 * @param {Array} items
 * @returns {Map<string, Array>} - label → items
 */
function groupByDate(items) {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const todayStr = fmtDate(today);
  const yesterdayStr = fmtDate(yesterday);

  const groups = new Map();

  for (const item of items) {
    let dateKey = item.created || '';
    // Extract date portion
    if (dateKey.includes('T')) dateKey = dateKey.split('T')[0];
    if (dateKey.includes(' ')) dateKey = dateKey.split(' ')[0];

    let label = dateKey;
    if (dateKey === todayStr) {
      label = 'СЕГОДНЯ';
    } else if (dateKey === yesterdayStr) {
      label = 'ВЧЕРА';
    }

    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(item);
  }

  // Sort groups: СЕГОДНЯ first, then ВЧЕРА, then by date descending
  const sorted = new Map();
  const order = { 'СЕГОДНЯ': 0, 'ВЧЕРА': 1 };
  const entries = [...groups.entries()].sort((a, b) => {
    const aP = order[a[0]] != null ? order[a[0]] : 2;
    const bP = order[b[0]] != null ? order[b[0]] : 2;
    if (aP !== bP) return aP - bP;
    return b[0].localeCompare(a[0]); // descending for date strings
  });
  for (const [k, v] of entries) {
    sorted.set(k, v);
  }

  return sorted;
}

/**
 * Format a Date as YYYY-MM-DD.
 */
function fmtDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}