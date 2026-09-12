# Attention inbox and menu-bar implementation

## Contract
Implement selected design 2 and the compact native menu-bar dropdown using the
existing daemon status payload and existing management actions.

## Changed code and proof
- `daemon/gsd_daemon/serve.py`: attention inbox, project filters, detail pane,
  health strip, URL navigation, settings access, explicit offline state.
  Exercised through the real HTTP handler by `tests/test_daemon_inbox_ui.py`.
- `daemon/macos/Sources/GSDPathTray/PopoverViewController.swift`: compact rows,
  attention summary, visible pre-plan projects, settings and project links.
  Exercised by `tests/daemon_tray_ui.swift` using real AppKit controls.
- `tests/test_daemon_serve.py`: removed the obsolete literal `&tab=` source
  assertion. The browser test now verifies navigation and reload behavior.

## RED
On the original implementation at HEAD `472244e`:
- `GSD_UI_TEST=1 python3 -m unittest discover -s tests -p test_daemon_inbox_ui.py`
  exited 1: `What needs you` was absent; the old project overview rendered.
- Compile the native test using the command in `daemon/macos/README.md`, then
  `/tmp/gsd-tray-ui-test`: exited 1, `compact watched-project count`.

## GREEN
- `GSD_UI_TEST=1 python3 -m unittest discover -s tests -p 'test_daemon_*.py'`:
  157 tests passed, including the embedded-browser acceptance test.
- Native compile and `/tmp/gsd-tray-ui-test`: passed project order, task counts,
  attention summary, settings, rescan callback, encoded project link,
  empty state, offline state and retry callback.
- `bash daemon/macos/build.sh`: built and signed `GSDPathTray.app`.
- `git diff --check`: passed.

## Sabotage
- Temporarily forced filter selection to `all`; ran the inbox test above.
  Exit 1: Atlas API incorrectly remained in Running.
- Temporarily changed `attentionCount > 0` to `attentionCount < 0`; compiled
  and ran the native test above. Exit 1: `attention summary action`.
- Restored both files before the final passing runs.

## Visual review
Viewed the rendered dashboard in Orca's embedded browser and the real AppKit
view in a temporary native window. Rechecked corrected tab spacing (22px).
At a 390px viewport, the dashboard document width was also 390px, with no
horizontal page overflow. Native controls follow system light/dark appearance.
Sample data is limited to the test fixtures. No new runtime dependencies.

## Scope
Local implementation and app build. No installation, commit, push or PR.

## Studio restyle
Reference: `/Users/jeremymcspadden/github/open-gsd/gsd-cloud/web/app/globals.css`
and `docs/design.md`. Applied its exact light/dark palette, left rail, spacing,
indigo selection and monospace metadata to the dashboard and native dropdown.

Proof for `serve.py` and `PopoverViewController.swift`:
- RED: browser test failed on the former warm background; native test failed
  with `Studio dark surface` before implementation.
- GREEN: `GSD_UI_TEST=1 python3 -m unittest discover -s tests -p test_daemon_inbox_ui.py`
  passed; `python3 -m unittest discover -s tests -p test_daemon_serve.py` passed 13 tests.
- GREEN: compiled `tests/daemon_tray_ui.swift` with the app sources excluding
  `main.swift`; the binary passed, including its new rendered dark-surface check.
- Sabotage: replacing the web light background with black failed the browser
  assertion; replacing the native dark background with black failed its assertion.
  Both restored before final passing checks. No runtime dependencies added.
- Built the native app and reinstalled the local daemon package; restarted the
  daemon and launched the rebuilt tray. Viewed the live dashboard in Orca and
  the real native views in a temporary test window. The test window was closed.

Earlier Claude review findings remain open; this change addresses visual design.

## Compact dashboard sizing
User screenshot showed excessive dashboard spacing. Kept the Studio palette and
14px body text; reused its 16px section heading and 10px/14px row padding.
Reused the existing responsive widths (190px navigation, 240px project list) for
desktop. Removed the redundant eyebrow and tightened detail spacing.

- Browser test: RED at 24px heading versus intended 16px; GREEN after change.
- Sabotage: restored 24px heading temporarily; assertion failed, then restored
  compact CSS and passed the browser test again.
- Focused server tests: 13 passed. `git diff --check` passed.
- Ponytail review: CSS and redundant label only; reused existing layout and
  spacing values, with no dependencies or new layout abstractions.
- Installed local daemon and restarted launchd; inspected live Orca screenshot.
- At 1422x959 viewport, header decreased from 129.6px to 65.1px; rail from
  244px to 190px; detail pane increased from 830px to 960px.
- At 390px viewport, document width was 390px (no horizontal overflow).
- Native dropdown unchanged. Existing Claude review findings remain open.

## Scroll continuity and layout
Reproduced expanded detail closing and scroll resetting during refresh in a
900x600 browser frame (native minimum window dimensions). Browser regression
failed before implementation, passed after, failed again when restoration was
sabotaged, and passed after restoration. Focused server tests: 13 passed.
Removed the duplicate health footer; bounded both panes with min-height:0 and
made them keyboard focusable. Restore expansion and scroll only for the same
view/filter/project/tab. Empty focus datasets no longer match the first button.
Ponytail review: use native scrolling and existing render path, no dependencies.
Installed and restarted local daemon. Inspected live expanded/scrolled dashboard
in Orca; expansion and scroll survived polling. Native wheel input was not tested.

## Unified project workspace and review fixes
Removed overlapping Inbox/Projects/Activity navigation. Kept project tabs,
rendered all attention items, restored path/copy, removed repeated overview
sections, made unknown verification neutral, and distinguished initial loading.
Cold links retain their requested project while loading; refresh retains focused
controls and panes for the same project view. Runtime attention uses merged
answer context. Native rows have one opening action and an Actions menu; footer
controls remain outside the scroll area; copy feedback and icon accessibility
labels added.

Proof: browser acceptance passed; probe tests 41 passed; server tests 13 passed;
AppKit harness passed. Sabotage caught cold-link fallback, missing merged answer
context, and missing native copy feedback. Restored all before final passing
checks. Browser checks include multiple attention items, neutral unknown result,
project path, cold reload, focus/scroll retention. Native checks include fixed
Dashboard control and actual clipboard copy. Ponytail review kept existing
renderer and native controls, with no new dependencies.
Built and relaunched native app; installed local daemon and restarted launchd.
Inspected live dashboard after reload: Projects/Plugin navigation and requested
report-dashboard selection. Inspected native test window; closed it afterwards.

## Remove navigation rail
Replaced the left rail with a top toolbar containing the project-home action,
connection state and Settings disclosure. Plugin and Watched Folders remain
reachable through Settings; expanded menu survives polling and Escape closes it.
The project workspace now occupies the full width. Ponytail review used native
details/summary and the existing navigation handler; no new dependencies.

Browser acceptance: RED with the old rail, GREEN with toolbar; sabotage disabled
menu-state restoration and failed the assertion. Restored final browser run
passed. An intermediate run failed in the browser tool during navigation; final
rerun passed. Server tests: 13 passed. Live 390px frame: document width 390px.
Installed local package, restarted launchd, reloaded live browser. Screenshot
capture reported visibility timeout; rendered browser assertions are the proof.

## Compact both surfaces
User: "Too large—make them more compact". Reused existing 8px/4px spacing.
Removed inherited 66px toolbar minimum; live toolbar now 54px. Title/summary
share a line; live intro is 35.75px. Tightened rows and detail spacing while
keeping 14px body text. Tray actions share project heading; connection shares
app heading. Same native fixture window decreased from 645px to 509px high.
Browser and native regression checks failed before changes and on deliberate
sabotage, then passed after restoration. Server tests: 13 passed. Ponytail:
existing CSS/native stack layout only, no new dependency or arbitrary size cap.
Rebuilt and relaunched tray, installed/restarted daemon. Inspected live dashboard
and native sample window screenshots; closed the sample window.

## Status board (milestone stacks)
User chose variant E of `daemon/prototype-statusboard.html` for both surfaces
and asked for light mode. Replaced the attention inbox with one card per
project: shipped milestones, the current milestone (phase, wave, tasks, time in
phase, waves, git branch/head) and planned milestones from `roadmap_milestones`
plus `next_milestone`. Removed attention items, next commands, copy and reveal
actions, evidence, activity and usage views from both surfaces. Kept Settings
(Plugin, Watched folders), offline handling, `#project=` deep links, and the
Studio light/dark tokens with `data-theme` override.

- `daemon/gsd_daemon/serve.py`: board renderer, milestone stack builder, page
  CSS; 698 lines changed, net -282. `node --check` on the inline script passes.
- `daemon/macos/Sources/GSDPathTray/Models.swift`: `roadmap_milestones`,
  `milestoneStack`, `stackText`, `hereText`, `stateLabel`, `stateRank`.
- `PopoverViewController.swift`: stack row, no attention summary or Actions menu.
- Tests: `tests/test_daemon_board_ui.py` replaces `test_daemon_inbox_ui.py`;
  `tests/daemon_tray_ui.swift`, `test_daemon_serve.py` and
  `test_daemon_plugin.py` updated for the removed inbox markers.

RED: `test_daemon_serve.test_dashboard_html` and
`test_daemon_plugin.test_dashboard_has_plugin_tab` failed against the new page
until their inbox markers were replaced; the tray test's stack assertions do not
exist in the old row view.
GREEN: `python3 -m unittest discover -s tests -p 'test_daemon_*.py'`: 157 pass,
1 skipped; `test_daemon_attention.test_pending_answer_question_amber` fails
identically on the untouched HEAD and is out of scope.
`GSD_UI_TEST=1 ... test_daemon_board_ui.py` passed in Orca's browser: theme
palettes, card order, done/here/ahead stack, lookahead milestone, no commands
on the board, deep-link reveal surviving refresh, Settings menu, folders and
plugin views, 390px frame width 390, empty and offline states.
Native: compiled `tests/daemon_tray_ui.swift` with the app sources; passed
stack lines, state pills, absence of actions, footer, order, rescan, deep link,
empty and offline states. `bash daemon/macos/build.sh` built and signed.
`git diff --check` passed.
Installed the local package, restarted launchd, relaunched the tray. Inspected
the live dashboard in Orca at 1440px in dark and light: 4 project cards,
summary "4 projects · 1 in progress · 3 shipped", report-dashboard stack
M001-M004 shipped and M005 pending, no console errors, no horizontal overflow.
Native window screenshot was blocked by the display capture permission; the
AppKit assertions are the tray proof.
Ponytail review: one render path, no new dependencies or abstractions; the
stack builder is shared logic in the page script and in Models.swift.

## Briefing details on both surfaces
User chose variant B of `daemon/prototype-details.html`. New parsers in
`probe.py`: roadmap goal, depends-on and integrated commit; archive
`MANIFEST.md` (ship date, verdict, waves, tasks, review cycles average, carried
rulings); `parse_phase_log` (STATE.md log scoped to the current milestone, each
phase once in first-seen order, current phase dated by its latest entry);
`_section_paragraph` for CHARTER.md Vision and intent Summary;
`parse_latest_lesson`. `model.py` carries `phase_log`, `vision`, `intent`,
`lesson`. The dashboard card renders vision, manifest metadata and goals on
shipped rows, goal, intent, depends-on, entered date, usage, task names per
wave, criteria strip with the last verify result, phase-log strip and the
latest lesson. The tray row adds criteria and since-date to the here line, the
goal line and a last-shipped line. Still no next steps or actions.

Proof: Python suite 164 tests, OK, 1 skipped (new probe tests for roadmap
fields, manifest, phase log scoping and de-duplication, section paragraphs,
lessons). `GSD_UI_TEST=1 ... test_daemon_board_ui.py` passed in Orca with the
briefing assertions (vision, manifest line, goals, depends-on, intent, task
names, 2 of 3 criteria, verify pass, phase log `def|plan|now:build`, lesson).
Native test passed the here line with criteria and since-date, the goal line and
the last-shipped line. `git diff --check` passed. The real report-dashboard
project probes to a 6-entry phase log after scoping (106 raw entries before),
4 manifests, a vision and a lesson. Installed and restarted the daemon and tray;
inspected the live board at 1440px in dark and light with 4 real projects, no
console errors, document width 1440. Phase labels abbreviated after live
inspection showed them wrapping in narrow segments.

## Board, project page, and usage from host session logs
User chose the board → project page layout (`daemon/prototype-pages.html` A)
and the usage ledger (`daemon/prototype-usage.html` B, ledger folded).

- `daemon/gsd_daemon/sessions.py` (new): parses Codex rollouts (session_meta /
  turn_context cwd and model, task_started timing, token_usage_record per model
  response, `$gsd-path-*` skill and task id from user prompts) and Claude Code
  transcripts (assistant `message.model` + `message.usage`, cwd, sidechains as
  subagents). `SessionIndex` reads only the head of each file for its cwd, parses
  files under a watched root, and re-parses only when size or mtime change.
  `spend_for` aggregates turns, prompts, tokens, cost, models, agents, recent
  turns and per-milestone slots (a turn dated on or before a ship date belongs
  to that milestone). Cost is tokens × `Config.prices`; a slot with no priced
  turn has cost `null`, never `$0.00`.
- `config.py`: `session_dirs` (glob patterns, defaults for `~/.codex`, Orca's
  codex-accounts homes and `~/.claude/projects`) and `prices` per model.
- `watcher.py`: scans sessions and attaches `spend` on every poll, since usage
  changes without touching `.project`; failures never stop the poll.
- `serve.py`: board rows grouped Needs attention / In progress / Shipped with
  stack line, here line, cost · turns and pill; project page with back button
  and project switcher; usage block with stat tiles, per-model bars, per-agent
  table, folded per-turn ledger and an unpriced-models note; milestone cost on
  stack rows. `#project=<root>` opens the page.
- Tray: `Spend` model; here line appends `$cost · N turns` for the current
  milestone when present.

Proof: Python suite 173 tests, OK, 1 skipped (new `test_daemon_sessions.py`:
Codex and Claude parsing, duration, agent naming, price table, index caching and
re-parse on growth, root matching, spend totals, unpriced handling, milestone
attribution; config price parsing). `GSD_UI_TEST=1 ... test_daemon_board_ui.py`
passed in Orca: row order and groups, stack and here lines, cost · turns on the
row, no cards on the board, page open with hash, switcher, briefing details,
usage tiles, model bars, agent table, folded ledger content, page survives
polling, switcher navigation, cold deep link, Back, Settings, folders, plugin,
390px page width. Native test passed the here line with cost and turns.
`git diff --check` passed.
Real data: 12,049 session files scanned in 4.85 s once, then 0.08 s per poll;
214 files matched watched roots. report-dashboard resolved to 9,233 model
responses over 282 prompts, models gpt-5.6-sol and gpt-6-astra, agents such as
`$gsd-path-ship · T003`; with no price table every cost reads "—" and both
models are listed as unpriced. Installed and restarted the daemon and tray;
inspected the live board (4 rows, shipped rows collapsed, turns on the right)
and the report-dashboard page with its usage block at 1280px; no console
errors, document width 1280.
