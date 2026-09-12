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
