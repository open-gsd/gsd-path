# Contributing to GSD Path

Thank you for your help. This page gives the rules for issues and pull
requests in this repository.

## Report a problem

Use the **Bug report** form. A report must have:

- the GSD Path version (`npx @opengsd/gsd-path@latest --doctor` shows it);
- the coding-agent host and its version;
- the operating system;
- the command or skill you ran, what you expected, and the exact output.

Write one problem in one issue. A field report with many findings is welcome,
but each finding gets its own issue after triage.

Report a security problem privately. See [SECURITY.md](SECURITY.md).

## Propose a change

Open an issue before you write code that changes pipeline behavior. Say what
is wrong or missing, and what the smallest change is. A pull request for a
typo or a clear bug does not need an issue first.

## Set up

You need Node.js 18.17 or later, Python 3.9 or later, and Git. See
[TEST_ENVIRONMENT.md](TEST_ENVIRONMENT.md) for the details, Windows notes, and
troubleshooting.

```bash
git clone https://github.com/open-gsd/gsd-path.git
cd gsd-path
make install
make verify
```

`make verify` is the same offline gate that CI runs. It needs no API key and
no coding-agent host.

## Rules for a change

- **Edit the canonical file.** Helper scripts live in `scripts/`. Shared
  references live in `skills/gsd-path/references/`, and shared templates
  live in `skills/gsd-path/templates/`. The dispatch contract is the
  exception: it lives in `platforms/shared-agents/dispatch.md`. Each skill
  contract lives in `skills/gsd-path/SKILL.md` or
  `skills/gsd-path-<phase>/SKILL.md`. Every other copy of these files under
  `skills/` is generated, and sync overwrites it. This includes
  `skills/gsd-path/references/dispatch.md`, the phase files such as
  `skills/gsd-path/BUILD.md`, each `scripts/` directory under `skills/`,
  and all of `skills/path/`. After an edit, run
  `python3 scripts/sync_skill_resources.py`, and commit the result.
  `npm run test:sync` fails when a copy is out of date.
- **Keep the file lists equal.** The `files` list in `package.json` must
  equal `package_files` in `scripts/skill-resources.json`.
- **Prove the change.** A behavior change needs a test that fails before the
  change and passes after it. A test must run the code. A test that only
  reads source text is not accepted.
- **Keep the change small.** Change only what the issue needs. Do not
  refactor nearby code in the same pull request.
- **Update the docs** that describe the behavior you changed.
- **Do not edit release evidence** under `docs/trust-validation/evidence/`.
  Maintainers record it during a release.

## Pull requests

- Start from an up-to-date `main` on a new branch.
- Use one pull request for one issue.
- Write the commit subject as `fix: ...`, `feat: ...`, `docs: ...`,
  `test: ...`, or `chore: ...`. Explain the cause and the fix in the body.
  Name the issue with `Fixes #123` or `Refs #123`.
- Say in the pull request how you verified the change: the test command and
  its result.
- CI must be green before review.

A maintainer merges the pull request. Live host evaluations and releases are
maintainer tasks; see [RELEASE.md](RELEASE.md).

## License

Your contribution is licensed under the [MIT License](LICENSE).
