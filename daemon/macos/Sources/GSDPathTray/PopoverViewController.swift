import AppKit

// Instrument palette, shared with the dashboard CSS in daemon/gsd_daemon/serve.py. Keep both in sync.
func paletteColor(light: Int, dark: Int) -> NSColor {
    NSColor(name: nil) { appearance in
        let value = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? dark : light
        return NSColor(srgbRed: CGFloat((value >> 16) & 255) / 255,
                       green: CGFloat((value >> 8) & 255) / 255,
                       blue: CGFloat(value & 255) / 255, alpha: 1)
    }
}
let paletteText = paletteColor(light: 0x1a1d22, dark: 0xe9ebee)
let paletteDim = paletteColor(light: 0x595e64, dark: 0xa7abb1)
let paletteFaint = paletteColor(light: 0x71757a, dark: 0x82878c)
let paletteDone = paletteColor(light: 0x51565c, dark: 0xa0a5ab)
let paletteSegment = paletteColor(light: 0xe0e3e6, dark: 0x2b2e32)
let paletteAccent = paletteColor(light: 0x008f83, dark: 0x3dbbae)
let paletteOnAccent = paletteColor(light: 0xffffff, dark: 0x101214)
let paletteDanger = paletteColor(light: 0xc9302d, dark: 0xef675c)
let paletteWarn = paletteColor(light: 0x8d5e00, dark: 0xe4ac59)

/// Appearance shared by the popover and the dashboard window: "system", "light" (default) or "dark".
let appearanceChoices = ["system", "light", "dark"]
var appearanceChoice: String {
    get { UserDefaults.standard.string(forKey: "appearance").flatMap { appearanceChoices.contains($0) ? $0 : nil } ?? "light" }
    set { UserDefaults.standard.set(newValue, forKey: "appearance"); applyAppearance() }
}
func applyAppearance() {
    NSApp.appearance = appearanceChoice == "system" ? nil : NSAppearance(named: appearanceChoice == "dark" ? .darkAqua : .aqua)
}

final class PaletteSurface: NSView {
    override var wantsUpdateLayer: Bool { true }
    override func updateLayer() {
        effectiveAppearance.performAsCurrentDrawingAppearance {
            layer?.backgroundColor = paletteColor(light: 0xfbfcfd, dark: 0x101214).cgColor
        }
    }
    override func viewDidChangeEffectiveAppearance() { needsDisplay = true }
}

// MARK: - Small view building blocks

final class DotView: NSView {
    var color: NSColor = .systemGray { didSet { needsDisplay = true } }
    override func draw(_ dirtyRect: NSRect) {
        color.setFill()
        NSBezierPath(ovalIn: bounds.insetBy(dx: 1, dy: 1)).fill()
    }
}

func makeLabel(_ text: String, size: CGFloat, weight: NSFont.Weight = .regular,
               color: NSColor = paletteText) -> NSTextField {
    let f = NSTextField(labelWithString: text)
    f.font = .systemFont(ofSize: size, weight: weight)
    f.textColor = color
    f.lineBreakMode = .byTruncatingTail
    return f
}

func healthColor(_ h: Health) -> NSColor {
    switch h {
    case .green: return paletteAccent
    case .yellow: return paletteWarn
    case .red: return paletteDanger
    case .gray: return .systemGray
    }
}

/// Eight phase segments, as on the dashboard board: done, the current phase, then ahead.
final class PhaseMeterView: NSView {
    let segments: [StackKind]
    private let blocked: Bool
    var highlighted = false { didSet { needsDisplay = true } }
    init(_ segments: [StackKind], blocked: Bool) {
        self.segments = segments
        self.blocked = blocked
        super.init(frame: .zero)
        translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            widthAnchor.constraint(equalToConstant: CGFloat(segments.count) * 12 - 2),
            heightAnchor.constraint(equalToConstant: 8),
        ])
    }
    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }
    override func draw(_ dirtyRect: NSRect) {
        for (index, kind) in segments.enumerated() {
            let color: NSColor
            switch kind {
            case .done: color = highlighted ? paletteOnAccent : paletteDone
            case .now: color = highlighted ? paletteOnAccent : blocked ? paletteDanger : paletteAccent
            case .ahead: color = highlighted ? paletteOnAccent.withAlphaComponent(0.35) : paletteSegment
            }
            color.setFill()
            NSBezierPath(roundedRect: NSRect(x: CGFloat(index) * 12, y: 0, width: 10, height: 8), xRadius: 1.5, yRadius: 1.5).fill()
        }
    }
}

/// Borderless full-width button that highlights like a menu item while the pointer is over it.
class MenuRowButton: NSButton {
    var hovered = false { didSet { hoverChanged() } }
    init() {
        super.init(frame: .zero)
        isBordered = false
        setButtonType(.momentaryChange)
        wantsLayer = true
        layer?.cornerRadius = 6
    }
    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect], owner: self))
    }
    override func mouseEntered(with event: NSEvent) { hovered = true }
    override func mouseExited(with event: NSEvent) { hovered = false }
    func hoverChanged() {
        effectiveAppearance.performAsCurrentDrawingAppearance {
            layer?.backgroundColor = hovered ? paletteAccent.cgColor : NSColor.clear.cgColor
        }
    }
}

private final class InsetTitleCell: NSButtonCell {
    override func drawTitle(_ title: NSAttributedString, withFrame frame: NSRect, in controlView: NSView) -> NSRect {
        super.drawTitle(title, withFrame: frame.offsetBy(dx: 9, dy: 0), in: controlView)
    }
}

final class MenuItemButton: MenuRowButton {
    init(_ title: String, target: AnyObject, action: Selector) {
        super.init()
        let cell = InsetTitleCell(textCell: title)
        cell.isBordered = false
        cell.alignment = .left
        self.cell = cell
        setButtonType(.momentaryChange)
        self.title = title
        self.target = target
        self.action = action
        hoverChanged()
    }
    override var intrinsicContentSize: NSSize {
        NSSize(width: super.intrinsicContentSize.width + 18, height: 24)
    }
    override func hoverChanged() {
        super.hoverChanged()
        attributedTitle = NSAttributedString(string: title, attributes: [
            .font: NSFont.systemFont(ofSize: 13), .foregroundColor: hovered ? paletteOnAccent : paletteText,
        ])
    }
}

// MARK: - Popover content

final class PopoverViewController: NSViewController {
    private let statusURL: URL
    private let dashboardURL = URL(string: "http://localhost:8765")!
    private let pluginURL = URL(string: "http://localhost:8765/#plugin")!
    private let parentsURL = URL(string: "http://127.0.0.1:8765/api/config/parents")!
    private let stack = NSStackView()
    private let controls = NSStackView()
    private var onRescan: () -> Void = {}

    init(statusURL: URL, onRescan: @escaping () -> Void) {
        self.statusURL = statusURL
        self.onRescan = onRescan
        super.init(nibName: nil, bundle: nil)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    override func loadView() {
        let scroll = NSScrollView()
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.scrollerStyle = .overlay
        // The popover grows to its content; the list only scrolls past the screen height, and never bounces.
        scroll.verticalScrollElasticity = .none
        scroll.horizontalScrollElasticity = .none
        scroll.drawsBackground = false
        scroll.borderType = .noBorder

        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 1
        stack.edgeInsets = NSEdgeInsets(top: 6, left: 6, bottom: 4, right: 6)
        stack.translatesAutoresizingMaskIntoConstraints = false

        let doc = NSView()
        doc.translatesAutoresizingMaskIntoConstraints = false
        doc.addSubview(stack)
        scroll.documentView = doc

        let content = PaletteSurface()
        content.wantsLayer = true
        content.addSubview(scroll)
        controls.orientation = .vertical
        controls.alignment = .leading
        controls.spacing = 1
        controls.edgeInsets = NSEdgeInsets(top: 0, left: 6, bottom: 6, right: 6)
        controls.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(controls)
        scroll.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            scroll.topAnchor.constraint(equalTo: content.topAnchor),
            scroll.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            scroll.bottomAnchor.constraint(equalTo: controls.topAnchor),
            controls.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            controls.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            controls.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            stack.topAnchor.constraint(equalTo: doc.topAnchor),
            stack.leadingAnchor.constraint(equalTo: doc.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: doc.trailingAnchor),
            stack.bottomAnchor.constraint(equalTo: doc.bottomAnchor),
            stack.widthAnchor.constraint(equalTo: scroll.widthAnchor),
        ])
        view = content
    }

    // MARK: Rendering

    func showOffline() {
        rebuild {
            let title = makeLabel("GSD Path", size: 13, weight: .semibold)
            let msg = makeLabel("daemon not reachable on 127.0.0.1:8765", size: 12,
                                color: .secondaryLabelColor)
            let cmd = makeLabel("python3 -m gsd_daemon serve", size: 12)
            cmd.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
            cmd.isSelectable = true
            cmd.wantsLayer = true
            cmd.layer?.cornerRadius = 5
            cmd.layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor
            let hint = makeLabel("start the daemon, then:", size: 11, color: .tertiaryLabelColor)
            let retry = NSButton(title: "Retry", target: self, action: #selector(rescanPressed))
            retry.bezelStyle = .rounded
            let addFolder = NSButton(title: "Add Watched Folder…", target: self, action: #selector(addFolderPressed))
            addFolder.bezelStyle = .rounded
            addFolder.isEnabled = false
            let dash = NSButton(title: "Open Dashboard", target: self, action: #selector(dashboardPressed))
            dash.bezelStyle = .rounded
            let quit = NSButton(title: "Quit", target: self, action: #selector(quitPressed))
            quit.bezelStyle = .rounded
            let buttons = NSStackView(views: [retry, addFolder, dash, quit])
            buttons.orientation = .horizontal
            buttons.spacing = 8
            let daemonRow = DaemonRowView()
            daemonRow.onRescan = onRescan
            return [title, makeLabel("Offline", size: 12, color: paletteDanger), msg, hint, cmd, daemonRow, buttons].map { inset($0, top: 4) }
        }
    }

    func show(status: StatusResponse) {
        let projects = status.projects ?? []
        var views: [NSView] = []

        let icon = NSImageView(image: NSImage(systemSymbolName: "tablecells", accessibilityDescription: nil) ?? NSImage())
        icon.contentTintColor = paletteText
        let title = makeLabel("GSD Path", size: 13, weight: .semibold)
        let spacer = NSView()
        spacer.setContentHuggingPriority(.init(1), for: .horizontal)
        let dot = DotView()
        dot.color = paletteAccent
        dot.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([dot.widthAnchor.constraint(equalToConstant: 7), dot.heightAnchor.constraint(equalToConstant: 7)])
        let updated = makeLabel(generatedStamp(status.generated_at).map { "Updated \($0)" } ?? "Connected", size: 12, color: paletteDim)
        let header = NSStackView(views: [icon, title, spacer, dot, updated])
        header.spacing = 6
        header.edgeInsets = NSEdgeInsets(top: 4, left: 9, bottom: 6, right: 9)
        views.append(header)

        // Board order: blocked, then active, then shipped; name within each.
        let sorted = projects.sorted { a, b in
            if a.stateRank != b.stateRank { return a.stateRank < b.stateRank }
            return a.displayProject.localizedCaseInsensitiveCompare(b.displayProject) == .orderedAscending
        }
        for (caption, list) in [("In progress", sorted.filter { $0.projectState != "shipped" }),
                                ("Shipped", sorted.filter { $0.projectState == "shipped" })] where !list.isEmpty {
            views.append(inset(makeLabel(caption, size: 11, weight: .semibold, color: paletteFaint), top: 6))
            views += list.map { ProjectRowView(project: $0, dashboardURL: dashboardURL) }
        }
        if projects.isEmpty {
            views.append(inset(makeLabel("No projects in your watched folders.", size: 12, color: paletteDim), top: 6))
        }

        // Plugin update row, only when the daemon reports one.
        if let plugin = status.plugin, plugin.update_available == true, let latest = plugin.latest {
            views.append(MenuItemButton("GSD Path update available — v\(latest)", target: self, action: #selector(pluginPressed)))
        }

        let daemonRow = DaemonRowView()
        daemonRow.onRescan = onRescan
        let appearance = NSSegmentedControl(labels: ["System", "Light", "Dark"], trackingMode: .selectOne,
                                            target: self, action: #selector(appearanceChanged(_:)))
        appearance.controlSize = .small
        appearance.selectedSegment = appearanceChoices.firstIndex(of: appearanceChoice) ?? 1
        let appearanceSpacer = NSView()
        appearanceSpacer.setContentHuggingPriority(.init(1), for: .horizontal)
        let appearanceRow = NSStackView(views: [makeLabel("Appearance", size: 13), appearanceSpacer, appearance])
        appearanceRow.edgeInsets = NSEdgeInsets(top: 2, left: 9, bottom: 2, right: 9)
        let footerViews: [NSView] = [
            separator(),
            MenuItemButton("Open Dashboard", target: self, action: #selector(dashboardPressed)),
            MenuItemButton("Plugin settings…", target: self, action: #selector(pluginPressed)),
            MenuItemButton("Watched folders…", target: self, action: #selector(foldersPressed)),
            MenuItemButton("Rescan", target: self, action: #selector(rescanPressed)),
            inset(daemonRow, top: 4),
            appearanceRow,
            separator(),
            MenuItemButton("Quit", target: self, action: #selector(quitPressed)),
        ]
        rebuild(footer: footerViews) { views }
    }

    private func rebuild(footer: [NSView] = [], _ makeViews: () -> [NSView]) {
        for v in controls.arrangedSubviews { controls.removeArrangedSubview(v); v.removeFromSuperview() }
        for v in footer {
            controls.addArrangedSubview(v)
            v.widthAnchor.constraint(equalTo: controls.widthAnchor,
                                     constant: -(controls.edgeInsets.left + controls.edgeInsets.right)).isActive = true
        }
        for v in stack.arrangedSubviews { stack.removeArrangedSubview(v); v.removeFromSuperview() }
        for v in makeViews() {
            stack.addArrangedSubview(v)
            v.widthAnchor.constraint(equalTo: stack.widthAnchor,
                                     constant: -(stack.edgeInsets.left + stack.edgeInsets.right)).isActive = true
        }
        stack.layoutSubtreeIfNeeded()
        let contentHeight = stack.fittingSize.height + controls.fittingSize.height
        preferredContentSize = NSSize(width: 400, height: min(max(contentHeight, 120), NSScreen.main.map { $0.visibleFrame.height } ?? 600))
    }

    private func generatedStamp(_ iso: String?) -> String? {
        guard let iso = iso else { return nil }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = parser.date(from: iso) ?? {
            parser.formatOptions = [.withInternetDateTime]
            return parser.date(from: iso)
        }()
        guard let date = date else { return nil }
        let fmt = DateFormatter()
        fmt.dateFormat = "HH:mm:ss"
        return fmt.string(from: date)
    }

    @objc private func rescanPressed() { onRescan() }
    @objc private func appearanceChanged(_ sender: NSSegmentedControl) {
        appearanceChoice = appearanceChoices[max(0, sender.selectedSegment)]
    }
    @objc private func dashboardPressed() { DashboardWindowController.shared.show() }
    @objc private func pluginPressed() { DashboardWindowController.shared.show(pluginURL) }
    @objc private func foldersPressed() {
        DashboardWindowController.shared.show(URL(string: "http://localhost:8765/#folders")!)
    }

    @objc private func addFolderPressed() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.prompt = "Watch"
        panel.message = "All gsd-path projects beneath the chosen folder will be monitored."
        guard panel.runModal() == .OK, let chosen = panel.url else { return }
        postParentAction(url: parentsURL, action: "add", path: chosen.path) { [weak self] result in
            DispatchQueue.main.async {
                switch result {
                case .success:
                    self?.onRescan()
                case .failure(let error):
                    let alert = NSAlert()
                    alert.messageText = "Could not add watched folder"
                    alert.informativeText = describe(error)
                    alert.alertStyle = .warning
                    alert.runModal()
                }
            }
        }
    }
    @objc private func quitPressed() { NSApplication.shared.terminate(nil) }
}

private func separator() -> NSBox {
    let line = NSBox()
    line.boxType = .separator
    return line
}

/// Wraps a view with the tray's inner padding so text lines up with row titles.
private func inset(_ view: NSView, top: CGFloat = 0) -> NSStackView {
    let box = NSStackView(views: [view])
    box.edgeInsets = NSEdgeInsets(top: top, left: 9, bottom: 2, right: 9)
    return box
}

// MARK: - Project row: name, phase meter and one detail line

final class ProjectRowView: MenuRowButton {
    let project: ProjectStatus
    let meter: PhaseMeterView
    let name: NSTextField
    let detail: NSTextField
    private let dashboardURL: URL

    init(project p: ProjectStatus, dashboardURL: URL) {
        project = p
        self.dashboardURL = dashboardURL
        name = makeLabel(p.displayProject, size: 13, weight: .semibold)
        detail = makeLabel(p.trayDetail, size: 11.5, color: paletteDim)
        meter = PhaseMeterView(p.phaseMeter, blocked: p.projectState == "blocked")
        super.init()
        title = ""
        target = self
        action = #selector(openProject)
        name.setContentHuggingPriority(.defaultLow, for: .horizontal)
        name.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        detail.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let top = NSStackView(views: [name, meter])
        top.spacing = 12
        top.distribution = .fill
        let column = NSStackView(views: [top, detail])
        column.orientation = .vertical
        column.alignment = .leading
        column.spacing = 1
        column.edgeInsets = NSEdgeInsets(top: 5, left: 9, bottom: 5, right: 9)
        column.translatesAutoresizingMaskIntoConstraints = false
        addSubview(column)
        NSLayoutConstraint.activate([
            column.topAnchor.constraint(equalTo: topAnchor),
            column.leadingAnchor.constraint(equalTo: leadingAnchor),
            column.trailingAnchor.constraint(equalTo: trailingAnchor),
            column.bottomAnchor.constraint(equalTo: bottomAnchor),
            top.widthAnchor.constraint(equalTo: column.widthAnchor, constant: -18),
            detail.widthAnchor.constraint(lessThanOrEqualTo: column.widthAnchor, constant: -18),
        ])
        let health = p.attentionItems.compactMap(\.label).joined(separator: " · ")
        toolTip = [p.stackText, p.goalText, health.isEmpty ? nil : health].compactMap { $0 }.joined(separator: "\n")
        setAccessibilityLabel("\(p.displayProject), \(p.stateLabel), \(p.trayDetail)")
    }

    // The whole row is one control: labels never swallow the click.
    override func hitTest(_ point: NSPoint) -> NSView? { NSPointInRect(point, frame) ? self : nil }

    override func hoverChanged() {
        super.hoverChanged()
        name.textColor = hovered ? paletteOnAccent : paletteText
        detail.textColor = hovered ? paletteOnAccent : paletteDim
        meter.highlighted = hovered
    }

    @objc private func openProject() {
        DashboardWindowController.shared.show(projectDeepLink(base: dashboardURL, root: project.root))
    }
}

/// Dashboard deep link selecting a project by its (fragment-encoded) root.
func projectDeepLink(base: URL, root: String?) -> URL {
    guard let root = root else { return base }
    let safe = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
    let encoded = root.addingPercentEncoding(withAllowedCharacters: safe) ?? ""
    return URL(string: "\(base.absoluteString)#project=\(encoded)") ?? base
}
