# Initial branch binding: Git guarantees and application policy

Date: 2026-09-04

Scope: official Git documentation plus local implementation findings supplied by the main research thread. No product files or evaluation fixture changed.

## Local evidence

- The [router](../../skills/gsd-path/SKILL.md#L111) writes state before binding. [Initial binding](../../scripts/pipeline_git.py#L501) rejects all dirty status, then requires HEAD to equal the fetched main SHA. Its already-bound path supports an interruption before state transition.
- The [full-cycle test](../../tests/test_full_cycle.py#L358) commits state before binding, so it does not exercise the router's real sequence.
- [Initialization](../../scripts/detect_project.py#L1434) uses an anchored secure create, but persists no creation receipt or hash. Validation therefore cannot prove creator identity.
- [State validation](../../scripts/pipeline_state.py#L468) is reusable. [Initial binding transition checks](../../scripts/pipeline_state.py#L1594) preserve phase/status and require the exact initial-binding event; the transition itself uses locking and expected-state checks.

## Findings

Git does not require a clean working tree or index to switch branches. It refuses a normal switch that would lose local changes. `git switch -c <branch> <start-point>` combines creation and switching: a failed switch does not create the branch. This guarantee concerns the Git operation; it does not include validating or writing an application state file. Do not use force, discard, merge, or ignore-other-worktrees options to resolve this initialization problem. [Git switch documentation](https://git-scm.com/docs/git-switch)

For an exact path exception, use machine-parsed `git --no-optional-locks status --porcelain=v1 -z --untracked-files=all`. Porcelain v1 is stable, uses repository-relative paths, and NUL output avoids filename quoting ambiguity. `all` exposes individual files inside untracked directories; the normal mode can hide them behind a directory entry. Inspect both index and working-tree columns. Ignored files are absent unless requested. Decide ignored-file policy separately; a normal status result is not proof that every on-disk file is tracked or absent. The optional-locks flag avoids status writing an index refresh during research. [Git status documentation](https://git-scm.com/docs/git-status)

The index holds a stored tree version; the working tree holds actual files and local edits. A file having valid contents on disk does not prove that the same contents are staged. If the exception is for newly initialized, unstaged state, admitting a staged addition or a tracked modification is a different policy and should not happen through a filename-only allowlist. [Git glossary](https://git-scm.com/docs/gitglossary)

Git reference transactions lock and verify reference updates. They do not include an arbitrary `.project/STATE.md` write. Even reference transactions document that a concurrent reader can observe a subset of changed references. Thus neither `switch -c` nor `update-ref` establishes a fully atomic application initialization transaction. [Git update-ref documentation](https://git-scm.com/docs/git-update-ref)

## Recommendation and tradeoffs

For the demonstrated initialize-then-bind deadlock, prefer a narrow initial-state admission over redesigning the whole initialization lifecycle, provided the product accepts **validated initial state** as the admission contract. Preserve the existing exact-base, branch collision, and worktree checks. Admit only the exact untracked regular state file, with a clean index, no other reported changes, and no linked directory/file substitution. Use the existing deterministic validator and require initial `inspect` or `define` phase, active status, and null branch, milestone, and archive. Recheck the file contents and binding result before recording success. These are proposed application rules, not guarantees supplied by Git.

Do not describe this as proving “helper-created.” A valid marker, expected fields, or a content hash computed only at bind time establishes current content, not who created it. If provenance is required, initialization must produce a durable receipt tied to the worktree, starting SHA, and state content, and binding must consume that receipt. That expands the repair into an application transaction with explicit interruption and recovery states.

| Option | Benefit | Cost and limitation |
|---|---|---|
| Exact validated initial-state admission | Repairs the known deadlock within the existing flow; keeps general cleanliness strict | Content validation is not creation provenance; interrupted switch/state persistence still needs existing recovery |
| Journaled initialize-and-bind operation | Can prove which state the operation created and make interruptions explicitly recoverable | Adds ownership, journal lifecycle, recovery, compatibility, and failure-injection work; Git alone does not make it atomic |

Both approaches have a check/use gap when another process can write to the repository between inspection and mutation. A journal improves recovery; it does not prevent unrelated writers. Revalidation detects some races but is not an exclusive repository lock. Do not claim race freedom without a defined coordination contract.

The decisive acceptance tests are: the actual initialize → bind → transition chain passes without an intervening commit; any additional dirty path fails; malformed or noninitial state fails; wrong SHA and collisions fail; and interruption between binding and transition resumes without adopting unrelated state or a colliding branch. Reuse the existing already-bound recovery path if these tests prove it. A live rerun must then establish whether initialization was the remaining delivery blocker. Static Git research cannot prove that milestone result.
