const API = (() => {
  const BASE = window.location.origin;
  async function get(path) {
    const r = await fetch(BASE + path);
    if (!r.ok) throw new Error('API ' + r.status);
    return r.json();
  }
  async function post(path, body) {
    const r = await fetch(BASE + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error('API ' + r.status);
    return r.json();
  }
  return {
    dashboard: () => get('/api/dashboard'),
    dept: (slug) => get('/api/dept/' + slug),
    models: () => get('/api/models'),
    economics: () => get('/api/economics'),
    narads: () => get('/api/narads'),
    naradApprove: (id) => post('/api/narads/' + id + '/approve'),
    naradReject: (id) => post('/api/narads/' + id + '/reject'),
    archive: (q, dept) => {
      const params = new URLSearchParams();
      if (q) params.set('q', q);
      if (dept) params.set('dept', dept);
      return get('/api/archive?' + params.toString());
    },
    adminStatus: () => get('/api/admin/status'),
  };
})();
