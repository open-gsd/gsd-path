// The app's own update: the "ready" dialog, the refused state, and the row in Settings → Updates.
import { useState } from "react";
import { t } from "../i18n";
import { appUpdateRow, refusedText } from "../appUpdate";
import { checkUpdate, installUpdate } from "../shell";
import type { Shell } from "../shell";
import { CopyButton } from "../ui";

/** Settings asks the main window to show the dialog with this event; the tray asks through the shell. */
export const SHOW_UPDATE = "gsd-path:show-update";

export function AppUpdateDialog({ shell, onClose }: { shell: Shell; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const row = appUpdateRow(shell);
  if (!row || row.state === "check-failed" || !shell.update) return null;
  // A refused install comes back as shell.update_error through the shell event.
  const install = () => { setBusy(true); installUpdate().catch(() => undefined).finally(() => setBusy(false)); };
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-labelledby="update-title">
      <div className="modal-card">
        {row.state === "refused" ? (
          <>
            <b id="update-title">{t("appUpdateDialog.notInstalled", { version: shell.update.version })}</b>
            <span>{refusedText(shell)}</span>
            <div className="modal-actions">
              <CopyButton text={refusedText(shell)} label={t("appUpdateDialog.copyDetails")} />
              <button className="btn" onClick={onClose}>{t("updates.close")}</button>
              <button className="btn primary" disabled={busy} onClick={install}>{busy ? t("appUpdateDialog.trying") : t("common.tryAgain")}</button>
            </div>
          </>
        ) : (
          <>
            <b id="update-title">{t("appUpdateDialog.ready", { version: shell.update.version })}</b>
            <span>{t("appUpdateDialog.restartNote")}{row.notes ? ` ${row.notes}` : ""}</span>
            <div className="modal-actions">
              <button className="btn" disabled={busy} onClick={onClose}>{t("appUpdateDialog.later")}</button>
              <button className="btn primary" disabled={busy} onClick={install}>{busy ? t("appUpdateDialog.updating") : t("appUpdateDialog.restartAndUpdate")}</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** The app's row at the top of Settings → Updates. */
export function AppUpdateRow({ shell }: { shell: Shell }) {
  const [checking, setChecking] = useState(false);
  const [checked, setChecked] = useState(false);
  const row = appUpdateRow(shell);
  const check = () => { setChecking(true); checkUpdate().catch(() => undefined).finally(() => { setChecking(false); setChecked(true); }); };
  return (
    <div className="card app-update">
      <div className="set-update">
        <div><b>{t("appUpdateDialog.appRow")}</b>
          <div className="set-path">
            {row?.state === "check-failed" ? t("appUpdateDialog.checkFailed", { error: shell.update_error })
              : row?.state === "refused" ? refusedText(shell)
              : checked && !row ? t("appUpdateDialog.newest") : t("appUpdateDialog.signed")}
          </div>
        </div>
        <span className="set-version">{row?.text ?? shell.version}</span>
        {row && row.state !== "check-failed"
          ? <button className="btn small primary" onClick={() => dispatchEvent(new Event(SHOW_UPDATE))}>{row.state === "refused" ? t("appUpdateDialog.details") : t("appUpdateDialog.updateEllipsis")}</button>
          : <button className="btn small" disabled={checking} onClick={check}>{checking ? t("appUpdateDialog.checking") : t("skillsPage.checkForUpdates")}</button>}
      </div>
    </div>
  );
}
