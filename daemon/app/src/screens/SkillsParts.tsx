// Pieces the Skills page, the project Setup card and the setup wizard share.
import { useState } from "react";
import { t } from "../i18n";
import { api } from "../shell";
import { releaseOptions } from "../skills";
import type { Failure, Releases, UninstallPlan } from "../skills";
import { message } from "../skillsApi";
import { CopyButton } from "../ui";

/** Installer output, as the daemon sent it. */
export function Output({ text }: { text: string }) {
  return <pre className="sk-out">{text || t("updates.noPreview")}</pre>;
}

/** Latest plus the older releases. Hidden when the daemon installs from a git clone. */
export function ReleasePicker({ releases, disabled, onChanged }: { releases: Releases | undefined; disabled?: boolean; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const options = releaseOptions(releases);
  if (!options) return null;
  const choose = async (value: string) => {
    setBusy(true);
    setError(null);
    try {
      await api<Releases>("POST", "/api/plugin/release", { version: value || null });
      onChanged();
    } catch (failed) {
      setError(message(failed));
    }
    setBusy(false);
  };
  return (
    <label className="sk-field">{t("skillsPage.release")}
      <select value={releases!.selected ?? ""} disabled={disabled || busy} onChange={(event) => choose(event.target.value)}>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
      {error && <span className="sk-field-error" role="alert">{error}</span>}
    </label>
  );
}

/** What failed, what was not changed, the fix, and the installer output on request. */
export function FailureCard({ failure, output, busy, onRetry, onClose }: {
  failure: Failure; output: string; busy?: boolean; onRetry: () => void; onClose?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="sk-fail" role="alert">
      <div className="line"><b>{failure.title}</b><span className="pill bad">{t("skillsPage.failed")}</span></div>
      <span className="sk-fail-text">{failure.text.split("`").map((part, index) => (index % 2 ? <code key={index} className="mono">{part}</code> : part))}
        {failure.unchanged && <> {failure.unchanged}</>}</span>
      {failure.fix && <div className="code">{failure.fix}</div>}
      <div className="actions">
        {failure.fix && <CopyButton text={failure.fix} label={t("skillsPage.copyFix")} className="btn small" />}
        <button className="btn small primary" disabled={busy} onClick={onRetry}>{t("common.tryAgain")}</button>
        <button className="link" aria-expanded={open} onClick={() => setOpen(!open)}>{t("skillsPage.installerOutput")}</button>
        {onClose && <button className="link" onClick={onClose}>{t("updates.close")}</button>}
      </div>
      {open && <Output text={output} />}
    </div>
  );
}

/** An uninstall plan: what is removed and what is kept, then the confirm. */
export function PlanBox({ plan, confirm, busy, onConfirm, onCancel }: {
  plan: UninstallPlan; confirm: string; busy: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <div className="sk-plan">
      <b>{t("skillsPage.plan")}</b>
      {plan.plan.length ? (
        <ul>{plan.plan.map((entry) => <li key={entry.path}><span className="mono">{entry.path}</span><small>{entry.reason}</small></li>)}</ul>
      ) : <div className="sub">{t("skillsPage.nothingToRemove")}</div>}
      {plan.skipped.length > 0 && <>
        <b>{t("skillsPage.kept")}</b>
        <ul>{plan.skipped.map((entry) => <li key={entry.path}><span className="mono">{entry.path}</span><small>{entry.reason}</small></li>)}</ul>
      </>}
      <div className="sub">{t("skillsPage.projectUntouched", { dir: ".project/" })}</div>
      <div className="actions">
        {plan.plan.length > 0 && <button className="btn small sk-danger" disabled={busy} onClick={onConfirm}>{busy ? t("skillsPage.removing") : confirm}</button>}
        <button className="btn small" disabled={busy} onClick={onCancel}>{t("updates.cancel")}</button>
      </div>
    </div>
  );
}
