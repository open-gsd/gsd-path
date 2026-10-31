# Changelog: OpenGSD Path app

Changes to the desktop app in `daemon/app` and the monitor daemon it bundles.
The app has its own version and `app-v<version>` tags, separate from the
[npm package](../../CHANGELOG.md). Newest first.

## [Unreleased]

### Added
- The Projects board lists gsd-pi (`.gsd/`) and gsd-core (`.planning/`)
  projects. A folder with more than one framework shows one card per
  framework, with a framework badge. These cards are read-only.
- gsd-core cards show their milestone, phase step (discuss, research, plan,
  execute, verify), plans as tasks, phases as waves, the milestone timeline,
  VERIFICATION and UAT results, and STATE.md concerns (amber).
- gsd-pi cards show their milestone, phase step, slices as waves, tasks,
  every milestone, assessments, the verification ledger, STATE.md blockers and
  the next command. They read `gsd.db` read-only, with a fallback to the older
  markdown layout.
- **History & files** lists `.planning` and `.gsd` records and opens a gsd-pi
  or gsd-core card at its own `STATE.md`. A `.gsd` folder that links into
  `~/.gsd/projects/` is followed; every other link is still refused.
- Cards that share a folder name their framework in the tray and the Stats
  scope list, and Stats keeps each card's time per phase apart. The phase chart
  of a gsd-pi or gsd-core card follows its own steps.
- The Skills page lists gsd-pi and gsd-core with their installed versions
  (gsd-core per agent host) and the latest release. **Check for updates** reads
  them too (a failed check shows its error next to the framework), the update
  banner names any that are behind, and **Update…** shows
  the commands and then runs each framework's own update.
- Settings → App has a **Language** choice next to Appearance: System,
  English, or Simplified Chinese. System follows the OS language (zh, zh-CN,
  zh-SG, zh-MY, and zh-Hans pick Simplified Chinese; zh-TW and zh-HK stay
  English). The tray popover follows the choice. Project content (artifact
  text, phase names, file paths, command output), the native tray menu, and
  the browser dashboard at :8765 stay in English.

### Fixed
- When the installer refuses a request (exit 2), the failure card says
  "installer refused the request" and "Nothing was changed." It no longer says
  "partial install" and "Some folders were changed", because the installer
  refuses before it writes anything.

### Fixed
- On macOS and Linux, when the app or `gsd-path-daemon install` finds a
  `~/.gsd-path/venv` made by another Python, it rebuilds the venv for the
  current Python. Before, the venv mixed two Pythons: each launch reinstalled
  the daemon but still ran the old one.

### Fixed
- The Tasks table no longer squeezes short columns, such as task ID and
  wave, to one character per line. Task file paths wrap at `/`.

### Fixed
- Release and framework update checks work when the daemon runs under a
  python.org macOS Python with no CA certificates installed. The daemon then
  also trusts the macOS system roots (`/etc/ssl/cert.pem`); certificate checks
  stay on.

## [0.1.2] - 2026-10-03

### Fixed
- Guard hooks **Refresh** and **Add guards** work on a project with the old
  runtime layout (`.gsd-path/runtime/`). The app migrates the runtime first, in
  the same click, in place of the error "legacy runtime requires
  --runtime-migrate before refresh". Migration changes only `.gsd-path` files
  and leaves them as an unstaged Git change to review.
- **Add guards** adds the guards for the agents that have GSD Path skills
  installed on this computer. With no agent installed, it changes nothing and
  tells you to install the skills for an agent first.

## [0.1.1] - 2026-10-03

### Changed
- macOS builds are signed with a Developer ID certificate and notarized by
  Apple, so macOS no longer shows "Apple could not verify OpenGSD Path". The
  app opens without an approval in Privacy & Security.

## [0.1.0] - 2026-10-02

First tester pre-release. Builds have no OS code signature.

### Added
- One app for macOS (Apple Silicon and Intel), Windows, and Linux, with a tray
  icon and a tray popover.
- Setup: checks for Python 3.9+ and Git and shows the fix when one is missing;
  picks coding agents, installs skills, and chooses watched folders.
- Move from the old tray apps: the first launch removes the old LaunchAgent,
  Startup shortcut, systemd unit, and Swift login item, and turns on launch at
  login only when each one is gone.
- Projects board and project page: phases, milestones, tasks, reviews, verify
  history, usage, files at any Git version, and full recorded evidence.
- Skills page: installed and latest version per agent, release picker,
  preview, install, update, and uninstall with a plan.
- Project setup: runtime update and restore, guard hooks, health check, member
  hooks, and member marker repair.
- Settings: updates, Path settings, monitoring, usage and prices, launch at
  login, appearance, logs, and a diagnostics report.
- Stats: tokens and cost per day, time per phase, tasks per wave, and verify
  history.
- Environment editor for a project's `.env` files: values masked, one value
  shown on request, and a diff before each save.
- Signed self-update: the app asks before it installs and refuses an update
  whose signature does not match.

### Security
- The monitor the app starts accepts changes only with a local token that
  never enters the app's web view.
- Skills install from the npm release only after its sha512 matches the
  registry.

### Known limits
- No coordinator and member rows on the projects board.
- "Add project", "Open in agent", and "Remove everything" are not built.
- The Swift menu-bar app and the browser dashboard still exist beside the app.
