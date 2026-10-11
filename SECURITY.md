# Security policy

## Supported versions

Security fixes go into the latest release of
[`@opengsd/gsd-path`](https://www.npmjs.com/package/@opengsd/gsd-path) and the
latest desktop app release. Update before you report a problem.

## Report a vulnerability

Do not open a public issue for a security problem.

Use GitHub private vulnerability reporting: open the
[Security tab](https://github.com/open-gsd/gsd-path/security) of this
repository and select **Report a vulnerability**. Only the maintainers can
read the report.

Include:

- the GSD Path version, the coding-agent host, and the operating system;
- what an attacker can do, and what the attacker needs first;
- the steps to reproduce the problem.

## Scope

GSD Path runs on your computer with your permissions. These parts are in
scope:

- the installers (`scripts/install.mjs`, `scripts/install.py`);
- the pipeline helpers under `scripts/`;
- the guard hooks ([HOOKS.md](HOOKS.md));
- the monitor daemon and the desktop app under `daemon/`.

The behavior of a coding-agent host or of a model is out of scope. Report that
to the vendor of the host.
