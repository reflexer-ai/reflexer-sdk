"""The static promises, and a planted fault for each that shows its gate can fail. Offline, no network.
Run: uv run --group dev python -m unittest tests.test_gates"""
import ast, builtins, importlib, importlib.util, os, pathlib, re, shutil, subprocess, sys, tempfile, tomllib, types, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # the import gate imports the provider SDKs: LiteLLM's prices from its own copy


def tool_module(name):
    """tools/<name>.py, loaded by its path: no module of the same name elsewhere on the path stands in for it."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


budget, majors, promises = tool_module("budget"), tool_module("majors"), tool_module("promises")

STDLIB_CORE = {"base64", "copy", "functools", "threading", "hashlib", "importlib.metadata.version", "ipaddress", "json", "logging", "random", "re",
               "time", "urllib.parse", "weakref"}
ALLOWED = {  # what each file may import: the standard library, and the provider SDK the client already has, in its own file
    "__init__.py": STDLIB_CORE,
    "transport.py": STDLIB_CORE,
    "openai.py": {"openai"},
    "anthropic.py": {"anthropic"},
    "gemini.py": {"httpx", "httpx2", "inspect", "google.genai"},
    "langchain_openai.py": {"langchain_openai", "openai", "os.environ"},  # os.environ: LangChain's own proxy variable, read as LangChain does
    "langchain_gemini.py": {"langchain_google_genai"},
    "bedrock.py": {"copy", "inspect", "re"},  # Bedrock's wire and what its lines share: the standard library only
    "boto3.py": {"boto3", "botocore", "urllib3"},  # urllib3: botocore's own HTTP library, whose read timeout botocore names its own
    # aiohttp, yarl: the session aiobotocore sends by, and its URL; gc.get_referents, gc's one function used here: the one
    # way to the request headers aiohttp keeps with an answer (P27)
    "aiobotocore.py": {"aiobotocore", "botocore", "aiohttp", "yarl", "asyncio", "gc.get_referents"},
    "anthropic_bedrock.py": {"anthropic", "contextvars", "inspect"},  # contextvars: a call's own state, set by our middleware for our transport
    "litellm.py": {"litellm", "httpx", "asyncio", "contextvars", "datetime", "inspect", "threading", "time"},  # httpx: LiteLLM's own HTTP library; the rest, its window's bound
}


def dependencies(root):
    return tomllib.loads((root / "pyproject.toml").read_text())["project"]["dependencies"]


def allows(allowed, module):
    """Whether a file's allowlist takes `module`: the standard library's by its exact name, so `logging` is not
    `logging.handlers`; a provider SDK's with its own submodules (`google.genai`'s, not every `google` package's)."""
    return module in allowed or module.split(".")[0] not in sys.stdlib_module_names and any(module.startswith(each + ".") for each in allowed)


def importable(module, allowed):
    """Whether the gate may import `module` to read its attributes: one the file's allowlist takes, or a package above
    one (`importlib`, above `importlib.metadata.version`): a provider SDK's own module, or the standard library's allowed.
    No other module a plant names runs here."""
    return allows(allowed, module) or any(entry.startswith(module + ".") for entry in allowed)


def submodule(module, name, allowed):
    """The name of the module `module.name` is (a submodule, or a module `module` holds), or None for another attribute.
    A submodule is found by its spec, never run; `module` is imported only when the gate may (`importable`)."""
    if not importable(module, allowed):
        return None
    inner = getattr(importlib.import_module(module), name, None)
    if isinstance(inner, types.ModuleType):
        return inner.__name__
    try:
        return f"{module}.{name}" if importlib.util.find_spec(f"{module}.{name}") else None
    except (ImportError, ValueError):  # `module` is no package
        return None


def reached(module, names, allowed):
    """What the allowlist does not take, reached from `module` through its attributes `names`: a module (`random._os`,
    `inspect.os`, a provider SDK's `asyncio`), or an attribute of a module not allowed (`importlib.import_module`)."""
    for name in names:
        inner = submodule(module, name, allowed)
        if inner is None:
            return None if allows(allowed, module) else f"{module}.{name}"
        module = inner
        if not allows(allowed, module):
            return module
    return None


OWN = "reflexer:"  # a name bound to a file of the SDK's: `from . import transport`


def exports(root):
    """{SDK file's stem: {name: the module its imports bind to that name}}, for what another file reaches by `from . import`."""
    held = {}
    for path in sorted((root / "reflexer").glob("*.py")):
        allowed, names = ALLOWED.get(path.name, set()), {}
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names |= {alias.asname or alias.name.split(".")[0]: alias.name if alias.asname else alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names |= {alias.asname or alias.name: inner for alias in node.names if (inner := submodule(node.module, alias.name, allowed))}
        held[path.stem] = names
    return held


def chain(node):
    """(name, [attributes]) of `a.b.c` or `getattr(a.b, "c")`, or None."""
    if isinstance(node, ast.Name):
        return node.id, []
    if isinstance(node, ast.Attribute):
        inner = chain(node.value)
        return inner and (inner[0], inner[1] + [node.attr])
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
        inner = chain(node.args[0])
        return inner and (inner[0], inner[1] + [node.args[1].value])
    return None


def shadowed(name, node, parents):
    """Whether `name`, read at `node`, is not the module's: only where Python's own rule is plain, a read in a class's
    body after that body defines a function or class of the name, with no `global` or `del` of it there. Elsewhere
    the gate takes the name as the module's: at worst too strictly, never fooled by a scope."""
    statement = node
    while statement in parents and not isinstance(parents[statement], ast.ClassDef):
        if isinstance(parents[statement], (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return False
        statement = parents[statement]
    body = getattr(parents.get(statement), "body", [])
    if statement not in body or any(isinstance(each, (ast.Global, ast.Delete)) for each in ast.walk(parents[statement])):
        return False
    for each in reversed(body[:body.index(statement)]):  # the name's last binding before the read: a def, or else the module's
        if isinstance(each, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and each.name == name:
            return True
        if any(isinstance(inner, ast.Name) and inner.id == name or isinstance(inner, ast.alias) and (inner.asname or inner.name.split(".")[0]) == name
               or isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and inner.name == name for inner in ast.walk(each)):
            return False
    return False


ATTRIBUTES = {"random", "copy", "types", "time", "datetime"}  # the attributes named as a standard-library module the SDK reads: random.random, a client's copy, genai.types, time.time, datetime.datetime


def imports_not_allowed(root):
    """Every module a file reaches that its allowlist does not take: by an import, its own or another SDK file's
    (`from . import random`), through another module's attributes, resolved, or, the standard library's, handed on as a
    value. And, however a module is held (a class, a value, another module), any attribute named as a module of the
    standard library but those `ATTRIBUTES` lists (`made.utils.io`), and an import in a class's body."""
    found, shared = [], exports(root)
    for path in sorted((root / "reflexer").glob("*.py")):
        allowed = ALLOWED.get(path.name)
        if allowed is None:
            found.append(f"{path.name}: a file with no import allowlist")
            continue
        tree, bound = ast.parse(path.read_text()), {}  # bound: a name the file binds to a module, and that module's name
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level > 0:  # the SDK's own: a module one of its files binds is that module
                source = shared.get(node.module or "__init__", {})
                for alias in node.names:
                    if node.module is None and (root / "reflexer" / f"{alias.name}.py").exists():  # a file of the SDK's, whose modules the chains below follow
                        bound[alias.asname or alias.name] = f"{OWN}{alias.name}"
                    elif alias.name == "*" or alias.name in source:
                        module = "*" if alias.name == "*" else source[alias.name]
                        found += [f"{path.name}: {module}"] if not allows(allowed, module) else []
                        bound[alias.asname or alias.name] = module
            elif isinstance(node, ast.ImportFrom):  # a module's one function allowed is not the module
                for alias in node.names:
                    whole = f"{node.module}.{alias.name}"
                    if alias.name == "*":  # binds names no gate sees
                        found.append(f"{path.name}: {whole}")
                        continue
                    module = submodule(node.module, alias.name, allowed)
                    if module:
                        bound[alias.asname or alias.name] = whole = module
                    if whole not in allowed and not allows(allowed, module or node.module):
                        found.append(f"{path.name}: {whole}")
            elif isinstance(node, ast.Import):
                found += [f"{path.name}: {alias.name}" for alias in node.names if not allows(allowed, alias.name)]
                bound |= {alias.asname or alias.name.split(".")[0]: alias.name if alias.asname else alias.name.split(".")[0] for alias in node.names}
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        found += [f"{path.name}: an import in a class's body, which makes the module the class's attribute" for node in ast.walk(tree)
                  if isinstance(node, (ast.Import, ast.ImportFrom)) and isinstance(parents.get(node), ast.ClassDef)]
        for node in ast.walk(tree):  # a module however held, by its name: one the standard library has, read but as listed
            attribute = node.attr if isinstance(node, ast.Attribute) else node.args[1].value if (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) > 1
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)) else None
            if attribute and attribute.lstrip("_") in sys.stdlib_module_names and attribute not in ATTRIBUTES:
                found.append(f"{path.name}: .{attribute}, a module's name")
        for node in ast.walk(tree):
            names = chain(node)
            if not names or names[0] not in bound or shadowed(names[0], node, parents):
                continue
            module, attributes = bound[names[0]], names[1]
            if module.startswith(OWN) and attributes:  # through a file of the SDK's: what it binds to a module
                module, attributes = shared.get(module.removeprefix(OWN), {}).get(attributes[0], ""), attributes[1:]
                found += [f"{path.name}: {module}"] if module and not allows(allowed, module) else []
            if module and attributes and not module.startswith(OWN):
                found += [f"{path.name}: {where}" for where in [reached(module, attributes, allowed)] if where]
            elif not names[1] and isinstance(node.ctx, ast.Load) and module.split(".")[0] in sys.stdlib_module_names:
                parent = parents.get(node)
                if not isinstance(parent, ast.Attribute) and not (isinstance(parent, ast.Call) and chain(parent)):
                    found.append(f"{path.name}: {node.id} handed on as a value")
    return list(dict.fromkeys(found))


BUILTINS = {  # the builtins the SDK reads: none prints, reads the terminal, opens a file, imports or runs code built at run time
    "BaseException", "Exception", "ImportError", "OSError", "RuntimeError", "TimeoutError", "TypeError", "ValueError", "all", "any",
    "bytes", "dict", "enumerate", "float", "getattr", "hasattr", "id", "int", "isinstance", "iter", "len", "list", "max", "min",
    "next", "set", "staticmethod", "str", "sum", "super", "type"}


def builtins_not_allowed(root):
    """Every name a file reads that is a builtin `BUILTINS` does not list (`print`, `open`, `input`, `license`, `vars`,
    `__import__`), however it is reached: called, aliased or handed on. A name of the file's own that a builtin has is
    refused too: the gate reads no scope, so it is never fooled by one."""
    found = []
    for path in sorted((root / "reflexer").glob("*.py")):
        found += [f"{path.name}: {node.id}" for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.Name)
                  and node.id in dir(builtins) and node.id not in BUILTINS]
    return list(dict.fromkeys(found))


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


PART = re.compile(r"(?<![a-z])k(?:ey?)?(?![a-z])", re.I)  # a part of the key header's name, `k`, `ke` or `key`, apart from other letters


def key_header_named(root):
    """Every text of the SDK's, outside `Reflexer.route`, that holds a part of the key header's name, so could build it
    (`"-".join(["reflexer", "key"])`, `OURS + "k" + "ey"`, `"reflexer-\\x6bey"`): its value is read, escapes and implicit
    joins included. Not a docstring, nor a message: a log's, or an error's raised to the client."""
    found = []
    for path in sorted((root / "reflexer").glob("*.py")):
        tree = ast.parse(path.read_text())
        spared, own = set(), {each.id for each in ast.walk(tree) if isinstance(each, ast.Name) and not isinstance(each.ctx, ast.Load)} | {
            each.name for each in ast.walk(tree) if isinstance(each, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler))} | {
            each.arg for each in ast.walk(tree) if isinstance(each, ast.arg)} | {
            getattr(each, "name", None) or getattr(each, "rest", None) for each in ast.walk(tree) if isinstance(each, (ast.MatchAs, ast.MatchStar, ast.MatchMapping))} | {
            (each.asname or each.name).split(".")[0] for each in ast.walk(tree) if isinstance(each, ast.alias)}
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body and isinstance(body[0], ast.Expr):
                spared.add(body[0].value)  # a docstring
            if isinstance(node, ast.Module) and path.name == "__init__.py":  # the module's own class, not one nested
                body = [each.body for each in body if isinstance(each, ast.ClassDef) and each.name == "Reflexer"]
                body = body[0] if body else []
                spared |= {each for each in body if isinstance(each, ast.FunctionDef) and each.name == "route"}
            if (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name)
                    and isinstance(getattr(builtins, node.exc.func.id, None), type) and issubclass(getattr(builtins, node.exc.func.id), BaseException)
                    and node.exc.func.id not in own):
                spared |= set(node.exc.args[:1])  # an error's message: `raise ValueError("...")`, a builtin error the file does not rebind
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "log" and node.args):
                spared.add(node.args[0])
        spared = {each for node in spared for each in ([node, *node.values] if isinstance(node, ast.JoinedStr) else [node])}  # its text, not what it formats
        within = {each for node in spared if isinstance(node, ast.FunctionDef) for each in ast.walk(node)}  # route
        found += [f"{path.name}:{node.lineno}" for node in ast.walk(tree) if node not in spared and node not in within
                  and isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes))
                  and PART.search(node.value if isinstance(node.value, str) else node.value.decode("latin-1"))]
    return found


INSTALLERS = ["README.md", "CONTRIBUTING.md", "docs/**/*.md", "tests/**/*.md", "typescript/*.md", "tools/*.sh", ".github/**/*.yml", ".github/**/*.yaml"]  # what a person or CI runs
SETTINGS = [".npmrc", "typescript/.npmrc", ".yarnrc", ".yarnrc.yml", "uv.toml", "pip.conf", "pip.ini"]  # a package tool's settings, none of which the repo holds
TOOL = re.compile(r"(?:^|[\s/\"'`])(?:uv pip|pip[\d.]*|pipx|uvx?|hatch|hatchling|flit|pyproject-build|poetry|pdm|npm|npx|pnpm|yarn|bunx?|corepack)(?=[\s\"'`]|$)"
                  r"|(?:^|[\s\"'`])-m\s+(?:pip|build|hatchling|flit)\b|\bsetup\.py\b")
SETTING = re.compile(r"\b(?!UV_PROJECT_ENVIRONMENT\b)(?:UV|PIP|NPM_CONFIG|npm_config|YARN)_\w+")  # a package tool's setting, however set
INSTALLS = [re.compile(form) for form in (  # the commands of a package tool the docs, scripts and workflows may run, whole, their variables read
    r"pip install --build-constraint \S*build-constraints\.txt [./~][\w./~-]*",  # the SDK, from a path, its build tools pinned and hashed
    r"uv build --build-constraint build-constraints\.txt --require-hashes( -o \S+)?",
    r"uv sync( --locked)?( --group \S+| --no-default-groups| --python \S+)*",  # the SDK never built (`package = false`)
    r"uv run( --locked)?( --group \S+| --no-default-groups)* (python|zizmor) .*",
    r"uv venv \S+", r"uv pip list .*", r'uv pip install --python \S+ --resolution "\$RESOLUTION"( --group \S+)*',  # drift's: no path, no build
    r"npm ci --ignore-scripts", r"npm pack( --pack-destination \S+)?", r"npm run build", r"npm test", r"npm audit --audit-level=\w+",
    r"npm audit signatures", r'npm view "\$name(@\$major)?" version( --json)?',
    r"xargs npm install --no-save --ignore-scripts( < \S+)?", r"npm install /path/to/\S+\.tgz", r"npm publish \S+\.tgz .*")]


def lines_run(path):
    """(line number, text) of what a file runs or shows to run: a script's lines; a workflow's `run:` steps; a page's code
    blocks (fenced or indented) and code spans. A line continued is read whole, at its first line."""
    lines, held, fence, block = path.read_text().split("\n"), [], None, None
    for number, line in enumerate(lines, 1):
        if number > 1 and lines[number - 2].endswith("\\"):
            continue  # read with the line it continues
        for after in lines[number:]:
            if not line.endswith("\\"):
                break
            line = line[:-1] + " " + after
        if path.suffix == ".md":
            if re.match(r"\s*(```|~~~)", line) and (not fence or line.strip().startswith(fence)):
                fence = None if fence else line.strip()[:3]
            elif fence or line.startswith("    "):
                held.append((number, line))
            else:
                held += [(number, span) for span in re.findall(r"`([^`]+)`", line)]
        elif path.suffix in (".yml", ".yaml"):
            indent = len(line) - len(line.lstrip())
            if block is not None and (indent > block or not line.strip()):
                held.append((number, line))
                continue
            block, step = None, re.match(r"(\s*)(?:-\s+)?run:\s*(.*)", line)
            if step and re.match(r"[|>][-+]?\s*(#.*)?$", step[2]):
                block = len(step[1])
            elif step:
                held.append((number, step[2]))
        else:
            held.append((number, line))
    return held


def expanded(text, values):
    """`text` with each `$NAME` the file assigns read as every value it is given, together."""
    for _ in range(3):
        text = re.sub(r'"?\$\{?(\w+)\}?"?', lambda found: values.get(found[1], found[0]), text)
    return text


def installs_unpinned(root):
    """Every command of a package tool (pip, uv, npm, and their kin) the docs, the scripts or the workflows run that is
    not one of `INSTALLS`, its variables read as every value the file gives them: an install or a build the release's
    pins do not hold (the SDK built with its build tools unhashed, a Node package's install script run), or one not yet
    judged. A variable before it but uv's environment, a package tool's setting (an `env:` of a workflow, a file of
    `SETTINGS`, a `[tool.uv]` key but `package`) is refused too; and uv building the SDK for `uv sync` or `uv run`,
    which `[tool.uv] package = false` keeps it from."""
    uv = tomllib.loads((root / "pyproject.toml").read_text()).get("tool", {}).get("uv", {})
    found = [] if uv == {"package": False} else [f"pyproject.toml: [tool.uv] {uv}: only `package = false`"]
    found += [f"{name}: a package tool's settings" for name in SETTINGS if (root / name).exists()]
    for path in sorted({path for pattern in INSTALLERS for path in root.glob(pattern)}):
        text = path.read_text()
        found += [f"{path.relative_to(root)}: {name}, a package tool's setting" for name in SETTING.findall(text)]  # in an env:, an export, wherever
        values = {}
        for name, double, single, bare in re.findall(r"""(?:^|\s)([A-Za-z_]\w*)=(?:"([^"]*)"|'([^']*)'|(\S*))""", text, re.M):
            values[name] = " ".join(filter(None, [values.get(name), double or single or bare]))
        values = {name: re.sub(rf'"?\$\{{?{name}\}}?"?', "", value) for name, value in values.items()}  # a value built on its own
        for number, line in lines_run(path):
            for command in re.split(r"&&|\|\||[;|()]", re.split(r"(?:^|\s)#", line)[0]):
                command = " ".join(command.split())
                whole = re.sub(r"^UV_PROJECT_ENVIRONMENT=\S+ ", "", " ".join(expanded(command, values).split()))  # where uv puts the environment: no other variable
                if TOOL.search(command) and (not any(form.fullmatch(whole) for form in INSTALLS) or len(TOOL.findall(whole)) > 1):  # one tool, whole
                    found.append(f"{path.relative_to(root)}:{number}: {command}")
    return list(dict.fromkeys(found))


HOME, MAC, AGENT = "/" + "home/", "/" + "Users/", "." + "claude/"  # in parts, so this file does not name them whole
LOCAL = re.compile("|".join(re.escape(part) for part in (HOME, MAC, AGENT)) + r"|[A-Z]:\\\\Users\\\\")  # a person's machine


def local_paths(root):
    """Every tracked file naming a path on someone's machine: it would ship in the source archive."""
    names = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True).stdout.split("\0")
    return [name for name in names if name and (root / name).is_file() and LOCAL.search((root / name).read_text(errors="replace"))]


def licenses_differ(root):
    """Whether typescript/LICENSE, which npm packs (only the license beside its package.json), differs from LICENSE."""
    return (root / "typescript" / "LICENSE").read_bytes() != (root / "LICENSE").read_bytes()


class Gates(unittest.TestCase):
    def test_no_local_path_in_any_file(self):
        self.assertEqual(local_paths(ROOT), [])

    def test_no_dependency(self):
        self.assertEqual(dependencies(ROOT), [])

    def test_the_build_backend_is_pinned(self):
        self.assertEqual(unpinned_build(ROOT), [])

    def test_every_install_takes_the_releases_pins(self):
        self.assertEqual(installs_unpinned(ROOT), [])

    def test_imports_are_allowed(self):
        self.assertEqual(imports_not_allowed(ROOT), [])

    def test_only_the_builtins_listed(self):
        self.assertEqual(builtins_not_allowed(ROOT), [])

    def test_within_budget(self):
        self.assertEqual(budget.problems(ROOT / "reflexer", tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["reflexer"]["budget"]), [])

    def test_ruff_clean(self):
        self.assertEqual(ruff(), 0)

    def test_the_keys_header_named_only_in_route(self):
        self.assertEqual(key_header_named(ROOT), [])

    def test_semgrep_clean(self):
        self.assertEqual(semgrep(), 0)

    def test_workflows_clean(self):
        self.assertEqual(zizmor(), 0)

    def test_the_majors_check_reads_every_provider_file(self):
        self.assertEqual(majors.tested(ROOT), {"openai": [3], "anthropic": [2], "google-genai": [2], "langchain-openai": [1],
                                               "langchain-google-genai": [4], "boto3": [1], "aiobotocore": [3], "litellm": [1]})

    def test_every_promise_is_held_and_can_fail(self):
        self.assertEqual(promises.problems(ROOT), [])

    def test_the_npm_package_carries_the_same_license(self):
        self.assertFalse(licenses_differ(ROOT))


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

    def test_an_install_skipping_the_releases_pins_turns_it_red(self):
        self.assertEqual(installs_unpinned(self.root), [])
        planted = ["pip install ./reflexer-sdk", "pip install --build-constraint reflexer-sdk/build-constraints.txt ./reflexer-sdk",
                   "cd typescript && npm ci && npm pack  # makes made-up.tgz", "npm install /path/to/made-up.tgz  # in your project",
                   "uv build --build-constraint build-constraints.txt", "npm install https://made-up.example/made-up.tgz", "pnpm install",
                   "pip install --build-constraint build-constraints.txt --no-build-isolation .", "pip install \\", "  ./reflexer-sdk",
                   "PIP_NO_BUILD_ISOLATION=0 pip install --build-constraint build-constraints.txt ./reflexer-sdk", "npm clean-install",
                   "pip3.12 install ./reflexer-sdk", "hatch build", "sudo pip install ./reflexer-sdk",
                   "pip install --build-constraint build-constraints.txt reflexer"]
        (self.root / "docs").mkdir()
        (self.root / "docs" / "made_up.md").write_text("Run `pip install .` from a clone.\n\n```sh\n" + "\n".join(planted) + "\n```\n")
        script = self.root / "tools" / "ci.sh"
        lines = len(script.read_text().split("\n"))  # the script's last line, empty, then the two planted
        script.write_text(script.read_text() + 'npx -y -p "node@20" -- npm test\nuv pip install --python made-up -e .\n'
                          'MADE_UP="--with ."\nuv run --locked $MADE_UP python made_up.py\n')
        (self.root / "typescript" / ".npmrc").write_text("ignore-scripts=false\n")
        (self.root / ".github" / "workflows" / "made_up.yaml").write_text(
            "jobs:\n  made-up:\n    steps:\n      - run: >\n          pip install\n    env:\n      UV_NO_BUILD_ISOLATION: 1\n"
            "      - run: sh -c \"pip install ./reflexer-sdk\"\n      - run: npm audit fix\n      - run: uv run --locked python -m pip install .\n")
        path = self.root / "pyproject.toml"
        path.write_text(path.read_text().replace("package = false", "package = true"))
        self.assertEqual([each.split(": ")[0] for each in installs_unpinned(self.root)],
                         ["pyproject.toml", "typescript/.npmrc", ".github/workflows/made_up.yaml", *(f".github/workflows/made_up.yaml:{line}" for line in (5, 8, 9, 10))]
                         + ["docs/made_up.md"] + [f"docs/made_up.md:{line}" for line in (1, 4, 6, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 19)]
                         + [f"tools/ci.sh:{line}" for line in (lines, lines + 1, lines + 3)])

    def test_an_import_outside_the_allowlist_turns_it_red(self):
        self.plant("__init__.py", "import made_up_module")
        self.assertEqual(imports_not_allowed(self.root), ["__init__.py: made_up_module"])

    def test_more_of_a_module_than_its_function_allowed_turns_it_red(self):
        self.plant("aiobotocore.py", "import gc\nfrom gc import get_referrers")
        self.assertEqual(imports_not_allowed(self.root), ["aiobotocore.py: gc", "aiobotocore.py: gc.get_referrers"])

    def test_a_way_past_names_counted_where_not_allowed_turns_it_red(self):
        limits = tomllib.loads((self.root / "pyproject.toml").read_text())["tool"]["reflexer"]["budget"]
        self.plant("transport.py", "import gc\ndef made_up(thing):\n    return gc.get_referents(thing)")
        self.assertEqual([problem.split(",")[0] for problem in budget.problems(self.root / "reflexer", limits) if "private" in problem],
                         ["private_names: 1"])

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

    def test_the_keys_header_outside_route_turns_it_red(self):
        self.plant("__init__.py", 'def made_up(headers, key):\n    headers["reflexer-key"] = key')
        self.assertNotEqual(key_header_named(self.root), [])

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

    def test_the_keys_header_in_other_case_turns_it_red(self):
        self.plant("__init__.py", 'def made_up(headers, key):\n    headers["Reflexer-Key"] = key')
        self.assertNotEqual(key_header_named(self.root), [])

    def test_the_keys_header_built_turns_it_red(self):
        self.plant("__init__.py", 'OURS = "reflexer-"\ndef made_up(headers, key):\n    headers[OURS + "key"] = key')
        self.assertNotEqual(key_header_named(self.root), [])

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

    def test_the_keys_header_built_in_other_case_turns_it_red(self):
        self.plant("__init__.py", 'OURS = "reflexer-"\ndef made_up(headers, key):\n    headers[OURS + "Key"] = key')
        self.assertNotEqual(key_header_named(self.root), [])

    def test_a_harmless_exception_or_name_holding_log_of_anothers_stays_green(self):
        # an attribute named `log` of another's is a finding (log-only-by-its-logger): a logger may be named so
        self.plant("__init__.py", "def other(task, queue):\n    return task.exception(), queue.backlog, queue.login")
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

    def test_the_keys_header_formatted_turns_it_red(self):
        self.plant("__init__.py", 'OURS = "reflexer-"\ndef made_up(headers, key):\n    headers["{}key".format(OURS)] = key')
        self.assertNotEqual(key_header_named(self.root), [])

    def test_the_keys_header_in_another_route_turns_it_red(self):
        self.plant("__init__.py", 'class MadeUp:\n    def route(self, headers, key):\n        headers["reflexer-key"] = key')
        self.assertNotEqual(key_header_named(self.root), [])

    def test_a_log_reached_another_way_turns_semgrep_red(self):
        logger = 'import logging\nlog = logging.getLogger("made-up")\n'
        for text in (logger + "def made_up(body):\n    say = log.warning\n    say(body)",
                     logger + 'def made_up(body):\n    getattr(log, "warning")(body)',
                     logger + 'def made_up(body):\n    log.handle(log.makeRecord("made-up", 30, "made_up.py", 1, body, None, None))',
                     'import logging\nmade = logging.getLogger("made-up")\ndef made_up(body):\n    made.warning(body)',
                     'import logging as made\ndef made_up(body):\n    made.root.warning(body)',
                     'from logging import getLogger\ndef made_up(body):\n    getLogger("made-up").warning(body)',
                     'from logging import LogRecord, StreamHandler\ndef made_up(body):\n'
                     '    StreamHandler().emit(LogRecord("made-up", 30, "made_up.py", 1, body, None, None))',
                     'import logging\ndef made_up():\n    logging.basicConfig(filename="made-up.log")',
                     "import botocore.utils\ndef made_up(body):\n    made = botocore.utils.logger\n    made.warning(body)",
                     logger + 'def made_up(body):\n    log.warning("made up", type(open("made-up.txt", "w").write(body)).__name__)',
                     logger + 'def made_up():\n    log.debug("made up", type(logging.basicConfig(filename="made-up.log")).__name__)',
                     ):
            with self.subTest(text):
                self.setUp()
                self.plant("__init__.py", text)
                self.assertNotEqual(semgrep(self.root), 0, text)

    def test_a_builtin_not_listed_turns_it_red(self):
        for text, found in (("def made_up(body):\n    print(body)", "print"), ("def made_up(body):\n    say = print\n    say(body)", "print"),
                            ('def made_up(body):\n    with open("made-up.txt", "w") as file:\n        file.write(body)', "open"),
                            ("def made_up(body):\n    input(body)", "input"), ("def made_up(body):\n    exit(body)", "exit"),
                            ("def made_up(body):\n    help(body)", "help"), ('def made_up(body):\n    type(license)("made-up", body)()', "license"),
                            ('made_up = vars(__builtins__)["__import__"]("made_up")', "vars"), ('made_up = __import__("made_up")', "__import__"),
                            ("def made_up(text):\n    return eval(text)", "eval"),
                            ('def decoy(open=None):\n    pass\ndef made_up(body):\n    open("made-up.txt", "w").write(body)', "open"),
                            ('def made_up(body):\n    [0 for input in ()]\n    input(body)', "input")):
            with self.subTest(text):
                self.setUp()
                self.plant("__init__.py", text)
                self.assertIn(f"__init__.py: {found}", builtins_not_allowed(self.root))

    def test_a_namespace_read_by_name_turns_semgrep_red(self):
        for text in ('made_up = vars(__builtins__)["__import__"]("made_up")',
                     'made_up = __builtins__["__import__"]("made_up")',
                     'made_up = globals()["__builtins__"]["__import__"]("made_up")',
                     "def made_up(name):\n    return getattr(made_up, name)",
                     'made_up = print.__self__.__import__("made_up")',
                     'import random\nmade_up = random.Random.__init__.__globals__["_os"]',
                     'import random\nmade_up = random.__dict__["_os"]',
                     'import inspect\nmade_up = inspect.getmodule(inspect.getmodule)',
                     'import inspect\nmade_up = inspect.currentframe().f_globals["__builtins__"]',
                     'import random\nmade_up = getattr(random.Random.__init__, "__globals__")["_os"]',
                     'import random\nmade_up = getattr(random, "__dict__")["_os"]',
                     'made_up = getattr(object, "__subclasses__")()',
                     'import functools, random\nmade_up = functools.reduce(getattr, ["__globals__"], random.Random.__init__)',
                     'import inspect, random\nmade_up = inspect.getattr_static(random.Random.__init__, "__globals__")',
                     'def made_up(f):\n    return (globals()["__builtins__"] or f).f_globals.get("__name__")',
                     'import inspect\ndef made_up(name):\n    return getattr(*(inspect.getfile, name))',
                     'import inspect\nmade_up = inspect.getclosurevars(inspect.getfile).globals',
                     'import inspect\nmade_up = inspect.getmembers_static(inspect)',
                     'def made_up():\n    return getattr(made_up, "__doc__")'):
            with self.subTest(text):
                self.setUp()
                self.plant("__init__.py", text)
                self.assertNotEqual(semgrep(self.root), 0, text)

    def test_a_module_reached_another_way_turns_it_red(self):
        for text, found in (('import importlib.metadata\nmade_up = getattr(importlib, "import_module")("made_up")', "importlib.import_module"),
                            ('import importlib.metadata\nsay = importlib.import_module\nmade_up = say("made_up")', "importlib.import_module"),
                            ('import importlib.metadata\nmade_up = importlib.metadata.import_module("made_up")', "importlib.metadata"),
                            ("from importlib.metadata import import_module", "importlib.metadata.import_module"),
                            ('from importlib.metadata import EntryPoint\nmade_up = EntryPoint("x", "made_up:x", "x").load()', "importlib.metadata.EntryPoint"),
                            ("def made_up(command):\n    import random\n    return random._os.system(command)", "os"),  # an import in a function
                            ("class MadeUp:\n    import random as made\n    run = made._os.system", "os"),
                            ("import random\ndef made_up(random=random):\n    return random", "random handed on as a value"),
                            ("import random\ndef made_up():\n    global random\n    random = random\n    return random._os", "os"),
                            ("import random\nclass MadeUp:\n    random = random\n    run = random._os", "os"),
                            ("import random\nclass MadeUp:\n    def random(self):\n        pass\n    def run(self, command):\n        return random._os.system(command)", "os"),
                            ("import random\nclass MadeUp:\n    run = random._os\n    def random(self):\n        pass", "os"),
                            ("import random as made\nclass MadeUp:\n    def random(self):\n        pass\n    random = made\n    run = random._os", "os"),
                            ("class Made:\n    import random\nrun = Made.random._os.system", "._os, a module's name"),
                            ("class Made:\n    import random\n", "an import in a class's body, which makes the module the class's attribute"),
                            ('from logging.handlers import SocketHandler\nmade_up = SocketHandler("made-up", 1)', "logging.handlers.SocketHandler"),
                            ('import logging.handlers as made\nmade_up = made.SocketHandler("made-up", 1)', "logging.handlers"),
                            ("import logging.config\nmade_up = logging.config.listen(1)", "logging.config"),
                            ("made_up = random._os.system", "os"),
                            ('made_up = getattr(random, "_os")', "os"),
                            ("made = random\nmade_up = made._os", "random handed on as a value"),
                            ("from logging import *\nmade_up = handlers", "logging.*")):
            with self.subTest(text):
                self.setUp()
                self.plant("__init__.py", text)
                self.assertIn(f"__init__.py: {found}", imports_not_allowed(self.root))
        for file, text, found in (("boto3.py", "made_up = botocore.awsrequest.functools", "functools"),  # a provider SDK's module, resolved
                                  ("boto3.py", "made_up = boto3.logging.root", "logging"),
                                  ("boto3.py", "made = botocore\nmade_up = made.utils.io", ".io, a module's name"),  # held by a value
                                  ("boto3.py", "def made_up(made=botocore):\n    return getattr(made.utils, 'tempfile')", ".tempfile, a module's name"),
                                  ("gemini.py", "def made_up():\n    [0 for genai in ()]\n    return genai.live.websockets", "websockets"),  # a comprehension's name
                                  ("openai.py", "from . import random as made\nmade_up = made._os", "random"),  # another SDK file's import
                                  ("openai.py", "from . import transport\nmade_up = transport.copy.copy", "copy")):
            with self.subTest(text):
                self.setUp()
                self.plant(file, text)
                self.assertIn(f"{file}: {found}", imports_not_allowed(self.root))

    def test_the_keys_header_built_from_parts_turns_it_red(self):
        ours = 'OURS = "reflexer-"\n'
        for text in ('def made_up(headers, key):\n    headers["-".join(["reflexer", "key"])] = key',
                     'def made_up(headers, key):\n    headers["reflexer-%s" % "key"] = key',
                     'def made_up(headers, key):\n    headers["%s-%s" % ("reflexer", "Key")] = key',
                     ours + 'def made_up(headers, key):\n    headers[OURS + "k" + "ey"] = key',
                     'OURS, PART = "reflexer-", "KEY"\ndef made_up(headers, key):\n    headers[f"{OURS}{PART}"] = key',
                     ours + 'def made_up(headers, key):\n    headers[f"{OURS}key"] = key',
                     'def made_up(headers, key, ours="reflexer"):\n    headers[f"{ours}_k{\'ey\'}"] = key',
                     'def made_up(headers, key):\n    headers["{}-{}".format("reflexer", "key")] = key',
                     'def made_up(headers, key):\n    headers[str.join("-", ("reflexer", "ke" "y"))] = key',
                     'def made_up(headers, key):\n    headers["REFLEXER-KEY".lower()] = key',
                     'def made_up(headers, key):\n    headers["reflexer key".replace(" ", "-")] = key',
                     'def made_up(headers, key):\n    headers["-".join("the reflexer key is revoked".split()[1:3])] = key',
                     'def made_up(headers, key):\n    headers["reflexer-\\x6bey"] = key',
                     'def made_up(headers, key):\n    headers["reflexer-\\N{LATIN SMALL LETTER K}ey"] = key',
                     'def made_up(headers, key):\n    raise ValueError(f"{headers.update({OURS + \'key\': key})}")',
                     'def made_up(headers, key):\n    headers[b"reflexer-key"] = key',
                     'def Put(name):\n    pass\ndef made_up():\n    raise Put("reflexer-key")',
                     'def made_up(headers, key, ValueError=None):\n    raise ValueError("reflexer-key")',
                     'def made_up(headers, key):\n    raise headers.setdefault("reflexer-key", key)',
                     'def made_up():\n    class Reflexer:\n        def route(self, headers, key):\n            headers["reflexer-key"] = key'):
            with self.subTest(text):
                self.setUp()
                self.plant("__init__.py", text)
                self.assertNotEqual(key_header_named(self.root), [], text)

    def test_a_license_copy_that_drifts_turns_it_red(self):
        shutil.copy(ROOT / "LICENSE", self.root / "LICENSE")
        shutil.copy(ROOT / "LICENSE", self.root / "typescript" / "LICENSE")
        self.assertFalse(licenses_differ(self.root))
        (self.root / "typescript" / "LICENSE").write_text((ROOT / "LICENSE").read_text() + "A made-up line, drifted.\n")  # whatever the notice names
        self.assertTrue(licenses_differ(self.root))

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
                     "export const made = (body) => console.warn.call(console, body);",
                     'export const made = (body) => console.warn("made up", process.stderr.write(body) instanceof Error ? '
                     'process.stderr.write(body).name : typeof process.stderr.write(body));'):
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
                     'export const made = (headers, key) => { headers[OURS.concat("key")] = key; };',
                     'export const made = (headers, key) => { headers[["reflexer", "key"].join("-")] = key; };',
                     'export const made = (headers, key) => { headers[OURS + "k" + "ey"] = key; };',
                     'export const made = (headers, key) => { headers[`${OURS}k${"ey"}`] = key; };',
                     "export const made = (headers, key) => { headers[OURS + 'KEY'.toLowerCase()] = key; };",
                     'export const made = (headers, key) => { headers[OURS + " key".trim()] = key; };',
                     'export const made = (headers, key) => { headers["reflexer-\\x6bey"] = key; };',
                     "export const made = (headers, key) => { headers[`reflexer-\\u{6b}ey`] = key; };",
                     'export const made = (key) => ({ "reflexer-\\x6bey": key });',
                     'function Put(name) {}\nexport const made = () => { throw new Put("reflexer-key"); };'):
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
