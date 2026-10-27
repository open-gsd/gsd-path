# Project runtime selection

Before running a project runtime helper, check for
`<absolute-project>/.gsd-path/runtime.json`. When present, run the stable launcher:

```sh
python3 -B <absolute-project>/.gsd-path/status_runtime.py --repo <absolute-project> --runtime-path
```

Use `python` only when it is the compatible Python 3.9+ interpreter. A failure
stops helper execution: follow the exact-version restore action in the error.
Do not install, upgrade, or fall back to the current plugin's runtime implicitly.

The returned directory is the verified Project runtime. Resolve helper names
present in its `manifest.json` from that directory, including status, state,
isolation, integration, archive, recovery, build-state, final-verification, and guard helpers.
The workflow runner resolves its subprocess helpers from this same directory;
helper imports stay within the selected runtime. This rule overrides
references to bundled copies of those helpers. Other skill helpers, templates,
and role briefs remain in the installed skill bundle. Pass `-B` to Python helper
invocations so execution does not create bytecode in the runtime store.

When the runtime enforcing an active task cannot finish it, one narrowly
authorized recovery exists:
`python3 -B <absolute isolation.py> runtime-hotfix --repo <absolute primary>
--task-id <id> --runtime <64-hex runtime digest printed by runtime_store.py publish>
--authorized-by <the owner ruling>` validates the replacement runtime,
re-runs that task's Verify in a fresh sidecar at the recorded base under the
replacement pin, and records the receipt twice: a Log line in the task file
naming the task, base, and both runtime digests, and an identical blob behind
the local ref `refs/gsd-path/runtime-hotfix/<task>-<base>`. Only a Log line
whose exact twin that ref holds later admits `.gsd-path/runtime.json` into that
task's landing, and only when the pin names exactly the receipt's runtime; any
other task, base, a Log line alone, or a bare mention authorizes nothing, and a
failing re-run refuses the hotfix. Limits: the command serves only a serial
task working in the primary and refuses parallel or member tasks; the ref is
local repository state, so a clone without it cannot land the pin and the
proof fails closed. The guard applies two rules to agent shell commands. It
denies any command where `runtime-hotfix` directly follows `isolation.py`, stdin
`-`, or an `isolation` module operand (`-m isolation`, `-Bm isolation`,
`-misolation`). It also denies every Git command whose words, including global
`-c` options and shell variables set earlier in the command, contain
`refs/gsd-path/`; this deliberately blocks read-only uses such as
`git log refs/gsd-path/<ref>` too. Limits: it cannot see a copied or renamed
`isolation.py`, a refspec stored in a Git config file, a ref write made from
inside another program, or a direct edit of files under `.git/`.

Publishing a runtime to the shared store is project-free:
`python3 -B <absolute runtime_store.py> publish --source <absolute package root>`
verifies and publishes the content-addressed runtime, printing its version,
digest, and store path as JSON; `--provenance` records a note in that output
only. Publication alone neither authorizes execution nor changes a project's
trusted runtime — a project runs the bytes only when its own pin names that
digest.

The selected runtime is authoritative for each helper in its `manifest.json`;
this includes `review_findings.py` and `task_context.py`. A selected runtime
that was published before a helper became a runtime file does not list that
helper: run the bundled copy until the project runtime is upgraded.
`dispatch_driver.py` and `workflow_run.py` always run from the installed skill
bundle, because they read role briefs and templates from it; a skill update
replaces them, a runtime upgrade does not. The driver reloads the helper modules
that it imports from the selected runtime, and runs the subprocess helpers that
the runtime lists (such as the fix-task brief lint) from it.

With no declaration, retain the legacy helper lookup. An existing
`.gsd-path/runtime/` requires the explicit `--runtime-migrate --project PATH`
operation before adopting external storage; review the resulting Git diff.
