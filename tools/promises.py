"""Each promise in SECURITY.md is held by a check and broken by a planted fault that turns that check red; this refuses a
promise missing either, or naming one that does not exist: `python tools/promises.py`.

A check is `test:PATH::CLASS::METHOD`, `ruff:CODE` or `semgrep:RULE`."""
import ast, pathlib, re, sys, tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROW = re.compile(r"^\| *\*\*(P\d+)\*\*")


def promises(text):
    """{id: (held_by, broken_by)}, from the table's rows: `| **P1** ... | checks | faults |`."""
    found = {}
    for line in text.splitlines():
        if ROW.match(line):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            found[ROW.match(line)[1]] = tuple(re.findall(r"`([^`]+)`", cell) for cell in cells[-2:])
    return found


def exists(check, root=ROOT):
    kind, _, name = check.partition(":")
    if kind == "test":
        path, *names = name.split("::")
        file = root / path
        if not file.is_file():
            return False
        tree = ast.parse(file.read_text())
        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        if len(names) != 2 or names[0] not in classes:
            return False
        return any(isinstance(node, ast.FunctionDef) and node.name == names[1] for node in classes[names[0]].body)
    if kind == "ruff":
        selected = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["ruff"]["lint"]["select"]
        return any(name.startswith(prefix) for prefix in selected)
    if kind == "semgrep":
        return re.search(rf"^\s*- id: {re.escape(name)}\s*$", (root / "semgrep.yml").read_text(), re.M) is not None
    return False


def problems(root=ROOT):
    table = promises((root / "SECURITY.md").read_text())
    found = [] if table else ["SECURITY.md lists no promise"]
    for promise, (held_by, broken_by) in table.items():
        if not held_by:
            found.append(f"{promise}: held by no check")
        if not broken_by:
            found.append(f"{promise}: no fault shows its check can fail")
        found += [f"{promise}: no such check {check}" for check in held_by + broken_by if not exists(check, root)]
    return found


if __name__ == "__main__":
    for problem in problems():
        print(problem, file=sys.stderr)
    sys.exit(1 if problems() else 0)
