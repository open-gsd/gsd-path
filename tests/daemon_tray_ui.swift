import AppKit

@main
struct TrayUITest {
    static func main() throws {
        _ = NSApplication.shared
        NSApp.setActivationPolicy(.accessory)
        let data = Data("""
        {"projects":[
          {"root":"/sample/gsd","project":"GSD Path","milestone":"daemon","phase":"build","status":"active","branch":"gsd-path/M004","next_skill":"gsd-path-build","tasks_done":6,"tasks_total":9,"current_wave":2,
           "roadmap_milestones":[{"number":"M003","slug":"core","status":"shipped","archive":".project/archive/003-core","manifest":{"shipped":"2026-09-06","tasks_total":12}},{"number":"M004","slug":"daemon","status":"active","goal":"Native tray and dashboard for the daemon."},{"number":"M005","slug":"notify","status":"pending"}],
           "criteria":[{"id":"SC1","verdict":"met"},{"id":"SC2","verdict":"met"},{"id":"SC3","verdict":"not-met"}],
           "phase_log":[{"phase":"plan","date":"2026-09-09"},{"phase":"build","date":"2026-09-10"}],
           "spend":{"turns":90,"cost":26.1,"milestones":{"M003":{"turns":6,"tokens":1000,"cost":1.5},"M004":{"turns":84,"tokens":14100000,"cost":24.6}}}},
          {"root":"/sample/atlas'&tab=usage","project":"Atlas API","milestone":"api-v2","phase":"ship","status":"blocked","branch":"gsd-path/M002","health":"red","attention":[{"kind":"blocked","label":"ship blocked","ref":null}],
           "next_milestone":{"milestone":"api-v3","phase":"define","status":"pending"}},
          {"root":"/sample/notes","project":"Field Notes","milestone":"bootstrap","phase":"research","status":"active","branch":"gsd-path/M001"},
          {"root":"/sample/done","project":"Done Thing","milestone":"graph","phase":"shipped","status":"shipped","archive":".project/archive/001-graph",
           "roadmap_milestones":[{"number":"M001","slug":"graph","status":"shipped","archive":".project/archive/001-graph","manifest":{"shipped":"2026-09-01","tasks_total":4}}]}
        ]}
        """.utf8)
        let status = try JSONDecoder().decode(StatusResponse.self, from: data)
        UserDefaults.standard.removeObject(forKey: "appearance")
        defer { UserDefaults.standard.removeObject(forKey: "appearance") }
        var rescans = 0
        let vc = PopoverViewController(statusURL: URL(string: "http://127.0.0.1:8765/status")!) { rescans += 1 }
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 680),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.contentViewController = vc
        vc.show(status: status)
        vc.view.appearance = NSAppearance(named: .darkAqua)
        vc.view.display()
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
        require(labels().contains("OpenGSD Path") && labels().contains("Connected"), "header with connection state")
        require(labels().contains("In progress") && labels().contains("Shipped"), "in progress and shipped captions")
        let rows = descendants(vc.view).compactMap { $0 as? ProjectRowView }
        // Board order: blocked first, then active by name, then shipped.
        require(rows.map(\.name.stringValue) == ["Atlas API", "Field Notes", "GSD Path", "Done Thing"], "row order")
        require(rows.map(\.detail.stringValue) == [
            "M002 · Blocked · ship · no tasks yet",
            "M001 · research · no tasks yet",
            "M004 · build · wave 2 · 6 of 9 tasks · 2/3 criteria · since 2026-09-10 · $24.60 · 84 turns",
            "M001 shipped 2026-09-01 · 4 tasks",
        ], "detail lines: milestone, phase, wave, tasks, criteria, since date, cost and turns; shipped date and tasks")
        let meter: (ProjectRowView) -> String = { row in
            row.meter.segments.map { $0 == .done ? "d" : $0 == .now ? "n" : "-" }.joined()
        }
        require(rows.map(meter) == ["dddddddn", "ddn-----", "ddddddn-", "dddddddd"], "phase meters in canonical phase order")
        require(rows[2].toolTip == "M003 ✓  M004 ●  M005 ○\nNative tray and dashboard for the daemon.", "stack and goal tooltip")
        require(rows[0].toolTip == "M002 ■  next ○\nship blocked", "blocked stack, lookahead milestone and health reason")
        require(rows[2].accessibilityLabel()?.hasPrefix("GSD Path, In build, M004 · build") == true, "row accessibility label")
        rows[2].hovered = true
        var nativeSelection = false
        rows[2].effectiveAppearance.performAsCurrentDrawingAppearance {
            nativeSelection = rows[2].layer?.backgroundColor == NSColor.selectedContentBackgroundColor.cgColor
        }
        require(nativeSelection && rows[2].name.textColor == .alternateSelectedControlTextColor && rows[2].meter.highlighted,
                "hover uses the native selection colors")
        rows[2].hovered = false
        require(rows[2].name.textColor == .labelColor && rows[2].detail.textColor == .secondaryLabelColor, "hover clears to native label colors")
        // A status board: no attention summary, next steps, copy or reveal actions.
        require(!buttons().contains { $0.title.contains("needs you") }, "no attention summary")
        require(!buttons().contains { $0.title == "Actions" }, "no actions menu")
        require(!buttons().contains { $0 is NSPopUpButton }, "no per-row menus")
        require(!labels().contains("ship blocked"), "no attention copy")
        let icons = buttons().compactMap { $0 as? IconButton }
        require(icons.map { $0.toolTip ?? "" } == ["Open dashboard", "Plugin settings", "Watched folders", "Rescan", "Quit"], "footer icon buttons")
        require(icons.allSatisfy { $0.image != nil && $0.accessibilityLabel() == $0.toolTip }, "icons have symbols and accessibility names")
        require(descendants(vc.view).compactMap { $0 as? DaemonRowView }.first!.fittingSize.height == 24, "daemon row is sized before its status arrives")
        // Appearance: light by default; the choice is stored and applied app-wide.
        let appearance = descendants(vc.view).compactMap { $0 as? NSSegmentedControl }.first!
        require(appearance.selectedSegment == 1 && appearanceChoice == "light", "light appearance by default")
        appearance.selectedSegment = 2
        _ = appearance.sendAction(appearance.action, to: appearance.target)
        require(UserDefaults.standard.string(forKey: "appearance") == "dark" && NSApp.appearance?.name == .darkAqua, "dark appearance applied")
        require(window.appearance?.name == .darkAqua, "open windows (the popover's included) take the choice")
        appearance.selectedSegment = 0
        _ = appearance.sendAction(appearance.action, to: appearance.target)
        require(NSApp.appearance == nil && window.appearance == nil, "system appearance follows macOS")
        require(appearance.toolTip(forSegment: 1) == "Appearance: Light" && appearance.image(forSegment: 1) != nil, "appearance icons with tooltips")
        let themed = themedDashboardURL(projectDeepLink(base: URL(string: "http://localhost:8765")!, root: "/sample/gsd"), choice: "dark")
        require(themed.absoluteString == "http://localhost:8765?theme=dark#project=%2Fsample%2Fgsd", "dashboard link carries the appearance")
        let scroll = descendants(vc.view).compactMap { $0 as? NSScrollView }.first!
        require(!descendants(scroll).contains { $0 is IconButton }, "footer stays outside scrolling content")
        buttons().first { $0.toolTip == "Rescan" }?.performClick(nil)
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
        print("PASS: rows, detail lines, phase meters, hover, menu items, rescan, links, empty and offline states")
    }
}
