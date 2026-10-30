// The Projects board: one row per project, with filters and search.
import { useState } from "react";
import { t } from "../i18n";
import { boardRow, filterCounts, setupPill, updateBanner, visibleProjects } from "../board";
import { projectHash, settingsHash } from "../route";
import { targetVersion } from "../skills";
import type { usePlugin } from "../skillsApi";
import { DASH, flavorOf } from "../status";
import type { Status } from "../status";
import { Cells } from "../ui";
import "./skills.css";

export function Board({ status, offline, now, skills }: { status: Status | null; offline: boolean; now: number; skills: ReturnType<typeof usePlugin> }) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const projects = status?.projects ?? [];
  const shown = visibleProjects(projects, filter, query);
  const { plugin, hosts, error: setupError } = skills;
  const banner = updateBanner(hosts, plugin, projects);
  const setupOf = (root: string) => setupPill(plugin?.projects.find((item) => item.root === root), targetVersion(plugin));
  const empty = !status ? (offline ? t("board.empty.offline") : t("board.empty.loading"))
    : !projects.length ? t("board.empty.none")
    : t("board.empty.filtered");

  return (
    <main className="page" aria-label={t("nav.projects")}>
      {banner && (
        <div className="update-banner" role="status">
          <b>{banner.title}</b><span>{banner.text}</span>
          <a className="btn small" href={settingsHash("updates")}>{t("board.reviewUpdates")}</a>
        </div>
      )}
      <div className="board-head">
        <h1 className="title">{t("nav.projects")}</h1>
        <p>{t("board.tagline")}</p>
      </div>
      <div className="filters">
        {filterCounts(projects).map((item) => (
          <button key={item.key} className="filter" aria-pressed={filter === item.key} onClick={() => setFilter(item.key)}>
            {item.label}<span>{item.count}</span>
          </button>
        ))}
        <label className="search">
          <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
            <path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <input type="search" placeholder={t("board.findProject")} aria-label={t("board.findProject")} value={query}
            onChange={(event) => setQuery(event.target.value)} />
        </label>
      </div>
      {shown.length ? (
        <div className="scroll-x"><div className="board with-setup">
          <div className="board-th">
            <span>{t("board.col.project")}</span><span>{t("board.col.milestone")}</span><span>{t("board.col.status")}</span><span className="num">{t("board.col.tasks")}</span><span className="num">{t("board.col.usage")}</span><span>{t("board.col.setup")}</span>
          </div>
          {shown.map((project) => ({ ...boardRow(project, now), setup: flavorOf(project) ? null : setupOf(project.root) })).map((row) => (
            <div key={row.id} className="board-row" onClick={() => { location.hash = projectHash(row.id); }}>
              <div>
                <a className="pname" href={projectHash(row.id)}><i className={`dot small ${row.tone}`} />{row.name}{row.flavor && <span className="pill mute flavor">{row.flavor}</span>}</a>
                <div className="ppath">{row.path}</div>
              </div>
              <div>
                <div className="ms-name"><span className="mono">{row.number}</span> {row.slug}</div>
                <div className="ms-phase"><Cells cells={row.cells} />{row.phase}</div>
              </div>
              <div>
                <span className={`state ${row.state}`}>{row.label}</span>
                {row.note && <div className="state-note">{row.note}</div>}
                <div className="meta">{row.ago}</div>
              </div>
              <div className="num">{row.tasks}</div>
              <div className="num">{row.cost}<div className="meta">{row.turns}</div></div>
              <div>
                {row.setup ? <span className={`pill ${row.setup.tone}`}>{row.setup.label}</span>
                  : row.flavor ? <span className="meta">{DASH}</span>
                  : <span className="meta" title={setupError ?? undefined}>{plugin ? t("board.notReported") : setupError ? t("board.notAvailable") : DASH}</span>}
              </div>
            </div>
          ))}
        </div></div>
      ) : <div className="empty">{empty}</div>}
      <div className="board-foot">
        <span>{t("board.count", { shown: shown.length, total: projects.length })}</span><span>{t("board.usageNote")}</span>
      </div>
    </main>
  );
}
