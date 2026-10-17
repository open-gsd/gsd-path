import { describe, expect, it } from "vitest";
import { boardRow, filterCounts, setupPill, updateBanner, visibleProjects } from "./board";
import { asking, blocked, building, shipped, status } from "./fixtures";
import type { HostInfo, PluginStatus, ProjectSetup } from "./skills";
import { phaseTrack } from "./project";
import { nameOf } from "./status";

const NOW = Date.parse(status.generated_at!);
const names = (filter: string, query = "") => visibleProjects(status.projects, filter, query).map(nameOf);

describe("filters", () => {
  it("counts projects per state", () => {
    expect(filterCounts(status.projects)).toEqual([
      { key: "all", label: "All", count: 4 }, { key: "active", label: "In progress", count: 2 },
      { key: "blocked", label: "Blocked", count: 1 }, { key: "shipped", label: "Shipped", count: 1 },
    ]);
  });
  it("lists Unverified only when a project is unverified", () => {
    const old = { ...building, workflow: undefined };
    expect(filterCounts([old, blocked]).map((f) => [f.key, f.count])).toEqual([
      ["all", 2], ["active", 0], ["blocked", 1], ["shipped", 0], ["unverified", 1]]);
  });
  it("puts a project with no milestone after the projects in progress", () => {
    const idle = { ...building, repository: "aaa-new", workflow: { state: "idle" as const, label: "Not started" } };
    expect(visibleProjects([shipped, idle, building], "all", "").map(nameOf)).toEqual(["gsd-path", "aaa-new", "done-thing"]);
  });
  it("shows only the projects in the chosen state, in board order", () => {
    expect(names("all")).toEqual(["atlas", "field-notes", "gsd-path", "done-thing"]);
    expect(names("active")).toEqual(["field-notes", "gsd-path"]);
    expect(names("blocked")).toEqual(["atlas"]);
    expect(names("shipped")).toEqual(["done-thing"]);
  });
  it("searches name, folder and milestone without case", () => {
    expect(names("all", "  ATLAS ")).toEqual(["atlas"]);
    expect(names("all", "/work/notes")).toEqual(["field-notes"]);
    expect(names("all", "daemon")).toEqual(["gsd-path"]);
    expect(names("all", "gsd path")).toEqual(["gsd-path"]); // the project state name
    expect(names("shipped", "atlas")).toEqual([]);
    expect(names("all", "zzz")).toEqual([]);
  });
});

describe("boardRow", () => {
  it("says why a project with no milestone has no status", () => {
    const idle = { ...building, attention: [], workflow: { state: "idle" as const, label: "Not started", reason: "No milestone has started yet." } };
    const row = boardRow(idle, NOW);
    expect([row.state, row.label, row.note]).toEqual(["idle", "Not started", "No milestone has started yet."]);
    expect(boardRow({ ...blocked, attention: [] }, NOW).note).toBe(""); // only the idle state falls back to the reason
  });
  it("shows the milestone, phase, tasks and usage of a project in build", () => {
    expect(boardRow(building, NOW)).toEqual({
      id: "/work/gsd-path", root: "/work/gsd-path", flavor: null, name: "gsd-path", tone: "warn", path: "/work/gsd-path",
      number: "M004", slug: "daemon", cells: ["done", "done", "done", "done", "done", "done", "now", "todo"], phase: "build",
      state: "active", label: "In build", note: "no activity for 2d", ago: "2d ago",
      tasks: "2/3", cost: "$26.10", turns: "90 turns",
    });
  });
  it("gives each framework in one folder its own card id and badge", () => {
    const core = { ...building, id: "/work/gsd-path::gsd-core", flavor: "gsd-core" };
    expect(boardRow(core, NOW)).toMatchObject({ id: "/work/gsd-path::gsd-core", root: "/work/gsd-path", flavor: "gsd-core" });
    expect(boardRow({ ...building, flavor: "gsd-path" }, NOW).flavor).toBeNull();
    expect(visibleProjects([building, core], "all", "gsd-core").map((p) => p.id)).toEqual(["/work/gsd-path::gsd-core"]);
  });
  it("draws a gsd-core card with its own five steps", () => {
    const core = { ...building, flavor: "gsd-core", phases: ["discuss", "research", "plan", "execute", "verify"], phase: "plan" };
    expect(boardRow(core, NOW).cells).toEqual(["done", "done", "now", "todo", "todo"]);
    expect(phaseTrack(core).map((step) => [step.label, step.state])).toEqual([
      ["discuss", "done"], ["research", "done"], ["plan", "now"], ["execute", "todo"], ["verify", "todo"]]);
    expect(boardRow({ ...core, workflow: { state: "shipped", label: "Shipped" } }, NOW).cells).toEqual(Array(5).fill("done"));
  });
  it("shows a blocked project with its reason and no invented usage", () => {
    expect(boardRow(blocked, NOW)).toMatchObject({
      tone: "bad", state: "blocked", label: "Blocked", note: ".project/review/FINAL.md — reject", ago: "3h ago",
      tasks: "—", cost: "—", turns: "No matched sessions",
    });
  });
  it("has no note for a healthy project and says when no phase is recorded", () => {
    expect(boardRow(shipped, NOW)).toMatchObject({ note: "", label: "Shipped", ago: "28d ago" });
    expect(boardRow({ ...asking, phase: null }, NOW).phase).toBe("No phase recorded");
  });
  it("names the worktree next to the project folder", () => {
    expect(boardRow({ ...building, worktree_root: "/work/wt/a" }, NOW).path).toBe("/work/gsd-path · Worktree: /work/wt/a");
  });
});

const setup = (over: Partial<ProjectSetup> = {}): ProjectSetup =>
  ({ root: "/work/gsd-path", local_skills: [], runtime: true, contracts: true, hooks: true, runtime_version: "1.4.0", ...over });

describe("setupPill", () => {
  it("says Up to date for the latest runtime with guard hooks", () => {
    expect(setupPill(setup(), "1.4.0")).toEqual({ label: "Up to date", tone: "ok" });
  });
  it("puts a runtime update before missing guards", () => {
    expect(setupPill(setup({ runtime_version: "1.3.2", hooks: false }), "1.4.0")).toEqual({ label: "Runtime update", tone: "acc" });
    expect(setupPill(setup({ runtime_version: null }), "1.4.0")).toEqual({ label: "Runtime update", tone: "acc" }); // an old runtime without a stamp
  });
  it("warns when the guard hooks are missing", () => {
    expect(setupPill(setup({ hooks: false }), "1.4.0")).toEqual({ label: "No guards", tone: "warn" });
  });
  it("says when the project has no runtime", () => {
    expect(setupPill(setup({ runtime: false, runtime_version: null }), "1.4.0")).toEqual({ label: "No runtime", tone: "warn" });
  });
  it("does not report an update when the latest release is not known", () => {
    expect(setupPill(setup({ runtime_version: "1.3.2" }), null)).toEqual({ label: "Up to date", tone: "ok" });
  });
  it("shows nothing for a project the plugin status does not list", () => {
    expect(setupPill(undefined, "1.4.0")).toBeNull();
  });
});

describe("updateBanner", () => {
  const hosts: HostInfo[] = [
    { id: "codex", name: "Codex", found: true, path: null, skills_root: "/h/.agents/skills" },
    { id: "claude", name: "Claude Code", found: true, path: null, skills_root: "/h/.claude/skills" },
    { id: "zed", name: "Zed", found: true, path: null, skills_root: "/h/.agents/skills" },
  ];
  const plugin = (over: Partial<PluginStatus> = {}): PluginStatus => ({
    latest: "1.4.0", update_available: true,
    hosts: { codex: { installed: true, version: "1.3.2" }, zed: { installed: true, version: "1.3.2" }, claude: { installed: true, version: "1.4.0" } },
    projects: [setup({ runtime_version: "1.3.2" }), setup({ root: "/work/atlas", hooks: false }), setup({ root: "/work/gone", runtime_version: "1.0.0" })],
    ...over,
  });
  it("lists only the pending skills and runtime updates", () => {
    expect(updateBanner(hosts, plugin(), status.projects)).toEqual({
      count: 2, title: "2 updates available", text: "skills for Codex and Zed, runtime for gsd-path" });
  });
  it("counts one update in the singular", () => {
    const one = plugin({ hosts: { claude: { installed: true, version: "1.4.0" } } });
    expect(updateBanner(hosts, one, status.projects)).toEqual({ count: 1, title: "1 update available", text: "runtime for gsd-path" });
    // A gsd-core card in the same folder shares the folder, not the GSD Path runtime.
    const core = { ...building, id: "/work/gsd-path::gsd-core", flavor: "gsd-core" };
    expect(updateBanner(hosts, one, [...status.projects, core])?.text).toBe("runtime for gsd-path");
  });
  it("compares a runtime with the chosen release, not the latest one", () => {
    const chosen = plugin({ hosts: {}, releases: { latest: "1.4.0", selected: "1.3.2", versions: ["1.4.0", "1.3.2"] } });
    expect(updateBanner(hosts, chosen, status.projects)).toBeNull();
  });
  it("is hidden when nothing is pending or the status is not loaded", () => {
    expect(updateBanner(hosts, plugin({ hosts: {}, projects: [setup()] }), status.projects)).toBeNull();
    expect(updateBanner(hosts, null, status.projects)).toBeNull();
  });
});
