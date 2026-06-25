/**
 * Fosved Office Mini App — CSS-only Chart Helpers
 */

/**
 * Horizontal bar for economics breakdown.
 */
export function createHorizontalBar(value, max, color, label, suffix = '') {
  const safeMax = Math.max(max, 0.01);
  const pct = Math.min(100, Math.max(0, (value / safeMax) * 100));
  return `
    <div class="hbar-row">
      <span class="hbar-label">${label}</span>
      <div class="hbar-track">
        <div class="hbar-fill" style="width:${pct.toFixed(1)}%;background:${color}"></div>
      </div>
      <span class="hbar-value">€${value.toFixed(2)}</span>
    </div>`;
}

/**
 * Budget bar with color coding.
 */
export function createBudgetBar(used, total, prefix = '€') {
  const safeTotal = Math.max(total, 0.01);
  const pct = Math.min(100, (used / safeTotal) * 100);
  const color = pct >= 90 ? '#E24B4A' : pct >= 70 ? '#EF9F27' : '#639922';
  return `
    <div class="card">
      <div class="budget-header">
        <span class="budget-label">Дневной лимит</span>
        <span class="budget-value">${prefix}${used.toFixed(2)} / ${prefix}${total.toFixed(2)}</span>
      </div>
      <div class="progress-bar">
        <div class="progress-fill ${pct >= 90 ? 'red' : pct >= 70 ? 'orange' : 'green'}" style="width:${pct.toFixed(1)}%"></div>
      </div>
    </div>`;
}

/**
 * CSS-only percentage circle (SVG).
 */
export function createPercentCircle(pct, color, size = 40) {
  const r = Math.max(1, (size / 2) - 3);
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - Math.min(100, Math.max(0, pct)) / 100);
  return `
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="transform:rotate(-90deg)">
      <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="#e0e0e0" stroke-width="3"/>
      <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${color}" stroke-width="3"
              stroke-dasharray="${circ.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"
              stroke-linecap="round" style="transition:stroke-dashoffset .6s ease"/>
    </svg>`;
}