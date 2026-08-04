/**
 * FOSVED Mini App — Dashboard Screen v2
 */

import { esc } from '../app.js';
import { createKPICard, createAlertCard, createSectionTitle } from '../components/card.js';
import { formatRating, getDeptDisplayName } from '../api.js';

export async function render(container) {
  let data, archiveData;
  try {
    [data, archiveData] = await Promise.all([
      API.dashboard(),
      API.archive('', '').catch(() => ({ status: 'ok', results: [] }))
    ]);
  } catch (e) {
    container.innerHTML = `<div class="empty-state">⚠️ Ошибка загрузки</div>`;
    return;
  }

  if (data.status !== 'ok') {
    container.innerHTML = `<div class="empty-state">⚠️ ${esc(data.error)}</div>`;
    return;
  }

  const { kpis, alerts, depts, admin } = data;
  const reports = (archiveData?.results || []).slice(0, 5);

  // Stats
  const activeCount = (depts || []).filter(d => d.status === 'active').length;
  const idleCount = (depts || []).filter(d => d.status !== 'active').length;
  const alertCount = (alerts || []).length;

  let html = '';

  // Topbar: FOSVED Office в овале, клик → чат с Яной
  html += `<div class="topbar">
    <button class="topbar-title-btn" data-nav="/chat/yana">FOSVED Office</button>
  </div>`;

  html += `<div class="screen-scroll">`;

  // KPI row
  html += `<div class="dashboard-kpi-row">`;
  html += createKPICard(kpis?.tasks ?? '—', 'ЗАДАЧ', '#C9A84C');
  html += createKPICard(kpis?.cost_today ?? '—', 'РАСХОД', '#185FA5');
  html += createKPICard(formatRating(kpis?.rating), 'ОЦЕНКА', '#639922');
  html += `</div>`;

  // Office Status
  html += createSectionTitle('СТАТУС ОФИСА');
  html += `<div class="status-bar">`;
  html += `<div class="status-pill"><span class="status-dot" style="background:#639922"></span>${activeCount} активных</div>`;
  html += `<div class="status-pill"><span class="status-dot" style="background:#EF9F27"></span>${idleCount} idle</div>`;
  html += `<div class="status-pill"><span class="status-dot" style="background:#E24B4A"></span>${alertCount} алерт</div>`;
  html += `<div class="status-pill"><span class="status-dot" style="background:#185FA5"></span>${esc(kpis?.cost_today || '—')}/день</div>`;
  html += `</div>`;

  // Alerts
  html += createSectionTitle('АЛЕРТЫ');
  if (alerts?.length) {
    for (const a of alerts) html += createAlertCard(a.type, a.title, a.subtitle);
  } else {
    html += `<div class="empty-state">Нет активных алертов</div>`;
  }

  // Reports
  html += createSectionTitle('ОТЧЁТЫ', `${reports.length} новых`);
  if (reports.length) {
    for (const r of reports) {
      const deptColor = r.dept_color || '#C9A84C';
      html += `
        <div class="report-card" data-nav="/report/${esc(r.id)}">
          <div class="report-title">${esc(r.title)}</div>
          <div class="report-meta">${esc(r.dept || '—')} · глубина ${r.depth || '—'} · <span class="report-dept" style="background:${esc(deptColor)};color:#fff">${esc(r.dept || '—')}</span></div>
        </div>`;
    }
  } else {
    html += `<div class="empty-state">Нет новых отчётов</div>`;
  }

  // Departments
  if (depts?.length) {
    html += createSectionTitle('ОТДЕЛЫ', `${depts.length} всего`);
    html += `<div class="dept-grid">`;
    for (const d of depts) {
      const c = d.color || { accent: '#888', start: '#333', end: '#111' };
      const displayName = getDeptDisplayName(d);
      const rating = formatRating(d.rating);
      const modelName = d.model || '—';
      html += `
        <div class="dept-card" data-nav="/dept/${esc(d.slug)}">
          <div class="dept-card-head">
            <span class="dept-card-dot" style="background:${esc(c.accent)}"></span>
            <span class="dept-card-name">${esc(displayName)}</span>
            <span class="dept-card-rating">${esc(rating)}</span>
          </div>
          <div class="dept-card-desc">${d.calls ?? 0} задач · ${esc(modelName)} · ${d.status === 'active' ? '● активен' : '○ idle'}</div>
          <div class="dept-card-footer">
            <div class="dept-card-stat"><div class="dept-card-stat-label">ЗАДАЧ</div><div class="dept-card-stat-val">${d.calls ?? 0}</div></div>
            <div class="dept-card-stat"><div class="dept-card-stat-label">ОЦЕНКА</div><div class="dept-card-stat-val">${esc(rating)}</div></div>
            <div class="dept-card-stat"><div class="dept-card-stat-label">МОДЕЛЬ</div><div class="dept-card-stat-val">${esc(modelName)}</div></div>
          </div>
        </div>`;
    }
    html += `</div>`;
  } else {
    html += createSectionTitle('ОТДЕЛЫ');
    html += `<div class="empty-state">Нет доступных отделов</div>`;
  }

  // Admin / System
  if (admin) {
    html += createSectionTitle('СИСТЕМА');
    html += `<div class="card system-card">
      Nodes: ${esc(admin.nodes)} · Edges: ${esc(admin.edges)} · Issues: ${esc(admin.issues)} · Proposals: ${esc(admin.proposals)}<br>
      Uptime: ${esc(admin.uptime || '—')} · Latency: ${esc(admin.latency || '—')} · Models: ${esc(admin.models_online || '—')}
    </div>`;
  }

  html += `</div>`;
  container.innerHTML = html;
}
