/**
 * Fosved Office Mini App — Chat Screen (Screen 3)
 * View-only chat interface. Actual conversation happens via Telegram bot.
 */

import { createTopBar, esc } from '../components/card.js';
import { createChip, createStatusDot } from '../components/badge.js';

/**
 * Known department slugs for the chip selector.
 */
const DEPT_LIST = [
  { slug: 'yana',      label: 'Яна',        color: '#293133' },
  { slug: 'osp',       label: 'ОСП',        color: '#b91c1c' },
  { slug: 'lz',        label: 'ЛЗ',         color: '#0e7490' },
  { slug: 'dev',       label: 'Dev',         color: '#1d4ed8' },
  { slug: 'expert',    label: 'Expert',      color: '#3730a3' },
  { slug: 'marketing', label: 'Marketing',   color: '#c2410c' },
  { slug: 'finance',   label: 'Finance',     color: '#15803d' },
  { slug: 'legal',     label: 'Legal',       color: '#475569' },
  { slug: 'design',    label: 'Design',      color: '#be185d' },
  { slug: 'qa',        label: 'QA',          color: '#4d7c0f' },
  { slug: 'visual',    label: 'Visual',      color: '#7e22ce' },
  { slug: 'engineering', label: 'Eng',       color: '#44403c' },
  { slug: 'kavalnya',  label: 'Kavalnya',    color: '#b45309' },
  { slug: 'admin',     label: 'Admin',       color: '#1e40af' },
];

/**
 * Model info per department (static — for display purposes only).
 */
const DEPT_MODELS = {
  yana:      'claude-sonnet-4-20250514',
  osp:       'claude-sonnet-4-20250514',
  lz:        'claude-sonnet-4-20250514',
  dev:       'claude-sonnet-4-20250514',
  expert:    'claude-sonnet-4-20250514',
  marketing: 'claude-sonnet-4-20250514',
  finance:   'claude-sonnet-4-20250514',
  legal:     'claude-sonnet-4-20250514',
  design:    'claude-sonnet-4-20250514',
  qa:        'claude-sonnet-4-20250514',
  visual:    'claude-sonnet-4-20250514',
  engineering: 'claude-sonnet-4-20250514',
  kavalnya:  'claude-sonnet-4-20250514',
  admin:     'claude-sonnet-4-20250514',
};

export function render(container, deptSlug = 'yana') {
  const currentDept = DEPT_LIST.find(d => d.slug === deptSlug) || DEPT_LIST[0];
  const currentModel = DEPT_MODELS[deptSlug] || 'claude-sonnet-4-20250514';

  let html = '';

  // ── Top Bar ──
  html += createTopBar('Чат');

  // ── Dept Chips ──
  html += `<div style="display:flex;gap:6px;padding:8px 12px;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none">`;
  for (const dept of DEPT_LIST) {
    const isActive = dept.slug === currentDept.slug;
    html += `
      <span class="chip${isActive ? ' chip-active' : ''}"
            style="white-space:nowrap;border-color:${isActive ? '' : dept.color};color:${isActive ? '' : dept.color}"
            data-nav="/chat/${dept.slug}">${esc(dept.label)}</span>`;
  }
  html += `</div>`;

  // ── Chat Header ──
  html += `
    <div style="padding:8px 16px;border-bottom:1px solid rgba(0,0,0,0.08);background:#fff;display:flex;align-items:center;gap:10px">
      <div style="width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,${currentDept.color},${currentDept.color}dd);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:600;font-size:14px">${currentDept.label.charAt(0)}</div>
      <div style="flex:1">
        <div style="font-size:14px;font-weight:600">${esc(currentDept.label)}</div>
        <div style="font-size:11px;color:#aaa;font-family:'DM Mono',monospace">${esc(currentModel)}</div>
      </div>
      ${createStatusDot('online', '')}
    </div>`;

  // ── Messages Area (View-Only) ──
  html += `
    <div id="chat-messages" style="flex:1;min-height:200px;padding:8px 0;display:flex;flex-direction:column">
      <div style="text-align:center;padding:60px 24px;color:#aaa;font-size:13px;line-height:1.6">
        <div style="font-size:36px;margin-bottom:12px">&#128172;</div>
        <div style="font-size:15px;font-weight:500;color:#555;margin-bottom:8px">${esc(currentDept.label)}</div>
        <div>Use the Telegram bot for conversations.</div>
        <div style="margin-top:8px">Commands and responses are handled via the main bot chat.</div>
      </div>
    </div>`;

  // ── Input Bar (disabled / informational) ──
  html += `
    <div class="chat-input-bar">
      <input class="chat-input" id="chat-input"
             placeholder="Use Telegram bot for conversations..."
             disabled
             style="opacity:0.5">
      <button class="chat-send-btn" disabled style="opacity:0.4">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="22" y1="2" x2="11" y2="13"></line>
          <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>
      </button>
    </div>`;

  container.innerHTML = html;
}
