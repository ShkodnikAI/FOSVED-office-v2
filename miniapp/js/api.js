/**
 * FOSVED Mini App — API Module v2
 */

const BASE_URL = '';
const USE_MOCKS = false;

const DEPT_NAME_MAP = {
  'Yana': 'Яна',
  'OSP': 'ОСП — Стратегический анализ',
  'Laboratoriya znanii': 'Лаборатория знаний',
  'Tekhnicheskiy preparator': 'Технический препаратор',
  'Finansy': 'Финансы',
  'Razrabotka': 'Разработка',
  'Marketing': 'Маркетинг',
  'Dev': 'Разработка',
  'Design': 'Дизайн',
  'QA': 'Тестирование',
  'Visual': 'Визуал',
  'Engineering': 'Инженерия',
  'Kavalnya': 'Кавальня',
  'Expert': 'Экспертиза',
  'Legal': 'Юрист',
  'Finance': 'Финансы',
};

export function formatRating(r) {
  if (r === 0 || r === '0' || r === null || r === undefined || r === '') return '—';
  return r;
}

export function getDeptDisplayName(dept) {
  if (!dept) return '—';
  if (dept.display_name) return dept.display_name;
  if (DEPT_NAME_MAP[dept.name]) return DEPT_NAME_MAP[dept.name];
  return dept.name;
}


class ApiError extends Error {
  constructor(message, status, data) { super(message); this.name='ApiError'; this.status=status; this.data=data; }
}

function buildHeaders(custom={}) {
  const h={'Accept':'application/json','Content-Type':'application/json',...custom};
  if (window._apiSecret) h['Authorization']='Bearer '+window._apiSecret;
  return h;
}

function buildQuery(params) {
  if (!params) return '';
  const parts=[];
  for (const [k,v] of Object.entries(params)) {
    if (v!==undefined&&v!==null&&v!=='') parts.push(encodeURIComponent(k)+'='+encodeURIComponent(v));
  }
  return parts.length?'?'+parts.join('&'):'';
}

async function parseResponse(r) {
  const ct=r.headers.get('content-type')||'';
  if (!r.ok) {
    let ed; try { ed=await r.json(); } catch { ed=await r.text().catch(()=>null); }
    throw new ApiError(ed?.error||ed?.message||`HTTP ${r.status}`, r.status, ed);
  }
  if (ct.includes('text/html')) return r.text();
  return r.json();
}

async function realGet(path,params) {
  const r=await fetch(BASE_URL+path+buildQuery(params),{method:'GET',headers:buildHeaders(),credentials:'same-origin'});
  return parseResponse(r);
}
async function realPost(path,data) {
  const r=await fetch(BASE_URL+path,{method:'POST',headers:buildHeaders(),credentials:'same-origin',body:JSON.stringify(data??{})});
  return parseResponse(r);
}
async function realPut(path,data) {
  const r=await fetch(BASE_URL+path,{method:'PUT',headers:buildHeaders(),credentials:'same-origin',body:JSON.stringify(data??{})});
  return parseResponse(r);
}
async function realDelete(path) {
  const r=await fetch(BASE_URL+path,{method:'DELETE',headers:buildHeaders(),credentials:'same-origin'});
  return parseResponse(r);
}

function mockDelay(ms=80){return new Promise(r=>setTimeout(r,ms));}

// ── Mock Data ───────────────────────────────────────────────

const DEPT_COMMANDS = {
  osp: [
    { cmd:'/deconstruct', desc:'Деконструкция сложных задач на атомарные компоненты для стратегического анализа', valid:true },
    { cmd:'/awareness', desc:'Фрейм осознанности — проверка когнитивных искажений в аналитических выводах', valid:true },
    { cmd:'/forecast', desc:'Прогнозирование рыночных трендов на основе ACH-анализа и триангуляции источников', valid:true },
    { cmd:'/iw_watchlist', desc:'Мониторинг информационных войн — требует обновления источников', valid:false },
    { cmd:'/calibration', desc:'Калибровка вероятностных оценок по методу Калмана', valid:true },
    { cmd:'/narrative_vs_flows', desc:'Сравнительный анализ нарративов и потоков данных', valid:true },
  ],
  lz: [
    { cmd:'/kb_search', desc:'Поиск по базе знаний с семантическим ранжированием', valid:true },
    { cmd:'/recent_reports', desc:'Вывод последних сгенерированных отчётов по запросу', valid:true },
    { cmd:'/kb_summary', desc:'Сводка знаний — агрегация ключевых концепций из БЗ', valid:true },
    { cmd:'/source_triangulate', desc:'Триангуляция источников для повышения достоверности', valid:true },
  ],
  dev: [
    { cmd:'/deploy_status', desc:'Статус текущего деплоя и CI/CD pipeline', valid:true },
    { cmd:'/bugs', desc:'Актуальный бэклог багов с приоритизацией', valid:true },
    { cmd:'/ci_status', desc:'Состояние непрерывной интеграции и тестов', valid:true },
    { cmd:'/code_review', desc:'Автоматический код-ревью с метриками качества', valid:true },
  ],
  marketing: [
    { cmd:'/audience', desc:'Анализ целевой аудитории и сегментация', valid:true },
    { cmd:'/channels', desc:'Эффективность каналов коммуникации', valid:true },
    { cmd:'/ab_test', desc:'Планирование и анализ A/B тестов', valid:true },
  ],
  finance: [
    { cmd:'/cashflow', desc:'Прогноз денежных потоков на основе текущих данных', valid:true },
    { cmd:'/mrr', desc:'Анализ MRR/ARR метрик подписки', valid:true },
    { cmd:'/budget', desc:'Текущее состояние бюджета и прогноз расходов', valid:true },
  ],
  legal: [
    { cmd:'/contract', desc:'Генерация и анализ договорных документов', valid:true },
    { cmd:'/risk_map', desc:'Карта юридических рисков проекта', valid:true },
    { cmd:'/gdpr', desc:'Проверка соответствия GDPR требованиям', valid:true },
  ],
  design: [
    { cmd:'/design_system', desc:'Актуальное состояние дизайн-системы FOSVED', valid:true },
    { cmd:'/components', desc:'Инвентаризация UI-компонентов и их статус', valid:true },
  ],
  qa: [
    { cmd:'/tests', desc:'Статус тестового покрытия и результаты прогона', valid:true },
    { cmd:'/coverage', desc:'Метрики покрытия кода тестами', valid:true },
  ],
  visual: [
    { cmd:'/infographic', desc:'Генерация инфографики на основе данных', valid:true },
    { cmd:'/presentation', desc:'Создание презентационных материалов', valid:true },
  ],
  engineering: [
    { cmd:'/load', desc:'Мониторинг нагрузки на инфраструктуру', valid:true },
    { cmd:'/uptime', desc:'Uptime метрики и SLA compliance', valid:true },
  ],
  kavalnya: [
    { cmd:'/ops', desc:'Оперативная сводка текущих задач кавальни', valid:true },
    { cmd:'/report', desc:'Формирование оперативного доклада', valid:true },
  ],
  expert: [
    { cmd:'/combat_questions', desc:'Анализ боевых вопросов и контр-аргументов', valid:true },
    { cmd:'/deep_profile', desc:'Глубокий профиль субъекта анализа', valid:true },
    { cmd:'/cross_check', desc:'Перекрёстная проверка фактов и гипотез', valid:true },
  ],
  'tekhnicheskiy-preparator': [
    { cmd:'/parse', desc:'Парсинг и извлечение структурированных данных из неструктурированных источников', valid:true },
    { cmd:'/clean', desc:'Очистка данных от дубликатов, шума и аномалий', valid:true },
    { cmd:'/format', desc:'Форматирование и нормализация данных под стандарты офиса', valid:true },
    { cmd:'/enrich', desc:'Обогащение данных дополнительными источниками и метаданными', valid:true },
  ],
  yana: [
    { cmd:'/schedule', desc:'Управление расписанием, встречами и дедлайнами руководителя', valid:true },
    { cmd:'/brief', desc:'Подготовка брифингов и сводок перед важными решениями', valid:true },
    { cmd:'/delegate', desc:'Распределение задач между отделами с учётом загрузки', valid:true },
    { cmd:'/remind', desc:'Напоминания о ключевых событиях и сроках', valid:true },
  ],
};

const DEPT_MODEL_PRIORITY = {
  osp: [
    { key:'ZA', name:'GLM 4.6', provider:'Z.ai', tier:'priority', valid:true },
    { key:'CL', name:'Claude Sonnet', provider:'Anthropic', tier:'paid', valid:true },
    { key:'DS', name:'DeepSeek V3', provider:'DeepSeek', tier:'cheap', valid:true },
    { key:'GP', name:'GPT-4o', provider:'OpenAI', tier:'special', valid:false },
  ],
  lz: [
    { key:'ZA', name:'GLM 4.6', provider:'Z.ai', tier:'priority', valid:true },
    { key:'DS', name:'DeepSeek V3', provider:'DeepSeek', tier:'cheap', valid:true },
    { key:'CL', name:'Claude Sonnet', provider:'Anthropic', tier:'paid', valid:true },
  ],
  'tekhnicheskiy-preparator': [
    { key:'DS', name:'DeepSeek V3', provider:'DeepSeek', tier:'cheap', valid:true },
    { key:'ZA', name:'GLM 4.6', provider:'Z.ai', tier:'priority', valid:true },
    { key:'GP', name:'GPT-4o', provider:'OpenAI', tier:'special', valid:true },
  ],
  yana: [
    { key:'CL', name:'Claude Sonnet', provider:'Anthropic', tier:'paid', valid:true },
    { key:'ZA', name:'GLM 4.6', provider:'Z.ai', tier:'priority', valid:true },
    { key:'DS', name:'DeepSeek V3', provider:'DeepSeek', tier:'cheap', valid:true },
  ],
};

const MOCK = {
  dashboard: {
    status:'ok',
    kpis:{ tasks:247, cost_today:'€0.74', rating:'4.2', reports:38, tasks_week:812 },
    alerts:[
      { type:'red', title:'Grok 2 — лимит исчерпан.', subtitle:'Задачи переключены на Claude' },
      { type:'green', title:'Админ: 2 бага исправлены за ночь.', subtitle:'Code health: 7.2' },
    ],
    depts:[
      { slug:'osp', name:'ОСП — Стратегический анализ', description:'Стратегический анализ', status:'active', calls:12, rating:'4.5', color:{ accent:'#dc2626', start:'#b91c1c', end:'#7f1d1d' } },
      { slug:'lz', name:'ЛЗ — Лаборатория знаний', description:'Лаборатория знаний', status:'active', calls:8, rating:'4.1', color:{ accent:'#0891b2', start:'#0e7490', end:'#164e63' } },
      { slug:'marketing', name:'Маркетинг — Исследование', description:'Исследование', status:'active', calls:5, rating:'3.2', color:{ accent:'#ea580c', start:'#c2410c', end:'#7c2d12' } },
      { slug:'finance', name:'Финансы — Анализ', description:'Анализ', status:'active', calls:7, rating:'4.0', color:{ accent:'#16a34a', start:'#15803d', end:'#14532d' } },
      { slug:'legal', name:'Юрист — Право', description:'Право', status:'active', calls:3, rating:'3.8', color:{ accent:'#64748b', start:'#475569', end:'#1e293b' } },
      { slug:'dev', name:'Dev — Разработка', description:'Разработка', status:'active', calls:15, rating:'4.3', color:{ accent:'#2563eb', start:'#1d4ed8', end:'#1e3a8a' } },
      { slug:'design', name:'Design — Дизайн', description:'Дизайн', status:'active', calls:4, rating:'4.6', color:{ accent:'#ec4899', start:'#be185d', end:'#831843' } },
      { slug:'qa', name:'QA — Тестирование', description:'Тестирование', status:'active', calls:6, rating:'3.9', color:{ accent:'#65a30d', start:'#4d7c0f', end:'#365314' } },
      { slug:'visual', name:'Visual — Визуал', description:'Визуал', status:'idle', calls:2, rating:'3.5', color:{ accent:'#a855f7', start:'#7e22ce', end:'#581c87' } },
      { slug:'engineering', name:'Engineering — Инженерия', description:'Инженерия', status:'active', calls:9, rating:'4.1', color:{ accent:'#78716c', start:'#44403c', end:'#292524' } },
      { slug:'kavalnya', name:'Кавальня — Кавалерия', description:'Кавалерия', status:'idle', calls:1, rating:'3.0', color:{ accent:'#d97706', start:'#b45309', end:'#78350f' } },
      { slug:'expert', name:'Expert — Экспертиза', description:'Экспертиза', status:'active', calls:10, rating:'4.4', color:{ accent:'#4f46e5', start:'#3730a3', end:'#1e1b4b' } },
      { slug:'tekhnicheskiy-preparator', name:'Технический препаратор', description:'Подготовка данных, парсинг, очистка и структурирование сырых данных для анализа', status:'active', calls:8, rating:'3.7', color:{ accent:'#0ea5e9', start:'#0369a1', end:'#0c4a6e' } },
      { slug:'yana', name:'Яна', description:'Личный ассистент руководителя. Координация, планирование, коммуникации', status:'active', calls:20, rating:'4.8', color:{ accent:'#C9A84C', start:'#b8943f', end:'#8B6914' } },
    ],
    admin:{ nodes:847, edges:2341, issues:3, proposals:1, code_health:'7.2' },
  },

  dept: {
    status:'ok',
    name:'ОСП — Стратегический анализ',
    color:{ start:'#b91c1c', end:'#7f1d1d', accent:'#dc2626' },
    kpis:{ tasks:12, rating:'4.5', cost_today:'€0.32' },
    tasks:[
      { text:'Анализ AI-регулирования ЕС', created:'14:32', depth:3, stars:4 },
      { text:'Прогноз рынка EdTech', created:'вчера', depth:2, stars:5 },
    ],
    skills:['decomp.','calibrate','ACH','cantill.','source-triangul.'],
    corrections:[{ type:'TOO_GENERAL', text:'Нужна конкретика в выводах', created:'2 дня назад' }],
    observations:[{ topic:'AI-регулирование ЕС', freq:'еженедельно', last:'3д' }],
    model:'GLM 4.6',
    provider:'Z.ai',
    override:null,
  },

  models: {
    status:'ok',
    models:[
      { key:'ZA', name:'GLM 4.6', label:'Z.ai · приоритетная', status:'active', tier:'priority', usage:1, health:100, limit:10000, used:120, latency:320, cost:0.004 },
      { key:'CL', name:'Claude Sonnet', label:'Anthropic · платная', status:'active', tier:'paid', usage:1, health:100, limit:1000, used:12, latency:850, cost:0.015 },
      { key:'GR', name:'Grok 3', label:'xAI · бесплатный лимит', status:'limited', tier:'free_limit', usage:100, health:100, limit:500, used:500, latency:1200, cost:0.0 },
      { key:'DS', name:'DeepSeek Chat', label:'DeepSeek · дешёвая', status:'active', tier:'cheap', usage:1, health:100, latency:600, cost:0.001 },
      { key:'GQ', name:'Groq Llama', label:'Groq · бесплатная', status:'active', tier:'free', usage:1, health:100, latency:150, cost:0.0 },
      { key:'GP', name:'GPT-4o', label:'OpenAI · не подключён', status:'no_key', tier:'special', usage:0, health:0, latency:0, cost:0 },
    ],
    overrides:{ 'ОСП':'Claude Opus', 'Остальные':'GLM 4.6' },
    analytics:{ requests_today:247, cost_today:'€0.74', active_providers:3, avg_latency:1200, error_rate:0.3, tokens_today:184000, cache_hit:67 },
  },

  economics: {
    status:'ok',
    periods:{ today:'€0.74', week:'€4.12', month:'€18.50' },
    budget:'10.00',
    by_dept:[
      { dept:'ОСП', cost:6.20, color:'#dc2626' },
      { dept:'Dev', cost:4.80, color:'#2563eb' },
      { dept:'ЛЗ', cost:3.90, color:'#0891b2' },
      { dept:'Маркетинг', cost:2.10, color:'#ea580c' },
      { dept:'Финансы', cost:1.50, color:'#16a34a' },
    ],
    by_provider:[
      { provider:'GLM 4.6', cost:8.40 },
      { provider:'Claude', cost:5.20 },
      { provider:'DeepSeek', cost:3.10 },
      { provider:'Groq', cost:1.80 },
    ],
    recommendation:'ОСП: перевести рутинные запросы на DeepSeek (экономия ~40%). Dev: оптимизировать промпты для Claude (экономия ~25%).',
  },

  narads: {
    status:'ok',
    narads:[
      { id:'narad-1719283746', title:'Добавить команду /schedule', description:'Добавить команду /schedule в Админа', status:'pending', risk:'medium', files:3, created:'5 мин назад' },
      { id:'fix-1719281234', title:'Race condition DeptColor', description:'Исправить race condition в DeptColor', status:'done', risk:'low', files:1, created:'2ч назад' },
      { id:'narad-1719272345', title:'Обновить профиль Финансов', description:'Обновить системный промпт Финансов', status:'done', risk:'low', files:1, created:'5ч назад' },
      { id:'fix-1719265432', title:'Исправить /voice-set', description:'Перезапуск proxy не сработал', status:'failed', risk:'high', files:1, created:'вчера', error:'proxy не перезапущен' },
    ],
  },

  archive: {
    status:'ok',
    results:[
      { id:'doc-osp-001', dept:'osp', title:'Анализ AI-регулирования ЕС', created:'2026-06-26 14:32', depth:3, stars:'4.5', conf:'high' },
      { id:'doc-lz-002', dept:'lz', title:'Квантовые вычисления 2026', created:'2026-06-26 11:15', depth:2, stars:'4.0', conf:'med' },
      { id:'doc-fin-003', dept:'finance', title:'Cashflow прогноз Q3', created:'2026-06-25 16:45', depth:2, stars:'3.5', conf:'med', disclaimer:true },
      { id:'doc-osp-004', dept:'osp', title:'Кто бенефициар AI-гонки', created:'2026-06-25 10:20', depth:3, stars:'5.0', conf:'high' },
    ],
  },

  settings: {
    status:'ok',
    profile:{ name:'Яна', role:'Fosved · Owner', badge:'PREMIUM' },
    yanaVoice:{ messages:true, replies:true, briefing:false, engine:'ru-RU-DmitryNeural', speed:1.0 },
    system:{ darkMode:false, urgentAlerts:true, autoUpdate:true, marketScan:true },
    fallback:{ model:'gpt-4o-mini', maxTokens:4096, temperature:0.7 },
    apiSecret:'sk-fosved-****',
    models:[
      { id:'m1', name:'GLM 4.6', tier:'priority', key:'sk-zai-4x8k2m9p...q7n3' },
      { id:'m2', name:'Claude Sonnet', tier:'paid', key:'sk-ant-9k2m...p4x7' },
      { id:'m3', name:'DeepSeek V3', tier:'cheap', key:'sk-ds-2k9m...x4p1' },
    ],
  },

  reportHtml: `<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><title>Отчёт</title>
<style>body{font-family:system-ui;max-width:800px;margin:2rem auto;padding:0 1rem;color:#1e293b;line-height:1.7}h1{font-size:1.5rem;border-bottom:2px solid #e2e8f0;padding-bottom:.5rem}.meta{color:#64748b;font-size:.85rem;margin-bottom:1.5rem}section{margin:1.5rem 0}h2{font-size:1.15rem;color:#334155}p{margin:.5rem 0}.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.75rem;font-weight:600}.badge-high{background:#dcfce7;color:#166534}.badge-med{background:#fef9c3;color:#854d0e}.tag{display:inline-block;background:#f1f5f9;padding:2px 8px;border-radius:4px;font-size:.8rem;margin:2px}</style></head><body>
<h1>Анализ AI-регулирования ЕС</h1><div class="meta">ОСП · 2026-06-26 14:32 · глубина 3 · <span class="badge badge-high">высокая доверительность</span></div>
<section><h2>Суммари</h2><p>Европейский союз активно работает над регулированием искусственного интеллекта. AI Act вступил в силу в 2025 году, устанавливая трёхуровневую систему классификации рисков.</p></section>
<section><h2>Ключевые выводы</h2><p>1. Риск-ориентированный подход создаёт новые барьеры для стартапов.</p><p>2. Властные полномочия предполагают аудит и цифровой надзор.</p><p>3. Глобальный эффект «Брюссельского эффекта» на международных рынках.</p></section>
<section><h2>Теги</h2><div><span class="tag">AI Act</span><span class="tag">ЕС</span><span class="tag">регулирование</span><span class="tag">риски</span></div></section>
</body></html>`,

  adminStatus: {
    status:'ok', nodes:847, edges:2341,
    issues:[
      { id:'iss-1', severity:'warning', text:'Grok 3 лимит исчерпан' },
      { id:'iss-2', severity:'info', text:'Cache hit rate ниже обычного' },
      { id:'iss-3', severity:'info', text:'Новый провайдер доступен' },
    ],
    proposals:[{ id:'prop-1', text:'Добавить /schedule команду', votes:3 }],
    code_health:'7.2',
  },
};

// ── API Object ──────────────────────────────────────────────

const API = {
  async get(path,params) {
    if (USE_MOCKS) { await mockDelay(); return MOCK.dashboard; }
    return realGet(path,params);
  },
  async post(path,data) {
    if (USE_MOCKS) { await mockDelay(); return {status:'ok'}; }
    return realPost(path,data);
  },
  async put(path,data) {
    if (USE_MOCKS) { await mockDelay(); return {status:'ok'}; }
    return realPut(path,data);
  },
  async delete(path) {
    if (USE_MOCKS) { await mockDelay(); return {status:'ok'}; }
    return realDelete(path);
  },

  async dashboard() {
    if (USE_MOCKS) { await mockDelay(); return MOCK.dashboard; }
    return API.get('/api/dashboard');
  },

  async depts() {
    if (USE_MOCKS) { await mockDelay(); return { status:'ok', depts:MOCK.dashboard.depts }; }
    return API.get('/api/depts');
  },

  async dept(slug) {
    if (USE_MOCKS) {
      await mockDelay();
      const d = MOCK.dashboard.depts.find(x => x.slug === slug);
      if (!d) return { status:'error', error:'Отдел не найден' };
      return {
        status:'ok',
        name: d.name,
        color: d.color,
        kpis: { tasks: d.calls, rating: d.rating, cost_today: '€0.32' },
        tasks: MOCK.dept.tasks,
        skills: MOCK.dept.skills,
        corrections: MOCK.dept.corrections,
        observations: MOCK.dept.observations,
        model: 'GLM 4.6',
        provider: 'Z.ai',
        commands: DEPT_COMMANDS[slug] || DEPT_COMMANDS.osp,
        modelPriority: DEPT_MODEL_PRIORITY[slug] || DEPT_MODEL_PRIORITY.osp,
      };
    }
    return API.get('/api/dept/' + encodeURIComponent(slug));
  },

  async getDeptCommands(slug) {
    if (USE_MOCKS) { await mockDelay(); return { status:'ok', commands: DEPT_COMMANDS[slug] || [] }; }
    return API.get('/api/dept/' + encodeURIComponent(slug) + '/commands');
  },

  async getDeptModelPriority(slug) {
    if (USE_MOCKS) { await mockDelay(); return { status:'ok', models: DEPT_MODEL_PRIORITY[slug] || [] }; }
    return API.get('/api/dept/' + encodeURIComponent(slug) + '/model-priority');
  },

  async setDeptModelPriority(slug, order) {
    if (USE_MOCKS) {
      await mockDelay();
      localStorage.setItem('fosved-dept-' + slug + '-models', JSON.stringify(order));
      return { status:'ok' };
    }
    return API.post('/api/dept/' + encodeURIComponent(slug) + '/model-priority', { order });
  },

  async models() {
    if (USE_MOCKS) { await mockDelay(); return MOCK.models; }
    return API.get('/api/models');
  },

  async modelTest(key) {
    if (USE_MOCKS) { await mockDelay(); return { status:'ok', latency: Math.floor(200 + Math.random()*800) }; }
    return API.post('/api/model-test', { key });
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
    if (USE_MOCKS) { await mockDelay(); const n=MOCK.narads.narads.find(x=>x.id===id); if(n)n.status='done'; return {status:'ok',id}; }
    return API.post('/api/narads/'+encodeURIComponent(id)+'/approve');
  },

  async naradReject(id) {
    if (USE_MOCKS) { await mockDelay(); const n=MOCK.narads.narads.find(x=>x.id===id); if(n)n.status='rejected'; return {status:'ok',id}; }
    return API.post('/api/narads/'+encodeURIComponent(id)+'/reject');
  },

  
  async projects() {
    if (USE_MOCKS) return {
      status: 'ok',
      projects: [
        { id:'fosved-v2', name:'FOSVED Office v2', status:'active', description:'Разработка мини-приложения для Telegram WebApp. Интерфейс управления AI-офисом.', repo:'https://github.com/ShkodnikAI/FOSVED-office-v2', servers:['api.fosved.io','ws.fosved.io'], context:'12 чекпоинтов', keys:[{label:'API_KEY_•••Xf7',type:'api'},{label:'GH_PAT_•••SQb',type:'github'},{label:'WS_TOKEN_•••k9m',type:'server'}], depts:['osp','razrabotka','design','qa','visual','engineering'], progress:78 },
        { id:'eu-ai-reg', name:'AI-регулирование ЕС', status:'inprogress', description:'Мониторинг и анализ AI Act, подготовка стратегии соответствия для клиентов.', repo:'https://github.com/ShkodnikAI/eu-ai-reg', servers:['eu-ai.fosved.io'], context:'47 документов', keys:[{label:'EU_API_•••3a2',type:'api'},{label:'CDN_KEY_•••p8q',type:'server'}], depts:['osp','lz','expert','yana'], progress:45 },
        { id:'edtech-q3', name:'EdTech Прогноз Q3', status:'completed', description:'Прогноз рынка образовательных технологий на третий квартал 2026.', repo:'https://github.com/ShkodnikAI/edtech-q3', servers:[], context:'архивирован', keys:[{label:'EDT_API_•••9k1',type:'api'}], depts:['marketing','finansy'], progress:100 },
        { id:'tts-audit', name:'Аудит TTS-системы', status:'paused', description:'Проверка работоспособности TTS-пайплайнов, замена Яндекса на альтернативы.', repo:'https://github.com/ShkodnikAI/tts-audit', servers:['tts.fosved.io'], context:'3 теста', keys:[{label:'TTS_KEY_•••m4n',type:'api'}], depts:['engineering','qa'], progress:12 },
      ]
    };
    return this._get('/api/projects');
  }

  async project(id) {
    if (USE_MOCKS) {
      const projects = [
        { id:'fosved-v2', name:'FOSVED Office v2', status:'active', description:'Разработка мини-приложения для Telegram WebApp. Интерфейс управления AI-офисом с 14 отделами.', progress:78, prompt:'Создать мини-приложение для Telegram WebApp на чистом HTML/CSS/JS. Приложение должно управлять AI-офисом с 14 отделами. Каждый отдел имеет свою модель, команды, задачи. Dashboard показывает KPI, алерты, отчёты. Чат с Яной — центральная точка коммуникации.', repo:'https://github.com/ShkodnikAI/FOSVED-office-v2', servers:['api.fosved.io','ws.fosved.io'], plan_url:'https://notion.so/fosved-v2', keys:[{label:'API_KEY_•••Xf7',type:'api'},{label:'GH_PAT_•••SQb',type:'github'},{label:'WS_TOKEN_•••k9m',type:'server'},{label:'TG_BOT_•••a3b',type:'api'}], plan:[{id:'p1',text:'Архитектура и структура проекта',done:true,assignee:'Dev',date:'25.07'},{id:'p2',text:'Dashboard с KPI и алертами',done:true,assignee:'Design',date:'27.07'},{id:'p3',text:'Список отделов с фильтрами',done:true,assignee:'Dev',date:'28.07'},{id:'p4',text:'Детали отдела + чат',done:false,assignee:'Dev',date:'30.07'},{id:'p5',text:'Модели + Экономика + Проекты',done:false,assignee:'Dev',date:'31.07'},{id:'p6',text:'Тестирование и деплой',done:false,assignee:'QA',date:'02.08'}], files:[{id:'f1',name:'index.html',type:'code',meta:'точка входа · Dev · 29.07',size:'12 KB'},{id:'f2',name:'screens.css',type:'code',meta:'стили экранов · Design · 30.07',size:'8 KB'},{id:'f3',name:'api.js',type:'code',meta:'API-клиент · Dev · 30.07',size:'15 KB'},{id:'f4',name:'FOSVED_CONTEXT.md',type:'doc',meta:'контекст · ОСП · 30.07',size:'4 KB'}], model_stats:[{name:'GLM 4.6',short:'GL',provider:'Z.ai',requests:120,cost:'€0.48',pct:40,color:'linear-gradient(135deg,#16a34a,#15803d)',bar_color:'#16a34a'},{name:'Claude Sonnet',short:'CL',provider:'Anthropic',requests:89,cost:'€1.07',pct:30,color:'linear-gradient(135deg,#7c3aed,#6d28d9)',bar_color:'#7c3aed'},{name:'DeepSeek V3',short:'DS',provider:'DeepSeek',requests:245,cost:'€0.25',pct:25,color:'linear-gradient(135deg,#ea580c,#c2410c)',bar_color:'#ea580c'},{name:'GPT-4o',short:'GP',provider:'OpenAI',requests:0,cost:'€0.00',pct:0,color:'linear-gradient(135deg,#64748b,#475569)',bar_color:'#64748b'}], available_models:[{key:'ZA',name:'GLM 4.6',short:'GL',provider:'Z.ai',tier:'priority',valid:true,enabled:true,color:'linear-gradient(135deg,#16a34a,#15803d)'},{key:'CL',name:'Claude Sonnet',short:'CL',provider:'Anthropic',tier:'paid',valid:true,enabled:true,color:'linear-gradient(135deg,#7c3aed,#6d28d9)'},{key:'DS',name:'DeepSeek V3',short:'DS',provider:'DeepSeek',tier:'cheap',valid:true,enabled:true,color:'linear-gradient(135deg,#ea580c,#c2410c)'},{key:'GP',name:'GPT-4o',short:'GP',provider:'OpenAI',tier:'special',valid:false,enabled:false,color:'linear-gradient(135deg,#64748b,#475569)'}] },
      ];
      const project = projects.find(p => p.id === id);
      if (!project) return { status: 'error', error: 'Проект не найден' };
      return { status: 'ok', project };
    }
    return this._get(`/api/projects/${id}`);
  }

  async updateProjectModel(projectId, modelKey, enabled) {
    if (USE_MOCKS) return { status: 'ok' };
    return this._post(`/api/projects/${projectId}/models`, { modelKey, enabled });
  }

  async updateProjectStep(projectId, stepId, done) {
    if (USE_MOCKS) return { status: 'ok' };
    return this._post(`/api/projects/${projectId}/steps`, { stepId, done });
  }
async archive(q,dept) {
    if (USE_MOCKS) {
      await mockDelay();
      let results=MOCK.archive.results;
      if (q) results=results.filter(r=>r.title.toLowerCase().includes(q.toLowerCase()));
      if (dept) results=results.filter(r=>r.dept===dept);
      return {status:'ok',results};
    }
    return API.get('/api/archive',{q:q||'',dept:dept||''});
  },

  async reportHtml(id) {
    if (USE_MOCKS) { await mockDelay(); return MOCK.reportHtml; }
    return API.get('/miniapp/'+encodeURIComponent(id));
  },

  async settings() {
    if (USE_MOCKS) { await mockDelay(); return MOCK.settings; }
    return API.get('/api/settings');
  },

  async saveSettings(data) {
    if (USE_MOCKS) { await mockDelay(); Object.assign(MOCK.settings,data); return {status:'ok'}; }
    return API.post('/api/settings',data);
  },

  async getModelsConfig() {
    if (USE_MOCKS) { await mockDelay(); return {status:'ok',models:MOCK.settings.models}; }
    return API.get('/api/models/config');
  },

  async addModel(data) {
    if (USE_MOCKS) { await mockDelay(); MOCK.settings.models.push({id:'m'+Date.now(),...data}); return {status:'ok'}; }
    return API.post('/api/models',data);
  },

  async updateModel(id,data) {
    if (USE_MOCKS) { await mockDelay(); const m=MOCK.settings.models.find(x=>x.id===id); if(m)Object.assign(m,data); return {status:'ok'}; }
    return API.put('/api/models/'+encodeURIComponent(id),data);
  },

  async deleteModel(id) {
    if (USE_MOCKS) { await mockDelay(); MOCK.settings.models=MOCK.settings.models.filter(x=>x.id!==id); return {status:'ok'}; }
    return API.delete('/api/models/'+encodeURIComponent(id));
  },

  async adminStatus() {
    if (USE_MOCKS) { await mockDelay(); return MOCK.adminStatus; }
    return API.get('/api/admin/status');
  },

  // ── SEC-6: Integrations Screen ──
  async integrations() {
    if (USE_MOCKS) {
      await mockDelay();
      return {
        status: 'ok',
        integrations: [
          { id:'ZAI_API_KEY', label:'Z.ai (GLM)', kind:'model', connected:true, masked:'zai-…a3f7', source:'env' },
          { id:'DEEPSEEK_API_KEY', label:'DeepSeek', kind:'model', connected:true, masked:'sk-…9b2c', source:'db' },
          { id:'GROQ_API_KEY', label:'Groq', kind:'model', connected:true, masked:'gsk_…4d1e', source:'env' },
          { id:'CEREBRAS_API_KEY', label:'Cerebras', kind:'model', connected:false, masked:null, source:'none' },
          { id:'KIMI_API_KEY', label:'Kimi (Moonshot)', kind:'model', connected:true, masked:'sk-…7f8a', source:'db' },
          { id:'ANTHROPIC_API_KEY', label:'Anthropic (Claude)', kind:'model', connected:true, masked:'sk-ant-…3c5b', source:'env' },
          { id:'OPENAI_API_KEY', label:'OpenAI', kind:'model', connected:false, masked:null, source:'none' },
          { id:'GROK_API_KEY', label:'Grok (xAI)', kind:'model', connected:false, masked:null, source:'none' },
          { id:'NVIDIA_API_KEY', label:'NVIDIA', kind:'model', connected:false, masked:null, source:'none' },
          { id:'APODEX_API_KEY', label:'Apodex', kind:'model', connected:false, masked:null, source:'none' },
          { id:'TAVILY_API_KEY', label:'Tavily (веб-поиск)', kind:'service', connected:true, masked:'tvly-…2e9d', source:'env' },
          { id:'GITHUB_TOKEN_METALOGOS', label:'GitHub (трекинг)', kind:'service', connected:true, masked:'ghp_…8a4c', source:'db' },
        ]
      };
    }
    return API.get('/api/integrations');
  },

  async integrationSet(envKey, value) {
    if (USE_MOCKS) { await mockDelay(); return { status:'ok', masked: value.substring(0,3) + '…' + value.substring(value.length-4) }; }
    return API.post('/api/integrations/' + encodeURIComponent(envKey), { value });
  },

  async integrationDelete(envKey) {
    if (USE_MOCKS) { await mockDelay(); return { status:'ok' }; }
    return API.delete('/api/integrations/' + encodeURIComponent(envKey));
  },

  async sendChatMessage(dept, message, attachments) {
    if (USE_MOCKS) { await mockDelay(); return { status:'ok', messageId: 'msg-'+Date.now() }; }
    return API.post('/api/chat/'+encodeURIComponent(dept)+'/message', { message, attachments });
  },

  async uploadFile(file) {
    if (USE_MOCKS) { await mockDelay(); return { status:'ok', url: 'https://mock.fosved.ai/upload/'+Date.now(), name: file.name, size: file.size }; }
    const form = new FormData();
    form.append('file', file);
    const r = await fetch(BASE_URL+'/api/upload', { method:'POST', body:form, credentials:'same-origin' });
    return parseResponse(r);
  },
};

window.API = API;
export default API;
export { API, ApiError, USE_MOCKS };
