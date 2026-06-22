(async function() {
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) { tg.ready(); tg.expand(); tg.setHeaderColor('#F8F7F4'); tg.setBackgroundColor('#F8F7F4'); }
  const container = document.getElementById('screen-container');
  let currentRoute = '';
  function navigate(route) { window.location.hash = route; }
  window.addEventListener('hashchange', () => { renderScreen(location.hash.slice(1) || '/'); });
  if (tg) {
    tg.BackButton.show();
    tg.BackButton.onClick(() => { if (currentRoute !== '/') history.back(); });
  }
  window.tgSendData = (data) => { if (tg) tg.sendData(JSON.stringify(data)); };

  function updateNavActive(route) {
    document.querySelectorAll('.bottom-nav-item, .sidebar-item[data-route]').forEach(el => {
      el.classList.toggle('active', el.dataset.route === route || (el.dataset.route === '/chat' && route.startsWith('/chat')) || (el.dataset.route === '/dept/' && route.startsWith('/dept/')));
    });
  }
  function setLoading(show) { container.innerHTML = show ? '<div style="text-align:center;padding:60px;color:#aaa">Loading...</div>' : ''; }
  function setError(msg) { container.innerHTML = '<div style="text-align:center;padding:60px;color:#E24B4A">' + msg + '</div>'; }
  async function loadScreen(name) { try { return await import('./screens/' + name + '.js'); } catch(e) { console.error('Failed:', name, e); return null; } }

  async function renderScreen(route) {
    currentRoute = route; updateNavActive(route);
    const screens = { '/': 'dashboard', '/settings': 'settings', '/models': 'models', '/economics': 'economics', '/narads': 'narads', '/archive': 'archive' };
    if (route.startsWith('/dept/')) return (await loadScreen('dept')).render(container, route.slice(6));
    if (route.startsWith('/chat')) return (await loadScreen('chat')).render(container, route);
    if (route.startsWith('/report/')) return (await loadScreen('report')).render(container, route.slice(8));
    const screen = screens[route] || 'dashboard';
    setLoading(true);
    try { const mod = await loadScreen(screen); if (mod && mod.render) mod.render(container); } catch(e) { setError(screen + ' error'); }
  }
  renderScreen(location.hash.slice(1) || '/');
})();
