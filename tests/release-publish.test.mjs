import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { parse } from 'yaml';

const release = parse(fs.readFileSync(new URL('../.github/workflows/release.yml', import.meta.url), 'utf8'));
const job = release.jobs.publish;

function resolveVersion(event, requested, ref = 'v1.0.1') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'release-version-'));
  try {
    const pkg = JSON.stringify({ name: 'gsd-path', version: '1.0.1' });
    fs.writeFileSync(path.join(dir, 'package.json'), pkg);
    const output = path.join(dir, 'output');
    const result = spawnSync('bash', ['-e', '-o', 'pipefail', '-c', job.steps.find(step => step.id === 'version').run], {
      cwd: dir, encoding: 'utf8',
      env: { ...process.env, GITHUB_EVENT_NAME: event, RELEASE_VERSION: requested,
        GITHUB_REF_NAME: ref, GITHUB_OUTPUT: output },
    });
    assert.ifError(result.error);
    assert.equal(fs.readFileSync(path.join(dir, 'package.json'), 'utf8'), pkg);
    return { ...result, output: fs.existsSync(output) ? fs.readFileSync(output, 'utf8') : '' };
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test('release uses GitHub-hosted OIDC with a supported Node version and no npm token', () => {
  assert.equal((job.permissions ?? release.permissions)['id-token'], 'write');
  assert.equal(job['runs-on'], 'ubuntu-latest');
  const setup = job.steps.find(step => step.uses?.startsWith('actions/setup-node@'));
  assert.equal(setup.with['node-version'], '24'); // npm recommends Node 24 for OIDC.
  for (const env of [release.env, job.env, ...job.steps.map(step => step.env)]) {
    assert.equal(env?.NODE_AUTH_TOKEN, undefined);
    assert.equal(env?.NPM_TOKEN, undefined);
  }
});

test('manual dispatch publishes in the same job after the release gate', () => {
  assert.equal(job.if, undefined);
  assert.equal(release.jobs.tag, undefined);
  const gate = job.steps.findIndex(step => step.run === 'npm run verify:release');
  const tag = job.steps.findIndex(step => step.name === 'Create release tag');
  const publish = job.steps.findIndex(step => step.run === 'npm publish --access public');
  assert.ok(gate >= 0 && tag > gate && publish > tag);
  assert.equal(job.steps[tag].if, "github.event_name == 'workflow_dispatch'");
  assert.equal(job.steps[publish].if, undefined);
  assert.equal(job.steps.find(step => step.name === 'Align package version'), undefined);
});

test('tag and manual versions resolve without changing the frozen package', () => {
  for (const event of ['push', 'workflow_dispatch']) {
    const result = resolveVersion(event, '1.0.1', event === 'push' ? 'v1.0.1' : 'main');
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.output, 'version=1.0.1\ntag=v1.0.1\n');
  }
});

test('version mismatch and invalid input fail before emitting release outputs', () => {
  for (const version of ['1.0.2', 'bad', '1.0.1; echo unsafe']) {
    for (const event of ['push', 'workflow_dispatch']) {
      const result = resolveVersion(event, version, `v${version}`);
      assert.notEqual(result.status, 0);
      assert.equal(result.output, '');
    }
  }
});
