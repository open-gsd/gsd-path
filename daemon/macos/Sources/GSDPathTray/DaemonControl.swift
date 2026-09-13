import AppKit

// MARK: - launchctl lifecycle control for the org.gsd-path.daemon LaunchAgent

struct DaemonActionError: Error {
    let message: String
}

enum DaemonState {
    case running(pid: Int)
    case stopped
    case notInstalled
}

enum DaemonControl {
    static let label = "org.gsd-path.daemon"
    static let plistPath = NSHomeDirectory() + "/Library/LaunchAgents/\(label).plist"
    private static var serviceTarget: String { "gui/\(getuid())/\(label)" }
    private static var domainTarget: String { "gui/\(getuid())" }

    /// Completion is dispatched to `queue` (main by default for UI callers).
    static func status(queue: DispatchQueue = .main,
                       completion: @escaping (DaemonState) -> Void) {
        run(["print", serviceTarget], queue: queue) { result in
            switch result {
            case .success(let out):
                // `launchctl print` exits 0 for a loaded service; a running one
                // has a `pid = N` line, "state = not running" does not.
                var pid: Int?
                for line in out.split(separator: "\n") {
                    let t = line.trimmingCharacters(in: .whitespaces)
                    if t.hasPrefix("pid = ") { pid = Int(t.dropFirst("pid = ".count)) }
                }
                completion(pid.map { .running(pid: $0) } ?? .stopped)
            case .failure:
                // "Could not find service" (or any non-zero exit): the plist
                // decides between stopped-but-installed and not installed.
                completion(FileManager.default.fileExists(atPath: plistPath) ? .stopped : .notInstalled)
            }
        }
    }

    static func start(queue: DispatchQueue = .main,
                      completion: @escaping (Result<Void, DaemonActionError>) -> Void) {
        run(["bootstrap", domainTarget, plistPath], queue: queue) { result in
            switch result {
            case .success: completion(.success(()))
            case .failure: run(["load", "-w", plistPath], queue: queue) { completion($0.map { _ in () }) }
            }
        }
    }

    static func stop(queue: DispatchQueue = .main,
                     completion: @escaping (Result<Void, DaemonActionError>) -> Void) {
        run(["bootout", serviceTarget], queue: queue) { result in
            switch result {
            case .success: completion(.success(()))
            case .failure: run(["unload", plistPath], queue: queue) { completion($0.map { _ in () }) }
            }
        }
    }

    static func restart(queue: DispatchQueue = .main,
                        completion: @escaping (Result<Void, DaemonActionError>) -> Void) {
        run(["kickstart", "-k", serviceTarget], queue: queue) { completion($0.map { _ in () }) }
    }

    /// Runs launchctl on a background queue with a hard timeout, capturing
    /// stdout/stderr. Success carries stdout; failure carries stderr text (or
    /// a short fallback). Completion is dispatched to `queue`.
    private static func run(_ arguments: [String], timeout: TimeInterval = 3,
                            queue: DispatchQueue,
                            completion: @escaping (Result<String, DaemonActionError>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
            process.arguments = arguments
            let outPipe = Pipe()
            let errPipe = Pipe()
            process.standardOutput = outPipe
            process.standardError = errPipe
            do {
                try process.run()
            } catch {
                queue.async { completion(.failure(DaemonActionError(message: error.localizedDescription))) }
                return
            }
            let watchdog = DispatchWorkItem { [process] in
                if process.isRunning { process.terminate() }
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: watchdog)
            let outData = outPipe.fileHandleForReading.readDataToEndOfFile()
            let errData = errPipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            watchdog.cancel()
            let out = String(data: outData, encoding: .utf8) ?? ""
            let err = String(data: errData, encoding: .utf8) ?? ""
            if process.terminationReason == .exit && process.terminationStatus == 0 {
                queue.async { completion(.success(out)) }
            } else {
                let message = err.trimmingCharacters(in: .whitespacesAndNewlines)
                let fallback = process.terminationReason == .exit
                    ? "launchctl exited \(process.terminationStatus)"
                    : "launchctl timed out"
                queue.async { completion(.failure(DaemonActionError(message: message.isEmpty ? fallback : message))) }
            }
        }
    }
}

// MARK: - Popover daemon row

/// Compact status row: health dot + state text + contextual start/stop/restart
/// buttons. Refreshes itself via `DaemonControl.status`; the popover recreates
/// it on every poll, so the state can never go stale.
final class DaemonRowView: NSView {
    var onRescan: (() -> Void)?
    private let stack = NSStackView()
    private var buttons: [NSButton] = []

    override init(frame: NSRect) {
        super.init(frame: frame)
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 8
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            // Fixed height: the status arrives after the popover is sized, so the row must not grow.
            heightAnchor.constraint(equalToConstant: 24),
            stack.centerYAnchor.constraint(equalTo: centerYAnchor),
            stack.leadingAnchor.constraint(equalTo: leadingAnchor),
            stack.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor),
        ])
        refresh()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    func refresh() {
        DaemonControl.status { [weak self] state in
            self?.render(state)
        }
    }

    private func render(_ state: DaemonState) {
        for v in stack.arrangedSubviews { stack.removeArrangedSubview(v); v.removeFromSuperview() }
        buttons = []

        let dot = DotView()
        dot.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([dot.widthAnchor.constraint(equalToConstant: 8),
                                     dot.heightAnchor.constraint(equalToConstant: 8)])
        let text: String
        switch state {
        case .running(let pid):
            dot.color = .systemGreen
            text = "daemon: running · pid \(pid)"
        case .stopped:
            dot.color = .systemGray
            text = "daemon: stopped"
        case .notInstalled:
            dot.color = .systemYellow
            text = "daemon: autostart not installed"
        }
        stack.addArrangedSubview(dot)
        stack.addArrangedSubview(makeLabel(text, size: 12, color: .secondaryLabelColor))

        switch state {
        case .running:
            addButton("Restart", action: #selector(restartPressed))
            addButton("Stop", action: #selector(stopPressed))
        case .stopped:
            addButton("Start", action: #selector(startPressed))
        case .notInstalled:
            let cmd = makeLabel("run: gsd-path-daemon install", size: 11)
            cmd.font = NSFont.monospacedSystemFont(ofSize: 11, weight: .regular)
            cmd.isSelectable = true
            stack.addArrangedSubview(cmd)
        }
    }

    private func addButton(_ title: String, action: Selector) {
        let b = NSButton(title: title, target: self, action: action)
        b.bezelStyle = .rounded
        b.controlSize = .small
        b.font = .systemFont(ofSize: 11)
        buttons.append(b)
        stack.addArrangedSubview(b)
    }

    @objc private func startPressed() { performAction { DaemonControl.start(completion: $0) } }
    @objc private func stopPressed() { performAction { DaemonControl.stop(completion: $0) } }
    @objc private func restartPressed() { performAction { DaemonControl.restart(completion: $0) } }

    private func performAction(_ action: (@escaping (Result<Void, DaemonActionError>) -> Void) -> Void) {
        buttons.forEach { $0.isEnabled = false }
        action { [weak self] result in
            guard let self = self else { return }
            switch result {
            case .success:
                // launchd needs a moment before status reflects the change.
                DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
                    self.refresh()
                    self.onRescan?()
                }
            case .failure(let error):
                self.refresh()
                let alert = NSAlert()
                alert.messageText = "Daemon action failed"
                alert.informativeText = error.message
                alert.alertStyle = .warning
                alert.runModal()
            }
        }
    }
}
