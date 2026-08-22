import assert from "node:assert/strict";
import { PassThrough } from "node:stream";
import { test } from "node:test";

import { TARGETS } from "../scripts/install.mjs";
import { banner, makeTheme, wizard } from "../scripts/wizard.mjs";

const KEYS = { down: "[B", space: " ", enter: "\r", a: "a", q: "q" };

function run(keys, options = {}) {
  const input = new PassThrough();
  const output = new PassThrough();
  let text = "";
  output.on("data", (chunk) => (text += chunk));
  const done = wizard({ input, output, colored: false, cwd: "/repo", targets: TARGETS, ...options });
  for (const key of keys) input.write(KEYS[key]);
  return done.then((argv) => ({ argv, text }));
}

test("wizard builds an --all install argv", async () => {
  // global → all hosts → write contracts → hooks yes → install
  const { argv, text } = await run(["enter", "a", "enter", "enter", "enter", "enter"]);
  assert.deepEqual(argv, ["--all", "--project", "/repo", "--hooks"]);
  assert.match(text, /Equivalent command:/);
});

test("wizard builds a per-host local dry run", async () => {
  // local → toggle claude (2nd) → no contracts → dry run
  const { argv } = await run(["down", "enter", "down", "space", "enter", "down", "enter", "down", "enter"]);
  assert.deepEqual(argv, ["--claude", "--local", "--dry-run"]);
});

test("wizard offers update when installs exist and honors quit", async () => {
  const scopes = [];
  const installed = (target, local) => (scopes.push(local), target === "codex");
  // global → keep preselected codex → update → no contracts → quit
  const { argv, text } = await run(["enter", "enter", "enter", "down", "enter", "down", "down", "enter"], { installed });
  assert.deepEqual([...new Set(scopes)], [false]);
  assert.equal(argv, null);
  assert.match(text, /installed/);
  assert.match(text, /Update in place/);
  assert.match(text, /gsd-path --codex --update/);
});

test("wizard cancels on q", async () => {
  const { argv, text } = await run(["q"]);
  assert.equal(argv, null);
  assert.match(text, /Cancelled/);
});

test("banner carries the OpenGSD wordmark", () => {
  assert.match(banner(makeTheme(false), "1.0.0"), /██/);
  assert.match(banner(makeTheme(false), "1.0.0"), /installer v1\.0\.0/);
});
