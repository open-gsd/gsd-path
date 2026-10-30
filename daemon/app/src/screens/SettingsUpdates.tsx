// Settings → Updates: skills per agent folder and the runtime of each project. Each update is previewed first.
import { Fragment, useEffect, useState } from "react";
import { t } from "../i18n";
import { allCurrent, opOutcome, updatePlan, updateRows } from "../settingsUpdates";
import type { OpResult, PluginStatus, UpdateStep } from "../settingsUpdates";
import { api } from "../shell";
import { nameOf } from "../status";
import type { Shell } from "../shell";
import { AppUpdateRow } from "./AppUpdate";
import type { Status } from "../status";
import { FixText } from "../ui";

type Op = { step: UpdateStep; phase: "checking" | "preview" | "running" | "done" | "failed"; output: string; error: string };

export function UpdatesTab({ shell, status }: { shell: Shell; status: Status | null }) {
  const [plugin, setPlugin] = useState<PluginStatus | null>(null);
  const [error, setError] = useState("");
  const [ops, setOps] = useState<Record<string, Op>>({});
  /** "Update all" waits for one confirmation for every preview. */
  const [all, setAll] = useState<"" | "confirm" | "stopped">("");

  const load = () => api<PluginStatus>("GET", "/api/plugin/status").then(
    (next) => { setPlugin(next); setError(next.error ?? ""); }, (reason) => setError(String(reason)));
  useEffect(() => { load(); }, []);

  const names = Object.fromEntries((status?.projects ?? []).map((project) => [project.root, nameOf(project)]));
  const rows = plugin ? updateRows(plugin, names) : [];
  const plan = updatePlan(rows);
  const busy = Object.values(ops).some((op) => op.phase === "checking" || op.phase === "running");
  const setOp = (id: string, op: Op | null) => setOps((old) => {
    const { [id]: _gone, ...rest } = old;
    return op ? { ...rest, [id]: op } : rest;
  });

  /** One request to the installer. Returns true when it worked. */
  const send = async (step: UpdateStep, dryRun: boolean) => {
    setAll((old) => (old === "stopped" ? "" : old));
    setOp(step.id, { step, phase: dryRun ? "checking" : "running", output: "", error: "" });
    try {
      const result = opOutcome(await api<OpResult>("POST", "/api/plugin/update", { ...step.body, ...(dryRun ? { dry_run: true } : {}) }));
      setOp(step.id, { ...result, step, phase: !result.ok ? "failed" : dryRun ? "preview" : "done" });
      return result.ok;
    } catch (reason) {
      setOp(step.id, { step, phase: "failed", output: "", error: String(reason) });
      return false;
    }
  };
  const run = async (step: UpdateStep) => { await send(step, false); await load(); };
  const previewAll = async () => {
    setAll("");
    for (const step of plan) if (!(await send(step, true))) return;
    setAll("confirm");
  };
  const runAll = async () => {
    setAll("");
    for (const step of plan) {
      if (await send(step, false)) continue;
      setAll("stopped");
      break;
    }
    await load();
  };
  const cancelAll = () => { setAll(""); setOps({}); };

  // The preview and result of an action show under the last row it updates.
  const last = Object.fromEntries(rows.map((row) => [row.group, row.key]));
  return (
    <>
      <div className="set-head">
        <h2>{t("settings.tab.updates")}</h2>
        <button className="btn primary" disabled={busy || !plan.length || all === "confirm"} onClick={previewAll}>{t("updates.updateAll")}</button>
      </div>
      <AppUpdateRow shell={shell} />
      {error && <div className="error" role="alert">{t("updates.cannotRead")} <FixText text={error} /></div>}
      {all === "confirm" && (
        <div className="set-confirm" role="status">
          <span className="grow"><b>{t(plan.length === 1 ? "updates.oneReady" : "updates.manyReady", { n: plan.length })}</b> {t("updates.nothingChangedPreviews")}</span>
          <button className="btn small primary" onClick={runAll}>{t("updates.updateAllNow")}</button>
          <button className="btn small" onClick={cancelAll}>{t("updates.cancel")}</button>
        </div>
      )}
      {all === "stopped" && <div className="error" role="alert">{t("updates.updateFailedStopped")}</div>}
      {!plugin ? (!error && <p className="note">{t("updates.reading")}</p>) : (
        <>
          {allCurrent(rows) && !busy && (
            <p className="set-fine" role="status">
              <i className="dot ok" />{t("updates.everythingCurrent")}{!rows.length && " " + t("updates.nothingInstalled")}
            </p>
          )}
          {rows.length > 0 && (
            <div className="card">
              {rows.map((row) => {
                const op = last[row.group] === row.key ? ops[row.group] : undefined;
                return (
                  <Fragment key={row.key}>
                    <div className="set-update">
                      <div><b>{row.name}</b><div className="set-path">{row.sub}</div></div>
                      <span className="set-version">{row.version}</span>
                      {row.state === "current" ? <span className="pill ok">{t("setup.upToDate")}</span>
                        : row.state === "unknown" ? <span className="pill mute">{row.note}</span>
                        : <button className="btn small" disabled={busy || all === "confirm" || !!ops[row.group]}
                            onClick={() => send(row.step!, true)}>{row.note || t("updates.update")}</button>}
                    </div>
                    {op && <OpPanel op={op} solo={all !== "confirm"} busy={busy}
                      onRun={() => run(op.step)} onRetry={() => send(op.step, true)} onClose={() => setOp(row.group, null)} />}
                  </Fragment>
                );
              })}
            </div>
          )}
          {plugin.latest == null && !error && (
            <p className="note">{t("updates.latestNotKnown", { skills: t("nav.skills") })}</p>
          )}
          <p className="note">{t("updates.separateNote")}</p>
        </>
      )}
    </>
  );
}

/** The preview, progress and result of one update, under its row. */
function OpPanel({ op, solo, busy, onRun, onRetry, onClose }: {
  op: Op; solo: boolean; busy: boolean; onRun: () => void; onRetry: () => void; onClose: () => void;
}) {
  const output = op.output ? <pre className="code set-output">{op.output}</pre> : null;
  return (
    <div className="set-op" aria-live="polite">
      {op.phase === "checking" && <span className="sub">{t("updates.preparingPreview")}</span>}
      {op.phase === "running" && <span className="sub">{t("updates.updatingDoNotClose")}</span>}
      {op.phase === "preview" && (
        <>
          <div><b>{t("updates.previewOf", { label: op.step.label })}</b> <span className="sub">{t("updates.nothingChanged")}</span></div>
          {output ?? <span className="sub">{t("updates.noPreview")}</span>}
          {solo && (
            <div className="actions">
              <button className="btn small primary" disabled={busy} onClick={onRun}>{t("updates.updateNow")}</button>
              <button className="btn small" disabled={busy} onClick={onClose}>{t("updates.cancel")}</button>
            </div>
          )}
        </>
      )}
      {op.phase === "done" && (
        <>
          <div className="line"><span className="pill ok">{t("updates.updated")}</span><span className="sub grow">{op.step.label}</span>
            <button className="link" onClick={onClose}>{t("updates.hide")}</button></div>
          {output}
        </>
      )}
      {op.phase === "failed" && (
        <>
          <div className="error" role="alert"><b>{t("updates.didNotFinish")}</b> <FixText text={op.error} /></div>
          {output}
          <div className="actions">
            <button className="btn small" disabled={busy} onClick={onRetry}>{t("common.tryAgain")}</button>
            <button className="btn small" disabled={busy} onClick={onClose}>{t("updates.close")}</button>
          </div>
        </>
      )}
    </div>
  );
}
