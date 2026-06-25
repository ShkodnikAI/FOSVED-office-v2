/**
 * Fosved Office Mini App — Economics Screen (Screen 6)
 * Shows cost hero, budget, department/provider breakdowns, and recommendation.
 */

import { esc } from '../app.js';
import { createTopBar, createSectionTitle } from '../components/card.js';
import { createHorizontalBar, createBudgetBar } from '../components/chart.js';

export async function render(container) {
  let data;
  try {
    data = await API.economics();
  } catch (e) {
    container.innerHTML = `<div style="text-align:center;padding:60px;color:#E24B4A">Ошибка загрузки экономики</div>`;
    return;
  }

  if (data.status !== 'ok') {
    container.innerHTML = `<div style="text-align:center;padding:60px;color:#E24B4A">${esc(data.error || 'Неизвестная ошибка')}</div>`;
    return;
  }

  const { periods, by_dept, by_provider, budget, recommendation } = data;

  let html = '';

  // ── Top Bar ──
  html += createTopBar('Экономика');

  html += `<div class="screen-scroll">`;

  // ── Cost Hero Card ──
  html += `
    <div style="padding:12px 16px">
      <div class="cost-hero card">
        <div style="font-size:11px;font-family:'DM Mono',monospace;color:#888;letter-spacing:0.05em;margin-bottom:10px">РАСХОД LLM</div>
        <div class="cost-period-row">
          <div style="flex:1;text-align:center">
            <div class="cost-period-value">${esc(periods?.today ?? '—')}</div>
            <div class="cost-period-label">Сегодня</div>
          </div>
          <div style="flex:1;text-align:center">
            <div class="cost-period-value">${esc(periods?.week ?? '—')}</div>
            <div class="cost-period-label">Неделя</div>
          </div>
          <div style="flex:1;text-align:center">
            <div class="cost-period-value">${esc(periods?.month ?? '—')}</div>
            <div class="cost-period-label">Месяц</div>
          </div>
        </div>
      </div>
    </div>`;

  // ── Budget Bar ──
  html += `<div style="padding:0 16px 8px">`;
  html += createSectionTitle('БЮДЖЕТ');
  html += `</div>`;
  const budgetTotal = parseFloat(budget) || 10;
  const usedToday = parseFloat(String(periods?.today || '0').replace('€', '').replace('$', '')) || 0;
  html += `<div style="padding:0 16px 8px">`;
  html += createBudgetBar(usedToday, budgetTotal, '€');
  html += `</div>`;

  // ── By Department (месяц) ──
  if (by_dept && by_dept.length) {
    html += createSectionTitle('ПО ОТДЕЛАМ (месяц)');
    html += `<div class="card" style="margin:0 16px 12px">`;
    const deptMax = Math.max(...by_dept.map(d => d.cost), 0.01);
    for (const d of by_dept) {
      const deptColor = d.color || '#C9A84C';
      html += createHorizontalBar(d.cost, deptMax, deptColor, d.dept || d.name || '?', '');
    }
    html += `</div>`;
  }

  // ── By Provider (месяц) ──
  if (by_provider && by_provider.length) {
    html += createSectionTitle('ПО МОДЕЛЯМ (месяц)');
    html += `<div class="card" style="margin:0 16px 12px">`;
    const provMax = Math.max(...by_provider.map(p => p.cost), 0.01);
    for (const p of by_provider) {
      html += createHorizontalBar(p.cost, provMax, '#185FA5', p.provider || '?', '');
    }
    html += `</div>`;
  }

  // ── Recommendation ──
  if (recommendation) {
    html += `
      <div style="padding:0 16px 16px">
        <div class="recommendation-card card" style="border-left:3px solid #C9A84C">
          <div style="font-size:11px;color:#C9A84C;font-family:'DM Mono',monospace;margin-bottom:4px">РЕКОМЕНДАЦИЯ</div>
          <div style="font-size:13px;line-height:1.5;color:#555">💡 ${esc(recommendation)}</div>
        </div>
      </div>`;
  }

  html += `</div>`; // close screen-scroll

  container.innerHTML = html;
}