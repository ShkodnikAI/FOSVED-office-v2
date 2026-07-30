/**
 * FOSVED Mini App — Badge Component
 */

export function createBadge(type, text) {
  const styles = {
    red:    'background:#FFF0F0;color:#C0392B;',
    orange: 'background:#FFFBF0;color:#A86C00;',
    green:  'background:#EEF7EE;color:#2D7A2D;',
    blue:   'background:#E6F1FB;color:#0C447C;',
    premium:'background:#0F0F0F;color:#C9A84C;',
  };
  return `<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;${styles[type]||styles.red}">${text}</span>`;
}

export function createStatusDot(status, label) {
  const colors = { online:'#639922', offline:'#E24B4A', away:'#EF9F27', busy:'#E24B4A' };
  return `<span style="display:inline-flex;align-items:center;gap:4px"><span class="status-dot" style="background:${colors[status]||colors.offline}"></span>${label?`<span style="font-size:11px;color:#888">${label}</span>`:''}</span>`;
}
