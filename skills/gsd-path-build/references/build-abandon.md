## Milestone abandon (program flow only)

Abandon the active milestone only on an explicit user ruling — from the
review-cycle-cap escalation, a decision invalidation, or a direct request.
Require `.project/ROADMAP.md`; a single-milestone project has no abandon
path — stop and let the user decide how to restart.

1. Retire every recorded task worktree and branch with `isolation.py retire`
   after confirming ownership, recording each discarded uncommitted diff's
   exact path set and hash in the STATE.md log. Never discard work the
   recorded metadata cannot own.
2. Run the bundled `scripts/archive_milestone.py abandon --repo <absolute
   repo root> --slug <milestone slug> --reason <user ruling, verbatim>`.
   This one helper-owned transaction journals the exact request and starting
   HEAD before mutation; archives the partial artifacts without review gates;
   marks the exact ROADMAP entry `Status: abandoned` with its `Archive:` path;
   appends `- <NNN>-<slug> — abandoned: <collapsed ruling>` exactly once to
   LESSONS.md; transitions STATE to `roadmap/active` with `milestone: null`
   and `archive: null`; and creates the checkpoint with exact subject `build:
   abandon milestone <slug>` and body `Why: <collapsed ruling>`. The manifest
   `Reason:` and checkpoint `Why:` are the same normalized ruling.
3. Rerun the same command with the same slug and ruling after any interruption.
   It resumes archive moves, metadata, state transition, or checkpoint from
   the journaled starting HEAD; a changed slug, ruling, archive, branch, or
   manifest reason blocks. Success returns the archive, exact checkpoint
   commit, and `committed` or `already-complete` status. Never edit or commit
   any part of this transaction manually and never select another sequence
   number.
4. Return to the router, which routes `roadmap/active` to the roadmap
   contract in re-slice mode. The abandoned code stays on the build branch
   until the next milestone's integration, then reaches the default branch as
   inert history; the re-slice plans around it. Never revert product commits
   yourself.
