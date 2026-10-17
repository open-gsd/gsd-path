// The project page: facts strip, phase bar, current milestone, milestones and usage.
// The same mapping as projectPage() in the daemon dashboard (serve.py).
import {
  ago, DASH, duration, healthOf, int, milestoneStack, money, phaseCells, phasesOf, reasons, shortTime, spendCell,
  stateLabel, stateOf, tokens,
} from "./status";
import { runtimePending } from "./board";
import type { OpResult, ProjectSetup } from "./skills";
import type { Cell, Milestone, Project } from "./status";

export function facts(p: Project, now: number): [string, string][] {
  const git = p.git ?? {};
  const matched = !!p.spend?.turns;
  return [
    ["State", stateLabel(p)],
    ["Health", [healthOf(p), reasons(p)].filter(Boolean).join(" · ")],
    ["Milestone", milestoneStack(p).cur.number],
    ["Branch", git.branch || p.branch || DASH],
    ["Head", git.head ? git.head.slice(0, 7) + (git.dirty ? " · dirty" : "") : DASH],
    ...(p.integration ? [["Integration", p.integration] as [string, string]] : []),
    ["Updated", ago(p.last_activity_iso, now)],
    ["Cost", matched ? money(p.spend!.cost) : DASH],
    ["Turns", matched ? int(p.spend!.turns!) : DASH],
  ];
}

/** The phase bar. A phase entered twice shows its first date; the current phase shows its last. */
export function phaseTrack(p: Project): { label: string; date: string; state: Cell }[] {
  const log = p.phase_log ?? [];
  const cells = phaseCells(p);
  return phasesOf(p).map((label, k) => {
    const entries = log.filter((entry) => entry.phase === label);
    const entry = label === p.phase ? entries[entries.length - 1] : entries[0];
    return { label, date: (entry?.date ?? "").slice(5), state: cells[k] };
  });
}

export type NowBox = {
  blocked: boolean; title: string; line: string; goal: string | null; intent: string | null;
  percent: number | null; count: string; waves: { state: Cell; text: string }[];
  criteria: string | null; verify: { result: string; at: string } | null; reason: string | null;
};

/** The current milestone card. A shipped project has none. */
export function nowBox(p: Project): NowBox | null {
  const state = stateOf(p);
  if (state === "shipped") return null;
  const { cur } = milestoneStack(p);
  const done = p.tasks_done ?? 0, total = p.tasks_total ?? 0;
  const entered = (p.phase_log ?? []).filter((entry) => entry.phase === p.phase).pop();
  const when = [entered ? `entered ${entered.phase} ${entered.date}` : null, duration(p.time_in_phase_s)].filter(Boolean).join(" · ");
  const allDone = total > 0 && done >= total;
  const waves = Object.entries(p.waves ?? {}).map(([n, name]) => [Number(n), name] as const).sort((a, b) => a[0] - b[0]);
  const criteria = p.criteria ?? [];
  const last = p.ledger?.[0];
  return {
    blocked: state === "blocked",
    title: `${cur.number} ${cur.slug}`,
    line: [p.phase || "no phase", p.current_wave != null ? `wave ${p.current_wave}` : null].filter(Boolean).join(" · "),
    goal: cur.goal ?? null,
    intent: p.intent ?? null,
    percent: total ? Math.round((100 * done) / total) : null,
    count: total ? `${done} of ${total} tasks${when ? " · " + when : ""}` : `${when ? when + " · " : ""}no tasks yet`,
    waves: waves.map(([n, name]) => ({
      state: p.current_wave != null ? (n < p.current_wave ? "done" : n === p.current_wave ? "now" : "todo") : allDone ? "done" : "todo",
      text: `wave ${n} ${name}`,
    })),
    criteria: criteria.length ? `${criteria.filter((c) => c.verdict === "met").length} of ${criteria.length} criteria met` : null,
    verify: last ? { result: last.result || "unknown", at: shortTime(last.recorded_at) } : null,
    reason: state === "blocked" ? p.workflow?.reason || null : null,
  };
}

export type MilestoneRow = {
  kind: "done" | "now" | "todo"; blocked: boolean; number: string; slug: string; goal: string | null; meta: string;
  status: string; tasks: string; usage: string; tokens: string | null;
};

const manifestMeta = (m: Milestone) => {
  const mf = m.manifest ?? {};
  return [
    mf.tasks_total != null ? `${mf.tasks_done} of ${mf.tasks_total} tasks` : null,
    mf.waves != null ? `${mf.waves} waves` : null,
    mf.cycles_avg != null ? `${mf.cycles_avg} review cycles avg` : null,
    m.integrated ? "integrated " + m.integrated.slice(0, 7) : null,
    mf.carried ? `${mf.carried} rulings carried` : null,
    mf.verdict || null,
  ];
};
const shippedOn = (m: Milestone) => (m.manifest?.shipped ? "shipped " + m.manifest.shipped : m.status || "shipped");

export function milestoneRows(p: Project): MilestoneRow[] {
  const { before, cur, after } = milestoneStack(p), state = stateOf(p);
  const slots = p.spend?.milestones ?? {};
  const row = (m: Milestone, kind: MilestoneRow["kind"], status: string): MilestoneRow => {
    const slot = slots[m.number];
    const tasks = m.manifest?.tasks_total ?? (kind === "now" && p.tasks_total ? p.tasks_total : null);
    const spend = spendCell(slot);
    return {
      kind, blocked: kind === "now" && state === "blocked", number: m.number, slug: m.slug, goal: m.goal ?? null,
      meta: [...(kind === "done" ? manifestMeta(m) : []), m.depends?.length ? `after ${m.depends.join(", ")}` : null].filter(Boolean).join(" · "),
      status, tasks: tasks != null ? String(tasks) : DASH,
      usage: slot?.turns ? [slot.cost != null ? spend.cost : null, spend.turns].filter(Boolean).join(" · ") : DASH,
      tokens: slot?.turns && slot.tokens != null ? `${tokens(slot.tokens)} tokens` : null,
    };
  };
  return [
    ...before.map((m) => row(m, "done", shippedOn(m))),
    state === "shipped" ? row(cur, "done", shippedOn(cur)) : row(cur, "now", stateLabel(p)),
    ...after.map((m) => row(m, "todo", [m.phase, m.status || "planned"].filter(Boolean).join(" · "))),
  ];
}

/** Totals from matched host sessions, or null when none matched. */
export function usageTiles(p: Project): [string, string][] | null {
  const sp = p.spend;
  if (!sp?.turns) return null;
  const cached = sp.tokens_cached ?? 0, inputs = (sp.tokens_in ?? 0) + cached;
  const timed = sp.timed_turns ? sp.duration_s ?? 0 : null;
  return [
    ["Cost", money(sp.cost)], ["Turns", int(sp.turns)], ["Prompts", int(sp.prompts ?? 0)],
    ["Tokens in", tokens(sp.tokens_in ?? 0)], ["Cached", tokens(cached)], ["Tokens out", tokens(sp.tokens_out ?? 0)],
    ["Cache hit", inputs ? Math.round((100 * cached) / inputs) + "%" : DASH],
    ["Agent time", duration(timed) ?? DASH],
    ["Cost / turn", sp.cost != null && sp.priced_turns ? money(sp.cost / sp.priced_turns) : DASH],
    ["Time / turn", timed != null ? Math.round(timed / sp.timed_turns!) + "s" : DASH],
  ];
}

export type SetupRun = "update" | "runtime-restore" | "hooks-init" | "hooks-refresh" | "doctor" | "env";
export type SetupRow = {
  key: "runtime" | "hooks" | "skills" | "doctor" | "env"; label: string; value: string; sub: string;
  /** Shows the "Up to date" pill in place of a button. */
  ok: boolean; action: { label: string; primary: boolean; run: SetupRun } | null;
};

/** The "Setup in this project" card. Without a plugin status entry, only the rows that need none. */
export function setupRows(setup: ProjectSetup | undefined, latest: string | null, doctor: OpResult | null, names: Record<string, string>): SetupRow[] {
  const quiet = (label: string, run: SetupRun) => ({ label, primary: false, run });
  const rows: SetupRow[] = [];
  if (setup) {
    const pending = runtimePending(setup, latest);
    rows.push(!setup.runtime ? {
      key: "runtime", label: "Runtime", value: setup.runtime_version || "Not installed", ok: false,
      sub: setup.runtime_version ? "The runtime files are missing." : "This project has no Path runtime.",
      action: setup.runtime_version ? quiet("Restore", "runtime-restore") : null,
    } : {
      key: "runtime", label: "Runtime", value: setup.runtime_version || "No version stamp", ok: !pending,
      sub: pending ? "Newer runtime available" : "Guard hooks are kept on update",
      action: pending ? { label: `Update to ${latest}`, primary: true, run: "update" } : null,
    });
    rows.push(setup.hooks ? {
      key: "hooks", label: "Guard hooks", value: "Installed", sub: "pre-commit, commit-msg, pre-push", ok: false,
      action: quiet("Refresh", "hooks-refresh"),
    } : {
      key: "hooks", label: "Guard hooks", value: "None", ok: false,
      sub: "Edits to archived work and unapproved ship commits are not blocked.",
      action: { label: "Add guards", primary: true, run: "hooks-init" },
    });
    rows.push(setup.local_skills.length ? {
      key: "skills", label: "Skills", value: setup.local_skills.map((id) => names[id] ?? id).join(", "),
      sub: "Project copies in this repository.", ok: false, action: null,
    } : {
      key: "skills", label: "Skills", value: "Global only", sub: "Agents read the shared install. No project copies.", ok: false, action: null,
    });
  }
  rows.push({
    key: "doctor", label: "Health check", value: doctor ? doctorReport(doctor).summary : "Not run yet",
    sub: "Read-only. It changes nothing.", ok: false, action: quiet(doctor ? "Run again" : "Run", "doctor"),
  });
  rows.push({ key: "env", label: "Environment", value: ".env files", sub: "Variables for this project.", ok: false, action: quiet("Edit…", "env") });
  return rows;
}

/** The doctor output. `ok: false` means findings, not a crash; they are in `error`. */
export function doctorReport(result: OpResult): { ok: boolean; summary: string; lines: { kind: "note" | "line" | "error"; text: string }[] } {
  const split = (text: string | null | undefined) => (text ?? "").split("\n").map((line) => line.trim()).filter(Boolean);
  return {
    ok: result.ok, summary: result.ok ? "Passed" : "Findings",
    lines: [
      ...split(result.stdout_tail).map((line) => line.startsWith("note:")
        ? { kind: "note" as const, text: line.slice(5).trim() } : { kind: "line" as const, text: line }),
      ...split(result.error).map((text) => ({ kind: "error" as const, text })),
    ],
  };
}

/** One member from the `members` project operation. */
export type Member = {
  name: string; checkout: string; remote: string; integration: string;
  marker: { current: boolean; reason: string | null }; hooks: boolean;
};
type Pill = { label: string; tone: "ok" | "warn" | "bad" };
export type MemberRow = {
  name: string; checkout: string; watched: boolean; integration: string; reason: string | null;
  marker: Pill; hooks: Pill; actions: ("repair" | "hooks")[];
};

/** The "Member repositories" table. A watched member links to its own project page. */
export const memberRows = (members: Member[], watched: string[]): MemberRow[] => members.map((member) => ({
  name: member.name, checkout: member.checkout, watched: watched.includes(member.checkout), integration: member.integration,
  reason: member.marker.current ? null : member.marker.reason,
  marker: member.marker.current ? { label: "Marker ok", tone: "ok" } : { label: "Marker stale", tone: "bad" },
  hooks: member.hooks ? { label: "Member hooks installed", tone: "ok" } : { label: "No member hooks", tone: "warn" },
  actions: [...(member.marker.current ? [] : ["repair" as const]), ...(member.hooks ? [] : ["hooks" as const])],
}));
