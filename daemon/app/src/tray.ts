// The tray popover: the status line, the "Needs attention" cards and the project list.
import { healthTone, idOf, milestoneStack, nameOf, phaseCells, reasons, sortProjects, stateLabel, stateOf } from "./status";
import type { Cell, Project, Status, Tone } from "./status";

export function trayStatus(status: Status | null, offline: boolean): { tone: Tone; text: string } {
  if (offline || !status) return { tone: "bad", text: "Stopped" };
  const count = status.projects.length;
  return { tone: "ok", text: `${count} ${count === 1 ? "project" : "projects"}` };
}

const SEVERITY: Record<Tone, number> = { bad: 0, warn: 1, ok: 2 };

/** Projects with attention items: red first, then amber, then by name. */
export function attentionCards(projects: Project[]): { root: string; name: string; reason: string }[] {
  return projects
    .filter((p) => p.attention?.length)
    .sort((a, b) => SEVERITY[healthTone(a)] - SEVERITY[healthTone(b)] || nameOf(a).localeCompare(nameOf(b)))
    .map((p) => ({ root: idOf(p), name: nameOf(p), reason: reasons(p) || stateLabel(p) }));
}

export type TrayRow = { root: string; name: string; tone: Tone; line: string; cells: Cell[]; quiet: boolean };

export function trayRows(projects: Project[]): TrayRow[] {
  return sortProjects(projects).map((p) => {
    const shipped = stateOf(p) === "shipped";
    const progress = p.tasks_total ? `${p.tasks_done ?? 0} of ${p.tasks_total} tasks` : null;
    return {
      root: idOf(p), name: nameOf(p), tone: healthTone(p), cells: phaseCells(p), quiet: shipped,
      line: [milestoneStack(p).cur.number, ...(shipped ? ["shipped"] : [p.phase || "no phase", progress])].filter(Boolean).join(" · "),
    };
  });
}
