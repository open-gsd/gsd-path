// One project: the same sections as projectPage() and projectRecords() in the daemon dashboard.
import { Fragment, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { t } from "../i18n";
import { facts, milestoneRows, nowBox, phaseTrack, repoRows, usageTiles } from "../project";
import { filesHash, statsHash } from "../route";
import { api } from "../shell";
import { DASH, duration, flavorOf, healthTone, idOf, stateFileOf, int, money, nameOf, shortDate, shortTime, tokens } from "../status";
import type { Project } from "../status";
import { Fold, Table } from "../ui";
import type { usePlugin } from "../skillsApi";
import { SetupCard } from "./SetupCard";

type Row = Record<string, unknown>;
type Records = { verify_records: Row[]; usage_records: Row[]; turns: Row[]; activity: Row[]; sources: Row[] };
type Activity = { root?: string; id?: string; at?: string; type?: string; detail?: string };

const WAVE_MARK = { done: "✓", now: "●", blocked: "●", todo: "○" };
const GOOD = new Set(["pass", "met", "approve", "approved"]);
const POOR = new Set(["fail", "not-met", "unverifiable", "reject", "rejected"]);

function Verdict({ value }: { value: string | null | undefined }) {
  if (!value) return <>{DASH}</>;
  const key = value.toLowerCase();
  return <span className={GOOD.has(key) ? "good" : POOR.has(key) ? "poor" : undefined}>{value}</span>;
}

/** Rows the daemon sends as plain records: one column per key. */
function RecordTable({ rows, columns }: { rows: Row[] | undefined; columns: [string, string][] }) {
  if (!rows?.length) return <p className="note">{t("projectPage.noRecords")}</p>;
  const cell = (value: unknown) => (value == null ? DASH : typeof value === "object" ? JSON.stringify(value) : String(value));
  return <Table head={columns.map(([, label]) => label)} rows={rows.map((row) => columns.map(([key]) => cell(row[key])))} />;
}

// gsd-pi and gsd-core projects have no GSD Path install to set up.
const NoSetup = ({ children }: { children: ReactNode }) => <>{children}</>;

export function ProjectPage({ project: p, now, stamp, skills }: { project: Project; now: number; stamp: string | null; skills: ReturnType<typeof usePlugin> }) {
  const [activity, setActivity] = useState<Activity[]>([]);
  const [records, setRecords] = useState<{ data?: Records; error?: string; busy?: boolean; at?: string }>({});

  useEffect(() => {
    // Keep the last list when a read fails.
    api<{ events?: Activity[] }>("GET", "/activity").then((result) => setActivity(result.events ?? []), () => {});
  }, [p.root, stamp]);
  useEffect(() => setRecords({}), [idOf(p)]);

  const loadRecords = async () => {
    setRecords((old) => ({ ...old, busy: true, error: undefined }));
    try {
      const data = await api<Records>("GET", "/api/project-data?" + new URLSearchParams({ root: idOf(p) }));
      setRecords({ data, at: new Date().toLocaleTimeString() });
    } catch (error) {
      setRecords({ error: String(error) });
    }
  };

  const source = (path: string, label: string) => <a className="link" href={filesHash(idOf(p), path)}>{label} ↗</a>;
  const Setup = flavorOf(p) ? NoSetup : SetupCard;
  const box = nowBox(p), tiles = usageTiles(p), sp = p.spend;
  const tasks = p.tasks ?? [], criteria = p.criteria ?? [], reviews = p.reviews ?? [], ledger = p.ledger ?? [];
  const repos = repoRows(p);
  const answers = p.answers ?? [], attention = p.attention ?? [];
  const events = activity.filter((event) => (event.id ?? event.root) === idOf(p)).slice(0, 30);
  const section = (title: string, count: string | number, rows: unknown[], table: ReactNode) =>
    rows.length > 0 && <Fold title={title} count={count}>{table}</Fold>;

  return (
    <main className="page project">
      <a className="crumb" href="#/projects">‹ {t("nav.projects")}</a>
      <div className="phead">
        <h1 className="title"><i className={`dot ${healthTone(p)}`} />{nameOf(p)}{flavorOf(p) && <span className="pill mute flavor">{flavorOf(p)}</span>}</h1>
        <span className="mono">{t("projectPage.folder")}: {p.project_root || p.root}</span>
        {p.worktree_root && <span className="mono">{t("board.worktree")}: {p.worktree_root}</span>}
        <a className="right" href={filesHash(idOf(p), stateFileOf(p))}>{t("projectPage.historyFiles")} ↗</a>
      </div>
      <dl className="facts">{facts(p, now).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
      {p.handoff && <p className="handoff">{p.handoff.outcome} — {p.handoff.next}</p>}
      {p.vision && <p className="vision">{p.vision}</p>}

      <div className="cols">
        <section>
          <h2>{t("projectPage.phase")} <span>{p.phase || t("tray.noPhase")}</span></h2>
          <div className="phases">
            {phaseTrack(p).map((step) => <div key={step.label} className={step.state}><i />{step.label}<small>{step.date}</small></div>)}
          </div>
          {box && (
            <div className={box.blocked ? "now-box blocked" : "now-box"}>
              <div><b>{box.title}</b> · {box.line}</div>
              {box.goal && <div className="dim">{box.goal}</div>}
              {box.intent && <div className="dim intent">{box.intent}</div>}
              {box.percent != null && <div className="bar"><i style={{ width: `${box.percent}%` }} /></div>}
              <div className="dim">{box.count}</div>
              {box.waves.length > 0 && (
                <div className="waves">{box.waves.map((wave) => <span key={wave.text} className={wave.state}>{WAVE_MARK[wave.state]} {wave.text}</span>)}</div>
              )}
              {box.criteria && <div className="dim">{box.criteria}</div>}
              {box.verify && <div className="dim">{t("projectPage.verify")} <Verdict value={box.verify.result} /> {box.verify.at}</div>}
              {box.reason && <div className="reason">{box.reason}</div>}
            </div>
          )}

          {attention.length > 0 && <>
            <h2>{t("projectPage.needsAttention")} <span>{attention.length}</span></h2>
            <div className="card">
              {attention.map((item, index) => (
                <div key={index} className="row line">
                  <span className={item.kind === "blocked" || item.kind === "failed" ? "pill bad" : "pill warn"}>{item.kind}</span>
                  <span className="grow">{item.label}</span>
                </div>
              ))}
            </div>
          </>}

          <h2>{t("projectPage.milestones")}</h2>
          <div className="ms-list">
            {milestoneRows(p).map((m) => (
              <div key={m.number + m.slug} className={`ms-row ${m.kind}${m.blocked ? " blocked" : ""}`}>
                <span className="mono">{m.number}</span>
                <div>
                  <div>{m.slug}</div>
                  {m.goal && <div className="sub">{m.goal}</div>}
                  {m.meta && <div className="sub">{m.meta}</div>}
                </div>
                <span>{m.status}</span>
                <span className="num">{m.tasks}</span>
                <span className="num">{m.usage}{m.tokens && <div className="meta">{m.tokens}</div>}</span>
              </div>
            ))}
          </div>

          {section(t("projectPage.successCriteria"), t("projectPage.criteriaMetCount", { met: criteria.filter((c) => c.verdict === "met").length, total: criteria.length }), criteria,
            <Table head={[t("projectPage.id"), t("projectPage.criterion"), t("projectPage.verdict")]}
              rows={criteria.map((c) => [<span className="mono id">{c.id || DASH}</span>, c.text, <Verdict value={c.verdict} />])} />)}
          {section(t("repos.title"), repos.length, repos,
            <Table head={[t("repos.repository"), t("board.col.tasks"), t("repos.branch"), t("repos.base"), t("repos.close")]} rows={repos.map((repo) => [
              repo.name, <span className="whole">{repo.tasks}</span>, <span className="mono">{repo.branch}</span>, <span className="mono whole">{repo.base}</span>,
              repo.close ? <span className="whole"><span className={`pill ${repo.close.tone}`}>{repo.close.label}</span>{repo.close.detail && <div className="meta mono">{repo.close.detail}</div>}</span> : DASH,
            ])} />)}
          {section(t("projectPage.tasksAndFiles"), t("projectPage.tasksCount", { done: p.tasks_done ?? 0, total: p.tasks_total || tasks.length }), tasks,
            <Table head={[t("projectPage.id"), t("projectPage.task"), t("projectPage.waveCol"), t("board.col.status"), t("projectPage.files")]} rows={tasks.map((task) => [
              <span className="mono id">{task.id}</span>, task.title,
              <span className="whole">{task.wave != null ? `${task.wave} ${p.waves?.[task.wave] ?? ""}` : DASH}</span>,
              <span className="whole">{`${task.status === "done" ? "✓" : task.status === "failed" ? "✗" : "○"} ${task.status || t("projectPage.pending")}`}</span>,
              task.files.length ? <span className="mono">{task.files.map((file) => <div key={file}>{file.split("/").map((part, at, all) => <Fragment key={at}>{part}{at < all.length - 1 && <>/<wbr /></>}</Fragment>)}</div>)}</span> : DASH,
            ])} />)}
          {section(t("projectPage.reviews"), reviews.length, reviews,
            <Table head={[t("projectPage.review"), t("projectPage.cycle"), t("projectPage.depth"), t("projectPage.verdict"), t("projectPage.note")]} num={[1]} rows={reviews.map((review) => [
              <span title={review.file}>{review.kind}</span>, review.cycle ?? DASH, review.depth || DASH,
              <Verdict value={review.verdict} />, review.note,
            ])} />)}
          {section(t("projectPage.recentVerification"), t("projectPage.latest", { n: ledger.length }), ledger,
            <Table head={[t("projectPage.recorded"), t("projectPage.command"), t("projectPage.commit"), t("projectPage.result")]} rows={ledger.map((entry) => [
              <span className="mono">{shortDate(entry.recorded_at)}</span>, <span className="mono">{entry.command}</span>,
              <span className="mono">{(entry.commit ?? "").slice(0, 7)}</span>, <Verdict value={entry.result} />,
            ])} />)}
          {section(t("projectPage.pendingAnswers"), answers.length, answers, <>
            <RecordTable rows={answers} columns={[["id", t("projectPage.answer")], ["question", t("projectPage.question")], ["status", t("board.col.status")], ["follow_up", t("projectPage.followUp")], ["owner", t("projectPage.owner")]]} />
            {!p.record_files && source(".project/discuss/ANSWERS.md", t("projectPage.readDiscussion"))}
          </>)}
        </section>

        <section>
          <Setup project={p} skills={skills}>
          <h2>{t("projectPage.usage")}</h2>
          {!tiles || !sp ? <p className="note">{t("projectPage.noSessions")} <a href={statsHash(idOf(p))}>{t("projectPage.seeCharts")} ›</a></p> : <>
            <dl className="tiles">{tiles.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
            <a className="see-charts" href={statsHash(idOf(p))}>{t("projectPage.seeCharts")} ›</a>
            <h2>{t("projectPage.models")}</h2>
            <Table head={[t("settings.model"), t("projectPage.host"), t("usage.turns"), t("projectPage.tokens"), t("usage.cost")]} num={[2, 3, 4]} rows={(sp.models ?? []).map((m) => [
              <span className="mono">{m.model}</span>, m.host, int(m.turns), tokens(m.tokens), money(m.cost)])} />
            <h2>{t("setupWizard.agents")}</h2>
            <Table head={[t("projectPage.agentModels"), t("usage.turns"), t("projectPage.tokens"), t("projectPage.time"), t("usage.cost")]} num={[1, 2, 3, 4]} rows={(sp.agents ?? []).map((a) => [
              <>{a.agent}<div className="meta mono">{a.models.join(", ")}</div></>,
              int(a.turns), tokens(a.tokens), a.duration_s ? duration(a.duration_s) : DASH, money(a.cost)])} />
            <Fold title={t("projectPage.turnLedger")} count={t("projectPage.latestOf", { shown: (sp.recent ?? []).length, total: int(sp.turns ?? 0) })}>
              <Table head={[t("projectPage.time"), t("path.agent"), t("settings.model"), t("projectPage.in"), t("usage.cached"), t("projectPage.out"), t("usage.cost"), t("projectPage.dur")]} num={[3, 4, 5, 6, 7]} rows={(sp.recent ?? []).map((turn) => [
                <span className="mono">{shortTime(turn.at)}</span>, turn.agent, <span className="mono">{turn.model || "?"}</span>,
                tokens(turn.tokens_in), tokens(turn.tokens_cached), tokens(turn.tokens_out), money(turn.cost),
                turn.duration_s != null ? `${turn.duration_s}s` : DASH])} />
            </Fold>
            {(sp.unpriced ?? []).length > 0 && (
              <p className="note">{t("projectPage.noPrice", { models: sp.unpriced!.join(t("list.separator")) })}</p>
            )}
            <p className="note">{t("projectPage.fromSessionLogs")}</p>
          </>}

          <h2>{t("projectPage.activity")} <span>{t("projectPage.recordedChanges")}</span></h2>
          {events.length ? (
            <Table head={[t("projectPage.when"), t("projectPage.change"), t("projectPage.detail")]} rows={events.map((event) => [
              <span className="mono">{shortDate(event.at)}</span>, event.type, event.detail])} />
          ) : <p className="note">{t("projectPage.noChanges")}</p>}
          {p.lesson && <><h2>{t("projectPage.latestLesson")}</h2><p className="vision">{p.lesson}</p></>}
          </Setup>
        </section>
      </div>

      <section className="records">
        <h2>{t("projectPage.recordsSources")}</h2>
        <div className="tools">
          <button className="link" onClick={loadRecords} disabled={records.busy}>{records.data ? t("projectPage.refreshRecords") : t("projectPage.loadRecords")}</button>
          <span className="sub">{records.busy ? t("settings.loading") : records.data ? t("projectPage.loaded", { at: records.at }) : t("projectPage.loadOnDemand")}</span>
        </div>
        {records.error && <p className="error" role="alert">{records.error}</p>}
        <Fold title={t("projectPage.pipelineUsage")}>
          {p.usage ? <>
            <RecordTable rows={p.usage.by_phase} columns={[["phase", t("projectPage.phaseCol")], ["tokens", t("projectPage.tokens")]]} />
            <RecordTable rows={p.usage.by_task} columns={[["task", t("projectPage.task")], ["model", t("settings.model")], ["tokens", t("projectPage.tokens")]]} />
          </> : <p className="note">{t("projectPage.noParsedUsage")}</p>}
        </Fold>
        {records.data && <>
          <Fold title={t("projectPage.fullLedger")}>
            <RecordTable rows={records.data.verify_records} columns={[["recorded_at", t("projectPage.recorded")], ["task", t("projectPage.task")], ["command", t("projectPage.command")], ["commit", t("projectPage.commit")], ["result", t("projectPage.result")]]} />
            {!p.record_files && source(".project/build/verify-ledger.jsonl", t("projectPage.readLedger"))}
          </Fold>
          <Fold title={t("projectPage.fullUsageRecords")}>
            <RecordTable rows={records.data.usage_records} columns={[["task", t("projectPage.task")], ["phase", t("projectPage.phaseCol")], ["model", t("settings.model")], ["tokens_in", t("settings.input")], ["tokens_out", t("settings.output")], ["cost", t("usage.cost")]]} />
            {!p.record_files && source(".project/build/usage.jsonl", t("projectPage.readUsage"))}
          </Fold>
          <Fold title={t("projectPage.fullTurnLedger")}>
            <RecordTable rows={records.data.turns} columns={[["at", t("projectPage.time")], ["agent", t("path.agent")], ["host", t("projectPage.host")], ["model", t("settings.model")], ["tokens_in", t("settings.input")], ["tokens_cached", t("usage.cached")], ["tokens_out", t("settings.output")], ["duration_s", t("projectPage.seconds")], ["cost", t("usage.cost")]]} />
          </Fold>
          <Fold title={t("projectPage.fullActivity")}>
            <RecordTable rows={records.data.activity} columns={[["at", t("projectPage.time")], ["type", t("projectPage.change")], ["detail", t("projectPage.detail")]]} />
          </Fold>
          <Fold title={t("projectPage.dataCoverage")}>
            <p className="note">{t("projectPage.coverageNote")}</p>
            <RecordTable rows={records.data.sources} columns={[["path", t("path.source")], ["status", t("board.col.status")], ["records", t("projectPage.recordsCol")], ["invalid_lines", t("projectPage.invalidLines")], ["error", t("projectPage.readError")], ["detail", t("projectPage.detail")]]} />
          </Fold>
        </>}
        <div className="tools">
          {p.record_files ? p.record_files.slice(1).map((file) => <span key={file.path}>{source(file.path, file.label)}</span>) : <>
            {source(".project/ROADMAP.md", t("projectPage.roadmap"))}{source(".project/intent/INTENT.md", t("projectPage.intent"))}{source(".project/plan/PLAN.md", t("projectPage.plan"))}
            {source(".project/review/FINAL.md", t("projectPage.finalReview"))}{source(".project/LESSONS.md", t("projectPage.lessons"))}
          </>}
        </div>
      </section>
    </main>
  );
}
