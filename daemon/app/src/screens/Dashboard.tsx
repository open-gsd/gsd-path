// The monitor runs: the header, the offline banner and the page the route names.
import { t } from "../i18n";
import type { Route } from "../route";
import type { Shell } from "../shell";
import { pendingSkills } from "../skills";
import { usePlugin } from "../skillsApi";
import { clock, idOf } from "../status";
import { Logo } from "../ui";
import { useStatus } from "../useStatus";
import { Board } from "./Board";
import { Environment } from "./Environment";
import { Files } from "./Files";
import { ProjectPage } from "./Project";
import { Settings } from "./Settings";
import { Skills } from "./Skills";
import { Stats } from "./Stats";

const NAV = () => ({ projects: t("nav.projects"), skills: t("nav.skills"), stats: t("nav.stats"), settings: t("nav.settings") });
// A project page, its files, and its environment all sit under Projects.
const navOf = (route: Route) => (route.page === "project" || route.page === "env" ? "projects" : route.page);

export function Dashboard({ shell, route, onStart }: { shell: Shell; route: Route; onStart: () => void }) {
  const { status, offline, refresh } = useStatus(shell.port);
  const updated = clock(status?.generated_at);
  const now = Date.parse(status?.generated_at ?? "") || Date.now();
  // A project that is no longer watched falls back to the board, as in the daemon dashboard.
  const project = route.page === "project" || route.page === "env"
    ? status?.projects.find((p) => idOf(p) === route.root) : undefined;
  // One plugin state for the nav badge, the Skills page, the board and the project setup card.
  // It loads again on each page or project change and when /status reports other skills or projects.
  const skills = usePlugin(JSON.stringify([route.page, "root" in route && route.root, status?.projects.map(idOf), status?.plugin]));
  const pending = pendingSkills(skills.hosts, skills.plugin).length;

  return (
    <>
      <header className="top">
        <Logo />
        <nav className="nav" aria-label={t("nav.main")}>
          {Object.entries(NAV()).map(([page, label]) => (
            <a key={page} href={"#/" + page} aria-current={navOf(route) === page ? "page" : undefined}>
              {label}{page === "skills" && pending > 0 && <span className="nav-badge">{pending}</span>}
            </a>
          ))}
        </nav>
        <span className="grow" />
        <button className="btn tall" onClick={refresh}>{t("nav.refresh")}</button>
        <span className="updated" role="status">
          <i className={offline ? "dot bad" : status ? "dot ok" : "dot"} />
          {offline ? t("nav.offline") : updated ? t("nav.updated", { time: updated }) : t("nav.connecting")}
        </span>
      </header>
      {offline && (
        <div className="offline" role="status">
          <i className="dot bad" />
          <span className="grow"><b>{t("nav.offlineDot")}</b> {updated ? t("nav.showingLast", { time: updated }) : t("nav.noAnswer")}</span>
          <button className="btn small" onClick={onStart}>{t("nav.startMonitor")}</button>
        </div>
      )}
      {route.page === "skills" ? <Skills skills={skills} />
        : route.page === "stats" ? <Stats status={status} root={route.root} />
        : route.page === "settings" ? <Settings shell={shell} status={status} tab={route.tab} />
        : !project ? <Board status={status} offline={offline} now={now} skills={skills} />
        : route.page === "env" ? <Environment project={project} />
        : route.page === "project" && route.file ? <Files project={project} path={route.file} />
        : <ProjectPage project={project} now={now} stamp={status!.generated_at} skills={skills} />}
    </>
  );
}
