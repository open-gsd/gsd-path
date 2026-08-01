# GSD Path

A disk-backed project pipeline for Codex. It turns a raw idea into shipped
code through six gated phases. Each phase writes a fixed artifact that the
next phase reads, so a fresh task can resume from `.project/` alone.

## The flow

```text
$gsd-path  (router: detects project state, then runs the next phase)
  |
  |-- 0. $gsd-path-onboard     brownfield scan + audit  -> research/evidence-codebase.md
  |                                                    research/DOCS-AUDIT.md
  |-- 1. $gsd-path-grill       interactive intent       -> intent/INTENT.md
  |-- 2. $gsd-path-research    4 evidence researchers   -> research/evidence-*.md
  |-- 3. $gsd-path-synthesize  evidence to decisions    -> research/SYNTHESIS.md
  |-- 4. $gsd-path-plan        waves and task contracts -> plan/PLAN.md + tasks/T*.md
  |-- 5. $gsd-path-build       parallel coder agents    -> code, commits, BOARD.md
  `-- 6. $gsd-path-review      wave and final gates     -> review/*.md
```

Invoke a skill by naming it in a Codex prompt, for example `$gsd-path`. The
router reports the current state and continues the pipeline. Invoke a phase
skill directly, such as `$gsd-path-plan`, when you intentionally want that
phase. A direct phase run stops at its handoff; explicitly invoke `$gsd-path`
or the named next phase to continue. Only an active router may auto-advance
through its bundled phase contracts.
All nine skills disable implicit invocation, so generic requests such as
"continue the project" do not inject this pipeline accidentally.
The router carries synchronized copies of all eight phase contracts, so an
explicit `$gsd-path` can auto-advance without relying on hidden phase skills
being present in the ordinary catalog.

With no `.project/STATE.md`, the router detects the project kind before
asking anything. Existing code or docs → brownfield: `$gsd-path-onboard` maps
the codebase and audits every Markdown doc against reality, presents ground
truth, then the grill asks only delta questions. Empty directory →
greenfield: straight to the grill. `$gsd-path-docs-audit` also runs standalone
at the safe pre-build checkpoints documented by that skill.

## Agent execution

The grill and build orchestrator run in the main task. Researchers,
synthesizer, planner, coders, and reviewers use Codex's built-in `default` and
`worker` agent types with role briefs bundled under
`skills/gsd-path/references/`. No custom-agent registration is required.

The orchestrator uses `spawn_agent` for bounded work. Every dispatch has an
explicit built-in agent type, `fork_turns: "none"`, and a deterministic task
name. Independent briefs run
in parallel up to the available child capacity; larger fan-outs run in
batches. Dependencies run in layers. A spawned agent has isolated context, so
every brief names its input paths, output path, acceptance contract, and
allowed scope. Durable context belongs in `.project/`, not chat history.

## Handoff contract

```text
.project/
  STATE.md                    pipeline owner, phase, branch, archive transaction
  intent/INTENT.md            approved intent, constraints, and vetoes
  research/
    evidence-codebase.md      brownfield ground truth (onboard)
    DOCS-AUDIT.md             doc-vs-code verdicts and remediation queue
    evidence-domain.md        domain rules and prior art
    evidence-stack.md         stack choices and tradeoffs
    evidence-pitfalls.md      risks and failure modes
    evidence-similar.md       comparable projects
    SYNTHESIS.md              fully gated decisions and planner brief
  plan/PLAN.md                waves, dependency graph, project verify
  tasks/T###-slug.md          task contract, clean base, state, exact commit
  BOARD.md                    build and escalation summary
  review/wave-N.cycleC.md     wave review verdicts
  review/final-gap-N.md       cross-wave gap verdicts
  review/FINAL.md             success-criteria audit (`met` / `not-met` / `unverifiable`)
  archive/<NNN>-<slug>/       shipped milestones, moved here at ship (read-only)
```

Shipping archives the milestone: every artifact above (except `STATE.md`)
moves into a numbered `archive/` directory with a MANIFEST.md, so the next
milestone starts clean instead of overwriting history.

## Install

Each phase skill is self-contained. Before installing, verify the generated
copies match the canonical router resources:

```bash
python3 scripts/sync_skill_resources.py --check
```

For every install—fresh or upgrade—first quit Codex and move any legacy
`ogsd*` skills and previous `gsd-path*` install to a recoverable backup. Legacy
O-GSD uses broad triggers and overlapping `.project/STATE.md` paths; a machine
can have it installed even when GSD Path itself is new.

```bash
gsd_path_codex_root="${CODEX_HOME:-$HOME/.codex}"
gsd_path_project_root="/path/to/project"
gsd_path_backup="$gsd_path_codex_root/disabled-gsd-skills-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$gsd_path_codex_root/skills" "$gsd_path_backup"

find "$gsd_path_codex_root/skills" -mindepth 1 -maxdepth 1 -type d \
  \( -name 'ogsd' -o -name 'ogsd-*' -o -name 'gsd-path' -o -name 'gsd-path-*' \) \
  -exec mv {} "$gsd_path_backup/" \;

for gsd_path_source in skills/gsd-path*; do
  cp -R "$gsd_path_source" "$gsd_path_codex_root/skills/"
done
```

For a brand-new target with neither project contract, copy them with a
fail-loud guard:

```bash
if [ -e "$gsd_path_project_root/AGENTS.md" ] || [ -e "$gsd_path_project_root/WORKFLOW.md" ]; then
  echo "project contracts already exist; review and merge them explicitly" >&2
  exit 1
fi
cp AGENTS.md WORKFLOW.md "$gsd_path_project_root/"
```

Never run that copy command for a contract upgrade. Review `diff -u` for
AGENTS.md and merge the new rules without overwriting project-specific
instructions; replace or deliberately merge WORKFLOW.md. The state contract now carries
`pipeline: gsd-path/v1`, `branch`, and crash-resumable `archive` fields; tasks
also carry `base`, `worktree`, and `task_branch`. Pre-marker state is not
auto-stamped as v1 because those values cannot be reconstructed safely.

Reload or restart Codex after copying. Then explicitly invoke `$gsd-path`.

## Repository layout

- `skills/` — the nine `$gsd-path*` skills
- `skills/gsd-path/templates/` — canonical artifact formats
- `skills/gsd-path/references/` — canonical role and dispatch contracts
- `scripts/sync_skill_resources.py` — refreshes/checks phase resources and router contracts
- `scripts/archive_milestone.py` — prepares and validates the ship transaction
- `AGENTS.md` — shared operating rules to install in the project root
- `WORKFLOW.md` — phase-by-phase SOP to install in the project root
- `LICENSE` — MIT
