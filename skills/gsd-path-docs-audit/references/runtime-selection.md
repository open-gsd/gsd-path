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
isolation, integration, archive, recovery, and guard helpers. This rule overrides
references to bundled copies of those helpers. Other skill helpers, templates,
and role briefs remain in the installed skill bundle. Pass `-B` to Python helper
invocations so execution does not create bytecode in the runtime store.

With no declaration, retain the legacy helper lookup. An existing
`.gsd-path/runtime/` requires the explicit `--runtime-migrate --project PATH`
operation before adopting external storage; review the resulting Git diff.
