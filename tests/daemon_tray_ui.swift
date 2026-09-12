import AppKit

@main
struct TrayUITest {
    static func main() throws {
        _ = NSApplication.shared
        NSApp.setActivationPolicy(.accessory)
        let data = Data("""
        {"projects":[
          {"root":"/sample/gsd","project":"GSD Path","milestone":"M004","phase":"build","status":"active","next_skill":"gsd-path-build","tasks_done":6,"tasks_total":9,"current_wave":2},
          {"root":"/sample/atlas'&tab=usage","project":"Atlas API","milestone":"M002","phase":"decide","status":"active","health":"amber","attention":[{"kind":"question","label":"API version strategy","ref":"A012"}]},
          {"root":"/sample/notes","project":"Field Notes","phase":"research","status":"active"}
        ]}
        """.utf8)
        let status = try JSONDecoder().decode(StatusResponse.self, from: data)
        var rescans = 0
        let vc = PopoverViewController(statusURL: URL(string: "http://127.0.0.1:8765/status")!) { rescans += 1 }
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 680),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.contentViewController = vc
        vc.show(status: status)
        vc.view.appearance = NSAppearance(named: .darkAqua)
        vc.view.display()
        guard let background = vc.view.layer?.backgroundColor,
              let rgb = NSColor(cgColor: background)?.usingColorSpace(.deviceRGB),
              abs(rgb.redComponent - 12.0 / 255) < 0.001 else {
            print("FAIL: Studio dark surface"); exit(1)
        }
        func descendants(_ view: NSView) -> [NSView] {
            [view] + view.subviews.flatMap(descendants)
        }
        func labels() -> [String] {
            descendants(vc.view).compactMap { ($0 as? NSTextField)?.stringValue }
        }
        func buttons() -> [NSButton] { descendants(vc.view).compactMap { $0 as? NSButton } }
        func require(_ condition: Bool, _ message: String) {
            if !condition { print("FAIL: \(message)"); exit(1) }
        }
        require(labels().contains("3 watched projects"), "compact watched-project count")
        require(labels().contains("Connected"), "connected state")
        require(buttons().contains { $0.title.contains("1 item needs you") }, "attention summary action")
        require(labels().contains("Needs input"), "question status pill")
        require(labels().contains("6 of 9 tasks done"), "real task progress")
        require(buttons().contains { $0.title.contains("Field Notes") }, "pre-plan projects remain visible")
        require(buttons().contains { $0.title == "Plugin settings…" }, "plugin settings always available")
        require(buttons().contains { $0.title == "Watched folders…" }, "folder settings available")
        require(!buttons().contains { $0.title == "View project ↗" }, "one opening action per project")
        require(buttons().contains { $0.title == "Actions" }, "secondary actions menu")
        let scroll = descendants(vc.view).compactMap { $0 as? NSScrollView }.first!
        require(!descendants(scroll).contains { ($0 as? NSButton)?.title == "Open Dashboard" }, "dashboard stays outside scrolling content")
        let copy = buttons().compactMap { $0 as? NSPopUpButton }.flatMap { $0.itemArray }.first { $0.title.contains("command") }!
        NSApp.sendAction(copy.action!, to: copy.target, from: copy)
        require(copy.title == "Copied" && NSPasteboard.general.string(forType: .string) == "$gsd-path-build", "copy feedback and command")
        let projectName = buttons().first { $0.title.contains("Atlas API") }!
        let rowActions = buttons().compactMap { $0 as? NSPopUpButton }.first!
        require(projectName.superview === rowActions.superview, "row actions share the project heading")
        let names = buttons().map(\.title)
        require(names.firstIndex(where: { $0.contains("Atlas API") })! < names.firstIndex(where: { $0.contains("GSD Path") })!, "attention project first")
        buttons().first { $0.title == "Rescan" }?.performClick(nil)
        require(rescans == 1, "rescan action invokes its callback")
        let link = projectDeepLink(base: URL(string: "http://localhost:8765")!, root: "/sample/atlas'&tab=usage")
        require(link.fragment?.contains("&tab=usage") == false, "root cannot inject a dashboard tab")
        if CommandLine.arguments.contains("--preview") {
            window.setContentSize(vc.preferredContentSize)
            window.center()
            window.orderFrontRegardless()
            vc.view.layoutSubtreeIfNeeded()
            window.display()
            NSApp.activate(ignoringOtherApps: true)
            print("Preview PID: \(ProcessInfo.processInfo.processIdentifier)")
            NSApp.run()
        }
        vc.show(status: StatusResponse(projects: []))
        require(labels().contains { $0.contains("No projects") }, "empty state")
        vc.showOffline()
        require(labels().contains("Offline"), "offline state clears live status")
        require(!labels().contains("Connected"), "no stale connected status")
        buttons().first { $0.title == "Retry" }?.performClick(nil)
        require(rescans == 2, "offline retry")
        print("PASS: tray rows, attention, settings, rescan, links, empty and offline states")
    }
}
