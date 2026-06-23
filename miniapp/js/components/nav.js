/**
 * Fosved Office Mini App — Navigation Components
 * Renders bottom nav (mobile) and sidebar (tablet+).
 * Active states are driven by the current route.
 */

/**
 * Tab definitions for the bottom navigation bar.
 */
const NAV_TABS = [
  { route: '/',         label: 'Главная',    iconSvg: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0a1 1 0 01-1-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 01-1 1h-2z' },
  { route: '/chat',     label: 'Чат',        iconSvg: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z' },
  { route: '/models',   label: 'Модели',     iconSvg: 'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
  { route: '/economics', label: 'Экономика', iconSvg: 'M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z' },
  { route: '/settings', label: 'Настройки',  iconSvg: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z' },
];

/**
 * Sidebar menu structure with 3 sections.
 */
const SIDEBAR_SECTIONS = [
  {
    title: 'ОФИС',
    items: [
      { route: '/',         label: 'Главная', dot: '#C9A84C' },
      { route: '/archive',  label: 'Архив',  dot: '#639922' },
    ],
  },
  {
    title: 'КОММУНИКАЦИИ',
    items: [
      { route: '/chat',    label: 'Чат',     dot: '#185FA5' },
      { route: '/narads',  label: 'Наряды',  dot: '#EF9F27' },
    ],
  },
  {
    title: 'СИСТЕМА',
    items: [
      { route: '/models',     label: 'Модели',     dot: '#3730a3' },
      { route: '/economics',  label: 'Экономика',  dot: '#C9A84C' },
      { route: '/settings',   label: 'Настройки',  dot: '#888888' },
    ],
  },
];

/**
 * Check if a route matches a given nav route.
 * Supports prefix matching for parameterized routes.
 */
function isRouteActive(currentRoute, navRoute) {
  if (navRoute === '/') return currentRoute === '/';
  return currentRoute.startsWith(navRoute);
}

/**
 * Render the bottom navigation bar HTML.
 * @param {string} activeRoute — current route path (without #)
 * @returns {string} HTML
 */
export function renderBottomNav(activeRoute = '/') {
  return NAV_TABS.map(tab => {
    const active = isRouteActive(activeRoute, tab.route);
    return `
      <a class="bottom-nav-item${active ? ' active' : ''}"
         data-route="${tab.route}"
         href="#${tab.route}">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="${tab.iconSvg}"/>
        </svg>
        <span>${tab.label}</span>
      </a>`;
  }).join('\n');
}

/**
 * Render the sidebar navigation HTML.
 * @param {string} activeRoute — current route path (without #)
 * @returns {string} HTML
 */
export function renderSidebar(activeRoute = '/') {
  let html = '<div class="sidebar-brand">Fosved <span>Office</span></div>';

  for (const section of SIDEBAR_SECTIONS) {
    html += `<div class="sidebar-section">${section.title}</div>`;
    for (const item of section.items) {
      const active = isRouteActive(activeRoute, item.route);
      html += `
        <a class="sidebar-item${active ? ' active' : ''}"
           data-route="${item.route}"
           href="#${item.route}">
          <span class="sidebar-dot" style="background:${active ? '#C9A84C' : item.dot}"></span>
          ${item.label}
        </a>`;
    }
  }

  return html;
}

/**
 * Update active states on existing nav elements after route change.
 * @param {string} activeRoute — current route path (without #)
 */
export function updateNavActive(activeRoute = '/') {
  document.querySelectorAll('.bottom-nav-item').forEach(el => {
    el.classList.toggle('active', isRouteActive(activeRoute, el.dataset.route));
  });
  document.querySelectorAll('.sidebar-item[data-route]').forEach(el => {
    const route = el.dataset.route;
    el.classList.toggle('active', isRouteActive(activeRoute, route));
    // Update sidebar dot color on active state
    const dot = el.querySelector('.sidebar-dot');
    if (dot) {
      dot.style.background = isRouteActive(activeRoute, route) ? '#C9A84C' : '';
    }
  });
}

export { NAV_TABS, SIDEBAR_SECTIONS };
