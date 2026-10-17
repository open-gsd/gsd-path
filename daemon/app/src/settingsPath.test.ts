import { describe, expect, it } from "vitest";
import { canReset, fieldValue, integrationOptions, lockOf, modelKey, pathChanges, pathProjects, savedNote, scopeQuery } from "./settingsPath";
import type { PathData } from "./settingsPath";
import type { Project } from "./status";

const user: PathData = {
  scope: "user", locked: null, approved_review_panel: null,
  settings: {
    integration: { value: "direct", source: "built-in" },
    review_panel: { value: "detected", source: "/home/me/.gsd-path/config.json" },
  },
  models: { "models.roles.coder.model": { value: "gpt-6-astra", source: "/home/me/.gsd-path/config.json" } },
  roles: ["coder", "reviewer"], hosts: ["codex", "claude"],
};
const project: PathData = {
  ...user, scope: "project",
  settings: {
    integration: { value: "pull-request", source: "/work/a/.project/STATE.md", current: "direct", current_source: "milestone override",
      locked: "Shipping mode is locked when build starts." },
    review_panel: { value: "off", source: "built-in" },
  },
};

describe("pathProjects", () => {
  it("offers only GSD Path cards for the project scope", () => {
    const card = (root: string, flavor?: string) => ({ root, id: flavor && flavor !== "gsd-path" ? `${root}::${flavor}` : root, flavor }) as Project;
    const shown = pathProjects([card("/work/both", "gsd-path"), card("/work/both", "gsd-core"), card("/work/pi", "gsd-pi"), card("/work/old")]);
    expect(shown.map((p) => p.id)).toEqual(["/work/both", "/work/old"]);
  });
});

describe("scopeQuery", () => {
  it("names the project root only for project scope", () => {
    expect(scopeQuery("")).toEqual({ scope: "user" });
    expect(scopeQuery("/work/a")).toEqual({ scope: "project", root: "/work/a" });
  });
});

describe("modelKey", () => {
  it("builds the role key, or the host key when a host is chosen", () => {
    expect(modelKey("", "coder", "model")).toBe("models.roles.coder.model");
    expect(modelKey("claude", "reviewer", "effort")).toBe("models.hosts.claude.reviewer.effort");
  });
});

describe("fieldValue", () => {
  it("shows the draft, then the configured value, then inherit for a model without an override", () => {
    expect(fieldValue(user, {}, "integration")).toBe("direct");
    expect(fieldValue(user, { integration: "pull-request" }, "integration")).toBe("pull-request");
    expect(fieldValue(user, {}, "models.roles.coder.model")).toBe("gpt-6-astra");
    expect(fieldValue(user, {}, "models.roles.coder.effort")).toBe("inherit");
  });
  it("keeps the configured value on screen for a key marked for reset", () => {
    expect(fieldValue(user, { review_panel: null }, "review_panel")).toBe("detected");
  });
});

describe("lockOf", () => {
  it("locks shipping mode once build starts, and nothing else", () => {
    expect(lockOf(project, "integration")).toBe("Shipping mode is locked when build starts.");
    expect(lockOf(project, "review_panel")).toBeNull();
    expect(lockOf(user, "integration")).toBeNull();
  });
  it("locks every field during ship and after shipment", () => {
    const shipped = { ...project, locked: "Project settings are locked during ship and after shipment." };
    expect(lockOf(shipped, "review_panel")).toBe(shipped.locked);
    expect(lockOf(shipped, "models.roles.coder.model")).toBe(shipped.locked);
  });
});

describe("canReset", () => {
  it("offers Reset for user settings and for a model override that exists", () => {
    expect(canReset(user, "integration", "")).toBe(true);
    expect(canReset(user, "review_panel", "")).toBe(true);
    expect(canReset(user, "models.roles.coder.model", "")).toBe(true);
    expect(canReset(user, "models.roles.coder.effort", "")).toBe(false);
  });
  it("never offers Reset for a project's shipping mode, or for a locked field", () => {
    expect(canReset({ ...project, settings: { ...project.settings, integration: { value: "direct", source: "x" } } }, "integration", "/work/a")).toBe(false);
    expect(canReset(project, "review_panel", "/work/a")).toBe(true);
    expect(canReset({ ...project, locked: "Locked." }, "review_panel", "/work/a")).toBe(false);
  });
});

describe("integrationOptions", () => {
  it("offers direct and pull request, plus the current value when it is another mode", () => {
    expect(integrationOptions("direct")).toEqual([["direct", "Direct merge"], ["pull-request", "Pull request"]]);
    expect(integrationOptions("external-landing")).toEqual([
      ["direct", "Direct merge"], ["pull-request", "Pull request"], ["external-landing", "External landing"]]);
  });
});

describe("pathChanges", () => {
  it("has no request when the drafts equal the configured values", () => {
    expect(pathChanges(user, { integration: "direct", "models.roles.coder.effort": "inherit" }))
      .toEqual({ requests: [], errors: [], summary: [] });
  });
  it("sets a changed value and resets a key marked for reset", () => {
    expect(pathChanges(user, { integration: "pull-request", review_panel: null, "models.roles.coder.effort": "high" })).toEqual({
      requests: [
        { action: "set", key: "integration", value: "pull-request" },
        { action: "reset", key: "review_panel" },
        { action: "set", key: "models.roles.coder.effort", value: "high" },
      ],
      errors: [],
      summary: ["Shipping mode: direct → pull-request", "Review panel: reset (now detected)", "coder effort: inherit → high"],
    });
  });
  it("names the host in the summary of a host key", () => {
    expect(pathChanges(user, { "models.hosts.claude.reviewer.model": "opus" }).summary).toEqual(["reviewer model on claude: inherit → opus"]);
  });
  it("refuses an empty value and a review panel with spaces", () => {
    expect(pathChanges(user, { "models.roles.coder.model": " ", review_panel: "claude, gpt" })).toEqual({
      requests: [], summary: [],
      errors: ["coder model needs a value. Use Reset to remove it.",
        "Review panel: use off, detected, or comma-separated families without spaces."],
    });
  });
  it("skips a locked field", () => {
    expect(pathChanges(project, { integration: "direct", review_panel: "detected" }).requests)
      .toEqual([{ action: "set", key: "review_panel", value: "detected" }]);
  });
});

describe("savedNote", () => {
  it("says when each saved setting applies", () => {
    expect(savedNote(["integration"], "")).toBe("Saved. Applies to newly initialized projects.");
    expect(savedNote(["integration"], "/work/a")).toBe("Saved. Project shipping default updated.");
    expect(savedNote(["review_panel", "models.roles.coder.model", "models.roles.coder.effort"], "")).toBe(
      "Saved. Applies when preparing future review approvals. Applies to new assignments; running assignments keep their selection.");
  });
});
