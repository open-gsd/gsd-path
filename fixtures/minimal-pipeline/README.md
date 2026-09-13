# Minimal pipeline fixture

A tiny brownfield repository with an owned `.project/STATE.md` in the **define**
phase. Use it to practice router handoffs, docs-audit, or local skill installs
without initializing a milestone from scratch.

## Layout

```
minimal-pipeline/
├── README.md           # this file
├── count.py            # trivial CLI (3 widgets)
├── README.fixture.md   # intentional doc drift for docs-audit exercises
└── .project/
    ├── STATE.md        # pipeline: gsd-path/v2, phase: define
    └── research/       # empty — docs-audit writes DOCS-AUDIT.md here
```

## Bootstrap into a throwaway repo

```bash
REPO=/tmp/gsd-path-fixture
rm -rf "$REPO"
mkdir -p "$REPO"
cp -R fixtures/minimal-pipeline/. "$REPO/"
mv "$REPO/README.fixture.md" "$REPO/README.md"
cd "$REPO"
git init -b main
git config user.email you@example.com
git config user.name "Fixture User"
git add -A
git commit -m "minimal pipeline fixture"
```

Install GSD Path locally (from the gsd-path checkout):

```bash
node /path/to/gsd-path/scripts/install.mjs --claude --project "$REPO"
```

Then invoke `/gsd-path-docs-audit` or the router from your host.

## Disk contract reference

For the complete offline milestone path (research → ship), see
`tests/test_full_cycle.py`. For live host smoke, see `tests/dogfood.py`.
