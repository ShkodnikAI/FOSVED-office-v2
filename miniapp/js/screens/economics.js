export async function render(container) {
  const data = await API.economics();
  if (data.status !== 'ok') { container.innerHTML = '<p>Error</p>'; return; }
  const {periods,by_dept,by_provider,budget} = data;
  const mx = Math.max(...by_dept.map(d=>d.cost),1);
  let h = '<div class="top-bar"><div class="top-bar-title">Economics</div></div>';
  h += '<div class="econ-period" style="padding:12px 16px">'+ec('$'+periods.today,'TODAY')+ec('$'+periods.week,'WEEK')+ec('$'+periods.month,'MONTH')+'</div>';
  const bp = Math.min(100,(periods.today/parseFloat(budget||10))*100);
  h += '<div class="card" style="margin:0 16px 16px"><div style="display:flex;justify-content:space-between;align-items:center"><span style="font-size:14px;font-weight:500">Daily Budget</span><span style="font-family:DM Mono;font-size:13px">$'+periods.today+' / $'+budget+'</span></div><div class="progress-bar" style="margin-top:8px"><div class="progress-fill" style="width:'+bp+'%;background:'+(bp>90?'#E24B4A':'#C9A84C')+'"></div></div></div>';
  h += '<div style="padding:0 16px;margin:8px 0 4px"><div class="section-title">By Department (month)</div></div>';
  h += '<div class="card" style="margin:0 16px 12px">';
  by_dept.forEach(d=>{const p=Math.max(5,(d.cost/mx)*100);h+='<div class="hbar-row"><span class="hbar-label">'+d.name.split(' — ')[0]+'</span><div class="hbar-track"><div class="hbar-fill" style="width:'+p+'%"></div></div><span class="hbar-value">$'+d.cost+'</span></div>';});
  h += '</div>';
  h += '<div style="padding:0 16px;margin:8px 0 4px"><div class="section-title">By Provider (month)</div></div>';
  h += '<div class="card" style="margin:0 16px 12px">';
  const mp = Math.max(...by_provider.map(p=>p.cost),1);
  by_provider.forEach(p=>{const pc=Math.max(5,(p.cost/mp)*100);h+='<div class="hbar-row"><span class="hbar-label">'+p.provider+'</span><div class="hbar-track"><div class="hbar-fill" style="width:'+pc+'%"></div></div><span class="hbar-value">$'+p.cost+'</span></div>';});
  h += '</div>';
  container.innerHTML = h;
}
function ec(v,l){return '<div class="econ-period-card"><div style="font-family:DM Mono;font-size:20px;font-weight:700">'+v+'</div><div class="kpi-label">'+l+'</div></div>';}
