/**
 * FOSVED Mini App — Projects Screen (/projects)
 */

import { esc } from '../app.js';

const STATUS_CONFIG = {
  active:     { label: 'АКТИВЕН',    bg: '#E8F5E9', color: '#2E7D32' },
  inprogress: { label: 'В РАБОТЕ',  bg: '#FFF3E0', color: '#EF6C00' },
  paused:     { label: 'ПАУЗА',     bg: '#FFF8E1', color: '#F9A825' },
  completed:  { label: 'ЗАВЕРШЁН',  bg: '#E3F2FD', color: '#185FA5' },
  archived:   { label: 'АРХИВ',     bg: '#F5F5F5', color: '#888' },
};

const DEPT_MINI = {
  osp: { letter:'О', color:'linear-gradient(135deg,#dc2626,#991b1b)' },
  lz:  { letter:'Л', color:'linear-gradient(135deg,#0891b2,#0e7490)' },
  marketing: { letter:'М', color:'linear-gradient(135deg,#ea580c,#c2410c)' },
  finansy:   { letter:'Ф', color:'linear-gradient(135deg,#16a34a,#15803d)' },
  razrabotka:{ letter:'D', color:'linear-gradient(135deg,#2563eb,#1e3a8a)' },
  design:    { letter:'D', color:'linear-gradient(135deg,#ec4899,#be185d)' },
  qa:        { letter:'Q', color:'linear-gradient(135deg,#4d7c0f,#365314)' },
  visual:    { letter:'V', color:'linear-gradient(135deg,#a855f7,#7e22ce)' },
  engineering:{ letter:'E', color:'linear-gradient(135deg,#44403c,#292524)' },
  kavalnya:  { letter:'К', color:'linear-gradient(135deg,#b45309,#78350f)' },
  expert:    { letter:'E', color:'linear-gradient(135deg,#3730a3,#1e1b4b)' },
  'tekhnicheskiy-preparator': { letter:'Т', color:'linear-gradient(135deg,#0ea5e9,#0369a1)' },
  legal:     { letter:'Ю', color:'linear-gradient(135deg,#475569,#1e293b)' },
  yana:      { letter:'Я', color:'linear-gradient(135deg,#b8943f,#8B6914)' },
};

export async function render(container) {
  let data;
  try { data = await API.projects(); }
  catch (e) { container.innerHTML = `<div class="empty-state">⚠️ Ошибка загрузки</div>`; return; }

  if (data.status !== 'ok') { container.innerHTML = `<div class="empty-state">⚠️ ${esc(data.error)}</div>`; return; }

  const projects = data.projects || [];

  let html = `<div class="topbar"><div class="topbar-title">Проекты</div></div>`;
  html += `<div class="screen-scroll">`;
  html += `<div class="section-title">${projects.length} ПРОЕКТОВ</div>`;

  if (projects.length) {
    for (const p of projects) {
      const sc = STATUS_CONFIG[p.status] || STATUS_CONFIG.active;
      const depts = p.depts || [];
      const visibleDepts = depts.slice(0, 5);
      const hiddenCount = Math.max(0, depts.length - 5);

      html += `<div class="project-card" data-nav="/project/${esc(p.id)}">`;
      html += `  <div class="project-header">`;
      html += `    <span class="project-name">${esc(p.name)}</span>`;
      html += `    <span class="project-status" style="background:${esc(sc.bg)};color:${esc(sc.color)}">${esc(sc.label)}</span>`;
      html += `  </div>`;
      html += `  <div class="project-desc">${esc(p.description || '—')}</div>`;

      // Meta
      html += `  <div class="project-meta">`;
      if (p.repo) {
        html += `    <div class="meta-row"><span class="meta-icon">📁</span> <a class="meta-link" href="${esc(p.repo)}" target="_blank">${esc(p.repo.replace('https://',''))}</a></div>`;
      }
      if (p.servers?.length) {
        html += `    <div class="meta-row"><span class="meta-icon">🌐</span> <span>${esc(p.servers.join(' · '))}</span></div>`;
      }
      if (p.context) {
        html += `    <div class="meta-row"><span class="meta-icon">💾</span> <span>Контекст: ${esc(p.context)}</span></div>`;
      }
      html += `  </div>`;

      // Keys
      if (p.keys?.length) {
        html += `  <div class="project-keys">`;
        for (const k of p.keys) {
          const cls = k.type === 'api' ? 'api' : k.type === 'github' ? 'gh' : 'server';
          html += `<span class="key-chip ${cls}">${esc(k.label)}</span>`;
        }
        html += `  </div>`;
      }

      // Depts
      if (depts.length) {
        html += `  <div class="project-depts">`;
        for (const d of visibleDepts) {
          const dm = DEPT_MINI[d] || { letter: '?', color: '#888' };
          html += `<div class="dept-mini" style="background:${esc(dm.color)}">${esc(dm.letter)}</div>`;
        }
        if (hiddenCount > 0) {
          html += `<span class="dept-more">+${hiddenCount} отдел</span>`;
        }
        html += `  </div>`;
      }

      // Progress
      const pct = p.progress ?? 0;
      html += `  <div class="project-progress">`;
      html += `    <div class="progress-label"><span>Прогресс</span><span>${pct}%</span></div>`;
      html += `    <div class="progress-track"><div class="progress-fill" style="width:${pct}%;background:linear-gradient(90deg,${esc(sc.color)},${esc(sc.bg)})"></div></div>`;
      html += `  </div>`;

      html += `</div>`;
    }
  } else {
    html += `<div class="empty-state">Нет активных проектов</div>`;
  }

  html += `</div>`;
  container.innerHTML = html;
}
