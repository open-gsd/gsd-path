#!/usr/bin/env bash
# Prepare only missing or stale live-host evidence; --full prepares all hosts.
#
# Usage:
#   bash scripts/prepare_release_evidence.sh \
#     --candidate e6f48333cba4f939e27ab7d6bd20d39f0eabd412 \
#     --output-base "$HOME/evaluations/gsd-path-release-e6f4833"
#
# After preparation, run each host's live milestone from its directory, then
# assemble receipts with docs/trust-validation/evidence/releases/1.0.0/codex/release_receipt.py.
# See docs/trust-validation/HOST-MATRIX.md.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CANDIDATE="$(git -C "$ROOT" rev-parse HEAD)"
FULL=0
OUTPUT_BASE="${HOME}/evaluations/gsd-path-release"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --candidate)
      if git -C "$2" rev-parse HEAD >/dev/null 2>&1; then
        CANDIDATE="$(git -C "$2" rev-parse HEAD)"
      else
        CANDIDATE="$2"
      fi
      shift 2
      ;;
    --full)
      FULL=1
      shift
      ;;
    --output-base)
      OUTPUT_BASE="$2"
      shift 2
      ;;
    -h|--help)
      sed -n '1,12p' "$0"
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
  echo "repository must be clean before freezing a release candidate" >&2
  exit 1
fi

HEAD_SHA="$(git -C "$ROOT" rev-parse HEAD)"
if [[ "$CANDIDATE" != "$HEAD_SHA" ]]; then
  echo "candidate $CANDIDATE is not current HEAD $HEAD_SHA" >&2
  exit 1
fi

HOSTS="$(python3 -B - "$ROOT" "$FULL" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))
from check_trust_evidence import evaluation_hosts, validate_repository
hosts = json.loads((root / "scripts/skill-resources.json").read_text())["hosts"]
selected = evaluation_hosts(hosts) if sys.argv[2] == "1" else validate_repository(root, plan=True)["required_runs"]
print(" ".join(selected))
PY
)"

if [[ -z "$HOSTS" ]]; then
  echo "All required live-host evidence is valid and unchanged; no new runs needed."
  exit 0
fi

SHORT_SHA="$(git -C "$ROOT" rev-parse --short HEAD)"
BASE="${OUTPUT_BASE}-${SHORT_SHA}"
mkdir -p "$BASE"

echo "Frozen candidate: $HEAD_SHA"
echo "Output base: $BASE"
echo

for host in $HOSTS; do
  dir="${BASE}/${host}"
  if [[ -e "$dir" ]]; then
    echo "skip $host — already exists: $dir"
    continue
  fi
  echo "prepare $host -> $dir"
  python3 -B "$ROOT/tests/evaluate_host.py" prepare \
    --host "$host" \
    --directory "$dir" \
    --candidate "$ROOT"
done

cat <<EOF

Prepared evaluation harnesses under:
  $BASE

Next — for each host <H> with CLI on PATH and auth configured:

  cd $BASE/<H>
  python3 -B $ROOT/tests/evaluate_host.py run --host <H> --directory $BASE/<H>

Resume owner-gate pauses with --resume <session-id> and optional --prompt-file.

At archive prepare (before render-manifest), run release_receipt.py manifest.
After integration, run release_receipt.py receipt to write
docs/trust-validation/evidence/releases/<package-version>/<H>.md and artifacts.

Validate the full set:

  npm run verify:release

EOF
