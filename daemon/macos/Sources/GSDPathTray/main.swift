import AppKit

// Entry point. `--self-test [url]` never touches NSApplication so it works
// without a GUI session; anything else launches the menu-bar app.
let args = CommandLine.arguments
if let flagIndex = args.firstIndex(of: "--self-test") {
    let url = args.indices.contains(flagIndex + 1) ? args[flagIndex + 1] : "http://127.0.0.1:8765/status"
    exit(runSelfTest(urlString: url))
}

// Debug: `--dump-icon <dir>` renders the tray-icon states to PNGs and exits.
if let flagIndex = args.firstIndex(of: "--dump-icon") {
    let dir = args.indices.contains(flagIndex + 1) ? args[flagIndex + 1] : "."
    exit(dumpIcons(directory: dir))
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory) // menu-bar-only; LSUIElement reinforces this
app.run()
