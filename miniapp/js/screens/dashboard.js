/**
 * Fosved Office Mini App — Dashboard Screen (Screen 1: Главная)
 * KPIs, department cards, admin block, and alert banners.
 */

import { esc } from '../app.js';
import { createDeptCard, createKPICard, createAlertCard, createTopBar, createSectionTitle } from '../components/card.js';

export async function render(container) {
  let data;
  try { data = await API.dashboard(); } catch {
    container.innerHTML = '<div class="empty-state"><div style="font-size:28px">⚠️</div>Ошибка загрузки</div>';
    return;
  }
  if (data.status !== 'ok') {
    container.innerHTML = `<div class="empty-state"><div style="font-size:28px">⚠️</div>${esc(data.error || 'Ошибка')}</div>`;
    return;
  }

  const { kpis, depts, admin, alerts, version } = data;
  const ratingNum = parseFloat(kpis.rating) || 0;
  const statusColor = ratingNum >= 4 ? '#639922' : ratingNum >= 3 ? '#EF9F27' : '#E24B4A';
  const statusLabel = ratingNum >= 4 ? 'АКТИВЕН' : ratingNum >= 3 ? 'УМЕРЕННЫЙ' : 'НИЗКИЙ';
  const versionStr = version || 'v0.7.10';

  let html = '';

  // Top bar with Fosved branding
  html += `<div class="topbar">
    <div class="topbar-title" style="color:#C9A84C">φ Fosved</div>
    <span class="topbar-sub">${esc(versionStr)}</span>
  </div>`;

  // Status line
  html += `<div style="display:flex;align-items:center;justify-content:space-between">
    <div class="active-indicator"><span class="status-dot green"></span> ${statusLabel}</div>
    <span class="version-tag">${esc(versionStr)}</span>
  </div>`;

  // Alert banners
  if (alerts && alerts.length) {
    html += '<div style="display:flex;flex-direction:column;gap:6px">';
    for (const a of alerts) html += createAlertCard(a.type, a.title, a.subtitle);
    html += '</div>';
  }

  // KPI row
  html += '<div class="dashboard-kpi-row">';
  html += createKPICard(kpis.tasks, 'ЗАДАЧ', '#C9A84C');
  html += createKPICard(kpis.cost_today, 'РАСХОД', '#185FA5');
  html += createKPICard(kpis.rating, 'ОЦЕНКА', statusColor);
  if (window.innerWidth >= 481) {
    html += createKPICard(kpis.reports ?? '—', 'ОТЧЁТЫ', '#639922');
    html += createKPICard(kpis.tasks_week ?? '—', 'НЕДЕЛЯ', '#888');
  }
  html += '</div>';

  // Department cards
  html += createSectionTitle('ОТДЕЛЫ', `${depts.length}/13`);
  html += '<div class="dept-grid">';
  for (const d of depts) html += createDeptCard(d);
  html += '</div>';

  // Admin section
  if (admin) {
    html += createSectionTitle('АДМИН', admin.code_health ? `health ${admin.code_health}` : '');
    html += `
      <div class="admin-block">
        <div class="admin-title">СИСТЕМА</div>
        <div class="admin-stat-row"><span>${admin.nodes ?? 0}</span> nodes · <span>${admin.edges ?? 0}</span> edges</div>
        <div class="admin-stat-row"><span style="color:${admin.issues > 0 ? '#E24B4A' : '#639922'}">${admin.issues ?? 0}</span> open issues · <span>${admin.proposals ?? 0}</span> proposal</div>
      </div>`;
  }

  container.innerHTML = `<div class="screen-scroll">${html}</div>`;
}