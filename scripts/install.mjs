#!/usr/bin/env node
// Install GSD Path skills for supported coding agents (Node port of install.py).
// Dependency-free; requires Node >= 18.17.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";

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
export const SKILL_NAMES = [
  "gsd-path",
  "gsd-path-build",
  "gsd-path-docs-audit",
  "gsd-path-grill",
  "gsd-path-onboard",
  "gsd-path-plan",
  "gsd-path-research",
  "gsd-path-review",
  "gsd-path-synthesize",
];
export const CLAUDE_BRIDGE = "@../AGENTS.md\n@../WORKFLOW.md\n";
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

const SCRIPT_DIRECTORY = path.dirname(new URL(import.meta.url).pathname);

// Single source of truth for the resource tables, shared with
// sync_skill_resources.py and shipped in the npm package.
const MANIFEST = JSON.parse(
  fs.readFileSync(path.join(SCRIPT_DIRECTORY, "skill-resources.json"), "utf8")
);
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
      "expected exactly nine GSD Path skills; found " + [...found].sort().join(", ")
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

function projectDestinations(project, includeClaude) {
  const destinations = [
    [path.join(project, "AGENTS.md"), "AGENTS.md"],
    [path.join(project, "WORKFLOW.md"), "WORKFLOW.md"],
  ];
  if (includeClaude) destinations.push([path.join(project, ".claude", "CLAUDE.md"), ""]);
  return destinations;
}

function validateProject(sourceRoot, project, includeClaude, reservedRoots) {
  validateDirectoryDestination(project, "project path");
  for (const sourceName of ["AGENTS.md", "WORKFLOW.md"]) {
    const source = path.join(sourceRoot, sourceName);
    if (isSymlink(source) || !isFile(source)) {
      throw new InstallerError(`missing project contract: ${source}`);
    }
  }
  for (const [destination] of projectDestinations(project, includeClaude)) {
    if (lexists(destination)) {
      throw new InstallerError(`project contract already exists: ${destination}`);
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

function applyProject(sourceRoot, project, includeClaude, transaction) {
  createDirectory(project, transaction.createdDirectories);
  if (includeClaude) {
    createDirectory(path.join(project, ".claude"), transaction.createdDirectories);
  }
  for (const [destination, sourceName] of projectDestinations(project, includeClaude)) {
    const content = sourceName
      ? fs.readFileSync(path.join(sourceRoot, sourceName))
      : Buffer.from(CLAUDE_BRIDGE, "utf8");
    let fd = null;
    try {
      fd = fs.openSync(destination, "wx");
      fs.writeSync(fd, content);
      fs.closeSync(fd);
      fd = null;
      transaction.copied.push(destination);
    } catch (error) {
      if (fd !== null) fs.closeSync(fd);
      if (error && error.code === "EEXIST") {
        throw new InstallerError(`project contract already exists: ${destination}`);
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
  if (plan.profile === "cursor") {
    const agent = path.join(path.dirname(plan.root), "agents", CURSOR_AGENT_FILENAME);
    return `${label}: ${action} 9 skills to ${plan.root} and custom subagent to ${agent}`;
  }
  const shared = plan.profile === SHARED_AGENT_PROFILE ? " shared" : "";
  return `${label}: ${action} 9${shared} skills to ${plan.root}`;
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
export const hooks = { mismatches, applyTarget, rename: fs.renameSync.bind(fs) };

export async function install(sourceRoot, plans, options = {}) {
  const {
    project = null,
    dryRun = false,
    env = process.env,
    onProgress = null,
    migrateLegacy = true,
    update = false,
  } = options;
  const progress = async (text) => {
    if (onProgress) onProgress(text);
    await tick();
  };
  const selected = plans.map((plan) => plan.name);
  const deployments = deploymentPlans(plans);
  const adapters = [...selected];
  for (const deployment of deployments) {
    if (!adapters.includes(deployment.profile)) adapters.push(deployment.profile);
  }
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
    validateProject(sourceRoot, project, includeClaude, [...mutationRoots, ...plannedBackups]);
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
        let files = "AGENTS.md, WORKFLOW.md";
        if (includeClaude) files += ", .claude/CLAUDE.md";
        results.push(`project: would copy ${files} to ${project}`);
      }
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
        applyProject(sourceRoot, project, includeClaude, projectTransaction);
        let files = "AGENTS.md, WORKFLOW.md";
        if (includeClaude) files += ", .claude/CLAUDE.md";
        results.push(`project: copied ${files} to ${project}`);
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
    if (isDirectory(root) && fs.readdirSync(root).some((name) => isManagedName(name))) {
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
    "usage: gsd-path [--all] [--update] [--local] [--dry-run] [--project PATH] [target flags]\n" +
    `targets: ${flags}\n` +
    "  --update         refresh existing GSD Path installs in place; detects\n" +
    "                   which hosts have the skills (combine with --local for\n" +
    "                   the current project, or target flags to narrow)\n" +
    "  --local          install into the current project's per-host skill\n" +
    "                   directories instead of the global user roots\n" +
    "  --project PATH   also write AGENTS.md/WORKFLOW.md contracts into PATH\n" +
    "  --dry-run        preview every change without writing anything\n" +
    "each target also accepts --<target>-root PATH to override its skills root"
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
  const ui = makeUi(!values["no-color"]);
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
  const local = values.local;
  const rootFor = (target) => {
    const override = values[`${target}-root`];
    if (override !== undefined) return absolutePath(override);
    return local ? localRoot(target, process.cwd()) : defaultRoot(target, env);
  };
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

  const sourceRoot = values["source-root"]
    ? absolutePath(values["source-root"])
    : path.resolve(SCRIPT_DIRECTORY, "..");
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
  const project = values.project !== undefined ? absolutePath(values.project) : null;
  const spin = ui.spinner("Preparing");
  try {
    const results = await install(sourceRoot, plans, {
      project,
      dryRun: values["dry-run"],
      env,
      migrateLegacy: !local,
      update: values.update,
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
