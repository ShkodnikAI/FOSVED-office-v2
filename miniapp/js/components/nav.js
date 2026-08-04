/**
 * FOSVED Mini App — Navigation Component v2
 * Bottom nav + sidebar active state + more dropdown
 */

const ROUTE_MAP = {
  '/': 'Главная',
  '/archive': 'Архив',
  '/chat': 'Чат',
  '/models': 'Модели',
  '/settings': 'Настройки',
  '/narads': 'Наряды',
  '/economics': 'Экономика',
};

export function updateNavActive(route) {
  const baseRoute = '/' + (route.split('/')[1] || '');

  // Bottom nav
  document.querySelectorAll('.bottom-nav-v2 .nav-item').forEach(btn => {
    const r = btn.dataset.route;
    if (!r) return;
    const isActive = r === baseRoute || (r === '/' && baseRoute === '/');
    btn.classList.toggle('active', isActive);
  });

  // Sidebar
  document.querySelectorAll('.sidebar-item').forEach(item => {
    const r = item.dataset.route;
    if (!r) return;
    const isActive = r === baseRoute || (r === '/' && baseRoute === '/');
    item.classList.toggle('active', isActive);
  });

  // More dropdown highlight
  document.querySelectorAll('.more-item').forEach(item => {
    const r = item.dataset.route;
    if (!r) return;
    item.style.background = (r === baseRoute) ? 'var(--c-bg)' : '';
  });
}
