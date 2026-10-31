// The project page: facts strip, phase bar, current milestone, milestones and usage.
// The same mapping as projectPage() in the daemon dashboard (serve.py).
import { t } from "./i18n";
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
    [t("facts.state"), stateLabel(p)],
    [t("facts.health"), [healthOf(p), reasons(p)].filter(Boolean).join(" · ")],
    [t("facts.milestone"), milestoneStack(p).cur.number],
    [t("facts.branch"), git.branch || p.branch || DASH],
    [t("facts.head"), git.head ? git.head.slice(0, 7) + (git.dirty ? t("facts.dirty") : "") : DASH],
    ...(p.integration ? [[t("facts.integration"), p.integration] as [string, string]] : []),
    [t("facts.updated"), ago(p.last_activity_iso, now)],
    [t("usage.cost"), matched ? money(p.spend!.cost) : DASH],
    [t("usage.turns"), matched ? int(p.spend!.turns!) : DASH],
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
  const when = [entered ? t("project.enteredPhase", { phase: entered.phase, date: entered.date }) : null, duration(p.time_in_phase_s)].filter(Boolean).join(" · ");
  const allDone = total > 0 && done >= total;
  const waves = Object.entries(p.waves ?? {}).map(([n, name]) => [Number(n), name] as const).sort((a, b) => a[0] - b[0]);
  const criteria = p.criteria ?? [];
  const last = p.ledger?.[0];
  return {
    blocked: state === "blocked",
    title: `${cur.number} ${cur.slug}`,
    line: [p.phase || t("tray.noPhase"), p.current_wave != null ? t("project.wave", { n: p.current_wave }) : null].filter(Boolean).join(" · "),
    goal: cur.goal ?? null,
    intent: p.intent ?? null,
    percent: total ? Math.round((100 * done) / total) : null,
    count: total
      ? t("tray.progress", { done, total }) + (when ? " · " + when : "")
      : (when ? when + " · " : "") + t("project.noTasks"),
    waves: waves.map(([n, name]) => ({
      state: p.current_wave != null ? (n < p.current_wave ? "done" : n === p.current_wave ? "now" : "todo") : allDone ? "done" : "todo",
      text: `wave ${n} ${name}`,
    })),
    criteria: criteria.length ? t("project.criteriaMet", { met: criteria.filter((c) => c.verdict === "met").length, total: criteria.length }) : null,
    verify: last ? { result: last.result || t("project.unknown"), at: shortTime(last.recorded_at) } : null,
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
    mf.tasks_total != null ? t("tray.progress", { done: mf.tasks_done, total: mf.tasks_total }) : null,
    mf.waves != null ? t("project.wavesMeta", { n: mf.waves }) : null,
    mf.cycles_avg != null ? t("project.cyclesAvg", { n: mf.cycles_avg }) : null,
    m.integrated ? t("project.integrated", { sha: m.integrated.slice(0, 7) }) : null,
    mf.carried ? t("project.carried", { n: mf.carried }) : null,
    mf.verdict || null,
  ];
};
const shippedOn = (m: Milestone) => m.manifest?.shipped
  ? t("project.shippedOn", { date: m.manifest.shipped })
  : m.status || t("state.shipped");

export function milestoneRows(p: Project): MilestoneRow[] {
  const { before, cur, after } = milestoneStack(p), state = stateOf(p);
  const slots = p.spend?.milestones ?? {};
  const row = (m: Milestone, kind: MilestoneRow["kind"], status: string): MilestoneRow => {
    const slot = slots[m.number];
    const tasks = m.manifest?.tasks_total ?? (kind === "now" && p.tasks_total ? p.tasks_total : null);
    const spend = spendCell(slot);
    return {
      kind, blocked: kind === "now" && state === "blocked", number: m.number, slug: m.slug, goal: m.goal ?? null,
      meta: [...(kind === "done" ? manifestMeta(m) : []), m.depends?.length ? t("project.afterDeps", { deps: m.depends.join(t("list.separator")) }) : null].filter(Boolean).join(" · "),
      status, tasks: tasks != null ? String(tasks) : DASH,
      usage: slot?.turns ? [slot.cost != null ? spend.cost : null, spend.turns].filter(Boolean).join(" · ") : DASH,
      tokens: slot?.turns && slot.tokens != null ? t("project.tokensCount", { n: tokens(slot.tokens) }) : null,
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
    [t("usage.cost"), money(sp.cost)], [t("usage.turns"), int(sp.turns)], [t("usage.prompts"), int(sp.prompts ?? 0)],
    [t("usage.tokensIn"), tokens(sp.tokens_in ?? 0)], [t("usage.cached"), tokens(cached)], [t("usage.tokensOut"), tokens(sp.tokens_out ?? 0)],
    [t("usage.cacheHit"), inputs ? Math.round((100 * cached) / inputs) + "%" : DASH],
    [t("usage.agentTime"), duration(timed) ?? DASH],
    [t("usage.costPerTurn"), sp.cost != null && sp.priced_turns ? money(sp.cost / sp.priced_turns) : DASH],
    [t("usage.timePerTurn"), timed != null ? Math.round(timed / sp.timed_turns!) + "s" : DASH],
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
      key: "runtime", label: t("setup.runtime"), value: setup.runtime_version || t("skill.status.notInstalled"), ok: false,
      sub: setup.runtime_version ? t("setup.runtimeMissing") : t("setup.noPathRuntime"),
      action: setup.runtime_version ? quiet(t("setup.restore"), "runtime-restore") : null,
    } : {
      key: "runtime", label: t("setup.runtime"), value: setup.runtime_version || t("skill.noVersionStamp"), ok: !pending,
      sub: pending ? t("setup.newerRuntime") : t("setup.hooksKeptOnUpdate"),
      action: pending ? { label: t("skill.updateTo", { version: latest ?? "" }), primary: true, run: "update" } : null,
    });
    rows.push(setup.hooks ? {
      key: "hooks", label: t("setup.guardHooks"), value: t("skill.status.installed"), sub: "pre-commit, commit-msg, pre-push", ok: false,
      action: quiet(t("setup.refresh"), "hooks-refresh"),
    } : {
      key: "hooks", label: t("setup.guardHooks"), value: t("setup.none"), ok: false,
      sub: t("setup.noGuardsSub"),
      action: { label: t("setup.addGuards"), primary: true, run: "hooks-init" },
    });
    rows.push(setup.local_skills.length ? {
      key: "skills", label: t("nav.skills"), value: setup.local_skills.map((id) => names[id] ?? id).join(t("list.separator")),
      sub: t("setup.projectCopies"), ok: false, action: null,
    } : {
      key: "skills", label: t("nav.skills"), value: t("setup.globalOnly"), sub: t("setup.globalOnlySub"), ok: false, action: null,
    });
  }
  rows.push({
    key: "doctor", label: t("setup.healthCheck"), value: doctor ? doctorReport(doctor).summary : t("setup.notRunYet"),
    sub: t("setup.readOnly"), ok: false, action: quiet(doctor ? t("setup.runAgain") : t("setup.run"), "doctor"),
  });
  rows.push({ key: "env", label: t("setup.environment"), value: t("setup.envFiles"), sub: t("setup.envSub"), ok: false, action: quiet(t("setup.edit"), "env") });
  return rows;
}

/** The doctor output. `ok: false` means findings, not a crash; they are in `error`. */
export function doctorReport(result: OpResult): { ok: boolean; summary: string; lines: { kind: "note" | "line" | "error"; text: string }[] } {
  const split = (text: string | null | undefined) => (text ?? "").split("\n").map((line) => line.trim()).filter(Boolean);
  return {
    ok: result.ok, summary: result.ok ? t("doctor.passed") : t("doctor.findings"),
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
  marker: member.marker.current ? { label: t("member.markerOk"), tone: "ok" } : { label: t("member.markerStale"), tone: "bad" },
  hooks: member.hooks ? { label: t("member.hooksInstalled"), tone: "ok" } : { label: t("member.noHooks"), tone: "warn" },
  actions: [...(member.marker.current ? [] : ["repair" as const]), ...(member.hooks ? [] : ["hooks" as const])],
}));

/** The "Add member" form. `repo` and `visibility` count only for a new GitHub repository. */
export type MemberForm = { name: string; checkout: string; integration: string; create: boolean; repo: string; visibility: string };
export const MEMBER_INTEGRATIONS = ["default", "direct", "pull-request"];
export const MEMBER_VISIBILITIES = ["private", "internal", "public"];
export const emptyMemberForm = (): MemberForm =>
  ({ name: "", checkout: "", integration: "default", create: false, repo: "", visibility: "private" });

/** The member-add request and its confirm text, or the first field to fix. members.py checks the rest. */
export function memberAdd(form: MemberForm): { body: Record<string, string>; confirm: string } | { error: string } {
  const name = form.name.trim(), checkout = form.checkout.trim(), repo = form.repo.trim();
  if (!name) return { error: t("setupCard.memberNeedsName") };
  if (!checkout) return { error: t("setupCard.memberNeedsCheckout") };
  if (!/^([/~]|[A-Za-z]:[\\/])/.test(checkout)) return { error: t("setupCard.memberNeedsFullPath") };
  if (form.create && !/^[^/\s]+\/[^/\s]+$/.test(repo)) return { error: t("setupCard.memberNeedsRepo") };
  const body: Record<string, string> = { name, checkout, integration: form.integration };
  if (!form.create) return { body, confirm: t("setupCard.addExistingText", { name, checkout }) };
  return { body: { ...body, create: repo, visibility: form.visibility },
    confirm: t("setupCard.addCreateText", { name, checkout, repo, visibility: form.visibility }) };
}

/** The form fields a picked folder fills. For a new repository the pick is the parent folder: the clone
 *  goes into a folder named after the repository (or the member). An empty member name takes the folder name. */
export function browsedCheckout(form: MemberForm, picked: string): Partial<MemberForm> {
  const leaf = form.create ? (form.repo.trim().split("/")[1] || form.name.trim()) : "";
  const checkout = leaf ? picked.replace(/[\\/]+$/, "") + "/" + leaf : picked;
  // A picked parent with no clone folder yet names nothing.
  const folder = form.create && !leaf ? "" : checkout.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? "";
  return form.name.trim() || !folder ? { checkout } : { checkout, name: folder };
}
