"""The acceptance suite: its own step, `python tests/acceptance/run.py`, and its controls, `python -m unittest
tests.acceptance.test_controls`. Unit-test discovery stops here, so neither runs twice."""


def load_tests(loader, tests, pattern):
    return tests
