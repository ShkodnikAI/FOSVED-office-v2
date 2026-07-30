/**
 * FOSVED Mini App — Models Screen (/models)
 */

import { esc } from '../app.js';

const STATUS_COLORS = {
  online:  { bg: '#E8F5E9', text: '#2E7D32', border: '#639922' },
  away:    { bg: '#FFF3E0', text: '#EF6C00', border: '#EF9F27' },
  limited: { bg: '#FFF3E0', text: '#EF6C00', border: '#EF9F27' },
  offline: { bg: '#FFEBEE', text: '#C62828', border: '#E24B4A' },
};

export async function render(container) {
  let data;
  try { data = await API.models(); }
  catch (e) { container.innerHTML = `<div class="empty-state">⚠️ Ошибка загрузки</div>`; return; }

  if (data.status !== 'ok') { container.innerHTML = `<div class="empty-state">⚠️ ${esc(data.error)}</div>`; return; }

  const { kpis, models } = data;
  let html = '';

  // Topbar
  html += `<div class="topbar" style="justify-content:space-between"><div class="topbar-title">Модели</div><button class="add-btn" id="add-model-btn">+ Добавить</button></div>`;
  html += `<div class="screen-scroll">`;

  // KPI row
  html += `<div class="kpi-row">`;
  html += `<div class="kpi"><div class="kpi-value" style="color:#639922">${esc(kpis?.active ?? '—')}</div><div class="kpi-label">АКТИВНЫ</div></div>`;
  html += `<div class="kpi"><div class="kpi-value" style="color:#E24B4A">${esc(kpis?.cost ?? '—')}</div><div class="kpi-label">РАСХОД</div></div>`;
  html += `<div class="kpi"><div class="kpi-value" style="color:#185FA5">${esc(kpis?.uptime ?? '—')}</div><div class="kpi-label">UPTIME</div></div>`;
  html += `</div>`;

  // Models list
  html += `<div class="section-title" style="justify-content:space-between"><span>ПРИОРИТЕТ МОДЕЛЕЙ</span><span style="font-size:10px;color:#888;font-weight:500">↑↓ перетащите</span></div>`;

  if (models?.length) {
    models.forEach((m, idx) => {
      const sc = STATUS_COLORS[m.status] || STATUS_COLORS.offline;
      const isOffline = m.status === 'offline';
      html += `
        <div class="model-card" style="border-left-color:${esc(sc.border)};${isOffline?'opacity:0.7;':''}">
          <div class="model-priority">
            <span class="priority-rank">#${idx + 1}</span>
            ${idx === 0 ? '<span class="priority-badge">приоритет</span>' : ''}
            <div class="priority-btns">
              ${idx > 0 ? `<button class="priority-btn" data-up="${idx}">↑</button>` : ''}
              ${idx < models.length - 1 ? `<button class="priority-btn" data-down="${idx}">↓</button>` : ''}
            </div>
            <span class="priority-handle">⋮⋮</span>
          </div>
          <div class="model-card-header">
            <div class="model-avatar" style="background:linear-gradient(135deg,${esc(m.color||sc.border)},${esc(m.color2||sc.border)})">${esc(m.short||m.name?.substring(0,2)||'AI')}</div>
            <div class="model-info">
              <div class="model-name">${esc(m.name)}</div>
              <div class="model-provider">${esc(m.provider)} · ${esc(m.tier)}</div>
            </div>
            <span class="model-status" style="background:${esc(sc.bg)};color:${esc(sc.text)}">${esc(m.status?.toUpperCase())}</span>
          </div>
          <div class="model-stats">
            <div class="model-stat"><div class="model-stat-val" style="color:#C9A84C">${esc(m.requests ?? 0)}</div><div class="model-stat-label">ЗАПРОСЫ</div></div>
            <div class="model-stat"><div class="model-stat-val" style="color:#185FA5">${esc(m.latency ?? '—')}</div><div class="model-stat-label">LATENCY</div></div>
            <div class="model-stat"><div class="model-stat-val" style="color:#E24B4A">${esc(m.cost ?? '—')}</div><div class="model-stat-label">COST</div></div>
            <div class="model-stat"><div class="model-stat-val" style="color:${esc(sc.text)}">${esc(m.health ?? '—')}</div><div class="model-stat-label">HEALTH</div></div>
          </div>
          <div class="progress-bar"><div class="progress-fill" style="width:${esc(m.usage_pct ?? 0)}%;background:${esc(sc.border)}"></div></div>
          <div class="model-actions">
            <button class="model-btn secondary" data-logs="${esc(m.key)}">Логи</button>
            ${isOffline
              ? `<button class="model-btn primary" data-enable="${esc(m.key)}">Включить</button>`
              : `<button class="model-btn danger" data-disable="${esc(m.key)}">Отключить</button>`}
          </div>
        </div>`;
    });
  } else {
    html += `<div class="empty-state">Нет настроенных моделей</div>`;
  }

  html += `</div>`;

  // Modal
  html += `
    <div class="modal-overlay" id="modal-add-model" style="display:none;">
      <div class="modal" onclick="event.stopPropagation()">
        <div class="modal-title">Добавить модель</div>
        <div class="form-group"><label class="form-label">Название модели</label><input class="form-input" id="m-name" type="text" placeholder="Например: GPT-4o"></div>
        <div class="form-group"><label class="form-label">Провайдер</label><input class="form-input" id="m-provider" type="text" placeholder="Например: OpenAI"></div>
        <div class="form-group"><label class="form-label">API Key</label><input class="form-input" id="m-key" type="password" placeholder="sk-..."></div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">Tier</label><select class="form-select" id="m-tier"><option>priority</option><option>paid</option><option>cheap</option><option>special</option></select></div>
          <div class="form-group"><label class="form-label">Лимит ($)</label><input class="form-input" id="m-limit" type="number" placeholder="10.00"></div>
        </div>
        <div class="modal-actions">
          <button class="modal-btn secondary" id="modal-cancel">Отмена</button>
          <button class="modal-btn primary" id="modal-save">Добавить</button>
        </div>
      </div>
    </div>`;

  container.innerHTML = html;

  // Wire up modal
  const modal = container.querySelector('#modal-add-model');
  container.querySelector('#add-model-btn').addEventListener('click', () => { modal.style.display = 'flex'; });
  container.querySelector('#modal-cancel').addEventListener('click', () => { modal.style.display = 'none'; });
  container.querySelector('#modal-save').addEventListener('click', async () => {
    const payload = {
      name: container.querySelector('#m-name').value,
      provider: container.querySelector('#m-provider').value,
      key: container.querySelector('#m-key').value,
      tier: container.querySelector('#m-tier').value,
      limit: parseFloat(container.querySelector('#m-limit').value) || 0,
    };
    try { await API.addModel(payload); modal.style.display = 'none'; render(container); }
    catch (e) { alert('Ошибка: ' + e.message); }
  });
  modal.addEventListener('click', (e) => { if (e.target === modal) modal.style.display = 'none'; });
}
