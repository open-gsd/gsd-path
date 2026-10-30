import { describe, expect, it } from "vitest";
import { failure, frameworkRows, isNewer, joinNames, notDetected, pendingFrameworks, pendingSkills, releaseOptions, sharedRoots, skillRows, targetVersion } from "./skills";
import type { HostInfo, PluginStatus } from "./skills";

const host = (id: string, name: string, found: boolean, root: string): HostInfo =>
  ({ id, name, found, path: found ? "/usr/local/bin/" + id : null, skills_root: root });
const HOSTS = [
  host("codex", "Codex", true, "/Users/me/.agents/skills"), host("claude", "Claude Code", true, "/Users/me/.claude/skills"),
  host("grok", "Grok", false, "/Users/me/.grok/skills"), host("cursor", "Cursor", true, "/Users/me/.cursor/skills"),
  host("zed", "Zed", true, "/Users/me/.agents/skills"), host("kimi", "Kimi Code", false, "/Users/me/.kimi-code/skills"),
];
const plugin = (over: Partial<PluginStatus> = {}): PluginStatus => ({
  latest: "1.4.0", update_available: true, projects: [],
  releases: { latest: "1.4.0", selected: null, versions: ["1.4.0", "1.3.2", "1.3.1"], source: "npm" },
  hosts: {
    codex: { installed: true, version: "1.4.0" }, zed: { installed: true, version: "1.4.0" },
    claude: { installed: true, version: "1.3.2" }, cursor: { installed: false, version: null },
    grok: { installed: false, version: null }, kimi: { installed: false, version: null },
  },
  ...over,
});

describe("versions", () => {
  it("compares versions by number, not by text", () => {
    expect(isNewer("1.10.0", "1.9.0")).toBe(true);
    expect(isNewer("1.4.0", "1.4.0")).toBe(false);
    expect(isNewer("1.3.2", "1.4.0")).toBe(false);
  });
  it("compares as the daemon does: a longer version with the same start is newer", () => {
    expect(isNewer("1.2.0", "1.2")).toBe(true);
    expect(isNewer("1.2", "1.2.0")).toBe(false);
    expect(isNewer("1.4.1", "1.4")).toBe(true);
  });
  it("does not read a part that is not digits as a number", () => {
    expect(isNewer("1..2", "1.0.1")).toBe(false);
    expect(isNewer("2.0.0", "1..2")).toBe(false);
    expect(isNewer("1.4.0-rc1", "1.3.0")).toBe(false);
    expect(isNewer("1.4.0", "1.3.0 ")).toBe(true);
  });
  it("does not call an unknown version newer or older", () => {
    expect(isNewer(null, "1.4.0")).toBe(false);
    expect(isNewer("1.4.0", null)).toBe(false);
    expect(isNewer("1.4.0", "unknown")).toBe(false);
  });
  it("installs the chosen release, else the latest", () => {
    expect(targetVersion(plugin())).toBe("1.4.0");
    expect(targetVersion(plugin({ releases: { latest: "1.4.0", selected: "1.3.2", versions: [] } }))).toBe("1.3.2");
    expect(targetVersion(plugin({ releases: undefined }))).toBe("1.4.0");
    expect(targetVersion(null)).toBeNull();
  });
});

describe("skillRows", () => {
  it("shows agents that share a skills folder as one row", () => {
    const rows = skillRows(HOSTS, plugin());
    expect(rows.map((row) => row.label)).toEqual(["Codex and Zed", "Claude Code", "Cursor"]);
    expect(rows[0]).toEqual({
      ids: ["codex", "zed"], label: "Codex and Zed", path: "/Users/me/.agents/skills", version: "1.4.0",
      tone: "ok", status: "Installed", stateKey: "current", primary: null, preview: false, uninstall: true,
    });
  });
  it("offers the update and a preview when the installed version is older", () => {
    expect(skillRows(HOSTS, plugin())[1]).toMatchObject({
      version: "1.3.2", tone: "warn", status: "Update available", stateKey: "stale", primary: "Update to 1.4.0", preview: true, uninstall: false });
  });
  it("offers Install for a found agent without skills and shows no version", () => {
    expect(skillRows(HOSTS, plugin())[2]).toMatchObject({
      ids: ["cursor"], version: "—", tone: "mute", status: "Not installed", stateKey: "missing", primary: "Install", preview: true, uninstall: false });
  });
  it("lists an agent that is not found when its skills are installed", () => {
    const rows = skillRows(HOSTS, plugin({ hosts: { ...plugin().hosts, grok: { installed: true, version: "1.4.0" } } }));
    expect(rows.map((row) => row.label)).toContain("Grok");
  });
  it("offers the chosen older release without calling it an update", () => {
    const older = plugin({ releases: { latest: "1.4.0", selected: "1.3.2", versions: ["1.4.0", "1.3.2"] } });
    const [codex, claude] = skillRows(HOSTS, older);
    expect(codex).toMatchObject({ status: "Installed", tone: "ok", primary: "Install 1.3.2", preview: true, uninstall: true });
    expect(claude).toMatchObject({ status: "Installed", primary: null, preview: false, uninstall: true });
  });
  it("says when an install has no version stamp", () => {
    const row = skillRows(HOSTS, plugin({ hosts: { ...plugin().hosts, claude: { installed: true, version: null } } }))[1];
    expect(row).toMatchObject({ version: "—", status: "No version stamp", stateKey: "no-stamp", tone: "warn", primary: "Update to 1.4.0", preview: true });
  });
  it("offers no update when the latest release is not known", () => {
    const row = skillRows(HOSTS, plugin({ latest: null, releases: undefined }))[1];
    expect(row).toMatchObject({ status: "Installed", primary: null, uninstall: true });
  });
  it("is empty until the plugin status loads", () => {
    expect(skillRows(HOSTS, null)).toEqual([]);
  });
});

describe("pendingSkills", () => {
  it("counts a shared skills folder once", () => {
    const old = plugin({ hosts: { codex: { installed: true, version: "1.3.2" }, zed: { installed: true, version: "1.3.2" } } });
    expect(pendingSkills(HOSTS, old).map((row) => row.label)).toEqual(["Codex and Zed"]);
  });
  it("compares with the chosen release, not the latest one", () => {
    const chosen = plugin({
      releases: { latest: "1.4.0", selected: "1.3.2", versions: ["1.4.0", "1.3.2", "1.3.1"] },
      hosts: { codex: { installed: true, version: "1.3.1" }, claude: { installed: true, version: "1.3.2" } },
    });
    expect(pendingSkills(HOSTS, chosen).map((row) => row.label)).toEqual(["Codex and Zed"]);
  });
  it("skips an unknown version and a version newer than the release", () => {
    const odd = plugin({ hosts: { codex: { installed: true, version: null }, claude: { installed: true, version: "1.5.0" } } });
    expect(pendingSkills(HOSTS, odd)).toEqual([]);
    expect(pendingSkills(HOSTS, null)).toEqual([]);
  });
});

describe("footer", () => {
  it("names the agents that are not detected and have no skills", () => {
    expect(notDetected(HOSTS, plugin())).toEqual(["Grok", "Kimi Code"]);
  });
  it("names the agents that share one skills folder", () => {
    expect(sharedRoots(HOSTS)).toEqual([{ names: "Codex and Zed", path: "/Users/me/.agents/skills" }]);
  });
  it("joins names as a sentence", () => {
    expect([joinNames(["A"]), joinNames(["A", "B"]), joinNames(["A", "B", "C"])]).toEqual(["A", "A and B", "A, B and C"]);
  });
});

describe("releaseOptions", () => {
  it("lists Latest first, then the older releases", () => {
    expect(releaseOptions(plugin().releases)).toEqual([
      { value: "", label: "Latest · 1.4.0" }, { value: "1.3.2", label: "1.3.2" }, { value: "1.3.1", label: "1.3.1" }]);
  });
  it("is hidden for a git source and before the releases are known", () => {
    expect(releaseOptions({ latest: "1.4.0", selected: null, versions: ["1.4.0"], source: "git" })).toBeNull();
    expect(releaseOptions(undefined)).toBeNull();
    expect(releaseOptions({ latest: null, selected: null, versions: [] })).toBeNull();
  });
});

describe("failure", () => {
  it("names what failed and takes the fix command from the message", () => {
    expect(failure("updated", ["Claude Code"], "Permission denied writing to ~/.claude/skills. Run `chmod -R u+w ~/.claude/skills`, then try again.")).toEqual({
      title: "Claude Code was not updated", unchanged: null, fix: "chmod -R u+w ~/.claude/skills",
      text: "Permission denied writing to ~/.claude/skills. Run `chmod -R u+w ~/.claude/skills`, then try again.",
    });
  });
  it("says nothing was changed only when the installer rolled back or refused", () => {
    expect(failure("installed", ["Codex", "Zed"], "installation failed and was rolled back: disk full")).toMatchObject({
      title: "Codex and Zed were not installed", unchanged: "Nothing was changed.", fix: null });
    expect(failure("installed", ["Cursor"], "installer refused the request (exit 2), nothing was changed: error: bad flag").unchanged)
      .toBe("Nothing was changed.");
    expect(failure("installed", ["Cursor"], "host cursor failed").unchanged).toBeNull();
  });
});

describe("frameworkRows", () => {
  const core = { installed: "1.11.0", latest: "1.17.0", checked: "2026-10-18T12:00:00Z", update_available: true, detected: true,
    hosts: [{ host: "claude", dir: "/Users/me/.claude", version: "1.13.0" }, { host: "codex", dir: "/Users/me/.codex", version: "1.3.1" }] };
  it("lists the CLI and every host, and offers the update when one is behind", () => {
    const rows = frameworkRows(plugin({ frameworks: { "gsd-core": core } }));
    expect(rows).toEqual([{ name: "gsd-core", where: "/Users/me/.claude, /Users/me/.codex",
      version: "CLI\u00a01.11.0\nclaude\u00a01.13.0\ncodex\u00a01.3.1", status: "Update to 1.17.0", tone: "acc", update: true, error: null }]);
    expect(pendingFrameworks(plugin({ frameworks: { "gsd-core": core } }))).toEqual(["gsd-core 1.17.0"]);
  });
  it("says not checked before the first check, and hides frameworks that are not installed", () => {
    const pi = { installed: "1.21.1", hosts: [], latest: null, checked: null, update_available: false, detected: true };
    const none = { ...pi, installed: null, detected: false };
    expect(frameworkRows(plugin({ frameworks: { "gsd-pi": pi, "gsd-core": none } })).map((row) => [row.name, row.where, row.status, row.update]))
      .toEqual([["gsd-pi", "global command", "Not checked yet", false]]);
    expect(pendingFrameworks(plugin({ frameworks: { "gsd-pi": pi } }))).toEqual([]);
    expect(frameworkRows(plugin())).toEqual([]);  // an older daemon sends no frameworks
  });
  it("shows a failed registry check next to the framework and keeps the last known version", () => {
    const rows = frameworkRows(plugin({ frameworks: { "gsd-core": core } }), { "gsd-pi": null, "gsd-core": "offline" });
    expect(rows.map((row) => [row.name, row.status, row.error])).toEqual([["gsd-core", "Update to 1.17.0", "offline"]]);
  });
});
