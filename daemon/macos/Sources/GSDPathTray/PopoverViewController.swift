import AppKit

/// Appearance shared by the popover and the dashboard window: "system", "light" (default) or "dark".
let appearanceChoices = ["system", "light", "dark"]
var appearanceChoice: String {
    get { UserDefaults.standard.string(forKey: "appearance").flatMap { appearanceChoices.contains($0) ? $0 : nil } ?? "light" }
    set { UserDefaults.standard.set(newValue, forKey: "appearance"); applyAppearance() }
}
/// Popovers take their appearance from the menu-bar button, not NSApp, so open windows are set too;
/// AppDelegate sets the popover's own appearance before showing it.
func applyAppearance() {
    let appearance = appearanceChoice == "system" ? nil : NSAppearance(named: appearanceChoice == "dark" ? .darkAqua : .aqua)
    NSApp.appearance = appearance
    NSApp.windows.forEach { $0.appearance = appearance }
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
               color: NSColor = NSColor.labelColor) -> NSTextField {
    let f = NSTextField(labelWithString: text)
    f.font = .systemFont(ofSize: size, weight: weight)
    f.textColor = color
    f.lineBreakMode = .byTruncatingTail
    return f
}

func makeBrandMarkView() -> NSImageView {
    let icon = NSImageView(image: makeBrandIcon(color: .labelColor))
    icon.translatesAutoresizingMaskIntoConstraints = false
    NSLayoutConstraint.activate([
        icon.widthAnchor.constraint(equalToConstant: 18),
        icon.heightAnchor.constraint(equalToConstant: 18),
    ])
    return icon
}

func healthColor(_ h: Health) -> NSColor {
    switch h {
    case .green: return .systemGreen
    case .yellow: return NSColor.systemOrange
    case .red: return NSColor.systemRed
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
            case .done: color = highlighted ? NSColor.alternateSelectedControlTextColor : NSColor.secondaryLabelColor
            case .now: color = highlighted ? NSColor.alternateSelectedControlTextColor : blocked ? NSColor.systemRed : NSColor.controlAccentColor
            case .ahead: color = highlighted ? NSColor.alternateSelectedControlTextColor.withAlphaComponent(0.35) : NSColor.quaternaryLabelColor
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
            layer?.backgroundColor = hovered ? NSColor.selectedContentBackgroundColor.cgColor : NSColor.clear.cgColor
        }
    }
}

/// Borderless SF Symbol button for the footer toolbar; the label is its tooltip and accessibility name.
final class IconButton: MenuRowButton {
    init(symbol: String, label: String, target: AnyObject, action: Selector) {
        super.init()
        setButtonType(.momentaryPushIn)
        image = NSImage(systemSymbolName: symbol, accessibilityDescription: label)
        imagePosition = .imageOnly
        toolTip = label
        setAccessibilityLabel(label)
        self.target = target
        self.action = action
        translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([widthAnchor.constraint(equalToConstant: 30), heightAnchor.constraint(equalToConstant: 26)])
        hoverChanged()
    }
    override func hoverChanged() {
        super.hoverChanged()
        contentTintColor = hovered ? NSColor.alternateSelectedControlTextColor : NSColor.secondaryLabelColor
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
            .font: NSFont.systemFont(ofSize: 13), .foregroundColor: hovered ? NSColor.alternateSelectedControlTextColor : NSColor.labelColor,
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

        let content = NSView()
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
            let title = makeLabel("OpenGSD Path", size: 13, weight: .semibold)
            let header = NSStackView(views: [makeBrandMarkView(), title])
            header.spacing = 6
            header.edgeInsets = NSEdgeInsets(top: 4, left: 9, bottom: 6, right: 9)
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
            return [header, makeLabel("Offline", size: 12, color: NSColor.systemRed), msg, hint, cmd, daemonRow, buttons].map { inset($0, top: 4) }
        }
    }

    func show(status: StatusResponse) {
        let projects = status.projects ?? []
        var views: [NSView] = []

        let title = makeLabel("OpenGSD Path", size: 13, weight: .semibold)
        let spacer = NSView()
        spacer.setContentHuggingPriority(.init(1), for: .horizontal)
        let dot = DotView()
        dot.color = .systemGreen
        dot.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([dot.widthAnchor.constraint(equalToConstant: 7), dot.heightAnchor.constraint(equalToConstant: 7)])
        let updated = makeLabel(generatedStamp(status.generated_at).map { "Updated \($0)" } ?? "Connected", size: 12, color: NSColor.secondaryLabelColor)
        let header = NSStackView(views: [makeBrandMarkView(), title, spacer, dot, updated])
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
            views.append(inset(makeLabel(caption, size: 11, weight: .semibold, color: NSColor.tertiaryLabelColor), top: 6))
            views += list.map { ProjectRowView(project: $0, dashboardURL: dashboardURL) }
        }
        if projects.isEmpty {
            views.append(inset(makeLabel("No projects in your watched folders.", size: 12, color: NSColor.secondaryLabelColor), top: 6))
        }

        // Plugin update row, only when the daemon reports one.
        if let plugin = status.plugin, plugin.update_available == true, let latest = plugin.latest {
            views.append(MenuItemButton("OpenGSD Path update available — v\(latest)", target: self, action: #selector(pluginPressed)))
        }

        let daemonRow = DaemonRowView()
        daemonRow.onRescan = onRescan
        let symbols = [("circle.lefthalf.filled", "System"), ("sun.max", "Light"), ("moon", "Dark")]
        let appearance = NSSegmentedControl(images: symbols.map { NSImage(systemSymbolName: $0.0, accessibilityDescription: $0.1) ?? NSImage() },
                                            trackingMode: .selectOne, target: self, action: #selector(appearanceChanged(_:)))
        for (index, symbol) in symbols.enumerated() { appearance.setToolTip("Appearance: \(symbol.1)", forSegment: index) }
        appearance.controlSize = .small
        appearance.selectedSegment = appearanceChoices.firstIndex(of: appearanceChoice) ?? 1
        let toolbarSpacer = NSView()
        toolbarSpacer.setContentHuggingPriority(.init(1), for: .horizontal)
        let toolbar = NSStackView(views: [
            IconButton(symbol: "macwindow", label: "Open dashboard", target: self, action: #selector(dashboardPressed)),
            IconButton(symbol: "puzzlepiece.extension", label: "Plugin settings", target: self, action: #selector(pluginPressed)),
            IconButton(symbol: "folder", label: "Watched folders", target: self, action: #selector(foldersPressed)),
            IconButton(symbol: "arrow.clockwise", label: "Rescan", target: self, action: #selector(rescanPressed)),
            toolbarSpacer, appearance,
            IconButton(symbol: "power", label: "Quit", target: self, action: #selector(quitPressed)),
        ])
        toolbar.spacing = 2
        toolbar.edgeInsets = NSEdgeInsets(top: 2, left: 3, bottom: 0, right: 3)
        let footerViews: [NSView] = [separator(), inset(daemonRow, top: 4), toolbar]
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
        detail = makeLabel(p.trayDetail, size: 11.5, color: NSColor.secondaryLabelColor)
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
        name.textColor = hovered ? NSColor.alternateSelectedControlTextColor : NSColor.labelColor
        detail.textColor = hovered ? NSColor.alternateSelectedControlTextColor : NSColor.secondaryLabelColor
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
