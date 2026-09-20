# Review — wave 1, cycle 1

Wave verdict: pass
Cycle: 1
Depth: full
Reviewed HEAD: a649b1ffda475bb6c02998a4bb5becf2eeca4284
Review scope: final
Lens:
Tasks reviewed: 1

## T001 — Add --json output and input validation to count.py with real-CLI tests: pass

- ✅ 1. `python3 count.py` prints `0 widgets` and exits 0. — walkthrough in verify sidecar returned exit 0 with stdout `0 widgets\n` and empty stderr; count.py:27-39
- ✅ 2. `python3 count.py 3` prints `3 widgets` and exits 0; `python3 count.py -2` prints `-2 widgets` and exits 0. — walkthrough returned exit 0 with stdout `3 widgets\n` and `-2 widgets\n`; count.py:19-24,34-37
- ✅ 3. `python3 count.py --json` prints a JSON object with `"widgets": 0` and exits 0. — walkthrough returned exit 0 with stdout `{"widgets": 0}\n`; count.py:24,34-35
- ✅ 4. `python3 count.py --json 5` and `python3 count.py 5 --json` both print a JSON object with `"widgets": 5` and exit 0. — walkthrough returned exit 0 with stdout `{"widgets": 5}\n` for both flag orders; count.py:9-24,34-35
- ✅ 5. `python3 count.py abc` exits non-zero and prints a non-empty, human-readable message to stderr (not a Python traceback); `python3 count.py 1 2` also exits non-zero with a non-empty stderr message. — walkthrough returned exit 1 with stderr `invalid input: expected signed integer, got: abc\n` and `invalid input: unexpected argument: 2\n`, stdout empty, no traceback; count.py:16-22,28-32
- ✅ 6. `python3 test_count.py` and `python3 -m unittest test_count.py` both exit 0, and the test source invokes `count.py` only via subprocess (no `import count`), covering every case in AC1–AC5. — live `python3 test_count.py` exited 0 with `Ran 8 tests ... OK`; recorded task Verify shows `python3 -m unittest test_count.py -v` passed at the landed commit; test source uses `subprocess.run([sys.executable, str(SCRIPT), *args], ...)` and covers default, positive, negative, JSON default, both JSON flag orders, non-integer input, and extra positional input; test_count.py:13-19,21-69; .project/tasks/T001-add-json-and-validation.md:106-137
- ✅ 7. No import in `count.py` or `test_count.py` resolves to a third-party (non-stdlib) package. — imports are `json`, `sys`, `subprocess`, `unittest`, and `pathlib`; count.py:1-2; test_count.py:1-5

Warnings (non-blocking):
- none

Contract violations (blocking):
- none

## Intent coverage

### SC1 — `python3 count.py` (no arguments) prints `0 widgets` and exits 0.: pass
- ✅ `python3 count.py` (no arguments) prints `0 widgets` and exits 0. — walkthrough returned exit 0 with stdout `0 widgets\n` and empty stderr; count.py:27-39
- **Surface**: CLI
- **Check**: Ran `python3 count.py` in the verify sidecar from the repository root.
- **Observed**: Exit 0; stdout `0 widgets\n`; stderr empty.

### SC2 — `python3 count.py <signed integer>` prints `"<n> widgets"` for that integer (e.g. `3` → `3 widgets`, `-2` → `-2 widgets`) and exits 0.: pass
- ✅ `python3 count.py <signed integer>` prints `"<n> widgets"` for that integer (e.g. `3` → `3 widgets`, `-2` → `-2 widgets`) and exits 0. — walkthrough returned exit 0 with stdout `3 widgets\n` for `3` and `-2 widgets\n` for `-2`; count.py:19-24,34-37
- **Surface**: CLI
- **Check**: Ran `python3 count.py 3` and `python3 count.py -2` in the verify sidecar.
- **Observed**: Both commands exited 0; stdout was `3 widgets\n` and `-2 widgets\n`; stderr empty.

### SC3 — `python3 count.py --json` (no count argument) prints exactly a JSON object with an integer `widgets` field defaulting to `0` (e.g. `{"widgets": 0}`, exact whitespace unspecified) and exits 0.: pass
- ✅ `python3 count.py --json` (no count argument) prints exactly a JSON object with an integer `widgets` field defaulting to `0` (e.g. `{"widgets": 0}`, exact whitespace unspecified) and exits 0. — walkthrough returned exit 0 with stdout `{"widgets": 0}\n`; count.py:24,34-35
- **Surface**: CLI
- **Check**: Ran `python3 count.py --json` in the verify sidecar.
- **Observed**: Exit 0; stdout `{"widgets": 0}\n`, which parses as valid JSON with integer field `widgets: 0`; stderr empty.

### SC4 — `python3 count.py --json <n>` and `python3 count.py <n> --json` (flag before or after the optional count) both print exactly a JSON object with `widgets` set to the integer `n` and exit 0.: pass
- ✅ `python3 count.py --json <n>` and `python3 count.py <n> --json` (flag before or after the optional count) both print exactly a JSON object with `widgets` set to the integer `n` and exit 0. — walkthrough returned exit 0 with stdout `{"widgets": 5}\n` for both `--json 5` and `5 --json`; count.py:9-24,34-35
- **Surface**: CLI
- **Check**: Ran `python3 count.py --json 5` and `python3 count.py 5 --json` in the verify sidecar.
- **Observed**: Both commands exited 0; each printed `{"widgets": 5}\n`; stderr empty.

### SC5 — Invalid input — a non-integer count argument, an extra/unrecognized positional argument, or any other malformed invocation — exits non-zero and prints a useful, human-readable message to stderr (not a raw Python traceback); exact wording and stderr line count are unspecified.: pass
- ✅ Invalid input — a non-integer count argument, an extra/unrecognized positional argument, or any other malformed invocation — exits non-zero and prints a useful, human-readable message to stderr (not a raw Python traceback); exact wording and stderr line count are unspecified. — walkthrough returned exit 1 with stderr `invalid input: expected signed integer, got: abc\n` for `abc` and `invalid input: unexpected argument: 2\n` for `1 2`; stdout empty and no traceback; count.py:16-22,28-32
- **Surface**: CLI
- **Check**: Ran `python3 count.py abc` and `python3 count.py 1 2` in the verify sidecar.
- **Observed**: Both commands exited non-zero; stderr was non-empty and human-readable; stdout was empty; no raw Python traceback appeared.

### SC6 — A real-CLI automated test suite (invoking `count.py` as a subprocess, not importing internals) exists and passes, covering: default count, a positive and a negative signed integer, `--json` default, `--json` with a count in both flag positions, and at least one invalid-input case asserting a non-zero exit code and non-empty stderr.: pass
- ✅ A real-CLI automated test suite (invoking `count.py` as a subprocess, not importing internals) exists and passes, covering: default count, a positive and a negative signed integer, `--json` default, `--json` with a count in both flag positions, and at least one invalid-input case asserting a non-zero exit code and non-empty stderr. — recorded task Verify shows `python3 -m unittest test_count.py -v` passed with 8 tests at the landed commit; `test_count.py` invokes `count.py` only via `subprocess.run(...)` and covers all listed cases; live `python3 test_count.py` also exited 0 in the verify sidecar; test_count.py:13-19,21-69; .project/tasks/T001-add-json-and-validation.md:106-137
- **Surface**: CLI
- **Check**: Read T001's recorded Verify log entry, inspected `test_count.py`, and ran `python3 test_count.py` because the recorded output plus diff did not settle the direct-invocation half of AC6/SC6.
- **Observed**: The task log records `python3 -m unittest test_count.py -v` passing with 8 tests; `test_count.py` uses subprocess-only CLI invocation and covers AC1-AC5 cases; live `python3 test_count.py` exited 0 with `Ran 8 tests ... OK`.

### SC7 — No new third-party dependencies are introduced; the CLI and its tests run with the Python standard library only.: pass
- ✅ No new third-party dependencies are introduced; the CLI and its tests run with the Python standard library only. — `count.py` imports only `json` and `sys`; `test_count.py` imports only `json`, `subprocess`, `sys`, `unittest`, and `pathlib`; live CLI walkthrough and direct test-file execution succeeded under `python3` with no dependency installation; count.py:1-2; test_count.py:1-5
- **Surface**: CLI
- **Check**: Inspected import statements in `count.py` and `test_count.py`, then ran the CLI walkthrough and `python3 test_count.py` in the verify sidecar.
- **Observed**: Only standard-library modules are imported, and the CLI plus tests ran successfully without adding or installing any dependency.

## Summary for orchestrator

- blocked findings: none
- repeat offenders: none
- warnings worth a human eye: none