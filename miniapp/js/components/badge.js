/**
 * Fosved Office Mini App — Badge Components
 * Small inline badges for categorizing content types.
 */

/**
 * Badge type definitions: CSS class mapping.
 */
const BADGE_TYPES = {
  fact:       { cls: 'badge-fact',       label: 'FACT' },
  interp:     { cls: 'badge-interp',     label: 'INTERP' },
  int:        { cls: 'badge-interp',     label: 'INT' },
  spec:       { cls: 'badge-spec',       label: 'SPEC' },
  verified:   { cls: 'badge-green',      label: 'VERIFIED' },
  unverified: { cls: 'badge-orange',     label: 'UNVERIFIED' },
  conflicting:{ cls: 'badge-red',        label: 'CONFLICT' },
  red:        { cls: 'badge-red',        label: '' },
  orange:     { cls: 'badge-orange',     label: '' },
  green:      { cls: 'badge-green',      label: '' },
  blue:       { cls: 'badge-blue',       label: '' },
  premium:    { cls: 'badge-premium',    label: '' },
};

/**
 * Create an HTML badge.
 * @param {string} type — badge type key (fact, interp, spec, verified, unverified, conflicting, red, orange, green, blue, premium)
 * @param {string} [text] — custom display text; if omitted, uses default label from type
 * @returns {string} HTML
 */
export function createBadge(type, text) {
  const def = BADGE_TYPES[type] || BADGE_TYPES.blue;
  const displayText = text || def.label;
  if (!displayText) return '';
  return `<span class="badge ${def.cls}">${escHtml(displayText)}</span>`;
}

/**
 * Create a status dot with optional label.
 * @param {'active'|'idle'|'inactive'|'online'|'offline'} status
 * @param {string} [label] — optional label text
 * @returns {string} HTML
 */
export function createStatusDot(status, label = '') {
  const colors = {
    active:   '#639922',
    idle:     '#EF9F27',
    inactive: '#cccccc',
    online:   '#639922',
    offline:  '#cccccc',
  };
  const color = colors[status] || '#cccccc';
  return `<span class="status-dot" style="background:${color}"></span>${label ? ` ${escHtml(label)}` : ''}`;
}

/**
 * Create a chip (filter toggle).
 * @param {string} label — display text
 * @param {string} value — data attribute value
 * @param {boolean} active — whether this chip is selected
 * @param {string} [group] — optional group name for data-group attribute
 * @returns {string} HTML
 */
export function createChip(label, value, active = false, group = '') {
  return `
    <span class="chip${active ? ' chip-active' : ''}"
          data-group="${group}" data-value="${escHtml(value)}"
          style="white-space:nowrap">${escHtml(label)}</span>`;
}

function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export { escHtml, BADGE_TYPES };
