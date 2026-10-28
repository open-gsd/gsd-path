// The app's own update (Tauri updater): what Settings → Updates, the dialog, and the tray show.
import { t } from "./i18n";
import type { Shell } from "./shell";

export type AppUpdateRow = {
  state: "ready" | "refused" | "check-failed";
  /** "0.1.0 → 0.1.1", or the current version when no newer one is known. */
  text: string;
  notes: string | null;
};

export function appUpdateRow(shell: Shell): AppUpdateRow | null {
  if (shell.update) {
    return { state: shell.update_error ? "refused" : "ready",
      text: `${shell.version} → ${shell.update.version}`, notes: shell.update.notes };
  }
  return shell.update_error ? { state: "check-failed", text: shell.version, notes: null } : null;
}

/** A refused update changed nothing; say so with the updater's reason. */
export const refusedText = (shell: Shell) =>
  t("appUpdate.refused", { reason: shell.update_error, version: shell.version });

/** The tray strip: the app update first, then how many other updates wait. */
export function readyLine(shell: Shell, others: number): string | null {
  if (!shell.update || shell.update_error) return null;
  const more = others > 0 ? " · " + (others === 1 ? t("appUpdate.oneMore") : t("appUpdate.moreUpdates", { n: others })) : "";
  return t("appUpdate.ready", { version: shell.update.version }) + more;
}

/** The tray strip's Review: an app update opens its dialog; a skills update opens the dashboard. */
export const reviewAction = (shell: Shell) => (readyLine(shell, 0) ? "app-update" : "open");
