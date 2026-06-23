/**
 * Fosved Office Mini App — Report Viewer Screen (Screen 4)
 * Fetches and displays a full HTML report with an action bar.
 */

import { esc } from '../components/card.js';

export async function render(container, id) {
  if (!id) {
    container.innerHTML = `<div class="empty-state">Report ID required</div>`;
    return;
  }

  let html = '';

  // ── Top Bar ──
  html += `
    <div class="top-bar">
      <div class="top-bar-title">Report</div>
      <span style="margin-left:auto;font-family:'DM Mono',monospace;font-size:11px;color:#aaa">${esc(id)}</span>
    </div>`;

  container.innerHTML = html + `<div style="text-align:center;padding:60px;color:#aaa">Loading report...</div>`;

  try {
    const response = await fetch('/miniapp/' + encodeURIComponent(id));
    if (!response.ok) {
      container.innerHTML = `
        ${html}
        <div class="empty-state">
          <div style="font-size:28px;margin-bottom:12px">&#128196;</div>
          Report not found
          <div style="font-size:12px;margin-top:8px;color:#ccc">${esc(id)}</div>
        </div>`;
      return;
    }

    const reportHtml = await response.text();

    // ── Report Content ──
    let content = html;
    content += `<div class="report-body">${reportHtml}</div>`;

    // ── Action Bar ──
    content += `
      <div class="action-bar">
        <button class="action-btn action-btn-gold" data-action="deepen">&#128269; Углубить</button>
        <button class="action-btn" data-action="control">&#9989; Контроль</button>
        <button class="action-btn" data-action="copy">&#128203; Копировать</button>
        <button class="action-btn" data-action="share">&#128279; Поделиться</button>
      </div>`;

    container.innerHTML = content;

    // Wire up action buttons
    wireActions(container, id, reportHtml);

  } catch (e) {
    container.innerHTML = `
      ${html}
      <div class="empty-state">
        <div style="font-size:28px;margin-bottom:12px">&#9888;&#65039;</div>
        Failed to load report
        <button class="btn btn-primary" style="margin-top:16px" onclick="location.reload()">Retry</button>
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
          // Trigger a deeper report generation via bot command
          if (window.tgSendData) {
            window.tgSendData({ action: 'deepen', reportId: id });
          } else {
            location.hash = '#/chat/yana';
          }
          break;

        case 'control':
          // Mark report for quality control
          if (window.tgSendData) {
            window.tgSendData({ action: 'control', reportId: id });
          }
          showInlineToast(container, 'Контроль отправлен');
          break;

        case 'copy':
          // Copy report text to clipboard
          copyToClipboard(reportHtml)
            .then(() => showInlineToast(container, 'Скопировано'))
            .catch(() => showInlineToast(container, 'Ошибка копирования'));
          break;

        case 'share':
          // Share via Telegram
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
 * Copy text to clipboard.
 */
async function copyToClipboard(text) {
  // Strip HTML tags for plain text copy
  const plain = text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  if (navigator.clipboard) {
    return navigator.clipboard.writeText(plain);
  }
  // Fallback for older browsers / restricted contexts
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
  });
  container.appendChild(toast);
  requestAnimationFrame(() => { toast.style.opacity = '1'; });
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 1500);
}
