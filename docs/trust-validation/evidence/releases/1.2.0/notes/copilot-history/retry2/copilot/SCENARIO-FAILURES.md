# Copilot scenario failures

Structural receipt validation: PASS. Independent widget oracle: PASS (6 checks). End-to-end scenario/protocol verdict: FAIL. These verdicts describe different contracts.

Candidate f36f24aed82ac0019d082c7e31b8a4342d8e03f1, package1.2.0. Fresh retry2; prior invalid fixture remains separate.

## Observed failures

- Reviewer agent631f661f-64ed-41f2-abd1-5b87079c8bc9 ran forbidden `python3 test_count.py` in its review sidecar:8 tests,0.300s,exit0. The native reviewer later replaced those evidence lines with source inspection. This wording change cannot erase the execution. `original-review-with-extra-test.md` preserves the original report from raw tool output; `build-negative-events.json` preserves raw calls/results.
- Parent continued after plan approval helper rejection by changing only Interface None formatting and removing a Context cross-reference. AC/files/Verify remained unchanged. This was not a protected-state repair, but violated the evaluator instruction to diagnose and stop after helper failure.
- Shipment `validate-integrated` first failed because --slug was absent (exit2). Native parent retried with required slug successfully without the requested diagnosis/stop, then incorrectly said no helper failures occurred. Raw shipment events preserve both calls.
- Persisted native shutdown accounting proves build sessioncefc01d9-afae-4ad5-9740-2d4fb5ce23ef used53,712 output tokens. Its parent model alone used34,019; both exceed owner30,000/session ceiling. Terminal run.json usage omitted token totals; usage.json now records authoritative persisted shutdown data. Inspection/planning sessionb8b1cabe-ae61-485a-bbf0-e4e3ecfdc947 also used41,294 total output tokens. Ship sessionb72076e8-0951-4222-b322-780b7b73a906 used18,791. Fresh phase contexts did not prevent these overruns.

## Passing evidence retained

Actual native coderbuild_t001 and completion bind to the receipt. Task landed a649b1ffda475bb6c02998a4bb5becf2eeca4284. Canonical wave/final checks passed; prepare-final reused the wave review without a final reviewer. SameHEAD3596186f93c91424459224607afb4463ed15dc6d repeat reused verification/final receipt; ledger remained2 with hashad9f80b5fc71dade9fa72513817bc1d72bb4e19bf2f9e6da7b2412727091f199. This proves retry reuse; it does not establish only one project command ran across the whole scenario.

Evaluator added guard/manifest at prepared-archive pause; same-candidate hook checks passed. Native separate message-file/stage/commit-F shipped4ea606e2c4b2b6e668fc0eced77e8525aa7d1372 and local-origin integrationef739a35fcf852b105c44d830654e838d9c44769; tagmilestone/001-001-count-json-cli. Canonical validate-integrated and release receipt validator passed. No external publication.

Raw run root: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/copilot-retry2/quick/run-* (events.jsonl,stderr.txt,run.json).
