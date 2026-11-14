"""LiteLLM's line (SECURITY.md), `reflexer.litellm.through(key)`, through each provider whose wire reflexer takes, on
LiteLLM's real library over the acceptance suite's stand-ins in this process (real sockets and TLS, names resolved to this
machine only), sync and async, streamed and not; and each check shown red under a planted fault.
Offline, every key and answer made up. Run: python -m unittest tests.test_litellm"""
import asyncio, contextlib, json, os, socket, subprocess, sys, shutil, threading, time, unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path[:0] = [os.path.join(ROOT, "tests", "acceptance"), ROOT]
import harness, scratch  # noqa: E402 the acceptance suite's stand-ins and temp folders
from harness import bedrock, certs, standins  # noqa: E402
import litellm  # noqa: E402
from litellm.integrations.custom_logger import CustomLogger  # noqa: E402
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler, HTTPHandler  # noqa: E402
import reflexer.litellm, reflexer.transport  # noqa: E402

SAVED = {}
MESSAGES = [{"role": "user", "content": "Hi"}]
PROVIDERS = {  # each provider's call as a LiteLLM user writes it, with its own key; Gemini's model is one LiteLLM calls at v1beta
    "openai": dict(model="openai/frontier-x", api_key=harness.PROVIDER_KEY["openai"]),
    "azure": dict(model="azure/frontier-d", api_key=harness.PROVIDER_KEY["azure"], api_base=harness.AZURE_ENDPOINT, api_version=harness.AZURE_VERSION),
    "anthropic": dict(model="anthropic/frontier-y", api_key=harness.PROVIDER_KEY["anthropic"], max_tokens=8),
    "gemini": dict(model="gemini/gemini-2.5-flash", api_key=harness.PROVIDER_KEY["gemini"]),
    "bedrock": dict(model=f"bedrock/converse/{bedrock.MODEL}", api_key=bedrock.BEARER, aws_region_name=bedrock.REGION, max_tokens=8),
}
PROVIDER_KEY_HEADER = {"openai": "authorization", "azure": "api-key", "anthropic": "x-api-key", "gemini": "x-goog-api-key", "bedrock": "authorization"}
UPSTREAM = {"azure": harness.AZURE_ENDPOINT, "bedrock": f"https://{bedrock.RUNTIME}"}  # the rest: the provider's own, named by none
OTHERS = [  # LiteLLM's calls to other providers, at hosts the suite resolves to its stand-ins, on wires reflexer takes
    ("groq/frontier-x", dict(api_key="gsk-made-up")), ("openrouter/made-up/frontier-x", dict(api_key="or-made-up")),
    *[(model, dict(aws_region_name=bedrock.REGION, max_tokens=8) | auth) for model in ("bedrock_mantle/anthropic.frontier-b-made-up-v1:0", "bedrock_mantle/openai.frontier-o")
      for auth in (dict(api_key=bedrock.BEARER), dict(aws_access_key_id=bedrock.ACCESS_KEY, aws_secret_access_key=bedrock.SECRET))],
]
OWN_BASE = {"openai": "https://api.openai.com/v1"}  # a fallback's address where LiteLLM would carry the failing call's over; None: its default
WAYS = [(is_async, stream) for is_async in (False, True) for stream in (False, True)]
GLOBALS = ("client_session", "aclient_session", "sync_transport")
CALLBACK_LISTS = ("callbacks", "input_callback", "success_callback", "failure_callback", "_async_success_callback",
                  "_async_failure_callback")  # where LiteLLM files each callback, on its first call after it is set
NONE = object()  # an argument left out of a call
CALL_TIMEOUT = 1.5  # seconds, a call's own
LOOPS, LOOP_OVERLAP = 6, 0.5  # event loops at once, each its thread's, and seconds reflexer holds each answer so they overlap
LOGGED_WAIT, LOGGED_POLL = 5.0, 0.01  # seconds a callback is waited on, at most


def setUpModule():
    SAVED.update(socket=(socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex), env=dict(os.environ))
    SAVED["folder"] = scratch.folder("litellm")
    SAVED["certs"] = certs.Certs(SAVED["folder"], harness.NAMES)
    for name in bedrock.AMBIENT:
        os.environ.pop(name, None)
    os.environ.update(bedrock.ENVIRONMENT, SSL_CERT_FILE=SAVED["certs"].ca, AWS_CA_BUNDLE=SAVED["certs"].ca)
    harness.resolver.install()


def tearDownModule():
    socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = SAVED["socket"]
    os.environ.clear()
    os.environ.update(SAVED["env"])
    shutil.rmtree(SAVED["folder"], ignore_errors=True)


class World(unittest.TestCase):
    """Each test: stand-ins of its own, and LiteLLM as a process of its own starts, with none of the last test's clients
    and no line; what the line set is undone after it."""

    def setUp(self):
        self.world = harness.World((SAVED["certs"].context(), SAVED["certs"].untrusted()))
        self.addCleanup(self.close)
        saved = {name: getattr(litellm, name, None) for name in (*GLOBALS, "module_level_client")}
        lists = {name: list(getattr(litellm, name)) for name in CALLBACK_LISTS}
        self.addCleanup(lambda: (reflexer.litellm.dropped(), [setattr(litellm, name, value) for name, value in saved.items()],
                                 [getattr(litellm, name).__setitem__(slice(None), value) for name, value in lists.items()]))
        bedrock.without_litellms_line()  # a line another test of this process ran, as the docs' examples do

    def close(self):
        for standin in (self.world.reflexer, self.world.provider, self.world.elsewhere, self.world.runner):
            standin._cut_connections()
            standin._close()
        self.world.proxy.server.shutdown()
        self.world.proxy.server.server_close()

    def ask(self, provider, is_async=False, stream=False, logged=None, **more):
        """One call as a LiteLLM user writes it: its text, or the error it raised. `logged`: a callback's list, waited on
        till LiteLLM, which logs after the call returns, has handed it this call."""
        given = dict(messages=MESSAGES, num_retries=0, timeout=10, stream=stream) | PROVIDERS.get(provider, {}) | more
        given = {name: value for name, value in given.items() if value is not NONE}

        def text(chunks):
            return "".join((chunk.choices[0].delta.content or "") for chunk in chunks if chunk.choices)

        async def asked():
            answer = await litellm.acompletion(**given)
            said = text([chunk async for chunk in answer]) if stream else answer.choices[0].message.content
            while logged is not None and len(logged) <= heard and time.monotonic() < deadline:
                await asyncio.sleep(LOGGED_POLL)
            return said
        heard, deadline = len(logged or ()), time.monotonic() + LOGGED_WAIT
        try:
            if is_async:
                return asyncio.run(asked())
            answer = litellm.completion(**given)
            said = text(answer) if stream else answer.choices[0].message.content
            while logged is not None and len(logged) <= heard and time.monotonic() < deadline:
                time.sleep(LOGGED_POLL)
            return said
        except Exception as failure:
            return failure

    def keyed_elsewhere(self):
        """The arrivals, anywhere but reflexer, that carried the reflexer key."""
        key = self.world.key
        return [arrival for standin in (self.world.provider, self.world.elsewhere, self.world.runner) for arrival in standin.seen
                if any(key in value for value in arrival.headers.values()) or key.encode() in (arrival.body or b"")]


@contextlib.contextmanager
def logged():
    """A callback of the client's own: every `kwargs` LiteLLM hands it, as text, and its standard logging payload."""
    seen = []

    class Logger(CustomLogger):
        def log_success_event(self, kwargs, response_obj, start_time, end_time):
            seen.append(repr(kwargs) + json.dumps(kwargs.get("standard_logging_object"), default=str))

        async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
            self.log_success_event(kwargs, response_obj, start_time, end_time)
    logger = Logger()
    litellm.callbacks.append(logger)
    try:
        yield seen
    finally:
        litellm.callbacks.remove(logger)


class Line(World):
    def test_every_provider_sync_async_and_streamed_goes_through_reflexer_with_both_keys(self):
        reflexer.litellm.through(self.world.key)
        for provider in PROVIDERS:
            for is_async, stream in WAYS:
                with self.subTest(provider=provider, is_async=is_async, stream=stream):
                    before = len(self.world.reflexer.seen)
                    self.assertEqual(self.ask(provider, is_async, stream), standins.SERVED_TEXT)
                    arrival = self.world.reflexer.seen[before]
                    self.assertEqual(arrival.headers.get("reflexer-key"), self.world.key)
                    self.assertIn(PROVIDERS[provider]["api_key"], arrival.headers.get(PROVIDER_KEY_HEADER[provider], ""))
                    self.assertEqual(arrival.headers.get("reflexer-upstream"), UPSTREAM.get(provider))
        self.assertEqual(self.world.provider.seen, [])

    def test_reflexer_busy_or_dead_each_call_reaches_the_provider(self):
        for mode in ("busy", "dead"):
            self.world.reflexer.set(mode)
            for provider in PROVIDERS:
                for is_async, stream in WAYS:
                    with self.subTest(mode=mode, provider=provider, is_async=is_async, stream=stream):
                        reflexer.litellm.through(self.world.key)  # anew, its breaker closed: each call tries reflexer first
                        tried = len(self.world.reflexer.seen)
                        self.assertEqual(self.ask(provider, is_async, stream), standins.STRAIGHT_TEXT)
                        self.assertTrue(mode == "dead" or len(self.world.reflexer.seen) > tried)
        self.assertEqual(self.keyed_elsewhere(), [])

    def test_async_calls_in_several_event_loops_at_once_or_in_turn_are_served(self):
        """As stock LiteLLM keeps an async HTTP client per event loop: threads each running their own, at once, on aiohttp's
        transport; and loops one after the other on httpx's."""
        reflexer.litellm.through(self.world.key)
        self.world.reflexer.set("ok", delay=LOOP_OVERLAP)
        for provider in PROVIDERS:
            said = []
            threads = [threading.Thread(target=lambda: said.append(self.ask(provider, True))) for _ in range(LOOPS)]
            for each in threads:
                each.start()
            for each in threads:
                each.join()
            self.assertEqual(said, [standins.SERVED_TEXT] * LOOPS, provider)
        self.world.reflexer.set("ok")
        with mock.patch.object(litellm, "disable_aiohttp_transport", True):
            reflexer.litellm.through(self.world.key)
            for _ in range(LOOPS):
                for provider in PROVIDERS:
                    self.assertEqual(self.ask(provider, True), standins.SERVED_TEXT, provider)

    def test_after_litellms_own_cleanup_async_calls_still_go_through(self):
        """`close_litellm_async_clients`, LiteLLM's own, closes the clients it keeps, the line's among them, in that event
        loop: the next call makes the line's anew, as LiteLLM's handlers remake theirs; OpenAI's and Azure's session, the
        line's for the process, stays open; in that loop and the next."""
        reflexer.litellm.through(self.world.key)
        for provider in PROVIDERS:
            given = dict(messages=MESSAGES, num_retries=0, timeout=10) | PROVIDERS[provider]

            async def twice():
                first = (await litellm.acompletion(**given)).choices[0].message.content
                await litellm.close_litellm_async_clients()
                return first, (await litellm.acompletion(**given)).choices[0].message.content
            self.assertEqual(asyncio.run(twice()), (standins.SERVED_TEXT, standins.SERVED_TEXT), provider)
            self.assertEqual(self.ask(provider, True), standins.SERVED_TEXT, provider)  # a loop after it

    def test_an_event_loops_calls_share_one_client_kept_where_litellm_keeps_its_own(self):
        """One HTTP client of the line's per event loop, in LiteLLM's cache of its clients, which evicts and closes them
        as its own: none made per call, none kept past it."""
        reflexer.litellm.through(self.world.key)

        async def calls():
            return [(await litellm.acompletion(messages=MESSAGES, num_retries=0, **PROVIDERS[provider])).choices[0].message.content
                    for provider in PROVIDERS for _ in range(2)]
        for loops in (1, 2):
            self.assertEqual(set(asyncio.run(calls())), {standins.SERVED_TEXT})
            kept = [key for key in litellm.in_memory_llm_clients_cache.cache_dict if key.startswith("reflexer-litellm-")]
            self.assertEqual(len(kept), loops, kept)

    def test_an_async_call_naming_its_model_by_position_goes_through(self):
        reflexer.litellm.through(self.world.key)
        for provider in PROVIDERS:
            given = dict(PROVIDERS[provider])

            async def asked():
                return (await litellm.acompletion(given.pop("model"), messages=MESSAGES, num_retries=0, **given)).choices[0].message.content
            self.assertEqual(asyncio.run(asked()), standins.SERVED_TEXT, provider)

    def test_the_clients_own_transport_stays_open(self):
        closed = []

        class Own(__import__("httpx").HTTPTransport):
            def close(self):
                closed.append(self)
                super().close()
        litellm.sync_transport = Own()
        reflexer.litellm.through(self.world.key)
        reflexer.litellm.through(self.world.key)
        __import__("gc").collect()
        self.assertEqual(closed, [])
        self.assertEqual(self.ask("anthropic"), standins.SERVED_TEXT)

    def test_the_skip_goes_straight_and_never_leaves(self):
        reflexer.litellm.through(self.world.key)
        for provider in PROVIDERS:
            for is_async in (False, True):
                with self.subTest(provider=provider, is_async=is_async):
                    answer = self.ask(provider, is_async, extra_headers={harness.SKIP: "true"})
                    self.assertEqual(answer, standins.STRAIGHT_TEXT)
        self.assertEqual([a for s in (self.world.reflexer, self.world.provider) for a in s.seen if harness.SKIP.lower() in a.headers], [])
        self.assertEqual(self.world.reflexer.seen, [])

    def test_the_lines_namespace_and_options_reach_reflexer_and_a_calls_own_header_wins(self):
        """The line takes what every other line takes: each option, sent only when it differs from its default, on every
        call to reflexer; a call's own header of ours wins over the line's."""
        reflexer.litellm.through(self.world.key, namespace="team a", answer=True, store=False, pass_through=True, timeout_ms=1500)
        sent = {"reflexer-namespace": "team a", "reflexer-store": "false", "reflexer-pass-through": "true", "reflexer-timeout-ms": "1500"}
        for provider in PROVIDERS:
            for is_async in (False, True):
                with self.subTest(provider=provider, is_async=is_async):
                    self.world.reflexer.seen.clear()
                    self.assertEqual(self.ask(provider, is_async), standins.SERVED_TEXT)
                    self.assertEqual([{name: a.headers.get(name) for name in (*sent, "reflexer-answer")} for a in self.world.reflexer.seen],
                                     [sent | {"reflexer-answer": None}])
                    self.world.reflexer.seen.clear()
                    self.assertEqual(self.ask(provider, is_async, extra_headers={"Reflexer-Namespace": "call b"}), standins.SERVED_TEXT)
                    self.assertEqual([a.headers.get("reflexer-namespace") for a in self.world.reflexer.seen], ["call b"])
        self.assertEqual([a for a in self.world.provider.seen if any(name.startswith("reflexer-") for name in a.headers)], [])

    def test_a_wrong_option_is_refused_before_the_line_changes_anything(self):
        before = {name: getattr(litellm, name, None) for name in GLOBALS}
        for wrong in (dict(answer="no"), dict(store=0), dict(pass_through=None), dict(timeout_ms=0), dict(namespace="a\nb")):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                reflexer.litellm.through(self.world.key, **wrong)
        self.assertEqual({name: getattr(litellm, name, None) for name in GLOBALS}, before)

    def test_a_calls_wrong_header_of_ours_raises_before_anything_is_sent(self):
        """The old skip, `Reflexer-Pass-Through: 1`, and a skip neither true nor false: the call fails, and sends nothing."""
        reflexer.litellm.through(self.world.key)
        for headers in ({"Reflexer-Pass-Through": "1"}, {harness.SKIP: "yes"}):
            for provider in PROVIDERS:
                for is_async in (False, True):
                    with self.subTest(headers=headers, provider=provider, is_async=is_async):
                        self.assertIsInstance(self.ask(provider, is_async, extra_headers=headers), Exception)
        self.assertEqual([s.seen for s in (self.world.reflexer, self.world.provider, self.world.elsewhere)], [[], [], []])

    def test_a_wrong_header_of_ours_raises_on_another_providers_call_the_line_carries(self):
        """A sync call to another provider's host goes by the line's transport, as stock: a wrong header of ours fails it
        there, as on every other line, and it sends nothing."""
        reflexer.litellm.through(self.world.key)
        model, more = OTHERS[0]
        self.assertIsInstance(self.ask("other", model=model, extra_headers={"Reflexer-Pass-Through": "1"}, **more), Exception)
        self.assertEqual([s.seen for s in (self.world.reflexer, self.world.provider, self.world.elsewhere)], [[], [], []])

    def test_no_callback_of_the_clients_sees_the_key(self):
        reflexer.litellm.through(self.world.key)
        with logged() as seen:
            for provider in PROVIDERS:
                for is_async, stream in WAYS:
                    self.assertEqual(self.ask(provider, is_async, stream, logged=seen), standins.SERVED_TEXT, (provider, is_async, stream))
        self.assertGreaterEqual(len(seen), len(PROVIDERS) * len(WAYS))  # a streamed call is heard more than once
        self.assertEqual([text for text in seen if self.world.key in text], [])

    def test_the_clients_own_sessions_stay_theirs_and_their_hooks_never_see_the_key(self):
        heard = []
        litellm.client_session = __import__("httpx").Client(event_hooks={"request": [lambda request: heard.append(dict(request.headers))]},
                                                             headers={"x-made-up": "kept"})

        async def ahook(request):
            heard.append(dict(request.headers))
        litellm.aclient_session = __import__("httpx").AsyncClient(event_hooks={"request": [ahook]}, headers={"x-made-up": "kept"})
        theirs = (litellm.client_session, litellm.aclient_session)
        reflexer.litellm.through(self.world.key)
        for is_async in (False, True):
            self.assertEqual(self.ask("openai", is_async), standins.SERVED_TEXT)
        self.assertEqual(len(heard), 2)
        self.assertFalse(any(name.startswith("reflexer-") for headers in heard for name in headers), heard)
        self.assertTrue(all(arrival.headers.get("x-made-up") == "kept" for arrival in self.world.reflexer.seen))
        self.assertEqual((litellm.client_session.reflexer_own, litellm.aclient_session.reflexer_own), theirs)

    def test_run_again_it_takes_the_last_ones_place(self):
        reflexer.litellm.through(self.world.key)
        self.ask("anthropic")  # LiteLLM files each callback in its lists at a call
        reflexer.litellm.through(self.world.key)
        self.ask("anthropic")
        for name in ("callbacks", "input_callback"):
            self.assertEqual(sum(isinstance(each, reflexer.litellm.Hook) for each in getattr(litellm, name)), 1, name)
        self.world.reflexer.seen.clear()
        for provider in PROVIDERS:
            for is_async in (False, True):
                self.assertEqual(self.ask(provider, is_async), standins.SERVED_TEXT)
        self.assertEqual(len(self.world.reflexer.seen), 2 * len(PROVIDERS))  # one leg to reflexer each, never two
        self.assertEqual({arrival.headers.get("reflexer-key") for arrival in self.world.reflexer.seen}, {self.world.key})
        self.assertEqual({arrival.headers.get("reflexer-upstream") for arrival in self.world.reflexer.seen}, {None, *UPSTREAM.values()})  # never reflexer
        self.assertEqual([getattr(litellm, name).reflexer_own for name in GLOBALS], [None, None, None])

    def test_calls_made_before_the_line_go_through_after_it(self):
        """LiteLLM keeps the clients it made for reuse: the line drops them, so the next call makes them anew, by it."""
        for provider in PROVIDERS:
            for is_async, stream in WAYS:
                self.assertEqual(self.ask(provider, is_async, stream), standins.STRAIGHT_TEXT)
        reflexer.litellm.through(self.world.key)
        for provider in PROVIDERS:
            for is_async, stream in WAYS:
                with self.subTest(provider=provider, is_async=is_async, stream=stream):
                    self.assertEqual(self.ask(provider, is_async, stream), standins.SERVED_TEXT)

    def test_the_async_clients_dropped_by_the_line_are_closed_by_exit(self):
        """An async call before the line, by `module_level_aclient` as a streamed call's, its connection kept alive by the
        server; the line run after its event loop ended, or in it, with no yield after; then the process exits: every aiohttp
        session LiteLLM made before the line is closed by then, none is logged unclosed at exit, where LiteLLM's filter on
        asyncio's log fails ("sys.meta_path is None"), and no close is left undone in an event loop."""
        script = """import asyncio, atexit, sys, threading, aiohttp, litellm
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
made = []
atexit.register(lambda: print("open", sum(not session.closed for session in made)))  # run after the line's close at exit
import reflexer.litellm
class Kept(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # the connection kept alive, in aiohttp's pool
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        self.send_response(200)
        self.send_header("content-length", "2")
        self.end_headers()
        self.wfile.write(b"{}")
    def log_message(self, *args):
        pass
server = ThreadingHTTPServer(("127.0.0.1", 0), Kept)
threading.Thread(target=server.serve_forever, daemon=True).start()
def sessions():
    handlers = [*litellm.in_memory_llm_clients_cache.cache_dict.values(), litellm.module_level_aclient]
    found = [getattr(getattr(getattr(handler, "client", None), "_transport", None), "client", None) for handler in handlers]
    return [session for session in found if isinstance(session, aiohttp.ClientSession)]
async def asked(line):
    await litellm.module_level_aclient.post(f"http://127.0.0.1:{server.server_port}", json={})
    if line:
        made.extend(sessions())
        reflexer.litellm.through(sys.argv[2])
asyncio.run(asked(sys.argv[1] == "in its loop"))
if sys.argv[1] == "after its loop":
    made.extend(sessions())
    reflexer.litellm.through(sys.argv[2])
"""
        for where in ("after its loop", "in its loop"):
            done = subprocess.run([sys.executable, "-c", script, where, self.world.key], capture_output=True, text=True,
                                  timeout=60, cwd=ROOT, env=os.environ | {"PYTHONPATH": ROOT})
            self.assertEqual((done.returncode, done.stdout.split()[-2:]), (0, ["open", "0"]), (where, done.stdout, done.stderr))
            for logged in ("Unclosed client session", "sys.meta_path is None", "Task was destroyed", "was never awaited"):
                self.assertNotIn(logged, done.stderr, where)

    def test_the_clients_own_async_session_stays_open(self):
        """The line drops LiteLLM's client made around the client's own `aclient_session`, and leaves that session open."""
        theirs = litellm.aclient_session = __import__("httpx").AsyncClient()
        self.assertEqual(self.ask("openai", True), standins.STRAIGHT_TEXT)
        reflexer.litellm.through(self.world.key)
        self.assertFalse(theirs.is_closed)

    def test_litellms_clients_the_line_does_not_drop_stay_open(self):
        """LiteLLM's aiohttp handler for `aiohttp_openai/` models, which the line neither drops nor makes anew, stays open:
        a call made before the line is made again after it, in the same event loop (its session is of one loop), as before."""
        given = dict(model="aiohttp_openai/frontier-x", api_key=harness.PROVIDER_KEY["openai"], messages=MESSAGES, num_retries=0)

        async def twice():
            before = (await litellm.acompletion(**given)).choices[0].message.content
            reflexer.litellm.through(self.world.key)
            return before, (await litellm.acompletion(**given)).choices[0].message.content
        self.assertEqual(asyncio.run(twice()), (standins.STRAIGHT_TEXT, standins.STRAIGHT_TEXT))

    def test_litellms_module_level_aclient_is_made_anew_and_the_clients_own_stays(self):
        litellms = litellm.module_level_aclient  # made by LiteLLM, in its cache
        reflexer.litellm.through(self.world.key)
        self.assertIsNot(litellm.module_level_aclient, litellms)
        theirs = litellm.module_level_aclient = AsyncHTTPHandler()
        self.addCleanup(delattr, litellm, "module_level_aclient")
        reflexer.litellm.through(self.world.key)
        self.assertIs(litellm.module_level_aclient, theirs)

    def test_another_providers_call_never_reaches_reflexer(self):
        """Calls on a wire reflexer takes, at a host not the provider's: other providers of LiteLLM's, and Bedrock's Mantle,
        keyed or signed, go as stock; Azure's own domain on any of its routes goes by Azure's line."""
        reflexer.litellm.through(self.world.key)
        for model, given in OTHERS:
            for is_async in (False, True):
                with self.subTest(model=model, is_async=is_async):
                    self.ask(None, is_async, model=model, **given)
        self.assertEqual(self.world.reflexer.seen, [])
        self.assertTrue(self.world.provider.seen)
        wires = reflexer.litellm.Wires(__import__("httpx").Client(), reflexer.litellm.ways(self.world.key))
        for path in ("/openai/v1/chat/completions", "/openai/deployments/frontier-d/chat/completions", "/openai/responses"):
            line = wires.line_of(__import__("httpx").Request("POST", f"{harness.AZURE_ENDPOINT}{path}"), wires.now()[0])
            self.assertEqual(line.reflexer.way[0], "/azure", path)

    def test_litellms_own_fallbacks_to_another_provider_go_through(self):
        """`fallbacks=`, LiteLLM's own: from a provider on LiteLLM's handlers whose call fails (nothing listens at its
        address) to OpenAI or Azure, each given its address, as LiteLLM carries the failing call's over."""
        reflexer.litellm.through(self.world.key)
        for primary in reflexer.litellm.HANDLED:
            for fallback in ("openai", "azure"):
                given = dict(PROVIDERS[primary]) | dict(api_base="https://127.0.0.1:9/")

                async def failing_over():
                    return (await litellm.acompletion(messages=MESSAGES, num_retries=0, timeout=5, fallbacks=[other], **given)).choices[0].message.content
                other = {"api_base": OWN_BASE.get(fallback)} | PROVIDERS[fallback]  # its own, not the failing one's, which LiteLLM carries over
                with self.subTest(primary=primary, fallback=fallback):
                    self.assertEqual(asyncio.run(failing_over()), standins.SERVED_TEXT)

    def test_a_call_given_its_own_aiohttp_session_keeps_it(self):
        import aiohttp
        reflexer.litellm.through(self.world.key)

        async def asked():
            async with aiohttp.ClientSession() as own:
                return (await litellm.acompletion(messages=MESSAGES, num_retries=0, shared_session=own, **PROVIDERS["anthropic"])).choices[0].message.content
        self.assertEqual(asyncio.run(asked()), standins.STRAIGHT_TEXT)  # by the client's own session, as stock
        self.assertEqual(self.world.reflexer.seen, [])

    def test_an_openai_call_given_its_own_aiohttp_session_goes_by_the_lines(self):
        """LiteLLM takes `aclient_session`, the line's, before a call's `shared_session`: served, by ours (Known limits)."""
        import aiohttp
        reflexer.litellm.through(self.world.key)

        async def asked():
            async with aiohttp.ClientSession() as own:
                return (await litellm.acompletion(messages=MESSAGES, num_retries=0, shared_session=own, **PROVIDERS["openai"])).choices[0].message.content
        self.assertEqual(asyncio.run(asked()), standins.SERVED_TEXT)

    def test_each_request_of_an_async_call_has_its_timeout(self):
        """Gemini's context caching makes its own requests by the call's client, one with no timeout of LiteLLM's: each
        carries the call's, as stock's do. And Bedrock's converse route, which hands a given client none either."""
        import httpx
        timeouts, real = [], httpx.AsyncClient.send

        async def send(client, request, **options):
            if "cachedContents" in request.url.path:
                timeouts.append(request.extensions.get("timeout", {}).get("read"))
                return httpx.Response(200, json={"cachedContents": []} if request.method == "GET" else {"name": "cachedContents/made-up"}, request=request)
            return await real(client, request, **options)
        cached = [{"role": "system", "content": [{"type": "text", "text": "made up context " * 3000, "cache_control": {"type": "ephemeral"}}]},
                  {"role": "user", "content": "Hi"}]
        reflexer.litellm.through(self.world.key)
        with mock.patch.object(httpx.AsyncClient, "send", send):
            self.assertEqual(self.ask("gemini", True, messages=cached, timeout=CALL_TIMEOUT), standins.SERVED_TEXT)
        self.assertEqual(timeouts, [CALL_TIMEOUT, CALL_TIMEOUT])
        self.world.reflexer.set("stall")
        began = time.monotonic()
        self.assertEqual(self.ask("bedrock", True, timeout=CALL_TIMEOUT), standins.STRAIGHT_TEXT)
        self.assertLess(time.monotonic() - began, 2 * CALL_TIMEOUT + LOOP_OVERLAP)

    def test_a_replay_never_reaches_any_host_but_reflexer(self):
        """A call carrying `replay_response` at its body's top, reflexer busy: at its provider's host, or at a gateway or
        another provider, which the line does not take, by the line's clients, it raises; never reaches them."""
        reflexer.litellm.through(self.world.key)
        self.world.reflexer.set("busy")
        replay = {"extra_body": {"replay_response": {"id": "made-up"}}}
        for provider, more, ways in (("openai", {}, (False, True)), ("openai", {"api_base": "https://openrouter.ai/api/v1"}, (False, True)),
                                     (None, dict(OTHERS[1][1], model=OTHERS[1][0]), (False,))):  # another provider's async: as stock
            for is_async in ways:
                with self.subTest(provider=provider, more=more, is_async=is_async):
                    self.assertIsInstance(self.ask(provider, is_async, **replay, **more), Exception)
        self.assertEqual([arrival for arrival in self.world.provider.seen if b"replay_response" in (arrival.body or b"")], [])

    def test_an_async_calls_timeout_is_as_stock_resolves_it(self):
        """None given, the call's own, or one LiteLLM takes as text: what each request of the call is bounded by, as stock."""
        import httpx
        read, real = [], httpx.AsyncClient.send

        async def send(client, request, **options):
            if request.url.host != harness.REFLEXER_NAMES[0]:
                read.append(request.extensions.get("timeout", {}).get("read"))
            return await real(client, request, **options)

        def bounds(line, given):
            if line:
                reflexer.litellm.through(self.world.key)
            else:
                bedrock.without_litellms_line()
            read.clear()
            with mock.patch.object(httpx.AsyncClient, "send", send), mock.patch.object(litellm, "disable_aiohttp_transport", True):
                said = [self.ask(provider, True, **given) for provider in ("gemini", "bedrock")]
            return said, list(read)
        self.world.reflexer.set("busy")  # each call to the provider too, by the same handler
        for given in ({"timeout": NONE}, {"timeout": "5"}, {"timeout": CALL_TIMEOUT}):
            with self.subTest(given=given):
                (stock_said, stock_read), (said, ours) = bounds(False, given), bounds(True, given)
                self.assertEqual(said, stock_said)
                self.assertEqual(set(ours), set(stock_read))  # by its handler's client and the one under it

    def test_one_breaker_for_sync_and_async_calls(self):
        reflexer.litellm.through(self.world.key)
        self.world.reflexer.set("dead")
        self.assertEqual(self.ask("anthropic"), standins.STRAIGHT_TEXT)  # a failure: the breaker opens
        self.world.reflexer.set("ok")
        self.assertEqual(self.ask("anthropic", True), standins.STRAIGHT_TEXT)

    def test_a_call_given_its_own_client_keeps_it(self):
        reflexer.litellm.through(self.world.key)
        own = AsyncHTTPHandler()
        self.assertEqual(self.ask("anthropic", True, client=own), standins.STRAIGHT_TEXT)
        self.assertEqual(self.world.reflexer.seen, [])

    def test_the_line_warns_when_litellms_global_certificate_check_is_off(self):
        """Every call the line's HTTP client sends takes LiteLLM's global check, so with it off a call asking for the check
        is not checked: the line says so, by `litellm.ssl_verify` or by `SSL_VERIFY`, as LiteLLM reads them; on, silence."""
        self.addCleanup(setattr, litellm, "ssl_verify", litellm.ssl_verify)
        with self.assertNoLogs("reflexer", "WARNING"):
            reflexer.litellm.through(self.world.key)
        for off in (dict(attribute=False), dict(environment="false")):
            litellm.ssl_verify = off.get("attribute", True)
            with mock.patch.dict(os.environ, {"SSL_VERIFY": off["environment"]} if "environment" in off else {}), \
                    self.assertLogs("reflexer", "WARNING") as said:
                reflexer.litellm.through(self.world.key)
            self.assertIn("not checked", " ".join(said.output))

    def test_a_key_or_an_address_refused_changes_nothing(self):
        for way in (dict(reflexer_key="rfx1_made_up"), dict(reflexer_key=self.world.key, base="http://reflexer.example")):
            before = [getattr(litellm, name, None) for name in GLOBALS] + [list(litellm.callbacks)]
            with self.assertRaises(ValueError):
                reflexer.litellm.through(**way)
            self.assertEqual([getattr(litellm, name, None) for name in GLOBALS] + [list(litellm.callbacks)], before)

    def test_a_release_that_drops_its_sync_transport_fails_the_line_and_changes_nothing(self):
        """LiteLLM's handlers no longer sending by the setting, by their helper or past it: the line fails as it runs, a line
        of ours run before it left as it was, and nothing sent off this machine."""
        reflexer.litellm.through(self.world.key)
        before = [getattr(litellm, name, None) for name in GLOBALS] + [list(litellm.callbacks)]
        for name, dropped in (("_create_sync_transport", lambda self: None), ("create_client", lambda self: __import__("httpx").Client())):
            with mock.patch.object(HTTPHandler, name, dropped), mock.patch.dict(os.environ, ALL_PROXY=self.world.proxy.url), \
                    self.assertRaises(RuntimeError):
                reflexer.litellm.through(self.world.key)  # a proxy of the machine's set: the probe goes to none
            self.assertEqual([getattr(litellm, name, None) for name in GLOBALS] + [list(litellm.callbacks)], before)
        self.assertEqual((self.world.proxy.plain, self.world.proxy.tunnels), ([], []))


class Broken(World):
    """Each check above, red with one fault planted in the line."""

    def served_everywhere(self):
        reflexer.litellm.through(self.world.key)
        return {(provider, is_async, stream): self.ask(provider, is_async, stream) == standins.SERVED_TEXT
                for provider in PROVIDERS for is_async, stream in WAYS}

    def test_no_hook_turns_the_async_calls_on_litellms_handlers_red(self):
        async def none(self, kwargs, call_type):
            return kwargs
        with mock.patch.object(reflexer.litellm.Hook, "async_pre_call_deployment_hook", none):
            served = self.served_everywhere()
        self.assertEqual(sorted(way for way, ok in served.items() if not ok),
                         sorted((provider, True, stream) for provider in reflexer.litellm.HANDLED for stream in (False, True)))

    def test_no_transport_for_litellms_clients_turns_every_sync_call_red(self):
        real = reflexer.litellm.Wires.__init__

        def unused(self, inner, way):
            real(self, inner, way)
            if not callable(inner):  # a sync client: LiteLLM's own transport under it, as with no line, the line's probe aside
                ours = self.handle_request
                self.handle_request = lambda request: ours(request) if request.url.scheme == "reflexer-probe" else inner._transport.handle_request(request)
        with mock.patch.object(reflexer.litellm.Wires, "__init__", unused):
            served = self.served_everywhere()
        self.assertEqual(sorted(way for way, ok in served.items() if not ok), sorted((provider, False, stream) for provider in PROVIDERS for stream in (False, True)))

    def test_a_wire_left_out_turns_its_provider_red(self):
        for left_out in reflexer.litellm.LINES:
            provider = left_out[0]["reflexer_path"].strip("/")
            with self.subTest(wire=provider), \
                    mock.patch.object(reflexer.litellm, "LINES", tuple(line for line in reflexer.litellm.LINES if line is not left_out)):
                served = self.served_everywhere()
                self.assertEqual({way[0] for way, ok in served.items() if not ok}, {provider})

    def test_lines_picked_by_path_alone_turn_another_providers_call_red(self):
        with mock.patch.object(reflexer.litellm, "at", lambda host, where: True):  # any host
            reflexer.litellm.through(self.world.key)
            for model, given in OTHERS:
                self.ask(None, model=model, **given)
        self.assertTrue(self.world.reflexer.seen)

    def test_one_async_client_for_every_event_loop_turns_it_red(self):
        real = reflexer.litellm.Wires.now

        def shared(self):
            self.lines = self.lines or real(self)  # the first loop's, for every loop after it
            return self.lines
        with mock.patch.object(reflexer.litellm.Wires, "now", shared), mock.patch.object(litellm, "disable_aiohttp_transport", True):
            reflexer.litellm.through(self.world.key)
            said = [self.ask(provider, True) for _ in range(LOOPS) for provider in PROVIDERS]
        self.assertNotEqual(set(said), {standins.SERVED_TEXT})

    def test_the_model_read_by_name_only_turns_a_positional_one_red(self):
        given = dict(PROVIDERS["anthropic"])
        with mock.patch.object(reflexer.litellm, "provider", lambda kwargs: litellm.get_llm_provider(model=kwargs.get("model") or "")[1]
                               if kwargs.get("model") else None):
            reflexer.litellm.through(self.world.key)
            said = asyncio.run(litellm.acompletion(given.pop("model"), messages=MESSAGES, num_retries=0, **given)).choices[0].message.content
        self.assertEqual(said, standins.STRAIGHT_TEXT)

    def test_our_handler_carried_to_another_providers_fallback_turns_it_red(self):
        async def kept(self, kwargs, call_type):  # ours given, never taken back
            if call_type == "acompletion" and kwargs.get("client") is None and reflexer.litellm.provider(kwargs) in reflexer.litellm.HANDLED:
                kwargs["client"] = reflexer.litellm.Handler(transport=self.transport)
            return kwargs
        with mock.patch.object(reflexer.litellm.Hook, "async_pre_call_deployment_hook", kept):
            reflexer.litellm.through(self.world.key)

            async def failing_over():
                return await litellm.acompletion(messages=MESSAGES, num_retries=0, timeout=5, fallbacks=[PROVIDERS["openai"] | {"api_base": OWN_BASE["openai"]}],
                                                 **PROVIDERS["anthropic"] | {"api_base": "https://127.0.0.1:9/"})
            with self.assertRaises(Exception):
                asyncio.run(failing_over())

    def test_a_client_made_for_each_call_turns_it_red(self):
        with mock.patch.object(reflexer.litellm.Wires, "now", lambda self: self.lines or self.over(self.inner())):  # none kept
            reflexer.litellm.through(self.world.key)
            asyncio.run(litellm.acompletion(messages=MESSAGES, num_retries=0, **PROVIDERS["anthropic"]))
        self.assertEqual([key for key in litellm.in_memory_llm_clients_cache.cache_dict if key.startswith("reflexer-litellm-")], [])

    def test_a_replays_body_unread_turns_it_red(self):
        with mock.patch.object(reflexer.litellm, "body_of", lambda request: None):
            reflexer.litellm.through(self.world.key)
            self.world.reflexer.set("busy")
            self.ask("openai", api_base="https://openrouter.ai/api/v1", extra_body={"replay_response": {"id": "made-up"}})
        self.assertTrue([arrival for arrival in self.world.provider.seen if b"replay_response" in (arrival.body or b"")])

    def test_no_fallback_turns_it_red(self):
        with mock.patch.object(reflexer.transport, "stays_straight", mock.Mock(side_effect=RuntimeError("made up"))):
            reflexer.litellm.through(self.world.key)
            self.world.reflexer.set("busy")
            self.assertNotEqual(self.ask("anthropic"), standins.STRAIGHT_TEXT)

    def test_the_key_in_a_calls_metadata_turns_the_callbacks_red(self):
        key, real = self.world.key, reflexer.litellm.Hook.async_pre_call_deployment_hook

        async def carried(self, kwargs, call_type):  # the key carried to our handler in the call's own metadata
            return await real(self, kwargs | {"metadata": {"reflexer": key}}, call_type)
        with mock.patch.object(reflexer.litellm.Hook, "async_pre_call_deployment_hook", carried):
            reflexer.litellm.through(key)
            with logged() as seen:
                self.ask("anthropic", is_async=True, logged=seen)
        self.assertTrue(any(key in text for text in seen))

    def test_the_clients_hooks_kept_below_turn_it_red(self):
        heard = []
        theirs = litellm.client_session = __import__("httpx").Client(event_hooks={"request": [lambda request: heard.append(dict(request.headers))]})
        real = reflexer.litellm.Wires.__init__

        def kept_below(self, inner, way):
            real(self, inner, way)
            inner.event_hooks = theirs.event_hooks  # its hooks kept on the client under ours
        with mock.patch.object(reflexer.litellm.Wires, "__init__", kept_below):
            reflexer.litellm.through(self.world.key)
            self.ask("openai")
        self.assertTrue(any("reflexer-key" in headers for headers in heard), heard)

    def test_the_clients_kept_from_before_the_line_turn_it_red(self):
        for provider in PROVIDERS:
            self.ask(provider)
        with mock.patch.object(litellm.in_memory_llm_clients_cache, "flush_cache", lambda: None):
            reflexer.litellm.through(self.world.key)
        self.assertNotEqual({self.ask(provider) for provider in PROVIDERS}, {standins.SERVED_TEXT})

    def test_a_line_that_stacks_turns_it_red(self):
        with mock.patch.object(reflexer.litellm, "getattr", lambda thing, name, default=None: getattr(thing, name, default)
                               if name != "reflexer_own" else default, create=True):
            reflexer.litellm.through(self.world.key)
            reflexer.litellm.through(self.world.key)
            self.ask("openai")
        self.assertEqual([arrival.headers.get("reflexer-key") for arrival in self.world.reflexer.seen], [None])  # the line under ours took it off


if __name__ == "__main__":
    unittest.main()
