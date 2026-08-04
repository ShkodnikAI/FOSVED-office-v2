/**
 * FOSVED Mini App — Card Component Helpers
 */

import { esc } from '../app.js';

export function createKPICard(value, label, color) {
  return `<div class="kpi"><div class="kpi-value" style="color:${esc(color||'var(--c-text)')}">${esc(value)}</div><div class="kpi-label">${esc(label)}</div></div>`;
}

export function createTopBar(title, subtitle='') {
  return `<div class="top-bar"><div class="top-bar-title">${esc(title)}${subtitle?`<div class="topbar-sub">${esc(subtitle)}</div>`:''}</div></div>`;
}

export function createSectionTitle(title, extra='') {
  return `<div class="section-title">${esc(title)}${extra?` <span style="color:var(--c-text-tertiary);font-weight:400">${esc(extra)}</span>`:''}</div>`;
}

export function createAlertCard(type, title, subtitle) {
  const colors = { red:'#E24B4A', orange:'#EF9F27', green:'#639922', blue:'#185FA5' };
  const c = colors[type] || colors.red;
  return `<div class="alert" style="border-color:${c};background:${c}11"><div style="font-size:13px;font-weight:600;color:${c};margin-bottom:2px">${esc(title)}</div><div style="font-size:11px;color:#666">${esc(subtitle)}</div></div>`;
}

export function createStatusDot(status, label) {
  const colors = { online:'#639922', offline:'#E24B4A', away:'#EF9F27', busy:'#E24B4A' };
  return `<span style="display:inline-flex;align-items:center;gap:4px"><span class="status-dot" style="background:${colors[status]||colors.offline}"></span>${label?`<span style="font-size:11px;color:#888">${esc(label)}</span>`:''}</span>`;
}
