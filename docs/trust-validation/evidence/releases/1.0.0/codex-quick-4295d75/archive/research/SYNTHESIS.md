# Synthesis — Widget counter CLI

## Settled

- Quick lane, one full wave, review panel off, finding skeptics off; research and decide are skipped. Source: INTENT.md Lane, Review panel, Finding skeptics, and Constraints; owner approval of the unchanged intent on 2026-09-06.
- Preserve default zero and signed integer text output; add JSON in both flag positions and useful invalid-input failures. Source: INTENT.md SC1–SC3; evidence-codebase.md records present behavior and missing JSON handling.
- Use standard-library real-CLI tests and no new dependencies. Source: INTENT.md SC4 and Constraints; evidence-codebase.md records no existing product tests and Python 3.9.6.
- Use the pinned bundles, native children, canonical helpers, measured shell wrapper, local origin only, and named capture stops. Do not change installed skills or read evaluator tests. Source: INTENT.md Constraints and Scope out.
- Native guard evidence requires actual host enforcement in the evaluator-owned fixture; unavailable enforcement remains unverifiable. Source: INTENT.md evaluation sequence step 5.

## For the planner

One runnable slice: count.py plus test_count.py. All SCs belong to T001. The one full-wave review must include explicit final scope and actual CLI walkthrough observations; canonical prepare-final owns project verification and reuse classification.
