"""The static promises, and a planted fault for each that shows its gate can fail. Offline, no network.
Run: uv run --group dev python -m unittest tests.test_gates"""
import ast, pathlib, shutil, subprocess, sys, tempfile, tomllib, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import budget, promises

STDLIB_CORE = {"base64", "copy", "functools", "threading", "hashlib", "importlib.metadata", "ipaddress", "json", "logging", "random", "re",
               "time", "urllib.parse"}
ALLOWED = {  # what each file may import: the standard library, and the provider SDK the client already has, in its own file
    "__init__.py": STDLIB_CORE,
    "transport.py": STDLIB_CORE,
    "openai.py": {"openai"},
    "anthropic.py": {"anthropic"},
    "gemini.py": {"httpx", "httpx2", "inspect", "google"},
}


def dependencies(root):
    return tomllib.loads((root / "pyproject.toml").read_text())["project"]["dependencies"]


def imports_not_allowed(root):
    found = []
    for path in sorted((root / "reflexer").glob("*.py")):
        allowed = ALLOWED.get(path.name)
        if allowed is None:
            found.append(f"{path.name}: a file with no import allowlist")
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
            found += [f"{path.name}: {name}" for name in names if name not in allowed and name.split(".")[0] not in allowed]
    return found


def tool(name, *arguments, root=ROOT):
    """A standard tool's verdict on a tree: its exit code. It must be installed: a gate that cannot run is a red gate."""
    found = shutil.which(name)
    if found is None:
        raise AssertionError(f"{name} is not installed: uv sync --group dev")
    return subprocess.run([found, *arguments], cwd=root, capture_output=True, text=True).returncode


def ruff(root=ROOT):
    return tool("ruff", "check", "--quiet", "reflexer", root=root)


def zizmor(root=ROOT):
    return tool("zizmor", "--offline", "--min-severity", "low", ".github/workflows", root=root)


def semgrep(root=ROOT):
    return tool("semgrep", "scan", "--quiet", "--error", "--metrics=off", "--no-git-ignore", "--disable-nosem", "--config", "semgrep.yml", ".", root=root)  # the rules pick their own paths


def unpinned_build(root):
    return [name for name in tomllib.loads((root / "pyproject.toml").read_text())["build-system"]["requires"] if "==" not in name]


class Gates(unittest.TestCase):
    def test_no_dependency(self):
        self.assertEqual(dependencies(ROOT), [])

    def test_the_build_backend_is_pinned(self):
        self.assertEqual(unpinned_build(ROOT), [])

    def test_imports_are_allowed(self):
        self.assertEqual(imports_not_allowed(ROOT), [])

    def test_within_budget(self):
        self.assertEqual(budget.over(budget.measure(ROOT / "reflexer"), tomllib.loads((ROOT / "pyproject.toml").read_text())
                                     ["tool"]["reflexer"]["budget"]), [])

    def test_ruff_clean(self):
        self.assertEqual(ruff(), 0)

    def test_semgrep_clean(self):
        self.assertEqual(semgrep(), 0)

    def test_workflows_clean(self):
        self.assertEqual(zizmor(), 0)

    def test_every_promise_is_held_and_can_fail(self):
        self.assertEqual(promises.problems(ROOT), [])


class Broken(unittest.TestCase):
    """Each gate above, red on a copy of the tree with one fault planted."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="reflexer-gates-"))
        self.addCleanup(shutil.rmtree, self.root)
        for name in ("reflexer", "tools", ".github"):
            shutil.copytree(ROOT / name, self.root / name)
        for name in ("pyproject.toml", "semgrep.yml", "SECURITY.md"):
            shutil.copy(ROOT / name, self.root / name)

    def plant(self, name, text):
        with open(self.root / "reflexer" / name, "a") as file:
            file.write("\n" + text + "\n")

    def test_a_dependency_turns_it_red(self):
        path = self.root / "pyproject.toml"
        path.write_text(path.read_text().replace("dependencies = []", 'dependencies = ["made-up-package"]'))
        self.assertNotEqual(dependencies(self.root), [])

    def test_an_unpinned_build_backend_turns_it_red(self):
        path = self.root / "pyproject.toml"
        path.write_text(path.read_text().replace('requires = ["hatchling==', 'requires = ["made-up", "hatchling=='))
        self.assertEqual(unpinned_build(self.root), ["made-up"])

    def test_an_import_outside_the_allowlist_turns_it_red(self):
        self.plant("__init__.py", "import made_up_module")
        self.assertEqual(imports_not_allowed(self.root), ["__init__.py: made_up_module"])

    def test_a_file_with_no_allowlist_turns_it_red(self):
        (self.root / "reflexer" / "made_up.py").write_text("")
        self.assertEqual(imports_not_allowed(self.root), ["made_up.py: a file with no import allowlist"])

    def test_growth_past_budget_turns_it_red(self):
        self.plant("__init__.py", "\n".join(f"made_up_{n} = 1 if True else 0" for n in range(400)))
        self.assertTrue(budget.over(budget.measure(self.root / "reflexer"), {"lines": 300, "ifs": 35, "private_names": 0}))

    def test_another_private_name_turns_it_red(self):
        self.plant("__init__.py", "def made_up(other):\n    return other._made_up_private")
        self.assertEqual(budget.measure(self.root / "reflexer")["private_names"], ["_made_up_private"])

    def test_a_socket_turns_ruff_red(self):
        self.plant("__init__.py", "import socket")
        self.assertNotEqual(ruff(self.root), 0)

    def test_a_dynamic_import_turns_ruff_red(self):
        self.plant("__init__.py", "import importlib\nmade_up = importlib.import_module('made_up')")
        self.assertNotEqual(ruff(self.root), 0)

    def test_an_eval_turns_ruff_red(self):
        self.plant("__init__.py", "def made_up(text):\n    return eval(text)")
        self.assertNotEqual(ruff(self.root), 0)

    def test_a_logged_body_turns_semgrep_red(self):
        self.plant("__init__.py", 'import logging\nlog = logging.getLogger("x")\ndef made_up(request):\n'
                                  '    log.warning("sent %s", request.content)')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_the_keys_header_outside_route_turns_semgrep_red(self):
        self.plant("__init__.py", 'def made_up(headers, key):\n    headers["reflexer-key"] = key')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_an_action_not_pinned_by_hash_turns_zizmor_red(self):
        path = self.root / ".github" / "workflows" / "ci.yml"
        path.write_text(path.read_text().replace("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "actions/checkout@v7"))
        self.assertNotEqual(zizmor(self.root), 0)

    def test_a_logged_body_by_another_logger_turns_semgrep_red(self):
        self.plant("__init__.py", 'import logging\nlogger = logging.getLogger("x")\ndef made_up(body):\n    logger.warning(body)')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_a_logged_exception_turns_semgrep_red(self):
        self.plant("__init__.py", 'import logging\nlog = logging.getLogger("x")\ndef made_up():\n    log.exception("failed")')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_a_printed_body_turns_semgrep_red(self):
        self.plant("__init__.py", 'def made_up(body):\n    print(body)')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_the_keys_header_in_other_case_turns_semgrep_red(self):
        self.plant("__init__.py", 'def made_up(headers, key):\n    headers["Reflexer-Key"] = key')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_the_keys_header_built_turns_semgrep_red(self):
        self.plant("__init__.py", 'OURS = "reflexer-"\ndef made_up(headers, key):\n    headers[OURS + "key"] = key')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_a_builtin_import_turns_semgrep_red(self):
        self.plant("__init__.py", 'made_up = __import__("socket")')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_a_row_not_of_the_form_turns_it_red(self):
        path = self.root / "SECURITY.md"
        path.write_text(path.read_text().replace("| **P1** ", "| P1 ", 1))
        self.assertTrue(any(p.startswith("a promise row not of the form: | P1 ") for p in promises.problems(self.root)))

    def test_a_module_reached_through_sys_turns_it_red(self):
        self.plant("__init__.py", 'import sys\nmade_up = sys.modules["socket"]')
        self.assertIn("__init__.py: sys", imports_not_allowed(self.root))

    def test_importlibs_import_turns_semgrep_red(self):
        self.plant("__init__.py", 'import importlib\nmade_up = importlib.__import__("socket")')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_an_entry_point_loaded_turns_semgrep_red(self):
        self.plant("__init__.py", 'from importlib.metadata import entry_points\nmade_up = [e.load() for e in entry_points(group="x")]')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_a_body_written_to_stderr_turns_semgrep_red(self):
        self.plant("__init__.py", 'import sys\ndef made_up(body):\n    sys.stderr.write(body)')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_a_suppressed_finding_turns_semgrep_red(self):
        self.plant("__init__.py", 'def made_up(body):\n    print(body)  # nosemgrep')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_the_keys_header_built_in_other_case_turns_semgrep_red(self):
        self.plant("__init__.py", 'OURS = "reflexer-"\ndef made_up(headers, key):\n    headers[OURS + "Key"] = key')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_a_harmless_log_or_exception_of_anothers_stays_green(self):
        self.plant("__init__.py", "import math\nmade_up = math.log(2)\ndef other(task):\n    return task.exception()")
        self.assertEqual(semgrep(self.root), 0)

    def test_a_promise_written_elsewhere_turns_it_red(self):
        path = self.root / "SECURITY.md"
        path.write_text(path.read_text() + "\n- **P99** made up\n")
        self.assertIn("a promise outside the table: P99", promises.problems(self.root))

    def test_a_promise_with_no_check_turns_it_red(self):
        path = self.root / "SECURITY.md"
        path.write_text(path.read_text() + "\n| **P99** made up | | |\n")
        self.assertIn("P99: held by no check", promises.problems(self.root))

    def test_a_check_that_does_not_exist_turns_it_red(self):
        path = self.root / "SECURITY.md"
        path.write_text(path.read_text() + "\n| **P99** made up | `test:tests/made_up.py::A::b` | `semgrep:made-up` |\n")
        self.assertIn("P99: no such check semgrep:made-up", promises.problems(self.root))


if __name__ == "__main__":
    unittest.main()
