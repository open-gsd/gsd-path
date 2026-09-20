import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { detectBumpLevel, nextVersion } from "../scripts/bump_version.mjs";

test("detectBumpLevel maps conventional commits to semver increments", () => {
  assert.equal(
    detectBumpLevel([{ subject: "feat: add dashboard", body: "" }]),
    "minor"
  );
  assert.equal(
    detectBumpLevel([{ subject: "fix: guard regression", body: "" }]),
    "patch"
  );
  assert.equal(
    detectBumpLevel([{ subject: "feat!: remove legacy API", body: "" }]),
    "major"
  );
  assert.equal(
    detectBumpLevel([{ subject: "feat: add setting", body: "BREAKING CHANGE: rename flag" }]),
    "major"
  );
  assert.equal(detectBumpLevel([], "minor"), "minor");
});

test("detectBumpLevel ignores merge commits and non-release work", () => {
  assert.throws(
    () => detectBumpLevel([{ subject: "Merge pull request #1 from org/branch", body: "" }]),
    /no releasable conventional commits/
  );
  assert.throws(
    () => detectBumpLevel([{ subject: "docs: refresh README", body: "" }]),
    /no releasable conventional commits/
  );
});

test("nextVersion increments major, minor, and patch from the base version", () => {
  assert.deepEqual(
    nextVersion({
      from: "1.1.0",
      bump: "auto",
      commits: [{ subject: "feat: add settings", body: "" }],
    }),
    { level: "minor", current: "1.1.0", next: "1.2.0" }
  );
  assert.deepEqual(
    nextVersion({
      from: "1.1.0",
      bump: "auto",
      commits: [{ subject: "fix: guard regression", body: "" }],
    }),
    { level: "patch", current: "1.1.0", next: "1.1.1" }
  );
  assert.deepEqual(
    nextVersion({
      from: "1.1.0",
      bump: "major",
      commits: [],
    }),
    { level: "major", current: "1.1.0", next: "2.0.0" }
  );
});


test("candidate preparation retries reuse an unpublished version", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "bump-retry-"));
  try {
    fs.mkdirSync(path.join(dir, "scripts"));
    fs.copyFileSync(new URL("../scripts/bump_version.mjs", import.meta.url), path.join(dir, "scripts/bump_version.mjs"));
    fs.writeFileSync(path.join(dir, "package.json"), JSON.stringify({ name: "fixture", version: "1.1.0" }));
    fs.writeFileSync(path.join(dir, "package-lock.json"), JSON.stringify({ name: "fixture", version: "1.1.0", lockfileVersion: 3, packages: { "": { name: "fixture", version: "1.1.0" } } }));
    const env = { ...process.env, GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1",
      GIT_AUTHOR_NAME: "Test", GIT_AUTHOR_EMAIL: "test@example.invalid",
      GIT_COMMITTER_NAME: "Test", GIT_COMMITTER_EMAIL: "test@example.invalid" };
    const run = (exe, args) => {
      const result = spawnSync(exe, args, { cwd: dir, env, encoding: "utf8" });
      assert.equal(result.status, 0, result.stderr); return result.stdout;
    };
    run("git", ["init", "-q"]); run("git", ["add", "."]); run("git", ["commit", "-qm", "fixture"]);
    run("git", ["tag", "v1.1.0"]); run("git", ["commit", "--allow-empty", "-qm", "feat: candidate"]);
    run(process.execPath, ["scripts/bump_version.mjs"]);
    const candidate = fs.readFileSync(path.join(dir, "package.json"), "utf8");
    const lock = fs.readFileSync(path.join(dir, "package-lock.json"), "utf8");
    assert.equal(JSON.parse(candidate).version, "1.2.0");
    run(process.execPath, ["scripts/bump_version.mjs"]);
    assert.equal(fs.readFileSync(path.join(dir, "package.json"), "utf8"), candidate);
    assert.equal(fs.readFileSync(path.join(dir, "package-lock.json"), "utf8"), lock);
    run(process.execPath, ["scripts/bump_version.mjs", "--from", "1.2.0", "--bump", "patch"]);
    assert.equal(JSON.parse(fs.readFileSync(path.join(dir, "package.json"))).version, "1.2.1");
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
