# Changelog

All notable changes to [@opengsd/gsd-path](https://www.npmjs.com/package/@opengsd/gsd-path)
are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.0] - 2026-09-18

### Added
- Scoped npm package `@opengsd/gsd-path` with trusted publishing workflow
- Release trust evidence validation and host matrix documentation

### Changed
- Release workflow and maintainer documentation for npm publication

## [1.0.0] - 2026-09-15

### Added
- Initial public release of the disk-backed GSD Path pipeline
- Multi-host installer, skills package, and project contracts

## [1.2.0] - 2026-09-20

### Added
- add Path settings and project history dashboard
- add optional Jev evidence screening
- store worktrees and pinned runtimes outside project checkouts
- centralize sub-agent model selection policy

### Changed
- Correct stale release guidance and consolidate scope references
- record passing eight-host release gate
- validate corrected OpenCode release evidence
- validate recovered Claude release evidence
- record affected release gate results
- preserve blocked host evaluations without receipt fallback
- record passing Antigravity Kimi and Grok release runs
- record remaining 1.2.0 release gate failures
- record Kimi receipt and complete offline recheck
- preserve 1.2.0 host receipts and release blockers
- record v1.3.0 live release evidence and blockers
- bump version to v1.3.0
- Align release documentation with risk-based host validation
- bump version to v1.2.0
- Automate npm release docs, pack verification, and provenance (#133)
- refresh README changes and dashboard screenshots
- Refresh dashboard navigation and file history documentation
- Clarify Jev receipt fields and consolidate documentation
- Refresh dashboard update and guard documentation
- Correct runtime installation, update, guard, and uninstall documentation
- Correct model policy and dispatch documentation

### Fixed
- reuse unchanged host receipts for releases
- verify prepared releases without advancing failed versions
- scope release evidence to affected hosts
- show project runtime updates and release completed milestone guards

### Other
- Fixed tests/package.test.mjs to invoke git_guard.py with pre-commit in a temporary Git repository instead of unsupported --help. The focused test failed before the fix and during restored-original sabotage. All 6 package tests now pass; resource sync and diff checks pass. Verified locally on Node 26; Node 18/20 CI reruns remain with the outer executor
- Preserve historical commit selection across relative document links
- Validate Jev probability normalization with CLI regression coverage
- Record passing focused checks and isolation violation
- Fix integration guard and runtime installer regression coverage
- Fixed stale runtime paths in tests/test_git_guard.py using the installed runtime resolver. Both CI failures reproduced before the fix; all 38 Git guard tests now pass. Both corrected tests also caught a temporarily disabled native guard, which was restored. git diff --check passed. Only the test file changed; remote CI remains for the outer executor
- Fix pinned runtime routing, guard blocking, and launcher bytes
- Restore same-cycle recovery after partial review completion
- Isolate assignment rejections and align native panel exclusions
- Fix dispatch isolation, legacy pinning, and independent panel selection

## [1.3.0] - 2026-09-21

### Added
- migrate legacy runtimes during upgrades

### Changed
- Clarify receipt reuse and consolidate release policy guidance
- Clarify legacy upgrade guidance and verify syntax
- update release notes for v1.2.0

### Fixed
- validate installer changes without live host reruns
- preserve closed review cycles in host recovery
- clarify owner gates and accept serial task release evidence

### Other
- Clarify reviewer ownership; live verification remains pending
- Reject unretired verification worktrees and branches in release evidence
