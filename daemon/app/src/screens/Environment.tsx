// The .env editor of one project. Values stay masked until Show; a save shows its diff first.
import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { buildChanges, diffLines, ENV_FILES, fileNote, gitPill, hide, isDirty, JEV, jevOn, jevPlan, MASK, needsValue, newRow, refusal, rowErrors, rowsFrom, valueView } from "../env";
import type { Change, DiffItem, EnvFile, EnvRow, Listing } from "../env";
import { projectHash } from "../route";
import { api, boot } from "../shell";
import { nameOf } from "../status";
import type { Project } from "../status";
import "./environment.css";

type Loaded = {
  listings: Partial<Record<EnvFile, Listing>>;
  errors: Partial<Record<EnvFile, string>>;
  /** The value of GSD_PATH_JEV per file that has it. Path reads GSD_PATH_* keys back; they are not secrets. */
  jev: Partial<Record<EnvFile, string>>;
};
type SaveResult = { written: boolean; diff: DiffItem[] };
type JevPreview = { on: boolean; items: { file: EnvFile; changes: Change[]; diff: DiffItem[] }[] };

const message = (error: unknown) => (error instanceof Error ? error.message : String(error));

export function Environment({ project }: { project: Project }) {
  const root = project.root;
  const [file, setFile] = useState<EnvFile>(".env.local");
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [rows, setRows] = useState<EnvRow[]>([]);
  const [rowNotes, setRowNotes] = useState<Record<number, string>>({});
  const [checked, setChecked] = useState(false);
  const [preview, setPreview] = useState<{ changes: Change[]; diff: DiffItem[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null);
  const [jevTarget, setJevTarget] = useState<EnvFile>(".env.local");
  const [jevPreview, setJevPreview] = useState<JevPreview | null>(null);
  const [jevError, setJevError] = useState<string | null>(null);
  // An answer for an older file, project or page is dropped: its value must not come back.
  const turn = useRef(0);

  const save = (name: EnvFile, changes: Change[], dryRun: boolean) =>
    api<SaveResult>("POST", "/api/env/save", { root, file: name, changes, dry_run: dryRun });
  const reveal = (name: EnvFile, variable: string) =>
    api<{ value: string }>("POST", "/api/env/reveal", { root, file: name, name: variable }).then((answer) => answer.value);

  /** Forget every edit and shown value, and show `listing` again. */
  const reset = (listing: Listing | undefined) => {
    turn.current += 1;
    setRows(rowsFrom(listing?.vars ?? []));
    setRowNotes({}); setChecked(false); setPreview(null); setNote(null);
  };

  const load = async (open: EnvFile) => {
    const mine = ++turn.current;
    const next: Loaded = { listings: {}, errors: {}, jev: {} };
    await Promise.all(ENV_FILES.map(async (name) => {
      try {
        const listing = await api<Listing>("POST", "/api/env/list", { root, file: name });
        next.listings[name] = listing;
        if (listing.vars.some((item) => item.name === JEV)) next.jev[name] = await reveal(name, JEV);
      } catch (error) {
        next.errors[name] = message(error);
      }
    }));
    if (mine !== turn.current) return;
    setLoaded(next);
    setJevPreview(null);
    reset(next.listings[open]);
  };

  useEffect(() => {
    setLoaded(null);
    load(file);
    return () => { turn.current += 1; };
  }, [root]);

  const open = (name: EnvFile) => { setFile(name); reset(loaded?.listings[name]); };
  /** Change the rows; an open save preview is no longer true, so close it. */
  const edit = (change: (rows: EnvRow[]) => EnvRow[]) => { setRows(change); setPreview(null); setNote(null); };
  const patch = (key: number, over: Partial<EnvRow>) => edit((list) => list.map((row) => (row.key === key ? { ...row, ...over } : row)));

  const show = async (row: EnvRow) => {
    setRowNotes((old) => ({ ...old, [row.key]: "" }));
    // An edit or a new row is already in the page; only a value in the file is read.
    if (row.draft !== null || row.original === null) return setRows((list) => list.map((item) => (item.key === row.key ? { ...item, shown: true } : item)));
    const mine = turn.current;
    try {
      const disk = await reveal(file, row.original);
      if (mine === turn.current) setRows((list) => list.map((item) => (item.key === row.key ? { ...item, disk, shown: true } : item)));
    } catch (error) {
      if (mine === turn.current) setRowNotes((old) => ({ ...old, [row.key]: message(error) }));
    }
  };
  const remove = (row: EnvRow) => edit((list) => row.original === null
    ? list.filter((item) => item.key !== row.key)
    : list.map((item) => (item.key === row.key ? { ...hide(item), removed: true } : item)));

  const errors = rowErrors(rows);
  const dirty = isDirty(rows);

  const previewSave = async () => {
    setChecked(true); setPreview(null); setNote(null);
    if (Object.keys(errors).length) return setNote({ text: t("envPage.correctNames"), bad: true });
    const mine = turn.current;
    setBusy(true);
    try {
      // A renamed variable is remove + add; the add needs the value from the file. It is not kept in the rows.
      const fetched: Record<string, string> = {};
      for (const name of needsValue(rows)) fetched[name] = await reveal(file, name);
      const changes = buildChanges(rows, fetched);
      const result = await save(file, changes, true);
      if (mine !== turn.current) return;
      if (result.diff.length) setPreview({ changes, diff: result.diff });
      else setNote({ text: t("envPage.noChange", { file }) });
    } catch (error) {
      if (mine === turn.current) setNote({ text: message(error), bad: true });
    } finally {
      setBusy(false);
    }
  };
  const confirmSave = async () => {
    if (!preview) return;
    setBusy(true);
    try {
      await save(file, preview.changes, false);
      await load(file);
      setNote({ text: t("envPage.savedFile", { file }) });
    } catch (error) {
      setNote({ text: message(error), bad: true });
    } finally {
      setBusy(false);
    }
  };

  const on = loaded ? jevOn(loaded.jev) : [];
  const previewJev = async () => {
    if (!loaded) return;
    setJevError(null);
    setBusy(true);
    try {
      const items = [];
      for (const item of jevPlan(!on.length, jevTarget, loaded.jev)) items.push({ ...item, diff: (await save(item.file, item.changes, true)).diff });
      setJevPreview({ on: !on.length, items });
    } catch (error) {
      setJevError(message(error));
    } finally {
      setBusy(false);
    }
  };
  const confirmJev = async () => {
    if (!jevPreview) return;
    setBusy(true);
    try {
      for (const item of jevPreview.items) await save(item.file, item.changes, false);
      setJevError(null);
    } catch (error) {
      // A file before the failed one can be written already; the reload below shows the true state.
      setJevError(message(error));
    } finally {
      await load(file);
      setBusy(false);
    }
  };
  const restart = async () => {
    setBusy(true);
    try { await boot(); } catch (error) { setNote({ text: message(error), bad: true }); }
    await load(file);
    setBusy(false);
  };

  const listing = loaded?.listings[file];
  const refused = loaded ? refusal(ENV_FILES.map((name) => loaded.errors[name] ?? null)) : null;
  const pill = listing && gitPill(listing.git);

  return (
    <main className="page env" aria-label={t("setup.environment")}>
      <a className="crumb" href={projectHash(root)}>‹ {nameOf(project)}</a>
      <div className="env-head">
        <h1 className="title">{t("setup.environment")}</h1>
        <p>{t("envPage.lead")}</p>
      </div>

      {!loaded ? <div className="empty" role="status">{t("envPage.reading")}</div> : refused ? (
        <div className="env-refused" role="alert">
          <b>{t("envPage.refuses")}</b>
          <span>{refused}</span>
          <div className="actions">
            <button className="btn primary" onClick={restart} disabled={busy}>{t("envPage.restartMonitor")}</button>
            {note?.bad && <span className="env-note bad">{note.text}</span>}
          </div>
        </div>
      ) : <>
        <div className="env-bar">
          <div className="env-seg" role="group" aria-label={t("envPage.envFile")}>
            {ENV_FILES.map((name) => <button key={name} aria-pressed={file === name} disabled={busy} onClick={() => open(name)}>{name}</button>)}
          </div>
          {pill && <span className={`pill ${pill.tone}`}>{pill.label}</span>}
        </div>
        {listing ? <>
          <div className="env-file-note">{fileNote(listing)}</div>
          <div className="env-table">
            <div className="env-th"><span>{t("envPage.name")}</span><span>{t("envPage.value")}</span><span /></div>
            {rows.map((row) => {
              const value = valueView(row);
              const error = (checked && errors[row.key]) || rowNotes[row.key];
              return (
                <div key={row.key} className={row.removed ? "env-row removed" : "env-row"}>
                  <div>
                    <input className="env-name" aria-label={t("envPage.name")} value={row.name} disabled={row.removed} spellCheck={false}
                      placeholder="NEW_VARIABLE" aria-invalid={checked && !!errors[row.key]} autoFocus={row.original === null}
                      onChange={(event) => patch(row.key, { name: event.target.value })} />
                    {error && <div className="env-error" role="alert">{error}</div>}
                  </div>
                  <div>
                    {row.removed ? <span className="env-quiet">{t("envPage.removedWhenSave")}</span>
                      : value === null ? <span className="env-mask" aria-label={t("envPage.hiddenValue")}>{MASK}</span>
                      : value.includes("\n") ? <span className="env-multi">{value}<small>{t("envPage.multiLine")}</small></span>
                      : <input className="env-value" aria-label={t("envPage.valueOf", { name: row.name || t("envPage.newVariable") })} value={value} spellCheck={false}
                          autoComplete="off" placeholder={t("envPage.empty")} onChange={(event) => patch(row.key, { draft: event.target.value, shown: true })} />}
                  </div>
                  <span className="env-actions">
                    {row.removed ? <button className="btn small" onClick={() => patch(row.key, { removed: false })}>{t("envPage.undo")}</button> : <>
                      {value !== "" && (row.shown && value !== null
                        ? <button className="btn small" onClick={() => setRows((list) => list.map((item) => (item.key === row.key ? hide(item) : item)))}>{t("updates.hide")}</button>
                        : <button className="btn small" onClick={() => show(row)}>{t("envPage.show")}</button>)}
                      <button className="btn small danger" onClick={() => remove(row)}>{t("settings.remove")}</button>
                    </>}
                  </span>
                </div>
              );
            })}
            {!rows.length && <div className="env-row"><span className="env-quiet">{listing.exists ? t("envPage.noVariables", { file }) : t("envPage.notExist", { file })}</span></div>}
            <div className="env-add"><button className="btn small" onClick={() => edit((list) => [...list, newRow(list)])}>{t("envPage.addVariable")}</button></div>
          </div>
        </> : <p className="error" role="alert">{t("envPage.cannotOpen", { file, error: loaded.errors[file] })}</p>}

        <div className="env-jev">
          <div className="env-jev-row">
            <div className="grow">
              <b id="jev-label">{t("envPage.jevTitle")}</b>
              <div className="sub">{t("envPage.jevSub1")} <span className="mono">GSD_PATH_JEV=1</span> {t("envPage.jevSub2")} <span className="mono">TYPESAFE_API_KEY</span>{t("envPage.jevSub3")}</div>
            </div>
            <button className="env-toggle" role="switch" aria-checked={on.length > 0} aria-labelledby="jev-label"
              disabled={busy || dirty || !!jevPreview} onClick={previewJev}><i /></button>
          </div>
          <div className="env-jev-target">
            <label htmlFor="jev-file">{t("envPage.writeFlagTo")}</label>
            <select id="jev-file" value={on[0] ?? jevTarget} disabled={on.length > 0 || !!jevPreview}
              onChange={(event) => setJevTarget(event.target.value as EnvFile)}>
              {ENV_FILES.map((name) => <option key={name}>{name}</option>)}
            </select>
            <span>{on.length ? t("envPage.onIn", { files: on.join(t("list.separator")) }) : dirty ? t("envPage.saveOrDiscardFirst", { file }) : ""}</span>
          </div>
          {jevPreview && (
            <div className="env-preview">
              <b>{jevPreview.on ? t("envPage.turnJevOn") : t("envPage.turnJevOff")}</b>
              {jevPreview.items.map((item) => (
                <div key={item.file}><span className="mono">{item.file}</span>
                  <ul>{item.diff.length ? diffLines(item.diff).map((line) => <li key={line} className="mono">{line}</li>) : <li>{t("envPage.flagAlreadySet")}</li>}</ul>
                </div>
              ))}
              <div className="actions">
                <button className="btn primary" onClick={confirmJev} disabled={busy}>{t("envPage.confirm")}</button>
                <button className="btn" onClick={() => setJevPreview(null)} disabled={busy}>{t("updates.cancel")}</button>
              </div>
            </div>
          )}
          {jevError && <p className="env-error" role="alert">{jevError}</p>}
        </div>

        {preview && (
          <div className="env-preview">
            <b>{t("envPage.changesTo", { file })}</b>
            <ul>{diffLines(preview.diff).map((line) => <li key={line} className="mono">{line}</li>)}</ul>
            <div className="sub">{t("envPage.onlyRewritten", { file })}</div>
            <div className="actions">
              <button className="btn primary" onClick={confirmSave} disabled={busy}>{t("envPage.confirm")}</button>
              <button className="btn" onClick={() => setPreview(null)} disabled={busy}>{t("updates.cancel")}</button>
            </div>
          </div>
        )}
        <div className="env-foot">
          <button className="btn primary" onClick={previewSave} disabled={busy || !listing || !dirty || !!preview}>{t("envPage.saveFile", { file })}</button>
          <button className="btn" onClick={() => reset(listing)} disabled={busy || !dirty}>{t("settings.discard")}</button>
          <span className={note?.bad ? "env-note bad" : "env-note"} role={note?.bad ? "alert" : "status"}>
            {note ? note.text : dirty ? t("envPage.unsavedChanges") : t("envPage.savingNote")}
          </span>
        </div>
      </>}
    </main>
  );
}
