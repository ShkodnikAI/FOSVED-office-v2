/**
 * Fosved Office Mini App — Settings Screen (Screen 7)
 * Static settings page with profile, toggles, integrations, and security.
 */

import { createTopBar, createSectionTitle, esc } from '../components/card.js';
import { createStatusDot } from '../components/badge.js';

/**
 * Settings state (local toggle state, no persistence required for MVP).
 */
const settingsState = {
  voiceReplies: true,
  morningBrief: true,
  urgentAlerts: true,
  marketScan: false,
  weeklyDigest: true,
  darkMode: false,
};

export function render(container) {
  let html = '';

  // ── Top Bar ──
  html += createTopBar('Настройки');

  // ── Profile Card ──
  html += `
    <div class="card" style="margin:12px 16px;display:flex;align-items:center;gap:14px">
      <div style="width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#0F0F0F,#1a1a2e);display:flex;align-items:center;justify-content:center;color:#C9A84C;font-family:'Cormorant Garamond',serif;font-size:22px;font-weight:700;flex-shrink:0">&#9678;</div>
      <div style="flex:1;min-width:0">
        <div style="font-weight:600;font-size:15px">Owner</div>
        <div style="font-size:12px;color:#888">Fosved &middot; Owner</div>
      </div>
      <div style="font-size:11px;color:#aaa;font-family:'DM Mono',monospace">ID: —</div>
    </div>`;

  // ── Morning Brief ──
  html += createSectionTitle('MORNING BRIEF');
  html += `<div class="card" style="margin:0 16px 12px">`;
  html += settingToggle('morningBrief', 'Morning Brief', 'Daily summary at 08:00 MSK', settingsState.morningBrief);
  html += `</div>`;

  // ── Voice Settings ──
  html += createSectionTitle('VOICE');
  html += `<div class="card" style="margin:0 16px 12px">`;
  html += settingToggle('voiceReplies', 'Voice Replies', 'Short answers spoken aloud', settingsState.voiceReplies);
  html += `
    <div class="setting-row">
      <div>
        <div class="setting-label">Voice Profile</div>
        <div class="setting-desc">ru-RU-DmitryNeural</div>
      </div>
      <span style="font-size:12px;color:#C9A84C">Male</span>
    </div>`;
  html += `</div>`;

  // ── Notifications ──
  html += createSectionTitle('NOTIFICATIONS');
  html += `<div class="card" style="margin:0 16px 12px">`;
  html += settingToggle('urgentAlerts', 'Urgent Alerts', 'Telegram + push for critical events', settingsState.urgentAlerts);
  html += settingToggle('marketScan', 'Market Scan', 'Weekly on Friday', settingsState.marketScan);
  html += settingToggle('weeklyDigest', 'Weekly Digest', 'Summary every Monday', settingsState.weeklyDigest);
  html += `</div>`;

  // ── Integrations ──
  html += createSectionTitle('INTEGRATIONS');
  html += `<div class="card" style="margin:0 16px 12px">`;
  html += integrationRow('Telegram Bot', true, 'Connected');
  html += integrationRow('GitHub', true, 'Connected');
  html += integrationRow('Archive Channel', true, 'Active');
  html += integrationRow('Yandex Cloud', false, 'Not configured');
  html += `</div>`;

  // ── Appearance ──
  html += createSectionTitle('APPEARANCE');
  html += `<div class="card" style="margin:0 16px 12px">`;
  html += settingToggle('darkMode', 'Dark Mode', 'Follows system preference', settingsState.darkMode);
  html += `</div>`;

  // ── Security ──
  html += createSectionTitle('SECURITY');
  html += `
    <div class="card" style="margin:0 16px 24px;display:flex;flex-direction:column;gap:10px">
      <div class="setting-row" style="border:none;padding-top:0">
        <div>
          <div class="setting-label">Two-Factor Auth</div>
          <div class="setting-desc">Enabled via Telegram</div>
        </div>
        <span style="font-size:12px;color:#639922">&#10003;</span>
      </div>
      <div class="setting-row" style="border:none">
        <div>
          <div class="setting-label">API Keys</div>
          <div class="setting-desc">3 keys configured</div>
        </div>
        <span style="font-size:12px;color:#C9A84C">Manage</span>
      </div>
      <button class="btn"
              style="width:100%;background:#fef2f2;color:#E24B4A;border:1px solid #fecaca;font-size:13px;margin-top:8px"
              id="btn-lockdown">
        &#128274; Emergency Lockdown
      </button>
      <div style="font-size:11px;color:#aaa;text-align:center">Freeze all processes immediately</div>
    </div>`;

  container.innerHTML = html;

  // ── Wire Toggle Events ──
  wireToggles(container);
  wireLockdown(container);
}

/**
 * Generate a toggle setting row.
 */
function settingToggle(key, label, desc, active) {
  return `
    <div class="setting-row">
      <div>
        <div class="setting-label">${esc(label)}</div>
        <div class="setting-desc">${esc(desc)}</div>
      </div>
      <div class="toggle ${active ? 'active' : ''}" data-setting="${key}"></div>
    </div>`;
}

/**
 * Generate an integration row.
 */
function integrationRow(name, connected, statusText) {
  const dot = connected ? createStatusDot('online') : createStatusDot('offline');
  const color = connected ? '#639922' : '#888';
  return `
    <div class="setting-row">
      <div>
        <div class="setting-label">${esc(name)}</div>
        <div style="display:flex;align-items:center;gap:4px;margin-top:2px">
          ${dot}
          <span style="font-size:12px;color:${color}">${esc(statusText)}</span>
        </div>
      </div>
      ${connected
        ? '<span style="font-size:12px;color:#aaa">&#10003;</span>'
        : '<span class="btn btn-outline" style="font-size:11px;padding:4px 10px">Connect</span>'}
    </div>`;
}

/**
 * Wire up toggle click events.
 */
function wireToggles(container) {
  container.querySelectorAll('.toggle[data-setting]').forEach(toggle => {
    toggle.addEventListener('click', () => {
      const key = toggle.dataset.setting;
      settingsState[key] = !settingsState[key];
      toggle.classList.toggle('active', settingsState[key]);
    });
  });
}

/**
 * Wire up the emergency lockdown button.
 */
function wireLockdown(container) {
  const btn = container.querySelector('#btn-lockdown');
  if (!btn) return;
  btn.addEventListener('click', () => {
    if (!confirm('Emergency Lockdown: Freeze all processes?')) return;
    if (window.tgSendData) {
      window.tgSendData({ action: 'lockdown' });
    }
    btn.textContent = 'Lockdown initiated';
    btn.disabled = true;
    btn.style.opacity = '0.5';
  });
}
