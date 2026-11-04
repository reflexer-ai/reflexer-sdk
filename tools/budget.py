"""The size of the code a client audits, against its budget in pyproject.toml: `python tools/budget.py [DIR]`.

lines: lines holding code, by the tokenizer, with no comment or docstring. ifs: `if`, `elif`, a conditional expression,
`case`. private_names: another's `_single_underscore` names the code reads, which a release of theirs may break.
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


def private(name):
    return name.startswith("_") and not name.startswith("__") and name.replace("_", "").isalnum()


def private_names(trees):
    """Another's: read, never defined here. Setting an attribute on another's object does not make it ours."""
    defined, used = set(), set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
                defined |= {t.attr for t in node.targets if isinstance(t, ast.Attribute) and getattr(t.value, "id", "") == "self"}
            if isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                used |= set(node.value.split("."))
    return sorted(name for name in used - defined if private(name))


def measure(package):
    texts = [path.read_text() for path in sorted(pathlib.Path(package).glob("*.py"))]
    trees = [ast.parse(text) for text in texts]
    return {"lines": sum(code_lines(text, tree) for text, tree in zip(texts, trees)),
            "ifs": sum(isinstance(node, (ast.If, ast.IfExp, ast.match_case)) for tree in trees for node in ast.walk(tree)),
            "private_names": private_names(trees)}


def over(size, budget):
    """What exceeds the budget, as text; empty when within it."""
    found = {"lines": size["lines"], "ifs": size["ifs"], "private_names": len(size["private_names"])}
    return [f"{name}: {found[name]}, budget {budget[name]}" for name in budget if found[name] > budget[name]]


def main(package=ROOT / "reflexer"):
    budget = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["reflexer"]["budget"]
    size = measure(package)
    print(f"lines {size['lines']}/{budget['lines']}, ifs {size['ifs']}/{budget['ifs']}, "
          f"private names {len(size['private_names'])}/{budget['private_names']} {size['private_names'] or ''}")
    problems = over(size, budget)
    for problem in problems:
        print("over budget:", problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
