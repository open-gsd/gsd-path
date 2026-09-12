import Foundation

/// `--self-test [url]` mode: no NSApplication, no GUI session required.
/// Prints one line per project plus `OK` and exits 0; prints `OFFLINE` and
/// exits 1 on any fetch or decode failure.
func runSelfTest(urlString: String) -> Int32 {
    guard let url = URL(string: urlString) else {
        print("OFFLINE")
        return 1
    }
    let semaphore = DispatchSemaphore(value: 0)
    var outcome: Result<StatusResponse, FetchError>?
    fetchStatus(url: url) { result in
        outcome = result
        semaphore.signal()
    }
    _ = semaphore.wait(timeout: .now() + 10)

    switch outcome {
    case .success(let status):
        for p in status.projects ?? [] {
            let next = p.nextSkillDisplay ?? "-"
            print("\(p.displayProject) \(p.displayPhase)/\(p.displayStatus) tasks=\(p.done)/\(p.total) next=\(next) health=\(healthName(p.effectiveHealth))")
            for a in p.attentionItems {
                print("attention \(p.displayProject) \(a.kind ?? "?") \(a.label ?? "?")")
            }
        }
        if let plugin = status.plugin, plugin.update_available == true, let latest = plugin.latest {
            print("plugin-update-available \(latest)")
        }
        print(daemonStatusLine())
        print("OK")
        return 0
    default:
        print("OFFLINE")
        print(daemonStatusLine())
        return 1
    }
}

/// Blocking daemon-state probe for --self-test. The query completes on a
/// background queue so the main thread can wait on the semaphore.
private func daemonStatusLine() -> String {
    let semaphore = DispatchSemaphore(value: 0)
    var line = "daemon unknown"
    let background = DispatchQueue.global(qos: .userInitiated)
    DaemonControl.status(queue: background) { state in
        switch state {
        case .running(let pid): line = "daemon running pid \(pid)"
        case .stopped: line = "daemon stopped"
        case .notInstalled: line = "daemon not-installed"
        }
        semaphore.signal()
    }
    _ = semaphore.wait(timeout: .now() + 5)
    return line
}
