// The setup wizard: its steps, what the footer offers, and where the skills go.
import { t } from "./i18n";
import { joinNames } from "./skills";
import type { HostInfo } from "./skills";

export const STEPS = () => [t("setupWizard.requirements"), t("setupWizard.agents"), t("setupWizard.skills"), t("setupWizard.watchFolders")];
const LAST = () => STEPS().length - 1;

/** Steps 2 to 4 talk to the monitor. Without it the wizard stays on Requirements. */
export const stepGate = (step: number, ready: boolean) => (ready ? step : 0);

export function footer(step: number, state: { blocked: boolean; ready: boolean; installing: boolean }) {
  return {
    back: step > 0 && !state.installing,
    skip: step === LAST(),
    next: step === LAST() ? t("setupWizard.openDashboard") : t("setupWizard.continue"),
    canNext: step === 0 ? !state.blocked && state.ready : !state.installing,
  };
}

export const preselected = (hosts: HostInfo[]) => hosts.filter((host) => host.found).map((host) => host.id);

export const agentCards = (hosts: HostInfo[], selected: string[]) => hosts.map((host) => ({
  id: host.id, name: host.name, found: host.found, note: host.found ? t("setupWizard.foundHere") : t("setupWizard.notFound"),
  on: selected.includes(host.id),
}));

export const agentsWord = (count: number) => count === 1 ? t("setupWizard.oneAgent") : t("setupWizard.agentsCount", { n: count });

/** One install folder per skills root: agents that share a root get one row. */
export function installTargets(hosts: HostInfo[], selected: string[]): { label: string; path: string; ids: string[] }[] {
  const byRoot = new Map<string, HostInfo[]>();
  for (const host of hosts) {
    if (selected.includes(host.id)) byRoot.set(host.skills_root, [...(byRoot.get(host.skills_root) ?? []), host]);
  }
  return [...byRoot].map(([root, group]) => ({
    label: joinNames(group.map((host) => host.name)),
    path: root + (root.includes("\\") ? "\\" : "/") + "gsd-path",
    ids: group.map((host) => host.id),
  }));
}
