#!/usr/bin/env node
/**
 * Update CHANGELOG.md and the README release section from git history.
 *
 * Usage:
 *   node scripts/update_release_docs.mjs --version 1.2.0
 *   node scripts/update_release_docs.mjs --version 1.2.0 --notes-only
 *   node scripts/update_release_docs.mjs --version 1.2.0 --dry-run
 */

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const changelogPath = path.join(root, "CHANGELOG.md");
const readmePath = path.join(root, "README.md");
const packagePath = path.join(root, "package.json");

const MARKER_START = "<!-- release-docs -->";
const MARKER_END = "<!-- /release-docs -->";
const CHANGELOG_HEADER = `# Changelog

All notable changes to [@opengsd/gsd-path](https://www.npmjs.com/package/@opengsd/gsd-path)
are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

`;

const SECTION_ORDER = ["Added", "Changed", "Fixed", "Security", "Deprecated", "Removed", "Other"];

function parseArgs(argv) {
  const options = {
    version: null,
    dryRun: false,
    notesOnly: false,
    previousTag: null,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--version") {
      options.version = argv[index + 1];
      index += 1;
      continue;
    }
    if (arg === "--previous-tag") {
      options.previousTag = argv[index + 1];
      index += 1;
      continue;
    }
    if (arg === "--dry-run") {
      options.dryRun = true;
      continue;
    }
    if (arg === "--notes-only") {
      options.notesOnly = true;
      continue;
    }
    if (arg === "-h" || arg === "--help") {
      process.stdout.write(`Usage: node scripts/update_release_docs.mjs --version <semver> [--previous-tag vX.Y.Z] [--dry-run] [--notes-only]\n`);
      process.exit(0);
    }
    throw new Error(`unknown argument: ${arg}`);
  }

  if (!options.version) {
    options.version = JSON.parse(fs.readFileSync(packagePath, "utf8")).version;
  }

  if (!/^[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.-]+)?$/.test(options.version)) {
    throw new Error(`invalid semver version: ${options.version}`);
  }

  return options;
}

function git(...args) {
  return execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();
}

function previousTagFor(version, explicitPreviousTag) {
  if (explicitPreviousTag) {
    return explicitPreviousTag;
  }

  const currentTag = `v${version}`;
  const tags = git("tag", "--list", "v*", "--sort=-v:refname")
    .split("\n")
    .filter(Boolean);

  for (const tag of tags) {
    if (tag !== currentTag) {
      return tag;
    }
  }

  return null;
}

function releaseDateFor(version) {
  const tag = `v${version}`;
  try {
    git("rev-parse", "--verify", `refs/tags/${tag}`);
    return git("log", "-1", "--format=%cs", tag);
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function normalizeSubject(subject) {
  return subject
    .replace(/^no-mistakes\([^)]+\):\s*/i, "")
    .replace(/^(feat|fix|docs|document|ci|test|chore|refactor|perf|build)(\([^)]+\))?:\s*/i, "")
    .trim();
}

function categorizeSubject(subject) {
  const lower = subject.toLowerCase();
  if (/^merge pull request\b/.test(lower) || /^merge branch\b/.test(lower)) {
    return null;
  }
  if (/^feat(\(|:|\b)/.test(lower)) {
    return "Added";
  }
  if (/^fix(\(|:|\b)/.test(lower)) {
    return "Fixed";
  }
  if (/^security(\(|:|\b)/.test(lower)) {
    return "Security";
  }
  if (/^(docs|document)(\(|:|\b)/.test(lower)) {
    return "Changed";
  }
  if (/^deprecated(\(|:|\b)/.test(lower)) {
    return "Deprecated";
  }
  if (/^removed(\(|:|\b)/.test(lower)) {
    return "Removed";
  }
  if (/^no-mistakes\((document|docs)\)/.test(lower)) {
    return "Changed";
  }
  if (/^no-mistakes\((ci|test|review)\)/.test(lower)) {
    return "Other";
  }
  return "Changed";
}

function commitsSinceTag(previousTag) {
  const range = previousTag ? `${previousTag}..HEAD` : "HEAD";
  const output = git("log", range, "--pretty=format:%s");
  if (!output) {
    return [];
  }

  const seen = new Set();
  const commits = [];

  for (const subject of output.split("\n")) {
    const category = categorizeSubject(subject);
    if (!category) {
      continue;
    }
    const normalized = normalizeSubject(subject);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    commits.push({ category, text: normalized });
  }

  return commits;
}

function buildSections(commits) {
  const sections = new Map(SECTION_ORDER.map((name) => [name, []]));

  for (const commit of commits) {
    sections.get(commit.category).push(commit.text);
  }

  return sections;
}

function anchorFor(version, date) {
  return `${version.replace(/\./g, "")}---${date}`;
}

function formatEntry(version, date, sections) {
  const lines = [`## [${version}] - ${date}`, ""];

  for (const name of SECTION_ORDER) {
    const items = sections.get(name);
    if (!items?.length) {
      continue;
    }
    lines.push(`### ${name}`);
    for (const item of items) {
      lines.push(`- ${item}`);
    }
    lines.push("");
  }

  return `${lines.join("\n").trimEnd()}\n`;
}

function upsertChangelog(version, entry) {
  const headerPattern = /^## \[/;
  let content = fs.existsSync(changelogPath)
    ? fs.readFileSync(changelogPath, "utf8")
    : CHANGELOG_HEADER;

  if (!content.startsWith("# Changelog")) {
    content = CHANGELOG_HEADER + content.trimStart();
  }

  const versionHeader = `## [${version}]`;
  if (content.includes(`${versionHeader} -`)) {
    const pattern = new RegExp(`${versionHeader} - [0-9-]+\\n[\\s\\S]*?(?=\\n## \\[|$)`);
    content = content.replace(pattern, entry.trimEnd());
  } else {
    const splitIndex = content.search(headerPattern);
    if (splitIndex === -1) {
      content = `${content.trimEnd()}\n\n${entry}`;
    } else {
      content = `${content.slice(0, splitIndex).trimEnd()}\n\n${entry}${content.slice(splitIndex)}`;
    }
  }

  return content.endsWith("\n") ? content : `${content}\n`;
}

function extractHighlights(sections, limit = 5) {
  const preferred = ["Added", "Fixed", "Changed", "Security"];
  const highlights = [];

  for (const name of preferred) {
    for (const item of sections.get(name)) {
      highlights.push(item);
      if (highlights.length >= limit) {
        return highlights;
      }
    }
  }

  for (const name of SECTION_ORDER) {
    for (const item of sections.get(name)) {
      if (highlights.includes(item)) {
        continue;
      }
      highlights.push(item);
      if (highlights.length >= limit) {
        return highlights;
      }
    }
  }

  return highlights;
}

function updateReadme(version, date, highlights) {
  const readme = fs.readFileSync(readmePath, "utf8");
  const start = readme.indexOf(MARKER_START);
  const end = readme.indexOf(MARKER_END);

  if (start === -1 || end === -1 || end < start) {
    throw new Error(`README.md is missing ${MARKER_START} / ${MARKER_END} markers`);
  }

  const anchor = anchorFor(version, date);
  const npmUrl = `https://www.npmjs.com/package/@opengsd/gsd-path/v/${version}`;
  const lines = [
    MARKER_START,
    `**Latest npm release:** [@opengsd/gsd-path@${version}](${npmUrl}) — [release notes](CHANGELOG.md#${anchor})`,
    "",
  ];

  if (highlights.length > 0) {
    lines.push("**Recent highlights**");
    for (const item of highlights) {
      lines.push(`- ${item}`);
    }
    lines.push("");
  }

  lines.push(MARKER_END);
  const replacement = `${lines.join("\n")}\n`;

  return `${readme.slice(0, start)}${replacement}${readme.slice(end + MARKER_END.length).replace(/^\n/, "")}`;
}

function extractReleaseNotes(changelog, version) {
  const pattern = new RegExp(`## \\[${version}\\] - [0-9-]+\\n[\\s\\S]*?(?=\\n## \\[|$)`);
  const match = changelog.match(pattern);
  if (!match) {
    throw new Error(`changelog entry for ${version} not found`);
  }
  return match[0].trim();
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const previousTag = previousTagFor(options.version, options.previousTag);
  const date = releaseDateFor(options.version);
  const commits = commitsSinceTag(previousTag);
  const sections = buildSections(commits);
  const entry = formatEntry(options.version, date, sections);

  if (options.notesOnly) {
    const changelog = upsertChangelog(options.version, entry);
    process.stdout.write(`${extractReleaseNotes(changelog, options.version)}\n\nPublished to npm as \`@opengsd/gsd-path@${options.version}\`.\n`);
    return;
  }

  const changelog = upsertChangelog(options.version, entry);
  const readme = updateReadme(options.version, date, extractHighlights(sections));

  if (options.dryRun) {
    process.stdout.write(changelog);
    process.stdout.write("\n--- README ---\n");
    process.stdout.write(readme);
    return;
  }

  fs.writeFileSync(changelogPath, changelog);
  fs.writeFileSync(readmePath, readme);
}

main();
