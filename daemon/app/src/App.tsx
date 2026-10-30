import { useEffect, useState } from "react";
import { parseRoute } from "./route";
import { pickScreen } from "./screen";
import { boot, getShell, onShellChange, onShowUpdate, usePort } from "./shell";
import type { Shell } from "./shell";
import { t, useLanguage } from "./i18n";
import { FirstLaunch } from "./screens/FirstLaunch";
import { BlockingProblems, PortInUse, PythonMissing } from "./screens/Problems";
import { AppUpdateDialog, SHOW_UPDATE } from "./screens/AppUpdate";
import { Dashboard } from "./screens/Dashboard";
import { Requirements } from "./screens/Requirements";
import { Tray } from "./screens/Tray";

const SETUP_DONE = "gsd-path.setup-done";

export function App() {
  useLanguage();
  const [shell, setShell] = useState<Shell | null>(null);
  const [setupDone, setSetupDone] = useState(() => localStorage.getItem(SETUP_DONE) === "1");
  const [firstLaunchSeen, setFirstLaunchSeen] = useState(false);
  const [hash, setHash] = useState(location.hash);
  // The version the update dialog shows; "Later" closes it until Settings or the tray asks again.
  const [updateShown, setUpdateShown] = useState<string | null>(null);
  const offered = shell?.update?.version ?? null;
  // A newly found update opens the dialog one time.
  useEffect(() => { if (offered) setUpdateShown(offered); }, [offered]);

  useEffect(() => {
    getShell().then(setShell);
    // The tray can also start, stop, or restart the monitor.
    const stop = onShellChange(setShell);
    const onHash = () => setHash(location.hash);
    addEventListener("hashchange", onHash);
    const showUpdate = () => setUpdateShown("asked");
    addEventListener(SHOW_UPDATE, showUpdate);
    const stopShow = onShowUpdate(showUpdate);
    return () => {
      stop.then((off) => off());
      stopShow.then((off) => off());
      removeEventListener("hashchange", onHash);
      removeEventListener(SHOW_UPDATE, showUpdate);
    };
  }, []);

  if (!shell) return null;
  const route = parseRoute(hash);
  // The tray popover is a window of its own; setup screens stay in the main window.
  if (route.page === "tray") return <Tray shell={shell} />;
  const retry = () => { setShell({ ...shell, phase: "checking" }); boot().then(setShell); };
  const finishSetup = () => { localStorage.setItem(SETUP_DONE, "1"); setSetupDone(true); };

  switch (pickScreen(shell, { setupDone, firstLaunchSeen })) {
    case "checking":
      return <div className="center"><p className="lead">{t("app.checking")}</p></div>;
    case "first-launch":
      return <FirstLaunch shell={shell} onRetry={retry} onDone={() => setFirstLaunchSeen(true)} />;
    case "requirements":
      return <Requirements shell={shell} onRetry={retry} onDone={finishSetup} />;
    case "python":
      return <PythonMissing shell={shell} onRetry={retry} />;
    case "port":
      return <PortInUse shell={shell} onRetry={retry}
        problem={shell.launch!.problems.find((problem) => problem.kind === "port")!}
        onUsePort={(port) => { setShell({ ...shell, phase: "checking" }); usePort(port).then(setShell); }} />;
    case "problem":
      return <BlockingProblems shell={shell} onRetry={retry} />;
    case "ready":
      return (
        <>
          <Dashboard shell={shell} route={route} onStart={retry} />
          {updateShown && <AppUpdateDialog shell={shell} onClose={() => setUpdateShown(null)} />}
        </>
      );
  }
}
