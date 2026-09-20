# Antigravity receipt blocked

The native fixture completed local shipment and integration, but the evaluator supplied the wrong Verify branch name to the manifest assembler. The archived manifest says `gsd-path-verify/task-t001-verify`; native isolate-verify and retirement output prove `gsd-path-verify/verify-T001`. See [manifest-mismatch.json](manifest-mismatch.json). No passing host receipt is issued. The archive is unchanged.

Other negative results remain preserved: inspection and planning exceeded the 30,000 output-token session limit (44,423 and 58,718). The native parent also continued after dirty-sidecar retirement failed and manually restored/deleted its verification files before retirement. Quick-wave final reuse failed on Surface alignment; the required native final review then passed. Later same-HEAD reuse passed. These are not an all-pass scenario.

The original failed attempt remains at `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/antigravity`. The retry remains at `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/antigravity-retry2`. No retry or archive rewrite was performed after discovering the mismatch.
