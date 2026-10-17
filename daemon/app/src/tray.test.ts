import { describe, expect, it } from "vitest";
import { asking, blocked, building, shipped, status } from "./fixtures";
import { attentionCards, trayRows, trayStatus } from "./tray";

describe("trayStatus", () => {
  it("counts projects while the monitor answers", () => {
    expect(trayStatus(status, false)).toEqual({ tone: "ok", text: "4 projects" });
    expect(trayStatus({ ...status, projects: [building] }, false).text).toBe("1 project");
  });
  it("says Stopped when the monitor does not answer", () => {
    expect(trayStatus(status, true)).toEqual({ tone: "bad", text: "Stopped" });
    expect(trayStatus(null, false)).toEqual({ tone: "bad", text: "Stopped" });
  });
});

describe("attentionCards", () => {
  it("opens a gsd-pi or gsd-core card by its id, not its shared folder", () => {
    const pi = { ...building, id: "/work/gsd-path::gsd-pi", flavor: "gsd-pi" };
    expect(attentionCards([pi])[0].root).toBe("/work/gsd-path::gsd-pi");
    expect(trayRows([building, pi]).map((row) => row.root).sort()).toEqual(["/work/gsd-path", "/work/gsd-path::gsd-pi"]);
  });
  it("lists only projects that need attention, red before amber, then by name", () => {
    expect(attentionCards(status.projects)).toEqual([
      { root: "/work/atlas", name: "atlas", reason: ".project/review/FINAL.md — reject" },
      { root: "/work/notes", name: "field-notes", reason: "Which search index do we ship?" },
      { root: "/work/gsd-path", name: "gsd-path", reason: "no activity for 2d" },
    ]);
  });
  it("joins several reasons and is empty when nothing needs attention", () => {
    const two = { ...blocked, attention: [{ kind: "blocked", label: "T004 — Ship" }, { kind: "question", label: "Which port?" }] };
    expect(attentionCards([two])[0].reason).toBe("T004 — Ship · Which port?");
    expect(attentionCards([shipped])).toEqual([]);
  });
});

describe("trayRows", () => {
  it("lists every project in board order with a one-line summary", () => {
    expect(trayRows(status.projects).map((row) => [row.name, row.line, row.tone, row.quiet])).toEqual([
      ["atlas", "M002 · ship", "bad", false],
      ["field-notes", "M001 · research", "warn", false],
      ["gsd-path", "M004 · build · 2 of 3 tasks", "warn", false],
      ["done-thing", "M003 · shipped", "ok", true],
    ]);
  });
  it("carries the phase cells and says when no phase is recorded", () => {
    expect(trayRows([blocked])[0].cells[7]).toBe("blocked");
    expect(trayRows([{ ...asking, phase: null }])[0].line).toBe("M001 · no phase");
  });
});
