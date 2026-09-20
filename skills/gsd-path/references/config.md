# Path settings

`$path config` (or `/path config`) is independent of phase routing. Resolve
`scripts/path_config.py` from the selected project runtime; without a declaration,
use the router skill's bundled helper (`gsd-path` or its `path` alias). Copies in
other phase skills support internal imports; they are not config CLI entry points.
An older selected runtime without this helper requires
an explicit runtime upgrade; never substitute it.

Run `python3 -B <absolute-helper> show --repo <absolute-root>` for an initialized
project. Without STATE.md use `show --scope user`. Show returned values, sources,
recorded review panel, current milestone shipping mode, and lock reasons.
Do not initialize state, bind a branch, dispatch a phase, approve, or commit.

For bare `config`, show settings and ask which scope and setting to change.
Offer user defaults and, when initialized, project settings. For explicit
arguments, pass the action to the same helper:

```text
show --scope user
validate --scope project --repo <absolute-root>
set integration pull-request --scope project --repo <absolute-root>
set review_panel detected --scope user
set models.roles.coder.model inherit --scope project --repo <absolute-root>
set models.hosts.codex.plan.effort high --scope project --repo <absolute-root>
reset models.roles.coder.model --scope project --repo <absolute-root>
```

Write only the user's explicit selection. Use exact host-advertised model/effort
values; unavailable values block dispatch. `inherit` clears a control override;
`reset` removes this scope's setting and exposes defaults. Project shipping needs
an explicit mode; milestone overrides use configure-integration. Report the
returned source and when it applies. Errors stop the request; never repair by hand.

## Ownership and timing

- User defaults: `~/.gsd-path/config.json`. Shipping affects newly initialized
  projects. Model choices affect new assignments; recorded assignments stay pinned.
- Project shipping: STATE.md, written by configure-integration. It locks when
  build starts. Project-default changes preserve explicit milestone overrides.
- Project models: `.project/model-policy.json`. Precedence is user common roles,
  user host roles, project common roles, project host roles, then task overrides,
  independently for model and effort. Existing effort hints remain.
- Future review preference: `.project/config.json`, then user default, then off.
  Define presents it in the approval draft when no CHARTER or explicit user choice
  applies. Approved INTENT/PLAN values remain authoritative; quick lane keeps off.
- Project writes require the bound branch; ship and shipped projects are locked.
  Config cannot advance phases or edit archives.

Config leaves project edits for the pipeline's next normal metadata checkpoint.
In-flight task landings preserve these edits. Project preferences persist outside
milestone archives so later milestones keep them.

Dashboard Path settings calls this same helper for watched projects, using their
selected runtime. Background monitoring stays read-only. Existing watched-folder
and appearance controls stay separate. No background writes or automatic pipeline
execution are authorized by this settings exception.
