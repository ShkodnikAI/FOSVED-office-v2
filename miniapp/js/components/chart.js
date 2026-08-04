/**
 * FOSVED Mini App — Mini Chart Component
 */

import { esc } from '../app.js';

export function createMiniChart(items, color='#C9A84C') {
  const max = Math.max(...items.map(i => i.value || 0), 1);
  const bars = items.map(item => {
    const h = Math.max(4, (item.value / max) * 100);
    return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px"><div style="width:100%;height:${h.toFixed(0)}%;background:${esc(color)};border-radius:3px 3px 0 0;min-height:4px;opacity:0.8"></div><div style="font-size:9px;font-family:var(--font-mono);color:#aaa;text-align:center">${esc(item.label)}</div></div>`;
  }).join('');
  return `<div style="display:flex;align-items:flex-end;gap:4px;height:80px;padding:8px 0">${bars}</div>`;
}

export function createBudgetBar(used, total) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const cls = pct >= 80 ? 'danger' : pct >= 50 ? 'warn' : 'safe';
  return `<div class="budget-bar"><div class="budget-bar-fill ${cls}" style="width:${pct.toFixed(1)}%"></div></div>`;
}
