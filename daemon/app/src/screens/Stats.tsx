// Charts from GET /api/stats. Missing data shows a hatched blank with the reason, never zero.
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { t } from "../i18n";
import { settingsHash } from "../route";
import { api } from "../shell";
import { costChart, phaseRows, reloadDue, scopes, tokenChart, unpricedNote, verifyChart, waveRows } from "../stats";
import type { Chart, StatsPayload } from "../stats";
import { idOf, phasesOf } from "../status";
import type { Status } from "../status";
import "./stats.css";

function Card({ title, total, wide, children }: { title: string; total?: string; wide?: boolean; children: ReactNode }) {
  return (
    <section className={wide ? "stats-card wide" : "stats-card"} aria-label={title}>
      <div className="stats-card-head"><b>{title}</b>{total && <span>{total}</span>}</div>
      {children}
    </section>
  );
}

const Blank = ({ reason, short }: { reason: string; short?: boolean }) =>
  <div className={short ? "stats-blank short" : "stats-blank"}>{reason}</div>;

function Bars({ chart, tone }: { chart: Chart; tone: "tokens" | "cost" }) {
  return (
    <>
      <div className="stats-peak">{chart.peak}</div>
      <div className={`stats-bars ${tone}`}>
        {chart.bars.map((bar) => (
          // A blank slot keeps the day's place; it has no bar.
          <span key={bar.date} title={bar.title}>{bar.percent != null && <i style={{ height: `${bar.percent}%` }} />}</span>
        ))}
      </div>
      <div className="stats-axis"><span>{chart.first}</span><span>{chart.last}</span></div>
    </>
  );
}

export function Stats({ status, root }: { status: Status | null; root: string | null }) {
  const [loaded, setLoaded] = useState<{ root: string | null; data?: StatsPayload; error?: string } | null>(null);
  const last = useRef<{ root: string | null; at: number } | null>(null);
  const wanted = useRef(root);
  wanted.current = root;
  const stamp = status?.generated_at ?? null;

  useEffect(() => {
    // /status arrives every few seconds; the charts load on a scope change and at most once per minute.
    if (!reloadDue(last.current, root, Date.now())) return;
    last.current = { root, at: Date.now() };
    api<StatsPayload>("GET", "/api/stats" + (root ? "?root=" + encodeURIComponent(root) : "")).then(
      (data) => { if (wanted.current === root) setLoaded({ root, data }); },
      // Keep the last charts of this scope when a reload fails.
      (error) => { if (wanted.current === root) setLoaded((old) => ({ root, data: old?.root === root ? old.data : undefined, error: error instanceof Error ? error.message : String(error) })); },
    );
  }, [root, stamp]);

  const projects = status?.projects ?? [];
  const now = loaded?.root === root ? loaded : null;
  const data = now?.data;
  const end = stamp ? stamp.slice(0, 10) : null;
  const tokens = data && tokenChart(data, end), cost = data && costChart(data, end);
  const scoped = projects.find((p) => idOf(p) === root);
  const phases = data && phaseRows(data, scoped ? phasesOf(scoped) : undefined), verify = data && verifyChart(data);
  const waves = data && waveRows(data, projects.find((p) => idOf(p) === root)?.waves);
  const unpriced = data ? unpricedNote(data.unpriced) : null;

  return (
    <main className="page stats" aria-label={t("nav.stats")}>
      <div className="stats-head">
        <div>
          <h1 className="title">{t("nav.stats")}</h1>
          <p>{t("stats.lead")}</p>
        </div>
        <nav className="stats-scope" aria-label={t("stats.scope")}>
          {scopes(projects, root).map((scope) => (
            <a key={scope.href} href={scope.href} aria-current={scope.current ? "page" : undefined}>{scope.label}</a>
          ))}
        </nav>
      </div>
      {now?.error && <p className="error" role="alert">{t("stats.cannotLoad", { error: now.error })}</p>}
      {!now && <div className="empty" role="status">{t("stats.loading")}</div>}
      {data && (
        <div className="stats-grid">
          <Card title={t("stats.tokensPerDay")} total={typeof tokens === "object" ? tokens.total : undefined}>
            {typeof tokens === "string" ? <Blank reason={tokens} /> : <Bars chart={tokens!} tone="tokens" />}
          </Card>
          <Card title={t("stats.costPerDay")} total={typeof cost === "object" ? cost.total : undefined}>
            {typeof cost === "string" ? <Blank reason={cost} /> : <Bars chart={cost!} tone="cost" />}
            {unpriced && <p className="stats-note">{unpriced} <a href={settingsHash("usage")}>{t("stats.addAPrice")}</a></p>}
          </Card>
          <Card title={t("stats.timePerPhase")}>
            {typeof phases === "string" ? <Blank reason={phases} /> : (
              <div className="stats-rows">
                {phases!.map((row) => (
                  <div key={row.label}>
                    <span>{row.label}</span>
                    <span className="stats-track">{row.percent != null && <i style={{ width: `${row.percent}%` }} />}</span>
                    <span className="num">{row.value}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
          <Card title={t("stats.tasksPerWave")}>
            {typeof waves === "string" ? <Blank reason={waves} short /> : (
              <div className="stats-rows by-wave">
                {waves!.map((row) => (
                  <div key={row.label}>
                    <span>{row.label}</span>
                    <span className="stats-cells" aria-hidden="true">{row.cells.map((done, index) => <i key={index} className={done ? "done" : undefined} />)}</span>
                    <span className="num">{row.value}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
          <Card title={t("stats.verifyHistory")} total={typeof verify === "object" ? verify.total : undefined} wide>
            {typeof verify === "string" ? <Blank reason={verify} short /> : <>
              <div className="stats-squares">
                {verify!.squares.map((square, index) => (
                  <i key={index} className={square.pass ? "pass" : "fail"} title={square.title} role="img" aria-label={square.title} />
                ))}
              </div>
              <div className="stats-legend"><span>{t("stats.oldestFirst")}</span><span><i className="pass" />{t("stats.pass")}</span><span><i className="fail" />{t("stats.fail")}</span></div>
            </>}
          </Card>
        </div>
      )}
    </main>
  );
}
