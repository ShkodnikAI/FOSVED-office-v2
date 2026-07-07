/**
 * Fosved Office Mini App — Models Screen (Screen 5)
 * Shows active models with status, overrides, and analytics KPIs.
 */

import { esc } from '../app.js';
import { createKPICard, createTopBar, createSectionTitle, createAlertCard } from '../components/card.js';
import { createBadge } from '../components/badge.js';

/**
 * Status style map for model cards.
 */
const STATUS_STYLE = {
  active:   { color: '#639922', label: '✓ Act' },
  limited:  { color: '#EF9F27', label: '⚠ Lim' },
  no_key:   { color: '#E24B4A', label: '✗ Нет' },
  disabled: { color: '#888',    label: '— Off' },
};

const TIER_LABELS = {
  priority:   'Приоритет',
  paid:       'Платная',
  free:       'Бесплатная',
  free_limit: 'Лимит',
  cheap:      'Дешёвая',
  special:    '—',
};

/**
 * Determine progress bar color based on usage percentage.
 */
function progressColor(pct) {
  if (pct >= 90) return '#E24B4A';
  if (pct >= 70) return '#EF9F27';
  return '#639922';
}

export async function render(container) {
  let data;
  try {
    data = await API.models();
  } catch (e) {
    container.innerHTML = `<div style="text-align:center;padding:60px;color:#E24B4A">Ошибка загрузки моделей</div>`;
    return;
  }

  if (data.status !== 'ok') {
    container.innerHTML = `<div style="text-align:center;padding:60px;color:#E24B4A">${esc(data.error || 'Неизвестная ошибка')}</div>`;
    return;
  }

  const { models, overrides, analytics } = data;
  const hasLimited = models.some(m => m.status === 'limited');

  let html = '';

  // ── Top Bar ──
  html += createTopBar('Модели');

  html += `<div class="screen-scroll">`;

  // ── Warning Banner ──
  if (hasLimited) {
    const limitedNames = models
      .filter(m => m.status === 'limited')
      .map(m => m.name)
      .join(', ');
    html += `<div style="padding:12px 16px 4px">`;
    html += createAlertCard('red', `${limitedNames} — лимит исчерпан.`, 'Запросы перенаправлены на резервные модели.');
    html += `</div>`;
  }

  // ── Analytics KPI Row (3 cards) ──
  if (analytics) {
    html += `<div class="analytics-kpi-row">`;
    html += createKPICard(analytics.requests_today ?? '—', 'ЗАПРОСОВ', '#C9A84C');
    html += createKPICard(analytics.cost_today ?? '—', 'РАСХОД', '#185FA5');
    html += createKPICard(analytics.active_providers ?? '—', 'МОДЕЛЕЙ', '#3730a3');
    html += `</div>`;
  }

  // ── Active Models ──
  html += createSectionTitle('АКТИВНЫЕ МОДЕЛИ', `${models.length} всего`);
  html += `<div style="padding:0 16px;display:flex;flex-direction:column;gap:8px">`;

  for (const m of models) {
    const st = STATUS_STYLE[m.status] || STATUS_STYLE.disabled;
    const tierLabel = TIER_LABELS[m.tier] || m.tier || '';
    const shortKey = (m.key || '??').substring(0, 2).toUpperCase();

    // Progress calculation
    const limit = m.limit || 0;
    const used = m.used || 0;
    const hasProgress = limit > 0;
    const usagePct = hasProgress ? Math.min(100, (used / limit) * 100) : 0;
    const pColor = hasProgress ? progressColor(usagePct) : '#e0e0e0';
    const usageText = hasProgress ? `${used}/${limit.toLocaleString('ru-RU')}` : '';

    html += `
      <div class="model-card-item">
        <div class="model-header">
          <span class="model-key" style="background:${st.color}22;color:${st.color}">${esc(shortKey)}</span>
          <span class="model-name">
            <span class="status-dot" style="background:${st.color}"></span>
            ${esc(m.name)}
          </span>
          <span style="margin-left:auto;font-family:'DM Mono',monospace;font-size:11px;color:${st.color}">${st.label}</span>
        </div>
        <div class="model-desc">${esc(m.label)} · ${esc(tierLabel)}</div>
        ${hasProgress ? `
          <div class="model-progress">
            <div class="progress-bar" style="flex:1">
              <div class="progress-fill ${usagePct >= 90 ? 'red' : usagePct >= 70 ? 'orange' : 'green'}" style="width:${usagePct.toFixed(1)}%;background:${pColor}"></div>
            </div>
            <span style="font-family:'DM Mono',monospace;font-size:11px;color:#888;margin-left:8px">${esc(usageText)}</span>
          </div>` : ''}
        <div class="model-actions">
          <button class="btn btn-sm" style="flex:1;font-size:12px" data-action="priority" data-model="${esc(m.key)}">Приоритет</button>
          <button class="btn btn-sm" style="flex:1;font-size:12px" data-action="configure" data-model="${esc(m.key)}">Настроить</button>
        </div>
      </div>`;
  }

  html += `</div>`;

  // ── Overrides Section ──
  if (overrides && typeof overrides === 'object') {
    const entries = Object.entries(overrides);
    if (entries.length) {
      html += createSectionTitle('OVERRIDES ПО ОТДЕЛАМ');
      html += `<div class="card" style="margin:0 16px 12px">`;
      for (const [dept, model] of entries) {
        html += `
          <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(0,0,0,0.06);font-family:'DM Mono',monospace;font-size:12px">
            <span style="color:#555">${esc(dept)}</span>
            <span style="color:#C9A84C">${esc(model)}</span>
          </div>`;
      }
      html += `</div>`;
    }
  }

  // ── Analytics Today (2x2 grid) ──
  if (analytics) {
    html += createSectionTitle('АНАЛИТИКА · СЕГОДНЯ');
    html += `
      <div class="card" style="margin:0 16px 16px">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div>
            <div style="font-size:12px;color:#888">Avg Response</div>
            <div style="font-family:'DM Mono',monospace;font-size:16px;font-weight:600">${analytics.avg_latency ?? '—'}ms</div>
          </div>
          <div>
            <div style="font-size:12px;color:#888">Error Rate</div>
            <div style="font-family:'DM Mono',monospace;font-size:16px;font-weight:600;color:${(analytics.error_rate ?? 0) > 5 ? '#E24B4A' : '#639922'}">${analytics.error_rate ?? 0}%</div>
          </div>
          <div>
            <div style="font-size:12px;color:#888">Tokens</div>
            <div style="font-family:'DM Mono',monospace;font-size:16px;font-weight:600">${(analytics.tokens_today ?? 0).toLocaleString('ru-RU')}</div>
          </div>
          <div>
            <div style="font-size:12px;color:#888">Cache Hit</div>
            <div style="font-family:'DM Mono',monospace;font-size:16px;font-weight:600;color:#185FA5">${analytics.cache_hit ?? 0}%</div>
          </div>
        </div>
      </div>`;
  }

  html += `</div>`; // close screen-scroll

  container.innerHTML = html;
}