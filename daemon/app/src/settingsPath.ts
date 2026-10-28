// Settings → Path settings: the form over GET/POST /api/path-config (daemon/gsd_daemon/path_settings.py).
// The daemon takes one key per request; Save sends one request per changed key.
import { t } from "./i18n";
import { flavorOf } from "./status";
import type { Project } from "./status";

export type PathItem = { value: string; source: string; locked?: string | null; current?: string; current_source?: string };
export type PathData = {
  scope: "user" | "project";
  settings: { integration: PathItem; review_panel: PathItem };
  /** Configured overrides only, by key: models.roles.<role>.<field> or models.hosts.<host>.<role>.<field>. */
  models: Record<string, { value: string; source: string }>;
  roles: string[];
  hosts: string[];
  /** Why the whole scope is read-only, or null. */
  locked: string | null;
  approved_review_panel: { value: string; source: string } | null;
};
/** Unsaved edits by key. null: remove this scope's override (Reset). */
export type PathDrafts = Record<string, string | null>;
export type PathRequest = { action: "set"; key: string; value: string } | { action: "reset"; key: string };

/** An empty root is the user defaults. */
/** Only GSD Path cards have a project scope; other frameworks are read-only. */
export const pathProjects = (projects: Project[]) => projects.filter((p) => !flavorOf(p));

export const scopeQuery = (root: string): { scope: "user" } | { scope: "project"; root: string } =>
  (root ? { scope: "project", root } : { scope: "user" });

export const modelKey = (host: string, role: string, field: "model" | "effort") =>
  `models.${host ? "hosts." + host : "roles"}.${role}.${field}`;

const isSetting = (key: string): key is "integration" | "review_panel" => key === "integration" || key === "review_panel";
const configured = (data: PathData, key: string) => (isSetting(key) ? data.settings[key].value : data.models[key]?.value ?? "inherit");

/** What the field shows: the draft, or the configured value. */
export const fieldValue = (data: PathData, drafts: PathDrafts, key: string) => drafts[key] ?? configured(data, key);

/** Why a field is read-only, or null. */
export const lockOf = (data: PathData, key: string): string | null =>
  data.locked || (isSetting(key) && data.settings[key].locked) || null;

/** Reset removes this scope's override. A project always has an explicit shipping mode. */
export const canReset = (data: PathData, key: string, root: string): boolean =>
  !lockOf(data, key) && (isSetting(key) ? !(key === "integration" && root) : key in data.models);

const MODES = (): [string, string][] => [["direct", t("path.directMerge")], ["pull-request", t("path.pullRequest")]];
/** The modes the dashboard offers, plus the configured one when it is another mode. */
export const integrationOptions = (value: string): [string, string][] => {
  const modes = MODES();
  return modes.some(([mode]) => mode === value) ? modes
    : [...modes, [value, value === "external-landing" ? t("path.externalLanding") : value]];
};

function labelOf(key: string): string {
  if (key === "integration") return t("path.shippingMode");
  if (key === "review_panel") return t("path.reviewPanel");
  const bits = key.split(".");
  return bits[1] === "hosts"
    ? t("path.modelOnHost", { field: `${bits[3]} ${bits[4]}`, host: bits[2] })
    : `${bits[2]} ${bits[3]}`;
}

/** The requests Save sends, in draft order, and the same list as text for the user to check first. */
export function pathChanges(data: PathData, drafts: PathDrafts): { requests: PathRequest[]; errors: string[]; summary: string[] } {
  const requests: PathRequest[] = [];
  const errors: string[] = [];
  const summary: string[] = [];
  for (const [key, draft] of Object.entries(drafts)) {
    if (lockOf(data, key)) continue;
    const label = labelOf(key), before = configured(data, key);
    if (draft === null) {
      requests.push({ action: "reset", key });
      summary.push(t("path.summaryReset", { label, before }));
    } else if (!draft.trim()) {
      errors.push(t("path.needsValue", { label }));
    } else if (key === "review_panel" && /\s/.test(draft)) {
      errors.push(t("path.panelSpaces"));
    } else if (draft.trim() !== before) {
      requests.push({ action: "set", key, value: draft.trim() });
      summary.push(t("path.summarySet", { label, before, after: draft.trim() }));
    }
  }
  return errors.length ? { requests: [], errors, summary: [] } : { requests, errors, summary };
}

/** When the saved settings take effect: the same texts as the daemon dashboard. */
export function savedNote(keys: string[], root: string): string {
  const notes = keys.map((key) => (key === "integration"
    ? (root ? t("path.noteProjectUpdated") : t("path.noteNewProjects"))
    : key === "review_panel" ? t("path.notePanel")
    : t("path.noteAssignments")));
  return [t("settings.saved"), ...new Set(notes)].join(" ");
}
