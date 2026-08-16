# GSD Path

Pipeline that takes an idea to shipped code through gated phases. This glossary
is for the product domain, not for any one implementation of git.

## Language

**Milestone close**:
The ship-phase sequence after final-review approval: the archive, the ship
commit, and whatever git makes that close durable. It is not task-end landing
and not abandon.
_Avoid_: end of work, ship (the whole phase), integration (one optional leg)

**Ship commit**:
The single `.project/`-only commit on the bound branch, subject
`ship: <NNN>-<slug>`, that records shipped state, final reviews, and the
archive.
_Avoid_: ship merge, integrate commit

**Milestone tag**:
An annotated tag `milestone/<NNN>-<slug>` pointing at the ship commit. Ship
creates it at close and pushes it to origin. It names that close; it is not
the landing pointer.
_Avoid_: release, GitHub Release, lightweight tag

**Integration**:
A write-access human creating default ancestry from the landing pointer. On
GitHub they merge the PR (button, `gh pr merge`, auto-merge, or merge queue).
The pipeline never merges or enqueues.
_Avoid_: ship, land (unless you mean this)

**Default ancestry**:
The milestone's product commits and the ship commit are ancestors of the remote
default branch. Required eventually; not what completes close.
_Avoid_: merged, shipped, landed (unless you mean this)

**Landing pointer**:
The durable handle created at close that lets a human create default ancestry
later. On a GitHub remote, ship opens a pull request (base = default, head =
bound branch). Elsewhere it is the pushed bound branch.
_Avoid_: pointer (bare)

**GitHub remote**:
`origin` whose host is github.com or GitHub Enterprise Server.
_Avoid_: GitHub (bare, unless you mean the host family), github.com (unless you
mean that host only)

**Bound branch**:
The long-lived `gsd-path/<slug>` branch recorded in `STATE.branch`. Pipeline
commits live here.
_Avoid_: feature branch, milestone branch, worktree branch

**Default branch**:
The repository's remote default (usually `main`). This effort treats mutating
it as a trust boundary.
_Avoid_: main (unless you mean that specific name), production branch

**Shipped**:
The router-visible "this milestone is complete" state. True when the ship
commit validates and the landing pointer exists. The router may start the
next milestone then; it does not wait for default ancestry.
_Avoid_: archived, merged, done, integrated

**Dispatch round**:
The set of ready tasks isolated together at one recorded base SHA.
_Avoid_: wave, layer

**Task isolation**:
The checkout a coder uses for one task until task landing. A parallel
dispatch round uses a named branch distinct from the bound branch. A serial
dispatch round (one ready task) uses the bound branch itself.
_Avoid_: detached HEAD, feature branch, worktree (bare)

**Task landing**:
The orchestrator-owned commit that records one task's product on the bound
branch.
_Avoid_: integration, ship commit, cherry-pick

**Verify sidecar**:
A named throwaway checkout at a recorded revision used only for review,
inspect, or project Verify. It is never the bound branch.
_Avoid_: detached HEAD, disposable worktree (unless you mean the filesystem path)
