/**
 * Fosved Office Mini App — Badge & Chip Components
 */

import { esc } from '../app.js';

const BADGE_TYPES = {
  fact:        { cls: 'badge-fact',       label: '✓' },
  interp:      { cls: 'badge-interp',     label: '◈' },
  int:         { cls: 'badge-interp',     label: '◈' },
  spec:        { cls: 'badge-spec',       label: '⚡' },
  verified:    { cls: 'badge-verified',   label: '✓ verified' },
  unverified:  { cls: 'badge-unverified', label: '⚠ unverified' },
  conflicting: { cls: 'badge-conflicting',label: '⚠' },
  red:    { cls: 'badge-err',  label: '' },
  orange: { cls: 'badge-warn', label: '' },
  green:  { cls: 'badge-ok',   label: '' },
  blue:   { cls: 'badge-info',  label: '' },
  premium:{ cls: 'badge-premium',label: '' },
};

export function createBadge(type, text) {
  const def = BADGE_TYPES[type] || BADGE_TYPES.blue;
  const display = text || def.label;
  if (!display) return '';
  return `<span class="badge ${def.cls}">${esc(display)}</span>`;
}

export function createStatusDot(status, label = '') {
  const colors = { active:'#639922', idle:'#EF9F27', inactive:'#ccc', online:'#639922', offline:'#ccc' };
  return `<span class="status-dot ${status === 'active' || status === 'online' ? 'green' : status === 'idle' ? 'orange' : ''}"></span>${label ? ' ' + esc(label) : ''}`;
}

export function createChip(label, value, active = false, color = '') {
  const style = active ? '' : (color ? `border-color:${color};color:${color}` : '');
  return `<span class="chip${active ? ' active' : ''}" data-value="${esc(value)}" style="white-space:nowrap;${style}">${esc(label)}</span>`;
}

export { esc, BADGE_TYPES };