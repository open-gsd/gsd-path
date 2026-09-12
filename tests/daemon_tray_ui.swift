import AppKit

@main
struct TrayUITest {
    static func main() throws {
        _ = NSApplication.shared
        NSApp.setActivationPolicy(.accessory)
        let data = Data("""
        {"projects":[
          {"root":"/sample/gsd","project":"GSD Path","milestone":"daemon","phase":"build","status":"active","branch":"gsd-path/M004","next_skill":"gsd-path-build","tasks_done":6,"tasks_total":9,"current_wave":2,
           "roadmap_milestones":[{"number":"M003","slug":"core","status":"shipped","archive":".project/archive/003-core"},{"number":"M004","slug":"daemon","status":"active"},{"number":"M005","slug":"notify","status":"pending"}]},
          {"root":"/sample/atlas'&tab=usage","project":"Atlas API","milestone":"api-v2","phase":"ship","status":"blocked","branch":"gsd-path/M002","health":"red","attention":[{"kind":"blocked","label":"ship blocked","ref":null}],
           "next_milestone":{"milestone":"api-v3","phase":"define","status":"pending"}},
          {"root":"/sample/notes","project":"Field Notes","milestone":"bootstrap","phase":"research","status":"active","branch":"gsd-path/M001"}
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
        // Milestone stack: done / here / ahead from ROADMAP.md, lookahead from next/STATE.md, number from the branch.
        require(labels().contains("M003 ✓  M004 ●  M005 ○"), "roadmap stack line")
        require(labels().contains("M002 ■  next ○"), "blocked stack with lookahead milestone")
        require(labels().contains("M001 ●"), "pre-plan project stack from branch")
        require(labels().contains("build · wave 2 · 6 of 9 tasks"), "here line with wave and tasks")
        require(labels().contains("research · no tasks yet"), "here line without tasks")
        require(labels().contains("Blocked") && labels().contains("In build"), "state pills")
        // A status board: no attention summary, next steps, copy or reveal actions.
        require(!buttons().contains { $0.title.contains("needs you") }, "no attention summary")
        require(!buttons().contains { $0.title == "Actions" }, "no actions menu")
        require(!buttons().contains { $0 is NSPopUpButton }, "no per-row menus")
        require(!labels().contains("ship blocked"), "no attention copy")
        require(buttons().contains { $0.title.contains("Field Notes") }, "pre-plan projects remain visible")
        require(buttons().contains { $0.title == "Plugin settings…" }, "plugin settings always available")
        require(buttons().contains { $0.title == "Watched folders…" }, "folder settings available")
        let scroll = descendants(vc.view).compactMap { $0 as? NSScrollView }.first!
        require(!descendants(scroll).contains { ($0 as? NSButton)?.title == "Open Dashboard" }, "dashboard stays outside scrolling content")
        let names = buttons().map(\.title)
        require(names.firstIndex(where: { $0.contains("Atlas API") })! < names.firstIndex(where: { $0.contains("Field Notes") })!
                && names.firstIndex(where: { $0.contains("Field Notes") })! < names.firstIndex(where: { $0.contains("GSD Path") })!, "blocked first, then active by name")
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
        print("PASS: milestone stacks, state pills, settings, rescan, links, empty and offline states")
    }
}
