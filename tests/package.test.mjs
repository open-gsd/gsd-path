import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";


const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");


function resourceManifest() {
  return JSON.parse(
    readFileSync(path.join(projectRoot, "scripts/skill-resources.json"), "utf8")
  );
}


test("npm package includes the pipeline helpers", () => {
  const output = execFileSync("npm", ["pack", "--dry-run", "--json"], {
    cwd: projectRoot,
    encoding: "utf8",
  });
  const [{ files }] = JSON.parse(output);
  const packagedPaths = new Set(files.map((entry) => entry.path));
  const manifest = resourceManifest();

  for (const helper of [
    "bootstrap_repository.py",
    "build_state.py",
    "pipeline_state.py",
  ]) {
    assert.ok(packagedPaths.has(`scripts/${helper}`));
    assert.ok(packagedPaths.has(`skills/gsd-path/scripts/${helper}`));
  }
  assert.ok(packagedPaths.has("skills/gsd-path-build/scripts/build_state.py"));
  assert.ok(packagedPaths.has("skills/gsd-path-build/scripts/pipeline_state.py"));
  for (const canonical of ["inspect", "define", "decide", "roadmap", "ship"]) {
    assert.ok(packagedPaths.has(`skills/gsd-path-${canonical}/SKILL.md`));
  }
  for (const removed of ["onboard", "grill", "synthesize", "review"]) {
    assert.ok(!packagedPaths.has(`skills/gsd-path-${removed}/SKILL.md`));
  }
  for (const [, target] of manifest.script_targets) {
    assert.ok(packagedPaths.has(target), `missing packaged helper: ${target}`);
  }
});

test("every copied Python helper imports from its own bundle", (context) => {
  const scratch = mkdtempSync(path.join(tmpdir(), "gsd-path-helper-imports-"));
  context.after(() => rmSync(scratch, { recursive: true, force: true }));
  const targets = [...new Set(resourceManifest().script_targets.map(([, target]) => target))];

  for (const target of targets) {
    execFileSync("python3", [path.join(projectRoot, target), "--help"], {
      cwd: scratch,
      encoding: "utf8",
      env: { ...process.env, PYTHONNOUSERSITE: "1", PYTHONPATH: "" },
      stdio: "pipe",
    });
  }
});

test("plugin manifest conforms to the Agent Plugins specification", () => {
  const output = execFileSync("npm", ["pack", "--dry-run", "--json"], {
    cwd: projectRoot,
    encoding: "utf8",
  });
  const [{ files }] = JSON.parse(output);
  assert.ok(files.some((entry) => entry.path === "plugin.json"));

  const manifest = JSON.parse(
    execFileSync(process.execPath, ["-e", "process.stdout.write(require('fs').readFileSync('plugin.json'))"], {
      cwd: projectRoot,
      encoding: "utf8",
    })
  );
  const allowed = new Set([
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "extensions",
  ]);
  assert.equal(
    manifest.$schema,
    "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
  );
  assert.equal(manifest.name, "gsd-path");
  assert.match(manifest.name, /^[a-z0-9]([a-z0-9.-]{0,62}[a-z0-9])?$/);
  assert.ok(!manifest.name.includes("--") && !manifest.name.includes(".."));
  for (const key of Object.keys(manifest)) {
    assert.ok(allowed.has(key), `unknown plugin manifest field: ${key}`);
  }
});

test("npm package file policy is owned by the resource manifest", () => {
  const manifest = resourceManifest();
  const packageJson = JSON.parse(
    execFileSync(process.execPath, ["-e", "process.stdout.write(require('fs').readFileSync('package.json'))"], {
      cwd: projectRoot,
      encoding: "utf8",
    })
  );

  assert.deepEqual(packageJson.files, manifest.package_files);
});

test("npm verify runs every local verification suite", () => {
  const packageJson = JSON.parse(
    execFileSync(process.execPath, ["-e", "process.stdout.write(require('fs').readFileSync('package.json'))"], {
      cwd: projectRoot,
      encoding: "utf8",
    })
  );

  assert.equal(
    packageJson.scripts["test:python"],
    "python3 -m unittest discover -s tests"
  );
  assert.equal(
    packageJson.scripts.verify,
    "npm test && npm run test:python && python3 scripts/sync_skill_resources.py --check"
  );
});
