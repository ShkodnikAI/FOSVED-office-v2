/**
 * Fosved Office Mini App — Department Details Screen (Screen 2: Отдел)
 * Gradient header, KPIs, recent tasks, skills, corrections, observations, model.
 */

import { esc } from '../app.js';
import { createKPICard, createSectionTitle } from '../components/card.js';

export async function render(container, slug) {
  if (!slug) {
    container.innerHTML = '<div class="empty-state"><div style="font-size:28px">⚠️</div>Отдел не указан</div>';
    return;
  }

  let data;
  try {
    data = await API.dept(slug);
  } catch {
    container.innerHTML = '<div class="empty-state"><div style="font-size:28px">⚠️</div>Ошибка загрузки</div>';
    return;
  }

  if (data.status !== 'ok') {
    container.innerHTML = `<div class="empty-state"><div style="font-size:28px">⚠️</div>${esc(data.error || 'Отдел не найден')}</div>`;
    return;
  }

  const { name, color, kpis, tasks, corrections, skills, observations, model, provider } = data;
  const c = color || { start: '#334155', end: '#1e293b', accent: '#64748b' };
  const shortName = name.includes(' — ') ? name.split(' — ')[0] : name;
  const subtitle = name.includes(' — ') ? name.split(' — ').slice(1).join(' — ') : '';
  const ratingNum = parseFloat(kpis?.rating) || 0;
  const statusColor = ratingNum >= 4 ? '#639922' : ratingNum >= 3 ? '#EF9F27' : '#E24B4A';
  const statusLabel = ratingNum >= 4 ? 'АКТИВЕН' : ratingNum >= 3 ? 'УМЕРЕННЫЙ' : 'НИЗКИЙ';

  let html = '';

  // ── 1. Topbar: back + name + chat ──
  html += `<div class="topbar">
    <span data-nav="/" style="cursor:pointer;font-size:18px;margin-right:8px" aria-label="Назад">←</span>
    <div class="topbar-title">${esc(shortName)}</div>
    <span data-nav="/chat/${esc(slug)}" style="margin-left:auto;font-size:12px;color:#185FA5;cursor:pointer;white-space:nowrap">💬 [chat]</span>
  </div>`;

  // ── 2. Gradient header ──
  html += `
    <div class="dept-gradient-header" style="background:linear-gradient(135deg,${c.start},${c.end})">
      <h1 style="margin:0;font-size:22px;font-weight:700;color:#fff">${esc(shortName)}</h1>
      ${subtitle ? `<div style="font-size:13px;color:rgba(255,255,255,0.7);margin-top:4px">${esc(subtitle)}</div>` : ''}
      <div style="display:flex;align-items:center;gap:6px;margin-top:10px;font-size:12px;color:rgba(255,255,255,0.8)">
        <span class="status-dot" style="background:${statusColor}"></span>
        ${statusLabel} · <span style="font-family:var(--font-mono,monospace)">${esc(model || '—')}</span>
      </div>
    </div>`;

  // ── 3. KPI row (2-col: tasks + rating) ──
  html += '<div class="dept-kpi-row">';
  html += createKPICard(kpis?.tasks ?? '—', 'ЗАДАЧ', '#C9A84C');
  html += createKPICard(kpis?.rating ?? '—', 'ОЦЕНКА', statusColor);
  html += '</div>';

  // ── 4. ПОСЛЕДНИЕ ЗАДАЧИ ──
  if (tasks && tasks.length) {
    html += createSectionTitle('ПОСЛЕДНИЕ ЗАДАЧИ');
    for (const t of tasks) {
      const starsStr = '★'.repeat(Math.min(t.stars || 0, 5)) + '☆'.repeat(Math.max(5 - (t.stars || 0), 0));
      html += `
        <div class="task-item">
          <div class="task-text">${esc(t.text)}</div>
          <div class="task-meta">
            ${esc(t.created)}
            ${t.depth != null ? ` · depth ${t.depth}` : ''}
            ${t.stars != null ? ` · <span style="color:#C9A84C">${starsStr}</span>` : ''}
          </div>
        </div>`;
    }
  }

  // ── 5. НАВЫКИ ──
  if (skills && skills.length) {
    html += createSectionTitle('НАВЫКИ');
    html += '<div class="skills-grid">';
    for (const s of skills) {
      html += `<span class="skill-chip">${esc(s)}</span>`;
    }
    html += '</div>';
  }

  // ── 6. КОРРЕКЦИИ (/fix) ──
  if (corrections && corrections.length) {
    html += createSectionTitle('КОРРЕКЦИИ (/fix)');
    for (const cr of corrections) {
      html += `
        <div class="correction-item">
          <div class="correction-type">${esc(cr.type || 'FIX')}</div>
          <div class="correction-text">${esc(cr.text)}</div>
          <div class="correction-date">${esc(cr.created)}</div>
        </div>`;
    }
  }

  // ── 7. НАБЛЮДЕНИЕ ──
  if (observations && observations.length) {
    html += createSectionTitle('НАБЛЮДЕНИЕ');
    for (const o of observations) {
      html += `
        <div class="observation-item">
          <div style="font-size:13px;font-weight:500">${esc(o.topic)}</div>
          <div style="font-size:11px;color:#888;margin-top:3px">${esc(o.freq)}${o.last ? ' · ' + esc(o.last) : ''}</div>
        </div>`;
    }
  }

  // ── 8. МОДЕЛЬ ──
  html += createSectionTitle('МОДЕЛЬ');
  html += `
    <div class="card" style="margin:0 0 24px">
      <div style="font-family:var(--font-mono,monospace);font-size:14px;color:#C9A84C">${esc(model || '—')}</div>
      ${provider ? `<div style="font-size:12px;color:#888;margin-top:4px">Provider: ${esc(provider)}</div>` : ''}
    </div>`;

  container.innerHTML = `<div class="screen-scroll">${html}</div>`;
}