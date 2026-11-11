#!/bin/sh
# Every check of .github/workflows/ci.yml, run on this machine. Keep the two in step: a check added there is added here.
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
      tests.test_logic tests.test_transport tests.test_promises tests.test_langchain tests.test_pydantic_ai tests.test_bedrock tests.test_litellm
    UV_PROJECT_ENVIRONMENT="$work/venv-$v" uv run --locked --no-default-groups --group test --group bedrock \
      python tests/acceptance/run.py
    UV_PROJECT_ENVIRONMENT="$work/venv-$v" uv run --locked $GROUPS_PY python -m unittest tests.acceptance.test_docs
  done
}

# The bin directory of a Node of major $1 already on this machine: nvm's, or the `node` on PATH. Nothing is fetched or
# installed here, so no package's install script runs: a major missing fails, saying how to get it.
node_bin() {
  found=""
  if [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
    found=$(. "${NVM_DIR:-$HOME/.nvm}/nvm.sh" --no-use && nvm which "$1" 2>/dev/null) || found=""
  fi
  if [ -z "$found" ] && [ "$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null)" = "$1" ]; then found=$(command -v node); fi
  if [ -z "$found" ]; then echo "Node $1 is not on this machine: install it with your version manager (nvm install $1), or narrow NODES" >&2; return 1; fi
  dirname "$found"
}

job_typescript() {
  (cd typescript && npm ci --ignore-scripts)
  for v in $NODES; do
    echo "== Node $v"
    bin=$(node_bin "$v")
    (cd typescript && PATH="$bin:$PATH" && npm run build && npm test)
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
