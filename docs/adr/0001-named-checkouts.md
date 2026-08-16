# Named checkouts, never detach

Task isolation and verify sidecars are named branches. Git refuses a second
checkout of the bound branch, and a SHA checkout detaches HEAD, so the
pipeline would otherwise look like it had fallen off `gsd-path/<slug>`.
Serial dispatch rounds (one ready task) land on the bound branch in the
primary worktree; parallel rounds use `gsd-path-task/<id>`. Reviews use
`gsd-path-verify/<name>`. The orchestrator calls `scripts/isolation.py`
instead of inventing `git worktree add`.

**Considered options:** always-detach sidecars (Git's default, opaque to
operators); always-isolate even serial tasks (keeps recovery branches, pays
the cherry-pick tax for one coder); commit serial tasks on the bound branch
(matches "work then commit", loses a retained task branch).

**Consequences:** `task_branch` is null on a serial round so retirement cannot
delete the bound branch. Ship's old detached merge onto default is out of
scope — `docs/milestone-close-git.md` already replaces that path.
