import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, test } from "node:test";
import { fileURLToPath } from "node:url";

import * as installer from "../scripts/install.mjs";

// Project behavior moved with its implementation to test_install.py and
// test_runtime_lifecycle.py. This file covers JS host installs and adapter wiring.
const REPO_ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

let root;
let source;
let env;
let priorHome;
const originalHooks = { ...installer.hooks };

function makeSource(base) {
  const src = path.join(base, "source");
  fs.mkdirSync(path.join(src, "skills"), { recursive: true });
  fs.copyFileSync(path.join(REPO_ROOT, "AGENTS.md"), path.join(src, "AGENTS.md"));
  fs.copyFileSync(path.join(REPO_ROOT, "WORKFLOW.md"), path.join(src, "WORKFLOW.md"));
  for (const name of installer.SKILL_NAMES) {
    const skill = path.join(src, "skills", name);
    fs.mkdirSync(path.join(skill, "references"), { recursive: true });
    fs.mkdirSync(path.join(skill, "agents"));
    const canonical = installer.SKILL_ALIASES[name];
    const body = canonical
      ? `# Deprecated alias\n\nInvoke $${name}, then read [the canonical skill](CANONICAL.md).\n`
      : "Run $gsd-path, $gsd-path-build, and $gsd-path-discuss.\n" +
        (name === "gsd-path" ? "Run $gsd-path status.\n" : "");
    fs.writeFileSync(
      path.join(skill, "SKILL.md"),
      `---\nname: ${name}\ndescription: test\n---\n${body}`
    );
    if (canonical) {
      fs.writeFileSync(
        path.join(skill, "CANONICAL.md"),
        `---\nname: ${canonical}\ndescription: test\n---\nUse $${canonical}.\n`
      );
    }
    fs.writeFileSync(path.join(skill, "guide.md"), "Use $gsd-path.\n");
    fs.writeFileSync(path.join(skill, "agents", "openai.yaml"), 'default_prompt: "Use $gsd-path."\n');
    fs.writeFileSync(path.join(skill, "references", "dispatch.md"), "old dispatch\n");
    if (name === "gsd-path" || Object.hasOwn(installer.ROUTER_ALIASES, name)) {
      fs.mkdirSync(path.join(skill, "scripts"));
      fs.copyFileSync(
        path.join(REPO_ROOT, "scripts", "pipeline_state.py"),
        path.join(skill, "scripts", "pipeline_state.py")
      );
    }
  }
  for (const target of installer.TARGETS) {
    const adapter = path.join(src, "platforms", target, "dispatch.md");
    fs.mkdirSync(path.dirname(adapter), { recursive: true });
    fs.writeFileSync(adapter, `${target} dispatch for $gsd-path\n`);
  }
  const shared = path.join(src, "platforms", installer.SHARED_AGENT_PROFILE, "dispatch.md");
  fs.mkdirSync(path.dirname(shared), { recursive: true });
  fs.writeFileSync(shared, "shared dispatch for $gsd-path with invoke_subagent\n");
  fs.writeFileSync(
    path.join(src, "platforms", "cursor", "agent.md"),
    "---\nname: gsd-path\ndescription: test\nmodel: inherit\n---\ncursor agent\n"
  );
  fs.writeFileSync(path.join(src, "package.json"), '{"version": "9.9.9"}\n');
  fs.mkdirSync(path.join(src, "scripts"), { recursive: true });
  for (const name of installer.GUARD_SCRIPTS) {
    fs.writeFileSync(
      path.join(src, "scripts", name),
      `# ${name}\n${installer.GUARD_MARKER}\n`
    );
  }
  for (const name of installer.PROJECT_RUNTIME_SCRIPTS) {
    fs.writeFileSync(
      path.join(src, "scripts", name),
      `# ${name}\n${installer.PROJECT_RUNTIME_MARKER}\n`
    );
  }
  fs.copyFileSync(
    path.join(REPO_ROOT, "scripts", installer.PROJECT_STATUS_LAUNCHER),
    path.join(src, "scripts", installer.PROJECT_STATUS_LAUNCHER)
  );
  return src;
}

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "gsd-path-test-"));
  priorHome = process.env.HOME;
  process.env.HOME = path.join(root, "home");
  source = makeSource(root);
  env = { CODEX_HOME: path.join(root, "legacy") };
  installer.hooks.mismatches = () => [];
  installer.hooks.resolveGitHooksPath = (project) => {
    const resolved = originalHooks.resolveGitHooksPath(project);
    const dotGit = path.join(project, ".git");
    return resolved ?? (fs.existsSync(dotGit) && fs.statSync(dotGit).isDirectory()
      ? path.join(dotGit, "hooks")
      : null);
  };
});

afterEach(() => {
  Object.assign(installer.hooks, originalHooks);
  fs.rmSync(root, { recursive: true, force: true });
  if (priorHome === undefined) delete process.env.HOME;
  else process.env.HOME = priorHome;
});

function runInstall(plans, options = {}) {
  return installer.install(source, plans, { env, ...options });
}

test("Node and Python installers share target ownership locks", async () => {
  const target = path.join(root, "shared-target", "skills");
  installer.hooks.applyTarget = async (...args) => {
    const probe = spawnSync(installer.detectPythonInterpreter(), ["-B", "-c",
      "import sys; from pathlib import Path; from scripts.install import _acquire_install_locks; _acquire_install_locks([Path(sys.argv[1])])",
      target,
    ], { cwd: REPO_ROOT, encoding: "utf8" });
    assert.notEqual(probe.status, 0);
    assert.match(probe.stderr, /installation already in progress/);
    return originalHooks.applyTarget(...args);
  };
  await runInstall([installer.targetPlan("claude", target)]);
});

test("project adapter receives install options and doctor roots", async () => {
  const calls = [];
  installer.hooks.projectAdapter = (...args) => { calls.push(args); return ["receipt"]; };
  const project = path.join(root, "project");
  const target = installer.targetPlan("claude", path.join(root, "skills"));
  assert.deepEqual(await runInstall([target], {
    project, hooks: true, update: true, dryRun: true, migrateLegacy: false,
  }), ["receipt"]);
  assert.deepEqual(calls[0], [source, project, "install", {
    plans: [target], dryRun: true, hooks: true, migrateLegacy: false, update: true,
  }, env]);
  assert.deepEqual(installer.doctor(source, {
    targets: ["claude"], rootFor: () => target.root, project,
  }), ["receipt"]);
  assert.deepEqual(calls[1], [source, project, "doctor", {
    targets: ["claude"], roots: { claude: target.root },
  }]);
});

test("Node CLI installs and explicitly restores an external project runtime", () => {
  const project = path.join(root, "real-project");
  fs.mkdirSync(project);
  const environment = { ...process.env, HOME: path.join(root, "home") };
  const git = spawnSync("git", ["init", "-q", project], { encoding: "utf8", env: environment });
  assert.equal(git.status, 0, git.stderr);
  const cli = (flag, extra = []) => spawnSync(process.execPath, [
    path.join(REPO_ROOT, "scripts/install.mjs"), flag, "--project", project,
    "--source-root", REPO_ROOT, ...extra,
  ], { encoding: "utf8", env: environment });
  const installed = cli("--hooks-init", ["--claude"]);
  assert.equal(installed.status, 0, installed.stderr);
  const declaration = path.join(project, ".gsd-path/runtime.json");
  const before = fs.readFileSync(declaration, "utf8");
  const runtime = path.join(environment.HOME, ".gsd-path/runtimes", JSON.parse(before).digest);
  assert.ok(fs.existsSync(path.join(runtime, "pipeline_state.py")));
  assert.ok(!fs.existsSync(path.join(project, ".gsd-path/runtime")));
  const refreshed = cli("--hooks-refresh");
  assert.equal(refreshed.status, 0, refreshed.stderr);
  assert.equal(fs.readFileSync(declaration, "utf8"), before);
  fs.rmSync(runtime, { recursive: true });
  const restored = cli("--runtime-restore");
  assert.equal(restored.status, 0, restored.stderr);
  assert.equal(fs.readFileSync(declaration, "utf8"), before);
  assert.ok(fs.existsSync(path.join(runtime, "pipeline_state.py")));
});

test("default path resolution", () => {
  assert.equal(installer.defaultRoot("claude", { CLAUDE_CONFIG_DIR: "/tmp/c" }), path.resolve("/tmp/c/skills"));
  assert.equal(installer.defaultRoot("grok", { GROK_HOME: "/tmp/g" }), path.resolve("/tmp/g/skills"));
  assert.equal(installer.defaultRoot("opencode", { XDG_CONFIG_HOME: "/tmp/x" }), path.resolve("/tmp/x/opencode/skills"));
  const config = path.join(root, "opencode.json");
  fs.writeFileSync(config, "{}");
  assert.equal(installer.defaultRoot("opencode", { OPENCODE_CONFIG: config }), path.join(root, "skills"));
  assert.equal(
    installer.defaultRoot("opencode", { OPENCODE_CONFIG: path.join(root, "future", "opencode.json") }),
    path.join(root, "future", "skills")
  );
  const home = os.homedir();
  assert.equal(installer.defaultRoot("codex", {}), path.join(home, ".agents", "skills"));
  assert.equal(installer.defaultRoot("zed", {}), path.join(home, ".agents", "skills"));
  assert.equal(installer.defaultRoot("copilot", { COPILOT_HOME: "/tmp/copilot" }), path.resolve("/tmp/copilot/skills"));
  assert.equal(installer.defaultRoot("qwen", { QWEN_HOME: "/tmp/qwen" }), path.resolve("/tmp/qwen/skills"));
  assert.equal(installer.defaultRoot("kiro", { KIRO_HOME: "/tmp/kiro" }), path.resolve("/tmp/kiro/skills"));
  assert.equal(installer.defaultRoot("kimi", { KIMI_CODE_HOME: "/tmp/kimi-code" }), path.resolve("/tmp/kimi-code/skills"));
  assert.equal(installer.defaultRoot("kimi", {}), path.join(home, ".kimi-code", "skills"));
  assert.equal(installer.defaultRoot("antigravity", {}), path.join(home, ".gemini", "antigravity-cli", "skills"));
  assert.equal(installer.defaultRoot("cursor", {}), path.join(home, ".cursor", "skills"));
  for (const [target, variable] of [
    ["claude", "CLAUDE_CONFIG_DIR"],
    ["grok", "GROK_HOME"],
    ["copilot", "COPILOT_HOME"],
    ["qwen", "QWEN_HOME"],
    ["kiro", "KIRO_HOME"],
    ["kimi", "KIMI_CODE_HOME"],
  ]) {
    assert.equal(installer.defaultRoot(target, {}), installer.defaultRoot(target, { [variable]: "" }));
  }
  assert.equal(installer.defaultRoot("opencode", {}), installer.defaultRoot("opencode", { XDG_CONFIG_HOME: "" }));
  assert.equal(installer.legacyCodexRoot({ CODEX_HOME: "" }), path.join(home, ".codex", "skills"));
});

test("interpreter probe rejects unsupported Python", () => {
  const bin = path.join(root, "old-python");
  fs.mkdirSync(bin);
  for (const name of ["python3", "python"]) {
    const executable = path.join(bin, name);
    fs.writeFileSync(
      executable,
      '#!/bin/sh\n[ "$1" = "--version" ] && exit 0\nexit 1\n',
      { mode: 0o755 }
    );
  }
  const originalPath = process.env.PATH;
  process.env.PATH = bin;
  try {
    assert.equal(installer.detectPythonInterpreter(), null);
  } finally {
    process.env.PATH = originalPath;
  }
});

test("skill names are derived from resource manifest", () => {
  const manifest = {
    skills: ["gsd-path", "gsd-path-alpha", "gsd-path-zeta"],
  };

  assert.deepEqual(installer.skillNamesForManifest(manifest), [
    "gsd-path",
    "gsd-path-alpha",
    "gsd-path-zeta",
  ]);
});

test("discussion skill is installed and invocable", async () => {
  assert.ok(installer.SKILL_NAMES.includes("gsd-path-discuss"));
  const target = path.join(root, "discussion", "skills");

  await runInstall([installer.targetPlan("claude", target)]);

  const discussion = path.join(target, "gsd-path-discuss", "SKILL.md");
  assert.ok(fs.existsSync(discussion));
  assert.match(fs.readFileSync(discussion, "utf8"), /\/gsd-path-discuss/);
});

test("install refuses to replace an unrelated path skill", async () => {
  const target = path.join(root, "foreign-path", "skills");
  const foreign = path.join(target, "path");
  fs.mkdirSync(path.join(foreign, "scripts"), { recursive: true });
  fs.writeFileSync(path.join(foreign, "scripts", "pipeline_state.py"), "");
  fs.writeFileSync(path.join(foreign, "SKILL.md"), "---\nname: path\n---\nforeign\n");

  await assert.rejects(
    () => runInstall([installer.targetPlan("grok", target)]),
    /unrelated skill/
  );
  assert.equal(fs.readFileSync(path.join(foreign, "SKILL.md"), "utf8"), "---\nname: path\n---\nforeign\n");
});

test("install refuses path alias with invalid version", async () => {
  const target = path.join(root, "invalid-path-version", "skills");
  const foreign = path.join(target, "path");
  fs.mkdirSync(path.join(foreign, "scripts"), { recursive: true });
  fs.writeFileSync(path.join(foreign, "scripts", "pipeline_state.py"), "");
  for (const version of ["", "release", "1..0", "1.0.beta", "1.0\nforeign"]) {
    fs.writeFileSync(path.join(foreign, "VERSION"), version);
    await assert.rejects(
      () => runInstall([installer.targetPlan("grok", target)]),
      /unrelated skill/
    );
    assert.equal(fs.readFileSync(path.join(foreign, "VERSION"), "utf8"), version);
  }
});

test("install replaces a pre-stamp path alias with the managed runtime", async () => {
  const target = path.join(root, "pre-stamp-path", "skills");
  const scripts = path.join(target, "path", "scripts");
  fs.mkdirSync(scripts, { recursive: true });
  fs.writeFileSync(
    path.join(scripts, "pipeline_state.py"),
    `#!/usr/bin/env python3\n# ${installer.PROJECT_RUNTIME_MARKER}\n`
  );
  await runInstall([installer.targetPlan("grok", target)]);
  assert.match(fs.readFileSync(path.join(target, "path", "SKILL.md"), "utf8"), /^name: path$/m);
});

test("install replaces an owned path router alias", async () => {
  const target = path.join(root, "owned-path", "skills");
  const owned = path.join(target, "path");
  fs.mkdirSync(path.join(owned, "scripts"), { recursive: true });
  fs.writeFileSync(path.join(owned, "scripts", "pipeline_state.py"), "# previous alias\n");
  fs.writeFileSync(path.join(owned, "VERSION"), "1.0.0\n");

  const results = await runInstall([installer.targetPlan("grok", target)]);
  assert.match(results.join("\n"), /backed up/);
  assert.match(
    fs.readFileSync(path.join(target, "path", "SKILL.md"), "utf8"),
    /^name: path$/m
  );
  assert.equal(
    fs.readFileSync(
      path.join(path.dirname(target), "disabled-gsd-skills", "path", "scripts", "pipeline_state.py"),
      "utf8"
    ),
    "# previous alias\n"
  );
});

test("path is a short slash name for the router", () => {
  assert.deepEqual(installer.ROUTER_ALIASES, { path: "gsd-path" });
  const staged = path.join(root, "staged-router-alias");
  fs.mkdirSync(staged);
  installer.stageTarget(REPO_ROOT, "grok", staged);
  const skill = fs.readFileSync(path.join(staged, "path", "SKILL.md"), "utf8");
  assert.match(skill, /^name: path$/m);
  assert.doesNotMatch(skill, /^name: gsd-path$/m);
  assert.match(skill, /invokes \/path or \/gsd-path/);
  assert.match(skill, /\/gsd-path-undo/);
});

test("v2 canonical skills are installed without aliases", async () => {
  assert.deepEqual(installer.SKILL_ALIASES, {});
  assert.deepEqual(installer.ROUTER_ALIASES, { path: "gsd-path" });

  const target = path.join(root, "terminology", "skills");
  await runInstall([installer.targetPlan("claude", target)]);

  for (const canonical of ["gsd-path-inspect", "gsd-path-define", "gsd-path-decide", "gsd-path-roadmap", "gsd-path-ship"]) {
    const skill = path.join(target, canonical, "SKILL.md");
    assert.ok(fs.existsSync(skill));
    assert.match(fs.readFileSync(skill, "utf8"), new RegExp(`name: ${canonical}`));
  }
});

test("local root resolution", () => {
  const project = path.join(root, "proj");
  assert.deepEqual(installer.LOCAL_ROOTS, {
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
  });
  assert.equal(installer.localRoot("claude", project), path.join(project, ".claude", "skills"));
  assert.throws(() => installer.localRoot("bogus", project));
});

function stagedSkillDirectories(staged) {
  return fs
    .readdirSync(staged, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

test("all platform transforms", () => {
  for (const target of [...installer.TARGETS, installer.SHARED_AGENT_PROFILE]) {
    const staged = path.join(root, `staged-${target}`);
    fs.mkdirSync(staged);
    installer.stageTarget(source, target, staged);
    const stagedSkills = stagedSkillDirectories(staged);
    assert.deepEqual(stagedSkills, [...installer.SKILL_NAMES].sort(), target);
    for (const name of stagedSkills) {
      const label = `${target}/${name}`;
      const content = fs.readFileSync(path.join(staged, name, "SKILL.md"), "utf8");
      const dispatchPath = path.join(staged, name, "references", "dispatch.md");
      assert.ok(fs.existsSync(dispatchPath), label);
      const dispatch = fs.readFileSync(dispatchPath, "utf8");
      const agentsKept = fs.existsSync(path.join(staged, name, "agents", "openai.yaml"));
      if (target === "codex") {
        assert.match(content, /\$gsd-path/, label);
        assert.doesNotMatch(content, /disable-model-invocation/, label);
        assert.match(dispatch, /codex dispatch for \$gsd-path/, label);
        assert.ok(agentsKept, label);
      } else if (target === "opencode") {
        assert.match(content, /Run gsd-path, gsd-path-build, and gsd-path-discuss/, label);
        assert.doesNotMatch(content, /[$/]gsd-path/, label);
        assert.match(dispatch, /opencode dispatch for gsd-path/, label);
        assert.ok(!agentsKept, label);
      } else if (target === installer.SHARED_AGENT_PROFILE) {
        assert.match(content, /\$gsd-path \(Codex\)/, label);
        assert.match(content, /\/gsd-path \(Antigravity\/Zed\)/, label);
        assert.match(dispatch, /shared dispatch for \$gsd-path \(Codex\)/, label);
        assert.match(dispatch, /\/gsd-path \(Antigravity\/Zed\)/, label);
        assert.ok(agentsKept, label);
      } else {
        assert.match(content, /\/gsd-path/, label);
        assert.doesNotMatch(content, /\$gsd-path/, label);
        assert.match(dispatch, new RegExp(`${target} dispatch for /gsd-path`), label);
        assert.ok(!agentsKept, label);
      }
      if (installer.EXPLICIT_ONLY_TARGETS.has(target)) {
        assert.match(content, /disable-model-invocation: true/, label);
      }
      if (target === "opencode" || target === installer.SHARED_AGENT_PROFILE) {
        assert.match(content, /opencode\/autoinvoke: "false"/, label);
        assert.match(content, /opencode\/slash: "true"/, label);
      }
    }
  }
});

test("staging from the real repo applies the real platform adapter to every skill", () => {
  const cases = [
    ["claude", path.join(REPO_ROOT, "platforms", "claude", "dispatch.md"), "/gsd-path"],
    [
      installer.SHARED_AGENT_PROFILE,
      path.join(REPO_ROOT, "platforms", installer.SHARED_AGENT_PROFILE, "dispatch.md"),
      "gsd-path",
    ],
  ];
  for (const [target, adapterPath, invocation] of cases) {
    const staged = path.join(root, `staged-real-${target}`);
    fs.mkdirSync(staged);
    installer.stageTarget(REPO_ROOT, target, staged);
    const expected = fs.readFileSync(adapterPath, "utf8").replaceAll("$gsd-path", invocation);
    let checked = 0;
    for (const name of stagedSkillDirectories(staged)) {
      const dispatch = path.join(staged, name, "references", "dispatch.md");
      if (!fs.existsSync(dispatch)) continue;
      checked += 1;
      assert.equal(fs.readFileSync(dispatch, "utf8"), expected, `${target}/${name}`);
    }
    assert.ok(checked >= 2, `expected multiple dispatch-bearing skills, saw ${checked}`);
    if (target === installer.SHARED_AGENT_PROFILE) {
      const router = fs.readFileSync(path.join(staged, "gsd-path", "SKILL.md"), "utf8");
      const invocation = "`$gsd-path status` (Codex) or `/gsd-path status` (Antigravity/Zed)";
      assert.equal(router.split(invocation).length - 1, 1);
      assert.doesNotMatch(router, /\(other hosts\)/);
    }
  }
});

test("all targets install with shared codex+zed root", async () => {
  const roots = {};
  for (const target of installer.TARGETS) {
    roots[target] = path.join(root, target, "skills");
  }
  roots.zed = roots.codex;
  const plans = installer.TARGETS.map((target) => installer.targetPlan(target, roots[target]));
  const results = await runInstall(plans);
  const distinct = new Set(Object.values(roots));
  assert.equal(distinct.size, 10);
  for (const targetRoot of distinct) {
    assert.deepEqual(fs.readdirSync(targetRoot).sort(), [...installer.SKILL_NAMES].sort());
  }
  const cursorAgent = path.join(path.dirname(roots.cursor), "agents", installer.CURSOR_AGENT_FILENAME);
  assert.ok(fs.readFileSync(cursorAgent, "utf8").endsWith("cursor agent\n"));
  const joined = results.join("\n");
  assert.match(
    joined,
    new RegExp(`codex\\+zed: installed ${installer.SKILL_NAMES.length} shared skills`)
  );
  assert.match(joined, /custom subagent/);
  assert.match(joined, /OpenCode stable discovers/);
  assert.match(joined, /Antigravity discovers/);
  assert.match(joined, /Kiro discovers/);
});

test("install reports progress events", async () => {
  const target = path.join(root, "progress", "skills");
  const events = [];
  await runInstall([installer.targetPlan("claude", target)], {
    onProgress: (text) => events.push(text),
  });
  assert.ok(events.some((text) => /Validating/.test(text)));
  assert.ok(events.some((text) => /Staging claude/.test(text)));
  assert.ok(events.some((text) => /Installing claude/.test(text)));
});

test("codex dry run validates the resolved shared profile from the real repository", async () => {
  const target = path.join(root, "real-codex", "skills");

  const status = await installer.main(
    [
      "--codex",
      "--codex-root",
      target,
      "--dry-run",
      "--source-root",
      REPO_ROOT,
      "--no-color",
    ],
    env
  );

  assert.equal(status, 0);
  assert.ok(!fs.existsSync(target));
});

test("shared agent hosts use one deployment and back up existing entries", async () => {
  const shared = path.join(root, "shared", "skills");
  const deployments = installer.deploymentPlans([
    installer.targetPlan("codex", shared),
    installer.targetPlan("antigravity", shared),
    installer.targetPlan("zed", shared),
  ]);
  assert.deepEqual(deployments, [
    {
      profile: installer.SHARED_AGENT_PROFILE,
      root: shared,
      targets: ["codex", "antigravity", "zed"],
    },
  ]);
  fs.mkdirSync(path.join(shared, "gsd-path-old"), { recursive: true });

  const results = await runInstall([
    installer.targetPlan("codex", shared),
    installer.targetPlan("antigravity", shared),
    installer.targetPlan("zed", shared),
  ]);
  const joined = results.join("\n");
  const sharedInstall = new RegExp(
    `installed ${installer.SKILL_NAMES.length} shared skills`,
    "g"
  );
  assert.equal((joined.match(sharedInstall) || []).length, 1);
  assert.equal((joined.match(/backed up 1 entries/g) || []).length, 1);
  assert.ok(fs.statSync(path.join(path.dirname(shared), "disabled-gsd-skills", "gsd-path-old")).isDirectory());
  const content = fs.readFileSync(path.join(shared, "gsd-path", "SKILL.md"), "utf8");
  assert.match(content, /disable-model-invocation: true/);
  assert.match(content, /\$gsd-path \(Codex\) or \/gsd-path \(Antigravity\/Zed\)/);
  assert.match(
    content,
    /\$gsd-path status \(Codex\) or \/gsd-path status \(Antigravity\/Zed\)/
  );
  assert.ok(fs.existsSync(path.join(shared, "gsd-path", "agents", "openai.yaml")));
});

test("unrelated targets cannot share or overlap roots", async () => {
  const collision = path.join(root, "collision");
  const cases = [
    [installer.targetPlan("copilot", collision), installer.targetPlan("qwen", collision)],
    [installer.targetPlan("claude", collision), installer.targetPlan("grok", path.join(collision, "nested"))],
  ];
  for (const plans of cases) {
    await assert.rejects(runInstall(plans), /share|overlap/);
    assert.ok(!fs.existsSync(collision));
  }
});

test("non-shared host cannot write the standard shared root", () => {
  assert.throws(
    () => installer.deploymentPlans([installer.targetPlan("copilot", installer.defaultRoot("codex", {}))]),
    /shared ~\/.agents\/skills/
  );
});

test("cursor subagent installed and existing copy backed up", async () => {
  const cursorRoot = path.join(root, "cursor-install", "skills");
  const agent = path.join(path.dirname(cursorRoot), "agents", installer.CURSOR_AGENT_FILENAME);
  fs.mkdirSync(path.dirname(agent), { recursive: true });
  fs.writeFileSync(agent, "old agent\n");

  const results = await runInstall([installer.targetPlan("cursor", cursorRoot)]);
  assert.match(results.join("\n"), /custom subagent/);
  assert.match(fs.readFileSync(agent, "utf8"), /cursor agent/);
  const backup = path.join(path.dirname(cursorRoot), "disabled-gsd-skills");
  assert.equal(fs.readFileSync(path.join(backup, installer.CURSOR_AGENT_BACKUP_NAME), "utf8"), "old agent\n");
});

test("existing managed entries backed up and unrelated preserved", async () => {
  const target = path.join(root, "codex", "skills");
  fs.mkdirSync(target, { recursive: true });
  for (const name of ["ogsd", "ogsd-old", "gsd-path", "gsd-path-old"]) {
    fs.mkdirSync(path.join(target, name));
    fs.writeFileSync(path.join(target, name, "old.txt"), name);
  }
  const outside = path.join(root, "outside");
  fs.mkdirSync(outside);
  fs.writeFileSync(path.join(outside, "marker"), "preserve");
  fs.symlinkSync(outside, path.join(target, "ogsd-link"));
  fs.mkdirSync(path.join(target, "other-skill"));

  const results = await runInstall([installer.targetPlan("codex", target)]);
  const backup = path.join(path.dirname(target), "disabled-gsd-skills");
  assert.deepEqual(
    fs.readdirSync(backup).sort(),
    ["gsd-path", "gsd-path-old", "ogsd", "ogsd-link", "ogsd-old"]
  );
  assert.ok(fs.lstatSync(path.join(backup, "ogsd-link")).isSymbolicLink());
  assert.equal(fs.readFileSync(path.join(outside, "marker"), "utf8"), "preserve");
  assert.ok(fs.statSync(path.join(target, "other-skill")).isDirectory());
  assert.match(results.join("\n"), /backed up 5 entries/);
});

test("codex migrates legacy root and preserves unrelated entries", async () => {
  const legacy = path.join(root, "legacy", "skills");
  fs.mkdirSync(path.join(legacy, "gsd-path-old"), { recursive: true });
  fs.mkdirSync(path.join(legacy, "unrelated"));
  const target = path.join(root, "new", "skills");

  const results = await runInstall([installer.targetPlan("codex", target)]);
  assert.ok(
    fs.statSync(path.join(path.dirname(legacy), "disabled-gsd-skills", "gsd-path-old")).isDirectory()
  );
  assert.ok(fs.statSync(path.join(legacy, "unrelated")).isDirectory());
  assert.ok(!fs.readdirSync(legacy).includes("gsd-path"));
  assert.match(results.join("\n"), /codex-legacy: backed up 1 entries/);
});

test("migrateLegacy false skips the legacy root entirely", async () => {
  const legacy = path.join(root, "legacy", "skills");
  fs.mkdirSync(path.join(legacy, "gsd-path-old"), { recursive: true });
  const target = path.join(root, "new", "skills");

  const results = await runInstall([installer.targetPlan("codex", target)], {
    migrateLegacy: false,
  });
  assert.ok(fs.existsSync(path.join(legacy, "gsd-path-old")));
  assert.doesNotMatch(results.join("\n"), /codex-legacy/);
});

test("dry run makes no destination changes", async () => {
  const target = path.join(root, "dry", "skills");
  const project = path.join(root, "project");
  const results = await installer.install(REPO_ROOT, [installer.targetPlan("claude", target)], {
    project,
    env: { ...process.env, HOME: path.join(root, "home") },
    dryRun: true,
  });
  assert.ok(!fs.existsSync(target));
  assert.ok(!fs.existsSync(project));
  const joined = results.join("\n");
  assert.match(joined, new RegExp(`would install ${installer.SKILL_NAMES.length} skills`));
  assert.match(joined, /\.claude\/CLAUDE\.md/);
});

test("dry run reports the registered skill count", async () => {
  const extraName = "gsd-path-extra";
  fs.cpSync(
    path.join(source, "skills", "gsd-path"),
    path.join(source, "skills", extraName),
    { recursive: true }
  );
  installer.SKILL_NAMES.push(extraName);
  try {
    const results = await runInstall([installer.targetPlan("claude", path.join(root, "dynamic"))], {
      dryRun: true,
    });
    assert.match(
      results.join("\n"),
      new RegExp(`would install ${installer.SKILL_NAMES.length} skills`)
    );
  } finally {
    installer.SKILL_NAMES.pop();
  }
});

test("stale sync fails before mutation", async () => {
  installer.hooks.mismatches = () => [
    "stale generated resource: skills/gsd-path-build/references/dispatch.md",
  ];
  const target = path.join(root, "codex", "skills");
  await assert.rejects(
    runInstall([installer.targetPlan("codex", target)]),
    /source resources are stale/
  );
  assert.ok(!fs.existsSync(target));
});

test("real mismatches detects a stale generated resource", () => {
  installer.hooks.mismatches = originalHooks.mismatches;
  const repo = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
  assert.deepEqual(installer.mismatches(repo), []);
  const copy = path.join(root, "repo-copy");
  fs.cpSync(repo, copy, {
    recursive: true,
    filter: (candidate) =>
      !candidate.includes(`${path.sep}.git`) && !candidate.includes(`${path.sep}node_modules`),
  });
  fs.appendFileSync(path.join(copy, "skills", "gsd-path-build", "references", "dispatch.md"), "drift\n");
  assert.ok(
    installer
      .mismatches(copy)
      .some((problem) => problem.includes("stale generated resource"))
  );
});

test("target root must not overlap source", async () => {
  for (const target of [root, path.join(source, "nested", "skills")]) {
    await assert.rejects(
      runInstall([installer.targetPlan("claude", target)]),
      /overlaps source repository/
    );
    assert.ok(fs.statSync(path.join(source, "skills", "gsd-path")).isDirectory());
    assert.ok(!fs.existsSync(path.join(root, "disabled-gsd-skills")));
  }
});

test("backup root cannot overlap another target", async () => {
  const first = path.join(root, "backup-collision", "skills");
  fs.mkdirSync(path.join(first, "gsd-path-old"), { recursive: true });
  const second = path.join(path.dirname(first), "disabled-gsd-skills");
  await assert.rejects(
    runInstall([installer.targetPlan("claude", first), installer.targetPlan("grok", second)]),
    /backup overlaps/
  );
  assert.ok(fs.statSync(path.join(first, "gsd-path-old")).isDirectory());
  assert.ok(!fs.existsSync(second));
});

test("multi-target failure rolls back prior target and backup", async () => {
  const codex = path.join(root, "codex", "skills");
  fs.mkdirSync(path.join(codex, "gsd-path-old"), { recursive: true });
  fs.writeFileSync(path.join(codex, "gsd-path-old", "marker"), "old");
  const claude = path.join(root, "claude", "skills");
  let calls = 0;
  installer.hooks.applyTarget = (plan, staged, transaction) => {
    calls += 1;
    if (calls === 2) throw new Error("injected failure");
    return originalHooks.applyTarget(plan, staged, transaction);
  };

  await assert.rejects(
    runInstall([installer.targetPlan("codex", codex), installer.targetPlan("claude", claude)]),
    /rolled back/
  );
  assert.ok(fs.statSync(path.join(codex, "gsd-path-old", "marker")).isFile());
  assert.ok(!fs.existsSync(path.join(codex, "gsd-path")));
  assert.ok(!fs.existsSync(path.join(path.dirname(codex), "disabled-gsd-skills")));
  assert.ok(!fs.existsSync(claude));
});

test("failure after backup move still restores original", async () => {
  const target = path.join(root, "move-interrupt", "skills");
  fs.mkdirSync(path.join(target, "gsd-path-old"), { recursive: true });
  fs.writeFileSync(path.join(target, "gsd-path-old", "marker"), "old");
  let moved = false;
  installer.hooks.rename = (from, to) => {
    fs.renameSync(from, to);
    if (!moved) {
      moved = true;
      throw new Error("injected failure");
    }
  };

  await assert.rejects(runInstall([installer.targetPlan("claude", target)]), /rolled back/);
  assert.equal(fs.readFileSync(path.join(target, "gsd-path-old", "marker"), "utf8"), "old");
  assert.ok(!fs.existsSync(path.join(path.dirname(target), "disabled-gsd-skills")));
});

test("install collision does not remove a concurrent destination", async () => {
  const target = path.join(root, "concurrent-install", "skills");
  const destination = path.join(target, installer.SKILL_NAMES[0]);
  let raced = false;
  installer.hooks.reserveDirectory = (candidate) => {
    if (candidate === destination && !raced) {
      raced = true;
      fs.mkdirSync(candidate);
      fs.writeFileSync(path.join(candidate, "other-installer.txt"), "live install\n");
    }
    return originalHooks.reserveDirectory(candidate);
  };

  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)]),
    /rolled back/
  );

  assert.equal(raced, true);
  assert.equal(
    fs.readFileSync(path.join(destination, "other-installer.txt"), "utf8"),
    "live install\n"
  );
});

test("active target owner prevents backup mutation", async () => {
  const target = path.join(root, "owned-install", "skills");
  const existing = path.join(target, "gsd-path-old");
  fs.mkdirSync(existing, { recursive: true });
  fs.writeFileSync(path.join(existing, "marker"), "old\n");
  fs.mkdirSync(installer.installLockPath(target), { recursive: true });

  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)]),
    /already in progress/
  );

  assert.equal(fs.readFileSync(path.join(existing, "marker"), "utf8"), "old\n");
  assert.ok(!fs.existsSync(path.join(path.dirname(target), "disabled-gsd-skills")));
});

test("install lock publishes a live owner", async () => {
  const target = path.join(root, "live-owner", "skills");
  const lock = installer.installLockPath(target);
  let owner = null;
  installer.hooks.applyTarget = async (...args) => {
    owner = JSON.parse(fs.readFileSync(path.join(lock, "owner.json"), "utf8"));
    return originalHooks.applyTarget(...args);
  };

  await runInstall([installer.targetPlan("claude", target)]);

  assert.equal(owner.schema, "gsd-path/install-lock/v2");
  assert.equal(owner.pid, process.pid);
  assert.ok(owner.identity);
  assert.ok(!fs.existsSync(lock));
});

test("install recovers a stale owned lock", async () => {
  const target = path.join(root, "stale-owner", "skills");
  const lock = installer.installLockPath(target);
  fs.mkdirSync(lock, { recursive: true });
  fs.writeFileSync(path.join(lock, "owner.json"), JSON.stringify({
    schema: "gsd-path/install-lock/v2", pid: process.pid, identity: "reused-pid",
  }));

  await runInstall([installer.targetPlan("claude", target)]);

  assert.ok(fs.existsSync(path.join(target, installer.SKILL_NAMES[0])));
  assert.ok(!fs.existsSync(lock));
});

test("concurrent stale recovery keeps each quarantine owned", async () => {
  const parent = path.join(root, "concurrent-stale-owner");
  const firstTarget = path.join(parent, "first-skills");
  const secondTarget = path.join(parent, "second-skills");
  const lock = installer.installLockPath(firstTarget);
  fs.mkdirSync(lock, { recursive: true });
  fs.writeFileSync(path.join(lock, "owner.json"), JSON.stringify({
    schema: "gsd-path/install-lock/v2",
    pid: process.pid,
    identity: "reused-pid",
  }));
  let raced = false;
  installer.hooks.renameInstallLock = (from, to) => {
    fs.renameSync(from, to);
    if (raced) return;
    raced = true;
    const moduleUrl = new URL("../scripts/install.mjs", import.meta.url).href;
    const script = `
      import * as installer from ${JSON.stringify(moduleUrl)};
      installer.hooks.mismatches = () => [];
      await installer.install(
        ${JSON.stringify(source)},
        [installer.targetPlan("claude", ${JSON.stringify(secondTarget)})],
        { env: ${JSON.stringify(env)} }
      );
    `;
    const competitor = spawnSync(
      process.execPath,
      ["--input-type=module", "-e", script],
      { encoding: "utf8" }
    );
    assert.equal(competitor.status, 0, competitor.stderr || competitor.stdout);
  };

  await runInstall([installer.targetPlan("claude", firstTarget)]);

  assert.equal(raced, true);
  assert.ok(fs.existsSync(path.join(firstTarget, installer.SKILL_NAMES[0])));
  assert.ok(fs.existsSync(path.join(secondTarget, installer.SKILL_NAMES[0])));
  assert.ok(!fs.existsSync(lock));
  assert.deepEqual(
    fs.readdirSync(parent).filter((entry) =>
      entry.startsWith(".gsd-path-install-lock.stale-")
    ),
    []
  );
});

test("install reclaims an orphaned stale quarantine", async () => {
  const target = path.join(root, "orphaned-quarantine", "skills");
  const lock = installer.installLockPath(target);
  const quarantine = `${lock}.stale`;
  fs.mkdirSync(quarantine, { recursive: true });
  fs.writeFileSync(
    path.join(quarantine, "owner.json"),
    JSON.stringify({
      schema: "gsd-path/install-lock/v2",
      pid: process.pid,
      identity: "reused-pid",
    })
  );

  await runInstall([installer.targetPlan("claude", target)]);

  assert.ok(fs.existsSync(path.join(target, installer.SKILL_NAMES[0])));
  assert.ok(!fs.existsSync(quarantine));
});

test("install reclaims a unique orphaned stale quarantine", async () => {
  const target = path.join(root, "unique-orphaned-quarantine", "skills");
  const lock = installer.installLockPath(target);
  const staging = path.join(path.dirname(lock), ".install-lock-stage-abandoned");
  const quarantine = `${lock}.stale-${path.basename(staging)}`;
  const owner = JSON.stringify({
    schema: "gsd-path/install-lock/v2",
    pid: process.pid,
    identity: "reused-pid",
  });
  for (const directory of [staging, quarantine]) {
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, "owner.json"), owner);
  }

  await runInstall([installer.targetPlan("claude", target)]);

  assert.ok(fs.existsSync(path.join(target, installer.SKILL_NAMES[0])));
  assert.ok(!fs.existsSync(staging));
  assert.ok(!fs.existsSync(quarantine));
});

test("stale lock recovery preserves a replacement owner", async () => {
  const target = path.join(root, "raced-stale-owner", "skills");
  const lock = installer.installLockPath(target);
  const ownerPath = path.join(lock, "owner.json");
  fs.mkdirSync(lock, { recursive: true });
  fs.writeFileSync(ownerPath, JSON.stringify({
    schema: "gsd-path/install-lock/v2",
    pid: process.pid,
    identity: "reused-pid",
  }));
  const displaced = path.join(path.dirname(lock), "displaced-stale-lock");
  let raced = false;
  installer.hooks.renameInstallLock = (from, to) => {
    if (!raced) {
      raced = true;
      fs.renameSync(from, displaced);
      fs.mkdirSync(lock);
      fs.writeFileSync(ownerPath, JSON.stringify({
        schema: "gsd-path/install-lock/v2",
        pid: process.pid,
        identity: originalHooks.processIdentity(process.pid),
      }));
    }
    fs.renameSync(from, to);
  };

  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)]),
    /already in progress/
  );

  assert.equal(raced, true);
  assert.equal(
    JSON.parse(fs.readFileSync(ownerPath, "utf8")).identity,
    originalHooks.processIdentity(process.pid)
  );
  assert.ok(!fs.existsSync(target));
});

test("lost stale lock race removes only the quarantine", async () => {
  const target = path.join(root, "lost-stale-owner", "skills");
  const lock = installer.installLockPath(target);
  const ownerPath = path.join(lock, "owner.json");
  fs.mkdirSync(lock, { recursive: true });
  fs.writeFileSync(ownerPath, JSON.stringify({
    schema: "gsd-path/install-lock/v2", pid: process.pid, identity: "reused-pid",
  }));
  let raced = false;
  installer.hooks.renameInstallStage = (from, to) => {
    raced = true;
    fs.mkdirSync(lock);
    fs.writeFileSync(ownerPath, JSON.stringify({
      schema: "gsd-path/install-lock/v2",
      pid: process.pid,
      identity: originalHooks.processIdentity(process.pid),
    }));
    fs.renameSync(from, to);
  };

  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)]),
    /already in progress/
  );

  assert.equal(raced, true);
  assert.ok(fs.existsSync(lock));
  assert.ok(!fs.existsSync(`${lock}.stale`));
});

test("failure restores cursor subagent", async () => {
  const cursorRoot = path.join(root, "cursor-rollback", "skills");
  const agent = path.join(path.dirname(cursorRoot), "agents", installer.CURSOR_AGENT_FILENAME);
  fs.mkdirSync(path.dirname(agent), { recursive: true });
  fs.writeFileSync(agent, "old cursor agent\n");
  const claude = path.join(root, "claude-after-cursor", "skills");
  let calls = 0;
  installer.hooks.applyTarget = (plan, staged, transaction) => {
    calls += 1;
    if (calls === 2) throw new Error("injected failure");
    return originalHooks.applyTarget(plan, staged, transaction);
  };

  await assert.rejects(
    runInstall([installer.targetPlan("cursor", cursorRoot), installer.targetPlan("claude", claude)]),
    /rolled back/
  );
  assert.equal(fs.readFileSync(agent, "utf8"), "old cursor agent\n");
  assert.ok(!fs.existsSync(cursorRoot));
  assert.ok(!fs.existsSync(path.join(path.dirname(cursorRoot), "disabled-gsd-skills")));
  assert.ok(!fs.existsSync(claude));
});

test("staging stamps the installed VERSION from package.json", () => {
  const staged = path.join(root, "staged-version");
  fs.mkdirSync(staged);
  installer.stageTarget(source, "claude", staged);
  assert.equal(fs.readFileSync(path.join(staged, "gsd-path", "VERSION"), "utf8"), "9.9.9\n");
  assert.equal(fs.readFileSync(path.join(staged, "path", "VERSION"), "utf8"), "9.9.9\n");

  fs.rmSync(path.join(source, "package.json"));
  const unstamped = path.join(root, "staged-unstamped");
  fs.mkdirSync(unstamped);
  installer.stageTarget(source, "claude", unstamped);
  assert.ok(!fs.existsSync(path.join(unstamped, "gsd-path", "VERSION")));
  assert.ok(!fs.existsSync(path.join(unstamped, "path", "VERSION")));
});

test("detectInstalls finds only roots with managed entries", () => {
  const claudeRoot = path.join(root, "detect", "claude");
  const grokRoot = path.join(root, "detect", "grok");
  const kiroRoot = path.join(root, "detect", "kiro");
  fs.mkdirSync(path.join(claudeRoot, "gsd-path"), { recursive: true });
  fs.mkdirSync(path.join(grokRoot, "path"), { recursive: true });
  fs.writeFileSync(path.join(grokRoot, "path", "SKILL.md"), "---\nname: path\n---\nforeign\n");
  fs.mkdirSync(path.join(kiroRoot, "unrelated-skill"), { recursive: true });
  const roots = { claude: claudeRoot, grok: grokRoot, kiro: kiroRoot, qwen: path.join(root, "missing") };
  const plans = installer.detectInstalls(Object.keys(roots), (target) => roots[target]);
  assert.deepEqual(plans, [installer.targetPlan("claude", claudeRoot)]);
});

test("update refreshes only detected local installs", async () => {
  const project = path.join(root, "update-project");
  fs.mkdirSync(project);
  const previous = process.cwd();
  process.chdir(project);
  try {
    assert.equal(
      await installer.main(["--claude", "--local", "--source-root", source, "--no-color"], env),
      0
    );
    const skillFile = path.join(project, ".claude", "skills", "gsd-path", "SKILL.md");
    fs.writeFileSync(skillFile, "tampered\n");

    assert.equal(
      await installer.main(["--update", "--local", "--source-root", source, "--no-color"], env),
      0
    );
    assert.match(
      fs.readFileSync(skillFile, "utf8"),
      /Run \/gsd-path, \/gsd-path-build, and \/gsd-path-discuss/
    );
    const backup = path.join(project, ".claude", "disabled-gsd-skills");
    assert.equal(
      fs.readFileSync(path.join(backup, "gsd-path", "SKILL.md"), "utf8"),
      "tampered\n"
    );
    assert.ok(!fs.existsSync(path.join(project, ".grok")), "update must not touch uninstalled hosts");
    assert.ok(!fs.existsSync(path.join(project, ".agents")), "update must not touch uninstalled hosts");
  } finally {
    process.chdir(previous);
  }
});

test("update with nothing installed fails cleanly", async () => {
  const project = path.join(root, "empty-project");
  fs.mkdirSync(project);
  const previous = process.cwd();
  process.chdir(project);
  try {
    assert.equal(
      await installer.main(["--update", "--local", "--source-root", source, "--no-color"], env),
      1
    );
    assert.deepEqual(fs.readdirSync(project), []);
  } finally {
    process.chdir(previous);
  }
});

test("cli parses target flags and requires a selection", () => {
  const values = installer.parseCli(["--all", "--dry-run", "--local", "--claude-root", "/tmp/x"]);
  assert.equal(values.all, true);
  assert.equal(values["dry-run"], true);
  assert.equal(values.local, true);
  assert.equal(values["claude-root"], "/tmp/x");
  for (const target of installer.TARGETS) {
    assert.ok(target in values);
  }
  assert.throws(() => installer.parseCli(["--bogus"]));
});

test("hooks require a project", async () => {
  const target = path.join(root, "claude", "skills");
  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { hooks: true }),
    /--hooks requires --project/
  );
  assert.ok(!fs.existsSync(target));
});

test("cli loads from an install path containing spaces", () => {
  const spaced = path.join(root, "dir with spaces");
  fs.mkdirSync(spaced, { recursive: true });
  for (const name of ["install.mjs", "skill-resources.json"]) {
    fs.copyFileSync(path.join(REPO_ROOT, "scripts", name), path.join(spaced, name));
  }
  const result = spawnSync(process.execPath, [path.join(spaced, "install.mjs"), "--help"], {
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /project contracts and status runtime; requires Python 3\.9\+/);
});

test("doctor reports missing package version", () => {
  fs.unlinkSync(path.join(source, "package.json"));

  const findings = installer.doctor(source, { targets: [], rootFor: () => "" });

  assert.ok(findings.some(({ level, text }) => level === "fail" && text === "package: version cannot be read"));
});

test("doctor reports an unreadable skills root", () => {
  const skills = path.join(root, "unreadable-skills");
  fs.mkdirSync(skills);
  fs.chmodSync(skills, 0);
  let findings;
  try {
    findings = installer.doctor(source, { targets: ["claude"], rootFor: () => skills });
  } finally {
    fs.chmodSync(skills, 0o755);
  }

  assert.ok(findings.some(({ level, text }) => level === "fail" && /skills root cannot be read/.test(text)));
});

test("doctor flags stale versions and incomplete installs", async () => {
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)]);
  fs.writeFileSync(path.join(target, "gsd-path", "VERSION"), "0.0.1\n");
  let findings = installer.doctor(source, { targets: ["claude"], rootFor: () => target });
  assert.ok(findings.some((finding) => finding.level === "warn" && /stale install/.test(finding.text)));
  fs.rmSync(path.join(target, "gsd-path-build"), { recursive: true });
  findings = installer.doctor(source, { targets: ["claude"], rootFor: () => target });
  assert.ok(findings.some((finding) => finding.level === "fail" && /gsd-path-build/.test(finding.text)));
});

function git(...args) {
  const result = spawnSync("git", args, { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout;
}

test("doctor cli exits zero when healthy and nonzero on problems", async () => {
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)]);
  const cli = ["--doctor", "--claude", "--claude-root", target, "--source-root", source, "--no-color"];
  assert.equal(await installer.main(cli, env), 0);
  fs.rmSync(path.join(target, "gsd-path-plan"), { recursive: true });
  assert.equal(await installer.main(cli, env), 1);
});

test("doctor cli fails when a linked worktree hooks directory cannot be resolved", async () => {
  const project = path.join(root, "unresolved-worktree");
  const target = path.join(root, "uninstalled-claude", "skills");
  fs.mkdirSync(path.join(project, installer.HOOKS_DIRECTORY), { recursive: true });
  fs.writeFileSync(path.join(project, "AGENTS.md"), "agents\n");
  fs.writeFileSync(path.join(project, "WORKFLOW.md"), "workflow\n");
  fs.writeFileSync(path.join(project, ".git"), "gitdir: /unavailable\n");
  for (const name of installer.GUARD_SCRIPTS) {
    fs.copyFileSync(
      path.join(source, "scripts", name),
      path.join(project, installer.HOOKS_DIRECTORY, name)
    );
  }
  installer.hooks.resolveGitHooksPath = () => null;

  const status = await installer.main(
    [
      "--doctor",
      "--claude",
      "--claude-root",
      target,
      "--project",
      project,
      "--source-root",
      source,
      "--no-color",
    ],
    env
  );

  assert.equal(status, 1);
});
