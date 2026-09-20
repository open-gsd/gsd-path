# Codex live release blocker — 1.3.0

Candidate: `45466c40e57c6cc0d7acd099e880d1644b33f5ee`. Verdict: blocked; no passing host receipt.

## Evidence

Fresh native attempt 2 used session `01a0bf47-36c1-76e2-b23d-f86ef783b40b`. First task activation and native coder both used `build_t001`; completion was listed. Task landed as `89992c26a26a591c87c0ac7fda381c9af9fc3993`, with five passing isolated CLI tests. Native cumulative output was 24,953 tokens.

Cycle 1 was rejected for missing canonical pass-evidence bullets despite recorded walkthroughs. The evaluator authorized only the pinned new-cycle recovery; a native reviewer wrote cycle 2, which passed and was committed at `bc086eb21f0ba83f372dbf825ce81bf6cca79780`. Build completion then rejected the missing canonical first cycle. No final-ready, archive, integration, external oracle or receipt validation occurred.

Raw log: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/codex-rerun/quick/run-20260920T145810991638Z/events.jsonl`

Executed command:
```sh
/bin/zsh -lc 'python3 /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/codex-rerun/plugin/tests/evaluate_codex.py activity --arm /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/codex-rerun/quick --category verification -- python3 -B /Users/jeremymcspadden/.gsd-path/runtimes/36cf1845fbc977caa9893dda7eda1ea56469b8d33e6f255f0c23251eb1f0beb6/check_handoffs.py wave --repo /Users/jeremymcspadden/.gsd-path/projects/aaf7f1238986c7499c373f93ed7affb16c1b0fe2c08c12f42fa9d0c9165a334d/a2dd3cd2f4bef57b2a91c15809fdae658b7b9c983145bab6c68592b2093c8c36/verify/wave-1-cycle-1 --review .project/review/wave-1.cycle1.md'
```

Recorded result (exit 1):
```text
handoff validation failed: wave-1.cycle1.md SC1 lacks pass evidence
```

Raw log: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/codex-rerun/quick/run-20260920T151013089411Z/events.jsonl`

Executed command:
```sh
/bin/zsh -lc 'python3 /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/codex-rerun/plugin/tests/evaluate_codex.py activity --arm /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/codex-rerun/quick --category verification -- python3 -B /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/codex-rerun/quick/repo/.agents/skills/gsd-path/scripts/dispatch_driver.py complete --repo /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/codex-rerun/quick/repo'
```

Recorded result (exit 1):
```text
{"blocked": [{"code": null, "reason": "review cycles for wave 1 are not contiguous"}], "next": "$gsd-path-forensics", "status": "blocked", "steps": [{"result": {"branch": "gsd-path/M001", "command": "ready", "current_wave": null, "head": "bc086eb21f0ba83f372dbf825ce81bf6cca79780", "ready": []}, "script": "build_state.py ready"}]}
```

## Contract conflict and collection check

Pinned `references/build-native.md` step 6 requires validating a reviewer artifact before collection. Its earlier-cycle rule says: “the only repair is a new review cycle at the current HEAD, which counts toward the cap.” The evaluator followed that route and preserved cycle 1 without edits.

Pinned `scripts/isolation.py:2279–2288` requires both primary and source worktree HEAD to equal the recorded collection base. Cycle 1 sidecar is at `97336b528103c66fe72c2ea59ede59670c278838`; primary is now `bc086eb21f0ba83f372dbf825ce81bf6cca79780`. No base satisfies both checks. A late `collect-artifact` call cannot legally retain the earlier artifact in primary, and its validation already failed. This conclusion is static contract evidence; no unsafe collection attempt was made. No documented rejected-review retention path was found in the applicable build contract.

The native completion failure ran canonical diagnosis, which reported `ok` and supplied no corrective command. The next read-only action is `$gsd-path status`. Do not copy or reconstruct cycle 1, rewrite state, reset HEAD, modify the frozen candidate, or start another fixture to hide this failure.

Preserved cycle 1 artifact: `/Users/jeremymcspadden/.gsd-path/projects/aaf7f1238986c7499c373f93ed7affb16c1b0fe2c08c12f42fa9d0c9165a334d/a2dd3cd2f4bef57b2a91c15809fdae658b7b9c983145bab6c68592b2093c8c36/verify/wave-1-cycle-1/.project/review/wave-1.cycle1.md`

SHA-256: `1b7b6f0f4267bde5334e4093bf507532663af0b4819747996bbec38828dc3e02`

Passing cycle 2: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/codex-rerun/quick/repo/.project/review/wave-1.cycle2.md`

## Separate evaluator error

The original `../codex` fixture is also preserved. It failed because the evaluator requested uppercase `build_T001`, rejected by native task-name validation. That first attempt is evaluator-contaminated and is not evidence of this candidate recovery defect. Attempt 2 began with host-valid lowercase names.
