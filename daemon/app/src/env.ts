// The Environment page: rows, masking, name checks and the changes a save sends.
// A value is in memory only while its row shows it, or while it is an edit not saved yet.
import { t } from "./i18n";

export const ENV_FILES = [".env", ".env.local", ".env.development", ".env.production"] as const;
export type EnvFile = (typeof ENV_FILES)[number];
export type GitState = "tracked" | "ignored" | "untracked";
export type Listing = { file: string; exists: boolean; git: GitState; vars: { name: string; empty: boolean }[] };
export type Change = { name: string; value: string } | { name: string; remove: true };
export type DiffItem = { name: string; change: "add" | "change" | "remove" };
export type EnvRow = {
  key: number;
  /** The name in the file; null for a row the user added. */
  original: string | null;
  name: string;
  /** The value in the file is empty. */
  empty: boolean;
  /** The user's edit; null when the value is not edited. */
  draft: string | null;
  /** The value read from the file after Show; dropped on Hide. */
  disk: string | null;
  shown: boolean;
  removed: boolean;
};

export const MASK = "•".repeat(12);
export const JEV = "GSD_PATH_JEV";
// The same rule as NAME in the daemon's env_files.py.
const NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const NAME_RULE = () => t("envPage.nameRule");
const DUPLICATE = () => t("envPage.duplicateName");

export const rowsFrom = (vars: Listing["vars"]): EnvRow[] => vars.map((item, key) => (
  { key, original: item.name, name: item.name, empty: item.empty, draft: null, disk: null, shown: false, removed: false }));

/** "Add variable": an empty row the user can type in. */
export const newRow = (rows: EnvRow[]): EnvRow => (
  { key: Math.max(-1, ...rows.map((row) => row.key)) + 1, original: null, name: "", empty: true, draft: null, disk: null, shown: true, removed: false });

/** The value as far as the page knows it; null when it is in the file only. */
const known = (row: EnvRow) => row.draft ?? row.disk ?? (row.empty ? "" : null);

/** The text of the value cell. null: draw the mask. An empty value shows as empty. */
export function valueView(row: EnvRow): string | null {
  const value = known(row);
  return value === "" || (row.shown && value !== null) ? value : null;
}

/** Hide: forget the value read from the file. An edit stays, masked, until Save or Discard. */
export const hide = (row: EnvRow): EnvRow => ({ ...row, shown: false, disk: null });

const renamed = (row: EnvRow) => row.original !== null && row.name !== row.original;

/** Name errors by row key. Checked before Save; the daemon checks the same rules again. */
export function rowErrors(rows: EnvRow[]): Record<number, string> {
  // Every name the save touches: a removed or renamed variable still uses its old name once.
  const used = rows.flatMap((row) => [
    ...(row.removed ? [] : [row.name]),
    ...(row.original !== null && (row.removed || renamed(row)) ? [row.original] : [])]);
  const errors: Record<number, string> = {};
  for (const row of rows) {
    if (row.removed) continue;
    const error = !row.name ? t("envPage.enterName") : !NAME.test(row.name) ? NAME_RULE()
      : used.filter((name) => name === row.name).length > 1 ? DUPLICATE() : null;
    if (error) errors[row.key] = error;
  }
  return errors;
}

/** Renamed variables whose value must be read from the file before the save. */
export const needsValue = (rows: EnvRow[]): string[] =>
  rows.filter((row) => !row.removed && renamed(row) && known(row) === null).map((row) => row.original!);

/** The `changes` of POST /api/env/save. `fetched` holds the values that needsValue() asked for. */
export function buildChanges(rows: EnvRow[], fetched: Record<string, string>): Change[] {
  return rows.flatMap((row): Change[] => {
    if (row.removed) return row.original === null ? [] : [{ name: row.original, remove: true }];
    if (row.original === null) return [{ name: row.name, value: row.draft ?? "" }];
    if (renamed(row)) {
      const value = known(row) ?? fetched[row.original];
      if (value === undefined) throw new Error(t("envPage.valueNotLoaded", { name: row.original }));
      return [{ name: row.original, remove: true }, { name: row.name, value }];
    }
    const same = row.draft === null || row.draft === row.disk || (row.empty && row.draft === "");
    return same ? [] : [{ name: row.name, value: row.draft! }];
  });
}

/** The rows hold a change that Save would send. */
export const isDirty = (rows: EnvRow[]) =>
  buildChanges(rows, Object.fromEntries(needsValue(rows).map((name) => [name, ""]))).length > 0;

/** The files where Jev screening is on. `values` is the flag's value per file that has it. */
export const jevOn = (values: Partial<Record<EnvFile, string>>): EnvFile[] => ENV_FILES.filter((file) => values[file] === "1");

/** On: write the flag to `target`. Off: remove it from every file where it is on. */
export function jevPlan(on: boolean, target: EnvFile, values: Partial<Record<EnvFile, string>>): { file: EnvFile; changes: Change[] }[] {
  if (on) return [{ file: target, changes: [{ name: JEV, value: "1" }] }];
  return jevOn(values).map((file) => ({ file, changes: [{ name: JEV, remove: true }] }));
}

export const gitPill = (git: GitState): { tone: "warn" | "ok" | "mute"; label: string } => ({
  tracked: { tone: "warn" as const, label: t("envPage.trackedByGit") },
  ignored: { tone: "ok" as const, label: t("envPage.ignoredByGit") },
  untracked: { tone: "mute" as const, label: t("envPage.notTracked") },
})[git];

export function fileNote({ file, git, exists }: Listing): string {
  const text = git === "tracked" ? t("envPage.noteTracked", { file })
    : git === "ignored" ? t("envPage.noteIgnored", { file })
    : t("envPage.noteUntracked", { file });
  return exists ? text : text + " " + t("envPage.noteNotExists");
}

const VERB = { add: () => t("envPage.verbAdd"), change: () => t("envPage.verbChange"), remove: () => t("envPage.verbRemove") };
/** The save preview: names and the kind of change. Never a value. */
export const diffLines = (diff: DiffItem[]) => diff.map((item) => `${VERB[item.change]()} ${item.name}`);

/** The monitor refuses every env route (no write token): all files fail with one message. */
export const refusal = (errors: (string | null)[]): string | null =>
  errors.length > 0 && errors.every((error) => error !== null && error === errors[0]) ? errors[0] : null;
