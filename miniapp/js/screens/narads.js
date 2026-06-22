/**
 * Fosved Office Mini App — Narads Screen (Screen 8)
 * Shows work orders with status badges and approve/reject actions.
 */

import { createTopBar, createNaradCard, createSectionTitle, esc } from '../components/card.js';

export async function render(container) {
  let html = '';

  // ── Top Bar ──
  html += createTopBar('Наряды');

  container.innerHTML = html + `<div style="text-align:center;padding:40px;color:#aaa">Loading narads...</div>`;

  let data;
  try {
    data = await API.narads();
  } catch (e) {
    container.innerHTML = `
      ${html}
      <div style="text-align:center;padding:60px;color:#E24B4A">Failed to load narads</div>`;
    return;
  }

  if (data.status !== 'ok') {
    container.innerHTML = `
      ${html}
      <div style="text-align:center;padding:60px;color:#E24B4A">${esc(data.error || 'Unknown error')}</div>`;
    return;
  }

  const narads = data.narads || [];

  // ── Summary Stats ──
  const pending = narads.filter(n => n.status === 'pending').length;
  const approved = narads.filter(n => n.status === 'approved' || n.status === 'done').length;
  const rejected = narads.filter(n => n.status === 'rejected' || n.status === 'failed').length;

  html += `
    <div style="padding:0 16px;margin:8px 0 12px;display:flex;gap:8px">
      <div class="card kpi" style="flex:1">
        <div class="kpi-value" style="color:#EF9F27">${pending}</div>
        <div class="kpi-label">PENDING</div>
      </div>
      <div class="card kpi" style="flex:1">
        <div class="kpi-value" style="color:#639922">${approved}</div>
        <div class="kpi-label">DONE</div>
      </div>
      <div class="card kpi" style="flex:1">
        <div class="kpi-value" style="color:#E24B4A">${rejected}</div>
        <div class="kpi-label">FAILED</div>
      </div>
    </div>`;

  // ── Narad List ──
  if (!narads.length) {
    html += `<div class="empty-state">
      <div style="font-size:36px;margin-bottom:12px">&#128203;</div>
      No narads yet
    </div>`;
  } else {
    html += createSectionTitle('WORK ORDERS', `${narads.length} total`);
    html += `<div style="padding:0 16px">`;
    for (const narad of narads) {
      html += createNaradCard(narad);
    }
    html += `</div>`;
  }

  container.innerHTML = html;

  // ── Wire approve/reject buttons ──
  wireActions(container);
}

/**
 * Attach event handlers to approve/reject buttons.
 */
function wireActions(container) {
  container.querySelectorAll('[data-action="approve"],[data-action="reject"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const action = btn.dataset.action;
      if (!id) return;

      // Disable buttons to prevent double-click
      const card = btn.closest('.narad-card');
      if (card) {
        card.querySelectorAll('button').forEach(b => {
          b.disabled = true;
          b.style.opacity = '0.5';
        });
      }

      try {
        if (action === 'approve') {
          await API.naradApprove(id);
        } else {
          await API.naradReject(id);
        }

        // Update the card visually without full reload
        if (card) {
          const statusEl = card.querySelector('[class*="badge"],[class*="PENDING"],[class*="APPROVED"]');
          // Remove action buttons
          const actionsDiv = card.querySelector('[style*="display:flex"][style*="gap:6px"]');
          if (actionsDiv) actionsDiv.remove();

          // Update status badge
          const statusSpans = card.querySelectorAll('span');
          for (const span of statusSpans) {
            if (span.textContent.trim() === 'PENDING') {
              span.textContent = action === 'approve' ? 'APPROVED' : 'REJECTED';
              span.style.color = action === 'approve' ? '#639922' : '#E24B4A';
              span.style.background = action === 'approve' ? '#EEF7EE' : '#FFF0F0';
              break;
            }
          }

          // Update status dot
          const dot = card.querySelector('.status-dot');
          if (dot) {
            dot.style.background = action === 'approve' ? '#639922' : '#E24B4A';
          }
        }
      } catch (e) {
        console.error('[Narads] Action failed:', e);
        // Re-enable buttons on error
        if (card) {
          card.querySelectorAll('button').forEach(b => {
            b.disabled = false;
            b.style.opacity = '1';
          });
        }
      }
    });
  });
}
