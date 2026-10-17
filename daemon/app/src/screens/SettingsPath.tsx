// Settings → Path settings: user defaults or one project. The same fields and rules as the daemon dashboard.
import { useEffect, useState } from "react";
import { canReset, fieldValue, integrationOptions, lockOf, modelKey, pathChanges, pathProjects, savedNote, scopeQuery } from "../settingsPath";
import type { PathData, PathDrafts } from "../settingsPath";
import { api } from "../shell";
import { nameOf } from "../status";
import type { Status } from "../status";
import { FixText } from "../ui";
import { SaveBar } from "./SettingsParts";

export function PathTab({ status }: { status: Status | null }) {
  const projects = pathProjects(status?.projects ?? []);
  /** The project root; empty for the user defaults. */
  const [root, setRoot] = useState("");
  const [host, setHost] = useState("");
  const [data, setData] = useState<PathData | null>(null);
  const [drafts, setDrafts] = useState<PathDrafts>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    let live = true;
    setData(null); setDrafts({}); setError(""); setNote("");
    api<PathData>("GET", "/api/path-config?" + new URLSearchParams(scopeQuery(root))).then(
      (next) => { if (live) setData(next); }, (reason) => { if (live) setError(String(reason)); });
    return () => { live = false; };
  }, [root]);

  const changes = data ? pathChanges(data, drafts) : { requests: [], errors: [], summary: [] };
  const edit = (key: string, value: string | null) => { setNote(""); setDrafts((old) => ({ ...old, [key]: value })); };
  const undo = (keys: string[]) => setDrafts((old) => Object.fromEntries(Object.entries(old).filter(([key]) => !keys.includes(key))));

  // One request per key. A refused key stops the save; the keys after it stay as drafts.
  const save = async () => {
    setBusy(true); setError(""); setNote("");
    const done: string[] = [];
    try {
      for (const request of changes.requests) {
        setData(await api<PathData>("POST", "/api/path-config", { ...scopeQuery(root), ...request }));
        done.push(request.key);
      }
      setDrafts({});
    } catch (reason) {
      undo(done);
      setError(String(reason));
    }
    if (done.length) setNote(savedNote(done, root));
    setBusy(false);
  };

  const scope = (
    <div className="set-scope">
      <div className="seg" role="group" aria-label="Settings for">
        <button aria-pressed={!root} disabled={busy} onClick={() => setRoot("")}>User defaults</button>
        <button aria-pressed={!!root} disabled={busy || !projects.length} onClick={() => root || setRoot(projects[0].root)}>Project</button>
      </div>
      {root && (
        <select className="set-input" aria-label="Project" value={root} disabled={busy} onChange={(event) => setRoot(event.target.value)}>
          {projects.map((project) => <option key={project.root} value={project.root}>{nameOf(project)}</option>)}
        </select>
      )}
      {!projects.length && <span className="sub">No watched project to choose.</span>}
    </div>
  );
  if (!data) {
    return (
      <>
        <h2 className="set-h2">Path settings</h2>
        {scope}
        {error ? <div className="error" role="alert"><FixText text={error} /></div> : <p className="note">Loading settings…</p>}
      </>
    );
  }

  const off = (key: string) => busy || !!lockOf(data, key);
  const reset = (keys: string[]) => {
    const able = keys.filter((key) => canReset(data, key, root));
    if (!able.length) return null;
    const marked = able.some((key) => drafts[key] === null);
    return (
      <button className="link" disabled={busy} onClick={() => (marked ? undo(able) : able.forEach((key) => edit(key, null)))}>
        {marked ? "Undo reset" : "Reset"}
      </button>
    );
  };
  const source = (key: "integration" | "review_panel") => <div className="set-source">Source: {data.settings[key].source}</div>;
  const mode = data.settings.integration;
  const input = (key: string, label: string) => (
    <input className={drafts[key] === null ? "set-input struck" : "set-input"} aria-label={label} value={fieldValue(data, drafts, key)}
      disabled={off(key) || drafts[key] === null} onChange={(event) => edit(key, event.target.value)} />
  );

  return (
    <>
      <h2 className="set-h2">Path settings</h2>
      {scope}
      {data.locked && <div className="set-locked" role="status">{data.locked}</div>}
      <div className="set-rows">
        <div className="set-setting">
          <div>
            <b>Shipping mode</b>
            <div className="sub">How finished milestones reach main. {mode.locked
              || (root ? "Changes the project default; explicit milestone overrides are retained." : "Used when a new project is initialized.")}</div>
            {root && mode.current && <div className="sub">Current milestone: {mode.current} ({mode.current_source})</div>}
            {source("integration")}
          </div>
          <select className={drafts.integration === null ? "set-input struck" : "set-input"} aria-label="Shipping mode"
            value={fieldValue(data, drafts, "integration")} disabled={off("integration") || drafts.integration === null}
            onChange={(event) => edit("integration", event.target.value)}>
            {integrationOptions(mode.value).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          {reset(["integration"])}
        </div>
        <div className="set-setting">
          <div>
            <b>Review panel</b>
            <div className="sub">Extra reviewers from other model families: <span className="mono">off</span>, <span className="mono">detected</span>,
              or comma-separated model families. Quick lane keeps panels off.</div>
            {data.approved_review_panel && (
              <div className="sub">Recorded review panel: {data.approved_review_panel.value} ({data.approved_review_panel.source}).
                Approved review contracts keep their values.</div>
            )}
            {source("review_panel")}
          </div>
          <input className={drafts.review_panel === null ? "set-input struck" : "set-input"} aria-label="Review panel" list="set-panel-options"
            value={fieldValue(data, drafts, "review_panel")} disabled={off("review_panel") || drafts.review_panel === null}
            onChange={(event) => edit("review_panel", event.target.value)} />
          <datalist id="set-panel-options"><option value="off" /><option value="detected" /></datalist>
          {reset(["review_panel"])}
        </div>
        <div className="set-models">
          <div className="line">
            <div className="grow">
              <b>Models and effort</b>
              <div className="sub">Per role. Use an exact value your agent offers, or <span className="mono">inherit</span>.
                Unsupported values stop dispatch. Recorded assignments stay pinned.</div>
            </div>
            <select className="set-input" aria-label="Agent" value={host} disabled={busy} onChange={(event) => setHost(event.target.value)}>
              <option value="">All agents</option>
              {data.hosts.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </div>
          <div className="set-roles">
            <span className="set-th">Role</span><span className="set-th">Model</span><span className="set-th">Effort</span><span />
            {data.roles.map((role) => {
              const model = modelKey(host, role, "model"), effort = modelKey(host, role, "effort");
              return (
                <div key={role} className="set-role">
                  <span className="mono">{role}</span>
                  {input(model, `${role} model`)}
                  {input(effort, `${role} effort`)}
                  <span>{reset([model, effort])}</span>
                </div>
              );
            })}
          </div>
          <details className="set-sources">
            <summary>Configured values and sources</summary>
            {Object.entries(data.models).map(([key, entry]) => (
              <p key={key} className="set-source"><b>{key}</b>: {entry.value} · {entry.source}</p>
            ))}
            {!Object.keys(data.models).length && <p className="sub">No model overrides.</p>}
          </details>
        </div>
      </div>
      <SaveBar summary={changes.summary} errors={changes.errors} error={error} note={note} busy={busy} onSave={save}
        onDiscard={() => { setDrafts({}); setError(""); }} />
    </>
  );
}
