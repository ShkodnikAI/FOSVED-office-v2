export async function render(container) {
  const data = await API.models();
  if (data.status !== 'ok') { container.innerHTML = '<p>Error</p>'; return; }
  const {models,overrides,analytics} = data;
  const limited = models.find(m => m.status === 'limited');
  let h = '<div class="top-bar"><div class="top-bar-title">Models</div></div>';
  if (limited) h += '<div class="alert alert-orange" style="margin:12px 16px"><strong>'+limited.name+'</strong> &mdash; rate limit reached.</div>';
  h += '<div class="kpi-row"><div class="card kpi"><div class="kpi-value">'+analytics.requests_today+'</div><div class="kpi-label">REQUESTS</div></div><div class="card kpi"><div class="kpi-value">$'+analytics.cost_today+'</div><div class="kpi-label">COST</div></div><div class="card kpi"><div class="kpi-value">'+analytics.active_providers+'</div><div class="kpi-label">MODELS</div></div></div>';
  h += '<div style="padding:0 16px;margin:12px 0 8px"><div class="section-title">Active Models</div></div><div class="models-grid" style="padding:0 16px">';
  models.forEach(m => {
    const sc = m.status==='active'?'#639922':m.status==='limited'?'#EF9F27':m.status==='no_key'?'#E24B4A':'#888';
    const sl = m.status==='active'?'Active':m.status==='limited'?'Limited':m.status==='no_key'?'No Key':m.status;
    const tl = m.tier==='priority'?'Priority':m.tier==='paid'?'Paid':m.tier==='free'?'Free':m.tier==='free_limit'?'Free':m.tier==='cheap'?'Cheap':'Special';
    const ib = m.status==='active'?'#f0fdf4':m.status==='limited'?'#fffbeb':m.status==='no_key'?'#fef2f2':'#f5f5f5';
    h += '<div class="model-card"><div class="model-icon" style="background:'+ib+';color:'+sc+'">'+m.key.substring(0,2).toUpperCase()+'</div><div style="flex:1"><div style="font-size:14px;font-weight:500">'+m.name+'</div><div style="font-size:12px;color:#888">'+m.label+' &middot; '+tl+'</div><div style="font-family:DM Mono;font-size:11px;color:'+sc+';margin-top:2px">&#9679; '+sl+'</div></div></div>';
  });
  h += '</div>';
  const oe = Object.entries(overrides);
  if(oe.length){
    h += '<div style="padding:0 16px;margin:16px 0 8px"><div class="section-title">Overrides</div></div><div class="card" style="margin:0 16px">';
    oe.forEach(([d,v])=>{h+='<div style="font-size:13px;padding:4px 0;border-bottom:1px solid rgba(0,0,0,0.06)"><span style="font-weight:500">'+d+'</span> <span style="float:right;font-family:DM Mono;font-size:12px;color:#C9A84C">'+v+'</span></div>';});
    h += '</div>';
  }
  container.innerHTML = h;
}
