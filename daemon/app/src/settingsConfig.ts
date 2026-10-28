// Settings → Monitoring and Usage and prices: the form over GET/POST /api/config.
// The daemon checks every value again (settings_api.py); these checks give the message before the request.
import { t } from "./i18n";
import type { Status } from "./status";

export const PRICE_KEYS = ["input", "cached", "output"] as const;
export type PriceKey = (typeof PRICE_KEYS)[number];
export type Price = Partial<Record<PriceKey, number>>;
export type Config = {
  parents: string[]; excludes: string[]; max_depth: number; poll_seconds: number;
  notify: boolean; history: boolean; session_dirs: string[]; prices: Record<string, Price>;
};
export type PriceRow = Record<PriceKey, string> & {
  id: number; model: string;
  /** The model name comes from the daemon; only a row the user added has a name field. */
  known: boolean;
  /** Seen in usage without a price. */
  unpriced: boolean;
};
/** Number fields stay text until Save, so a half-typed value is not lost. */
export type Draft = Omit<Config, "max_depth" | "poll_seconds" | "prices"> & { max_depth: string; poll_seconds: string; prices: PriceRow[] };

/** Models that appear in usage without a price, from every project's spend. */
export const unpricedModels = (status: Status | null): string[] =>
  [...new Set((status?.projects ?? []).flatMap((project) => project.spend?.unpriced ?? []))].sort();

export function parseWhole(text: string, label: string): { value: number } | { error: string } {
  const clean = text.trim();
  return /^\d+$/.test(clean) && Number(clean) >= 1 ? { value: Number(clean) }
    : { error: t("settings.wholeNumber", { label }) };
}

const text = (amount: number | undefined) => (amount == null ? "" : String(amount));

/** The rows, with an empty row added for each model usage has without a price. Edits are kept. */
export function withUnpriced(rows: PriceRow[], unpriced: string[]): PriceRow[] {
  let id = Math.max(-1, ...rows.map((row) => row.id));
  const missing = unpriced.filter((model) => !rows.some((row) => row.model.trim() === model));
  return [
    ...rows.map((row) => ({ ...row, unpriced: unpriced.includes(row.model.trim()) })),
    ...missing.map((model) => ({ id: ++id, model, input: "", cached: "", output: "", known: true, unpriced: true })),
  ];
}

/** Configured prices by model name, then an empty row for each model that needs a price. */
export const priceRows = (prices: Record<string, Price>, unpriced: string[]): PriceRow[] =>
  withUnpriced(Object.keys(prices).sort().map((model, id) => ({
    id, model, input: text(prices[model].input), cached: text(prices[model].cached), output: text(prices[model].output),
    known: true, unpriced: false,
  })), unpriced);

const isEmpty = (row: PriceRow) => PRICE_KEYS.every((key) => !row[key].trim());
/** Highlight: usage has this model and the row holds no price yet. */
export const needsPrice = (row: PriceRow) => row.unpriced && isEmpty(row);

/** The `prices` value to send. Empty rows are dropped. */
export function toPrices(rows: PriceRow[]): { prices: Record<string, Price> } | { errors: string[] } {
  const prices: Record<string, Price> = {};
  const errors: string[] = [];
  for (const row of rows) {
    if (isEmpty(row)) continue;
    const model = row.model.trim();
    if (!model) { errors.push(t("settings.typeModelName")); continue; }
    if (model in prices) { errors.push(t("settings.listedTwice", { model })); continue; }
    prices[model] = {};
    for (const key of PRICE_KEYS) {
      const clean = row[key].trim();
      if (!clean) continue;
      const amount = Number(clean);
      if (Number.isFinite(amount) && amount >= 0) prices[model][key] = amount;
      else errors.push(t("settings.priceNumber", { key, model }));
    }
  }
  return errors.length ? { errors } : { prices };
}

export const toDraft = (config: Config, unpriced: string[]): Draft => ({
  ...config, max_depth: String(config.max_depth), poll_seconds: String(config.poll_seconds),
  prices: priceRows(config.prices, unpriced),
});

/** A list with one more item; the same list for an empty or repeated item. */
export const addUnique = (list: string[], item: string | null): string[] => {
  const clean = item?.trim();
  return clean && !list.includes(clean) ? [...list, clean] : list;
};

const onOff = (flag: boolean) => (flag ? t("settings.on") : t("settings.off"));
const same = (a: Price | undefined, b: Price | undefined) => PRICE_KEYS.every((key) => a?.[key] === b?.[key]);

/** What Save sends: only the keys that changed. With an error, nothing is sent. */
export function configChanges(config: Config, draft: Draft): { payload: Partial<Config>; errors: string[]; summary: string[] } {
  const payload: Partial<Config> = {};
  const errors: string[] = [];
  const summary: string[] = [];

  const folders = (key: "parents" | "excludes" | "session_dirs", added: string, removed: string) => {
    const before = config[key], after = draft[key];
    const more = after.filter((item) => !before.includes(item)), less = before.filter((item) => !after.includes(item));
    if (!more.length && !less.length) return;
    payload[key] = after;
    summary.push(...more.map((item) => `${added} ${item}`), ...less.map((item) => `${removed} ${item}`));
  };
  const whole = (key: "max_depth" | "poll_seconds", label: string) => {
    const parsed = parseWhole(draft[key], label);
    if ("error" in parsed) errors.push(parsed.error);
    else if (parsed.value !== config[key]) { payload[key] = parsed.value; summary.push(`${label}: ${config[key]} → ${parsed.value}`); }
  };
  const flag = (key: "notify" | "history", label: string) => {
    if (draft[key] === config[key]) return;
    payload[key] = draft[key];
    summary.push(`${label}: ${onOff(config[key])} → ${onOff(draft[key])}`);
  };

  folders("parents", t("settings.watch"), t("settings.stopWatching"));
  folders("excludes", t("settings.exclude"), t("settings.stopExcluding"));
  whole("max_depth", t("settings.scanDepth"));
  whole("poll_seconds", t("settings.refreshInterval"));
  flag("notify", t("settings.desktopNotifications"));
  flag("history", t("settings.activityHistory"));
  folders("session_dirs", t("settings.addSessionFolder"), t("settings.removeSessionFolder"));

  const result = toPrices(draft.prices);
  if ("errors" in result) errors.push(...result.errors);
  else {
    const before = config.prices, after = result.prices;
    const lines = [
      ...Object.keys(before).filter((model) => !(model in after)).map((model) => t("settings.removePriceFor", { model })),
      ...Object.keys(after).filter((model) => !same(before[model], after[model]))
        .map((model) => t(model in before ? "settings.changePriceFor" : "settings.setPriceFor", { model })),
    ];
    if (lines.length) { payload.prices = after; summary.push(...lines); }
  }
  return errors.length ? { payload: {}, errors, summary: [] } : { payload, errors, summary };
}
