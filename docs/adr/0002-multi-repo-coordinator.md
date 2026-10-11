# Multi-repo milestones use a coordinator repo

Status: accepted.

One milestone may change several Git repositories. One **coordinator** holds
`.project/`: state, tasks, review, archive, and the ship commit. Its
`.project/MEMBERS.md` lists the **members**; `members add` creates the file for
new or existing Git repositories. The fixed `REPOSITORY.md` format stays
unchanged.
Coordinator operations keep one `--repo`; the checkout-local detection command
is specified in the [work plan](../multi-repo-work.md). Without `MEMBERS.md`,
Path keeps its single-repo behavior and output.

One task changes one repo (`repo:` defaults to the coordinator). A member task
lands a product commit in the member and a record commit in the coordinator;
a journal makes the pair resumable. Build locks the participating members in
their `MEMBERS.md` order under `.project/build/`, not in STATE. Ship integrates
and tags those members in that order, then closes the coordinator. It records
each member's reviewed HEAD and integration. Git cannot merge repos atomically,
so a failed close remains partially shipped. Resume checks the exact remote
merge and tag before continuing, or a patch plan completes the close.

**Considered options:** a workspace folder outside Git holds `.project/` (the
ship commit and archive leave Git); linked peer projects each hold `.project/`
(no shared milestone or close); open every PR and merge all at the end
(pull-request mode only).

**Consequences:** every member bound, task, verify, and integrate branch, plus
member tags, includes the coordinator name. Branch checks accept these names
only for verified members. Joining adds no new tracked Path
files and leaves a member's existing `.project/` untouched. Its shared Git
directory holds a validated coordinator marker and exact push authorization
per ref and object, plus delete authorization per ref at its expected remote
SHA; member hooks call the coordinator guard. Member sidecars get untracked host
guard configs. They sit beside the coordinator verify sidecar in a shared,
pinned layout for cross-repo Verify. Ship records a
`Reviewed-HEAD` for each member. Member close creates no ship commit for this
milestone: its integration merge must have that reviewed HEAD as second parent,
and its tag is `milestone/<coord>-<archive-name>`. A member's remote default
must be `main`; each member may choose its integration mode. The
coordinator may be a product repo or a dedicated program repo. Submodules,
nested repos, and one task across two repos stay out of scope. The work plan is
[multi-repo-work.md](../multi-repo-work.md).

**Update 2026-10-10 (issue #372):** a member's remote default no longer must
be `main`. `members add` records the default branch of the member one time in
its `MEMBERS.md` section (`Default branch`); a section without the field means
`main`. The members and the coordinator may have different default branches.
A new repository that `members add --create` creates still uses `main`.
