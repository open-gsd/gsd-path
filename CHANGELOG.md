# Changelog

All notable changes to [@opengsd/gsd-path](https://www.npmjs.com/package/@opengsd/gsd-path)
are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This file covers the npm package: the skills, the installer, the pipeline
scripts and project runtime, the guard hooks, and their documentation. Until
1.4.0 it also lists changes to the monitor daemon and its dashboard, which are
in this repository but not in the npm package. From October 2026 the desktop
app and the daemon have their own file,
[daemon/app/CHANGELOG.md](daemon/app/CHANGELOG.md). Release bookkeeping and
test-only changes are not listed; the Git history has them.

## [1.5.0] - 2026-10-09

### Added
- **Edge and prohibition rulings at define.** Define walks each success
  criterion through a fixed list of edge cases and asks what the criterion
  must never silently become. The owner rules on each item: a success
  criterion, a `held-out` test, a `judgment`, or dismissed with a reason.
  `INTENT.md` records the rulings in `## Edge coverage` and `## Prohibitions`,
  and define is not done while a table is incomplete. Plan gives every
  `held-out` edge a row in `## Held-out checks` with its task and test file.
  Final review accepts such a criterion as `met` only when its evidence cites
  each ruling.
- **External landing.** `external-landing` is a third integration mode beside
  `direct` and `pull-request`. Ship publishes the milestone branch and stops
  at `awaiting-merge` with no GitHub API calls. After the branch is merged, on
  any forge, the resume step checks the merge commit and records it in the
  milestone tag.
- **Muse Code host.** `--muse` installs the skills to `~/.agents/skills`;
  invoke them with `/path` or `/gsd-path`. Muse Code has no live release
  evidence yet; see the host trust matrix.
- **Runtime hotfix provenance.** The Python installer
  (`python3 scripts/install.py`) accepts `--runtime-provenance-source`,
  `--runtime-provenance-patch`, and `--runtime-provenance-note` with
  `--runtime-upgrade` to record where a patched runtime came from. The
  `gsd-path` command does not accept these flags. The record does not change
  the digest or the runtime validation (#353).

### Changed
- A plan can send an intent correction back to define (#271).
- One research question can name several dimensions (#288) and can contain
  inline code (#307).
- Tasks in the same wave can change the same file when one depends on the
  other (#353).
- A wave with a blocked review holds the later waves until its repair tasks
  pass a new review (#315).
- Earlier wave review cycles are kept as history. Only the last cycle must
  agree with the current plan (#274, #278, #317).
- Docs audit queue numbers stay the same across audits (#299).
- The guard applies the build-phase rule to shell commands that write product
  files, such as redirections, `cp`, and `sed -i` (#239).
- The guard permits more read-only commands: read-only Git with a variable
  inside double quotes, `cd` to an assigned variable, pipes of permitted
  archive reads, here-strings, and quoted paths with spaces (#327, #353).
- A ship commit can have more Git trailers after its required lines (#198).

### Fixed
- The installer no longer fails on Node 26 when a skill directory exists
  (#249), and it updates an install that has a prerelease or build version
  (#286).
- The npm package has no Python bytecode (#287). A `__pycache__` directory in
  a pinned runtime no longer blocks every guarded tool call (#323).
- The package copy of `dispatch_driver.py` finds its role briefs and
  templates (#325), and dispatch uses the helpers of the pinned runtime
  (#209).
- Native task activations count toward the attempt limit (#179). A task is no
  longer marked orphaned before its exit receipt is read.
- A blocked serial task can be recovered, and its unused Verify worktree is
  removed (#324). `finish` creates a deleted serial Verify worktree again, and
  serial activation is refused while the parallel worktree of the task is
  live (#353).
- Dispatch brief checks accept landed tasks and tasks in progress (#318).
- Member validate and repair no longer refuse the refs that Path creates, and
  a landed member task finds its base in the coordinator or the member
  repository (#353).
- Plan approval accepts `.project/model-policy.json` and `config.json`
  (#211) and ignores file overlap between landed tasks (#231). The gate-plan
  brief check gives the same result as plan approval (#210).
- Surface names with a comma inside parentheses are not split (#293), and
  task brief checks no longer read search patterns as file paths (#281).
- Review fields that continue on the next lines are read by the final gate
  and the archive (#282).
- Final review accepts a HEAD that differs only by a runtime pin commit
  (#297).
- The archive accepts `#` in frontmatter values (#268), a missing archive of
  an earlier milestone (#269), and evidence with several code spans (#328).
- Undo accepts a prepared archive after the ship log entry (#329).
- Status and route no longer fail on an old bind-next record after a
  milestone is abandoned (#343).
- Windows: a member landing lock no longer stops at the 10-second limit, and
  the pipes of a timed-out command are closed (#248). Files with CRLF line
  ends no longer put stray characters into briefs (#202).
- WSL: state commits work on drvfs mounts (#207).
- Linux: `.project` listings are current on btrfs (#245).
- Git versions without `worktree list -z` are supported (#212).

### Security
- The guard refuses `git -c` and `git config` keys whose value Git runs as a
  program, such as `core.fsmonitor`, `core.hooksPath`, editors, pagers,
  `core.sshCommand`, and credential helpers. It also applies these checks to
  the command that a command runner runs: `nice`, `nohup`, `timeout`, `sudo`,
  `watch`, `time`, `env`, `stdbuf`, and `setsid`.
- Windows: project detection reads evidence through pinned handles, so a
  replaced parent junction cannot redirect it (#203).

## [1.4.0] - 2026-09-30

### Added
- **Multi-repo milestones.** One coordinator project can plan, build, review,
  and ship tasks in other repositories (members). A task names its repository
  with `repo:`. Each member gets a marker, guard hooks
  (`--member-of`), a Path-owned checkout for its tasks, and a bound branch at
  build start. Landings in two repositories are journaled so an interrupted
  one can be finished. Members integrate by direct merge or pull request, and
  a member landing can be undone. A member accepts a push only with an
  authorization for that ref, and refuses symlinked lock, marker, and task
  copy paths.
- **Native Windows support.** The installer, hooks, state locking, dispatch,
  Verify commands, and the project runtime run on Windows with Git for
  Windows (Git Bash). A Windows job in CI now blocks a merge.
- **Managed `AGENTS.md` block.** The installer adds a marked Path block to an
  existing `AGENTS.md` and keeps the owner's text, on update and on uninstall.
  The block is smaller; phase rules moved into the skills.
- **Pre-approved gates.** `--pre-approve intent,plan` grants the intent and
  plan approvals for one milestone, for unattended quick-lane runs (#150).
  Ship approval stays manual.
- **Native retry.** A failed task that was dispatched natively can be retried
  and finished, also for a member task.

### Changed
- The verify ledger records the repository of each row, and a build stops when
  a member repository changed outside Path.
- The monitor daemon refuses POST requests from other websites and requests
  that are not JSON.
- The dashboard and the tray show the project folder beside the worktree and
  wrap long paths.

### Fixed
- An ignored `.DS_Store` inside `.project` no longer blocks setup, landings, or
  the ship check (#149).
- A landing is refused when ignore rules hide `.project` state (#145).
- `finish` lands parallel tasks that were dispatched natively (#142).
- `retire` recovers a task worktree that was only half retired (#143).
- Empty host `.claude` folders are removed before `.project` gates (#144).
- The docs audit keeps `Repo root` on the primary repository (#148).
- A build checkpoint commits a verify ledger that old ignore rules hid (#158).
- The decide phase can run the research handoff check.
- The installer names a working path when `--project` finds an existing
  contract.
- The update notice says that local edits to skills are not carried forward
  (#151).

### Security
- Guard bypasses through Git Bash paths and directory junctions on Windows are
  closed.

## [1.3.1] - 2026-09-22

### Changed
- Clearer guidance for the legacy runtime migration and its backup.

### Fixed
- The legacy runtime migration keeps older runtime folders that Git does not
  track, and the installer help describes this case.

## [1.3.0] - 2026-09-21

### Added
- An upgrade moves a legacy in-repository runtime out of the project and
  leaves a backup to review (`--runtime-migrate`).

### Changed
- On Cursor and Copilot, only the reviewer corrects a review, and only while
  its review cycle is open. A closed review cycle is not rewritten.

## [1.2.0] - 2026-09-20

### Added
- **Path settings.** Set the shipping mode, the review panel, and the model and
  effort per role, for the user or for one project, in the dashboard or with
  `path_config.py`.
- **Project history in the dashboard.** Browse project files and archived
  milestones, read a file at any Git commit, and load the full recorded
  evidence.
- **Optional Jev evidence screening.** Reviewers can ask for an advisory check
  of chosen criteria and evidence. It is off by default and never replaces a
  recorded review or Verify.
- **External worktrees and pinned runtimes.** Task, verification, and
  integration worktrees live outside the project checkout. A project pins its
  runtime version by content digest, with upgrade and restore commands.
- **One model policy.** User, project, host, and task choices for sub-agent
  models go through one resolver. A recorded assignment stays pinned.

### Changed
- npm releases are automated: release notes, package verification, and
  provenance.
- The release gate validates only the hosts a change affects and reuses
  unchanged host receipts.

### Fixed
- The dashboard shows project runtime updates and their results.
- After verified integration, ordinary branches can take product work again
  while archived milestones stay protected.

## [1.1.0] - 2026-09-18

### Added
- Scoped npm package `@opengsd/gsd-path` with trusted publishing.
- Release trust evidence validation and the host matrix.

### Changed
- Release workflow and maintainer documentation for npm publication.

## [1.0.0] - 2026-09-15

### Added
- First public release of the disk-backed GSD Path pipeline.
- Multi-host installer, skills package, and project contracts.
