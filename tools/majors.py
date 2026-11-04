"""Whether a provider SDK has a major release newer than those its file is tested on: `python3 tools/majors.py`.
Reads each `supported(package, majors)` call in `reflexer/`, and each package's newest version on PyPI."""
import ast, json, pathlib, sys, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent


def tested(root=ROOT):
    """{package: majors}, from the provider files' own calls."""
    found = {}
    for path in sorted((root / "reflexer").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "supported":
                package, majors = (ast.literal_eval(argument) for argument in node.args)
                found[package] = majors
    return found


def newest(package):
    with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=30) as answer:
        return json.load(answer)["info"]["version"]


def untested(majors_of, newest_of):
    return [f"{package} {newest_of[package]}: tested on majors {majors}" for package, majors in majors_of.items()
            if int(newest_of[package].split(".")[0]) > max(majors)]


if __name__ == "__main__":
    majors_of = tested()
    problems = untested(majors_of, {package: newest(package) for package in majors_of})
    for problem in problems:
        print("untested major:", problem, file=sys.stderr)
    sys.exit(1 if problems else 0)
