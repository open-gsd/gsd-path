import { describe, expect, it } from "vitest";
import { building, blocked } from "./fixtures";
import { costChart, phaseRows, reloadDue, scopes, tokenChart, unpricedNote, verifyChart, waveRows } from "./stats";
import type { StatsPayload } from "./stats";

const END = "2026-10-01";
const payload = (over: Partial<StatsPayload> = {}): StatsPayload => ({
  scope: null, days: null, unpriced: [], phases: null, waves: null, verify: null, missing: {}, ...over,
});
const days = [
  { date: "2026-09-01", tokens: 9_000_000, turns: 50, cost: 99 }, // older than the window
  { date: "2026-09-18", tokens: 1_000_000, turns: 4, cost: 1 },
  { date: "2026-09-29", tokens: 4_200_000, turns: 12, cost: 3.8 },
  { date: "2026-09-30", tokens: 2_100_000, turns: 6, cost: null },
];

describe("tokenChart", () => {
  it("shows the last 14 days up to the end day, with the peak and the total of those days", () => {
    const chart = tokenChart(payload({ days }), END);
    if (typeof chart === "string") throw new Error(chart);
    expect(chart.total).toBe("7.3M tokens");
    expect(chart.peak).toBe("peak 4.2M · Sep 29");
    expect([chart.first, chart.last]).toEqual(["Sep 18", "Oct 1"]);
    expect(chart.bars).toHaveLength(14);
    expect(chart.bars[0]).toEqual({ date: "2026-09-18", percent: 24, title: "Sep 18 · 1.0M tokens · 4 turns" });
    expect(chart.bars[11].percent).toBe(100);
    expect(chart.bars[12].percent).toBe(50);
  });
  it("leaves a day without sessions blank: no bar, never a zero bar", () => {
    const chart = tokenChart(payload({ days }), END);
    if (typeof chart === "string") throw new Error(chart);
    expect(chart.bars[1]).toEqual({ date: "2026-09-19", percent: null, title: "Sep 19 · no sessions" });
    expect(chart.bars[13].percent).toBeNull(); // Oct 1
  });
  it("ends at the last recorded day when no end day is known", () => {
    const chart = tokenChart(payload({ days }), null);
    if (typeof chart === "string") throw new Error(chart);
    expect([chart.first, chart.last]).toEqual(["Sep 17", "Sep 30"]);
  });
  it("gives the daemon's reason when there are no days", () => {
    expect(tokenChart(payload({ missing: { days: "No host sessions matched." } }), END)).toBe("No host sessions matched.");
    expect(tokenChart(payload(), END)).toBe("No data recorded.");
  });
  it("says so when every recorded day is older than the window", () => {
    expect(tokenChart(payload({ days: [days[0]] }), END)).toBe("No host sessions in the last 14 days.");
  });
});

describe("costChart", () => {
  it("sums only priced days and gives a day without a price no bar", () => {
    const chart = costChart(payload({ days }), END);
    if (typeof chart === "string") throw new Error(chart);
    expect(chart.total).toBe("$4.80");
    expect(chart.peak).toBe("peak $3.80 · Sep 29");
    expect(chart.bars[0]).toEqual({ date: "2026-09-18", percent: 26, title: "Sep 18 · $1.00" });
    expect(chart.bars[11].percent).toBe(100);
    expect(chart.bars[12]).toEqual({ date: "2026-09-30", percent: null, title: "Sep 30 · no price" });
    expect(chart.bars[1].title).toBe("Sep 19 · no sessions");
  });
  it("is missing, not $0.00, when no day in the window has a price", () => {
    expect(costChart(payload({ days: [days[3]] }), END)).toBe("No model in these sessions has a price, so no cost is known.");
  });
  it("gives the reason when there are no days", () => {
    expect(costChart(payload({ missing: { days: "No host sessions matched." } }), END)).toBe("No host sessions matched.");
    expect(costChart(payload({ days: [days[0]] }), END)).toBe("No host sessions in the last 14 days.");
  });
});

describe("unpricedNote", () => {
  it("names the models that have no price", () => {
    expect(unpricedNote([])).toBeNull();
    expect(unpricedNote(["claude-sonnet-5"])).toBe("claude-sonnet-5 has no price, so its tokens are counted and its cost is left out.");
    expect(unpricedNote(["a", "b"])).toBe("a, b have no price, so their tokens are counted and their cost is left out.");
  });
});

describe("phaseRows", () => {
  it("lists the eight phases in order; a phase with no record says not yet and has no bar", () => {
    const rows = phaseRows(payload({ phases: [{ phase: "build", seconds: 50400 }, { phase: "plan", seconds: 9000 }, { phase: "define", seconds: 300 }] }));
    if (typeof rows === "string") throw new Error(rows);
    expect(rows.map((row) => row.label)).toEqual(["inspect", "define", "research", "decide", "roadmap", "plan", "build", "ship"]);
    expect(rows[0]).toEqual({ label: "inspect", value: "not yet", percent: null });
    expect(rows[1]).toEqual({ label: "define", value: "5m", percent: 1 });
    expect(rows[5]).toEqual({ label: "plan", value: "2h 30m", percent: 18 });
    expect(rows[6]).toEqual({ label: "build", value: "14h 0m", percent: 100 });
  });
  it("keeps a phase name the app does not know, after the eight", () => {
    const rows = phaseRows(payload({ phases: [{ phase: "shipped", seconds: 60 }] }));
    if (typeof rows === "string") throw new Error(rows);
    expect(rows).toHaveLength(9);
    expect(rows[8]).toEqual({ label: "shipped", value: "1m", percent: 100 });
  });
  it("orders a gsd-pi or gsd-core card by its own steps", () => {
    const rows = phaseRows(payload({ phases: [{ phase: "execute", seconds: 60 }] }), ["discuss", "research", "plan", "execute", "verify"]);
    if (typeof rows === "string") throw new Error(rows);
    expect(rows.map((row) => row.label)).toEqual(["discuss", "research", "plan", "execute", "verify"]);
  });
  it("gives the reason when no phase change is recorded", () => {
    expect(phaseRows(payload({ missing: { phases: "No phase change recorded yet." } }))).toBe("No phase change recorded yet.");
  });
});

describe("waveRows", () => {
  it("shows done and open cells per wave, with the wave name when the project has one", () => {
    const rows = waveRows(payload({ waves: [{ wave: 1, total: 3, done: 3 }, { wave: 2, total: 4, done: 3 }, { wave: 3, total: 2, done: 0 }] }), building.waves);
    expect(rows).toEqual([
      { label: "wave 1 parsers", cells: [true, true, true], value: "3/3" },
      { label: "wave 2 watcher", cells: [true, true, true, false], value: "3/4" },
      { label: "wave 3 tray", cells: [false, false], value: "0/2" },
    ]);
  });
  it("works without wave names", () => {
    expect(waveRows(payload({ waves: [{ wave: 4, total: 1, done: 1 }] }), undefined)).toEqual([{ label: "wave 4", cells: [true], value: "1/1" }]);
  });
  it("gives the reason when there are no waves", () => {
    expect(waveRows(payload({ missing: { waves: "Choose a project to see its waves." } }), undefined)).toBe("Choose a project to see its waves.");
  });
});

describe("verifyChart", () => {
  const run = (result: string, at: string) => ({ command: "npm test", commit: "0e9a3b1c55d2", result, recorded_at: at, project: "gsd-path" });
  it("keeps the daemon's order, marks pass and fail, and counts them", () => {
    const chart = verifyChart(payload({ verify: [run("pass", "2026-09-28T01:00:00+00:00"), run("fail", "2026-09-29T02:00:00+00:00"), run("pass", "2026-09-29T03:58:11+00:00")] }));
    if (typeof chart === "string") throw new Error(chart);
    expect(chart.total).toBe("2 pass · 1 fail");
    expect(chart.squares.map((square) => square.pass)).toEqual([true, false, true]);
    expect(chart.squares[1].title).toBe("fail · gsd-path · npm test · 0e9a3b1 · 2026-09-29 02:00");
  });
  it("does not count an unknown result as a pass", () => {
    const chart = verifyChart(payload({ verify: [run("error", "2026-09-28T01:00:00+00:00")] }));
    if (typeof chart === "string") throw new Error(chart);
    expect(chart.total).toBe("0 pass · 1 fail");
    expect(chart.squares[0].pass).toBe(false);
  });
  it("gives the reason when no run is recorded", () => {
    expect(verifyChart(payload({ missing: { verify: "No verify run recorded." } }))).toBe("No verify run recorded.");
  });
});

describe("scopes", () => {
  it("lists All projects, then every project, and marks the open one", () => {
    expect(scopes([building, blocked], "/work/atlas")).toEqual([
      { label: "All projects", href: "#/stats", current: false },
      { label: "gsd-path", href: "#/stats/%2Fwork%2Fgsd-path", current: false },
      { label: "atlas", href: "#/stats/%2Fwork%2Fatlas", current: true },
    ]);
    expect(scopes([], null)).toEqual([{ label: "All projects", href: "#/stats", current: true }]);
  });
});

describe("reloadDue", () => {
  const last = { root: "/work/atlas", at: 1_000_000 };
  it("loads the first time and when the scope changes", () => {
    expect(reloadDue(null, null, 0)).toBe(true);
    expect(reloadDue(last, null, 1_000_001)).toBe(true);
    expect(reloadDue(last, "/work/gsd-path", 1_000_001)).toBe(true);
  });
  it("loads the same scope again only after one minute", () => {
    expect(reloadDue(last, "/work/atlas", 1_005_000)).toBe(false);
    expect(reloadDue(last, "/work/atlas", 1_059_999)).toBe(false);
    expect(reloadDue(last, "/work/atlas", 1_060_000)).toBe(true);
  });
});
