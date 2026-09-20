"""Dashboard views for on-demand project records and the read-only file browser."""

RECORDS_CSS = r'''
  .source-link { border:0; background:none; color:var(--accent); padding:4px 0; cursor:pointer; font-size:12px; min-height:32px; }
  .project-tools { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin:16px 0; }
  .project-records { border-top:1px solid var(--line); margin-top:24px; padding-top:20px; }
  .project-records > details { border-bottom:1px solid var(--line); margin:0; padding:10px 0; }
  .project-records summary { min-height:40px; align-content:center; cursor:pointer; font-weight:600; }
  .project-records .record-error, .file-error { color:var(--danger); background:var(--danger-soft); padding:12px; border-radius:7px; overflow-wrap:anywhere; }
  .file-workspace { display:grid; grid-template-columns:250px minmax(0,1fr); border:1px solid var(--line); border-radius:10px; overflow:hidden; background:var(--card); margin-top:24px; }
  .file-sidebar { background:var(--chrome); padding:18px; border-right:1px solid var(--line); }
  .file-search { display:block; width:100%; min-height:40px; padding:8px 10px; margin:8px 0 20px; background:var(--card); border:1px solid var(--line); border-radius:7px; }
  .file-list { max-height:70vh; overflow:auto; }
  .file-list h3 { font-size:11px; color:var(--dim); margin:20px 8px 8px; text-transform:uppercase; letter-spacing:.05em; }
  .file-list button { display:block; width:100%; text-align:left; border:0; background:none; padding:9px 10px; border-radius:7px; cursor:pointer; overflow-wrap:anywhere; }
  .file-list button:hover { background:var(--hover); }
  .file-list button[aria-current=page] { color:var(--accent); background:var(--card); }
  .file-list small { display:block; color:var(--dim); font-size:10px; margin-top:3px; }
  .file-content { min-width:0; }
  .file-toolbar { display:flex; align-items:center; gap:12px; padding:18px 24px; border-bottom:1px solid var(--line); flex-wrap:wrap; }
  .file-toolbar .segc { margin-left:auto; }
  .file-path { overflow-wrap:anywhere; }
  .file-meta { font-size:11px; color:var(--dim); margin-top:5px; }
  .revision-bar { display:flex; align-items:center; gap:12px; flex-wrap:wrap; border-bottom:1px solid var(--line); padding:12px 24px; font-size:12px; }
  .revision-bar select { min-height:40px; max-width:100%; background:var(--card); border:1px solid var(--line); border-radius:7px; padding:8px; }
  .document { padding:28px 32px; min-height:320px; overflow-wrap:anywhere; }
  .document h1 { font-size:26px; margin:20px 0; }.document h2 { font-size:20px; margin:24px 0 12px; }.document h3 { margin:20px 0 10px; }
  .document p { margin:8px 0; max-width:72ch; line-height:1.7; }.document ul,.document ol { padding-left:24px; line-height:1.8; }
  .document pre,.record-json { white-space:pre-wrap; overflow-wrap:anywhere; background:var(--chrome); padding:16px; border-radius:7px; font:12px/1.7 var(--mono); }
  .document code { font-family:var(--mono); font-size:12px; background:var(--chrome); }
  .document table { border-collapse:collapse; width:100%; margin:18px 0; }.document td,.document th { padding:10px; border:1px solid var(--line); text-align:left; }
  .document hr { border:0; border-top:1px solid var(--line); margin:16px 0; }.document blockquote { margin:16px 0; padding:12px 16px; background:var(--chrome); }
  .document a { color:var(--accent); }.file-history { border-top:1px solid var(--line); padding:16px 24px; margin:0; }
  .file-history summary { min-height:40px; align-content:center; cursor:pointer; }.file-history button { display:flex; gap:16px; text-align:left; width:100%; background:none; border:0; border-top:1px solid var(--line); min-height:40px; padding:10px 0; cursor:pointer; }
  .file-history button:hover { color:var(--accent); }.file-history button span:last-child { margin-left:auto; }
  .record-tools { display:flex; gap:12px; align-items:center; margin:12px 0; flex-wrap:wrap; }
  .records-status { font-size:12px; color:var(--dim); }
  .breadcrumb { display:flex; gap:8px; align-items:center; color:var(--dim); margin-bottom:24px; font-size:12px; }
  @media(max-width:760px) { .file-workspace { grid-template-columns:1fr; }.file-sidebar { border-right:0; border-bottom:1px solid var(--line); }.file-list { max-height:30vh; }.document { padding:20px; }.file-toolbar,.revision-bar,.file-history { padding:14px; }.file-history button { flex-wrap:wrap; } }
'''

RECORDS_JS = r'''
const RECORDS = {root:null, data:null, error:'', busy:false, loadedAt:null};
const FILES = {root:null, path:'.project/STATE.md', revision:'', format:'preview', query:'', files:[], coverage:[], scope:'', data:null, history:null, error:'', busy:false, request:0};
const sourceLink = (path,label='View source') => `<button class="source-link" data-open-file="${esc(path)}">${esc(label)} ↗</button>`;
async function fileRequest(params) {
  const response = await fetch('/api/project-files?' + new URLSearchParams(params));
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Cannot load project file.');
  return data;
}
async function loadRecords(root) {
  RECORDS.root=root; RECORDS.busy=true; RECORDS.error=''; RECORDS.data=null; render();
  try {
    const response=await fetch('/api/project-data?' + new URLSearchParams({root}));
    const data=await response.json();
    if(RECORDS.root!==root)return;
    if(!response.ok)throw new Error(data.error || 'Cannot load project records.');
    RECORDS.data=data; RECORDS.loadedAt=new Date().toLocaleTimeString();
  } catch(error) { if(RECORDS.root===root) RECORDS.error=error.message; }
  if(RECORDS.root===root)RECORDS.busy=false;
  render();
}
async function openFiles(root,path='.project/STATE.md',revision='',updateHash=true) {
  const changedRoot=FILES.root!==root;
  FILES.root=root; FILES.path=path; FILES.revision=revision; FILES.data=null; FILES.history=null; FILES.error=''; FILES.busy=true;
  if(changedRoot){FILES.files=[];FILES.query='';FILES.coverage=[];}
  CState.root=root; CState.view='files'; if(updateHash)setHash(); render();
  const request=++FILES.request;
  try {
    const [listing,history] = await Promise.all([
      fileRequest({root,action:'list'}), fileRequest({root,path,action:'history'})
    ]);
    if(request!==FILES.request)return;
    FILES.files=listing.files;FILES.coverage=listing.coverage;FILES.scope=listing.scope;FILES.history=history;
    try { const content=await fileRequest({root,path,action:'read',...(revision?{revision}:{})}); if(request===FILES.request)FILES.data=content; }
    catch(error){if(request===FILES.request)FILES.error=error.message;}
  } catch(error){if(request===FILES.request)FILES.error=error.message;}
  if(request!==FILES.request)return;
  FILES.busy=false;render();
}
function filesPage(p) {
  const entries=FILES.files.filter(f=>f.path.toLowerCase().includes(FILES.query.toLowerCase()));
  const data=FILES.data, history=FILES.history;
  const markdown=/\.(md|markdown)$/i.test(FILES.path);
  return `<div class="breadcrumb"><button class="source-link" data-nav="board">Projects</button> / <button class="source-link" data-root="${esc(p.root)}">${esc(p.project||p.root)}</button> / History & files</div>
    <div class="phead"><h1>History & files</h1><span class="dim">Read-only · ${esc(p.project||p.root)}</span></div>
    <p class="note">Current files and committed versions. Uncommitted older contents are not retained by the watcher.</p>
    <div class="file-workspace"><aside class="file-sidebar"><label for="file-search">Find a file</label><input id="file-search" class="file-search" data-file-search placeholder="Name or path…" value="${esc(FILES.query)}"><nav class="file-list" aria-label="Project files">${entries.length?['Project records','Archived milestone','Repository'].map(group=>{const files=entries.filter(f=>f.group===group);return files.length?`<h3>${group}</h3>${files.map(f=>`<button data-select-file="${esc(f.path)}" aria-current="${f.path===FILES.path?'page':'false'}"><span>${esc(f.path.split('/').pop())}</span><small>${esc(f.path.split('/').slice(0,-1).join('/')||'Project root')}</small></button>`).join('')}`:''}).join(''):`<p class="note">${FILES.busy?'Loading files…':'No matching files.'}</p>`}</nav><p class="note">${esc(FILES.scope)}</p>${FILES.coverage.length?`<p class="file-error">${FILES.coverage.length} file sources need attention.</p><details><summary>Read errors</summary><pre class="record-json">${esc(JSON.stringify(FILES.coverage,null,2))}</pre></details>`:''}</aside>
    <section class="file-content"><div class="file-toolbar"><div><div class="file-path mono">${esc(FILES.path)}</div><div class="file-meta">${data?`${esc(data.group)} · ${int(data.bytes)} bytes · ${data.revision?'Committed file':data.modified?new Date(data.modified*1000).toLocaleString():'Working tree'}`:'File contents'}</div></div><div class="segc"><button data-file-format="preview" aria-pressed="${FILES.format==='preview'}" ${!markdown||!data?.html?'disabled':''}>Preview</button><button data-file-format="raw" aria-pressed="${FILES.format==='raw'}">Raw</button></div></div>
    <div class="revision-bar"><label for="file-revision">Version</label><select id="file-revision" data-file-revision ${FILES.busy?'disabled':''}><option value="">Working tree</option>${(history?.revisions||[]).map(v=>`<option value="${v.revision}" ${v.revision===FILES.revision?'selected':''}>${esc(v.at)} · ${esc(v.label)} · ${v.revision.slice(0,7)}</option>`).join('')}</select><button class="source-link" data-file-reload>Reload file</button></div>
    ${FILES.error?`<p class="file-error" role="alert">${esc(FILES.error)}</p>`:''}
    <article class="document" aria-label="File contents">${FILES.busy?'<p role="status">Loading file…</p>':data?`${data.preview_warning?`<p class="note">${esc(data.preview_warning)}</p>`:''}${FILES.format==='preview'&&data.html?data.html:`<pre>${esc(data.text)}</pre>`}`:''}</article>
    <details class="file-history" data-section="file-history"><summary>Git history · ${(history?.revisions||[]).length} revisions</summary><p class="note">${esc(history?.reason||'History could not be loaded.')}</p>${(history?.revisions||[]).map(v=>`<button data-file-version="${v.revision}"><span class="mono">${v.revision.slice(0,7)}</span><span>${esc(v.label)}</span><span class="dim">${esc(v.at)}</span></button>`).join('')}</details></section></div>`;
}
function recordTable(rows, columns) {
  if(!rows?.length)return '<p class="note">No records available from this source.</p>';
  return `<div class="tablewrap"><table class="t"><thead><tr>${columns.map(([_,label])=>`<th>${esc(label)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${columns.map(([key])=>`<td>${esc(row[key]==null?'—':typeof row[key]==='object'?JSON.stringify(row[key]):row[key])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function projectRecords(p) {
  const matching=RECORDS.root===p.root, data=matching?RECORDS.data:null;
  const section=(id,label,body)=>`<details data-section="${id}"><summary>${label}</summary>${body}</details>`;
  return `<section class="project-records"><h2>Records & sources</h2><div class="record-tools">${sourceLink('.project/STATE.md','History & files')}<button class="source-link" data-load-records="${esc(p.root)}" ${matching&&RECORDS.busy?'disabled':''}>${data?'Refresh full records':'Load full records'}</button><span class="records-status">${matching&&RECORDS.busy?'Loading…':data?'Loaded '+esc(RECORDS.loadedAt):'Full histories load on demand.'}</span></div>${matching&&RECORDS.error?`<p class="record-error" role="alert">${esc(RECORDS.error)}</p>`:''}
    ${section('discussions','Discussion answers',recordTable(p.answers||[],[['id','Answer'],['question','Question'],['status','Status'],['follow_up','Follow-up'],['owner','Owner']])+sourceLink('.project/discuss/ANSWERS.md','Read complete discussion record'))}
    ${section('build-usage','Pipeline usage by phase and task',p.usage?recordTable(p.usage.by_phase,[['phase','Phase'],['tokens','Tokens']])+recordTable(p.usage.by_task,[['task','Task'],['model','Model'],['tokens','Tokens']]):'<p class="note">No parsed pipeline usage is available.</p>')}
    ${data?section('full-verification','Full verification ledger',recordTable(data.verify_records,[['recorded_at','Recorded'],['task','Task'],['command','Command'],['commit','Commit'],['result','Result']])+sourceLink('.project/build/verify-ledger.jsonl','Read original ledger')):''}
    ${data?section('full-usage','Full pipeline usage records',recordTable(data.usage_records,[['task','Task'],['phase','Phase'],['model','Model'],['tokens_in','Input'],['tokens_out','Output'],['cost','Cost']])+sourceLink('.project/build/usage.jsonl','Read original usage')):''}
    ${data?section('full-turns','Full host turn ledger',recordTable(data.turns,[['at','Time'],['agent','Agent'],['host','Host'],['model','Model'],['tokens_in','Input'],['tokens_cached','Cached'],['tokens_out','Output'],['duration_s','Seconds'],['cost','Cost']])):''}
    ${data?section('full-activity','Full recorded activity',recordTable(data.activity,[['at','Time'],['type','Change'],['detail','Detail']])):''}
    ${data?section('coverage','Data coverage',`<p class="note">Available means the file can be opened, not that every field was parsed. Loaded sources report their actual record count. Unsupported hosts are not counted as zero.</p>`+recordTable(data.sources,[['path','Source'],['status','Status'],['records','Records'],['invalid_lines','Invalid lines'],['error','Read error'],['detail','Detail']])):''}
    <div class="record-tools">${sourceLink('.project/ROADMAP.md','Roadmap')}${sourceLink('.project/intent/INTENT.md','Intent')}${sourceLink('.project/plan/PLAN.md','Plan')}${sourceLink('.project/review/FINAL.md','Final review')}${sourceLink('.project/LESSONS.md','Lessons')}</div></section>`;
}
document.getElementById('stage').addEventListener('click',event=>{
  const b=event.target.closest('button');
  if(b?.dataset.openFile)openFiles(CState.root,b.dataset.openFile);
  else if(b?.dataset.selectFile)openFiles(FILES.root,b.dataset.selectFile);
  else if(b?.dataset.fileVersion)openFiles(FILES.root,FILES.path,b.dataset.fileVersion);
  else if(b?.dataset.fileFormat){FILES.format=b.dataset.fileFormat;render();}
  else if(b?.hasAttribute('data-file-reload'))openFiles(FILES.root,FILES.path,FILES.revision);
  else if(b?.dataset.loadRecords)loadRecords(b.dataset.loadRecords);
  const link=event.target.closest('[data-document-link]');
  if(link){event.preventDefault();const href=link.dataset.documentLink;
    if(href.startsWith('#'))return;
    const base=new URL(FILES.path,'http://project.invalid/');let target,path;
    try{target=new URL(href,base);path=decodeURIComponent(target.pathname.slice(1));}
    catch{return;}
    if(target.origin===base.origin)openFiles(FILES.root,path,FILES.revision);
  }
});
document.getElementById('stage').addEventListener('input',event=>{
  if(event.target.matches('[data-file-search]')){FILES.query=event.target.value;render();}
});
document.getElementById('stage').addEventListener('change',event=>{
  if(event.target.matches('[data-file-revision]'))openFiles(FILES.root,FILES.path,event.target.value);
});
'''
