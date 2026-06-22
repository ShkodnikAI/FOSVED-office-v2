export async function render(container, slug) {
  const data = await API.dept(slug);
  if (data.status !== 'ok') { container.innerHTML = '<p>Dept not found</p>'; return; }
  const {name,color,kpis,tasks,corrections,skills,model,provider} = data;
  const c = color||{start:'#334155',end:'#1e293b',accent:'#64748b'};
  let h = '<div class="top-bar"><div class="top-bar-title">'+name+'</div></div>';
  h += '<div class="dept-header" style="background:linear-gradient(135deg,'+c.start+','+c.end+')"><h1>'+name+'</h1><div class="dept-header-status">&#9679; Active &middot; '+model+'</div></div>';
  h += '<div class="kpi-row">'+kc(kpis.tasks,'TASKS','#C9A84C')+kc(kpis.rating,'RATING','#639922')+'</div>';
  if(tasks.length){
    h+='<div style="padding:0 16px;margin:12px 0 8px"><div class="section-title">Recent Tasks</div></div>';
    tasks.forEach(t=>{h+='<div class="card" style="margin:0 16px 6px;padding:12px"><div style="font-size:13px">'+t.text+'</div><div style="font-size:11px;color:#aaa;margin-top:4px">'+t.created+'</div></div>';});
  }
  if(skills.length){
    h+='<div style="padding:0 16px;margin:12px 0 8px"><div class="section-title">Skills</div></div>';
    h+='<div style="display:flex;flex-wrap:wrap;gap:6px;padding:0 16px">';
    skills.forEach(s=>{h+='<span class="chip">'+s+'</span>';});
    h+='</div>';
  }
  if(corrections.length){
    h+='<div style="padding:0 16px;margin:12px 0 8px"><div class="section-title">Corrections</div></div>';
    corrections.forEach(cr=>{h+='<div class="card" style="margin:0 16px 6px;padding:10px 12px;border-left:3px solid #EF9F27"><div style="font-size:12px;color:#555">'+cr.original+'</div><div style="font-size:11px;color:#aaa;margin-top:2px">'+cr.created+'</div></div>';});
  }
  h+='<div style="padding:0 16px;margin:12px 0 8px"><div class="section-title">Model</div></div>';
  h+='<div class="card" style="margin:0 16px"><div style="font-family:DM Mono;font-size:13px;color:#C9A84C">'+model+'</div><div style="font-size:12px;color:#888;margin-top:4px">Provider: '+provider+'</div></div>';
  container.innerHTML = h;
}
function kc(v,l,c){return '<div class="card kpi"><div class="kpi-value" style="color:'+c+'">'+v+'</div><div class="kpi-label">'+l+'</div></div>';}
