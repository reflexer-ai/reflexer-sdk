# Security

What this SDK promises, and what holds each promise. Every promise names a check that runs on every change, and a planted fault that turns that check red, so a green check means something. `tools/promises.py` refuses a promise missing either.

| Promise | Held by | Shown able to fail by |
|---|---|---|
| **P1** No dependency: the package requires nothing. | `test:tests/test_gates.py::Gates::test_no_dependency` | `test:tests/test_gates.py::Broken::test_a_dependency_turns_it_red` |
| **P2** Each file imports only the standard library, and a provider file only that provider's SDK, which the client already has. | `test:tests/test_gates.py::Gates::test_imports_are_allowed` | `test:tests/test_gates.py::Broken::test_an_import_outside_the_allowlist_turns_it_red`, `test:tests/test_gates.py::Broken::test_a_file_with_no_allowlist_turns_it_red` |
| **P3** No connection, process, native code or code loaded from data of the SDK's own: every call goes by the client's HTTP client. | `ruff:S`, `ruff:TID251` | `test:tests/test_gates.py::Broken::test_a_socket_turns_ruff_red`, `test:tests/test_gates.py::Broken::test_an_eval_turns_ruff_red` |
| **P4** Nothing a request or an answer holds is logged, nor the key: only what kind of thing happened. | `semgrep:log-only-kinds` | `test:tests/test_gates.py::Broken::test_a_logged_body_turns_semgrep_red` |
| **P5** Only one place names the key's header. | `semgrep:key-header-only-in-route` | `test:tests/test_gates.py::Broken::test_the_keys_header_outside_route_turns_semgrep_red` |
| **P6** The code stays small enough to read in one sitting, and reads no private name of another's package. | `test:tests/test_gates.py::Gates::test_within_budget` | `test:tests/test_gates.py::Broken::test_growth_past_budget_turns_it_red`, `test:tests/test_gates.py::Broken::test_another_private_name_turns_it_red` |
| **P7** The checks run with read-only rights, on actions pinned by hash; no secret is in any commit. | `test:tests/test_gates.py::Gates::test_workflows_clean`, CI's gitleaks over every commit | `test:tests/test_gates.py::Broken::test_an_action_not_pinned_by_hash_turns_zizmor_red`, CI's planted key |
| **P8** Each promise here is held and shown able to fail. | `test:tests/test_gates.py::Gates::test_every_promise_is_held_and_can_fail` | `test:tests/test_gates.py::Broken::test_a_promise_with_no_check_turns_it_red`, `test:tests/test_gates.py::Broken::test_a_check_that_does_not_exist_turns_it_red` |

## Reporting a vulnerability

Through GitHub's private vulnerability reporting on this repository, not a public issue.
