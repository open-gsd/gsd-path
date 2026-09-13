# GSDPathTray — native macOS menu-bar app for the gsd-path daemon

Renders compact project rows in an `NSPopover` from the daemon's
`http://127.0.0.1:8765/status` JSON (polled every 5 s). The dropdown follows the selected menu-bar design and adapts to the native system appearance.

## Requirements

- macOS 12+
- Xcode Command Line Tools (`xcode-select --install`) — uses `swiftc`, no
  Xcode project or SPM package needed
- The daemon running: `pip install ./daemon` then `python3 -m gsd_daemon serve`

## Build

`gsd-path-daemon install` (see `../README.md`) runs this automatically —
it invokes `build.sh`, copies the result to `~/Applications/GSDPathTray.app`,
and registers it as a login item. Build by hand only for development:

```sh
./build.sh
```

Compiles the Swift sources (release), wraps the binary into
`build/GSDPathTray.app` with `LSUIElement = true` (menu-bar-only, no Dock
icon), and ad-hoc signs it. Idempotent; prints the resulting `.app` path.

## Run

```sh
open build/GSDPathTray.app
```

Click the menu-bar icon to open the dropdown. The icon uses an aggregate
progress ring and an attention badge; offline it becomes a gray ring. The
dropdown is a status board in the dashboard's Instrument palette: the last
update time, then projects under In progress (blocked first) and Shipped.

Each row is one button (click to open the project page) with the project name,
an 8-segment phase meter (red when blocked) and one detail line: milestone,
phase, wave, task progress, criteria met, the date the phase started and the
current milestone's cost and turns; shipped rows show the ship date and task
count from the archive manifest. The tooltip carries the milestone stack
(`M001 ✓  M002 ●  M003 ○`), the current goal and the health reason. Rows carry
no commands or actions. The fixed footer, outside the scrolling project list,
holds the daemon lifecycle row and an icon toolbar: open dashboard, plugin
settings, watched folders, rescan, Appearance (System / Light / Dark, light by
default, applied to the popover and the dashboard window) and quit. Each icon
has a tooltip and an accessibility name.

## Self-test (no GUI required)

```sh
./build/GSDPathTray.app/Contents/MacOS/GSDPathTray --self-test [url]
```

Fetches the status URL (default `http://127.0.0.1:8765/status`), prints one
line per project plus `OK`, exits 0. On any fetch/decode failure prints
`OFFLINE` and exits 1.

`stub_server.py` serves a static two-project fixture on 127.0.0.1:8765 for
manual testing when the real daemon is not running:

```sh
python3 stub_server.py
```

## UI acceptance checks

From the repository root, compile the real AppKit views with the test entry point:

```sh
swiftc -o /tmp/gsd-tray-ui-test $(rg --files daemon/macos/Sources/GSDPathTray | rg '\.swift$' | rg -v '/main.swift$') tests/daemon_tray_ui.swift
/tmp/gsd-tray-ui-test
```

Pass `--preview` to the test binary to inspect the real views using sample data
in a temporary window. Stop that test process when finished.

The dashboard browser test uses Orca's embedded browser and the real HTTP handler:

```sh
GSD_UI_TEST=1 python3 -m unittest discover -s tests -p test_daemon_board_ui.py
```
