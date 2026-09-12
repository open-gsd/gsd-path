import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let statusURL = URL(string: "http://127.0.0.1:8765/status")!
    private var statusItem: NSStatusItem!
    private var popover: NSPopover!
    private var pollTimer: Timer?
    private var online = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.image = makeRingIcon(fraction: 0, arcColor: nil)
            button.imagePosition = .imageLeft
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
            let aggregate = projects.reduce(Health.green) { worst, p in
                let h = p.health
                if worst == .red || h == .red { return .red }
                if worst == .yellow || h == .yellow { return .yellow }
                return worst
            }
            let active = projects.filter { !$0.isShipped }
            let done = active.reduce(0) { $0 + $1.done }
            let total = active.reduce(0) { $0 + $1.total }
            let fraction = total > 0 ? Double(done) / Double(total) : 0
            button.title = ""
            button.image = makeRingIcon(fraction: fraction, arcColor: healthColor(aggregate))
            vc.show(status: status)
        case .failure:
            online = false
            button.title = ""
            button.image = makeRingIcon(fraction: 0, arcColor: nil)
            vc.showOffline()
        }
    }
}

/// Progress-ring glyph drawn in code (no assets): a subtle full-circle track
/// plus a clockwise arc from 12 o'clock tinted by aggregate health. Offline
/// (arcColor == nil) draws just a hollow gray ring. The drawing handler
/// re-rasterizes per display scale, so it stays crisp at 2x.
func makeRingIcon(fraction: Double, arcColor: NSColor?) -> NSImage {
    let size = NSSize(width: 18, height: 18)
    let image = NSImage(size: size, flipped: false) { rect in
        let lineWidth: CGFloat = 2.5
        let ringRect = rect.insetBy(dx: lineWidth / 2 + 1, dy: lineWidth / 2 + 1)
        let center = NSPoint(x: ringRect.midX, y: ringRect.midY)
        let radius = min(ringRect.width, ringRect.height) / 2

        // Track ring: adapts to light/dark menu bars via labelColor alpha;
        // a plain hollow gray when offline.
        let track = NSBezierPath(ovalIn: ringRect)
        track.lineWidth = lineWidth
        if arcColor == nil {
            NSColor.systemGray.setStroke()
        } else {
            NSColor.labelColor.withAlphaComponent(0.3).setStroke()
        }
        track.stroke()

        // Progress arc, 12 o'clock clockwise.
        if let color = arcColor, fraction > 0 {
            color.setStroke()
            if fraction >= 1 {
                let full = NSBezierPath(ovalIn: ringRect)
                full.lineWidth = lineWidth
                full.stroke()
            } else {
                let arc = NSBezierPath()
                arc.lineWidth = lineWidth
                arc.lineCapStyle = .round
                arc.appendArc(withCenter: center, radius: radius,
                              startAngle: 90, endAngle: 90 - 360 * CGFloat(fraction),
                              clockwise: true)
                arc.stroke()
            }
        }
        return true
    }
    image.isTemplate = false
    return image
}

/// `--dump-icon <dir>` debug helper: renders the ring states to PNGs so the
/// icon can be eyeballed without launching the app.
func dumpIcons(directory: String) -> Int32 {
    let states: [(String, Double, NSColor?)] = [
        ("icon-green-60", 0.6, healthColor(.green)),
        ("icon-yellow-35", 0.35, healthColor(.yellow)),
        ("icon-red-80", 0.8, healthColor(.red)),
        ("icon-offline", 0, nil),
    ]
    for (name, fraction, color) in states {
        let image = makeRingIcon(fraction: fraction, arcColor: color)
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
