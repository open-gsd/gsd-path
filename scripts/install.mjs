#!/usr/bin/env node
// Install GSD Path skills for supported coding agents (Node port of install.py).
// Dependency-free; requires Node >= 18.17.

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath, pathToFileURL } from "node:url";

export const TARGETS = [
  "codex",
  "claude",
  "grok",
  "opencode",
  "copilot",
  "qwen",
  "antigravity",
  "cursor",
  "zed",
  "kiro",
  "kimi",
];
export const CLAUDE_BRIDGE = "@../AGENTS.md\n@../WORKFLOW.md\n";
export const HOOKS_DIRECTORY = ".gsd-path";
export const GUARD_SCRIPTS = ["guard_hook.py", "git_guard.py"];
export const GUARD_MARKER = "gsd-path guard";
export const CLAUDE_MATCHER =
  "Edit|Write|MultiEdit|NotebookEdit|Delete|StrReplace|ApplyPatch|Create|Shell|Bash";
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
export function preCommitHook(interpreter) {
  return (
    "#!/bin/sh\n" +
    "# gsd-path guard: archive immutability before commit.\n" +
    `exec ${interpreter} "$(git rev-parse --show-toplevel)/${HOOKS_DIRECTORY}/git_guard.py" pre-commit\n`
  );
}
export function commitMsgHook(interpreter) {
  return (
    "#!/bin/sh\n" +
    "# gsd-path guard: archive immutability and ship-commit purity.\n" +
    `exec ${interpreter} "$(git rev-parse --show-toplevel)/${HOOKS_DIRECTORY}/git_guard.py" commit-msg "$1"\n`
  );
}

// Every interpreter a managed hook may legitimately be pinned to.
const INTERPRETER_CANDIDATES = ["python3", "python"];

// Probe for a runnable Python interpreter (python3, then python) so emitted
// hooks never hard-code an interpreter that does not exist on this machine
// (python3 is typically absent on Windows).
export function detectPythonInterpreter() {
  for (const candidate of INTERPRETER_CANDIDATES) {
    const result = spawnSync(candidate, ["--version"], { stdio: "ignore" });
    if (!result.error && result.status === 0) return candidate;
  }
  return null;
}

// Single owner of the interpreter probe and its policy: returns the probed
// interpreter, or null when no interpreter works — callers must then skip
// writing hook content instead of pinning a nonexistent python3.
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
  const dotGit = path.join(project, ".git");
  if (!lexists(dotGit)) return null;
  const resolved = hooks.resolveGitHooksPath(project);
  if (resolved !== null) return resolved;
  // Fallback when git is not runnable: only a plain .git directory is safe.
  return isDirectory(dotGit) ? path.join(dotGit, "hooks") : null;
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
const SHARED_AGENT_TARGETS = new Set(["codex", "zed"]);
export const SHARED_AGENT_PROFILE = "shared-agents";
export const CURSOR_AGENT_FILENAME = "gsd-path.md";
export const CURSOR_AGENT_BACKUP_NAME = "cursor-agent-gsd-path.md";

const SCRIPT_DIRECTORY = path.dirname(fileURLToPath(import.meta.url));

// Single source of truth for the resource tables, shared with
// sync_skill_resources.py and shipped in the npm package.
const MANIFEST = JSON.parse(
  fs.readFileSync(path.join(SCRIPT_DIRECTORY, "skill-resources.json"), "utf8")
);
export function skillNamesForManifest(manifest) {
  return [...manifest.skills];
}

export const SKILL_NAMES = skillNamesForManifest(MANIFEST);
export const SKILL_ALIASES = { ...MANIFEST.skill_aliases };
const PHASE_RESOURCES = MANIFEST.phase_resources;
const SCRIPT_TARGETS = MANIFEST.script_targets;
const PHASE_CONTRACT_TARGETS = MANIFEST.phase_contract_targets;
const SHARED_DISPATCH_TARGETS = MANIFEST.shared_dispatch_targets;

export class InstallerError extends Error {}

const tick = () => new Promise((resolve) => setImmediate(resolve));

const messageOf = (error) => String(error && error.message ? error.message : error);

function readPackageVersion(manifest) {
  try {
    return JSON.parse(fs.readFileSync(manifest, "utf8")).version || null;
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
    normalized.startsWith("ogsd-") ||
    normalized.startsWith("gsd-path-")
  );
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
    ...[...Object.keys(PHASE_RESOURCES), ...Object.keys(SKILL_ALIASES)].sort(),
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
  for (const [source, destination] of pairs) {
    if (!isFile(source)) {
      problems.push(`missing canonical resource: ${path.relative(root, source)}`);
    } else if (!isFile(destination)) {
      problems.push(`missing generated resource: ${path.relative(root, destination)}`);
    } else if (!fs.readFileSync(source).equals(fs.readFileSync(destination))) {
      problems.push(`stale generated resource: ${path.relative(root, destination)}`);
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
    .filter((name) => isManagedName(name) && name.startsWith("gsd-path"));
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

  const version = readPackageVersion(path.join(sourceRoot, "package.json"));
  if (version) {
    fs.writeFileSync(path.join(stagedRoot, "gsd-path", "VERSION"), `${version}\n`);
  }

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
    const invocation =
      target === "opencode" || target === SHARED_AGENT_PROFILE ? "gsd-path" : "/gsd-path";
    for (const name of SKILL_NAMES) {
      const entrypoint = path.join(stagedRoot, name, "SKILL.md");
      fs.writeFileSync(entrypoint, augmentFrontmatter(fs.readFileSync(entrypoint, "utf8"), target));
    }
    for (const markdown of markdownFiles(stagedRoot)) {
      const content = fs.readFileSync(markdown, "utf8");
      fs.writeFileSync(markdown, content.replaceAll("$gsd-path", invocation));
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
    .filter((name) => isManagedName(name))
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
    transaction.installed.push(destination);
    fs.cpSync(path.join(stagedRoot, name), destination, { recursive: true, errorOnExist: true, force: false });
    await tick();
  }
  if (cursorAgent !== null) {
    transaction.installed.push(cursorAgent);
    fs.copyFileSync(path.join(stagedRoot, CURSOR_AGENT_FILENAME), cursorAgent);
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
function projectDestinations(project, includeClaude, hooksEnabled, interpreter, hooksDir) {
  const destinations = [
    [path.join(project, "AGENTS.md"), "AGENTS.md", null, false],
    [path.join(project, "WORKFLOW.md"), "WORKFLOW.md", null, false],
  ];
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
    if (hooksDir !== null) {
      destinations.push([
        path.join(hooksDir, "pre-commit"),
        null,
        preCommitHook(interpreter),
        true,
      ]);
      destinations.push([
        path.join(hooksDir, "commit-msg"),
        null,
        commitMsgHook(interpreter),
        true,
      ]);
    }
  }
  return destinations;
}

function describeProjectPath(project, destination) {
  const relative = path.relative(project, destination);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    return destination.split(path.sep).join("/");
  }
  return relative.split(path.sep).join("/");
}

function projectFiles(project, includeClaude, hooksEnabled, interpreter, hooksDir) {
  return projectDestinations(project, includeClaude, hooksEnabled, interpreter, hooksDir)
    .map(([destination]) => describeProjectPath(project, destination))
    .join(", ");
}

function existingContractError(destination) {
  return new InstallerError(
    `project contract already exists: ${destination} — the installer never ` +
      "overwrites project files. Run --update to refresh installed skills; " +
      "merge template changes manually (see UPDATE.md)."
  );
}

function validateProject(sourceRoot, project, includeClaude, hooksEnabled, reservedRoots, interpreter, hooksDir) {
  validateDirectoryDestination(project, "project path");
  const sources = ["AGENTS.md", "WORKFLOW.md"];
  if (hooksEnabled) {
    sources.push(...GUARD_SCRIPTS.map((name) => path.join("scripts", name)));
  }
  for (const sourceName of sources) {
    const source = path.join(sourceRoot, sourceName);
    if (isSymlink(source) || !isFile(source)) {
      throw new InstallerError(`missing project contract: ${source}`);
    }
  }
  for (const [destination] of projectDestinations(project, includeClaude, hooksEnabled, interpreter, hooksDir)) {
    if (lexists(destination)) {
      throw existingContractError(destination);
    }
    for (const [label, root] of reservedRoots) {
      if (pathsOverlap(destination, root)) {
        throw new InstallerError(`project contract overlaps ${label}: ${destination}, ${root}`);
      }
    }
  }
  const claudeDirectory = path.join(project, ".claude");
  if (
    includeClaude &&
    lexists(claudeDirectory) &&
    (isSymlink(claudeDirectory) || !isDirectory(claudeDirectory))
  ) {
    throw new InstallerError(`unsafe Claude project directory: ${claudeDirectory}`);
  }
}

function applyProject(sourceRoot, project, includeClaude, hooksEnabled, transaction, interpreter, hooksDir) {
  createDirectory(project, transaction.createdDirectories);
  for (const [destination, sourceName, literal, executable] of projectDestinations(
    project,
    includeClaude,
    hooksEnabled,
    interpreter,
    hooksDir
  )) {
    createDirectory(path.dirname(destination), transaction.createdDirectories);
    const content = sourceName
      ? fs.readFileSync(path.join(sourceRoot, sourceName))
      : Buffer.from(literal, "utf8");
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
  for (const destination of [...transaction.copied].reverse()) {
    removePath(destination);
  }
  removeEmptyDirectories(transaction.createdDirectories);
}

function isManagedGuardScript(destination) {
  if (!isFile(destination)) return false;
  return fs.readFileSync(destination, "utf8").includes(GUARD_MARKER);
}

function isManagedGitHook(destination) {
  if (!isFile(destination)) return false;
  const text = fs.readFileSync(destination, "utf8");
  return text.includes(GUARD_MARKER) && text.includes("git_guard.py");
}

function isManagedClaudeSettings(destination) {
  if (!isFile(destination)) return false;
  const text = fs.readFileSync(destination, "utf8");
  return text.includes("guard_hook.py") && text.includes(HOOKS_DIRECTORY);
}

function temporaryPathFor(destination) {
  return path.join(
    path.dirname(destination),
    `.${path.basename(destination)}.gsd-path-tmp`
  );
}

function writeFileAtomic(destination, content, mode) {
  const temporary = temporaryPathFor(destination);
  try {
    fs.writeFileSync(temporary, content);
    if (mode !== undefined) {
      fs.chmodSync(temporary, mode);
    } else if (isFile(destination) && !isSymlink(destination)) {
      fs.chmodSync(temporary, fs.statSync(destination).mode & 0o777);
    }
    fs.renameSync(temporary, destination);
  } catch (error) {
    removePath(temporary);
    throw error;
  }
}

function copyFileAtomic(source, destination) {
  const temporary = temporaryPathFor(destination);
  try {
    fs.copyFileSync(source, temporary);
    fs.renameSync(temporary, destination);
  } catch (error) {
    removePath(temporary);
    throw error;
  }
}

// A PreToolUse entry is ours when one of its commands runs the guard hook.
function isManagedHookEntry(entry) {
  return Boolean(
    entry &&
      typeof entry === "object" &&
      !Array.isArray(entry) &&
      Array.isArray(entry.hooks) &&
      entry.hooks.some(
        (hook) =>
          hook &&
          typeof hook.command === "string" &&
          hook.command.includes(`${HOOKS_DIRECTORY}/guard_hook.py`)
      )
  );
}

function mergedClaudeSettings(settings, interpreter) {
  let parsed;
  try {
    parsed = JSON.parse(fs.readFileSync(settings, "utf8"));
  } catch {
    throw new InstallerError(
      `managed hook settings file is not valid JSON: ${settings}`
    );
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new InstallerError(
      `managed hook settings file is not a JSON object: ${settings}`
    );
  }
  // Merge: replace only the managed PreToolUse guard entry; preserve every
  // other hook event (Stop, PostToolUse, ...) and user PreToolUse entries.
  const managedEntry = claudeGuardEntry(interpreter);
  const hooksObject =
    parsed.hooks && typeof parsed.hooks === "object" && !Array.isArray(parsed.hooks)
      ? parsed.hooks
      : {};
  const existing = Array.isArray(hooksObject.PreToolUse) ? hooksObject.PreToolUse : [];
  const merged = [];
  let replaced = false;
  for (const entry of existing) {
    if (isManagedHookEntry(entry)) {
      if (!replaced) {
        merged.push(managedEntry);
        replaced = true;
      }
    } else {
      merged.push(entry);
    }
  }
  if (!replaced) merged.push(managedEntry);
  hooksObject.PreToolUse = merged;
  parsed.hooks = hooksObject;
  return JSON.stringify(parsed, null, 2) + "\n";
}

function validateHooksRefresh(sourceRoot, project, full, hooksDir) {
  validateDirectoryDestination(project, "project path");
  for (const name of GUARD_SCRIPTS) {
    const destination = path.join(project, HOOKS_DIRECTORY, name);
    if (isSymlink(destination)) {
      throw new InstallerError(`refusing to refresh a symlink: ${destination}`);
    }
    if (!isManagedGuardScript(destination)) {
      throw new InstallerError(`not a managed GSD Path guard script: ${destination}`);
    }
    const source = path.join(sourceRoot, "scripts", name);
    if (isSymlink(source) || !isFile(source)) {
      throw new InstallerError(`missing guard script source: ${source}`);
    }
  }
  if (full) {
    const settings = path.join(project, ".claude", "settings.json");
    if (isSymlink(settings)) {
      throw new InstallerError(`refusing to refresh a symlink: ${settings}`);
    }
    if (lexists(settings) && !isManagedClaudeSettings(settings)) {
      throw new InstallerError(`not a managed GSD Path hook settings file: ${settings}`);
    }
    if (hooksDir !== null) {
      for (const hookName of ["pre-commit", "commit-msg"]) {
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

// Returns refreshed project-relative paths; entries prefixed "note:" are
// user-facing notes rather than refreshed files.
function refreshHooks(sourceRoot, project, full, dryRun) {
  const hooksDir = full ? gitHooksDirectory(project) : null;
  validateHooksRefresh(sourceRoot, project, full, hooksDir);
  const refreshed = [];
  for (const name of GUARD_SCRIPTS) {
    const destination = path.join(project, HOOKS_DIRECTORY, name);
    const source = path.join(sourceRoot, "scripts", name);
    if (!dryRun) copyFileAtomic(source, destination);
    refreshed.push(describeProjectPath(project, destination));
  }
  if (full) {
    // Dry-run only lists paths, so it never needs the interpreter probe.
    const interpreter = dryRun ? null : effectiveInterpreter();
    if (!dryRun && interpreter === null) {
      refreshed.push(
        "note: hooks: no working python3 or python interpreter found on PATH; " +
          "skipped Claude settings and git hook refresh"
      );
      return refreshed;
    }
    const settings = path.join(project, ".claude", "settings.json");
    if (lexists(settings)) {
      if (!dryRun) writeFileAtomic(settings, mergedClaudeSettings(settings, interpreter));
      refreshed.push(describeProjectPath(project, settings));
    }
    if (hooksDir !== null) {
      for (const hookName of ["pre-commit", "commit-msg"]) {
        const hookPath = path.join(hooksDir, hookName);
        if (!dryRun) {
          const content =
            hookName === "pre-commit" ? preCommitHook(interpreter) : commitMsgHook(interpreter);
          fs.mkdirSync(path.dirname(hookPath), { recursive: true });
          writeFileAtomic(hookPath, content, 0o755);
        }
        refreshed.push(describeProjectPath(project, hookPath));
      }
    }
  }
  return refreshed;
}

const PIPELINE_MARKER = "gsd-path/v2";

function stateFrontmatter(text) {
  const lines = splitLines(text);
  if (lines[0] !== "---") return null;
  const values = {};
  for (const line of lines.slice(1)) {
    if (line === "---") return values;
    const match = /^([a-z_]+):\s*([^#]*?)(?:\s+#.*)?$/.exec(line);
    if (match) values[match[1]] = match[2].trim().replace(/^["']|["']$/g, "");
  }
  return null;
}

function hasManagedInstall(root) {
  return isDirectory(root) && fs.readdirSync(root).some((name) => isManagedName(name));
}

function isExecutable(candidate) {
  try {
    return (fs.statSync(candidate).mode & 0o111) !== 0;
  } catch {
    return false;
  }
}

// Read-only health check: host installs, project contracts, guard hooks,
// and pipeline state. Never writes.
export function doctor(sourceRoot, { targets, rootFor, project = null }) {
  const findings = [];
  const push = (level, text) => findings.push({ level, text });
  const version = readPackageVersion(path.join(sourceRoot, "package.json"));

  const seen = [];
  for (const target of targets) {
    const root = rootFor(target);
    const prior = seen.find(([, other]) => samePath(other, root));
    if (prior) {
      push("note", `${target}: shares ${prior[0]}'s skills root`);
      continue;
    }
    seen.push([target, root]);
    if (!hasManagedInstall(root)) {
      push("note", `${target}: not installed (${root})`);
      continue;
    }
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

  for (const name of ["AGENTS.md", "WORKFLOW.md"]) {
    if (isFile(path.join(project, name))) push("ok", `project: ${name} present`);
    else push("fail", `project: missing contract ${name} — run --project "${project}"`);
  }
  const bridge = path.join(project, ".claude", "CLAUDE.md");
  if (!isFile(bridge)) {
    push("note", "project: no .claude/CLAUDE.md bridge (only written for --claude installs)");
  } else if (fs.readFileSync(bridge, "utf8") === CLAUDE_BRIDGE) {
    push("ok", "project: .claude/CLAUDE.md bridge present");
  } else {
    push("note", "project: .claude/CLAUDE.md exists but is not the managed bridge");
  }

  if (!isDirectory(path.join(project, HOOKS_DIRECTORY))) {
    push("note", "hooks: guard hooks not installed (opt in with --hooks; see HOOKS.md)");
  } else {
    for (const name of GUARD_SCRIPTS) {
      const destination = path.join(project, HOOKS_DIRECTORY, name);
      if (!isFile(destination)) {
        push("fail", `hooks: missing ${HOOKS_DIRECTORY}/${name} — run --hooks-refresh`);
        continue;
      }
      const content = fs.readFileSync(destination);
      if (!content.toString("utf8").includes(GUARD_MARKER)) {
        push("warn", `hooks: ${HOOKS_DIRECTORY}/${name} is not a managed guard script`);
      } else if (!content.equals(fs.readFileSync(path.join(sourceRoot, "scripts", name)))) {
        push("warn", `hooks: ${HOOKS_DIRECTORY}/${name} is stale — run --hooks-refresh`);
      } else {
        push("ok", `hooks: ${HOOKS_DIRECTORY}/${name} current`);
      }
    }
    // Staleness must not depend on which interpreter wins today's probe: a
    // hook legitimately installed with any known interpreter is current.
    const managedVariants = INTERPRETER_CANDIDATES.map((candidate) =>
      JSON.stringify(claudeGuardEntry(candidate))
    );
    const settings = path.join(project, ".claude", "settings.json");
    if (!isFile(settings)) {
      push("note", "hooks: no .claude/settings.json guard wiring");
    } else if (!isManagedClaudeSettings(settings)) {
      push("warn", "hooks: .claude/settings.json is not the managed guard wiring");
    } else {
      let hooksCurrent = false;
      try {
        const parsed = JSON.parse(fs.readFileSync(settings, "utf8"));
        const entries =
          parsed && typeof parsed === "object" && parsed.hooks
            ? parsed.hooks.PreToolUse
            : null;
        hooksCurrent =
          Array.isArray(entries) &&
          entries.some((entry) => managedVariants.includes(JSON.stringify(entry)));
      } catch {
        hooksCurrent = false;
      }
      if (hooksCurrent) {
        push("ok", "hooks: .claude/settings.json guard wiring present");
      } else {
        push("warn", "hooks: .claude/settings.json guard wiring is stale — run --hooks-refresh-full");
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
        for (const [hookName, generator] of [
          ["pre-commit", preCommitHook],
          ["commit-msg", commitMsgHook],
        ]) {
          const hookPath = path.join(hooksDir, hookName);
          const label = describeProjectPath(project, hookPath);
          if (!lexists(hookPath)) {
            push(
              "fail",
              `hooks: ${hookName} is missing from the effective git hooks directory ` +
                `${hooksDir} — run --hooks-refresh-full`
            );
            if (custom) missingFromCustom = true;
          } else if (!isManagedGitHook(hookPath)) {
            push("warn", `hooks: ${label} is not a managed GSD Path git hook`);
          } else if (
            !INTERPRETER_CANDIDATES.some(
              (candidate) => fs.readFileSync(hookPath, "utf8") === generator(candidate)
            )
          ) {
            push("warn", `hooks: ${label} is stale — run --hooks-refresh-full`);
          } else if (!isExecutable(hookPath)) {
            push("warn", `hooks: ${label} is not executable — run --hooks-refresh-full`);
          } else {
            push("ok", `hooks: ${label} wired`);
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
    const values = stateFrontmatter(fs.readFileSync(stateFile, "utf8"));
    if (values === null) {
      push("fail", "state: STATE.md frontmatter is malformed");
    } else if (values.pipeline !== PIPELINE_MARKER) {
      push("fail", `state: STATE.md has the wrong pipeline marker (${values.pipeline || "<missing>"})`);
    } else if (!values.phase || !values.status) {
      push("fail", "state: STATE.md is missing phase or status");
    } else {
      push("ok", `state: ${values.phase}/${values.status}`);
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
          `only Codex and Zed may share a skills root: ${targets.join(", ")}`
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
    count = fs.readdirSync(plan.root).filter((name) => isManagedName(name)).length;
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
  detectPythonInterpreter,
  resolveGitHooksPath,
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
  // Resolve per-run environment facts (interpreter, git hooks directory)
  // once here and thread them down.
  let effectiveHooks = hooksEnabled;
  let interpreter = "python3";
  let hooksDir = null;
  const hookNotes = [];
  if (hooksEnabled) {
    const probed = effectiveInterpreter();
    if (probed === null) {
      effectiveHooks = false;
      hookNotes.push(
        "note: hooks: no working python3 or python interpreter found on PATH; " +
          "skipped guard hook install"
      );
    } else {
      interpreter = probed;
    }
  }
  if (effectiveHooks) {
    hooksDir = gitHooksDirectory(project);
    if (hooksDir === null && lexists(path.join(project, ".git"))) {
      hookNotes.push(
        "note: hooks: found .git but could not resolve the git hooks directory " +
          "(is git runnable?); git hooks were not installed"
      );
    }
  }
  const progress = async (text) => {
    if (onProgress) onProgress(text);
    await tick();
  };
  const selected = plans.map((plan) => plan.name);
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
  const includeClaude = selected.includes("claude");
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
    validateProject(
      sourceRoot,
      project,
      includeClaude,
      effectiveHooks,
      [...mutationRoots, ...plannedBackups],
      interpreter,
      hooksDir
    );
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
        const count = managedEntryCount(plan);
        const suffix = count ? `; would back up ${count} entries` : "";
        results.push(installResult(plan, true, update) + suffix);
      }
      if (project !== null) {
        const files = projectFiles(project, includeClaude, effectiveHooks, interpreter, hooksDir);
        results.push(`project: would copy ${files} to ${project}`);
      }
      results.push(...hookNotes);
      appendHostNotes(results, selected);
      return results;
    }

    const targetTransactions = [];
    const projectTransaction = { createdDirectories: [], copied: [] };
    try {
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
        applyProject(
          sourceRoot,
          project,
          includeClaude,
          effectiveHooks,
          projectTransaction,
          interpreter,
          hooksDir
        );
        const files = projectFiles(project, includeClaude, effectiveHooks, interpreter, hooksDir);
        results.push(`project: copied ${files} to ${project}`);
      }
      results.push(...hookNotes);
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
export const LOCAL_ROOTS = {
  codex: ".agents/skills",
  claude: ".claude/skills",
  grok: ".grok/skills",
  opencode: ".opencode/skills",
  copilot: ".github/skills",
  qwen: ".qwen/skills",
  antigravity: ".agents/skills",
  cursor: ".cursor/skills",
  zed: ".agents/skills",
  kiro: ".kiro/skills",
  kimi: ".kimi-code/skills",
};

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
    "usage: gsd-path            (no flags on a terminal opens the interactive wizard)\n"
    + "       gsd-path [--all] [--update] [--local] [--dry-run] [--project PATH]\n" +
    "              [--hooks] [--hooks-refresh] [--hooks-refresh-full] [target flags]\n\n" +
    "  First install:  gsd-path --all --dry-run && gsd-path --all\n" +
    "  New repo:       gsd-path --all --project /path/to/repo\n" +
    "  Update skills:  gsd-path --update   (or npx gsd-path@latest --update)\n\n" +
    `targets: ${flags}\n` +
    "  --update              refresh existing installs in place\n" +
    "  --local               install into this project's per-host skill dirs\n" +
    "  --project PATH        also write AGENTS.md and WORKFLOW.md into PATH\n" +
    "  --doctor              read-only health check of installs, hooks, and state\n" +
    "  --hooks               with --project: install guard hooks (see HOOKS.md)\n" +
    "  --hooks-refresh       with --project: overwrite managed .gsd-path scripts\n" +
    "  --hooks-refresh-full  also refresh managed Claude settings and git hooks\n" +
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
  const hooksRefresh = values["hooks-refresh"] || values["hooks-refresh-full"];
  if (hooksRefresh) {
    if (project === null) {
      ui.error("--hooks-refresh requires --project");
      return 2;
    }
    const refreshMode =
      `hooks refresh for ${project}` + (values["dry-run"] ? " · dry run" : "");
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
        values["hooks-refresh-full"],
        values["dry-run"]
      );
      spin.stop();
      const notes = refreshed.filter((line) => line.startsWith("note:"));
      const files = refreshed.filter((line) => !line.startsWith("note:"));
      ui.result(
        values["dry-run"]
          ? `hooks: would refresh ${files.join(", ")}`
          : `hooks: refreshed ${files.join(", ")}`
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
  const extraNotes = [];
  if (
    selected.includes("antigravity") &&
    ["codex", "zed"].some(
      (target) =>
        selected.includes(target) && samePath(rootFor(target), rootFor("antigravity"))
    )
  ) {
    selected = selected.filter((target) => target !== "antigravity");
    extraNotes.push(
      "note: antigravity reads the same project .agents/skills directory " +
        "installed for codex/zed; skipped installing a second bundle there."
    );
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
    for (const result of [...results, ...extraNotes]) {
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
