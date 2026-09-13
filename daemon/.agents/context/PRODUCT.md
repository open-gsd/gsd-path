# Daemon product context

## Register
product

## Users and purpose
Developers monitor local GSD Path projects and identify the next item that needs their input. The daemon reads project state; the dashboard exposes existing plugin and watched-folder management actions.

## Selected design
The user selected the attention inbox (concept 2) and the compact native menu-bar dropdown. Use an attention-first project list, a selected-project detail pane, visible verification and next-command copy actions. Use compact project rows in the dropdown, with attention summary and dashboard/settings links. Keep the native system appearance.

## Principles
Show real recorded state. Keep missing evidence visible. Use plain labels. Do not turn monitoring controls into pipeline execution or approval. Retain keyboard-operable controls and explicit status labels alongside colors.

## Visual reference update
The user requested the look of `~/github/open-gsd/gsd-cloud`. Use its Studio
palette and console layout: fixed left navigation, independently scrolling work
panes, indigo selection, neutral light/dark surfaces, 14px body, 24px headings,
8px controls and 14px panels. Source: `web/app/globals.css` and `docs/design.md`
in that repository. Human text uses the UI font; IDs and paths use monospace.
Use local font fallbacks so the daemon needs no font service.

## Project workspace correction
User: "not sure this is the right layout - maybe we neeed to unify them at a project level - the inbox/projects/activity pages all look the same .. just changing tabs on the project .. seems very redundant"
Use one Projects workspace with Attention / Active / All filters. Overview,
Activity and Usage belong to the selected project. Tray project links enter this
same workspace. Plugin and watched-folder management remain separate controls.

## Toolbar correction
User approved removing the left navigation rail. Use a slim top toolbar for the
GSD Path home action, connection status, and Settings menu. Group Plugin and
Watched Folders in Settings. The project workspace occupies the full width.

## Status board correction
User: "i think i want to make it just a status board .. no next steps. just
what we've done, where we are and where the path is headed. state is fine".
Chosen from five throwaway variants (`daemon/prototype-statusboard.html`):
variant E, milestone stacks, on both the tray and the dashboard, with light
mode. Each project shows shipped milestones, the current milestone with phase,
wave, tasks and git position, and planned milestones from ROADMAP.md plus the
lookahead in next/STATE.md. Remove attention items, next commands, copy and
reveal actions, evidence, activity and usage views. Keep the state pill and
health dot, the Settings menu with Plugin and Watched Folders, and offline
handling.

## Briefing details
User: "B on both, implement" after `daemon/prototype-details.html` (A Glance,
B Briefing). Both surfaces read more of `.project`: ROADMAP.md goal, depends-on
and integrated commit; archive MANIFEST.md ship date, tasks, waves, review
cycles and carried rulings; the STATE.md log as a phase timeline; CHARTER.md
Vision; intent Summary; task names per wave; success criteria with the last
verify result; and the latest LESSONS.md entry. Still no next steps or actions.

## Board, project page and usage
User: "should we do a per-project page with tabs? i feel that 1 page is going
to get cluttered". Chosen (`daemon/prototype-pages.html` A): a compact board
row per project and a per-project page with a back button and project switcher;
no tabs. User: "i also want to show cost + per turn + model/agent used". Chosen
(`daemon/prototype-usage.html` B with the ledger folded): usage read from host
session logs (Codex rollouts, Claude Code transcripts) matched by working
directory; cost from a per-model price table in daemon.json with no defaults;
cost and turns on the board row, the tray here line and each milestone; a
per-agent table and a per-turn ledger on the project page.

## Instrument redesign
User: "lets use the impeccable skill and redesign the toolbar and dashboard",
scope both the tray and the dashboard, problem "looks generic". Chosen from three
directions (`daemon/prototype-redesign.html`: A Route, B Instrument, C Lanes):
"B Instrument on both". Replaces the Studio palette with a cool graphite
Instrument palette and one teal signal, shared as hex values by `serve.py` and
`PopoverViewController.swift`. Dashboard toolbar: GSD Path, All / Active /
Shipped filters with counts, project search, update time, Settings gear. Board:
one table row per project with route squares, milestone, an 8-segment phase
meter in `canonicalPhases` order, tasks, cost, turns, updated, state. Project
page: Back and a project switcher, a facts strip, phase track, current
milestone, milestone and task tables, usage tables and the folded turn ledger.
Tray: menu-style rows (name, phase meter, one detail line) under In progress and
Shipped, and menu items in the footer. State pills and the tray goal and
last-shipped lines are removed.

## Light default and full data
User: "where is the light version .. also .. are we revealing all data/info/stats
that we can ?" Chosen: light by default with a System / Light / Dark switch on
both surfaces, and all four data groups: reviews and verify history; deeper
usage (token split, cache hit, agent time, cost and time per turn, tokens per
milestone, host per model); the reason behind a health dot, as plain text; and
milestone and task detail (task files, criteria text, archived verdict,
integration mode, recorded activity). Health reasons are shown as facts only;
there are still no next steps or actions. `serve` now records watcher events to
`history.jsonl` so the Activity list has data on macOS.

## Native colors and tray icons
User: "light doesn't work in toolbar - can we fix the open dashboard/plugin
settings/watched folders .. can those be icons ?" and "i also don't like that
green highlight color - lets use native OS colors". The tray uses system label,
separator, accent and selection colors with the popover's native material; the
footer is an icon toolbar with tooltips. The dashboard keeps graphite neutrals
but takes its accent from CSS `AccentColor` (system blue fallback); health dots
use system green. The teal signal is retired.
