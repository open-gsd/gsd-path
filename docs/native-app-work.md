# Native dashboard app — work plan

Design: [ADR 0005](adr/0005-native-dashboard-app.md). Screens:
[design handoff](design/native-app/README.md).

## Contract

A user downloads one app for macOS, Windows, or Linux. From it they can:

- see which hosts have GSD Path skills, at which version, and install or
  update them;
- see each watched project's runtime version, guard hooks, and multi-repo
  member health, and install, update, or repair them;
- update the plugin and the app itself;
- see project progress and usage as charts;
- change monitoring, price, and Path settings, and edit a project's `.env`
  files.

No `npx` flags are needed for these tasks. The CLI installer stays for scripts.
Background monitoring stays read-only; only explicit user actions write.
Install, update, and repair actions write through the existing installer and
helpers. The daemon itself writes two more things on request: its `daemon.json`
config and a project's `.env` files.

## Slices

| Slice | Contract |
|---|---|
| A0 Same-origin writes | Every daemon POST route (`/api/plugin/*`, `/api/config/parents`, `/api/refresh`) refuses a foreign Host, a cross-site Origin, and a non-JSON body, like `/api/path-config`. Update the dashboard's bodyless `/api/refresh` POST to send JSON. Tracked as its own task; it lands before any app build is published. |
| A0b Local API token | `gsd_daemon serve --require-token` creates or reads `~/.gsd-path/app/api-token`, readable by the user only. Every POST then needs the `X-GSD-Path-Token` header. A daemon started without the flag behaves as before. On a daemon started with the flag, the inline dashboard opened in a browser is read-only: it has no token, its write actions are refused, and the page tells the user to use the app. The token never enters a web view. Lands before any app build is published. |
| A1a Launch check | `gsd_daemon launch` prints one JSON object for the app: problems with their fix (Python 3.9+, Git, and as optional items GitHub CLI and sign-in, Windows long paths, Git Bash, Linux `python3-venv`), legacy autostart state, and what to do with the port (start, reuse, replace). It creates or reuses `~/.gsd-path/venv` and installs the bundled daemon package. Before replacing any daemon, it uses existing `gsd_daemon uninstall` cleanup to retire the old LaunchAgent, Startup shortcut, systemd unit, and Swift login item, and checks each registration is gone, regardless of the uninstall exit status. `/status` carries the daemon version; bump the package version whenever daemon code changes in an app build. A daemon older than the bundled one, or without a version, is stopped and replaced; otherwise it is reused. |
| A1b Shell | Tauri 2 project in `daemon/app/` with a React + Vite frontend. Rust runs the launch check, starts the daemon it owns with `--require-token`, and stops only a process it launched; a reused daemon keeps running on quit. One Rust command sends frontend requests to the daemon and adds the token. Screens: Requirements (setup step 1), First launch (migration; if a registration remains, show the manual fix and do not enable app autostart), and the Python missing, port in use, and monitor stopped states. After the daemon starts, A1b shows only these screens; the board comes in A1c. Tray icon, single instance, and launch at login through Tauri autostart. |
| A1c Dashboard parity | The frontend shows what the inline dashboard and the Swift app show today, read-only: project board, project page with history, files, and records, and the tray popover (project count and attention count, Open dashboard, Open in browser, Start, Stop, Restart, Quit, update notice). "Open in browser" opens the read-only dashboard from A0b. |
| A2 Builds | CI builds the app on macOS (arm64 and x64), Windows, and Linux, and attaches `.dmg`, `.msi`, `.deb`, and AppImage files to a GitHub pre-release tagged `app-v<version>` for testers. macOS signing: see [the signing guide](app-macos-signing-guide.md). The Windows installer bootstraps WebView2. OS code signing is required before the first non-prerelease app release. `ci.yml` runs the frontend and Rust tests. |
| A3 Self-update | The Tauri updater reads `latest.json` from the fixed `app-latest` GitHub pre-release at `https://github.com/open-gsd/gsd-path/releases/download/app-latest/latest.json`. CI replaces that asset after each `app-v*` release and signs update artifacts with the owner's updater key, stored as a repository secret. The app checks on launch and from Settings → Updates, and asks before installing. |
| A4a Release source | The plugin manager installs skills from the npm registry in place of a clone of `main`: it lists versions and dist-tags, downloads the release tarball, checks its sha512 against `dist.integrity`, and runs that release's `install.py`. This gives A4 its "latest" and the release picker. |
| A4 Install view | Skills page: hosts × installed skill version × latest, with Preview (dry run), Install, Update, and Uninstall; hosts found on this computer are detected. Per project: runtime version, guard hooks, health check, and their actions. For a coordinator with `.project/MEMBERS.md`: each member's marker, member hooks, and `origin/main`, with **Install hooks** (`install.py --member-of`) and **Repair** (`members.py repair`). Settings → Updates lists app, skills, and runtime updates in one place. Setup steps Agents, Skills, and Watch folders. Each failed check shows the exact fix. All data comes from installer and helper output; the daemon adds no rule of its own. |
| A4c Settings | Settings pages for Path settings (existing `/api/path-config`), Monitoring (watched and excluded folders, scan depth, refresh interval, notifications, activity history), Usage and prices (model prices, session folders), and App (launch at login, appearance, run setup again, open logs, copy a diagnostics report). The daemon reads and writes `daemon.json` through one config route. |
| A4d Environment | Per project, edit `.env`, `.env.local`, `.env.development`, and `.env.production`. The daemon masks values, reveals one key on request, shows a diff before save, and rewrites only the chosen file. Every env route (list, reveal, save) is a POST that needs the token and passes the A0 same-origin and JSON checks; no GET route returns env content. The env routes exist only on a daemon started with `--require-token`; a daemon without the flag refuses each of them with a reason. On a reused daemon without the flag, the Environment page shows that reason and offers **Restart monitor**, which replaces the daemon with an app-owned one that has the token. Values never reach logs, history, or the diagnostics report. The Jev toggle writes `GSD_PATH_JEV=1`. |
| A5 Stats | Charts from data the daemon already records: tokens and cost over time, time per phase, task throughput per wave, verify pass and fail history. Missing data shows as missing, never as zero. |
| A6 Retire old UI | Remove `daemon/macos`, the inline dashboard in `serve.py`, and the autostart code in `gsd_daemon install` that the app replaces. The daemon serves the built frontend for "Open in browser". The frontend API client has two transports: the Rust command in the app, and same-origin `fetch` with no token when the daemon serves the frontend to a browser; A6 builds the second one. In a browser, reads always work. Writes work only on a daemon without the flag; on a daemon started with `--require-token` they are refused and the page tells the user to use the app, as in A0b. Keep the legacy uninstall cleanup used by A1a. README, `daemon/README.md`, and the npm installer's final message point to the app download. |
| Later: A4b Add project | Find Git repositories without Path and set them up from the app; setup steps Add project and Start /path; Open in agent. Not built until the owner rules it in. |
| Later: A7 Remove everything | Plan-first removal of skills, hooks, venv, and autostart. Not built until the owner rules it in. |

A0, A0b, and A1a come first and do not depend on each other. A1b needs A0b
and A1a; A1c needs A1b. A1a retires old autostart before A2 publishes an app
build. A3 needs A2. A4 needs A1c and A4a. A4c, A4d, and A5 need only A1c and
can run in parallel. A6 comes last. Until A4b lands, setup has four steps.

## Proof

- A0: daemon tests send a cross-site Origin, a foreign Host, and a text/plain
  body to each write route and see a refusal with no installer call; a
  same-origin JSON request still works. The dashboard sends a JSON body and
  content type to `/api/refresh`, and refresh still succeeds.
- A0b: with `--require-token`, a same-origin JSON POST without the header, or
  with a wrong token, is refused with no installer call; the same request with
  the token works. Without the flag, behavior does not change. With the flag,
  each write action of the inline dashboard in a browser is refused and the
  page tells the user to use the app; the page still shows status.
- A1 (A1a and A1b): on each OS, a first run with no Python shows the setup page and starts
  no daemon; a first run with Python starts the daemon and shows the A1b
  screens with no error state; quitting stops the process the app started. Upgrade an old daemon
  install on each OS, including the Swift app on macOS: old startup entries
  are gone before daemon replacement, and only the new app starts at login.
  Simulate failed cleanup and see the manual fix with no app autostart. Build
  two apps with distinct daemon versions: the newer app replaces the older
  daemon. A pre-A0 daemon without a version is also replaced; a current daemon
  is reused and keeps running on quit.
- A1c: on each OS, a first run with Python shows the dashboard. With a sample
  `/status`, the board, project page, and tray popover show the same projects,
  phases, attention items, and usage as the inline dashboard. "Open in
  browser" opens the read-only dashboard.
- A2: the release workflow produces all listed files, and each installs and
  launches on a clean machine or VM for that OS. Unsigned builds are available
  only through pre-releases; the first non-prerelease build has OS signing.
- A3: after a newer npm `v*` release exists, an app at N updates to N+1
  through `app-latest`; an update with a bad signature is refused.
- A4a: a release installs from the registry tarball; a tarball whose sha512
  does not match is refused and nothing is installed.
- A4: a two-repo fixture with one member missing hooks shows that member as
  unguarded; **Install hooks** fixes it; a moved coordinator shows a stale
  marker and **Repair** fixes it.
- A4c: a change to each setting is in `daemon.json` after save and applies on
  the next scan; the diagnostics report holds no env value and no token.
- A4d: after save, the file differs only in the changed keys; a dry run writes
  nothing; a secret value is in no log and no report. An env list, reveal, or
  save request without the token is refused, and no GET route returns env
  content. A daemon without the flag refuses each env route with a reason; on
  a reused daemon without the flag, the Environment page shows the reason, and
  **Restart monitor** starts an app-owned daemon on which the editor works.
- A5: a sample project renders every chart; a project without a usage ledger
  shows the missing state.
- A6: after retirement, install and launch the new app; "Open in browser"
  shows the same frontend, and it reads status. In a browser on a daemon
  without the flag, a write works; on a daemon started with `--require-token`,
  a write is refused and the page tells the user to use the app. Run
  `gsd_daemon install` and confirm it no longer registers autostart. Separately
  review active docs and install messages for correct app download and startup
  instructions.

## Decisions

- Shell: Tauri 2 (owner ruling 2026-09-29).
- The Swift app is replaced once the new app matches it (owner ruling
  2026-09-29).
- Unsigned `app-v*` builds are GitHub pre-releases for testers only; OS code
  signing is required before the first non-prerelease app release (owner
  ruling 2026-09-29).
- Remove autostart from `gsd_daemon install` in A6. Scripted installs lose
  startup behavior; the app becomes the only autostart path (owner ruling
  2026-09-29).
- Check `/status` before reuse: replace a daemon older than the bundled version
  or missing a version; reuse a daemon at least as new and leave it running on
  quit (owner ruling 2026-09-29).
- Retire old autostart on first app launch before daemon replacement, and bump
  the bundled daemon package version when its code changes (owner ruling
  2026-09-29).
- App updates use the fixed `app-latest` GitHub pre-release asset
  `https://github.com/open-gsd/gsd-path/releases/download/app-latest/latest.json`;
  CI replaces it on each `app-v*` release (owner ruling 2026-09-29).
- The daemon runs from a venv, not a frozen binary; see the ADR.
- The app has its own version and `app-v*` release tags, separate from the
  npm package (owner ruling 2026-09-29). The npm release workflow triggers
  on `v*` tags only, so `app-v*` tags never publish to npm.
- Linux ships `.deb` and AppImage only (owner ruling 2026-09-29).
- The frontend is a React + Vite app bundled in the Tauri app, not the
  daemon's inline dashboard (owner ruling 2026-10-01).
- The Environment editor is built with the contract in the design handoff
  (owner ruling 2026-10-01).
- On a daemon started with `--require-token`, the dashboard in a browser is
  read-only and tells the user to use the app; the token never enters a web
  view (owner ruling 2026-10-01).
- Every env route is a token-gated POST; no GET returns env content (owner
  ruling 2026-10-01).
- Env routes exist only on a daemon started with `--require-token` (owner
  ruling 2026-10-01).
- The frontend API client has two transports: the Rust command in the app,
  and same-origin `fetch` with no token in a browser (owner ruling
  2026-10-01).
- A4a and A0b are in scope. A4b and A7 stay out until the owner rules them in
  (2026-10-01).

## Open questions

- A1: How will the app compare the running daemon version before changing the
  shared venv and ensure it never downgrades a newer installed package? The
  installer uses `pip install --upgrade`, which can replace it.
- A1: How will the app identify a process on the port as a GSD Path daemon
  before stopping it, and what happens when another service holds the port?
- A1b: the "Install page" URL for each agent, and the exact one-click fix
  commands on the Requirements step. Until given, the app shows the command
  with Copy and opens the official page.
- A1b: the Linux setup screen is not drawn in the handoff.

## Out of scope

- Advancing any pipeline phase from the app.
- A mobile or web-hosted dashboard.
