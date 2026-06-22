/**
 * Fosved Office Mini App — Archive Screen (Screen 9)
 * Search and browse reports with dept filtering and date grouping.
 */

import { createTopBar, createSectionTitle, esc } from '../components/card.js';
import { createChip } from '../components/badge.js';

/**
 * Department color mapping for archive card borders.
 */
const DEPT_COLORS = {
  osp:        '#b91c1c',
  lz:         '#0e7490',
  expert:     '#3730a3',
  marketing:  '#c2410c',
  finance:    '#15803d',
  legal:      '#475569',
  dev:        '#1d4ed8',
  design:     '#be185d',
  qa:         '#4d7c0f',
  visual:     '#7e22ce',
  engineering:'#44403c',
  kavalnya:   '#b45309',
  yana:       '#293133',
  admin:      '#1e40af',
};

/**
 * All department slugs for filter chips.
 */
const DEPT_SLUGS = [
  'all', 'osp', 'lz', 'dev', 'expert', 'marketing', 'finance', 'legal',
  'design', 'qa', 'visual', 'engineering', 'kavalnya', 'yana', 'admin',
];

export async function render(container) {
  let html = '';

  // ── Top Bar ──
  html += createTopBar('Архив');

  // ── Search Input ──
  html += `
    <div style="padding:12px 16px;position:relative">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#aaa" stroke-width="2"
           style="position:absolute;left:28px;top:50%;transform:translateY(-50%)">
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
      </svg>
      <input class="search-input" id="archive-search"
             placeholder="Search reports..."
             autocomplete="off">
    </div>`;

  // ── Department Filter Chips ──
  html += `<div id="archive-chips" style="display:flex;gap:6px;padding:0 16px 12px;overflow-x:auto;scrollbar-width:none">`;
  for (const slug of DEPT_SLUGS) {
    const label = slug === 'all' ? 'All' : slug.charAt(0).toUpperCase() + slug.slice(1);
    const color = DEPT_COLORS[slug] || '#888';
    const isActive = slug === 'all';
    html += `
      <span class="chip${isActive ? ' chip-active' : ''}"
            data-dept="${slug}"
            data-nav=""
            style="white-space:nowrap;${isActive ? '' : `border-color:${color};color:${color}`}">${esc(label)}</span>`;
  }
  html += `</div>`;

  // ── Results Container ──
  html += `<div id="arc-results" style="padding:0 16px 16px"></div>`;

  container.innerHTML = html;

  // ── State ──
  let activeDept = 'all';
  let debounceTimer = null;

  // ── Load Results ──
  async function loadResults(dept) {
    const searchEl = document.getElementById('archive-search');
    const query = searchEl ? searchEl.value.trim() : '';
    const deptFilter = dept || activeDept;
    const resultsEl = document.getElementById('arc-results');

    if (!resultsEl) return;

    resultsEl.innerHTML = `<div style="text-align:center;padding:24px;color:#aaa;font-size:13px">Searching...</div>`;

    try {
      const data = await API.archive(query, deptFilter === 'all' ? '' : deptFilter);
      const results = data.results || [];

      if (!results.length) {
        resultsEl.innerHTML = `
          <div class="empty-state">
            <div style="font-size:36px;margin-bottom:12px">&#128196;</div>
            ${query ? 'No reports matching your search' : 'No reports found'}
          </div>`;
        return;
      }

      // Group by date
      const grouped = groupByDate(results);

      let out = '';
      for (const [date, items] of Object.entries(grouped)) {
        out += `<div style="margin-top:12px">${createSectionTitle(date)}</div>`;
        for (const item of items) {
          const borderColor = DEPT_COLORS[item.dept] || '#888';
          const shortDate = item.created || date;
          out += `
            <div class="archive-item"
                 style="border-left-color:${borderColor}"
                 data-nav="/report/${esc(item.id)}">
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
                <span style="font-family:'DM Mono',monospace;font-size:11px;font-weight:500;color:${borderColor}">${esc((item.dept || '').toUpperCase())}</span>
                <span style="font-size:11px;color:#aaa">${esc(shortDate)}</span>
              </div>
              <div style="font-size:13px;line-height:1.4">${esc(item.title)}</div>
              ${item.summary ? `<div style="font-size:11px;color:#888;margin-top:2px">${esc(item.summary)}</div>` : ''}
            </div>`;
        }
      }

      resultsEl.innerHTML = out;
    } catch (e) {
      console.error('[Archive] Load error:', e);
      resultsEl.innerHTML = `<div style="text-align:center;padding:24px;color:#E24B4A;font-size:13px">Failed to load</div>`;
    }
  }

  // ── Event: Search Input ──
  const searchEl = document.getElementById('archive-search');
  if (searchEl) {
    searchEl.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => loadResults(activeDept), 400);
    });
    searchEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        clearTimeout(debounceTimer);
        loadResults(activeDept);
      }
    });
  }

  // ── Event: Chip Filter ──
  const chipsContainer = document.getElementById('archive-chips');
  if (chipsContainer) {
    chipsContainer.addEventListener('click', (e) => {
      const chip = e.target.closest('[data-dept]');
      if (!chip) return;
      e.preventDefault();
      activeDept = chip.dataset.dept;

      // Update chip active states
      chipsContainer.querySelectorAll('.chip').forEach(c => {
        const slug = c.dataset.dept;
        const isActive = slug === activeDept;
        c.classList.toggle('chip-active', isActive);
        if (isActive) {
          c.style.borderColor = '';
          c.style.color = '';
        } else {
          const color = DEPT_COLORS[slug] || '#888';
          c.style.borderColor = color;
          c.style.color = color;
        }
      });

      loadResults(activeDept);
    });
  }

  // ── Initial Load ──
  loadResults('all');
}

/**
 * Group items by date string (YYYY-MM-DD or date prefix).
 */
function groupByDate(items) {
  const groups = {};
  for (const item of items) {
    // Use 'created' date, extract just the date portion
    let dateKey = item.created || 'Unknown';
    if (dateKey.includes('T')) dateKey = dateKey.split('T')[0];
    if (dateKey.includes(' ')) dateKey = dateKey.split(' ')[0];
    if (!groups[dateKey]) groups[dateKey] = [];
    groups[dateKey].push(item);
  }
  // Sort groups by date descending
  const sorted = {};
  Object.keys(groups).sort((a, b) => b.localeCompare(a)).forEach(k => {
    sorted[k] = groups[k];
  });
  return sorted;
}
