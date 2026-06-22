/**
 * Fosved Office Mini App — Economics Screen (Screen 6)
 * Shows cost KPIs, budget, department/provider breakdowns.
 */

import { createTopBar, createSectionTitle, esc } from '../components/card.js';
import { createHorizontalBar, createBudgetBar } from '../components/chart.js';

export async function render(container) {
  let data;
  try {
    data = await API.economics();
  } catch (e) {
    container.innerHTML = `<div style="text-align:center;padding:60px;color:#E24B4A">Failed to load economics</div>`;
    return;
  }

  if (data.status !== 'ok') {
    container.innerHTML = `<div style="text-align:center;padding:60px;color:#E24B4A">${esc(data.error || 'Unknown error')}</div>`;
    return;
  }

  const { periods, by_dept, by_provider, budget, recommendation } = data;

  let html = '';

  // ── Top Bar ──
  html += createTopBar('Экономика');

  // ── Period KPIs ──
  html += `<div class="econ-period" style="padding:12px 16px">`;
  html += createPeriodCard('$' + (periods?.today ?? 0), 'TODAY');
  html += createPeriodCard('$' + (periods?.week ?? 0), 'WEEK');
  html += createPeriodCard('$' + (periods?.month ?? 0), 'MONTH');
  html += `</div>`;

  // ── Budget Bar ──
  const budgetTotal = parseFloat(budget) || 10;
  const usedToday = parseFloat(periods?.today) || 0;
  html += createBudgetBar(usedToday, budgetTotal);

  // ── By Department ──
  if (by_dept && by_dept.length) {
    html += createSectionTitle('BY DEPARTMENT (month)');
    html += `<div class="card" style="margin:0 16px 12px">`;
    const deptMax = Math.max(...by_dept.map(d => d.cost), 0.01);
    for (const d of by_dept) {
      const deptColor = d.color || '#C9A84C';
      const shortName = (d.name || d.dept || '').includes(' — ')
        ? (d.name || d.dept).split(' — ')[0]
        : (d.name || d.dept || '?');
      html += createHorizontalBar(d.cost, deptMax, deptColor, shortName, '');
      // Add $ prefix in value
      // The chart helper already outputs value, so we override by wrapping
    }
    html += `</div>`;
  }

  // ── By Provider ──
  if (by_provider && by_provider.length) {
    html += createSectionTitle('BY PROVIDER (month)');
    html += `<div class="card" style="margin:0 16px 12px">`;
    const provMax = Math.max(...by_provider.map(p => p.cost), 0.01);
    for (const p of by_provider) {
      html += createHorizontalBar(p.cost, provMax, '#185FA5', p.provider, '');
    }
    html += `</div>`;
  }

  // ── Recommendation ──
  if (recommendation) {
    html += `<div style="padding:0 16px;margin:8px 0">`;
    html += `
      <div class="card" style="border-left:3px solid #C9A84C">
        <div style="font-size:11px;color:#C9A84C;font-family:'DM Mono',monospace;margin-bottom:4px">RECOMMENDATION</div>
        <div style="font-size:13px;line-height:1.5;color:#555">${esc(recommendation)}</div>
      </div>`;
    html += `</div>`;
  }

  container.innerHTML = html;
}

/**
 * Period card for the top economics row.
 */
function createPeriodCard(value, label) {
  return `
    <div class="econ-period-card">
      <div style="font-family:'DM Mono',monospace;font-size:20px;font-weight:700">${value}</div>
      <div class="kpi-label">${label}</div>
    </div>`;
}
