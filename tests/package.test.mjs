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
  for (const canonical of ["inspect", "define", "decide", "ship"]) {
    assert.ok(packagedPaths.has(`skills/gsd-path-${canonical}/SKILL.md`));
  }
  for (const alias of ["onboard", "grill", "synthesize", "review"]) {
    assert.ok(packagedPaths.has(`skills/gsd-path-${alias}/SKILL.md`));
    assert.ok(packagedPaths.has(`skills/gsd-path-${alias}/CANONICAL.md`));
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
