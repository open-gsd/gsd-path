# Trust validation

Validation workstream for every host declared in the installer manifest.
Every release runs automated checks. Live milestone receipts are required
for hosts affected by changes since the previous reachable release tag.
Shared workflow changes require all hosts; documentation, release tooling,
tests, and daemon-only changes do not require new host runs. An affected host
remains release-blocking until its current versioned receipt passes validation.

**Start here:** [TRUST-VALIDATION-SPEC.md](TRUST-VALIDATION-SPEC.md)  
**Manual runs:** [TRUST-EVIDENCE.md](TRUST-EVIDENCE.md)  
**Tracking issue:** [GitHub issue #3](https://github.com/open-gsd/gsd-path/issues/3)

| File | Purpose |
|------|---------|
| [FEATURE-EVALUATION.md](FEATURE-EVALUATION.md) | Longer Codex scenarios, lookahead checkpoints, product oracles and separate native evidence |
| [full-run-4295d75.md](full-run-4295d75.md) | Quick-lane evaluation at candidate 4295d75, replay evidence, and native guard recipe |
| [HOST-MATRIX.md](HOST-MATRIX.md) | Current all-host posture and evidence status |
| [LIVE-EVIDENCE-TEMPLATE.md](LIVE-EVIDENCE-TEMPLATE.md) | Required full milestone receipt contract |
| [automated-test-inventory.md](automated-test-inventory.md) | Test suites and CI gap |
| [doc-vs-code-gaps.md](doc-vs-code-gaps.md) | Documentation vs code catalog |
| [evidence-mapping.md](evidence-mapping.md) | Criteria × automation map |
| [manual-dogfood-evidence-bar.md](manual-dogfood-evidence-bar.md) | Historical three-host smoke checklist |
