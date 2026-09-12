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
dropdown is a status board: connection state, watched-project count, and one
row per project ordered blocked, then in progress, then shipped.

Each row shows the project name (click to open its dashboard card), a state
pill (Blocked, In <phase>, Shipped), the milestone stack on one line —
`M001 ✓  M002 ●  M003 ○` for done / here / ahead, ■ when blocked — and a
here line with phase, wave and task progress. Rows carry no commands or
actions. The fixed footer keeps dashboard, plugin, watched-folder, daemon
lifecycle, rescan, and quit controls outside the scrolling project list.

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
