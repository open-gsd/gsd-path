from __future__ import annotations

import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional, Tuple

from .history import append_event, resolve_history_path
from .model import aggregate
from .plugin import PluginManager
from .path_settings import configure
from .project_files import FileAccessError, request_files
from .project_data import project_records
from .dashboard_records import RECORDS_CSS, RECORDS_JS
from .dashboard_layout import LAYOUT_CSS, LAYOUT_JS
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
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenGSD Path</title>
<style>
  /* Instrument palette: graphite neutrals and the macOS accent colour (system blue where AccentColor is unsupported). */
  :root {
    --bg: #fbfcfd; --chrome: #eef0f3; --card: #ffffff; --text: #1a1d22; --dim: #595e64; --faint: #71757a;
    --line: #e1e3e6; --hover: #f0f4f7; --seg: #e0e3e6; --done: #51565c;
    --accent: #0062cc; --accent-fill: #007aff; --accent-fg: #ffffff; --accent-soft: #e5f1ff;
    --danger: #c9302d; --danger-soft: #ffe7e4; --wait: #8d5e00; --wait-soft: #fdf1dc; --ok: #34c759;
    --run: var(--accent); --run-soft: var(--accent-soft); --sunken: var(--chrome);
    --shadow: 0 1px 2px rgb(26 29 34 / .08), 0 0 0 1px rgb(26 29 34 / .06);
    --ui: -apple-system, BlinkMacSystemFont, "SF Pro Text", Inter, "Segoe UI", system-ui, sans-serif;
    --mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace;
    color-scheme: light;
  }
  @media(prefers-color-scheme:dark) { :root:not([data-theme="light"]) {
    --bg: #101214; --chrome: #171a1d; --card: #141619; --text: #e9ebee; --dim: #a7abb1; --faint: #82878c;
    --line: #292c2f; --hover: #1d1f23; --seg: #2b2e32; --done: #a0a5ab;
    --accent: #4da3ff; --accent-fill: #0a84ff; --accent-fg: #ffffff; --accent-soft: #0f2640;
    --danger: #ef675c; --danger-soft: #47211d; --wait: #e4ac59; --wait-soft: #3a2a12; --ok: #30d158;
    --shadow: 0 1px 2px rgb(0 0 0 / .4), 0 0 0 1px rgb(255 255 255 / .06);
    color-scheme: dark;
  }}
  :root[data-theme="dark"] {
    --bg: #101214; --chrome: #171a1d; --card: #141619; --text: #e9ebee; --dim: #a7abb1; --faint: #82878c;
    --line: #292c2f; --hover: #1d1f23; --seg: #2b2e32; --done: #a0a5ab;
    --accent: #4da3ff; --accent-fill: #0a84ff; --accent-fg: #ffffff; --accent-soft: #0f2640;
    --danger: #ef675c; --danger-soft: #47211d; --wait: #e4ac59; --wait-soft: #3a2a12; --ok: #30d158;
    --shadow: 0 1px 2px rgb(0 0 0 / .4), 0 0 0 1px rgb(255 255 255 / .06);
    color-scheme: dark;
  }
  /* The OS accent where supported (WebKit, the tray's dashboard window). :root:root outranks the theme blocks. */
  @supports (color: AccentColor) { :root:root {
    --accent: AccentColor; --accent-fill: AccentColor; --accent-fg: AccentColorText;
    --accent-soft: color-mix(in srgb, AccentColor 11%, transparent);
  }}
  * { box-sizing: border-box; margin: 0; }
  body { background: var(--bg); color: var(--text); font: 13px/1.5 var(--ui); -webkit-font-smoothing: antialiased; min-height: 100vh; }
  button, input, select { font: inherit; color: inherit; }
  button:focus-visible, summary:focus-visible, select:focus-visible, tr:focus-visible { outline: 2px solid var(--accent-fill); outline-offset: 2px; }
  .dim { color: var(--dim); } .faint { color: var(--faint); }
  .mono { font-family: var(--mono); font-size: 12px; }
  .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; flex: none; background: var(--faint); }
  .dot.g { background: var(--ok); } .dot.y { background: var(--wait); } .dot.r { background: var(--danger); }
  .pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; white-space: nowrap; }
  .pill.active, .pill.shipped { background: var(--run-soft); color: var(--run); }
  .pill.blocked { background: var(--danger-soft); color: var(--danger); }
  .pill.progress, .pill.done { background: var(--accent-soft); color: var(--accent); }
  .pill.missing { background: var(--sunken); color: var(--faint); }
  .pill.outdated { background: var(--wait-soft); color: var(--wait); }
  .btn { background: var(--card); border: 1px solid var(--line); color: var(--text); border-radius: 7px; padding: 6px 12px; font-size: 12.5px; cursor: pointer; }
  .btn:hover { border-color: var(--faint); }
  .btn.primary { background: var(--accent-fill); border-color: var(--accent-fill); color: var(--accent-fg); }
  .btn.danger { border-color: var(--danger); color: var(--danger); }
  kbd { background: var(--sunken); border: 1px solid var(--line); border-radius: 4px; padding: 0 5px; font: 11px var(--mono); }

  /* Toolbar: title, filters and search on the board; back and project switcher on a project. */
  html { overscroll-behavior: none; }
  .stage { min-height: 100dvh; }
  .topbar { position: sticky; top: 0; z-index: 5; display: flex; align-items: center; gap: 12px; min-height: 52px; padding: 4px 16px; background: var(--chrome); border-bottom: 1px solid var(--line); }
  .brand { display: flex; gap: 8px; align-items: center; padding: 0; border: 0; background: none; font-size: 13.5px; font-weight: 650; cursor: pointer; white-space: nowrap; }
  .brand svg { width: 18px; height: 18px; flex: none; }
  .settings-menu summary svg, .search svg { width: 16px; height: 16px; flex: none; }
  .segc { display: flex; padding: 2px; border-radius: 7px; background: var(--seg); }
  .segc button { padding: 3px 12px; border: 0; border-radius: 5px; background: none; font-size: 12.5px; color: var(--dim); cursor: pointer; white-space: nowrap; }
  .segc button[aria-pressed="true"] { background: var(--card); color: var(--text); font-weight: 600; box-shadow: var(--shadow); }
  .segc button span { color: var(--faint); margin-left: 4px; font-weight: 400; font-variant-numeric: tabular-nums; }
  .search { margin-left: auto; display: flex; align-items: center; gap: 6px; height: 40px; width: 220px; padding: 0 8px; border-radius: 7px; background: var(--card); box-shadow: inset 0 0 0 1px var(--line); color: var(--faint); }
  .search input { border: 0; outline: 0; background: transparent; width: 100%; min-width: 0; font-size: 13px; color: var(--text); }
  .search:focus-within { box-shadow: inset 0 0 0 1px var(--accent-fill), 0 0 0 3px var(--accent-soft); }
  .back { display: flex; align-items: center; gap: 2px; padding: 4px 8px; border: 0; border-radius: 6px; background: none; color: var(--dim); cursor: pointer; white-space: nowrap; }
  .back:hover { background: var(--seg); color: var(--text); }
  .switcher { min-width: 0; max-width: 40vw; padding: 3px 6px; border: 0; border-radius: 6px; background: transparent; font-weight: 650; font-size: 13.5px; cursor: pointer; }
  .switcher:hover { background: var(--seg); }
  .connection { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--dim); white-space: nowrap; font-variant-numeric: tabular-nums; }
  .topbar .spacer { margin-left: auto; }
  .settings-menu { position: relative; }
  .settings-menu summary { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 6px; color: var(--dim); cursor: pointer; list-style: none; }
  .settings-menu summary::-webkit-details-marker { display: none; }
  .settings-menu summary:hover, .settings-menu[open] summary { background: var(--seg); color: var(--text); }
  .settings-menu nav { position: absolute; right: 0; top: calc(100% + 4px); z-index: 10; display: grid; padding: 4px; background: var(--card); border-radius: 9px; box-shadow: 0 8px 24px rgb(26 29 34 / .14), var(--shadow); white-space: nowrap; }
  .settings-menu .btn { text-align: left; border: 0; border-radius: 5px; }
  .settings-menu .btn:hover { background: var(--hover); color: var(--text); }
  .appearance { display: grid; gap: 4px; padding: 6px 8px 4px; margin-top: 4px; border-top: 1px solid var(--line); font-size: 11.5px; color: var(--faint); }
  .stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); margin: 0; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: var(--card); }
  .stats div { padding: 6px 10px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); margin: 0 -1px -1px 0; }
  .stats dt { font-size: 11px; color: var(--faint); }
  .stats dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; }
  .verdict-pass, .verdict-met { color: var(--accent); } .verdict-fail, .verdict-not-met, .verdict-unverifiable { color: var(--danger); }

  /* Board: one table row per project. */
  .board { padding-bottom: 24px; overflow-x: auto; }
  table.grid { width: 100%; border-collapse: collapse; min-width: 900px; table-layout: auto; }
  .grid th { text-align: left; font-size: 11.5px; font-weight: 600; color: var(--dim); padding: 8px 12px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  .grid td { padding: 8px 12px; border-bottom: 1px solid var(--line); vertical-align: middle; white-space: nowrap; }
  .grid th:first-child, .grid td:first-child { padding-left: 20px; width: 36%; }
  .grid .n { text-align: right; font-variant-numeric: tabular-nums; }
  .prow { cursor: pointer; }
  .prow:hover td { background: var(--hover); }
  .pname { display: flex; align-items: center; gap: 7px; padding: 0; border: 0; background: none; font-weight: 600; cursor: pointer; }
  .ppath { font: 11px var(--mono); color: var(--faint); padding-left: 14px; max-width: min(48vw, 640px); overflow: hidden; text-overflow: ellipsis; }
  .msl { max-width: min(32vw, 420px); overflow: hidden; text-overflow: ellipsis; }
  .msl .mono { color: var(--dim); margin-right: 4px; }
  .route { display: inline-flex; gap: 3px; vertical-align: middle; }
  .route i { width: 9px; height: 9px; border-radius: 2px; background: var(--done); }
  .route i.now { background: var(--accent-fill); } .route i.blocked { background: var(--danger); }
  .route i.ahead { background: none; box-shadow: inset 0 0 0 1.5px var(--faint); }
  .meter { display: inline-flex; gap: 2px; vertical-align: middle; margin-right: 8px; }
  .meter i { width: 10px; height: 8px; border-radius: 1.5px; background: var(--seg); }
  .meter i.done { background: var(--done); } .meter i.now { background: var(--accent-fill); }
  .meter.blocked i.now { background: var(--danger); }
  .phlabel { color: var(--dim); }
  .state { font-size: 12.5px; color: var(--dim); }
  .state.active { color: var(--accent); font-weight: 600; } .state.blocked { color: var(--danger); font-weight: 600; }
  .board .empty { padding: 28px 20px; color: var(--dim); }

  /* Project page: facts strip, then the path on the left and usage on the right. */
  .page { padding: 20px 24px 40px; width: 100%; max-width: none; }
  .phead { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; min-width: 0; }
  .phead h1 { font-size: 20px; font-weight: 680; letter-spacing: -.015em; }
  .phead .mono { color: var(--faint); overflow-wrap: anywhere; }
  .facts { display: flex; flex-wrap: wrap; margin: 14px 0 0; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: var(--card); }
  .facts div { padding: 7px 14px; border-right: 1px solid var(--line); min-width: 0; }
  .facts div:last-child { border-right: 0; }
  .facts dt { font-size: 11px; color: var(--faint); }
  .facts dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
  .vision { max-width: 80ch; color: var(--dim); margin-top: 12px; text-wrap: pretty; }
  .cols { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: 32px; margin-top: 8px; }
  .page h2 { font-size: 12.5px; font-weight: 650; margin: 20px 0 8px; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .page h2 span { color: var(--faint); font-weight: 400; }
  .phases { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 3px; }
  .phases div { font-size: 11.5px; color: var(--faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .phases i { display: block; height: 6px; border-radius: 2px; background: var(--seg); margin-bottom: 4px; }
  .phases .done { color: var(--dim); } .phases .done i { background: var(--done); }
  .phases .now { color: var(--accent); font-weight: 650; } .phases .now i { background: var(--accent-fill); }
  .phases.blocked .now { color: var(--danger); } .phases.blocked .now i { background: var(--danger); }
  .phases small { display: block; font: 10.5px var(--mono); }
  .now-box { margin-top: 10px; padding: 10px 12px; border-radius: 8px; background: var(--accent-soft); }
  .now-box.blocked { background: var(--danger-soft); }
  .goal { color: var(--dim); text-wrap: pretty; }
  .intent { color: var(--dim); font-style: italic; margin-top: 2px; }
  .sub { color: var(--dim); margin-top: 4px; }
  .bar { height: 4px; border-radius: 2px; background: var(--seg); overflow: hidden; margin: 8px 0 2px; }
  .bar > i { display: block; height: 100%; background: var(--accent-fill); }
  .crit { display: flex; gap: 3px; margin-top: 6px; align-items: center; color: var(--dim); }
  .crit i { width: 14px; height: 6px; border-radius: 2px; background: var(--seg); display: block; }
  .crit i.met { background: var(--accent-fill); } .crit i.not-met, .crit i.unverifiable { background: var(--danger); }
  .crit span { margin-left: 6px; }
  .waves { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 2px 14px; color: var(--dim); }
  .waves .w-done { color: var(--done); } .waves .w-now { color: var(--accent); font-weight: 600; } .waves .w-ahead { color: var(--faint); }
  table.t { width: 100%; border-collapse: collapse; }
  .t th { text-align: left; font-size: 11px; font-weight: 600; color: var(--faint); padding: 5px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  .t td { padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
  .t .n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .t td.mono, .t td.st { white-space: nowrap; }
  .t .goal, .t .meta { font-size: 12px; margin-top: 1px; }
  .t .meta { color: var(--faint); }
  .t tr.now td { background: var(--accent-soft); }
  .t tr.now.blocked td { background: var(--danger-soft); }
  .t tr.ahead td { color: var(--dim); }
  .t tr.end td { color: var(--faint); }
  .tablewrap { overflow-x: auto; }
  details.turns summary { cursor: pointer; color: var(--accent); margin-top: 12px; font-size: 12.5px; }
  .note { font-size: 12px; color: var(--faint); margin-top: 8px; max-width: 70ch; }
  .lesson { color: var(--dim); text-wrap: pretty; }

  @media(max-width:760px) {
    .topbar { flex-wrap: wrap; gap: 8px; }
    .search { width: 100%; order: 5; margin-left: 0; }
    .cols { grid-template-columns: minmax(0, 1fr); gap: 0; }
    .phases small { display: none; }
  }

  /* Settings views */
  .settings { width: 100%; max-width: 1000px; margin: 0 auto; padding: 24px 24px 40px; }
  .settings h2 { font-size: 16px; font-weight: 600; margin-bottom: 16px; }
  .path-config { display: grid; gap: 16px; }
  .path-config h2 { margin-bottom: 0; }
  .path-config h2, .path-config h3 { text-wrap: balance; }
  .path-config p { text-wrap: pretty; }
  .path-config h3 + p { margin: 4px 0 12px; }
  .path-config .config-row + .config-row { margin-top: 12px; }
  .path-config label { display: grid; gap: 5px; }
  .path-config input, .path-config select { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; min-width: 0; }
  .path-config .config-row { display: flex; gap: 8px; align-items: end; flex-wrap: wrap; }
  .path-config .config-row label { flex: 1; min-width: 0; }
  .path-config .config-source { overflow-wrap: anywhere; font-size: 12px; margin-top: 6px; }
  /* Match the skill's 40px desktop / 44px touch targets without overlapping hit areas. */
  .topbar button, .topbar select, .path-config button, .path-config input, .path-config select {
    min-height: 40px; min-width: 40px;
  }
  .path-config summary { min-height: 40px; align-content: center; cursor: pointer; color: var(--dim); }
  .path-config summary:hover { color: var(--text); }
  .path-config .btn:not(:disabled):hover, .topbar .btn:not(:disabled):hover { background: var(--hover); }
  .path-config .btn:not(:disabled):active, .topbar .btn:not(:disabled):active { background: var(--seg); }
  .path-config .btn.primary:not(:disabled):hover { background: var(--accent-fill); filter: brightness(.95); }
  .path-config .btn.primary:not(:disabled):active { background: var(--accent-fill); filter: brightness(.9); }
  @media (max-width: 760px) {
    .path-config .config-row label { flex-basis: 100%; }
  }
  @media (pointer: coarse) {
    .topbar button, .topbar select, .path-config button, .path-config input, .path-config select, .path-config summary { min-height: 44px; min-width: 44px; }
    .settings-menu summary { width: 44px; height: 44px; }
    .search { height: 44px; }
  }
  .path-config button:disabled, .path-config input:disabled, .path-config select:disabled { opacity: .6; cursor: not-allowed; }
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

__RECORDS_CSS__
__LAYOUT_CSS__
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
const healthReason = p => [healthOf(p), ...(p.attention || []).map(a => a.label).filter(Boolean)].join(" · ");
const healthDot = p => ({red: "r", amber: "y", green: "g"})[healthOf(p)] || "g";

let DATA = {schema: null, generated_at: null, projects: []};
let PLUGIN = null;
let PLUGIN_OP = null;
let ONLINE = null;
let CState = {view: "board", root: null, filter: "all", q: ""};
let ACTIVITY = [];
const CFG = {root: '', data: null, drafts: {}, busy: false, error: '', message: '', role: 'coder', host: '', field: 'model'};
const configScope = () => CFG.root ? {scope:'project', root:CFG.root} : {scope:'user'};
const configModelKey = () => 'models.' + (CFG.host ? 'hosts.' + CFG.host : 'roles') + '.' + CFG.role + '.' + CFG.field;
async function loadConfig() {
  const root = CFG.root;
  CFG.data = null; CFG.error = ''; CFG.message = ''; CFG.drafts = {};
  render();
  try {
    const response = await fetch('/api/path-config?' + new URLSearchParams(configScope()));
    const data = await response.json();
    if (root !== CFG.root) return;
    if (!response.ok) throw new Error(data.error || 'Cannot load settings.');
    CFG.data = data;
  } catch (error) { if (root === CFG.root) CFG.error = error.message; }
  render();
}
async function saveConfig(key, reset=false) {
  if (CFG.busy) return;
  const value = document.querySelector('[data-config-key="' + key + '"]')?.value;
  CFG.busy = true; CFG.error = ''; CFG.message = ''; render();
  try {
    const response = await fetch('/api/path-config', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({...configScope(), action:reset ? 'reset' : 'set', key, value})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Cannot save settings.');
    CFG.data = data; delete CFG.drafts[key]; CFG.message = 'Saved. ' + (key === 'integration'
      ? (CFG.root ? 'Project shipping default updated.' : 'Applies to newly initialized projects.')
      : key === 'review_panel' ? 'Applies when preparing future review approvals.' : 'Applies to new assignments; running assignments keep their selection.');
  } catch (error) { CFG.error = error.message; }
  CFG.busy = false; render();
}
function pathConfigPage() {
  const data = CFG.data, disabled = CFG.busy || data?.locked;
  const options = (values, current) => values.map(([value, label]) => `<option value="${esc(value)}" ${value === current ? 'selected' : ''}>${esc(label)}</option>`).join('');
  const scope = `<label>Settings for<select data-config-scope ${CFG.busy ? 'disabled' : ''}>${options([['','User defaults'], ...(DATA.projects || []).map(p => [p.root, p.project || p.root])], CFG.root)}</select></label>`;
  const feedback = `<p role="${CFG.error ? 'alert' : 'status'}">${esc(CFG.error || CFG.message || (CFG.busy ? 'Saving…' : ''))}</p>`;
  if (!data) return scope + feedback + (CFG.error ? '' : '<p class="dim">Loading settings…</p>');
  const setting = (key, label, choices, note) => {
    const item = data.settings[key], locked = disabled || item.locked;
    const value = CFG.drafts[key] ?? item.value;
    const control = choices ? `<select data-config-key="${key}" ${locked ? 'disabled' : ''}>${options(choices.map(v => [v, v === 'pull-request' ? 'Pull request' : 'Direct integration']), value)}</select>`
      : `<input data-config-key="${key}" value="${esc(value)}" ${locked ? 'disabled' : ''} list="panel-options">`;
    return `<section class="box"><div class="config-row"><label>${label}${control}</label><button class="btn primary" data-save-config="${key}" ${locked ? 'disabled' : ''}>Save</button>${key !== 'integration' || !CFG.root ? `<button class="btn" data-reset-config="${key}" ${locked ? 'disabled' : ''}>Reset</button>` : ''}</div>
      <p class="dim config-source">${esc(item.locked || note)}</p><p class="dim config-source">Source: ${esc(item.source)}</p>
      ${key === 'integration' && CFG.root ? `<p class="dim">Current milestone: ${esc(item.current)} (${esc(item.current_source)})</p>` : ''}</section>`;
  };
  const modelKey = configModelKey(), item = data.models[modelKey];
  const modelValue = CFG.drafts[modelKey] ?? item?.value ?? 'inherit';
  return scope + feedback + (data.locked ? `<p role="status">${esc(data.locked)}</p>` : '')
    + setting('integration', 'Shipping mode', ['direct','pull-request'], CFG.root ? 'Changes the project default; explicit milestone overrides are retained.' : 'Used when a new project is initialized.')
    + setting('review_panel', 'Review panel preference', null, 'off, detected, or comma-separated model families. Quick lane keeps panels off.')
    + `<datalist id="panel-options"><option value="off"><option value="detected"></datalist>`
    + (data.approved_review_panel ? `<p class="dim">Recorded review panel: ${esc(data.approved_review_panel.value)} (${esc(data.approved_review_panel.source)}). Approved review contracts keep their values.</p>` : '')
    + `<section class="box"><h3>Agent models and effort</h3><p class="dim">Use an exact value advertised by your host, or inherit. Unsupported values stop dispatch. Reset removes this scope's override.</p>
      <div class="config-row"><label>Role<select data-model-choice="role">${options(data.roles.map(v => [v,v.replaceAll('_',' ')]), CFG.role)}</select></label>
      <label>Host<select data-model-choice="host">${options([['','All hosts'], ...data.hosts.map(v => [v,v])], CFG.host)}</select></label>
      <label>Setting<select data-model-choice="field">${options([['model','Model'],['effort','Effort']], CFG.field)}</select></label></div>
      <div class="config-row"><label>Value<input data-config-key="${modelKey}" value="${esc(modelValue)}" ${disabled ? 'disabled' : ''}></label><button class="btn primary" data-save-config="${modelKey}" ${disabled ? 'disabled' : ''}>Save</button><button class="btn" data-reset-config="${modelKey}" ${disabled ? 'disabled' : ''}>Reset</button></div>
      <p class="dim config-source">Source: ${esc(item?.source || 'No override at this level; role, user, and host defaults apply.')}</p>
      <details><summary>Configured values and sources</summary>${Object.entries(data.models).map(([key, entry]) => `<p class="config-source"><strong>${esc(key)}</strong>: ${esc(entry.value)} · ${esc(entry.source)}</p>`).join('') || '<p class="dim">No model overrides.</p>'}</details></section>`;
}
/* Appearance: light unless chosen otherwise. The tray passes its choice as ?theme=. */
const THEMES = ["system", "light", "dark"];
let THEME = (() => {
  let saved = null;
  try { saved = localStorage.getItem("gsd-theme"); } catch (e) { /* storage blocked */ }
  const asked = new URLSearchParams(location.search).get("theme");
  return THEMES.includes(asked) ? asked : THEMES.includes(saved) ? saved : "light";
})();
function applyTheme() {
  if (THEME === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = THEME;
}
function setTheme(choice) {
  THEME = choice;
  try { localStorage.setItem("gsd-theme", choice); } catch (e) { /* storage blocked */ }
  applyTheme(); render();
}
applyTheme();

function setHash() {
  if (CState.view === "project" && CState.root) history.replaceState(null, "", "#" + new URLSearchParams({project: CState.root}));
  else if (CState.view === 'files' && CState.root) history.replaceState(null, '', '#' + new URLSearchParams({project:CState.root, file:FILES.path, ...(FILES.revision?{revision:FILES.revision}:{})}));
  else if (CState.view === "board") history.replaceState(null, "", location.pathname);
  else history.replaceState(null, "", "#" + CState.view);
}
function openProject(root) { CState.view = "project"; CState.root = root; setHash(); render(); window.scrollTo(0, 0); loadActivity().then(render); }
function navigate(view) {
  CState.view = view;
  setHash(); render();
  if (view === "plugin") loadPlugin().then(render);
  if (view === "config") loadConfig();
}
async function loadPlugin() {
  try {
    const r = await fetch("/api/plugin/status");
    if (!r.ok) return false;
    PLUGIN = await r.json();
    return !PLUGIN.error;
  } catch (e) { return false; }
}
async function pluginOp(path, body) {
  if (PLUGIN_OP?.busy) return null;
  const action = path.split("/").pop();
  const label = {install: "Install", update: "Update", uninstall: "Uninstall"}[action];
  const pending = {install: "Installing", update: "Updating", uninstall: "Uninstalling"}[action];
  const target = body.scope === "project" ? "project runtime: " + body.root : "global skills";
  PLUGIN_OP = {busy: true, message: pending + " " + target + "…", output: "", error: false};
  render();
  let payload = null;
  try {
    const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"},
                                 body: JSON.stringify(body)});
    payload = await r.json();
    PLUGIN_OP.output = payload.stdout_tail || "";
    if (r.status === 409) throw new Error("Another plugin operation is in progress — try again shortly.");
    if (!r.ok || payload.ok !== true) throw new Error(payload.error
      || (payload.errors || []).map(e => e.path + ": " + e.error).join("; ")
      || ("Request failed (" + r.status + ")"));
    PLUGIN_OP.message = label + " complete — " + target + "."
      + (body.scope === "global" ? " Project runtimes were not changed; use each project's Update button below." : "");
  } catch (e) {
    PLUGIN_OP.error = true;
    PLUGIN_OP.message = label + " failed — " + target + ": " + e.message;
  } finally {
    if (payload?.source_notice) PLUGIN_OP.message += " " + payload.source_notice;
    if (!await loadPlugin()) PLUGIN_OP.message += " Could not refresh installed versions. Reload to check.";
    PLUGIN_OP.busy = false;
    render();
  }
  return PLUGIN_OP.error ? null : payload;
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
  await refresh();
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
    rows.push('<div class="browse-row" data-path="' + esc(payload.parent)
      + '">📁 <span class="dim">..</span></div>');
  }
  for (const d of (payload.dirs || [])) {
    rows.push('<div class="browse-row" data-path="' + esc(d.path) + '">📁 ' + esc(d.name)
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
    row.onclick = () => openBrowseModal(row.dataset.path);
  });
  document.getElementById("plan-cancel").onclick = closeModal;
  document.getElementById("browse-select").onclick = () => {
    closeModal();
    parentOp("add", payload.path);
  };
  back.onclick = e => { if (e.target === back) closeModal(); };
}
function removeParent(path) {
  closeModal();
  const back = document.createElement("div");
  back.className = "modal-back";
  back.id = "plan-modal";
  back.innerHTML = '<div class="modal"><h3>Stop watching this folder?</h3><p>' + esc(path)
    + '</p><div style="display:flex;gap:10px;justify-content:flex-end">'
    + '<button class="btn" id="plan-cancel">Cancel</button>'
    + '<button class="btn danger" id="plan-confirm">Stop watching</button></div></div>';
  document.body.appendChild(back);
  back.querySelector("#plan-cancel").onclick = closeModal;
  back.querySelector("#plan-confirm").onclick = () => { closeModal(); parentOp("remove", path); };
  back.onclick = e => { if (e.target === back) closeModal(); };
}

async function refresh(rescan = false) {
  try {
    if (rescan) {
      const scan = await fetch("/api/refresh", {method: "POST"});
      if (!scan.ok) throw new Error("Refresh failed");
    }
    const response = await fetch("/status");
    if (!response.ok) throw new Error("Status unavailable");
    DATA = await response.json(); ONLINE = true;
    if (DATA.daemon) Object.assign(DAEMON, DATA.daemon);
  } catch (e) { ONLINE = false; }
  if (CState.view === "project") await loadActivity();
  render();
}
async function loadActivity() {
  try {
    const r = await fetch("/activity");
    if (r.ok) ACTIVITY = (await r.json()).events || [];
  } catch (e) { /* keep last good data */ }
}

/* ---- milestone stack: done / here / ahead from ROADMAP.md, STATE.md and next/STATE.md ---- */
const STATE_RANK = {blocked: 0, unverified: 1, active: 1, shipped: 2};
const stateOf = p => p.workflow?.state || "unverified";
const stateLabel = p => p.workflow?.label || "Unverified";
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
const fmt = n => n >= 1e9 ? (n/1e9).toFixed(2)+"B" : n >= 1e6 ? (n/1e6).toFixed(1)+"M" : n >= 1e3 ? Math.round(n/1e3)+"k" : String(n);
const int = n => Number(n).toLocaleString("en-US");
const money = v => v == null ? "—" : "$" + Number(v).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const DASH = '<span class="faint">—</span>';
/* Same order as canonicalPhases in the tray's Models.swift. */
const PHASES = ["inspect", "define", "research", "decide", "roadmap", "plan", "build", "ship"];
const phaseIndex = p => stateOf(p) === "shipped" ? PHASES.length : PHASES.indexOf(p.phase);
const ago = iso => {
  const t = Date.parse(iso), now = Date.parse(DATA.generated_at) || Date.now();
  if (isNaN(t)) return "—";
  const s = Math.max(0, (now - t) / 1000);
  return s < 60 ? "just now" : s < 3600 ? Math.floor(s/60) + "m ago" : s < 86400 ? Math.floor(s/3600) + "h ago" : Math.floor(s/86400) + "d ago";
};
function stackLine(p) {
  const {before, cur, after} = milestoneStack(p);
  const st = stateOf(p);
  return [...before.map(m => `${m.number} ✓`), `${cur.number} ${st === "blocked" ? "■" : st === "shipped" ? "✓" : "●"}`,
          ...after.map(m => `${m.number} ○`)].join("  ");
}
function routeMarks(p) {
  const {before, cur, after} = milestoneStack(p), st = stateOf(p);
  const mark = (m, kind) => `<i class="${kind}" title="${esc(m.number + " " + m.slug)}"></i>`;
  return `<span class="route" role="img" aria-label="${esc(stackLine(p))}">${before.map(m => mark(m, "done")).join("")}${mark(cur, st === "shipped" ? "done" : st === "blocked" ? "blocked" : "now")}${after.map(m => mark(m, "ahead")).join("")}</span>`;
}
function phaseMeter(p) {
  const i = phaseIndex(p);
  return `<span class="meter ${stateOf(p)}" role="img" aria-label="${esc(p.phase || "no phase")}">${PHASES.map((ph, k) => `<i class="${k < i ? "done" : k === i ? "now" : ""}" title="${ph}"></i>`).join("")}</span>`;
}
function boardRow(p) {
  const st=stateOf(p), {cur}=milestoneStack(p), sp=p.spend||{};
  const tail=String(p.root||'').split('/').slice(-2).join('/');
  const reasons=(p.attention||[]).map(a=>a.label).filter(Boolean).join(' · ');
  return `<tr class="prow ${st}" data-root="${esc(p.root)}"><td><button class="pname" data-root="${esc(p.root)}" aria-label="Open ${esc(p.project||p.root)}"><span class="dot ${healthDot(p)}" title="health ${esc(healthReason(p))}"></span><span>${esc(p.project||p.root)}</span></button><div class="ppath">${esc(tail)}</div></td>
    <td><div class="milestone-name"><span class="mono dim">${esc(cur.number)}</span> ${esc(cur.slug)}</div><div class="milestone-phase">${phaseMeter(p)}<span class="phlabel">${esc(p.phase||'No phase recorded')}</span></div></td>
    <td><span class="state ${st}">${esc(stateLabel(p))}</span>${reasons?`<p class="health-note">${esc(reasons)}</p>`:''}<div class="ago">${ago(p.last_activity_iso)}</div></td><td class="n">${p.tasks_total?`${p.tasks_done||0}/${p.tasks_total}`:DASH}</td><td class="n">${sp.turns&&sp.cost!=null?money(sp.cost):DASH}<div class="ago">${sp.turns?int(sp.turns)+' turns':'No matched sessions'}</div></td></tr>`;
}
const TASK_GLYPH = {done: "✓", failed: "✗"};
function waveRows(p) {
  const waves = Object.entries(p.waves || {}).map(([n, name]) => [Number(n), name]).sort((a, b) => a[0] - b[0]);
  const allDone = stateOf(p) === "shipped" || (p.tasks_total > 0 && p.tasks_done >= p.tasks_total);
  return waves.map(([n, name]) => {
    const kind = p.current_wave != null ? (n < p.current_wave ? "done" : n === p.current_wave ? "now" : "ahead") : allDone ? "done" : "ahead";
    return `<span class="w-${kind}">${kind === "done" ? "✓" : kind === "now" ? "●" : "○"} wave ${n} ${esc(name)}</span>`;
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
  return `<div class="sub">verify <span style="color:${ok ? "var(--accent)" : last.result === "fail" ? "var(--danger)" : "var(--dim)"}">${esc(last.result || "unknown")}${last.recorded_at ? " " + esc(shortT(last.recorded_at)) : ""}</span></div>`;
}
function phaseTrack(p) {
  const i = phaseIndex(p), log = p.phase_log || [];
  const dateOf = ph => ((ph === p.phase ? log.filter(e => e.phase === ph).slice(-1)[0] : log.find(e => e.phase === ph)) || {}).date;
  return `<div class="phases ${stateOf(p)}">${PHASES.map((ph, k) => `<div class="${k < i ? "done" : k === i ? "now" : ""}" title="${ph}${dateOf(ph) ? " · " + esc(dateOf(ph)) : ""}"><i></i>${ph}<small>${esc(String(dateOf(ph) || "").slice(5)) || "&nbsp;"}</small></div>`).join("")}</div>`;
}
const spendText = slot => slot && slot.turns ? [slot.cost != null ? money(slot.cost) : null, `${int(slot.turns)} turns`].filter(Boolean).join(" · ") : "";
const manifestMeta = m => {
  const mf = m.manifest || {};
  return [mf.tasks_total != null ? `${mf.tasks_done} of ${mf.tasks_total} tasks` : null,
          mf.waves != null ? `${mf.waves} waves` : null,
          mf.cycles_avg != null ? `${mf.cycles_avg} review cycles avg` : null,
          m.integrated ? "integrated " + String(m.integrated).slice(0, 7) : null,
          mf.carried ? `${mf.carried} rulings carried` : null, mf.verdict || null].filter(Boolean).join(" · ");
};
function milestoneTable(p) {
  const {before, cur, after} = milestoneStack(p), st = stateOf(p);
  const slots = (p.spend || {}).milestones || {};
  const depends = m => (m.depends || []).length ? `after ${esc(m.depends.join(", "))}` : "";
  const row = (m, kind, status) => {
    const meta = [kind === "done" ? manifestMeta(m) : "", depends(m)].filter(Boolean).join(" · ");
    const tasks = m.manifest && m.manifest.tasks_total != null ? m.manifest.tasks_total : kind === "now" && p.tasks_total ? p.tasks_total : null;
    return `<tr class="ms ${kind}${kind === "now" ? " " + st : ""}"><td class="mono k">${esc(m.number)}</td><td><div>${esc(m.slug)}</div>${m.goal ? `<div class="goal">${esc(m.goal)}</div>` : ""}${meta ? `<div class="meta">${meta}</div>` : ""}</td>
      <td class="st">${esc(status)}</td><td class="n">${tasks != null ? tasks : DASH}</td><td class="n">${spendText(slots[m.number]) ? spendText(slots[m.number]) + `<div class="meta">${fmt(slots[m.number].tokens)} tokens</div>` : DASH}</td></tr>`;
  };
  const shippedOn = m => m.manifest && m.manifest.shipped ? "shipped " + m.manifest.shipped : m.status || "shipped";
  const rows = [...before.map(m => row(m, "done", shippedOn(m))),
                row(cur, st === "shipped" ? "done" : "now", st === "shipped" ? shippedOn(cur) : stateLabel(p)),
                ...after.map(m => row(m, "ahead", [m.phase, m.status || "planned"].filter(Boolean).join(" · ")))].join("");
  const end = after.length ? "" : `<tr class="end"><td class="mono">—</td><td colspan="4">end of roadmap</td></tr>`;
  return `<div class="tablewrap"><table class="t milestones"><tr><th>#</th><th>Milestone</th><th>Status</th><th class="n">Tasks</th><th class="n">Usage</th></tr>${rows}${end}</table></div>`;
}
function nowBox(p) {
  const st = stateOf(p);
  if (st === "shipped") return "";
  const {cur} = milestoneStack(p);
  const entered = (p.phase_log || []).filter(e => e.phase === p.phase).slice(-1)[0];
  const when = [entered ? "entered " + esc(entered.phase) + " " + esc(entered.date) : null, dur(p.time_in_phase_s)].filter(Boolean).join(" · ");
  const progress = p.tasks_total
    ? `<div class="bar"><i style="width:${Math.round(100 * (p.tasks_done || 0) / p.tasks_total)}%"></i></div><div class="sub">${p.tasks_done || 0} of ${p.tasks_total} tasks${when ? " · " + when : ""}</div>`
    : `<div class="sub">${when ? when + " · " : ""}no tasks yet</div>`;
  const waves = waveRows(p);
  return `<div class="now-box ${st}"><div><b>${esc(cur.number)} ${esc(cur.slug)}</b> · ${esc([p.phase || "no phase", p.current_wave != null ? "wave " + p.current_wave : null].filter(Boolean).join(" · "))}</div>
    ${cur.goal ? `<div class="goal">${esc(cur.goal)}</div>` : ""}${p.intent ? `<div class="intent">${esc(p.intent)}</div>` : ""}
    ${progress}${waves ? `<div class="waves">${waves}</div>` : ""}${criteriaStrip(p)}${verifyLine(p)}</div>`;
}
function taskTable(p) {
  const tasks = p.tasks || [];
  if (!tasks.length) return "";
  const waves = p.waves || {};
  return `<h2>Tasks <span>${p.tasks_done || 0} of ${p.tasks_total || tasks.length}</span></h2><div class="tablewrap"><table class="t tasks-t"><tr><th>ID</th><th>Task</th><th>Wave</th><th>Status</th><th>Files</th></tr>${tasks.map(t =>
    `<tr><td class="mono">${esc(t.id)}</td><td>${esc(t.title || "")}</td><td>${esc(t.wave != null ? t.wave + (waves[t.wave] ? " " + waves[t.wave] : "") : "—")}</td><td class="st">${TASK_GLYPH[t.status] || "○"} ${esc(t.status || "pending")}</td><td class="mono">${(t.files || []).map(esc).join("<br>") || DASH}</td></tr>`).join("")}</table></div>`;
}
const verdict = v => v ? `<span class="verdict-${esc(v)}">${esc(v)}</span>` : DASH;
function criteriaTable(p) {
  const crits = p.criteria || [];
  if (!crits.length) return "";
  return `<h2>Success criteria <span>${crits.filter(c => c.verdict === "met").length} of ${crits.length} met</span></h2><div class="tablewrap"><table class="t criteria"><tr><th>ID</th><th>Criterion</th><th>Verdict</th></tr>${crits.map(c =>
    `<tr><td class="mono">${esc(c.id || "—")}</td><td>${esc(c.text || "")}</td><td class="st">${verdict(c.verdict)}</td></tr>`).join("")}</table></div>`;
}
function reviewTable(p) {
  const reviews = p.reviews || [];
  if (!reviews.length) return "";
  return `<h2>Reviews <span>${reviews.length}</span></h2><div class="tablewrap"><table class="t reviews"><tr><th>Review</th><th class="n">Cycle</th><th>Depth</th><th>Verdict</th><th>Note</th></tr>${reviews.map(r =>
    `<tr title="${esc(r.file)}"><td>${esc(r.kind)}</td><td class="n">${r.cycle != null ? r.cycle : DASH}</td><td>${esc(r.depth || "—")}</td><td class="st">${verdict(r.verdict)}</td><td>${esc(r.note || "")}</td></tr>`).join("")}</table></div>`;
}
function ledgerTable(p) {
  const ledger = p.ledger || [];
  if (!ledger.length) return "";
  return `<h2>Verify ledger <span>latest ${ledger.length}</span></h2><div class="tablewrap"><table class="t ledger"><tr><th>Recorded</th><th>Command</th><th>Commit</th><th>Result</th></tr>${ledger.map(e =>
    `<tr><td class="mono">${esc(String(e.recorded_at || "").slice(0, 16).replace("T", " "))}</td><td class="mono">${esc(e.command || "")}</td><td class="mono">${esc(String(e.commit || "").slice(0, 7))}</td><td class="st">${verdict(e.result)}</td></tr>`).join("")}</table></div>`;
}
function activityTable(p) {
  const events = ACTIVITY.filter(e => e.root === p.root).slice(0, 30);
  return `<h2>Activity <span>recorded changes</span></h2>${events.length
    ? `<div class="tablewrap"><table class="t activity"><tr><th>When</th><th>Change</th><th>Detail</th></tr>${events.map(e =>
      `<tr><td class="mono">${esc(String(e.at || "").slice(0, 16).replace("T", " "))}</td><td>${esc(e.type)}</td><td>${esc(e.detail || "")}</td></tr>`).join("")}</table></div>`
    : `<p class="note">No recorded changes yet.</p>`}`;
}
function usageColumn(p) {
  const sp = p.spend;
  if (!sp || !sp.turns) return `<h2>Usage</h2><p class="note">No host session logs matched this project yet.</p>`;
  const models = sp.models.map(m => `<tr><td class="mono">${esc(m.model)}</td><td>${esc(m.host || "")}</td><td class="n">${int(m.turns)}</td><td class="n">${fmt(m.tokens)}</td><td class="n">${money(m.cost)}</td></tr>`).join("");
  const agents = sp.agents.map(a => `<tr><td>${esc(a.agent)}<div class="meta mono">${esc(a.models.join(", "))}</div></td><td class="n">${int(a.turns)}</td><td class="n">${fmt(a.tokens)}</td><td class="n">${a.duration_s ? dur(a.duration_s) : DASH}</td><td class="n">${money(a.cost)}</td></tr>`).join("");
  const inputs = (sp.tokens_in || 0) + (sp.tokens_cached || 0);
  const stats = [["Cost", money(sp.cost)], ["Turns", int(sp.turns)], ["Prompts", int(sp.prompts || 0)],
                 ["Tokens in", fmt(sp.tokens_in || 0)], ["Cached", fmt(sp.tokens_cached || 0)], ["Tokens out", fmt(sp.tokens_out || 0)],
                 ["Cache hit", inputs ? Math.round(100 * (sp.tokens_cached || 0) / inputs) + "%" : "—"],
                 ["Agent time", sp.timed_turns ? dur(sp.duration_s) : "—"],
                 ["Cost / turn", sp.cost != null && sp.priced_turns ? money(sp.cost / sp.priced_turns) : "—"],
                 ["Time / turn", sp.timed_turns ? Math.round(sp.duration_s / sp.timed_turns) + "s" : "—"]];
  const turns = sp.recent.map(t => `<tr><td class="mono">${esc(shortT(t.at))}</td><td>${esc(t.agent)}</td><td class="mono">${esc(t.model || "?")}</td><td class="n">${fmt(t.tokens_in)}</td><td class="n">${fmt(t.tokens_cached)}</td><td class="n">${fmt(t.tokens_out)}</td><td class="n">${money(t.cost)}</td><td class="n">${t.duration_s != null ? t.duration_s + "s" : "—"}</td></tr>`).join("");
  const note = sp.unpriced.length ? `<div class="note">No price configured for ${esc(sp.unpriced.join(", "))}: tokens counted, cost excluded. Add prices per million tokens under "prices" in daemon.json.</div>` : "";
  return `<h2>Usage</h2><dl class="stats">${stats.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>
    <h2>Models</h2>
    <div class="tablewrap"><table class="t models"><tr><th>Model</th><th>Host</th><th class="n">Turns</th><th class="n">Tokens</th><th class="n">Cost</th></tr>${models}</table></div>
    <h2>Agents</h2><div class="tablewrap"><table class="t agents"><tr><th>Agent · models</th><th class="n">Turns</th><th class="n">Tokens</th><th class="n">Time</th><th class="n">Cost</th></tr>${agents}</table></div>
    <details class="turns"><summary>Turn ledger · latest ${sp.recent.length} of ${int(sp.turns)}</summary><div class="tablewrap"><table class="t"><tr><th>Time</th><th>Agent</th><th>Model</th><th class="n">In</th><th class="n">Cached</th><th class="n">Out</th><th class="n">Cost</th><th class="n">Dur</th></tr>${turns}</table></div></details>
    ${note}<div class="note">From host session logs matched to this project by working directory.</div>`;
}
function projectPage(p) {
  const {cur} = milestoneStack(p), sp = p.spend, git = p.git || {};
  const head = git.head ? String(git.head).slice(0, 7) + (git.dirty ? " · dirty" : "") : "—";
  const facts = [["State", stateLabel(p)], ["Health", healthReason(p)], ["Milestone", cur.number], ["Branch", git.branch || p.branch || "—"], ["Head", head],
                 ...(p.integration ? [["Integration", p.integration]] : []),
                 ["Updated", ago(p.last_activity_iso)], ["Cost", sp && sp.turns ? money(sp.cost) : "—"], ["Turns", sp && sp.turns ? int(sp.turns) : "—"]];
  return `<article class="project" data-root="${esc(p.root)}">
    <div class="project-tools">${sourceLink('.project/STATE.md','History & files')}</div><div class="phead"><h1><span class="dot ${healthDot(p)}" title="health ${esc(healthReason(p))}"></span> ${esc(p.project || p.root)}</h1><span class="mono">${esc(p.root)}</span></div>
    <dl class="facts">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>
    ${p.handoff ? `<p class="runtime-handoff">${esc(p.handoff.outcome)} — ${esc(p.handoff.next)}</p>` : ""}
    ${p.vision ? `<p class="vision">${esc(p.vision)}</p>` : ""}
    <div class="cols"><section>
      <h2>Phase <span>${esc(p.phase || "no phase")}</span></h2>${phaseTrack(p)}${nowBox(p)}
      ${foldProject('criteria','Success criteria',criteriaTable(p))}
      <h2>Milestones</h2>${milestoneTable(p)}
      ${foldProject('tasks','Tasks and files',taskTable(p))}${foldProject('reviews','Reviews',reviewTable(p))}${foldProject('verification','Recent verification',ledgerTable(p))}
    </section><section>
      ${usageColumn(p)}
      ${activityTable(p)}
      ${p.lesson ? `<h2>Latest lesson</h2><p class="lesson">${esc(p.lesson)}</p>` : ""}
    </section></div></article>`;
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
    <span>Global skills: <b>${esc(versions.join(", ") || "not installed")}</b></span>
    <span class="dim">Latest: <b>${esc(latest || "unknown")}</b></span>
    ${PLUGIN.update_available ? '<span class="pill outdated">Update available</span>'
      + "<button class='btn primary' onclick='pluginOp(&quot;/api/plugin/update&quot;, {scope:&quot;global&quot;})'>Update global skills</button>" : ""}
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
    const root = esc(JSON.stringify(pr.root));
    const version = pr.runtime_version && pr.runtime_version !== "unknown" ? pr.runtime_version : null;
    const versionLabel = !pr.runtime ? "Not installed" : version || "Unknown — version metadata unavailable";
    const update = version && latest && version !== latest ? `<div class="dim">Latest: ${esc(latest)}</div>` : "";
    return `<tr><td class="faint" style="word-break:break-all">${esc(pr.root)}</td><td>${esc(versionLabel)}${update}</td><td>${pills}</td>
      <td style="white-space:nowrap">
        <button class="btn" onclick='pluginOp("/api/plugin/install", {scope:"project", root:${root}})'>Install</button>
        <button class="btn" onclick='pluginOp("/api/plugin/update", {scope:"project", root:${root}})'>Update</button>
        <button class="btn danger" onclick='uninstallPlan({scope:"project", root:${root}})'>Uninstall</button>
      </td></tr>`;
  }).join("");
  const projectsBox = `<div class="box" style="margin-top:12px"><h4>Watched projects</h4>`
    + (projects ? `<table class="tasks"><tr><th>Project root</th><th>Runtime version</th><th>Installed</th><th></th></tr>${projects}</table>`
                : '<p class="dim">No watched projects.</p>') + `</div>`;
  const feedback = PLUGIN_OP ? `<div id="plugin-feedback" class="box" role="${PLUGIN_OP.error ? "alert" : "status"}" aria-live="polite">
    <strong>${esc(PLUGIN_OP.message)}</strong>
    ${PLUGIN_OP.output ? `<details><summary>Installer output</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(PLUGIN_OP.output)}</pre></details>` : ""}
  </div>` : "";
  return feedback + `<p class="dim">Global skills and project runtimes are installed separately. Update each project to refresh its local runtime and existing guards.</p>`
    + `<fieldset class="plugin-controls" style="border:0;padding:0;margin:0;min-width:0" ${PLUGIN_OP?.busy ? "disabled" : ""}>`
    + banner + hostsTable + projectsBox + `</fieldset>`;
}
const ICON = {
  mark: '<svg viewBox="0 0 18 18" fill="none" aria-hidden="true"><path d="M1.6 4 5.6 9 1.6 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M7 4 11 9 7 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M12.4 4 16.4 9 12.4 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  settings: '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M2 4h3m4 0h5M2 12h7m4 0h1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="7" cy="4" r="2" stroke="currentColor" stroke-width="1.5"/><circle cx="11" cy="12" r="2" stroke="currentColor" stroke-width="1.5"/></svg>',
  search: '<svg viewBox="0 0 16 16" fill="none" aria-hidden="true"><circle cx="7" cy="7" r="4.5" stroke="currentColor" stroke-width="1.5"/><path d="m10.5 10.5 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
};
__RECORDS_JS__
__LAYOUT_JS__
function render() {
  const stage = document.getElementById("stage");
  const previousKey = stage.dataset.readingKey;
  const settingsOpen = !!stage.querySelector('.settings-menu[open]');
  const expanded = [...stage.querySelectorAll('details[open][data-section]')].map(e=>e.dataset.section);
  const sidebarScroll = stage.querySelector('.file-list')?.scrollTop || 0;
  const pageScroll = [window.scrollX, window.scrollY];
  const focusIndex = [...stage.querySelectorAll('button, summary, select, input, [tabindex]')].indexOf(document.activeElement);
  const caret = document.activeElement && document.activeElement.matches("[data-search], [data-file-search]") ? document.activeElement.selectionStart : null;
  const projects = (DATA.projects || []).slice().sort((a, b) =>
    STATE_RANK[stateOf(a)] - STATE_RANK[stateOf(b)] || String(a.project || a.root).localeCompare(String(b.project || b.root)));
  const shipped = projects.filter(p => stateOf(p) === "shipped").length;
  const connection = ONLINE === null ? "Connecting…" : ONLINE ? (DATA.generated_at ? "Updated " + esc(shortT(DATA.generated_at)) : "Connected") : "Offline · showing last update";
  const settings = `<details class="settings-menu"><summary aria-label="Settings" title="Settings">${ICON.settings}</summary><nav aria-label="Settings"><button class="btn" data-nav="config">Path settings</button><button class="btn" data-nav="plugin">Plugin</button><button class="btn" data-nav="folders">Watched folders</button><div class="appearance" role="group" aria-label="Appearance">Appearance<div class="segc">${THEMES.map(t => `<button data-theme-choice="${t}" aria-pressed="${THEME === t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div></div></nav></details>`;
  const status = `<button class="btn" data-action="refresh" aria-label="Refresh dashboard">Refresh</button><span class="connection" role="status"><span class="dot ${ONLINE === null ? "" : ONLINE ? "g" : "r"}"></span>${connection}</span>`;
  const current = ["project","files"].includes(CState.view) ? projects.find(p => p.root === CState.root) : null;
  let header, body;
  if (current) {
    header = `<header class="topbar"><button class="back" data-nav="board" aria-label="Back to projects">‹ Projects</button><select class="switcher" data-switch aria-label="Project">${projects.map(q => `<option value="${esc(q.root)}"${q.root === current.root ? " selected" : ""}>${esc(q.project || q.root)}</option>`).join("")}</select><span class="spacer"></span>${status}${settings}</header>`;
    body = `<main class="page">${CState.view==='files'?filesPage(current):projectPage(current)+projectRecords(current)}</main>`;
  } else {
    header = `<header class="topbar"><button class="brand" data-nav="board" aria-label="OpenGSD Path projects">${ICON.mark}OpenGSD Path</button><nav class="topnav" aria-label="Main"><button data-nav="board" aria-current="${CState.view==='board'?'page':'false'}">Projects</button><button data-nav="config" aria-current="${['config','folders','plugin'].includes(CState.view)?'page':'false'}">Settings</button></nav><span class="spacer"></span>${status}${settings}</header>`;
    if (CState.view === "plugin") body = settingsFrame('Plugin',tabPlugin());
    else if (CState.view === 'config') body = settingsFrame('Path settings',pathConfigPage(),true);
    else if (CState.view === "folders") body = settingsFrame('Watched folders', `<p class="dim">Projects inside these folders appear automatically.</p>${(DAEMON.parents || []).map((path, i) => `<div class="folder-row"><span>${esc(path)}</span><button class="btn danger" data-remove-parent="${i}">Stop watching</button></div>`).join("")}<p style="margin-top:16px"><button class="btn" data-action="add-folder">Add folder…</button></p>`);
    else {
      if (CState.view === "project" && ONLINE !== null) { CState.view = "board"; CState.root = null; setHash(); }
      body = boardPage(projects);
    }
  }
  const readingKey = JSON.stringify([CState.view, CState.root]);
  stage.innerHTML = header + body;
  stage.dataset.readingKey = readingKey;
  if (previousKey === readingKey) {
    stage.querySelector('.settings-menu').open = settingsOpen;
    stage.querySelectorAll('details[data-section]').forEach(e=>{e.open=expanded.includes(e.dataset.section);});
    if(stage.querySelector('.file-list'))stage.querySelector('.file-list').scrollTop=sidebarScroll;
    window.scrollTo(...pageScroll);
    const target = focusIndex >= 0 ? stage.querySelectorAll('button, summary, select, input, [tabindex]')[focusIndex] : null;
    if (target) {
      target.focus({preventScroll: true});
      if (caret != null && target.matches("[data-search], [data-file-search]")) target.setSelectionRange(caret, caret);
    }
  }
}
document.getElementById("stage").addEventListener("click", event => {
  const b = event.target.closest("button, tr[data-root]");
  if (!b) return;
  if (b.dataset.nav) { CState.root = null; navigate(b.dataset.nav); }
  else if (b.dataset.filter) { CState.filter = b.dataset.filter; render(); }
  else if (b.dataset.themeChoice) setTheme(b.dataset.themeChoice);
  else if (b.dataset.root) openProject(b.dataset.root);
  else if (b.dataset.action === "refresh") refresh(true);
  else if (b.dataset.action === "add-folder") addParent();
  else if (b.dataset.saveConfig) saveConfig(b.dataset.saveConfig);
  else if (b.dataset.resetConfig) saveConfig(b.dataset.resetConfig, true);
  else if (b.dataset.removeParent != null) removeParent(DAEMON.parents[Number(b.dataset.removeParent)]);
});
document.getElementById("stage").addEventListener("input", event => {
  if (event.target.matches("[data-search]")) { CState.q = event.target.value; render(); }
  if (event.target.dataset.configKey) CFG.drafts[event.target.dataset.configKey] = event.target.value;
});
document.getElementById("stage").addEventListener("change", event => {
  if (event.target.matches("[data-switch]")) openProject(event.target.value);
  if (event.target.matches('[data-config-scope]')) { CFG.root = event.target.value; loadConfig(); }
  if (event.target.dataset.modelChoice) { CFG[event.target.dataset.modelChoice] = event.target.value; render(); }
});
function applyHash() {
  const h = location.hash.slice(1);
  if (h === "plugin" || h === "folders" || h === "config") {
    CState.view = h;
    if (h === "plugin") loadPlugin().then(render);
    if (h === 'config') loadConfig();
  } else {
    const params=new URLSearchParams(h);
    CState.root = params.get("project") || null;
    if(CState.root && params.has('file')) { openFiles(CState.root,params.get('file'),params.get('revision')||'',false); return; }
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
        if path == '/api/path-config':
            self._path_config(False)
            return
        if path in ("/api/project-files", "/api/project-data"):
            self._project_files()
            return
        if path == "/health":
            self._respond(200, "application/json", json.dumps({"ok": True}))
            return
        if path == "/api/fs/browse":
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code, payload = _browse_dirs((query.get("path") or [None])[0])
            self._respond(code, "application/json", json.dumps(payload, indent=2, sort_keys=True))
        elif path.startswith("/status"):
            payload = aggregate(list(self.watcher.projects.values()), utc_now_iso())
            payload["daemon"] = {"parents": list(self.watcher.config.parents), "poll_seconds": self.watcher.config.poll_seconds}
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
        if path == '/api/path-config':
            self._path_config(True)
            return
        if path == "/api/refresh":
            try:
                self.scan(scan_sessions=False)
            except Exception as error:
                self._respond(500, "application/json", json.dumps({"error": str(error)}))
                return
            self._respond(200, "application/json", json.dumps({"ok": True}))
            return
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

    def _project_files(self):
        port = self.server.server_address[1]
        host = self.headers.get('Host')
        if host not in (f'127.0.0.1:{port}', f'localhost:{port}') or self.headers.get('Origin') not in (None, f'http://{host}') or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._respond(403, 'application/json', json.dumps({'error': 'Same-origin project file requests only.'}))
            return
        try:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query, keep_blank_values=True)
            if any(len(values) != 1 for values in query.values()):
                raise FileAccessError('File query fields cannot repeat.')
            request = {key: values[0] for key, values in query.items()}
            if self.path.split('?', 1)[0] == '/api/project-data':
                if set(request) != {'root'}:
                    raise FileAccessError('Project data requires only a root field.')
                payload = project_records(self.watcher, request['root'])
            else:
                payload = request_files(self.watcher.projects, request)
            code = 200
        except FileAccessError as error:
            code, payload = error.code, {'error': str(error), 'status': error.status}
        except (OSError, ValueError) as error:
            code, payload = 400, {'error': str(error), 'status': 'failed'}
        self._respond(code, 'application/json', json.dumps(payload))

    def _path_config(self, write):
        port = self.server.server_address[1]
        host = self.headers.get('Host')
        if host not in (f'127.0.0.1:{port}', f'localhost:{port}') or (
            self.headers.get('Origin') not in (None, f'http://{host}')
        ):
            self._respond(403, 'application/json', json.dumps({'error': 'Same-origin settings requests only.'}))
            return
        try:
            if write:
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('settings writes require application/json')
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0:
                    raise ValueError('settings writes require a JSON body')
                request = json.loads(self.rfile.read(length))
            else:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if any(len(values) != 1 for values in query.values()):
                    raise ValueError('settings query fields cannot repeat')
                request = {key: values[0] for key, values in query.items()}
            payload = configure(self.plugin, self.watcher.projects, request, write)
            code = 200
        except (ValueError, OSError) as error:
            code, payload = 400, {'error': str(error)}
        self._respond(code, 'application/json', json.dumps(payload))

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
            self.scan(scan_sessions=False)
        except Exception as error:
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
        return DASHBOARD_PAGE.replace("__DAEMON_JSON__", json.dumps(daemon)).replace("__RECORDS_CSS__", RECORDS_CSS).replace("__RECORDS_JS__", RECORDS_JS).replace("__LAYOUT_CSS__", LAYOUT_CSS).replace("__LAYOUT_JS__", LAYOUT_JS)


def serve(watcher: Watcher, port: int = DEFAULT_PORT,
          plugin: Optional[PluginManager] = None) -> ThreadingHTTPServer:
    # Bind before the first session scan: scanning every host session log on
    # the machine can take a while cold, and the dashboard must not wait on it.
    watcher.poll_once(scan_sessions=False)
    scan_lock = threading.Lock()

    def scan(scan_sessions=True):
        with scan_lock:
            events = watcher.poll_once(scan_sessions=scan_sessions)
            if watcher.config.history:
                for event in events:
                    append_event(event)

    handler = type("Handler", (_Handler,),
                   {"watcher": watcher, "plugin": plugin or PluginManager(), "scan": staticmethod(scan)})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    stop = threading.Event()
    server.watcher_stop = stop  # callers may set() to end the poll loop

    def poll_loop() -> None:
        # The startup poll above is not recorded, so a restart does not log every project as added.
        while not stop.is_set():
            try:
                scan()
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
