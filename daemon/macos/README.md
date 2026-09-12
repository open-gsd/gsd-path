# GSDPathTray — native macOS menu-bar app for the gsd-path daemon

Renders per-project progress cards in an `NSPopover` from the daemon's
`http://127.0.0.1:8765/status` JSON (polled every 5 s). Layout follows
Variant B of `../prototype-ui.html`.

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

Click the menu-bar icon to open the popover. The icon dot shows aggregate
health (red = any blocked project, yellow = pending answers or dirty git,
green = clean, gray = daemon offline); the title shows `<done>/<total>`
task counts across non-shipped projects. Card actions: Reveal in Finder,
copy next-skill invocation (`$gsd-path-…`), open the dashboard
(`http://localhost:8765`). Footer: Open Dashboard, Rescan, Quit.

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
