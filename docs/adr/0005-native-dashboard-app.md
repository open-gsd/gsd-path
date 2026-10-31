# One Tauri app is the dashboard on every OS

Status: proposed.

Users install GSD Path through `npx` flags, and the dashboard needs a Git
checkout and `python3 -m gsd_daemon install`. Only macOS has a native app
(`daemon/macos`, a Swift shell around the dashboard). Windows and Linux get a
`pystray` icon. Multi-repo adds more install state per project that nothing
shows.

**Decision:** one [Tauri 2](https://v2.tauri.app/) app in `daemon/app/` is the
dashboard on macOS, Windows, and Linux. It lets users manage installs, update
the plugin and the app, and see project stats.

- **Shell.** Tauri gives a tray icon, a window, and notifications. The window
  shows a React + Vite frontend that is bundled in the app and runs in the OS
  web view (WKWebView, WebView2, WebKitGTK), so one UI serves every OS and
  the setup and error screens work while no daemon runs (owner ruling
  2026-10-01; this replaces "the window shows the daemon's existing
  dashboard"). In the app, the frontend never calls the daemon directly: one Rust command
  sends each request to the daemon on `127.0.0.1`, so the daemon needs no
  CORS rule. The app starts the daemon when needed. On first launch, it uses the daemon's existing uninstall cleanup
  to retire the old LaunchAgent, Startup shortcut, systemd unit, and Swift app
  login item before replacing a daemon. It checks that each old registration is
  gone before enabling Tauri autostart and shows a manual fix if cleanup fails.
  It then checks the daemon version in `/status` before reuse. An older daemon,
  or one without a version, is stopped and replaced by an app-owned process. A
  current daemon stays running on quit; the app stops only a process it launched.
- **Backend.** The Python daemon stays the backend. The app creates
  `~/.gsd-path/venv` with the user's Python 3.9+ and installs the bundled
  daemon package into it, as `gsd_daemon install` does today. It does not
  freeze the daemon: projects need Python 3.9+ anyway, and the daemon runs
  `install.py` and each project's `status_runtime.py` with `sys.executable`,
  which is not a Python interpreter in a frozen binary. When Python or Git is
  missing, the app shows a static setup page with the fix, before any daemon
  starts. Each app build with changed daemon code bumps the daemon package
  version so the reuse check can detect the change.
- **One source of logic.** The app and dashboard show state and call the
  installer and the bundled helpers (`install.py`, `members.py`). They never
  copy a helper's rules. The existing copy of the guard-command check in
  `plugin.py` is debt to remove, not a pattern to follow.
- **Writes.** Every daemon write route accepts same-origin requests only,
  like `/api/path-config`. A daemon started with `--require-token` also
  requires a token header on every write. The token is in a file only the
  user can read; the Rust side adds it, so it never enters the web view. A
  browser page can then read from that daemon but not write: the dashboard
  opened in a browser is read-only, its write actions are refused, and the
  page tells the user to use the app. A daemon started without the flag
  behaves as before. The app never writes pipeline state. It can edit a
  project's `.env` files on request: values are masked, shown as a diff
  before save, and never logged. Every env route (list, reveal, save) is a
  POST that needs the token, so no GET returns env content. The env routes
  exist only on a daemon started with `--require-token`; a daemon without
  the flag refuses them with a reason. Multi-repo
  actions are adding a member, member hook install, and marker repair (owner
  ruling 2026-10-31; this replaces "joining a member stays in the router").
  `members.py add` owns every joining rule. A member row also changes the
  member's integration mode (`members.py set-integration`) and removes the
  member (`members.py remove`, after a confirm).
- **Updates.** The app updates through the Tauri updater from `latest.json`
  on the fixed `app-latest` GitHub pre-release. CI replaces that asset after
  each `app-v*` release. Tauri requires signed update artifacts; the key is a
  free keypair the owner holds, not OS code signing. The plugin updates through
  the daemon's existing plugin manager.
- **Signing.** Unsigned `app-v*` builds are GitHub pre-releases for testers only.
  macOS builds carry an ad-hoc signature, which Apple Silicon requires; users
  still approve the app once in Privacy & Security. Windows shows a SmartScreen
  warning. OS code signing is required before the first non-prerelease app
  release. Update 2026-10: `app-release.yml` signs macOS builds with a
  Developer ID certificate and notarizes them when the Apple secrets are set
  (see `docs/app-macos-signing-guide.md`); Windows signing is still open.

**Considered options:** Electron (same shape, much larger app); three native
shells (Swift, C#, GTK) with three codebases to keep equal; a frozen daemon
sidecar (no Python needed for the app, but Python is still needed for
projects, and child processes lose their interpreter); keeping the Swift app
beside the new one (two macOS apps).

**Consequences:** CI builds the app on macOS, Windows, and Linux and needs a
Rust toolchain and Node for the frontend build. The daemon's inline dashboard
is removed once the frontend matches it; the daemon then serves the built
frontend for "Open in browser". There the frontend uses same-origin `fetch`
with no token: reads always work, and writes work only on a daemon started
without `--require-token`. The Swift app in `daemon/macos` is removed once the new app
matches it. Removing autostart from `gsd_daemon install` means scripted installs
no longer start the daemon at login; the app becomes the only autostart path.
The npm package is unchanged; the installer and docs point to the app. The work
plan is [native-app-work.md](../native-app-work.md).
