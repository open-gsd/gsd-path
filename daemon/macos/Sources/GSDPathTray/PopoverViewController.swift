import AppKit

// MARK: - Small view building blocks

final class DotView: NSView {
    var color: NSColor = .systemGray { didSet { needsDisplay = true } }
    override func draw(_ dirtyRect: NSRect) {
        color.setFill()
        NSBezierPath(ovalIn: bounds.insetBy(dx: 1, dy: 1)).fill()
    }
}

final class BarView: NSView {
    var fraction: Double = 0 { didSet { needsDisplay = true } }
    var fillColor: NSColor = .systemGreen { didSet { needsDisplay = true } }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.gray.withAlphaComponent(0.3).setFill()
        NSBezierPath(roundedRect: bounds, xRadius: 2.5, yRadius: 2.5).fill()
        let w = bounds.width * CGFloat(max(0, min(1, fraction)))
        if w > 0 {
            fillColor.setFill()
            NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: w, height: bounds.height),
                         xRadius: 2.5, yRadius: 2.5).fill()
        }
    }
}

func makeLabel(_ text: String, size: CGFloat, weight: NSFont.Weight = .regular,
               color: NSColor = .labelColor) -> NSTextField {
    let f = NSTextField(labelWithString: text)
    f.font = .systemFont(ofSize: size, weight: weight)
    f.textColor = color
    f.lineBreakMode = .byTruncatingTail
    return f
}

func makePill(_ text: String, textColor: NSColor) -> NSTextField {
    let f = makeLabel(text, size: 11, weight: .semibold, color: textColor)
    f.wantsLayer = true
    f.layer?.cornerRadius = 9
    f.layer?.backgroundColor = textColor.withAlphaComponent(0.18).cgColor
    f.setContentHuggingPriority(.required, for: .horizontal)
    return f
}

func healthColor(_ h: Health) -> NSColor {
    switch h {
    case .green: return .systemGreen
    case .yellow: return .systemYellow
    case .red: return .systemRed
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
    private var onRescan: () -> Void = {}
    private var lastStatus: StatusResponse?
    private var quietExpanded = false

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

        let content = NSView()
        content.addSubview(scroll)
        scroll.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            scroll.topAnchor.constraint(equalTo: content.topAnchor),
            scroll.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            scroll.bottomAnchor.constraint(equalTo: content.bottomAnchor),
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
            let title = makeLabel("gsd-path", size: 15, weight: .bold)
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
            return [title, msg, hint, cmd, daemonRow, buttons]
        }
    }

    func show(status: StatusResponse) {
        lastStatus = status
        let projects = status.projects ?? []
        var views: [NSView] = []

        // Header: project count + generated_at time.
        let header = makeLabel("gsd-path", size: 15, weight: .bold)
        let stamp = generatedStamp(status.generated_at)
        let sub = makeLabel("\(projects.count) project\(projects.count == 1 ? "" : "s")\(stamp.map { " · updated \($0)" } ?? "")",
                            size: 11, color: .secondaryLabelColor)
        let headRow = NSStackView(views: [header, sub])
        headRow.alignment = .firstBaseline
        headRow.spacing = 8
        views.append(headRow)

        // Sort by health severity (red, amber, green), then name.
        let sorted = projects.sorted { a, b in
            if a.severity != b.severity { return a.severity < b.severity }
            return a.displayProject.localizedCaseInsensitiveCompare(b.displayProject) == .orderedAscending
        }

        // "Needs you": one row per attention item across all projects.
        let attentionPairs = sorted.flatMap { p in p.attentionItems.map { (item: $0, project: p) } }
        if !attentionPairs.isEmpty {
            views.append(makeLabel("NEEDS YOU", size: 11, weight: .semibold,
                                   color: .secondaryLabelColor))
            for pair in attentionPairs {
                views.append(AttentionRowView(item: pair.item, project: pair.project,
                                              dashboardURL: dashboardURL))
            }
        }

        // Quiet projects collapse behind a disclosure row at the bottom.
        let loud = sorted.filter { !$0.isQuiet }
        let quiet = sorted.filter { $0.isQuiet }
        for p in loud {
            views.append(ProjectCardView(project: p, dashboardURL: dashboardURL))
        }
        if !quiet.isEmpty {
            let toggle = NSButton(
                title: "\(quietExpanded ? "▾" : "▸") \(quiet.count) quiet project\(quiet.count == 1 ? "" : "s")",
                target: self, action: #selector(toggleQuiet))
            toggle.bezelStyle = .inline
            toggle.setButtonType(.momentaryPushIn)
            toggle.font = .systemFont(ofSize: 12)
            views.append(toggle)
            if quietExpanded {
                for p in quiet {
                    views.append(ProjectCardView(project: p, dashboardURL: dashboardURL))
                }
            }
        }
        if projects.isEmpty {
            views.append(makeLabel("No gsd-path projects under the watched folders.",
                                   size: 12, color: .secondaryLabelColor))
        }

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

        // Daemon lifecycle row, just above the watched-folder action.
        let daemonRow = DaemonRowView()
        daemonRow.onRescan = onRescan
        views.append(daemonRow)

        // Watched-folder action, on its own row just above the footer.
        let addFolder = NSButton(title: "Add Watched Folder…", target: self, action: #selector(addFolderPressed))
        addFolder.bezelStyle = .rounded
        views.append(addFolder)

        // Footer row: Open Dashboard, Rescan, Quit.
        let dash = NSButton(title: "Open Dashboard", target: self, action: #selector(dashboardPressed))
        dash.bezelStyle = .rounded
        let rescan = NSButton(title: "Rescan", target: self, action: #selector(rescanPressed))
        rescan.bezelStyle = .rounded
        let quit = NSButton(title: "Quit", target: self, action: #selector(quitPressed))
        quit.bezelStyle = .rounded
        let footer = NSStackView(views: [dash, rescan, quit])
        footer.orientation = .horizontal
        footer.spacing = 8
        views.append(footer)

        rebuild { views }
    }

    private func rebuild(_ makeViews: () -> [NSView]) {
        for v in stack.arrangedSubviews { stack.removeArrangedSubview(v); v.removeFromSuperview() }
        for v in makeViews() {
            stack.addArrangedSubview(v)
            v.widthAnchor.constraint(equalTo: stack.widthAnchor,
                                     constant: -(stack.edgeInsets.left + stack.edgeInsets.right)).isActive = true
        }
        stack.layoutSubtreeIfNeeded()
        let contentHeight = stack.fittingSize.height
        preferredContentSize = NSSize(width: 400, height: min(max(contentHeight, 120), 600))
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
    @objc private func toggleQuiet() {
        quietExpanded.toggle()
        if let status = lastStatus { show(status: status) }
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

// MARK: - Project card (prototype variant B)

final class ProjectCardView: NSView {
    init(project p: ProjectStatus, dashboardURL: URL) {
        super.init(frame: .zero)
        wantsLayer = true
        layer?.cornerRadius = 10
        layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor

        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 6
        stack.edgeInsets = NSEdgeInsets(top: 11, left: 12, bottom: 11, right: 12)
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: topAnchor),
            stack.leadingAnchor.constraint(equalTo: leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: trailingAnchor),
            stack.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
        let fullWidth = { (v: NSView) in
            v.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -24).isActive = true
        }

        // Top row: health dot + name + milestone + pill.
        let dot = DotView()
        dot.color = healthColor(p.effectiveHealth)
        dot.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([dot.widthAnchor.constraint(equalToConstant: 8),
                                     dot.heightAnchor.constraint(equalToConstant: 8)])
        let name = makeLabel(p.displayProject, size: 14, weight: .bold)
        let ms = makeLabel(p.milestone.map { "M· \($0)" } ?? "—", size: 11, color: .secondaryLabelColor)
        let pill: NSTextField
        if p.status == "blocked" {
            pill = makePill("blocked", textColor: .systemRed)
        } else if p.isShipped {
            pill = makePill("shipped", textColor: .systemBlue)
        } else {
            pill = makePill(p.displayPhase, textColor: .systemGreen)
        }
        let top = NSStackView(views: [dot, name, ms, pill])
        top.orientation = .horizontal
        top.alignment = .centerY
        top.spacing = 8
        stack.addArrangedSubview(top)
        fullWidth(top)

        // 8-segment phase stepper.
        let idx = canonicalPhases.firstIndex(of: p.phase ?? "")
        let steps = NSStackView()
        steps.orientation = .horizontal
        steps.spacing = 3
        steps.distribution = .fillEqually
        for i in 0..<canonicalPhases.count {
            let seg = NSView()
            seg.wantsLayer = true
            seg.layer?.cornerRadius = 2
            if p.isShipped || (idx != nil && i < idx!) {
                seg.layer?.backgroundColor = NSColor.systemGreen.cgColor
            } else if idx != nil && i == idx! {
                seg.layer?.backgroundColor = (p.status == "blocked" ? NSColor.systemRed : NSColor.systemBlue).cgColor
            } else {
                seg.layer?.backgroundColor = NSColor.gray.withAlphaComponent(0.35).cgColor
            }
            seg.translatesAutoresizingMaskIntoConstraints = false
            seg.heightAnchor.constraint(equalToConstant: 4).isActive = true
            steps.addArrangedSubview(seg)
        }
        stack.addArrangedSubview(steps)
        fullWidth(steps)

        // Step labels: inspect … decide … build … ship.
        let labels = ["inspect", "decide", "build", "ship"].map {
            makeLabel($0, size: 10, color: .tertiaryLabelColor)
        }
        let labelRow = NSStackView()
        labelRow.orientation = .horizontal
        labelRow.distribution = .equalSpacing
        for l in labels { labelRow.addArrangedSubview(l) }
        stack.addArrangedSubview(labelRow)
        fullWidth(labelRow)

        // Tasks progress.
        if p.total > 0 {
            let bar = BarView()
            bar.fraction = Double(p.done) / Double(p.total)
            bar.fillColor = p.status == "blocked" ? .systemRed : .systemGreen
            bar.translatesAutoresizingMaskIntoConstraints = false
            bar.heightAnchor.constraint(equalToConstant: 5).isActive = true
            stack.addArrangedSubview(bar)
            fullWidth(bar)

            var taskText = "Tasks \(p.done)/\(p.total)"
            if let wave = p.current_wave, let waveName = p.waves?[String(wave)] {
                taskText += " · wave \(wave) “\(waveName)”"
            } else if p.done == p.total {
                taskText += " · all done"
            }
            let pct = Int(round(100.0 * Double(p.done) / Double(p.total)))
            let taskRow = NSStackView(views: [
                makeLabel(taskText, size: 12, color: .secondaryLabelColor),
                makeLabel("\(pct)%", size: 12, color: .secondaryLabelColor),
            ])
            taskRow.distribution = .equalSpacing
            stack.addArrangedSubview(taskRow)
            fullWidth(taskRow)
        } else {
            let l = makeLabel("No tasks yet — pre-plan phase", size: 12, color: .secondaryLabelColor)
            stack.addArrangedSubview(l)
            fullWidth(l)
        }

        // Branch + clean/dirty, next-skill chip on the right.
        let branchText: String
        if let branch = p.branch {
            branchText = p.isDirty ? "\(branch) · dirty" : "\(branch) · clean"
        } else {
            branchText = "no branch"
        }
        let branchLabel = makeLabel(branchText, size: 12,
                                    color: p.isDirty ? .systemYellow : .secondaryLabelColor)
        let branchRow = NSStackView()
        branchRow.orientation = .horizontal
        branchRow.distribution = .equalSpacing
        branchRow.addArrangedSubview(branchLabel)
        if let skill = p.nextSkillDisplay {
            let chip = NSButton(title: skill, target: nil, action: nil)
            chip.bezelStyle = .inline
            chip.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .medium)
            chip.setButtonType(.momentaryPushIn)
            if let raw = p.next_skill {
                chip.target = self
                chip.action = #selector(copySkill(_:))
                chip.identifier = NSUserInterfaceItemIdentifier(raw)
            } else {
                chip.isEnabled = false
            }
            branchRow.addArrangedSubview(chip)
        }
        stack.addArrangedSubview(branchRow)
        fullWidth(branchRow)

        // Pending answers warning.
        if !p.answers.isEmpty {
            let ids = p.answers.map { "\($0.answer ?? "?") (\($0.status ?? "?"))" }.joined(separator: ", ")
            let l = makeLabel("⚠ \(p.answers.count) pending answer\(p.answers.count > 1 ? "s" : "") — \(ids)",
                              size: 12, color: .systemYellow)
            stack.addArrangedSubview(l)
            fullWidth(l)
        }

        // Optional note (tolerated, not in the core contract).
        if let note = p.note, !note.isEmpty {
            let l = makeLabel("⛔ \(note)", size: 12, color: .systemRed)
            stack.addArrangedSubview(l)
            fullWidth(l)
        }

        // Lookahead, only when present.
        if let next = p.next_milestone, let msName = next.milestone {
            let l = makeLabel("⏭ lookahead: \(msName) (\(next.phase ?? "?"))",
                              size: 12, color: .secondaryLabelColor)
            stack.addArrangedSubview(l)
            fullWidth(l)
        }

        // Usage footer, only when usage non-null.
        if let usage = p.usage {
            let tokens = (usage.tokens_in ?? 0) + (usage.tokens_out ?? 0)
            var text = "⚡ \(fmtTokens(tokens)) tok · $\(String(format: "%.2f", usage.cost ?? 0))"
            if p.isShipped {
                text += " · milestone complete"
            } else if let t = p.time_in_phase_s {
                text += " · ⏱ \(fmtDuration(t)) in \(p.displayPhase)"
            }
            let l = makeLabel(text, size: 12, color: .secondaryLabelColor)
            stack.addArrangedSubview(l)
            fullWidth(l)
        }

        // Card actions.
        let reveal = NSButton(title: "Reveal", target: self, action: #selector(revealPressed))
        let dash = NSButton(title: "Dashboard", target: self, action: #selector(dashPressed))
        for b in [reveal, dash] {
            b.bezelStyle = .rounded
            b.controlSize = .small
            b.font = .systemFont(ofSize: 11)
        }
        let actions = NSStackView(views: [reveal, dash])
        actions.orientation = .horizontal
        actions.spacing = 8
        stack.addArrangedSubview(actions)

        self.project = p
        self.dashboardURL = dashboardURL
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    private var project: ProjectStatus?
    private var dashboardURL: URL?

    @objc private func copySkill(_ sender: NSButton) {
        guard let raw = sender.identifier?.rawValue else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString("$\(raw)", forType: .string)
    }

    @objc private func revealPressed() {
        guard let root = project?.root else { return }
        let path = (root as NSString).expandingTildeInPath
        NSWorkspace.shared.selectFile(path, inFileViewerRootedAtPath: "")
    }

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
    let encoded = root.addingPercentEncoding(withAllowedCharacters: .urlFragmentAllowed) ?? root
    return URL(string: "\(base.absoluteString)#project=\(encoded)") ?? base
}

// MARK: - "Needs you" attention row

/// One attention item: kind pill in the project's health color, the item
/// label, the project name. Clicking opens the project deep link in the
/// native dashboard window.
final class AttentionRowView: NSView {
    private let url: URL

    init(item: AttentionItem, project: ProjectStatus, dashboardURL: URL) {
        url = projectDeepLink(base: dashboardURL, root: project.root)
        super.init(frame: .zero)

        let pill = makePill(item.kind ?? "?", textColor: healthColor(project.effectiveHealth))
        let label = makeLabel(item.label ?? "?", size: 12)
        label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let name = makeLabel(project.displayProject, size: 11, color: .secondaryLabelColor)
        name.setContentHuggingPriority(.required, for: .horizontal)
        let row = NSStackView(views: [pill, label, name])
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 8
        row.translatesAutoresizingMaskIntoConstraints = false
        addSubview(row)
        NSLayoutConstraint.activate([
            row.topAnchor.constraint(equalTo: topAnchor),
            row.leadingAnchor.constraint(equalTo: leadingAnchor),
            row.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor),
            row.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])

        let click = NSClickGestureRecognizer(target: self, action: #selector(openDashboard))
        addGestureRecognizer(click)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    @objc private func openDashboard() {
        DashboardWindowController.shared.show(url)
    }
}
