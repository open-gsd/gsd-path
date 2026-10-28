// Settings → Monitoring and Usage and prices: two views of one form over /api/config.
import { useEffect, useState } from "react";
import { t } from "../i18n";
import { addUnique, configChanges, needsPrice, PRICE_KEYS, toDraft, unpricedModels, withUnpriced } from "../settingsConfig";
import type { Config, Draft, PriceRow } from "../settingsConfig";
import { api, pickFolder } from "../shell";
import type { Status } from "../status";
import { Field, SaveBar, Toggle } from "./SettingsParts";

/** The form lives in the Settings page, so an edit survives a change of tab. */
export function useConfigForm(status: Status | null) {
  const unpriced = unpricedModels(status);
  const [config, setConfig] = useState<Config | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    api<Config>("GET", "/api/config").then(setConfig, (reason) => setError(String(reason)));
  }, []);
  // A new saved config replaces the draft. A model that usage reports later only adds its empty row.
  useEffect(() => { if (config) setDraft(toDraft(config, unpriced)); }, [config]);
  const models = unpriced.join("\n");
  useEffect(() => {
    setDraft((old) => old && { ...old, prices: withUnpriced(old.prices, unpriced) });
  }, [models]);

  const changes = config && draft ? configChanges(config, draft) : { payload: {}, errors: [], summary: [] };
  const set = (part: Partial<Draft>) => { setNote(""); setDraft((old) => old && { ...old, ...part }); };
  const save = async () => {
    setBusy(true); setError(""); setNote("");
    try {
      setConfig(await api<Config>("POST", "/api/config", changes.payload));
      setNote(t("settings.saved"));
    } catch (reason) {
      setError(String(reason)); // the daemon refused: nothing changed
    }
    setBusy(false);
  };
  const discard = () => { setError(""); if (config) setDraft(toDraft(config, unpriced)); };
  const bar = <SaveBar summary={changes.summary} errors={changes.errors} error={error} note={note} busy={busy} onSave={save} onDiscard={discard} />;
  return { draft, set, busy, error, bar };
}
type Form = ReturnType<typeof useConfigForm>;

function Loading({ title, error }: { title: string; error: string }) {
  return (
    <>
      <h2 className="set-h2">{title}</h2>
      {error ? <div className="error" role="alert">{t("settings.cannotRead")} {error}</div> : <p className="note">{t("settings.loading")}</p>}
    </>
  );
}

/** A folder list with a remove button per line and a folder dialog to add one. */
function Folders({ name, items, empty, remove, add, danger, disabled, onChange }: {
  name: string; items: string[]; empty: string; remove: string; add: string; danger?: boolean; disabled: boolean; onChange: (items: string[]) => void;
}) {
  const [error, setError] = useState("");
  const pick = () => pickFolder().then((folder) => { setError(""); onChange(addUnique(items, folder)); }, (reason) => setError(String(reason)));
  return (
    <div className="set-block">
      <b>{name}</b>
      {items.map((item) => (
        <div key={item} className="set-item">
          <span>{item}</span>
          <button className={danger ? "btn small danger" : "btn small"} disabled={disabled} onClick={() => onChange(items.filter((other) => other !== item))}>{remove}</button>
        </div>
      ))}
      {!items.length && <div className="sub">{empty}</div>}
      <button className="btn small set-add" disabled={disabled} onClick={pick}>{add}</button>
      {error && <div className="error" role="alert">{error}</div>}
    </div>
  );
}

export function MonitoringTab({ form }: { form: Form }) {
  const { draft, set, busy } = form;
  if (!draft) return <Loading title={t("settings.tab.monitoring")} error={form.error} />;
  const number = (key: "max_depth" | "poll_seconds", label: string) => (
    <input className="set-input num" inputMode="numeric" aria-label={label} value={draft[key]} disabled={busy}
      onChange={(event) => set({ [key]: event.target.value })} />
  );
  return (
    <>
      <h2 className="set-h2">{t("settings.tab.monitoring")}</h2>
      <div className="card set-card">
        <Folders name={t("settings.watchedFolders")} items={draft.parents} remove={t("settings.stopWatching")} add={t("settings.addFolder")} danger disabled={busy}
          empty={t("settings.noWatched")} onChange={(parents) => set({ parents })} />
        <Folders name={t("settings.excludedFolders")} items={draft.excludes} remove={t("settings.remove")} add={t("settings.excludeFolder")} disabled={busy}
          empty={t("settings.noExcluded")} onChange={(excludes) => set({ excludes })} />
        <Field name={t("settings.scanDepth")} hint={t("settings.scanDepthHint")}>{number("max_depth", t("settings.scanDepth"))}</Field>
        <Field name={t("settings.refreshInterval")} hint={t("settings.refreshIntervalHint")}>{number("poll_seconds", t("settings.refreshInterval"))}</Field>
        <Field name={t("settings.desktopNotifications")} hint={t("settings.notificationsHint")}>
          <Toggle on={draft.notify} label={t("settings.desktopNotifications")} disabled={busy} onChange={(notify) => set({ notify })} />
        </Field>
        <Field name={t("settings.activityHistory")} hint={<>Keep a record of changes in <span className="mono">history.jsonl</span>.</>}>
          <Toggle on={draft.history} label={t("settings.activityHistory")} disabled={busy} onChange={(history) => set({ history })} />
        </Field>
      </div>
      {form.bar}
    </>
  );
}

export function UsageTab({ form }: { form: Form }) {
  const { draft, set, busy } = form;
  const [pattern, setPattern] = useState("");
  if (!draft) return <Loading title={t("settings.tab.usage")} error={form.error} />;
  const rows = draft.prices;
  const change = (id: number, part: Partial<PriceRow>) => set({ prices: rows.map((row) => (row.id === id ? { ...row, ...part } : row)) });
  // A model that usage reports keeps its row: Remove only empties it.
  const remove = (row: PriceRow) => (row.unpriced ? change(row.id, { input: "", cached: "", output: "" })
    : set({ prices: rows.filter((other) => other.id !== row.id) }));
  const addModel = () => set({ prices: [...rows, { id: Math.max(-1, ...rows.map((row) => row.id)) + 1, model: "",
    input: "", cached: "", output: "", known: false, unpriced: false }] });
  const addPattern = () => { set({ session_dirs: addUnique(draft.session_dirs, pattern) }); setPattern(""); };
  const missing = rows.filter(needsPrice);

  return (
    <>
      <h2 className="set-h2 tight">{t("settings.tab.usage")}</h2>
      <p className="set-lead">{t("settings.usageLead")}</p>
      <div className="card set-pad">
        <div className="set-prices">
          <span className="set-th">{t("settings.model")}</span><span className="set-th num">{t("settings.input")}</span><span className="set-th num">{t("usage.cached")}</span>
          <span className="set-th num">{t("settings.output")}</span><span />
          {rows.map((row) => (
            <div key={row.id} className={needsPrice(row) ? "set-price missing" : "set-price"}>
              {row.known ? <span className="mono">{row.model}</span>
                : <input className="set-input mono" aria-label={t("settings.modelName")} placeholder="model name" value={row.model} disabled={busy}
                    onChange={(event) => change(row.id, { model: event.target.value })} />}
              {PRICE_KEYS.map((key) => (
                <input key={key} className="set-input num" inputMode="decimal" placeholder="—" disabled={busy}
                  aria-label={t("settings.priceFor", { key, model: row.model || t("settings.newModel") })} value={row[key]}
                  onChange={(event) => change(row.id, { [key]: event.target.value })} />
              ))}
              <button className="link" disabled={busy || needsPrice(row)} onClick={() => remove(row)}>{t("settings.remove")}</button>
            </div>
          ))}
        </div>
        {!rows.length && <div className="sub">{t("settings.noPrices")}</div>}
        {missing.map((row) => <div key={row.id} className="set-missing">{t("settings.hasNoPrice", { model: row.model })}</div>)}
        <button className="btn small set-add" disabled={busy} onClick={addModel}>{t("settings.addModel")}</button>
      </div>
      <div className="card set-pad set-gap">
        <b>{t("settings.sessionFolders")}</b>
        <div className="sub">{t("settings.sessionFoldersSub")}</div>
        {draft.session_dirs.map((item) => (
          <div key={item} className="set-item">
            <span>{item}</span>
            <button className="btn small" disabled={busy} onClick={() => set({ session_dirs: draft.session_dirs.filter((other) => other !== item) })}>{t("settings.remove")}</button>
          </div>
        ))}
        {!draft.session_dirs.length && <div className="sub set-warn">{t("settings.noSessionFolders")}</div>}
        <form className="set-new" onSubmit={(event) => { event.preventDefault(); addPattern(); }}>
          <input className="set-input mono" aria-label={t("settings.sessionFolderLabel")} placeholder="~/.codex/sessions" value={pattern}
            disabled={busy} onChange={(event) => setPattern(event.target.value)} />
          <button className="btn small" disabled={busy || !pattern.trim()}>{t("settings.addFolder")}</button>
        </form>
      </div>
      {form.bar}
    </>
  );
}
