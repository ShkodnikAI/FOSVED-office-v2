/**
 * Fosved Office Mini App — Report Viewer Screen (Screen 4)
 * Fetches and displays a full HTML report with action bar and inline toasts.
 */

import { esc } from '../app.js';

export async function render(container, id) {
  if (!id) {
    container.innerHTML = `<div class="empty-state">ID отчёта не указан</div>`;
    return;
  }

  const isLandscape = document.documentElement.classList.contains('landscape-mode');

  // ── Top Bar ──
  const topbarHtml = `
    <div class="top-bar">
      <a class="topbar-back" data-nav="/archive" title="В архив">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="width:18px;height:18px"><path d="M15 18l-6-6 6-6"/></svg>
      </a>
      <div class="top-bar-title">Отчёт</div>
      <button class="orientation-toggle ${isLandscape ? 'active' : ''}" data-action="toggle-orientation" title="Таблет">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" style="width:18px;height:18px"><rect x="4" y="2" width="16" height="20" rx="2"/><line x1="12" y1="18" x2="12" y2="18.01" stroke-width="2.5" stroke-linecap="round"/></svg>
      </button>
      <span style="font-family:'DM Mono',monospace;font-size:11px;color:#aaa">${esc(id)}</span>
    </div>`;

  container.innerHTML = topbarHtml + `<div class="screen-scroll"><div style="text-align:center;padding:60px;color:#aaa">Загрузка отчёта...</div></div>`;

  try {
    const reportHtml = await API.reportHtml(id);

    // Wrap bare <table> elements in .table-wrap for horizontal scroll
    const wrappedHtml = reportHtml.replace(/<table/gi, '<div class="table-wrap"><table').replace(/<\/table>/gi, '</table></div>');

    let content = `<div class="report-screen">`;
    content += topbarHtml;
    content += `<div class="report-scroll">`;
    content += `<div class="report-body">${wrappedHtml}</div>`;
    content += `</div>`;

    // ── Action Bar (pinned to bottom) ──
    content += `<div class="report-action-dock">
      <div class="action-bar">
        <button class="action-btn" data-action="deepen">Углубить</button>
        <button class="action-btn" data-action="redteam">Red Team</button>
        <button class="action-btn" data-action="control">Контроль</button>
      </div>
      <div class="action-bar">
        <button class="action-btn" data-action="journalist">Журналист</button>
        <button class="action-btn" data-action="counterforecast">Контр-прогноз</button>
      </div>
      <div class="action-bar">
        <button class="action-btn action-btn-archive" data-action="archive">В архив</button>
        <button class="action-btn" data-action="copy">Копировать</button>
        <button class="action-btn" data-action="pdf">PDF</button>
        <button class="action-btn" data-action="share">Поделиться</button>
      </div>
    </div>`;
    content += `</div>`;

    container.innerHTML = content;

    // Wire up action buttons
    wireActions(container, id, reportHtml);

  } catch (e) {
    container.innerHTML = `
      ${topbarHtml}
      <div class="screen-scroll">
        <div class="empty-state">
          <div style="font-size:28px;margin-bottom:12px">📄</div>
          <div style="color:#E24B4A;font-size:15px;font-weight:500">Отчёт не найден</div>
          <div style="color:#888;font-size:13px;margin-top:8px">${esc(id)}</div>
          <button class="btn btn-primary" style="margin-top:20px" onclick="location.reload()">Повторить</button>
        </div>
      </div>`;
  }
}

/**
 * POST action to backend /webhook/miniapp-action, then show result or toast.
 */
async function postAction(container, docId, action, toastMsg) {
  showInlineToast(container, toastMsg);
  try {
    const res = await fetch('/webhook/miniapp-action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, doc_id: docId }),
    });
    const data = await res.json();
    if (data.status === 'ok' && data.reply) {
      showInlineToast(container, 'Готово');
    } else if (data.status === 'error') {
      showInlineToast(container, 'Ошибка: ' + (data.msg || 'неизвестно'));
    }
  } catch (e) {
    // Silent — toast already shown
  }
}

/**
 * Attach event handlers to the action bar buttons.
 */
function wireActions(container, id, reportHtml) {
  container.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.action;
      switch (action) {
        case 'deepen':
          postAction(container, id, 'deepen_to_2', 'Углубление отправлено');
          break;

        case 'redteam':
          postAction(container, id, 'deepen_to_4', 'Red Team запущен');
          break;

        case 'control':
          postAction(container, id, 'control_daily', 'На контроле');
          break;

        case 'journalist':
          postAction(container, id, 'journalist', 'Журналист запущен');
          break;

        case 'counterforecast':
          postAction(container, id, 'counter_forecast', 'Контр-прогноз запущен');
          break;

        case 'archive':
          postAction(container, id, 'archive', 'В архив');
          break;

        case 'copy':
          copyToClipboard(reportHtml)
            .then(() => showInlineToast(container, 'Скопировано'))
            .catch(() => showInlineToast(container, 'Ошибка копирования'));
          break;

        case 'pdf':
          window.print();
          break;

        case 'crisis':
          postAction(container, id, 'crisis_protocol', 'Кризис-протокол запущен');
          break;

        case 'share':
          if (navigator.share) {
            const plain = reportHtml.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
            navigator.share({ title: 'Отчёт ' + id, text: plain })
              .catch(() => {});
          } else if (window.tgSendData) {
            window.tgSendData({ action: 'share', doc_id: id });
          } else {
            copyToClipboard(reportHtml)
              .then(() => showInlineToast(container, 'Скопировано (Share недоступен)'))
              .catch(() => showInlineToast(container, 'Ошибка'));
          }
          break;

        case 'toggle-orientation':
          document.documentElement.classList.toggle('landscape-mode');
          btn.classList.toggle('active');
          showInlineToast(container, document.documentElement.classList.contains('landscape-mode') ? 'Таблет' : 'Телефон');
          break;
      }
    });
  });
}

/**
 * Copy text to clipboard. Strips HTML tags for plain-text copy.
 */
async function copyToClipboard(text) {
  const plain = text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  if (navigator.clipboard) {
    return navigator.clipboard.writeText(plain);
  }
  // Fallback for restricted contexts
  const ta = document.createElement('textarea');
  ta.value = plain;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
}

/**
 * Show a brief inline toast notification.
 * Fixed position, black background, white text, fade in/out.
 */
function showInlineToast(container, message) {
  const toast = document.createElement('div');
  toast.textContent = message;
  Object.assign(toast.style, {
    position: 'fixed',
    bottom: '80px',
    left: '50%',
    transform: 'translateX(-50%)',
    background: '#0F0F0F',
    color: '#fff',
    padding: '8px 20px',
    borderRadius: '20px',
    fontSize: '13px',
    zIndex: '999',
    opacity: '0',
    transition: 'opacity 0.3s ease',
    whiteSpace: 'nowrap',
  });
  container.appendChild(toast);
  requestAnimationFrame(() => { toast.style.opacity = '1'; });
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 1500);
}