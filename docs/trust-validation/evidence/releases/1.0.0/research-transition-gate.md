# Research transition gate

The state helper now validates research artifacts before writing research/done
or advancing from research to decide. A rejected handoff leaves STATE.md bytes
unchanged, including its log. This applies to both the active and lookahead tracks.
The standalone research gate retains its research/active requirement.

Implementation: `scripts/pipeline_state.py` calls the shared artifact validator
in `scripts/check_handoffs.py` while holding the state lock, after expected-state
and transition checks and before the atomic state write. Artifact files are not
locked by this operation. Evidence is checked again on entry into decide.

`scripts/skill-resources.json` adds the validator to the define, inspect, and
docs-audit bundles that already carry the state helper. Generated copies were
synced and checked: 184 resources, no sync warnings. The CLI regression exercises
the canonical helper and every bundled copy, testing invalid and valid evidence
on both transitions and both tracks. Simplification review retained a single
artifact validator and the existing standalone state gate.

## Executable proof

Test file: `tests/test_handoffs.py`.

RED, GREEN, and sabotage regression command:

```sh
python3 -B -m unittest tests.test_handoffs.HandoffValidationTests.test_research_transition_validates_evidence_before_writing_state
```

- RED: before the fix, all four canonical cases returned success and changed
  state despite mismatched `Questions assigned` evidence.
- GREEN: after the fix, invalid evidence is rejected without a state write;
  restored valid evidence advances successfully. All bundled copies also pass.
- Sabotage: temporarily replaced the research transition guard with `False`;
  the four canonical cases failed because invalid transitions succeeded. Restored
  the source and reran the regression successfully.

Compatibility command:

```sh
python3 -B -m unittest tests.test_handoffs tests.test_pipeline_state tests.test_full_cycle
```

Result: 164 tests passed, including the full-cycle test.

The previously blocked live fixture was preserved. This change prevents the
observed transition bypass; it does not establish a completed live milestone.
