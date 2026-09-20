# gsd-path-daemon

A progress-monitoring daemon and cross-platform tray app for GSD Path
projects. It watches one or more folders for
directories containing a `.project/STATE.md` with `pipeline: gsd-path/v2`,
parses the pipeline state (phase, status, tasks, waves, roadmap, lookahead
milestone), enriches it with git info and — when available — the project's
bundled runtime status, and surfaces everything through a CLI, a localhost
HTTP endpoint, a JSONL event history, desktop notifications, and a system
tray icon.

Background monitoring is read-only against watched projects: file reads plus
`git` read commands only. Completion checks may read the remote refs and, for
pull-request integration, GitHub metadata. They never fetch or write refs.
Unavailable or stale proof is shown as **Unverified**, with available phase
and task facts retained. Explicit **Settings → Path settings** saves are the
exception: they invoke the selected runtime's validated config helper and cannot
advance pipeline phases.

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
     `KeepAlive`, `ProcessType` Interactive so the scan is not throttled to
     background QoS, logs in `~/.gsd-path/logs/{stdout,stderr}.log`), loaded with
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

Core (CLI, watcher, HTTP server), Python 3.9+. The package installs
`markdown-it-py` for safe Markdown previews:

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
- `GET /status` — aggregated status JSON (the `dump` schema below, plus
  `daemon` with current `parents` and `poll_seconds`, and compact `plugin`
  status). Also consumed by the native macOS app.
- `GET /activity` — recent events from `history.jsonl`, newest first.
- `GET /` — a self-contained dashboard (inline CSS/JS, no build step) that
  polls `/status` every 5 seconds.
- `POST /api/refresh` — scans projects before returning `{"ok": true}`.
- `POST /api/config/parents` — accepts `{"action": "add"|"remove", "path":
  "<folder>"}`, saves the watched folders, and scans projects before returning
  `ok`, the current `parents`, and the discovered `projects` count. These
  request scans skip host session logs, share a lock with background scans,
  and record changes when history is enabled.

The native dashboard window fills the display's usable area on first open
(later sizes are kept) and the green button can take it into macOS full screen.
The board and project page use the full window width; prose (vision, notes)
stays at a readable line length.

The dashboard uses graphite neutrals with the macOS accent color (CSS `AccentColor`,
system blue where unsupported), light by default. Settings → Appearance
switches between System, Light and Dark; the choice is kept in the browser, and
the tray passes its own choice as `?theme=`. It is a pure **status board**: what each
project has done, where it is now, where its roadmap goes next, and what it has
cost. The project page also shows the runtime handoff described under
[/status schema](#status-schema).

- **Toolbar**: OpenGSD Path mark and name, All / Active / Shipped filters with counts, a project
  search, Refresh (requests a project scan and reloads status), the last update
  time, and the Settings menu (Plugin, Watched folders).
- **Watched folders**: Add folder opens a picker; click a folder or `..` to
  navigate, then select the current folder. Stop watching opens a confirmation
  dialog; Cancel or clicking outside it leaves the folder watched. Adding or
  removing a folder updates discovered projects immediately. Other open
  dashboards receive the current watched folders on their next status poll.
- **Board**: one table row per project, blocked first, then in progress and
  Unverified, then shipped. Columns: project with health dot and path, route
  (one square per milestone: done, current, ahead; red when blocked), current milestone, an
  8-segment phase meter (inspect, define, research, decide, roadmap, plan,
  build, ship), tasks, cost and turns for the project, last activity, state.
  The health dot's tooltip gives the reason (for example `no activity for 21d`).
- **Project page** (click a row, or the tray's `#project=<root>` deep link): the
  toolbar becomes Back and a project switcher. The page shows a facts strip
  (state, health with its reason, milestone, branch, head, integration mode,
  updated, cost, turns) and the charter vision. The left column holds the phase
  track with entry dates; the current milestone with goal, intent, task
  progress, entered date, waves, criteria and the last verify result; success
  criteria with their text and verdict; a milestone table (shipped milestones
  with ship date, tasks, waves, review cycles, integrated commit, carried
  rulings and verdict; planned milestones with depends-on; cost, turns and
  tokens per milestone); tasks with their files; reviews (kind, cycle, depth,
  verdict, note); and the verify ledger (latest 20 runs). The right column holds
  **Usage**, **Activity** (changes recorded in `history.jsonl` for the project)
  and the latest lesson.
- **Usage** comes from host session logs matched to the project root by working
  directory: Codex rollouts (`~/.codex/sessions` and Orca's per-account homes)
  and Claude Code transcripts (`~/.claude/projects`). It shows cost, turns,
  prompts, tokens in / cached / out, cache hit rate, agent time (Codex turn
  durations; Claude transcripts carry none), cost per priced turn and time per
  timed turn; a per-model table with host, turns, tokens and cost; a per-agent table
  with agent time (the `$gsd-path-*` skill and task named in the
  session, subagents marked), and a folded per-turn ledger with time, agent,
  model, in / cached / out tokens, cost and duration. A turn is one model
  response. Turns dated on or before a milestone's ship date count toward that
  milestone; later turns toward the current one.
- **Cost** is tokens × the `prices` table in `daemon.json`, USD per million
  tokens per model, e.g. `{"prices": {"gpt-6-astra": {"input": 1.25,
  "cached": 0.125, "output": 10}}}`. There are no built-in prices: a model
  without a price contributes tokens only and is listed as unpriced.
  `session_dirs` overrides the scanned locations (glob patterns). The daemon
  atomically saves resolved file-to-working-directory matches in
  `~/.gsd-path/sessions-index.json`; an unreadable or corrupt cache is ignored.
  With `GSD_DAEMON_CONFIG`, the cache sits beside that config file; `--config`
  alone does not move it. Restarts reuse resolved matches and retry unresolved
  heads. Within a run, unresolved heads are retried when file size or mtime
  changes. Both `serve` and `tray --serve` bind the dashboard before the first
  session scan; usage appears when the first background poll completes.
- Sources for the rest: `ROADMAP.md`, `archive/*/MANIFEST.md`, the `STATE.md`
  log, `CHARTER.md` Vision, `intent/INTENT.md` Summary, `LESSONS.md`, task
  files, `review/FINAL.md`, the verify ledger, and `next/STATE.md`.

`#plugin` and `#folders` open settings directly; the OpenGSD Path button and Back
return to the board. Refresh preserves page scroll, the open Settings menu and
focus. Connection status changes to Offline after a failed status request; the
last received data remains visible with an explicit offline label. The
dashboard advances no pipeline phases; explicit Path settings saves use the
configuration helper described below.

## Path settings

Open **Settings → Path settings** (`#config`) to edit user defaults or a watched
project's shipping mode, future review-panel preference, and model/effort choices.
Sources and lock reasons are shown. Save changes individually; Reset removes that
scope's override. Watched folders and appearance retain their existing controls.

User defaults require the daemon's plugin source checkout; project settings need
an updated selected runtime. Missing support shows an update message. Settings
never fetch, install, or upgrade automatically.

`GET /api/path-config?scope=user` (or `scope=project&root=<watched-root>`) reads
settings. Same-origin JSON `POST /api/path-config` accepts `scope`, project `root`,
`action` (`set` or `reset`), `key`, and string `value` for set. Unknown fields and
unwatched project roots are rejected. See [Path settings](../skills/gsd-path/references/config.md)
for supported keys, precedence, and when changes apply.

## Plugin lifecycle

The daemon manages the gsd-path **skill plugin** itself (this is separate
from `install`/`uninstall`, which manage the daemon): install, update, and
uninstall, both globally (per-host skill roots) and per-project.

**Source.** The skills are also available through
[`@opengsd/gsd-path` on npm](https://www.npmjs.com/package/@opengsd/gsd-path).
The daemon's plugin manager uses a git clone, which it keeps at `~/.gsd-path/src`
(`https://github.com/open-gsd/gsd-path.git`, override with the `plugin_repo`
key in `daemon.json`) and runs its `scripts/install.py` for every
install/update. Background source refresh does `git fetch origin main` +
`git pull --ff-only` at most once per 24h, cached in
`~/.gsd-path/update-check.json` (last-fetch timestamp + last-known latest
version from the clone's `package.json`). Background refresh failures retain
the cached state. Explicit global updates and project updates from a clean source
checkout bypass this cache period and stop if source refresh fails. When the
source checkout has local changes, project Update uses that local build without
fetching or merging and displays a source notice. It never discards those edits.
Project updates invoke `--runtime-upgrade`, or `--runtime-migrate` for legacy
runtime directories; see
[project runtime versions](../DOCS.md#project-runtime-versions) for version
selection and legacy migration, and [Dashboard feedback](../UPDATE.md#update-the-project-runtime-and-guard-hooks)
for the displayed controls and results. Every installer operation (argv, exit code,
output tail) is appended to `~/.gsd-path/logs/plugin.log`.

**Repository access.** The default `open-gsd/gsd-path` repository is public.
If you configure a private `plugin_repo`, cloning needs credentials on the
machine. `ensure_source` tries HTTPS first, then SSH on failure. Use
`gh auth login` or an SSH key for access to a private source.

**CLI:**

```bash
gsd-path-daemon plugin status [--json]                 # detected installs + update state (no clone, no fetch)
gsd-path-daemon plugin install --global [--host kimi --host claude]
gsd-path-daemon plugin install --project PATH [--local HOST ...] [--hooks]
gsd-path-daemon plugin update [--global | --project PATH] [--dry-run]
gsd-path-daemon plugin uninstall (--global [--host H ...] | --project PATH) [--dry-run] [--yes]
```

`plugin status` and the update check work offline from runtime declarations, legacy VERSION stamps, and
the cache — they never clone. Uninstall without `--yes` prints the removal
plan and stops; `--yes` is required to apply anything.

**API** (all POST bodies are JSON; operations run in a worker thread under
one global op-lock — a second concurrent operation gets
`409 {"error": "operation in progress"}`):

- `GET /status` — now includes a top-level `plugin` key
  (`{latest, update_available, hosts}`) built cheaply from VERSION probes
  and the cache only — no git fetch.
- `GET /api/plugin/status` — full detection: global hosts plus
  `projects: [...]` for every watched root. Each project's `runtime_version`
  comes from its runtime declaration, falling back to legacy
  `.gsd-path/runtime/VERSION`; unstamped runtimes report `null`.
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
- Project: project-local managed skill dirs; `.gsd-path/runtime.json` when it
  declares the managed schema (shared runtime versions are retained); legacy
  `.gsd-path/runtime/VERSION` when it contains a recognized version or `unknown`
  and is not a symlink; legacy `.gsd-path/runtime/*.py` and
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
`node scripts/install.mjs`, `python3 scripts/install.py`, or `npx @opengsd/gsd-path`
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
  (`{branch, head, dirty}`). `dirty` is Boolean or null; runtime changed-file
  lists become `false` when empty and `true` when nonempty.
- Runtime enrichment: `pending_answers`, `next_skill`, `handoff`. The project
  detail page displays the runtime handoff outcome and next action.
- `workflow`: `{state, label, reason?}` is the shared browser/tray presentation.
  State is `active`, `blocked`, `shipped`, or `unverified`. Only runtime
  integration proof permits `shipped`; an archive path alone does not. Older
  payloads without this field display **Unverified**.
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
- `history` — append events to `~/.gsd-path/history.jsonl` (both `serve` and the Python tray record changes after their startup scan)
  (override with `GSD_DAEMON_HISTORY`).

## Autostart (manual fallback)

`gsd-path-daemon install` registers autostart automatically; the recipes
below are only for hand-rolled setups.

### macOS LaunchAgent

`~/Library/LaunchAgents/org.gsd-path.daemon.plist` (the label the installer
uses — keep them identical so `uninstall` can clean up):

Use the plist emitted by the installer's preview instead of maintaining a
separate template. From a repository checkout:

```bash
GSD_DAEMON_PLATFORM=darwin PYTHONPATH=daemon python3 -m gsd_daemon install --dry-run --no-tray
```

Copy the XML shown for that LaunchAgent path (without the preview's `|`
prefixes), adjusting the Python executable and log paths for your setup.
Create the log directory before loading it. Keep the generated process type
and label; see [Install (one command)](#install-one-command) for their purpose.

Then `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/org.gsd-path.daemon.plist`
(or `launchctl load -w` on older macOS).

### Windows Startup folder

Create a shortcut in `shell:startup` (Win+R → `shell:startup`) with target:

```
"C:\Users\you\.gsd-path\venv\Scripts\pythonw.exe" -m gsd_daemon tray --serve
```

or run `gsd-path-daemon.exe tray --serve` from a PowerShell scheduled task at
logon.

## Project history and files

Open a project and choose **History & files**. The viewer lists Git-tracked and
non-ignored repository files plus `.project` records, including archived
milestones. UTF-8 text is shown in full. Markdown has Preview and Raw views;
HTML is escaped and images are represented by their alt text, without loading
remote resources. Relative document links open within the same project.

The Version selector and Git history show committed versions of the selected
path. Working tree shows current contents. Uncommitted older contents are not
retained, and history does not follow renames. Binary files, symlinks, hard
links, `.git` internals, and paths outside watched projects are rejected.
Secure working-tree reads currently require POSIX directory descriptors;
unsupported platforms report that limitation instead of using an unsafe fallback.

**Records & sources → Load full records** loads the full recorded pipeline
usage, verification ledger, daemon activity, and indexed host turns on demand.
Data coverage distinguishes available files, loaded records, invalid JSONL
lines, missing files, and unverified runtime state. Host turns are the records
currently indexed from Codex and Claude Code logs, not a guarantee that every
host log was parsed. The regular status snapshot still uses recent-record
windows; full records and files are fetched separately.

Read-only endpoints, restricted to watched roots and same-origin local requests:

- `GET /api/project-files?root=...&action=list`
- `GET /api/project-files?root=...&action=read&path=...` (optional full commit `revision`)
- `GET /api/project-files?root=...&action=history&path=...`
- `GET /api/project-data?root=...`

The Board and Milestones views use real watched-project state. Project detail
keeps its existing facts and usage tables, with tasks and evidence in expandable
sections. Settings groups Path settings, watched folders, and plugin management.
