"""The docs' pages as text: each library page's Behavior section in the words of its one source, docs/behavior.template,
and every link and anchor between README.md and docs/ leading somewhere. Their code blocks run in
tests/acceptance/test_docs.py. Run: python -m unittest tests.test_docs_pages"""
import glob, os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
PAGES = [os.path.join(ROOT, "README.md"), *sorted(glob.glob(os.path.join(DOCS, "**", "*.md"), recursive=True))]
TEMPLATE = os.path.join(DOCS, "behavior.template")
SECTION = "## Behavior"


def read(path):
    with open(path) as file:
        return file.read()


def template(text):
    """(providers by page, [(conditions, line)]) from the template's text."""
    providers, lines = {}, []
    for line in text.split("\n"):
        if line.startswith("#") or not line.strip():
            continue
        if line.startswith("provider "):
            _, page, name = line.split(" ", 2)
            providers[page] = name
            continue
        conditions, _, body = line.partition("|")
        lines.append((conditions.split(), body.removeprefix(" ")))
    return providers, lines


def expected(name, page, source):
    """The Behavior section the template gives the page `name`, whose text is `page`."""
    providers, lines = template(source)
    py = bool(re.search(r"```python|<!-- example: [^>]*python", page))
    ts = bool(re.search(r"```js|<!-- example: [^>]*js", page))
    facts = {"all": True, "py": py, "ts": ts, "py-only": py and not ts, "ts-only": ts and not py, "both": py and ts}
    holds = lambda condition: (name != condition[1:]) if condition.startswith("!") else name == condition if condition.endswith(".md") \
        else facts[condition]
    provider = providers.get(name, "your provider")
    key = "your provider key" if provider == "your provider" else f"your {provider} key"
    return "\n".join(body.replace("{provider}", provider).replace("{key}", key) for conditions, body in lines if all(map(holds, conditions)))


def section(page):
    """The page's Behavior section: from its heading to the next heading or the page's "Next:" line."""
    found = []
    for line in page.split("\n"):
        if found and (line.startswith("## ") or line.startswith("Next:")):
            break
        if found or line == SECTION:
            found.append(line)
    return "\n".join(found).strip()


def behavior_problem(name, page, source):
    """None, or what differs between the page's Behavior section and the template's."""
    want, have = expected(name, page, source).strip(), section(page)
    return None if want == have else f"{name}: its Behavior section is not the template's; it should read:\n\n{want}\n"


def slug(heading):
    """The anchor GitHub gives a heading."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def link_problems(path, text):
    """Every relative link of `text` (the page at `path`) whose file or anchor does not exist."""
    problems = []
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+:", target):
            continue
        file, _, anchor = target.partition("#")
        where = os.path.normpath(os.path.join(os.path.dirname(path), file)) if file else path
        if not os.path.exists(where):
            problems.append(f"{os.path.relpath(path, ROOT)}: {target}: no such file")
        elif anchor and where.endswith(".md") and anchor not in {slug(h) for h in re.findall(r"^#+ (.*)$", read(where), re.M)}:
            problems.append(f"{os.path.relpath(path, ROOT)}: {target}: no such heading")
    return problems


class Pages(unittest.TestCase):
    def test_each_behavior_section_is_the_templates(self):
        source, pages = read(TEMPLATE), [path for path in PAGES if f"\n{SECTION}\n" in read(path)]
        self.assertTrue(pages, "no page has a Behavior section")
        for path in pages:
            with self.subTest(os.path.basename(path)):
                problem = behavior_problem(os.path.basename(path), read(path), source)
                if problem:
                    self.fail(problem)  # the section to paste, as it reads

    def test_each_library_page_has_a_behavior_section(self):
        for path in PAGES:
            if "## 2. Add the line" in read(path):
                with self.subTest(os.path.basename(path)):
                    self.assertIn(f"\n{SECTION}\n", read(path))

    def test_the_bedrock_page_says_what_a_signed_call_carries_to_reflexer(self):
        self.assertEqual(signed_unsaid(read(os.path.join(DOCS, "bedrock.md"))), [])

    def test_every_link_and_anchor_leads_somewhere(self):
        for path in PAGES:
            with self.subTest(os.path.relpath(path, ROOT)):
                self.assertEqual(link_problems(path, read(path)), [])


SIGNED = ("signature", "access key's id", "session token", "AWS secret")  # what P21 says a signed call carries, and does not


def signed_unsaid(page):
    """What the Bedrock page's Behavior section does not name, of what a signed call carries to reflexer (P21)."""
    return [each for each in SIGNED if each not in section(page)]


class Broken(unittest.TestCase):
    def test_a_page_whose_copy_drifted_turns_it_red(self):
        page, source = read(os.path.join(DOCS, "openai.md")), read(TEMPLATE)
        self.assertIsNone(behavior_problem("openai.md", page, source))
        drifted = page.replace("for about a minute at most", "for about two minutes at most", 1)
        self.assertNotEqual(drifted, page)
        self.assertIsNotNone(behavior_problem("openai.md", drifted, source))

    def test_a_signed_calls_carriage_unsaid_turns_it_red(self):
        page = read(os.path.join(DOCS, "bedrock.md"))
        self.assertEqual(signed_unsaid(page.replace("session token", "made-up")), ["session token"])

    def test_a_line_missing_or_added_turns_it_red(self):
        page, source = read(os.path.join(DOCS, "bedrock.md")), read(TEMPLATE)
        missing = re.sub(r"^- \*\*Mantle:\*\*.*\n", "", page, flags=re.M)
        added = page.replace("- **What stays the same:**", "- **Mantle:** made up.\n- **What stays the same:**", 1)
        for name, text in (("missing", missing), ("added", added)):
            with self.subTest(name):
                self.assertNotEqual(text, page)
                self.assertIsNotNone(behavior_problem("bedrock.md", text, source))

    def test_a_broken_link_or_anchor_turns_it_red(self):
        path = os.path.join(DOCS, "openai.md")
        for target in ("no-such-page.md", "limits.md#no-such-heading", "#no-such-heading"):
            with self.subTest(target):
                self.assertEqual(len(link_problems(path, f"[x]({target})")), 1)


if __name__ == "__main__":
    unittest.main()
