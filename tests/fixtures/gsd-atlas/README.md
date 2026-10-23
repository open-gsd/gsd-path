# gsd-atlas probe envelope fixtures

Captured for the daemon-side launch prep of the index panel (issue #447,
owner ruling 2026-10-18: prep only, no panel UI before the first gsd-atlas
release). These fixtures are the reader's contract: the health panel PR is
written against them.

Provenance: the 2026-10-18 probe table in issue #447, run against gsd-atlas
at d23b44c (health before build → `not_indexed` exit 2; health degraded with
`reasons: [follower]` while an agent MCP server holds the lease; health with
no other process → `writerLeaseHeld: true`; each `health` call counted as one
`atlas_status` answer in `status`). The two health fixtures and
`status-answers.json` are live captures from gsd-atlas d23b44c, with only the
repo path rewritten to `/tmp/atlas-probe/repo`. A follower has no indexer, so
its envelope carries `indexer: null` and top-level `degraded: ["follower"]`.
The status capture was taken after six `health` calls. The error envelope
follows `src/query/envelope.ts` (`gsd-atlas.error/1`, code in `diagnostics`).

Refresh these from a live run on the first released gsd-atlas version
(launch checklist step 3) before the panel PRs ship.
