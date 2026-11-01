// Reads and calls shared by the Skills page, the board, the project page and the setup wizard.
import { useEffect, useState } from "react";
import { api } from "./shell";
import type { HostInfo, OpResult, PluginStatus, UninstallPlan } from "./skills";

type Loaded = { plugin: PluginStatus | null; hosts: HostInfo[]; error: string | null };

/** The plugin status and the agent list. They load again when `key` changes or after reload(). */
export function usePlugin(key: unknown = null) {
  const [state, setState] = useState<Loaded>({ plugin: null, hosts: [], error: null });
  const [round, setRound] = useState(0);
  useEffect(() => {
    let live = true;
    Promise.allSettled([
      api<PluginStatus>("GET", "/api/plugin/status"), api<{ hosts: HostInfo[] }>("GET", "/api/hosts"),
    ]).then(([plugin, hosts]) => {
      if (!live) return;
      const failed = [plugin, hosts].find((result) => result.status === "rejected") as PromiseRejectedResult | undefined;
      // Keep the last good payload when one read fails.
      setState((old) => ({
        plugin: plugin.status === "fulfilled" ? plugin.value : old.plugin,
        hosts: hosts.status === "fulfilled" ? hosts.value.hosts ?? [] : old.hosts,
        error: failed ? String(failed.reason) : null,
      }));
    });
    return () => { live = false; };
  }, [key, round]);
  return { ...state, reload: () => setRound((count) => count + 1) };
}

export const installSkills = (hosts: string[], dry_run: boolean) =>
  api<OpResult>("POST", "/api/plugin/install", { scope: "global", hosts, dry_run });
export const planUninstall = (body: { scope: "global"; hosts: string[] } | { scope: "project"; root: string }) =>
  api<{ ok: boolean; plan: UninstallPlan }>("POST", "/api/plugin/uninstall", { ...body, dry_run: true });
export const applyUninstall = (body: { scope: "global"; hosts: string[] } | { scope: "project"; root: string }) =>
  api<{ ok: boolean; applied: string[]; errors: { path: string; error: string }[] }>("POST", "/api/plugin/uninstall", { ...body, confirm: true });
export const projectOp = <T = OpResult>(root: string, op: string, more: { dry_run?: boolean; member?: string } & Record<string, string | boolean> = {}) =>
  api<T>("POST", "/api/project/op", { root, op, ...more });

/** The text of a failed call: the daemon's message, without the "Error: " a thrown Error adds. */
export const message = (error: unknown) => String(error instanceof Error ? error.message : error);
