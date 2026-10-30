import { describe, expect, it } from "vitest";
import { agentCards, agentsWord, footer, installTargets, preselected, stepGate, STEPS } from "./setup";
import type { HostInfo } from "./skills";

const host = (id: string, name: string, found: boolean, root: string): HostInfo =>
  ({ id, name, found, path: null, skills_root: root });
const HOSTS = [
  host("codex", "Codex", true, "/Users/me/.agents/skills"), host("claude", "Claude Code", true, "/Users/me/.claude/skills"),
  host("grok", "Grok", false, "/Users/me/.grok/skills"), host("zed", "Zed", false, "/Users/me/.agents/skills"),
];
const OPEN = { blocked: false, ready: true, installing: false };

describe("steps", () => {
  it("has four steps", () => {
    expect(STEPS()).toEqual(["Requirements", "Agents", "Skills", "Watch folders"]);
  });
  it("stays on Requirements while the monitor does not run", () => {
    expect(stepGate(2, false)).toBe(0);
    expect(stepGate(2, true)).toBe(2);
  });
});

describe("footer", () => {
  it("blocks Continue on Requirements while a required item is missing or the monitor waits", () => {
    expect(footer(0, OPEN)).toEqual({ back: false, skip: false, next: "Continue", canNext: true });
    expect(footer(0, { ...OPEN, blocked: true }).canNext).toBe(false);
    expect(footer(0, { ...OPEN, ready: false }).canNext).toBe(false);
  });
  it("offers Back from step 2 on", () => {
    expect(footer(1, OPEN)).toEqual({ back: true, skip: false, next: "Continue", canNext: true });
  });
  it("blocks Continue and Back while skills install", () => {
    expect(footer(2, { ...OPEN, installing: true })).toMatchObject({ back: false, canNext: false });
    expect(footer(2, OPEN)).toMatchObject({ back: true, canNext: true });
  });
  it("ends on Watch folders with Skip for now and Open dashboard", () => {
    expect(footer(3, OPEN)).toEqual({ back: true, skip: true, next: "Open dashboard", canNext: true });
  });
});

describe("agents", () => {
  it("preselects the agents found on this computer", () => {
    expect(preselected(HOSTS)).toEqual(["codex", "claude"]);
  });
  it("makes one card per agent and says if it was found", () => {
    expect(agentCards(HOSTS, ["codex", "grok"])).toEqual([
      { id: "codex", name: "Codex", found: true, note: "Found on this computer", on: true },
      { id: "claude", name: "Claude Code", found: true, note: "Found on this computer", on: false },
      { id: "grok", name: "Grok", found: false, note: "Not found", on: true },
      { id: "zed", name: "Zed", found: false, note: "Not found", on: false },
    ]);
  });
  it("counts agents in words", () => {
    expect([agentsWord(1), agentsWord(3)]).toEqual(["1 agent", "3 agents"]);
  });
});

describe("installTargets", () => {
  it("lists one folder per skills root for the selected agents", () => {
    expect(installTargets(HOSTS, ["codex", "zed", "grok"])).toEqual([
      { label: "Codex and Zed", path: "/Users/me/.agents/skills/gsd-path", ids: ["codex", "zed"] },
      { label: "Grok", path: "/Users/me/.grok/skills/gsd-path", ids: ["grok"] },
    ]);
  });
  it("names only the selected agent of a shared folder", () => {
    expect(installTargets(HOSTS, ["zed"])).toEqual([{ label: "Zed", path: "/Users/me/.agents/skills/gsd-path", ids: ["zed"] }]);
  });
  it("uses the path separator of the skills root", () => {
    const windows = [host("claude", "Claude Code", true, "C:\\Users\\me\\.claude\\skills")];
    expect(installTargets(windows, ["claude"])[0].path).toBe("C:\\Users\\me\\.claude\\skills\\gsd-path");
  });
  it("is empty when no agent is selected", () => {
    expect(installTargets(HOSTS, [])).toEqual([]);
  });
});
