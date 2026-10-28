// The Projects board: filters, search and one row per project.
import { t } from "./i18n";
import { ago, DASH, flavorOf, healthTone, idOf, milestoneStack, nameOf, phaseCells, reasons, sortProjects, spendCell, stateLabel, stateOf } from "./status";
import { isNewer, pendingFrameworks, pendingSkills, targetVersion } from "./skills";
import type { HostInfo, PluginStatus, ProjectSetup } from "./skills";
import type { Cell, Project, Tone } from "./status";

const FILTERS = () => [["all", t("board.filter.all")], ["active", t("board.filter.active")], ["blocked", t("board.filter.blocked")], ["shipped", t("board.filter.shipped")]];

const inFilter = (p: Project, filter: string) => filter === "all" || stateOf(p) === filter;

/** The filter buttons with their counts. Unverified shows only when a project is in that state. */
export function filterCounts(projects: Project[]): { key: string; label: string; count: number }[] {
  const count = (key: string) => projects.filter((p) => inFilter(p, key)).length;
  const all = [...FILTERS(), ["unverified", t("state.unverified")]].map(([key, label]) => ({ key, label, count: count(key) }));
  return all.filter((item) => item.key !== "unverified" || item.count > 0);
}

/** The projects a filter and a search text leave, in board order. */
export function visibleProjects(projects: Project[], filter: string, query: string): Project[] {
  const text = query.trim().toLowerCase();
  return sortProjects(projects).filter((p) => inFilter(p, filter) &&
    [p.repository, p.project, p.root, p.milestone, p.flavor].filter(Boolean).join(" ").toLowerCase().includes(text));
}

export type BoardRow = {
  id: string; root: string; flavor: string | null; name: string; tone: Tone; path: string; number: string; slug: string; cells: Cell[]; phase: string;
  state: string; label: string; note: string; ago: string; tasks: string; cost: string; turns: string;
};

export function boardRow(p: Project, now: number): BoardRow {
  const { cur } = milestoneStack(p);
  return {
    id: idOf(p), root: p.root, flavor: flavorOf(p), name: nameOf(p), tone: healthTone(p),
    path: (p.project_root || p.root) + (p.worktree_root ? ` · ${t("board.worktree")}: ${p.worktree_root}` : ""),
    number: cur.number, slug: cur.slug, cells: phaseCells(p), phase: p.phase || t("board.noPhase"),
    state: stateOf(p), label: stateLabel(p), note: reasons(p), ago: ago(p.last_activity_iso, now),
    tasks: p.tasks_total ? `${p.tasks_done ?? 0}/${p.tasks_total}` : DASH,
    ...spendCell(p.spend),
  };
}

/** A runtime older than the latest release, or an old runtime without a version stamp. */
export const runtimePending = (setup: { runtime?: boolean; runtime_version?: string | null }, latest: string | null) =>
  setup.runtime && !!latest && (!setup.runtime_version || isNewer(latest, setup.runtime_version));

/** The Setup column. Null when the plugin status does not list the project. */
export function setupPill(setup: ProjectSetup | undefined, latest: string | null): { label: string; tone: "ok" | "warn" | "acc" } | null {
  if (!setup) return null;
  if (!setup.runtime) return { label: t("setup.noRuntime"), tone: "warn" };
  if (runtimePending(setup, latest)) return { label: t("setup.runtimeUpdate"), tone: "acc" };
  if (!setup.hooks) return { label: t("setup.noGuards"), tone: "warn" };
  return { label: t("setup.upToDate"), tone: "ok" };
}

/** The banner above the board: only the updates that wait. Null when there are none. */
export function updateBanner(hosts: HostInfo[], plugin: PluginStatus | null, projects: Project[]): { count: number; title: string; text: string } | null {
  if (!plugin) return null;
  const skills = pendingSkills(hosts, plugin).map((row) => t("banner.skillsFor", { name: row.label }));
  // Only GSD Path cards have a runtime; other frameworks in the same folder share it.
  const runtimes = projects.filter((p) => {
    if (flavorOf(p)) return false;
    const setup = plugin.projects.find((item) => item.root === p.root);
    return setup && runtimePending(setup, targetVersion(plugin));
  }).map((p) => t("banner.runtimeFor", { name: nameOf(p) }));
  const items = [...skills, ...runtimes, ...pendingFrameworks(plugin)];
  if (!items.length) return null;
  return {
    count: items.length,
    title: items.length === 1 ? t("banner.oneUpdate") : t("banner.updates", { n: items.length }),
    text: items.join(t("banner.separator")),
  };
}
