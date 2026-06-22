export async function render(container) {
  let h = '<div class="top-bar"><div class="top-bar-title">Archive</div></div>';
  h += '<div style="padding:12px 16px;position:relative"><span style="position:absolute;left:28px;top:50%;transform:translateY(-50%);color:#aaa;font-size:16px">&#128269;</span><input class="search-input" id="archive-search" placeholder="Search reports..." onkeydown="if(event.key===\'Enter\')window._loadArc()" oninput="window._debArc()"></div>';
  h += '<div style="display:flex;gap:6px;padding:0 16px 12px;overflow-x:auto">';
  ['all','osp','lz','dev','finance','legal','marketing','expert','design','qa','visual','engineering','kavalnya','yana','admin'].forEach(d => {
    h += '<span class="chip ac" data-dept="'+d+'" onclick="window._filterArc(\''+d+'\')" style="white-space:nowrap">'+(d==='all'?'All':d.charAt(0).toUpperCase()+d.slice(1))+'</span>';
  });
  h += '</div><div id="arc-results"></div>';
  container.innerHTML = h;
  window._loadArc = loadArc;
  window._filterArc = function(dept){ document.querySelectorAll('.ac').forEach(c=>c.classList.toggle('chip-active',c.dataset.dept===dept)); loadArc(dept); };
  window._debArc = function(){ clearTimeout(window._dt); window._dt = setTimeout(loadArc,500); };
  await loadArc();
}
async function loadArc(df) {
  const s = document.getElementById('archive-search');
  const q = s?s.value:'';
  const dept = df||'all';
  try {
    const data = await API.archive(q,dept==='all'?'':dept);
    const r = document.getElementById('arc-results');
    if(!data.results||!data.results.length){ r.innerHTML='<div class="empty-state">No reports found</div>'; return; }
    const dc = {osp:'#b91c1c',lz:'#0e7490',expert:'#3730a3',marketing:'#c2410c',finance:'#15803d',legal:'#475569',dev:'#1d4ed8',design:'#be185d',qa:'#4d7c0f',visual:'#7e22ce',engineering:'#44403c',kavalnya:'#b45309',yana:'#293133',admin:'#1e40af'};
    let html='';
    data.results.forEach(x=>{ const c=dc[x.dept]||'#888';
      html+='<div class="archive-item" style="border-left-color:'+c+'" onclick="location.hash=\'/report/'+x.id+'\'"><div style="display:flex;align-items:center;gap:6px;margin-bottom:2px"><span style="font-weight:500;font-size:13px">'+x.dept.toUpperCase()+'</span><span style="font-size:11px;color:#aaa">'+x.created+'</span></div><div style="font-size:13px">'+x.title+'</div></div>';
    });
    r.innerHTML = html;
  } catch(e){ console.error('Archive error:',e); }
}
