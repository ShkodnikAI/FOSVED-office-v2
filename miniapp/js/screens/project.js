/**
 * FOSVED Mini App — Project Detail Screen (/project/:id)
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

export async function render(container, params) {
  const projectId = params?.id || 'fosved-v2';
  let data;
  try { data = await API.project(projectId); }
  catch (e) { container.innerHTML = `<div class="empty-state">⚠️ Ошибка загрузки</div>`; return; }

  if (data.status !== 'ok') { container.innerHTML = `<div class="empty-state">⚠️ ${esc(data.error)}</div>`; return; }

  const p = data.project || {};
  const sc = STATUS_CONFIG[p.status] || STATUS_CONFIG.active;

  let html = '';

  // Topbar
  html += `<div class="topbar"><span class="topbar-back" data-nav="/projects">←</span><div class="topbar-title">${esc(p.name || 'Проект')}</div></div>`;
  html += `<div class="screen-scroll">`;

  // Header card
  html += `<div class="project-header-card">`;
  html += `  <div class="name">${esc(p.name)}</div>`;
  html += `  <span class="status" style="background:${esc(sc.bg)};color:${esc(sc.color)}">${esc(sc.label)}</span>`;
  html += `  <div class="desc">${esc(p.description || '—')}</div>`;
  html += `  <div class="progress-section">`;
  html += `    <div class="progress-label"><span>Прогресс реализации</span><span>${p.progress ?? 0}%</span></div>`;
  html += `    <div class="progress-track"><div class="progress-fill" style="width:${p.progress ?? 0}%"></div></div>`;
  html += `  </div>`;
  html += `</div>`;

  // Prompt
  if (p.prompt) {
    html += `<div class="section-title">ПРОМПТ / ЗАДАНИЕ</div>`;
    html += `<div class="prompt-box">`;
    html += `  <div class="prompt-label">ЗАДАНИЕ ДЛЯ ИИ</div>`;
    html += `  <div class="prompt-text">${esc(p.prompt)}</div>`;
    html += `</div>`;
  }

  // Resources
  html += `<div class="section-title">РЕСУРСЫ ПРОЕКТА</div>`;
  html += `<div class="meta-card">`;
  if (p.repo) {
    html += `  <div class="meta-row"><span class="meta-icon">📁</span><span class="meta-label">РЕПО</span><span class="meta-value"><a href="${esc(p.repo)}" target="_blank">${esc(p.repo.replace('https://',''))}</a></span></div>`;
  }
  if (p.servers?.length) {
    for (const s of p.servers) {
      html += `  <div class="meta-row"><span class="meta-icon">🌐</span><span class="meta-label">СЕРВЕР</span><span class="meta-value">${esc(s)}</span></div>`;
    }
  }
  if (p.plan_url) {
    html += `  <div class="meta-row"><span class="meta-icon">📋</span><span class="meta-label">ПЛАН</span><span class="meta-value"><a href="${esc(p.plan_url)}" target="_blank">${esc(p.plan_url.replace('https://',''))}</a></span></div>`;
  }
  html += `</div>`;

  // Keys
  if (p.keys?.length) {
    html += `<div class="section-title">КЛЮЧИ ДОСТУПА</div>`;
    html += `<div class="meta-card"><div class="keys-grid">`;
    for (const k of p.keys) {
      const cls = k.type === 'api' ? 'api' : k.type === 'github' ? 'gh' : 'server';
      html += `<span class="key-chip ${cls}">${esc(k.label)}</span>`;
    }
    html += `</div></div>`;
  }

  // Plan
  if (p.plan?.length) {
    html += `<div class="section-title">ПЛАН РЕАЛИЗАЦИИ</div>`;
    html += `<div class="meta-card">`;
    for (const step of p.plan) {
      const done = step.done ? ' done' : '';
      html += `<div class="plan-item" data-step="${esc(step.id)}">`;
      html += `  <div class="plan-check${done}">${step.done ? '✓' : ''}</div>`;
      html += `  <div><div class="plan-text${done}">${esc(step.text)}</div><div class="plan-assignee">${esc(step.assignee || '—')} · ${esc(step.date || '—')}</div></div>`;
      html += `</div>`;
    }
    html += `</div>`;
  }

  // Result files
  if (p.files?.length) {
    html += `<div class="section-title">РЕЗУЛЬТИРУЮЩИЕ ФАЙЛЫ</div>`;
    html += `<div class="meta-card">`;
    for (const f of p.files) {
      const icon = f.type === 'image' ? '🖼️' : f.type === 'video' ? '🎬' : f.type === 'code' ? '⚙️' : f.type === 'doc' ? '📄' : '📎';
      html += `<div class="file-item" data-file="${esc(f.id)}">`;
      html += `  <span class="file-icon">${icon}</span>`;
      html += `  <div class="file-info"><div class="file-name">${esc(f.name)}</div><div class="file-meta">${esc(f.meta || '—')}</div></div>`;
      html += `  <span class="file-size">${esc(f.size || '—')}</span>`;
      html += `</div>`;
    }
    html += `</div>`;
  }

  // Model stats
  if (p.model_stats?.length) {
    html += `<div class="section-title">СТАТИСТИКА МОДЕЛЕЙ</div>`;
    html += `<div class="meta-card">`;
    for (const m of p.model_stats) {
      html += `<div class="model-stat-row">`;
      html += `  <div class="model-stat-avatar" style="background:${esc(m.color || '#888')}">${esc(m.short || m.name?.substring(0,2) || 'AI')}</div>`;
      html += `  <div class="model-stat-info"><div class="model-stat-name">${esc(m.name)}</div><div class="model-stat-sub">${esc(m.provider)} · ${m.requests ?? 0} запросов</div></div>`;
      html += `  <div class="model-stat-bar"><div class="model-stat-fill" style="width:${m.pct ?? 0}%;background:${esc(m.bar_color || '#888')}"></div></div>`;
      html += `  <div class="model-stat-val">${esc(m.cost || '—')}</div>`;
      html += `</div>`;
    }
    html += `</div>`;
  }

  // Model selector
  if (p.available_models?.length) {
    html += `<div class="section-title">МОДЕЛИ НА ПРОЕКТЕ</div>`;
    html += `<div class="meta-card">`;
    for (const m of p.available_models) {
      const on = m.enabled ? ' on' : '';
      const valid = m.valid ? '✓ валидна' : '✗ offline';
      html += `<div class="model-select-row">`;
      html += `  <div class="model-select-avatar" style="background:${esc(m.color || '#888')}">${esc(m.short || m.name?.substring(0,2) || 'AI')}</div>`;
      html += `  <div class="model-select-info"><div class="model-select-name">${esc(m.name)}</div><div class="model-select-provider">${esc(m.provider)} · ${esc(m.tier)} · ${valid}</div></div>`;
      html += `  <div class="model-toggle${on}" data-model="${esc(m.key)}" data-enabled="${m.enabled ? '1' : '0'}"></div>`;
      html += `</div>`;
    }
    html += `</div>`;
  }

  html += `</div>`;
  container.innerHTML = html;

  // Wire up toggles
  container.querySelectorAll('.model-toggle').forEach(toggle => {
    toggle.addEventListener('click', async () => {
      const key = toggle.dataset.model;
      const enabled = toggle.dataset.enabled === '1';
      try {
        await API.updateProjectModel(projectId, key, !enabled);
        toggle.classList.toggle('on');
        toggle.dataset.enabled = enabled ? '0' : '1';
      } catch (e) { alert('Ошибка: ' + e.message); }
    });
  });

  // Wire up plan checkboxes
  container.querySelectorAll('.plan-item').forEach(item => {
    item.querySelector('.plan-check')?.addEventListener('click', async () => {
      const stepId = item.dataset.step;
      const check = item.querySelector('.plan-check');
      const text = item.querySelector('.plan-text');
      const done = check.classList.contains('done');
      try {
        await API.updateProjectStep(projectId, stepId, !done);
        check.classList.toggle('done');
        text.classList.toggle('done');
        check.textContent = done ? '' : '✓';
      } catch (e) { alert('Ошибка: ' + e.message); }
    });
  });
}
