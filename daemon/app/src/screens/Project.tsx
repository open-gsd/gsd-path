// One project: the same sections as projectPage() and projectRecords() in the daemon dashboard.
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { facts, milestoneRows, nowBox, phaseTrack, usageTiles } from "../project";
import { filesHash, statsHash } from "../route";
import { api } from "../shell";
import { DASH, duration, flavorOf, healthTone, idOf, int, money, nameOf, shortDate, shortTime, tokens } from "../status";
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
  if (!rows?.length) return <p className="note">No records available from this source.</p>;
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
  const answers = p.answers ?? [], attention = p.attention ?? [];
  const events = activity.filter((event) => (event.id ?? event.root) === idOf(p)).slice(0, 30);
  const section = (title: string, count: string | number, rows: unknown[], table: ReactNode) =>
    rows.length > 0 && <Fold title={title} count={count}>{table}</Fold>;

  return (
    <main className="page project">
      <a className="crumb" href="#/projects">‹ Projects</a>
      <div className="phead">
        <h1 className="title"><i className={`dot ${healthTone(p)}`} />{nameOf(p)}{flavorOf(p) && <span className="pill mute flavor">{flavorOf(p)}</span>}</h1>
        <span className="mono">Project folder: {p.project_root || p.root}</span>
        {p.worktree_root && <span className="mono">Worktree: {p.worktree_root}</span>}
        <a className="right" href={filesHash(idOf(p))}>History &amp; files ↗</a>
      </div>
      <dl className="facts">{facts(p, now).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
      {p.handoff && <p className="handoff">{p.handoff.outcome} — {p.handoff.next}</p>}
      {p.vision && <p className="vision">{p.vision}</p>}

      <div className="cols">
        <section>
          <h2>Phase <span>{p.phase || "no phase"}</span></h2>
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
              {box.verify && <div className="dim">verify <Verdict value={box.verify.result} /> {box.verify.at}</div>}
              {box.reason && <div className="reason">{box.reason}</div>}
            </div>
          )}

          {attention.length > 0 && <>
            <h2>Needs attention <span>{attention.length}</span></h2>
            <div className="card">
              {attention.map((item, index) => (
                <div key={index} className="row line">
                  <span className={item.kind === "blocked" || item.kind === "failed" ? "pill bad" : "pill warn"}>{item.kind}</span>
                  <span className="grow">{item.label}</span>
                </div>
              ))}
            </div>
          </>}

          <h2>Milestones</h2>
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

          {section("Success criteria", `${criteria.filter((c) => c.verdict === "met").length} of ${criteria.length} met`, criteria,
            <Table head={["ID", "Criterion", "Verdict"]}
              rows={criteria.map((c) => [<span className="mono">{c.id || DASH}</span>, c.text, <Verdict value={c.verdict} />])} />)}
          {section("Tasks and files", `${p.tasks_done ?? 0} of ${p.tasks_total || tasks.length}`, tasks,
            <Table head={["ID", "Task", "Wave", "Status", "Files"]} rows={tasks.map((task) => [
              <span className="mono">{task.id}</span>, task.title,
              task.wave != null ? `${task.wave} ${p.waves?.[task.wave] ?? ""}` : DASH,
              `${task.status === "done" ? "✓" : task.status === "failed" ? "✗" : "○"} ${task.status || "pending"}`,
              task.files.length ? <span className="mono">{task.files.map((file) => <div key={file}>{file}</div>)}</span> : DASH,
            ])} />)}
          {section("Reviews", reviews.length, reviews,
            <Table head={["Review", "Cycle", "Depth", "Verdict", "Note"]} num={[1]} rows={reviews.map((review) => [
              <span title={review.file}>{review.kind}</span>, review.cycle ?? DASH, review.depth || DASH,
              <Verdict value={review.verdict} />, review.note,
            ])} />)}
          {section("Recent verification", `latest ${ledger.length}`, ledger,
            <Table head={["Recorded", "Command", "Commit", "Result"]} rows={ledger.map((entry) => [
              <span className="mono">{shortDate(entry.recorded_at)}</span>, <span className="mono">{entry.command}</span>,
              <span className="mono">{(entry.commit ?? "").slice(0, 7)}</span>, <Verdict value={entry.result} />,
            ])} />)}
          {section("Pending answers", answers.length, answers, <>
            <RecordTable rows={answers} columns={[["id", "Answer"], ["question", "Question"], ["status", "Status"], ["follow_up", "Follow-up"], ["owner", "Owner"]]} />
            {source(".project/discuss/ANSWERS.md", "Read complete discussion record")}
          </>)}
        </section>

        <section>
          <Setup project={p} skills={skills}>
          <h2>Usage</h2>
          {!tiles || !sp ? <p className="note">No host session logs matched this project yet. <a href={statsHash(idOf(p))}>See charts ›</a></p> : <>
            <dl className="tiles">{tiles.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
            <a className="see-charts" href={statsHash(idOf(p))}>See charts ›</a>
            <h2>Models</h2>
            <Table head={["Model", "Host", "Turns", "Tokens", "Cost"]} num={[2, 3, 4]} rows={(sp.models ?? []).map((m) => [
              <span className="mono">{m.model}</span>, m.host, int(m.turns), tokens(m.tokens), money(m.cost)])} />
            <h2>Agents</h2>
            <Table head={["Agent · models", "Turns", "Tokens", "Time", "Cost"]} num={[1, 2, 3, 4]} rows={(sp.agents ?? []).map((a) => [
              <>{a.agent}<div className="meta mono">{a.models.join(", ")}</div></>,
              int(a.turns), tokens(a.tokens), a.duration_s ? duration(a.duration_s) : DASH, money(a.cost)])} />
            <Fold title="Turn ledger" count={`latest ${(sp.recent ?? []).length} of ${int(sp.turns ?? 0)}`}>
              <Table head={["Time", "Agent", "Model", "In", "Cached", "Out", "Cost", "Dur"]} num={[3, 4, 5, 6, 7]} rows={(sp.recent ?? []).map((turn) => [
                <span className="mono">{shortTime(turn.at)}</span>, turn.agent, <span className="mono">{turn.model || "?"}</span>,
                tokens(turn.tokens_in), tokens(turn.tokens_cached), tokens(turn.tokens_out), money(turn.cost),
                turn.duration_s != null ? `${turn.duration_s}s` : DASH])} />
            </Fold>
            {(sp.unpriced ?? []).length > 0 && (
              <p className="note">No price configured for {sp.unpriced!.join(", ")}: tokens counted, cost excluded. Add prices per million tokens under "prices" in daemon.json.</p>
            )}
            <p className="note">From host session logs matched to this project by working directory.</p>
          </>}

          <h2>Activity <span>recorded changes</span></h2>
          {events.length ? (
            <Table head={["When", "Change", "Detail"]} rows={events.map((event) => [
              <span className="mono">{shortDate(event.at)}</span>, event.type, event.detail])} />
          ) : <p className="note">No recorded changes yet.</p>}
          {p.lesson && <><h2>Latest lesson</h2><p className="vision">{p.lesson}</p></>}
          </Setup>
        </section>
      </div>

      <section className="records">
        <h2>Records &amp; sources</h2>
        <div className="tools">
          <button className="link" onClick={loadRecords} disabled={records.busy}>{records.data ? "Refresh full records" : "Load full records"}</button>
          <span className="sub">{records.busy ? "Loading…" : records.data ? `Loaded ${records.at}` : "Full histories load on demand."}</span>
        </div>
        {records.error && <p className="error" role="alert">{records.error}</p>}
        <Fold title="Pipeline usage by phase and task">
          {p.usage ? <>
            <RecordTable rows={p.usage.by_phase} columns={[["phase", "Phase"], ["tokens", "Tokens"]]} />
            <RecordTable rows={p.usage.by_task} columns={[["task", "Task"], ["model", "Model"], ["tokens", "Tokens"]]} />
          </> : <p className="note">No parsed pipeline usage is available.</p>}
        </Fold>
        {records.data && <>
          <Fold title="Full verification ledger">
            <RecordTable rows={records.data.verify_records} columns={[["recorded_at", "Recorded"], ["task", "Task"], ["command", "Command"], ["commit", "Commit"], ["result", "Result"]]} />
            {source(".project/build/verify-ledger.jsonl", "Read original ledger")}
          </Fold>
          <Fold title="Full pipeline usage records">
            <RecordTable rows={records.data.usage_records} columns={[["task", "Task"], ["phase", "Phase"], ["model", "Model"], ["tokens_in", "Input"], ["tokens_out", "Output"], ["cost", "Cost"]]} />
            {source(".project/build/usage.jsonl", "Read original usage")}
          </Fold>
          <Fold title="Full host turn ledger">
            <RecordTable rows={records.data.turns} columns={[["at", "Time"], ["agent", "Agent"], ["host", "Host"], ["model", "Model"], ["tokens_in", "Input"], ["tokens_cached", "Cached"], ["tokens_out", "Output"], ["duration_s", "Seconds"], ["cost", "Cost"]]} />
          </Fold>
          <Fold title="Full recorded activity">
            <RecordTable rows={records.data.activity} columns={[["at", "Time"], ["type", "Change"], ["detail", "Detail"]]} />
          </Fold>
          <Fold title="Data coverage">
            <p className="note">Available means the file can be opened, not that every field was parsed. Loaded sources report their actual record count. Unsupported hosts are not counted as zero.</p>
            <RecordTable rows={records.data.sources} columns={[["path", "Source"], ["status", "Status"], ["records", "Records"], ["invalid_lines", "Invalid lines"], ["error", "Read error"], ["detail", "Detail"]]} />
          </Fold>
        </>}
        <div className="tools">
          {source(".project/ROADMAP.md", "Roadmap")}{source(".project/intent/INTENT.md", "Intent")}{source(".project/plan/PLAN.md", "Plan")}
          {source(".project/review/FINAL.md", "Final review")}{source(".project/LESSONS.md", "Lessons")}
        </div>
      </section>
    </main>
  );
}
