/**
 * Fosved Office Mini App — API Module
 * Fetch wrapper with error handling for all backend calls.
 * Base URL is empty string (relative paths, served via reverse_proxy → llm_proxy).
 */

const BASE_URL = '';

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

const API = {
  /**
   * GET request. Returns parsed JSON (or text for HTML responses).
   * @param {string} path — e.g. '/api/dashboard'
   * @param {Object} [params] — optional query params
   */
  async get(path, params) {
    const url = BASE_URL + path + buildQuery(params);
    const response = await fetch(url, {
      method: 'GET',
      headers: buildHeaders(),
      credentials: 'same-origin',
    });
    return parseResponse(response);
  },

  /**
   * POST request. Sends JSON body, returns parsed JSON.
   * @param {string} path — e.g. '/api/narads/:id/approve'
   * @param {Object} [data] — request body
   */
  async post(path, data) {
    const url = BASE_URL + path;
    const response = await fetch(url, {
      method: 'POST',
      headers: buildHeaders(),
      credentials: 'same-origin',
      body: JSON.stringify(data ?? {}),
    });
    return parseResponse(response);
  },

  // ---- Convenience shortcuts ----

  dashboard:     ()        => API.get('/api/dashboard'),
  dept:          (slug)    => API.get('/api/dept/' + encodeURIComponent(slug)),
  models:        ()        => API.get('/api/models'),
  economics:     ()        => API.get('/api/economics'),
  narads:        ()        => API.get('/api/narads'),
  naradApprove:  (id)      => API.post('/api/narads/' + encodeURIComponent(id) + '/approve'),
  naradReject:   (id)      => API.post('/api/narads/' + encodeURIComponent(id) + '/reject'),
  adminStatus:   ()        => API.get('/api/admin/status'),

  /**
   * @param {string} [q] — search query
   * @param {string} [dept] — department filter
   */
  archive:       (q, dept) => API.get('/api/archive', { q: q || '', dept: dept || '' }),

  /**
   * Fetch a full HTML report (returns HTML string, not JSON).
   * @param {string} id — report ID
   */
  reportHtml:    (id)      => API.get('/miniapp/' + encodeURIComponent(id)),
};

// Make API globally available for dynamically imported screen modules
window.API = API;

export default API;
export { API, ApiError };
