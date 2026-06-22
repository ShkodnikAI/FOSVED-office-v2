/**
 * Fosved Office Mini App — Main Application
 * Initializes Telegram WebApp, sets up hash-based SPA router,
 * and delegates rendering to screen modules.
 */

import { updateNavActive } from './components/nav.js';

// ─── Telegram WebApp Setup ────────────────────────────────────────────────

const tg = window.Telegram?.WebApp || null;

function initTelegram() {
  if (!tg) {
    console.warn('Telegram WebApp SDK not detected — running in browser mode.');
    return;
  }
  tg.ready();
  tg.expand();
  tg.setHeaderColor('#F8F7F4');
  tg.setBackgroundColor('#F8F7F4');
  tg.enableClosingConfirmation();
}

function setupBackButton(currentRoute) {
  if (!tg) return;
  const isRoot = currentRoute === '/';
  if (isRoot) {
    tg.BackButton.hide();
  } else {
    tg.BackButton.show();
    tg.BackButton.onClick(() => {
      if (currentRoute !== '/') {
        history.back();
      }
    });
  }
}

// ─── Navigation Helpers (global) ───────────────────────────────────────────

window.navigate = (hash) => { window.location.hash = hash; };
window.goBack = () => { history.back(); };
window.tgSendData = (data) => {
  if (tg) tg.sendData(JSON.stringify(data));
};

// ─── HTML Escape ──────────────────────────────────────────────────────────

function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ─── Screen Container ────────────────────────────────────────────────────

const container = document.getElementById('screen-container');
let currentRoute = '';

function setLoading(show) {
  container.innerHTML = show
    ? `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:80px 20px;color:#aaa">
         <div style="width:32px;height:32px;border:3px solid #e0e0e0;border-top-color:#C9A84C;border-radius:50%;animation:spin 0.8s linear infinite"></div>
         <style>@keyframes spin{to{transform:rotate(360deg)}}</style>
         <div style="margin-top:16px;font-size:13px">Loading...</div>
       </div>`
    : '';
}

function setError(msg, detail = '') {
  container.innerHTML = `
    <div style="text-align:center;padding:60px 20px">
      <div style="font-size:28px;margin-bottom:12px">&#9888;&#65039;</div>
      <div style="color:#E24B4A;font-size:15px;font-weight:500">${esc(msg)}</div>
      ${detail ? `<div style="color:#888;font-size:13px;margin-top:8px">${esc(detail)}</div>` : ''}
      <button class="btn btn-primary" style="margin-top:20px" onclick="location.reload()">Retry</button>
    </div>`;
}

// ─── Screen Loader ───────────────────────────────────────────────────────

const screenCache = {};

async function loadScreen(name) {
  if (screenCache[name]) return screenCache[name];
  try {
    const mod = await import('./screens/' + name + '.js');
    if (mod?.render) {
      screenCache[name] = mod;
      return mod;
    }
  } catch (e) {
    console.error(`[Router] Failed to load screen: ${name}`, e);
  }
  return null;
}

// ─── Route Table ───────────────────────────────────────────────────────────

const ROUTE_TABLE = {
  '/':          'dashboard',
  '/settings':  'settings',
  '/models':    'models',
  '/economics': 'economics',
  '/narads':    'narads',
  '/archive':   'archive',
};

/**
 * Parse the hash into a route object.
 * @param {string} raw — raw hash string, e.g. '#/dept/osp' or ''
 * @returns {{ route: string, params: string[] }}
 */
function parseRoute(raw) {
  const path = raw.startsWith('#') ? raw.slice(1) : raw;
  const parts = path.split('/').filter(Boolean);
  return {
    route: '/' + (parts[0] || ''),
    params: parts.slice(1),
  };
}

// ─── Screen Renderer ──────────────────────────────────────────────────────

async function renderScreen(routePath) {
  const { route, params } = parseRoute(routePath);
  const fullRoute = route + (params.length ? '/' + params.join('/') : '');
  currentRoute = fullRoute;

  updateNavActive(fullRoute);
  setupBackButton(fullRoute);
  setLoading(true);

  try {
    // Parameterized routes
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

    // Static routes
    const screenName = ROUTE_TABLE[route] || 'dashboard';
    const mod = await loadScreen(screenName);
    if (mod?.render) {
      return mod.render(container);
    }

    setError('Screen not found', route);
  } catch (e) {
    console.error('[Router] Error rendering screen:', e);
    setError('Error loading screen', e.message);
  }
}

// ─── Router Events ────────────────────────────────────────────────────────

function handleHashChange() {
  renderScreen(location.hash || '/');
}

window.addEventListener('hashchange', handleHashChange);

// ─── Event Delegation ─────────────────────────────────────────────────────
// Handle clicks on [data-nav] elements for SPA navigation within rendered content

document.addEventListener('click', (e) => {
  const navEl = e.target.closest('[data-nav]');
  if (navEl) {
    e.preventDefault();
    const target = navEl.dataset.nav;
    if (target) location.hash = target;
  }
});

// Handle clicks on chip filters
document.addEventListener('click', (e) => {
  const chip = e.target.closest('.chip[data-value]');
  if (chip && chip.dataset.filterAction) {
    e.preventDefault();
    const fn = window[chip.dataset.filterAction];
    if (typeof fn === 'function') fn(chip.dataset.value);
  }
});

// ─── Initialize ────────────────────────────────────────────────────────────

initTelegram();
handleHashChange();
