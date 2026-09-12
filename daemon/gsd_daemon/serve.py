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

  /* Studio console: sticky toolbar, the page itself scrolls only when it must. */
  html { overscroll-behavior: none; }
  .stage { min-height: 100dvh; }
  .topbar { position: sticky; top: 0; z-index: 5; display: flex; align-items: center; gap: 16px; padding: 8px 16px; background: var(--rail); border-bottom: 1px solid var(--line); }
  .brand { display: flex; gap: 8px; align-items: center; padding: 0; border: 0; background: none; color: var(--text); font-size: 16px; font-weight: 600; cursor: pointer; }
  .brand::before { content: "G"; display: grid; place-items: center; width: 24px; height: 24px; background: var(--accent-fill); color: var(--accent-fg); border-radius: 7px; font-size: 12.5px; }
  .summary { font-size: 12.5px; color: var(--dim); }
  .connection { margin-left: auto; font-size: 12.5px; display: flex; align-items: center; gap: 6px; }
  .settings-menu { position: relative; }
  .settings-menu summary { cursor: pointer; padding: 7px 12px; border: 1px solid var(--line); border-radius: 8px; list-style: none; }
  .settings-menu nav { position: absolute; right: 0; top: 100%; z-index: 10; display: grid; padding: 8px; background: var(--card); border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); white-space: nowrap; }
  .settings-menu .btn { text-align: left; border: 0; }

  /* Status board: one card per project holding its milestone stack. */
  .board { padding: 16px; display: grid; align-content: start;
           grid-template-columns: repeat(auto-fill, minmax(min(320px, 100%), 1fr)); gap: 14px; }
  .board .empty { grid-column: 1 / -1; padding: 28px; color: var(--dim); }
  .card { background: var(--card); border-radius: 14px; box-shadow: var(--shadow); padding: 12px 14px; min-width: 0; overflow-wrap: anywhere; }
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
  .card .vision { font-size: 12.5px; color: var(--dim); border-left: 3px solid var(--line); padding: 2px 10px; margin: 0 0 10px; }
  .ms .goal { font-size: 12px; color: var(--dim); margin-top: 2px; }
  .ms .intent { font-size: 12px; color: var(--dim); margin-top: 2px; font-style: italic; }
  .ms .meta { font-family: var(--mono); font-size: 11.5px; color: var(--faint); margin-top: 2px; }
  .ms .sub { font-size: 12px; color: var(--dim); margin-top: 3px; }
  .ms .waves small { display: block; color: var(--faint); font-size: 11px; margin-left: 14px; }
  .crit { display: flex; gap: 3px; margin-top: 5px; align-items: center; font-size: 12px; color: var(--dim); }
  .crit i { width: 14px; height: 6px; border-radius: 2px; background: var(--line); display: block; }
  .crit i.met { background: var(--run); } .crit i.not-met, .crit i.unverifiable { background: var(--danger); }
  .crit span { margin-left: 6px; }
  .phase-log { display: flex; gap: 2px; margin-top: 6px; align-items: flex-end; }
  .phase-log div { flex: 1; min-width: 0; text-align: center; font: 10px var(--mono); color: var(--faint); overflow: hidden; white-space: nowrap; }
  .phase-log div i { display: block; height: 4px; border-radius: 2px; background: var(--run); margin-bottom: 3px; }
  .phase-log div.now { color: var(--accent); } .phase-log div.now i { background: var(--accent); }
  .card .lesson { font-size: 12px; color: var(--dim); border-top: 1px dashed var(--line); margin-top: 6px; padding-top: 6px; }
  .card .lesson b { color: var(--faint); font-weight: 600; }

  /* Board: one compact row per project, grouped by state. */
  .board { display: block; padding: 10px 16px 24px; }
  .group { font-size: 10.5px; text-transform: uppercase; letter-spacing: .8px; color: var(--faint); padding: 12px 2px 6px; }
  .prow { display: grid; grid-template-columns: minmax(140px, 200px) minmax(0, 1fr) auto auto; gap: 14px; align-items: center;
          width: 100%; text-align: left; background: var(--card); border: 0; border-radius: 10px; box-shadow: var(--shadow);
          padding: 9px 14px; margin-bottom: 8px; color: var(--text); cursor: pointer; font: inherit; }
  .prow:hover { box-shadow: 0 0 0 1.5px var(--accent), var(--shadow); }
  .prow.shipped { padding: 6px 14px; }
  .prow .name { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 13.5px; min-width: 0; }
  .prow .name span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .prow .mid { min-width: 0; }
  .prow .stack { font-family: var(--mono); font-size: 12px; font-weight: 500; }
  .prow .stack .s-done { color: var(--run); } .prow .stack .s-now { color: var(--accent); } .prow .stack .s-now.blocked { color: var(--danger); } .prow .stack .s-ahead { color: var(--faint); }
  .prow .here { font-family: var(--mono); font-size: 11.5px; color: var(--dim); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .prow .spend { font-family: var(--mono); font-size: 11.5px; color: var(--dim); white-space: nowrap; }
  .board .empty { padding: 28px 0; color: var(--dim); }
  /* Project page: the full card, one scrolling page. */
  .page { padding: 16px; max-width: 860px; }
  .back { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; font-size: 12.5px; color: var(--text); cursor: pointer; white-space: nowrap; }
  .switcher { display: flex; gap: 2px; background: var(--sunken); padding: 3px; border-radius: 9px; overflow: auto; min-width: 0; }
  .switcher button { display: flex; align-items: center; gap: 6px; padding: 4px 10px; border: 0; border-radius: 7px; background: none; color: var(--dim); font-size: 12.5px; white-space: nowrap; cursor: pointer; }
  .switcher button.sel { background: var(--card); color: var(--text); box-shadow: var(--shadow); font-weight: 600; }
  /* Usage: cost, turns, models and the per-turn ledger from host session logs. */
  .usage { border-top: 1px solid var(--line); margin-top: 8px; padding-top: 8px; }
  .usage h4 { font-size: 11px; text-transform: uppercase; letter-spacing: .7px; color: var(--faint); margin: 0 0 4px; }
  .stat { display: flex; gap: 10px; flex-wrap: wrap; margin: 8px 0; }
  .stat div { background: var(--sunken); border-radius: 8px; padding: 6px 10px; min-width: 96px; }
  .stat .v { font-size: 15px; font-weight: 650; } .stat .k { font-size: 10.5px; color: var(--faint); text-transform: uppercase; letter-spacing: .5px; }
  .mrow { display: flex; align-items: center; gap: 10px; font-size: 12px; margin-top: 4px; }
  .mrow .nm { width: 150px; font-family: var(--mono); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .mrow .bar { flex: 1; margin: 0; } .mrow .bar > i.claude { background: var(--wait); } .mrow .bar > i.codex { background: var(--accent); }
  .mrow .r { width: 170px; text-align: right; color: var(--dim); font-family: var(--mono); font-size: 11px; }
  table.u { width: 100%; border-collapse: collapse; font-size: 11.5px; margin-top: 6px; }
  table.u th { text-align: left; color: var(--faint); font-size: 10px; text-transform: uppercase; letter-spacing: .5px; padding: 4px 6px; border-bottom: 1px solid var(--line); }
  table.u td { padding: 4px 6px; border-bottom: 1px solid var(--line); font-family: var(--mono); }
  table.u td.t { font-family: var(--ui); } table.u td.n, table.u th.n { text-align: right; }
  details.turns summary { cursor: pointer; font-size: 12px; color: var(--accent); margin-top: 8px; }
  .usage .note { font-size: 11px; color: var(--faint); margin-top: 6px; }
  .ms .meta .spend { color: var(--dim); }

  /* Settings views */
  .settings { width: 100%; max-width: 1000px; margin: 0 auto; padding: 24px 24px 40px; }
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
    .topbar { flex-wrap: wrap; gap: 8px; }
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
let CState = {view: "board", root: null};

function setHash() {
  if (CState.view === "project" && CState.root) history.replaceState(null, "", "#" + new URLSearchParams({project: CState.root}));
  else if (CState.view === "board") history.replaceState(null, "", location.pathname);
  else history.replaceState(null, "", "#" + CState.view);
}
function openProject(root) { CState.view = "project"; CState.root = root; setHash(); render(); window.scrollTo(0, 0); }
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
const fmt = n => n >= 1e6 ? (n/1e6).toFixed(1)+"M" : n >= 1e3 ? Math.round(n/1e3)+"k" : String(n);
const TASK_GLYPH = {done: "✓", failed: "✗"};
function waveRows(p) {
  const waves = Object.entries(p.waves || {}).map(([n, name]) => [Number(n), name]).sort((a, b) => a[0] - b[0]);
  const allDone = stateOf(p) === "shipped" || (p.tasks_total > 0 && p.tasks_done >= p.tasks_total);
  const tasks = p.tasks || [];
  return waves.map(([n, name]) => {
    const kind = p.current_wave != null ? (n < p.current_wave ? "done" : n === p.current_wave ? "now" : "ahead") : allDone ? "done" : "ahead";
    const glyph = kind === "done" ? "✓" : kind === "now" ? "●" : "○";
    const names = tasks.filter(t => t.wave === n).map(t => `${esc(t.id)} ${esc(t.title || "")} ${TASK_GLYPH[t.status] || (kind === "done" ? "✓" : "○")}`).join(" · ");
    return `<span class="w-${kind}">${glyph} wave ${n} ${esc(name)}${names ? `<small>${names}</small>` : ""}</span>`;
  }).join("");
}
function criteriaStrip(p) {
  const crits = p.criteria || [];
  if (!crits.length) return "";
  const met = crits.filter(c => c.verdict === "met").length;
  return `<div class="crit">${crits.map(c => `<i class="${esc(c.verdict || "")}" title="${esc((c.id ? c.id + " — " : "") + (c.text || ""))}"></i>`).join("")}<span>${met} of ${crits.length} criteria met</span></div>`;
}
function verifyLine(p) {
  const last = (p.ledger || [])[0];
  if (!last) return "";
  const ok = last.result === "pass";
  return `<div class="sub">verify <span style="color:${ok ? "var(--run)" : last.result === "fail" ? "var(--danger)" : "var(--dim)"}">${esc(last.result || "unknown")}${last.recorded_at ? " " + esc(shortT(last.recorded_at)) : ""}</span></div>`;
}
const PHASE_SHORT = {inspect: "insp", define: "def", research: "rsch", decide: "dec", roadmap: "rmap", plan: "plan", build: "build", ship: "ship", shipped: "done"};
function phaseLog(p) {
  const log = p.phase_log || [];
  if (!log.length) return "";
  return `<div class="phase-log">${log.map(e => `<div class="${e.phase === p.phase ? "now" : ""}" title="${esc(e.phase)} · ${esc(e.date)}"><i></i>${esc(PHASE_SHORT[e.phase] || String(e.phase).slice(0, 5))}<br>${esc(String(e.date).slice(5))}</div>`).join("")}</div>`;
}
const money = v => v == null ? "—" : "$" + Number(v).toFixed(2);
const spendText = slot => slot && slot.turns ? [slot.cost != null ? money(slot.cost) : null, `${slot.turns} turns`].filter(Boolean).join(" · ") : "";
const manifestMeta = (p, m) => {
  const mf = m.manifest || {};
  const slot = ((p.spend || {}).milestones || {})[m.number];
  return [mf.tasks_total != null ? `${mf.tasks_done} of ${mf.tasks_total} tasks` : null,
          mf.waves != null ? `${mf.waves} waves` : null,
          mf.cycles_avg != null ? `${mf.cycles_avg} review cycles avg` : null,
          m.integrated ? "integrated " + String(m.integrated).slice(0, 7) : null,
          mf.carried ? `${mf.carried} rulings carried` : null,
          spendText(slot) ? `<span class="spend">${spendText(slot)}</span>` : null].filter(Boolean).join(" · ");
};
function usageBlock(p, cur) {
  const sp = p.spend;
  if (!sp || !sp.turns) return "";
  const slot = (sp.milestones || {})[cur.number] || {turns: 0, tokens: 0, cost: null};
  const maxTok = Math.max(...sp.models.map(m => m.tokens), 1);
  const models = sp.models.map(m => `<div class="mrow"><span class="nm" title="${esc(m.model)}">${esc(m.model)}</span><span class="bar"><i class="${esc(m.host)}" style="width:${Math.max(2, Math.round(100 * m.tokens / maxTok))}%"></i></span><span class="r">${m.turns} turns · ${fmt(m.tokens)} · ${money(m.cost)}</span></div>`).join("");
  const agents = sp.agents.map(a => `<tr><td class="t">${esc(a.agent)}</td><td>${esc(a.models.join(", "))}</td><td class="n">${a.turns}</td><td class="n">${fmt(a.tokens)}</td><td class="n">${money(a.cost)}</td></tr>`).join("");
  const turns = sp.recent.map(t => `<tr><td>${esc(shortT(t.at))}</td><td class="t">${esc(t.agent)}</td><td>${esc(t.model || "?")}</td><td class="n">${fmt(t.tokens_in)}</td><td class="n">${fmt(t.tokens_cached)}</td><td class="n">${fmt(t.tokens_out)}</td><td class="n">${money(t.cost)}</td><td class="n">${t.duration_s != null ? t.duration_s + "s" : "—"}</td></tr>`).join("");
  const note = sp.unpriced.length ? `<div class="note">No price configured for ${esc(sp.unpriced.join(", "))}: tokens counted, cost excluded. Add prices per million tokens under "prices" in daemon.json.</div>` : "";
  return `<div class="usage"><h4>Usage · ${esc(cur.number)}</h4>
    <div class="stat"><div><div class="v">${money(slot.cost)}</div><div class="k">cost</div></div><div><div class="v">${slot.turns}</div><div class="k">turns</div></div><div><div class="v">${fmt(slot.tokens || 0)}</div><div class="k">tokens</div></div><div><div class="v">${sp.models.length}</div><div class="k">models</div></div><div><div class="v">${money(sp.cost)}</div><div class="k">all milestones</div></div><div><div class="v">${sp.turns}</div><div class="k">turns · all</div></div></div>
    ${models}
    <table class="u"><tr><th>Agent</th><th>Models</th><th class="n">Turns</th><th class="n">Tokens</th><th class="n">Cost</th></tr>${agents}</table>
    <details class="turns"><summary>Turn ledger · latest ${sp.recent.length} of ${sp.turns}</summary><table class="u"><tr><th>Time</th><th>Agent</th><th>Model</th><th class="n">In</th><th class="n">Cached</th><th class="n">Out</th><th class="n">Cost</th><th class="n">Dur</th></tr>${turns}</table></details>
    ${note}<div class="note">From host session logs matched to this project by working directory.</div></div>`;
}
function card(p) {
  const {before, cur, after} = milestoneStack(p);
  const st = stateOf(p);
  const here = [esc(p.phase || "no phase"), p.current_wave != null ? "wave " + p.current_wave : null].filter(Boolean).join(" · ");
  const entered = (p.phase_log || []).find(e => e.phase === p.phase) || (p.phase_log || []).slice(-1)[0];
  const age = dur(p.time_in_phase_s);
  const when = [entered ? "entered " + esc(entered.phase) + " " + esc(entered.date) : null, age].filter(Boolean).join(" · ");
  const progress = p.tasks_total
    ? `<div class="bar"><i style="width:${Math.round(100 * (p.tasks_done || 0) / p.tasks_total)}%"></i></div><div class="sub">${p.tasks_done || 0} of ${p.tasks_total} tasks${when ? " · " + when : ""}</div>`
    : `<div class="sub">${when ? when + " · " : ""}no tasks yet</div>`;
  const git = p.git ? `<div class="meta">${esc(p.git.branch || p.branch || "no branch")} · ${esc(String(p.git.head || "").slice(0, 7) || "—")}${p.git.dirty ? " · dirty" : ""}</div>`
                    : (p.branch ? `<div class="meta">${esc(p.branch)}</div>` : "");
  const depends = m => (m.depends || []).length ? ` <span class="faint">· after ${esc(m.depends.join(", "))}</span>` : "";
  const goal = m => m.goal ? `<div class="goal">${esc(m.goal)}</div>` : "";
  const doneRows = before.map(m => {
    const shipped = m.manifest && m.manifest.shipped;
    const meta = manifestMeta(p, m);
    return `<div class="ms done"><span class="k">${esc(m.number)}</span><div class="body">${esc(m.slug)} <span class="faint">· ${shipped ? "shipped " + esc(shipped) : esc(m.status || "shipped")}</span>${meta ? `<div class="meta">${meta}</div>` : ""}${goal(m)}</div></div>`;
  }).join("");
  const aheadRows = after.length
    ? after.map(m => `<div class="ms ahead"><span class="k">${esc(m.number)}</span><div class="body">${esc(m.slug)} <span>· ${esc(m.phase || m.status || "planned")}</span>${depends(m)}${goal(m)}</div></div>`).join("")
    : `<div class="ms ahead"><span class="k">—</span><div class="body">end of roadmap</div></div>`;
  const waves = waveRows(p);
  return `<article class="card" data-root="${esc(p.root)}">
    <div class="title"><span class="dot ${healthDot(p)}"></span><b>${esc(p.project || p.root)}</b><span class="pill ${st === "active" ? "progress" : st}">${esc(stateLabel(p))}</span></div>
    <div class="path">${esc(p.root)}</div>
    ${p.vision ? `<div class="vision">${esc(p.vision)}</div>` : ""}
    ${doneRows}
    <div class="ms now ${st}"><span class="k">${esc(cur.number)}</span><div class="body"><b>${esc(cur.slug)}</b> · ${here}${depends(cur)}${goal(cur)}${p.intent ? `<div class="intent">${esc(p.intent)}</div>` : ""}${progress}${waves ? `<div class="waves">${waves}</div>` : ""}${criteriaStrip(p)}${verifyLine(p)}${phaseLog(p)}${git}${usageBlock(p, cur)}</div></div>
    ${aheadRows}
    ${p.lesson ? `<div class="lesson"><b>latest lesson</b> · ${esc(p.lesson)}</div>` : ""}
  </article>`;
}
function stackLine(p) {
  const {before, cur, after} = milestoneStack(p);
  const st = stateOf(p);
  return [...before.map(m => `<span class="s-done">${esc(m.number)} ✓</span>`),
          `<span class="s-now ${st}">${esc(cur.number)} ${st === "blocked" ? "■" : st === "shipped" ? "✓" : "●"}</span>`,
          ...after.map(m => `<span class="s-ahead">${esc(m.number)} ○</span>`)].join("  ");
}
function boardRow(p) {
  const st = stateOf(p);
  const {cur} = milestoneStack(p);
  const crits = p.criteria || [];
  const last = (p.roadmap_milestones || []).filter(isDoneMilestone).slice(-1)[0];
  const here = [esc(p.phase || "no phase"), p.current_wave != null ? "wave " + p.current_wave : null,
                p.tasks_total ? `${p.tasks_done || 0} of ${p.tasks_total} tasks` : "no tasks yet",
                crits.length ? `${crits.filter(c => c.verdict === "met").length}/${crits.length} criteria` : null,
                last ? `last shipped ${esc(last.number)}${last.manifest && last.manifest.shipped ? " " + esc(last.manifest.shipped) : ""}` : null]
               .filter(Boolean).join(" · ") + (cur.goal ? " — " + esc(cur.goal) : "");
  const slot = ((p.spend || {}).milestones || {})[cur.number];
  return `<button class="prow ${st}" data-root="${esc(p.root)}" aria-label="Open ${esc(p.project || p.root)}">
    <span class="name"><span class="dot ${healthDot(p)}"></span><span>${esc(p.project || p.root)}</span></span>
    <span class="mid"><span class="stack">${stackLine(p)}</span>${st === "shipped" ? "" : `<span class="here" style="display:block">${here}</span>`}</span>
    <span class="spend">${spendText(slot)}</span>
    <span class="pill ${st === "active" ? "progress" : st}">${esc(stateLabel(p))}</span></button>`;
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
  const settings = `<details class="settings-menu"><summary>Settings</summary><nav aria-label="Settings"><button class="btn" data-nav="plugin">Plugin</button><button class="btn" data-nav="folders">Watched folders</button></nav></details>`;
  const status = `<span class="connection" role="status"><span class="dot ${ONLINE === null ? "" : ONLINE ? "g" : "r"}"></span> ${connection}</span>`;
  const current = CState.view === "project" ? projects.find(p => p.root === CState.root) : null;
  let header, body;
  if (current) {
    header = `<header class="topbar"><button class="back" data-nav="board" aria-label="Back to the status board">‹ Board</button><nav class="switcher" aria-label="Projects">${projects.map(q => `<button class="${q.root === current.root ? "sel" : ""}" data-root="${esc(q.root)}" aria-pressed="${q.root === current.root}"><span class="dot ${healthDot(q)}"></span>${esc(q.project || q.root)}</button>`).join("")}</nav>${status}${settings}</header>`;
    body = `<main class="page">${card(current)}</main>`;
  } else {
    header = `<header class="topbar"><button class="brand" data-nav="board" aria-label="GSD Path status board">GSD Path</button><span class="summary">${summary}</span>${status}${settings}</header>`;
    if (CState.view === "plugin") body = `<main class="settings"><h2>Plugin</h2>${tabPlugin()}</main>`;
    else if (CState.view === "folders") body = `<main class="settings"><h2>Watched folders</h2><p class="dim">Projects inside these folders appear automatically.</p>${(DAEMON.parents || []).map((path, i) => `<div class="folder-row"><span>${esc(path)}</span><button class="btn danger" data-remove-parent="${i}">Stop watching</button></div>`).join("")}<p style="margin-top:16px"><button class="btn" data-action="add-folder">Add folder…</button></p></main>`;
    else {
      if (CState.view === "project" && ONLINE !== null) { CState.view = "board"; CState.root = null; setHash(); }
      const empty = ONLINE === null ? "Loading projects…" : !ONLINE && !projects.length ? "Cannot load projects. Check the daemon connection." : "No projects yet. Add a watched folder to get started.";
      const groups = [["blocked", "Needs attention"], ["active", "In progress"], ["shipped", "Shipped"]]
        .map(([st, label]) => [label, projects.filter(p => stateOf(p) === st)]).filter(([, list]) => list.length)
        .map(([label, list]) => `<div class="group">${label} · ${list.length}</div>${list.map(boardRow).join("")}`).join("");
      body = `<main class="board" aria-label="Status board">${groups || `<div class="empty">${empty}</div>`}</main>`;
    }
  }
  const readingKey = JSON.stringify([CState.view, CState.root]);
  stage.innerHTML = header + body;
  stage.dataset.readingKey = readingKey;
  if (previousKey === readingKey) {
    stage.querySelector('.settings-menu').open = settingsOpen;
    window.scrollTo(...pageScroll);
    if (focusIndex >= 0) stage.querySelectorAll('button, summary, [tabindex]')[focusIndex]?.focus({preventScroll: true});
  }
}
document.getElementById("stage").addEventListener("click", event => {
  const b = event.target.closest("button");
  if (!b) return;
  if (b.dataset.nav) { CState.root = null; navigate(b.dataset.nav); }
  else if (b.dataset.root) openProject(b.dataset.root);
  else if (b.dataset.action === "add-folder") addParent();
  else if (b.dataset.removeParent != null) removeParent(DAEMON.parents[Number(b.dataset.removeParent)]);
});
function applyHash() {
  const h = location.hash.slice(1);
  if (h === "plugin" || h === "folders") {
    CState.view = h;
    if (h === "plugin") loadPlugin().then(render);
  } else {
    CState.root = new URLSearchParams(h).get("project") || null;
    CState.view = CState.root ? "project" : "board";
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
    # Bind before the first session scan: scanning every host session log on
    # the machine can take a while cold, and the dashboard must not wait on it.
    watcher.poll_once(scan_sessions=False)
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
