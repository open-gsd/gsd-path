// States where no monitor runs: Python missing, port taken, or another blocking problem.
import { t } from "../i18n";
import { heldByDaemon, pythonFix } from "../screen";
import type { Problem, Shell } from "../shell";
import { ActionButton, CopyButton, FixText, firstCommand } from "../ui";

function Page({ children }: { children: React.ReactNode }) {
  return <div className="center"><div className="column">{children}</div></div>;
}

export function PythonMissing({ shell, onRetry }: { shell: Shell; onRetry: () => void }) {
  const fix = pythonFix(shell.os);
  return (
    <Page>
      <div className="problem">
        <b>{t("problems.pythonTitle")}</b>
        <span>{t("problems.pythonText")}</span>
        {"copy" in fix && <div className="code">{fix.copy}</div>}
        <div className="actions">
          <button className="btn primary" onClick={onRetry}>{t("common.checkAgain")}</button>
          <ActionButton action={fix} primary={false} />
        </div>
      </div>
    </Page>
  );
}

export function PortInUse({ shell, problem, onRetry, onUsePort }: {
  shell: Shell; problem: Problem; onRetry: () => void; onUsePort: (port: number) => void;
}) {
  const { pid, name } = problem.detail ?? {};
  if (heldByDaemon(problem)) {
    return (
      <Page>
        <div className="problem">
          <b>{t("problems.portInUse", { port: shell.port })}</b>
          <span>{problem.message} <FixText text={problem.fix} /></span>
          <div className="actions">
            <button className="btn primary" onClick={onRetry}>{t("common.checkAgain")}</button>
            <button className="btn" onClick={() => onUsePort(shell.port + 1)}>{t("problems.usePort", { port: shell.port + 1 })}</button>
          </div>
        </div>
      </Page>
    );
  }
  return (
    <Page>
      <div className="problem">
        <b>{t("problems.portInUse", { port: shell.port })}</b>
        <span>
          {name
            ? <>{t("problems.namedProgram")}<span className="mono">{name}</span>{pid ? t("problems.pid", { pid }) : ""}{t("problems.listening")} </>
            : t("problems.anotherProgram")}
          {t("problems.leaveRunning")}
        </span>
        <div className="actions">
          <button className="btn primary" onClick={() => onUsePort(shell.port + 1)}>{t("problems.usePort", { port: shell.port + 1 })}</button>
          <button className="btn" onClick={onRetry}>{t("common.checkAgain")}</button>
        </div>
      </div>
    </Page>
  );
}

export function BlockingProblems({ shell, onRetry }: { shell: Shell; onRetry: () => void }) {
  const problems: Problem[] = shell.launch?.problems.filter((problem) => problem.blocking) ?? [];
  if (!problems.length) {
    problems.push({ kind: "launch", message: t("problems.setupFailed"), fix: shell.error ?? t("common.checkAgain") + ".", blocking: true });
  }
  return (
    <Page>
      {problems.map((problem) => {
        const command = firstCommand(problem.fix);
        return (
          <div className="problem" key={problem.kind + problem.message}>
            <b>{problem.message}</b>
            <span><FixText text={problem.fix} /> {t("problems.noMonitor")}</span>
            <div className="actions">
              <button className="btn primary" onClick={onRetry}>{t("common.checkAgain")}</button>
              {command && <CopyButton text={command} label={t("req.copyCommand")} />}
            </div>
          </div>
        );
      })}
    </Page>
  );
}
