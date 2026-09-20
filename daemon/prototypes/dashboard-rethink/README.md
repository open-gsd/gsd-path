# Dashboard rethink

Interactive, disposable design study. Sample data only. No daemon API calls, pipeline actions, or real settings writes. Open `index.html` directly, or use the local server at http://127.0.0.1:8876.

## Direction

Recommended: **Board as the default, Milestones as an alternate view**. This keeps the current project-first model while making future scope easier to compare. Project details remain a single page with folded history, not separate Overview/Activity/Usage tabs.

Physical scene: a developer at a bright desk checks several local projects beside their editor during the workday. Start with light neutral surfaces and a restrained blue accent; provide a dark switch for evening use. System typography and explicit labels carry the hierarchy. No new library, font service, or production styling system.

The nested `daemon/.agents/context/PRODUCT.md` supplies the current design constraints. In particular: a status board, no next-command prompts, no pipeline approvals, compact data, explicit missing evidence, and light/dark support. These override older attention-inbox notes.

## What to change

1. **Make state understandable without learning the glyphs.** Put phase names and plain blocked reasons beside the existing progress track. Keep cost and turns together.
2. **Show roadmap context on demand.** A past/current/planned view answers where projects are headed without adding columns to the daily board.
3. **Separate facts from detail.** A project page leads with the current milestone and phase, puts workspace/usage facts alongside it, and folds deep records.
4. **Give settings a coherent home.** Path defaults, agent models, watched folders, and plugin information share navigation. Save/Discard shows whether an edit is pending.

The prototype changes the hierarchy, not pipeline ownership. No run, approve, ship, or recovery controls are proposed.

## Try it

- Switch between Board and Milestones.
- Filter blocked or shipped projects; search names, repositories or milestones.
- Open Civic Nest to see a blocked project and the recorded reason.
- Open Settings, change Shipping mode, Save, change it again, then Discard.
- Switch theme with the moon button.

Settings persist only in this page's memory. Reload resets the sample. Project override editing, real plugin/folder management, live refresh/offline handling, complete ledgers and deep links are outside this prototype. They remain production integration work if this direction is selected.

## Verification

Run the server:

```sh
python3 -m http.server 8876 --bind 127.0.0.1 --directory daemon/prototypes/dashboard-rethink
```

Run the browser check with Orca open:

```sh
python3 -B daemon/prototypes/dashboard-rethink/verify.py
```

Observed RED: search did not filter rows. GREEN: board, state filters, blocked detail, timeline, settings Save/Discard, theme, search and empty state passed. Sabotage: removing the search predicate failed the same check. Restored file passed again. See `verification.log`.

Inspected actual browser screenshots of the board, timeline, project detail and settings. Both themes were rendered. This is not a full accessibility audit or a native toolbar redesign.

A formal DESIGN.md is absent. After choosing a direction, `/impeccable document` can record its tokens and component rules; this study does not make a new production design decision.

## History and file viewer

Open any project, then **History & files**, or follow a source link under Project records.

- Browse current milestone documents, an archived manifest, and repository README.
- Search by filename or path.
- Read Markdown preview or complete raw sample text, including JSONL.
- Select a recorded version or use a history entry to open that snapshot.
- See the source path, project, record group, timestamp, byte size, and read-only status.
- Expand tasks/criteria, reviews/verification, usage/models/turns, discussion/lessons/activity, and data-coverage examples on the project page.

The Markdown preview supports headings, paragraphs, lists, simple tables, code fences, inline code and bold. Raw text preserves the full sample. HTML is displayed as text. This small prototype renderer is not a complete CommonMark implementation.

**Production boundary:** these are embedded sample files and snapshots, not reads from watched project directories. Historical contents need Git revisions or stored snapshots; filesystem event history alone is insufficient. Live integration must retain full documents, safely confine reads to the selected project, preserve read-only archives, and expose missing/unsupported/failed sources distinctly. The expanded data sections demonstrate placement, not complete ingestion or accounting.

Viewer verification: the missing source-link check failed before implementation. Browser checks passed for evidence-to-file navigation, Markdown/raw modes, earlier revisions, archived records, file search/empty state and inert HTML. A sabotage that always displayed the latest file failed the earlier-revision assertion; the restored version passed. See `file-viewer-verification.log`.
