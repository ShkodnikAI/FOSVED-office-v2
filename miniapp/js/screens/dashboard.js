export async function render(container) {
  const data = await API.dashboard();
  if (data.status !== 'ok') { container.innerHTML = '<p>Error loading dashboard</p>'; return; }
  const {kpis, depts, admin} = data;
  const sc = kpis.rating >= 4 ? '#639922' : kpis.rating >= 3 ? '#EF9F27' : '#E24B4A';
  const st = kpis.rating >= 4 ? 'Active' : kpis.rating >= 3 ? 'Moderate' : 'Low';
  let h = '<div class="top-bar"><div class="top-bar-title" style="color:#C9A84C">&#9678; Fosved</div></div>';
  h += '<div class="dept-header" style="background:linear-gradient(135deg,#0F0F0F,#1a1a2e)"><h1>Fosved Office v2</h1><div class="dept-header-sub">' + st + ' &mdash; ' + kpis.rating + '/5 &nbsp;<span style="font-family:DM Mono;font-size:11px;color:rgba(255,255,255,0.6)">v0.7.10</span></div></div>';
  h += '<div class="kpi-row">';
  h += kc(kpis.tasks,'TASKS','#C9A84C') + kc('$'+kpis.cost_today,'COST','#185FA5') + kc(kpis.rating,'RATING',sc);
  h += kc(kpis.reports,'REPORTS','#639922');
  if (window.innerWidth>=481) h += kc(kpis.tasks_week,'WEEK','#888');
  h += '</div>';
  h += '<div style="padding:0 16px;margin:8px 0 4px;display:flex;justify-content:space-between;align-items:center"><div class="section-title" style="margin:0">Departments</div><span style="font-family:DM Mono;font-size:11px;color:#aaa">'+depts.length+'/13</span></div>';
  h += '<div class="dept-grid">';
  depts.forEach(d => {
    const dc = d.status==='active'?'#639922':d.status==='idle'?'#EF9F27':'#ccc';
    h += '<div class="card card-dept" style="border-left-color:'+d.color.accent+'" onclick="location.hash=\'/dept/'+d.slug+'\'">';
    h += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px"><span class="status-dot" style="background:'+dc+'"></span><span style="font-weight:600;font-size:14px">'+d.name.split(' — ')[0]+'</span><span style="margin-left:auto;font-family:DM Mono;font-size:12px;color:'+sc+'">'+d.rating+'</span></div>';
    h += '<div style="font-size:12px;color:#888;margin-bottom:2px">'+(d.name.includes(' — ')?d.name.split(' — ')[1]:'')+' &middot; '+d.calls+' calls</div>';
    if(d.override) h+='<div style="font-size:11px;color:#C9A84C;font-family:DM Mono">'+d.override+'</div>';
    h += '</div>';
  });
  h += '</div>';
  h += '<div style="padding:0 16px;margin:16px 0 8px;display:flex;justify-content:space-between;align-items:center"><div class="section-title" style="margin:0">Admin</div><span style="font-family:DM Mono;font-size:11px;color:#aaa">'+admin.code_health+'</span></div>';
  h += '<div class="card" style="margin:0 16px 16px"><div style="font-family:DM Mono;font-size:13px;color:#555">'+admin.nodes+' nodes &middot; '+admin.edges+' edges</div><div style="font-size:12px;color:#888;margin-top:4px">'+admin.issues+' issues &middot; '+admin.proposals+' proposals</div></div>';
  container.innerHTML = h;
}
function kc(v,l,c){return '<div class="card kpi"><div class="kpi-value" style="color:'+c+'">'+v+'</div><div class="kpi-label">'+l+'</div></div>';}
