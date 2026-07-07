/**
 * Fosved Office Mini App — Chat Screen (Screen 3: Чат)
 * View-only chat interface. Actual conversation happens via Telegram bot.
 */

import { esc } from '../app.js';
import { createStatusDot } from '../components/badge.js';

const DEPT_LIST = [
  { slug: 'yana',        label: 'Яна',        color: '#293133' },
  { slug: 'osp',         label: 'ОСП',         color: '#b91c1c' },
  { slug: 'lz',          label: 'ЛЗ',          color: '#0e7490' },
  { slug: 'dev',         label: 'Dev',         color: '#1d4ed8' },
  { slug: 'expert',      label: 'Expert',      color: '#3730a3' },
  { slug: 'marketing',   label: 'Маркетинг',   color: '#c2410c' },
  { slug: 'finance',     label: 'Финансы',     color: '#15803d' },
  { slug: 'legal',       label: 'Юрист',       color: '#475569' },
  { slug: 'design',      label: 'Design',      color: '#be185d' },
  { slug: 'qa',          label: 'QA',          color: '#4d7c0f' },
  { slug: 'visual',      label: 'Visual',      color: '#7e22ce' },
  { slug: 'engineering', label: 'Eng',         color: '#44403c' },
  { slug: 'kavalnya',    label: 'Кавальня',    color: '#b45309' },
  { slug: 'admin',       label: 'Админ',       color: '#1e40af' },
];

const DEPT_MODELS = {
  yana:'claude-sonnet-4', osp:'GLM 4.6', lz:'GLM 4.6', dev:'GLM 4.6',
  expert:'claude-sonnet-4', marketing:'GLM 4.6', finance:'GLM 4.6',
  legal:'GLM 4.6', design:'GLM 4.6', qa:'GLM 4.6', visual:'GLM 4.6',
  engineering:'GLM 4.6', kavalnya:'GLM 4.6', admin:'GLM 4.6',
};

const YANA_MESSAGES = [
  { role:'ai', label:'ЯНА', body:'Доброе утро! Вот что важного:\n\n🔴 Grok 2 — лимит исчерпан\n🟡 3 задачи pending\n\n', choices:['Статус','Анализ ОСП','Расход LLM'], tts:true },
  { role:'user', body:'Покажи расход LLM' },
  { role:'ai', label:'ЯНА', body:'Расход сегодня: €0.74 (247 запросов)\n\nGLM 4.6    €0.48    63%\nClaude      €0.18    24%\nDeepSeek    €0.06     9%\nGroq        €0.02     4%\n\nБюджет: €10.00/день · Осталось: €9.26', inlineBtn:{label:'Открыть отчёт →',nav:'/archive'} },
];

/**
 * Quick-action buttons per department.
 * Each button sends a command to the bot via tg.sendData().
 */
const DEPT_QUICK_ACTIONS = {
  osp: [
    { label: 'Деконструкция',  cmd: '/deconstruct' },
    { label: 'Awareness frame', cmd: '/awareness' },
    { label: 'Прогноз',         cmd: '/forecast' },
    { label: 'IW Watchlist',    cmd: '/iw_watchlist' },
    { label: 'Калман',          cmd: '/calibration' },
    { label: 'Нарратив/Потоки', cmd: '/narrative_vs_flows' },
  ],
  lz: [
    { label: 'Поиск в БЗ',       cmd: '/kb_search' },
    { label: 'Последние отчёты', cmd: '/recent_reports' },
    { label: 'Сводка знаний',    cmd: '/kb_summary' },
  ],
  expert: [
    { label: 'Combat вопросы', cmd: '/combat_questions' },
    { label: 'Deep profile',   cmd: '/deep_profile' },
    { label: 'Cross-check',    cmd: '/cross_check' },
  ],
  marketing: [
    { label: 'Аудитория',   cmd: '/audience' },
    { label: 'Каналы',      cmd: '/channels' },
    { label: 'A/B тест',    cmd: '/ab_test' },
  ],
  finance: [
    { label: 'Cashflow',  cmd: '/cashflow' },
    { label: 'MRR/ARR',  cmd: '/mrr' },
    { label: 'Бюджет',    cmd: '/budget' },
  ],
  legal: [
    { label: 'Договор',    cmd: '/contract' },
    { label: 'Риски',      cmd: '/risk_map' },
    { label: 'GDPR',       cmd: '/gdpr' },
  ],
  dev: [
    { label: 'Деплой',   cmd: '/deploy_status' },
    { label: 'Баги',     cmd: '/bugs' },
    { label: 'CI/CD',    cmd: '/ci_status' },
  ],
  design: [
    { label: 'Дизайн-система', cmd: '/design_system' },
    { label: 'Компоненты',     cmd: '/components' },
  ],
  qa: [
    { label: 'Тесты',    cmd: '/tests' },
    { label: 'Покрытие',  cmd: '/coverage' },
  ],
  visual: [
    { label: 'Инфографика', cmd: '/infographic' },
    { label: 'Презентация', cmd: '/presentation' },
  ],
  engineering: [
    { label: 'Нагрузка',  cmd: '/load' },
    { label: 'Uptime',   cmd: '/uptime' },
  ],
  kavalnya: [
    { label: 'Оперативка',  cmd: '/ops' },
    { label: 'Доклад',      cmd: '/report' },
  ],
  admin: [
    { label: 'Статус системы', cmd: '/system_status' },
    { label: 'Логи',          cmd: '/logs' },
  ],
};

export function render(container, deptSlug = 'yana') {
  const dept = DEPT_LIST.find(d => d.slug === deptSlug) || DEPT_LIST[0];
  const model = DEPT_MODELS[deptSlug] || 'GLM 4.6';
  const msgs = deptSlug === 'yana' ? YANA_MESSAGES : [];

  // ── Header (non-scrollable, flex-shrink: 0) ──
  const chips = DEPT_LIST.map(d => {
    const a = d.slug === dept.slug;
    return `<span class="chat-chip chip${a ? ' active' : ''}" data-nav="/chat/${d.slug}">${esc(d.label)}</span>`;
  }).join('');

  const header = `
    <div class="topbar"><div class="topbar-title">Чат</div></div>
    <div class="chat-chips">${chips}</div>
    <div class="chat-header-bar">
      <div class="chat-avatar" style="background:${dept.color}">${esc(dept.label.charAt(0))}</div>
      <div style="flex:1;min-width:0">
        <div class="chat-dept-name">${esc(dept.label)}</div>
        <div class="chat-dept-model">${esc(model)}</div>
      </div>
      ${createStatusDot('online', '')}
    </div>
    <div class="chat-context-bar">📌 Portal Nexus 78% 🔴</div>`;

  // ── Messages (scrollable, flex:1) ──
  const quickActions = DEPT_QUICK_ACTIONS[deptSlug] || [];
  let msgContent = '';
  if (msgs.length === 0) {
    if (quickActions.length > 0) {
      msgContent += `
        <div class="chat-msg chat-msg-ai">
          <div class="chat-msg-label">${esc(dept.label)}</div>
          <div style="font-size:13px;line-height:1.6;color:#555">
            Быстрые команды <b>${esc(dept.label)}</b>.<br>
            Нажмите для отправки в бота.
          </div>
        </div>
        <div class="chat-quick-actions">
          ${quickActions.map(a =>
            `<button class="chat-quick-btn" data-cmd="${esc(a.cmd)}" style="border-color:${dept.color};color:${dept.color}">${esc(a.label)}</button>`
          ).join('')}
        </div>`;
    } else {
      msgContent += `
        <div class="chat-msg chat-msg-ai">
          <div class="chat-msg-label">${esc(dept.label)}</div>
          <div style="font-size:13px;line-height:1.6;color:#555">
            Используйте Telegram бота для общения с <b>${esc(dept.label)}</b>.<br>
            Все команды обрабатываются через основной чат бота.
          </div>
        </div>`;
    }
  } else {
    for (const m of msgs) {
      if (m.role === 'user') {
        msgContent += `<div class="chat-msg chat-msg-user"><div style="font-size:13px;line-height:1.6">${esc(m.body)}</div></div>`;
      } else {
        msgContent += `<div class="chat-msg chat-msg-ai">
          <div class="chat-msg-label">${esc(m.label)}</div>
          <div style="font-size:13px;line-height:1.7;white-space:pre-line">${esc(m.body)}</div>`;
        if (m.choices?.length) {
          msgContent += '<div class="chat-choices">';
          for (const c of m.choices) msgContent += `<span class="chat-choice">${esc(c)}</span>`;
          msgContent += '</div>';
        }
        if (m.tts) msgContent += '<button class="chat-tts-btn">🔊 Прослушать</button>';
        if (m.inlineBtn) msgContent += `<span class="chat-inline-btn" data-nav="${esc(m.inlineBtn.nav)}">${esc(m.inlineBtn.label)}</span>`;
        msgContent += '</div>';
      }
    }
  }

  const messages = `<div class="chat-messages">${msgContent}</div>`;

  // ── Input bar (fixed bottom, flex-shrink: 0) ──
  const inputPlaceholder = dept.label === 'Яна' ? 'Написать Яне...' : `Написать ${dept.label.toLowerCase()}...`;
  const inputBar = `
    <div class="chat-input-bar">
      <input placeholder="${esc(inputPlaceholder)}" disabled style="flex:1;border:none;background:transparent;font-family:var(--font-body);font-size:14px;padding:8px 0;outline:none;color:var(--c-text);opacity:0.5">
      <button class="chat-send-btn" disabled style="opacity:0.4">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="22" y1="2" x2="11" y2="13"></line>
          <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>
      </button>
    </div>`;

  // ── Compose: header (shrink) + messages (flex:1) + input (shrink) ──
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;height:100%;overflow:hidden">
      <div style="flex-shrink:0">${header}</div>
      ${messages}
      ${inputBar}
    </div>`;

  // ── Wire up quick-action buttons ──
  container.querySelectorAll('.chat-quick-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const cmd = btn.dataset.cmd;
      if (cmd && window.tgSendData) {
        window.tgSendData({ action: 'dept_command', dept: deptSlug, command: cmd });
        btn.style.opacity = '0.4';
        btn.style.pointerEvents = 'none';
      }
    });
  });
}