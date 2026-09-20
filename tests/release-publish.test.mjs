import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { parse } from 'yaml';

const release = parse(fs.readFileSync(new URL('../.github/workflows/release.yml', import.meta.url), 'utf8'));
const job = release.jobs.publish;

function resolveVersion(event, requested, ref = 'v1.0.1', name = '@opengsd/gsd-path') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'release-version-'));
  try {
    const pkg = JSON.stringify({ name, version: '1.0.1' });
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
  const publish = job.steps.findIndex(step => step.run === 'npm publish --access public --provenance');
  assert.ok(gate >= 0 && tag > gate && publish > tag);
  assert.equal(job.steps[tag].if, "github.event_name == 'workflow_dispatch'");
  assert.equal(job.steps[publish].if, undefined);
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

test('release rejects an unscoped or wrong-owner package before publication', () => {
  for (const name of ['gsd-path', '@other/gsd-path']) {
    for (const event of ['push', 'workflow_dispatch']) {
      const result = resolveVersion(event, '1.0.1', 'v1.0.1', name);
      assert.notEqual(result.status, 0);
      assert.equal(result.output, '');
    }
  }
});

test('npm packs the organization-scoped package', () => {
  const result = spawnSync('npm', ['pack', '--dry-run', '--json'], {
    cwd: new URL('../', import.meta.url), encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout)[0].name, '@opengsd/gsd-path');
});

function assertFrozenPackage(steps, event) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'release-frozen-'));
  try {
    const frozen = new Map(['package.json', 'package-lock.json'].map(file => {
      const bytes = JSON.stringify(JSON.parse(fs.readFileSync(new URL(`../${file}`, import.meta.url))));
      fs.writeFileSync(path.join(dir, file), bytes);
      fs.utimesSync(path.join(dir, file), 0, 0);
      return [file, bytes];
    }));
    fs.mkdirSync(path.join(dir, 'scripts'), { recursive: true });
    fs.copyFileSync(
      new URL('../scripts/update_release_docs.mjs', import.meta.url),
      path.join(dir, 'scripts/update_release_docs.mjs')
    );
    fs.writeFileSync(
      path.join(dir, 'README.md'),
      '# Fixture\n\n<!-- release-docs -->\nold\n<!-- /release-docs -->\n'
    );
    fs.writeFileSync(path.join(dir, 'CHANGELOG.md'), '# Changelog\n\n');
    const version = JSON.parse(frozen.get('package.json')).version;
    const run = command => {
      const result = spawnSync('bash', ['--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', command], {
        cwd: dir, encoding: 'utf8',
        env: { ...process.env, TAG: `v${version}`, GIT_CONFIG_NOSYSTEM: '1',
          GIT_CONFIG_GLOBAL: '/dev/null', GIT_AUTHOR_NAME: 'Release test',
          GIT_AUTHOR_EMAIL: 'release@example.invalid', GIT_COMMITTER_NAME: 'Release test',
          GIT_COMMITTER_EMAIL: 'release@example.invalid' },
      });
      assert.ifError(result.error);
      assert.equal(result.status, 0, result.stderr);
    };
    run('git init -q && git add package.json package-lock.json && git commit -qm fixture');
    for (const step of steps) {
      if (step.if) {
        assert.equal(step.if, "github.event_name == 'workflow_dispatch'");
        if (event !== 'workflow_dispatch') continue;
      }
      assert.equal(typeof step.run, 'string');
      run(`git() { if [[ "$1" == push ]]; then return 0; else command git "$@"; fi; }\n` +
        step.run.replaceAll('${{ steps.version.outputs.version }}', version));
      for (const [file, bytes] of frozen) {
        assert.equal(fs.readFileSync(path.join(dir, file), 'utf8'), bytes, `${file} changed after release verification`);
        assert.equal(fs.statSync(path.join(dir, file)).mtimeMs, 0, `${file} changed after release verification`);
      }
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

const gateIndex = job.steps.findIndex(step => step.run === 'npm run verify:release');
const publishIndex = job.steps.findIndex(step => step.run === 'npm publish --access public --provenance');
const prepublication = job.steps.slice(gateIndex + 1, publishIndex);

for (const event of ['push', 'workflow_dispatch']) {
  test(`${event} preserves frozen package files between verification and publication`, () => {
    assert.ok(gateIndex >= 0 && publishIndex > gateIndex);
    assertFrozenPackage(prepublication, event);
  });

  test(`${event} detects version rewriting regardless of the step label`, () => {
    const mutated = [...prepublication, {
      name: 'Prepare publication',
      run: 'npm version "${{ steps.version.outputs.version }}" --no-git-tag-version --allow-same-version',
    }];
    assert.throws(() => assertFrozenPackage(mutated, event), /package.json changed after release verification/);
  });
}
