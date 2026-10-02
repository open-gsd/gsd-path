import assert from "node:assert/strict";
import { execFileSync, execSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { findPython } from "../scripts/dev/py.mjs";


const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PYTHON = findPython() ?? ["python3"];


// npm is npm.cmd on Windows, which only cmd.exe can start. The name stays
// unquoted: cmd.exe resolves a quoted batch name's %~dp0 to the current
// directory, so npm.cmd would look for npm-cli.js there.
function npm(args, options) {
  if (process.platform !== "win32") return execFileSync("npm", args, options);
  return execSync(["npm", ...args.map((arg) => `"${arg}"`)].join(" "), options);
}


function python(args, options) {
  const [command, ...prefix] = PYTHON;
  return execFileSync(command, [...prefix, ...args], options);
}


function resourceManifest() {
  return JSON.parse(
    readFileSync(path.join(projectRoot, "scripts/skill-resources.json"), "utf8")
  );
}


function normalizedScriptGraph(packageJson, scriptName) {
  return packageJson.scripts[scriptName].split(/\s*&&\s*/).map((command) => {
    const [executable, ...args] = command.trim().split(/\s+/);
    if (executable === "npm" && args.length === 1 && args[0] === "test") {
      return { script: "test" };
    }
    if (executable === "npm" && args[0] === "run" && args.length === 2) {
      return { script: args[1] };
    }
    return { executable, args };
  });
}


test("npm package includes the pipeline helpers", () => {
  const output = npm(["pack", "--dry-run", "--json"], {
    cwd: projectRoot,
    encoding: "utf8",
  });
  const [{ files }] = JSON.parse(output);
  const packagedPaths = new Set(files.map((entry) => entry.path));
  const manifest = resourceManifest();
  const forbiddenPaths = [...packagedPaths].filter(
    (entry) => entry.split("/").includes("__pycache__") || entry.endsWith(".pyc")
  );

  assert.deepEqual(forbiddenPaths, []);

  for (const helper of [
    "bootstrap_repository.py",
    "build_state.py",
    "pipeline_state.py",
  ]) {
    assert.ok(packagedPaths.has(`scripts/${helper}`));
    assert.ok(packagedPaths.has(`skills/gsd-path/scripts/${helper}`));
  }
  assert.ok(packagedPaths.has("scripts/status_runtime.py"));
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

test("npm tarball excludes ignored cache contents and Python bytecode beneath whitelisted skills", (context) => {
  const scratch = mkdtempSync(path.join(tmpdir(), "gsd-path-package-bytecode-"));
  const destination = path.join(scratch, "dist");
  mkdirSync(destination);
  context.after(() => rmSync(scratch, { recursive: true, force: true }));

  const packageJson = JSON.parse(readFileSync(path.join(projectRoot, "package.json"), "utf8"));
  assert.ok(packageJson.files.includes("skills/"));
  writeFileSync(
    path.join(scratch, "package.json"),
    `${JSON.stringify({ name: packageJson.name, version: packageJson.version, files: packageJson.files }, null, 2)}\n`
  );
  writeFileSync(
    path.join(scratch, ".gitignore"),
    `${readFileSync(path.join(projectRoot, ".gitignore"), "utf8")}*.pyc\n`
  );

  const skillRoot = "skills/gsd-path-build";
  const ordinaryFile = `${skillRoot}/SKILL.md`;
  const ignoredArtifacts = [
    `${skillRoot}/__pycache__/publisher.cpython-312.pyc`,
    `${skillRoot}/__pycache__/publisher-cache-sentinel.txt`,
    `${skillRoot}/references/__pycache__/nested.cpython-312.pyc`,
    `${skillRoot}/scripts/publisher-helper.pyc`,
  ];
  for (const relativePath of [ordinaryFile, ...ignoredArtifacts]) {
    const absolutePath = path.join(scratch, relativePath);
    mkdirSync(path.dirname(absolutePath), { recursive: true });
    writeFileSync(absolutePath, "fixture");
  }

  execFileSync("git", ["init", "--quiet", "--initial-branch=main"], { cwd: scratch });
  const ignoredPaths = execFileSync("git", ["check-ignore", ...ignoredArtifacts], {
    cwd: scratch,
    encoding: "utf8",
  }).trim().split(/\r?\n/);
  assert.deepEqual(ignoredPaths, ignoredArtifacts);

  const output = npm(
    ["pack", "--ignore-scripts", "--json", "--pack-destination", destination],
    { cwd: scratch, encoding: "utf8" }
  );
  const [{ filename }] = JSON.parse(output);
  const entries = execFileSync("tar", ["-tzf", filename], {
    cwd: destination,
    encoding: "utf8",
  }).trim().split(/\r?\n/);
  const packagedPaths = entries.map((entry) => entry.replace(/^package\//, ""));
  assert.ok(packagedPaths.includes(ordinaryFile));
  assert.deepEqual(
    packagedPaths.filter((entry) => entry.split("/").includes("__pycache__") || entry.endsWith(".pyc")),
    []
  );
});

test("packed Python installer starts with only packaged files", (context) => {
  const scratch = mkdtempSync(path.join(tmpdir(), "gsd-path-package-"));
  context.after(() => rmSync(scratch, { recursive: true, force: true }));
  const output = npm(
    ["pack", "--ignore-scripts", "--json", "--pack-destination", scratch],
    { cwd: projectRoot, encoding: "utf8" }
  );
  const [{ filename }] = JSON.parse(output);
  // A bare name: GNU tar (Git for Windows) reads "C:" in a path as a remote host.
  execFileSync("tar", ["-xzf", filename], { cwd: scratch });

  python([path.join(scratch, "package", "scripts", "install.py"), "--help"], {
    cwd: scratch,
    encoding: "utf8",
    env: { ...process.env, PYTHONNOUSERSITE: "1", PYTHONPATH: "" },
    stdio: "pipe",
  });
});

test("every copied Python helper imports from its own bundle", (context) => {
  const scratch = mkdtempSync(path.join(tmpdir(), "gsd-path-helper-imports-"));
  context.after(() => rmSync(scratch, { recursive: true, force: true }));
  const targets = [...new Set(resourceManifest().script_targets.map(([, target]) => target))];

  for (const target of targets) {
    const isGitGuard = path.basename(target) === "git_guard.py";
    const cwd = isGitGuard ? mkdtempSync(path.join(scratch, "git-guard-")) : scratch;
    if (isGitGuard) {
      // Hooks need a repository and use hook arguments, not --help.
      execFileSync("git", ["init", "--quiet", "--initial-branch=main", cwd]);
    }
    python([path.join(projectRoot, target), isGitGuard ? "pre-commit" : "--help"], {
      cwd,
      encoding: "utf8",
      env: { ...process.env, PYTHONNOUSERSITE: "1", PYTHONPATH: "" },
      stdio: "pipe",
    });
  }
});

test("plugin manifest conforms to the Agent Plugins specification", () => {
  const output = npm(["pack", "--dry-run", "--json"], {
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

test("npm verification graph includes every local suite", () => {
  const packageJson = JSON.parse(
    execFileSync(process.execPath, ["-e", "process.stdout.write(require('fs').readFileSync('package.json'))"], {
      cwd: projectRoot,
      encoding: "utf8",
    })
  );

  assert.deepEqual(normalizedScriptGraph(packageJson, "test:python"), [
    {
      executable: "node",
      args: ["scripts/dev/py.mjs", "-m", "unittest", "discover", "-s", "tests"],
    },
  ]);
  assert.deepEqual(normalizedScriptGraph(packageJson, "test:sync"), [
    {
      executable: "node",
      args: ["scripts/dev/py.mjs", "scripts/sync_skill_resources.py", "--check"],
    },
  ]);
  assert.deepEqual(normalizedScriptGraph(packageJson, "verify"), [
    { script: "test" },
    { script: "test:python" },
    { script: "test:sync" },
  ]);
  assert.deepEqual(normalizedScriptGraph(packageJson, "prepublishOnly"), [
    { script: "verify:release" },
  ]);
});
