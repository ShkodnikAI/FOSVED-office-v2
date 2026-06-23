/**
 * Fosved Office Mini App — Dashboard Screen (Screen 1)
 * Shows KPIs, department cards, admin status, and alerts.
 */

import { createDeptCard, createKPICard, createAlertCard, createTopBar, createSectionTitle, esc } from '../components/card.js';

export async function render(container) {
  let data;
  try {
    data = await API.dashboard();
  } catch (e) {
    container.innerHTML = `<div style="text-align:center;padding:60px;color:#E24B4A">Failed to load dashboard</div>`;
    return;
  }

  if (data.status !== 'ok') {
    container.innerHTML = `<div style="text-align:center;padding:60px;color:#E24B4A">${esc(data.error || 'Unknown error')}</div>`;
    return;
  }

  const { kpis, depts, admin, alerts } = data;

  // Determine overall system status
  const ratingNum = parseFloat(kpis.rating) || 0;
  const statusColor = ratingNum >= 4 ? '#639922' : ratingNum >= 3 ? '#EF9F27' : '#E24B4A';
  const statusLabel = ratingNum >= 4 ? 'Active' : ratingNum >= 3 ? 'Moderate' : 'Low';

  let html = '';

  // ── Top Bar ──
  html += `<div class="top-bar">
    <div class="top-bar-title" style="color:#C9A84C">&#9678; Fosved</div>
    <span style="margin-left:auto;font-family:'DM Mono',monospace;font-size:11px;color:#aaa">v0.7.10</span>
  </div>`;

  // ── Header Banner ──
  html += `
    <div class="dept-header" style="background:linear-gradient(135deg,#0F0F0F,#1a1a2e)">
      <h1>Fosved Office v2</h1>
      <div class="dept-header-sub">
        <span class="status-dot" style="background:${statusColor}"></span>
        ${statusLabel} &mdash; ${kpis.rating}/5
      </div>
    </div>`;

  // ── Alert Banners ──
  if (alerts && alerts.length) {
    html += `<div style="padding:12px 16px 4px;display:flex;flex-direction:column;gap:6px">`;
    for (const alert of alerts) {
      html += createAlertCard(alert.type || 'orange', alert.title, alert.subtitle);
    }
    html += `</div>`;
  }

  // ── KPI Cards ──
  html += `<div class="kpi-row">`;
  html += createKPICard(kpis.tasks, 'TASKS', '#C9A84C');
  html += createKPICard('$' + kpis.cost_today, 'COST TODAY', '#185FA5');
  html += createKPICard(kpis.rating, 'RATING', statusColor);
  html += createKPICard(kpis.reports, 'REPORTS', '#639922');
  if (window.innerWidth >= 481) {
    html += createKPICard(kpis.tasks_week ?? '—', 'WEEK', '#888');
  }
  html += `</div>`;

  // ── Department Cards ──
  html += createSectionTitle('ОТДЕЛЫ', `${depts.length}/13`);
  html += `<div class="dept-grid">`;
  for (const dept of depts) {
    html += createDeptCard(dept);
  }
  html += `</div>`;

  // ── Admin Section ──
  if (admin) {
    html += createSectionTitle('ADMIN', admin.code_health ?? '');
    html += `
      <div class="card" style="margin:0 16px 16px">
        <div style="display:flex;gap:16px;flex-wrap:wrap">
          <div class="card kpi" style="flex:1;min-width:80px">
            <div class="kpi-value">${admin.nodes ?? 0}</div>
            <div class="kpi-label">NODES</div>
          </div>
          <div class="card kpi" style="flex:1;min-width:80px">
            <div class="kpi-value">${admin.edges ?? 0}</div>
            <div class="kpi-label">EDGES</div>
          </div>
          <div class="card kpi" style="flex:1;min-width:80px">
            <div class="kpi-value" style="color:${admin.issues > 0 ? '#E24B4A' : '#639922'}">${admin.issues ?? 0}</div>
            <div class="kpi-label">ISSUES</div>
          </div>
          <div class="card kpi" style="flex:1;min-width:80px">
            <div class="kpi-value" style="color:#C9A84C">${admin.proposals ?? 0}</div>
            <div class="kpi-label">PROPOSALS</div>
          </div>
        </div>
      </div>`;
  }

  container.innerHTML = html;
}
