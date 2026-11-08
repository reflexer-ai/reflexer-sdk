"""LiteLLM's line (SECURITY.md), `reflexer.litellm.through(key)`, through each provider whose wire reflexer takes, on
LiteLLM's real library over the acceptance suite's stand-ins in this process (real sockets and TLS, names resolved to this
machine only), sync and async, streamed and not; and each check shown red under a planted fault.
Offline, every key and answer made up. Run: python -m unittest tests.test_litellm"""
import asyncio, contextlib, json, os, socket, sys, tempfile, shutil, time, unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path[:0] = [os.path.join(ROOT, "tests", "acceptance"), ROOT]
import harness  # noqa: E402 the acceptance suite's stand-ins
from harness import bedrock, certs, standins  # noqa: E402
import litellm  # noqa: E402
from litellm.integrations.custom_logger import CustomLogger  # noqa: E402
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler, HTTPHandler  # noqa: E402
import reflexer.litellm  # noqa: E402

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
WAYS = [(is_async, stream) for is_async in (False, True) for stream in (False, True)]
GLOBALS = ("client_session", "aclient_session", "sync_transport")
CALLBACK_LISTS = ("callbacks", "input_callback", "success_callback", "failure_callback", "_async_success_callback",
                  "_async_failure_callback")  # where LiteLLM files each callback, on its first call after it is set
LOGGED_WAIT, LOGGED_POLL = 5.0, 0.01  # seconds a callback is waited on, at most


def setUpModule():
    SAVED.update(socket=(socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex), env=dict(os.environ))
    SAVED["folder"] = tempfile.mkdtemp(prefix="reflexer-litellm-")
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
        self.addCleanup(lambda: ([setattr(litellm, name, value) for name, value in saved.items()],
                                 [getattr(litellm, name).__setitem__(slice(None), value) for name, value in lists.items()],
                                 litellm.in_memory_llm_clients_cache.flush_cache()))
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
        given = dict(messages=MESSAGES, num_retries=0, timeout=10, stream=stream) | PROVIDERS[provider] | more

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
            reflexer.litellm.through(self.world.key)  # anew: a breaker closed
            self.world.reflexer.set(mode)
            for provider in PROVIDERS:
                for is_async, stream in WAYS:
                    with self.subTest(mode=mode, provider=provider, is_async=is_async, stream=stream):
                        self.assertEqual(self.ask(provider, is_async, stream), standins.STRAIGHT_TEXT)
        self.assertEqual(self.keyed_elsewhere(), [])

    def test_the_skip_goes_straight_and_never_leaves(self):
        reflexer.litellm.through(self.world.key)
        for provider in PROVIDERS:
            for is_async in (False, True):
                with self.subTest(provider=provider, is_async=is_async):
                    answer = self.ask(provider, is_async, extra_headers={harness.PASS_THROUGH: "1"})
                    self.assertEqual(answer, standins.STRAIGHT_TEXT)
        self.assertEqual([a for s in (self.world.reflexer, self.world.provider) for a in s.seen if harness.PASS_THROUGH.lower() in a.headers], [])
        self.assertEqual(self.world.reflexer.seen, [])

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
        reflexer.litellm.through(self.world.key)
        self.assertEqual(sum(isinstance(each, reflexer.litellm.Hook) for each in litellm.callbacks), 1)
        for provider in PROVIDERS:
            for is_async in (False, True):
                self.assertEqual(self.ask(provider, is_async), standins.SERVED_TEXT)
        self.assertEqual(len(self.world.reflexer.seen), 2 * len(PROVIDERS))  # one leg to reflexer each, never two
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

    def test_a_call_given_its_own_client_keeps_it(self):
        reflexer.litellm.through(self.world.key)
        own = AsyncHTTPHandler()
        self.assertEqual(self.ask("anthropic", True, client=own), standins.STRAIGHT_TEXT)
        self.assertEqual(self.world.reflexer.seen, [])

    def test_a_key_or_an_address_refused_changes_nothing(self):
        for way in (dict(reflexer_key="rfx1_made_up"), dict(reflexer_key=self.world.key, base="http://reflexer.example")):
            before = [getattr(litellm, name, None) for name in GLOBALS] + [list(litellm.callbacks)]
            with self.assertRaises(ValueError):
                reflexer.litellm.through(**way)
            self.assertEqual([getattr(litellm, name, None) for name in GLOBALS] + [list(litellm.callbacks)], before)

    def test_a_release_that_drops_its_sync_transport_fails_the_line_and_changes_nothing(self):
        """The setting dropped, or the private name the line reads it by renamed: the line fails as it runs, a line of ours
        run before it left as it was."""
        reflexer.litellm.through(self.world.key)
        before = [getattr(litellm, name, None) for name in GLOBALS] + [list(litellm.callbacks)]
        for dropped in (lambda self: None, lambda self: "another", None):
            with mock.patch.object(HTTPHandler, "_create_sync_transport", dropped), self.assertRaises((RuntimeError, AttributeError)):
                if dropped is None:
                    del HTTPHandler._create_sync_transport
                reflexer.litellm.through(self.world.key)
            self.assertEqual([getattr(litellm, name, None) for name in GLOBALS] + [list(litellm.callbacks)], before)


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

        def unused(self, inner, **way):
            real(self, inner, **way)
            if hasattr(inner._transport, "handle_request"):  # LiteLLM's own sync transport, as with no line
                self.handle_request = inner._transport.handle_request
        with mock.patch.object(reflexer.litellm.Wires, "__init__", unused):
            served = self.served_everywhere()
        self.assertEqual(sorted(way for way, ok in served.items() if not ok), sorted((provider, False, stream) for provider in PROVIDERS for stream in (False, True)))

    def test_a_wire_left_out_turns_its_provider_red(self):
        for left_out in reflexer.litellm.LINES:
            with self.subTest(wire=left_out[0]["reflexer_path"]), \
                    mock.patch.object(reflexer.litellm, "LINES", tuple(line for line in reflexer.litellm.LINES if line is not left_out)):
                served = self.served_everywhere()
                self.assertFalse(all(served.values()))

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

        def kept_below(self, inner, **way):
            real(self, inner, **way)
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
        self.assertEqual([arrival.headers.get("reflexer-upstream") for arrival in self.world.reflexer.seen], ["https://api.reflexer.ai/openai"])


if __name__ == "__main__":
    unittest.main()
