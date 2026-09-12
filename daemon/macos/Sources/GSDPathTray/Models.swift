import Foundation

// MARK: - Status JSON model (gsd-path-daemon/status/v1)
// Every per-project key is optional; decoding must tolerate missing fields.

struct StatusResponse: Codable {
    var schema: String?
    var generated_at: String?
    var projects: [ProjectStatus]?
    var plugin: PluginStatus?
}

struct PluginStatus: Codable {
    var latest: String?
    var update_available: Bool?
    var hosts: [String: PluginHost]?
}

struct PluginHost: Codable {
    var installed: Bool?
    var version: String?
    var root: String?
}

struct ProjectStatus: Codable {
    var root: String?
    var project: String?
    var milestone: String?
    var phase: String?
    var status: String?
    var branch: String?
    var git: GitStatus?
    var tasks_done: Int?
    var tasks_total: Int?
    var current_wave: Int?
    var waves: [String: String]?
    var pending_answers: [PendingAnswer]?
    var next_skill: String?
    var time_in_phase_s: Double?
    var usage: Usage?
    var next_milestone: NextMilestone?
    var note: String?
    var health: String?
    var attention: [AttentionItem]?
}

struct AttentionItem: Codable {
    var kind: String?
    var label: String?
    var ref: String?
}

struct GitStatus: Codable {
    var branch: String?
    var head: String?
    var dirty: Bool?
}

struct PendingAnswer: Codable {
    var answer: String?
    var owner: String?
    var status: String?
}

struct Usage: Codable {
    var tokens_in: Int?
    var tokens_out: Int?
    var cost: Double?
    var models: [ModelUsage]?
}

struct ModelUsage: Codable {
    var model: String?
    var family: String?
    var share: Double?
}

struct NextMilestone: Codable {
    var phase: String?
    var status: String?
    var milestone: String?
}

// MARK: - Display helpers (shared by the GUI and --self-test)

enum Health {
    case green, yellow, red, gray
}

let canonicalPhases = ["inspect", "define", "research", "decide", "roadmap", "plan", "build", "ship"]

extension ProjectStatus {
    var displayProject: String { project ?? "?" }
    var displayPhase: String { phase ?? "?" }
    var displayStatus: String { status ?? "?" }
    var isShipped: Bool { phase == "shipped" }
    var done: Int { tasks_done ?? 0 }
    var total: Int { tasks_total ?? 0 }
    var answers: [PendingAnswer] { pending_answers ?? [] }
    var isDirty: Bool { git?.dirty ?? false }
    var attentionItems: [AttentionItem] { attention ?? [] }

    /// Server-reported health ("green" | "amber" | "red"), nil on older daemons.
    var serverHealth: Health? {
        switch health {
        case "red": return .red
        case "amber": return .yellow
        case "green": return .green
        default: return nil
        }
    }

    /// Local fallback when the server does not report health.
    var derivedHealth: Health {
        if status == "blocked" { return .red }
        if !answers.isEmpty || isDirty { return .yellow }
        return .green
    }

    var effectiveHealth: Health { serverHealth ?? derivedHealth }

    /// Sort rank: red first, then amber, then green.
    var severity: Int {
        switch effectiveHealth {
        case .red: return 0
        case .yellow: return 1
        default: return 2
        }
    }

    /// Green projects that are shipped or have no incomplete tasks.
    var isQuiet: Bool { effectiveHealth == .green && (isShipped || done >= total) }

    /// "gsd-path-forensics" -> "FORENSICS". Raw id is kept for copy actions.
    var nextSkillDisplay: String? {
        next_skill.map(skillDisplayName)
    }
}

func skillDisplayName(_ raw: String) -> String {
    var s = raw
    if s.hasPrefix("gsd-path-") { s = String(s.dropFirst("gsd-path-".count)) }
    return s.uppercased()
}

func healthName(_ h: Health) -> String {
    switch h {
    case .green: return "green"
    case .yellow: return "amber"
    case .red: return "red"
    case .gray: return "gray"
    }
}

/// 412000 -> "412k", 1500000 -> "1.5M"
func fmtTokens(_ n: Int) -> String {
    if n >= 1_000_000 { return String(format: "%.1fM", Double(n) / 1_000_000) }
    if n >= 1_000 { return "\(n / 1_000)k" }
    return String(n)
}

/// 3480 -> "58m", 273600 -> "3d 4h", 57600 -> "16h"
func fmtDuration(_ seconds: Double) -> String {
    let s = Int(seconds)
    if s < 60 { return "\(s)s" }
    let days = s / 86400, hours = (s % 86400) / 3600, mins = (s % 3600) / 60
    if days > 0 { return hours > 0 ? "\(days)d \(hours)h" : "\(days)d" }
    if hours > 0 { return "\(hours)h" }
    return "\(mins)m"
}
