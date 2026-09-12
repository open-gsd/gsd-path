# gsd-path-daemon

A progress-monitoring daemon and cross-platform tray app for GSD Path
projects. It watches one or more folders for
directories containing a `.project/STATE.md` with `pipeline: gsd-path/v2`,
parses the pipeline state (phase, status, tasks, waves, roadmap, lookahead
milestone), enriches it with git info and — when available — the project's
bundled runtime status, and surfaces everything through a CLI, a localhost
HTTP endpoint, a JSONL event history, desktop notifications, and a system
tray icon.

The daemon is strictly read-only against watched projects: file reads plus
`git` read commands only. It never writes into a watched project.

## Install (one command)

From a repository checkout:

```bash
PYTHONPATH=daemon python3 -m gsd_daemon install
```

or, once the package is installed anywhere (`pip install ./daemon`):

```bash
gsd-path-daemon install
```

The installer prints a numbered step list as it goes and is idempotent —
re-running it upgrades cleanly. It:

1. Creates an isolated virtualenv at `~/.gsd-path/venv` and installs the
   daemon package from the checkout into it (then the `[tray]` extra; if the
   extra fails — no network, no pystray wheel — it warns and continues, since
   the CLI, watcher, and dashboard work without it).
2. Registers autostart for the dashboard server
   (`python -m gsd_daemon serve --port 8765`):
   - **macOS** — a LaunchAgent at
     `~/Library/LaunchAgents/org.gsd-path.daemon.plist` (`RunAtLoad` +
     `KeepAlive`, logs in `~/.gsd-path/logs/{stdout,stderr}.log`), loaded with
     `launchctl bootstrap gui/<uid>` (falls back to `launchctl load`).
   - **Windows** — a `gsd-path-daemon.lnk` shortcut in the Startup folder
     targeting `<venv>\Scripts\pythonw.exe -m gsd_daemon tray --serve` (one
     process for tray + dashboard).
   - **Linux** — a best-effort systemd user unit
     `~/.config/systemd/user/gsd-path-daemon.service` plus
     `systemctl --user enable --now`.
3. On macOS, builds the native tray app (`daemon/macos/build.sh`, requires
   `swiftc`), copies it to `~/Applications/GSDPathTray.app`, and adds a login
   item. Without `swiftc` it skips this step with a warning.

Flags: `--dry-run` prints every action (exact commands and paths) without
executing anything; `--no-tray` skips the tray extra and the native app;
`--no-autostart` installs only. Preview another platform's steps with
`GSD_DAEMON_PLATFORM=win32|linux ... install --dry-run`.

Remove the autostart registration (the venv is kept; delete
`~/.gsd-path/venv` manually to remove everything):

```bash
python3 -m gsd_daemon uninstall
```

Check status:

- **macOS** — `launchctl print gui/<uid>/org.gsd-path.daemon`;
  logs at `~/.gsd-path/logs/`.
- **Windows** — Task Manager → Startup tab (`gsd-path-daemon`).
- **Linux** — `systemctl --user status gsd-path-daemon`.

## Install (manual)

Core (CLI, watcher, HTTP server) — stdlib only, Python 3.9+:

```bash
pip install ./daemon
```

With the tray app (adds `pystray` and `Pillow`):

```bash
pip install './daemon[tray]'
```

## CLI

```bash
gsd-path-daemon scan            # {"projects": [{root, project, milestone, phase, status}...]}
gsd-path-daemon dump            # full aggregated status JSON (schema gsd-path-daemon/status/v1)
gsd-path-daemon serve --port 8765   # localhost dashboard: GET / (HTML), GET /status (JSON)
gsd-path-daemon tray            # system tray app
gsd-path-daemon tray --serve [--port 8765]  # tray + dashboard server in one process
gsd-path-daemon install [--no-tray] [--no-autostart] [--dry-run]  # venv + autostart
gsd-path-daemon uninstall [--dry-run]                             # remove autostart
gsd-path-daemon plugin <status|install|update|uninstall>          # manage the skill plugin
```

`python -m gsd_daemon <command>` works too when the package is on `PYTHONPATH`.

## Dashboard

`gsd-path-daemon serve` runs a localhost-only HTTP server (default port
8765):

- `GET /health` — `{"ok": true}` liveness probe.
- `GET /status` — aggregated status JSON (same shape as `dump`; see the
  schema below). Also consumed by the native macOS app.
- `GET /activity` — recent events from `history.jsonl`, newest first.
- `GET /` — a self-contained dashboard (inline CSS/JS, no build step) that
  polls `/status` every 5 seconds.

The dashboard uses the GSD Cloud Studio theme (system light/dark, or force one
with `<html data-theme="light|dark">`) and is a pure **status board**: what each
project has done, where it is now, and where its roadmap goes next. It shows
no next steps, commands, or attention items.

- A slim top toolbar contains the GSD Path home action, a one-line summary
  (projects, in progress, blocked, shipped), connection status with the last
  update time, and a **Settings** menu for Plugin and Watched Folders.
- One card per project holds its **milestone stack**: shipped milestones
  collapsed to a line, the current milestone expanded with phase, wave, task
  progress, time in phase, waves (done ✓ / current ● / ahead ○) and the git
  branch and head, then planned milestones as ghosts, or "end of roadmap".
  Past and planned milestones come from `.project/ROADMAP.md`; the lookahead
  milestone from `.project/next/STATE.md` is appended when it is not listed.
- Cards are ordered blocked, then in progress, then shipped, by name within
  each group. The state pill reads Blocked, In <phase>, or Shipped; the dot
  keeps the daemon's health colour.

`#project=<root>` (used by the native tray) highlights and reveals that card.
`#plugin` and `#folders` open settings directly; the GSD Path toolbar button
returns to the board. Refresh preserves scroll position, the open Settings
menu, and focus. Connection status changes to Offline after a failed status
request; the last received data remains visible with an explicit offline label.
The dashboard does not execute pipeline commands.

## Plugin lifecycle

The daemon manages the gsd-path **skill plugin** itself (this is separate
from `install`/`uninstall`, which manage the daemon): install, update, and
uninstall, both globally (per-host skill roots) and per-project.

**Source.** The npm package is unpublished, so the only working source is a
git clone. The daemon keeps one at `~/.gsd-path/src`
(`https://github.com/open-gsd/gsd-path.git`, override with the `plugin_repo`
key in `daemon.json`) and runs its `scripts/install.py` for every
install/update. `refresh_source` does `git fetch origin main` +
`git pull --ff-only` at most once per 24h, cached in
`~/.gsd-path/update-check.json` (last-fetch timestamp + last-known latest
version from the clone's `package.json`). Offline or any failure falls back
to the cached state and never raises. Every operation (argv, exit code,
output tail) is appended to `~/.gsd-path/logs/plugin.log`.

**Private repo.** `open-gsd/gsd-path` is currently private, so cloning needs
GitHub credentials on the machine. `ensure_source` tries HTTPS first, then
SSH (`git@github.com:open-gsd/gsd-path.git`) on failure. If neither works it
fails with plain-English guidance: run `gh auth login`, add an SSH key to the
GitHub account, or set `plugin_repo` to a token-embedded URL. Once the repo
goes public (or publishes releases), no credentials are needed — and the
source strategy can move from clone to release-archive download behind the
same single function.

**CLI:**

```bash
gsd-path-daemon plugin status [--json]                 # detected installs + update state (no clone, no fetch)
gsd-path-daemon plugin install --global [--host kimi --host claude]
gsd-path-daemon plugin install --project PATH [--local HOST ...] [--hooks]
gsd-path-daemon plugin update [--global | --project PATH] [--dry-run]
gsd-path-daemon plugin uninstall (--global [--host H ...] | --project PATH) [--dry-run] [--yes]
```

`plugin status` and the update check work offline from VERSION stamps and
the cache — they never clone. Uninstall without `--yes` prints the removal
plan and stops; `--yes` is required to apply anything.

**API** (all POST bodies are JSON; operations run in a worker thread under
one global op-lock — a second concurrent operation gets
`409 {"error": "operation in progress"}`):

- `GET /status` — now includes a top-level `plugin` key
  (`{latest, update_available, hosts}`) built cheaply from VERSION probes
  and the cache only — no git fetch.
- `GET /api/plugin/status` — full detection: global hosts plus
  `projects: [...]` for every watched root.
- `POST /api/plugin/install` — `{scope: "global"|"project", hosts?, root?,
  local_hosts?, hooks?, dry_run?}` → `{ok, argv, stdout_tail, error}`.
- `POST /api/plugin/update` — `{scope, root?, dry_run?}`.
- `POST /api/plugin/uninstall` — `{scope, hosts?, root?, dry_run?}` returns
  the plan; `{..., confirm: true}` applies it. Neither `dry_run` nor
  `confirm` → 400.

**Uninstall safety rules** (daemon-owned, dry-run = plan only):

- Global: removes only directories under a host root named `gsd-path`,
  `gsd-path-*`, or `path` **and** proven by a `VERSION` stamp or a SKILL.md
  mentioning gsd-path, plus `~/.cursor/agents/gsd-path.md`. Managed-name
  directories without that proof are skipped with a reason.
  `disabled-gsd-skills*` backup directories are never touched.
- Project: project-local managed skill dirs; `.gsd-path/runtime/*.py` and
  `status_runtime.py` only when marker-matched; `guard_hook.py` /
  `git_guard.py` only when marker-matched; `AGENTS.md`, `WORKFLOW.md`, and
  `.claude/CLAUDE.md` only when byte-identical to the source template
  (user-modified files are kept); settings files
  (`.claude/settings.json`, `.codex/hooks.json`, `.cursor/hooks.json`) are
  surgically un-merged — only the gsd-path guard entries are removed,
  foreign keys and hooks are preserved, and the file is deleted only if
  nothing remains; git hooks (`pre-commit`, `commit-msg`, `pre-push`) only
  when marker-matched. Nothing under `.project/` is ever planned or
  removed.

Power users can always drive the plugin installer directly with
`node scripts/install.mjs`, `python3 scripts/install.py`, or `npx gsd-path`
from a checkout — the daemon is a convenience wrapper around the same
installer.

## `/status` schema

Top level: `schema` (`gsd-path-daemon/status/v1`), `generated_at`,
`projects`, and `plugin` (`{latest, update_available, hosts}` — cheap
VERSION-stamp probes plus the update-check cache, never a git fetch; see
"Plugin lifecycle"). Each project object carries (keys are stable and additive):

- Identity/state: `root`, `project`, `milestone`, `phase`, `status`,
  `branch`, `archive`, `integration`, `status_source`, `state_mtime`,
  `last_activity_iso`.
- Progress: `tasks` (`[{id, title, wave, status, files}]`), `tasks_done`,
  `tasks_total`, `current_wave`, `waves`, `roadmap_milestones`
  (`[{number, slug, status, archive, duration_s, tokens}]` — `duration_s`
  and `tokens` are null placeholders for now), `next_milestone`, `git`
  (`{branch, head, dirty}`).
- Runtime enrichment: `pending_answers`, `next_skill`.
- Dashboard detail:
  - `reviews` — `[{file, kind, verdict, cycle, depth, note}]` parsed from
    `.project/review/*.md` (`kind` is `wave`, `final`, `gap`,
    `patch-findings`, or `other`).
  - `criteria` — per-criterion verdicts `[{id, text, verdict}]` from
    `.project/review/FINAL.md`, or `null` when no final review exists.
  - `ledger` — most recent 20 entries (newest first) of
    `.project/build/verify-ledger.jsonl`:
    `[{command, commit, result, recorded_at}]`.
  - `answers` — pending discussion records
    `[{id, question, owner, status, thread, target}]` (question truncated
    to 200 chars). Prefers the project's bundled runtime status; falls
    back to a tolerant direct parse of `.project/discuss/ANSWERS.md`.
  - `time_in_phase_s` — seconds in the current phase (int or null),
    derived from `history.jsonl` phase-changed events, else the STATE.md
    log.
  - `usage` — aggregated usage ledger (see below), or `null` when absent.

## Usage ledger (opt-in)

The daemon aggregates `.project/build/usage.jsonl` when the pipeline (or a
host integration) records it. One JSON object per line; every key is
optional and missing keys are tolerated:

```json
{"task": "T001", "model": "kimi-k2", "family": "kimi", "tokens_in": 1200, "tokens_out": 400, "cost": 0.12, "recorded_at": "2026-09-11T11:00:00+00:00", "phase": "build"}
```

The aggregated `usage` object is
`{tokens_in, tokens_out, cost, models: [{model, family, share}],
by_phase: [{phase, tokens}], by_task: [{task, model, tokens}]}` with
`by_task` limited to the top 10 by tokens.

## Config

JSON at `~/.gsd-path/daemon.json` (override with `--config` or the
`GSD_DAEMON_CONFIG` environment variable):

```json
{
  "parents": ["/Users/you/work"],
  "excludes": ["/Users/you/work/archive"],
  "max_depth": 6,
  "poll_seconds": 5,
  "notify": true,
  "history": true
}
```

- `parents` — folders scanned for gsd-path projects (absolute paths).
- `excludes` — paths skipped during scanning (exact path or prefix).
- `max_depth` — how deep below each parent to look for `.project/STATE.md`.
- `poll_seconds` — watcher poll interval.
- `notify` — desktop notifications for phase changes, blocks, pending answers.
- `history` — append events to `~/.gsd-path/history.jsonl`
  (override with `GSD_DAEMON_HISTORY`).

## Autostart (manual fallback)

`gsd-path-daemon install` registers autostart automatically; the recipes
below are only for hand-rolled setups.

### macOS LaunchAgent

`~/Library/LaunchAgents/org.gsd-path.daemon.plist` (the label the installer
uses — keep them identical so `uninstall` can clean up):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>org.gsd-path.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/you/.gsd-path/venv/bin/python3</string>
    <string>-m</string>
    <string>gsd_daemon</string>
    <string>serve</string>
    <string>--port</string>
    <string>8765</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/you/.gsd-path/logs/stdout.log</string>
  <key>StandardErrorPath</key><string>/Users/you/.gsd-path/logs/stderr.log</string>
</dict>
</plist>
```

Then `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/org.gsd-path.daemon.plist`
(or `launchctl load -w` on older macOS).

### Windows Startup folder

Create a shortcut in `shell:startup` (Win+R → `shell:startup`) with target:

```
"C:\Users\you\.gsd-path\venv\Scripts\pythonw.exe" -m gsd_daemon tray --serve
```

or run `gsd-path-daemon.exe tray --serve` from a PowerShell scheduled task at
logon.
