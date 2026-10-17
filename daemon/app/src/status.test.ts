import { describe, expect, it } from "vitest";
import { asking, blocked, building, shipped, status } from "./fixtures";
import {
  ago, clock, duration, healthTone, milestoneStack, money, nameOf, phaseCells, pollMs, sortProjects, spendCell,
  stateLabel, stateOf, tokens,
  stateFileOf,
} from "./status";

const NOW = Date.parse("2026-10-01T04:00:21+00:00");

describe("names and state", () => {
  it("names a project by repository, then project, then folder", () => {
    expect(nameOf(building)).toBe("gsd-path");
    expect(nameOf({ ...building, repository: null })).toBe("GSD Path");
    expect(nameOf({ ...building, repository: null, project: null })).toBe("/work/gsd-path");
  });
  it("an older payload without workflow is Unverified", () => {
    const old = { ...building, workflow: undefined };
    expect([stateOf(old), stateLabel(old)]).toEqual(["unverified", "Unverified"]);
    expect([stateOf(blocked), stateLabel(blocked)]).toEqual(["blocked", "Blocked"]);
  });
  it("maps health to a dot tone, with a guess for older payloads", () => {
    expect([building, blocked, shipped].map(healthTone)).toEqual(["warn", "bad", "ok"]);
    expect(healthTone({ ...blocked, health: undefined })).toBe("bad");
    expect(healthTone({ ...building, health: undefined })).toBe("ok");
  });
});

describe("stateFileOf", () => {
  it("opens each framework's own state file", () => {
    expect(stateFileOf(building)).toBe(".project/STATE.md");
    expect(stateFileOf({ ...building, record_files: [{ path: ".gsd/STATE.md", label: "State" }] })).toBe(".gsd/STATE.md");
  });
});

describe("phaseCells", () => {
  it("marks phases before the current one done and the current one now", () => {
    expect(phaseCells(building)).toEqual(["done", "done", "done", "done", "done", "done", "now", "todo"]);
    expect(phaseCells(asking)).toEqual(["done", "done", "now", "todo", "todo", "todo", "todo", "todo"]);
  });
  it("marks the current phase of a blocked project blocked", () => {
    expect(phaseCells(blocked)[7]).toBe("blocked");
    expect(phaseCells(blocked).slice(0, 7)).toEqual(Array(7).fill("done"));
  });
  it("fills every cell for a shipped project and none for an unknown phase", () => {
    expect(phaseCells(shipped)).toEqual(Array(8).fill("done"));
    expect(phaseCells({ ...asking, phase: null })).toEqual(Array(8).fill("todo"));
  });
});

describe("milestoneStack", () => {
  it("splits the roadmap around the current milestone", () => {
    const stack = milestoneStack(building);
    expect(stack.before.map((m) => m.number)).toEqual(["M003"]);
    expect(stack.cur.number).toBe("M004");
    expect(stack.after.map((m) => m.number)).toEqual(["M005"]);
  });
  it("takes the number from the branch when the roadmap does not list the milestone", () => {
    expect(milestoneStack(asking).cur).toMatchObject({ number: "M001", slug: "bootstrap" });
    expect(milestoneStack({ ...asking, branch: "main", milestone: null }).cur).toMatchObject({ number: "now", slug: "no milestone" });
  });
  it("adds the next milestone once", () => {
    const next = { milestone: "notify", status: "planned", phase: "define" };
    expect(milestoneStack({ ...building, next_milestone: next }).after).toHaveLength(1);
    expect(milestoneStack({ ...asking, next_milestone: next }).after).toEqual([
      { number: "next", slug: "notify", status: "planned", phase: "define" }]);
  });
});

describe("formatting", () => {
  it("shows a missing cost as a dash, never as zero", () => {
    expect(money(null)).toBe("—");
    expect(money(undefined)).toBe("—");
    expect(money(0)).toBe("$0.00");
    expect(money(1234.5)).toBe("$1,234.50");
  });
  it("shortens token counts", () => {
    expect([999, 412_000, 1_500_000, 2_340_000_000].map(tokens)).toEqual(["999", "412k", "1.5M", "2.34B"]);
  });
  it("tells relative time against the payload time", () => {
    const at = (seconds: number) => new Date(NOW - seconds * 1000).toISOString();
    expect([30, 150, 3 * 3600 + 5, 2 * 86400 + 5].map((s) => ago(at(s), NOW))).toEqual(["just now", "2m ago", "3h ago", "2d ago"]);
    expect(ago(null, NOW)).toBe("—");
    expect(ago("not a date", NOW)).toBe("—");
    expect(ago(at(-60), NOW)).toBe("just now"); // a clock ahead of the daemon
  });
  it("shortens durations", () => {
    expect([duration(183600), duration(5400), duration(300), duration(null)]).toEqual(["2d 3h", "1h 30m", "5m", null]);
  });
  it("shows the payload time as a local clock time", () => {
    expect(clock(new Date(2026, 9, 1, 4, 0, 21).toISOString())).toBe("04:00:21");
    expect(clock(null)).toBeNull();
  });
});

describe("spendCell", () => {
  it("shows cost and turns for matched sessions", () => {
    expect(spendCell(building.spend)).toEqual({ cost: "$26.10", turns: "90 turns" });
  });
  it("shows a dash and a reason when no session matched", () => {
    expect(spendCell(null)).toEqual({ cost: "—", turns: "No matched sessions" });
    expect(spendCell({ turns: 0, cost: 0 })).toEqual({ cost: "—", turns: "No matched sessions" });
  });
  it("keeps the turns when no model had a price", () => {
    expect(spendCell({ turns: 1200, cost: null })).toEqual({ cost: "—", turns: "1,200 turns" });
  });
});

describe("polling and order", () => {
  it("polls at the daemon's interval, 5 seconds by default", () => {
    expect(pollMs({ ...status, daemon: { poll_seconds: 12 } })).toBe(12000);
    expect(pollMs({ ...status, daemon: undefined })).toBe(5000);
    expect(pollMs(null)).toBe(5000);
  });
  it("sorts blocked first, then in progress by name, then shipped", () => {
    expect(sortProjects(status.projects).map(nameOf)).toEqual(["atlas", "field-notes", "gsd-path", "done-thing"]);
    expect(status.projects.map(nameOf)).toEqual(["gsd-path", "atlas", "done-thing", "field-notes"]); // input untouched
  });
});
