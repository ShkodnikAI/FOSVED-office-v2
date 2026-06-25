/**
 * Fosved Office Mini App — Narads Screen (Screen 8)
 * Shows work orders with status KPIs and approve/reject/retry/rollback actions.
 */

import { esc } from '../app.js';
import { createTopBar, createSectionTitle, createNaradCard } from '../components/card.js';

export async function render(container) {
  let html = '';

  // ── Top Bar ──
  html += createTopBar('Наряды Админа');

  // Show skeleton immediately
  container.innerHTML = html + '<div class="screen-scroll"><div style="text-align:center;padding:40px;color:#aaa">Загрузка нарядов...</div></div>';

  let data;
  try {
    data = await API.narads();
  } catch (e) {
    container.innerHTML = `
      ${html}
      <div class="screen-scroll">
        <div style="text-align:center;padding:60px;color:#E24B4A">Не удалось загрузить наряды</div>
      </div>`;
    return;
  }

  if (data.status !== 'ok') {
    container.innerHTML = `
      ${html}
      <div class="screen-scroll">
        <div style="text-align:center;padding:60px;color:#E24B4A">${esc(data.error || 'Ошибка')}</div>
      </div>`;
    return;
  }

  const narads = data.narads || [];

  // ── Summary KPIs ──
  const pending = narads.filter(n => n.status === 'pending').length;
  const done = narads.filter(n => n.status === 'approved' || n.status === 'done').length;
  const failed = narads.filter(n => n.status === 'rejected' || n.status === 'failed').length;

  html += '<div class="screen-scroll">';

  html += `
    <div style="padding:0 16px;margin:8px 0 12px;display:flex;gap:8px">
      <div class="card kpi" style="flex:1">
        <div class="kpi-value" style="color:#EF9F27">${pending}</div>
        <div class="kpi-label">PENDING</div>
      </div>
      <div class="card kpi" style="flex:1">
        <div class="kpi-value" style="color:#639922">${done}</div>
        <div class="kpi-label">ВЫПОЛНЕНО</div>
      </div>
      <div class="card kpi" style="flex:1">
        <div class="kpi-value" style="color:#E24B4A">${failed}</div>
        <div class="kpi-label">ОШИБКИ</div>
      </div>
    </div>`;

  // ── Narad List ──
  if (!narads.length) {
    html += `
      <div class="empty-state">
        <div style="font-size:36px;margin-bottom:12px">&#128203;</div>
        Нет нарядов
      </div>`;
  } else {
    html += createSectionTitle('НАРЯДЫ', `${narads.length}`);
    html += `<div style="padding:0 16px">`;
    for (const narad of narads) {
      html += createNaradCard(narad);
    }
    html += `</div>`;
  }

  html += '</div>'; // .screen-scroll

  container.innerHTML = html;

  // ── Wire all action buttons ──
  wireActions(container);
}

/**
 * Attach event handlers to approve, reject, retry, and rollback buttons.
 */
function wireActions(container) {
  container.querySelectorAll('[data-action="approve"],[data-action="reject"],[data-action="retry"],[data-action="rollback"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const action = btn.dataset.action;
      if (!id) return;

      const card = btn.closest('.narad-card');
      if (!card) return;

      // Disable all buttons in the card to prevent double-click
      card.querySelectorAll('button').forEach(b => {
        b.disabled = true;
        b.style.opacity = '0.5';
      });

      try {
        if (action === 'approve') {
          await API.naradApprove(id);
          updateCardStatus(card, 'approved');
        } else if (action === 'reject') {
          await API.naradReject(id);
          updateCardStatus(card, 'rejected');
        } else if (action === 'retry') {
          await API.naradApprove(id);
          updateCardStatus(card, 'done');
        } else if (action === 'rollback') {
          await API.naradReject(id);
          updateCardStatus(card, 'rejected');
        }
      } catch (e) {
        console.error('[Narads] Action failed:', e);
        // Re-enable buttons on error
        card.querySelectorAll('button').forEach(b => {
          b.disabled = false;
          b.style.opacity = '1';
        });
      }
    });
  });
}

/**
 * Update a narad card's visual state after a successful action.
 * @param {HTMLElement} card - The .narad-card element
 * @param {string} newStatus - 'approved', 'rejected', 'done'
 */
function updateCardStatus(card, newStatus) {
  const statusMap = {
    approved: { label: 'APPROVED', color: '#639922', border: '#639922' },
    rejected: { label: 'REJECTED', color: '#E24B4A', border: '#E24B4A' },
    done:     { label: 'DONE',     color: '#639922', border: '#639922' },
  };
  const s = statusMap[newStatus] || statusMap.approved;

  // Remove action buttons
  const actionsDiv = card.querySelector('.narad-actions');
  if (actionsDiv) actionsDiv.remove();

  // Update status badge
  const badge = card.querySelector('.badge');
  if (badge) {
    badge.textContent = s.label;
    badge.style.color = s.color;
    badge.style.background = newStatus === 'rejected' ? '#FFF0F0' : '#EEF7EE';
    badge.className = 'badge badge-' + (newStatus === 'rejected' ? 'err' : 'ok');
  }

  // Update border-left color
  card.style.borderLeftColor = s.border;

  // Update the narad-id color
  const naradId = card.querySelector('.narad-id');
  if (naradId) {
    naradId.style.color = s.color;
  }
}