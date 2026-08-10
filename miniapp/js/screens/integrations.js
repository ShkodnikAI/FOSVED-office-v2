/**
 * FOSVED Mini App — Integrations Screen (/integrations) — SEC-6
 * Owner-only screen for managing API keys and service integrations.
 */

import { esc } from '../app.js';

const KIND_LABELS = {
  model: 'Модель',
  service: 'Сервис',
};

const KIND_ICONS = {
  model: '\u{1F916}',   // 🤖
  service: '\u{1F527}',  // 🔧
};

const SOURCE_LABELS = {
  db: 'БД (переопределён)',
  env: 'Render (env)',
  none: 'не подключено',
};

export async function render(container) {
  let data;
  try {
    data = await API.integrations();
  } catch (e) {
    container.innerHTML = `<div class="empty-state">\u26A0\uFE0F Ошибка загрузки интеграций</div>`;
    return;
  }

  if (data.status !== 'ok') {
    container.innerHTML = `<div class="empty-state">\u26A0\uFE0F ${esc(data.error || data.message || 'Ошибка')}</div>`;
    return;
  }

  const integrations = data.integrations || [];
  const models = integrations.filter(i => i.kind === 'model');
  const services = integrations.filter(i => i.kind === 'service');
  const connectedCount = integrations.filter(i => i.connected).length;

  let html = '';

  // Topbar
  html += `<div class="topbar"><div class="topbar-title">Интеграции</div></div>`;
  html += `<div class="screen-scroll">`;

  // KPI row
  html += `<div class="kpi-row">`;
  html += `<div class="kpi"><div class="kpi-value" style="color:#639922">${connectedCount}</div><div class="kpi-label">ПОДКЛЮЧЕНО</div></div>`;
  html += `<div class="kpi"><div class="kpi-value" style="color:#185FA5">${integrations.length}</div><div class="kpi-label">ВСЕГО</div></div>`;
  html += `<div class="kpi"><div class="kpi-value" style="color:#C9A84C">${integrations.length - connectedCount}</div><div class="kpi-label">НЕ НАСТРОЕНО</div></div>`;
  html += `</div>`;

  // Master-key warning banner (hidden by default, shown on save error)
  html += `<div id="sec6-masterkey-warning" class="alert-banner" style="display:none;background:#FFF3E0;border:1px solid #EF9F27;border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:13px;color:#EF6C00;">`;
  html += `\u26A0\uFE0F <b>SECRETS_MASTER_KEY не настроен на сервере.</b> Сохранение ключей невозможно. Добавьте ключ в переменные окружения Render.`;
  html += `</div>`;

  // Models section
  html += `<div class="section-title">${KIND_ICONS.model} МОДЕЛИ</div>`;
  if (models.length) {
    html += `<div class="integrations-group">`;
    for (const item of models) {
      html += _renderCard(item);
    }
    html += `</div>`;
  } else {
    html += `<div class="empty-state" style="padding:12px">Нет моделей</div>`;
  }

  // Services section
  html += `<div class="section-title" style="margin-top:16px">${KIND_ICONS.service} СЕРВИСЫ</div>`;
  if (services.length) {
    html += `<div class="integrations-group">`;
    for (const item of services) {
      html += _renderCard(item);
    }
    html += `</div>`;
  } else {
    html += `<div class="empty-state" style="padding:12px">Нет сервисов</div>`;
  }

  html += `</div>`; // .screen-scroll

  // Modal for editing key
  html += `
    <div class="modal-overlay" id="sec6-key-modal" style="display:none;">
      <div class="modal" onclick="event.stopPropagation()">
        <div class="modal-title" id="sec6-modal-title">Изменить ключ</div>
        <div class="form-group">
          <label class="form-label" id="sec6-modal-label"></label>
          <input class="form-input" id="sec6-key-input" type="password" placeholder="Вставьте ключ…" autocomplete="off">
        </div>
        <div id="sec6-modal-error" style="display:none;color:#E24B4A;font-size:13px;margin-bottom:8px;"></div>
        <div class="modal-actions">
          <button class="modal-btn secondary" id="sec6-modal-cancel">Отмена</button>
          <button class="modal-btn primary" id="sec6-modal-save">Сохранить</button>
        </div>
      </div>
    </div>`;

  container.innerHTML = html;

  // Wire up card buttons
  _wireCards(container);
  // Wire up modal
  _wireModal(container);
}

function _renderCard(item) {
  const dotColor = item.connected ? '#639922' : '#E24B4A';
  const dotTitle = item.connected ? 'Подключено' : 'Не подключено';
  const sourceLabel = SOURCE_LABELS[item.source] || item.source;
  const canDelete = item.source === 'db';
  const kindLabel = KIND_LABELS[item.kind] || item.kind;

  let statusLine = '';
  if (item.connected) {
    statusLine = `<span class="int-masked">${esc(item.masked)}</span> <span class="int-source">${esc(sourceLabel)}</span>`;
  } else {
    statusLine = `<span class="int-disconnected">не подключено</span>`;
  }

  return `
    <div class="int-card" data-id="${esc(item.id)}" data-kind="${esc(item.kind)}">
      <div class="int-header">
        <div class="int-dot" style="background:${dotColor}" title="${dotTitle}"></div>
        <div class="int-info">
          <div class="int-label">${esc(item.label)}</div>
          <div class="int-kind">${esc(kindLabel)} · <span class="int-env">${esc(item.id)}</span></div>
        </div>
      </div>
      <div class="int-status">${statusLine}</div>
      <div class="int-actions">
        <button class="int-btn edit" data-edit="${esc(item.id)}">Изменить</button>
        ${canDelete ? `<button class="int-btn delete" data-delete="${esc(item.id)}">Отключить</button>` : ''}
      </div>
    </div>`;
}

function _wireCards(container) {
  container.querySelectorAll('[data-edit]').forEach(btn => {
    btn.addEventListener('click', () => {
      const envKey = btn.dataset.edit;
      const card = container.querySelector(`.int-card[data-id="${envKey}"]`);
      const label = card?.querySelector('.int-label')?.textContent || envKey;
      _openEditModal(container, envKey, label);
    });
  });

  container.querySelectorAll('[data-delete]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const envKey = btn.dataset.delete;
      if (!confirm(`Удалить переопределение ключа ${envKey}?\nЗначение вернётся к переменной окружения (если задана).`)) return;
      try {
        const res = await API.integrationDelete(envKey);
        if (res.status === 'ok') {
          render(container);
        } else {
          alert('Ошибка: ' + (res.message || res.error || 'неизвестная'));
        }
      } catch (e) {
        alert('Ошибка удаления: ' + e.message);
      }
    });
  });
}

function _wireModal(container) {
  const modal = container.querySelector('#sec6-key-modal');
  const cancelBtn = container.querySelector('#sec6-modal-cancel');
  const saveBtn = container.querySelector('#sec6-modal-save');

  cancelBtn.addEventListener('click', () => { modal.style.display = 'none'; });
  modal.addEventListener('click', (e) => { if (e.target === modal) modal.style.display = 'none'; });

  saveBtn.addEventListener('click', async () => {
    const envKey = saveBtn.dataset.envKey;
    const input = container.querySelector('#sec6-key-input');
    const errorDiv = container.querySelector('#sec6-modal-error');
    const value = input.value.trim();
    errorDiv.style.display = 'none';

    if (!value) {
      errorDiv.textContent = 'Значение не может быть пустым';
      errorDiv.style.display = 'block';
      return;
    }

    saveBtn.disabled = true;
    saveBtn.textContent = 'Сохранение…';

    try {
      const res = await API.integrationSet(envKey, value);
      if (res.status === 'ok') {
        modal.style.display = 'none';
        // Re-fetch list (never show the entered value again)
        render(container);
      } else {
        // Check for master key error (B.2)
        const msg = res.message || res.error || 'неизвестная ошибка';
        if (msg.includes('SECRETS_MASTER_KEY')) {
          const warning = container.querySelector('#sec6-masterkey-warning');
          if (warning) warning.style.display = 'block';
          modal.style.display = 'none';
        } else {
          errorDiv.textContent = msg;
          errorDiv.style.display = 'block';
        }
      }
    } catch (e) {
      errorDiv.textContent = e.message;
      errorDiv.style.display = 'block';
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Сохранить';
    }
  });
}

function _openEditModal(container, envKey, label) {
  const modal = container.querySelector('#sec6-key-modal');
  container.querySelector('#sec6-modal-title').textContent = `Ключ: ${label}`;
  container.querySelector('#sec6-modal-label').textContent = envKey;
  container.querySelector('#sec6-key-input').value = '';
  container.querySelector('#sec6-modal-error').style.display = 'none';
  container.querySelector('#sec6-modal-save').dataset.envKey = envKey;
  modal.style.display = 'flex';
  // Focus input
  setTimeout(() => container.querySelector('#sec6-key-input')?.focus(), 100);
}
