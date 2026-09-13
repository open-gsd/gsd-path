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

struct MilestoneManifest: Codable {
    var shipped: String?
    var verdict: String?
    var waves: Int?
    var tasks_done: Int?
    var tasks_total: Int?
    var cycles_avg: Double?
    var carried: Int?
}

struct RoadmapMilestone: Codable {
    var number: String?
    var slug: String?
    var status: String?
    var archive: String?
    var goal: String?
    var depends: [String]?
    var integrated: String?
    var manifest: MilestoneManifest?
}

struct PhaseLogEntry: Codable {
    var phase: String?
    var date: String?
}

struct Criterion: Codable {
    var id: String?
    var text: String?
    var verdict: String?
}

struct MilestoneSpend: Codable {
    var turns: Int?
    var tokens: Int?
    var cost: Double?
}

struct Spend: Codable {
    var turns: Int?
    var cost: Double?
    var milestones: [String: MilestoneSpend]?
}

struct ProjectStatus: Codable {
    var root: String?
    var project: String?
    var milestone: String?
    var phase: String?
    var status: String?
    var branch: String?
    var archive: String?
    var roadmap_milestones: [RoadmapMilestone]?
    var phase_log: [PhaseLogEntry]?
    var vision: String?
    var intent: String?
    var lesson: String?
    var criteria: [Criterion]?
    var spend: Spend?
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

// MARK: - Milestone stack (done / here / ahead) for the status board

enum StackKind { case done, now, ahead }

struct StackEntry: Equatable {
    let number: String
    let slug: String
    let kind: StackKind
}

extension ProjectStatus {
    /// "blocked" | "shipped" | "active" — the only states the status board shows.
    var projectState: String {
        if status == "blocked" { return "blocked" }
        if isShipped || status == "shipped" || archive != nil { return "shipped" }
        return "active"
    }
    var stateLabel: String {
        switch projectState {
        case "blocked": return "Blocked"
        case "shipped": return "Shipped"
        default: return "In \(phase ?? "progress")"
        }
    }
    /// Sort rank for the board: blocked, then active, then shipped.
    var stateRank: Int { ["blocked": 0, "active": 1, "shipped": 2][projectState] ?? 1 }

    /// Milestones before, at and after the current one, from ROADMAP.md, STATE.md and next/STATE.md.
    var milestoneStack: [StackEntry] {
        let roadmap = roadmap_milestones ?? []
        let isDone: (RoadmapMilestone) -> Bool = { $0.status == "shipped" || $0.status == "archived" || $0.archive != nil }
        let index = roadmap.firstIndex { $0.slug != nil && $0.slug == milestone }
        let before = index.map { Array(roadmap[..<$0]) } ?? roadmap.filter(isDone)
        var after = index.map { Array(roadmap[($0 + 1)...]) } ?? roadmap.filter { !isDone($0) }
        let fromBranch = branch.flatMap { b in b.range(of: #"M\d{3,}"#, options: .regularExpression).map { String(b[$0]) } }
        let number = index.map { roadmap[$0].number ?? "?" } ?? fromBranch ?? "now"
        if let next = next_milestone?.milestone, next != milestone, !after.contains(where: { $0.slug == next }) {
            after.append(RoadmapMilestone(number: "next", slug: next, status: next_milestone?.status, archive: nil))
        }
        return before.map { StackEntry(number: $0.number ?? "?", slug: $0.slug ?? "", kind: .done) }
            + [StackEntry(number: number, slug: milestone ?? "no milestone", kind: .now)]
            + after.map { StackEntry(number: $0.number ?? "?", slug: $0.slug ?? "", kind: .ahead) }
    }

    /// "M001 ✓  M002 ●  M003 ○" — the tray's one-line stack. Blocked shows ■, shipped ✓.
    var stackText: String {
        milestoneStack.map { entry -> String in
            let glyph: String
            switch entry.kind {
            case .done: glyph = "✓"
            case .now: glyph = projectState == "blocked" ? "■" : projectState == "shipped" ? "✓" : "●"
            case .ahead: glyph = "○"
            }
            return "\(entry.number) \(glyph)"
        }.joined(separator: "  ")
    }

    /// "build · wave 2 · 7 of 12 tasks · 3/5 criteria · since 2026-09-10" — where the current milestone is.
    var hereText: String {
        var parts = [phase ?? "no phase"]
        if let wave = current_wave { parts.append("wave \(wave)") }
        parts.append(total > 0 ? "\(done) of \(total) tasks" : "no tasks yet")
        if let criteria = criteria, !criteria.isEmpty {
            parts.append("\(criteria.filter { $0.verdict == "met" }.count)/\(criteria.count) criteria")
        }
        if let since = (phase_log?.first { $0.phase == phase } ?? phase_log?.last)?.date { parts.append("since \(since)") }
        if let spend = currentSpendText { parts.append(spend) }
        return parts.joined(separator: " · ")
    }

    /// "$24.60 · 84 turns" for the current milestone; tokens-only projects show turns alone.
    var currentSpendText: String? {
        let number = (roadmap_milestones ?? []).first { $0.slug != nil && $0.slug == milestone }?.number
            ?? branch.flatMap { b in b.range(of: #"M\d{3,}"#, options: .regularExpression).map { String(b[$0]) } } ?? "now"
        guard let slot = spend?.milestones?[number], let turns = slot.turns, turns > 0 else { return nil }
        var parts: [String] = []
        if let cost = slot.cost { parts.append(String(format: "$%.2f", cost)) }
        parts.append("\(turns) turns")
        return parts.joined(separator: " · ")
    }

    /// The current milestone's goal from ROADMAP.md, if listed.
    var goalText: String? {
        (roadmap_milestones ?? []).first { $0.slug != nil && $0.slug == milestone }?.goal
    }

    /// Eight segments in canonicalPhases order: done before the current phase, now at it; shipped fills all.
    var phaseMeter: [StackKind] {
        let index = projectState == "shipped" ? canonicalPhases.count : canonicalPhases.firstIndex(of: phase ?? "") ?? -1
        return canonicalPhases.indices.map { $0 < index ? .done : $0 == index ? .now : .ahead }
    }

    /// The tray's detail line: "M004 · build · wave 2 · …" while in progress, "M003 shipped 2026-09-06 · 12 tasks" once shipped.
    var trayDetail: String {
        let current = milestoneStack.first { $0.kind == .now }?.number ?? "now"
        switch projectState {
        case "shipped":
            let manifest = (roadmap_milestones ?? []).first { $0.number == current }?.manifest
            return (["\(current) shipped" + (manifest?.shipped.map { " \($0)" } ?? "")]
                    + [manifest?.tasks_total.map { "\($0) tasks" }].compactMap { $0 }).joined(separator: " · ")
        case "blocked": return "\(current) · Blocked · \(hereText)"
        default: return "\(current) · \(hereText)"
        }
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
