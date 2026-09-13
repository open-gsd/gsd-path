#!/usr/bin/env bash
# Verify toolchain prerequisites for the GSD Path test harness.
# Exit 0 when required tools meet minimum versions; nonzero with a clear message otherwise.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "check-test-prereqs: $*" >&2
  exit 1
}

require_cmd() {
  local name="$1"
  command -v "$name" >/dev/null 2>&1 || fail "missing required command: $name"
}

version_ge() {
  # usage: version_ge 18.17.0 18.17
  local IFS=.
  local -a current=($1) required=($2)
  local i
  for i in 0 1 2; do
    local c=${current[$i]:-0}
    local r=${required[$i]:-0}
    if ((10#$c > 10#$r)); then
      return 0
    fi
    if ((10#$c < 10#$r)); then
      return 1
    fi
  done
  return 0
}

echo "GSD Path test prerequisites"
echo "  repo: $ROOT"
echo

require_cmd node
require_cmd npm
require_cmd python3
require_cmd git

NODE_VERSION="$(node -p "process.versions.node")"
PY_VERSION="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
GIT_VERSION="$(git --version | awk '{print $3}')"

echo "  node:    $NODE_VERSION (required >= 18.17)"
echo "  python3: $PY_VERSION (required >= 3.9; CI uses 3.12)"
echo "  git:     $GIT_VERSION (required; 2.30+ recommended for worktree tests)"
echo

version_ge "$NODE_VERSION" "18.17" || fail "node $NODE_VERSION is below 18.17"

PY_MINOR="$(python3 -c 'import sys; print(sys.version_info[:2] >= (3, 9))')"
[[ "$PY_MINOR" == "True" ]] || fail "python3 must be 3.9 or newer"

if [[ ! -f package-lock.json ]]; then
  fail "package-lock.json is missing; run npm install from a release checkout"
fi

if [[ -f package-lock.json ]] && ! node -e "const p=require('./package.json'); process.exit(Object.keys(p.dependencies||{}).length?0:1)" 2>/dev/null; then
  if [[ ! -d node_modules ]]; then
    echo "  note: node_modules/ is absent — run 'make install' or 'npm ci' before tests"
  fi
fi

if ! git config user.email >/dev/null 2>&1 || ! git config user.name >/dev/null 2>&1; then
  echo "  note: git user.name/user.email are unset; many tests set these in temp repos,"
  echo "        but configuring them globally avoids surprises in manual git work."
fi

echo
echo "Required prerequisites satisfied."
