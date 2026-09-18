import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { parse } from 'yaml';

const root = new URL('../', import.meta.url);
const workflow = name => parse(fs.readFileSync(new URL(`.github/workflows/${name}.yml`, root), 'utf8'));
const scripts = JSON.parse(fs.readFileSync(new URL('package.json', root))).scripts;

// Execute workflow shell at the external command boundary. A stale receipt
// rejects verify:release; offline tests succeed. No publication is performed.
function execute(command, event) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'release-gates-'));
  try {
    const log = path.join(dir, 'calls.jsonl');
    for (const tool of ['npm', 'python3']) {
      fs.writeFileSync(path.join(dir, tool), `#!${process.execPath}\n` +
        `const fs = require('node:fs');\n` +
        `const args = process.argv.slice(2);\n` +
        `fs.appendFileSync(process.env.CALL_LOG, JSON.stringify(['${tool}', ...args]) + '\\n');\n` +
        `process.exit(args.includes('verify:release') ? 23 : 0);\n`, { mode: 0o755 });
    }
    const result = spawnSync('bash', ['--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', command], {
      encoding: 'utf8',
      env: { ...process.env, PATH: `${dir}${path.delimiter}${process.env.PATH}`,
        CALL_LOG: log, GITHUB_EVENT_NAME: event },
    });
    assert.ifError(result.error);
    return { status: result.status, calls: fs.existsSync(log)
      ? fs.readFileSync(log, 'utf8').trim().split('\n').map(JSON.parse) : [] };
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

function trustCommand() {
  const job = workflow('release-trust').jobs['verify-release-evidence'];
  assert.ok(job, 'keep the required PR check name');
  assert.equal(job.if, undefined);
  assert.equal(job['continue-on-error'], undefined);
  const step = job.steps.at(-1);
  assert.equal(step.if, undefined);
  assert.equal(step['continue-on-error'], undefined);
  return step.run;
}

for (const event of ['pull_request', 'push']) {
  test(`${event} runs trust validator tests without requiring release receipts`, () => {
    const result = execute(trustCommand(), event);
    assert.equal(result.status, 0);
    assert.deepEqual(result.calls, [['python3', '-m', 'unittest', 'tests.test_trust_evidence']]);
    const triggers = workflow('release-trust').on;
    assert.ok(Object.hasOwn(triggers, event));
    assert.equal(triggers[event]?.paths, undefined, 'required check must run for every change');
    assert.equal(triggers[event]?.['paths-ignore'], undefined);
    if (event === 'push') assert.deepEqual(triggers.push.branches, ['main']);
    const ci = workflow('ci');
    assert.ok(Object.hasOwn(ci.on, event));
    assert.ok(ci.jobs.verify.steps.some(step => step.run === 'npm run verify' && !step.if));
  });
}

test('manual frozen-candidate validation rejects stale receipts', () => {
  assert.ok(Object.hasOwn(workflow('release-trust').on, 'workflow_dispatch'));
  const result = execute(trustCommand(), 'workflow_dispatch');
  assert.equal(result.status, 23);
  assert.deepEqual(result.calls, [['npm', 'run', 'verify:release']]);
});

test('npm publication and release workflow retain the strict blocking gate', () => {
  assert.deepEqual(scripts['verify:release'].split('&&').map(command => command.trim()),
    ['npm run verify', 'python3 scripts/check_trust_evidence.py --repo .']);
  const local = execute(scripts.prepublishOnly, 'local');
  assert.equal(local.status, 23);
  assert.deepEqual(local.calls, [['npm', 'run', 'verify:release']]);

  const job = workflow('release').jobs.publish;
  assert.equal(job['continue-on-error'], undefined);
  const publishIndex = job.steps.findIndex(step => step.run === 'npm publish --access public');
  assert.ok(publishIndex >= 0);
  const gate = job.steps.slice(0, publishIndex).find(step => step.run === 'npm run verify:release');
  assert.ok(gate, 'release must verify before publishing');
  assert.equal(gate.if, undefined);
  assert.equal(gate['continue-on-error'], undefined);
  const release = execute(`${gate.run}\nnpm publish --access public`, 'push');
  assert.equal(release.status, 23);
  assert.deepEqual(release.calls, [['npm', 'run', 'verify:release']]);
});
