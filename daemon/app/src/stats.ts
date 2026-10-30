// The Stats page: turns the daemon's GET /api/stats payload into what the charts show.
// A chart with no data is a reason text, never a zero and never an empty axis.
import { t } from "./i18n";
import { statsHash } from "./route";
import { duration, idOf, labelOf, money, PHASES, shortDate, tokens } from "./status";
import type { Project } from "./status";

export type Day = { date: string; tokens: number; turns: number; cost: number | null };
export type VerifyRun = { command?: string; commit?: string; result?: string; recorded_at?: string; project?: string };
type Missing = "days" | "phases" | "waves" | "verify";
export type StatsPayload = {
  scope: string | null;
  days: Day[] | null;
  unpriced: string[];
  phases: { phase: string; seconds: number }[] | null;
  waves: { wave: number; total: number; done: number }[] | null;
  verify: VerifyRun[] | null;
  missing: Partial<Record<Missing, string>>;
};

/** A bar with `percent: null` is a blank slot: no sessions, or no price, on that day. */
export type Bar = { date: string; percent: number | null; title: string };
export type Chart = { total: string; peak: string; bars: Bar[]; first: string; last: string };

// The design shows "Last 14 days" with 14 bars.
const WINDOW_DAYS = 14;
const RELOAD_MS = 60_000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const reason = (payload: StatsPayload, key: Missing) => payload.missing[key] || t("stats.noDataRecorded");
/** "2026-09-29" → "Sep 29". */
const dayLabel = (date: string) => `${MONTHS[Number(date.slice(5, 7)) - 1]} ${Number(date.slice(8, 10))}`;

/** The 14 dates that end at `end`, oldest first. */
function windowDates(end: string): string[] {
  const last = Date.parse(end + "T00:00:00Z");
  return Array.from({ length: WINDOW_DAYS }, (_, index) =>
    new Date(last - (WINDOW_DAYS - 1 - index) * 86_400_000).toISOString().slice(0, 10));
}

/** One bar chart over the window. `value` is null for a day that has no number; `blank` says why. */
function barChart(payload: StatsPayload, end: string | null, value: (day: Day) => number | null,
  text: (n: number) => string, unit: string, detail: (day: Day) => string, blank: string, none: string): Chart | string {
  const days = payload.days;
  if (!days?.length) return reason(payload, "days");
  const dates = windowDates(end ?? days[days.length - 1].date);
  const byDate = new Map(days.map((day) => [day.date, day]));
  const inWindow = dates.map((date) => byDate.get(date));
  if (!inWindow.some(Boolean)) return t("stats.noSessionsWindow", { n: WINDOW_DAYS });
  const values = inWindow.map((day) => (day ? value(day) : null));
  const known = values.filter((n): n is number => n != null);
  if (!known.length) return none;
  const peak = Math.max(...known);
  const at = dates[values.indexOf(peak)];
  return {
    total: text(known.reduce((sum, n) => sum + n, 0)) + unit,
    peak: t("stats.peakOf", { value: text(peak), date: dayLabel(at) }),
    first: dayLabel(dates[0]), last: dayLabel(dates[WINDOW_DAYS - 1]),
    bars: dates.map((date, index) => {
      const day = inWindow[index], n = values[index];
      const note = !day ? t("stats.noSessions") : n == null ? blank : detail(day);
      return { date, percent: n == null ? null : peak ? Math.round((100 * n) / peak) : 0, title: `${dayLabel(date)} · ${note}` };
    }),
  };
}

/** Tokens per day. `end` is today's date as the daemon writes it; without it the last recorded day. */
export const tokenChart = (payload: StatsPayload, end: string | null) => barChart(payload, end,
  (day) => day.tokens, tokens, " " + t("stats.tokensUnit"), (day) => `${tokens(day.tokens)} ${t("stats.tokensUnit")} · ${day.turns} ${t("stats.turnsUnit")}`, "", t("stats.noDataRecorded"));

/** Cost per day. A day whose models have no price has no bar and adds nothing to the total. */
export const costChart = (payload: StatsPayload, end: string | null) => barChart(payload, end,
  (day) => day.cost, money, "", (day) => money(day.cost), t("stats.noPriceShort"), t("stats.noPriceLong"));

export function unpricedNote(unpriced: string[]): string | null {
  if (!unpriced.length) return null;
  return t(unpriced.length === 1 ? "stats.unpricedOne" : "stats.unpricedMany", { models: unpriced.join(t("list.separator")) });
}

export type PhaseRow = { label: string; value: string; percent: number | null };

/** The card's phases in order (GSD Path's eight by default), then any other recorded phase. No record: "not yet", no bar. */
export function phaseRows(payload: StatsPayload, order: string[] = PHASES): PhaseRow[] | string {
  const phases = payload.phases;
  if (!phases?.length) return reason(payload, "phases");
  const seconds = new Map(phases.map((item) => [item.phase, item.seconds]));
  const peak = Math.max(...seconds.values());
  const names = [...order, ...phases.map((item) => item.phase).filter((phase) => !order.includes(phase))];
  return names.map((label) => {
    const spent = seconds.get(label);
    if (spent == null) return { label, value: t("stats.notYet"), percent: null };
    return { label, value: duration(spent) ?? "", percent: peak ? Math.round((100 * spent) / peak) : 0 };
  });
}

export type WaveRow = { label: string; cells: boolean[]; value: string };

/** One row per wave; a cell is true for a done task. `names` is the project's wave names. */
export function waveRows(payload: StatsPayload, names: Record<string, string> | undefined): WaveRow[] | string {
  if (!payload.waves?.length) return reason(payload, "waves");
  return payload.waves.map(({ wave, total, done }) => ({
    label: [t("project.wave", { n: wave }), names?.[wave]].filter((part) => part != null && part !== "").join(" "),
    cells: Array.from({ length: total }, (_, index) => index < done),
    value: `${done}/${total}`,
  }));
}

export type VerifyChart = { total: string; squares: { pass: boolean; title: string }[] };

/** Verify runs in the daemon's order (oldest first). Only "pass" is a pass. */
export function verifyChart(payload: StatsPayload): VerifyChart | string {
  if (!payload.verify?.length) return reason(payload, "verify");
  const squares = payload.verify.map((run) => ({
    pass: run.result === "pass",
    title: [run.result, run.project, run.command, (run.commit ?? "").slice(0, 7), shortDate(run.recorded_at)].filter(Boolean).join(" · "),
  }));
  const passed = squares.filter((square) => square.pass).length;
  return { total: `${passed} ${t("stats.pass")} · ${squares.length - passed} ${t("stats.fail")}`, squares };
}

/** The scope switch: All projects, then one entry per project. */
export function scopes(projects: Project[], root: string | null): { label: string; href: string; current: boolean }[] {
  return [{ label: t("stats.allProjects"), href: statsHash(null), current: root === null },
    ...projects.map((p) => ({ label: labelOf(p), href: statsHash(idOf(p)), current: idOf(p) === root }))];
}

/** Load when the scope changes; for the same scope at most once per minute. */
export const reloadDue = (last: { root: string | null; at: number } | null, root: string | null, now: number) =>
  !last || last.root !== root || now - last.at >= RELOAD_MS;
