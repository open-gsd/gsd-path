// The daemon's /status payload (daemon/README.md, "/status schema") and the
// derivations every view shares. The daemon decides state and health; this
// module only formats them. Missing values stay missing: a dash, never zero.

export type Milestone = {
  number: string; slug: string; status?: string | null; archive?: string | null; goal?: string | null;
  phase?: string | null; depends?: string[]; integrated?: string | null;
  manifest?: { shipped?: string; verdict?: string; waves?: number; tasks_done?: number; tasks_total?: number;
    cycles_avg?: number; carried?: number } | null;
};
export type SpendSlot = { turns?: number; tokens?: number; cost?: number | null };
export type Spend = SpendSlot & {
  prompts?: number; tokens_in?: number; tokens_cached?: number; tokens_out?: number;
  priced_turns?: number; duration_s?: number; timed_turns?: number; unpriced?: string[];
  models?: { model: string; host?: string; turns: number; tokens: number; cost: number | null }[];
  agents?: { agent: string; models: string[]; turns: number; tokens: number; cost: number | null; duration_s?: number }[];
  milestones?: Record<string, SpendSlot>;
  recent?: { at: string; agent: string; model?: string | null; tokens_in: number; tokens_cached: number;
    tokens_out: number; cost: number | null; duration_s?: number | null }[];
};
export type Project = {
  root: string;
  /** Card id: the root for GSD Path, "<root>::<flavor>" for gsd-pi and gsd-core. Older daemons omit it. */
  id?: string; flavor?: string;
  /** The phase strip; gsd-pi and gsd-core cards send their own. Missing means PHASES. */
  phases?: string[] | null;
  project?: string | null; repository?: string | null; project_root?: string | null; worktree_root?: string | null;
  milestone?: string | null; phase?: string | null; status?: string | null; branch?: string | null;
  integration?: string | null;
  tasks?: { id: string; title: string | null; wave: number | null; status: string | null; files: string[] }[];
  tasks_done?: number; tasks_total?: number; current_wave?: number | null; waves?: Record<string, string>;
  roadmap_milestones?: Milestone[];
  next_milestone?: { milestone?: string | null; status?: string | null; phase?: string | null } | null;
  phase_log?: { phase: string; date: string }[];
  vision?: string | null; intent?: string | null; lesson?: string | null;
  git?: { branch?: string | null; head?: string | null; dirty?: boolean | null } | null;
  pending_answers?: Record<string, unknown>[];
  handoff?: { outcome?: string; next?: string } | null;
  workflow?: { state: "active" | "blocked" | "shipped" | "unverified" | "idle"; label: string; reason?: string };
  last_activity_iso?: string | null;
  reviews?: { file: string; kind: string; verdict: string | null; cycle: number | null; depth: string | null; note: string | null }[];
  criteria?: { id: string | null; text: string | null; verdict: string | null }[] | null;
  ledger?: { command?: string; commit?: string; result?: string; recorded_at?: string }[];
  answers?: Record<string, unknown>[];
  time_in_phase_s?: number | null;
  usage?: { by_phase?: Record<string, unknown>[]; by_task?: Record<string, unknown>[]; [key: string]: unknown } | null;
  spend?: Spend | null;
  health?: string;
  attention?: { kind?: string; label?: string; ref?: string | null }[];
};
export type Status = {
  generated_at: string | null;
  projects: Project[];
  daemon?: { poll_seconds?: number };
  plugin?: {
    latest?: string | null;
    update_available?: boolean;
    hosts?: Record<string, { installed: boolean; version: string | null }>;
  };
};

export type Tone = "ok" | "warn" | "bad";
export type Cell = "done" | "now" | "blocked" | "todo";

export const DASH = "—";
// Same order as PHASES in the daemon dashboard (serve.py).
export const PHASES = ["inspect", "define", "research", "decide", "roadmap", "plan", "build", "ship"];

export const nameOf = (p: Project) => p.repository || p.project || p.root;
export const idOf = (p: Project) => p.id || p.root;
/** The framework badge; GSD Path cards have none. */
export const flavorOf = (p: Project) => (p.flavor && p.flavor !== "gsd-path" ? p.flavor : null);
export const stateOf = (p: Project) => p.workflow?.state ?? "unverified";
export const stateLabel = (p: Project) => p.workflow?.label ?? "Unverified";
/** Health comes from the daemon; older payloads get a local guess. */
export const healthOf = (p: Project) => p.health || (p.status === "blocked" ? "red" : "green");
export const healthTone = (p: Project): Tone => ({ red: "bad", amber: "warn" } as Record<string, Tone>)[healthOf(p)] ?? "ok";
/** The daemon's attention labels: why a project is not green. An idle project has none, so it shows why it has no status. */
export const reasons = (p: Project) => (p.attention ?? []).map((item) => item.label).filter(Boolean).join(" · ")
  || (stateOf(p) === "idle" && p.workflow?.reason) || "";

export const phasesOf = (p: Project) => p.phases ?? PHASES;

/** One cell per phase: done before the current phase; a shipped project fills all. */
export function phaseCells(p: Project): Cell[] {
  const state = stateOf(p), phases = phasesOf(p);
  const index = state === "shipped" ? phases.length : phases.indexOf(p.phase ?? "");
  return phases.map((_, k) => (k < index ? "done" : k > index ? "todo" : state === "blocked" ? "blocked" : "now"));
}

const isDone = (m: Milestone) => m.status === "shipped" || m.status === "archived" || !!m.archive;

/** Milestones before, at and after the current one, from ROADMAP.md, STATE.md and next/STATE.md. */
export function milestoneStack(p: Project): { before: Milestone[]; cur: Milestone; after: Milestone[] } {
  const roadmap = p.roadmap_milestones ?? [];
  const index = roadmap.findIndex((m) => m.slug === p.milestone);
  const fromBranch = (p.branch ?? "").match(/M\d{3,}/);
  const cur = index >= 0 ? roadmap[index] : { number: fromBranch ? fromBranch[0] : "now", slug: p.milestone || "no milestone" };
  const before = index >= 0 ? roadmap.slice(0, index) : roadmap.filter(isDone);
  const after = index >= 0 ? roadmap.slice(index + 1) : roadmap.filter((m) => !isDone(m));
  const next = p.next_milestone;
  if (next?.milestone && next.milestone !== cur.slug && !after.some((m) => m.slug === next.milestone)) {
    after.push({ number: "next", slug: next.milestone, status: next.status || "planned", phase: next.phase });
  }
  return { before, cur, after };
}

export const int = (n: number) => n.toLocaleString("en-US");
export const money = (value: number | null | undefined) => value == null ? DASH
  : "$" + value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const tokens = (n: number) => n >= 1e9 ? (n / 1e9).toFixed(2) + "B" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M"
  : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n);

export function ago(iso: string | null | undefined, now: number): string {
  const then = Date.parse(iso ?? "");
  if (Number.isNaN(then)) return DASH;
  const s = Math.max(0, (now - then) / 1000);
  return s < 60 ? "just now" : s < 3600 ? Math.floor(s / 60) + "m ago"
    : s < 86400 ? Math.floor(s / 3600) + "h ago" : Math.floor(s / 86400) + "d ago";
}

export function duration(seconds: number | null | undefined): string | null {
  if (seconds == null) return null;
  const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600), m = Math.floor((seconds % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

/** hh:mm:ss of an ISO time, in the local time zone. */
export function clock(iso: string | null | undefined): string | null {
  const at = new Date(iso ?? "");
  return Number.isNaN(at.getTime()) ? null : at.toLocaleTimeString("en-GB");
}

/** The time of day inside an ISO text, as the daemon wrote it. */
export const shortTime = (iso: string | null | undefined) => (iso && iso.length >= 19 ? iso.slice(11, 19) : iso ?? "");
/** "2026-09-29T03:58:11+00:00" → "2026-09-29 03:58". */
export const shortDate = (iso: string | null | undefined) => (iso ?? "").slice(0, 16).replace("T", " ");

/** Cost and turns of matched host sessions. No session: a dash and the reason. */
export function spendCell(slot: SpendSlot | null | undefined): { cost: string; turns: string } {
  if (!slot?.turns) return { cost: DASH, turns: "No matched sessions" };
  return { cost: money(slot.cost), turns: `${int(slot.turns)} turns` };
}

/** The daemon's own scan interval; 5 seconds is its default. */
export const pollMs = (status: Status | null) => (status?.daemon?.poll_seconds ?? 5) * 1000;

const STATE_RANK = { blocked: 0, unverified: 1, active: 1, shipped: 2, idle: 2 };

/** Board order: blocked, then in progress, then shipped; by name within each. */
export const sortProjects = (projects: Project[]) => [...projects].sort((a, b) =>
  STATE_RANK[stateOf(a)] - STATE_RANK[stateOf(b)] || nameOf(a).localeCompare(nameOf(b)));
