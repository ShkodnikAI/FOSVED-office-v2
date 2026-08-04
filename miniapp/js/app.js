/**
 * FOSVED Office Mini App — Main Application v2
 * Hash-based SPA router + Telegram WebApp + orientation
 */

import { updateNavActive } from './components/nav.js';
import API from './api.js';
window.API = API;

const tg = window.Telegram?.WebApp || null;

function initTelegram() {
  if (!tg) return;
  tg.ready();
  tg.expand();
  tg.setHeaderColor('#F8F7F4');
  tg.setBackgroundColor('#F8F7F4');
  tg.enableClosingConfirmation();
}

function setupBackButton(route) {
  if (!tg) return;
  if (route === '/') { tg.BackButton.hide(); return; }
  tg.BackButton.show();
  tg.BackButton.onClick(() => { if (route !== '/') history.back(); });
}

window.navigate = (hash) => { window.location.hash = hash; };
window.goBack = () => { history.back(); };
window.tgSendData = (data) => { if (tg) tg.sendData(JSON.stringify(data)); };

export function esc(str) {
  if (str == null) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

const container = document.getElementById('screen-container');
let currentRoute = '';

function setLoading(show) {
  container.innerHTML = show
    ? `<div class="loading"><div style="width:28px;height:28px;border:3px solid #e0e0e0;border-top-color:#C9A84C;border-radius:50%;animation:spin .8s linear infinite"></div><style>@keyframes spin{to{transform:rotate(360deg)}}</style>Загрузка...</div>`
    : '';
}

function setError(msg, detail) {
  container.innerHTML = `<div class="empty-state"><div style="font-size:28px;margin-bottom:12px">⚠️</div><div style="color:#E24B4A;font-size:15px;font-weight:500">${esc(msg)}</div>${detail ? `<div style="color:#888;font-size:13px;margin-top:8px">${esc(detail)}</div>` : ''}<button class="btn btn-primary" style="margin-top:20px" onclick="location.reload()">Повторить</button></div>`;
}

const screenCache = {};

async function loadScreen(name) {
  if (screenCache[name]) return screenCache[name];
  try {
    const mod = await import('./screens/' + name + '.js');
    if (mod?.render) { screenCache[name] = mod; return mod; }
  } catch (e) { console.error(`[Router] Failed to load screen: ${name}`, e); }
  return null;
}

const ROUTES = {
  '/': 'dashboard',
  '/settings': 'settings',
  '/models': 'models',
  '/economics': 'economics',
  '/narads': 'narads',
  '/archive': 'archive',
  '/chat': 'chat',
  '/report': 'report',
};

function parseRoute(raw) {
  const path = (raw || '').startsWith('#') ? raw.slice(1) : raw;
  const parts = path.split('/').filter(Boolean);
  return { route: '/' + (parts[0] || ''), params: parts.slice(1) };
}

async function renderScreen(routePath) {
  const { route, params } = parseRoute(routePath);
  const fullRoute = route + (params.length ? '/' + params.join('/') : '');
  currentRoute = fullRoute;

  updateNavActive(fullRoute);
  setupBackButton(fullRoute);
  setLoading(true);

  try {
    if (route === '/dept' && params[0]) {
      const mod = await loadScreen('dept');
      return mod?.render(container, params[0]);
    }
    if (route === '/chat') {
      const mod = await loadScreen('chat');
      return mod?.render(container, params[0] || null);
    }
    if (route === '/report' && params[0]) {
      const mod = await loadScreen('report');
      return mod?.render(container, params[0]);
    }

    const screenName = ROUTES[route] || 'dashboard';
    const mod = await loadScreen(screenName);
    if (mod?.render) return mod.render(container);

    setError('Экран не найден', route);
  } catch (e) {
    console.error('[Router] Error:', e);
    setError('Ошибка загрузки', e.message);
  }
}

function handleHashChange() { renderScreen(location.hash || '/'); }
window.addEventListener('hashchange', handleHashChange);

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-nav]');
  if (el) { e.preventDefault(); const t = el.dataset.nav; if (t) location.hash = t; }
  const routeEl = e.target.closest('[data-route]');
  if (routeEl && !routeEl.closest('[data-nav]')) {
    const r = routeEl.dataset.route;
    if (r) location.hash = r;
  }
});

// Orientation handling
const mql = window.matchMedia('(orientation:landscape)');
function handleOrient(e) {
  document.documentElement.classList.toggle('landscape-mode', e.matches);
}
mql.addEventListener('change', handleOrient);
handleOrient(mql);

// More menu toggle
document.addEventListener('click', (e) => {
  const moreBtn = e.target.closest('#nav-more-btn');
  const moreMenu = document.getElementById('more-menu');
  if (moreBtn && moreMenu) {
    moreMenu.style.display = moreMenu.style.display === 'none' ? 'block' : 'none';
    e.stopPropagation();
  } else if (moreMenu && !e.target.closest('#more-menu')) {
    moreMenu.style.display = 'none';
  }
});

initTelegram();
handleHashChange();
