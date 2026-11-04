"""The SDK's behaviour promises (SECURITY.md), each checked, and each check shown red under a planted fault.
Offline, on the HTTP library's mock transport; every value made up. Run: python -m unittest tests.test_promises"""
import asyncio, os, sys, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import httpx, httpx2
import reflexer, reflexer.transport
from reflexer.transport import setup_http_client

SECRET = "rfx1_aaaaakq_" + "a" * 52
KEY = f"{SECRET}_{reflexer.checksum(SECRET)}"  # made up, of the form
WIRE = {"reflexer_path": "/openai", "provider": "https://api.openai.com", "calls": r"/v1/chat/completions$"}
CHAT = "https://api.openai.com/v1/chat/completions"
REFLEXER = "api.reflexer.ai"
REPLAY = b'{"model": "made-up", "replay_response": {"id": "made-up"}}'


def respond(request, status, **content):
    """An answer of the request's own HTTP library: httpx's or httpx2's."""
    library = httpx if isinstance(request, httpx.Request) else httpx2
    return library.Response(status, **content)


def through(answer, is_async=False, **settings):
    """Our HTTP client over a client's own; every request each host received."""
    seen = []

    def handler(request):
        seen.append(request)
        return answer(request)

    kind = httpx2.AsyncClient if is_async else httpx2.Client
    own = kind(transport=httpx2.MockTransport(handler), **settings)
    return setup_http_client(None, WIRE)(KEY, own=own), seen


def post(client, *args, **options):
    """`client.post`, run to its end on an async client too."""
    if isinstance(client, httpx2.AsyncClient):
        return asyncio.run(client.post(*args, **options))
    return client.post(*args, **options)


def busy(request):
    if request.url.host == REFLEXER:
        return respond(request, 503, headers={"reflexer-status-origin": "reflexer"})
    return respond(request, 200, json={"from": "provider"})


def down(request):
    if request.url.host == REFLEXER:
        raise (httpx if isinstance(request, httpx.Request) else httpx2).ConnectError("made up")
    return respond(request, 200, json={"from": "provider"})


def redirected(request):
    if request.url.host == REFLEXER:
        return respond(request, 307, headers={"location": "https://elsewhere.example/v1", "reflexer-status-origin": "reflexer"})
    return respond(request, 200, json={"from": "provider"})


def hook(seen, is_async):
    """A client's own request hook, recording the headers it saw."""
    async def async_record(request):
        seen.append(dict(request.headers))

    return async_record if is_async else (lambda request: seen.append(dict(request.headers)))


def hosts_given_the_key(is_async=False):
    """Every host that received the reflexer key, over a fallback, a redirect, and a client's own hook."""
    given, hooked = [], []
    for answer in (busy, down, redirected):
        client, seen = through(answer, is_async, follow_redirects=True, event_hooks={"request": [hook(hooked, is_async)]})
        post(client, CHAT, content=b"{}")
        given += [request.url.host for request in seen if "reflexer-key" in request.headers]
    given += ["a hook"] * sum("reflexer-key" in headers for headers in hooked)
    return sorted(set(given))


def a_replay_reached_the_provider(is_async=False):
    for answer in (busy, down):
        client, seen = through(answer, is_async)
        try:
            post(client, CHAT, content=REPLAY)
        except reflexer.ReplayNotTaken:
            pass
        if any(request.url.host != REFLEXER for request in seen):
            return True
    return False


def a_call_reflexer_could_not_take_reached_the_provider(is_async=False):
    for answer in (busy, down):
        client, _ = through(answer, is_async)
        try:
            if post(client, CHAT, content=b"{}").json() != {"from": "provider"}:
                return False
        except Exception:
            return False
    return True


def a_plain_http_address_for_reflexer_was_taken():
    try:
        reflexer.Reflexer(KEY, WIRE, base="http://api.reflexer.example")
        return True
    except ValueError:
        return False


def extensions_sent_to_reflexer(is_async=False):
    """What of the client's request extensions reach the request for reflexer, where a callback would see the key."""
    client, seen = through(busy, is_async)
    post(client, CHAT, content=b"{}", extensions={"trace": lambda name, info: None})
    return sorted(set().union(*(request.extensions for request in seen if request.url.host == REFLEXER)))


def each_sdk(answer):
    """Each provider SDK's own client, through reflexer, over a client's own HTTP client: (name, a call, what it received)."""
    import anthropic, openai
    import reflexer.anthropic, reflexer.gemini, reflexer.openai
    seen = []

    def handler(request):
        seen.append(request)
        return answer(request)

    on_httpx2 = dict(http_client=openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler)), max_retries=0)
    gpt = reflexer.openai.OpenAI(api_key="made-up", reflexer_key=KEY, **on_httpx2)
    claude = reflexer.anthropic.Anthropic(api_key="made-up", reflexer_key=KEY,
                                          **on_httpx2 | dict(http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler))))
    gemini = reflexer.gemini.Client(api_key="made-up", reflexer_key=KEY,
                                    http_options={"httpx_client": httpx.Client(transport=httpx.MockTransport(handler))})
    return [("openai", lambda extra: gpt.chat.completions.create(model="m", messages=[], extra_body=extra), seen),
            ("anthropic", lambda extra: claude.messages.create(model="m", max_tokens=1, messages=[], extra_body=extra), seen),
            ("gemini", lambda extra: gemini.models.generate_content(model="m", contents="x", config={"http_options": {"extra_body": extra}}), seen)]


def through_each_sdk(extra):
    """{sdk: the hosts that received a call, and whether they got the key}, reflexer busy."""
    found = {}
    for name, call, seen in each_sdk(busy):
        seen.clear()
        try:
            call(extra)
        except Exception:
            pass  # the made-up answers are no real ones; where the call went is what is checked
        found[name] = sorted({(request.url.host, "reflexer-key" in request.headers) for request in seen})
    return found


class Promises(unittest.TestCase):
    def test_the_key_reaches_only_reflexer(self):
        for is_async in (False, True):
            with self.subTest(is_async=is_async):
                self.assertEqual(hosts_given_the_key(is_async), [REFLEXER])

    def test_no_callback_of_the_clients_sees_reflexers_request(self):
        for is_async in (False, True):
            with self.subTest(is_async=is_async):
                self.assertEqual(extensions_sent_to_reflexer(is_async), ["timeout"])

    def test_a_replay_never_reaches_the_provider(self):
        for is_async in (False, True):
            with self.subTest(is_async=is_async):
                self.assertFalse(a_replay_reached_the_provider(is_async))

    def test_a_call_reflexer_does_not_take_still_reaches_the_provider(self):
        for is_async in (False, True):
            with self.subTest(is_async=is_async):
                self.assertTrue(a_call_reflexer_could_not_take_reached_the_provider(is_async))

    def test_reflexers_address_must_be_https(self):
        self.assertFalse(a_plain_http_address_for_reflexer_was_taken())

    def test_through_each_sdk_the_key_reaches_only_reflexer(self):
        for name, hosts in through_each_sdk({}).items():
            with self.subTest(sdk=name):
                self.assertEqual([host for host, keyed in hosts if keyed], [REFLEXER])
                self.assertIn((REFLEXER, True), hosts)

    def test_through_each_sdk_a_replay_never_reaches_the_provider(self):
        for name, hosts in through_each_sdk({"replay_response": {"id": "made-up"}}).items():
            with self.subTest(sdk=name):
                self.assertEqual({host for host, _ in hosts}, {REFLEXER})


def key_on_the_clients_own_request(real):
    def broken(way, request):
        request.headers["reflexer-key"] = KEY
        return real(way, request)
    return broken


class Broken(unittest.TestCase):
    """Each check above, red with one fault planted in the SDK."""

    def test_the_key_on_the_clients_own_request_turns_it_red(self):
        with mock.patch.object(reflexer.transport, "to_reflexer", key_on_the_clients_own_request(reflexer.transport.to_reflexer)), \
                mock.patch.object(reflexer.transport, "OURS", "not-ours-"):
            for is_async in (False, True):
                self.assertNotEqual(hosts_given_the_key(is_async), [REFLEXER], is_async)
            self.assertTrue(any(keyed and host != REFLEXER for hosts in through_each_sdk({}).values() for host, keyed in hosts))

    def test_hooks_given_the_key_turns_it_red(self):
        real = reflexer.transport.setup_http_client

        def keeps_hooks_below(stock, wire):
            made = real(stock, wire)

            def http_client(key, own=None, **way):
                outer = made(key, own=own, **way)
                outer._transport.inner.event_hooks = own.event_hooks
                return outer
            return http_client

        with mock.patch.object(sys.modules[__name__], "setup_http_client", keeps_hooks_below):
            self.assertIn("a hook", hosts_given_the_key())

    def test_the_clients_callbacks_on_reflexers_request_turns_it_red(self):
        with mock.patch.object(reflexer.transport, "KEPT", ("timeout", "trace")):
            for is_async in (False, True):
                self.assertIn("trace", extensions_sent_to_reflexer(is_async), is_async)

    def test_no_replay_guard_turns_it_red(self):
        with mock.patch.object(reflexer.transport, "is_replay", lambda body: False):
            for is_async in (False, True):
                self.assertTrue(a_replay_reached_the_provider(is_async), is_async)
            reached = through_each_sdk({"replay_response": {"id": "made-up"}})
            self.assertTrue(all({host for host, _ in hosts} != {REFLEXER} for hosts in reached.values()), reached)

    def test_no_fallback_turns_it_red(self):
        with mock.patch.object(reflexer.transport, "stays_straight", mock.Mock(side_effect=RuntimeError("made up"))):
            for is_async in (False, True):
                self.assertFalse(a_call_reflexer_could_not_take_reached_the_provider(is_async), is_async)

    def test_any_address_taken_turns_it_red(self):
        with mock.patch.object(reflexer, "checked_base", lambda base: base):
            self.assertTrue(a_plain_http_address_for_reflexer_was_taken())


if __name__ == "__main__":
    unittest.main()
