export async function render(container) {
  const data = await API.narads();
  if (data.status !== 'ok') { container.innerHTML = '<p>Error</p>'; return; }
  let h = '<div class="top-bar"><div class="top-bar-title">Narads</div></div>';
  if (!data.narads.length) h += '<div class="empty-state">No narads yet</div>';
  data.narads.forEach(n => {
    const sc = n.status==='approved'?'#639922':n.status==='rejected'?'#E24B4A':n.status==='done'?'#639922':'#EF9F27';
    const bg = n.status==='pending'?'#FFFBF0':n.status==='done'?'#EEF7EE':n.status==='rejected'?'#FFF0F0':'#EEF7EE';
    h += '<div class="narad-card"><div style="display:flex;align-items:center;gap:8px;margin-bottom:4px"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'+sc+'"></span><span style="font-family:DM Mono;font-size:11px;color:#888">'+n.id.substring(0,20)+'</span><span style="margin-left:auto;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;background:'+bg+';color:'+sc+'">'+n.status.toUpperCase()+'</span></div>';
    h += '<div style="font-size:14px;font-weight:500;margin-bottom:4px">'+(n.title||n.description||'Untitled')+'</div>';
    if(n.risk) h += '<div style="font-size:11px;color:#888">Risk: '+n.risk+'</div>';
    h += '<div style="font-size:11px;color:#aaa;margin-top:4px">'+n.created+'</div>';
    if (n.status==='pending') h += '<div style="display:flex;gap:6px;margin-top:8px"><button class="btn btn-outline" style="flex:1;font-size:12px" onclick="window._approve(\''+n.id+'\')">&#10003; Approve</button><button class="btn" style="flex:1;font-size:12px;background:#f5f5f5;border:none" onclick="window._reject(\''+n.id+'\')">&#10007; Reject</button></div>';
    h += '</div>';
  });
  container.innerHTML = h;
  window._approve = async function(id){ await API.naradApprove(id); location.reload(); };
  window._reject = async function(id){ await API.naradReject(id); location.reload(); };
}
