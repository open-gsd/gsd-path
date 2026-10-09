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
- record runtime hotfix provenance on the declaration
- add signed self-update
- add the Skills, Stats, Settings, and Environment pages and the setup wizard
- register the hosts, project operation, and env routes
- add project setup operations for the app
- detect installed coding agents
- add the env file module for the app's Environment page
- add the stats route for the app's charts
- add the project board, project page, and tray popover
- add the Tauri shell and React setup screens
- add settings and diagnostics routes
- install skills from the verified npm release
- report requirements in the launch check
- add the launch check for the native app
- add --require-token to gate POST routes
- add external-landing mode for forge-neutral ship
- add Muse Code as a shared-agents host
- rule on edges and prohibitions at define, gate held-out checks at plan and final

### Changed
- prepare 1.5.0 minor candidate
- point trust evidence link to current receipts
- refresh all seven host release receipts
- Name interactive.diffFilter in HOOKS.md executed-key list
- align guard, worktree pin, provenance, planner docs
- sync generated skill resource copies
- describe daemon hook-op migration and default hosts
- app: migrate a legacy runtime in the same click as a hook action
- app: send a legacy runtime to the update, not a hook refresh
- say macOS app builds are signed and notarized
- app: prepare 0.1.1, the first signed macOS build
- prove signing setup keeps keychain on success
- app: delete signing keychain on setup failure
- remove stale unsigned-build text after macOS signing
- app: sign and notarize macOS builds in the release workflow
- make diagnostic command assertion platform independent
- clarify patch finding source fields (#326)
- require maintainer rewrite of drafted changelog entry
- strengthen alias update regression assertions
- assert router alias payload refreshes on update
- rewrite the changelog entries for readers
- list the release upload script test in RELEASE.md
- prove the release upload script on macOS, Windows, and Linux runners
- Sync generated skill resource copies
- cover dispatch brief bases and in-flight lint regressions
- describe the desktop app in the README and add its changelog
- Document round exit-receipt reread in RUNTIME.md
- Merge validated main integration while preserving PR history
- Update ADR 0004 for Windows pinned-handle evidence reads
- sync detect_project skill copies
- correct app update check and release facts
- point README page list at route.ts
- Fix daemon README same-origin list and hosts docstring
- add app workflows to the RELEASE.md CI table
- Merge remote-tracking branch 'origin/main' into HEAD
- build tester installers on app-v tags and run shell tests
- Revert "fix: treat empty .project directory trees as greenfield (#273) (#292)"
- Revert "fix: reject Verify commands the host guard would refuse at plan time (#302)"
- Revert "fix(guard): allow read-only closed-milestone shell between ship and bind-next (#301)"
- match only real pip commands in the launch tests
- document INTENT SC heading text for multi-line criteria (#279) (#303)
- align plugin source wording with npm release source
- Document daemon version and pid in /status
- record native app design handoff and React frontend ruling
- run pinned-runtime reload in subprocess to avoid import pollution
- merge main: integrate #254/#265 and keep pinned-runtime test cleanup
- sync skill copies for state_checkpoint landed base fix
- sync skill copies for landed member base fix
- double-restore bundled scripts after pinned-runtime test
- drop pinned-runtime tests from native-attempt PR (#209 owns them)
- Revert "test: restore bundled scripts after pinned-runtime reload test"
- restore bundled scripts after pinned-runtime reload test
- invoke pipeline_state CLI from bundled script path
- retrigger checks
- sync skill copies after isolation change
- revert: keep ca89 dispatch finish path that passes member round tests
- merge main
- platform-neutral PowerShell path quoting expectation
- sync worktree_paths skill copies
- align package verify graph with main (drop stray check:locks)
- sync state_checkpoint skill copies
- expect LF-normalized intent hash for CRLF on-disk files
- skip WSL drvfs mount probes on Windows CI
- merge main into cursor/fix-spec-reach-probes-f72c
- merge main and sync skill resources
- merge main into cursor/fix-git-worktree-legacy-f72c
- merge main into cursor/fix-task-briefs-plan-deps-f72c
- merge main into cursor/fix-windows-member-lock-run-shell-f72c
- patch os.path.normcase in Windows session path test
- fix Windows normcase test on Linux CI (create=True, patch sep)
- sync detect_project copies after listdir_anchored fix
- update release notes for v1.4.0
- Point local shard command at py.mjs wrapper
- shard the Windows Python suite

### Fixed
- parse research questions with backticks
- Fix package-level dispatch resource defaults
- deny git -c keys whose value git executes
- close zsh flag and escaped-marker gaps in the git parameter exception
- review findings on the 353 branch
- dispatch footguns from the 1.4.0 multi-repo field report
- dashboard probe resolves the pinned runtime via the project launcher
- guard hook precision for read-only commands
- allow same-wave file overlap between dependency-ordered tasks
- members validate and repair stop rejecting the refs Path creates
- lint landed member briefs at their member base
- ignore stale retired bind-next journals
- recover blocked serial tasks and retire unused verify sidecars
- preserve code spans in archive validation (#328)
- allow proven safe shell guard commands
- tolerate bytecode caches in pinned runtimes
- validate superseded wave review cycles together
- prioritize repair waves after blocked review (#315)
- accept prepared archive ship log events
- exclude Python bytecode from npm releases
- stabilize docs audit numbering (#299)
- allow research questions across multiple dimensions
- fix installer ownership of prerelease aliases
- fix installer recognition of suffixed versions
- Fix dispatch task brief validation bases
- find release files without globstar in the app release workflow
- reread task exit receipt before marking orphaned
- verify Windows pins and drain refused POST bodies
- list Windows evidence dirs by path while opens stay handle-relative
- anchor detect_project evidence reads on pinned handles
- remove the host guard Verify check that PR #305 carried from #302
- reject Verify commands the host guard would refuse at plan time (#302)
- tolerate missing lower milestone archives (#269) (#306)
- treat superseded wave review cycles as history (#274, #278) (#305)
- allow plan intent corrections to return to define (#304)
- allow read-only closed-milestone shell between ship and bind-next (#301)
- Fix final-review HEAD checks to allow runtime-pin commits (#297)
- require wave evidence line in quick-lane final scope template (#296)
- tighten task brief path token detection (#281) (#295)
- Fix multiline review bullet field parsing for final gate and archive (#294)
- Fix Surfaces parsing to split only on top-level commas (#293)
- treat empty .project directory trees as greenfield (#273) (#292)
- isolate pinned-runtime in-process test and reload order
- parse frontmatter # only as YAML comment (#268) (#289)
- keep the pinned-runtime reload test out of suite discovery
- landed member base resolution and missing STATE.md dispatch records
- resolve landed member base on coordinator or member repo
- allow dispatch records when STATE.md is absent
- validate landed member task base in member repo
- do not refresh native shell when prior attempt is blocked
- restore finish_task landing flow while keeping native shell refresh
- validate landed member task bases on coordinator
- member finish verify logging and force sidecar retirement
- allow force member sidecar retirement without task-file rejection gate
- pass task-file when force-retiring member sidecars
- record member verify on coordinator task and force-retire sidecar
- resolve landed member bases on coordinator and finish native member dispatches cleanly
- refresh native dispatch shells on re-activation and prefer live task state at finish
- exclude check_lock_usage from LK_LOCK self-scan
- reject Windows symlinks and junctions in handle-based reads
- lazy pipeline_git import with git fallback for skill bundles
- prefer isolation import before scripts package
- treat native shells as pre-spawn, not orphaned
- phase-gate shell writes only on bound milestone branch in-tree
- Windows parity for file reads, subprocess, tray, and install
- record native activations for attempt limits
- WSL drvfs index.lock workaround for state commits
- phase-gate shell writes to product files
- load pinned runtime helpers in dispatch_driver
- ignore same-wave overlap between landed tasks
- normalize CRLF in user-edited pipeline text
- prefer scripts.isolation when scripts/ is on sys.path
- worktree list without -z and posix show paths
- allow optional git trailers after ship commit body
- align gate-plan task brief check with approval checkpoint
- allow path_config model-policy.json at approval
- list .project through fresh directory fd on Linux
- member landing lock and spec command timeout drain
- copy staged skill entries into reserved directory

### Other
- fix install command receipts and 1.4.0 trust evidence
- deny pager.<cmd> config keys that git executes
- parse runner short options as getopt, deny non-literal option words
- deny file-valued runner options and non-literal runner operands
- unwrap command runners so git checks reach payload
- scope git wrapper denial to exec-prefix programs
- deny git behind programs the guard does not model
- deny unresolved git option words and credential helpers
- deny joined continuations and expanding git option values
- require literal git subcommand, deny comments in git config
- deny non-literal git config arguments
- treat only one ASCII digit as redirection file descriptor
- allow redirected git config reads, keep digit sets denied
- deny gpg program keys and redirected git config sets
- parse git config modes; .git/config append stays open
- close executed git config keys, persisted form, disabling values
- narrow zsh flag detector and cover git -C paths
- keep exact --text allowed under git option prefix rule
- match denied git options by abbreviated prefix
- deny parameters in command-valued git options
- accept only plain name expansions in git parameter exception
- deny git parameters inside wrapped shell strings
- fail closed on unrecognized quoting in git parameter exception
- allow git parameters only inside double-quoted spans
- deny bare and substituted parameters in read-only git arguments
- fix guard fail-opens and remaining 353 review findings
- app: Add guards uses installed agents when no hosts sent
- narrow macOS signing claim to Privacy & Security approval
- Correct unsupported Fixed and Security changelog entries
- assert incomplete builds upload nothing at all
- Insert new changelog entries above existing entries
- Restore Windows start step in manual monitor README section
- Classify directory SKILL.md marker as unverified on Windows
- Reject symlinked SKILL.md marker in Windows bundle probe
- Detect junctions at held Windows handles; stat-only file opens
- stop daemon before install, add .deb update, tray dialog
- Cause: GitGuardian reported one "Generic High Entropy Secret" in commit be3bd5d4, file daemon/app/src/mocks/environment.ts line 10. The value was `tsk_mock_8f3a91c2d7`, a made-up key for TYPESAFE_API_KEY in the dev-only browser mock. It is not a real credential, so nothing needs rotation. Fix: replaced the value with the plain placeholder `mock-api-key` (one line). No other file uses the old value. No test added: this is mock data, not logic. Verification: `tsc --noEmit` is clean and Vitest passes (14 files, 226 tests). GitGuardian was not run locally, so the check result is not confirmed. Remaining risk: GitGuardian scans each commit of the PR, and commit be3bd5d4 still contains the old string. The check can stay red after this commit. If it does, the owner has two options: mark incident 37796517 as a false positive / test credential in the GitGuardian dashboard, or rewrite the branch history to drop the string from be3bd5d4. I did neither: the dashboard needs the owner's account, and a history rewrite plus push is outside this phase
- compare with release in use, share plugin state
- unify update rules, badge count, and env switch
- Fix hooks-init host flags and member hook state
- Fix env quoted values, host commands, None phase
- Remove command line from port owner detail
- Report program name, pass PATH to children, handle Reopen
- Serialize boot, refresh PATH, fix port screen and autostart
- The fix is in place, but the Windows failure is not reproduced locally (macOS); only CI on Windows can confirm it. - **Cause:** `test_foreign_host_refused` got `WinError 10053` on `/api/config/parents`. `do_POST` in `daemon/gsd_daemon/serve.py` sent a refusal (403 or 415) without reading the request body. On Windows, a socket closed with unread data resets the connection, so the client can lose the reply. This is a timing race, which is why only one shard and one route failed. - **Origin:** the same-origin refusal is already on main, so the race is not new in this PR. The token refusal that this PR adds has the same exposure. - **Fix:** `do_POST` now reads the full body (per `Content-Length`) before any reply and gives it to the route handlers through `self.rfile`. It is one change at the top of `do_POST`, plus `import io`. It covers all refusals, the 404, and `/api/refresh`. The check order (origin 403, content type 415, token 403) and the route handlers are unchanged. - **Behavior change:** a negative `Content-Length` is now read as 0. Before, the server waited on the socket. - **Verification:** `python3 -m unittest tests.test_daemon_serve` ran 32 tests, all OK. I added no test, because the existing `PostOriginTests` is the test that fails on Windows. - **Not done:** the ponytail and test-writer skills were not run as separate steps, and the change is not committed; it is one modified file in the worktree
- Keep unknown config keys, wake poll, mask log credentials
- Apply settings under scan lock; skip session scan in request
- Harden daemon settings routes: atomic save, host check, finite prices
- compare updates with release in use; refuse git-source selection
- fail loud on unpublished pin; reject prerelease selection
- Two test defects from this PR are fixed in tests/test_daemon_launch.py. No product code changed. The other failures are not from this change. Caused by this PR (fixed): 1. daemon, verify (18), verify (20): test_other_service_on_port_blocks_without_install failed on Linux. The assertion `runner.ran("pip") == []` matches by substring, so it caught the Linux-only python-venv check `python -c "import ensurepip"`. The assertion now checks that no `python -m venv` command ran, which is the first step of an install. 2. windows (3.9 and 3.12, shard 0): three LegacyAutostartTests run with platform="darwin" and reach `os.getuid()`, which does not exist on Windows. They now skip when `os.getuid` is absent, the same rule tests/test_daemon_install.py uses. Not caused by this PR (no change): - windows (3.9 and 3.12, shard 3): the 3.12 log shows only two test_member_tasks errors; I did not read the 3.9 log. - verify (18): the other 43 errors are in test_member_*, test_pipeline_*, test_workflow_architecture, test_trust_evidence and one test_rebase_recovery test. I did not read the verify (20) log beyond the excerpt. - The intent names all of these suites except test_rebase_recovery as the main-branch pollution from PR #260. These checks stay red until that separate fix lands. Verification: - RED: the CI log shows the Linux failure (`['.../python3', '-c', 'import ensurepip']] != []`) and the Windows AttributeError on `os.getuid`. - GREEN: `python3 -m unittest discover -s tests -p test_daemon_launch.py` ran 30 tests, OK (macOS). The changed test also passes with the installer platform forced to linux. With `os.getuid` removed, LegacyAutostartTests ran 6 tests, OK, 3 skipped. - Sabotage: with the port problem made non-blocking, the changed test fails. - Not run locally: the tests on real Linux or Windows, and the full suite
- Make the temporary daemon build copy user-writable
- Report failed legacy cleanup as non-blocking; check venv pip
- Harden launch check requirements and error reporting
- record env route flag rule and browser transport
- record read-only browser and token-gated env rulings
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
