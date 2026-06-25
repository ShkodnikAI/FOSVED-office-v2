/**
 * Fosved Office Mini App — Settings Screen (Screen 7)
 * Static settings page with profile, toggles, integrations, and security.
 */

import { esc } from '../app.js';
import { createTopBar, createSectionTitle } from '../components/card.js';
import { createBadge } from '../components/badge.js';

export function render(container) {
  let html = '';

  // ── Top Bar ──
  html += createTopBar('Настройки');

  html += '<div class="screen-scroll">';

  // ── Profile Card ──
  html += `
    <div class="profile-card card" style="margin:12px 16px;display:flex;align-items:center;gap:14px">
      <div class="profile-avatar" style="width:48px;height:48px;border-radius:50%;background:#0F0F0F;display:flex;align-items:center;justify-content:center;color:#C9A84C;font-family:'Cormorant Garamond',serif;font-size:22px;font-weight:700;flex-shrink:0">&#9678;</div>
      <div style="flex:1;min-width:0">
        <div style="font-weight:600;font-size:15px">Основатель</div>
        <div style="font-size:12px;color:#888">Fosved &middot; Owner</div>
      </div>
      ${createBadge('premium', 'TAG')}
    </div>`;

  // ── УТРЕННИЙ БРИФИНГ ──
  html += createSectionTitle('УТРЕННИЙ БРИФИНГ');
  html += `<div class="card" style="margin:0 16px 12px">`;
  html += `
    <div class="setting-row">
      <span class="setting-icon">&#128336;</span>
      <div class="setting-info">
        <div class="setting-name">Время брифинга</div>
        <div class="setting-desc">09:00 каждый день</div>
      </div>
    </div>`;
  html += `</div>`;

  // ── ГОЛОС ──
  html += createSectionTitle('ГОЛОС');
  html += `<div class="card" style="margin:0 16px 12px">`;
  html += settingRowToggle('&#128266;', 'Голосовое озвучивание', 'Брифинг прослушать вслух', true);
  html += settingRowToggle('&#128483;', 'Голос ответов', 'ru-RU-DmitryNeural', true);
  html += `</div>`;

  // ── УВЕДОМЛЕНИЯ ──
  html += createSectionTitle('УВЕДОМЛЕНИЯ');
  html += `<div class="card" style="margin:0 16px 12px">`;
  html += settingRowToggle('&#128276;', 'Срочные алерты', 'Telegram + push', true);
  html += settingRowToggle('&#128202;', 'Market scan', 'Раз в неделю · Пятница', false);
  html += `</div>`;

  // ── ИНТЕГРАЦИИ ──
  html += createSectionTitle('ИНТЕГРАЦИИ');
  html += `<div class="card" style="margin:0 16px 12px">`;
  html += integrationItem('◼ Telegram', '@fosved_office_v2_bot', 'Подключён');
  html += integrationItem('◼ GitHub', 'ShkodnikAI', 'Подключён');
  html += integrationItem('◼ Архивный канал', '@FosvedArchive', 'Активен');
  html += `</div>`;

  // ── БЕЗОПАСНОСТЬ ──
  html += createSectionTitle('БЕЗОПАСНОСТЬ');
  html += `
    <div style="margin:0 16px 24px">
      <button class="lockdown-btn card" style="width:100%;text-align:left;padding:14px 16px;border:1px solid #fecaca;background:#fef2f2;cursor:pointer">
        <div style="font-size:14px;font-weight:500;color:#E24B4A">&#128274; Экстренная блокировка</div>
        <div style="font-size:12px;color:#aaa;margin-top:2px">Заморозить все процессы</div>
      </button>
    </div>`;

  html += '</div>'; // .screen-scroll

  container.innerHTML = html;

  // ── Wire toggle click events ──
  wireToggles(container);

  // ── Wire lockdown button ──
  wireLockdown(container);
}

/**
 * Generate a setting row with a toggle switch.
 * @param {string} icon - Emoji icon
 * @param {string} name - Setting name
 * @param {string} desc - Setting description
 * @param {boolean} isOn - Whether the toggle is ON initially
 */
function settingRowToggle(icon, name, desc, isOn) {
  return `
    <div class="setting-row">
      <span class="setting-icon">${icon}</span>
      <div class="setting-info">
        <div class="setting-name">${esc(name)}</div>
        <div class="setting-desc">${esc(desc)}</div>
      </div>
      <div class="toggle${isOn ? ' on' : ''}"></div>
    </div>`;
}

/**
 * Generate an integration item row.
 * @param {string} name - Integration name
 * @param {string} desc - Description / identifier
 * @param {string} status - Status label (e.g. "Подключён")
 */
function integrationItem(name, desc, status) {
  return `
    <div class="integration-item">
      <span class="integration-dot" style="background:#639922"></span>
      <div style="flex:1;min-width:0">
        <div class="integration-name">${esc(name)}</div>
        <div class="integration-desc">${esc(desc)}</div>
      </div>
      <span style="font-size:12px;color:#639922;flex-shrink:0">${esc(status)}</span>
    </div>`;
}

/**
 * Wire up toggle click events — toggles the `.on` class.
 */
function wireToggles(container) {
  container.querySelectorAll('.toggle').forEach(toggle => {
    toggle.addEventListener('click', () => {
      toggle.classList.toggle('on');
    });
  });
}

/**
 * Wire up the emergency lockdown button.
 */
function wireLockdown(container) {
  const btn = container.querySelector('.lockdown-btn');
  if (!btn) return;
  btn.addEventListener('click', () => {
    if (!confirm('Экстренная блокировка: Заморозить все процессы?')) return;
    if (window.tgSendData) {
      window.tgSendData({ action: 'lockdown' });
    }
    btn.textContent = 'Блокировка инициирована';
    btn.disabled = true;
    btn.style.opacity = '0.5';
  });
}