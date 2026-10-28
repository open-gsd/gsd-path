// Shown once when the launch check found startup entries from the old tray apps.
import { t } from "../i18n";
import type { LegacyEntry, Shell } from "../shell";
import { Logo } from "../ui";

// Names come from legacy_registrations() in daemon/gsd_daemon/launch.py.
const ENTRY: Record<string, [string, string]> = {
  "launch-agent": ["LaunchAgent", "org.gsd-path.daemon"],
  "tray-app": ["Swift tray app", "~/Applications/GSDPathTray.app"],
  "login-item": ["Swift tray app login item", "GSDPathTray in Login Items"],
  "login-item-unknown": ["Login items could not be read", "System Events access was not allowed"],
  "startup-shortcut": ["Startup shortcut", "gsd-path-daemon.lnk in the Startup folder"],
  "systemd-unit": ["systemd user unit", "gsd-path-daemon.service"],
};

const MONITOR_WORD = () => ({
  waiting: t("firstLaunch.waiting"), replaced: t("firstLaunch.replaced"), kept: t("firstLaunch.kept"), started: t("firstLaunch.started"),
});

function monitorLine(shell: Shell): [string, string, string, "ok" | "warn"] {
  const launch = shell.launch!;
  const words = MONITOR_WORD();
  if (shell.phase !== "ready") return [t("firstLaunch.notStartedYet"), t("firstLaunch.fixThenCheck"), words.waiting, "warn"];
  if (launch.replaced) {
    return [t("firstLaunch.versionWasRunning", { version: launch.replaced }),
      t("firstLaunch.replacedText", { version: launch.version }), words.replaced, "ok"];
  }
  if (launch.action === "reuse") {
    return [t("firstLaunch.versionIsRunning", { version: launch.version }), t("firstLaunch.keptText"), words.kept, "ok"];
  }
  return [t("firstLaunch.versionStarted", { version: launch.version }), t("firstLaunch.startedText"), words.started, "ok"];
}

function Entry({ entry }: { entry: LegacyEntry }) {
  const [name, detail] = ENTRY[entry.name] ?? [entry.name, ""];
  return (
    <div className="row">
      <div className="line">
        <i className={`dot ${entry.removed ? "ok" : "bad"}`} />
        <div className="grow"><b>{name}</b><div className="mono sub" style={{ fontSize: 12 }}>{detail}</div></div>
        <span className={`pill ${entry.removed ? "ok" : "bad"}`}>{entry.removed ? t("firstLaunch.removed") : t("firstLaunch.stillPresent")}</span>
      </div>
      {!entry.removed && (
        <div className="manual"><div style={{ fontWeight: 600, marginBottom: 4 }}>{t("firstLaunch.removeByHand")}</div>
          <div className="mono" style={{ fontSize: 12, overflowWrap: "anywhere" }}>{entry.fix}</div></div>
      )}
    </div>
  );
}

export function FirstLaunch({ shell, onRetry, onDone }: { shell: Shell; onRetry: () => void; onDone: () => void }) {
  const launch = shell.launch!;
  const failed = launch.legacy.some((entry) => !entry.removed);
  const [title, text, label, tone] = monitorLine(shell);
  return (
    <div className="center">
      <div className="column">
        <div>
          <Logo size={26} label={false} />
          <h1 className="title" style={{ marginTop: 14 }}>{t("firstLaunch.title")}</h1>
          <p className="lead">{t("firstLaunch.lead")}</p>
        </div>
        <div className="card">
          <div className="row-head">{t("firstLaunch.step1")}</div>
          {launch.legacy.map((entry) => <Entry key={entry.name} entry={entry} />)}
          <div className="row-head">{t("firstLaunch.step2")}</div>
          <div className="row line">
            <i className={`dot ${tone}`} />
            <div className="grow"><b>{title}</b><div className="sub">{text}</div></div>
            <span className={`pill ${tone}`}>{label}</span>
          </div>
          <div className="row-head">{t("firstLaunch.step3")}</div>
          <div className="row line">
            <div className="grow" style={{ fontSize: 13, color: "var(--dim)" }}>
              {failed ? t("firstLaunch.loginStaysOff")
                : shell.autostart ? t("firstLaunch.loginTurnedOn")
                : t("firstLaunch.loginOff")}
            </div>
            <span className={`pill ${failed ? "warn" : shell.autostart ? "ok" : "mute"}`}>
              {failed ? MONITOR_WORD().waiting : shell.autostart ? t("firstLaunch.on") : t("firstLaunch.off")}
            </span>
          </div>
        </div>
        <div className="actions">
          {failed ? (
            <>
              <button className="btn primary" onClick={onRetry}>{t("common.checkAgain")}</button>
              <button className="btn" onClick={onDone}>{t("firstLaunch.continueWithout")}</button>
            </>
          ) : <button className="btn primary" onClick={onDone}>{t("trayPop.openDashboard")}</button>}
        </div>
      </div>
    </div>
  );
}
