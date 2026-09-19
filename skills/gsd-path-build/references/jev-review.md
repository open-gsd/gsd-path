# Optional Jev evidence screening

Jev screens selected criterion/evidence pairs for a wave or final reviewer.
It is disabled by default. Normal Path review needs no account, API key, SDK,
or network access. This helper uses Python's standard library.

## Enable or disable

Set these environment variables in the session that launches the reviewing
agent; child agents must inherit them to use Jev:

| Variable | Value |
| --- | --- |
| `GSD_PATH_JEV` | Exactly `1` enables screening. Unset it to disable. |
| `TYPESAFE_API_KEY` | Your TypeSafe API key, supplied through the environment. |
| `GSD_PATH_JEV_TIMEOUT_SECONDS` | Positive finite seconds chosen by the owner for the HTTP socket timeout. There is no default. |

Enabling this option permits the selected criterion and evidence text to be
sent to TypeSafe's hosted API. Supply only material authorized for that service.
Do not include credentials, environment dumps, or unrelated repository content.
Having a key alone does not enable Jev. Do not put keys in commands or artifacts.

## Reviewer procedure

1. Use only still-uncovered criteria from the assigned wave/final review and
   the corresponding evidence already available in the supplied verify sidecar.
   Keep existing rules for isolated evidence, command reuse, and provenance.
2. Pass JSON through stdin to `python3 -B <absolute skill scripts/jev_review.py>`
   from that sidecar. Resolve the helper as `../scripts/jev_review.py` relative
   to this reference directory. Do not create another project report. The input
   has exactly this shape; replace the illustrative revision and contents:

   ```json
   {
     "reviewed_head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
     "items": [
       {
         "id": "T001-AC1",
         "criterion": "Reject an empty name.",
         "evidence": "Recorded isolated Verify: test_empty_name passed."
       }
     ]
   }
   ```

   Use the full review SHA supplied by the orchestrator, unique nonempty item
   IDs, verbatim criterion text, and selected evidence text. Empty evidence is
   allowed. The SHA is caller-supplied context; the helper does not prove Git
   ancestry or that the text actually came from that revision.
3. Read the JSON status. `disabled` means ordinary review. `unavailable` means
   ordinary review with the explicit reason recorded in the assigned artifact.
   Neither is a failed criterion. The helper exits zero for these optional
   outcomes and makes no automatic retries. Correct invalid input/configuration
   before an explicit retry; keep a service failure visible and continue review.
4. For `ok`, inspect per-item `supported`, `partial`, `unsupported`, or `unclear`
   answers, their probabilities, and confidence. Independently examine suggested
   gaps under the existing rubric. A Jev answer is neither executable evidence
   nor an independent review verdict. It cannot satisfy or waive a criterion,
   change a gate, select a route, or authorize publication.
5. Keep the advisory JSON receipt in the assigned review artifact's notes or
   evidence prose, outside fixed-format verdict fields. An `ok` receipt includes
   the supplied revision, SHA-256 of the exact canonical request, versioned model,
   item IDs and answers, and token usage. An `unavailable` receipt includes the
   reason and, only after request construction, the revision and request hash;
   it has no model, answers, or usage. A `disabled` receipt contains only the
   status and advisory marker. Retain the selected input with that evidence if it
   is not already reconstructible from cited sources. Keep all canonical verdicts and template
   structure unchanged. Reuse the recorded advisory when its exact request and
   review revision remain unchanged; skip screening for a reused proven review.

## Service behavior

The helper calls only `https://api.typesafe.ai/v1/systemone` with the documented
version `jev-1.13.0`. It does not follow redirects, echo provider error bodies,
write files, or install packages. Missing keys/timeouts, HTTP and network errors,
and invalid input/responses return `unavailable`. There is no confidence cutoff:
the existing reviewer owns acceptance. Real model accuracy and savings must be
evaluated on chosen evidence before relying on this advisory signal.

Sources: [HTTP API](https://docs.typesafe.ai/api),
[models](https://docs.typesafe.ai/models),
[confidence](https://docs.typesafe.ai/confidence).
