# Claude Fable review

I'm reviewing the supplied sources and diff only, with no tools and no test execution.

**Verdict: approve with one small code fix.** The helper honors the contract: opt-in is exact, no defaults or retries are invented, the timeout is owner-supplied and validated as positive finite, redirects never carry the credential, error bodies are never echoed, only the supplied state plus fixed instructions go out, and the receipt is always marked advisory. The tests exercise the real CLI and transport at a local HTTP boundary and give meaningful evidence for the opt-in, validation, redirect, and no-write claims.

**Proven defect**

- `scripts/jev_review.py:126` (also `:110`). A deeply nested JSON response, for example a body of one hundred thousand `[` characters, makes the C JSON decoder raise `RecursionError`. That is not a `ValueError`, so it escapes the handler, prints a traceback, and exits nonzero with no receipt. Contract broken: an invalid service must yield an explicit unavailable receipt while review continues. The same applies to caller-supplied nested stdin at line 110. Smallest fix is to add `RecursionError` to both except tuples:

  ```python
  except (ValueError, UnicodeError, RecursionError):
  ```

  Add a test variant with `b"[" * 100000` to the invalid-response list so sabotage would catch it.

**Speculative concerns, not defects**

- **Live response contract is unverified.** `scripts/jev_review.py:68` requires the response `model` to equal `jev-1.13.0` exactly, and lines 71 to 92 assume the `answers`, `probabilities`, `confidence`, and `usage` shapes. If the service returns a resolved model string or a different envelope, every enabled run yields `invalid_response`. This is a transport contract, not model quality, so one owner-run live smoke test before relying on it is the right closure.
- **Proxy and TLS env inheritance is undocumented.** `build_opener` picks up `https_proxy` and the default SSL context honors `SSL_CERT_FILE` and `SSL_CERT_DIR`. The reference claims the helper calls only the TypeSafe URL, which is true end to end over TLS but the connection may go through a configured proxy. Add one sentence to `skills/gsd-path/references/jev-review.md` under Service behavior.
- **Test robustness.** `tests/test_jev_review.py:78` inherits the host environment, so an `http_proxy` without `no_proxy` for localhost would break every test. Pop the proxy variables or set `no_proxy=127.0.0.1` in `process_env`. The timeout test at line 167 also has a small window where the handler thread may not have appended the request before the assertion runs.
- **Role wording.** `skills/gsd-path/references/reviewer.md:35` says "wave and final reviewers", while Skeptic and Wave panel modes also load wave evidence rules. If those modes should not screen, say "in Wave and Final modes" to remove the ambiguity.

**Test gaps worth one variant each**

- Timeout values `inf` and negative numbers.
- Whitespace-only `id`, empty `criterion`, uppercase SHA, and an extra top-level key.
- A response whose `choice` is not the maximum probability, and negative or boolean `usage` values.

**Distribution check**

The manifest adds three script targets and two reference list entries. That is consistent with one source skill plus two generated bundles, and the test covers all four helper copies including the alias. No finding.
