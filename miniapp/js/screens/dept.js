/**
 * FOSVED Mini App — Department Details Screen v2
 * Commands with descriptions, model priority (drag-drop), chat integration
 */

import { esc } from '../app.js';
import { createKPICard, createSectionTitle } from '../components/card.js';
import { formatRating, getDeptDisplayName } from '../api.js';

export async function render(container, slug) {
  if (!slug) {
    container.innerHTML = '<div class="empty-state"><div style="font-size:28px">⚠️</div>Отдел не указан</div>';
    return;
  }

  let data;
  try { data = await API.dept(slug); }
  catch { container.innerHTML = '<div class="empty-state"><div style="font-size:28px">⚠️</div>Ошибка загрузки</div>'; return; }

  if (data.status !== 'ok') {
    container.innerHTML = `<div class="empty-state"><div style="font-size:28px">⚠️</div>${esc(data.error || 'Отдел не найден')}</div>`;
    return;
  }

  const { name, color, kpis, tasks, corrections, skills, observations, model, provider, commands, modelPriority } = data;
  const c = color || { start: '#334155', end: '#1e293b', accent: '#64748b' };
  const displayName = getDeptDisplayName({name});
  const shortName = displayName.includes(' — ') ? displayName.split(' — ')[0] : displayName;
  const subtitle = name.includes(' — ') ? name.split(' — ').slice(1).join(' — ') : '';
  const ratingNum = parseFloat(formatRating(kpis?.rating)) || 0;
  const displayRating = formatRating(kpis?.rating);
  const statusColor = ratingNum >= 4 ? '#639922' : ratingNum >= 3 ? '#EF9F27' : '#E24B4A';
  const statusLabel = ratingNum >= 4 ? 'АКТИВЕН' : ratingNum >= 3 ? 'УМЕРЕННЫЙ' : 'НИЗКИЙ';

  // Load saved priority from localStorage
  let priorityList = modelPriority || [];
  try {
    const saved = localStorage.getItem('fosved-dept-' + slug + '-models');
    if (saved) priorityList = JSON.parse(saved);
  } catch(e) {}

  let html = '';

  // ── Topbar ──
  html += `<div class="topbar">
    <span data-nav="/depts" style="cursor:pointer;font-size:18px;margin-right:8px" aria-label="Назад">←</span>
    <div class="topbar-title">${esc(shortName)}</div>
    <span data-nav="/chat/${esc(slug)}" style="margin-left:auto;font-size:12px;color:#185FA5;cursor:pointer;white-space:nowrap">💬 [chat]</span>
  </div>`;

  // ── Gradient header ──
  html += `<div class="dept-gradient-header" style="background:linear-gradient(135deg,${c.start},${c.end})">
    <h1 style="margin:0;font-size:22px;font-weight:700;color:#fff">${esc(shortName)}</h1>
    ${subtitle ? `<div style="font-size:13px;color:rgba(255,255,255,0.7);margin-top:4px">${esc(subtitle)}</div>` : ''}
    <div style="display:flex;align-items:center;gap:6px;margin-top:10px;font-size:12px;color:rgba(255,255,255,0.8)">
      <span class="status-dot" style="background:${statusColor}"></span>
      ${statusLabel} · <span style="font-family:var(--font-mono,monospace)">${esc(model || '—')}</span>
    </div>
  </div>`;

  html += `<div class="screen-scroll">`;

  // ── KPI row ──
  html += '<div class="dept-kpi-row">';
  html += createKPICard(kpis?.tasks ?? '—', 'ЗАДАЧ', '#C9A84C');
  html += createKPICard(displayRating, 'ОЦЕНКА', statusColor);
  html += '</div>';

  // ── КОМАНДЫ (новое!) ──
  if (commands && commands.length) {
    html += createSectionTitle('КОМАНДЫ');
    html += `<div style="display:flex;flex-direction:column;gap:6px;">`;
    for (const cmd of commands) {
      const validClass = cmd.valid ? 'ok' : 'fail';
      const validText = cmd.valid ? '✓ валидна' : '✗ offline';
      html += `
        <div class="command-card${cmd.valid ? '' : ' offline'}" data-cmd="${esc(cmd.cmd)}" data-nav="/chat/${esc(slug)}?cmd=${encodeURIComponent(cmd.cmd)}">
          <div class="command-card-head">
            <span class="dept-card-dot" style="background:${cmd.valid ? c.accent : '#888'}"></span>
            <span class="command-card-name">${esc(cmd.cmd)}</span>
            <span class="command-valid ${validClass}">${validText}</span>
          </div>
          <div class="command-card-desc">${esc(cmd.desc)}</div>
        </div>`;
    }
    html += `</div>`;
  }

  // ── ПРИОРИТЕТ МОДЕЛЕЙ (новое!) ──
  if (priorityList && priorityList.length) {
    html += createSectionTitle('ПРИОРИТЕТ МОДЕЛЕЙ');
    html += `<div class="card" style="padding:12px">`;
    html += `<div style="font-size:11px;color:#888;margin-bottom:10px">Перетащите для изменения порядка</div>`;
    html += `<div class="model-priority-list" id="priority-list-${esc(slug)}">`;
    for (let i = 0; i < priorityList.length; i++) {
      const m = priorityList[i];
      const isOffline = !m.valid;
      html += `
        <div class="model-priority-item${i===0?' rank-1':''}${isOffline?' offline':''}" draggable="${!isOffline}" data-key="${esc(m.key)}" data-idx="${i}">
          <span class="model-priority-rank">${isOffline ? '—' : '#'+(i+1)}</span>
          <span class="model-priority-name">${esc(m.name)}</span>
          <span class="model-priority-valid ${m.valid?'ok':'fail'}">${m.valid?'✓':'✗'}</span>
          ${i===0 && m.valid ? '<span class="model-priority-badge">приоритет</span>' : ''}
          ${!isOffline ? '<span class="model-priority-handle">⋮⋮</span>' : ''}
        </div>`;
    }
    html += `</div>`;
    html += `<div class="model-priority-controls">`;
    html += `<button class="btn btn-sm" id="priority-up-${esc(slug)}">↑</button>`;
    html += `<button class="btn btn-sm" id="priority-down-${esc(slug)}">↓</button>`;
    html += `<button class="btn btn-sm btn-gold" id="priority-save-${esc(slug)}">Сохранить</button>`;
    html += `</div></div>`;
  }

  // ── ЧАТ-БЫСТРЫЙ ДОСТУП (новое!) ──
  html += createSectionTitle('БЫСТРЫЙ ЧАТ');
  html += `<div class="card" style="display:flex;align-items:center;gap:10px;padding:12px;cursor:pointer" data-nav="/chat/${esc(slug)}">
    <div style="width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,${c.start},${c.end});display:flex;align-items:center;justify-content:center;color:#fff;font-weight:600;font-size:14px">${esc(shortName.charAt(0))}</div>
    <div style="flex:1">
      <div style="font-size:14px;font-weight:600">${esc(shortName)}</div>
      <div style="font-size:11px;color:#888">Написать запрос или голосовую команду</div>
    </div>
    <span style="font-size:18px">💬</span>
  </div>`;

  // ── ЗАДАЧИ ──
  if (tasks && tasks.length) {
    html += createSectionTitle('ПОСЛЕДНИЕ ЗАДАЧИ');
    for (const t of tasks) {
      const starsStr = '★'.repeat(Math.min(t.stars || 0, 5)) + '☆'.repeat(Math.max(5 - (t.stars || 0), 0));
      html += `<div class="task-item">
        <div class="task-text">${esc(t.text)}</div>
        <div class="task-meta">${esc(t.created)}${t.depth != null ? ` · depth ${t.depth}` : ''}${t.stars != null ? ` · <span style="color:#C9A84C">${starsStr}</span>` : ''}</div>
      </div>`;
    }
  }

  // ── НАВЫКИ ──
  if (skills && skills.length) {
    html += createSectionTitle('НАВЫКИ');
    html += '<div class="skills-grid">';
    for (const s of skills) html += `<span class="skill-chip">${esc(s)}</span>`;
    html += '</div>';
  }

  // ── КОРРЕКЦИИ ──
  if (corrections && corrections.length) {
    html += createSectionTitle('КОРРЕКЦИИ (/fix)');
    for (const cr of corrections) {
      html += `<div class="correction-item">
        <div class="correction-type">${esc(cr.type || 'FIX')}</div>
        <div class="correction-text">${esc(cr.text)}</div>
        <div class="correction-date">${esc(cr.created)}</div>
      </div>`;
    }
  }

  // ── НАБЛЮДЕНИЯ ──
  if (observations && observations.length) {
    html += createSectionTitle('НАБЛЮДЕНИЕ');
    for (const o of observations) {
      html += `<div class="observation-item">
        <div style="font-size:13px;font-weight:500">${esc(o.topic)}</div>
        <div style="font-size:11px;color:#888;margin-top:3px">${esc(o.freq)}${o.last ? ' · ' + esc(o.last) : ''}</div>
      </div>`;
    }
  }

  // ── МОДЕЛЬ ──
  html += createSectionTitle('МОДЕЛЬ');
  html += `<div class="card" style="margin:0 0 24px">
    <div style="font-family:var(--font-mono,monospace);font-size:14px;color:#C9A84C">${esc(model || '—')}</div>
    ${provider ? `<div style="font-size:12px;color:#888;margin-top:4px">Provider: ${esc(provider)}</div>` : ''}
  </div>`;

  html += `</div>`;
  container.innerHTML = html;

  // ── Wire up drag-and-drop for model priority ──
  setupDragAndDrop(slug, priorityList);
  setupPriorityButtons(slug, priorityList);
}

function setupDragAndDrop(slug, list) {
  const container = document.getElementById('priority-list-' + slug);
  if (!container) return;

  let draggedEl = null;
  let draggedIdx = null;

  container.querySelectorAll('.model-priority-item[draggable="true"]').forEach((el, idx) => {
    el.addEventListener('dragstart', (e) => {
      draggedEl = el;
      draggedIdx = parseInt(el.dataset.idx);
      el.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    el.addEventListener('dragend', () => {
      if (draggedEl) draggedEl.classList.remove('dragging');
      draggedEl = null; draggedIdx = null;
      renumberPriority(slug);
    });
    el.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
    });
    el.addEventListener('drop', (e) => {
      e.preventDefault();
      if (!draggedEl || draggedIdx === null) return;
      const targetIdx = parseInt(el.dataset.idx);
      if (draggedIdx === targetIdx) return;
      const items = Array.from(container.children).filter(c => c.classList.contains('model-priority-item'));
      const draggedItem = items[draggedIdx];
      const targetItem = items[targetIdx];
      if (draggedIdx < targetIdx) targetItem.after(draggedItem);
      else targetItem.before(draggedItem);
      renumberPriority(slug);
    });
  });
}

function renumberPriority(slug) {
  const container = document.getElementById('priority-list-' + slug);
  if (!container) return;
  const items = Array.from(container.children).filter(c => c.classList.contains('model-priority-item'));
  items.forEach((item, i) => {
    item.dataset.idx = i;
    const rank = item.querySelector('.model-priority-rank');
    if (rank && !item.classList.contains('offline')) rank.textContent = '#' + (i + 1);
    item.classList.toggle('rank-1', i === 0 && !item.classList.contains('offline'));
    const badge = item.querySelector('.model-priority-badge');
    if (badge) badge.style.display = (i === 0 && !item.classList.contains('offline')) ? 'inline-block' : 'none';
  });
}

function setupPriorityButtons(slug, list) {
  const upBtn = document.getElementById('priority-up-' + slug);
  const downBtn = document.getElementById('priority-down-' + slug);
  const saveBtn = document.getElementById('priority-save-' + slug);
  const container = document.getElementById('priority-list-' + slug);

  if (!container) return;

  let selectedIdx = 0;

  function getItems() {
    return Array.from(container.children).filter(c => c.classList.contains('model-priority-item') && !c.classList.contains('offline'));
  }

  function highlight(idx) {
    getItems().forEach((item, i) => {
      item.style.background = i === idx ? '#f5f5f0' : '';
      item.style.borderColor = i === idx ? '#C9A84C' : '';
    });
    selectedIdx = idx;
  }

  getItems().forEach((item, i) => {
    item.addEventListener('click', () => highlight(i));
  });

  if (upBtn) {
    upBtn.addEventListener('click', () => {
      const items = getItems();
      if (selectedIdx > 0) {
        items[selectedIdx - 1].before(items[selectedIdx]);
        renumberPriority(slug);
        highlight(selectedIdx - 1);
      }
    });
  }

  if (downBtn) {
    downBtn.addEventListener('click', () => {
      const items = getItems();
      if (selectedIdx < items.length - 1) {
        items[selectedIdx + 1].after(items[selectedIdx]);
        renumberPriority(slug);
        highlight(selectedIdx + 1);
      }
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      const items = getItems();
      const order = items.map(el => el.dataset.key);
      try {
        await API.setDeptModelPriority(slug, order);
        localStorage.setItem('fosved-dept-' + slug + '-models', JSON.stringify(
          items.map(el => list.find(m => m.key === el.dataset.key)).filter(Boolean)
        ));
        saveBtn.textContent = '✓ Сохранено';
        setTimeout(() => saveBtn.textContent = 'Сохранить', 1500);
      } catch (e) {
        saveBtn.textContent = '✗ Ошибка';
        setTimeout(() => saveBtn.textContent = 'Сохранить', 1500);
      }
    });
  }
}
