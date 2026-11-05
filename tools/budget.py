"""The size of the code a client audits, against its budget in pyproject.toml: `python tools/budget.py [DIR]`.

lines: lines holding code, by the tokenizer, with no comment or docstring. ifs: `if`, `elif`, a conditional expression,
`case`. private_names: another's `_single_underscore` names the code reads, which a release of theirs may break; but
those `private_names_allowed` lists for the file that reads them, each with its reason there. Bedrock's files (`bedrock`'s
`files`) have a budget of their own, apart from every other file's, so an audit of another provider's path reads them
in none of its numbers.
"""
import ast, io, pathlib, sys, tokenize, tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}


def docstrings(tree):
    held = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                held |= set(range(first.lineno, first.end_lineno + 1))
    return held


def code_lines(text, tree):
    held = set()
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type not in SKIP:
            held |= set(range(token.start[0], token.end[0] + 1))
    return len(held - docstrings(tree))


INTERNALS = {"get_referents", "get_referrers", "get_objects"}  # gc's: a way into another's objects past every name they give


def private(name):
    return name in INTERNALS or name.startswith("_") and not name.startswith("__") and name.replace("_", "").isalnum()


def private_names(trees, allowed=None):
    """Another's: read, never defined here, and not allowed to the file that reads it. Setting an attribute on another's
    object does not make it ours. `trees`: {file name: tree}; `allowed`: {file name: [names]}."""
    defined, used = set(), set()
    for name, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
                defined |= {t.attr for t in node.targets if isinstance(t, ast.Attribute) and getattr(t.value, "id", "") == "self"}
            if isinstance(node, ast.Attribute):
                used.add((name, node.attr))
            elif isinstance(node, ast.ImportFrom):
                used |= {(name, alias.name) for alias in node.names}
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                used |= {(name, part) for part in node.value.split(".")}
    excused = {(name, each) for name, names in (allowed or {}).items() for each in names}
    return sorted({each for name, each in used - excused if each not in defined and private(each)})


def measure(package, allowed=None, only=None, but=()):
    """The size of the package's files: `only` those named, if given, and not those in `but`."""
    paths = [path for path in sorted(pathlib.Path(package).glob("*.py")) if (only is None or path.name in only) and path.name not in but]
    texts = {path.name: path.read_text() for path in paths}
    trees = {name: ast.parse(text) for name, text in texts.items()}
    return {"lines": sum(code_lines(texts[name], tree) for name, tree in trees.items()),
            "ifs": sum(isinstance(node, (ast.If, ast.IfExp, ast.match_case)) for tree in trees.values() for node in ast.walk(tree)),
            "private_names": private_names(trees, allowed)}


def over(size, budget):
    """What exceeds the budget, as text; empty when within it."""
    found = {"lines": size["lines"], "ifs": size["ifs"], "private_names": len(size["private_names"])}
    return [f"{name}: {found[name]}, budget {budget[name]}" for name in found if name in budget and found[name] > budget[name]]


def problems(package, budget):
    """What exceeds either budget: every file but Bedrock's against the package's, Bedrock's against its own."""
    apart = budget.get("bedrock", {})
    shared = measure(package, budget.get("private_names_allowed"), but=apart.get("files", ()))
    bedrock = measure(package, budget.get("private_names_allowed"), only=apart.get("files", ()))
    return over(shared, budget) + [f"bedrock {problem}" for problem in over(bedrock, apart)]


def main(package=ROOT / "reflexer"):
    budget = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["reflexer"]["budget"]
    apart = budget.get("bedrock", {})
    size = measure(package, budget.get("private_names_allowed"), but=apart.get("files", ()))
    bedrock = measure(package, budget.get("private_names_allowed"), only=apart.get("files", ()))
    print(f"lines {size['lines']}/{budget['lines']}, ifs {size['ifs']}/{budget['ifs']}, "
          f"private names {len(size['private_names'])}/{budget['private_names']} {size['private_names'] or ''}; "
          f"Bedrock's files: lines {bedrock['lines']}/{apart.get('lines')}, ifs {bedrock['ifs']}/{apart.get('ifs')}")
    found = problems(package, budget)
    for problem in found:
        print("over budget:", problem, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
