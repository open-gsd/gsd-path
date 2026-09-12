# Claude review receipt

Scope: uncommitted attention inbox and menu-bar implementation against HEAD `472244e`.
Source: Claude Code, completed successfully. This is a static review; no tests were run by the reviewer.

I read the full tracked diff, the three untracked files, `serve.py`, `PopoverViewController.swift`, `Models.swift`, `AppDelegate.swift`, `DashboardWindowController.swift`, `model.py`, `probe.py`, `watcher.py`, `discovery.py`, and the changed test. Nothing was executed; every claim below is marked as inspected code or derived reasoning.

# Review — attention inbox + compact tray dropdown (uncommitted, baseline 472244e)

## Findings

### F1 — High. The 5-second poll re-renders everything, collapsing the expanded overview and stealing keyboard focus

**Where:** `daemon/gsd_daemon/serve.py:661` (`stage.innerHTML = header + body`), reached unconditionally from `refresh()` at `serve.py:415`, on `setInterval(refresh, 5000)` at `serve.py:698`.

**Inspected facts.** `render()` rebuilds the whole `#stage` subtree on every poll, whether or not the payload changed. Three concrete consequences:

*A — the expandable overview cannot stay open.* `inboxDetail` emits `<details class="more">` with no `open` attribute (`serve.py:631`). Trigger: select any project on the Inbox view, click "Project overview, criteria and roadmap", keep reading. Within 5 s a brand-new `<details>` replaces it and it snaps shut. In the Inbox view this element is the only path to the phase stepper, stat cards, success criteria, and roadmap, so the contract's "expandable project overview" is effectively unusable. (Workaround exists: the Projects nav renders `tabOverview` unwrapped.)

*B — focus jumps to the Inbox nav button.* The focus-restore at `serve.py:662-665` does `focusData = {...focus.dataset}` and then matches with `Object.entries(focusData).every(...)`. For a focused element with no `data-*` attribute that object is `{}`, and `.every()` on an empty array is vacuously `true`, so `.find()` returns the *first* `<button>` in the stage — the `data-nav="inbox"` button. Every button in the Plugin view is in that category (`serve.py:568`, `570`, `577-579`, `596-598`), as is the `<summary>` element. Trigger: on the Plugin view, Tab to "Install for all detected hosts" and wait 5 s; focus is silently on "Inbox", so the next Space/Enter navigates away instead of installing. (Click-focus is a WebKit/Chrome difference; keyboard focus is the reliable trigger, and the patch deliberately added `:focus-visible` styling at `serve.py:158`, so keyboard use is intended.)

*C — the health footer loses its scroll position.* `.health-strip` is `overflow-x:auto` (`serve.py:198`) with `min-width:180px` per project plus a 24 px gap (`serve.py:199`). Past roughly eight projects it scrolls horizontally; because the element is a new DOM node after each render, its `scrollLeft` is 0 again every 5 s, so the projects past the fold cannot be reached and clicked. (New element ⇒ default scroll offset; this part is derived, not executed.)

**Smallest fix:** two small changes. (1) Guard the restore: `if (focusData && Object.keys(focusData).length)`. (2) Keep the disclosure state in `CState` (`CState.expanded`) and emit `open` accordingly, with a `toggle` listener to set it. Optionally also skip the DOM write when the produced string is unchanged, which removes most of the churn on idle polls.

---

### F2 — Medium. On runtime-enriched projects the attention headline degrades to "pending question" and the discussion context renders empty

**Where:** `daemon/gsd_daemon/probe.py:556-561` (`compute_attention`), consumed by `serve.py:608`, `615`, `617-623`.

**Inspected facts.** `compute_attention` takes `questions = status.pending_answers or status.answers`, then reads `pending.get("question")` and `pending.get("id")`. When `.gsd-path/runtime/pipeline_state.py` exists, `probe_project` sets `status.pending_answers` to the raw runtime list (`probe.py:658-665`). Those runtime records are keyed `answer`, not `id`, and carry no `question` — established by two independent places in the tree: `_collect_answers` resolves the id as `record.get("answer") or record.get("id")` and takes `"question": base.get("question")` from the ANSWERS.md parse only, never from the record (`probe.py:366-375`); and the Swift model declares `PendingAnswer { answer, owner, status }` (`Models.swift:59-63`).

**Derived failure.** For such a project the attention item becomes `{kind: "question", label: "pending question", ref: None}`. In the new UI that string is the list summary (`serve.py:608`) *and* the detail `<h2>` (`serve.py:618`), and because `inboxDetail` matches by `find(a => (a.id || a.answer) === item.ref)` with `ref === null` (`serve.py:615`), there is no question paragraph, no Owner row, and no Reference row. The contract's "discussion context" renders as a bare "pending question". On the parse-only path (no runtime file) the same code works correctly, because `status.answers` entries do carry `id` and `question` — so the feature works in exactly the configuration the tests use and fails in the enriched one.

Trigger: a project with `.gsd-path/runtime/pipeline_state.py` present that reports one pending answer, plus `.project/discuss/ANSWERS.md` containing `## Answer A012` with `**Question**:` / `**Status**: NEEDS-USER` / `**Follow-up**: required`.

This defect is pre-existing in `probe.py`; the patch exposes it by promoting the attention label from one line in a "Needs you" box to the page headline.

**Smallest fix:** in `compute_attention`, iterate `status.answers` (already populated at `probe.py:670`, before the call on `:671`, and already carrying `id`/`question` merged from ANSWERS.md) instead of the raw `pending_answers`.

---

### F3 — Medium. Every page load first paints "No projects yet" with a red connection dot

**Where:** `serve.py:696` (`applyHash()` → `render()`) runs before `refresh()` at `serve.py:697` resolves.

**Inspected facts.** At that point `DATA.projects` is `[]` and `ONLINE` is `null`. `render()` therefore produces: intro "0 projects need attention. 0 projects are moving." (`serve.py:655`), detail pane "No projects yet. Add a watched folder to get started." (`serve.py:651`), an empty health strip, and a **red** dot beside "Connecting…" — the class is `ONLINE ? "g" : "r"` (`serve.py:645`) and `null` is falsy, so "connecting" is painted in the same colour the rest of the UI reserves for blocked/offline.

Trigger: load `http://localhost:8765` (browser, or the tray's "Open Dashboard", which does a full `webView.load` / `reloadFromOrigin` per `DashboardWindowController.swift:52-60`) with any number of watched projects. The false state is not a race — the synchronous `render()` always precedes the first `/status` response. It also persists for the whole request if `/status` errors; `do_GET` has no guard around the `/status` branch (`serve.py:769-772`), so a serialization failure leaves the user told to add a folder while folders are watched.

**Smallest fix:** while `ONLINE === null`, render a "Connecting…" placeholder instead of the empty-state copy, and select the dot class from a three-way map (`null` → neutral, `true` → `g`, `false` → `r`).

---

### F4 — Medium. The project root path and the status source disappeared from the dashboard

**Where:** the patch deletes `<div class="faint">${esc(p.root)} · source: ${esc(p.status_source || "?")}</div>` (diff hunk at old `serve.py:449`). I checked every new render path: `p.root` now appears only as a fallback when `project` is null (`serve.py:617`, `650`, `659`), as the opaque `data-root` value, and in `tabActivity`'s heading fallback (`serve.py:552`). `tabOverview` (`serve.py:455-477`) never showed either field.

**Concrete failures.**
1. Two watched projects whose `STATE.md` `project:` values are equal — two separate repositories for the same product, or a project copied to a second location — render as two identical rows in the inbox list, two identical buttons in the health footer, and an identical detail header. Nothing distinguishes them or tells you which one is selected. (Git worktrees of one repo are deduped in `discovery.py:48-52`, so this needs two distinct repos.)
2. You copy `$gsd-path-build` from the detail pane and the dashboard tells you nothing about which directory to run it in. The native tray still has "Reveal" (`PopoverViewController.swift:339-343`); the dashboard has no equivalent.
3. `status_source` was the only signal distinguishing `runtime` from `parse-only` — the same distinction that silently changes behaviour in F2.

**Smallest fix:** put the root back into the detail kicker (`serve.py:617`) and onto the list row's `<small>` line or its `title` attribute, and restore the source next to it.

---

### F5 — Low. The native dropdown is no longer bounded, so it stops being compact

**Where:** `PopoverViewController.swift:207` raises the height cap from a fixed 600 to `NSScreen.main.visibleFrame.height`, while `show(status:)` now renders every project (`:151-153`) — the quiet-project disclosure and `lastStatus`/`quietExpanded` state are removed.

**Derived arithmetic** (from `ProjectRowView` at `:273-324`): 12/12 pt insets, 7 pt spacing, and up to five stacked lines (name+pill, milestone·phase·wave, tasks, attention, actions) gives roughly 130–145 pt per project, plus ~10 pt outer spacing; the header and footer blocks add a couple of hundred more. A handful of projects therefore exceeds a typical `visibleFrame` height and the popover clamps to the entire visible screen. A menu-bar popover that spans the full display is contrary to the contract's "compact dropdown"; the `NSScrollView` built in `loadView()` already exists to handle overflow.

**Smallest fix:** restore a bounded cap. The value removed was 600; the right ceiling is an owner call, but it should not be the screen height.

---

### F6 — Low. Top-nav state and page content disagree after switching detail tabs from the Activity view

**Where:** `serve.py:276` (`navigate`) and `serve.py:654-655`.

Trigger: click "Activity" in the top nav, then "Overview" in the detail tabs. `navigate("activity")` sets `view="activity", tab="activity"`; `cTab("overview")` (`serve.py:674`) changes only `tab`. The `detail` ternary then falls through to `inboxDetail(p)` because `view !== "projects"`, so the attention-inbox detail is shown while the top nav still marks Activity as `aria-current="page"` and the `<h1>` still reads "Recent activity".

**Smallest fix:** have `cTab` move `view` in step (`tab === "activity"` ⇒ stay, otherwise fall back to `inbox`), or derive the heading from `CState.tab`.

---

### F7 — Low. A verification record with no result is displayed as a failure

**Where:** `serve.py:629`: `class="${e.result === "pass" ? "pass" : "fail"}"` with text `esc(e.result || "Unknown")`.

`parse_verify_ledger` copies `result` straight through (`probe.py:286-291`), so a `verify-ledger.jsonl` line such as `{"command": "make test", "recorded_at": "..."}` with no `result` key yields `null`, and the contract's "recorded verification" pane prints "Unknown" in the red fail colour. Unknown is not failed.

**Smallest fix:** three-way class — `pass`, `fail`, neutral for anything else.

## Test blind spots

- `tests/test_daemon_inbox_ui.py` is the only test of the new dashboard behaviour and is `@skipUnless(GSD_UI_TEST)` plus dependent on Orca's CLI. `UI-VERIFICATION.md` confirms the recorded 157-test run set the variable, but a plain `python3 -m unittest discover -s tests` reports success while covering none of the inbox.
- `test_daemon_serve.py::test_dashboard_html` still passes only because `"Needs you"`, `class="tabs"`, `VERIFY`, and `DISCUSSION` happen to survive inside `tabOverview`/`activityItems`. It asserts nothing about the inbox, the filters, the health strip, or the offline state, and dropping the `"&tab="` marker removed its only URL-shape assertion without replacing it for the new `#project=&tab=&view=&filter=` form.
- `sample_projects()` hand-builds `attention=[{"kind":"question","ref":"A012"}]` alongside `answers=[{"id":"A012","question":…,"owner":…}]`. That pairing matches by construction and is not what `compute_attention` produces on the runtime path (F2). No test builds a `ProjectStatus` from a real `.project/` tree through `probe_project`, so the discussion pane is only ever proven against a fixture designed to satisfy it. `UI-VERIFICATION.md` states this limit explicitly ("Sample data is limited to the test fixtures").
- `daemon_tray_ui.swift:45` asserts `link.fragment?.contains("&tab=usage") == false`. Whether `URL.fragment` returns the percent-encoded or the decoded fragment depends on the Foundation version, so the assertion's meaning is toolchain-dependent. Nothing covers the dashboard half of that contract — that `%26`/`%3D` inside `project=` is not re-split by `URLSearchParams`. (I read that path and it is correct; only the proof is missing.)
- Nothing exercises the idle-poll re-render (F1). The browser test only calls `refresh()` explicitly and never leaves the page idle across a tick.
- The Folders view is covered only by asserting the words "Add folder" appear. `data-remove-parent` and `add-folder` are never clicked.

## Things I checked and found correct

Worth recording so the negative space is visible: modals are appended to `document.body` (`serve.py:328`, `394`), so the poll does **not** destroy the uninstall-plan or folder-browse dialogs; `data-remove-parent` uses `!= null`, so index 0 works (`serve.py:678`); plugin buttons with inline `onclick` bubble to the delegated listener without misfiring, because none of the dataset branches match; the tightened `esc` (`serve.py:240`) and the narrowed `projectDeepLink` character set (`PopoverViewController.swift:364-365`) together close the `&tab=` injection via a project root; `(p.waves || {})[p.current_wave]` works despite `waves` being serialized with string keys (`model.py:83`), since JS coerces property keys; the `#filter=attention`, `#folders`, `#plugin`, and `#project=…&tab=activity` deep links all parse to the intended state in `applyHash`; `DashboardWindowController.show` re-navigates on a fragment-only change, so tray links reach an already-open window; and no monitoring control posts to a pipeline endpoint — `copySkill` only writes `"$" + raw` to the clipboard.

## Verdict

**Changes requested.** The contract's surfaces are all present and wired to real daemon data, and the escaping and deep-link hardening are genuine improvements. But F1 makes the inbox's expandable overview unusable and silently moves keyboard focus, F2 means the headline discussion content is empty on the normal runtime-enriched project, F3 mis-states the system on every page load, and F4 drops the only identifying path from the dashboard. F1 and F3 are self-contained fixes in `serve.py`; F2 is a few lines in `compute_attention`; F4 is one restored line.

## Verification limitations

I ran nothing — no tests, no build, no browser, no daemon. Memtrace was unavailable, so all navigation was by direct reads. The recorded evidence (157 tests, native UI acceptance, app build, visual inspection) is taken as reported, not reproduced. F1-A, F1-B, F2, F3, F4, F6, and F7 are derived from code I read and are deterministic given the quoted lines. F1-C (health-strip scroll reset) and F5 (popover height) are arithmetic and DOM/AppKit reasoning I could not observe rendering; both would be confirmed in seconds by loading the dashboard with enough projects to overflow, and by opening the tray with five or more projects. I did not evaluate visual design quality, dark-mode behaviour, or the oklch fallback palette beyond reading the declarations, and I did not inspect the Swift self-test binary or `build.sh`.

# Maintainer triage

The source confirms the structures described in F1–F4. F2 is a pre-existing producer issue exposed by the new discussion detail view; it is not newly introduced by the patch. Runtime reproduction remains outstanding.

F5 is advisory, not a required fix: the report does not demonstrate failure at the actual screen size/project count, and project policy does not authorize inventing a replacement height cap.

The claim that the dashboard half of encoded-root navigation has no coverage is overstated: the browser test uses a root containing an apostrophe and `&tab=usage`, then follows a discussion link and reloads while asserting the Atlas detail remains selected.

No product or test code was changed during this review.
