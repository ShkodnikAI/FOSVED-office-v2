/**
 * FOSVED Mini App — Departments List Screen (/depts)
 */

import { esc } from '../app.js';
import { createSectionTitle } from '../components/card.js';
import { formatRating, getDeptDisplayName } from '../api.js';

const FILTERS = ['all', 'active', 'idle'];
const FILTER_LABELS = { all:'Все', active:'Активные', idle:'Ожидание' };

export async function render(container) {
  let data;
  try { data = await API.depts(); }
  catch (e) { container.innerHTML = `<div class="empty-state">⚠️ Ошибка загрузки</div>`; return; }

  if (data.status !== 'ok') { container.innerHTML = `<div class="empty-state">⚠️ ${esc(data.error)}</div>`; return; }

  let filter = 'all';
  let depts = data.depts || [];

  function renderList() {
    let filtered = depts;
    if (filter === 'active') filtered = depts.filter(d => d.status === 'active');
    if (filter === 'idle') filtered = depts.filter(d => d.status !== 'active');

    let html = createTopBar('Отделы');
    html += `<div class="screen-scroll">`;

    // Filter chips
    html += `<div class="filter-chips">`;
    for (const f of FILTERS) {
      html += `<button class="filter-chip${f===filter?' active':''}" data-filter="${f}">${FILTER_LABELS[f]}</button>`;
    }
    html += `</div>`;
    html += `<div class="depts-count">${filtered.length} отделов</div>`;

    // Grid — colored cards
    if (filtered.length) {
      html += `<div class="dept-grid">`;
      for (const d of filtered) {
        const c = d.color || { accent:'#888', start:'#333', end:'#111' };
        const displayName = getDeptDisplayName(d);
        const rating = formatRating(d.rating);
        const isIdle = d.status !== 'active';
        html += `
          <div class="dept-card" data-nav="/dept/${esc(d.slug)}" style="background:linear-gradient(135deg,${esc(c.start)},${esc(c.end)});${isIdle?' opacity:0.75;':''}">
            <div class="dept-card-head">
              <span class="dept-card-dot"></span>
              <span class="dept-card-name">${esc(displayName)}</span>
              <span class="dept-card-rating">${esc(rating)}</span>
            </div>
            <div class="dept-card-desc">${esc(d.description || '—')}</div>
            <div class="dept-card-footer">
              <div class="dept-card-stat"><div class="dept-card-stat-label">ЗАДАЧ</div><div class="dept-card-stat-val">${d.calls ?? 0}</div></div>
              <div class="dept-card-stat"><div class="dept-card-stat-label">ОЦЕНКА</div><div class="dept-card-stat-val">${esc(rating)}</div></div>
              <div class="dept-card-stat"><div class="dept-card-stat-label">МОДЕЛЬ</div><div class="dept-card-stat-val">${esc(d.model || '—')}</div></div>
            </div>
          </div>`;
      }
      html += `</div>`;
    } else {
      html += `<div class="empty-state" style="padding:40px 0;text-align:center"><div style="font-size:28px;margin-bottom:12px">📂</div><div style="font-size:14px;color:#888;font-weight:500">Нет отделов в этой категории</div></div>`;
    }

    html += `</div>`;
    container.innerHTML = html;

    // Wire up filters
    container.querySelectorAll('[data-filter]').forEach(btn => {
      btn.addEventListener('click', () => { filter = btn.dataset.filter; renderList(); });
    });
  }

  renderList();
}

function createTopBar(title) {
  return `<div class="topbar"><div class="topbar-title">${esc(title)}</div></div>`;
}
