/**
 * Fosved Office Mini App — Reusable Card / UI Components
 * Pure HTML generators (string returns, no DOM).
 */

import { esc } from '../app.js';

/**
 * Department card for dashboard grid.
 */
export function createDeptCard(d) {
  const sc = d.status === 'active' ? '#639922' : d.status === 'idle' ? '#EF9F27' : '#ccc';
  const name = d.name.includes(' — ') ? d.name.split(' — ')[0] : d.name;
  const desc = d.name.includes(' — ') ? d.name.split(' — ')[1] : (d.description || '');
  return `
    <div class="dept-card" style="border-left-color:${d.color?.accent || '#888'}" data-nav="/dept/${d.slug}">
      <div class="dept-card-head">
        <span class="status-dot ${d.status === 'active' ? 'green' : d.status === 'idle' ? 'orange' : ''}" ${!['active','idle'].includes(d.status) ? `style="background:${sc}"` : ''}></span>
        <span class="dept-card-name">${esc(name)}</span>
        <span class="dept-card-rating" style="color:${sc}">${d.rating ?? '—'}</span>
      </div>
      <div class="dept-card-desc">${esc(desc)} · ${d.calls ?? 0}з</div>
      ${d.override ? `<div style="font-size:11px;color:#C9A84C;font-family:var(--font-mono);margin-top:4px">${esc(d.override)}</div>` : ''}
    </div>`;
}

/**
 * KPI card.
 */
export function createKPICard(value, label, color = '#0F0F0F') {
  return `
    <div class="card kpi">
      <div class="kpi-value" style="color:${color}">${value}</div>
      <div class="kpi-label">${label}</div>
    </div>`;
}

/**
 * Alert banner.
 */
export function createAlertCard(type, title, subtitle = '') {
  const cls = type === 'red' ? 'alert-red' : type === 'green' ? 'alert-green' : 'alert-orange';
  const icon = type === 'red' ? '🔴' : type === 'green' ? '🟢' : '🟡';
  return `
    <div class="alert ${cls}">
      <div class="alert-title">${icon} ${esc(title)}</div>
      ${subtitle ? `<div class="alert-subtitle">${esc(subtitle)}</div>` : ''}
    </div>`;
}

/**
 * Narad card.
 */
export function createNaradCard(n) {
  const sm = {
    pending: { color:'#EF9F27', bg:'#FFFBF0', label:'PENDING' },
    done:    { color:'#639922', bg:'#EEF7EE', label:'DONE' },
    failed:  { color:'#E24B4A', bg:'#FFF0F0', label:'FAILED' },
    approved:{ color:'#639922', bg:'#EEF7EE', label:'APPROVED' },
  };
  const s = sm[n.status] || sm.pending;
  const title = n.title || n.description || 'Без названия';
  const shortId = n.id.length > 22 ? n.id.substring(0, 22) + '…' : n.id;

  let actions = '';
  if (n.status === 'pending') {
    actions = `
      <div class="narad-actions">
        <button class="btn btn-sm btn-primary" style="flex:1" data-action="approve" data-id="${esc(n.id)}">✅ Подтвердить</button>
        <button class="btn btn-sm" style="flex:1" data-action="reject" data-id="${esc(n.id)}">❌ Откл.</button>
      </div>`;
  }
  if (n.status === 'failed') {
    actions = `
      <div class="narad-actions">
        <button class="btn btn-sm btn-gold" style="flex:1" data-action="retry" data-id="${esc(n.id)}">🔄 Повторить</button>
        <button class="btn btn-sm" style="flex:1" data-action="rollback" data-id="${esc(n.id)}">↩ Откатить</button>
      </div>`;
  }

  return `
    <div class="narad-card" style="border-left-color:${s.color}">
      <div class="narad-header">
        <div>
          <div class="narad-id" style="color:${s.color}">${esc(shortId)}</div>
          <div class="narad-title">${esc(title)}</div>
        </div>
        <span class="badge badge-${n.status === 'done' ? 'ok' : n.status === 'failed' ? 'err' : 'warn'}" style="margin-left:auto;flex-shrink:0">${s.label}</span>
      </div>
      ${n.risk ? `<div class="narad-meta">Risk: ${esc(n.risk)}${n.files ? ' · ' + n.files + ' файл' : ''}</div>` : ''}
      ${n.error ? `<div class="narad-meta" style="color:#E24B4A">Ошибка: ${esc(n.error)}</div>` : ''}
      <div class="narad-meta">${esc(n.created)}</div>
      ${actions}
    </div>`;
}

/**
 * Top bar.
 */
export function createTopBar(title, subtitle = '') {
  return `
    <div class="topbar">
      <div class="topbar-title">${esc(title)}</div>
      ${subtitle ? `<span class="topbar-sub">${esc(subtitle)}</span>` : ''}
    </div>`;
}

/**
 * Section title with optional right badge.
 */
export function createSectionTitle(text, badge = '') {
  return `
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div class="section-title">${esc(text)}</div>
      ${badge ? `<span class="topbar-sub">${esc(badge)}</span>` : ''}
    </div>`;
}

export { esc };