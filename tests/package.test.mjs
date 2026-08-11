import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";


const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");


test("npm package includes the repository bootstrap helper", () => {
  const output = execFileSync("npm", ["pack", "--dry-run", "--json"], {
    cwd: projectRoot,
    encoding: "utf8",
  });
  const [{ files }] = JSON.parse(output);
  const packagedPaths = new Set(files.map((entry) => entry.path));

  assert.ok(packagedPaths.has("scripts/bootstrap_repository.py"));
  assert.ok(packagedPaths.has("skills/gsd-path/scripts/bootstrap_repository.py"));
  for (const canonical of ["inspect", "define", "decide", "roadmap", "ship"]) {
    assert.ok(packagedPaths.has(`skills/gsd-path-${canonical}/SKILL.md`));
  }
  for (const removed of ["onboard", "grill", "synthesize", "review"]) {
    assert.ok(!packagedPaths.has(`skills/gsd-path-${removed}/SKILL.md`));
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
  const manifest = JSON.parse(
    execFileSync(process.execPath, ["-e", "process.stdout.write(require('fs').readFileSync('scripts/skill-resources.json'))"], {
      cwd: projectRoot,
      encoding: "utf8",
    })
  );
  const packageJson = JSON.parse(
    execFileSync(process.execPath, ["-e", "process.stdout.write(require('fs').readFileSync('package.json'))"], {
      cwd: projectRoot,
      encoding: "utf8",
    })
  );

  assert.deepEqual(packageJson.files, manifest.package_files);
});
