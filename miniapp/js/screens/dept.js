/**
 * Fosved Office Mini App — Department Details Screen (Screen 2)
 * Shows department KPIs, tasks, corrections, skills, and model config.
 */

import { createKPICard, createTopBar, createSectionTitle, esc } from '../components/card.js';
import { createBadge } from '../components/badge.js';
import { createChip } from '../components/badge.js';

export async function render(container, slug) {
  if (!slug) {
    container.innerHTML = `<div class="empty-state">Department slug required</div>`;
    return;
  }

  let data;
  try {
    data = await API.dept(slug);
  } catch (e) {
    container.innerHTML = `<div style="text-align:center;padding:60px;color:#E24B4A">Failed to load department</div>`;
    return;
  }

  if (data.status !== 'ok') {
    container.innerHTML = `<div style="text-align:center;padding:60px;color:#E24B4A">${esc(data.error || 'Department not found')}</div>`;
    return;
  }

  const { name, color, kpis, tasks, corrections, skills, model, provider } = data;
  const c = color || { start: '#334155', end: '#1e293b', accent: '#64748b' };

  let html = '';

  // ── Top Bar with Chat Button ──
  html += `
    <div class="top-bar">
      <div class="top-bar-title">${esc(name)}</div>
      <a href="#/chat/${slug}" style="margin-left:auto;font-size:12px;color:#185FA5;text-decoration:none">💬 Chat</a>
    </div>`;

  // ── Gradient Header ──
  html += `
    <div class="dept-header" style="background:linear-gradient(135deg,${c.start},${c.end})">
      <h1>${esc(name)}</h1>
      <div class="dept-header-status">
        <span class="status-dot" style="background:#639922"></span> Active &middot; ${esc(model || '—')}
      </div>
    </div>`;

  // ── KPI Cards ──
  html += `<div class="kpi-row">`;
  html += createKPICard(kpis?.tasks ?? '—', 'TASKS', '#C9A84C');
  html += createKPICard(kpis?.rating ?? '—', 'RATING', '#639922');
  if (kpis?.cost_today != null) {
    html += createKPICard('$' + kpis.cost_today, 'COST', '#185FA5');
  }
  html += `</div>`;

  // ── Recent Tasks ──
  if (tasks && tasks.length) {
    html += createSectionTitle('TASKS');
    html += `<div style="padding:0 16px;display:flex;flex-direction:column;gap:6px">`;
    for (const task of tasks) {
      const badges = task.badges || [];
      html += `
        <div class="card" style="padding:12px">
          <div style="font-size:13px;line-height:1.5">${esc(task.text)}</div>
          <div style="display:flex;align-items:center;gap:4px;margin-top:6px;flex-wrap:wrap">
            ${badges.map(b => createBadge(b.type || b, b.label || b)).join('')}
            <span style="margin-left:auto;font-size:11px;color:#aaa">${esc(task.created)}</span>
          </div>
        </div>`;
    }
    html += `</div>`;
  }

  // ── Skills Badges ──
  if (skills && skills.length) {
    html += createSectionTitle('SKILLS');
    html += `<div style="display:flex;flex-wrap:wrap;gap:6px;padding:0 16px">`;
    for (const skill of skills) {
      html += createChip(skill, skill);
    }
    html += `</div>`;
  }

  // ── Corrections ──
  if (corrections && corrections.length) {
    html += createSectionTitle('CORRECTIONS');
    html += `<div style="padding:0 16px;display:flex;flex-direction:column;gap:6px">`;
    for (const cr of corrections) {
      html += `
        <div class="card" style="padding:10px 12px;border-left:3px solid #EF9F27">
          <div style="font-size:12px;color:#555;line-height:1.5">${esc(cr.original)}</div>
          ${cr.correction ? `<div style="font-size:12px;color:#639922;margin-top:4px">&#8594; ${esc(cr.correction)}</div>` : ''}
          <div style="font-size:11px;color:#aaa;margin-top:4px">${esc(cr.created)}</div>
        </div>`;
    }
    html += `</div>`;
  }

  // ── Model Info ──
  html += createSectionTitle('MODEL');
  html += `
    <div class="card" style="margin:0 16px 16px">
      <div style="font-family:'DM Mono',monospace;font-size:13px;color:#C9A84C">${esc(model || '—')}</div>
      ${provider ? `<div style="font-size:12px;color:#888;margin-top:4px">Provider: ${esc(provider)}</div>` : ''}
    </div>`;

  container.innerHTML = html;
}
