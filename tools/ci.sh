#!/bin/sh
# Every check of .github/workflows/ci.yml, run on this machine. GitHub runs that workflow weekly only, for its
# minutes; this is what runs before a merge. Keep the two in step: a check added there is added here.
# Usage: sh tools/ci.sh [check] [python] [typescript]   (all three by default)
#   PYTHONS="3.10 3.14" NODES="20 24" narrow the matrices (default: every version CI runs).
set -eu
cd "$(dirname "$0")/.."
PYTHONS=${PYTHONS:-3.10 3.11 3.12 3.13 3.14}
NODES=${NODES:-20 22 24}
JOBS=${*:-check python typescript}
GROUPS_ALL="--group dev --group test --group frameworks --group bedrock"
GROUPS_PY="--no-default-groups --group test --group frameworks --group bedrock"
work=$(mktemp -d)
trap 'rm -r "$work"' EXIT

job_check() {
  uv sync --locked $GROUPS_ALL
  uv run --locked python -m unittest discover -s tests -t .
  uv run --locked python tests/acceptance/run.py
  uv run --locked python -m unittest tests.acceptance.test_controls
  uv run --locked python -m unittest tests.acceptance.test_docs
  uv run --locked zizmor --min-severity low .github
  gitleaks git --redact --exit-code 1 .
  git init -q "$work/planted" && echo 'made_up = "AKIA''IOSFODNN7EXAMPLA"' > "$work/planted/key.py"
  git -C "$work/planted" add key.py && git -C "$work/planted" -c user.name=ci -c user.email=ci@example.invalid commit -qm planted
  if gitleaks git --exit-code 1 "$work/planted" >/dev/null 2>&1; then echo "gitleaks missed a key planted in a commit"; exit 1; fi
}

job_python() {
  for v in $PYTHONS; do
    echo "== Python $v"
    UV_PROJECT_ENVIRONMENT="$work/venv-$v" uv sync --locked $GROUPS_PY --python "$v"
    UV_PROJECT_ENVIRONMENT="$work/venv-$v" uv run --locked $GROUPS_PY python -m unittest \
      tests.test_logic tests.test_transport tests.test_promises tests.test_langchain tests.test_pydantic_ai tests.test_bedrock
    UV_PROJECT_ENVIRONMENT="$work/venv-$v" uv run --locked --no-default-groups --group test --group bedrock \
      python tests/acceptance/run.py
    UV_PROJECT_ENVIRONMENT="$work/venv-$v" uv run --locked $GROUPS_PY python -m unittest tests.acceptance.test_docs
  done
}

job_typescript() {
  (cd typescript && npm ci --ignore-scripts)
  for v in $NODES; do
    echo "== Node $v"
    (cd typescript && npx -y -p "node@$v" -- npm run build && npx -y -p "node@$v" -- npm test)
  done
  (cd typescript && npm audit --audit-level=low && npm audit signatures)
}

for job in $JOBS; do
  case $job in
    check|python|typescript) echo "=== $job"; "job_$job" ;;
    *) echo "unknown job: $job (check, python, typescript)"; exit 2 ;;
  esac
done
echo "=== all passed: $JOBS"
