// Development only: lets `npm run dev` show every screen in a plain browser,
// without the Rust shell. Pick a state with ?state=<name>. Never part of a build.
import { mockIPC } from "@tauri-apps/api/mocks";
import { mockEnvironment } from "./mocks/environment";
import { mockSettings } from "./mocks/settings";
import { mockSkills } from "./mocks/skills";
import { mockStats } from "./mocks/stats";
import { building, status } from "./fixtures";
import type { Launch, Shell } from "./shell";

const launch = (over: Partial<Launch> = {}): Launch => ({
  action: "start", port: 8765, version: "0.2.0", autostart_ok: true, problems: [], legacy: [], replaced: null,
  requirements: [
    { id: "python", required: true, state: "ready", detail: "3.9.6" },
    { id: "git", required: true, state: "ready", detail: "2.39.5 (Apple Git-154)" },
    { id: "gh", required: false, state: "missing", detail: null },
  ],
  ...over,
});
const shell = (over: Partial<Shell> = {}): Shell => ({
  phase: "ready", os: "macos", port: 8765, python_missing: false, launch: launch(), error: null, autostart: true, owned: true,
  version: "0.1.0", update: null, update_error: null, ...over,
});
const blocked = (kind: string, message: string, fix: string, detail?: object): Shell =>
  shell({ phase: "blocked", launch: launch({ action: "setup", problems: [{ kind, message, fix, blocking: true, detail }] }) });

const STATES: Record<string, Shell> = {
  ready: shell(),
  "no-python": shell({ phase: "blocked", python_missing: true, launch: null }),
  "no-python-windows": shell({ os: "windows", phase: "blocked", python_missing: true, launch: null }),
  "no-git": blocked("git", "Git is not installed.", "Run `xcode-select --install`, or install Git from https://git-scm.com/download/mac."),
  port: blocked("port", "Another program is using port 8765.", "Quit it, then choose Retry.", { owner: "other", pid: 4412, name: "node" }),
  "port-daemon": blocked("port", "An older GSD Path daemon is using port 8765 and could not be stopped.",
    "Stop it (Activity Monitor, Task Manager, or `kill`), then choose Retry.",
    { owner: "daemon", pid: 4412, name: "python3" }),
  install: blocked("install", "The daemon could not be installed into ~/.gsd-path/venv.", "Check your network connection, then choose Retry."),
  migrated: shell({ launch: launch({ replaced: "0.0.9", legacy: [
    { name: "launch-agent", removed: true, fix: "" }, { name: "login-item", removed: true, fix: "" },
    { name: "tray-app", removed: true, fix: "" }] }) }),
  update: shell({ update: { version: "0.1.1", notes: "Fixes the Settings save button and adds the environment editor." } }),
  "update-refused": shell({ update: { version: "0.1.1", notes: null }, update_error: "the signature does not match" }),
  "migrate-failed": shell({ autostart: false, launch: launch({ autostart_ok: false, replaced: "0.0.9", legacy: [
    { name: "launch-agent", removed: false, fix: "launchctl bootout gui/501/org.gsd-path.daemon" },
    { name: "login-item", removed: true, fix: "" }, { name: "tray-app", removed: true, fix: "" }] }) }),
};

const query = new URLSearchParams(location.search);
const state = STATES[query.get("state") ?? "ready"] ?? STATES.ready;
if (query.has("done")) localStorage.setItem("gsd-path.setup-done", "1");
else localStorage.removeItem("gsd-path.setup-done");

// The daemon's read endpoints, by path (without the query).
const API: Record<string, unknown> = {
  // ?flavors adds a gsd-core card in the GSD Path folder: one card per framework.
  "/status": query.has("flavors") ? { ...status, projects: [...status.projects, {
    ...building, id: "/work/gsd-path::gsd-core", flavor: "gsd-core", health: "amber",
    phases: ["discuss", "research", "plan", "execute", "verify"], phase: "execute",
    workflow: { state: "active", label: "In execute" },
    attention: [{ kind: "question", label: "Phase 02 needs a human check", ref: "02-VERIFICATION.md" }] }] } : status,
  "/api/refresh": { ok: true },
  "/activity": { events: [
    { root: "/work/gsd-path", at: "2026-09-29T03:58:00+00:00", type: "phase-changed", detail: "plan → build" },
    { root: "/work/atlas", at: "2026-10-01T01:00:00+00:00", type: "blocked", detail: "ship" }] },
  "/api/project-data": {
    verify_records: [{ recorded_at: "2026-09-29T03:58:11+00:00", task: "T002", command: "python -m unittest", commit: "0e9a3b1", result: "pass" }],
    usage_records: [{ task: "T001", phase: "build", model: "kimi-k2", tokens_in: 1200, tokens_out: 400, cost: 0.12 }],
    turns: [], activity: [],
    sources: [{ path: ".project/STATE.md", status: "available" }, { path: ".project/LESSONS.md", status: "missing" }],
  },
};
const FILES = [
  { path: ".project/STATE.md", group: "Project records" }, { path: ".project/ROADMAP.md", group: "Project records" },
  { path: "README.md", group: "Repository" }];
function projectFiles(params: URLSearchParams) {
  const path = params.get("path") ?? "";
  if (params.get("action") === "list") return { files: FILES, coverage: [], scope: "Git-tracked files, plus .project records." };
  if (params.get("action") === "history") {
    return { revisions: [{ revision: "0e9a3b1c55d2".padEnd(40, "0"), at: "2026-09-29T03:58:00+00:00", label: "T002: watch folders" }],
      reason: "Committed versions of this path." };
  }
  if (!FILES.some((file) => file.path === path)) throw new Error("File is not available.");
  return { group: "Project records", bytes: 64, revision: params.get("revision"), modified: 1790000000, preview_warning: null,
    text: `# ${path}\n\nSee [the roadmap](ROADMAP.md).`,
    html: `<h1>${path}</h1><p>See <a href="#" data-document-link="ROADMAP.md">the roadmap</a>.</p>` };
}

mockIPC((command, args) => {
  if (command === "api") {
    if (query.has("offline")) throw new Error("connection refused");
    const { method, path, body } = args as { method: string; path: string; body: unknown };
    const url = new URL(path, "http://daemon.invalid");
    // Each later page owns its routes in src/mocks/<page>.ts.
    for (const page of [mockSkills, mockStats, mockSettings, mockEnvironment]) {
      const answer = page(method, url, body);
      if (answer !== undefined) return answer;
    }
    return url.pathname === "/api/project-files" ? projectFiles(url.searchParams) : API[url.pathname];
  }
  if (command === "open_url") return void window.open((args as { url: string }).url);
  if (command === "tray_action") return void console.log("tray_action", args);
  if (command === "pick_folder") return "/Users/me/work";
  if (command === "open_logs") return void console.log("open_logs");
  if (command === "check_update") return state;
  if (command === "install_update") throw new Error("the signature does not match");
  if (command === "set_autostart") return { ...state, autostart: (args as { enabled: boolean }).enabled };
  return state; // shell_state, boot_command, use_port
}, { shouldMockEvents: true });
