/**
 * Fosved Office Mini App — Chart Helpers
 * CSS-only chart components (no canvas, no library).
 */

/**
 * Horizontal progress bar.
 * @param {number} value — current value
 * @param {number} max — maximum value
 * @param {string} color — bar fill color
 * @param {string} label — left-side label text
 * @param {string} [suffix=''] — value suffix (e.g. '$', '%')
 * @returns {string} HTML
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
      <span class="hbar-value">${value}${suffix}</span>
    </div>`;
}

/**
 * Budget usage bar with automatic color coding.
 * Green < 70%, Yellow < 90%, Red >= 90%.
 * @param {number} used — amount used
 * @param {number} total — total budget
 * @param {string} [prefix='$'] — value prefix
 * @returns {string} HTML — a card with label, bar, and values
 */
export function createBudgetBar(used, total, prefix = '$') {
  const safeTotal = Math.max(total, 0.01);
  const pct = Math.min(100, (used / safeTotal) * 100);
  const color = pct >= 90 ? '#E24B4A' : pct >= 70 ? '#EF9F27' : '#639922';

  return `
    <div class="card" style="margin:0 16px 16px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:14px;font-weight:500">Daily Budget</span>
        <span style="font-family:'DM Mono',monospace;font-size:13px">${prefix}${used} / ${prefix}${total}</span>
      </div>
      <div class="progress-bar" style="margin-top:8px">
        <div class="progress-fill" style="width:${pct.toFixed(1)}%;background:${color}"></div>
      </div>
      <div style="display:flex;justify-content:space-between;margin-top:4px">
        <span style="font-size:11px;color:#aaa">${pct.toFixed(0)}% used</span>
        <span style="font-size:11px;color:#aaa">${prefix}${(total - used).toFixed(2)} remaining</span>
      </div>
    </div>`;
}

/**
 * Sparkline-like mini bar (thin vertical bars for trend visualization).
 * @param {number[]} values — array of numeric values
 * @param {string} color — bar color
 * @param {number} [height=24] — max bar height in px
 * @returns {string} HTML
 */
export function createSparkBars(values, color, height = 24) {
  if (!values || !values.length) return '<span style="color:#ccc">—</span>';
  const max = Math.max(...values, 0.01);
  const barW = Math.max(2, Math.min(4, Math.floor(80 / values.length)));
  const bars = values.map(v => {
    const h = Math.max(1, (v / max) * height);
    return `<span style="display:inline-block;width:${barW}px;height:${h.toFixed(1)}px;background:${color};border-radius:1px;margin-right:1px;vertical-align:bottom"></span>`;
  }).join('');
  return `<span style="display:inline-flex;align-items:flex-end;height:${height}px;gap:1px">${bars}</span>`;
}

/**
 * Simple percentage indicator circle (CSS-only).
 * @param {number} pct — 0–100
 * @param {string} color — circle color
 * @param {number} [size=40] — diameter in px
 * @returns {string} HTML
 */
export function createPercentCircle(pct, color, size = 40) {
  const r = Math.max(1, (size / 2) - 3);
  const circumference = 2 * Math.PI * r;
  const offset = circumference * (1 - Math.min(100, Math.max(0, pct)) / 100);
  return `
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="transform:rotate(-90deg)">
      <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="#e0e0e0" stroke-width="3"/>
      <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="none" stroke="${color}" stroke-width="3"
              stroke-dasharray="${circumference.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"
              stroke-linecap="round" style="transition:stroke-dashoffset 0.6s ease"/>
    </svg>`;
}
