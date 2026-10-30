// The tray popover: the status line, the "Needs attention" cards and the project list.
import { t } from "./i18n";
import { healthTone, idOf, labelOf, milestoneStack, nameOf, phaseCells, reasons, sortProjects, stateLabel, stateOf } from "./status";
import type { Cell, Project, Status, Tone } from "./status";

export function trayStatus(status: Status | null, offline: boolean): { tone: Tone; text: string } {
  if (offline || !status) return { tone: "bad", text: t("tray.stopped") };
  const count = status.projects.length;
  return { tone: "ok", text: count === 1 ? t("tray.oneProject") : t("tray.projects", { n: count }) };
}

const SEVERITY: Record<Tone, number> = { bad: 0, warn: 1, ok: 2 };

/** Projects with attention items: red first, then amber, then by name. */
export function attentionCards(projects: Project[]): { root: string; name: string; reason: string }[] {
  return projects
    .filter((p) => p.attention?.length)
    .sort((a, b) => SEVERITY[healthTone(a)] - SEVERITY[healthTone(b)] || nameOf(a).localeCompare(nameOf(b)))
    .map((p) => ({ root: idOf(p), name: labelOf(p), reason: reasons(p) || stateLabel(p) }));
}

export type TrayRow = { root: string; name: string; tone: Tone; line: string; cells: Cell[]; quiet: boolean };

export function trayRows(projects: Project[]): TrayRow[] {
  return sortProjects(projects).map((p) => {
    const shipped = stateOf(p) === "shipped";
    const progress = p.tasks_total ? t("tray.progress", { done: p.tasks_done ?? 0, total: p.tasks_total }) : null;
    return {
      root: idOf(p), name: labelOf(p), tone: healthTone(p), cells: phaseCells(p), quiet: shipped,
      line: [milestoneStack(p).cur.number, ...(shipped ? [t("state.shipped")] : [p.phase || t("tray.noPhase"), progress])].filter(Boolean).join(" · "),
    };
  });
}
