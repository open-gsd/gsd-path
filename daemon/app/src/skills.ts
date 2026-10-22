// Path skills per agent: the payloads of /api/hosts and /api/plugin/status, and what the Skills page shows.
import { DASH } from "./status";

/** One agent from GET /api/hosts. */
export type HostInfo = { id: string; name: string; found: boolean; path: string | null; skills_root: string };
export type PluginHost = { installed: boolean; version: string | null; root?: string };
/** One project from detect_project() in the daemon. */
export type ProjectSetup = {
  root: string; local_skills: string[]; runtime: boolean; contracts: boolean; hooks: boolean; runtime_version: string | null;
};
export type Releases = { latest: string | null; selected: string | null; versions: string[]; source?: "npm" | "git" };
export type PluginStatus = {
  latest: string | null; update_available: boolean; hosts: Record<string, PluginHost>; projects: ProjectSetup[]; releases?: Releases;
  /** gsd-pi and gsd-core: installed and latest versions. Older daemons omit it. */
  frameworks?: Record<string, FrameworkStatus>;
};
export type FrameworkStatus = {
  installed: string | null; hosts: { host: string; dir: string; version: string | null }[];
  latest: string | null; checked: string | null; update_available: boolean; detected: boolean;
};
export type FrameworkRow = { name: string; where: string; version: string; status: string; tone: "ok" | "acc" | "mute"; update: boolean; error: string | null };
/** The answer of install, update and the project operations. */
export type OpResult = { ok: boolean; argv?: string[]; stdout_tail?: string; error?: string | null; source_notice?: string };
export type UninstallPlan = { plan: { path: string; kind: string; reason: string }[]; skipped: { path: string; reason: string }[] };

/** The same rule as _parse_version() in the daemon: digits between dots, else the version is unknown. */
export const versionParts = (version: string | null | undefined) => {
  const numbers = (version ?? "").trim().split(".").map((part) => (/^\d+$/.test(part) ? Number(part) : NaN));
  return version && !numbers.some(Number.isNaN) ? numbers : null;
};

/** The same rule as _is_newer() in the daemon: a tuple compare, and an unknown version is never newer or older. */
export function isNewer(latest: string | null | undefined, installed: string | null | undefined): boolean {
  const a = versionParts(latest), b = versionParts(installed);
  if (!a || !b) return false;
  for (let k = 0; k < Math.max(a.length, b.length); k++) {
    if (a[k] === undefined) return false; // equal so far and `latest` is shorter
    if (b[k] === undefined) return true;
    if (a[k] !== b[k]) return a[k] > b[k];
  }
  return false;
}

/** The release an install writes: the chosen one, else the latest. */
export const targetVersion = (plugin: { latest?: string | null; releases?: Releases } | null) =>
  plugin?.releases?.selected ?? plugin?.releases?.latest ?? plugin?.latest ?? null;

export const joinNames = (names: string[]) =>
  names.length < 2 ? names.join("") : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];

/** Agents by skills folder, in the daemon's order. Codex and Zed share one folder. */
function groups(hosts: HostInfo[]): HostInfo[][] {
  const byRoot = new Map<string, HostInfo[]>();
  for (const host of hosts) byRoot.set(host.skills_root, [...(byRoot.get(host.skills_root) ?? []), host]);
  return [...byRoot.values()];
}

const installedIn = (group: HostInfo[], plugin: PluginStatus) =>
  group.map((host) => plugin.hosts[host.id]).find((entry) => entry?.installed);
/** A folder has a row when an agent that uses it is on this computer, or skills are in it. */
const shown = (group: HostInfo[], plugin: PluginStatus) => group.some((host) => host.found) || !!installedIn(group, plugin);

export type SkillRow = {
  ids: string[]; label: string; path: string; version: string; tone: "ok" | "warn" | "mute"; status: string;
  /** The label of the install button, or null when there is nothing to install. */
  primary: string | null; preview: boolean; uninstall: boolean;
};

export function skillRows(hosts: HostInfo[], plugin: PluginStatus | null): SkillRow[] {
  if (!plugin) return [];
  const target = targetVersion(plugin);
  return groups(hosts).filter((group) => shown(group, plugin)).map((group) => {
    const base = { ids: group.map((host) => host.id), label: joinNames(group.map((host) => host.name)), path: group[0].skills_root };
    const entry = installedIn(group, plugin);
    if (!entry) {
      return { ...base, version: DASH, tone: "mute", status: "Not installed", primary: "Install", preview: true, uninstall: false };
    }
    const update = target ? `Update to ${target}` : null;
    if (!entry.version) {
      return { ...base, version: DASH, tone: "warn", status: "No version stamp", primary: update, preview: !!update, uninstall: !update };
    }
    if (isNewer(target, entry.version)) {
      return { ...base, version: entry.version, tone: "warn", status: "Update available", primary: update, preview: true, uninstall: false };
    }
    // An older release was chosen: offer it, but it is not an update.
    const other = target && target !== entry.version ? `Install ${target}` : null;
    return { ...base, version: entry.version, tone: "ok", status: "Installed", primary: other, preview: !!other, uninstall: true };
  });
}

/** The rows that show "Update available": the banner lists them and the Skills nav badge counts them. */
export const pendingSkills = (hosts: HostInfo[], plugin: PluginStatus | null) =>
  skillRows(hosts, plugin).filter((row) => row.status === "Update available");

/** Agents that are not on this computer and have no skills folder with Path in it. */
export const notDetected = (hosts: HostInfo[], plugin: PluginStatus | null) =>
  plugin ? groups(hosts).filter((group) => !shown(group, plugin)).flat().map((host) => host.name) : [];

export const sharedRoots = (hosts: HostInfo[]) => groups(hosts).filter((group) => group.length > 1)
  .map((group) => ({ names: joinNames(group.map((host) => host.name)), path: group[0].skills_root }));

/** The release picker: "" follows the latest release. Null hides the picker (git source, or no release list). */
export function releaseOptions(releases: Releases | undefined): { value: string; label: string }[] | null {
  if (!releases?.latest || releases.source === "git") return null;
  return [{ value: "", label: `Latest · ${releases.latest}` },
    ...releases.versions.filter((version) => version !== releases.latest).map((version) => ({ value: version, label: version }))];
}

export type Failure = { title: string; text: string; unchanged: string | null; fix: string | null };

/** The failure card: what failed, what the installer says was not changed, and the fix command when the message has one. */
export function failure(done: "installed" | "updated" | "removed", labels: string[], error: string): Failure {
  return {
    title: `${joinNames(labels)} ${labels.length > 1 ? "were" : "was"} not ${done}`,
    text: error,
    unchanged: error.startsWith("installer refused") || error.includes("rolled back") ? "Nothing was changed." : null,
    fix: error.split("`")[1] ?? null,
  };
}

/** One row per gsd-pi / gsd-core install found on this computer. gsd-core lists its CLI and every agent host.
 *  `errors` are the failed registry checks of the last Check for updates; the row keeps the last known version. */
export function frameworkRows(plugin: PluginStatus | null, errors: Record<string, string | null> = {}): FrameworkRow[] {
  return Object.entries(plugin?.frameworks ?? {}).filter(([, item]) => item.detected).map(([name, item]) => {
    const parts = [...(item.installed ? [`CLI\u00a0${item.installed}`] : []), ...item.hosts.map((h) => `${h.host}\u00a0${h.version ?? "?"}`)];
    return {
      name, where: item.hosts.length ? item.hosts.map((h) => h.dir).join(", ") : "global command",
      version: parts.join("\n") || "—",  // one install per line
      status: !item.latest ? "Not checked yet" : item.update_available ? `Update to ${item.latest}` : "Up to date",
      tone: !item.latest ? "mute" : item.update_available ? "acc" : "ok",
      update: item.update_available,
      error: errors[name] ?? null,
    };
  });
}

/** The frameworks with an update waiting, for the banner. */
export const pendingFrameworks = (plugin: PluginStatus | null) =>
  Object.entries(plugin?.frameworks ?? {}).filter(([, item]) => item.update_available).map(([name, item]) => `${name} ${item.latest}`);
