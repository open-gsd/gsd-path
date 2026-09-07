#!/usr/bin/env node
// Install GSD Path skills for supported coding agents (Node port of install.py).
// Dependency-free; requires Node >= 18.17.

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath, pathToFileURL } from "node:url";

export const CLAUDE_BRIDGE = "@../AGENTS.md\n@../WORKFLOW.md\n";
export const HOOKS_DIRECTORY = ".gsd-path";
export const GUARD_SCRIPTS = ["guard_hook.py", "git_guard.py"];
export const GUARD_MARKER = "gsd-path guard";
export const PROJECT_RUNTIME_SCRIPTS = [
  "pipeline_state.py",
  "check_handoffs.py",
  "check_task_briefs.py",
  "isolation.py",
  "discussion_records.py",
  "pipeline_git.py",
  "archive_milestone.py",
  "review_panel.py",
  "_common.py",
  "state_checkpoint.py",
  "state_promote.py",
  "discussion_validate.py",
  "integration.py",
];
export const PROJECT_RUNTIME_MARKER = "gsd-path project runtime";
export const PROJECT_STATUS_LAUNCHER = "status_runtime.py";
export const PROJECT_STATUS_MARKER = "gsd-path project status launcher";
const INSTALL_LOCK_NAME = ".gsd-path-install-lock";
const INSTALL_LOCK_OWNER = "owner.json";
const INSTALL_LOCK_SCHEMA = "gsd-path/install-lock/v2";
const PROJECT_CONTRACTS = [
  ["AGENTS.md", "## Plain-prompt re-entry"],
  ["WORKFLOW.md", "### Plain-prompt re-entry"],
];
const STATUS_ACTIONS = new Set([
  "bind-initial",
  "block",
  "resume-checkpoint",
  "resume-next-handoff",
  "resume-promotion",
  "resume-shipment",
  "resume-undo",
  "run-phase",
  "validate-integrated",
  "wait",
]);
const STATUS_PHASES = new Set(["inspect", "define", "research", "decide", "roadmap", "plan", "build", "ship", "shipped"]);
const STATUS_VALUES = new Set(["active", "done", "blocked"]);
const STATUS_STATE_FIELDS = [
  "archive",
  "branch",
  "integration",
  "integration_default",
  "integration_source",
  "milestone",
  "phase",
  "pipeline",
  "project",
  "status",
];
const STATUS_INTEGRATION_MODES = new Set(["direct", "pull-request"]);
const STATUS_INTEGRATION_SOURCES = new Set(["default", "milestone"]);
const STATUS_TRANSITIONS = new Map([
  ["inspect", new Set(["inspect", "define"])],
  ["define", new Set(["define", "research", "plan"])],
  ["research", new Set(["research", "decide"])],
  ["decide", new Set(["decide", "roadmap", "plan"])],
  ["roadmap", new Set(["roadmap", "define"])],
  ["plan", new Set(["plan", "build"])],
  ["build", new Set(["build"])],
  ["ship", new Set(["ship", "plan"])],
  ["shipped", new Set(["ship"])],
]);
const STATUS_SLUG = /^[a-z0-9][a-z0-9-]*$/;
const STATUS_BRANCH = /^gsd-path\/M(\d{3,})$/;
const STATUS_ARCHIVE = /^\.project\/archive\/(\d{3,})-([a-z0-9][a-z0-9-]*)\/?$/;
export const CLAUDE_MATCHER = ".*";
// The managed PreToolUse guard entry, as an object.
export function claudeGuardEntry(interpreter) {
  return {
    matcher: CLAUDE_MATCHER,
    hooks: [
      {
        type: "command",
        command: `${interpreter} "$CLAUDE_PROJECT_DIR/${HOOKS_DIRECTORY}/guard_hook.py"`,
      },
    ],
  };
}
export function claudeHooksSettings(interpreter) {
  return (
    JSON.stringify({ hooks: { PreToolUse: [claudeGuardEntry(interpreter)] } }, null, 2) + "\n"
  );
}
function codexGuardCommand(interpreter) {
  return `${interpreter} "$(git rev-parse --show-toplevel)/${HOOKS_DIRECTORY}/guard_hook.py"`;
}

function codexGuardCommandWindows(interpreter) {
  return (
    "powershell.exe -NoProfile -NonInteractive -Command " +
    `"$root = git rev-parse --show-toplevel; & ${interpreter} ` +
    `(Join-Path $root '${HOOKS_DIRECTORY}\\guard_hook.py')"`
  );
}

function codexGuardEntry(interpreter) {
  return {
    matcher: ".*",
    hooks: [
      {
        type: "command",
        command: codexGuardCommand(interpreter),
        commandWindows: codexGuardCommandWindows(interpreter),
      },
    ],
  };
}

export function codexHooksSettings(interpreter) {
  return (
    JSON.stringify(
      {
        hooks: {
          PreToolUse: [codexGuardEntry(interpreter)],
        },
      },
      null,
      2
    ) + "\n"
  );
}

function cursorGuardEntry(interpreter) {
  return {
    command: `${interpreter} "${HOOKS_DIRECTORY}/guard_hook.py"`,
    matcher: ".*",
    failClosed: true,
  };
}

export function cursorHooksSettings(interpreter) {
  return (
    JSON.stringify(
      {
        version: 1,
        hooks: {
          preToolUse: [cursorGuardEntry(interpreter)],
        },
      },
      null,
      2
    ) + "\n"
  );
}
export function preCommitHook(interpreter) {
  return (
    "#!/bin/sh\n" +
    "# gsd-path guard: archive immutability before commit.\n" +
    `exec ${interpreter} "$(git rev-parse --show-toplevel)/${HOOKS_DIRECTORY}/git_guard.py" pre-commit\n`
  );
}
export function prePushHook(interpreter) {
  return (
    "#!/bin/sh\n" +
    "# gsd-path guard: bound branches publish only as ship commits.\n" +
    `exec ${interpreter} "$(git rev-parse --show-toplevel)/${HOOKS_DIRECTORY}/git_guard.py" pre-push "$@"\n`
  );
}

export function commitMsgHook(interpreter) {
  return (
    "#!/bin/sh\n" +
    "# gsd-path guard: archive immutability and ship-commit purity.\n" +
    `exec ${interpreter} "$(git rev-parse --show-toplevel)/${HOOKS_DIRECTORY}/git_guard.py" commit-msg "$1"\n`
  );
}

export const GIT_HOOKS = [
  ["pre-commit", preCommitHook],
  ["commit-msg", commitMsgHook],
  ["pre-push", prePushHook],
];
export const GIT_HOOK_NAMES = GIT_HOOKS.map(([name]) => name);

// Every interpreter a managed hook may legitimately be pinned to.
const INTERPRETER_CANDIDATES = ["python3", "python"];

// Probe for a runnable Python interpreter (python3, then python) so emitted
// hooks never hard-code an interpreter that does not exist on this machine
// (python3 is typically absent on Windows).
export function detectPythonInterpreter() {
  for (const candidate of INTERPRETER_CANDIDATES) {
    const result = spawnSync(
      candidate,
      ["-B", "-c", "import sys; raise SystemExit(sys.version_info < (3, 9))"],
      { stdio: "ignore" }
    );
    if (!result.error && result.status === 0) return candidate;
  }
  return null;
}

// Single owner of the interpreter probe and its policy. Hook installation
// fails before writing when no interpreter works.
function effectiveInterpreter() {
  return hooks.detectPythonInterpreter();
}

// Resolve the repository's effective hooks directory via
// `git rev-parse --git-path hooks`, which honors core.hooksPath and linked
// worktrees. Returns null when git cannot resolve it for this project.
export function resolveGitHooksPath(project) {
  const result = spawnSync(
    "git",
    ["rev-parse", "--show-toplevel", "--git-path", "hooks"],
    { cwd: project, encoding: "utf8" }
  );
  if (result.error || result.status !== 0) return null;
  const lines = result.stdout.split(/\r?\n/).filter((line) => line !== "");
  if (lines.length !== 2) return null;
  const [toplevel, hooksPath] = lines;
  if (!samePath(toplevel, project)) return null;
  return path.resolve(project, hooksPath);
}

function gitHooksDirectory(project) {
  return gitHooksLocation(project).directory;
}

function gitHooksLocation(project) {
  const dotGit = path.join(project, ".git");
  if (!lexists(dotGit)) return { directory: null, resolved: false };
  const resolved = hooks.resolveGitHooksPath(project);
  if (resolved !== null) return { directory: resolved, resolved: true };
  // Fallback when git is not runnable: only a plain .git directory is safe.
  return {
    directory: isDirectory(dotGit) ? path.join(dotGit, "hooks") : null,
    resolved: false,
  };
}

function requiredPythonRuntime(command, selected = []) {
  const targetSuffix = selected.length ? ` for selected hosts: ${selected.join(", ")}` : "";
  const interpreter = effectiveInterpreter();
  if (interpreter === null) {
    throw new InstallerError(
      `${command} requires a working Python interpreter${targetSuffix}`
    );
  }
  return interpreter;
}

function requiredHookRuntime(project, command, selected = []) {
  const targetSuffix = selected.length ? ` for selected hosts: ${selected.join(", ")}` : "";
  const interpreter = requiredPythonRuntime(command, selected);
  const location = gitHooksLocation(project);
  if (!location.resolved) {
    throw new InstallerError(
      `${command} requires an initialized Git repository with a resolvable hooks ` +
        `directory${targetSuffix}`
    );
  }
  return { interpreter, hooksDir: location.directory };
}
const HOST_NOTES = {
  opencode:
    "note: OpenCode stable discovers the skills but has no documented hard " +
    'explicit-only switch; OpenCode v2 honors opencode/autoinvoke="false" ' +
    "and /gsd-path.",
  antigravity:
    "note: Antigravity discovers /gsd-path but has no documented hard " +
    "explicit-only skill switch; invoke the skill explicitly.",
  kiro:
    "note: Kiro discovers /gsd-path but has no documented hard explicit-only " +
    "skill switch; invoke the skill explicitly.",
};
export const EXPLICIT_ONLY_TARGETS = new Set([
  "claude",
  "grok",
  "copilot",
  "qwen",
  "cursor",
  "zed",
  "kimi",
  "shared-agents",
]);
const SHARED_AGENT_TARGETS = new Set(["codex", "antigravity", "zed"]);
export const SHARED_AGENT_PROFILE = "shared-agents";
export const CURSOR_AGENT_FILENAME = "gsd-path.md";
export const CURSOR_AGENT_BACKUP_NAME = "cursor-agent-gsd-path.md";

const SCRIPT_DIRECTORY = path.dirname(fileURLToPath(import.meta.url));

// Single source of truth for the resource tables, shared with
// sync_skill_resources.py and shipped in the npm package.
const MANIFEST = JSON.parse(
  fs.readFileSync(path.join(SCRIPT_DIRECTORY, "skill-resources.json"), "utf8")
);

function sharedInvocations(text) {
  const pattern = /(`?)(\$gsd-path(?:-[a-z0-9]+)*|\$path)( status)?\1(?: \(Codex\) (?:and|or) (`?)\/(gsd-path(?:-[a-z0-9]+)*|path)( status)?\4 \((?:other hosts|Antigravity\/Zed)\))?/g;
  return text.replace(pattern, (_match, quote, token, arguments_, pairedQuote, pairedSkill, pairedArguments) => {
    const skill = token.slice(1);
    const argumentsText = arguments_ || "";
    if (pairedSkill && (pairedSkill !== skill || (pairedArguments || "") !== argumentsText || pairedQuote !== quote)) {
      throw new InstallerError("shared invocation pair is inconsistent");
    }
    const codex = `${MANIFEST.hosts.codex.invocation_prefix}${skill}`;
    const others = `${MANIFEST.hosts.antigravity.invocation_prefix}${skill}`;
    return `${quote}${codex}${argumentsText}${quote} (Codex) or ${quote}${others}${argumentsText}${quote} (Antigravity/Zed)`;
  });
}
export function skillNamesForManifest(manifest) {
  return [...manifest.skills];
}

export function targetsForManifest(manifest) {
  return Object.keys(manifest.hosts);
}

export function localRootsForManifest(manifest) {
  return Object.fromEntries(
    Object.entries(manifest.hosts).map(([target, config]) => [target, config.local_root])
  );
}

export const TARGETS = targetsForManifest(MANIFEST);
export const LOCAL_ROOTS = localRootsForManifest(MANIFEST);
export const SKILL_NAMES = skillNamesForManifest(MANIFEST);
export const SKILL_ALIASES = { ...MANIFEST.skill_aliases };
export const ROUTER_ALIASES = { ...MANIFEST.router_aliases };
const PHASE_RESOURCES = MANIFEST.phase_resources;
const SCRIPT_TARGETS = MANIFEST.script_targets;
const PHASE_CONTRACT_TARGETS = MANIFEST.phase_contract_targets;
const SHARED_DISPATCH_TARGETS = MANIFEST.shared_dispatch_targets;

export class InstallerError extends Error {}

const tick = () => new Promise((resolve) => setImmediate(resolve));

const messageOf = (error) => String(error && error.message ? error.message : error);

function readPackageVersion(manifest) {
  try {
    const version = JSON.parse(fs.readFileSync(manifest, "utf8")).version;
    return typeof version === "string" && version ? version : null;
  } catch {
    return null;
  }
}

export function targetPlan(name, root) {
  return { name, root };
}

function lexists(candidate) {
  try {
    fs.lstatSync(candidate);
    return true;
  } catch {
    return false;
  }
}

function isSymlink(candidate) {
  try {
    return fs.lstatSync(candidate).isSymbolicLink();
  } catch {
    return false;
  }
}

function isDirectory(candidate) {
  try {
    return fs.statSync(candidate).isDirectory();
  } catch {
    return false;
  }
}

function isFile(candidate) {
  try {
    return fs.statSync(candidate).isFile();
  } catch {
    return false;
  }
}

function expandUser(value) {
  if (value === "~") return os.homedir();
  if (value.startsWith("~/") || value.startsWith("~\\")) {
    return path.join(os.homedir(), value.slice(2));
  }
  return value;
}

function absolutePath(value) {
  return path.resolve(expandUser(String(value)));
}

export function defaultRoot(target, env = process.env) {
  if (target === "codex") return absolutePath("~/.agents/skills");
  if (target === "claude") {
    return absolutePath(path.join(env.CLAUDE_CONFIG_DIR || expandUser("~/.claude"), "skills"));
  }
  if (target === "grok") {
    return absolutePath(path.join(env.GROK_HOME || expandUser("~/.grok"), "skills"));
  }
  if (target === "opencode") {
    let base;
    if (env.OPENCODE_CONFIG_DIR) {
      base = env.OPENCODE_CONFIG_DIR;
    } else if (env.OPENCODE_CONFIG) {
      base = path.dirname(absolutePath(env.OPENCODE_CONFIG));
    } else {
      base = path.join(env.XDG_CONFIG_HOME || expandUser("~/.config"), "opencode");
    }
    return absolutePath(path.join(base, "skills"));
  }
  if (target === "copilot") {
    return absolutePath(path.join(env.COPILOT_HOME || expandUser("~/.copilot"), "skills"));
  }
  if (target === "qwen") {
    return absolutePath(path.join(env.QWEN_HOME || expandUser("~/.qwen"), "skills"));
  }
  if (target === "antigravity") return absolutePath("~/.gemini/antigravity-cli/skills");
  if (target === "cursor") return absolutePath("~/.cursor/skills");
  if (target === "zed") return absolutePath("~/.agents/skills");
  if (target === "kiro") {
    return absolutePath(path.join(env.KIRO_HOME || expandUser("~/.kiro"), "skills"));
  }
  if (target === "kimi") {
    return absolutePath(path.join(env.KIMI_CODE_HOME || expandUser("~/.kimi-code"), "skills"));
  }
  throw new Error(`unsupported target: ${target}`);
}

export function legacyCodexRoot(env = process.env) {
  return absolutePath(path.join(env.CODEX_HOME || expandUser("~/.codex"), "skills"));
}

function isManagedName(name) {
  const normalized = name.toLowerCase();
  return (
    normalized === "ogsd" ||
    normalized === "gsd-path" ||
    Object.hasOwn(ROUTER_ALIASES, normalized) ||
    normalized.startsWith("ogsd-") ||
    normalized.startsWith("gsd-path-")
  );
}

function isOwnedRouterAlias(skillDir) {
  return isFile(path.join(skillDir, "scripts", "pipeline_state.py"));
}

function isManagedInstallEntry(root, name) {
  if (!isManagedName(name)) return false;
  if (!Object.hasOwn(ROUTER_ALIASES, name.toLowerCase())) return true;
  return isOwnedRouterAlias(path.join(root, name));
}

function rejectRouterAliasCollisions(root) {
  if (!isDirectory(root)) return;
  for (const alias of Object.keys(ROUTER_ALIASES)) {
    const candidate = path.join(root, alias);
    if (!lexists(candidate)) continue;
    if (isOwnedRouterAlias(candidate)) continue;
    throw new InstallerError(
      `refusing to replace unrelated skill ${candidate}; rename it or move it aside before installing GSD Path`
    );
  }
}

function stampInstalledVersions(stagedRoot, version) {
  if (!version) return;
  const names = new Set(["gsd-path", ...Object.keys(ROUTER_ALIASES)]);
  for (const name of names) {
    fs.writeFileSync(path.join(stagedRoot, name, "VERSION"), `${version}\n`);
  }
}

function rewriteRouterAliasSkill(text, alias, canonical) {
  if (!text.startsWith("---\n")) {
    throw new InstallerError("SKILL.md is missing YAML frontmatter");
  }
  const end = text.indexOf("\n---\n", 4);
  if (end === -1) {
    throw new InstallerError("SKILL.md has unterminated YAML frontmatter");
  }
  const header = text.slice(4, end);
  const rest = text.slice(end);
  const expected = `name: ${canonical}`;
  const replacement = `name: ${alias}`;
  const lines = header.split("\n");
  if (!lines.includes(expected)) {
    throw new InstallerError(`router alias ${alias} is missing ${expected}`);
  }
  const rewritten = lines.map((line) => (line === expected ? replacement : line));
  if (rewritten.filter((line) => line === replacement).length !== 1) {
    throw new InstallerError(`router alias ${alias} name rewrite was not unique`);
  }
  const invoke = `invokes $${canonical}.`;
  const invokeWithAlias = `invokes $${alias} or $${canonical}.`;
  let headerText = rewritten.join("\n");
  if (!headerText.includes(invoke)) {
    throw new InstallerError(`router alias ${alias} is missing ${invoke}`);
  }
  headerText = headerText.replace(invoke, invokeWithAlias);
  return `---\n${headerText}${rest}`;
}

function materializedResourceBytes(source, destination) {
  const data = fs.readFileSync(source);
  if (path.basename(destination) !== "SKILL.md") return data;
  const alias = path.basename(path.dirname(destination));
  const canonical = ROUTER_ALIASES[alias];
  if (!canonical) return data;
  return Buffer.from(rewriteRouterAliasSkill(data.toString("utf8"), alias, canonical));
}

function resolveNonStrict(value) {
  let prefix = path.resolve(value);
  const suffix = [];
  for (;;) {
    try {
      return path.join(fs.realpathSync(prefix), ...suffix);
    } catch {
      const parent = path.dirname(prefix);
      if (parent === prefix) return path.join(prefix, ...suffix);
      suffix.unshift(path.basename(prefix));
      prefix = parent;
    }
  }
}

function comparisonPath(value) {
  const resolved = resolveNonStrict(value);
  if (process.platform === "darwin" || process.platform === "win32") {
    return resolved.toLowerCase();
  }
  return resolved;
}

function isAncestor(ancestor, descendant) {
  const relative = path.relative(ancestor, descendant);
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
}

function pathsOverlap(left, right) {
  const a = comparisonPath(left);
  const b = comparisonPath(right);
  return a === b || isAncestor(a, b) || isAncestor(b, a);
}

function samePath(left, right) {
  return comparisonPath(left) === comparisonPath(right);
}

function validateProjectGitRoot(project) {
  let probe = project;
  while (!lexists(probe)) probe = path.dirname(probe);
  const result = spawnSync("git", ["rev-parse", "--show-toplevel"], {
    cwd: probe,
    encoding: "utf8",
    env: { ...process.env, GIT_OPTIONAL_LOCKS: "0" },
  });
  const topLevel = result.status === 0 ? result.stdout.trim() : "";
  if (topLevel && !samePath(topLevel, project)) {
    throw new InstallerError(`project path is not the Git worktree root: ${project}`);
  }
}

function validateDirectoryDestination(candidate, label) {
  if (lexists(candidate)) {
    if (isSymlink(candidate)) throw new InstallerError(`${label} is a symlink: ${candidate}`);
    if (!isDirectory(candidate)) throw new InstallerError(`${label} is not a directory: ${candidate}`);
    return;
  }
  let parent = path.dirname(candidate);
  while (!lexists(parent)) parent = path.dirname(parent);
  if (isSymlink(parent) || !isDirectory(parent)) {
    throw new InstallerError(`${label} has an unsafe parent: ${parent}`);
  }
}

function walk(directory, visit) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.name === ".git" || entry.name === "node_modules") continue;
    const candidate = path.join(directory, entry.name);
    visit(candidate, entry);
    if (entry.isDirectory() && !entry.isSymbolicLink()) walk(candidate, visit);
  }
}

function rejectSourceSymlinks(root) {
  walk(root, (candidate, entry) => {
    if (entry.isSymbolicLink()) {
      throw new InstallerError(`source contains a symlink: ${candidate}`);
    }
  });
}

export function mismatches(root) {
  const problems = [];
  const pairs = [];
  const expectedSkills = [
    "gsd-path",
    ...[
      ...Object.keys(PHASE_RESOURCES),
      ...Object.keys(SKILL_ALIASES),
      ...Object.keys(ROUTER_ALIASES),
    ].sort(),
  ];
  if (JSON.stringify(SKILL_NAMES) !== JSON.stringify(expectedSkills)) {
    problems.push("manifest skills must be root gsd-path plus every canonical skill and alias");
  }
  for (const [legacy, canonicalSkill] of Object.entries(SKILL_ALIASES)) {
    if (Object.hasOwn(PHASE_RESOURCES, legacy)) {
      problems.push("skill aliases cannot also own phase resources");
    }
    if (!Object.hasOwn(PHASE_RESOURCES, canonicalSkill)) {
      problems.push(`skill alias target is not canonical: ${legacy} -> ${canonicalSkill}`);
    }
  }
  for (const [alias, canonicalSkill] of Object.entries(ROUTER_ALIASES)) {
    if (Object.hasOwn(PHASE_RESOURCES, alias)) {
      problems.push("router aliases cannot also own phase resources");
    }
    if (Object.hasOwn(SKILL_ALIASES, alias)) {
      problems.push("router aliases cannot also be skill aliases");
    }
    if (canonicalSkill !== "gsd-path") {
      problems.push(`router alias target is not the router: ${alias} -> ${canonicalSkill}`);
    }
  }
  for (const [source, destination] of SHARED_DISPATCH_TARGETS) {
    pairs.push([path.join(root, source), path.join(root, destination)]);
  }
  const canonical = path.join(root, "skills", "gsd-path");
  for (const [skill, resources] of Object.entries(PHASE_RESOURCES)) {
    for (const relative of resources) {
      pairs.push([path.join(canonical, relative), path.join(root, "skills", skill, relative)]);
    }
  }
  for (const [source, destination] of [...SCRIPT_TARGETS, ...PHASE_CONTRACT_TARGETS]) {
    pairs.push([path.join(root, source), path.join(root, destination)]);
  }
  for (const [legacy, canonicalSkill] of Object.entries(SKILL_ALIASES)) {
    const legacyDirectory = path.join(root, "skills", legacy);
    pairs.push([
      path.join(root, "skills", canonicalSkill, "SKILL.md"),
      path.join(legacyDirectory, "CANONICAL.md"),
    ]);
    for (const relative of PHASE_RESOURCES[canonicalSkill] || []) {
      pairs.push([path.join(canonical, relative), path.join(legacyDirectory, relative)]);
    }
    const canonicalPrefix = `skills/${canonicalSkill}/`;
    for (const [source, destination] of SCRIPT_TARGETS) {
      if (destination.startsWith(canonicalPrefix)) {
        pairs.push([
          path.join(root, source),
          path.join(legacyDirectory, destination.slice(canonicalPrefix.length)),
        ]);
      }
    }
  }
  for (const [alias, canonicalSkill] of Object.entries(ROUTER_ALIASES)) {
    const canonicalDirectory = path.join(root, "skills", canonicalSkill);
    const aliasDirectory = path.join(root, "skills", alias);
    walk(canonicalDirectory, (candidate, entry) => {
      if (!entry.isFile() || path.basename(candidate) === ".DS_Store") return;
      pairs.push([candidate, path.join(aliasDirectory, path.relative(canonicalDirectory, candidate))]);
    });
  }
  for (const [source, destination] of pairs) {
    if (!isFile(source)) {
      problems.push(`missing canonical resource: ${path.relative(root, source)}`);
    } else if (!isFile(destination)) {
      problems.push(`missing generated resource: ${path.relative(root, destination)}`);
    } else {
      try {
        if (!materializedResourceBytes(source, destination).equals(fs.readFileSync(destination))) {
          problems.push(`stale generated resource: ${path.relative(root, destination)}`);
        }
      } catch (error) {
        problems.push(messageOf(error));
      }
    }
  }
  walk(root, (candidate, entry) => {
    if (entry.name === ".DS_Store") {
      problems.push(`unexpected package metadata: ${path.relative(root, candidate)}`);
    }
  });
  return problems;
}

function validateSource(sourceRoot, profiles) {
  const problems = hooks.mismatches(sourceRoot);
  if (problems.length) {
    throw new InstallerError("source resources are stale: " + problems.join("; "));
  }

  const skillsRoot = path.join(sourceRoot, "skills");
  if (!isDirectory(skillsRoot) || isSymlink(skillsRoot)) {
    throw new InstallerError(`missing safe skills directory: ${skillsRoot}`);
  }
  const found = fs
    .readdirSync(skillsRoot)
    .filter(
      (name) =>
        isManagedName(name) &&
        (name.startsWith("gsd-path") || Object.hasOwn(ROUTER_ALIASES, name))
    );
  const expected = new Set(SKILL_NAMES);
  if (found.length !== expected.size || !found.every((name) => expected.has(name))) {
    throw new InstallerError(
      `expected exactly ${SKILL_NAMES.length} GSD Path skills; found ` +
        [...found].sort().join(", ")
    );
  }
  for (const name of SKILL_NAMES) {
    const skill = path.join(skillsRoot, name);
    if (isSymlink(skill) || !isDirectory(skill) || !isFile(path.join(skill, "SKILL.md"))) {
      throw new InstallerError(`invalid skill directory: ${skill}`);
    }
    rejectSourceSymlinks(skill);
  }

  for (const profile of profiles) {
    const adapter = path.join(sourceRoot, "platforms", profile, "dispatch.md");
    if (isSymlink(adapter) || !isFile(adapter)) {
      throw new InstallerError(`missing dispatch adapter: ${adapter}`);
    }
    if (profile === "cursor") {
      const agent = path.join(sourceRoot, "platforms", "cursor", "agent.md");
      if (isSymlink(agent) || !isFile(agent)) {
        throw new InstallerError(`missing Cursor subagent: ${agent}`);
      }
    }
  }
  return SKILL_NAMES;
}

function splitLines(text) {
  const lines = text.split(/\r\n|\r|\n/);
  if (lines.length && lines[lines.length - 1] === "" && /[\n\r]$/.test(text)) {
    lines.pop();
  }
  return lines;
}

function augmentFrontmatter(text, target) {
  const lines = splitLines(text);
  if (!lines.length || lines[0] !== "---") {
    throw new InstallerError("SKILL.md is missing YAML frontmatter");
  }
  const end = lines.indexOf("---", 1);
  if (end === -1) {
    throw new InstallerError("SKILL.md has unterminated YAML frontmatter");
  }
  const header = lines.slice(1, end);

  if (EXPLICIT_ONLY_TARGETS.has(target)) {
    const key = "disable-model-invocation:";
    const replacement = "disable-model-invocation: true";
    const index = header.findIndex((line) => line.startsWith(key));
    if (index === -1) header.push(replacement);
    else header[index] = replacement;
  }
  if (target === "opencode" || target === SHARED_AGENT_PROFILE) {
    const metadata = header.indexOf("metadata:");
    if (metadata === -1) {
      header.push("metadata:", '  opencode/autoinvoke: "false"', '  opencode/slash: "true"');
    } else {
      let sectionEnd = metadata + 1;
      while (
        sectionEnd < header.length &&
        (header[sectionEnd] === "" || /^\s/.test(header[sectionEnd]))
      ) {
        sectionEnd += 1;
      }
      const values = [
        ["opencode/autoinvoke:", '  opencode/autoinvoke: "false"'],
        ["opencode/slash:", '  opencode/slash: "true"'],
      ];
      for (const [key, replacement] of values) {
        let replaced = false;
        for (let index = metadata + 1; index < sectionEnd; index += 1) {
          if (header[index].trim().startsWith(key)) {
            header[index] = replacement;
            replaced = true;
            break;
          }
        }
        if (!replaced) {
          header.splice(sectionEnd, 0, replacement);
          sectionEnd += 1;
        }
      }
    }
  }

  const transformed = ["---", ...header, "---", ...lines.slice(end + 1)];
  return transformed.join("\n") + (/[\n\r]$/.test(text) ? "\n" : "");
}

function markdownFiles(root) {
  const files = [];
  walk(root, (candidate, entry) => {
    if (entry.isFile() && candidate.endsWith(".md")) files.push(candidate);
  });
  return files.sort();
}

export function stageTarget(sourceRoot, target, stagedRoot) {
  const skillsRoot = path.join(sourceRoot, "skills");
  for (const name of SKILL_NAMES) {
    fs.cpSync(path.join(skillsRoot, name), path.join(stagedRoot, name), { recursive: true });
  }

  stampInstalledVersions(stagedRoot, readPackageVersion(path.join(sourceRoot, "package.json")));

  const adapter = fs.readFileSync(path.join(sourceRoot, "platforms", target, "dispatch.md"), "utf8");
  for (const name of SKILL_NAMES) {
    const dispatch = path.join(stagedRoot, name, "references", "dispatch.md");
    if (isFile(dispatch)) fs.writeFileSync(dispatch, adapter);
  }
  if (target === "cursor") {
    fs.copyFileSync(
      path.join(sourceRoot, "platforms", "cursor", "agent.md"),
      path.join(stagedRoot, CURSOR_AGENT_FILENAME)
    );
  }

  if (target !== "codex") {
    if (target !== SHARED_AGENT_PROFILE) {
      for (const name of SKILL_NAMES) {
        const metadata = path.join(stagedRoot, name, "agents");
        if (isDirectory(metadata)) fs.rmSync(metadata, { recursive: true });
      }
    }
    const invocation = target === "opencode" ? "gsd-path" : "/gsd-path";
    const pathInvocation = target === "opencode" ? "path" : "/path";
    for (const name of SKILL_NAMES) {
      const entrypoint = path.join(stagedRoot, name, "SKILL.md");
      fs.writeFileSync(entrypoint, augmentFrontmatter(fs.readFileSync(entrypoint, "utf8"), target));
    }
    for (const markdown of markdownFiles(stagedRoot)) {
      const content = fs.readFileSync(markdown, "utf8");
      fs.writeFileSync(
        markdown,
        target === SHARED_AGENT_PROFILE
          ? sharedInvocations(content)
          : content.replaceAll("$gsd-path", invocation).replaceAll("$path", pathInvocation)
      );
    }
  }
}

function missingDirectories(candidate) {
  const missing = [];
  let cursor = candidate;
  while (!lexists(cursor)) {
    missing.push(cursor);
    cursor = path.dirname(cursor);
  }
  return missing.reverse();
}

function createDirectory(candidate, created) {
  created.push(...missingDirectories(candidate));
  fs.mkdirSync(candidate, { recursive: true });
}

function releaseInstallLocks(locks, createdDirectories) {
  for (const lock of [...locks].reverse()) {
    fs.rmSync(path.join(lock, INSTALL_LOCK_OWNER), { force: true });
    fs.rmdirSync(lock);
  }
  removeEmptyDirectories(createdDirectories);
}

function processIdentity(pid) {
  const windows = process.platform === "win32";
  const command = windows
    ? [
        "powershell.exe",
        [
          "-NoProfile",
          "-NonInteractive",
          "-Command",
          `(Get-Process -Id ${pid} -ErrorAction Stop).StartTime.ToUniversalTime().Ticks`,
        ],
      ]
    : ["ps", ["-o", "lstart=", "-p", String(pid)]];
  const result = spawnSync(command[0], command[1], { encoding: "utf8", windowsHide: true });
  const value = result.status === 0 ? result.stdout.trim() : "";
  return value ? `${windows ? "nt" : "posix"}:${value}` : null;
}

function processAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code !== "ESRCH";
  }
}

function staleInstallLockSnapshot(lock) {
  if (isSymlink(lock) || !isDirectory(lock)) {
    throw new InstallerError(`unsafe installation lock: ${lock}`);
  }
  let entries;
  let observed;
  let ownerBytes;
  let owner;
  try {
    observed = fs.statSync(lock);
    entries = fs.readdirSync(lock);
    ownerBytes = fs.readFileSync(path.join(lock, INSTALL_LOCK_OWNER));
    owner = JSON.parse(ownerBytes.toString("utf8"));
  } catch {
    throw new InstallerError(`installation already in progress for ${path.dirname(lock)}`);
  }
  const valid =
    owner.schema === INSTALL_LOCK_SCHEMA &&
    Number.isInteger(owner.pid) &&
    owner.pid > 0 &&
    typeof owner.identity === "string" &&
    owner.identity &&
    entries.length === 1 &&
    entries[0] === INSTALL_LOCK_OWNER;
  const currentIdentity = valid ? processIdentity(owner.pid) : null;
  if (
    !valid ||
    currentIdentity === owner.identity ||
    (currentIdentity === null && processAlive(owner.pid))
  ) {
    throw new InstallerError(`installation already in progress for ${path.dirname(lock)}`);
  }
  return { observed, ownerBytes };
}

function recoverStaleInstallLock(lock, quarantine) {
  const legacyQuarantine = `${lock}.stale`;
  if (!lexists(lock)) {
    const prefix = `${path.basename(lock)}.stale-`;
    for (const name of fs.readdirSync(path.dirname(lock))) {
      if (!name.startsWith(prefix)) continue;
      const orphan = path.join(path.dirname(lock), name);
      const staging = path.join(path.dirname(lock), name.slice(prefix.length));
      try {
        staleInstallLockSnapshot(orphan);
        if (lexists(staging)) staleInstallLockSnapshot(staging);
      } catch {
        continue;
      }
      if (lexists(staging)) fs.rmSync(staging, { recursive: true });
      fs.rmSync(orphan, { recursive: true });
    }
    if (lexists(legacyQuarantine)) {
      staleInstallLockSnapshot(legacyQuarantine);
      fs.rmSync(legacyQuarantine, { recursive: true });
    }
    return null;
  }
  const { observed, ownerBytes } = staleInstallLockSnapshot(lock);
  if (lexists(legacyQuarantine)) {
    staleInstallLockSnapshot(legacyQuarantine);
    fs.rmSync(legacyQuarantine, { recursive: true });
  }
  try {
    hooks.renameInstallLock(lock, quarantine);
  } catch (error) {
    if (error.code !== "ENOENT" && !lexists(quarantine)) throw error;
    throw new InstallerError(`installation already in progress for ${path.dirname(lock)}`);
  }
  let moved;
  let movedOwner;
  try {
    moved = fs.statSync(quarantine);
    movedOwner = fs.readFileSync(path.join(quarantine, INSTALL_LOCK_OWNER));
  } catch {
    throw new InstallerError(`installation already in progress for ${path.dirname(lock)}`);
  }
  if (
    moved.dev !== observed.dev ||
    moved.ino !== observed.ino ||
    !movedOwner.equals(ownerBytes)
  ) {
    if (!lexists(lock)) fs.renameSync(quarantine, lock);
    throw new InstallerError(`installation already in progress for ${path.dirname(lock)}`);
  }
  return quarantine;
}

function createInstallLock(lock) {
  const identity = processIdentity(process.pid);
  if (identity === null) throw new InstallerError("cannot determine installer process identity");
  const staging = fs.mkdtempSync(path.join(path.dirname(lock), ".install-lock-stage-"));
  const recovery = `${lock}.stale-${path.basename(staging)}`;
  let quarantine = null;
  let published = false;
  try {
    fs.writeFileSync(
      path.join(staging, INSTALL_LOCK_OWNER),
      JSON.stringify({ schema: INSTALL_LOCK_SCHEMA, pid: process.pid, identity }) + "\n",
      { flag: "wx" }
    );
    quarantine = recoverStaleInstallLock(lock, recovery);
    hooks.renameInstallStage(staging, lock);
    published = true;
    if (quarantine !== null) fs.rmSync(quarantine, { recursive: true });
  } catch (error) {
    fs.rmSync(staging, { recursive: true, force: true });
    if (quarantine !== null && lexists(quarantine)) {
      if (published && lexists(lock)) fs.rmSync(lock, { recursive: true });
      if (!lexists(lock)) fs.renameSync(quarantine, lock);
      else fs.rmSync(quarantine, { recursive: true });
    }
    if (lexists(lock)) {
      throw new InstallerError(`installation already in progress for ${path.dirname(lock)}`);
    }
    throw error;
  }
}

function acquireInstallLocks(roots) {
  const locks = [];
  for (const root of roots) {
    const candidate = path.join(path.dirname(root), INSTALL_LOCK_NAME);
    if (!locks.some((lock) => samePath(lock, candidate))) locks.push(candidate);
  }
  locks.sort();
  const acquired = [];
  const createdDirectories = [];
  try {
    for (const lock of locks) {
      createDirectory(path.dirname(lock), createdDirectories);
      createInstallLock(lock);
      acquired.push(lock);
    }
  } catch (error) {
    releaseInstallLocks(acquired, createdDirectories);
    throw error;
  }
  return { locks: acquired, createdDirectories };
}

function backupPath(root, reserved = []) {
  let candidate = path.join(path.dirname(root), "disabled-gsd-skills");
  let number = 1;
  while (lexists(candidate) || reserved.some((entry) => samePath(candidate, entry))) {
    candidate = path.join(path.dirname(root), `disabled-gsd-skills-${number}`);
    number += 1;
  }
  return candidate;
}

function backupExisting(transaction, extras = []) {
  const existing = fs
    .readdirSync(transaction.root)
    .filter((name) => isManagedInstallEntry(transaction.root, name))
    .sort()
    .map((name) => [path.join(transaction.root, name), name]);
  for (const [candidate, backupName] of extras) {
    if (lexists(candidate)) existing.push([candidate, backupName]);
  }
  if (existing.length) {
    transaction.backup = backupPath(transaction.root);
    fs.mkdirSync(transaction.backup);
    for (const [entry, backupName] of existing) {
      const stored = path.join(transaction.backup, backupName);
      transaction.moved.push([entry, stored]);
      hooks.rename(entry, stored);
    }
  }
}

async function applyTarget(plan, stagedRoot, transaction) {
  createDirectory(plan.root, transaction.createdDirectories);
  rejectRouterAliasCollisions(plan.root);
  const extras = [];
  let cursorAgent = null;
  if (plan.profile === "cursor") {
    cursorAgent = path.join(path.dirname(plan.root), "agents", CURSOR_AGENT_FILENAME);
    createDirectory(path.dirname(cursorAgent), transaction.createdDirectories);
    extras.push([cursorAgent, CURSOR_AGENT_BACKUP_NAME]);
  }
  backupExisting(transaction, extras);
  for (const name of SKILL_NAMES) {
    const destination = path.join(plan.root, name);
    hooks.reserveDirectory(destination);
    transaction.installed.push(destination);
    fs.cpSync(path.join(stagedRoot, name), destination, { recursive: true, errorOnExist: true, force: false });
    await tick();
  }
  if (cursorAgent !== null) {
    hooks.reserveFile(cursorAgent);
    transaction.installed.push(cursorAgent);
    fs.copyFileSync(path.join(stagedRoot, CURSOR_AGENT_FILENAME), cursorAgent);
  }
}

function reserveDirectory(destination) {
  fs.mkdirSync(destination);
}

function reserveFile(destination) {
  const descriptor = fs.openSync(destination, "wx", 0o644);
  try {
    fs.closeSync(descriptor);
  } catch (error) {
    fs.rmSync(destination, { force: true });
    throw error;
  }
}

function removePath(candidate) {
  if (!lexists(candidate)) return;
  if (isSymlink(candidate) || !isDirectory(candidate)) fs.unlinkSync(candidate);
  else fs.rmSync(candidate, { recursive: true });
}

function removeEmptyDirectories(paths) {
  for (const candidate of [...paths].reverse()) {
    try {
      fs.rmdirSync(candidate);
    } catch {
      // Not empty or already gone; leave it.
    }
  }
}

function rollbackTarget(transaction) {
  for (const destination of [...transaction.installed].reverse()) {
    removePath(destination);
  }
  for (const [original, stored] of [...transaction.moved].reverse()) {
    if (lexists(stored)) fs.renameSync(stored, original);
  }
  if (transaction.backup !== null) {
    try {
      fs.rmdirSync(transaction.backup);
    } catch {
      // Leave a non-empty backup in place.
    }
  }
  removeEmptyDirectories(transaction.createdDirectories);
}

// Each entry: [destination, sourceName, literalContent, executable].
// hooksDir is the pre-resolved git hooks directory (or null); resolving it
// once per run avoids repeated `git rev-parse` spawns.
function projectDestinations(project, selected, hooksEnabled, interpreter, hooksDir) {
  const includeClaude = selected.includes("claude");
  const destinations = [
    [path.join(project, "AGENTS.md"), "AGENTS.md", null, false],
    [path.join(project, "WORKFLOW.md"), "WORKFLOW.md", null, false],
    [
      path.join(project, HOOKS_DIRECTORY, PROJECT_STATUS_LAUNCHER),
      path.join("scripts", PROJECT_STATUS_LAUNCHER),
      null,
      false,
    ],
  ];
  for (const name of PROJECT_RUNTIME_SCRIPTS) {
    destinations.push([
      path.join(project, HOOKS_DIRECTORY, "runtime", name),
      path.join("scripts", name),
      null,
      false,
    ]);
  }
  if (includeClaude) {
    destinations.push([path.join(project, ".claude", "CLAUDE.md"), null, CLAUDE_BRIDGE, false]);
  }
  if (hooksEnabled) {
    for (const name of GUARD_SCRIPTS) {
      destinations.push([
        path.join(project, HOOKS_DIRECTORY, name),
        path.join("scripts", name),
        null,
        false,
      ]);
    }
    if (includeClaude) {
      destinations.push([
        path.join(project, ".claude", "settings.json"),
        null,
        claudeHooksSettings(interpreter),
        false,
      ]);
    }
    if (selected.includes("codex")) {
      destinations.push([
        path.join(project, ".codex", "hooks.json"),
        null,
        codexHooksSettings(interpreter),
        false,
      ]);
    }
    if (selected.includes("cursor")) {
      destinations.push([
        path.join(project, ".cursor", "hooks.json"),
        null,
        cursorHooksSettings(interpreter),
        false,
      ]);
    }
    if (hooksDir !== null) {
      for (const [hookName, generator] of GIT_HOOKS) {
        destinations.push([path.join(hooksDir, hookName), null, generator(interpreter), true]);
      }
    }
  }
  return destinations;
}

function nativeSettingsMergers(project, selected, hooksEnabled) {
  const mergers = new Map();
  if (!hooksEnabled) return mergers;
  if (selected.includes("claude")) {
    mergers.set(path.join(project, ".claude", "settings.json"), mergedClaudeSettings);
  }
  if (selected.includes("codex")) {
    mergers.set(path.join(project, ".codex", "hooks.json"), mergedCodexSettings);
  }
  if (selected.includes("cursor")) {
    mergers.set(path.join(project, ".cursor", "hooks.json"), mergedCursorSettings);
  }
  return mergers;
}

// --update replaces managed runtime, guard, and git hook files in place and
// keeps everything else (AGENTS.md, WORKFLOW.md, CLAUDE.md). Returns the
// managed-file check for a replaceable destination, or null for a kept one.
function updateReplacement(project, destination, hooksDir) {
  const parent = path.join(project, HOOKS_DIRECTORY);
  const directory = path.dirname(destination);
  if (samePath(directory, path.join(parent, "runtime"))) return isManagedProjectRuntime;
  if (samePath(destination, path.join(parent, PROJECT_STATUS_LAUNCHER))) {
    return isManagedProjectStatusLauncher;
  }
  if (GUARD_SCRIPTS.some((name) => samePath(destination, path.join(parent, name)))) {
    return isManagedGuardScript;
  }
  if (hooksDir !== null && samePath(directory, hooksDir)) return isManagedGitHook;
  return null;
}

function describeProjectPath(project, destination) {
  const relative = path.relative(project, destination);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    return destination.split(path.sep).join("/");
  }
  return relative.split(path.sep).join("/");
}

function projectFiles(project, selected, hooksEnabled, interpreter, hooksDir) {
  return projectDestinations(project, selected, hooksEnabled, interpreter, hooksDir)
    .map(([destination]) => describeProjectPath(project, destination))
    .join(", ");
}

function projectResult(project, selected, hooksEnabled, interpreter, hooksDir, update, dryRun) {
  if (!update) {
    const files = projectFiles(project, selected, hooksEnabled, interpreter, hooksDir);
    return `project: ${dryRun ? "would copy" : "copied"} ${files} to ${project}`;
  }
  const mergers = nativeSettingsMergers(project, selected, hooksEnabled);
  const refreshed = [];
  const kept = [];
  for (const [destination] of projectDestinations(project, selected, hooksEnabled, interpreter, hooksDir)) {
    const replaceable =
      mergers.has(destination) || updateReplacement(project, destination, hooksDir) !== null;
    (lexists(destination) && !replaceable ? kept : refreshed).push(describeProjectPath(project, destination));
  }
  let line = `project: ${dryRun ? "would refresh" : "refreshed"} ${refreshed.join(", ")} in ${project}`;
  if (kept.length) line += `; kept ${kept.join(", ")}`;
  return line;
}

function existingContractError(destination) {
  return new InstallerError(
    `project contract already exists: ${destination} — the installer never ` +
      "overwrites project files. Run --update --project PATH to refresh managed " +
      "runtime files; merge template changes manually (see UPDATE.md)."
  );
}

function validateProject(sourceRoot, project, selected, hooksEnabled, reservedRoots, interpreter, hooksDir, update = false) {
  const includeClaude = selected.includes("claude");
  validateDirectoryDestination(project, "project path");
  validateProjectGitRoot(project);
  validateDirectoryDestination(
    path.join(project, HOOKS_DIRECTORY),
    "project runtime parent directory"
  );
  validateDirectoryDestination(
    path.join(project, HOOKS_DIRECTORY, "runtime"),
    "project runtime directory"
  );
  const projectDirectories = [];
  if (includeClaude) projectDirectories.push(["Claude", path.join(project, ".claude")]);
  if (hooksEnabled && selected.includes("codex")) {
    projectDirectories.push(["Codex", path.join(project, ".codex")]);
  }
  if (hooksEnabled && selected.includes("cursor")) {
    projectDirectories.push(["Cursor", path.join(project, ".cursor")]);
  }
  for (const [label, directory] of projectDirectories) {
    if (lexists(directory) && (isSymlink(directory) || !isDirectory(directory))) {
      throw new InstallerError(`unsafe ${label} project directory: ${directory}`);
    }
  }
  const sources = [
    "AGENTS.md",
    "WORKFLOW.md",
    path.join("scripts", PROJECT_STATUS_LAUNCHER),
    ...PROJECT_RUNTIME_SCRIPTS.map((name) => path.join("scripts", name)),
  ];
  if (hooksEnabled) {
    sources.push(...GUARD_SCRIPTS.map((name) => path.join("scripts", name)));
  }
  for (const sourceName of sources) {
    const source = path.join(sourceRoot, sourceName);
    if (isSymlink(source) || !isFile(source)) {
      throw new InstallerError(`missing project contract: ${source}`);
    }
  }
  const mergers = nativeSettingsMergers(project, selected, hooksEnabled);
  for (const [destination] of projectDestinations(project, selected, hooksEnabled, interpreter, hooksDir)) {
    if (lexists(destination)) {
      const merge = mergers.get(destination);
      const managed = update ? updateReplacement(project, destination, hooksDir) : null;
      if (isSymlink(destination) || (merge === undefined && !update)) {
        throw existingContractError(destination);
      }
      if (merge !== undefined) {
        merge(destination, interpreter);
      } else if (managed !== null && !managed(destination)) {
        throw new InstallerError(`not a managed GSD Path project file: ${destination}`);
      }
    }
    for (const [label, root] of reservedRoots) {
      if (pathsOverlap(destination, root)) {
        throw new InstallerError(`project contract overlaps ${label}: ${destination}, ${root}`);
      }
    }
  }
}

function applyProject(sourceRoot, project, selected, hooksEnabled, transaction, interpreter, hooksDir, update = false) {
  createDirectory(project, transaction.createdDirectories);
  const mergers = nativeSettingsMergers(project, selected, hooksEnabled);
  for (const [destination, sourceName, literal, executable] of projectDestinations(
    project,
    selected,
    hooksEnabled,
    interpreter,
    hooksDir
  )) {
    createDirectory(path.dirname(destination), transaction.createdDirectories);
    const merge = mergers.get(destination);
    const content = sourceName
      ? fs.readFileSync(path.join(sourceRoot, sourceName))
      : Buffer.from(literal, "utf8");
    if (lexists(destination) && !isSymlink(destination)) {
      const replaceable = update && updateReplacement(project, destination, hooksDir) !== null;
      if (merge !== undefined || replaceable) {
        const original = fs.readFileSync(destination);
        const mode = fs.statSync(destination).mode & 0o777;
        const replacement = merge !== undefined ? merge(destination, interpreter) : content;
        writeFileAtomic(destination, replacement, executable ? 0o755 : mode);
        transaction.replaced.push({ destination, original, mode });
        continue;
      }
      if (update) continue;
    }
    let fd = null;
    try {
      fd = fs.openSync(destination, "wx");
      fs.writeSync(fd, content);
      if (executable) fs.fchmodSync(fd, 0o755);
      fs.closeSync(fd);
      fd = null;
      transaction.copied.push(destination);
    } catch (error) {
      if (fd !== null) fs.closeSync(fd);
      if (error && error.code === "EEXIST") {
        throw existingContractError(destination);
      }
      removePath(destination);
      throw error;
    }
  }
}

function rollbackProject(transaction) {
  for (const { destination, original, mode } of [...transaction.replaced].reverse()) {
    writeFileAtomic(destination, original, mode);
  }
  for (const destination of [...transaction.copied].reverse()) {
    removePath(destination);
  }
  removeEmptyDirectories(transaction.createdDirectories);
}

function managedFileContains(destination, marker, label) {
  if (!isFile(destination)) return false;
  try {
    return fs.readFileSync(destination, "utf8").includes(marker);
  } catch {
    throw new InstallerError(`cannot read ${label}: ${destination}`);
  }
}

function isManagedGuardScript(destination) {
  return managedFileContains(destination, GUARD_MARKER, "guard script");
}

function isManagedProjectRuntime(destination) {
  return managedFileContains(destination, PROJECT_RUNTIME_MARKER, "project runtime");
}

function isManagedProjectStatusLauncher(destination) {
  return managedFileContains(
    destination,
    PROJECT_STATUS_MARKER,
    "project status launcher"
  );
}

function isManagedGitHook(destination) {
  if (!isFile(destination)) return false;
  return isManagedGitHookContent(fs.readFileSync(destination, "utf8"));
}

function isManagedGitHookContent(text) {
  return text.includes(GUARD_MARKER) && text.includes("git_guard.py");
}

function isManagedHookSettings(destination) {
  if (!isFile(destination)) return false;
  try {
    return hasManagedHookSettings(parsedManagedSettings(destination));
  } catch {
    return false;
  }
}

function hasManagedGuardWiring(project) {
  const settings = [
    path.join(project, ".claude", "settings.json"),
    path.join(project, ".codex", "hooks.json"),
    path.join(project, ".cursor", "hooks.json"),
  ];
  if (settings.some(isManagedHookSettings)) return true;
  const hooksDir = gitHooksDirectory(project);
  return (
    hooksDir !== null &&
    GIT_HOOK_NAMES.some((name) => isManagedGitHook(path.join(hooksDir, name)))
  );
}

function atomicTemporary(destination) {
  const directory = fs.mkdtempSync(
    path.join(path.dirname(destination), `.${path.basename(destination)}.gsd-path-tmp-`)
  );
  return { directory, temporary: path.join(directory, "value") };
}

function writeFileAtomic(destination, content, mode) {
  const { directory, temporary } = atomicTemporary(destination);
  try {
    fs.writeFileSync(temporary, content, { flag: "wx" });
    if (mode !== undefined) {
      fs.chmodSync(temporary, mode);
    } else if (isFile(destination) && !isSymlink(destination)) {
      fs.chmodSync(temporary, fs.statSync(destination).mode & 0o777);
    }
    fs.renameSync(temporary, destination);
  } finally {
    removePath(directory);
  }
}

function copyFileAtomic(source, destination) {
  const { directory, temporary } = atomicTemporary(destination);
  try {
    fs.copyFileSync(source, temporary, fs.constants.COPYFILE_EXCL);
    fs.renameSync(temporary, destination);
  } finally {
    removePath(directory);
  }
}

// A PreToolUse entry is ours when one of its commands runs the guard hook.
function isGuardCommand(command) {
  const normalized = command.replaceAll("\\", "/");
  const match = /^(?:python3|python)\s+(?:"([^"\r\n]+)"|'([^'\r\n]+)'|(\S+))$/.exec(
    normalized
  );
  if (match === null) return false;
  const script = match[1] || match[2] || match[3];
  const managedScript = `${HOOKS_DIRECTORY}/guard_hook.py`;
  return script === managedScript || script.endsWith(`/${managedScript}`);
}

function isManagedCommandHook(hook) {
  return Boolean(
    hook &&
      typeof hook === "object" &&
      !Array.isArray(hook) &&
      typeof hook.command === "string" &&
      isGuardCommand(hook.command)
  );
}

function isManagedHookEntry(entry) {
  return Boolean(
    entry &&
      typeof entry === "object" &&
      !Array.isArray(entry) &&
      Array.isArray(entry.hooks) &&
      entry.hooks.some(isManagedCommandHook)
  );
}

function isManagedDirectHookEntry(entry) {
  return isManagedCommandHook(entry);
}

function hasManagedHookSettings(parsed) {
  const hooks = parsed.hooks;
  if (hooks === null || typeof hooks !== "object" || Array.isArray(hooks)) return false;
  const nested = hooks.PreToolUse;
  const direct = hooks.preToolUse;
  return (
    (Array.isArray(nested) && nested.some(isManagedHookEntry)) ||
    (Array.isArray(direct) && direct.some(isManagedDirectHookEntry))
  );
}

function parsedManagedSettings(settings) {
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(settings, "utf8"));
  } catch {
    throw new InstallerError(`managed hook settings file is not valid JSON: ${settings}`);
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new InstallerError(`managed hook settings file is not a JSON object: ${settings}`);
  }
  return parsed;
}

function mergedHookSettings(settings, eventName, managedEntry, isManagedEntry) {
  const parsed = parsedManagedSettings(settings);
  const hooksObject =
    parsed.hooks && typeof parsed.hooks === "object" && !Array.isArray(parsed.hooks)
      ? parsed.hooks
      : {};
  const existing = Array.isArray(hooksObject[eventName]) ? hooksObject[eventName] : [];
  const merged = [];
  let replaced = false;
  for (const entry of existing) {
    if (isManagedEntry(entry)) {
      if (!replaced) {
        merged.push(managedEntry);
        replaced = true;
      }
    } else {
      merged.push(entry);
    }
  }
  if (!replaced) merged.push(managedEntry);
  hooksObject[eventName] = merged;
  parsed.hooks = hooksObject;
  return JSON.stringify(parsed, null, 2) + "\n";
}

function mergedNestedHookSettings(settings, managedEntry) {
  const parsed = parsedManagedSettings(settings);
  const hooksObject =
    parsed.hooks && typeof parsed.hooks === "object" && !Array.isArray(parsed.hooks)
      ? parsed.hooks
      : {};
  const existing = Array.isArray(hooksObject.PreToolUse) ? hooksObject.PreToolUse : [];
  const merged = [];
  let replaced = false;
  for (const entry of existing) {
    if (!isManagedHookEntry(entry)) {
      merged.push(entry);
      continue;
    }
    const unrelatedHooks = entry.hooks.filter((hook) => !isManagedCommandHook(hook));
    if (!replaced) {
      merged.push(managedEntry);
      replaced = true;
    }
    if (unrelatedHooks.length > 0) {
      merged.push({ ...entry, hooks: unrelatedHooks });
    }
  }
  if (!replaced) merged.push(managedEntry);
  hooksObject.PreToolUse = merged;
  parsed.hooks = hooksObject;
  return JSON.stringify(parsed, null, 2) + "\n";
}

function mergedClaudeSettings(settings, interpreter) {
  return mergedNestedHookSettings(settings, claudeGuardEntry(interpreter));
}

function mergedCodexSettings(settings, interpreter) {
  const managedEntry = JSON.parse(codexHooksSettings(interpreter)).hooks.PreToolUse[0];
  return mergedNestedHookSettings(settings, managedEntry);
}

function mergedCursorSettings(settings, interpreter) {
  const managedEntry = JSON.parse(cursorHooksSettings(interpreter)).hooks.preToolUse[0];
  return mergedHookSettings(settings, "preToolUse", managedEntry, isManagedDirectHookEntry);
}

function refreshesGuards(project, full, initialize) {
  return (
    full ||
    initialize ||
    hasManagedGuardWiring(project) ||
    GUARD_SCRIPTS.some((name) => lexists(path.join(project, HOOKS_DIRECTORY, name)))
  );
}

function contractSection(content, heading) {
  const normalized = content.replaceAll("\r\n", "\n");
  const startPattern = new RegExp(`^${heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`, "m");
  const startMatch = startPattern.exec(normalized);
  if (startMatch === null) return null;
  const depth = heading.indexOf(" ");
  const afterHeading = normalized.indexOf("\n", startMatch.index);
  const bodyStart = afterHeading === -1 ? normalized.length : afterHeading + 1;
  const nextHeading = new RegExp(`^#{1,${depth}}\\s`, "m").exec(normalized.slice(bodyStart));
  const end = nextHeading === null ? normalized.length : bodyStart + nextHeading.index;
  return normalized.slice(startMatch.index, end).trimEnd();
}

function hasLegacyProjectContracts(sourceRoot, project) {
  return PROJECT_CONTRACTS.every(([name, heading]) => {
    const candidate = path.join(project, name);
    const source = path.join(sourceRoot, name);
    if (
      isSymlink(candidate) ||
      !isFile(candidate) ||
      isSymlink(source) ||
      !isFile(source)
    ) return false;
    const installed = contractSection(fs.readFileSync(candidate, "utf8"), heading);
    const canonical = contractSection(fs.readFileSync(source, "utf8"), heading);
    return installed !== null && installed === canonical;
  });
}

function validateHooksRefresh(sourceRoot, project, full, hooksDir, selected, initialize = false) {
  validateDirectoryDestination(project, "project path");
  validateProjectGitRoot(project);
  validateDirectoryDestination(
    path.join(project, HOOKS_DIRECTORY),
    "guard hooks directory"
  );
  validateDirectoryDestination(
    path.join(project, HOOKS_DIRECTORY, "runtime"),
    "project runtime directory"
  );
  const refreshGuards = refreshesGuards(project, full, initialize);
  const runtimeExists = PROJECT_RUNTIME_SCRIPTS.some((name) =>
    lexists(path.join(project, HOOKS_DIRECTORY, "runtime", name))
  );
  if (
    !initialize &&
    !refreshGuards &&
    !runtimeExists &&
    !hasLegacyProjectContracts(sourceRoot, project)
  ) {
    throw new InstallerError(
      `no managed GSD Path hooks or runtime found in project: ${project}`
    );
  }
  const runtime = path.join(project, HOOKS_DIRECTORY, "runtime");
  const launcher = path.join(project, HOOKS_DIRECTORY, PROJECT_STATUS_LAUNCHER);
  const launcherSource = path.join(sourceRoot, "scripts", PROJECT_STATUS_LAUNCHER);
  if (isSymlink(launcher) || (lexists(launcher) && !isManagedProjectStatusLauncher(launcher))) {
    throw new InstallerError(`not a managed GSD Path status launcher: ${launcher}`);
  }
  if (isSymlink(launcherSource) || !isFile(launcherSource)) {
    throw new InstallerError(`missing project status launcher source: ${launcherSource}`);
  }
  if (isDirectory(runtime)) {
    const unexpected = fs
      .readdirSync(runtime)
      .filter((name) => !PROJECT_RUNTIME_SCRIPTS.includes(name));
    if (unexpected.length) {
      throw new InstallerError(`unexpected project runtime entries: ${unexpected.join(", ")}`);
    }
  }
  if (refreshGuards) {
    for (const name of GUARD_SCRIPTS) {
      const destination = path.join(project, HOOKS_DIRECTORY, name);
      const exists = lexists(destination);
      if (isSymlink(destination)) {
        throw new InstallerError(`refusing to refresh a symlink: ${destination}`);
      }
      if (exists && !isManagedGuardScript(destination)) {
        throw new InstallerError(`not a managed GSD Path guard script: ${destination}`);
      }
      const source = path.join(sourceRoot, "scripts", name);
      if (isSymlink(source) || !isFile(source)) {
        throw new InstallerError(`missing guard script source: ${source}`);
      }
    }
  }
  for (const name of PROJECT_RUNTIME_SCRIPTS) {
    const destination = path.join(project, HOOKS_DIRECTORY, "runtime", name);
    if (isSymlink(destination)) {
      throw new InstallerError(`refusing to refresh a symlink: ${destination}`);
    }
    if (lexists(destination) && !isManagedProjectRuntime(destination)) {
      throw new InstallerError(`not a managed GSD Path project runtime: ${destination}`);
    }
    const source = path.join(sourceRoot, "scripts", name);
    if (isSymlink(source) || !isFile(source)) {
      throw new InstallerError(`missing project runtime source: ${source}`);
    }
  }
  if (full) {
    for (const [target, label, settings] of [
      ["claude", "Claude", path.join(project, ".claude", "settings.json")],
      ["codex", "Codex", path.join(project, ".codex", "hooks.json")],
      ["cursor", "Cursor", path.join(project, ".cursor", "hooks.json")],
    ]) {
      const exists = lexists(settings);
      if (initialize && !selected.includes(target)) continue;
      if (!exists && !selected.includes(target)) continue;
      validateDirectoryDestination(
        path.dirname(settings),
        `unsafe ${label} project directory`
      );
      if (isSymlink(settings)) {
        throw new InstallerError(`refusing to refresh a symlink: ${settings}`);
      }
      if (exists) {
        const parsed = parsedManagedSettings(settings);
        if (!selected.includes(target) && !hasManagedHookSettings(parsed)) {
          throw new InstallerError(`not a managed GSD Path hook settings file: ${settings}`);
        }
      }
    }
    if (hooksDir !== null) {
      for (const hookName of GIT_HOOK_NAMES) {
        const hookPath = path.join(hooksDir, hookName);
        if (isSymlink(hookPath)) {
          throw new InstallerError(`refusing to refresh a symlink: ${hookPath}`);
        }
        if (lexists(hookPath) && !isManagedGitHook(hookPath)) {
          throw new InstallerError(`not a managed GSD Path git hook: ${hookPath}`);
        }
      }
    }
  }
}

function publishProjectRuntime(sourceRoot, project, refreshGuards) {
  const parent = path.join(project, HOOKS_DIRECTORY);
  const runtime = path.join(parent, "runtime");
  fs.mkdirSync(parent, { recursive: true });
  const staging = fs.mkdtempSync(path.join(parent, ".runtime-stage-"));
  const previous = `${staging}-previous`;
  let movedPrevious = false;
  let publishedRuntime = false;
  const launcher = path.join(parent, PROJECT_STATUS_LAUNCHER);
  const launcherOriginal = lexists(launcher) ? fs.readFileSync(launcher) : null;
  const launcherMode = launcherOriginal === null ? undefined : fs.statSync(launcher).mode & 0o777;
  const guardOriginals = [];
  try {
    for (const name of PROJECT_RUNTIME_SCRIPTS) {
      hooks.copyRuntimeFile(
        path.join(sourceRoot, "scripts", name),
        path.join(staging, name)
      );
    }
    copyFileAtomic(path.join(sourceRoot, "scripts", PROJECT_STATUS_LAUNCHER), launcher);
    if (lexists(runtime)) {
      fs.renameSync(runtime, previous);
      movedPrevious = true;
    }
    fs.renameSync(staging, runtime);
    publishedRuntime = true;
    if (refreshGuards) {
      for (const name of GUARD_SCRIPTS) {
        const destination = path.join(parent, name);
        const original = lexists(destination) ? fs.readFileSync(destination) : null;
        const mode =
          original === null ? undefined : fs.statSync(destination).mode & 0o777;
        guardOriginals.push([destination, original, mode]);
        hooks.copyGuardFile(path.join(sourceRoot, "scripts", name), destination);
      }
    }
    if (movedPrevious) removePath(previous);
  } catch (error) {
    for (const [destination, original, mode] of guardOriginals.reverse()) {
      if (original === null) removePath(destination);
      else writeFileAtomic(destination, original, mode);
    }
    if (launcherOriginal === null) removePath(launcher);
    else writeFileAtomic(launcher, launcherOriginal, launcherMode);
    if (publishedRuntime && lexists(runtime)) removePath(runtime);
    if (!lexists(runtime) && movedPrevious && lexists(previous)) {
      fs.renameSync(previous, runtime);
    }
    throw new InstallerError(`project runtime refresh failed: ${error.message}`);
  } finally {
    removePath(staging);
  }
}

// Returns refreshed project-relative paths; entries prefixed "note:" are
// user-facing notes rather than refreshed files.
function refreshHooksUnlocked(sourceRoot, project, full, dryRun, selected, initialize) {
  let hooksDir = full ? gitHooksDirectory(project) : null;
  let interpreter = null;
  if (!dryRun) {
    if (full) {
      ({ interpreter, hooksDir } = requiredHookRuntime(
        project,
        initialize ? "--hooks-init" : "--hooks-refresh-full",
        selected
      ));
    } else {
      interpreter = requiredPythonRuntime("--hooks-refresh", selected);
    }
  }
  validateHooksRefresh(sourceRoot, project, full, hooksDir, selected, initialize);
  const refreshed = [];
  const refreshGuards = refreshesGuards(project, full, initialize);
  if (!dryRun) publishProjectRuntime(sourceRoot, project, refreshGuards);
  for (const name of PROJECT_RUNTIME_SCRIPTS) {
    refreshed.push(
      describeProjectPath(project, path.join(project, HOOKS_DIRECTORY, "runtime", name))
    );
  }
  refreshed.push(
    describeProjectPath(
      project,
      path.join(project, HOOKS_DIRECTORY, PROJECT_STATUS_LAUNCHER)
    )
  );
  if (refreshGuards) {
    for (const name of GUARD_SCRIPTS) {
      const destination = path.join(project, HOOKS_DIRECTORY, name);
      refreshed.push(describeProjectPath(project, destination));
    }
  }
  if (full) {
    for (const [target, settings, merge, generated] of [
      [
        "claude",
        path.join(project, ".claude", "settings.json"),
        mergedClaudeSettings,
        claudeHooksSettings,
      ],
      [
        "codex",
        path.join(project, ".codex", "hooks.json"),
        mergedCodexSettings,
        codexHooksSettings,
      ],
      [
        "cursor",
        path.join(project, ".cursor", "hooks.json"),
        mergedCursorSettings,
        cursorHooksSettings,
      ],
    ]) {
      if (initialize && !selected.includes(target)) continue;
      const exists = lexists(settings);
      if (exists || selected.includes(target)) {
        if (!dryRun) {
          fs.mkdirSync(path.dirname(settings), { recursive: true });
          const content = exists ? merge(settings, interpreter) : generated(interpreter);
          writeFileAtomic(settings, content);
        }
        refreshed.push(describeProjectPath(project, settings));
      }
    }
    if (hooksDir !== null) {
      for (const [hookName, generator] of GIT_HOOKS) {
        const hookPath = path.join(hooksDir, hookName);
        if (!dryRun) {
          const content = generator(interpreter);
          fs.mkdirSync(path.dirname(hookPath), { recursive: true });
          writeFileAtomic(hookPath, content, 0o755);
        }
        refreshed.push(describeProjectPath(project, hookPath));
      }
    }
  }
  return refreshed;
}

function refreshHooks(sourceRoot, project, full, dryRun, selected = [], initialize = false) {
  if (dryRun) {
    return refreshHooksUnlocked(sourceRoot, project, full, true, selected, initialize);
  }
  validateDirectoryDestination(project, "project path");
  const ownership = acquireInstallLocks([path.join(project, HOOKS_DIRECTORY)]);
  try {
    return refreshHooksUnlocked(sourceRoot, project, full, false, selected, initialize);
  } finally {
    releaseInstallLocks(ownership.locks, ownership.createdDirectories);
  }
}

const STATE_SCHEMA = "gsd-path/state/v1";

function validatedProjectState(sourceRoot, project) {
  const validator = path.join(sourceRoot, "scripts", "pipeline_state.py");
  if (isSymlink(validator) || !isFile(validator)) {
    throw new InstallerError(`canonical state validator is unavailable: ${validator}`);
  }
  const interpreter = effectiveInterpreter();
  if (interpreter === null) {
    throw new InstallerError("canonical state validation requires a working Python interpreter");
  }
  const result = spawnSync(
    interpreter,
    ["-B", validator, "validate", "--repo", project],
    { cwd: project, encoding: "utf8" }
  );
  if (result.error || result.status !== 0) {
    const detail =
      result.error?.message ||
      (result.stderr || "").trim() ||
      (result.stdout || "").trim() ||
      "unknown failure";
    throw new InstallerError(`canonical state validation failed: ${detail}`);
  }
  let payload;
  try {
    payload = JSON.parse(result.stdout);
  } catch {
    throw new InstallerError("canonical state validator returned invalid JSON");
  }
  if (!payload || typeof payload !== "object") {
    throw new InstallerError("canonical state validator returned an invalid payload");
  }
  const state = payload.state;
  if (
    payload.schema !== STATE_SCHEMA ||
    payload.status !== "valid" ||
    !state ||
    typeof state !== "object" ||
    typeof state.phase !== "string" ||
    typeof state.status !== "string"
  ) {
    throw new InstallerError("canonical state validator returned an invalid payload");
  }
  return state;
}

function hasManagedInstall(root) {
  return (
    isDirectory(root) &&
    fs.readdirSync(root).some((name) => isManagedInstallEntry(root, name))
  );
}

function validateProjectRuntimeStatus(sourceRoot, project) {
  const interpreter = requiredPythonRuntime("--doctor");
  const runtime = path.join(sourceRoot, "scripts", "pipeline_state.py");
  const result = spawnSync(
    interpreter,
    ["-B", runtime, "status", "--repo", project],
    {
      cwd: project,
      encoding: "utf8",
      env: { ...process.env, GIT_OPTIONAL_LOCKS: "0" },
    }
  );
  if (result.error || result.status !== 0) {
    const detail = result.error?.message || result.stderr?.trim() || result.stdout?.trim() || "unknown failure";
    throw new InstallerError(`project runtime status failed: ${detail}`);
  }
  let payload;
  try {
    payload = JSON.parse(result.stdout);
  } catch {
    throw new InstallerError("project runtime status returned invalid JSON");
  }
  if (!validStatusPayload(payload, project)) {
    throw new InstallerError("project runtime status returned an invalid payload");
  }
}

function projectRuntimeMatches(sourceRoot, project) {
  const pairs = [
    [
      path.join(project, HOOKS_DIRECTORY, PROJECT_STATUS_LAUNCHER),
      path.join(sourceRoot, "scripts", PROJECT_STATUS_LAUNCHER),
    ],
    ...PROJECT_RUNTIME_SCRIPTS.map((name) => [
      path.join(project, HOOKS_DIRECTORY, "runtime", name),
      path.join(sourceRoot, "scripts", name),
    ]),
  ];
  try {
    return pairs.every(
      ([destination, source]) =>
        !isSymlink(destination) &&
        isFile(destination) &&
        fs.readFileSync(destination).equals(fs.readFileSync(source))
    );
  } catch {
    return false;
  }
}

function validStatusPayload(payload, project) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  const state = payload.state;
  const route = payload.route;
  if (
    payload.schema !== "gsd-path/status/v1" ||
    payload.advance !== false ||
    !state ||
    typeof state !== "object" ||
    !validStatusState(state) ||
    !route ||
    typeof route !== "object" ||
    !STATUS_ACTIONS.has(route.action) ||
    typeof route.reason !== "string" ||
    !route.reason ||
    typeof payload.path !== "string" ||
    !path.isAbsolute(payload.path) ||
    !samePath(payload.path, path.join(project, ".project", "STATE.md"))
  ) {
    return false;
  }
  let expectedNextSkill = null;
  if (route.action === "run-phase") {
    if (
      typeof route.phase !== "string" ||
      !STATUS_TRANSITIONS.get(state.phase).has(route.phase) ||
      state.branch === null
    ) return false;
    expectedNextSkill = `gsd-path-${route.phase}`;
  } else if (Object.hasOwn(route, "phase")) {
    return false;
  } else if (route.action === "bind-initial") {
    return (
      state.branch === null &&
      typeof route.branch === "string" &&
      validStatusBranch(route.branch) !== null &&
      payload.next_skill === "gsd-path"
    );
  } else if (route.action === "resume-undo") {
    expectedNextSkill = "gsd-path-undo";
  } else if (route.action !== "wait") {
    expectedNextSkill = "gsd-path";
  }
  if (state.branch === null) return false;
  if (route.action === "validate-integrated" && !(state.phase === "shipped" && state.status === "done")) return false;
  if (route.action === "wait" && !(state.phase === "plan" && state.status === "done")) return false;
  return payload.next_skill === expectedNextSkill;
}

function validStatusState(state) {
  if (Object.keys(state).sort().join("\0") !== STATUS_STATE_FIELDS.join("\0")) return false;
  const archiveMatch = typeof state.archive === "string" ? STATUS_ARCHIVE.exec(state.archive) : null;
  if (
    state.pipeline !== "gsd-path/v2" ||
    typeof state.project !== "string" ||
    !STATUS_SLUG.test(state.project) ||
    !(state.milestone === null || typeof state.milestone === "string" && STATUS_SLUG.test(state.milestone)) ||
    !STATUS_PHASES.has(state.phase) ||
    !STATUS_VALUES.has(state.status) ||
    !STATUS_INTEGRATION_MODES.has(state.integration_default) ||
    !STATUS_INTEGRATION_MODES.has(state.integration) ||
    !STATUS_INTEGRATION_SOURCES.has(state.integration_source) ||
    (state.integration_source === "default" &&
      state.integration !== state.integration_default) ||
    !(state.branch === null || validStatusBranch(state.branch) !== null) ||
    !(state.archive === null || archiveMatch)
  ) return false;
  if (state.phase === "shipped" && (state.status !== "done" || state.archive === null)) return false;
  if (
    state.archive !== null &&
    state.phase !== "build" &&
    state.phase !== "ship" &&
    state.phase !== "shipped"
  ) return false;
  if ((state.phase === "ship" || state.phase === "shipped") && state.branch === null) return false;
  if (archiveMatch) {
    const branchMatch = validStatusBranch(state.branch);
    return state.milestone === archiveMatch[2] && branchMatch !== null && Number(branchMatch[1]) === Number(archiveMatch[1]);
  }
  return true;
}

function validStatusBranch(value) {
  if (typeof value !== "string") return null;
  const match = STATUS_BRANCH.exec(value);
  return match !== null && Number(match[1]) >= 1 ? match : null;
}

function isExecutable(candidate) {
  try {
    return (fs.statSync(candidate).mode & 0o111) !== 0;
  } catch {
    return false;
  }
}

function nativeGuardContract(target, project) {
  if (target === "claude") {
    return {
      settings: path.join(project, ".claude", "settings.json"),
      event: "PreToolUse",
      entry: claudeGuardEntry,
    };
  }
  if (target === "codex") {
    return {
      settings: path.join(project, ".codex", "hooks.json"),
      event: "PreToolUse",
      entry: codexGuardEntry,
    };
  }
  if (target === "cursor") {
    return {
      settings: path.join(project, ".cursor", "hooks.json"),
      event: "preToolUse",
      entry: cursorGuardEntry,
    };
  }
  return null;
}

// Read-only health check: host installs, project contracts, guard hooks,
// and pipeline state. Never writes.
export function doctor(sourceRoot, { targets, rootFor, project = null }) {
  const findings = [];
  const push = (level, text) => findings.push({ level, text });
  function readProjectFile(candidate, label) {
    try {
      return fs.readFileSync(candidate);
    } catch (error) {
      push("fail", `${label} cannot be read: ${error.message}`);
      return null;
    }
  }
  const version = readPackageVersion(path.join(sourceRoot, "package.json"));
  if (version === null) push("fail", "package: version cannot be read");

  const seen = [];
  const installedTargets = new Set();
  for (const target of targets) {
    const root = rootFor(target);
    const prior = seen.find(([, other]) => samePath(other, root));
    if (prior) {
      push("note", `${target}: shares ${prior[0]}'s skills root`);
      continue;
    }
    seen.push([target, root]);
    let managedInstall;
    try {
      managedInstall = hasManagedInstall(root);
    } catch (error) {
      push("fail", `${target}: skills root cannot be read: ${error.message}`);
      continue;
    }
    if (!managedInstall) {
      push("note", `${target}: not installed (${root})`);
      continue;
    }
    installedTargets.add(target);
    const missing = SKILL_NAMES.filter((name) => !isDirectory(path.join(root, name)));
    if (missing.length) {
      push("fail", `${target}: incomplete install at ${root} — missing ${missing.join(", ")}`);
      continue;
    }
    let stamp = null;
    try {
      stamp = fs.readFileSync(path.join(root, "gsd-path", "VERSION"), "utf8").trim();
    } catch {
      // No stamp; reported below.
    }
    if (!stamp) {
      push("warn", `${target}: ${SKILL_NAMES.length} skills at ${root}, no VERSION stamp — run --update`);
    } else if (version && stamp !== version) {
      push("warn", `${target}: stale install at ${root} (v${stamp}, current v${version}) — run --update`);
    } else {
      push("ok", `${target}: ${SKILL_NAMES.length} skills at ${root} (v${stamp})`);
    }
  }

  if (project === null) return findings;

  for (const [name, heading] of PROJECT_CONTRACTS) {
    const contract = path.join(project, name);
    if (isSymlink(contract)) {
      push("fail", `project: contract ${name} is a symlink`);
      continue;
    }
    if (!isFile(contract)) {
      push("fail", `project: missing contract ${name} — run --project "${project}"`);
      continue;
    }
    const content = readProjectFile(contract, `project: ${name}`);
    if (content === null) continue;
    const canonical = readProjectFile(
      path.join(sourceRoot, name),
      `package: ${name}`
    );
    if (canonical === null) continue;
    const installedSection = contractSection(content.toString("utf8"), heading);
    const canonicalSection = contractSection(canonical.toString("utf8"), heading);
    if (installedSection !== null && installedSection === canonicalSection) {
      push("ok", `project: ${name} present`);
    } else {
      push("fail", `project: ${name} lacks plain-prompt re-entry — merge the current contract`);
    }
  }
  const bridge = path.join(project, ".claude", "CLAUDE.md");
  if (!isFile(bridge)) {
    push("note", "project: no .claude/CLAUDE.md bridge (only written for --claude installs)");
  } else {
    const bridgeContent = readProjectFile(bridge, "project: .claude/CLAUDE.md");
    if (bridgeContent !== null) {
      if (bridgeContent.toString("utf8") === CLAUDE_BRIDGE) {
        push("ok", "project: .claude/CLAUDE.md bridge present");
      } else {
        push("note", "project: .claude/CLAUDE.md exists but is not the managed bridge");
      }
    }
  }

  const runtime = path.join(project, HOOKS_DIRECTORY, "runtime");
  const launcher = path.join(project, HOOKS_DIRECTORY, PROJECT_STATUS_LAUNCHER);
  let runtimeCurrent = true;
  if (isSymlink(launcher)) {
    push("fail", "project: status launcher is a symlink");
    runtimeCurrent = false;
  } else if (!isFile(launcher)) {
    push("fail", "project: missing status launcher");
    runtimeCurrent = false;
  } else {
    const launcherContent = readProjectFile(launcher, "project: status launcher");
    const launcherSource = readProjectFile(
      path.join(sourceRoot, "scripts", PROJECT_STATUS_LAUNCHER),
      "package: status launcher"
    );
    if (launcherContent === null || launcherSource === null) {
      runtimeCurrent = false;
    } else {
      if (!launcherContent.toString("utf8").includes(PROJECT_STATUS_MARKER)) {
        push("warn", "project: status launcher is not managed");
        runtimeCurrent = false;
      } else if (!launcherContent.equals(launcherSource)) {
        push(
          "warn",
          "project: status launcher is stale — refresh it with the project contracts"
        );
        runtimeCurrent = false;
      } else {
        push("ok", "project: status launcher current");
      }
    }
  }
  let runtimeSafe = true;
  try {
    validateDirectoryDestination(
      path.join(project, HOOKS_DIRECTORY),
      "project runtime parent directory"
    );
    validateDirectoryDestination(runtime, "project runtime directory");
  } catch (error) {
    if (!(error instanceof InstallerError)) throw error;
    push("fail", `project: unsafe runtime — ${error.message}`);
    runtimeSafe = false;
    runtimeCurrent = false;
  }
  if (runtimeSafe) {
    for (const name of PROJECT_RUNTIME_SCRIPTS) {
      const destination = path.join(runtime, name);
      if (isSymlink(destination)) {
        push("fail", `project: runtime ${name} is a symlink`);
        runtimeCurrent = false;
        continue;
      }
      if (!isFile(destination)) {
        push("fail", `project: missing runtime ${name}`);
        runtimeCurrent = false;
        continue;
      }
      const content = readProjectFile(destination, `project: runtime ${name}`);
      if (content === null) {
        runtimeCurrent = false;
        continue;
      }
      const source = readProjectFile(
        path.join(sourceRoot, "scripts", name),
        `package: runtime ${name}`
      );
      if (source === null) {
        runtimeCurrent = false;
        continue;
      }
      if (!content.toString("utf8").includes(PROJECT_RUNTIME_MARKER)) {
        push("warn", `project: runtime ${name} is not managed`);
        runtimeCurrent = false;
      } else if (!content.equals(source)) {
        push("warn", `project: runtime ${name} is stale — refresh it with the project contracts`);
        runtimeCurrent = false;
      } else {
        push("ok", `project: runtime ${name} current`);
      }
    }
  }

  let guardInstalled = GUARD_SCRIPTS.some((name) =>
    lexists(path.join(project, HOOKS_DIRECTORY, name))
  );
  const nativeWiredTargets = new Set();
  for (const target of targets) {
    const contract = nativeGuardContract(target, project);
    if (
      contract !== null &&
      (isSymlink(contract.settings) || isManagedHookSettings(contract.settings))
    ) {
      nativeWiredTargets.add(target);
    }
  }
  let guardWired = nativeWiredTargets.size > 0;
  const unreadableGitHooks = new Map();
  if (lexists(path.join(project, ".git"))) {
    const hooksDir = gitHooksDirectory(project);
    if (hooksDir !== null) {
      for (const name of GIT_HOOK_NAMES) {
        const hookPath = path.join(hooksDir, name);
        if (!lexists(hookPath)) continue;
        if (isSymlink(hookPath)) {
          guardWired = true;
          continue;
        }
        try {
          const managed = isManagedGitHookContent(fs.readFileSync(hookPath, "utf8"));
          guardWired = managed || guardWired;
        } catch (error) {
          unreadableGitHooks.set(hookPath, error.message);
        }
      }
    }
  }
  for (const [hookPath, error] of unreadableGitHooks) {
    const label = describeProjectPath(project, hookPath);
    push("fail", `hooks: ${label} cannot be read: ${error}`);
  }
  guardInstalled = guardInstalled || guardWired;
  if (!guardInstalled) {
    push("note", "hooks: guard hooks not installed (opt in with --hooks; see HOOKS.md)");
  } else {
    for (const name of GUARD_SCRIPTS) {
      const destination = path.join(project, HOOKS_DIRECTORY, name);
      if (isSymlink(destination)) {
        push("fail", `hooks: ${HOOKS_DIRECTORY}/${name} is a symlink`);
        continue;
      }
      if (!isFile(destination)) {
        push("fail", `hooks: missing ${HOOKS_DIRECTORY}/${name} — run --hooks-refresh`);
        continue;
      }
      const content = readProjectFile(destination, `hooks: ${HOOKS_DIRECTORY}/${name}`);
      if (content === null) continue;
      const source = readProjectFile(
        path.join(sourceRoot, "scripts", name),
        `package: guard ${name}`
      );
      if (source === null) continue;
      if (!content.toString("utf8").includes(GUARD_MARKER)) {
        push("warn", `hooks: ${HOOKS_DIRECTORY}/${name} is not a managed guard script`);
      } else if (!content.equals(source)) {
        push("warn", `hooks: ${HOOKS_DIRECTORY}/${name} is stale — run --hooks-refresh`);
      } else {
        push("ok", `hooks: ${HOOKS_DIRECTORY}/${name} current`);
      }
    }
    for (const target of targets) {
      if (!installedTargets.has(target) && !nativeWiredTargets.has(target)) continue;
      const contract = nativeGuardContract(target, project);
      if (contract === null) {
        if (MANIFEST.hosts[target]?.guard_tier !== "git-only") {
          push("fail", `hooks: ${target} declares a native guard without a health contract`);
        }
        continue;
      }
      if (isSymlink(contract.settings)) {
        push("fail", `hooks: ${target} native guard wiring is a symlink`);
        continue;
      }
      if (!isFile(contract.settings)) {
        push("fail", `hooks: ${target} native guard wiring is missing — run --hooks-refresh-full`);
        continue;
      }
      let current = false;
      try {
        const parsed = JSON.parse(fs.readFileSync(contract.settings, "utf8"));
        const entries =
          parsed && typeof parsed === "object" && parsed.hooks
            ? parsed.hooks[contract.event]
            : null;
        const variants = INTERPRETER_CANDIDATES.map((candidate) =>
          JSON.stringify(contract.entry(candidate))
        );
        current =
          Array.isArray(entries) &&
          entries.some((entry) => variants.includes(JSON.stringify(entry)));
      } catch {
        current = false;
      }
      if (current) {
        push("ok", `hooks: ${target} native guard wiring present`);
      } else {
        push("fail", `hooks: ${target} native guard wiring is stale — run --hooks-refresh-full`);
      }
    }
    const dotGit = path.join(project, ".git");
    if (lexists(dotGit)) {
      const hooksDir = gitHooksDirectory(project);
      if (hooksDir === null) {
        push(
          "fail",
          "hooks: cannot resolve the git hooks directory (is git runnable?); git hooks unverified"
        );
      } else {
        const custom = !samePath(hooksDir, path.join(dotGit, "hooks"));
        let missingFromCustom = false;
        for (const [hookName, generator] of GIT_HOOKS) {
          const hookPath = path.join(hooksDir, hookName);
          const label = describeProjectPath(project, hookPath);
          if (unreadableGitHooks.has(hookPath)) {
            continue;
          }
          if (!lexists(hookPath)) {
            push(
              "fail",
              `hooks: ${hookName} is missing from the effective git hooks directory ` +
                `${hooksDir} — run --hooks-refresh-full`
            );
            if (custom) missingFromCustom = true;
          } else if (isSymlink(hookPath)) {
            push("fail", `hooks: ${label} is a symlink`);
          } else {
            const hookContent = readProjectFile(hookPath, `hooks: ${label}`);
            if (hookContent === null) continue;
            const hookText = hookContent.toString("utf8");
            if (!isManagedGitHookContent(hookText)) {
              push("warn", `hooks: ${label} is not a managed GSD Path git hook`);
            } else if (
              !INTERPRETER_CANDIDATES.some(
                (candidate) => hookText === generator(candidate)
              )
            ) {
              push("warn", `hooks: ${label} is stale — run --hooks-refresh-full`);
            } else if (!isExecutable(hookPath)) {
              push("warn", `hooks: ${label} is not executable — run --hooks-refresh-full`);
            } else {
              push("ok", `hooks: ${label} wired`);
            }
          }
        }
        if (missingFromCustom) {
          push(
            "warn",
            `hooks: core.hooksPath points this repository at ${hooksDir}, ` +
              "but the guard hooks are not wired there"
          );
        }
      }
    }
  }

  const stateFile = path.join(project, ".project", "STATE.md");
  if (!isDirectory(path.join(project, ".project"))) {
    push("note", "state: no .project/ pipeline state (nothing started yet)");
  } else if (!isFile(stateFile)) {
    push("warn", "state: .project/ exists but STATE.md is missing");
  } else {
    try {
      const state = hooks.validatedProjectState(sourceRoot, project);
      if (!runtimeCurrent) {
        throw new InstallerError(
          "project runtime status was not executed because the installed runtime is not current"
        );
      }
      validateProjectRuntimeStatus(sourceRoot, project);
      if (!projectRuntimeMatches(sourceRoot, project)) {
        throw new InstallerError("project runtime changed during doctor validation");
      }
      push("ok", `state: ${state.phase}/${state.status}`);
    } catch (error) {
      push("fail", `state: ${messageOf(error)}`);
    }
  }
  return findings;
}

export function deploymentPlans(plans) {
  const names = plans.map((plan) => plan.name);
  if (new Set(names).size !== plans.length) {
    throw new InstallerError("each target may be selected only once");
  }
  const unsupported = [...new Set(names.filter((name) => !TARGETS.includes(name)))].sort();
  if (unsupported.length) {
    throw new InstallerError("unsupported target: " + unsupported.join(", "));
  }

  const groups = [];
  for (const plan of plans) {
    const group = groups.find((entries) => samePath(entries[0].root, plan.root));
    if (group) group.push(plan);
    else groups.push([plan]);
  }

  const deployments = [];
  for (const group of groups) {
    const targets = group.map((plan) => plan.name);
    let profile;
    if (group.length > 1) {
      if (!targets.every((name) => SHARED_AGENT_TARGETS.has(name))) {
        throw new InstallerError(
          `only Codex, Antigravity, and Zed may share a skills root: ${targets.join(", ")}`
        );
      }
      profile = SHARED_AGENT_PROFILE;
    } else if (SHARED_AGENT_TARGETS.has(group[0].name)) {
      profile = SHARED_AGENT_PROFILE;
    } else if (samePath(group[0].root, defaultRoot("codex"))) {
      throw new InstallerError(
        `${group[0].name} cannot install a host-specific bundle to the ` +
          "shared ~/.agents/skills root"
      );
    } else {
      profile = group[0].name;
    }
    deployments.push({ profile, root: group[0].root, targets });
  }
  return deployments;
}

function validateDistinctRoots(plans) {
  for (let index = 0; index < plans.length; index += 1) {
    for (const right of plans.slice(index + 1)) {
      const left = plans[index];
      if (pathsOverlap(left.root, right.root)) {
        throw new InstallerError(
          "target roots overlap: " +
            `${left.targets.join("+")}=${left.root}, ` +
            `${right.targets.join("+")}=${right.root}`
        );
      }
    }
  }

  const cursorPlans = plans.filter((plan) => plan.profile === "cursor");
  for (const cursorPlan of cursorPlans) {
    const agentRoot = path.join(path.dirname(cursorPlan.root), "agents");
    if (pathsOverlap(agentRoot, cursorPlan.root)) {
      throw new InstallerError(
        "Cursor skills and agent roots overlap: " +
          `skills=${cursorPlan.root}, agents=${agentRoot}`
      );
    }
    for (const plan of plans) {
      if (plan === cursorPlan) continue;
      if (pathsOverlap(agentRoot, plan.root)) {
        throw new InstallerError(
          "Cursor agent root overlaps a target root: " +
            `cursor=${agentRoot}, ${plan.targets.join("+")}=${plan.root}`
        );
      }
    }
  }
}

function appendHostNotes(results, selected) {
  for (const target of TARGETS) {
    if (selected.includes(target) && HOST_NOTES[target]) {
      results.push(HOST_NOTES[target]);
    }
  }
}

function installResult(plan, dryRun = false, update = false) {
  const verb = update ? "update" : "install";
  const action = dryRun ? `would ${verb}` : `${verb}${update ? "d" : "ed"}`;
  const label = plan.targets.join("+");
  const skillCount = SKILL_NAMES.length;
  if (plan.profile === "cursor") {
    const agent = path.join(path.dirname(plan.root), "agents", CURSOR_AGENT_FILENAME);
    return `${label}: ${action} ${skillCount} skills to ${plan.root} and custom subagent to ${agent}`;
  }
  const shared = plan.profile === SHARED_AGENT_PROFILE ? " shared" : "";
  return `${label}: ${action} ${skillCount}${shared} skills to ${plan.root}`;
}

function managedEntryCount(plan) {
  let count = 0;
  if (isDirectory(plan.root)) {
    count = fs.readdirSync(plan.root).filter((name) => isManagedInstallEntry(plan.root, name)).length;
  }
  if (
    plan.profile === "cursor" &&
    lexists(path.join(path.dirname(plan.root), "agents", CURSOR_AGENT_FILENAME))
  ) {
    count += 1;
  }
  return count;
}

function plannedBackupRoots(legacyRoot, deployments) {
  const transactions = [];
  if (
    legacyRoot !== null &&
    isDirectory(legacyRoot) &&
    fs.readdirSync(legacyRoot).some((name) => isManagedName(name))
  ) {
    transactions.push(["Codex legacy backup", legacyRoot]);
  }
  for (const plan of deployments) {
    if (managedEntryCount(plan)) {
      transactions.push([`${plan.targets.join("+")} backup`, plan.root]);
    }
  }

  const planned = [];
  const reserved = [];
  for (const [label, root] of transactions) {
    const backup = backupPath(root, reserved);
    reserved.push(backup);
    planned.push([label, backup]);
  }
  return planned;
}

// Test-injection points; production callers never touch these.
export const hooks = {
  mismatches,
  applyTarget,
  rename: fs.renameSync.bind(fs),
  renameInstallLock: fs.renameSync.bind(fs),
  renameInstallStage: fs.renameSync.bind(fs),
  validatedProjectState,
  processIdentity,
  reserveDirectory,
  reserveFile,
  detectPythonInterpreter,
  resolveGitHooksPath,
  copyRuntimeFile: fs.copyFileSync.bind(fs),
  copyGuardFile: copyFileAtomic,
};

export async function install(sourceRoot, plans, options = {}) {
  const {
    project = null,
    dryRun = false,
    env = process.env,
    onProgress = null,
    migrateLegacy = true,
    update = false,
    hooks: hooksEnabled = false,
  } = options;
  if (hooksEnabled && project === null) {
    throw new InstallerError("--hooks requires --project");
  }
  const selected = plans.map((plan) => plan.name);
  let interpreter = "python3";
  let hooksDir = null;
  if (project !== null && !hooksEnabled && !dryRun) {
    interpreter = requiredPythonRuntime("--project", selected);
  } else if (hooksEnabled) {
    ({ interpreter, hooksDir } = requiredHookRuntime(project, "--hooks", selected));
  }
  const progress = async (text) => {
    if (onProgress) onProgress(text);
    await tick();
  };
  const deployments = deploymentPlans(plans);
  const adapters = [...new Set(deployments.map((deployment) => deployment.profile))];
  await progress("Validating synchronized package");
  validateSource(sourceRoot, adapters);
  validateDistinctRoots(deployments);
  for (const plan of plans) {
    validateDirectoryDestination(plan.root, `${plan.name} skills root`);
    if (pathsOverlap(plan.root, sourceRoot)) {
      throw new InstallerError(
        `${plan.name} skills root overlaps source repository: ${plan.root}`
      );
    }
  }
  for (const deployment of deployments) {
    if (deployment.profile !== "cursor") continue;
    const cursorAgentRoot = path.join(path.dirname(deployment.root), "agents");
    validateDirectoryDestination(cursorAgentRoot, "Cursor agent root");
    if (pathsOverlap(cursorAgentRoot, sourceRoot)) {
      throw new InstallerError(
        `Cursor agent root overlaps source repository: ${cursorAgentRoot}`
      );
    }
  }
  let legacyRoot = migrateLegacy && selected.includes("codex") ? legacyCodexRoot(env) : null;
  const reservedRoots = deployments.map((plan) => [
    `${plan.targets.join("+")} skills root`,
    plan.root,
  ]);
  for (const plan of deployments) {
    if (plan.profile === "cursor") {
      reservedRoots.push(["Cursor agent root", path.join(path.dirname(plan.root), "agents")]);
    }
  }
  if (legacyRoot !== null) {
    const codexRoots = deployments
      .filter((plan) => plan.targets.includes("codex"))
      .map((plan) => plan.root);
    if (codexRoots.some((root) => samePath(legacyRoot, root))) {
      legacyRoot = null;
    } else if (pathsOverlap(legacyRoot, sourceRoot)) {
      throw new InstallerError(
        `Codex legacy root overlaps source repository: ${legacyRoot}`
      );
    } else {
      for (const [label, root] of reservedRoots) {
        if (pathsOverlap(legacyRoot, root)) {
          throw new InstallerError(
            `Codex legacy root overlaps ${label}: ${legacyRoot}, ${root}`
          );
        }
      }
    }
  }
  if (legacyRoot !== null) {
    validateDirectoryDestination(legacyRoot, "Codex legacy skills root");
  }

  const plannedBackups = plannedBackupRoots(legacyRoot, deployments);
  const mutationRoots = [...reservedRoots];
  if (legacyRoot !== null) {
    mutationRoots.push(["Codex legacy skills root", legacyRoot]);
  }
  for (const [backupLabel, backup] of plannedBackups) {
    for (const [rootLabel, root] of mutationRoots) {
      if (pathsOverlap(backup, root)) {
        throw new InstallerError(`${backupLabel} overlaps ${rootLabel}: ${backup}, ${root}`);
      }
    }
  }

  if (project !== null) {
    validateDirectoryDestination(project, "project path");
    if (dryRun) {
      validateProject(
        sourceRoot,
        project,
        selected,
        hooksEnabled,
        [...mutationRoots, ...plannedBackups],
        interpreter,
        hooksDir,
        update
      );
    }
  }

  const results = [];
  const staging = fs.mkdtempSync(path.join(os.tmpdir(), "gsd-path-install-"));
  try {
    const staged = [];
    for (const [index, plan] of deployments.entries()) {
      await progress(`Staging ${plan.profile} bundle`);
      const stagedRoot = path.join(staging, `${index}-${plan.profile}`);
      staged.push(stagedRoot);
      fs.mkdirSync(stagedRoot);
      stageTarget(sourceRoot, plan.profile, stagedRoot);
    }

    if (dryRun) {
      if (legacyRoot !== null && isDirectory(legacyRoot)) {
        const legacyCount = fs.readdirSync(legacyRoot).filter((name) => isManagedName(name)).length;
        if (legacyCount) {
          results.push(`codex-legacy: would back up ${legacyCount} entries from ${legacyRoot}`);
        }
      }
      for (const plan of deployments) {
        rejectRouterAliasCollisions(plan.root);
        const count = managedEntryCount(plan);
        const suffix = count ? `; would back up ${count} entries` : "";
        results.push(installResult(plan, true, update) + suffix);
      }
      if (project !== null) {
        results.push(projectResult(project, selected, hooksEnabled, interpreter, hooksDir, update, true));
      }
      appendHostNotes(results, selected);
      return results;
    }

    const lockRoots = deployments.map((plan) => plan.root);
    if (legacyRoot !== null && isDirectory(legacyRoot)) lockRoots.push(legacyRoot);
    if (project !== null) lockRoots.push(path.join(project, HOOKS_DIRECTORY));
    const ownership = acquireInstallLocks(lockRoots);
    const targetTransactions = [];
    const projectTransaction = { createdDirectories: [], copied: [], replaced: [] };
    try {
      if (project !== null) {
        validateProject(
          sourceRoot,
          project,
          selected,
          hooksEnabled,
          [...mutationRoots, ...plannedBackups],
          interpreter,
          hooksDir,
          update
        );
      }
      if (legacyRoot !== null && isDirectory(legacyRoot)) {
        await progress("Backing up legacy Codex skills");
        const legacyTransaction = {
          root: legacyRoot,
          createdDirectories: [],
          backup: null,
          moved: [],
          installed: [],
        };
        targetTransactions.push(legacyTransaction);
        backupExisting(legacyTransaction);
        if (legacyTransaction.backup !== null) {
          results.push(
            `codex-legacy: backed up ${legacyTransaction.moved.length} entries to ` +
              `${legacyTransaction.backup}`
          );
        }
      }
      for (const [index, plan] of deployments.entries()) {
        await progress(`Installing ${plan.targets.join("+")} skills`);
        const transaction = {
          root: plan.root,
          createdDirectories: [],
          backup: null,
          moved: [],
          installed: [],
        };
        targetTransactions.push(transaction);
        await hooks.applyTarget(plan, staged[index], transaction);
        results.push(installResult(plan, false, update));
        if (transaction.backup !== null) {
          results.push(
            `${plan.targets.join("+")}: backed up ${transaction.moved.length} entries ` +
              `to ${transaction.backup}`
          );
        }
      }
      if (project !== null) {
        await progress("Writing project contracts");
        const resultLine = projectResult(project, selected, hooksEnabled, interpreter, hooksDir, update, false);
        applyProject(
          sourceRoot,
          project,
          selected,
          hooksEnabled,
          projectTransaction,
          interpreter,
          hooksDir,
          update
        );
        results.push(resultLine);
      }
    } catch (error) {
      const rollbackErrors = [];
      try {
        rollbackProject(projectTransaction);
      } catch (rollbackError) {
        rollbackErrors.push(messageOf(rollbackError));
      }
      for (const transaction of [...targetTransactions].reverse()) {
        try {
          rollbackTarget(transaction);
        } catch (rollbackError) {
          rollbackErrors.push(messageOf(rollbackError));
        }
      }
      const detail = rollbackErrors.length
        ? `; rollback incomplete: ${rollbackErrors.join("; ")}`
        : "";
      throw new InstallerError(
        `installation failed and was rolled back: ${messageOf(error)}${detail}`
      );
    } finally {
      releaseInstallLocks(ownership.locks, ownership.createdDirectories);
    }
  } finally {
    fs.rmSync(staging, { recursive: true, force: true });
  }
  appendHostNotes(results, selected);
  return results;
}

// Documented project-relative skill roots (verified against each host's
// official skills docs). Codex, Zed, and Antigravity all discover the
// project-level .agents/skills standard directory.
export function localRoot(target, projectDir) {
  const relative = LOCAL_ROOTS[target];
  if (!relative) throw new Error(`unsupported target: ${target}`);
  return path.join(absolutePath(projectDir), relative);
}

export function detectInstalls(targets, rootFor) {
  const plans = [];
  for (const target of targets) {
    const root = rootFor(target);
    if (hasManagedInstall(root)) {
      plans.push(targetPlan(target, root));
    }
  }
  return plans;
}

export function parseCli(argv) {
  const options = {
    all: { type: "boolean", default: false },
    update: { type: "boolean", default: false },
    "dry-run": { type: "boolean", default: false },
    local: { type: "boolean", default: false },
    project: { type: "string" },
    doctor: { type: "boolean", default: false },
    hooks: { type: "boolean", default: false },
    "hooks-init": { type: "boolean", default: false },
    "hooks-refresh": { type: "boolean", default: false },
    "hooks-refresh-full": { type: "boolean", default: false },
    "source-root": { type: "string" },
    "no-color": { type: "boolean", default: false },
    help: { type: "boolean", default: false },
  };
  for (const target of TARGETS) {
    options[target] = { type: "boolean", default: false };
    options[`${target}-root`] = { type: "string" };
  }
  return parseArgs({ args: argv, options, allowPositionals: false }).values;
}

function packageVersion() {
  return readPackageVersion(path.join(SCRIPT_DIRECTORY, "..", "package.json")) || "";
}

function makeUi(colorEnabled) {
  const tty = Boolean(process.stdout.isTTY);
  const colored = colorEnabled && tty && !process.env.NO_COLOR;
  const paint = (code) => (text) => (colored ? `\u001b[${code}m${text}\u001b[0m` : text);
  const ui = {
    cyan: paint("36"),
    green: paint("32"),
    red: paint("31"),
    yellow: paint("33"),
    dim: paint("2"),
    bold: paint("1"),
  };
  const frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
  ui.spinner = (initial) => {
    if (!tty) return { update() {}, stop() {} };
    let text = initial;
    let index = 0;
    const render = () => {
      process.stdout.write(`\r\u001b[2K  ${ui.cyan(frames[index])} ${ui.dim(text)}`);
      index = (index + 1) % frames.length;
    };
    render();
    const timer = setInterval(render, 80);
    return {
      update(next) {
        text = next;
      },
      stop() {
        clearInterval(timer);
        process.stdout.write("\r\u001b[2K");
      },
    };
  };
  ui.banner = (mode) => {
    const version = packageVersion();
    const title = ui.bold(ui.cyan("GSD Path")) + ui.dim(` installer${version ? ` v${version}` : ""}`);
    console.log(`\n  ${ui.cyan("✦")} ${title}`);
    console.log(`  ${ui.dim(mode)}\n`);
  };
  ui.result = (line) => {
    if (line.startsWith("note:")) {
      console.log(`  ${ui.yellow("!")} ${ui.dim(line.slice(5).trim())}`);
    } else {
      console.log(`  ${ui.green("✓")} ${line}`);
    }
  };
  ui.error = (message) => {
    console.error(`  ${ui.red("✗")} ${message}`);
  };
  return ui;
}

function usage() {
  const flags = TARGETS.map((target) => `--${target}`).join(" ");
  return (
    "GSD Path installer — multi-host skills and project contracts.\n" +
    "Docs: DOCS.md (hub) · QUICK.md (first run) · FULL.md · UPDATE.md\n\n" +
    "usage: gsd-path            (no flags on a terminal opens the interactive wizard)\n" +
    "       gsd-path [--all] [--update] [--local] [--dry-run] [--project PATH]\n" +
    "              [--hooks] [--hooks-init] [--hooks-refresh] [--hooks-refresh-full] [target flags]\n\n" +
    "  First install:  gsd-path --all --dry-run && gsd-path --all\n" +
    "  New repo:       gsd-path --all --project /path/to/repo\n" +
    "  Update skills:  gsd-path --update   (or npx gsd-path@latest --update)\n\n" +
    `targets: ${flags}\n` +
    "  --update              refresh existing installs in place; with --project also\n" +
    "                        refreshes .gsd-path/ and keeps AGENTS.md/WORKFLOW.md\n" +
    "  --local               install into this project's per-host skill dirs\n" +
    "  --project PATH        write project contracts and status runtime; requires Python 3.9+\n" +
    "  --doctor              read-only health check of installs, hooks, and state\n" +
    "  --hooks               with --project: install guard hooks (see HOOKS.md)\n" +
    "  --hooks-init          add guards to an existing project without changing its contracts\n" +
    "  --hooks-refresh       with --project: overwrite managed .gsd-path scripts\n" +
    "  --hooks-refresh-full  refresh native settings/git hooks; target flags create missing configs\n" +
    "  --dry-run             preview without writing\n" +
    "  each target also accepts --<target>-root PATH to override its skills root"
  );
}

export async function main(argv, env = process.env) {
  let values;
  try {
    values = parseCli(argv);
  } catch (error) {
    console.error(`error: ${error.message}`);
    console.error(usage());
    return 2;
  }
  if (values.help) {
    console.log(usage());
    return 0;
  }
  if (!argv.length && process.stdin.isTTY && process.stdout.isTTY) {
    const { wizard } = await import("./wizard.mjs");
    const chosen = await wizard({
      input: process.stdin,
      output: process.stdout,
      colored: !process.env.NO_COLOR,
      version: packageVersion(),
      targets: TARGETS,
      installed: (target, local) =>
        hasManagedInstall(local ? localRoot(target, process.cwd()) : defaultRoot(target, env)),
    });
    return chosen ? main(chosen, env) : 0;
  }
  const ui = makeUi(!values["no-color"]);
  const sourceRoot = values["source-root"]
    ? absolutePath(values["source-root"])
    : path.resolve(SCRIPT_DIRECTORY, "..");
  const project =
    values.project !== undefined ? absolutePath(values.project) : null;
  const local = values.local;
  const rootFor = (target) => {
    const override = values[`${target}-root`];
    if (override !== undefined) return absolutePath(override);
    return local ? localRoot(target, process.cwd()) : defaultRoot(target, env);
  };
  if (values.doctor) {
    const named = TARGETS.filter((target) => values[target]);
    const targets = named.length && !values.all ? named : [...TARGETS];
    ui.banner(`doctor · ${local ? "project" : "global"} installs${project ? ` · ${project}` : ""}`);
    const findings = doctor(sourceRoot, { targets, rootFor, project });
    for (const { level, text } of findings) {
      if (level === "fail") ui.error(text);
      else ui.result(level === "ok" ? text : `note: ${text}`);
    }
    const failed = findings.filter(({ level }) => level === "fail").length;
    console.log(`\n  ${ui.dim(failed ? `${failed} problem${failed === 1 ? "" : "s"} found.` : "Healthy.")}\n`);
    return failed ? 1 : 0;
  }
  const hooksInit = values["hooks-init"];
  const hooksRefresh = values["hooks-refresh"] || values["hooks-refresh-full"];
  if (hooksInit || hooksRefresh) {
    if (project === null) {
      ui.error(`${hooksInit ? "--hooks-init" : "--hooks-refresh"} requires --project`);
      return 2;
    }
    const selected = TARGETS.filter((target) => values.all || values[target]);
    if (hooksInit && !selected.length) {
      ui.error("--hooks-init requires at least one target or --all");
      return 2;
    }
    const refreshMode =
      `hooks ${hooksInit ? "initialization" : "refresh"} for ${project}` +
      (values["dry-run"] ? " · dry run" : "");
    ui.banner(refreshMode);
    const spin = ui.spinner("Validating synchronized package");
    try {
      const problems = hooks.mismatches(sourceRoot);
      if (problems.length) {
        throw new InstallerError("source resources are stale: " + problems.join("; "));
      }
      spin.update("Refreshing guard scripts");
      const refreshed = refreshHooks(
        sourceRoot,
        project,
        hooksInit || values["hooks-refresh-full"],
        values["dry-run"],
        selected,
        hooksInit
      );
      spin.stop();
      const notes = refreshed.filter((line) => line.startsWith("note:"));
      const files = refreshed.filter((line) => !line.startsWith("note:"));
      ui.result(
        values["dry-run"]
          ? `hooks: would ${hooksInit ? "initialize" : "refresh"} ${files.join(", ")}`
          : `hooks: ${hooksInit ? "initialized" : "refreshed"} ${files.join(", ")}`
      );
      for (const note of notes) ui.result(note);
      console.log(
        `\n  ${ui.dim(values["dry-run"] ? "Dry run — nothing was written." : "Done.")}\n`
      );
    } catch (error) {
      spin.stop();
      if (error instanceof InstallerError) {
        ui.error(error.message);
        return 1;
      }
      throw error;
    }
    return 0;
  }
  let selected = TARGETS.filter((target) => values.all || values[target]);
  if (!selected.length) {
    if (values.update) {
      selected = [...TARGETS];
    } else {
      console.error("error: select at least one target or --all");
      console.error(usage());
      return 2;
    }
  }
  const sourceRootForInstall = sourceRoot;
  const scope = local ? `project ${values.update ? "update in" : "install into"} ${process.cwd()}` : `global ${values.update ? "update" : "install"}`;
  const mode = scope + (values["dry-run"] ? " · dry run" : "");
  ui.banner(mode);
  let plans;
  if (values.update) {
    plans = detectInstalls(selected, rootFor);
    if (!plans.length) {
      ui.error(
        `no existing GSD Path skills found to update (${local ? "this project" : "global roots"}); ` +
          "run an install first, e.g. --all" + (local ? " --local" : "")
      );
      return 1;
    }
  } else {
    plans = selected.map((target) => targetPlan(target, rootFor(target)));
  }
  const spin = ui.spinner("Preparing");
  try {
    const results = await install(sourceRootForInstall, plans, {
      project,
      dryRun: values["dry-run"],
      env,
      migrateLegacy: !local,
      update: values.update,
      hooks: values.hooks,
      onProgress: (text) => spin.update(text),
    });
    spin.stop();
    for (const result of results) {
      ui.result(result);
    }
    const closing = values["dry-run"]
      ? "Dry run — nothing was written."
      : values.update
        ? "Updated. Previous copies are in each root's disabled-gsd-skills backup."
        : "Done. Restart active agent sessions, then invoke the router explicitly.";
    console.log(`\n  ${ui.dim(closing)}\n`);
  } catch (error) {
    spin.stop();
    if (error instanceof InstallerError) {
      ui.error(error.message);
      return 1;
    }
    throw error;
  }
  return 0;
}

const invokedDirectly = (() => {
  if (!process.argv[1]) return false;
  try {
    return import.meta.url === pathToFileURL(fs.realpathSync(process.argv[1])).href;
  } catch {
    return false;
  }
})();
if (invokedDirectly) {
  process.exit(await main(process.argv.slice(2)));
}
