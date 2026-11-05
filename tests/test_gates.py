"""The static promises, and a planted fault for each that shows its gate can fail. Offline, no network.
Run: uv run --group dev python -m unittest tests.test_gates"""
import ast, pathlib, re, shutil, subprocess, sys, tempfile, tomllib, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import budget, majors, promises

STDLIB_CORE = {"base64", "copy", "functools", "threading", "hashlib", "importlib.metadata", "ipaddress", "json", "logging", "random", "re",
               "time", "urllib.parse", "weakref"}
ALLOWED = {  # what each file may import: the standard library, and the provider SDK the client already has, in its own file
    "__init__.py": STDLIB_CORE,
    "transport.py": STDLIB_CORE,
    "openai.py": {"openai"},
    "anthropic.py": {"anthropic"},
    "gemini.py": {"httpx", "httpx2", "inspect", "google"},
    "langchain_openai.py": {"langchain_openai", "openai", "os"},  # os: LangChain's own proxy variable, read as LangChain does
    "langchain_gemini.py": {"langchain_google_genai"},
    "bedrock.py": {"copy", "inspect", "re"},  # Bedrock's wire and what its lines share: the standard library only
    "boto3.py": {"boto3", "botocore", "urllib3"},  # urllib3: botocore's own HTTP library, whose read timeout botocore names its own
    "aiobotocore.py": {"aiobotocore", "botocore", "yarl", "asyncio"},  # yarl: aiohttp's URL, which aiobotocore sends by as its own send does
    "anthropic_bedrock.py": {"anthropic", "contextvars", "inspect"},  # contextvars: a call's own state, set by our middleware for our transport
    "litellm.py": {"litellm", "httpx", "asyncio", "contextvars", "datetime", "inspect", "threading", "time"},  # httpx: LiteLLM's own HTTP library; the rest, its window's bound
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
    return tool("zizmor", "--offline", "--min-severity", "low", ".github", root=root)  # the workflows and dependabot


def semgrep(root=ROOT):
    return tool("semgrep", "scan", "--quiet", "--error", "--metrics=off", "--no-git-ignore", "--disable-nosem", "--config", "semgrep.yml", ".", root=root)  # the rules pick their own paths


def unpinned_build(root):
    """The build backend, as pyproject.toml names it, unless pinned there and hashed in build-constraints.txt."""
    constraints = (root / "build-constraints.txt").read_text()
    return [name for name in tomllib.loads((root / "pyproject.toml").read_text())["build-system"]["requires"]
            if "==" not in name or f"{name} \\\n    --hash=sha256:" not in constraints]


HOME, MAC, AGENT = "/" + "home/", "/" + "Users/", "." + "claude/"  # in parts, so this file does not name them whole
LOCAL = re.compile("|".join(re.escape(part) for part in (HOME, MAC, AGENT)) + r"|[A-Z]:\\\\Users\\\\")  # a person's machine


def local_paths(root):
    """Every tracked file naming a path on someone's machine: it would ship in the source archive."""
    names = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True).stdout.split("\0")
    return [name for name in names if name and (root / name).is_file() and LOCAL.search((root / name).read_text(errors="replace"))]


class Gates(unittest.TestCase):
    def test_no_local_path_in_any_file(self):
        self.assertEqual(local_paths(ROOT), [])

    def test_no_dependency(self):
        self.assertEqual(dependencies(ROOT), [])

    def test_the_build_backend_is_pinned(self):
        self.assertEqual(unpinned_build(ROOT), [])

    def test_imports_are_allowed(self):
        self.assertEqual(imports_not_allowed(ROOT), [])

    def test_within_budget(self):
        self.assertEqual(budget.problems(ROOT / "reflexer", tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["reflexer"]["budget"]), [])

    def test_ruff_clean(self):
        self.assertEqual(ruff(), 0)

    def test_semgrep_clean(self):
        self.assertEqual(semgrep(), 0)

    def test_workflows_clean(self):
        self.assertEqual(zizmor(), 0)

    def test_the_majors_check_reads_every_provider_file(self):
        self.assertEqual(majors.tested(ROOT), {"openai": [3], "anthropic": [2], "google-genai": [2], "langchain-openai": [1],
                                               "langchain-google-genai": [4], "boto3": [1], "aiobotocore": [3], "litellm": [1]})

    def test_every_promise_is_held_and_can_fail(self):
        self.assertEqual(promises.problems(ROOT), [])


class Broken(unittest.TestCase):
    """Each gate above, red on a copy of the tree with one fault planted."""

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="reflexer-gates-"))
        self.addCleanup(shutil.rmtree, self.root)
        for name in ("reflexer", "tools", ".github", "typescript/src", "typescript/test"):
            shutil.copytree(ROOT / name, self.root / name)
        for name in ("pyproject.toml", "semgrep.yml", "SECURITY.md", "build-constraints.txt"):
            shutil.copy(ROOT / name, self.root / name)

    def plant(self, name, text, package="reflexer"):
        with open(self.root / package / name, "a") as file:
            file.write("\n" + text + "\n")

    def assert_typescript_turns_semgrep_red(self, text):
        self.plant("index.js", text, package="typescript/src")
        self.assertNotEqual(semgrep(self.root), 0, text)

    def test_a_dependency_turns_it_red(self):
        path = self.root / "pyproject.toml"
        path.write_text(path.read_text().replace("dependencies = []", 'dependencies = ["made-up-package"]'))
        self.assertNotEqual(dependencies(self.root), [])

    def test_an_unpinned_build_backend_turns_it_red(self):
        path = self.root / "pyproject.toml"
        path.write_text(path.read_text().replace('requires = ["hatchling==', 'requires = ["made-up", "hatchling=='))
        self.assertEqual(unpinned_build(self.root), ["made-up"])

    def test_a_build_backend_unhashed_turns_it_red(self):
        path = self.root / "build-constraints.txt"
        path.write_text(path.read_text().replace("hatchling==", "made-up=="))
        self.assertEqual(unpinned_build(self.root), ["hatchling==1.33.0"])

    def test_an_import_outside_the_allowlist_turns_it_red(self):
        self.plant("__init__.py", "import made_up_module")
        self.assertEqual(imports_not_allowed(self.root), ["__init__.py: made_up_module"])

    def test_a_file_with_no_allowlist_turns_it_red(self):
        (self.root / "reflexer" / "made_up.py").write_text("")
        self.assertEqual(imports_not_allowed(self.root), ["made_up.py: a file with no import allowlist"])

    def test_growth_past_budget_turns_it_red(self):
        self.plant("__init__.py", "\n".join(f"made_up_{n} = 1 if True else 0" for n in range(400)))
        self.assertTrue(budget.over(budget.measure(self.root / "reflexer"), {"lines": 300, "ifs": 35, "private_names": 0}))

    def test_growth_in_a_shared_file_is_not_bedrocks_to_hold(self):
        limits = tomllib.loads((self.root / "pyproject.toml").read_text())["tool"]["reflexer"]["budget"]
        self.plant("transport.py", "made_up = 1 if True else 0")
        self.assertEqual([problem.split(",")[0] for problem in budget.problems(self.root / "reflexer", limits)],
                         [f"lines: {limits['lines'] + 1}", f"ifs: {limits['ifs'] + 1}"])
        self.setUp()
        self.plant("boto3.py", "made_up = 1 if True else 0")
        apart = limits["bedrock"]
        self.assertEqual([problem.split(",")[0] for problem in budget.problems(self.root / "reflexer", limits)],
                         [f"bedrock lines: {apart['lines'] + 1}", f"bedrock ifs: {apart['ifs'] + 1}"])

    def test_another_private_name_turns_it_red(self):
        self.plant("__init__.py", "def made_up(other):\n    return other._made_up_private")
        allowed = tomllib.loads((self.root / "pyproject.toml").read_text())["tool"]["reflexer"]["budget"]["private_names_allowed"]
        self.assertEqual(budget.measure(self.root / "reflexer", allowed)["private_names"], ["_made_up_private"])

    def test_a_private_name_allowed_to_another_file_turns_it_red(self):
        allowed = tomllib.loads((self.root / "pyproject.toml").read_text())["tool"]["reflexer"]["budget"]["private_names_allowed"]
        self.assertEqual(budget.measure(self.root / "reflexer", allowed)["private_names"], [])
        self.plant("transport.py", "def made_up(client):\n    return client._endpoint")  # boto3.py's, read in a shared file
        self.plant("boto3.py", "def made_up_too(client):\n    return client._made_up_private")  # one boto3.py does not name
        self.assertEqual(budget.measure(self.root / "reflexer", allowed)["private_names"], ["_endpoint", "_made_up_private"])
        limits = tomllib.loads((self.root / "pyproject.toml").read_text())["tool"]["reflexer"]["budget"]
        self.assertEqual([problem.split(",")[0] for problem in budget.problems(self.root / "reflexer", limits) if "private" in problem],
                         ["private_names: 1", "bedrock private_names: 1"])  # each in the budget of its own file

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

    def test_a_new_major_turns_the_majors_check_red(self):
        self.assertEqual(majors.untested({"openai": [3]}, {"openai": "4.0.0"}), ["openai 4.0.0: tested on majors [3]"])
        self.assertEqual(majors.untested({"openai": [3]}, {"openai": "3.99.0"}), [])

    def test_a_module_reached_through_another_turns_semgrep_red(self):
        for text in ('import logging\nmade_up = logging.sys.modules["socket"]', 'import http\nmade_up = http.client',
                     'import boto3\nmade_up = boto3.session.client'):  # boto3's own `boto3.client` excepted, nothing past it
            with self.subTest(text):
                self.setUp()
                self.plant("__init__.py", text)
                self.assertNotEqual(semgrep(self.root), 0, text)

    def test_a_socket_handler_turns_semgrep_red(self):
        self.plant("__init__.py", 'import logging.handlers\nmade_up = logging.handlers.SocketHandler("made-up", 1)')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_a_command_through_another_module_turns_semgrep_red(self):
        self.plant("__init__.py", 'import inspect\ndef made_up():\n    inspect.os.system("made-up")')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_the_keys_header_formatted_turns_semgrep_red(self):
        self.plant("__init__.py", 'OURS = "reflexer-"\ndef made_up(headers, key):\n    headers["{}key".format(OURS)] = key')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_the_keys_header_in_another_route_turns_semgrep_red(self):
        self.plant("__init__.py", 'class MadeUp:\n    def route(self, headers, key):\n        headers["reflexer-key"] = key')
        self.assertNotEqual(semgrep(self.root), 0)

    def test_a_local_path_turns_it_red(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "made_up.txt").write_text(f"# made from {HOME}made-up/notes.in\n")
        subprocess.run(["git", "-C", str(self.root), "add", "made_up.txt"], check=True)
        self.assertEqual(local_paths(self.root), ["made_up.txt"])

    def test_typescript_a_logged_body_or_key_turns_semgrep_red(self):
        self.assert_typescript_turns_semgrep_red("export const made = (init, way) => console.warn(init.body, way.key);")

    def test_typescript_a_log_of_another_kind_turns_semgrep_red(self):
        self.assert_typescript_turns_semgrep_red('export const made = (body) => console.log("sent %s", body);')

    def test_typescript_a_body_written_to_stderr_turns_semgrep_red(self):
        self.assert_typescript_turns_semgrep_red("export const made = (body) => process.stderr.write(body);")

    def test_typescript_console_reached_another_way_turns_semgrep_red(self):
        for text in ('export const made = (body) => console["log"](body);',
                     "export const made = (body) => { const say = console.warn; say(body); };",
                     "export const made = (body) => console.warn.call(console, body);"):
            with self.subTest(text=text):
                self.setUp()
                self.assert_typescript_turns_semgrep_red(text)

    def test_typescript_the_keys_header_outside_route_turns_semgrep_red(self):
        self.assert_typescript_turns_semgrep_red('export const made = (headers, key) => { headers["reflexer-key"] = key; };')

    def test_typescript_the_keys_header_in_an_object_or_other_case_turns_semgrep_red(self):
        self.assert_typescript_turns_semgrep_red('export const made = (key) => ({ "Reflexer-Key": key });')

    def test_typescript_the_keys_header_built_turns_semgrep_red(self):
        for text in ('export const made = (headers, key) => { headers[OURS + "Key"] = key; };',
                     "export const made = (headers, key) => { headers[`${OURS}key`] = key; };",
                     'export const made = (headers, key) => { headers[OURS.concat("key")] = key; };'):
            with self.subTest(text=text):
                self.setUp()
                self.assert_typescript_turns_semgrep_red(text)

    def test_typescript_the_keys_header_in_another_route_turns_semgrep_red(self):
        self.assert_typescript_turns_semgrep_red('class MadeUp {\n  route(headers, key) { headers["reflexer-key"] = key; }\n}')

    def test_a_promise_with_no_check_turns_it_red(self):
        path = self.root / "SECURITY.md"
        path.write_text(path.read_text() + "\n| **P99** made up | | |\n")
        self.assertIn("P99: held by no check", promises.problems(self.root))

    def test_a_node_test_that_does_not_exist_turns_it_red(self):
        path, tests = self.root / "SECURITY.md", "node:typescript/test/promises.test.js"
        path.write_text(path.read_text() + f"\n| **P99** made up | `{tests}::Promises::made up` | `{tests}::Broken::the key reaches only reflexer` |\n")
        self.assertIn(f"P99: no such check {tests}::Promises::made up", promises.problems(self.root))
        self.assertIn(f"P99: no such check {tests}::Broken::the key reaches only reflexer", promises.problems(self.root))  # of another suite

    def test_a_check_that_does_not_exist_turns_it_red(self):
        path = self.root / "SECURITY.md"
        path.write_text(path.read_text() + "\n| **P99** made up | `test:tests/made_up.py::A::b` | `semgrep:made-up` |\n")
        self.assertIn("P99: no such check semgrep:made-up", promises.problems(self.root))


if __name__ == "__main__":
    unittest.main()
