// Pieces the Settings tabs share.
import type { ReactNode } from "react";
import { t } from "../i18n";

/** An on/off switch: 36×22 with an 18px knob. */
export function Toggle({ on, label, disabled, onChange }: { on: boolean; label: string; disabled?: boolean; onChange: (on: boolean) => void }) {
  return (
    <button type="button" role="switch" className="set-toggle" aria-checked={on} aria-label={label} disabled={disabled}
      onClick={() => onChange(!on)}><i /></button>
  );
}

/** One setting: name and hint on the left, the control on the right. */
export function Field({ name, hint, children }: { name: string; hint?: ReactNode; children?: ReactNode }) {
  return (
    <div className="set-field">
      <div className="grow"><b>{name}</b>{hint && <div className="sub">{hint}</div>}</div>
      {children}
    </div>
  );
}

/** The changes a save will write, then Save and Discard. Save is the confirmation of the list. */
export function SaveBar({ summary, errors, error, note, busy, onSave, onDiscard }: {
  summary: string[]; errors: string[]; error: string; note: string; busy: boolean; onSave: () => void; onDiscard: () => void;
}) {
  const dirty = summary.length > 0 || errors.length > 0;
  return (
    <div className="set-save">
      {summary.length > 0 && (
        <div className="set-changes">
          <b>{summary.length === 1 ? t("settings.saveWillWriteOne") : t("settings.saveWillWrite", { n: summary.length })}</b>
          <ul>{summary.map((line) => <li key={line}>{line}</li>)}</ul>
        </div>
      )}
      {errors.length > 0 && <ul className="set-errors" role="alert">{errors.map((line) => <li key={line}>{line}</li>)}</ul>}
      {error && <div className="error" role="alert">{error}</div>}
      <div className="actions">
        <button className="btn primary" disabled={busy || !summary.length} onClick={onSave}>{busy ? t("settings.saving") : t("settings.save")}</button>
        <button className="btn" disabled={busy || !dirty} onClick={onDiscard}>{t("settings.discard")}</button>
        {note && <span className="sub" role="status">{note}</span>}
      </div>
    </div>
  );
}
