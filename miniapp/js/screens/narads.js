/**
 * FOSVED Mini App — Narads Screen (/narads)
 */

import { esc } from '../app.js';

const STATUS_CONFIG = {
  pending: { label: 'В ОЖИДАНИИ', bg: '#FFF3E0', color: '#EF6C00', border: '#EF9F27' },
  done:    { label: 'ВЫПОЛНЕНО', bg: '#E8F5E9', color: '#2E7D32', border: '#639922' },
  failed:  { label: 'ОШИБКА',   bg: '#FFEBEE', color: '#C62828', border: '#E24B4A' },
};

export async function render(container) {
  let data;
  try { data = await API.narads(); }
  catch (e) { container.innerHTML = `<div class="empty-state">⚠️ Ошибка загрузки</div>`; return; }

  if (data.status !== 'ok') { container.innerHTML = `<div class="empty-state">⚠️ ${esc(data.error)}</div>`; return; }

  const narads = data.narads || [];

  let html = `<div class="topbar"><div class="topbar-title">Наряды</div></div>`;
  html += `<div class="screen-scroll">`;

  html += `<div class="section-title">${narads.length} НАРЯДОВ</div>`;

  if (narads.length) {
    for (const n of narads) {
      const sc = STATUS_CONFIG[n.status] || STATUS_CONFIG.pending;
      html += `
        <div class="narad-card" data-nav="/narad/${esc(n.id)}">
          <div class="narad-header">
            <span class="narad-id">#${esc(n.id)}</span>
            <span class="narad-status" style="background:${esc(sc.bg)};color:${esc(sc.color)};border-color:${esc(sc.border)}">${esc(sc.label)}</span>
          </div>
          <div class="narad-title">${esc(n.title)}</div>
          <div class="narad-desc">${esc(n.description || '—')}</div>
          <div class="narad-meta">
            <span class="narad-dept" style="background:${esc(n.dept_color || '#eee')};color:#fff">${esc(n.dept || '—')}</span>
            <span class="narad-date">${esc(n.date || '—')}</span>
            <span class="narad-assignee">👤 ${esc(n.assignee || '—')}</span>
          </div>
        </div>`;
    }
  } else {
    html += `<div class="empty-state">Нет активных нарядов</div>`;
  }

  html += `</div>`;
  container.innerHTML = html;
}
