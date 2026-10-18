// Skills in each agent: the installed version, the release to install, and the install actions.
import { useState } from "react";
import { api } from "../shell";
import { failure, notDetected, sharedRoots, skillRows, targetVersion } from "../skills";
import type { Failure, SkillRow, UninstallPlan } from "../skills";
import { applyUninstall, installSkills, message, planUninstall } from "../skillsApi";
import type { usePlugin } from "../skillsApi";
import { Frameworks } from "./Frameworks";
import { FailureCard, Output, PlanBox, ReleasePicker } from "./SkillsParts";
import "./skills.css";

// What the panel under the table shows. One at a time.
type Panel =
  | { kind: "preview"; row: SkillRow; text: string }
  | { kind: "done"; text: string; output: string }
  | { kind: "failed"; row: SkillRow; failure: Failure; output: string; retry: () => void }
  | { kind: "plan"; row: SkillRow; plan: UninstallPlan };

export function Skills({ skills }: { skills: ReturnType<typeof usePlugin> }) {
  const { plugin, hosts, error, reload } = skills;
  const [panel, setPanel] = useState<Panel | null>(null);
  const [busy, setBusy] = useState<string | null>(null); // what runs now, for the status line
  const [check, setCheck] = useState<{ text: string; bad: boolean } | null>(null);
  const rows = skillRows(hosts, plugin), target = targetVersion(plugin);
  const missing = notDetected(hosts, plugin);

  /** Run one call; a rejected call or an `ok: false` answer becomes the failure card. */
  const run = async (row: SkillRow, label: string, done: "installed" | "updated" | "removed", work: () => Promise<Panel>) => {
    setBusy(label);
    try {
      setPanel(await work());
    } catch (failed) {
      setPanel({ kind: "failed", row, failure: failure(done, [row.label], message(failed)), output: "", retry: () => run(row, label, done, work) });
    }
    setBusy(null);
    reload();
  };
  const verb = (row: SkillRow) => (row.status === "Update available" || row.status === "No version stamp" ? "updated" : "installed");

  const preview = (row: SkillRow) => run(row, `Reading the plan for ${row.label}…`, verb(row), async () => {
    const result = await installSkills(row.ids, true);
    if (!result.ok) throw new Error(result.error || "The dry run failed.");
    return { kind: "preview", row, text: result.stdout_tail ?? "" };
  });
  const install = (row: SkillRow) => run(row, `Installing ${target} in ${row.label}…`, verb(row), async () => {
    const result = await installSkills(row.ids, false);
    if (!result.ok) {
      return { kind: "failed", row, failure: failure(verb(row), [row.label], result.error || "The installer failed."),
        output: result.stdout_tail ?? "", retry: () => install(row) };
    }
    return { kind: "done", text: `Installed ${target} in ${row.label}.`, output: result.stdout_tail ?? "" };
  });
  const plan = (row: SkillRow) => run(row, `Reading the removal plan for ${row.label}…`, "removed", async () =>
    ({ kind: "plan", row, plan: (await planUninstall({ scope: "global", hosts: row.ids })).plan }));
  const remove = (row: SkillRow) => run(row, `Removing skills from ${row.label}…`, "removed", async () => {
    const result = await applyUninstall({ scope: "global", hosts: row.ids });
    if (!result.ok) throw new Error(result.errors.map((item) => `${item.path}: ${item.error}`).join("\n") || "The removal failed.");
    return { kind: "done", text: `Removed Path skills from ${row.label}.`, output: result.applied.join("\n") };
  });

  const checkNow = async () => {
    setBusy("Checking for updates…");
    setCheck(null);
    try {
      const result = await api<{ ok: boolean; error: string | null; latest: string | null }>("POST", "/api/plugin/check", {});
      setCheck(result.ok ? { text: result.latest ? `Checked. The latest release is ${result.latest}.` : "Checked. No release is published.", bad: false }
        : { text: result.error || "The check failed.", bad: true });
    } catch (failed) {
      setCheck({ text: message(failed), bad: true });
    }
    setBusy(null);
    reload();
  };

  return (
    <main className="page skills" aria-label="Skills">
      <div className="skills-head">
        <div><h1 className="title">Skills</h1><p>Path skills in each coding agent's global skills folder.</p></div>
        <span className="grow" />
        <ReleasePicker releases={plugin?.releases} disabled={!!busy} onChanged={() => { setPanel(null); reload(); }} />
        <button className="btn" disabled={!!busy} onClick={checkNow}>Check for updates</button>
      </div>
      {check && <p className={check.bad ? "error" : "note skills-check"} role={check.bad ? "alert" : "status"}>{check.text}</p>}
      {error && <p className="error" role="alert">{error} <button className="link" onClick={reload}>Try again</button></p>}

      {rows.length ? (
        <div className="card scroll-x">
          <div className="skills-table">
            <div className="skills-th"><span>Agent</span><span>Skills folder</span><span>Version</span><span>Status</span><span /></div>
            {rows.map((row) => (
              <div key={row.path} className="skills-row">
                <b>{row.label}</b>
                <span className="mono skills-path">{row.path}</span>
                <span className="sk-num-left">{row.version}</span>
                <span><span className={`pill ${row.tone}`}>{row.status}</span></span>
                <span className="skills-actions">
                  {row.primary && <button className="btn small primary" disabled={!!busy} onClick={() => preview(row)}>{row.primary}</button>}
                  {row.preview && <button className="btn small" disabled={!!busy} onClick={() => preview(row)}>Preview</button>}
                  {row.uninstall && <button className="btn small sk-danger-text" disabled={!!busy} onClick={() => plan(row)}>Uninstall</button>}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : !error && <div className="empty">{plugin ? "No coding agent was found on this computer." : "Loading skills…"}</div>}

      {busy && <div className="sk-progress" role="status"><div className="bar busy"><i /></div><div className="sub">{busy}</div></div>}
      {!busy && panel?.kind === "preview" && (
        <div className="sk-panel">
          <Output text={panel.text} />
          <div className="actions">
            <button className="btn small primary" onClick={() => install(panel.row)}>{panel.row.primary ?? "Install"} in {panel.row.label}</button>
            <button className="btn small" onClick={() => setPanel(null)}>Cancel</button>
          </div>
        </div>
      )}
      {!busy && panel?.kind === "done" && (
        <div className="sk-panel">
          <div className="sk-done-line" role="status"><i className="dot ok" />{panel.text}</div>
          {panel.output && <Output text={panel.output} />}
        </div>
      )}
      {!busy && panel?.kind === "failed" && (
        <FailureCard failure={panel.failure} output={panel.output} onRetry={panel.retry} onClose={() => setPanel(null)} />
      )}
      {!busy && panel?.kind === "plan" && (
        <div className="sk-panel">
          <PlanBox plan={panel.plan} confirm={`Uninstall from ${panel.row.label}`} busy={false}
            onConfirm={() => remove(panel.row)} onCancel={() => setPanel(null)} />
        </div>
      )}

      <Frameworks plugin={plugin} reload={reload} />

      {plugin && (
        <p className="note">
          {sharedRoots(hosts).map((shared) => (
            <span key={shared.path}>{shared.names} share <span className="mono">{shared.path}</span>, so installing for one covers both. </span>
          ))}
          {missing.length > 0 && `${missing.length} more ${missing.length === 1 ? "agent is" : "agents are"} not detected on this computer: ${missing.join(", ")}.`}
        </p>
      )}
    </main>
  );
}
