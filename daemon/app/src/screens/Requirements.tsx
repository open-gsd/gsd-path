// The setup wizard: Requirements, Agents, Skills, Watch folders. Steps 2 to 4 need the monitor.
import { useState } from "react";
import { t } from "../i18n";
import { requirementRows } from "../screen";
import { footer, preselected, stepGate, STEPS } from "../setup";
import type { Shell } from "../shell";
import { usePlugin } from "../skillsApi";
import { ActionButton, Logo } from "../ui";
import { SetupAgents } from "./SetupAgents";
import { SetupFolders } from "./SetupFolders";
import { SetupSkills } from "./SetupSkills";
import "./setup.css";
import "./skills.css";

const TONE = { ok: "ok", warn: "warn", miss: "bad" } as const;

export function Requirements({ shell, onRetry, onDone }: { shell: Shell; onRetry: () => void; onDone: () => void }) {
  const { rows, blocked } = requirementRows(shell);
  const ready = shell.phase === "ready";
  const [wanted, setStep] = useState(0);
  const step = stepGate(wanted, ready);
  // The agent list and the releases load when the monitor runs.
  const { plugin, hosts, error, reload } = usePlugin(ready);
  const [picked, setPicked] = useState<string[] | null>(null); // null: the user has not changed the preselection
  const selected = picked ?? preselected(hosts);
  const [installing, setInstalling] = useState(false);
  const foot = footer(step, { blocked, ready, installing });
  const toggle = (id: string) => setPicked(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id]);

  return (
    <div className="setup">
      <aside className="rail">
        <Logo size={20} />
        {STEPS().map((label, index) => (
          <button key={label} className={`step${index === step ? " current" : index < step ? " done" : ""}`}
            aria-current={index === step ? "step" : undefined} disabled={index > step || installing} onClick={() => setStep(index)}>
            <span className="step-mark">{index < step ? "✓" : index + 1}</span>{label}
          </button>
        ))}
        <div className="rail-foot">{t("setupWizard.railFoot")}</div>
      </aside>
      <div className="setup-main">
        <div className="setup-body">
          <div className="eyebrow">{t("setupWizard.stepOf", { n: step + 1, total: STEPS().length })}</div>
          {step === 0 && <>
            <h1 className="title">{t("setupWizard.needsTitle")}</h1>
            <p className="lead setup-lead">{t("setupWizard.needsLead")}</p>
            <div className="card">
              {rows.map((row) => (
                <div className="req" key={row.id}>
                  <div className="grow">
                    <div className="line" style={{ gap: 8, flexWrap: "wrap" }}>
                      <i className={`dot ${row.tone === "miss" && !row.required ? "" : TONE[row.tone]}`} />
                      <b>{row.name}</b>
                      <span className={`pill ${row.tone === "miss" && !row.required ? "mute" : TONE[row.tone]}`}>{row.pill}</span>
                    </div>
                    <div className="req-detail">{row.detail}</div>
                    <div className="req-hint">{row.hint}</div>
                  </div>
                  {row.action && <ActionButton action={row.action} />}
                </div>
              ))}
            </div>
            {shell.os === "windows" && (
              <p className="note">{t("setupWizard.webview2")}</p>
            )}
            {blocked && <p className="note danger">{t("setupWizard.installThenCheck")}</p>}
          </>}
          {step > 0 && error && <p className="error" role="alert">{error} <button className="link" onClick={reload}>{t("common.tryAgain")}</button></p>}
          {step === 1 && <SetupAgents hosts={hosts} selected={selected} onToggle={toggle} />}
          {step === 2 && <SetupSkills hosts={hosts} selected={selected} plugin={plugin} reload={reload} onBusy={setInstalling} />}
          {step === 3 && <SetupFolders />}
        </div>
        <div className="setup-foot">
          {foot.back && <button className="btn" onClick={() => setStep(step - 1)}>{t("common.back")}</button>}
          <span style={{ marginLeft: "auto" }} />
          {step === 0 && <button className="btn" onClick={onRetry}>{t("common.checkAgain")}</button>}
          {foot.skip && <button className="btn quiet" onClick={onDone}>{t("setupWizard.skipForNow")}</button>}
          <button className="btn primary" disabled={!foot.canNext} onClick={() => (step === STEPS().length - 1 ? onDone() : setStep(step + 1))}>{foot.next}</button>
        </div>
      </div>
    </div>
  );
}
