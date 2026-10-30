// The tray popover: a 380px window of its own (label "tray") that loads this bundle at #/tray.
import { useState } from "react";
import { t } from "../i18n";
import { readyLine, reviewAction } from "../appUpdate";
import { boot, openUrl, trayAction } from "../shell";
import type { Shell } from "../shell";
import { clock } from "../status";
import { attentionCards, trayRows, trayStatus } from "../tray";
import { Cells, CopyButton, Logo } from "../ui";
import { useStatus } from "../useStatus";

export function Tray({ shell }: { shell: Shell }) {
  // A new shell state (start, stop, restart) reads the monitor again at once.
  const { status, offline } = useStatus(shell);
  const [open, setOpen] = useState<string | null>(null);
  const projects = status?.projects ?? [];
  const state = trayStatus(status, offline);
  const stopped = state.tone === "bad";
  const attention = attentionCards(projects);
  const updated = clock(status?.generated_at);
  const appLine = readyLine(shell, status?.plugin?.update_available ? 1 : 0);

  return (
    <div className="tray">
      <div className="tray-head">
        <Logo label={false} /><b className="grow">OpenGSD Path</b>
        <i className={`dot ${state.tone}`} /><span className="sub">{state.text}</span>
      </div>
      {shell.phase === "blocked" ? (
        <div className="tray-strip">
          <span className="grow">{t("trayPop.setupAttention")}</span>
          <button className="btn tiny" onClick={() => trayAction("open")}>{t("trayPop.open")}</button>
        </div>
      ) : stopped && shell.phase === "ready" && (
        <div className="tray-strip">
          <span className="grow">{t("trayPop.monitorStopped")}{updated && " " + t("trayPop.showingFrom", { time: updated })}</span>
          <button className="btn tiny" onClick={() => boot()}>{t("trayPop.start")}</button>
        </div>
      )}
      <div className={stopped ? "tray-body stopped" : "tray-body"}>
        {attention.length > 0 && <>
          <div className="tray-cap attention">{t("trayPop.needsAttention", { n: attention.length })}</div>
          {attention.map((card) => (
            <button key={card.root} className="tray-card" onClick={() => trayAction("open", card.root)}>
              <span className="grow"><b>{card.name}</b><span className="sub" style={{ display: "block" }}>{card.reason}</span></span>
              <span>{t("trayPop.openArrow")}</span>
            </button>
          ))}
        </>}
        {projects.length > 0 && <div className="tray-cap">{t("nav.projects")}</div>}
        {trayRows(projects).map((row) => (
          <div key={row.root}>
            <button className={row.quiet ? "tray-row quiet" : "tray-row"} aria-expanded={open === row.root}
              onClick={() => setOpen(open === row.root ? null : row.root)}>
              <i className={`dot small ${row.tone}`} />
              <span className="grow"><b>{row.name}</b><span className="sub" style={{ display: "block" }}>{row.line}</span></span>
              <Cells cells={row.cells} />
            </button>
            {open === row.root && (
              <div className="tray-open">
                <button className="btn tiny" onClick={() => trayAction("open", row.root)}>{t("trayPop.details")}</button>
                <CopyButton className="btn tiny" text="/path" label={t("trayPop.copyPath")} />
              </div>
            )}
          </div>
        ))}
      </div>
      {(appLine || status?.plugin?.update_available) && (
        <div className="tray-strip update">
          <span className="grow"><b>{appLine ?? t("trayPop.skillsReady", { version: status?.plugin?.latest ?? t("trayPop.updateWord") })}</b></span>
          <button className="btn tiny primary" onClick={() => trayAction(reviewAction(shell))}>{t("trayPop.review")}</button>
        </div>
      )}
      <div className="tray-foot">
        <button className="btn primary" onClick={() => trayAction("open")}>{t("trayPop.openDashboard")}</button>
        <button className="btn quiet" disabled={stopped} onClick={() => openUrl(`http://127.0.0.1:${shell.port}/`)}>{t("trayPop.inBrowser")}</button>
        <span className="grow" />
        <button className="btn quiet" disabled={!shell.owned} onClick={() => trayAction("restart")}>{t("trayPop.restart")}</button>
        <button className="btn quiet" onClick={() => trayAction("quit")}>{t("trayPop.quit")}</button>
      </div>
    </div>
  );
}
