import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, test } from "node:test";

import * as installer from "../scripts/install.mjs";

let root;
let source;
let env;
const originalHooks = { ...installer.hooks };

function makeSource(base) {
  const src = path.join(base, "source");
  fs.mkdirSync(path.join(src, "skills"), { recursive: true });
  fs.writeFileSync(path.join(src, "AGENTS.md"), "agents\n");
  fs.writeFileSync(path.join(src, "WORKFLOW.md"), "workflow\n");
  for (const name of installer.SKILL_NAMES) {
    const skill = path.join(src, "skills", name);
    fs.mkdirSync(path.join(skill, "references"), { recursive: true });
    fs.mkdirSync(path.join(skill, "agents"));
    fs.writeFileSync(
      path.join(skill, "SKILL.md"),
      `---\nname: ${name}\ndescription: test\n---\nRun $gsd-path and $gsd-path-build.\n`
    );
    fs.writeFileSync(path.join(skill, "guide.md"), "Use $gsd-path.\n");
    fs.writeFileSync(path.join(skill, "agents", "openai.yaml"), 'default_prompt: "Use $gsd-path."\n');
    fs.writeFileSync(path.join(skill, "references", "dispatch.md"), "old dispatch\n");
  }
  for (const target of installer.TARGETS) {
    const adapter = path.join(src, "platforms", target, "dispatch.md");
    fs.mkdirSync(path.dirname(adapter), { recursive: true });
    fs.writeFileSync(adapter, `${target} dispatch for $gsd-path\n`);
  }
  const shared = path.join(src, "platforms", installer.SHARED_AGENT_PROFILE, "dispatch.md");
  fs.mkdirSync(path.dirname(shared), { recursive: true });
  fs.writeFileSync(shared, "shared dispatch for $gsd-path\n");
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
  return src;
}

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "gsd-path-test-"));
  source = makeSource(root);
  env = { CODEX_HOME: path.join(root, "legacy") };
  installer.hooks.mismatches = () => [];
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

test("all platform transforms", () => {
  for (const target of [...installer.TARGETS, installer.SHARED_AGENT_PROFILE]) {
    const staged = path.join(root, `staged-${target}`);
    fs.mkdirSync(staged);
    installer.stageTarget(source, target, staged);
    const content = fs.readFileSync(path.join(staged, "gsd-path", "SKILL.md"), "utf8");
    const dispatch = fs.readFileSync(path.join(staged, "gsd-path", "references", "dispatch.md"), "utf8");
    const agentsKept = fs.existsSync(path.join(staged, "gsd-path", "agents", "openai.yaml"));
    if (target === "codex") {
      assert.match(content, /\$gsd-path/);
      assert.doesNotMatch(content, /disable-model-invocation/);
      assert.match(dispatch, /codex dispatch for \$gsd-path/);
      assert.ok(agentsKept);
    } else if (target === "opencode") {
      assert.match(content, /Run gsd-path and gsd-path-build/);
      assert.doesNotMatch(content, /[$/]gsd-path/);
      assert.match(dispatch, /opencode dispatch for gsd-path/);
      assert.ok(!agentsKept);
    } else if (target === installer.SHARED_AGENT_PROFILE) {
      assert.match(content, /Run gsd-path and gsd-path-build/);
      assert.doesNotMatch(content, /[$/]gsd-path/);
      assert.match(dispatch, /shared dispatch for gsd-path/);
      assert.ok(agentsKept);
    } else {
      assert.match(content, /\/gsd-path/);
      assert.doesNotMatch(content, /\$gsd-path/);
      assert.match(dispatch, new RegExp(`${target} dispatch for /gsd-path`));
      assert.ok(!agentsKept);
    }
    if (installer.EXPLICIT_ONLY_TARGETS.has(target)) {
      assert.match(content, /disable-model-invocation: true/);
    }
    if (target === "opencode" || target === installer.SHARED_AGENT_PROFILE) {
      assert.match(content, /opencode\/autoinvoke: "false"/);
      assert.match(content, /opencode\/slash: "true"/);
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
  assert.match(joined, /codex\+zed: installed 9 shared skills/);
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
  assert.match(sharedSkill, /Run gsd-path and gsd-path-build/);
  assert.ok(fs.existsSync(path.join(project, ".cursor", "agents", installer.CURSOR_AGENT_FILENAME)));
  assert.ok(fs.existsSync(legacy), "legacy migration must not run for --local");
  assert.ok(!fs.existsSync(path.join(root, "legacy", "disabled-gsd-skills")));
});

test("codex and zed share one deployment and back up existing entries", async () => {
  const shared = path.join(root, "shared", "skills");
  const deployments = installer.deploymentPlans([
    installer.targetPlan("codex", shared),
    installer.targetPlan("zed", shared),
  ]);
  assert.deepEqual(deployments, [
    { profile: installer.SHARED_AGENT_PROFILE, root: shared, targets: ["codex", "zed"] },
  ]);
  fs.mkdirSync(path.join(shared, "gsd-path-old"), { recursive: true });

  const results = await runInstall([
    installer.targetPlan("codex", shared),
    installer.targetPlan("zed", shared),
  ]);
  const joined = results.join("\n");
  assert.equal((joined.match(/installed 9 shared skills/g) || []).length, 1);
  assert.equal((joined.match(/backed up 1 entries/g) || []).length, 1);
  assert.ok(fs.statSync(path.join(path.dirname(shared), "disabled-gsd-skills", "gsd-path-old")).isDirectory());
  const content = fs.readFileSync(path.join(shared, "gsd-path", "SKILL.md"), "utf8");
  assert.match(content, /disable-model-invocation: true/);
  assert.match(content, /Run gsd-path and gsd-path-build/);
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
  assert.match(joined, /would install 9 skills/);
  assert.match(joined, /\.claude\/CLAUDE\.md/);
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

  fs.rmSync(path.join(source, "package.json"));
  const unstamped = path.join(root, "staged-unstamped");
  fs.mkdirSync(unstamped);
  installer.stageTarget(source, "claude", unstamped);
  assert.ok(!fs.existsSync(path.join(unstamped, "gsd-path", "VERSION")));
});

test("detectInstalls finds only roots with managed entries", () => {
  const claudeRoot = path.join(root, "detect", "claude");
  const grokRoot = path.join(root, "detect", "grok");
  const kiroRoot = path.join(root, "detect", "kiro");
  fs.mkdirSync(path.join(claudeRoot, "gsd-path"), { recursive: true });
  fs.mkdirSync(grokRoot, { recursive: true });
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
    assert.match(fs.readFileSync(skillFile, "utf8"), /Run \/gsd-path and \/gsd-path-build/);
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
  const preCommit = path.join(project, ".git", "hooks", "pre-commit");
  const commitMsg = path.join(project, ".git", "hooks", "commit-msg");
  assert.equal(fs.readFileSync(preCommit, "utf8"), installer.PRE_COMMIT_HOOK);
  assert.equal(fs.readFileSync(commitMsg, "utf8"), installer.COMMIT_MSG_HOOK);
  if (process.platform !== "win32") {
    assert.ok(fs.statSync(commitMsg).mode & 0o100);
  }
  const projectLine = results.find((line) => line.startsWith("project:"));
  assert.match(projectLine, /\.gsd-path\/guard_hook\.py/);
  assert.match(projectLine, /\.git\/hooks\/pre-commit/);
  assert.match(projectLine, /\.git\/hooks\/commit-msg/);
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
  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );
  assert.equal(status, 0);
  assert.match(
    fs.readFileSync(path.join(project, installer.HOOKS_DIRECTORY, "guard_hook.py"), "utf8"),
    /guard v2/
  );
  assert.ok(fs.existsSync(target));
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

test("hooks refresh rejects unmanaged guard scripts", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, installer.HOOKS_DIRECTORY), { recursive: true });
  fs.writeFileSync(path.join(project, installer.HOOKS_DIRECTORY, "guard_hook.py"), "custom\n");
  const status = await installer.main(
    ["--hooks-refresh", "--project", project, "--source-root", source, "--no-color"]
  );
  assert.equal(status, 1);
});

test("hooks skip the git hook without a repository", async () => {
  const project = path.join(root, "project");
  const target = path.join(root, "claude", "skills");
  const results = await runInstall([installer.targetPlan("claude", target)], {
    project,
    hooks: true,
  });
  assert.ok(!fs.existsSync(path.join(project, ".git")));
  assert.ok(fs.existsSync(path.join(project, ".claude", "settings.json")));
  const projectLine = results.find((line) => line.startsWith("project:"));
  assert.ok(!/commit-msg/.test(projectLine));
});

test("hooks collision rolls back cleanly", async () => {
  const project = path.join(root, "project");
  fs.mkdirSync(path.join(project, ".claude"), { recursive: true });
  fs.writeFileSync(path.join(project, ".claude", "settings.json"), "{}");
  const target = path.join(root, "claude", "skills");
  await assert.rejects(
    runInstall([installer.targetPlan("claude", target)], { project, hooks: true }),
    /already exists/
  );
  assert.ok(!fs.existsSync(target));
  assert.ok(!fs.existsSync(path.join(project, "AGENTS.md")));
  assert.equal(fs.readFileSync(path.join(project, ".claude", "settings.json"), "utf8"), "{}");
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
