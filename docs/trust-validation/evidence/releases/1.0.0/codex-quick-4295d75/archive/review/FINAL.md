# Final Review — reused full wave

Reviewed HEAD: 7d4f9bca1fc71da6a8ed5076b5b1bfdb17ee0031
Overall verdict: pass
Source review: .project/review/wave-1.cycle1.md
Source commit: 7ccca35502a16c305ef208ca9702477e824e2b63

## Success criteria

### SC1 — Running `python3 count.py` prints exactly `0 widgets` followed by a newline. A signed integer argument prints that integer count followed by ` widgets` and a newline, including zero, positive, and negative values.

- **Verdict**: met
- **Check**: `python3 -B count.py`; `python3 -B count.py 0`; `python3 -B count.py 5`; `python3 -B count.py +5`; `python3 -B count.py -3`. Performed the corresponding PLAN Surface contract walkthrough in the isolated reconstruction.
- **Observed**: All five commands exited 0 with empty stderr. Omitted and zero counts printed zero, positive and explicitly positive counts printed five, and the negative count printed minus three, each in the exact required text format. Exact command results follow; JSON escaping preserves newlines.
- **Reference**: .project/review/wave-1.cycle1.md — SC1
- **Finding**: none
- **Fix direction**: none
- **Surface**: count.py CLI

### SC2 — `--json` alone, before a signed integer count, or after that count prints exactly one JSON object with only the `widgets` key and an integer value equal to the count; omitted count defaults to zero. Successful runs exit zero and emit no stderr.

- **Verdict**: met
- **Check**: `python3 -B count.py --json`; `python3 -B count.py --json -3`; `python3 -B count.py -3 --json`; `python3 -B count.py --json +5`; `python3 -B count.py +5 --json`. Performed the corresponding PLAN Surface contract walkthrough in the isolated reconstruction.
- **Observed**: All five commands exited 0 with empty stderr and exactly one JSON object. The only key was widgets; its value was integer zero for omitted count and the matching signed integer for each flag position. Exact command results follow; JSON escaping preserves newlines.
- **Reference**: .project/review/wave-1.cycle1.md — SC2
- **Finding**: none
- **Fix direction**: none
- **Surface**: count.py CLI

### SC3 — Invalid input fails with a nonzero exit and a useful diagnostic on stderr, without success output or an unhandled traceback. Non-integer counts, unknown options, and extra positional arguments are invalid.

- **Verdict**: met
- **Check**: `python3 -B count.py abc`; `python3 -B count.py 1.5`; `python3 -B count.py --unknown`; `python3 -B count.py 1 2`; `python3 -B count.py --json abc`; `python3 -B count.py abc --json`. Performed the corresponding PLAN Surface contract walkthrough in the isolated reconstruction.
- **Observed**: All six commands exited 2 with empty stdout and useful stderr identifying the invalid value or unrecognized argument. No traceback appeared, including invalid text with the JSON flag before and after it. Exact command results follow; JSON escaping preserves newlines.
- **Reference**: .project/review/wave-1.cycle1.md — SC3
- **Finding**: none
- **Fix direction**: none
- **Surface**: count.py CLI

### SC4 — Standard-library real-CLI tests invoke count.py as a subprocess and check exit status, stdout, stderr, JSON shape and integer type, default count, signed counts, both flag placements, and invalid input. Tests must detect missing requested behavior.

- **Verdict**: met
- **Check**: none
- **Observed**: Recorded isolated Verify passes. test_count.py:9 invokes the real script; test_count.py:16, test_count.py:20, test_count.py:29, test_count.py:40, and test_count.py:46 assert the required observable contracts. The task Log records the pre-implementation JSON-default test exiting 1 with ValueError on --json. Its unchanged success assertion detects that missing behavior; imports are standard library only. JSON parsing rejects trailing objects, exact key-set and type assertions reject extra keys and booleans, and invalid-input assertions require nonzero status, empty stdout, useful stderr, and no traceback. No tests were disabled or deleted.
- **Reference**: .project/review/wave-1.cycle1.md — SC4
- **Finding**: none
- **Fix direction**: none
