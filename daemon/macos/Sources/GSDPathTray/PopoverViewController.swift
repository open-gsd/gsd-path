import AppKit

// Studio palette from gsd-cloud/web/app/globals.css.
func studioColor(light: Int, dark: Int) -> NSColor {
    NSColor(name: nil) { appearance in
        let value = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? dark : light
        return NSColor(srgbRed: CGFloat((value >> 16) & 255) / 255,
                       green: CGFloat((value >> 8) & 255) / 255,
                       blue: CGFloat(value & 255) / 255, alpha: 1)
    }
}
let studioText = studioColor(light: 0x14161a, dark: 0xeceef2)
let studioAccent = studioColor(light: 0x4f5fe0, dark: 0x7c8cff)

final class StudioSurface: NSView {
    override var wantsUpdateLayer: Bool { true }
    override func updateLayer() {
        effectiveAppearance.performAsCurrentDrawingAppearance {
            layer?.backgroundColor = studioColor(light: 0xf7f8fa, dark: 0x0c0d10).cgColor
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
               color: NSColor = studioText) -> NSTextField {
    let f = NSTextField(labelWithString: text)
    f.font = .systemFont(ofSize: size, weight: weight)
    f.textColor = color
    f.lineBreakMode = .byTruncatingTail
    return f
}

/// Solid state capsule: white text on a filled background so it reads on both surfaces.
final class PillView: NSView {
    let label: NSTextField
    init(_ text: String, fill: NSColor) {
        label = makeLabel(text, size: 11, weight: .semibold, color: .white)
        super.init(frame: .zero)
        wantsLayer = true
        layer?.cornerRadius = 9
        layer?.backgroundColor = fill.cgColor
        self.fill = fill
        label.translatesAutoresizingMaskIntoConstraints = false
        addSubview(label)
        NSLayoutConstraint.activate([
            label.topAnchor.constraint(equalTo: topAnchor, constant: 2),
            label.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -2),
            label.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 8),
            label.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -8),
        ])
        setContentHuggingPriority(.required, for: .horizontal)
        setContentCompressionResistancePriority(.required, for: .horizontal)
    }
    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }
    private var fill: NSColor = .systemGray
    override func viewDidChangeEffectiveAppearance() {
        effectiveAppearance.performAsCurrentDrawingAppearance { layer?.backgroundColor = fill.cgColor }
    }
}

func makePill(_ text: String, fill: NSColor) -> NSView { PillView(text, fill: fill) }

/// Fill colour for the state pill: blocked red, shipped green, otherwise the accent.
func stateFill(_ state: String) -> NSColor {
    switch state {
    case "blocked": return studioColor(light: 0xb23a2c, dark: 0xd9483a)
    case "shipped": return studioColor(light: 0x0d7d53, dark: 0x1f8f62)
    default: return studioColor(light: 0x4f5fe0, dark: 0x5a68e8)
    }
}

func healthColor(_ h: Health) -> NSColor {
    switch h {
    case .green: return studioColor(light: 0x0d7d53, dark: 0x3ddc97)
    case .yellow: return studioColor(light: 0x7c5205, dark: 0xf5b544)
    case .red: return studioColor(light: 0xb23a2c, dark: 0xff6b5e)
    case .gray: return .systemGray
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
        stack.spacing = 10
        stack.edgeInsets = NSEdgeInsets(top: 14, left: 14, bottom: 12, right: 14)
        stack.translatesAutoresizingMaskIntoConstraints = false

        let doc = NSView()
        doc.translatesAutoresizingMaskIntoConstraints = false
        doc.addSubview(stack)
        scroll.documentView = doc

        let content = StudioSurface()
        content.wantsLayer = true
        content.addSubview(scroll)
        controls.orientation = .vertical
        controls.alignment = .leading
        controls.spacing = 8
        controls.edgeInsets = NSEdgeInsets(top: 8, left: 14, bottom: 12, right: 14)
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
            let title = makeLabel("GSD Path", size: 20, weight: .bold)
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
            return [title, makeLabel("Offline", size: 12, color: .systemRed), msg, hint, cmd, daemonRow, buttons]
        }
    }

    func show(status: StatusResponse) {
        let projects = status.projects ?? []
        var views: [NSView] = []

        let header = makeLabel("GSD Path", size: 16, weight: .semibold)
        header.textColor = studioAccent
        let connected = makeLabel("Connected", size: 12, color: .systemGreen)
        let count = makeLabel("\(projects.count) watched project\(projects.count == 1 ? "" : "s")", size: 12)
        let stamp = generatedStamp(status.generated_at)
        let updated = makeLabel(stamp.map { "Updated \($0)" } ?? "Update time unavailable", size: 11, color: .secondaryLabelColor)
        let sub = NSStackView(views: [count, updated])
        sub.distribution = .equalSpacing
        let titleRow = NSStackView(views: [header, connected])
        titleRow.distribution = .equalSpacing
        views += [titleRow, separator(), sub]

        // Board order: blocked, then active, then shipped; name within each.
        let sorted = projects.sorted { a, b in
            if a.stateRank != b.stateRank { return a.stateRank < b.stateRank }
            return a.displayProject.localizedCaseInsensitiveCompare(b.displayProject) == .orderedAscending
        }
        for project in sorted {
            views.append(ProjectRowView(project: project, dashboardURL: dashboardURL))
        }
        if projects.isEmpty {
            views.append(makeLabel("No projects in your watched folders.", size: 12, color: .secondaryLabelColor))
        }
        views.append(separator())

        // Plugin update row, only when the daemon reports one.
        if let plugin = status.plugin, plugin.update_available == true, let latest = plugin.latest {
            let update = NSButton(title: "", target: self, action: #selector(pluginPressed))
            update.bezelStyle = .inline
            update.setButtonType(.momentaryPushIn)
            let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 12)]
            let title = NSMutableAttributedString(
                string: "⬆ ",
                attributes: attrs.merging([.foregroundColor: NSColor.systemYellow]) { _, new in new })
            title.append(NSAttributedString(
                string: "GSD Path update available — v\(latest)",
                attributes: attrs.merging([.foregroundColor: NSColor.labelColor]) { _, new in new }))
            update.attributedTitle = title
            views.append(update)
        }

        var footerViews: [NSView] = []
        let dash = NSButton(title: "Open Dashboard", target: self, action: #selector(dashboardPressed))
        let plugin = NSButton(title: "Plugin settings…", target: self, action: #selector(pluginPressed))
        let folders = NSButton(title: "Watched folders…", target: self, action: #selector(foldersPressed))
        for button in [dash, plugin, folders] {
            button.bezelStyle = .inline
            button.isBordered = false
            button.alignment = .left
            button.font = .systemFont(ofSize: 13)
            footerViews.append(button)
        }
        let daemonRow = DaemonRowView()
        daemonRow.onRescan = onRescan
        footerViews.append(daemonRow)
        let rescan = NSButton(title: "Rescan", target: self, action: #selector(rescanPressed))
        let quit = NSButton(title: "Quit", target: self, action: #selector(quitPressed))
        for button in [rescan, quit] { button.bezelStyle = .inline }
        let footer = NSStackView(views: [rescan, quit])
        footer.distribution = .equalSpacing
        footerViews.append(footer)

        rebuild(footer: footerViews) { views }
    }

    private func rebuild(footer: [NSView] = [], _ makeViews: () -> [NSView]) {
        for v in controls.arrangedSubviews { controls.removeArrangedSubview(v); v.removeFromSuperview() }
        for v in footer { controls.addArrangedSubview(v) }
        for v in stack.arrangedSubviews { stack.removeArrangedSubview(v); v.removeFromSuperview() }
        for v in makeViews() {
            stack.addArrangedSubview(v)
            v.widthAnchor.constraint(equalTo: stack.widthAnchor,
                                     constant: -(stack.edgeInsets.left + stack.edgeInsets.right)).isActive = true
        }
        stack.layoutSubtreeIfNeeded()
        let contentHeight = stack.fittingSize.height + controls.fittingSize.height
        preferredContentSize = NSSize(width: 440, height: min(max(contentHeight, 120), NSScreen.main.map { $0.visibleFrame.height } ?? 600))
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

// MARK: - Milestone stack row (status board)

final class ProjectRowView: NSView {
    init(project p: ProjectStatus, dashboardURL: URL) {
        super.init(frame: .zero)
        self.project = p
        self.dashboardURL = dashboardURL
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 3
        stack.edgeInsets = NSEdgeInsets(top: 8, left: 14, bottom: 8, right: 14)
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: topAnchor),
            stack.leadingAnchor.constraint(equalTo: leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: trailingAnchor),
            stack.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
        let name = NSButton(title: p.displayProject + "  ›", target: self, action: #selector(dashPressed))
        name.bezelStyle = .inline
        name.isBordered = false
        name.font = .systemFont(ofSize: 14, weight: .semibold)
        name.alignment = .left
        name.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let pill = makePill(p.stateLabel, fill: stateFill(p.projectState))
        let top = NSStackView(views: [name, pill])
        top.distribution = .fill
        top.spacing = 10
        stack.addArrangedSubview(top)
        top.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -28).isActive = true

        // Done / here / ahead on one line: M001 ✓  M002 ●  M003 ○
        let line = NSMutableAttributedString()
        let mono = NSFont.monospacedSystemFont(ofSize: 12, weight: .medium)
        let nowColor = p.projectState == "blocked" ? healthColor(.red) : p.projectState == "shipped" ? healthColor(.green) : studioAccent
        for (index, entry) in p.milestoneStack.enumerated() {
            let color: NSColor
            switch entry.kind {
            case .done: color = healthColor(.green)
            case .now: color = nowColor
            case .ahead: color = .tertiaryLabelColor
            }
            let piece = p.stackText.components(separatedBy: "  ")[index]
            line.append(NSAttributedString(string: (index == 0 ? "" : "  ") + piece,
                                           attributes: [.font: mono, .foregroundColor: color]))
        }
        let stackLabel = NSTextField(labelWithAttributedString: line)
        stackLabel.lineBreakMode = .byTruncatingTail
        stackLabel.toolTip = p.milestoneStack.map { "\($0.number) \($0.slug)" }.joined(separator: "\n")
        stack.addArrangedSubview(stackLabel)

        let here = makeLabel(p.hereText, size: 12, color: .secondaryLabelColor)
        here.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        stack.addArrangedSubview(here)
        if let goal = p.goalText {
            let label = makeLabel(goal, size: 12, color: .secondaryLabelColor)
            label.lineBreakMode = .byWordWrapping
            label.maximumNumberOfLines = 2
            label.preferredMaxLayoutWidth = 400
            stack.addArrangedSubview(label)
        }
        if let shipped = p.lastShippedText {
            let label = makeLabel(shipped, size: 12, color: .secondaryLabelColor)
            label.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
            stack.addArrangedSubview(label)
        }
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    private var project: ProjectStatus?
    private var dashboardURL: URL?

    @objc private func dashPressed() {
        guard let base = dashboardURL else {
            DashboardWindowController.shared.show()
            return
        }
        DashboardWindowController.shared.show(projectDeepLink(base: base, root: project?.root))
    }
}

/// Dashboard deep link selecting a project by its (fragment-encoded) root.
func projectDeepLink(base: URL, root: String?) -> URL {
    guard let root = root else { return base }
    let safe = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
    let encoded = root.addingPercentEncoding(withAllowedCharacters: safe) ?? ""
    return URL(string: "\(base.absoluteString)#project=\(encoded)") ?? base
}
