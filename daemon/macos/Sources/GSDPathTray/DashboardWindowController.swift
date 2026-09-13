import AppKit
import WebKit

/// Single dashboard window embedding the daemon's web UI in a WKWebView.
/// The app is LSUIElement/.accessory, so the window flips the activation
/// policy to .regular while visible and back to .accessory on close.
final class DashboardWindowController: NSWindowController, NSWindowDelegate, WKNavigationDelegate {
    static let shared = DashboardWindowController()

    private let dashboardURL = URL(string: "http://localhost:8765")!
    private var webView: WKWebView!
    private var errorView: NSView!

    private init() {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1200, height: 800),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "GSD Path"
        window.minSize = NSSize(width: 900, height: 600)
        window.center()
        super.init(window: window)
        window.delegate = self
        windowFrameAutosaveName = "GSDPathDashboard"

        guard let content = window.contentView else { return }

        // Ephemeral store: nothing (HTTP cache included) persists across sessions.
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        webView = WKWebView(frame: content.bounds, configuration: configuration)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        content.addSubview(webView)

        errorView = makeErrorView(frame: content.bounds)
        errorView.isHidden = true
        content.addSubview(errorView)

        webView.load(URLRequest(url: themedDashboardURL(dashboardURL, choice: appearanceChoice)))
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError() }

    /// Brings the one dashboard window forward, creating it on first use.
    /// Loads `url` when the window is hidden or the target differs from the
    /// current URL. A fragment-only change (e.g. two different `#project=`
    /// deep links) re-navigates the same document: WKWebView treats it as
    /// same-document navigation, so the page's hashchange handler fires
    /// without a full reload.
    func show(_ url: URL? = nil) {
        let target = themedDashboardURL(url ?? dashboardURL, choice: appearanceChoice)
        if window?.isVisible != true || webView.url?.absoluteString != target.absoluteString {
            webView.load(URLRequest(url: target))
        } else {
            // Same URL re-show: refresh instead of no-op, bypassing the
            // in-memory cache so a fixed server-side page shows up.
            webView.reloadFromOrigin()
        }
        NSApp.setActivationPolicy(.regular)
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    // MARK: NSWindowDelegate

    func windowWillClose(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
    }

    // MARK: WKNavigationDelegate — offline error state

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        errorView.isHidden = true
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        errorView.isHidden = false
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        errorView.isHidden = false
    }

    // MARK: Error state

    private func makeErrorView(frame: NSRect) -> NSView {
        let view = NSView(frame: frame)
        view.autoresizingMask = [.width, .height]
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor

        let msg = makeLabel("Dashboard not reachable — is the daemon running?",
                            size: 14, weight: .medium, color: .secondaryLabelColor)
        let cmd = makeLabel("python3 -m gsd_daemon serve", size: 12)
        cmd.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        cmd.isSelectable = true
        cmd.wantsLayer = true
        cmd.layer?.cornerRadius = 5
        cmd.layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor
        let retry = NSButton(title: "Retry", target: self, action: #selector(retryPressed))
        retry.bezelStyle = .rounded
        let browser = NSButton(title: "Open in Browser", target: self, action: #selector(browserPressed))
        browser.bezelStyle = .rounded
        let buttons = NSStackView(views: [retry, browser])
        buttons.orientation = .horizontal
        buttons.spacing = 8

        let stack = NSStackView(views: [msg, cmd, buttons])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: view.centerYAnchor),
        ])
        return view
    }

    @objc private func retryPressed() {
        errorView.isHidden = true
        webView.load(URLRequest(url: themedDashboardURL(dashboardURL, choice: appearanceChoice)))
    }

    @objc private func browserPressed() {
        NSWorkspace.shared.open(themedDashboardURL(dashboardURL, choice: appearanceChoice))
    }
}

/// Adds the tray's appearance choice as ?theme= so the page matches the popover; the fragment is kept.
func themedDashboardURL(_ url: URL, choice: String) -> URL {
    guard var parts = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return url }
    parts.queryItems = [URLQueryItem(name: "theme", value: choice)]
    return parts.url ?? url
}
