// Development only: answers for the Skills page's daemon routes in the browser mock.
// Return undefined for a path this page does not own. The state lives until the page reloads.
import { status } from "../fixtures";
import type { Member } from "../project";
import type { ProjectSetup, Releases } from "../skills";

const HOME = "/Users/me";
// id, name, found, skills folder. Codex and Zed share one folder, as in the daemon.
const HOSTS: [string, string, boolean, string][] = [
  ["codex", "Codex", true, ".agents/skills"], ["claude", "Claude Code", true, ".claude/skills"],
  ["grok", "Grok", false, ".grok/skills"], ["opencode", "OpenCode", false, ".config/opencode/skills"],
  ["copilot", "Copilot CLI", false, ".copilot/skills"], ["qwen", "Qwen Code", false, ".qwen/skills"],
  ["antigravity", "Antigravity", false, ".gemini/antigravity-cli/skills"], ["cursor", "Cursor", true, ".cursor/skills"],
  ["zed", "Zed", true, ".agents/skills"], ["kiro", "Kiro", false, ".kiro/skills"], ["kimi", "Kimi Code", false, ".kimi-code/skills"],
];
const rootOf = (id: string) => `${HOME}/${HOSTS.find((host) => host[0] === id)![3]}`;

// Installed version per skills folder.
const installed: Record<string, string> = { [rootOf("codex")]: "1.4.0", [rootOf("claude")]: "1.3.2" };
const releases: Releases = { latest: "1.4.0", selected: null, versions: ["1.4.0", "1.3.2", "1.3.1"], source: "npm" };
const target = () => releases.selected ?? releases.latest!;
const setup = (root: string, over: Partial<ProjectSetup>): ProjectSetup =>
  ({ root, local_skills: [], runtime: true, contracts: true, hooks: true, runtime_version: "1.4.0", ...over });
const projects: ProjectSetup[] = status.projects.map((p) => setup(p.root,
  p.root === "/work/gsd-path" ? { runtime_version: "1.3.2" } : p.root === "/work/atlas" ? { hooks: false } : {}));
const member = (name: string, current: boolean, hooks: boolean, reason: string | null = null): Member => ({
  name, checkout: "/work/" + name, remote: `git@github.com:open-gsd/${name}.git`, integration: "pull-request", marker: { current, reason }, hooks });
// /work/gsd-path is a coordinator; /work/notes has a members file that does not validate.
const members = [member("gsd-path-daemon", true, false), member("gsd-path-app", false, true, "marker names another coordinator path"),
  member("gsd-path-docs", true, true)];
let failClaude = true; // the first real install into Claude Code fails, the next one works
let busy = false;

const installer = (...flags: string[]) => ["python3", `${HOME}/.gsd-path/releases/${target()}/scripts/install.py`, ...flags];

/** A slow operation. The daemon runs one at a time and refuses a second one. */
function slow<T>(work: () => T): Promise<T> {
  if (busy) throw new Error("operation in progress");
  busy = true;
  return new Promise((resolve, reject) => setTimeout(() => {
    busy = false;
    try { resolve(work()); } catch (error) { reject(error); }
  }, 900));
}

// gsd-pi and gsd-core, as the daemon's frameworks.status() reports them.
const frameworks = {
  "gsd-pi": { installed: "1.21.1", hosts: [], latest: "1.22.0", checked: "2026-10-18T12:00:00Z", update_available: true, detected: true },
  "gsd-core": { installed: "1.11.0", latest: "1.17.0", checked: "2026-10-18T12:00:00Z", update_available: true, detected: true,
    hosts: [{ host: "claude", dir: `${HOME}/.claude`, version: "1.13.0" }, { host: "codex", dir: `${HOME}/.codex`, version: "1.3.1" }] },
};
function updateFramework(data: Body & { name?: string }) {
  const item = frameworks[data.name as keyof typeof frameworks];
  const commands = data.name === "gsd-pi" ? [["/opt/homebrew/bin/gsd", "update"]]
    : [["/opt/homebrew/bin/npm", "install", "-g", "@opengsd/gsd-core@latest"],
      ...item.hosts.map((h) => ["/opt/homebrew/bin/npx", "-y", "--package=@opengsd/gsd-core@latest", "--", "gsd-core", `--${h.host}`, "--global", "--config-dir", h.dir])];
  if (data.dry_run) return { ok: true, commands, stdout_tail: "", error: null };
  return slow(() => {
    item.installed = item.latest;
    item.hosts.forEach((h) => { h.version = item.latest; });
    item.update_available = false;
    return { ok: true, commands, stdout_tail: commands.map((argv) => "$ " + argv.join(" ")).join("\n"), error: null };
  });
}

function pluginStatus() {
  const hosts = Object.fromEntries(HOSTS.map(([id]) => {
    const root = rootOf(id);
    return [id, { installed: root in installed, version: installed[root] ?? null, root }];
  }));
  const latest = releases.latest;
  return { latest, update_available: Object.values(installed).some((version) => version !== latest), hosts, projects, releases, frameworks };
}

function install(body: { hosts?: string[]; dry_run?: boolean }) {
  const ids = body.hosts?.length ? body.hosts : HOSTS.map((host) => host[0]);
  const roots = [...new Set(ids.map(rootOf))];
  const argv = installer(...ids.map((id) => "--" + id), ...(body.dry_run ? ["--dry-run"] : []));
  if (body.dry_run) {
    return { ok: true, argv, error: null, stdout_tail: ["dry run, nothing written",
      ...roots.map((root) => `would write ${root}/gsd-path (${installed[root] ?? "new"} → ${target()})`),
      `would stamp VERSION ${target()}`].join("\n") };
  }
  return slow(() => {
    if (ids.includes("claude") && failClaude) {
      failClaude = false;
      const root = rootOf("claude");
      return { ok: false, argv, stdout_tail: `installing gsd-path ${target()}\n${root}: PermissionError: [Errno 13] Permission denied`,
        error: `Permission denied writing to ${root}. Run \`chmod -R u+w ${root}\`, then try again.` };
    }
    for (const root of roots) installed[root] = target();
    return { ok: true, argv, error: null, stdout_tail: roots.map((root) => `installed gsd-path ${target()} at ${root}`).join("\n") };
  });
}

function update(body: { scope?: string; root?: string; dry_run?: boolean }) {
  if (body.scope !== "project") {
    if (body.dry_run) return { ok: true, argv: installer("--update", "--dry-run"), error: null, stdout_tail: "dry run, nothing written" };
    return slow(() => {
      for (const root of Object.keys(installed)) installed[root] = target();
      return { ok: true, argv: installer("--update"), error: null, stdout_tail: "updated" };
    });
  }
  const project = watched(body.root);
  const argv = installer("--runtime-upgrade", "--project", project.root, ...(body.dry_run ? ["--dry-run"] : []));
  if (body.dry_run) {
    return { ok: true, argv, error: null,
      stdout_tail: `dry run, nothing written\nwould update the runtime of ${project.root} (${project.runtime_version ?? "no stamp"} → ${releases.latest})\nwould keep the guard hooks` };
  }
  return slow(() => {
    project.runtime_version = releases.latest;
    return { ok: true, argv, error: null, stdout_tail: `runtime ${releases.latest} at ${project.root}` };
  });
}

function uninstall(body: { scope?: string; root?: string; hosts?: string[]; dry_run?: boolean; confirm?: boolean }) {
  if (!body.dry_run && !body.confirm) throw new Error("uninstall requires confirm=true (or dry_run=true to preview the plan)");
  if (body.scope === "project") {
    const project = watched(body.root), at = project.root;
    const plan = {
      plan: [
        ...(project.runtime ? [{ path: `${at}/.gsd-path/runtime.json`, kind: "file", reason: "managed runtime declaration; shared runtime versions are retained" }] : []),
        ...(project.hooks ? [{ path: `${at}/.gsd-path/guard_hook.py`, kind: "file", reason: "marker-matched guard script" },
          { path: `${at}/.git/hooks/pre-commit`, kind: "file", reason: "marker-matched gsd-path git hook" }] : []),
        ...(project.contracts ? [{ path: `${at}/AGENTS.md`, kind: "agents-block", reason: "remove the gsd-path block; owner text is kept" }] : []),
      ],
      skipped: project.contracts ? [{ path: `${at}/WORKFLOW.md`, reason: "user-modified, kept" }] : [],
    };
    if (body.dry_run) return { ok: true, plan };
    return slow(() => {
      Object.assign(project, { runtime: false, hooks: false, contracts: false, runtime_version: null });
      return { ok: true, applied: plan.plan.map((entry) => entry.path), errors: [], plan };
    });
  }
  const roots = [...new Set((body.hosts ?? HOSTS.map((host) => host[0])).map(rootOf))];
  const plan = {
    plan: roots.filter((root) => root in installed).map((root) => ({ path: root + "/gsd-path", kind: "dir", reason: "managed gsd-path skill directory" })),
    skipped: roots.filter((root) => !(root in installed)).map((root) => ({ path: root, reason: "skills root does not exist" })),
  };
  if (body.dry_run) return { ok: true, plan };
  return slow(() => {
    for (const root of roots) delete installed[root];
    return { ok: true, applied: plan.plan.map((entry) => entry.path), errors: [], plan };
  });
}

function watched(root: string | undefined): ProjectSetup {
  const project = projects.find((item) => item.root === root);
  if (!project) throw new Error("root is not a watched project");
  return project;
}

function projectOp(body: { root?: string; op?: string; dry_run?: boolean; member?: string }) {
  const project = watched(body.root), op = body.op ?? "", coordinator = project.root === "/work/gsd-path";
  if (busy) throw new Error("operation in progress");
  if (op === "members") {
    if (project.root === "/work/notes") {
      return { ok: false, members: [], error: "error: member field-notes-web: marker is missing or stale; run members.py repair --repo /work/notes" };
    }
    return { ok: true, members: coordinator ? members : [], error: null };
  }
  if (op === "doctor") {
    return slow(() => project.hooks
      ? { ok: true, argv: installer("--doctor"), error: null, stdout_tail: `note: claude: 14 skills at ${rootOf("claude")}\nnote: project: runtime ${project.runtime_version}\nnote: project: guard hooks current` }
      : { ok: false, argv: installer("--doctor"), stdout_tail: `note: project: runtime ${project.runtime_version}`,
        error: `project: guard hooks are not installed — run --hooks-init --project "${project.root}"` });
  }
  if (op === "member-repair") {
    if (body.dry_run) throw new Error("member repair has no preview; it rewrites only missing or stale markers");
    return slow(() => {
      for (const item of members) item.marker = { current: true, reason: null };
      return { ok: true, stdout_tail: '{"members": []}', error: null };
    });
  }
  const what = { "hooks-init": "add the guard hooks", "hooks-refresh": "refresh the guard hooks", "hooks-refresh-full": "refresh the guard hooks",
    "runtime-restore": "restore the runtime", "member-hooks": "install the member hooks" }[op];
  if (!what) throw new Error("op must be one of: hooks-init, hooks-refresh, hooks-refresh-full, runtime-restore, doctor, members, member-hooks, member-repair");
  const item = members.find((entry) => entry.checkout === body.member);
  if (op === "member-hooks" && (!coordinator || !item)) throw new Error("member is not a recorded member of this project");
  const where = item?.checkout ?? project.root;
  const argv = installer("--" + op, "--project", where, ...(body.dry_run ? ["--dry-run"] : []));
  if (body.dry_run) {
    return { ok: true, argv, error: null, stdout_tail: `dry run, nothing written\nwould ${what} in ${where}\nwould write .gsd-path/guard_hook.py, .gsd-path/git_guard.py and 3 Git hooks` };
  }
  return slow(() => {
    if (item) item.hooks = true;
    else if (op === "runtime-restore") project.runtime = true;
    else project.hooks = true;
    return { ok: true, argv, error: null, stdout_tail: `done: ${what} in ${where}` };
  });
}

type Body = {
  scope?: string; root?: string; hosts?: string[]; dry_run?: boolean; confirm?: boolean; op?: string; member?: string;
  version?: string | null; parents?: string[];
};

export function mockSkills(_method: string, url: URL, body: unknown): unknown {
  const data = (body ?? {}) as Body;
  switch (url.pathname) {
    case "/api/hosts":
      return { hosts: HOSTS.map(([id, name, found]) => ({ id, name, found, path: found ? "/usr/local/bin/" + id : null, skills_root: rootOf(id) })) };
    case "/api/plugin/status": return pluginStatus();
    case "/api/plugin/install": return install(data);
    case "/api/plugin/update": return update(data);
    case "/api/plugin/uninstall": return uninstall(data);
    case "/api/plugin/check": {
      const { latest, update_available } = pluginStatus();
      return slow(() => ({ ok: true, error: null, latest, update_available, installed: {} }));
    }
    case "/api/plugin/release": {
      const version = data.version ?? null;
      if (version && !releases.versions.includes(version)) throw new Error(`release ${version} is not published`);
      releases.selected = version;
      return releases;
    }
    case "/api/project/op": return projectOp(data);
    case "/api/frameworks/update": return updateFramework(data);
    // Watched folders, for the setup wizard. The Settings page owns the other keys of this route.
  }
  return undefined;
}
