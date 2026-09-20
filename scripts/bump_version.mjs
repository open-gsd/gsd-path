#!/usr/bin/env node
/**
 * Compute and apply the next semver from conventional commits or an explicit bump.
 *
 * Usage:
 *   node scripts/bump_version.mjs --bump auto
 *   node scripts/bump_version.mjs --bump minor --dry-run
 *   node scripts/bump_version.mjs --from 1.1.0 --bump patch
 */

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const packagePath = path.join(root, "package.json");

const BUMP_LEVELS = new Set(["auto", "major", "minor", "patch"]);

function parseArgs(argv) {
  const options = {
    bump: "auto",
    from: null,
    dryRun: false,
    githubOutput: null,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--bump") {
      options.bump = argv[index + 1];
      index += 1;
      continue;
    }
    if (arg === "--from") {
      options.from = argv[index + 1];
      index += 1;
      continue;
    }
    if (arg === "--dry-run") {
      options.dryRun = true;
      continue;
    }
    if (arg === "--github-output") {
      options.githubOutput = argv[index + 1];
      index += 1;
      continue;
    }
    if (arg === "-h" || arg === "--help") {
      process.stdout.write(
        "Usage: node scripts/bump_version.mjs [--bump auto|major|minor|patch] [--from X.Y.Z] [--dry-run] [--github-output FILE]\n"
      );
      process.exit(0);
    }
    throw new Error(`unknown argument: ${arg}`);
  }

  if (!BUMP_LEVELS.has(options.bump)) {
    throw new Error(`invalid bump level: ${options.bump}`);
  }

  return options;
}

function git(...args) {
  return execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();
}

function readPackageVersion() {
  return JSON.parse(fs.readFileSync(packagePath, "utf8")).version;
}

function latestTag() {
  try {
    return git("tag", "--list", "v*", "--sort=-v:refname").split("\n").find(Boolean) ?? null;
  } catch {
    return null;
  }
}

function parseVersion(version) {
  const match = /^(\d+)\.(\d+)\.(\d+)/.exec(version);
  if (!match) {
    throw new Error(`invalid semver version: ${version}`);
  }
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
  };
}

function formatVersion(parts) {
  return `${parts.major}.${parts.minor}.${parts.patch}`;
}

function increment(parts, level) {
  if (level === "major") {
    return { major: parts.major + 1, minor: 0, patch: 0 };
  }
  if (level === "minor") {
    return { major: parts.major, minor: parts.minor + 1, patch: 0 };
  }
  return { major: parts.major, minor: parts.minor, patch: parts.patch + 1 };
}

function compareVersions(left, right) {
  const a = parseVersion(left);
  const b = parseVersion(right);
  if (a.major !== b.major) return a.major - b.major;
  if (a.minor !== b.minor) return a.minor - b.minor;
  return a.patch - b.patch;
}

function baseVersion(explicitFrom) {
  const packageVersion = readPackageVersion();
  const tag = latestTag();
  const taggedVersion = tag ? tag.slice(1) : null;

  if (explicitFrom) {
    return explicitFrom;
  }

  if (taggedVersion && compareVersions(packageVersion, taggedVersion) > 0) {
    return packageVersion;
  }

  return taggedVersion ?? packageVersion;
}

function commitsSinceTag(tag) {
  const range = tag ? `${tag}..HEAD` : "HEAD";
  const output = git("log", range, "--pretty=format:%s%n%b%n----COMMIT----");
  if (!output) {
    return [];
  }

  return output
    .split("----COMMIT----")
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((chunk) => {
      const [subject = "", ...bodyParts] = chunk.split("\n");
      return { subject, body: bodyParts.join("\n").trim() };
    });
}

function isMergeCommit(subject) {
  const lower = subject.toLowerCase();
  return /^merge pull request\b/.test(lower) || /^merge branch\b/.test(lower) || /^merge remote-tracking\b/.test(lower);
}

function isBreaking({ subject, body }) {
  if (/^(\w+)(\(.*\))?!:/.test(subject)) {
    return true;
  }
  return /(^|\n)BREAKING CHANGE:/.test(body);
}

function commitKind(subject) {
  const lower = subject.toLowerCase();
  if (isMergeCommit(subject)) {
    return null;
  }
  if (/^feat(\(|:)/.test(lower)) {
    return "minor";
  }
  if (/^(fix|perf)(\(|:)/.test(lower)) {
    return "patch";
  }
  if (/^no-mistakes\((feat|fix|perf)\)/.test(lower)) {
    const match = /^no-mistakes\((\w+)\)/.exec(lower);
    return match?.[1] === "feat" ? "minor" : "patch";
  }
  return null;
}

export function detectBumpLevel(commits, requested = "auto") {
  if (requested !== "auto") {
    return requested;
  }

  let level = null;

  for (const commit of commits) {
    if (isBreaking(commit)) {
      return "major";
    }
    const kind = commitKind(commit.subject);
    if (kind === "minor") {
      level = "minor";
      continue;
    }
    if (kind === "patch" && !level) {
      level = "patch";
    }
  }

  if (!level) {
    throw new Error("no releasable conventional commits since the previous tag; use --bump major, minor, or patch");
  }

  return level;
}

export function nextVersion({ from, bump, commits }) {
  const level = detectBumpLevel(commits, bump);
  const current = parseVersion(from);
  const bumped = increment(current, level);
  return {
    level,
    current: formatVersion(current),
    next: formatVersion(bumped),
  };
}

function writeGithubOutput(filePath, values) {
  const lines = Object.entries(values).map(([key, value]) => `${key}=${value}\n`);
  fs.appendFileSync(filePath, lines.join(""));
}

function applyVersion(version) {
  execFileSync("npm", ["version", version, "--no-git-tag-version", "--allow-same-version"], {
    cwd: root,
    stdio: "inherit",
  });
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const tag = latestTag();
  const from = baseVersion(options.from);
  const commits = commitsSinceTag(tag);
  const result = nextVersion({ from, bump: options.bump, commits });

  if (compareVersions(result.next, result.current) <= 0) {
    throw new Error(`requested bump would not advance version beyond ${result.current}`);
  }

  if (options.dryRun) {
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    return;
  }

  if (result.next !== readPackageVersion()) {
    applyVersion(result.next);
  }

  process.stdout.write(`${result.next}\n`);

  if (options.githubOutput) {
    writeGithubOutput(options.githubOutput, {
      version: result.next,
      tag: `v${result.next}`,
      bump: result.level,
      from: result.current,
    });
  }
}

const modulePath = fileURLToPath(import.meta.url);
if (process.argv[1] === modulePath) {
  main();
}
