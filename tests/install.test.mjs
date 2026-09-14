import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, test } from "node:test";
import { fileURLToPath } from "node:url";

import * as installer from "../scripts/install.mjs";

const REPO_ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

let root;
let source;
let env;
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
});

function runInstall(plans, options = {}) {
  return installer.install(source, plans, { env, ...options });
}

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

test("local install via main uses project roots and skips legacy migration", async () => {
  const project = path.join(root, "local-project");
  fs.mkdirSync(project);
  const legacy = path.join(root, "legacy", "skills", "gsd-path-old");
  fs.mkdirSync(legacy, { recursive: true });
  const previous = process.cwd();
  process.chdir(project);
  try {
    const status = await installer.main(
      ["--all", "--local", "--source-root", source, "--no-color"],
      env
    );
    assert.equal(status, 0);
  } finally {
    process.chdir(previous);
  }
  for (const relative of [".agents/skills", ".claude/skills", ".github/skills", ".cursor/skills", ".kiro/skills"]) {
    assert.deepEqual(
      fs.readdirSync(path.join(project, relative)).sort(),
      [...installer.SKILL_NAMES].sort()
    );
  }
  const sharedSkill = fs.readFileSync(
    path.join(project, ".agents", "skills", "gsd-path", "SKILL.md"),
    "utf8"
  );
  assert.match(sharedSkill, /\$gsd-path \(Codex\) or \/gsd-path \(Antigravity\/Zed\)/);
  assert.match(
    fs.readFileSync(
      path.join(project, ".agents", "skills", "gsd-path", "references", "dispatch.md"),
      "utf8"
    ),
    /invoke_subagent/
  );
  assert.ok(fs.existsSync(path.join(project, ".cursor", "agents", installer.CURSOR_AGENT_FILENAME)));
  assert.ok(fs.existsSync(legacy), "legacy migration must not run for --local");
  assert.ok(!fs.existsSync(path.join(root, "legacy", "disabled-gsd-skills")));
});

test("project install rejects a nested Git directory", async () => {
  const repository = path.join(root, "repository");
  const project = path.join(repository, "nested");
  const target = path.join(root, "nested-target", "skills");
  fs.mkdirSync(project, { recursive: true });
  spawnSync("git", ["init", "-q"], { cwd: repository });

  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { project }),
    /not the Git worktree root/
  );
  assert.ok(!fs.existsSync(target));
  assert.deepEqual(fs.readdirSync(project), []);
});

test("dry run rejects a missing project nested in Git", async () => {
  const repository = path.join(root, "dry-repository");
  const project = path.join(repository, "missing", "project");
  const target = path.join(root, "dry-nested-target", "skills");
  fs.mkdirSync(repository);
  spawnSync("git", ["init", "-q"], { cwd: repository });

  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { project, dryRun: true }),
    /not the Git worktree root/
  );
  assert.ok(!fs.existsSync(project));
  assert.ok(!fs.existsSync(target));
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
  const results = await runInstall([installer.targetPlan("claude", target)], {
    project,
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

test("project collision fails before install mutation", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(project);
  fs.writeFileSync(path.join(project, "AGENTS.md"), "existing");
  const target = path.join(root, "claude", "skills");
  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { project }),
    /already exists/
  );
  assert.ok(!fs.existsSync(target));
});

test("claude project bridge uses imports and never overwrites", async () => {
  const project = path.join(root, "project");
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project });
  assert.equal(
    fs.readFileSync(path.join(project, ".claude", "CLAUDE.md"), "utf8"),
    installer.CLAUDE_BRIDGE
  );
  for (const name of installer.PROJECT_RUNTIME_SCRIPTS) {
    assert.ok(
      fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY, "runtime", name))
    );
  }

  const secondTarget = path.join(root, "claude-2", "skills");
  await assert.rejects(
    runInstall([installer.targetPlan("claude", secondTarget)], { project }),
    /already exists/
  );
  assert.ok(!fs.existsSync(secondTarget));
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
  fs.mkdirSync(path.join(path.dirname(target), ".gsd-path-install-lock"));

  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)]),
    /already in progress/
  );

  assert.equal(fs.readFileSync(path.join(existing, "marker"), "utf8"), "old\n");
  assert.ok(!fs.existsSync(path.join(path.dirname(target), "disabled-gsd-skills")));
});

test("install lock publishes a live owner", async () => {
  const target = path.join(root, "live-owner", "skills");
  const lock = path.join(path.dirname(target), ".gsd-path-install-lock");
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
  const lock = path.join(path.dirname(target), ".gsd-path-install-lock");
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
  const lock = path.join(parent, ".gsd-path-install-lock");
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
  const lock = path.join(path.dirname(target), ".gsd-path-install-lock");
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
  const lock = path.join(path.dirname(target), ".gsd-path-install-lock");
  const staging = path.join(path.dirname(target), ".install-lock-stage-abandoned");
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
  const lock = path.join(path.dirname(target), ".gsd-path-install-lock");
  const ownerPath = path.join(lock, "owner.json");
  fs.mkdirSync(lock, { recursive: true });
  fs.writeFileSync(ownerPath, JSON.stringify({
    schema: "gsd-path/install-lock/v2",
    pid: process.pid,
    identity: "reused-pid",
  }));
  const displaced = path.join(path.dirname(target), "displaced-stale-lock");
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
  const lock = path.join(path.dirname(target), ".gsd-path-install-lock");
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

test("update keeps project contracts and refreshes the managed runtime", async () => {
  const project = path.join(root, "update-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  fs.writeFileSync(path.join(project, "AGENTS.md"), "edited contract\n");
  fs.writeFileSync(path.join(project, ".claude", "CLAUDE.md"), "edited bridge\n");
  const runtimeFile = path.join(
    project,
    installer.HOOKS_DIRECTORY,
    "runtime",
    installer.PROJECT_RUNTIME_SCRIPTS[0]
  );
  const guardFile = path.join(project, installer.HOOKS_DIRECTORY, installer.GUARD_SCRIPTS[0]);
  fs.writeFileSync(runtimeFile, `# stale\n${installer.PROJECT_RUNTIME_MARKER}\n`);
  fs.writeFileSync(guardFile, `# stale\n${installer.GUARD_MARKER}\n`);
  const settingsPath = path.join(project, ".claude", "settings.json");
  const settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  settings.userSetting = true;
  fs.writeFileSync(settingsPath, JSON.stringify(settings) + "\n");

  const dryRun = await runInstall([installer.targetPlan("claude", target)], {
    project,
    hooks: true,
    update: true,
    dryRun: true,
  });
  assert.match(dryRun.find((line) => line.startsWith("project:")), /would refresh .*; kept AGENTS\.md, WORKFLOW\.md, \.claude\/CLAUDE\.md/);
  assert.equal(fs.readFileSync(runtimeFile, "utf8"), `# stale\n${installer.PROJECT_RUNTIME_MARKER}\n`);

  const results = await runInstall([installer.targetPlan("claude", target)], {
    project,
    hooks: true,
    update: true,
  });
  const projectLine = results.find((line) => line.startsWith("project:"));
  assert.match(projectLine, /^project: refreshed /);
  assert.match(projectLine, /kept AGENTS\.md, WORKFLOW\.md, \.claude\/CLAUDE\.md$/);
  assert.equal(fs.readFileSync(path.join(project, "AGENTS.md"), "utf8"), "edited contract\n");
  assert.equal(fs.readFileSync(path.join(project, ".claude", "CLAUDE.md"), "utf8"), "edited bridge\n");
  assert.equal(
    fs.readFileSync(runtimeFile, "utf8"),
    fs.readFileSync(path.join(source, "scripts", installer.PROJECT_RUNTIME_SCRIPTS[0]), "utf8")
  );
  assert.equal(
    fs.readFileSync(guardFile, "utf8"),
    fs.readFileSync(path.join(source, "scripts", installer.GUARD_SCRIPTS[0]), "utf8")
  );
  const merged = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  assert.equal(merged.userSetting, true);
  assert.equal(merged.hooks.PreToolUse.length, 1);
  assert.equal(
    fs.readFileSync(path.join(project, ".git", "hooks", "pre-commit"), "utf8"),
    installer.preCommitHook("python3")
  );
});

test("update refuses to replace an unmanaged project runtime file", async () => {
  const project = path.join(root, "update-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project });
  const runtimeFile = path.join(
    project,
    installer.HOOKS_DIRECTORY,
    "runtime",
    installer.PROJECT_RUNTIME_SCRIPTS[0]
  );
  fs.writeFileSync(runtimeFile, "foreign\n");
  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { project, update: true }),
    /not a managed GSD Path project file/
  );
  assert.equal(fs.readFileSync(runtimeFile, "utf8"), "foreign\n");
});

test("update with a project passes through the CLI", async () => {
  const project = path.join(root, "update-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const previous = process.cwd();
  process.chdir(project);
  try {
    assert.equal(
      await installer.main(
        ["--claude", "--local", "--project", project, "--source-root", source, "--no-color"],
        env
      ),
      0
    );
    assert.equal(
      await installer.main(
        ["--claude", "--update", "--local", "--project", project, "--source-root", source, "--no-color"],
        env
      ),
      0
    );
    assert.ok(fs.existsSync(path.join(project, "AGENTS.md")));
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

test("hooks init adds guards without changing existing project contracts", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const project = path.join(root, "existing-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  fs.writeFileSync(path.join(project, "AGENTS.md"), "existing agents\n");
  fs.writeFileSync(path.join(project, "WORKFLOW.md"), "existing workflow\n");

  assert.equal(
    await installer.main(
      [
        "--hooks-init",
        "--claude",
        "--project",
        project,
        "--source-root",
        source,
        "--no-color",
      ],
      env
    ),
    0
  );

  assert.equal(fs.readFileSync(path.join(project, "AGENTS.md"), "utf8"), "existing agents\n");
  assert.equal(
    fs.readFileSync(path.join(project, "WORKFLOW.md"), "utf8"),
    "existing workflow\n"
  );
  for (const name of installer.GUARD_SCRIPTS) {
    assert.ok(fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY, name)));
  }
  for (const name of installer.PROJECT_RUNTIME_SCRIPTS) {
    assert.ok(
      fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY, "runtime", name))
    );
  }
  assert.ok(fs.existsSync(path.join(project, ".claude", "settings.json")));
  assert.ok(fs.existsSync(path.join(project, ".git", "hooks", "pre-commit")));
  assert.ok(fs.existsSync(path.join(project, ".git", "hooks", "commit-msg")));
});

test("hooks init ignores unselected foreign native configs", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const project = path.join(root, "existing-grok-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const settings = path.join(project, ".claude", "settings.json");
  fs.mkdirSync(path.dirname(settings), { recursive: true });
  const original = JSON.stringify({ hooks: { custom: true } }) + "\n";
  fs.writeFileSync(settings, original);

  const status = await installer.main(
    [
      "--hooks-init",
      "--grok",
      "--project",
      project,
      "--source-root",
      source,
      "--no-color",
    ],
    env
  );

  assert.equal(status, 0);
  assert.equal(fs.readFileSync(settings, "utf8"), original);
  assert.ok(fs.existsSync(path.join(project, ".git", "hooks", "pre-commit")));
});

test("hooks install guard scripts, settings, and git hook", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  const results = await runInstall([installer.targetPlan("claude", target)], {
    project,
    hooks: true,
  });
  for (const name of installer.GUARD_SCRIPTS) {
    assert.equal(
      fs.readFileSync(path.join(project, installer.HOOKS_DIRECTORY, name), "utf8"),
      `# ${name}\n${installer.GUARD_MARKER}\n`
    );
  }
  const settings = JSON.parse(
    fs.readFileSync(path.join(project, ".claude", "settings.json"), "utf8")
  );
  assert.ok(settings.hooks.PreToolUse);
  assert.equal(settings.hooks.PreToolUse[0].matcher, installer.CLAUDE_MATCHER);
  assert.match("PowerShell", new RegExp(`^(?:${settings.hooks.PreToolUse[0].matcher})$`));
  assert.match("SaveFile", new RegExp(`^(?:${settings.hooks.PreToolUse[0].matcher})$`));
  assert.match(
    "mcp__filesystem__write_file",
    new RegExp(`^(?:${settings.hooks.PreToolUse[0].matcher})$`)
  );
  const preCommit = path.join(project, ".git", "hooks", "pre-commit");
  const commitMsg = path.join(project, ".git", "hooks", "commit-msg");
  assert.equal(fs.readFileSync(preCommit, "utf8"), installer.preCommitHook("python3"));
  assert.equal(fs.readFileSync(commitMsg, "utf8"), installer.commitMsgHook("python3"));
  assert.equal(
    fs.readFileSync(path.join(project, ".git", "hooks", "pre-push"), "utf8"),
    installer.prePushHook("python3")
  );
  if (process.platform !== "win32") {
    assert.ok(fs.statSync(commitMsg).mode & 0o100);
  }
  const projectLine = results.find((line) => line.startsWith("project:"));
  assert.match(projectLine, /\.gsd-path\/guard_hook\.py/);
  assert.match(projectLine, /\.git\/hooks\/pre-commit/);
  assert.match(projectLine, /\.git\/hooks\/commit-msg/);
});

test("hooks install native Codex and Cursor project configs", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const project = path.join(root, "native-hooks-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  await runInstall(
    [
      installer.targetPlan("codex", path.join(root, "codex", "skills")),
      installer.targetPlan("cursor", path.join(root, "cursor", "skills")),
    ],
    { project, hooks: true }
  );

  const codex = JSON.parse(fs.readFileSync(path.join(project, ".codex", "hooks.json"), "utf8"));
  assert.equal(
    codex.hooks.PreToolUse[0].hooks[0].command,
    'python3 "$(git rev-parse --show-toplevel)/.gsd-path/guard_hook.py"'
  );
  assert.match(codex.hooks.PreToolUse[0].hooks[0].commandWindows, /\.gsd-path\\guard_hook\.py/);
  const cursor = JSON.parse(fs.readFileSync(path.join(project, ".cursor", "hooks.json"), "utf8"));
  assert.equal(cursor.version, 1);
  assert.equal(cursor.hooks.preToolUse[0].command, 'python3 ".gsd-path/guard_hook.py"');
  assert.equal(cursor.hooks.preToolUse[0].failClosed, true);
});

test("hooks install merges selected native configs", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const project = path.join(root, "existing-native-hooks-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const codexPath = path.join(project, ".codex", "hooks.json");
  const cursorPath = path.join(project, ".cursor", "hooks.json");
  fs.mkdirSync(path.dirname(codexPath));
  fs.mkdirSync(path.dirname(cursorPath));
  fs.writeFileSync(
    codexPath,
    JSON.stringify({
      userSetting: true,
      hooks: {
        PreToolUse: [
          { matcher: "Write", hooks: [{ type: "command", command: "custom-codex" }] },
        ],
      },
    }) + "\n"
  );
  fs.writeFileSync(
    cursorPath,
    JSON.stringify({
      version: 1,
      userSetting: true,
      hooks: { preToolUse: [{ command: "custom-cursor" }] },
    }) + "\n"
  );

  await runInstall(
    [
      installer.targetPlan("codex", path.join(root, "codex", "skills")),
      installer.targetPlan("cursor", path.join(root, "cursor", "skills")),
    ],
    { project, hooks: true }
  );

  const codex = JSON.parse(fs.readFileSync(codexPath, "utf8"));
  assert.equal(codex.userSetting, true);
  assert.equal(codex.hooks.PreToolUse.length, 2);
  assert.equal(codex.hooks.PreToolUse[0].matcher, "Write");
  assert.equal(codex.hooks.PreToolUse[0].hooks[0].command, "custom-codex");
  assert.match(codex.hooks.PreToolUse[1].hooks[0].command, /guard_hook\.py/);
  const cursor = JSON.parse(fs.readFileSync(cursorPath, "utf8"));
  assert.equal(cursor.userSetting, true);
  assert.equal(cursor.hooks.preToolUse.length, 2);
  assert.equal(cursor.hooks.preToolUse[0].command, "custom-cursor");
  assert.match(cursor.hooks.preToolUse[1].command, /guard_hook\.py/);
});

test("native hook install rejects unsafe project directories", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  for (const host of ["codex", "cursor"]) {
    const project = path.join(root, `unsafe-${host}-project`);
    const outside = path.join(root, `outside-${host}`);
    fs.mkdirSync(path.join(project, ".git"), { recursive: true });
    fs.mkdirSync(outside);
    fs.symlinkSync(outside, path.join(project, `.${host}`), "dir");
    const target = path.join(root, host, "skills");

    await assert.rejects(
      runInstall([installer.targetPlan(host, target)], { project, hooks: true }),
      new RegExp(`unsafe ${host[0].toUpperCase()}${host.slice(1)} project directory`)
    );
    assert.ok(!fs.existsSync(path.join(outside, "hooks.json")));
    assert.ok(!fs.existsSync(target));
  }
});

test("hooks refresh updates managed guard scripts", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  fs.writeFileSync(
    path.join(source, "scripts", "guard_hook.py"),
    "# guard v2\n" + installer.GUARD_MARKER + "\n"
  );
  fs.writeFileSync(
    path.join(source, "scripts", "pipeline_state.py"),
    "# runtime v2\n" + installer.PROJECT_RUNTIME_MARKER + "\n"
  );
  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );
  assert.equal(status, 0);
  assert.match(
    fs.readFileSync(path.join(project, installer.HOOKS_DIRECTORY, "guard_hook.py"), "utf8"),
    /guard v2/
  );
  assert.match(
    fs.readFileSync(
      path.join(project, installer.HOOKS_DIRECTORY, "runtime", "pipeline_state.py"),
      "utf8"
    ),
    /runtime v2/
  );
  assert.ok(fs.existsSync(target));
});

test("hooks refresh updates runtime without optional guards", async () => {
  const project = path.join(root, "hookless-project");
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project });
  fs.writeFileSync(
    path.join(source, "scripts", "pipeline_state.py"),
    "# runtime v2\n" + installer.PROJECT_RUNTIME_MARKER + "\n"
  );

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );

  assert.equal(status, 0);
  assert.match(
    fs.readFileSync(
      path.join(project, installer.HOOKS_DIRECTORY, "runtime", "pipeline_state.py"),
      "utf8"
    ),
    /runtime v2/
  );
  for (const name of installer.GUARD_SCRIPTS) {
    assert.ok(!fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY, name)));
  }
});

test("hookless refresh requires an interpreter before writes", async () => {
  const project = path.join(root, "hookless-refresh-project");
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project });
  const runtime = path.join(
    project,
    installer.HOOKS_DIRECTORY,
    "runtime",
    "pipeline_state.py"
  );
  const before = fs.readFileSync(runtime);
  fs.writeFileSync(
    path.join(source, "scripts", "pipeline_state.py"),
    "# runtime v2\n" + installer.PROJECT_RUNTIME_MARKER + "\n"
  );
  installer.hooks.detectPythonInterpreter = () => null;

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );

  assert.equal(status, 1);
  assert.deepEqual(fs.readFileSync(runtime), before);
});

test("hooks refresh full updates settings and git hooks", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const settingsPath = path.join(project, ".claude", "settings.json");
  const settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  settings.hooks.PreToolUse[0].matcher = "old";
  fs.writeFileSync(settingsPath, JSON.stringify(settings) + "\n");
  const status = await installer.main(
    [
      "--hooks-refresh-full",
      "--project",
      project,
      "--source-root",
      source,
      "--no-color",
    ]
  );
  assert.equal(status, 0);
  const refreshed = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  assert.equal(refreshed.hooks.PreToolUse[0].matcher, installer.CLAUDE_MATCHER);
});

test("hooks refresh full updates native Codex and Cursor configs", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const project = path.join(root, "native-hooks-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  await runInstall(
    [
      installer.targetPlan("codex", path.join(root, "codex", "skills")),
      installer.targetPlan("cursor", path.join(root, "cursor", "skills")),
    ],
    { project, hooks: true }
  );
  const codexPath = path.join(project, ".codex", "hooks.json");
  const codex = JSON.parse(fs.readFileSync(codexPath, "utf8"));
  codex.hooks.PreToolUse[0].hooks[0].command = 'python "C:\\repo\\.gsd-path\\guard_hook.py"';
  codex.hooks.PreToolUse[0].matcher = "Write";
  codex.hooks.PreToolUse[0].hooks.push({ type: "command", command: "custom-codex" });
  codex.userSetting = true;
  fs.writeFileSync(codexPath, JSON.stringify(codex) + "\n");
  const cursorPath = path.join(project, ".cursor", "hooks.json");
  const cursor = JSON.parse(fs.readFileSync(cursorPath, "utf8"));
  cursor.hooks.preToolUse[0].command = 'python "C:\\repo\\.gsd-path\\guard_hook.py"';
  cursor.userSetting = true;
  fs.writeFileSync(cursorPath, JSON.stringify(cursor) + "\n");

  const status = await installer.main(
    ["--hooks-refresh-full", "--project", project, "--source-root", source, "--no-color"]
  );

  assert.equal(status, 0);
  const refreshedCodex = JSON.parse(fs.readFileSync(codexPath, "utf8"));
  assert.equal(
    refreshedCodex.hooks.PreToolUse[0].hooks[0].command,
    'python3 "$(git rev-parse --show-toplevel)/.gsd-path/guard_hook.py"'
  );
  assert.equal(refreshedCodex.userSetting, true);
  assert.equal(refreshedCodex.hooks.PreToolUse.length, 2);
  assert.equal(refreshedCodex.hooks.PreToolUse[0].hooks.length, 1);
  assert.equal(refreshedCodex.hooks.PreToolUse[1].matcher, "Write");
  assert.equal(refreshedCodex.hooks.PreToolUse[1].hooks[0].command, "custom-codex");
  const refreshedCursor = JSON.parse(fs.readFileSync(cursorPath, "utf8"));
  assert.equal(
    refreshedCursor.hooks.preToolUse[0].command,
    'python3 ".gsd-path/guard_hook.py"'
  );
  assert.equal(refreshedCursor.hooks.preToolUse[0].failClosed, true);
  assert.equal(refreshedCursor.userSetting, true);
  assert.equal(refreshedCursor.hooks.preToolUse.length, 1);
});

test("hooks refresh full creates selected missing native configs", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const project = path.join(root, "existing-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  await runInstall([installer.targetPlan("claude", path.join(root, "claude", "skills"))], {
    project,
    hooks: true,
  });

  const status = await installer.main(
    [
      "--hooks-refresh-full",
      "--codex",
      "--cursor",
      "--project",
      project,
      "--source-root",
      source,
      "--no-color",
    ]
  );

  assert.equal(status, 0);
  assert.ok(fs.existsSync(path.join(project, ".codex", "hooks.json")));
  assert.ok(fs.existsSync(path.join(project, ".cursor", "hooks.json")));
  assert.equal(
    fs.readFileSync(path.join(project, "AGENTS.md"), "utf8"),
    fs.readFileSync(path.join(source, "AGENTS.md"), "utf8")
  );
});

test("hooks refresh full merges selected foreign native configs", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const project = path.join(root, "foreign-native-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  await runInstall([installer.targetPlan("claude", path.join(root, "claude", "skills"))], {
    project,
    hooks: true,
  });
  const codexPath = path.join(project, ".codex", "hooks.json");
  const cursorPath = path.join(project, ".cursor", "hooks.json");
  fs.mkdirSync(path.dirname(codexPath));
  fs.mkdirSync(path.dirname(cursorPath));
  fs.writeFileSync(
    codexPath,
    JSON.stringify({
      custom: "codex",
      hooks: {
        PreToolUse: [
          { matcher: "Custom", hooks: [{ type: "command", command: "custom-codex" }] },
        ],
      },
    })
  );
  fs.writeFileSync(
    cursorPath,
    JSON.stringify({
      custom: "cursor",
      hooks: { preToolUse: [{ matcher: "Custom", command: "custom-cursor" }] },
    })
  );

  const status = await installer.main([
    "--hooks-refresh-full",
    "--codex",
    "--cursor",
    "--project",
    project,
    "--source-root",
    source,
    "--no-color",
  ]);

  assert.equal(status, 0);
  const codex = JSON.parse(fs.readFileSync(codexPath, "utf8"));
  const cursor = JSON.parse(fs.readFileSync(cursorPath, "utf8"));
  assert.equal(codex.custom, "codex");
  assert.equal(codex.hooks.PreToolUse[0].hooks[0].command, "custom-codex");
  assert.equal(codex.hooks.PreToolUse.length, 2);
  assert.equal(cursor.custom, "cursor");
  assert.equal(cursor.hooks.preToolUse[0].command, "custom-cursor");
  assert.equal(cursor.hooks.preToolUse.length, 2);
});

test("hooks refresh full rejects an unselected foreign native config", async () => {
  const project = path.join(root, "unselected-foreign-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  await runInstall([installer.targetPlan("claude", path.join(root, "claude", "skills"))], {
    project,
    hooks: true,
  });
  const settings = path.join(project, ".codex", "hooks.json");
  fs.mkdirSync(path.dirname(settings));
  const original = JSON.stringify({
    hooks: {
      PreToolUse: [
        { matcher: ".*", hooks: [{ type: "command", command: "echo .gsd-path/guard_hook.py" }] },
      ],
    },
  }) + "\n";
  fs.writeFileSync(settings, original);

  const status = await installer.main([
    "--hooks-refresh-full",
    "--project",
    project,
    "--source-root",
    source,
    "--no-color",
  ]);

  assert.equal(status, 1);
  assert.equal(fs.readFileSync(settings, "utf8"), original);
});

test("hooks refresh full does not follow the legacy temporary symlink", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const project = path.join(root, "temporary-symlink-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  await runInstall([installer.targetPlan("codex", path.join(root, "codex", "skills"))], {
    project,
    hooks: true,
  });
  const outside = path.join(root, "outside-hooks.json");
  fs.writeFileSync(outside, "outside\n");
  const legacyTemporary = path.join(project, ".codex", ".hooks.json.gsd-path-tmp");
  fs.symlinkSync(outside, legacyTemporary);

  const status = await installer.main([
    "--hooks-refresh-full",
    "--codex",
    "--project",
    project,
    "--source-root",
    source,
    "--no-color",
  ]);

  assert.equal(status, 0);
  assert.equal(fs.readFileSync(outside, "utf8"), "outside\n");
  assert.ok(fs.lstatSync(legacyTemporary).isSymbolicLink());
});

test("hooks refresh full rejects a symlinked native parent", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const project = path.join(root, "symlink-parent-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  await runInstall([installer.targetPlan("codex", path.join(root, "codex", "skills"))], {
    project,
    hooks: true,
  });
  const outside = path.join(root, "outside-codex");
  fs.renameSync(path.join(project, ".codex"), outside);
  fs.symlinkSync(outside, path.join(project, ".codex"), "dir");
  const before = fs.readFileSync(path.join(outside, "hooks.json"), "utf8");

  const status = await installer.main([
    "--hooks-refresh-full",
    "--project",
    project,
    "--source-root",
    source,
    "--no-color",
  ]);

  assert.equal(status, 1);
  assert.equal(fs.readFileSync(path.join(outside, "hooks.json"), "utf8"), before);
});

test("hooks refresh rejects unmanaged guard scripts", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, installer.HOOKS_DIRECTORY), { recursive: true });
  fs.writeFileSync(path.join(project, installer.HOOKS_DIRECTORY, "guard_hook.py"), "custom\n");
  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );
  assert.equal(status, 1);
});

test("hooks refresh rejects a project without managed ownership", async () => {
  const project = path.join(root, "unowned-project");
  fs.mkdirSync(project);

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );

  assert.equal(status, 1);
  assert.ok(!fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY)));
});

test("hooks refresh initializes runtime for a legacy project install", async () => {
  const project = path.join(root, "legacy-project");
  fs.mkdirSync(project);
  fs.copyFileSync(path.join(REPO_ROOT, "AGENTS.md"), path.join(project, "AGENTS.md"));
  fs.copyFileSync(path.join(REPO_ROOT, "WORKFLOW.md"), path.join(project, "WORKFLOW.md"));

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );

  assert.equal(status, 0);
  assert.ok(fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY, "runtime", "pipeline_state.py")));
  assert.ok(!fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY, "guard_hook.py")));
});

test("hooks refresh and doctor reject marker-only legacy contracts", async () => {
  const project = path.join(root, "stale-legacy-project");
  fs.mkdirSync(project);
  fs.writeFileSync(
    path.join(project, "AGENTS.md"),
    "# AGENTS.md — Operating Rules for the GSD Path Pipeline\n\n## Plain-prompt re-entry\n\n" +
      "<!-- gsd-path/plain-prompt-reentry/v1 -->\n"
  );
  fs.writeFileSync(
    path.join(project, "WORKFLOW.md"),
    "# WORKFLOW.md — GSD Path Pipeline SOP\n\n### Plain-prompt re-entry\n\n" +
      "<!-- gsd-path/plain-prompt-reentry/v1 -->\n"
  );

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );
  const findings = installer.doctor(source, { targets: [], rootFor: () => "", project });

  assert.equal(status, 1);
  assert.ok(!fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY)));
  assert.ok(findings.some(({ level, text }) => level === "fail" && /lacks plain-prompt re-entry/.test(text)));
});

test("hooks refresh honors the project ownership lock", async () => {
  const project = path.join(root, "locked-refresh-project");
  await runInstall([installer.targetPlan("claude", path.join(root, "locked-claude", "skills"))], { project });
  const runtime = path.join(project, installer.HOOKS_DIRECTORY, "runtime", "pipeline_state.py");
  const before = fs.readFileSync(runtime);
  fs.mkdirSync(path.join(project, ".gsd-path-install-lock"));

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );

  assert.equal(status, 1);
  assert.ok(fs.readFileSync(runtime).equals(before));
});

test("project install honors the project ownership lock", async () => {
  const project = path.join(root, "locked-install-project");
  const target = path.join(root, "locked-install-claude", "skills");
  fs.mkdirSync(project);
  fs.mkdirSync(path.join(project, ".gsd-path-install-lock"));

  const status = await installer.main([
    "--claude",
    "--claude-root",
    target,
    "--source-root",
    source,
    "--project",
    project,
    "--no-color",
  ]);

  assert.equal(status, 1);
  assert.ok(!fs.existsSync(path.join(project, "AGENTS.md")));
  assert.ok(!fs.existsSync(target));
});

test("runtime refresh restores the complete prior set after copy failure", async () => {
  const project = path.join(root, "transactional-runtime-project");
  await runInstall([installer.targetPlan("claude", path.join(root, "claude", "skills"))], { project });
  const runtime = path.join(project, installer.HOOKS_DIRECTORY, "runtime");
  const before = new Map(
    installer.PROJECT_RUNTIME_SCRIPTS.map((name) => [name, fs.readFileSync(path.join(runtime, name))])
  );
  fs.writeFileSync(
    path.join(source, "scripts", "pipeline_state.py"),
    `# changed\n${installer.PROJECT_RUNTIME_MARKER}\n`
  );
  let copies = 0;
  installer.hooks.copyRuntimeFile = (sourceFile, destination) => {
    copies += 1;
    if (copies === 2) throw new Error("injected runtime copy failure");
    fs.copyFileSync(sourceFile, destination);
  };

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );

  assert.equal(status, 1);
  for (const [name, content] of before) {
    assert.ok(fs.readFileSync(path.join(runtime, name)).equals(content));
  }
});

test("hooks refresh rejects unexpected runtime entries", async () => {
  const project = path.join(root, "runtime-extra-project");
  await runInstall([installer.targetPlan("claude", path.join(root, "claude", "skills"))], { project });
  const extra = path.join(project, installer.HOOKS_DIRECTORY, "runtime", "site_policy.py");
  fs.writeFileSync(extra, "keep\n");

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );

  assert.equal(status, 1);
  assert.equal(fs.readFileSync(extra, "utf8"), "keep\n");
});

test("guard failure rolls back the published runtime and guards", async () => {
  const project = path.join(root, "guard-runtime-transaction");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  await runInstall([installer.targetPlan("claude", path.join(root, "claude", "skills"))], { project, hooks: true });
  const runtime = path.join(project, installer.HOOKS_DIRECTORY, "runtime");
  fs.rmSync(runtime, { recursive: true });
  const guard = path.join(project, installer.HOOKS_DIRECTORY, "guard_hook.py");
  const before = fs.readFileSync(guard);
  fs.chmodSync(guard, 0o600);
  fs.writeFileSync(path.join(source, "scripts", "guard_hook.py"), `# changed\n${installer.GUARD_MARKER}\n`);
  let guardCopies = 0;
  installer.hooks.copyGuardFile = (sourceFile, destination) => {
    guardCopies += 1;
    if (guardCopies === 2) throw new Error("injected guard failure");
    originalHooks.copyGuardFile(sourceFile, destination);
    fs.chmodSync(destination, 0o755);
  };

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );

  assert.equal(status, 1);
  assert.ok(fs.readFileSync(guard).equals(before));
  assert.equal(fs.statSync(guard).mode & 0o777, 0o600);
  assert.ok(!fs.existsSync(runtime));
});

test("hooks refresh rejects an unmanaged project runtime", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  await runInstall([installer.targetPlan("claude", path.join(root, "claude", "skills"))], {
    project,
    hooks: true,
  });
  const runtime = path.join(
    project,
    installer.HOOKS_DIRECTORY,
    "runtime",
    "pipeline_state.py"
  );
  fs.writeFileSync(runtime, "custom\n");

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );

  assert.equal(status, 1);
  assert.equal(fs.readFileSync(runtime, "utf8"), "custom\n");
});

test("hooks refresh reports an unreadable project runtime", async () => {
  const project = path.join(root, "unreadable-runtime-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "unreadable-runtime-claude", "skills");
  await runInstall(
    [installer.targetPlan("claude", target)],
    { project, hooks: true }
  );
  const runtime = path.join(
    project,
    installer.HOOKS_DIRECTORY,
    "runtime",
    "pipeline_state.py"
  );
  const originalReadFileSync = fs.readFileSync;
  fs.readFileSync = (candidate, ...args) => {
    if (path.resolve(candidate) === path.resolve(runtime)) {
      const error = new Error("injected unreadable runtime");
      error.code = "EACCES";
      throw error;
    }
    return originalReadFileSync(candidate, ...args);
  };
  let status;
  try {
    status = await installer.main([
      "--hooks-refresh",
      "--project",
      project,
      "--source-root",
      source,
      "--no-color",
    ]);
  } finally {
    fs.readFileSync = originalReadFileSync;
  }

  assert.equal(status, 1);
});

test("hooks refresh rejects a symlinked project runtime", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  await runInstall([installer.targetPlan("claude", path.join(root, "claude", "skills"))], {
    project,
    hooks: true,
  });
  const runtime = path.join(
    project,
    installer.HOOKS_DIRECTORY,
    "runtime",
    "pipeline_state.py"
  );
  const outside = path.join(root, "outside-runtime.py");
  fs.renameSync(runtime, outside);
  fs.symlinkSync(outside, runtime);

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );

  assert.equal(status, 1);
  assert.ok(fs.lstatSync(runtime).isSymbolicLink());
  assert.match(fs.readFileSync(outside, "utf8"), /gsd-path project runtime/);
});

test("project install rejects a symlinked runtime directory", async () => {
  const project = path.join(root, "symlinked-runtime-project");
  const outside = path.join(root, "outside-runtime");
  fs.mkdirSync(path.join(project, installer.HOOKS_DIRECTORY), { recursive: true });
  fs.mkdirSync(outside);
  fs.symlinkSync(outside, path.join(project, installer.HOOKS_DIRECTORY, "runtime"), "dir");
  const target = path.join(root, "claude", "skills");

  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { project }),
    /symlink/
  );

  assert.deepEqual(fs.readdirSync(outside), []);
  assert.ok(!fs.existsSync(target));
});

test("project install rejects a symlinked runtime parent", async () => {
  const project = path.join(root, "symlinked-runtime-parent-project");
  const outside = path.join(root, "outside-runtime-parent");
  fs.mkdirSync(project);
  fs.mkdirSync(path.join(outside, "runtime"), { recursive: true });
  fs.symlinkSync(outside, path.join(project, installer.HOOKS_DIRECTORY), "dir");
  const target = path.join(root, "claude-parent", "skills");

  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { project }),
    /symlink/
  );

  assert.deepEqual(fs.readdirSync(path.join(outside, "runtime")), []);
  assert.ok(!fs.existsSync(target));
});

test("hooks refresh rejects a symlinked runtime directory", async () => {
  const project = path.join(root, "refresh-symlinked-runtime-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const runtime = path.join(project, installer.HOOKS_DIRECTORY, "runtime");
  const outside = path.join(root, "outside-refresh-runtime");
  fs.renameSync(runtime, outside);
  fs.symlinkSync(outside, runtime, "dir");
  const destination = path.join(outside, "pipeline_state.py");
  const before = fs.readFileSync(destination);
  fs.writeFileSync(
    path.join(source, "scripts", "pipeline_state.py"),
    "# runtime v2\n" + installer.PROJECT_RUNTIME_MARKER + "\n"
  );

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );

  assert.equal(status, 1);
  assert.deepEqual(fs.readFileSync(destination), before);
});

test("hooks refresh full merges settings preserving unrelated keys", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const settingsPath = path.join(project, ".claude", "settings.json");
  const settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  settings.hooks.PreToolUse[0].matcher = "old";
  settings.permissions = { allow: ["Bash(npm test)"] };
  settings.model = "opus";
  fs.writeFileSync(settingsPath, JSON.stringify(settings) + "\n");
  const status = await installer.main(
    ["--hooks-refresh-full", "--project", project, "--source-root", source, "--no-color"]
  );
  assert.equal(status, 0);
  const refreshed = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  assert.equal(refreshed.hooks.PreToolUse[0].matcher, installer.CLAUDE_MATCHER);
  assert.deepEqual(refreshed.permissions, { allow: ["Bash(npm test)"] });
  assert.equal(refreshed.model, "opus");
});

test("hooks refresh full rejects a malformed managed settings file", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const settingsPath = path.join(project, ".claude", "settings.json");
  fs.writeFileSync(settingsPath, "{ guard_hook.py .gsd-path\n");
  const status = await installer.main(
    ["--hooks-refresh-full", "--project", project, "--source-root", source, "--no-color"]
  );
  assert.equal(status, 1);
  assert.equal(fs.readFileSync(settingsPath, "utf8"), "{ guard_hook.py .gsd-path\n");
});

test("hooks refresh full recreates missing git hooks and fixes modes", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const preCommit = path.join(project, ".git", "hooks", "pre-commit");
  const commitMsg = path.join(project, ".git", "hooks", "commit-msg");
  fs.rmSync(preCommit);
  if (process.platform !== "win32") fs.chmodSync(commitMsg, 0o644);
  const status = await installer.main(
    ["--hooks-refresh-full", "--project", project, "--source-root", source, "--no-color"]
  );
  assert.equal(status, 0);
  assert.equal(fs.readFileSync(preCommit, "utf8"), installer.preCommitHook("python3"));
  if (process.platform !== "win32") {
    assert.ok(fs.statSync(preCommit).mode & 0o100);
    assert.ok(fs.statSync(commitMsg).mode & 0o100);
  }
});

test("hooks refresh full rejects a symlinked settings file", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const settingsPath = path.join(project, ".claude", "settings.json");
  const outside = path.join(root, "outside-settings.json");
  fs.renameSync(settingsPath, outside);
  fs.symlinkSync(outside, settingsPath);
  const before = fs.readFileSync(outside, "utf8");
  const status = await installer.main(
    ["--hooks-refresh-full", "--project", project, "--source-root", source, "--no-color"]
  );
  assert.equal(status, 1);
  assert.equal(fs.readFileSync(outside, "utf8"), before);
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

test("native hooks require an initialized repository", async () => {
  const project = path.join(root, "project");
  const target = path.join(root, "claude", "skills");
  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { project, hooks: true }),
    /initialized Git repository.*selected hosts: claude/
  );
  assert.ok(!fs.existsSync(path.join(project, ".git")));
  assert.ok(!fs.existsSync(path.join(project, ".claude", "settings.json")));
  assert.ok(!fs.existsSync(target));
});

test("git-only hooks require an initialized repository", async () => {
  const project = path.join(root, "plain-project");
  const target = path.join(root, "grok", "skills");

  await assert.rejects(
    runInstall([installer.targetPlan("grok", target)], { project, hooks: true }),
    /initialized Git repository.*selected hosts: grok/
  );

  assert.ok(!fs.existsSync(target));
  assert.ok(!fs.existsSync(path.join(project, "AGENTS.md")));
});

test("git-only hooks require a Python interpreter", async () => {
  installer.hooks.detectPythonInterpreter = () => null;
  const project = path.join(root, "grok-project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "grok", "skills");

  await assert.rejects(
    runInstall([installer.targetPlan("grok", target)], { project, hooks: true }),
    /working Python interpreter.*selected hosts: grok/
  );

  assert.ok(!fs.existsSync(target));
  assert.ok(!fs.existsSync(path.join(project, "AGENTS.md")));
});

test("hooks install merges an existing Claude settings file", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  fs.mkdirSync(path.join(project, ".claude"), { recursive: true });
  const settingsPath = path.join(project, ".claude", "settings.json");
  fs.writeFileSync(
    settingsPath,
    JSON.stringify({
      userSetting: true,
      hooks: { PreToolUse: [{ matcher: "Write", hooks: [{ type: "command", command: "custom" }] }] },
    }) + "\n"
  );
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  assert.equal(settings.userSetting, true);
  assert.equal(settings.hooks.PreToolUse.length, 2);
  assert.equal(settings.hooks.PreToolUse[0].hooks[0].command, "custom");
  assert.match(settings.hooks.PreToolUse[1].hooks[0].command, /guard_hook\.py/);
  assert.ok(fs.existsSync(path.join(project, "AGENTS.md")));
});

test("hooks collision rolls back cleanly", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  fs.mkdirSync(path.join(project, ".claude"), { recursive: true });
  fs.writeFileSync(path.join(project, ".claude", "settings.json"), "not json");
  const target = path.join(root, "claude", "skills");
  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { project, hooks: true }),
    /settings/
  );
  assert.ok(!fs.existsSync(target));
  assert.ok(!fs.existsSync(path.join(project, "AGENTS.md")));
  assert.equal(fs.readFileSync(path.join(project, ".claude", "settings.json"), "utf8"), "not json");
});

test("hooks dry run lists files without writing", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  const results = await runInstall([installer.targetPlan("claude", target)], {
    project,
    hooks: true,
    dryRun: true,
  });
  const projectLine = results.find((line) => line.startsWith("project:"));
  assert.match(projectLine, /\.gsd-path\/guard_hook\.py/);
  assert.match(projectLine, /\.git\/hooks\/commit-msg/);
  assert.ok(!fs.existsSync(target));
  assert.ok(!fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY)));
});

test("doctor reports a healthy install, hooks, and project", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const findings = installer.doctor(source, {
    targets: ["claude"],
    rootFor: () => target,
    project,
  });
  assert.ok(!findings.some((finding) => finding.level === "fail"));
  assert.ok(findings.some((finding) => finding.text.includes("(v9.9.9)")));
  assert.ok(findings.some((finding) => /guard_hook\.py current/.test(finding.text)));
  assert.ok(findings.some((finding) => /pre-commit wired/.test(finding.text)));
});

test("doctor rejects a symlinked project runtime", async () => {
  const project = path.join(root, "doctor-symlinked-runtime");
  const runtimeParent = path.join(project, installer.HOOKS_DIRECTORY);
  fs.mkdirSync(runtimeParent, { recursive: true });
  const outside = path.join(root, "outside-runtime");
  fs.mkdirSync(outside);
  for (const name of installer.PROJECT_RUNTIME_SCRIPTS) {
    fs.copyFileSync(path.join(source, "scripts", name), path.join(outside, name));
  }
  fs.symlinkSync(outside, path.join(runtimeParent, "runtime"), "dir");

  const findings = installer.doctor(source, {
    targets: [],
    rootFor: () => "",
    project,
  });

  assert.ok(findings.some((finding) => finding.level === "fail" && /symlink/.test(finding.text)));
  assert.ok(
    !findings.some(
      (finding) => finding.level === "ok" && finding.text.startsWith("project: runtime")
    )
  );
});

test("doctor rejects symlinked project contracts", () => {
  const project = path.join(root, "doctor-symlinked-contracts");
  fs.mkdirSync(project);
  for (const name of ["AGENTS.md", "WORKFLOW.md"]) {
    fs.symlinkSync(path.join(source, name), path.join(project, name));
  }

  const findings = installer.doctor(source, {
    targets: [],
    rootFor: () => "",
    project,
  });

  for (const name of ["AGENTS.md", "WORKFLOW.md"]) {
    assert.ok(
      findings.some(
        ({ level, text }) =>
          level === "fail" && text === `project: contract ${name} is a symlink`
      )
    );
  }
});

test("doctor rejects symlinked and unreadable project scripts", () => {
  const project = path.join(root, "doctor-unsafe-scripts");
  const managed = path.join(project, installer.HOOKS_DIRECTORY);
  const runtime = path.join(managed, "runtime");
  fs.mkdirSync(runtime, { recursive: true });
  for (const name of installer.PROJECT_RUNTIME_SCRIPTS) {
    fs.copyFileSync(path.join(source, "scripts", name), path.join(runtime, name));
  }
  const outsideGuard = path.join(root, "outside-guard.py");
  fs.copyFileSync(path.join(source, "scripts", "guard_hook.py"), outsideGuard);
  fs.symlinkSync(outsideGuard, path.join(managed, "guard_hook.py"));
  fs.copyFileSync(
    path.join(source, "scripts", "git_guard.py"),
    path.join(managed, "git_guard.py")
  );
  const unreadable = path.join(runtime, "pipeline_state.py");
  fs.chmodSync(unreadable, 0);
  let findings;
  try {
    findings = installer.doctor(source, { targets: [], rootFor: () => "", project });
  } finally {
    fs.chmodSync(unreadable, 0o644);
  }

  assert.ok(
    findings.some(
      (finding) => finding.level === "fail" && /guard_hook\.py is a symlink/.test(finding.text)
    )
  );
  assert.ok(
    findings.some(
      (finding) =>
        finding.level === "fail" && /runtime pipeline_state\.py cannot be read/.test(finding.text)
    )
  );
});

test("doctor reports a missing canonical runtime source", async () => {
  const project = path.join(root, "doctor-missing-source");
  await runInstall([installer.targetPlan("claude", path.join(root, "claude", "skills"))], { project });
  fs.unlinkSync(path.join(source, "scripts", "pipeline_state.py"));

  const findings = installer.doctor(source, { targets: [], rootFor: () => "", project });

  assert.ok(
    findings.some(
      ({ level, text }) =>
        level === "fail" && /package: runtime pipeline_state\.py cannot be read/.test(text)
    )
  );
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

test("doctor reports unreadable bridge and git hooks", async () => {
  const project = path.join(root, "doctor-unreadable-contracts");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const bridge = path.join(project, ".claude", "CLAUDE.md");
  const preCommit = path.join(project, ".git", "hooks", "pre-commit");
  fs.chmodSync(bridge, 0);
  fs.chmodSync(preCommit, 0);
  let findings;
  try {
    findings = installer.doctor(source, {
      targets: ["claude"],
      rootFor: () => target,
      project,
    });
  } finally {
    fs.chmodSync(bridge, 0o644);
    fs.chmodSync(preCommit, 0o755);
  }

  assert.ok(
    findings.some(
      (finding) => finding.level === "fail" && /\.claude\/CLAUDE\.md cannot be read/.test(finding.text)
    )
  );
  assert.ok(
    findings.some(
      (finding) => finding.level === "fail" && /pre-commit cannot be read/.test(finding.text)
    )
  );
});

test("doctor fails when installer-owned native guard config is missing", async () => {
  for (const [targetName, settingsPath] of [
    ["claude", [".claude", "settings.json"]],
    ["codex", [".codex", "hooks.json"]],
    ["cursor", [".cursor", "hooks.json"]],
  ]) {
    const project = path.join(root, `${targetName}-native-doctor`);
    fs.mkdirSync(path.join(project, ".git"), { recursive: true });
    const target = path.join(root, targetName, "skills");
    await runInstall([installer.targetPlan(targetName, target)], { project, hooks: true });
    fs.rmSync(path.join(project, ...settingsPath));

    const findings = installer.doctor(source, {
      targets: [targetName],
      rootFor: () => target,
      project,
    });
    assert.ok(
      findings.some(
        (finding) =>
          finding.level === "fail" &&
          finding.text.includes(`${targetName} native guard wiring is missing`)
      )
    );
  }
});

test("doctor fails when managed wiring points to deleted guards", async () => {
  const project = path.join(root, "dangling-guards");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "dangling-guards-claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  fs.rmSync(target, { recursive: true });
  for (const name of installer.GUARD_SCRIPTS) {
    fs.rmSync(path.join(project, installer.HOOKS_DIRECTORY, name));
  }

  const findings = installer.doctor(source, {
    targets: ["claude"],
    rootFor: () => target,
    project,
  });

  for (const name of installer.GUARD_SCRIPTS) {
    assert.ok(
      findings.some(
        (finding) => finding.level === "fail" && finding.text.includes(`missing .gsd-path/${name}`)
      )
    );
  }

  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );
  assert.equal(status, 0);
  for (const name of installer.GUARD_SCRIPTS) {
    assert.ok(fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY, name)));
  }
});

test("doctor validates detected native wiring without installed skills", async () => {
  const project = path.join(root, "stale-native-wiring");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "stale-native-wiring-claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  fs.rmSync(target, { recursive: true });
  const settings = path.join(project, ".claude", "settings.json");
  const parsed = JSON.parse(fs.readFileSync(settings, "utf8"));
  parsed.hooks.PreToolUse[0].matcher = "Write";
  fs.writeFileSync(settings, `${JSON.stringify(parsed)}\n`);

  const findings = installer.doctor(source, {
    targets: ["claude"],
    rootFor: () => target,
    project,
  });

  assert.ok(
    findings.some(
      ({ level, text }) =>
        level === "fail" && text.includes("claude native guard wiring is stale")
    )
  );
});

test("doctor rejects symlinked native and git wiring", async () => {
  const project = path.join(root, "symlinked-wiring");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "symlinked-wiring-claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const settings = path.join(project, ".claude", "settings.json");
  const outsideSettings = path.join(root, "outside-settings.json");
  fs.copyFileSync(settings, outsideSettings);
  fs.rmSync(settings);
  fs.symlinkSync(outsideSettings, settings);
  const preCommit = path.join(project, ".git", "hooks", "pre-commit");
  const outsideHook = path.join(root, "outside-pre-commit");
  fs.copyFileSync(preCommit, outsideHook);
  fs.rmSync(preCommit);
  fs.symlinkSync(outsideHook, preCommit);

  const findings = installer.doctor(source, {
    targets: ["claude"],
    rootFor: () => target,
    project,
  });

  assert.ok(
    findings.some(
      ({ level, text }) =>
        level === "fail" && text.includes("claude native guard wiring is a symlink")
    )
  );
  assert.ok(
    findings.some(
      ({ level, text }) => level === "fail" && text.includes("pre-commit is a symlink")
    )
  );
});

test("doctor reports unreadable effective git hooks", async () => {
  const project = path.join(root, "unreadable-git-wiring");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "unreadable-git-wiring-claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  for (const name of installer.GUARD_SCRIPTS) {
    fs.rmSync(path.join(project, installer.HOOKS_DIRECTORY, name));
  }
  const hooks = installer.GIT_HOOK_NAMES.map((name) => path.join(project, ".git", "hooks", name));
  for (const hook of hooks) fs.chmodSync(hook, 0);
  let findings;
  try {
    findings = installer.doctor(source, {
      targets: [],
      rootFor: () => target,
      project,
    });
  } finally {
    for (const hook of hooks) fs.chmodSync(hook, 0o755);
  }

  for (const name of installer.GIT_HOOK_NAMES) {
    assert.ok(
      findings.some(
        ({ level, text }) =>
          level === "fail" && text.includes(name) && text.includes("cannot be read")
      )
    );
  }
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

test("doctor flags stale guard scripts", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  fs.writeFileSync(
    path.join(source, "scripts", "guard_hook.py"),
    "# guard v2\n" + installer.GUARD_MARKER + "\n"
  );
  const findings = installer.doctor(source, {
    targets: ["claude"],
    rootFor: () => target,
    project,
  });
  assert.ok(
    findings.some(
      (finding) => finding.level === "warn" && /guard_hook\.py is stale/.test(finding.text)
    )
  );
});

test("doctor uses canonical pipeline state validation", async () => {
  for (const name of installer.PROJECT_RUNTIME_SCRIPTS) {
    fs.copyFileSync(path.join(REPO_ROOT, "scripts", name), path.join(source, "scripts", name));
  }
  const project = path.join(root, "project");
  fs.mkdirSync(project);
  git("init", "-q", project);
  fs.mkdirSync(path.join(project, ".project"), { recursive: true });
  fs.writeFileSync(path.join(project, "AGENTS.md"), "a\n");
  fs.writeFileSync(path.join(project, "WORKFLOW.md"), "w\n");
  const runtime = path.join(project, installer.HOOKS_DIRECTORY, "runtime");
  fs.mkdirSync(runtime, { recursive: true });
  fs.copyFileSync(
    path.join(source, "scripts", installer.PROJECT_STATUS_LAUNCHER),
    path.join(project, installer.HOOKS_DIRECTORY, installer.PROJECT_STATUS_LAUNCHER)
  );
  for (const name of installer.PROJECT_RUNTIME_SCRIPTS) {
    fs.copyFileSync(path.join(source, "scripts", name), path.join(runtime, name));
  }
  fs.writeFileSync(
    path.join(project, ".project", "STATE.md"),
    "---\npipeline: gsd-path/v2\nproject: demo\nmilestone: demo\n" +
      "phase: plan\nstatus: done\nbranch: null\narchive: null\n---\n"
  );
  let findings = installer.doctor(source, { targets: [], rootFor: () => "", project });
  assert.ok(
    findings.some((finding) => finding.level === "ok" && finding.text === "state: plan/done"),
    JSON.stringify(findings)
  );
  assert.ok(!fs.existsSync(path.join(source, "scripts", "__pycache__")));
  const runtimeState = path.join(runtime, "pipeline_state.py");
  const originalRuntime = fs.readFileSync(runtimeState);
  const doctorSideEffect = path.join(project, "doctor-runtime-executed");
  fs.writeFileSync(
    runtimeState,
    "from pathlib import Path\n" +
      `Path(${JSON.stringify(doctorSideEffect)}).write_text("executed")\n` +
      `# ${installer.PROJECT_RUNTIME_MARKER}\n`
  );
  findings = installer.doctor(source, { targets: [], rootFor: () => "", project });
  assert.ok(
    findings.some(
      (finding) =>
        finding.level === "fail" && /project runtime status was not executed/.test(finding.text)
    )
  );
  assert.ok(!fs.existsSync(doctorSideEffect));
  fs.writeFileSync(runtimeState, originalRuntime);
  const originalValidator = originalHooks.validatedProjectState;
  installer.hooks.validatedProjectState = (...args) => {
    const state = originalValidator(...args);
    fs.writeFileSync(
      runtimeState,
      "import pathlib\n" +
        `pathlib.Path(${JSON.stringify(doctorSideEffect)}).write_text("executed")\n` +
        `# ${installer.PROJECT_RUNTIME_MARKER}\n`
    );
    return state;
  };
  findings = installer.doctor(source, { targets: [], rootFor: () => "", project });
  assert.ok(!fs.existsSync(doctorSideEffect));
  assert.ok(
    findings.some(
      (finding) =>
        finding.level === "fail" && /runtime changed during doctor validation/.test(finding.text)
    )
  );
  installer.hooks.validatedProjectState = originalValidator;
  fs.writeFileSync(runtimeState, originalRuntime);
  fs.writeFileSync(
    path.join(project, ".project", "STATE.md"),
    "---\npipeline: gsd-path/v2\nphase: plan\nstatus: done\n---\n"
  );
  findings = installer.doctor(source, { targets: [], rootFor: () => "", project });
  assert.ok(
    findings.some((finding) => finding.level === "fail" && /^state:/.test(finding.text))
  );
});

function git(...args) {
  const result = spawnSync("git", args, { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout;
}

test("hooks install into a core.hooksPath directory", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const project = path.join(root, "hookspath-project");
  fs.mkdirSync(project);
  git("init", "-q", project);
  git("-C", project, "config", "core.hooksPath", ".husky");
  const target = path.join(root, "claude", "skills");
  const results = await runInstall([installer.targetPlan("claude", target)], {
    project,
    hooks: true,
  });
  assert.equal(
    fs.readFileSync(path.join(project, ".husky", "pre-commit"), "utf8"),
    installer.preCommitHook("python3")
  );
  assert.equal(
    fs.readFileSync(path.join(project, ".husky", "commit-msg"), "utf8"),
    installer.commitMsgHook("python3")
  );
  assert.ok(!fs.existsSync(path.join(project, ".git", "hooks", "pre-commit")));
  const projectLine = results.find((line) => line.startsWith("project:"));
  assert.match(projectLine, /\.husky\/pre-commit/);
});

test("hooks follow a linked worktree's resolved hooks directory", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const main = path.join(root, "wt-main");
  fs.mkdirSync(main);
  git("init", "-q", main);
  git(
    "-C", main,
    "-c", "user.email=t@test", "-c", "user.name=t",
    "commit", "--allow-empty", "-m", "init", "-q"
  );
  const project = path.join(root, "wt-project");
  git("-C", main, "worktree", "add", "--detach", "-q", project);
  assert.ok(fs.statSync(path.join(project, ".git")).isFile());
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  assert.equal(
    fs.readFileSync(path.join(main, ".git", "hooks", "pre-commit"), "utf8"),
    installer.preCommitHook("python3")
  );
  assert.equal(
    fs.readFileSync(path.join(main, ".git", "hooks", "commit-msg"), "utf8"),
    installer.commitMsgHook("python3")
  );
});

test("hooks reject a .git file that cannot be resolved", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  installer.hooks.resolveGitHooksPath = () => null;
  const project = path.join(root, "gitfile-project");
  fs.mkdirSync(project);
  fs.writeFileSync(path.join(project, ".git"), "gitdir: /nonexistent\n");
  const target = path.join(root, "claude", "skills");
  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { project, hooks: true }),
    /initialized Git repository.*selected hosts: claude/
  );
  assert.ok(!fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY)));
  assert.ok(!fs.existsSync(path.join(project, ".claude", "settings.json")));
  assert.ok(!fs.existsSync(target));
});

test("hooks refresh full preserves user hook events and entries", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const settingsPath = path.join(project, ".claude", "settings.json");
  const settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  settings.hooks.PreToolUse[0].matcher = "Write";
  settings.hooks.PreToolUse[0].label = "user-scope";
  settings.hooks.PreToolUse[0].hooks.push({ type: "command", command: "echo nested" });
  settings.hooks.PreToolUse.push({
    matcher: "WebFetch",
    hooks: [{ type: "command", command: "echo user" }],
  });
  settings.hooks.Stop = [{ hooks: [{ type: "command", command: "echo done" }] }];
  fs.writeFileSync(settingsPath, JSON.stringify(settings) + "\n");
  const status = await installer.main(
    ["--hooks-refresh-full", "--project", project, "--source-root", source, "--no-color"]
  );
  assert.equal(status, 0);
  const refreshed = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  assert.deepEqual(refreshed.hooks.Stop, [
    { hooks: [{ type: "command", command: "echo done" }] },
  ]);
  assert.equal(refreshed.hooks.PreToolUse.length, 3);
  assert.equal(refreshed.hooks.PreToolUse[0].matcher, installer.CLAUDE_MATCHER);
  assert.equal(refreshed.hooks.PreToolUse[0].hooks.length, 1);
  assert.deepEqual(refreshed.hooks.PreToolUse[1], {
    matcher: "Write",
    label: "user-scope",
    hooks: [{ type: "command", command: "echo nested" }],
  });
  assert.deepEqual(refreshed.hooks.PreToolUse[2], {
    matcher: "WebFetch",
    hooks: [{ type: "command", command: "echo user" }],
  });
});

test("emitted hooks use the probed interpreter token", async () => {
  installer.hooks.detectPythonInterpreter = () => "pythonX";
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const preCommit = fs.readFileSync(
    path.join(project, ".git", "hooks", "pre-commit"),
    "utf8"
  );
  assert.match(preCommit, /exec pythonX "/);
  const settings = JSON.parse(
    fs.readFileSync(path.join(project, ".claude", "settings.json"), "utf8")
  );
  assert.ok(
    settings.hooks.PreToolUse[0].hooks[0].command.startsWith('pythonX "')
  );
});

test("native hook install requires an interpreter", async () => {
  installer.hooks.detectPythonInterpreter = () => null;
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { project, hooks: true }),
    /working Python interpreter.*selected hosts: claude/
  );
  assert.ok(!fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY)));
  assert.ok(!fs.existsSync(path.join(project, ".claude", "settings.json")));
  assert.ok(!fs.existsSync(path.join(project, ".git", "hooks", "pre-commit")));
  assert.ok(!fs.existsSync(path.join(project, "AGENTS.md")));
});

test("hookless project install requires an interpreter", async () => {
  installer.hooks.detectPythonInterpreter = () => null;
  const project = path.join(root, "project");
  const target = path.join(root, "claude", "skills");

  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { project }),
    /--project requires a working Python interpreter.*selected hosts: claude/
  );

  assert.ok(!fs.existsSync(target));
  assert.ok(!fs.existsSync(path.join(project, "AGENTS.md")));
  assert.ok(!fs.existsSync(path.join(project, installer.HOOKS_DIRECTORY)));
});

test("hooks refresh full rejects before writes without an interpreter", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  const settingsPath = path.join(project, ".claude", "settings.json");
  const settingsBefore = fs.readFileSync(settingsPath, "utf8");
  const preCommit = path.join(project, ".git", "hooks", "pre-commit");
  const hookBefore = fs.readFileSync(preCommit, "utf8");
  fs.writeFileSync(
    path.join(source, "scripts", "guard_hook.py"),
    "# guard v2\n" + installer.GUARD_MARKER + "\n"
  );
  installer.hooks.detectPythonInterpreter = () => null;
  const status = await installer.main(
    ["--hooks-refresh-full", "--project", project, "--source-root", source, "--no-color"]
  );
  assert.equal(status, 1);
  assert.doesNotMatch(
    fs.readFileSync(path.join(project, installer.HOOKS_DIRECTORY, "guard_hook.py"), "utf8"),
    /guard v2/
  );
  assert.equal(fs.readFileSync(settingsPath, "utf8"), settingsBefore);
  assert.equal(fs.readFileSync(preCommit, "utf8"), hookBefore);
});

test("selected full refresh requires an initialized repository before writes", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const project = path.join(root, "plain-refresh-project");
  const managed = path.join(project, installer.HOOKS_DIRECTORY);
  fs.mkdirSync(managed, { recursive: true });
  for (const name of installer.GUARD_SCRIPTS) {
    fs.writeFileSync(path.join(managed, name), `old\n${installer.GUARD_MARKER}\n`);
  }
  const before = fs.readFileSync(path.join(managed, "guard_hook.py"), "utf8");

  const status = await installer.main([
    "--hooks-refresh-full",
    "--grok",
    "--project",
    project,
    "--source-root",
    source,
    "--no-color",
  ]);

  assert.equal(status, 1);
  assert.equal(fs.readFileSync(path.join(managed, "guard_hook.py"), "utf8"), before);
});

test("hooks refresh dry run never probes the interpreter", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  installer.hooks.detectPythonInterpreter = () => {
    throw new Error("dry-run refresh must not probe the interpreter");
  };
  const status = await installer.main(
    ["--hooks-refresh-full", "--dry-run", "--project", project, "--source-root", source, "--no-color"]
  );
  assert.equal(status, 0);
});

test("doctor fails when expected git hooks are missing from the effective dir", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".git"), { recursive: true });
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  fs.rmSync(path.join(project, ".git", "hooks", "pre-commit"));
  const findings = installer.doctor(source, {
    targets: ["claude"],
    rootFor: () => target,
    project,
  });
  assert.ok(
    findings.some(
      (finding) =>
        finding.level === "fail" &&
        /pre-commit is missing from the effective git hooks directory/.test(finding.text)
    )
  );
});

test("doctor checks hooks at the core.hooksPath directory", async () => {
  installer.hooks.detectPythonInterpreter = () => "python3";
  const project = path.join(root, "hookspath-doctor");
  fs.mkdirSync(project);
  git("init", "-q", project);
  git("-C", project, "config", "core.hooksPath", ".husky");
  const target = path.join(root, "claude", "skills");
  await runInstall([installer.targetPlan("claude", target)], { project, hooks: true });
  let findings = installer.doctor(source, {
    targets: ["claude"],
    rootFor: () => target,
    project,
  });
  assert.ok(!findings.some((finding) => finding.level === "fail"));
  assert.ok(findings.some((finding) => /\.husky\/pre-commit wired/.test(finding.text)));

  fs.rmSync(path.join(project, ".husky", "pre-commit"));
  findings = installer.doctor(source, {
    targets: ["claude"],
    rootFor: () => target,
    project,
  });
  assert.ok(
    findings.some(
      (finding) => finding.level === "fail" && /pre-commit is missing/.test(finding.text)
    )
  );
  assert.ok(
    findings.some(
      (finding) => finding.level === "warn" && /core\.hooksPath/.test(finding.text)
    )
  );
});

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
