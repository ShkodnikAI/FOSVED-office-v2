/**
 * Fosved Office Mini App — Models Screen (Screen 5)
 * Shows active models, overrides, and analytics KPIs.
 */

import { createKPICard, createTopBar, createSectionTitle, createAlertCard, esc } from '../components/card.js';
import { createBadge } from '../components/badge.js';
import { createPercentCircle } from '../components/chart.js';

/**
 * Status color mapping for model cards.
 */
const STATUS_STYLE = {
  active:    { color: '#639922', label: 'Active',    bg: '#f0fdf4' },
  limited:   { color: '#EF9F27', label: 'Limited',   bg: '#fffbeb' },
  no_key:    { color: '#E24B4A', label: 'No Key',    bg: '#fef2f2' },
  disabled:  { color: '#888888', label: 'Disabled',  bg: '#f5f5f5' },
  error:     { color: '#E24B4A', label: 'Error',     bg: '#fef2f2' },
};

const TIER_LABELS = {
  priority: 'Priority',
  paid:     'Paid',
  free:     'Free',
  free_limit: 'Free Limit',
  cheap:    'Cheap',
  special:  'Special',
};

export async function render(container) {
  let data;
  try {
    data = await API.models();
  } catch (e) {
    container.innerHTML = `<div style="text-align:center;padding:60px;color:#E24B4A">Failed to load models</div>`;
    return;
  }

  if (data.status !== 'ok') {
    container.innerHTML = `<div style="text-align:center;padding:60px;color:#E24B4A">${esc(data.error || 'Unknown error')}</div>`;
    return;
  }

  const { models, overrides, analytics } = data;
  const limitedModel = models.find(m => m.status === 'limited');

  let html = '';

  // ── Top Bar ──
  html += createTopBar('Модели');

  // ── Warning Banner ──
  if (limitedModel) {
    html += `<div style="padding:12px 16px">`;
    html += createAlertCard('orange', `${limitedModel.name} — rate limit reached.`, 'Requests will be throttled or routed to fallback.');
    html += `</div>`;
  }

  // ── Analytics KPIs ──
  if (analytics) {
    html += `<div class="kpi-row">`;
    html += createKPICard(analytics.requests_today ?? '—', 'REQUESTS', '#C9A84C');
    html += createKPICard('$' + (analytics.cost_today ?? 0), 'COST', '#185FA5');
    html += createKPICard(analytics.active_providers ?? '—', 'MODELS', '#3730a3');
    html += `</div>`;
  }

  // ── Model Cards ──
  html += createSectionTitle('ACTIVE MODELS', `${models.length} total`);
  html += `<div class="models-grid" style="padding:0 16px">`;

  for (const m of models) {
    const st = STATUS_STYLE[m.status] || STATUS_STYLE.disabled;
    const tierLabel = TIER_LABELS[m.tier] || m.tier || '';
    const shortKey = (m.key || '??').substring(0, 2).toUpperCase();
    const healthPct = m.health != null ? m.health : (m.status === 'active' ? 100 : 0);

    html += `
      <div class="model-card">
        <div class="model-icon" style="background:${st.bg};color:${st.color}">${esc(shortKey)}</div>
        <div style="flex:1;min-width:0">
          <div style="font-size:14px;font-weight:500">${esc(m.name)}</div>
          <div style="font-size:12px;color:#888">${esc(m.label)} &middot; ${esc(tierLabel)}</div>
          <div style="display:flex;align-items:center;gap:6px;margin-top:4px">
            <span class="status-dot" style="background:${st.color}"></span>
            <span style="font-family:'DM Mono',monospace;font-size:11px;color:${st.color}">${st.label}</span>
            ${m.usage != null ? `<span style="margin-left:auto;font-size:11px;color:#aaa">${m.usage}%</span>` : ''}
          </div>
          ${healthPct < 100 ? `
            <div class="progress-bar" style="margin-top:6px">
              <div class="progress-fill" style="width:${healthPct}%;background:${st.color}"></div>
            </div>` : ''}
        </div>
      </div>`;
  }

  html += `</div>`;

  // ── Overrides Section ──
  if (overrides && typeof overrides === 'object') {
    const entries = Object.entries(overrides);
    if (entries.length) {
      html += createSectionTitle('OVERRIDES');
      html += `<div class="card" style="margin:0 16px 16px">`;
      for (const [dept, model] of entries) {
        html += `
          <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(0,0,0,0.06)">
            <span style="font-size:13px;font-weight:500">${esc(dept)}</span>
            <span style="font-family:'DM Mono',monospace;font-size:12px;color:#C9A84C">${esc(model)}</span>
          </div>`;
      }
      html += `</div>`;
    }
  }

  // ── Analytics Detail ──
  if (analytics) {
    html += createSectionTitle('ANALYTICS');
    html += `
      <div class="card" style="margin:0 16px 16px">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div>
            <div style="font-size:12px;color:#888">Avg Response Time</div>
            <div style="font-family:'DM Mono',monospace;font-size:16px;font-weight:600">${analytics.avg_latency ?? '—'}ms</div>
          </div>
          <div>
            <div style="font-size:12px;color:#888">Error Rate</div>
            <div style="font-family:'DM Mono',monospace;font-size:16px;font-weight:600;color:${(analytics.error_rate ?? 0) > 5 ? '#E24B4A' : '#639922'}">${analytics.error_rate ?? 0}%</div>
          </div>
          <div>
            <div style="font-size:12px;color:#888">Tokens Today</div>
            <div style="font-family:'DM Mono',monospace;font-size:16px;font-weight:600">${analytics.tokens_today ?? '—'}</div>
          </div>
          <div>
            <div style="font-size:12px;color:#888">Cache Hit Rate</div>
            <div style="font-family:'DM Mono',monospace;font-size:16px;font-weight:600">${analytics.cache_hit ?? '—'}%</div>
          </div>
        </div>
      </div>`;
  }

  container.innerHTML = html;
}
