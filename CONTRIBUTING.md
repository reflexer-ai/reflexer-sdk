# Contributing

Every change keeps each promise in [SECURITY.md](SECURITY.md): a new promise names its check and a planted fault that turns that check red, and a fix comes with a test that fails before it and passes after.

    uv sync --group dev --group test --group frameworks --group bedrock
    uv run python -m unittest discover -s tests -t .           # gates, unit tests, promises, each with its faults
    uv run python tests/acceptance/run.py                      # the provider SDKs over real sockets, offline
    uv run python -m unittest tests.acceptance.test_controls   # each fault planted in the SDK turns its cases red

    cd typescript && npm ci && npm run build && npm test      # TypeScript: types, gates, tests, each with its planted fault

Before a merge, every check of CI runs here, each Python and Node version it covers: `sh tools/ci.sh` (`sh tools/ci.sh check`, `PYTHONS=3.14 NODES=24 ...` to narrow it). GitHub runs the same workflow weekly only.

The code stays within the size budget in `pyproject.toml` (TypeScript: in `typescript/package.json`); a pull request that raises it says why there. No dependency is added to either package: the provider SDKs are the client's.
