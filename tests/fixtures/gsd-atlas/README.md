# gsd-atlas probe envelope fixtures

Captured for the daemon-side launch prep of the index panel (issue #447,
owner ruling 2026-10-18: prep only, no panel UI before the first gsd-atlas
release). These fixtures are the reader's contract: the health panel PR is
written against them.

Provenance: the 2026-10-18 probe table in issue #447, run against gsd-atlas
at d23b44c (health before build → `not_indexed` exit 2; health degraded with
`reasons: [follower]` while an agent MCP server holds the lease; health with
no other process → `writerLeaseHeld: true`; three `health` calls counted as
three `atlas_status` answers in `status`). Envelope layout and field shapes taken from the gsd-atlas source at the
same commit: `src/query/envelope.ts` (error envelopes carry
`gsd-atlas.error/1` with the code in `diagnostics`), `src/query/status.ts`
(StatusSnapshot: `worktrees[].worktree`, `store.sizeBytes`/
`schemaVersion`/`rebuilt`, numeric or null `indexer.lastIndexedAt`,
`tiers[].module` with grammar/precise/platform flags), and
`src/fact-store/location.ts` (store location rules), cross-checked against
`scripts/cli-e2e.test.ts` and `docs/reference/cli.md`.

Refresh these from a live run on the first released gsd-atlas version
(launch checklist step 3) before the panel PRs ship.
