#!/usr/bin/env bash
# Quality gate — run before every commit.
#
#   scripts/check.sh          backend tests + coverage threshold, frontend lint + build
#
# Every step runs even if an earlier one fails, so one run shows all problems.
# Exit code is non-zero if any step failed.

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if command -v python >/dev/null 2>&1; then PY=python; else PY=python3; fi

for arg in "$@"; do
  case "$arg" in
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "check.sh: unknown option '$arg'" >&2; exit 2 ;;
  esac
done

failed=()

step() {
  local name="$1"; shift
  printf '\n== %s\n' "$name"
  if "$@"; then
    echo "-- ok: $name"
  else
    echo "-- FAILED: $name"
    failed+=("$name")
  fi
}

backend_tests() {
  cd "$ROOT/backend" && "$PY" -m coverage run -m unittest discover tests 2>&1 | tail -4
  return "${PIPESTATUS[0]}"
}

# `fail_under` in backend/.coveragerc makes this step fail below the threshold.
backend_coverage() {
  cd "$ROOT/backend" && "$PY" -m coverage report --skip-covered
}

frontend_lint() {
  cd "$ROOT/frontend" && npm run --silent lint
}

frontend_build() {
  cd "$ROOT/frontend" && npm run --silent build 2>&1 | tail -4
  return "${PIPESTATUS[0]}"
}

step "backend: unit + integration tests" backend_tests
step "backend: coverage threshold" backend_coverage
step "frontend: lint" frontend_lint
step "frontend: production build" frontend_build

echo
if [ "${#failed[@]}" -eq 0 ]; then
  echo "GATE: GREEN"
  exit 0
fi
echo "GATE: RED — failed steps:"
printf '  - %s\n' "${failed[@]}"
exit 1
