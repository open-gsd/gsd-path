// Which screen the window shows, and what the Requirements step lists.
// Pure functions of the shell state, so they can be tested without a window.
import { t } from "./i18n";
import type { Problem, Requirement, Shell } from "./shell";

export type Screen =
  | "checking" | "first-launch" | "requirements" | "python" | "port" | "problem" | "ready";
export type Seen = { setupDone: boolean; firstLaunchSeen: boolean };

// Problems the Requirements step shows as a row; other problems get their own screen.
const REQUIREMENT_KINDS = new Set(["git", "python-venv"]);

export function pickScreen(shell: Shell, seen: Seen): Screen {
  if (shell.phase === "checking") return "checking";
  if (shell.launch?.legacy.length && !seen.firstLaunchSeen) return "first-launch";
  if (shell.phase === "ready") return seen.setupDone ? "ready" : "requirements";
  const blocking = (shell.launch?.problems ?? []).filter((problem) => problem.blocking);
  if (blocking.some((problem) => problem.kind === "port")) return "port";
  const asRows = shell.python_missing ||
    (blocking.length > 0 && blocking.every((problem) => REQUIREMENT_KINDS.has(problem.kind)));
  if (!seen.setupDone && asRows) return "requirements";
  return shell.python_missing ? "python" : "problem";
}

/** The port is held by an older GSD Path daemon that could not be stopped, not by another program. */
export const heldByDaemon = (problem: Problem) => problem.detail?.owner === "daemon";

export type RowAction = { label: string; copy: string } | { label: string; url: string };
export type RequirementRow = {
  id: string;
  name: string;
  tone: "ok" | "warn" | "miss";
  required: boolean;
  pill: string;
  detail: string;
  hint: string;
  action: RowAction | null;
};

const PYTHON_PAGE = "https://www.python.org/downloads/";

export function pythonFix(os: Shell["os"]): RowAction {
  if (os === "windows") return { label: t("req.copyWinget"), copy: "winget install Python.Python.3.12" };
  if (os === "linux") return { label: t("req.copyCommand"), copy: "sudo apt install python3 python3-venv" };
  return { label: t("req.openPage"), url: PYTHON_PAGE };
}

function gitFix(os: Shell["os"]): RowAction {
  if (os === "windows") return { label: t("req.openPage"), url: "https://git-scm.com/download/win" };
  if (os === "linux") return { label: t("req.copyCommand"), copy: "sudo apt install git" };
  return { label: t("req.copyCommand"), copy: "xcode-select --install" };
}

function row(os: Shell["os"], item: Requirement): RequirementRow {
  const ready = item.state === "ready";
  const base = { id: item.id, required: item.required };
  const finish = (
    name: string, tone: RequirementRow["tone"], detail: string, hint: string, action: RowAction | null,
  ): RequirementRow => ({
    ...base, name, tone, detail, hint, action,
    pill: tone === "ok" ? t("req.pill.ready") : tone === "warn" ? t("req.pill.recommended")
      : item.required ? t("req.pill.required") : t("req.pill.optional"),
  });
  switch (item.id) {
    case "python": {
      // 3.9 runs Path but is past end of life; the macOS Command Line Tools still ship it.
      const old = ready && (item.detail ?? "").startsWith("3.9.");
      return finish(t("req.python.name"), !ready ? "miss" : old ? "warn" : "ok",
        ready ? item.detail ?? t("req.installed") : t("req.python.notFound"),
        old ? t("req.python.oldHint") : t("req.python.hint"),
        !ready ? pythonFix(os) : old ? { label: t("req.openPage"), url: PYTHON_PAGE } : null);
    }
    case "git":
      return finish(os === "windows" ? t("req.git.windowsName") : t("req.git.name"), ready ? "ok" : "miss",
        ready ? item.detail ?? t("req.installed") : t("req.git.notInstalled"),
        t("req.git.hint"), ready ? null : gitFix(os));
    case "python-venv":
      return finish(t("req.venv.name"), ready ? "ok" : "miss",
        ready ? t("req.installed") : t("req.venv.notInstalled"),
        t("req.venv.hint"),
        ready ? null : { label: t("req.copyCommand"), copy: "sudo apt install python3-venv" });
    case "gh":
      return finish(t("req.gh.name"),
        ready ? "ok" : item.state === "signed-out" ? "warn" : "miss",
        ready ? t("req.gh.signedIn") : item.state === "signed-out" ? t("req.gh.notSignedIn") : t("req.gh.notInstalled"),
        t("req.gh.hint"),
        ready ? null
          : item.state === "signed-out" ? { label: t("req.gh.copySignIn"), copy: "gh auth login" }
          : { label: t("req.gh.openInstall"), url: "https://cli.github.com/" });
    default:
      return finish(item.id, ready ? "ok" : "miss", item.detail ?? "", "", null);
  }
}

export function requirementRows(shell: Shell): { rows: RequirementRow[]; blocked: boolean } {
  const items: Requirement[] = shell.python_missing || !shell.launch
    ? [{ id: "python", required: true, state: shell.python_missing ? "missing" : "ready", detail: null }]
    : shell.launch.requirements;
  const rows = items.map((item) => row(shell.os, item));
  return { rows, blocked: rows.some((item) => item.required && item.tone === "miss") };
}
