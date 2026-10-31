// The Projects board: one row per project, with filters and search.
import { Fragment, useState } from "react";
import { t } from "../i18n";
import { boardRow, coordinatorOf, filterCounts, setupPill, updateBanner, visibleProjects } from "../board";
import { memberRows } from "../project";
import { projectHash, settingsHash } from "../route";
import { targetVersion } from "../skills";
import type { usePlugin } from "../skillsApi";
import { DASH, flavorOf } from "../status";
import type { Status } from "../status";
import { Cells } from "../ui";
import "./setup.css";
import "./skills.css";

export function Board({ status, offline, now, skills }: { status: Status | null; offline: boolean; now: number; skills: ReturnType<typeof usePlugin> }) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const projects = status?.projects ?? [];
  const shown = visibleProjects(projects, filter, query);
  const { plugin, hosts, error: setupError } = skills;
  const banner = updateBanner(hosts, plugin, projects);
  const setupEntry = (root: string) => plugin?.projects.find((item) => item.root === root);
  const memberOf = coordinatorOf(plugin?.projects ?? [], projects);
  const pathRoots = projects.filter((p) => !flavorOf(p)).map((p) => p.root);
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
          {shown.map((project) => {
            const entry = flavorOf(project) ? undefined : setupEntry(project.root);
            return { ...boardRow(project, now), setup: setupPill(entry, targetVersion(plugin)),
              coordinator: entry?.members ? { error: entry.members_error ?? null, members: memberRows(entry.members, pathRoots) } : null,
              memberOf: flavorOf(project) ? undefined : memberOf.get(project.root) };
          }).map((row) => (
            <Fragment key={row.id}>
            <div className="board-row" onClick={() => { location.hash = projectHash(row.id); }}>
              <div>
                <a className="pname" href={projectHash(row.id)}><i className={`dot small ${row.tone}`} />{row.name}{row.flavor && <span className="pill mute flavor">{row.flavor}</span>}</a>
                <div className="ppath">{row.path}</div>
                {row.coordinator && (
                  <div className="sk-pills board-rel">
                    {row.coordinator.error
                      ? <span className="pill bad" title={row.coordinator.error}>{t("board.membersInvalid")}</span>
                      : <span className="pill mute">{t("board.coordinator", { n: row.coordinator.members.length })}</span>}
                  </div>
                )}
                {row.memberOf && <div className="sk-pills board-rel"><span className="pill mute">{t("board.memberOf", { name: row.memberOf })}</span></div>}
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
            {row.coordinator?.members.map((member) => (
                <div key={member.checkout} className="board-member">
                  <span aria-hidden="true">↳</span>
                  <div className="grow">
                    {member.watched ? <a className="member-name" href={projectHash(member.checkout)}>{member.name}</a> : <b>{member.name}</b>}
                    <span className="ppath">{member.checkout}</span>
                    {member.reason && <div className="member-reason mono">{member.reason}</div>}
                  </div>
                  <span className="sk-pills">
                    <span className={`pill ${member.marker.tone}`}>{member.marker.label}</span>
                    <span className={`pill ${member.hooks.tone}`}>{member.hooks.label}</span>
                    {!member.watched && <span className="pill mute">{t("board.notWatched")}</span>}
                  </span>
                </div>
            ))}
            </Fragment>
          ))}
        </div></div>
      ) : <div className="empty">{empty}</div>}
      <div className="board-foot">
        <span>{t("board.count", { shown: shown.length, total: projects.length })}</span><span>{t("board.usageNote")}</span>
      </div>
    </main>
  );
}
