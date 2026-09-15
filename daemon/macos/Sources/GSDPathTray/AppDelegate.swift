import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let statusURL = URL(string: "http://127.0.0.1:8765/status")!
    private var statusItem: NSStatusItem!
    private var popover: NSPopover!
    private var pollTimer: Timer?
    private var online = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        applyAppearance()
        statusItem = NSStatusBar.system.statusItem(withLength: 22)
        if let button = statusItem.button {
            button.image = makeBrandIcon(template: true)
            button.imagePosition = .imageOnly
            button.target = self
            button.action = #selector(statusItemClicked)
        }

        popover = NSPopover()
        popover.behavior = .transient
        popover.contentViewController = PopoverViewController(statusURL: statusURL) { [weak self] in
            self?.poll()
        }

        poll()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.poll()
        }
    }

    @objc private func statusItemClicked() {
        guard let button = statusItem.button else { return }
        // Option-click opens the dashboard window instead of the popover.
        if NSApp.currentEvent?.modifierFlags.contains(.option) == true {
            if popover.isShown { popover.performClose(nil) }
            DashboardWindowController.shared.show()
            return
        }
        if popover.isShown {
            popover.performClose(nil)
        } else {
            // Refresh immediately on open so the cards are never one poll stale.
            poll()
            popover.appearance = NSApp.appearance
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        }
    }

    func poll() {
        let url = statusURL
        fetchStatus(url: url) { [weak self] result in
            DispatchQueue.main.async {
                self?.apply(result)
            }
        }
    }

    private func apply(_ result: Result<StatusResponse, FetchError>) {
        guard let vc = popover.contentViewController as? PopoverViewController,
              let button = statusItem.button else { return }
        switch result {
        case .success(let status):
            online = true
            let projects = status.projects ?? []
            let badge = projects.contains { !$0.attentionItems.isEmpty }
            let description = "OpenGSD Path: \(projects.count) projects, \(projects.filter { !$0.attentionItems.isEmpty }.count) need attention"
            button.toolTip = description
            button.setAccessibilityLabel(description)
            button.title = ""
            button.appearsDisabled = false
            button.image = makeBrandIcon(attention: badge, template: true)
            vc.show(status: status)
        case .failure:
            online = false
            button.title = ""
            button.appearsDisabled = true
            button.image = makeBrandIcon(template: true)
            button.toolTip = "OpenGSD Path: daemon offline"
            button.setAccessibilityLabel("OpenGSD Path: daemon offline")
            vc.showOffline()
        }
    }
}

/// OpenGSD Path mark drawn in code (no assets): three forward chevrons.
/// Same 18×18 geometry as ICON.mark in the dashboard HTML and tray._make_image.
/// `flipped: true` so SVG y-down coordinates copy across. Menu-bar copies are
/// template images so they follow the menu-bar tint. Attention is a small
/// corner dot — filling a chevron made the 18pt glyph read as a fat `>>`.
func makeBrandIcon(color: NSColor = .labelColor, attention: Bool = false,
                   template: Bool = false) -> NSImage {
    let size = NSSize(width: 18, height: 18)
    let image = NSImage(size: size, flipped: true) { rect in
        let ink = template ? NSColor.black : color
        ink.setFill()
        ink.setStroke()
        func chevron(_ x: CGFloat) {
            let path = NSBezierPath()
            path.move(to: NSPoint(x: x, y: 4))
            path.line(to: NSPoint(x: x + 4, y: 9))
            path.line(to: NSPoint(x: x, y: 14))
            path.lineWidth = 1.5
            path.lineCapStyle = .round
            path.lineJoinStyle = .round
            path.stroke()
        }
        chevron(1.6)
        chevron(7.0)
        chevron(12.4)
        if attention {
            ink.setFill()
            NSBezierPath(ovalIn: NSRect(x: rect.maxX - 3.6, y: 0.4,
                                        width: 3.2, height: 3.2)).fill()
        }
        return true
    }
    image.isTemplate = template
    return image
}

/// `--dump-icon <dir>` debug helper: renders the mark states to PNGs so the
/// icon can be eyeballed without launching the app.
func dumpIcons(directory: String) -> Int32 {
    let states: [(String, Bool, Bool)] = [
        ("icon-tray", false, true),
        ("icon-attention", true, true),
        ("icon-brand", false, false),
    ]
    for (name, attention, template) in states {
        let image = makeBrandIcon(attention: attention, template: template)
        guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 36, pixelsHigh: 36,
                                         bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                         isPlanar: false, colorSpaceName: .deviceRGB,
                                         bytesPerRow: 0, bitsPerPixel: 0) else { return 1 }
        rep.size = NSSize(width: 18, height: 18)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        image.draw(in: NSRect(x: 0, y: 0, width: 18, height: 18))
        NSGraphicsContext.restoreGraphicsState()
        guard let data = rep.representation(using: .png, properties: [:]) else { return 1 }
        let path = (directory as NSString).appendingPathComponent("\(name).png")
        do {
            try data.write(to: URL(fileURLWithPath: path))
        } catch {
            print("dump-icons: \(error.localizedDescription)")
            return 1
        }
        print(path)
    }
    return 0
}
