// gsd-pi and gsd-core on this computer: installed and latest versions, and their update.
// Update first shows the commands it runs; the second click runs them.
import { useState } from "react";
import { t } from "../i18n";
import { api } from "../shell";
import { frameworkRows } from "../skills";
import type { FrameworkRow, PluginStatus } from "../skills";
import { message } from "../skillsApi";
import { Output } from "./SkillsParts";

type Result = { ok: boolean; commands: string[][]; stdout_tail: string; error: string | null };
type Panel =
  | { kind: "preview"; row: FrameworkRow; commands: string }
  | { kind: "done"; text: string; output: string }
  | { kind: "failed"; row: FrameworkRow; error: string; output: string };

const update = (name: string, dry_run: boolean) => api<Result>("POST", "/api/frameworks/update", { name, dry_run });

export function Frameworks({ plugin, errors, reload }: { plugin: PluginStatus | null; errors: Record<string, string | null>; reload: () => void }) {
  const [panel, setPanel] = useState<Panel | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const rows = frameworkRows(plugin, errors);
  if (!rows.length) return null;

  const run = async (row: FrameworkRow, label: string, work: () => Promise<Panel>) => {
    setBusy(label);
    try {
      setPanel(await work());
    } catch (failed) {
      setPanel({ kind: "failed", row, error: message(failed), output: "" });
    }
    setBusy(null);
    reload();
  };
  const preview = (row: FrameworkRow) => run(row, t("frameworks.readingUpdate", { name: row.name }), async () => {
    const result = await update(row.name, true);
    return { kind: "preview", row, commands: result.commands.map((argv) => "$ " + argv.join(" ")).join("\n") };
  });
  const apply = (row: FrameworkRow) => run(row, t("frameworks.updating", { name: row.name }), async () => {
    const result = await update(row.name, false);
    return result.ok
      ? { kind: "done", text: t("frameworks.updated", { name: row.name }), output: result.stdout_tail }
      : { kind: "failed", row, error: result.error || t("frameworks.updateFailed"), output: result.stdout_tail };
  });

  return (
    <section className="frameworks" aria-label={t("frameworks.title")}>
      <h2>{t("frameworks.title")}</h2>
      <p className="note">{t("frameworks.note")}</p>
      <div className="card scroll-x">
        <div className="skills-table">
          <div className="skills-th"><span>{t("frameworks.framework")}</span><span>{t("frameworks.installedIn")}</span><span>{t("skillsPage.version")}</span><span>{t("board.col.status")}</span><span /></div>
          {rows.map((row) => (
            <div key={row.name} className="skills-row">
              <b>{row.name}</b>
              <span className="mono skills-path">{row.where}</span>
              <span className="sk-num-left fw-versions">{row.version}</span>
              <span>
                <span className={`pill ${row.tone}`}>{row.status}</span>
                {row.error && <div className="sk-field-error">{t("frameworks.checkFailed", { error: row.error })}</div>}
              </span>
              <span className="skills-actions">
                {row.update && <button className="btn small primary" disabled={!!busy} onClick={() => preview(row)}>{t("appUpdateDialog.updateEllipsis")}</button>}
              </span>
            </div>
          ))}
        </div>
      </div>
      {busy && <div className="sk-progress" role="status"><div className="bar busy"><i /></div><div className="sub">{busy}</div></div>}
      {!busy && panel?.kind === "preview" && (
        <div className="sk-panel">
          <p className="note">{t("frameworks.runsCommands")}</p>
          <Output text={panel.commands} />
          <div className="actions">
            <button className="btn small primary" onClick={() => apply(panel.row)}>{t("frameworks.updateName", { name: panel.row.name })}</button>
            <button className="btn small" onClick={() => setPanel(null)}>{t("updates.cancel")}</button>
          </div>
        </div>
      )}
      {!busy && panel?.kind === "done" && (
        <div className="sk-panel">
          <div className="sk-done-line" role="status"><i className="dot ok" />{panel.text}</div>
          {panel.output && <Output text={panel.output} />}
        </div>
      )}
      {!busy && panel?.kind === "failed" && (
        <div className="sk-panel" role="alert">
          <p className="error">{t("frameworks.updatingFailed", { name: panel.row.name, error: panel.error })}</p>
          {panel.output && <Output text={panel.output} />}
          <div className="actions">
            <button className="btn small" onClick={() => preview(panel.row)}>{t("common.tryAgain")}</button>
            <button className="btn small" onClick={() => setPanel(null)}>{t("updates.close")}</button>
          </div>
        </div>
      )}
    </section>
  );
}
