# Contributing

Every change keeps each promise in [SECURITY.md](SECURITY.md): a new promise names its check and a planted fault that turns that check red, and a fix comes with a test that fails before it and passes after.

    uv sync --group dev --group test --group frameworks --group bedrock
    uv run python -m unittest discover -s tests -t .           # gates, unit tests, promises, each with its faults
    uv run python tests/acceptance/run.py                      # the provider SDKs over real sockets, offline
    uv run python -m unittest tests.acceptance.test_controls   # each fault planted in the SDK turns its cases red
    uv run python -m unittest tests.acceptance.test_docs       # every example in README.md and docs/, run as written

    cd typescript && npm ci --ignore-scripts && npm run build && npm test   # TypeScript: types, gates, tests and the docs' examples, each with its planted fault

The library pages' Behavior sections are written once, in `docs/behavior.template`: `tests/test_docs_pages.py` fails when a page's copy differs, and prints the section to paste. It also checks every link and anchor between the pages.

Every code example in README.md and `docs/` but a shell command runs in those checks, after a comment saying what it must show (`tests/acceptance/test_docs.py`); an example no check runs is a bug.

Every check of CI also runs here, each Python and Node version it covers: `sh tools/ci.sh` (`sh tools/ci.sh check`, `PYTHONS=3.14 NODES=24 ...` to narrow it). It fetches no Node: each major comes from nvm, or is the `node` on your PATH. GitHub runs the same workflow on every pull request and every push to main.

The code stays within the size budget in `pyproject.toml` (TypeScript: in `typescript/package.json`); a pull request that raises it says why there. No dependency is added to either package: the provider SDKs are the client's.
