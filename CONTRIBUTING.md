# Contributing

Every change keeps each promise in [SECURITY.md](SECURITY.md): a new promise names its check and a planted fault that turns that check red, and a fix comes with a test that fails before it and passes after.

    uv sync --group dev --group test
    uv run python -m unittest discover -s tests -t .           # gates, unit tests, promises, each with its faults
    uv run python tests/acceptance/run.py                      # the provider SDKs over real sockets, offline
    uv run python -m unittest tests.acceptance.test_controls   # each fault planted in the SDK turns its cases red

The code stays within the size budget in `pyproject.toml`; a pull request that raises it says why there. No dependency is added to the package: the provider SDKs are the client's.
