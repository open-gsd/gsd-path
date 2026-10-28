// Settings → Updates: the rows and the "Update all" plan, from GET /api/plugin/status.
import { t } from "./i18n";
import { runtimePending } from "./board";
import { isNewer, joinNames, targetVersion, versionParts } from "./skills";
import type { Releases } from "./skills";
import { DASH } from "./status";

export type PluginStatus = {
  latest?: string | null;
  update_available?: boolean;
  error?: string;
  hosts?: Record<string, { installed: boolean; version: string | null; root?: string; skill_dirs?: string[] }>;
  projects?: { root: string; runtime?: boolean; runtime_version?: string | null; hooks?: boolean; contracts?: boolean; local_skills?: string[] }[];
  releases?: Releases;
};
/** The answer of POST /api/plugin/update. */
export type OpResult = { ok: boolean; argv: string[]; stdout_tail: string; error: string | null; source_notice?: string };
export type UpdateStep = { id: string; label: string; body: { scope: "global" } | { scope: "project"; root: string } };
export type UpdateRow = {
  key: string; name: string; sub: string; version: string;
  state: "pending" | "current" | "unknown";
  /** Why the state is unknown; for a pending row, the label of its button when it is not "Update". */
  note: string;
  step: UpdateStep | null;
  /** The id of the action that updates this row, pending or not: its preview and result show under the first row of the group. */
  group: string;
};

const AGENTS: Record<string, string> = {
  codex: "Codex", claude: "Claude Code", grok: "Grok", opencode: "OpenCode", copilot: "GitHub Copilot", qwen: "Qwen Code",
  antigravity: "Antigravity", cursor: "Cursor", zed: "Zed", kiro: "Kiro", kimi: "Kimi Code",
};
// One update refreshes the skills in every agent folder (install.py --update).
const GLOBAL = (): UpdateStep => ({ id: "global", label: t("updates.skillsEveryFolder"), body: { scope: "global" } });

function row(key: string, name: string, sub: string, version: string | null, latest: string | null, step: UpdateStep): UpdateRow {
  const group = step.id;
  const known = versionParts(version) ? version! : null;
  if (!known) return { key, name, sub, version: DASH, state: "unknown", note: t("updates.versionUnknown"), step: null, group };
  if (!versionParts(latest)) return { key, name, sub, version: known, state: "unknown", note: t("updates.latestUnknown"), step: null, group };
  return isNewer(latest, known)
    ? { key, name, sub, version: `${known} → ${latest}`, state: "pending", note: "", step, group }
    : { key, name, sub, version: known, state: "current", note: "", step: null, group };
}

/** Skills per agent folder (agents that share a folder are one row), then the runtime of each project. */
export function updateRows(plugin: PluginStatus, names: Record<string, string>): UpdateRow[] {
  const latest = targetVersion(plugin);
  const folders = new Map<string, { agents: string[]; version: string | null }>();
  for (const [host, entry] of Object.entries(plugin.hosts ?? {})) {
    if (!entry.installed) continue;
    const root = entry.root ?? host;
    const folder = folders.get(root) ?? { agents: [], version: entry.version };
    folder.agents.push(AGENTS[host] ?? host);
    folders.set(root, folder);
  }
  const rows = [...folders].map(([root, folder]) =>
    row("skills:" + root, t("updates.skillsIn", { agents: joinNames(folder.agents) }), root, folder.version, latest, GLOBAL()));
  for (const project of plugin.projects ?? []) {
    if (!project.runtime) continue;
    const name = t("updates.runtimeIn", { name: names[project.root] ?? project.root.split(/[\\/]/).filter(Boolean).pop() ?? project.root });
    const key = "project:" + project.root;
    const step: UpdateStep = { id: key, label: name, body: { scope: "project", root: project.root } };
    // A legacy runtime has no version stamp: the project update migrates it, as on the board.
    rows.push(!project.runtime_version && runtimePending(project, latest)
      ? { key, name, sub: project.root, version: `${t("skill.noVersionStamp")} → ${latest}`, state: "pending", note: t("updates.updateLegacyRuntime"), step, group: key }
      : row(key, name, project.root, project.runtime_version ?? null, latest, step));
  }
  return rows;
}

/** "Everything is up to date" is true only when each row is current. */
export const allCurrent = (rows: UpdateRow[]) => rows.every((item) => item.state === "current");

/** "Update all": each pending action once, in list order. */
export function updatePlan(rows: UpdateRow[]): UpdateStep[] {
  const steps = new Map<string, UpdateStep>();
  for (const item of rows) if (item.step) steps.set(item.step.id, item.step);
  return [...steps.values()];
}

/** A refused update answers with ok: false, not with a failed request. */
export function opOutcome(result: OpResult): { ok: boolean; output: string; error: string } {
  const output = [result.source_notice, result.stdout_tail?.trim()].filter(Boolean).join("\n");
  return { ok: result.ok, output, error: result.ok ? "" : result.error || t("updates.installerFailed") };
}
