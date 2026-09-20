import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const script = path.join(root, "scripts/update_release_docs.mjs");

function runInTempRepo(args) {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "release-docs-"));
  try {
    execFileSync("git", ["init", "-b", "main"], { cwd: tempRoot, stdio: "pipe" });
    execFileSync("git", ["config", "user.email", "test@example.com"], { cwd: tempRoot, stdio: "pipe" });
    execFileSync("git", ["config", "user.name", "Test"], { cwd: tempRoot, stdio: "pipe" });

    fs.mkdirSync(path.join(tempRoot, "scripts"), { recursive: true });
    fs.copyFileSync(script, path.join(tempRoot, "scripts/update_release_docs.mjs"));
    fs.writeFileSync(
      path.join(tempRoot, "package.json"),
      JSON.stringify({ name: "@opengsd/gsd-path", version: "1.2.0" }, null, 2) + "\n"
    );
    fs.writeFileSync(
      path.join(tempRoot, "README.md"),
      "# Demo\n\n<!-- release-docs -->\nold\n<!-- /release-docs -->\n"
    );
    fs.writeFileSync(path.join(tempRoot, "CHANGELOG.md"), "# Changelog\n\n");

    execFileSync("git", ["add", "."], { cwd: tempRoot, stdio: "pipe" });
    execFileSync("git", ["commit", "-m", "feat: initial feature"], { cwd: tempRoot, stdio: "pipe" });
    execFileSync("git", ["tag", "-a", "v1.1.0", "-m", "v1.1.0"], { cwd: tempRoot, stdio: "pipe" });
    execFileSync("git", ["commit", "--allow-empty", "-m", "fix: patch release item"], { cwd: tempRoot, stdio: "pipe" });
    execFileSync("git", ["tag", "-a", "v1.2.0", "-m", "v1.2.0"], { cwd: tempRoot, stdio: "pipe" });

    execFileSync(process.execPath, [path.join(tempRoot, "scripts/update_release_docs.mjs"), ...args], {
      cwd: tempRoot,
      stdio: "pipe",
    });

    return {
      changelog: fs.readFileSync(path.join(tempRoot, "CHANGELOG.md"), "utf8"),
      readme: fs.readFileSync(path.join(tempRoot, "README.md"), "utf8"),
      notes: execFileSync(
        process.execPath,
        [path.join(tempRoot, "scripts/update_release_docs.mjs"), "--version", "1.2.0", "--notes-only"],
        { cwd: tempRoot, encoding: "utf8" }
      ),
    };
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
}

test("update_release_docs writes changelog and README release section", () => {
  const result = runInTempRepo(["--version", "1.2.0", "--previous-tag", "v1.1.0"]);
  assert.match(result.changelog, /## \[1\.2\.0\] - /);
  assert.match(result.changelog, /### Fixed/);
  assert.match(result.changelog, /patch release item/);
  assert.match(result.readme, /Latest npm release:\*\* \[@opengsd\/gsd-path@1\.2\.0\]/);
  assert.match(result.readme, /Recent highlights/);
  assert.match(result.notes, /## \[1\.2\.0\]/);
  assert.match(result.notes, /Published to npm as `@opengsd\/gsd-path@1\.2\.0`/);
});

test("README contains release documentation markers", () => {
  const readme = fs.readFileSync(path.join(root, "README.md"), "utf8");
  assert.match(readme, /<!-- release-docs -->/);
  assert.match(readme, /<!-- \/release-docs -->/);
});

test("package manifest includes CHANGELOG.md", () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "scripts/skill-resources.json"), "utf8"));
  assert.ok(packageJson.files.includes("CHANGELOG.md"));
  assert.ok(manifest.package_files.includes("CHANGELOG.md"));
});
