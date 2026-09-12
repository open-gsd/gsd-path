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

DASHBOARD_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>gsd-path daemon</title>
<style>
  /* Studio tokens from gsd-cloud/web/app/globals.css. Keep both palettes in sync. */
  :root {
    --accent: #4f5fe0;
    --accent-fill: #4f5fe0;
    --accent-fg: #ffffff;
    --accent-soft: #edefff;
    --focus-ring: #14161a;
    --bg: #f7f8fa;
    --card: #ffffff;
    --sunken: #f2f4f7;
    --rail: #ffffff;
    --line: #e3e7ed;
    --text: #14161a;
    --dim: #5b6270;
    --faint: #66707e;
    --run: #0d7d53;
    --run-soft: #e6f7f0;
    --wait: #7c5205;
    --wait-soft: #fdf3e0;
    --danger: #b23a2c;
    --danger-soft: #fdecea;
    --shadow: 0 1px 2px rgb(16 24 40 / .06), 0 0 0 1px rgb(16 24 40 / .05);
    --shadow-lift: 0 12px 28px -8px rgb(16 24 40 / .14), 0 0 0 1px rgb(16 24 40 / .06);
    --panel: var(--card); --panel2: var(--sunken);
    --green: var(--run); --yellow: var(--wait); --red: var(--danger); --blue: var(--accent); --purple: var(--accent);
    --ui: Inter, -apple-system, "Segoe UI", sans-serif;
    --mono: "JetBrains Mono", ui-monospace, Menlo, monospace;
  }
  @media(prefers-color-scheme:dark) { :root:not([data-theme="light"]) {
    --accent: #7c8cff;
    --accent-fill: #5a68e8;
    --accent-fg: #ffffff;
    --accent-soft: #1b1f3a;
    --focus-ring: #f6f7f9;
    --bg: #0c0d10;
    --card: #131519;
    --sunken: #1a1d23;
    --rail: #0e1013;
    --line: #24272f;
    --text: #eceef2;
    --dim: #9ba1ad;
    --faint: #8b93a1;
    --run: #3ddc97;
    --run-soft: #0f2b22;
    --wait: #f5b544;
    --wait-soft: #2e2312;
    --danger: #ff6b5e;
    --danger-soft: #331715;
    --shadow: 0 1px 2px rgb(0 0 0 / .3), 0 0 0 1px rgb(255 255 255 / .04);
    --shadow-lift: 0 12px 30px -8px rgb(0 0 0 / .55), 0 0 0 1px rgb(255 255 255 / .06);
  }}
  :root[data-theme="dark"] {
    --accent: #7c8cff;
    --accent-fill: #5a68e8;
    --accent-fg: #ffffff;
    --accent-soft: #1b1f3a;
    --focus-ring: #f6f7f9;
    --bg: #0c0d10;
    --card: #131519;
    --sunken: #1a1d23;
    --rail: #0e1013;
    --line: #24272f;
    --text: #eceef2;
    --dim: #9ba1ad;
    --faint: #8b93a1;
    --run: #3ddc97;
    --run-soft: #0f2b22;
    --wait: #f5b544;
    --wait-soft: #2e2312;
    --danger: #ff6b5e;
    --danger-soft: #331715;
    --shadow: 0 1px 2px rgb(0 0 0 / .3), 0 0 0 1px rgb(255 255 255 / .04);
    --shadow-lift: 0 12px 30px -8px rgb(0 0 0 / .55), 0 0 0 1px rgb(255 255 255 / .06);
  }
  * { box-sizing: border-box; margin: 0; }
  body { background: var(--bg); color: var(--text); font: 13px/1.45 -apple-system, "SF Pro Text", "Segoe UI", sans-serif; min-height: 100vh; }
  .stage { padding: 24px 24px 60px; }
  .pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
  .pill.active  { background: var(--run-soft); color: var(--green); }
  .pill.blocked { background: var(--danger-soft); color: var(--red); }
  .pill.done    { background: var(--accent-soft); color: var(--blue); }
  .pill.prog    { background: var(--wait-soft); color: var(--yellow); }
  .pill.pend    { background: var(--panel2); color: var(--dim); }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex: none; }
  .dot.g { background: var(--green); } .dot.y { background: var(--yellow); } .dot.r { background: var(--red); }
  .bar { height: 5px; border-radius: 3px; background: var(--line); overflow: hidden; }
  .bar > i { display: block; height: 100%; background: var(--green); border-radius: 3px; }
  .dim { color: var(--dim); } .faint { color: var(--faint); }
  kbd { background: var(--panel2); border: 1px solid var(--line); border-radius: 4px; padding: 0 5px; font-size: 11px; }
  kbd.copy { cursor: pointer; }
  kbd.copy:hover { border-color: var(--blue); color: var(--blue); }

  .dash { max-width: 1180px; margin: 0 auto; display: grid; grid-template-columns: 240px 1fr; gap: 0;
          border: 1px solid var(--line); border-radius: 12px; overflow: hidden; min-height: 640px; background: var(--panel); }
  .side { border-right: 1px solid var(--line); padding: 14px 10px; background: var(--panel); }
  .side h3 { font-size: 11px; text-transform: uppercase; letter-spacing: .8px; color: var(--faint); padding: 6px 10px; }
  .sitem { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 7px; cursor: pointer; }
  .sitem:hover { background: var(--panel2); }
  .sitem.sel { background: var(--panel2); }
  .sitem.static { cursor: default; }
  .sitem.static:hover { background: none; }
  .sitem .nm { font-weight: 600; }
  .sitem .sub { font-size: 11px; color: var(--faint); word-break: break-all; }
  .main { padding: 18px 22px; }
  .main h2 { font-size: 19px; margin-bottom: 2px; }
  .statrow { display: flex; gap: 12px; margin: 14px 0 18px; }
  .stat { flex: 1; background: var(--panel2); border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; }
  .stat .v { font-size: 20px; font-weight: 700; }
  .stat .k { font-size: 11px; color: var(--faint); }
  table.tasks { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  table.tasks th { text-align: left; color: var(--faint); font-size: 11px; text-transform: uppercase; letter-spacing: .5px;
                   padding: 6px 10px; border-bottom: 1px solid var(--line); }
  table.tasks td { padding: 7px 10px; border-bottom: 1px solid var(--line); }

  .steps { display: flex; align-items: center; gap: 3px; margin: 9px 0 7px; }
  .step { flex: 1; height: 4px; border-radius: 2px; background: var(--line); position: relative; }
  .step.done { background: var(--green); }
  .step.now { background: var(--blue); box-shadow: 0 0 6px var(--blue); }
  .steplabel { font-size: 10px; color: var(--faint); display: flex; justify-content: space-between; margin-bottom: 8px; }
  .prow { display: flex; justify-content: space-between; font-size: 12px; color: var(--dim); margin-top: 3px; }

  .tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); margin: 14px 0 16px; }
  .tab { padding: 7px 14px; font-size: 12.5px; color: var(--dim); cursor: pointer; border-bottom: 2px solid transparent; }
  .tab:hover { color: var(--text); }
  .tab.sel { color: var(--text); border-bottom-color: var(--blue); font-weight: 600; }
  .tab .n { background: var(--panel2); border-radius: 8px; padding: 0 6px; font-size: 10.5px; margin-left: 4px; }
  .tab.sel .n { background: var(--blue); color: var(--panel); }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .box { background: var(--panel2); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
  .box h4 { font-size: 11px; text-transform: uppercase; letter-spacing: .6px; color: var(--faint); margin-bottom: 8px; }
  .crit { display: flex; gap: 8px; padding: 5px 0; border-top: 1px solid var(--line); font-size: 12.5px; }
  .crit:first-of-type { border-top: none; }
  .vmet { color: var(--green); font-weight: 700; width: 86px; flex: none; }
  .vnot { color: var(--red); font-weight: 700; width: 86px; flex: none; }
  .vunv { color: var(--yellow); font-weight: 700; width: 86px; flex: none; }
  .ledger { font: 11.5px/1.7 ui-monospace, monospace; color: var(--dim); }
  .ledger .pass { color: var(--green); } .ledger .fail { color: var(--red); }
  .rms { display: flex; align-items: center; gap: 10px; padding: 9px 0; border-top: 1px solid var(--line); font-size: 13px; }
  .rms:first-of-type { border-top: none; }
  .rms .mnum { font-weight: 700; width: 48px; }
  .rms .arch { margin-left: auto; font: 10.5px ui-monospace, monospace; color: var(--faint); }
  .feed { border: 1px solid var(--line); border-radius: 12px; background: var(--panel2); padding: 14px 18px; }
  .feed h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .7px; color: var(--faint); margin-bottom: 8px; }
  .fe { display: flex; gap: 10px; padding: 6px 0; border-top: 1px solid var(--line); font-size: 12.5px; }
  .fe time { color: var(--faint); width: 96px; flex: none; }
  .pass { color: var(--green); } .fail { color: var(--red); } .warn { color: var(--yellow); }
  .tagchip { display: inline-block; width: 86px; flex: none; text-align: center; padding: 1px 0;
             border-radius: 8px; font-size: 10.5px; font-weight: 700; letter-spacing: .4px; align-self: flex-start; margin-top: 1px; }
  .tagchip.task { background: var(--accent-soft); color: var(--blue); }
  .tagchip.review { background: var(--accent-soft); color: var(--purple); }
  .tagchip.discussion { background: var(--wait-soft); color: var(--yellow); }
  .tagchip.verify { background: var(--run-soft); color: var(--green); }
  .attn { background: var(--panel); border: 1px solid var(--line);
          border-radius: 8px; padding: 8px 12px; margin-bottom: 8px; font-size: 12.5px;
          display: flex; gap: 10px; align-items: center; }
  .attn.red { border-color: var(--red); }
  .healthbadge { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600;
                 padding: 2px 10px; border-radius: 10px; background: var(--panel2); border: 1px solid var(--line); }
  .btn { background: var(--panel2); border: 1px solid var(--line); color: var(--text);
         border-radius: 7px; padding: 3px 10px; font-size: 12px; cursor: pointer; }
  .btn:hover { border-color: var(--blue); }
  .btn.primary { background: var(--blue); border-color: var(--blue); color: var(--panel); }
  .btn.danger { border-color: var(--red); color: var(--red); }
  .pill.missing  { background: var(--panel2); color: var(--faint); }
  .pill.outdated { background: var(--wait-soft); color: var(--yellow); }
  .modal-back { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: flex;
                align-items: center; justify-content: center; z-index: 50; }
  .modal { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
           max-width: 760px; width: 90%; max-height: 80vh; overflow: auto; padding: 18px 22px; }
  .modal h3 { font-size: 15px; margin-bottom: 10px; }
  .modal .plist { font: 11.5px/1.7 ui-monospace, monospace; color: var(--dim);
                  max-height: 46vh; overflow: auto; margin: 8px 0 14px; }
  .browse-path { font: 12px ui-monospace, monospace; color: var(--dim); word-break: break-all;
                 background: var(--panel2); border: 1px solid var(--line); border-radius: 7px;
                 padding: 5px 9px; margin-bottom: 8px; }
  .browse-list { max-height: 46vh; overflow: auto; margin: 0 0 12px; border: 1px solid var(--line);
                 border-radius: 8px; }
  .browse-row { display: flex; align-items: center; gap: 8px; padding: 6px 12px; cursor: pointer;
                border-top: 1px solid var(--line); font-size: 13px; }
  .browse-row:first-child { border-top: none; }
  .browse-row:hover { background: var(--panel2); }
  .browse-row .proj { margin-left: auto; font-size: 10.5px; color: var(--green); }

  button { font: inherit; }
  button:focus-visible, summary:focus-visible { outline: 2px solid var(--blue); outline-offset: 3px; }
  .stage { padding: 0; }
  .topbar { display:flex; align-items:center; gap:34px; padding:0 32px; border-bottom:1px solid var(--line); min-height:66px; }
  .brand { font-size:22px; font-weight:750; letter-spacing:-.8px; white-space:nowrap; }
  .topnav { display:flex; gap:24px; align-self:stretch; }
  .nav { border:0; border-bottom:3px solid transparent; background:none; color:var(--dim); cursor:pointer; padding:12px 0; }
  .nav.sel { border-color:var(--blue); color:var(--text); font-weight:650; }
  .connection { margin-left:auto; font-size:12px; color:var(--dim); }
  .intro { padding:38px 34px 32px; }
  .intro h1 { font-size:40px; line-height:1.15; letter-spacing:-1.4px; margin:8px 0 10px; }
  .eyebrow { text-transform:uppercase; letter-spacing:1.3px; font-size:11px; color:var(--dim); }
  .inbox { display:grid; grid-template-columns:170px 330px minmax(0,1fr); min-height:520px; border-block:1px solid var(--line); }
  .filters { padding:18px 12px; border-right:1px solid var(--line); }
  .filter { display:flex; justify-content:space-between; align-items:center; width:100%; border:0; border-radius:6px; padding:13px 12px; margin-bottom:5px; background:none; color:var(--dim); text-align:left; cursor:pointer; }
  .filter.sel { background:var(--accent-soft); color:var(--blue); font-weight:650; }
  .count { font-size:11px; padding:1px 7px; border:1px solid var(--line); border-radius:5px; }
  .inbox-list { border-right:1px solid var(--line); min-width:0; }
  .list-heading { display:flex; justify-content:space-between; padding:22px; border-bottom:1px solid var(--line); }
  .project-item { display:flex; gap:14px; text-align:left; width:100%; border:0; border-bottom:1px solid var(--line); background:none; padding:22px; color:var(--text); cursor:pointer; }
  .project-item.sel { background:var(--accent-soft); }
  .project-item:hover, .filter:hover, .health-project:hover { background:var(--panel2); }
  .project-icon { flex:none; width:34px; height:34px; border-radius:7px; display:grid; place-items:center; background:var(--panel2); color:var(--blue); font-weight:700; font-size:17px; }
  .project-item.sel .project-icon { background:var(--blue); color:var(--panel); }
  .project-copy { min-width:0; display:grid; gap:5px; overflow-wrap:anywhere; }
  .project-copy strong { font-size:14px; }
  .project-copy small { color:var(--dim); font-size:12px; }
  .inbox-detail { padding:26px 30px; min-width:0; overflow-wrap:anywhere; background:var(--panel); }
  .inbox-detail h2 { font-size:25px; letter-spacing:-.5px; margin:20px 0; }
  .inbox-detail .tabs { gap:22px; margin-top:0; }
  .detail-kicker { display:flex; gap:10px; align-items:center; color:var(--dim); }
  .detail-question { font-size:16px; line-height:1.6; margin:20px 0 24px; max-width:65ch; }
  .detail-meta { display:flex; flex-wrap:wrap; gap:32px; border-block:1px solid var(--line); padding:18px 0; }
  .detail-meta dt { color:var(--dim); font-size:12px; margin-bottom:7px; }
  .next-action { padding:24px 0; border-bottom:1px solid var(--line); }
  .next-action h3, .evidence h3 { font-size:14px; margin-bottom:12px; }
  .next-action .btn { padding:10px 14px; }
  .evidence { padding:24px 0; }
  .evidence-row { display:flex; justify-content:space-between; gap:16px; border-bottom:1px solid var(--line); padding:12px 0; }
  .more { padding-top:16px; }
  .more summary { color:var(--blue); cursor:pointer; padding-bottom:14px; }
  .health-strip { display:flex; gap:24px; align-items:center; padding:22px 32px; overflow-x:auto; }
  .health-project { background:none; border:0; text-align:left; padding:8px 16px; border-radius:5px; cursor:pointer; color:var(--text); min-width:180px; }
  .health-project small { display:block; color:var(--dim); margin-top:8px; }
  .empty { padding:28px; color:var(--dim); }
  .settings { max-width:1000px; margin:auto; padding:28px 32px; }
  .settings h2 { margin-bottom:24px; }
  .statrow { flex-wrap:wrap; }
  .stat { background:none; border:0; padding:10px 0; }
  .stat .v { font-size:16px; }
  .box, .feed { background:none; border-radius:5px; }
  .step.now { box-shadow:none; }
  .fe { flex-wrap:wrap; }
  @media(max-width:1100px) { .inbox { grid-template-columns:135px 270px minmax(0,1fr); } .inbox-detail { padding:22px; } .grid2 { grid-template-columns:1fr; } }
  @media(max-width:760px) {
    .topbar { padding:12px 18px; gap:12px; flex-wrap:wrap; } .topnav { order:3; width:100%; gap:22px; overflow-x:auto; }
    .intro { padding:26px 20px; } .intro h1 { font-size:32px; }
    .inbox { grid-template-columns:1fr; } .filters { display:flex; gap:8px; border-right:0; border-bottom:1px solid var(--line); padding:10px; }
    .filter { gap:8px; padding:10px; margin:0; } .inbox-list { border-right:0; border-bottom:1px solid var(--line); }
    .project-item { padding:16px 20px; } .inbox-detail { padding:24px 20px; }
    .health-strip { padding:16px 20px; } .health-strip > strong { display:none; }
  }

  /* Studio console: fixed navigation and status; the work panes scroll. */
  body { font:14px/1.5 var(--ui); }
  .stage { display:grid; grid-template-columns:minmax(0,1fr); grid-template-rows:auto auto minmax(0,1fr); height:100dvh; }
  .topbar { display:flex; min-height:0; align-items:center; gap:16px; padding:8px 16px; background:var(--rail); border:0; border-bottom:1px solid var(--line); }
  .brand { display:flex; gap:8px; align-items:center; padding:0; border:0; background:none; color:var(--text); font-size:16px; font-weight:600; cursor:pointer; }
  .brand::before { content:"G"; display:grid; place-items:center; width:24px; height:24px; background:var(--accent-fill); color:var(--accent-fg); border-radius:7px; font-size:12.5px; }
  .connection { margin-left:auto; font-size:12.5px; }
  .settings-menu { position:relative; }
  .settings-menu summary { cursor:pointer; padding:7px 12px; border:1px solid var(--line); border-radius:8px; }
  .settings-menu nav { position:absolute; right:0; top:100%; z-index:10; display:grid; padding:8px; background:var(--card); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); white-space:nowrap; }
  .settings-menu .btn { text-align:left; border:0; }
  .intro { display:flex; flex-wrap:wrap; align-items:baseline; gap:8px 16px; padding:8px 16px; }
  .intro h1 { font-size:16px; font-weight:600; letter-spacing:-.01em; margin:0; }
  .intro p { font-size:12.5px; margin:0; }
  .eyebrow { font-size:10.5px; }
  .inbox { grid-column:1; margin:0 16px 16px; min-height:0; grid-template-columns:240px minmax(0,1fr); grid-template-rows:auto minmax(0,1fr); border:0; border-radius:14px; box-shadow:var(--shadow); overflow:hidden; background:var(--card); }
  .filters { grid-column:1/3; display:flex; gap:8px; padding:8px 14px; border:0; border-bottom:1px solid var(--line); }
  .filter { width:auto; gap:12px; margin:0; padding:7px 12px; border-radius:8px; font-size:12.5px; }
  .inbox-list { min-height:0; overflow:auto; background:var(--rail); }
  .list-heading { padding:8px 14px; font-size:12.5px; }
  .project-item { padding:8px 14px; gap:8px; }
  .project-copy { gap:0; }
  .project-icon { width:24px; height:24px; font-size:12.5px; background:var(--sunken); color:var(--dim); border-radius:8px; }
  .project-item.sel .project-icon { background:var(--accent-fill); color:var(--accent-fg); }
  .project-copy small, .count, .detail-kicker > span:last-child, .ledger, kbd { font-family:var(--mono); font-size:12.5px; }
  .inbox-detail { min-height:0; padding:16px; overflow:auto; }
  .inbox-detail h2 { font-size:16px; font-weight:600; letter-spacing:-.01em; margin:8px 0; }
  .inbox-detail .tabs .nav { padding:8px 0; }
  .detail-question { font-size:14px; margin:12px 0; }
  .detail-meta { gap:24px; padding:12px 0; margin:12px 0 0; }
  .detail-meta dt { margin-bottom:4px; }
  .next-action, .evidence { padding:8px 0; }
  .next-action h3, .evidence h3 { margin:0 0 8px; }
  .next-action .btn { padding:7px 12px; }
  .more { padding-top:8px; }
  .attention-item { padding:12px 0; border-bottom:1px solid var(--line); }
  .health-strip { grid-column:2; padding:8px 16px; gap:12px; border-top:1px solid var(--line); background:var(--rail); }
  .health-project { padding:0 8px; font-size:12.5px; min-width:0; flex:none; }
  .health-project small { margin-top:2px; }
  .btn { padding:7px 12px; border-radius:8px; background:var(--card); }
  .btn.primary { background:var(--accent-fill); color:var(--accent-fg); }
  .box, .feed { border:0; border-radius:14px; box-shadow:var(--shadow); background:var(--card); padding:16px; }
  .settings { grid-column:1; grid-row:2/4; min-height:0; overflow:auto; width:100%; }
  @media(max-width:760px) {
    .stage { display:block; height:auto; }
    .topbar { flex-wrap:wrap; padding:8px 16px; gap:8px; }
    .connection { margin-left:auto; }
    .inbox { display:block; margin:0 16px 16px; }
    .filters { overflow:auto; } .inbox-list,.inbox-detail { overflow:visible; }
  }
</style>
</head>
<body>
<div class="stage" id="stage"></div>
<script>
const DAEMON = __DAEMON_JSON__;
const PHASES = ["inspect","define","research","decide","roadmap","plan","build","ship"];
/* health comes from the backend; fall back to a local guess for older payloads */
const healthOf = p => p.health || (p.status === "blocked" ? "red" : ((p.pending_answers||[]).length || (p.git&&p.git.dirty)) ? "amber" : "green");
const healthDot = p => ({red: "r", amber: "y", green: "g"})[healthOf(p)] || "g";
const HEALTH_LABEL = {green: "healthy", amber: "needs attention", red: "blocked"};
const SEV = {red: 0, amber: 1, green: 2};
const ATTN_PILL = {blocked: '<span class="pill blocked">blocked</span>',
                   failed: '<span class="pill blocked">failed</span>',
                   question: '<span class="pill prog">question</span>',
                   stale: '<span class="pill pend">stale</span>'};
const ATTN_CLS = {blocked: "red", failed: "red"};
const badge = p => p.status === "blocked" ? '<span class="pill blocked">blocked</span>'
                 : p.phase === "shipped"      ? '<span class="pill done">shipped</span>'
                 : '<span class="pill active">' + esc(p.phase || "?") + '</span>';
const ms = p => p.milestone ? "M· " + p.milestone : "—";
const esc = s => String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
/* display form of a skill id: "gsd-path-forensics" -> "FORENSICS". Raw id kept for copy actions. */
const skill = s => s ? s.replace(/^gsd-path-/, "").toUpperCase() : null;
const fmt = n => n >= 1e6 ? (n/1e6).toFixed(1)+"M" : n >= 1e3 ? Math.round(n/1e3)+"k" : String(n);
const dur = s => {
  if (s == null) return "—";
  const d = Math.floor(s/86400), h = Math.floor((s%86400)/3600), m = Math.floor((s%3600)/60);
  return d ? d+"d "+h+"h" : h ? h+"h "+m+"m" : m+"m";
};
const shortT = iso => typeof iso === "string" && iso.length >= 16 ? iso.slice(5,10)+" "+iso.slice(11,16) : (iso || "");

let DATA = {schema: null, generated_at: null, projects: []};
let PLUGIN = null;
let ONLINE = null;
let CState = {root: null, tab: "overview", view: "projects", filter: "all"};
const TABS = ["overview", "activity", "usage", "plugin"];
function setHash() {
  if (["plugin", "folders"].includes(CState.view)) {
    history.replaceState(null, "", "#" + CState.view);
  } else {
    const params = new URLSearchParams({project: CState.root || "", tab: CState.tab, view: CState.view, filter: CState.filter});
    history.replaceState(null, "", "#" + params.toString());
  }
}
function cSel(root) {
  CState.root = root; CState.tab = "overview";
  setHash(); render();
}
function cTab(t) {
  CState.tab = t;
  if (t === "plugin") CState.view = "plugin";
  setHash();
  if (t === "plugin") loadPlugin().then(render);
  render();
}
function navigate(view) {
  CState.view = view; CState.tab = view === "activity" ? "activity" : "overview";
  if (view === "projects") CState.filter = "all";
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
function copySkill(raw) {
  const text = "$" + raw;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text);
  } else {
    const area = document.createElement("textarea");
    area.value = text; document.body.appendChild(area); area.select();
    document.execCommand("copy"); document.body.removeChild(area);
  }
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

function stepper(p) {
  const idx = PHASES.indexOf(p.phase);
  let steps = "";
  for (let i = 0; i < PHASES.length; i++) {
    const cls = p.phase === "shipped" ? "done" : i < idx ? "done" : i === idx
      ? (p.status === "blocked" ? "now\\" style=\\"background:var(--red);box-shadow:0 0 6px var(--red)" : "now") : "";
    steps += '<div class="step ' + cls + '"></div>';
  }
  return steps;
}

function tabOverview(p) {
  const steps = stepper(p);
  const attn = p.attention || [];
  const healthBadge = `<span class="healthbadge"><span class="dot ${healthDot(p)}"></span>${esc(HEALTH_LABEL[healthOf(p)] || healthOf(p))}</span>`;
  const crits = p.criteria || [];
  const cCount = v => crits.filter(c => c.verdict === v).length;
  const critBox = `<div class="box"><h4>Success criteria</h4>` + (crits.length
    ? `<div style="margin-bottom:4px"><span class="vmet">${cCount("met")} met</span> · <span class="vnot">${cCount("not-met")} not-met</span> · <span class="vunv">${cCount("unverifiable")} unverifiable</span></div>` +
      crits.filter(c => c.verdict !== "met").map(c =>
        `<div class="crit"><span class="${c.verdict === "not-met" ? "vnot" : "vunv"}">${esc(c.verdict || "—")}</span>
         <span><b>${esc(c.id || "—")}</b> — ${esc(c.text)}</span></div>`).join("")
    : '<span class="dim">no final review yet</span>') + `</div>`;
  const rmRows = (p.roadmap_milestones || []).map(m => `<div class="rms"><span class="mnum">${esc(m.number)}</span><b>${esc(m.slug)}</b>
    <span class="pill ${m.status === "active" ? "active" : m.status === "shipped" ? "done" : "pend"}">${esc(m.status || "?")}</span>
    ${m.archive ? `<span class="arch">${esc(m.archive)}</span>` : ""}</div>`).join("");
  const roadmapBox = `<div class="box"><h4>Roadmap</h4>`
    + (rmRows || '<span class="dim">No milestones in ROADMAP.md yet.</span>') + `</div>`;
  return `
    <div style="margin-bottom:6px">${healthBadge}</div>
    <div class="steps" style="margin-top:10px">${steps}</div>
    <div class="steplabel">${PHASES.map(x => "<span>"+x+"</span>").join("")}</div>
    <div class="statrow">
      <div class="stat"><div class="v">${p.tasks_done}/${p.tasks_total || "—"}</div><div class="k">tasks done${p.current_wave ? ` · wave ${p.current_wave} “${esc((p.waves || {})[p.current_wave]||"")}”` : ""}</div></div>
      <div class="stat"><div class="v">${dur(p.time_in_phase_s)}</div><div class="k">time in ${esc(p.phase || "?")}</div></div>
      <div class="stat"><div class="v" style="color:${attn.length ? "var(--yellow)" : "var(--text)"}">${attn.length}</div><div class="k">attention items</div></div>
      <div class="stat"><div class="v">${p.git ? (p.git.dirty ? '<span style="color:var(--yellow)">dirty</span>' : "clean") : "—"}</div><div class="k">git · ${esc(p.branch || "no branch")}</div></div>
    </div>
    <div class="grid2" style="margin-top:12px">${critBox}${roadmapBox}</div>`;
}

function tabUsage(p) {
  const u = p.usage;
  if (!u) {
    return '<p class="dim" style="padding:30px 0">No usage ledger yet — the pipeline can record one at <kbd>.project/build/usage.jsonl</kbd> (one JSON object per line: task, model, family, tokens_in, tokens_out, cost, recorded_at, phase?).</p>';
  }
  const tot = (u.tokens_in||0) + (u.tokens_out||0);
  const mrows = (u.models||[]).map(m => `<div class="prow" style="align-items:center">
    <span style="width:190px"><b>${esc(m.model)}</b> <span class="faint">${esc(m.family||"")}</span></span>
    <span style="flex:1;margin:0 12px"><span class="bar"><i style="width:${Math.round((m.share||0)*100)}%;background:var(--blue)"></i></span></span>
    <span class="dim" style="width:130px;text-align:right">${fmt(Math.round(tot*(m.share||0)))} tok · ${Math.round((m.share||0)*100)}%</span></div>`).join("");
  const maxT = Math.max(...(u.by_phase||[]).map(x => x.tokens||0), 1);
  const prows = (u.by_phase||[]).map(x => `<div class="prow" style="align-items:center">
    <span style="width:190px">${esc(x.phase)}${x.phase === p.phase ? ' <span class="pill active">now</span>' : ""}</span>
    <span style="flex:1;margin:0 12px"><span class="bar"><i style="width:${x.tokens ? Math.max(3, Math.round(100*x.tokens/maxT)) : 2}%;background:var(--purple)"></i></span></span>
    <span class="dim" style="width:120px;text-align:right">${x.tokens ? fmt(x.tokens)+" tok" : "—"}</span></div>`).join("");
  const trows = (u.by_task||[]).map(t => `<tr><td class="dim">${esc(t.task)}</td><td>${esc(t.model||"—")}</td><td class="dim">${fmt(t.tokens||0)} tok</td></tr>`).join("");
  return `
  <div class="statrow">
    <div class="stat"><div class="v">${fmt(tot)}</div><div class="k">tokens · in ${fmt(u.tokens_in||0)} / out ${fmt(u.tokens_out||0)}</div></div>
    <div class="stat"><div class="v">$${(u.cost||0).toFixed(2)}</div><div class="k">est. cost this milestone</div></div>
    <div class="stat"><div class="v">${(u.models||[]).length}</div><div class="k">models</div></div>
    <div class="stat"><div class="v">${dur(p.time_in_phase_s)}</div><div class="k">time in ${esc(p.phase || "?")}</div></div>
  </div>
  <div class="grid2">
    <div class="box"><h4>Tokens by model</h4>${mrows}
      <div class="faint" style="margin-top:9px;font-size:10.5px">same-model agreement counts as one evidence path — mixed families make reviews independent</div></div>
    <div class="box"><h4>Tokens by phase — ${esc(ms(p))}</h4>${prows}</div>
  </div>
  ${trows ? `<div class="box" style="margin-top:12px"><h4>Top tasks by tokens</h4>
    <table class="tasks"><tr><th>Task</th><th>Model</th><th>Tokens</th></tr>${trows}</table></div>` : ""}`;
}

function activityItems(p) {
  const dated = [], undated = [];
  for (const e of (p.ledger || [])) {
    dated.push({ts: e.recorded_at || null, tag: "verify", chip: "VERIFY",
      title: e.command || "(no command)",
      right: e.result || "?", cls: e.result === "pass" ? "pass" : e.result === "fail" ? "fail" : "dim",
      sub: e.commit ? "@" + String(e.commit).slice(0,7) : null});
  }
  for (const t of (p.tasks || [])) {
    undated.push({tag: "task", chip: "TASK",
      title: (t.id || "?") + (t.title ? " — " + t.title : ""),
      right: t.status || "?", cls: t.status === "done" ? "pass" : (t.status === "failed" ? "fail" : ""),
      sub: t.wave != null ? "wave " + t.wave : null});
  }
  for (const r of (p.reviews || [])) {
    undated.push({tag: "review", chip: "REVIEW",
      title: (r.file || "?") + (r.note ? " — " + r.note : ""),
      right: (r.verdict || "—").toUpperCase(),
      cls: r.verdict === "pass" ? "pass" : (r.verdict ? "fail" : ""),
      sub: [r.kind, r.cycle != null ? "cycle " + r.cycle : null, r.depth].filter(Boolean).join(" · ")});
  }
  for (const a of (p.answers || [])) {
    undated.push({tag: "discussion", chip: "DISCUSSION",
      title: (a.id || "?") + (a.question ? " — " + a.question : ""),
      right: a.status || "?", cls: a.status === "final" ? "pass" : (a.status === "NEEDS-USER" ? "warn" : ""),
      sub: [a.thread ? "thread " + a.thread : null, a.owner ? "owner " + skill(a.owner) : null,
            a.target ? "target " + a.target : null].filter(Boolean).join(" · ")});
  }
  dated.sort((x, y) => String(y.ts).localeCompare(String(x.ts)));
  return dated.concat(undated);
}

function tabActivity(p) {
  const items = activityItems(p).slice(0, 100);
  const rows = items.map(it => `<div class="fe">
    <span class="tagchip ${it.tag}">${it.chip}</span>
    <span style="flex:1">${esc(it.title)}${it.sub ? `<br><span class="faint">${esc(it.sub)}</span>` : ""}</span>
    <time>${it.ts ? esc(shortT(it.ts)) : "—"}</time>
    <b class="${it.cls}" style="width:110px;flex:none;text-align:right">${esc(it.right)}</b>
  </div>`).join("");
  return `<div class="feed" style="margin-top:4px"><h3>${esc(p.project || p.root)} — activity</h3>`
    + (rows || '<p class="dim">no activity recorded yet for this project</p>') + `</div>`;
}

function tabPlugin() {
  if (!PLUGIN) {
    return '<p class="dim" style="padding:30px 0">Loading plugin status…</p>';
  }
  const hosts = PLUGIN.hosts || {};
  const latest = PLUGIN.latest || null;
  const installed = Object.entries(hosts).filter(([, d]) => d.installed);
  const versions = [...new Set(installed.map(([, d]) => d.version || "unknown"))];
  const banner = `<div class="box" style="margin:4px 0 14px;display:flex;align-items:center;gap:12px">
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

function projectSummary(p) {
  if ((p.attention || []).length) return p.attention[0].label || "Needs your attention";
  if (p.phase === "shipped") return "Milestone shipped";
  if (p.tasks_total) return `${p.tasks_done || 0} of ${p.tasks_total} tasks done`;
  return `${p.phase || "Project"} in progress`;
}
function inboxDetail(p) {
  const items = p.attention || [];
  return `<div class="detail-kicker"><b>${esc(p.project || p.root)}</b> · ${esc(p.phase || "Unknown")}</div>
    <p class="dim">${esc(p.root)} <button class="btn" data-copy-path="${esc(p.root)}">Copy path</button></p>
    ${items.length ? items.map(item => attentionDetail(p, item)).join("") : `<h2>${esc(projectSummary(p))}</h2>`}
    <section class="next-action"><h3>Next step</h3>${p.next_skill ? `<button class="btn" data-copy="${esc(p.next_skill)}">Copy ${esc(skill(p.next_skill).toLowerCase())} command</button>` : '<p class="dim">No next command reported.</p>'}</section>
    <section class="evidence"><h3>Latest verification</h3>${(p.ledger || []).map(e => `<div class="evidence-row"><span>${esc(e.command)}<br><small class="dim">${esc(shortT(e.recorded_at))}${e.commit ? " · " + esc(e.commit) : ""}</small></span><strong class="${e.result === 'pass' ? 'pass' : e.result === 'fail' ? 'fail' : 'dim'}">${esc(e.result || 'Unknown')}</strong></div>`).join('') || '<p class="dim">No verification recorded yet.</p>'}</section>
    <details class="more"><summary>Progress, criteria and roadmap</summary>${tabOverview(p)}</details>`;
}
function attentionDetail(p, item) {
  const answer = item && [...(p.answers || []), ...(p.pending_answers || [])].find(a => (a.id || a.answer) === item.ref);
  return `<section class="attention-item">
    <h2>${esc(item ? item.label : projectSummary(p))}</h2>
    ${answer ? `<p class="detail-question">${esc(answer.question || item.label)}</p>` : ""}
    <dl class="detail-meta"><div><dt>Status</dt><dd>${item ? (ATTN_PILL[item.kind] || esc(item.kind)) : badge(p)}</dd></div>
      <div><dt>Phase</dt><dd>${esc(p.phase || "Unknown")}</dd></div>
      ${answer ? `<div><dt>Owner</dt><dd>${esc(skill(answer.owner) || "Not recorded")}</dd></div>` : ""}
      ${item && item.ref ? `<div><dt>Reference</dt><dd>${esc(item.ref)}</dd></div>` : ""}</dl>
    <button class="btn" data-action="discussion" data-ref="${esc(item.ref || '')}">${item.kind === 'question' ? 'View discussion' : 'View evidence'}</button></section>`;
}
function render() {
  const stage = document.getElementById("stage");
  const previousKey = stage.dataset.readingKey;
  const scroll = ['.inbox-list', '.inbox-detail', '.settings'].map(selector => {
    const el = stage.querySelector(selector);
    return [selector, el?.scrollTop || 0, el?.scrollLeft || 0];
  });
  const settingsOpen = !!stage.querySelector('.settings-menu[open]');
  const expanded = !!stage.querySelector('.more[open]');
  const pageScroll = [window.scrollX, window.scrollY];
  const focus = document.activeElement;
  const focusIndex = [...stage.querySelectorAll('button, summary, [tabindex]')].indexOf(focus);
  const projects = (DATA.projects || []).slice().sort((a,b) => (SEV[healthOf(a)] ?? 2) - (SEV[healthOf(b)] ?? 2) || String(a.project || a.root).localeCompare(String(b.project || b.root)));
  const attention = projects.filter(p => (p.attention || []).length);
  const running = projects.filter(p => !(p.attention || []).length && p.phase !== "shipped");
  const visible = CState.filter === "attention" ? attention : CState.filter === "running" ? running : projects;
  const p = visible.find(p => p.root === CState.root) || visible[0];
  if (ONLINE !== null) CState.root = p ? p.root : null;
  const connection = ONLINE === null ? "Connecting…" : ONLINE ? "Connected" : "Offline · showing last update";
  const header = `<header class="topbar"><button class="brand" data-nav="projects" aria-label="GSD Path projects">GSD Path</button><span class="connection" role="status"><span class="dot ${ONLINE === null ? "" : ONLINE ? "g" : "r"}"></span> ${connection}</span><details class="settings-menu"><summary>Settings</summary><nav aria-label="Settings"><button class="btn" data-nav="plugin">Plugin</button><button class="btn" data-nav="folders">Watched folders</button></nav></details></header>`;
  let body;
  if (CState.view === "plugin") body = `<main class="settings"><h2>Plugin</h2>${tabPlugin()}</main>`;
  else if (CState.view === "folders") body = `<main class="settings"><h2>Watched folders</h2><p class="dim">Projects inside these folders appear automatically.</p>${(DAEMON.parents || []).map((path,i) => `<div class="evidence-row"><span>${esc(path)}</span><button class="btn danger" data-remove-parent="${i}">Stop watching</button></div>`).join("")}<p class="more"><button class="btn" data-action="add-folder">Add folder…</button></p></main>`;
  else {
    const list = visible.map(q => `<button class="project-item ${p && p.root === q.root ? "sel" : ""}" data-root="${esc(q.root)}" aria-pressed="${p && p.root === q.root ? "true" : "false"}"><span class="project-icon">${esc((q.project || "?").slice(0,1))}</span><span class="project-copy"><strong>${esc(q.project || q.root)}</strong><span>${esc(projectSummary(q))}</span><small><span class="dot ${healthDot(q)}"></span> ${esc(q.phase || "Unknown")} · ${esc(q.milestone || "No milestone")}</small></span></button>`).join("");
    const detail = !p ? `<div class="empty">${ONLINE === null ? "Loading projects…" : !ONLINE && !projects.length ? "Cannot load projects. Check the daemon connection." : projects.length ? "No projects in this filter." : "No projects yet. Add a watched folder to get started."}</div>`
      : CState.tab === "activity" ? `<h2>${esc(p.project || p.root)}</h2>${tabActivity(p)}`
      : CState.tab === "usage" ? `<h2>${esc(p.project || p.root)}</h2>${tabUsage(p)}`
      : inboxDetail(p);
    body = `<section class="intro"><h1>Projects</h1><p class="dim">${attention.length} ${attention.length === 1 ? "project needs" : "projects need"} attention. ${running.length} ${running.length === 1 ? "project is" : "projects are"} active.${DATA.generated_at ? " Updated " + esc(shortT(DATA.generated_at)) + "." : ""}</p></section>
      <main class="inbox"><aside class="filters" aria-label="Project filters">${[["attention","Attention",attention.length],["running","Active",running.length],["all","All projects",projects.length]].map(([f,label,count]) => `<button class="filter ${CState.filter === f ? "sel" : ""}" data-filter="${f}" aria-pressed="${CState.filter === f}">${label}<span class="count">${count}</span></button>`).join("")}</aside>
      <section class="inbox-list" tabindex="0" aria-label="Projects"><div class="list-heading"><b>Projects</b><small class="dim">Attention first</small></div>${list || '<p class="empty">No projects to show.</p>'}</section>
      <section class="inbox-detail" tabindex="0" aria-label="Project details">${p ? `<div class="tabs">${[["overview","Overview"],["activity","Activity"],["usage","Usage"]].map(([t,label]) => `<button class="nav ${CState.tab === t ? "sel" : ""}" data-tab="${t}">${label}</button>`).join("")}</div>` : ""}${detail}</section></main>
`;
  }
  const readingKey = JSON.stringify([CState.view, CState.filter, CState.root, CState.tab]);
  stage.innerHTML = header + body;
  stage.dataset.readingKey = readingKey;
  if (previousKey === readingKey) {
    stage.querySelector('.settings-menu').open = settingsOpen;
    const more = stage.querySelector('.more');
    if (more) more.open = expanded;
    for (const [selector, top, left] of scroll) {
      stage.querySelector(selector)?.scrollTo(left, top);
    }
    window.scrollTo(...pageScroll);
  }
  if (previousKey === readingKey && focusIndex >= 0) {
    stage.querySelectorAll('button, summary, [tabindex]')[focusIndex]?.focus({preventScroll:true});
  }
}
document.getElementById("stage").addEventListener("click", event => {
  const b = event.target.closest("button");
  if (!b) return;
  if (b.dataset.nav) navigate(b.dataset.nav);
  else if (b.dataset.filter) { CState.filter = b.dataset.filter; CState.root = null; CState.tab = "overview"; render(); setHash(); }
  else if (b.dataset.root) cSel(b.dataset.root);
  else if (b.dataset.healthRoot) { CState.filter = "all"; CState.view = "inbox"; cSel(b.dataset.healthRoot); }
  else if (b.dataset.tab) cTab(b.dataset.tab);
  else if (b.dataset.copy || b.dataset.copyPath) {
    navigator.clipboard.writeText(b.dataset.copyPath || "$" + b.dataset.copy).then(() => { b.textContent = "Copied"; }, () => { b.textContent = "Copy failed — try again"; });
  }
  else if (b.dataset.action === "discussion") {
    cTab("activity");
    const row = [...stage.querySelectorAll('.fe')].find(el => b.dataset.ref && el.textContent.includes(b.dataset.ref));
    row?.scrollIntoView({block:'nearest'});
  }
  else if (b.dataset.action === "add-folder") addParent();
  else if (b.dataset.removeParent != null) removeParent(DAEMON.parents[Number(b.dataset.removeParent)]);
});
function applyHash() {
  const h = location.hash.slice(1);
  if (h === "plugin" || h === "folders") {
    CState.view = h;
    if (h === "plugin") loadPlugin().then(render);
  } else {
    const params = new URLSearchParams(h);
    CState.root = params.get("project");
    CState.tab = TABS.includes(params.get("tab")) ? params.get("tab") : "overview";
    CState.view = "projects";
    CState.filter = ["attention","running"].includes(params.get("filter")) ? params.get("filter") : "all";
    if (CState.tab === "plugin") { CState.view = "plugin"; loadPlugin().then(render); }
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
