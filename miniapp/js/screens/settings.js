/**
 * FOSVED Mini App — Settings Screen (/settings)
 */

import { esc } from '../app.js';

const SETTINGS_GROUPS = [
  {
    title: 'ИНТЕРФЕЙС',
    items: [
      { id: 'dark_theme', name: 'Тёмная тема', desc: 'Переключить оформление', icon: '🌙', iconBg: '#f0f0f0', type: 'toggle', default: false },
      { id: 'landscape', name: 'Горизонтальный режим', desc: 'Таблет / ландшафт', icon: '📱', iconBg: '#E3F2FD', type: 'toggle', default: false },
      { id: 'font_size', name: 'Размер шрифта', icon: '🔤', iconBg: '#E3F2FD', type: 'select', value: 'Средний', options: ['Маленький','Средний','Большой'] },
      { id: 'language', name: 'Язык', icon: '🌍', iconBg: '#E8F5E9', type: 'select', value: 'Русский', options: ['Русский','English'] },
    ]
  },
  {
    title: 'ГОЛОС',
    items: [
      { id: 'tts_yana', name: 'Голос Яны', desc: 'Озвучка ответов Яны', icon: '👩', iconBg: '#FFF3E0', type: 'toggle', default: true },
      { id: 'tts_depts', name: 'Голос отделов', desc: 'Озвучка ответов отделов', icon: '🗣', iconBg: '#E8F5E9', type: 'toggle', default: false },
      { id: 'tts_speed', name: 'Скорость речи', icon: '⚡', iconBg: '#F3E5F5', type: 'select', value: '1.0x', options: ['0.5x','0.75x','1.0x','1.25x','1.5x'] },
    ]
  },
  {
    title: 'УВЕДОМЛЕНИЯ',
    items: [
      { id: 'push', name: 'Push-уведомления', desc: 'Алерты и статусы', icon: '🔔', iconBg: '#FFF3E0', type: 'toggle', default: true },
      { id: 'sound', name: 'Звук', desc: 'При новых сообщениях', icon: '🔊', iconBg: '#F3E5F5', type: 'toggle', default: false },
      { id: 'vibration', name: 'Вибрация', icon: '📳', iconBg: '#E8F5E9', type: 'toggle', default: true },
    ]
  },
  {
    title: 'СИСТЕМА',
    items: [
      { id: 'autoupdate', name: 'Автообновление', desc: 'Проверка при запуске', icon: '🔄', iconBg: '#E3F2FD', type: 'toggle', default: true },
      { id: 'data_saver', name: 'Экономия трафика', desc: 'Сжимать изображения', icon: '💾', iconBg: '#FFF3E0', type: 'toggle', default: false },
      { id: 'cache', name: 'Кэш', desc: '12.4 MB использовано', icon: '📊', iconBg: '#E8F5E9', type: 'action' },
    ]
  },
];

export async function render(container) {
  let html = `<div class="topbar"><div class="topbar-title">Настройки</div></div>`;
  html += `<div class="screen-scroll">`;

  for (const group of SETTINGS_GROUPS) {
    html += `<div class="section-title">${esc(group.title)}</div>`;
    html += `<div class="settings-group">`;
    for (const item of group.items) {
      const saved = localStorage.getItem(`fosved_${item.id}`);
      const isOn = saved !== null ? saved === '1' : item.default;

      html += `<div class="setting-row" data-id="${esc(item.id)}" data-type="${esc(item.type)}">`;
      html += `  <div class="setting-icon-label">`;
      html += `    <div class="setting-icon" style="background:${esc(item.iconBg || '#f0f0f0')}">${item.icon}</div>`;
      html += `    <div><div class="setting-name">${esc(item.name)}</div>${item.desc ? `<div class="setting-desc">${esc(item.desc)}</div>` : ''}</div>`;
      html += `  </div>`;

      if (item.type === 'toggle') {
        html += `  <div class="toggle${isOn ? ' on' : ''}" data-id="${esc(item.id)}"></div>`;
      } else if (item.type === 'select') {
        html += `  <div class="setting-value">${esc(item.value)} ></div>`;
      } else if (item.type === 'action') {
        html += `  <div class="setting-chevron">></div>`;
      }

      html += `</div>`;
    }
    html += `</div>`;
  }

  html += `<button class="danger-btn" id="clear-cache">🗑 Очистить кэш и данные</button>`;
  html += `<div class="version">FOSVED Office v2.0.1<br>build 2026.07.30</div>`;
  html += `</div>`;

  container.innerHTML = html;

  // Wire up toggles
  container.querySelectorAll('.toggle').forEach(toggle => {
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = toggle.dataset.id;
      const on = toggle.classList.toggle('on');
      localStorage.setItem(`fosved_${id}`, on ? '1' : '0');

      // Apply landscape mode immediately
      if (id === 'landscape') {
        document.body.classList.toggle('landscape-mode', on);
      }
    });
  });

  // Wire up select rows
  container.querySelectorAll('[data-type="select"]').forEach(row => {
    row.addEventListener('click', () => {
      const id = row.dataset.id;
      alert(`Выбор опции: ${id}`);
    });
  });

  // Wire up action rows
  container.querySelectorAll('[data-type="action"]').forEach(row => {
    row.addEventListener('click', () => {
      const id = row.dataset.id;
      if (id === 'cache') {
        alert('Кэш: 12.4 MB
Нажмите "Очистить кэш" для удаления');
      }
    });
  });

  // Clear cache
  container.querySelector('#clear-cache').addEventListener('click', () => {
    if (confirm('Очистить кэш и локальные данные?')) {
      localStorage.clear();
      alert('Кэш очищен. Перезагрузите приложение.');
    }
  });
}
