/**
 * Fosved Office Mini App — Reusable Card Components
 * Pure HTML generators (no DOM manipulation, just string returns).
 */

/**
 * Department card with colored left border, status dot, name, calls, and rating.
 * @param {Object} dept — { slug, name, description, status, color: { accent }, calls, rating, override? }
 * @returns {string} HTML
 */
export function createDeptCard(dept) {
  const statusColor = dept.status === 'active' ? '#639922'
                    : dept.status === 'idle'   ? '#EF9F27'
                    : '#cccccc';
  const shortName = dept.name.includes(' — ') ? dept.name.split(' — ')[0] : dept.name;
  const description = dept.name.includes(' — ') ? dept.name.split(' — ')[1] : '';

  return `
    <div class="card card-dept"
         style="border-left-color:${dept.color?.accent || '#888'}"
         data-nav="/dept/${dept.slug}">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
        <span class="status-dot" style="background:${statusColor}"></span>
        <span style="font-weight:600;font-size:14px">${esc(shortName)}</span>
        <span style="margin-left:auto;font-family:'DM Mono',monospace;font-size:12px;color:${statusColor}">
          ${dept.rating ?? '—'}
        </span>
      </div>
      ${description ? `<div style="font-size:12px;color:#888;margin-bottom:2px">${esc(description)} &middot; ${dept.calls ?? 0} calls</div>` : ''}
      ${dept.override ? `<div style="font-size:11px;color:#C9A84C;font-family:'DM Mono',monospace">${esc(dept.override)}</div>` : ''}
    </div>`;
}

/**
 * KPI card — centered value with label.
 * @param {string|number} value — display value
 * @param {string} label — e.g. 'TASKS', 'COST', 'RATING'
 * @param {string} color — value text color
 * @returns {string} HTML
 */
export function createKPICard(value, label, color = '#0F0F0F') {
  return `
    <div class="card kpi">
      <div class="kpi-value" style="color:${color}">${value}</div>
      <div class="kpi-label">${label}</div>
    </div>`;
}

/**
 * Alert card — color-coded banner.
 * @param {'red'|'orange'|'green'} type — alert severity
 * @param {string} title — alert headline
 * @param {string} [subtitle] — optional detail text
 * @returns {string} HTML
 */
export function createAlertCard(type, title, subtitle = '') {
  const cls = type === 'red' ? 'alert-red' : type === 'orange' ? 'alert-orange' : 'alert-green';
  return `
    <div class="alert ${cls}">
      <strong>${esc(title)}</strong>${subtitle ? ` — ${esc(subtitle)}` : ''}
    </div>`;
}

/**
 * Narad card — work order with status badge and optional action buttons.
 * @param {Object} narad — { id, title, description, status, risk, created }
 * @returns {string} HTML
 */
export function createNaradCard(narad) {
  const statusMap = {
    pending:  { color: '#EF9F27', bg: '#FFFBF0', label: 'PENDING' },
    approved: { color: '#639922', bg: '#EEF7EE', label: 'APPROVED' },
    rejected: { color: '#E24B4A', bg: '#FFF0F0', label: 'REJECTED' },
    done:     { color: '#639922', bg: '#EEF7EE', label: 'DONE' },
    failed:   { color: '#E24B4A', bg: '#FFF0F0', label: 'FAILED' },
  };
  const s = statusMap[narad.status] || statusMap.pending;
  const title = narad.title || narad.description || 'Untitled';
  const shortId = narad.id.length > 24 ? narad.id.substring(0, 24) + '…' : narad.id;

  let actions = '';
  if (narad.status === 'pending') {
    actions = `
      <div style="display:flex;gap:6px;margin-top:8px">
        <button class="btn btn-outline"
                style="flex:1;font-size:12px"
                data-action="approve" data-id="${esc(narad.id)}">
          &#10003; Approve
        </button>
        <button class="btn"
                style="flex:1;font-size:12px;background:#f5f5f5"
                data-action="reject" data-id="${esc(narad.id)}">
          &#10007; Reject
        </button>
      </div>`;
  }

  return `
    <div class="narad-card">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
        <span class="status-dot" style="background:${s.color}"></span>
        <span style="font-family:'DM Mono',monospace;font-size:11px;color:#888">${esc(shortId)}</span>
        <span style="margin-left:auto;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:${s.bg};color:${s.color}">
          ${s.label}
        </span>
      </div>
      <div style="font-size:14px;font-weight:500;margin-bottom:4px">${esc(title)}</div>
      ${narad.risk ? `<div style="font-size:11px;color:#888">Risk: ${esc(narad.risk)}</div>` : ''}
      <div style="font-size:11px;color:#aaa;margin-top:4px">${esc(narad.created)}</div>
      ${actions}
    </div>`;
}

/**
 * Simple top bar for screens.
 * @param {string} title — bar title text
 * @param {string} [subtitle] — optional right-aligned subtitle
 * @returns {string} HTML
 */
export function createTopBar(title, subtitle = '') {
  return `
    <div class="top-bar">
      <div class="top-bar-title">${esc(title)}${subtitle ? ` <span style="margin-left:auto;font-size:12px;color:#888;font-weight:400">${esc(subtitle)}</span>` : ''}</div>
    </div>`;
}

/**
 * Generic section title.
 * @param {string} text — section heading
 * @param {string} [badge] — optional right-aligned badge text
 * @returns {string} HTML
 */
export function createSectionTitle(text, badge = '') {
  return `
    <div style="padding:0 16px;margin:12px 0 8px;display:flex;justify-content:space-between;align-items:center">
      <div class="section-title" style="margin:0">${esc(text)}</div>
      ${badge ? `<span style="font-family:'DM Mono',monospace;font-size:11px;color:#aaa">${esc(badge)}</span>` : ''}
    </div>`;
}

/**
 * HTML-escape a string for safe insertion.
 * @param {string} str
 * @returns {string}
 */
function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export { esc };
