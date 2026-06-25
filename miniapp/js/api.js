/**
 * Fosved Office Mini App — API Module
 * Fetch wrapper with error handling for all backend calls.
 * Base URL is empty string (relative paths, served via reverse_proxy → llm_proxy).
 *
 * Set USE_MOCKS = true to return static mock data instead of real fetch requests.
 */

const BASE_URL = '';
const USE_MOCKS = true;

// ---------------------------------------------------------------------------
// Error class & helpers
// ---------------------------------------------------------------------------

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

function buildHeaders(custom = {}) {
  return {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    ...custom,
  };
}

function buildQuery(params) {
  if (!params || typeof params !== 'object') return '';
  const parts = [];
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') {
      parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(v));
    }
  }
  return parts.length ? '?' + parts.join('&') : '';
}

async function parseResponse(response) {
  const contentType = response.headers.get('content-type') || '';
  if (!response.ok) {
    let errorData;
    try {
      errorData = await response.json();
    } catch {
      errorData = await response.text().catch(() => null);
    }
    throw new ApiError(
      errorData?.error || errorData?.message || `HTTP ${response.status}`,
      response.status,
      errorData,
    );
  }
  if (contentType.includes('text/html')) {
    return response.text();
  }
  return response.json();
}

// ---------------------------------------------------------------------------
// Real fetch layer
// ---------------------------------------------------------------------------

async function realGet(path, params) {
  const url = BASE_URL + path + buildQuery(params);
  const response = await fetch(url, {
    method: 'GET',
    headers: buildHeaders(),
    credentials: 'same-origin',
  });
  return parseResponse(response);
}

async function realPost(path, data) {
  const url = BASE_URL + path;
  const response = await fetch(url, {
    method: 'POST',
    headers: buildHeaders(),
    credentials: 'same-origin',
    body: JSON.stringify(data ?? {}),
  });
  return parseResponse(response);
}

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const MOCK = {
  dashboard: {
    status: 'ok',
    kpis: { tasks: 247, cost_today: '\u20AC0.74', rating: '4.2', reports: 38, tasks_week: 812 },
    alerts: [
      { type: 'red', title: 'Grok 2 \u2014 \u043B\u0438\u043C\u0438\u0442 \u0438\u0441\u0447\u0435\u0440\u043F\u0430\u043D.', subtitle: '\u0417\u0430\u0434\u0430\u0447\u0438 \u043F\u0435\u0440\u0435\u043A\u043B\u044E\u0447\u0435\u043D\u044B \u043D\u0430 Claude' },
      { type: 'green', title: '\u0410\u0434\u043C\u0438\u043D: 2 \u0431\u0430\u0433\u0430 \u0438\u0441\u043F\u0440\u0430\u0432\u043B\u0435\u043D\u044B \u0437\u0430 \u043D\u043E\u0447\u044C.', subtitle: 'Code health: 7.2' },
    ],
    depts: [
      { slug: 'osp', name: '\u041E\u0421\u041F \u2014 \u0421\u0442\u0440\u0430\u0442\u0435\u0433\u0438\u0447\u0435\u0441\u043A\u0438\u0439 \u0430\u043D\u0430\u043B\u0438\u0437', description: '\u0421\u0442\u0440\u0430\u0442\u0435\u0433\u0438\u0447\u0435\u0441\u043A\u0438\u0439 \u0430\u043D\u0430\u043B\u0438\u0437', status: 'active', calls: 12, rating: '4.5', color: { accent: '#dc2626', start: '#b91c1c', end: '#7f1d1d' } },
      { slug: 'lz', name: '\u041B\u0417 \u2014 \u041B\u0430\u0431\u043E\u0440\u0430\u0442\u043E\u0440\u0438\u044F \u0437\u043D\u0430\u043D\u0438\u0439', description: '\u041B\u0430\u0431\u043E\u0440\u0430\u0442\u043E\u0440\u0438\u044F \u0437\u043D\u0430\u043D\u0438\u0439', status: 'active', calls: 8, rating: '4.1', color: { accent: '#0891b2', start: '#0e7490', end: '#164e63' } },
      { slug: 'marketing', name: '\u041C\u0430\u0440\u043A\u0435\u0442\u0438\u043D\u0433 \u2014 \u0418\u0441\u0441\u043B\u0435\u0434\u043E\u0432\u0430\u043D\u0438\u0435', description: '\u0418\u0441\u0441\u043B\u0435\u0434\u043E\u0432\u0430\u043D\u0438\u0435', status: 'active', calls: 5, rating: '3.2', color: { accent: '#ea580c', start: '#c2410c', end: '#7c2d12' } },
      { slug: 'finance', name: '\u0424\u0438\u043D\u0430\u043D\u0441\u044B \u2014 \u0410\u043D\u0430\u043B\u0438\u0437', description: '\u0410\u043D\u0430\u043B\u0438\u0437', status: 'active', calls: 7, rating: '4.0', color: { accent: '#16a34a', start: '#15803d', end: '#14532d' } },
      { slug: 'legal', name: '\u042E\u0440\u0438\u0441\u0442 \u2014 \u041F\u0440\u0430\u0432\u043E', description: '\u041F\u0440\u0430\u0432\u043E', status: 'active', calls: 3, rating: '3.8', color: { accent: '#64748b', start: '#475569', end: '#1e293b' } },
      { slug: 'dev', name: 'Dev \u2014 \u0420\u0430\u0437\u0440\u0430\u0431\u043E\u0442\u043A\u0430', description: '\u0420\u0430\u0437\u0440\u0430\u0431\u043E\u0442\u043A\u0430', status: 'active', calls: 15, rating: '4.3', color: { accent: '#2563eb', start: '#1d4ed8', end: '#1e3a8a' } },
      { slug: 'design', name: 'Design \u2014 \u0414\u0438\u0437\u0430\u0439\u043D', description: '\u0414\u0438\u0437\u0430\u0439\u043D', status: 'active', calls: 4, rating: '4.6', color: { accent: '#ec4899', start: '#be185d', end: '#831843' } },
      { slug: 'qa', name: 'QA \u2014 \u0422\u0435\u0441\u0442\u0438\u0440\u043E\u0432\u0430\u043D\u0438\u0435', description: '\u0422\u0435\u0441\u0442\u0438\u0440\u043E\u0432\u0430\u043D\u0438\u0435', status: 'active', calls: 6, rating: '3.9', color: { accent: '#65a30d', start: '#4d7c0f', end: '#365314' } },
      { slug: 'visual', name: 'Visual \u2014 \u0412\u0438\u0437\u0443\u0430\u043B', description: '\u0412\u0438\u0437\u0443\u0430\u043B', status: 'idle', calls: 2, rating: '3.5', color: { accent: '#a855f7', start: '#7e22ce', end: '#581c87' } },
      { slug: 'engineering', name: 'Engineering \u2014 \u0418\u043D\u0436\u0435\u043D\u0435\u0440\u0438\u044F', description: '\u0418\u043D\u0436\u0435\u043D\u0435\u0440\u0438\u044F', status: 'active', calls: 9, rating: '4.1', color: { accent: '#78716c', start: '#44403c', end: '#292524' } },
      { slug: 'kavalnya', name: '\u041A\u0430\u0432\u0430\u043B\u044C\u043D\u044F \u2014 \u041A\u0430\u0432\u0430\u043B\u0435\u0440\u0438\u044F', description: '\u041A\u0430\u0432\u0430\u043B\u0435\u0440\u0438\u044F', status: 'idle', calls: 1, rating: '3.0', color: { accent: '#d97706', start: '#b45309', end: '#78350f' } },
      { slug: 'expert', name: 'Expert \u2014 \u042D\u043A\u0441\u043F\u0435\u0440\u0442\u0438\u0437\u0430', description: '\u042D\u043A\u0441\u043F\u0435\u0440\u0442\u0438\u0437\u0430', status: 'active', calls: 10, rating: '4.4', color: { accent: '#4f46e5', start: '#3730a3', end: '#1e1b4b' } },
    ],
    admin: { nodes: 847, edges: 2341, issues: 3, proposals: 1, code_health: '7.2' },
  },

  dept: {
    status: 'ok',
    name: '\u041E\u0421\u041F \u2014 \u0421\u0442\u0440\u0430\u0442\u0435\u0433\u0438\u0447\u0435\u0441\u043A\u0438\u0439 \u0430\u043D\u0430\u043B\u0438\u0437',
    color: { start: '#b91c1c', end: '#7f1d1d', accent: '#dc2626' },
    kpis: { tasks: 12, rating: '4.5', cost_today: '\u20AC0.32' },
    tasks: [
      { text: '\u0410\u043D\u0430\u043B\u0438\u0437 AI-\u0440\u0435\u0433\u0443\u043B\u0438\u0440\u043E\u0432\u0430\u043D\u0438\u044F \u0415\u0421', created: '14:32', depth: 3, stars: 4 },
      { text: '\u041F\u0440\u043E\u0433\u043D\u043E\u0437 \u0440\u044B\u043D\u043A\u0430 EdTech', created: '\u0432\u0447\u0435\u0440\u0430', depth: 2, stars: 5 },
    ],
    skills: ['decomp.', 'calibrate', 'ACH', 'cantill.', 'source-triangul.'],
    corrections: [{ type: 'TOO_GENERAL', text: '\u041D\u0443\u0436\u043D\u0430 \u043A\u043E\u043D\u043A\u0440\u0435\u0442\u0438\u043A\u0430 \u0432 \u0432\u044B\u0432\u043E\u0434\u0430\u0445', created: '2 \u0434\u043D\u044F \u043D\u0430\u0437\u0430\u0434' }],
    observations: [{ topic: 'AI-\u0440\u0435\u0433\u0443\u043B\u0438\u0440\u043E\u0432\u0430\u043D\u0438\u0435 \u0415\u0421', freq: '\u0435\u0436\u0435\u043D\u0435\u0434\u0435\u043B\u044C\u043D\u043E', last: '3\u0434' }],
    model: 'GLM 4.6',
    provider: 'Z.ai',
    override: null,
  },

  models: {
    status: 'ok',
    models: [
      { key: 'ZA', name: 'GLM 4.6', label: 'Z.ai \u00B7 \u043F\u0440\u0438\u043E\u0440\u0438\u0442\u0435\u0442\u043D\u0430\u044F', status: 'active', tier: 'priority', usage: 1, health: 100, limit: 10000, used: 120 },
      { key: 'CL', name: 'Claude Sonnet', label: 'Anthropic \u00B7 \u043F\u043B\u0430\u0442\u043D\u0430\u044F', status: 'active', tier: 'paid', usage: 1, health: 100, limit: 1000, used: 12 },
      { key: 'GR', name: 'Grok 3', label: 'xAI \u00B7 \u0431\u0435\u0441\u043F\u043B\u0430\u0442\u043D\u044B\u0439 \u043B\u0438\u043C\u0438\u0442', status: 'limited', tier: 'free_limit', usage: 100, health: 100, limit: 500, used: 500 },
      { key: 'DS', name: 'DeepSeek Chat', label: 'DeepSeek \u00B7 \u0434\u0435\u0448\u0451\u0432\u0430\u044F', status: 'active', tier: 'cheap', usage: 1, health: 100 },
      { key: 'GQ', name: 'Groq Llama', label: 'Groq \u00B7 \u0431\u0435\u0441\u043F\u043B\u0430\u0442\u043D\u0430\u044F', status: 'active', tier: 'free', usage: 1, health: 100 },
      { key: 'GP', name: 'GPT-4o', label: 'OpenAI \u00B7 \u043D\u0435 \u043F\u043E\u0434\u043A\u043B\u044E\u0447\u0451\u043D', status: 'no_key', tier: 'special', usage: 0, health: 0 },
    ],
    overrides: { '\u041E\u0421\u041F': 'Claude Opus', '\u041E\u0441\u0442\u0430\u043B\u044C\u043D\u044B\u0435': 'GLM 4.6' },
    analytics: { requests_today: 247, cost_today: '\u20AC0.74', active_providers: 3, avg_latency: 1200, error_rate: 0.3, tokens_today: 184000, cache_hit: 67 },
  },

  economics: {
    status: 'ok',
    periods: { today: '\u20AC0.74', week: '\u20AC4.12', month: '\u20AC18.50' },
    budget: '10.00',
    by_dept: [
      { dept: '\u041E\u0421\u041F', cost: 6.20, color: '#dc2626' },
      { dept: 'Dev', cost: 4.80, color: '#2563eb' },
      { dept: '\u041B\u0417', cost: 3.90, color: '#0891b2' },
      { dept: '\u041C\u0430\u0440\u043A\u0435\u0442\u0438\u043D\u0433', cost: 2.10, color: '#ea580c' },
      { dept: '\u0424\u0438\u043D\u0430\u043D\u0441\u044B', cost: 1.50, color: '#16a34a' },
    ],
    by_provider: [
      { provider: 'GLM 4.6', cost: 8.40 },
      { provider: 'Claude', cost: 5.20 },
      { provider: 'DeepSeek', cost: 3.10 },
      { provider: 'Groq', cost: 1.80 },
    ],
    recommendation: '\u041E\u0421\u041F: \u043F\u0435\u0440\u0435\u0432\u0435\u0441\u0442\u0438 \u0440\u0443\u0442\u0438\u043D\u043D\u044B\u0435 \u0437\u0430\u043F\u0440\u043E\u0441\u044B \u043D\u0430 DeepSeek (\u044D\u043A\u043E\u043D\u043E\u043C\u0438\u044F ~40%). Dev: \u043E\u043F\u0442\u0438\u043C\u0438\u0437\u0438\u0440\u043E\u0432\u0430\u0442\u044C \u043F\u0440\u043E\u043C\u043F\u0442\u044B \u0434\u043B\u044F Claude (\u044D\u043A\u043E\u043D\u043E\u043C\u0438\u044F ~25%).',
  },

  narads: {
    status: 'ok',
    narads: [
      { id: 'narad-1719283746', title: '\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u043A\u043E\u043C\u0430\u043D\u0434\u0443 /schedule', description: '\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C \u043A\u043E\u043C\u0430\u043D\u0434\u0443 /schedule \u0432 \u0410\u0434\u043C\u0438\u043D\u0430', status: 'pending', risk: 'medium', files: 3, created: '5 \u043C\u0438\u043D \u043D\u0430\u0437\u0430\u0434' },
      { id: 'fix-1719281234', title: 'Race condition DeptColor', description: '\u0418\u0441\u043F\u0440\u0430\u0432\u0438\u0442\u044C race condition \u0432 DeptColor', status: 'done', risk: 'low', files: 1, created: '2\u0447 \u043D\u0430\u0437\u0430\u0434' },
      { id: 'narad-1719272345', title: '\u041E\u0431\u043D\u043E\u0432\u0438\u0442\u044C \u043F\u0440\u043E\u0444\u0438\u043B\u044C \u0424\u0438\u043D\u0430\u043D\u0441\u043E\u0432', description: '\u041E\u0431\u043D\u043E\u0432\u0438\u0442\u044C \u0441\u0438\u0441\u0442\u0435\u043C\u043D\u044B\u0439 \u043F\u0440\u043E\u043C\u043F\u0442 \u0424\u0438\u043D\u0430\u043D\u0441\u043E\u0432', status: 'done', risk: 'low', files: 1, created: '5\u0447 \u043D\u0430\u0437\u0430\u0434' },
      { id: 'fix-1719265432', title: '\u0418\u0441\u043F\u0440\u0430\u0432\u0438\u0442\u044C /voice-set', description: '\u041F\u0435\u0440\u0435\u0437\u0430\u043F\u0443\u0441\u043A proxy \u043D\u0435 \u0441\u0440\u0430\u0431\u043E\u0442\u0430\u043B', status: 'failed', risk: 'high', files: 1, created: '\u0432\u0447\u0435\u0440\u0430', error: 'proxy \u043D\u0435 \u043F\u0435\u0440\u0435\u0437\u0430\u043F\u0443\u0449\u0435\u043D' },
    ],
  },

  archive: {
    status: 'ok',
    results: [
      { id: 'doc-osp-001', dept: 'osp', title: '\u0410\u043D\u0430\u043B\u0438\u0437 AI-\u0440\u0435\u0433\u0443\u043B\u0438\u0440\u043E\u0432\u0430\u043D\u0438\u044F \u0415\u0421', created: '2026-06-26 14:32', depth: 3, stars: '4.5', conf: 'high' },
      { id: 'doc-lz-002', dept: 'lz', title: '\u041A\u0432\u0430\u043D\u0442\u043E\u0432\u044B\u0435 \u0432\u044B\u0447\u0438\u0441\u043B\u0435\u043D\u0438\u044F 2026', created: '2026-06-26 11:15', depth: 2, stars: '4.0', conf: 'med' },
      { id: 'doc-fin-003', dept: 'finance', title: 'Cashflow \u043F\u0440\u043E\u0433\u043D\u043E\u0437 Q3', created: '2026-06-25 16:45', depth: 2, stars: '3.5', conf: 'med', disclaimer: true },
      { id: 'doc-osp-004', dept: 'osp', title: '\u041A\u0442\u043E \u0431\u0435\u043D\u0435\u0444\u0438\u0446\u0438\u0430\u0440 AI-\u0433\u043E\u043D\u043A\u0438', created: '2026-06-25 10:20', depth: 3, stars: '5.0', conf: 'high' },
    ],
  },

  reportHtml: `<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>\u041E\u0442\u0447\u0451\u0442</title>
<style>body{font-family:system-ui;max-width:800px;margin:2rem auto;padding:0 1rem;color:#1e293b;line-height:1.7}
h1{font-size:1.5rem;border-bottom:2px solid #e2e8f0;padding-bottom:.5rem}
.meta{color:#64748b;font-size:.85rem;margin-bottom:1.5rem}
section{margin:1.5rem 0}h2{font-size:1.15rem;color:#334155}p{margin:.5rem 0}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.75rem;font-weight:600}
.badge-high{background:#dcfce7;color:#166534}.badge-med{background:#fef9c3;color:#854d0e}
.tag{display:inline-block;background:#f1f5f9;padding:2px 8px;border-radius:4px;font-size:.8rem;margin:2px}
</style></head><body>
<h1>\u0410\u043D\u0430\u043B\u0438\u0437 AI-\u0440\u0435\u0433\u0443\u043B\u0438\u0440\u043E\u0432\u0430\u043D\u0438\u044F \u0415\u0421</h1>
<div class="meta">\u041E\u0421\u041F \u00B7 2026-06-26 14:32 \u00B7 \u0433\u043B\u0443\u0431\u0438\u043D\u0430 3 \u00B7 <span class="badge badge-high">\u0432\u044B\u0441\u043E\u043A\u0430\u044F \u0434\u043E\u0432\u0435\u0440\u0438\u0442\u0435\u043B\u044C\u043D\u043E\u0441\u0442\u044C</span></div>
<section><h2>\u0421\u0443\u043C\u043C\u0430\u0440\u0438</h2><p>\u0415\u0432\u0440\u043E\u043F\u0435\u0439\u0441\u043A\u0438\u0439 \u0441\u043E\u044E\u0437 \u0430\u043A\u0442\u0438\u0432\u043D\u043E \u0440\u0430\u0431\u043E\u0442\u0430\u0435\u0442 \u043D\u0430\u0434 \u0440\u0435\u0433\u0443\u043B\u0438\u0440\u043E\u0432\u0430\u043D\u0438\u0435\u043C \u0438\u0441\u043A\u0443\u0441\u0441\u0442\u0432\u0435\u043D\u043D\u043E\u0433\u043E \u0438\u043D\u0442\u0435\u043B\u043B\u0435\u043A\u0442\u0430. AI Act \u0432\u0441\u0442\u0443\u043F\u0438\u043B \u0432 \u0441\u0438\u043B\u0443 \u0432 2025 \u0433\u043E\u0434\u0443, \u0443\u0441\u0442\u0430\u043D\u0430\u0432\u043B\u0438\u0432\u0430\u044F \u0442\u0440\u0451\u0445\u0443\u0440\u043E\u0432\u043D\u0435\u0432\u0443\u044E \u0441\u0438\u0441\u0442\u0435\u043C\u0443 \u043A\u043B\u0430\u0441\u0441\u0438\u0444\u0438\u043A\u0430\u0446\u0438\u0438 \u0440\u0438\u0441\u043A\u043E\u0432.</p></section>
<section><h2>\u041A\u043B\u044E\u0447\u0435\u0432\u044B\u0435 \u0432\u044B\u0432\u043E\u0434\u044B</h2><p>1. \u0420\u0438\u0441\u043A-\u043E\u0440\u0438\u0435\u043D\u0442\u0438\u0440\u043E\u0432\u0430\u043D\u043D\u044B\u0439 \u043F\u043E\u0434\u0445\u043E\u0434 \u0441\u043E\u0437\u0434\u0430\u0451\u0442 \u043D\u043E\u0432\u044B\u0435 \u0431\u0430\u0440\u044C\u0435\u0440\u044B \u0434\u043B\u044F \u0441\u0442\u0430\u0440\u0442\u0430\u043F\u043E\u0432.</p><p>2. \u0412\u043B\u0430\u0441\u0442\u043D\u044B\u0435 \u043F\u043E\u043B\u043D\u043E\u043C\u043E\u0447\u0438\u044F \u043F\u0440\u0435\u0434\u043F\u043E\u043B\u0430\u0433\u0430\u044E\u0442 \u0430\u0443\u0434\u0438\u0442 \u0438 \u0446\u0438\u0444\u0440\u043E\u0432\u043E\u0439 \u043D\u0430\u0434\u0437\u043E\u0440.</p><p>3. \u0413\u043B\u043E\u0431\u0430\u043B\u044C\u043D\u044B\u0439 \u044D\u0444\u0444\u0435\u043A\u0442 \u00AB\u0411\u0440\u044E\u0441\u0441\u0435\u043B\u044C\u0441\u043A\u043E\u0433\u043E \u044D\u0444\u0444\u0435\u043A\u0442\u0430\u00BB \u043D\u0430 \u043C\u0435\u0436\u0434\u0443\u043D\u0430\u0440\u043E\u0434\u043D\u044B\u0445 \u0440\u044B\u043D\u043A\u0430\u0445.</p></section>
<section><h2>\u0422\u0435\u0433\u0438</h2><div><span class="tag">AI Act</span><span class="tag">\u0415\u0421</span><span class="tag">\u0440\u0435\u0433\u0443\u043B\u0438\u0440\u043E\u0432\u0430\u043D\u0438\u0435</span><span class="tag">\u0440\u0438\u0441\u043A\u0438</span></div></section>
</body></html>`,

  adminStatus: {
    status: 'ok',
    nodes: 847,
    edges: 2341,
    issues: [
      { id: 'iss-1', severity: 'warning', text: 'Grok 3 \u043B\u0438\u043C\u0438\u0442 \u0438\u0441\u0447\u0435\u0440\u043F\u0430\u043D' },
      { id: 'iss-2', severity: 'info', text: 'Cache hit rate \u043D\u0438\u0436\u0435 \u043E\u0431\u044B\u0447\u043D\u043E\u0433\u043E' },
      { id: 'iss-3', severity: 'info', text: '\u041D\u043E\u0432\u044B\u0439 \u043F\u0440\u043E\u0432\u0430\u0439\u0434\u0435\u0440 \u0434\u043E\u0441\u0442\u0443\u043F\u0435\u043D' },
    ],
    proposals: [{ id: 'prop-1', text: '\u0414\u043E\u0431\u0430\u0432\u0438\u0442\u044C /schedule \u043A\u043E\u043C\u0430\u043D\u0434\u0443', votes: 3 }],
    code_health: '7.2',
  },
};

// ---------------------------------------------------------------------------
// Simulated async delay (keeps the mock path feel like a real request)
// ---------------------------------------------------------------------------

function mockDelay(ms = 80) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Public API object
// ---------------------------------------------------------------------------

const API = {
  /**
   * GET request. Returns parsed JSON (or text for HTML responses).
   * @param {string} path — e.g. '/api/dashboard'
   * @param {Object} [params] — optional query params
   */
  async get(path, params) {
    if (USE_MOCKS) {
      await mockDelay();
      return MOCK.dashboard; // fallback — callers should use convenience methods
    }
    return realGet(path, params);
  },

  /**
   * POST request. Sends JSON body, returns parsed JSON.
   * @param {string} path — e.g. '/api/narads/:id/approve'
   * @param {Object} [data] — request body
   */
  async post(path, data) {
    if (USE_MOCKS) {
      await mockDelay();
      return { status: 'ok' };
    }
    return realPost(path, data);
  },

  // ---- Convenience shortcuts ----

  async dashboard() {
    if (USE_MOCKS) { await mockDelay(); return MOCK.dashboard; }
    return API.get('/api/dashboard');
  },

  async dept(slug) {
    if (USE_MOCKS) { await mockDelay(); return { ...MOCK.dept, _slug: slug }; }
    return API.get('/api/dept/' + encodeURIComponent(slug));
  },

  async models() {
    if (USE_MOCKS) { await mockDelay(); return MOCK.models; }
    return API.get('/api/models');
  },

  async economics() {
    if (USE_MOCKS) { await mockDelay(); return MOCK.economics; }
    return API.get('/api/economics');
  },

  async narads() {
    if (USE_MOCKS) { await mockDelay(); return MOCK.narads; }
    return API.get('/api/narads');
  },

  async naradApprove(id) {
    if (USE_MOCKS) {
      await mockDelay();
      const n = MOCK.narads.narads.find(x => x.id === id);
      if (n) n.status = 'done';
      return { status: 'ok', id };
    }
    return API.post('/api/narads/' + encodeURIComponent(id) + '/approve');
  },

  async naradReject(id) {
    if (USE_MOCKS) {
      await mockDelay();
      const n = MOCK.narads.narads.find(x => x.id === id);
      if (n) n.status = 'rejected';
      return { status: 'ok', id };
    }
    return API.post('/api/narads/' + encodeURIComponent(id) + '/reject');
  },

  /**
   * @param {string} [q] — search query
   * @param {string} [dept] — department filter
   */
  async archive(q, dept) {
    if (USE_MOCKS) {
      await mockDelay();
      let results = MOCK.archive.results;
      if (q) {
        const ql = q.toLowerCase();
        results = results.filter(r => r.title.toLowerCase().includes(ql));
      }
      if (dept) {
        results = results.filter(r => r.dept === dept);
      }
      return { status: 'ok', results };
    }
    return API.get('/api/archive', { q: q || '', dept: dept || '' });
  },

  /**
   * Fetch a full HTML report (returns HTML string, not JSON).
   * @param {string} id — report ID
   */
  async reportHtml(id) {
    if (USE_MOCKS) { await mockDelay(); return MOCK.reportHtml; }
    return API.get('/miniapp/' + encodeURIComponent(id));
  },

  async adminStatus() {
    if (USE_MOCKS) { await mockDelay(); return MOCK.adminStatus; }
    return API.get('/api/admin/status');
  },
};

// Make API globally available for dynamically imported screen modules
window.API = API;

export default API;
export { API, ApiError, USE_MOCKS };