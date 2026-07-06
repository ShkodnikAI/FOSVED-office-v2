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

  let topbarHtml = '';

  // ── Top Bar ──
  topbarHtml = `
    <div class="top-bar">
      <div class="top-bar-title">Отчёт</div>
      <span style="margin-left:auto;font-family:'DM Mono',monospace;font-size:11px;color:#aaa">${esc(id)}</span>
    </div>`;

  container.innerHTML = topbarHtml + `<div class="screen-scroll"><div style="text-align:center;padding:60px;color:#aaa">Загрузка отчёта...</div></div>`;

  try {
    const reportHtml = await API.reportHtml(id);

    let content = topbarHtml;
    content += `<div class="screen-scroll">`;
    content += `<div class="report-body">${reportHtml}</div>`;
    content += `</div>`;

    // ── Action Bar ──
    content += `
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
        <button class="action-btn" data-action="copy">Копировать</button>
        <button class="action-btn" data-action="pdf">PDF</button>
        <button class="action-btn" data-action="share">Поделиться</button>
      </div>`;

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
 * Attach event handlers to the action bar buttons.
 */
function wireActions(container, id, reportHtml) {
  container.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', () => {
      const action = btn.dataset.action;
      switch (action) {
        case 'deepen':
          if (window.tgSendData) {
            window.tgSendData({ action: 'deepen', reportId: id });
          }
          showInlineToast(container, 'Углубление отправлено');
          break;

        case 'redteam':
          if (window.tgSendData) {
            window.tgSendData({ action: 'redteam', reportId: id });
          }
          showInlineToast(container, 'Red Team запущен');
          break;

        case 'control':
          if (window.tgSendData) {
            window.tgSendData({ action: 'control', reportId: id });
          }
          showInlineToast(container, 'Контроль отправлен');
          break;

        case 'journalist':
          if (window.tgSendData) {
            window.tgSendData({ action: 'journalist', reportId: id });
          }
          showInlineToast(container, 'Журналист запущен');
          break;

        case 'counterforecast':
          if (window.tgSendData) {
            window.tgSendData({ action: 'counterforecast', reportId: id });
          }
          showInlineToast(container, 'Контр-прогноз запущен');
          break;

        case 'copy':
          copyToClipboard(reportHtml)
            .then(() => showInlineToast(container, 'Скопировано'))
            .catch(() => showInlineToast(container, 'Ошибка копирования'));
          break;

        case 'pdf':
          if (window.tgSendData) {
            window.tgSendData({ action: 'pdf', reportId: id });
          }
          showInlineToast(container, 'PDF запрошен');
          break;

        case 'share':
          if (window.tgSendData) {
            window.tgSendData({ action: 'share', reportId: id });
          }
          showInlineToast(container, 'Отправлено');
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