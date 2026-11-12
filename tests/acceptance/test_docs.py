"""The documentation's examples, each run as written: offline, over real sockets and TLS, against the suite's stand-ins
for reflexer and the providers, with made-up keys in the environment. Run: python -m unittest tests.acceptance.test_docs

Each code block in README.md and docs/ follows a comment saying what it must show (`node --test` runs the `js` ones):

    <!-- example: served -->    reflexer answers each call, and no call reaches the provider
    <!-- example: straight -->  the provider answers each call, and none reaches reflexer
    <!-- example: raises -->    the block raises, with no call made

Both stand-ins answer with the same made-up reply, `REPLY`, so a block's printed output is what the docs show. A
```text block right after a code block is its output: what the block prints, and the SDK's warnings, must be that, exactly; for
`raises`, its last line is the error. In each, a reply is printed for each call (unless an output is shown), no value printed is missing (None,
NaN), and the reflexer key reaches no provider. A share of calls (`sample`) is drawn at the middle of its range, so a
share below half goes straight. `bedrock` after the word runs the block twice: with a Bedrock API key in
`AWS_BEARER_TOKEN_BEDROCK`, and with none, its calls signed with made-up AWS credentials. A `diff` block, a change to
the reader's code, runs as it reads after the change, in the language its comment names: `<!-- example: served python -->`.
A `python`, `js` or `diff` block with no such comment fails, and so does a code block of any other language but `sh`
and an output's `text`, a word the comment does not know, or a fence of tildes, which no check reads.
"""
import contextlib, faulthandler, glob, io, logging, os, re, shutil, sys, tempfile, unittest, warnings
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [HERE, ROOT]
import harness  # noqa: E402
from harness import bedrock, certs, standins  # noqa: E402
from run import AMBIENT  # noqa: E402

DOCS = [os.path.join(ROOT, "README.md"), *sorted(glob.glob(os.path.join(ROOT, "docs", "**", "*.md"), recursive=True))]
BLOCK = re.compile(r"(?:<!-- example: ([a-z ]+) -->\n)?```(\w*)\n(.*?)^```\n(?:\n```text\n(.*?)^```\n)?", re.S | re.M)
OUTCOMES = ("served", "straight", "raises")
WORDS = {"bedrock", "python", "js"}
REPLY = "Hello! How can I help you today?"  # made up: both stand-ins' answer, in the docs' outputs
LIMIT = 60  # seconds a block may take: one that hangs ends the run, naming where it hung
WAYS = {"key": ({"AWS_BEARER_TOKEN_BEDROCK": bedrock.BEARER}, "Bearer"), "signed": ({}, "AWS4-HMAC-SHA256")}  # Bedrock's
ENVIRONMENT = bedrock.ENVIRONMENT | {
    "REFLEXER_KEY": harness.make_key(), "OPENAI_API_KEY": harness.PROVIDER_KEY["openai"],
    "ANTHROPIC_API_KEY": harness.PROVIDER_KEY["anthropic"], "GOOGLE_API_KEY": harness.PROVIDER_KEY["gemini"],
    "AZURE_OPENAI_API_KEY": harness.PROVIDER_KEY["azure"], "AZURE_OPENAI_ENDPOINT": harness.AZURE_ENDPOINT,
    "OPENAI_API_VERSION": harness.AZURE_VERSION}


def blocks():
    """(where, marker, language, code, output) of each code block in the docs; output None when none is shown."""
    for path in DOCS:
        with open(path) as doc:
            text = doc.read()
        if re.search(r"^\s*~~~", text, re.M):
            yield os.path.relpath(path, ROOT), None, "~~~", "", None
        for found in BLOCK.finditer(text):
            where, (marker, language, code, output) = f"{os.path.relpath(path, ROOT)}:{text.count(chr(10), 0, found.start()) + 1}", found.groups()
            if language == "diff":  # a change to the reader's code: run as it reads after, in the language its comment names
                language = next((word for word in (marker or "").split() if word in ("python", "js")), "diff")
                code = "\n".join(line[2:] for line in code.splitlines() if line[:1] in ("+", " ", "")) + "\n"  # "+ ", "  ": two marks
            yield where, marker, language, code, output


class Docs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(prefix="docs-")
        cls.addClassCleanup(shutil.rmtree, tmp)
        authority = certs.Certs(tmp, harness.NAMES)
        environment = mock.patch.dict(os.environ)  # the caller's, given back after
        environment.start()
        cls.addClassCleanup(environment.stop)
        for name in AMBIENT:
            os.environ.pop(name, None)
        os.environ["SSL_CERT_FILE"] = os.environ["AWS_CA_BUNDLE"] = authority.ca
        for name in ("SERVED_TEXT", "STRAIGHT_TEXT"):
            replies = mock.patch.object(standins, name, REPLY)
            replies.start()
            cls.addClassCleanup(replies.stop)
        harness.resolver.install()
        cls.world = harness.World((authority.context(), authority.untrusted()))  # one, so no block's leftovers reach a stand-in unseen

    def test_every_block_is_an_example_that_runs(self):
        found = [block for block in blocks() if block[2] != "sh"]
        self.assertTrue(any(language == "python" for _, _, language, _, _ in found), "no Python example found")
        for where, marker, language, code, output in found:
            self.assertIn(language, ("python", "js"), f"{where}: a code block must be python, js, diff or sh, fenced by backticks")
            words = (marker or "").split()
            self.assertTrue(words and words[0] in OUTCOMES and set(words[1:]) <= WORDS, f"{where}: no <!-- example: ... --> it knows")
            for way in (WAYS if "bedrock" in words else [None]) if language == "python" else ():
                with self.subTest(where, bedrock=way):
                    self.check(where, words[0], code, way, output)

    def test_a_planted_fault_turns_it_red(self):
        call = 'client.chat.completions.create(model="m", messages=[{"role": "user", "content": "Hi"}]).choices[0].message.content'
        converse = 'client.converse(modelId="m", messages=[{"role": "user", "content": [{"text": "Hi"}]}])'
        ours, stock = "import os, reflexer.openai\nclient = reflexer.openai.OpenAI(reflexer_key=os.environ['REFLEXER_KEY'])", "import openai\nclient = openai.OpenAI()"
        boto3 = "import os, reflexer.boto3\nclient = reflexer.boto3.client('bedrock-runtime', reflexer_key=os.environ['REFLEXER_KEY'])"
        planted = {  # name: (outcome, code, Bedrock's way, the output shown, the check that must fail)
            "a stock client, said to be served": ("served", f"{stock}\nprint({call})", None, None, "a call reached the provider"),
            "an answer not printed": ("served", f"{ours}\n{call}\nprint({call})", None, None, "a reply printed for each call"),
            "a call to reflexer, said to go straight": ("straight", f"{ours}\nprint({call})", None, None, "reflexer got the call"),
            "the reflexer key sent to a provider": ("straight", f"{stock}\nclient = client.with_options(default_headers={{'x-made-up': "
                                                                f"os.environ['REFLEXER_KEY']}})\nprint({call})", None, None, "the reflexer key reached a provider"),
            "a Bedrock key where a signed call is said": ("served", f"os.environ['AWS_BEARER_TOKEN_BEDROCK'] = {bedrock.BEARER!r}\n{boto3}\n"
                                                                    f"print({converse})", "signed", None, "not made the way asked"),
            "a call said to be Bedrock's, but not": ("served", f"{ours}\nprint({call})", "key", None, "not made the way asked"),
            "a value missing": ("served", f"{ours}\nprint({call}, client.chat.completions.with_raw_response.create(model='m', messages=[])"
                                          ".headers.get('Reflexer-Answerd-By'))", None, None, "a value printed is missing"),
            "a share that has no effect": ("straight", "import os, reflexer.openai\nclient = reflexer.openai.OpenAI(reflexer_key="
                                                       f"os.environ['REFLEXER_KEY'], sample=0.9)\nprint({call})", None, None, "reflexer got the call"),
            "an output not as shown": ("served", f"{ours}\nprint({call})\nprint('more')", None, f"{REPLY}\n", "the output is not as shown"),
            "an error not as shown": ("raises", "import reflexer.openai\nreflexer.openai.OpenAI(reflexer_key='rfx1_made-up')", None,
                                      "ValueError: a different message\n", "the error is not as shown"),
            "said to raise, but runs": ("raises", f"{ours}\nprint({call})", None, None, "did not raise"),
        }
        for name, (outcome, code, way, output, failure) in planted.items():
            with self.subTest(name), self.assertRaisesRegex(AssertionError, failure):
                self.check(name, outcome, f"import os\n{code}", way, output)

    def check(self, where, outcome, code, way, output):
        """`code` run in the world, what it printed and logged and what reached each stand-in judged by `outcome`, and
        compared with `output` when the docs show one."""
        world = self.world
        for standin in world.reflexer, world.provider:
            standin.seen.clear()
        environment, scheme = WAYS.get(way, ({}, None))
        out, raised = io.StringIO(), None
        logged = logging.StreamHandler(out)  # the SDK's own warnings, as a terminal shows them; other libraries' stderr is theirs
        logging.getLogger("reflexer").addHandler(logged)
        faulthandler.dump_traceback_later(LIMIT, exit=True)
        try:
            with mock.patch.dict(os.environ, ENVIRONMENT | environment), mock.patch("random.random", return_value=0.5), \
                 contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    exec(compile(code, where, "exec"), {"__name__": "__main__"})
                except Exception as error:
                    if outcome != "raises":
                        raise
                    raised = error
        finally:
            faulthandler.cancel_dump_traceback_later()
            logging.getLogger("reflexer").removeHandler(logged)
            if "reflexer.litellm" in sys.modules:  # LiteLLM's line is the process's: no block's reaches the next, nor another test
                bedrock.without_litellms_line()
        printed, reached, provided = out.getvalue(), world.reflexer.message_arrivals(), world.provider.message_arrivals()
        if outcome == "raises":
            self.assertIsNotNone(raised, "the block did not raise")
            self.assertEqual(reached + provided, [], "a call was made")
            if output is not None:
                self.assertEqual(f"{type(raised).__name__}: {raised}", output.strip().splitlines()[-1], "the error is not as shown")
            return
        if output is not None:
            self.assertEqual(printed.strip(), output.strip(), "the output is not as shown")
        self.assertIsNone(re.search(r"\b(None|NaN)\b", printed), f"a value printed is missing: {printed!r}")
        if output is None:  # an output shown already pins what is printed
            self.assertGreaterEqual(printed.count(REPLY), len(reached) + len(provided), f"a reply printed for each call: {printed!r}")
        if outcome == "served":
            self.assertEqual(provided, [], "a call reached the provider")
            self.assertTrue(reached, "reflexer got no call")
        else:
            self.assertEqual(reached, [], "reflexer got the call")
            self.assertTrue(provided, "the provider got no call")
        if scheme:
            calls = [arrival for arrival in reached + provided if bedrock.wire_of(arrival.path)]
            schemes = {arrival.headers.get("authorization", "").split(" ")[0] for arrival in calls}
            self.assertEqual(schemes, {scheme}, f"a Bedrock call not made the way asked: {schemes}")
        key = ENVIRONMENT["REFLEXER_KEY"]
        keyed = [arrival for arrival in world.provider.seen if key in f"{arrival.headers} {arrival.path} {arrival.body!r}"]
        self.assertEqual(keyed, [], "the reflexer key reached a provider")


if __name__ == "__main__":
    unittest.main()
