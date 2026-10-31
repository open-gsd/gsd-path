import { describe, expect, it } from "vitest";
import { asking, blocked, building, shipped, status } from "./fixtures";
import { doctorReport, facts, memberRows, milestoneRows, nowBox, phaseTrack, repoRows, setupRows, usageTiles } from "./project";
import { DASH } from "./status";
import type { ProjectSetup } from "./skills";

const NOW = Date.parse(status.generated_at!);

describe("facts", () => {
  it("lists state, health, git and usage", () => {
    expect(facts(building, NOW)).toEqual([
      ["State", "In build"], ["Health", "amber · no activity for 2d"], ["Milestone", "M004"],
      ["Branch", "gsd-path/M004"], ["Head", "0e9a3b1 · dirty"], ["Integration", "direct"],
      ["Updated", "2d ago"], ["Cost", "$26.10"], ["Turns", "90"],
    ]);
  });
  it("leaves out an unknown integration and shows dashes for missing git and usage", () => {
    expect(facts({ ...asking, git: null, branch: null }, NOW)).toEqual([
      ["State", "In research"], ["Health", "amber · Which search index do we ship?"], ["Milestone", "now"],
      ["Branch", "—"], ["Head", "—"], ["Updated", "1h ago"], ["Cost", "—"], ["Turns", "—"],
    ]);
  });
});

describe("phaseTrack", () => {
  it("dates each phase from the log", () => {
    expect(phaseTrack(building)).toEqual([
      { label: "inspect", date: "", state: "done" }, { label: "define", date: "09-09", state: "done" },
      { label: "research", date: "09-09", state: "done" }, { label: "decide", date: "", state: "done" },
      { label: "roadmap", date: "09-09", state: "done" }, { label: "plan", date: "09-09", state: "done" },
      { label: "build", date: "09-10", state: "now" }, { label: "ship", date: "", state: "todo" },
    ]);
  });
  it("uses the last entry of the current phase and the first entry of an earlier one", () => {
    const again = { ...building, phase_log: [
      { phase: "plan", date: "2026-09-01" }, { phase: "build", date: "2026-09-02" },
      { phase: "plan", date: "2026-09-03" }, { phase: "build", date: "2026-09-04" }] };
    const dates = Object.fromEntries(phaseTrack(again).map((step) => [step.label, step.date]));
    expect([dates.plan, dates.build]).toEqual(["09-01", "09-04"]);
  });
});

describe("nowBox", () => {
  it("shows progress, waves, criteria and the last verify of the current milestone", () => {
    expect(nowBox(building)).toEqual({
      blocked: false, title: "M004 daemon", line: "build · wave 2",
      goal: "Native tray and dashboard for the daemon.", intent: "One window for every project.",
      percent: 67, count: "2 of 3 tasks · entered build 2026-09-10 · 2d 3h",
      waves: [{ state: "done", text: "wave 1 parsers" }, { state: "now", text: "wave 2 watcher" }, { state: "todo", text: "wave 3 tray" }],
      criteria: "1 of 2 criteria met", verify: { result: "pass", at: "03:58:11" }, reason: null,
    });
  });
  it("shows the blocked reason and no progress bar without tasks", () => {
    expect(nowBox(blocked)).toMatchObject({
      blocked: true, title: "M002 api-v2", line: "ship", percent: null, count: "no tasks yet", waves: [],
      criteria: null, verify: null, reason: "The final review has not passed.",
    });
  });
  it("is hidden for a shipped project", () => {
    expect(nowBox(shipped)).toBeNull();
  });
  it("marks every wave done when all tasks are done and no wave is current", () => {
    const finished = { ...building, current_wave: null, tasks_done: 3 };
    expect(nowBox(finished)!.waves.map((wave) => wave.state)).toEqual(["done", "done", "done"]);
    expect(nowBox({ ...building, current_wave: null })!.waves.map((wave) => wave.state)).toEqual(["todo", "todo", "todo"]);
  });
});

describe("milestoneRows", () => {
  it("lists done, current and planned milestones with their usage", () => {
    expect(milestoneRows(building)).toEqual([
      { kind: "done", blocked: false, number: "M003", slug: "core", goal: "Parsers and the status endpoint.",
        meta: "5 of 5 tasks · 2 waves · integrated 91be44a", status: "shipped 2026-09-06", tasks: "5", usage: "$1.50 · 6 turns", tokens: "500k tokens" },
      { kind: "now", blocked: false, number: "M004", slug: "daemon", goal: "Native tray and dashboard for the daemon.",
        meta: "", status: "In build", tasks: "3", usage: "$24.60 · 84 turns", tokens: "8.9M tokens" },
      { kind: "todo", blocked: false, number: "M005", slug: "notify", goal: "Desktop notifications.",
        meta: "after M004", status: "pending", tasks: "—", usage: "—", tokens: null },
    ]);
  });
  it("marks the current milestone of a blocked project and never shows zero usage", () => {
    expect(milestoneRows(blocked)).toMatchObject([{ kind: "now", blocked: true, status: "Blocked", tasks: "—", usage: "—", tokens: null }]);
  });
  it("shows a shipped current milestone as done", () => {
    expect(milestoneRows(shipped)).toMatchObject([{ kind: "done", status: "shipped 2026-09-03", tasks: "4" }]);
  });
});

describe("usageTiles", () => {
  it("is empty when no host session matched", () => {
    expect(usageTiles(blocked)).toBeNull();
    expect(usageTiles({ ...blocked, spend: { turns: 0 } })).toBeNull();
  });
  it("totals cost, tokens, cache hit and time", () => {
    expect(usageTiles(building)).toEqual([
      ["Cost", "$26.10"], ["Turns", "90"], ["Prompts", "31"], ["Tokens in", "6.0M"], ["Cached", "3.0M"],
      ["Tokens out", "412k"], ["Cache hit", "33%"], ["Agent time", "1h 30m"], ["Cost / turn", "$0.29"], ["Time / turn", "60s"],
    ]);
  });
  it("shows dashes for values the logs do not carry", () => {
    const bare = usageTiles({ ...building, spend: { turns: 3, cost: null, priced_turns: 0, timed_turns: 0 } })!;
    expect(Object.fromEntries(bare)).toMatchObject({
      Cost: "—", Turns: "3", "Cache hit": "—", "Agent time": "—", "Cost / turn": "—", "Time / turn": "—" });
  });
});

const setup = (over: Partial<ProjectSetup> = {}): ProjectSetup =>
  ({ root: "/work/gsd-path", local_skills: [], runtime: true, contracts: true, hooks: true, runtime_version: "1.4.0", ...over });
const NAMES = { claude: "Claude Code", codex: "Codex" };
const row = (rows: ReturnType<typeof setupRows>, key: string) => rows.find((item) => item.key === key)!;

describe("setupRows", () => {
  it("lists runtime, guard hooks, skills, health check and environment", () => {
    expect(setupRows(setup(), "1.4.0", null, NAMES)).toEqual([
      { key: "runtime", label: "Runtime", value: "1.4.0", sub: "Guard hooks are kept on update", ok: true, action: null },
      { key: "hooks", label: "Guard hooks", value: "Installed", sub: "pre-commit, commit-msg, pre-push", ok: false,
        action: { label: "Refresh", primary: false, run: "hooks-refresh" } },
      { key: "skills", label: "Skills", value: "Global only", sub: "Agents read the shared install. No project copies.", ok: false, action: null },
      { key: "doctor", label: "Health check", value: "Not run yet", sub: "Read-only. It changes nothing.", ok: false,
        action: { label: "Run", primary: false, run: "doctor" } },
      { key: "env", label: "Environment", value: ".env files", sub: "Variables for this project.", ok: false,
        action: { label: "Edit…", primary: false, run: "env" } },
    ]);
  });
  it("offers the runtime update when a newer release exists", () => {
    expect(row(setupRows(setup({ runtime_version: "1.3.2" }), "1.4.0", null, NAMES), "runtime")).toEqual({
      key: "runtime", label: "Runtime", value: "1.3.2", sub: "Newer runtime available", ok: false,
      action: { label: "Update to 1.4.0", primary: true, run: "update" } });
  });
  it("offers the update for a runtime without a version stamp", () => {
    expect(row(setupRows(setup({ runtime_version: null }), "1.4.0", null, NAMES), "runtime")).toMatchObject({
      value: "No version stamp", action: { label: "Update to 1.4.0", run: "update" } });
  });
  it("offers Restore when the runtime files are missing, and nothing when no runtime was installed", () => {
    expect(row(setupRows(setup({ runtime: false }), "1.4.0", null, NAMES), "runtime")).toMatchObject({
      value: "1.4.0", sub: "The runtime files are missing.", ok: false, action: { label: "Restore", run: "runtime-restore" } });
    expect(row(setupRows(setup({ runtime: false, runtime_version: null }), "1.4.0", null, NAMES), "runtime")).toMatchObject({
      value: "Not installed", action: null, ok: false });
  });
  it("offers Add guards when the guard hooks are missing", () => {
    expect(row(setupRows(setup({ hooks: false }), "1.4.0", null, NAMES), "hooks")).toMatchObject({
      value: "None", sub: "Edits to archived work and unapproved ship commits are not blocked.",
      action: { label: "Add guards", primary: true, run: "hooks-init" } });
  });
  it("names the agents with skills inside the project", () => {
    expect(row(setupRows(setup({ local_skills: ["claude", "codex", "kiro"] }), "1.4.0", null, NAMES), "skills")).toMatchObject({
      value: "Claude Code, Codex, kiro", sub: "Project copies in this repository." });
  });
  it("shows the health check result and offers to run it again", () => {
    expect(row(setupRows(setup(), "1.4.0", { ok: true, stdout_tail: "note: fine", error: null }, NAMES), "doctor")).toMatchObject({
      value: "Passed", action: { label: "Run again", run: "doctor" } });
    expect(row(setupRows(setup(), "1.4.0", { ok: false, stdout_tail: "", error: "project: no guard" }, NAMES), "doctor").value).toBe("Findings");
  });
  it("says why the rows are missing when the plugin status does not list the project", () => {
    expect(setupRows(undefined, "1.4.0", null, NAMES).map((item) => item.key)).toEqual(["doctor", "env"]);
  });
});

describe("doctorReport", () => {
  it("splits notes, other lines and findings", () => {
    expect(doctorReport({ ok: false, stdout_tail: "note: claude ok\nchecked 3 targets\n", error: "project: AGENTS.md block is stale\nproject: no guard" })).toEqual({
      ok: false, summary: "Findings",
      lines: [{ kind: "note", text: "claude ok" }, { kind: "line", text: "checked 3 targets" },
        { kind: "error", text: "project: AGENTS.md block is stale" }, { kind: "error", text: "project: no guard" }],
    });
  });
  it("passes without findings", () => {
    expect(doctorReport({ ok: true, stdout_tail: "note: all good", error: null })).toEqual({
      ok: true, summary: "Passed", lines: [{ kind: "note", text: "all good" }] });
  });
});

describe("memberRows", () => {
  const member = (name: string, current: boolean, hooks: boolean, reason: string | null = null) => ({
    name, checkout: "/work/" + name, remote: "git@github.com:x/" + name + ".git", integration: "pull-request", marker: { current, reason }, hooks });
  it("shows marker and hooks pills and the action each member needs", () => {
    expect(memberRows([member("api", true, true), member("web", false, true, "coordinator moved"), member("worker", true, false)], ["/work/api"])).toEqual([
      { name: "api", checkout: "/work/api", watched: true, integration: "pull-request", reason: null, actions: [],
        marker: { label: "Marker ok", tone: "ok" }, hooks: { label: "Member hooks installed", tone: "ok" } },
      { name: "web", checkout: "/work/web", watched: false, integration: "pull-request", reason: "coordinator moved", actions: ["repair"],
        marker: { label: "Marker stale", tone: "bad" }, hooks: { label: "Member hooks installed", tone: "ok" } },
      { name: "worker", checkout: "/work/worker", watched: false, integration: "pull-request", reason: null, actions: ["hooks"],
        marker: { label: "Marker ok", tone: "ok" }, hooks: { label: "No member hooks", tone: "warn" } },
    ]);
  });
  it("offers both actions when the marker is stale and the hooks are missing", () => {
    expect(memberRows([member("api", false, false)], [])[0].actions).toEqual(["repair", "hooks"]);
  });
});

describe("repositories in this milestone", () => {
  const task = (id: string, status: string, repo?: string) => ({ id, title: id, wave: 1, status, files: [], repo });
  const lock = [{ name: "api", branch: "gsd-path/demo-M004", base: "a".repeat(40) }, { name: "web", branch: "gsd-path/demo-M004", base: "c".repeat(40) }];

  it("is empty for a single-repo milestone", () => {
    expect(repoRows({ ...building, tasks: [task("T1", "done"), task("T2", "pending")] })).toEqual([]);
  });
  it("counts tasks per repository and shows the locked branch and base", () => {
    const p = { ...building, branch: "gsd-path/M004", member_lock: lock,
      tasks: [task("T1", "done"), task("T2", "done", "api"), task("T3", "pending", "api"), task("T4", "pending", "docs")] };
    expect(repoRows(p)).toEqual([
      { name: "This project", tasks: "1/1", branch: "gsd-path/M004", base: DASH, close: null },
      { name: "api", tasks: "1/2", branch: "gsd-path/demo-M004", base: "aaaaaaa", close: null },
      { name: "web", tasks: DASH, branch: "gsd-path/demo-M004", base: "ccccccc", close: null },
      // Named by a task before build locks it.
      { name: "docs", tasks: "0/1", branch: DASH, base: DASH, close: null },
    ]);
  });
  it("shows each member's close state during ship", () => {
    const p = { ...building, member_lock: lock, tasks: [], member_close: [
      { name: "api", status: "integrated", merge: "b".repeat(40), tag: "milestone/demo-004-x" }, { name: "web", status: "pending", merge: null, tag: null }] };
    const [, api, web] = repoRows(p);
    expect(api.close).toEqual({ label: "Integrated", tone: "ok", detail: "bbbbbbb · milestone/demo-004-x" });
    expect(web.close).toEqual({ label: "Closing", tone: "acc", detail: null });
  });
});
