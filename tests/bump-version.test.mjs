import assert from "node:assert/strict";
import test from "node:test";
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
