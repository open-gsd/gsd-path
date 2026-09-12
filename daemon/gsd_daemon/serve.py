from __future__ import annotations

import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional, Tuple

from .history import resolve_history_path
from .model import aggregate
from .plugin import PluginManager
from .probe import utc_now_iso
from .watcher import Watcher

DEFAULT_PORT = 8765

_PLUGIN_OP_LOCK = threading.Lock()
_PLUGIN_ENDPOINTS = (
    "/api/plugin/install",
    "/api/plugin/update",
    "/api/plugin/uninstall",
)


class _BadRequest(Exception):
    pass

DASHBOARD_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>gsd-path daemon</title>
<style>
  /* Studio tokens from gsd-cloud/web/app/globals.css. Keep both palettes in sync. */
  :root {
    --accent: #4f5fe0; --accent-fill: #4f5fe0; --accent-fg: #ffffff; --accent-soft: #edefff;
    --bg: #f7f8fa; --card: #ffffff; --sunken: #f2f4f7; --rail: #ffffff; --line: #e3e7ed;
    --text: #14161a; --dim: #5b6270; --faint: #66707e;
    --run: #0d7d53; --run-soft: #e6f7f0; --wait: #7c5205; --wait-soft: #fdf3e0; --danger: #b23a2c; --danger-soft: #fdecea;
    --shadow: 0 1px 2px rgb(16 24 40 / .06), 0 0 0 1px rgb(16 24 40 / .05);
    --run-fill: #0d7d53; --danger-fill: #b23a2c;
    --ui: Inter, -apple-system, "Segoe UI", sans-serif;
    --mono: "JetBrains Mono", ui-monospace, Menlo, monospace;
  }
  @media(prefers-color-scheme:dark) { :root:not([data-theme="light"]) {
    --accent: #7c8cff; --accent-fill: #5a68e8; --accent-soft: #1b1f3a;
    --bg: #0c0d10; --card: #131519; --sunken: #1a1d23; --rail: #0e1013; --line: #24272f;
    --text: #eceef2; --dim: #9ba1ad; --faint: #8b93a1;
    --run: #3ddc97; --run-soft: #0f2b22; --wait: #f5b544; --wait-soft: #2e2312; --danger: #ff6b5e; --danger-soft: #331715;
    --shadow: 0 1px 2px rgb(0 0 0 / .3), 0 0 0 1px rgb(255 255 255 / .04);
    --run-fill: #1f8f62; --danger-fill: #d9483a;
  }}
  :root[data-theme="dark"] {
    --accent: #7c8cff; --accent-fill: #5a68e8; --accent-soft: #1b1f3a;
    --bg: #0c0d10; --card: #131519; --sunken: #1a1d23; --rail: #0e1013; --line: #24272f;
    --text: #eceef2; --dim: #9ba1ad; --faint: #8b93a1;
    --run: #3ddc97; --run-soft: #0f2b22; --wait: #f5b544; --wait-soft: #2e2312; --danger: #ff6b5e; --danger-soft: #331715;
    --shadow: 0 1px 2px rgb(0 0 0 / .3), 0 0 0 1px rgb(255 255 255 / .04);
    --run-fill: #1f8f62; --danger-fill: #d9483a;
  }
  * { box-sizing: border-box; margin: 0; }
  body { background: var(--bg); color: var(--text); font: 14px/1.5 var(--ui); min-height: 100vh; }
  button { font: inherit; }
  button:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
  .dim { color: var(--dim); } .faint { color: var(--faint); }
  .mono { font-family: var(--mono); font-size: 12px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .dot.g { background: var(--run); } .dot.y { background: var(--wait); } .dot.r { background: var(--danger); }
  .pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; white-space: nowrap; }
  .pill.active, .pill.shipped { background: var(--run-soft); color: var(--run); }
  .pill.blocked { background: var(--danger-soft); color: var(--danger); }
  .pill.progress, .pill.done { background: var(--accent-soft); color: var(--accent); }
  .pill.missing { background: var(--sunken); color: var(--faint); }
  .pill.outdated { background: var(--wait-soft); color: var(--wait); }
  .btn { background: var(--card); border: 1px solid var(--line); color: var(--text); border-radius: 8px; padding: 7px 12px; font-size: 12px; cursor: pointer; }
  .btn:hover { border-color: var(--accent); }
  .btn.primary { background: var(--accent-fill); border-color: var(--accent-fill); color: var(--accent-fg); }
  .btn.danger { border-color: var(--danger); color: var(--danger); }
  kbd { background: var(--sunken); border: 1px solid var(--line); border-radius: 4px; padding: 0 5px; font: 11px var(--mono); }

  /* Studio console: fixed toolbar, the board scrolls. */
  .stage { display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100dvh; }
  .topbar { display: flex; align-items: center; gap: 16px; padding: 8px 16px; background: var(--rail); border-bottom: 1px solid var(--line); }
  .brand { display: flex; gap: 8px; align-items: center; padding: 0; border: 0; background: none; color: var(--text); font-size: 16px; font-weight: 600; cursor: pointer; }
  .brand::before { content: "G"; display: grid; place-items: center; width: 24px; height: 24px; background: var(--accent-fill); color: var(--accent-fg); border-radius: 7px; font-size: 12.5px; }
  .summary { font-size: 12.5px; color: var(--dim); }
  .connection { margin-left: auto; font-size: 12.5px; display: flex; align-items: center; gap: 6px; }
  .settings-menu { position: relative; }
  .settings-menu summary { cursor: pointer; padding: 7px 12px; border: 1px solid var(--line); border-radius: 8px; list-style: none; }
  .settings-menu nav { position: absolute; right: 0; top: 100%; z-index: 10; display: grid; padding: 8px; background: var(--card); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); white-space: nowrap; }
  .settings-menu .btn { text-align: left; border: 0; }

  /* Status board: one card per project holding its milestone stack. */
  .board { min-height: 0; overflow: auto; padding: 16px; display: grid; align-content: start;
           grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr)); gap: 14px; }
  .board .empty { grid-column: 1 / -1; padding: 28px; color: var(--dim); }
  .card { background: var(--card); border-radius: 14px; box-shadow: var(--shadow); padding: 12px 14px; min-width: 0; overflow-wrap: anywhere; }
  .card.sel { box-shadow: 0 0 0 2px var(--accent), var(--shadow); }
  .card .title { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .card .title b { font-size: 14px; }
  .card .title .pill { margin-left: auto; color: #fff; }
  .card .title .pill.progress { background: var(--accent-fill); }
  .card .title .pill.shipped { background: var(--run-fill); }
  .card .title .pill.blocked { background: var(--danger-fill); }
  .card .path { font-family: var(--mono); font-size: 11.5px; color: var(--faint); margin: -6px 0 8px; }
  .ms { display: flex; gap: 10px; padding: 6px 0; border-top: 1px solid var(--line); font-size: 12.5px; align-items: flex-start; }
  .ms:first-of-type { border-top: 0; }
  .ms .k { width: 48px; flex: none; font-family: var(--mono); font-size: 11.5px; padding-top: 2px; }
  .ms .body { min-width: 0; flex: 1; }
  .ms.done .k { color: var(--run); }
  .ms.now { background: var(--accent-soft); margin: 0 -14px; padding: 8px 14px; border-top: 0; border-radius: 8px; }
  .ms.now .k { color: var(--accent); }
  .ms.now.blocked .k { color: var(--danger); }
  .ms.ahead { color: var(--faint); }
  .ms .waves { margin-top: 4px; font-size: 12px; color: var(--dim); display: flex; flex-wrap: wrap; gap: 4px 12px; }
  .ms .waves .w-done { color: var(--run); } .ms .waves .w-now { color: var(--accent); } .ms .waves .w-ahead { color: var(--faint); }
  .ms .git { margin-top: 4px; font-family: var(--mono); font-size: 11.5px; color: var(--faint); }
  .bar { height: 4px; border-radius: 2px; background: var(--line); overflow: hidden; margin: 6px 0 3px; }
  .bar > i { display: block; height: 100%; background: var(--run); }

  /* Settings views */
  .settings { min-height: 0; overflow: auto; width: 100%; max-width: 1000px; margin: 0 auto; padding: 24px 24px 40px; }
  .settings h2 { font-size: 16px; font-weight: 600; margin-bottom: 16px; }
  .box { background: var(--card); border-radius: 14px; box-shadow: var(--shadow); padding: 16px; }
  .box h4 { font-size: 11px; text-transform: uppercase; letter-spacing: .6px; color: var(--faint); margin-bottom: 8px; }
  table.tasks { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  table.tasks th { text-align: left; color: var(--faint); font-size: 11px; text-transform: uppercase; letter-spacing: .5px; padding: 6px 10px; border-bottom: 1px solid var(--line); }
  table.tasks td { padding: 7px 10px; border-bottom: 1px solid var(--line); }
  .folder-row { display: flex; justify-content: space-between; gap: 16px; align-items: center; border-bottom: 1px solid var(--line); padding: 12px 0; font-family: var(--mono); font-size: 12.5px; }
  .modal-back { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; z-index: 50; }
  .modal { background: var(--card); border: 1px solid var(--line); border-radius: 12px; max-width: 760px; width: 90%; max-height: 80vh; overflow: auto; padding: 18px 22px; }
  .modal h3 { font-size: 15px; margin-bottom: 10px; }
  .modal .plist { font: 11.5px/1.7 var(--mono); color: var(--dim); max-height: 46vh; overflow: auto; margin: 8px 0 14px; }
  .browse-path { font: 12px var(--mono); color: var(--dim); word-break: break-all; background: var(--sunken); border: 1px solid var(--line); border-radius: 7px; padding: 5px 9px; margin-bottom: 8px; }
  .browse-list { max-height: 46vh; overflow: auto; margin: 0 0 12px; border: 1px solid var(--line); border-radius: 8px; }
  .browse-row { display: flex; align-items: center; gap: 8px; padding: 6px 12px; cursor: pointer; border-top: 1px solid var(--line); font-size: 13px; }
  .browse-row:first-child { border-top: none; }
  .browse-row:hover { background: var(--sunken); }
  .browse-row .proj { margin-left: auto; font-size: 10.5px; color: var(--run); }

  @media(max-width:760px) {
    .stage { display: block; height: auto; }
    .topbar { flex-wrap: wrap; gap: 8px; }
    .board, .settings { overflow: visible; }
  }
</style>
</head>
<body>
<div class="stage" id="stage"></div>
<script>
const DAEMON = __DAEMON_JSON__;
const esc = s => String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
const dur = s => {
  if (s == null) return null;
  const d = Math.floor(s/86400), h = Math.floor((s%86400)/3600), m = Math.floor((s%3600)/60);
  return d ? d+"d "+h+"h" : h ? h+"h "+m+"m" : m+"m";
};
const shortT = iso => typeof iso === "string" && iso.length >= 19 ? iso.slice(11,19) : (iso || "");
/* health comes from the backend; fall back to a local guess for older payloads */
const healthOf = p => p.health || (p.status === "blocked" ? "red" : "green");
const healthDot = p => ({red: "r", amber: "y", green: "g"})[healthOf(p)] || "g";

let DATA = {schema: null, generated_at: null, projects: []};
let PLUGIN = null;
let ONLINE = null;
let CState = {view: "board", root: null, reveal: false};

function setHash() {
  if (CState.view === "board") history.replaceState(null, "", CState.root ? "#" + new URLSearchParams({project: CState.root}) : location.pathname);
  else history.replaceState(null, "", "#" + CState.view);
}
function navigate(view) {
  CState.view = view;
  setHash(); render();
  if (view === "plugin") loadPlugin().then(render);
}
async function loadPlugin() {
  try {
    const r = await fetch("/api/plugin/status");
    if (r.ok) PLUGIN = await r.json();
  } catch (e) { /* keep last good data */ }
}
async function pluginOp(path, body) {
  let payload = {};
  try {
    const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"},
                                 body: JSON.stringify(body)});
    payload = await r.json().catch(() => ({}));
    if (r.status === 409) { alert("Another plugin operation is in progress — try again shortly."); return null; }
    if (!r.ok) { alert(payload.error || ("Request failed (" + r.status + ")")); return null; }
  } catch (e) { alert("Request failed: " + e); return null; }
  await loadPlugin();
  render();
  return payload;
}
async function uninstallPlan(body) {
  let payload = {};
  try {
    const r = await fetch("/api/plugin/uninstall", {method: "POST", headers: {"Content-Type": "application/json"},
                                                    body: JSON.stringify(Object.assign({}, body, {dry_run: true}))});
    payload = await r.json().catch(() => ({}));
    if (r.status === 409) { alert("Another plugin operation is in progress — try again shortly."); return; }
    if (!r.ok) { alert(payload.error || ("Request failed (" + r.status + ")")); return; }
  } catch (e) { alert("Request failed: " + e); return; }
  showPlanModal(body, payload.plan || {plan: [], skipped: []});
}
function showPlanModal(body, plan) {
  closeModal();
  const items = plan.plan.length
    ? plan.plan.map(e => '<div>remove <b>' + esc(e.kind) + '</b> ' + esc(e.path)
        + '<br><span class="faint">' + esc(e.reason) + '</span></div>').join("")
    : '<div class="dim">Nothing to remove.</div>';
  const skipped = (plan.skipped || []).map(e =>
    '<div class="faint">skip ' + esc(e.path) + ' — ' + esc(e.reason) + '</div>').join("");
  const back = document.createElement("div");
  back.className = "modal-back";
  back.id = "plan-modal";
  back.innerHTML = '<div class="modal"><h3>Uninstall plan — review before confirming</h3>'
    + '<div class="plist">' + items + (skipped ? '<div style="margin-top:10px">' + skipped + '</div>' : "") + '</div>'
    + '<div style="display:flex;gap:10px;justify-content:flex-end">'
    + '<button class="btn" id="plan-cancel">Cancel</button>'
    + (plan.plan.length ? '<button class="btn danger" id="plan-confirm">Confirm uninstall</button>' : "")
    + '</div></div>';
  document.body.appendChild(back);
  document.getElementById("plan-cancel").onclick = closeModal;
  const confirmBtn = document.getElementById("plan-confirm");
  if (confirmBtn) confirmBtn.onclick = async () => {
    closeModal();
    await pluginOp("/api/plugin/uninstall", Object.assign({}, body, {confirm: true}));
  };
  back.onclick = e => { if (e.target === back) closeModal(); };
}
function closeModal() {
  const existing = document.getElementById("plan-modal");
  if (existing) existing.remove();
}
async function parentOp(action, path) {
  try {
    const r = await fetch("/api/config/parents", {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({action, path})});
    const payload = await r.json().catch(() => ({}));
    if (!r.ok) { alert(payload.error || ("Request failed (" + r.status + ")")); return; }
    DAEMON.parents = payload.parents || DAEMON.parents;
  } catch (e) { alert("Request failed: " + e); return; }
  refresh();
}
function addParent() {
  openBrowseModal("~");
}
async function openBrowseModal(path) {
  closeModal();
  let payload = null;
  try {
    const r = await fetch("/api/fs/browse?path=" + encodeURIComponent(path));
    payload = await r.json().catch(() => ({}));
    if (!r.ok) { alert(payload.error || ("Browse failed (" + r.status + ")")); return; }
  } catch (e) { alert("Browse failed: " + e); return; }
  const rows = [];
  if (payload.parent) {
    rows.push('<div class="browse-row" data-path=' + JSON.stringify(payload.parent)
      + '>📁 <span class="dim">..</span></div>');
  }
  for (const d of (payload.dirs || [])) {
    rows.push('<div class="browse-row" data-path=' + JSON.stringify(d.path) + '>📁 ' + esc(d.name)
      + (d.project ? '<span class="proj">● gsd-path project</span>' : "") + '</div>');
  }
  if (!rows.length) rows.push('<div class="browse-row dim">(no subfolders)</div>');
  const back = document.createElement("div");
  back.className = "modal-back";
  back.id = "plan-modal";
  back.innerHTML = '<div class="modal"><h3>Choose a folder to watch</h3>'
    + '<div class="browse-path">' + esc(payload.path) + '</div>'
    + '<div class="browse-list">' + rows.join("") + '</div>'
    + (payload.truncated ? '<div class="faint" style="margin-bottom:8px">showing first 500 folders</div>' : "")
    + '<div style="display:flex;gap:10px;justify-content:flex-end">'
    + '<button class="btn" id="plan-cancel">Cancel</button>'
    + '<button class="btn primary" id="browse-select">Watch this folder</button>'
    + '</div></div>';
  document.body.appendChild(back);
  back.querySelectorAll(".browse-row[data-path]").forEach(row => {
    row.onclick = () => openBrowseModal(JSON.parse(row.getAttribute("data-path")));
  });
  document.getElementById("plan-cancel").onclick = closeModal;
  document.getElementById("browse-select").onclick = () => {
    closeModal();
    parentOp("add", payload.path);
  };
  back.onclick = e => { if (e.target === back) closeModal(); };
}
function removeParent(path) {
  if (confirm("Stop watching " + path + "?")) parentOp("remove", path);
}

async function refresh() {
  try {
    const response = await fetch("/status");
    if (!response.ok) throw new Error("Status unavailable");
    DATA = await response.json(); ONLINE = true;
  } catch (e) { ONLINE = false; }
  render();
}

/* ---- milestone stack: done / here / ahead from ROADMAP.md, STATE.md and next/STATE.md ---- */
const STATE_RANK = {blocked: 0, active: 1, shipped: 2};
const stateOf = p => p.status === "blocked" ? "blocked"
  : (p.phase === "shipped" || p.status === "shipped" || p.archive) ? "shipped" : "active";
const stateLabel = p => ({blocked: "Blocked", shipped: "Shipped"})[stateOf(p)] || ("In " + (p.phase || "progress"));
const isDoneMilestone = m => m.status === "shipped" || m.status === "archived" || !!m.archive;
function milestoneStack(p) {
  const rm = p.roadmap_milestones || [];
  const idx = rm.findIndex(m => m.slug === p.milestone);
  const fromBranch = String(p.branch || "").match(/M\d{3,}/);
  const cur = idx >= 0 ? rm[idx] : {number: fromBranch ? fromBranch[0] : "now", slug: p.milestone || "no milestone"};
  const before = idx >= 0 ? rm.slice(0, idx) : rm.filter(isDoneMilestone);
  const after = idx >= 0 ? rm.slice(idx + 1) : rm.filter(m => !isDoneMilestone(m));
  const next = p.next_milestone;
  if (next && next.milestone && next.milestone !== cur.slug && !after.some(m => m.slug === next.milestone)) {
    after.push({number: "next", slug: next.milestone, status: next.status || "planned", phase: next.phase});
  }
  return {before, cur, after};
}
function waveRows(p) {
  const waves = Object.entries(p.waves || {}).map(([n, name]) => [Number(n), name]).sort((a, b) => a[0] - b[0]);
  const allDone = stateOf(p) === "shipped" || (p.tasks_total > 0 && p.tasks_done >= p.tasks_total);
  return waves.map(([n, name]) => {
    const kind = p.current_wave != null ? (n < p.current_wave ? "done" : n === p.current_wave ? "now" : "ahead") : allDone ? "done" : "ahead";
    const glyph = kind === "done" ? "✓" : kind === "now" ? "●" : "○";
    return `<span class="w-${kind}">${glyph} wave ${n} ${esc(name)}</span>`;
  }).join("");
}
function card(p) {
  const {before, cur, after} = milestoneStack(p);
  const st = stateOf(p);
  const here = [esc(p.phase || "no phase"), p.current_wave != null ? "wave " + p.current_wave : null].filter(Boolean).join(" · ");
  const age = dur(p.time_in_phase_s);
  const progress = p.tasks_total
    ? `<div class="bar"><i style="width:${Math.round(100 * (p.tasks_done || 0) / p.tasks_total)}%"></i></div><div class="dim" style="font-size:12px">${p.tasks_done || 0} of ${p.tasks_total} tasks${age ? " · " + age + " in " + esc(p.phase || "phase") : ""}</div>`
    : `<div class="dim" style="font-size:12px;margin-top:4px">${age ? age + " in " + esc(p.phase || "phase") + " · " : ""}no tasks yet</div>`;
  const git = p.git ? `<div class="git">${esc(p.git.branch || p.branch || "no branch")} · ${esc(String(p.git.head || "").slice(0, 7) || "—")}${p.git.dirty ? " · dirty" : ""}</div>`
                    : (p.branch ? `<div class="git">${esc(p.branch)}</div>` : "");
  const doneRows = before.map(m => `<div class="ms done"><span class="k">${esc(m.number)}</span><div class="body">${esc(m.slug)} <span class="faint">· ${esc(m.status || "shipped")}</span></div></div>`).join("");
  const aheadRows = after.length
    ? after.map(m => `<div class="ms ahead"><span class="k">${esc(m.number)}</span><div class="body">${esc(m.slug)} <span>· ${esc(m.phase || m.status || "planned")}</span></div></div>`).join("")
    : `<div class="ms ahead"><span class="k">—</span><div class="body">end of roadmap</div></div>`;
  return `<article class="card ${CState.root === p.root ? "sel" : ""}" data-root="${esc(p.root)}">
    <div class="title"><span class="dot ${healthDot(p)}"></span><b>${esc(p.project || p.root)}</b><span class="pill ${st === "active" ? "progress" : st}">${esc(stateLabel(p))}</span></div>
    <div class="path">${esc(p.root)}</div>
    ${doneRows}
    <div class="ms now ${st}"><span class="k">${esc(cur.number)}</span><div class="body"><b>${esc(cur.slug)}</b> · ${here}${progress}${waveRows(p) ? `<div class="waves">${waveRows(p)}</div>` : ""}${git}</div></div>
    ${aheadRows}
  </article>`;
}
function tabPlugin() {
  if (!PLUGIN) {
    return '<p class="dim" style="padding:30px 0">Loading plugin status…</p>';
  }
  const hosts = PLUGIN.hosts || {};
  const latest = PLUGIN.latest || null;
  const installed = Object.entries(hosts).filter(([, d]) => d.installed);
  const versions = [...new Set(installed.map(([, d]) => d.version || "unknown"))];
  const banner = `<div class="box" style="margin:4px 0 14px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
    <span>Installed: <b>${esc(versions.join(", ") || "not installed")}</b></span>
    <span class="dim">Latest: <b>${esc(latest || "unknown")}</b></span>
    ${PLUGIN.update_available ? '<span class="pill outdated">Update available</span>'
      + "<button class='btn primary' onclick='pluginOp(&quot;/api/plugin/update&quot;, {scope:&quot;global&quot;})'>Update all</button>" : ""}
    <span style="margin-left:auto"></span>
    <button class="btn primary" onclick="pluginOp('/api/plugin/install', {scope:'global'})">Install for all detected hosts</button>
  </div>`;
  const rows = Object.entries(hosts).map(([h, d]) => {
    const pill = !d.installed ? '<span class="pill missing">not installed</span>'
      : (latest && d.version && d.version !== latest) ? '<span class="pill outdated">update available</span>'
      : '<span class="pill active">installed</span>';
    const actions = d.installed
      ? `<button class="btn" onclick="pluginOp('/api/plugin/update', {scope:'global'})">Update</button>
         <button class="btn danger" onclick="uninstallPlan({scope:'global', hosts:['${h}']})">Uninstall</button>`
      : `<button class="btn" onclick="pluginOp('/api/plugin/install', {scope:'global', hosts:['${h}']})">Install</button>`;
    return `<tr><td><b>${esc(h)}</b></td><td class="faint" style="word-break:break-all">${esc(d.root || "")}</td>
      <td>${esc(d.version || "—")}</td><td>${pill}</td>
      <td style="white-space:nowrap">${actions}</td></tr>`;
  }).join("");
  const hostsTable = `<div class="box"><h4>Global hosts</h4>
    <table class="tasks"><tr><th>Host</th><th>Skill root</th><th>Version</th><th>Status</th><th></th></tr>${rows}</table></div>`;
  const projects = (PLUGIN.projects || []).map(pr => {
    const pills = [
      pr.contracts ? '<span class="pill active">contracts</span>' : '<span class="pill missing">no contracts</span>',
      pr.runtime ? '<span class="pill active">runtime</span>' : '<span class="pill missing">no runtime</span>',
      pr.hooks ? '<span class="pill active">hooks</span>' : "",
      (pr.local_skills || []).length ? `<span class="pill done">local: ${esc(pr.local_skills.join(", "))}</span>` : "",
    ].filter(Boolean).join(" ");
    const root = JSON.stringify(pr.root);
    return `<tr><td class="faint" style="word-break:break-all">${esc(pr.root)}</td><td>${pills}</td>
      <td style="white-space:nowrap">
        <button class="btn" onclick='pluginOp("/api/plugin/install", {scope:"project", root:${root}})'>Install</button>
        <button class="btn" onclick='pluginOp("/api/plugin/update", {scope:"project", root:${root}})'>Update</button>
        <button class="btn danger" onclick='uninstallPlan({scope:"project", root:${root}})'>Uninstall</button>
      </td></tr>`;
  }).join("");
  const projectsBox = `<div class="box" style="margin-top:12px"><h4>Watched projects</h4>`
    + (projects ? `<table class="tasks"><tr><th>Project root</th><th>Installed</th><th></th></tr>${projects}</table>`
                : '<p class="dim">No watched projects.</p>') + `</div>`;
  return banner + hostsTable + projectsBox;
}
function render() {
  const stage = document.getElementById("stage");
  const previousKey = stage.dataset.readingKey;
  const scroll = ['.board', '.settings'].map(selector => {
    const el = stage.querySelector(selector);
    return [selector, el?.scrollTop || 0];
  });
  const settingsOpen = !!stage.querySelector('.settings-menu[open]');
  const pageScroll = [window.scrollX, window.scrollY];
  const focusIndex = [...stage.querySelectorAll('button, summary, [tabindex]')].indexOf(document.activeElement);
  const projects = (DATA.projects || []).slice().sort((a, b) =>
    STATE_RANK[stateOf(a)] - STATE_RANK[stateOf(b)] || String(a.project || a.root).localeCompare(String(b.project || b.root)));
  const counts = {blocked: 0, active: 0, shipped: 0};
  for (const p of projects) counts[stateOf(p)]++;
  const summary = projects.length
    ? [`${projects.length} project${projects.length === 1 ? "" : "s"}`,
       counts.active ? `${counts.active} in progress` : null,
       counts.blocked ? `${counts.blocked} blocked` : null,
       counts.shipped ? `${counts.shipped} shipped` : null].filter(Boolean).join(" · ")
    : "";
  const connection = ONLINE === null ? "Connecting…" : ONLINE ? "Connected" + (DATA.generated_at ? " · updated " + esc(shortT(DATA.generated_at)) : "") : "Offline · showing last update";
  const header = `<header class="topbar"><button class="brand" data-nav="board" aria-label="GSD Path status board">GSD Path</button><span class="summary">${summary}</span><span class="connection" role="status"><span class="dot ${ONLINE === null ? "" : ONLINE ? "g" : "r"}"></span> ${connection}</span><details class="settings-menu"><summary>Settings</summary><nav aria-label="Settings"><button class="btn" data-nav="plugin">Plugin</button><button class="btn" data-nav="folders">Watched folders</button></nav></details></header>`;
  let body;
  if (CState.view === "plugin") body = `<main class="settings"><h2>Plugin</h2>${tabPlugin()}</main>`;
  else if (CState.view === "folders") body = `<main class="settings"><h2>Watched folders</h2><p class="dim">Projects inside these folders appear automatically.</p>${(DAEMON.parents || []).map((path, i) => `<div class="folder-row"><span>${esc(path)}</span><button class="btn danger" data-remove-parent="${i}">Stop watching</button></div>`).join("")}<p style="margin-top:16px"><button class="btn" data-action="add-folder">Add folder…</button></p></main>`;
  else {
    const empty = ONLINE === null ? "Loading projects…" : !ONLINE && !projects.length ? "Cannot load projects. Check the daemon connection." : "No projects yet. Add a watched folder to get started.";
    body = `<main class="board" tabindex="0" aria-label="Status board">${projects.length ? projects.map(card).join("") : `<div class="empty">${empty}</div>`}</main>`;
  }
  const readingKey = JSON.stringify([CState.view, CState.root]);
  stage.innerHTML = header + body;
  stage.dataset.readingKey = readingKey;
  if (previousKey === readingKey) {
    stage.querySelector('.settings-menu').open = settingsOpen;
    for (const [selector, top] of scroll) stage.querySelector(selector)?.scrollTo(0, top);
    window.scrollTo(...pageScroll);
    if (focusIndex >= 0) stage.querySelectorAll('button, summary, [tabindex]')[focusIndex]?.focus({preventScroll: true});
  }
  if (CState.reveal) {
    const target = stage.querySelector('.card.sel');
    if (target) { target.scrollIntoView({block: "nearest"}); CState.reveal = false; }
  }
}
document.getElementById("stage").addEventListener("click", event => {
  const b = event.target.closest("button");
  if (b) {
    if (b.dataset.nav) { CState.root = null; navigate(b.dataset.nav); }
    else if (b.dataset.action === "add-folder") addParent();
    else if (b.dataset.removeParent != null) removeParent(DAEMON.parents[Number(b.dataset.removeParent)]);
    return;
  }
  const c = event.target.closest(".card");
  if (c) { CState.root = CState.root === c.dataset.root ? null : c.dataset.root; setHash(); render(); }
});
function applyHash() {
  const h = location.hash.slice(1);
  if (h === "plugin" || h === "folders") {
    CState.view = h;
    if (h === "plugin") loadPlugin().then(render);
  } else {
    CState.view = "board";
    CState.root = new URLSearchParams(h).get("project") || null;
    CState.reveal = !!CState.root;
  }
  render();
}
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    const menu = document.querySelector('.settings-menu[open]');
    if (menu) { menu.open = false; menu.querySelector('summary').focus(); }
  }
});
window.addEventListener("hashchange", applyHash);
applyHash();
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


def _read_activity(limit: int = 500) -> List[dict]:
    try:
        lines = resolve_history_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for line in reversed(lines[-limit:]):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _browse_dirs(raw_path: Optional[str]) -> Tuple[int, dict]:
    folder = os.path.abspath(os.path.expanduser((raw_path or "~").strip() or "~"))
    if not os.path.isdir(folder):
        return 400, {"error": f"not a directory: {folder}"}
    dirs = []
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                try:
                    if not entry.is_dir(follow_symlinks=True):
                        continue
                except OSError:
                    continue
                dirs.append({
                    "name": entry.name,
                    "path": os.path.join(folder, entry.name),
                    "project": os.path.isfile(
                        os.path.join(entry.path, ".project", "STATE.md")),
                })
    except PermissionError:
        return 403, {"error": f"permission denied: {folder}"}
    except OSError as error:
        return 400, {"error": str(error)}
    dirs.sort(key=lambda item: item["name"].lower())
    parent = os.path.dirname(folder)
    return 200, {
        "path": folder,
        "parent": parent if parent != folder else None,
        "dirs": dirs[:500],
        "truncated": len(dirs) > 500,
    }


class _Handler(BaseHTTPRequestHandler):
    watcher: Watcher = None  # set by serve()
    plugin: PluginManager = None  # set by serve()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._respond(200, "application/json", json.dumps({"ok": True}))
            return
        if path == "/api/fs/browse":
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code, payload = _browse_dirs((query.get("path") or [None])[0])
            self._respond(code, "application/json", json.dumps(payload, indent=2, sort_keys=True))
        elif path.startswith("/status"):
            payload = aggregate(list(self.watcher.projects.values()), utc_now_iso())
            payload["plugin"] = self._plugin_compact()
            self._respond(200, "application/json", json.dumps(payload, indent=2, sort_keys=True))
        elif path == "/api/plugin/status":
            payload = self._plugin_compact()
            try:
                payload["hosts"] = self.plugin.detect_global()
                roots = sorted(str(status.root) for status in self.watcher.projects.values())
                payload["projects"] = [self.plugin.detect_project(root) for root in roots]
            except Exception as error:  # detection must never break the dashboard
                payload["hosts"] = {}
                payload["projects"] = []
                payload["error"] = str(error)
            self._respond(200, "application/json", json.dumps(payload, indent=2, sort_keys=True))
        elif path == "/activity":
            payload = {"generated_at": utc_now_iso(), "events": _read_activity()}
            self._respond(200, "application/json", json.dumps(payload))
        elif path in ("/", "/index.html"):
            self._respond(200, "text/html; charset=utf-8", self._page())
        else:
            self._respond(404, "text/plain", "not found")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/config/parents":
            self._parents_op()
            return
        if path not in _PLUGIN_ENDPOINTS:
            self._respond(404, "text/plain", "not found")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
        except ValueError:
            self._respond(400, "application/json", json.dumps({"error": "invalid JSON body"}))
            return
        if not _PLUGIN_OP_LOCK.acquire(blocking=False):
            self._respond(409, "application/json",
                          json.dumps({"error": "operation in progress"}))
            return
        try:
            holder: dict = {}

            def work() -> None:
                try:
                    holder["result"] = self._plugin_op(path, body)
                except Exception as error:  # surfaced below, off the worker thread
                    holder["error"] = error

            worker = threading.Thread(target=work, daemon=True)
            worker.start()
            worker.join()
            if "error" in holder:
                raise holder["error"]
            code, payload = holder["result"]
        except _BadRequest as error:
            code, payload = 400, {"error": str(error)}
        except Exception as error:
            code, payload = 500, {"error": str(error)}
        finally:
            _PLUGIN_OP_LOCK.release()
        self._respond(code, "application/json", json.dumps(payload, indent=2, sort_keys=True))

    def _parents_op(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
        except ValueError:
            self._respond(400, "application/json", json.dumps({"error": "invalid JSON body"}))
            return
        action = body.get("action")
        folder = body.get("path")
        if action not in ("add", "remove") or not isinstance(folder, str) or not folder.strip():
            self._respond(400, "application/json",
                          json.dumps({"error": "expected {action: 'add'|'remove', path: <folder>}"}))
            return
        folder = os.path.abspath(os.path.expanduser(folder.strip()))
        if action == "add" and not os.path.isdir(folder):
            self._respond(400, "application/json",
                          json.dumps({"error": f"not a directory: {folder}"}))
            return
        config = self.watcher.config
        if action == "add":
            config.add_parent(folder)
        else:
            config.remove_parent(folder)
        try:
            config.save()
        except OSError as error:
            self._respond(500, "application/json", json.dumps({"error": str(error)}))
            return
        self._respond(200, "application/json", json.dumps(
            {"ok": True, "parents": list(config.parents),
             "projects": len(self.watcher.projects)},
            indent=2, sort_keys=True))

    def _plugin_compact(self) -> dict:
        """Cheap plugin status: VERSION probes + cache only, no git fetch."""
        try:
            update = self.plugin.check_update(fetch=False)
            hosts = {
                host: {"installed": entry["installed"], "version": entry["version"]}
                for host, entry in self.plugin.detect_global().items()
            }
            return {
                "latest": update["latest"],
                "update_available": update["update_available"],
                "hosts": hosts,
            }
        except Exception:
            return {"latest": None, "update_available": False, "hosts": {}}

    def _plugin_op(self, path: str, body: dict) -> tuple:
        manager = self.plugin
        scope = body.get("scope")
        dry_run = bool(body.get("dry_run"))
        if path == "/api/plugin/install":
            if scope == "global":
                return 200, manager.install_global(body.get("hosts"), dry_run=dry_run)
            if scope == "project":
                root = body.get("root")
                if not root:
                    raise _BadRequest("root is required for scope 'project'")
                return 200, manager.install_project(
                    root, local_hosts=body.get("local_hosts"),
                    hooks=bool(body.get("hooks")), dry_run=dry_run,
                )
            raise _BadRequest("scope must be 'global' or 'project'")
        if path == "/api/plugin/update":
            if scope == "project":
                root = body.get("root")
                if not root:
                    raise _BadRequest("root is required for scope 'project'")
                return 200, manager.update_project(root, dry_run=dry_run)
            return 200, manager.update_global(dry_run=dry_run)
        if path == "/api/plugin/uninstall":
            if scope == "project":
                root = body.get("root")
                if not root:
                    raise _BadRequest("root is required for scope 'project'")
                plan = manager.plan_uninstall_project(root)
            elif scope == "global" or scope is None:
                plan = manager.plan_uninstall_global(body.get("hosts"))
            else:
                raise _BadRequest("scope must be 'global' or 'project'")
            if dry_run:
                return 200, {"ok": True, "plan": plan}
            if not body.get("confirm"):
                raise _BadRequest(
                    "uninstall requires confirm=true (or dry_run=true to preview the plan)")
            result = manager.apply_plan(plan, confirm=True)
            result["plan"] = plan
            return 200, result
        raise _BadRequest("unknown plugin operation")

    def log_message(self, format, *args) -> None:  # noqa: A002 - stdlib signature
        pass

    def _respond(self, code: int, content_type: str, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _page(self) -> str:
        config = self.watcher.config
        daemon = {
            "parents": list(config.parents),
            "poll_seconds": config.poll_seconds,
        }
        return DASHBOARD_PAGE.replace("__DAEMON_JSON__", json.dumps(daemon))


def serve(watcher: Watcher, port: int = DEFAULT_PORT,
          plugin: Optional[PluginManager] = None) -> ThreadingHTTPServer:
    watcher.poll_once()
    handler = type("Handler", (_Handler,),
                   {"watcher": watcher, "plugin": plugin or PluginManager()})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    stop = threading.Event()
    server.watcher_stop = stop  # callers may set() to end the poll loop

    def poll_loop() -> None:
        while not stop.is_set():
            try:
                watcher.poll_once()
            except Exception:
                pass  # a failed cycle must never kill the poll loop
            stop.wait(watcher.config.poll_seconds)

    threading.Thread(target=poll_loop, daemon=True).start()
    return server


def serve_in_thread(
    watcher: Watcher, port: int = DEFAULT_PORT, plugin: Optional[PluginManager] = None
) -> Tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the dashboard server on a daemon thread; returns (server, thread).

    Callers shut it down with server.shutdown() + server.server_close().
    """
    server = serve(watcher, port, plugin=plugin)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def run(watcher: Watcher, port: int = DEFAULT_PORT) -> None:
    server = serve(watcher, port)
    host, actual_port = server.server_address[:2]
    print(f"serving on http://{host}:{actual_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
