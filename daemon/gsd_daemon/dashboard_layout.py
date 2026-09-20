"""Project board and milestone layout, using the existing dashboard data contract."""

LAYOUT_CSS = r'''
  body { font-size:14px; }
  .topbar { padding:10px 28px; min-height:64px; background:var(--card); }
  .topnav { display:flex; gap:4px; margin-left:18px; }
  .topnav button { border:0; border-radius:7px; background:none; padding:8px 12px; min-height:40px; cursor:pointer; color:var(--dim); }
  .topnav button[aria-current=page] { background:var(--chrome); color:var(--text); }
  .page,.board,.settings { max-width:1450px; margin:0 auto; padding:32px 36px 60px; }
  .board-heading { display:flex; gap:20px; align-items:end; margin-bottom:26px; flex-wrap:wrap; }
  .board-heading h1 { font-size:28px; line-height:1.25; letter-spacing:-.025em; }
  .board-heading p { color:var(--dim); margin-top:8px; }
  .board-heading .segc { margin-left:auto; }
  .board-filters { display:flex; gap:8px; align-items:center; padding-bottom:16px; flex-wrap:wrap; }
  .board-filters .segc { background:transparent; padding:0; gap:4px; }
  .board-filters .segc button { min-height:40px; }
  .board-filters .segc button[aria-pressed=true] { color:var(--accent); background:var(--accent-soft); box-shadow:none; }
  .board-footer { display:flex; justify-content:space-between; gap:14px; padding-top:16px; color:var(--dim); font-size:12px; }
  .grid th { padding:14px 16px; text-transform:uppercase; font-size:11px; }
  .grid td { padding:18px 16px; vertical-align:top; }
  .grid th:first-child,.grid td:first-child { width:auto; padding-left:0; }
  .grid th:last-child,.grid td:last-child { padding-right:0; }
  .grid .pname { font-size:14px; }
  .grid .ppath { padding-left:0; margin-top:5px; max-width:240px; }
  .grid .milestone-name { margin-bottom:6px; font-size:13px; white-space:normal; }
  .grid .milestone-phase { display:flex; align-items:center; gap:8px; font-size:12px; color:var(--dim); }
  .grid .ago { font-size:11px; color:var(--dim); margin-top:6px; }
  .grid .health-note { font-size:12px; color:var(--dim); margin-top:7px; white-space:normal; max-width:32ch; }
  .grid .blocked .health-note { color:var(--danger); }
  .milestone-timeline { overflow-x:auto; }
  .timeline-head,.timeline-row { display:grid; grid-template-columns:minmax(170px,.8fr) repeat(3,minmax(200px,1fr)); gap:24px; min-width:830px; }
  .timeline-head { padding:14px 0; font-size:11px; color:var(--dim); text-transform:uppercase; }
  .timeline-row { border-top:1px solid var(--line); padding:24px 0; }
  .timeline-row .pname { min-height:40px; }
  .timeline-stop { padding-top:14px; position:relative; border-top:1px solid var(--line); margin-bottom:20px; }
  .timeline-stop:before { content:''; position:absolute; width:7px; height:7px; border-radius:50%; background:var(--dim); top:-4px; left:0; }
  .timeline-stop.current:before { background:var(--accent-fill); box-shadow:0 0 0 4px var(--accent-soft); }
  .timeline-stop.future:before { background:var(--bg); border:1px solid var(--dim); }
  .timeline-stop strong { display:block; font-size:13px; font-weight:550; margin:4px 0; }
  .timeline-stop p { color:var(--dim); font-size:12px; }
  .timeline-row .status-line { margin-top:6px; }
  .phead h1 { font-size:28px; }
  .cols { gap:40px; }
  .project-fold { margin:20px 0; border-top:1px solid var(--line); padding-top:12px; }
  .project-fold > summary { min-height:40px; align-content:center; cursor:pointer; font-size:14px; font-weight:600; }
  .settings-shell { max-width:1150px; }
  .settings-layout { display:grid; grid-template-columns:180px minmax(0,1fr); gap:40px; margin-top:26px; }
  .settings-nav { display:flex; flex-direction:column; gap:4px; }
  .settings-nav button { border:0; border-radius:7px; background:none; color:var(--dim); min-height:40px; padding:8px 12px; text-align:left; cursor:pointer; }
  .settings-nav button[aria-current=page] { background:var(--accent-soft); color:var(--accent); }
  .settings-content { min-width:0; }.settings-content h2 { font-size:20px; }
  .path-config .box { background:transparent; box-shadow:none; border-radius:0; border-bottom:1px solid var(--line); padding:20px 0; }
  .path-config .config-row { gap:12px; }.path-config .config-source { max-width:72ch; }
  @media(max-width:760px) { .page,.board,.settings { padding:24px 20px 50px; }.topbar { padding:8px 16px; }.topnav { margin-left:0; }.settings-layout { grid-template-columns:1fr; gap:20px; }.settings-nav { flex-direction:row; flex-wrap:wrap; }.board-heading .segc { margin-left:0; }.board-filters .search { width:100%; }.board-filters .segc { flex-wrap:wrap; }.connection { white-space:normal; } }
'''

LAYOUT_JS = r'''
function boardPage(projects) {
  const q=CState.q.trim().toLowerCase();
  const shown=projects.filter(p=>(CState.filter==='all'||stateOf(p)===CState.filter)&&[p.project,p.root,p.milestone].filter(Boolean).join(' ').toLowerCase().includes(q));
  const labels=[['all','All'],['active','In progress'],['blocked','Blocked'],['shipped','Shipped'],['unverified','Unverified']];
  const filters=labels.map(([key,label])=>`<button data-filter="${key}" aria-pressed="${CState.filter===key}">${label}<span>${key==='all'?projects.length:projects.filter(p=>stateOf(p)===key).length}</span></button>`).join('');
  const empty=ONLINE===null?'Loading projects…':!ONLINE&&!projects.length?'Cannot load projects. Check the daemon connection.':!projects.length?'No projects yet. Add a watched folder to get started.':'No projects match this filter.';
  const heading=`<div class="board-heading"><div><h1>Projects</h1><p>What shipped. Where things stand. What’s ahead.</p></div><div class="segc" role="group" aria-label="Project layout"><button data-layout="board" aria-pressed="${CState.layout!=='milestones'}">Board</button><button data-layout="milestones" aria-pressed="${CState.layout==='milestones'}">Milestones</button></div></div><div class="board-filters"><div class="segc" role="group" aria-label="Show projects">${filters}</div><label class="search">${ICON.search}<input type="search" data-search placeholder="Find a project…" aria-label="Filter projects" value="${esc(CState.q)}"></label></div>`;
  return `<main class="board" aria-label="Status board">${heading}${shown.length?(CState.layout==='milestones'?milestoneBoard(shown):`<div class="tablewrap"><table class="grid"><thead><tr><th>Project</th><th>Current milestone</th><th>Status</th><th class="n">Tasks</th><th class="n">Usage</th></tr></thead><tbody>${shown.map(boardRow).join('')}</tbody></table></div>`):`<div class="empty">${empty}</div>`}<div class="board-footer"><span>${shown.length} of ${projects.length} projects</span><span>Usage reflects matched host sessions</span></div></main>`;
}
function milestoneBoard(projects) {
  const stop=(m,kind)=>`<div class="timeline-stop ${kind}"><span class="mono dim">${esc(m.number||'')}</span><strong>${esc(m.slug||'Untitled milestone')}</strong>${m.goal?`<p>${esc(m.goal)}</p>`:''}<p>${esc([m.phase,m.status].filter(Boolean).join(' · '))}</p></div>`;
  return `<div class="milestone-timeline"><div class="timeline-head"><span>Project</span><span>Shipped</span><span>Current / latest</span><span>Planned</span></div>${projects.map(p=>{const {before,cur,after}=milestoneStack(p);return `<div class="timeline-row"><div><button class="pname" data-root="${esc(p.root)}">${esc(p.project||p.root)} ›</button><div class="status-line state ${stateOf(p)}">${esc(stateLabel(p))}</div></div><div>${before.length?before.map(m=>stop(m,'past')).join(''):'<p class="note">No earlier milestone recorded.</p>'}</div><div>${stop({...cur,phase:p.phase,status:stateLabel(p)},'current')}</div><div>${after.length?after.map(m=>stop(m,'future')).join(''):'<p class="note">No later milestone recorded.</p>'}</div></div>`}).join('')}</div>`;
}
function settingsFrame(title,body,config=false) {
  const nav=[['config','Path settings'],['folders','Watched folders'],['plugin','Plugin']].map(([view,label])=>`<button data-nav="${view}" aria-current="${CState.view===view?'page':'false'}">${label}</button>`).join('');
  return `<main class="settings settings-shell"><h1>Settings</h1><div class="settings-layout"><nav class="settings-nav" aria-label="Settings sections">${nav}</nav><section class="settings-content ${config?'path-config':''}"><h2>${title}</h2>${body}</section></div></main>`;
}
function foldProject(id,label,content) {
  return content?`<details class="project-fold" data-section="${id}"><summary>${label}</summary>${content}</details>`:'';
}
document.getElementById('stage').addEventListener('click',event=>{
  const b=event.target.closest('[data-layout]');
  if(b){CState.layout=b.dataset.layout;render();}
});
'''
