"""The transport, offline on the HTTP library's own mock transport; all values made up.
Run: python -m unittest tests.test_transport
"""
import asyncio, os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import httpx, httpx2
import reflexer, reflexer.gemini
from reflexer.transport import setup_http_client

CHAT = "https://api.openai.com/v1/chat/completions"
WIRE = {"reflexer_path": "/openai", "provider": "https://api.openai.com", "calls": r"/v1/chat/completions$"}
SERVED = {"reflexer-request-id": "made-up", "reflexer-answered-by": "reflexer", "reflexer-cost": "12000", "reflexer-status-origin": "reflexer"}
BODY = {"id": "made-up", "usage": {"in": 1}}
SECRET = "rfx1_aaaaakq_" + "a" * 52
KEY = f"{SECRET}_{reflexer.checksum(SECRET)}"  # made up, of the form
LONG = 10**6  # seconds: past every wait


def wrapped(answer, library=httpx2, **settings):
    """Our HTTP client over a client's own, whose transport answers by `answer(request)`; what it saw, as a list."""
    seen = []

    def handler(request):
        seen.append(request)
        return answer(request)

    own = library.Client(transport=library.MockTransport(handler), **settings)
    return setup_http_client(None, WIRE)(KEY, own=own), seen, own


def served(request):
    return httpx2.Response(200, headers=SERVED, json=BODY)


def busy(request):
    if request.url.host == "api.reflexer.ai":
        return httpx2.Response(503, headers={"reflexer-status-origin": "reflexer"})
    return httpx2.Response(200, json={"from": "provider"}, headers={"set-cookie": "theirs=1; Domain=api.openai.com"})


class TheWire(unittest.TestCase):
    """The API writes what a client reads: the SDK only routes, and changes no answer."""
    STREAM = b'event: a\ndata: {"n": 1}\n\ndata: {"n": 2}\r\n\r\n: comment\ndata: [DONE]\n\n'

    def test_an_answers_json_is_the_body_as_it_came(self):
        client, _, _ = wrapped(served)
        self.assertEqual(client.post(CHAT, content=b"{}").json(), BODY)

    def test_a_streams_bytes_are_the_wires(self):
        def answer(request):
            return httpx2.Response(200, headers=SERVED | {"content-type": "text/event-stream"}, content=self.STREAM)

        client, _, _ = wrapped(answer)
        with client.stream("POST", CHAT, content=b"{}") as made:
            self.assertEqual(b"".join(made.iter_bytes()), self.STREAM)

    def test_gemini_wraps_no_method_of_its_client(self):
        client = reflexer.gemini.Client(reflexer_key=KEY, api_key="made-up")
        self.assertNotIn("_generate_content", vars(client.models))
        self.assertNotIn("_generate_content", vars(client.aio.models))


class Replay(unittest.TestCase):
    """A request carrying `replay_response` bypasses the upstream : to reflexer, or an error, never to the provider."""
    REPLAY = b'{"model": "frontier-x", "replay_response": {"id": "made-up"}}'

    def hosts(self, seen):
        return [request.url.host for request in seen]

    def test_reflexer_down_raises_and_nothing_reaches_the_provider(self):
        def down(request):
            if request.url.host == "api.reflexer.ai":
                raise httpx2.ConnectError("made up")
            return httpx2.Response(200, json=BODY)

        client, seen, _ = wrapped(down)
        with self.assertRaises(reflexer.ReplayNotTaken):
            client.post(CHAT, content=self.REPLAY)
        self.assertEqual(self.hosts(seen), ["api.reflexer.ai"])

    def test_reflexer_saying_go_straight_raises_and_nothing_reaches_the_provider(self):
        client, seen, _ = wrapped(busy)
        with self.assertRaises(reflexer.ReplayNotTaken):
            client.post(CHAT, content=self.REPLAY)
        self.assertEqual(self.hosts(seen), ["api.reflexer.ai"])

    def test_the_flag_to_skip_reflexer_raises_and_nothing_is_sent(self):
        client, seen, _ = wrapped(served)
        with self.assertRaises(reflexer.ReplayNotTaken):
            client.post(CHAT, content=self.REPLAY, headers={"reflexer-pass-through": "1"})
        self.assertEqual(seen, [])

    def test_sampling_and_an_open_breaker_do_not_drop_a_replay(self):
        own = httpx2.Client(transport=httpx2.MockTransport(served))
        client = setup_http_client(None, WIRE)(KEY, own=own, sample=0.0)
        self.assertEqual(client.post(CHAT, content=self.REPLAY).json(), BODY)
        client._transport.reflexer.breaker.open_for(LONG)
        self.assertEqual(client.post(CHAT, content=self.REPLAY).json(), BODY)

    def test_a_call_through_the_real_sdk_never_reaches_the_provider(self):
        import openai
        client, seen, _ = wrapped(busy)
        sdk = openai.OpenAI(api_key="made-up", http_client=client, max_retries=0)
        with self.assertRaises(Exception) as raised:  # openai 3.0 wraps it in its connection error; later releases do not
            sdk.chat.completions.create(model="frontier-x", messages=[], extra_body={"replay_response": {"id": "made-up"}})
        chain, error = [], raised.exception
        while error is not None:
            chain, error = chain + [type(error)], error.__cause__
        self.assertIn(reflexer.ReplayNotTaken, chain)
        self.assertEqual(self.hosts(seen), ["api.reflexer.ai"])

    def test_an_escaped_field_name_is_a_replay(self):
        self.assertTrue(reflexer.is_replay(b'{"replay\\u005fresponse": {"id": "made-up"}}'))

    def test_only_the_field_itself_is_a_replay(self):
        for body in (b'{"messages": [{"content": "\\"replay_response\\": 1"}]}', b'{"metadata": {"replay_response": 1}}',
                     b'"replay_response"', b'not json "replay_response"', b"", b"{}"):
            self.assertFalse(reflexer.is_replay(body), body)
        self.assertTrue(reflexer.is_replay(self.REPLAY))

    def test_a_plain_call_still_falls_back(self):
        client, seen, _ = wrapped(busy)
        self.assertEqual(client.post(CHAT, content=b"{}").json(), {"from": "provider"})
        self.assertEqual(self.hosts(seen), ["api.reflexer.ai", "api.openai.com"])


class Copies(unittest.TestCase):
    """The SDK's own copy, `with_options(http_client=...)`, keeps working and keeps going through reflexer."""

    def test_a_copy_given_its_own_http_client_goes_through_reflexer(self):
        import anthropic, openai
        import reflexer.anthropic, reflexer.openai
        for module, made, stock in ((reflexer.openai, lambda c: c.chat.completions.create(model="m", messages=[]), openai),
                                    (reflexer.anthropic, lambda c: c.messages.create(model="m", max_tokens=1, messages=[]), anthropic)):
            seen = []
            own = stock.DefaultHttpxClient(transport=httpx2.MockTransport(lambda r: (seen.append(r), served(r))[1]))
            cls = module.OpenAI if module is reflexer.openai else module.Anthropic
            copy = cls(api_key="made-up", reflexer_key=KEY, max_retries=0).with_options(http_client=own)
            try:
                made(copy)
            except Exception:
                pass  # the made-up body is no real answer; where it went is what is checked
            self.assertEqual([r.url.host for r in seen], ["api.reflexer.ai"], module.__name__)


class GeminisArguments(unittest.TestCase):
    def test_a_request_of_a_subclass_finds_its_library(self):
        class Mine(httpx2.Request):
            pass

        both = reflexer.gemini.client_args(KEY)["transport"]
        self.assertIsInstance(both.through(Mine("POST", "https://example.invalid/")).inner, httpx2.Client)

    def test_threads_at_first_use_share_one_client(self):
        import threading
        both, made = reflexer.gemini.client_args(KEY)["transport"], []
        threads = [threading.Thread(target=lambda: made.append(both.through(httpx2.Request("POST", "https://example.invalid/"))))
                   for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len({id(through) for through in made}), 1)

    def test_either_http_library_of_geminis_gets_its_own_kind_of_client(self):
        both = reflexer.gemini.client_args(KEY)["transport"]
        for library in (httpx, httpx2):
            inner = both.through(library.Request("POST", "https://example.invalid/")).inner
            self.assertIsInstance(inner, library.Client, library.__name__)


class Settings(unittest.TestCase):
    def test_the_namespace_holds_through_a_second_round(self):
        """An auth round sends the same request again: the first round must leave it whole."""
        from reflexer.transport import to_reflexer
        way = reflexer.Reflexer(KEY, {"reflexer_path": "/openai", "provider": "https://api.openai.com", "calls": r"/v1/chat/completions$"})
        request = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions", headers={"reflexer-namespace": "made-up"}, content=b"{}")
        for _ in range(2):
            self.assertEqual(to_reflexer(way, request).headers["reflexer-namespace"], "made-up")

    def test_params_and_cookies_of_the_client_go_on_both_legs(self):
        client, seen, _ = wrapped(busy, params={"mine": "kept"}, cookies={"mine": "kept"})
        client.post(CHAT, content=b"{}")
        self.assertEqual([r.url.host for r in seen], ["api.reflexer.ai", "api.openai.com"])
        for request in seen:
            self.assertEqual(request.url.params["mine"], "kept")
            self.assertIn("mine=kept", request.headers["cookie"])

    def test_a_cookie_set_on_a_clients_jar_later_is_sent(self):
        client, seen, own = wrapped(busy)
        own.cookies.set("later", "kept")
        client.post(CHAT, content=b"{}")
        self.assertIn("later=kept", seen[0].headers["cookie"])

    def test_the_clients_own_object_stays_as_it_was(self):
        hook = lambda request: None
        client, _, own = wrapped(served, event_hooks={"request": [hook]})
        self.assertEqual(own.event_hooks["request"], [hook])
        self.assertEqual(client.event_hooks["request"], [hook])

    def test_max_redirects_holds(self):
        def again(request):
            return httpx2.Response(302, headers={"location": "https://api.openai.com/again"})

        client, seen, _ = wrapped(again, follow_redirects=True, max_redirects=2)
        with self.assertRaises(httpx2.TooManyRedirects):
            client.get("https://api.openai.com/first")
        self.assertEqual(len(seen), 3)

    def test_the_legacy_library_gets_its_own_request_type(self):
        client, seen, _ = wrapped(lambda request: httpx.Response(200, headers=SERVED, json=BODY), library=httpx)
        self.assertEqual(client.post(CHAT, content=b"{}").json(), BODY)
        self.assertIsInstance(seen[0], httpx.Request)


class Ending(unittest.TestCase):
    def test_closing_closes_the_clients_transport_as_stock(self):
        closed = []

        class Mine(httpx2.MockTransport):
            def close(self):
                closed.append(True)

        made = setup_http_client(None, WIRE)(KEY, own=httpx2.Client(transport=Mine(served)))
        made.close()
        self.assertEqual(closed, [True])

    def test_with_on_a_client_already_used(self):
        own = httpx2.Client(transport=httpx2.MockTransport(served))
        own.post(CHAT, content=b"{}")
        with setup_http_client(None, WIRE)(KEY, own=own) as made:
            self.assertEqual(made.post(CHAT, content=b"{}").json(), BODY)

    def test_async_with_on_a_client_already_used(self):
        async def run():
            own = httpx2.AsyncClient(transport=httpx2.MockTransport(served))
            await own.post(CHAT, content=b"{}")
            async with setup_http_client(None, WIRE)(KEY, own=own) as made:
                return (await made.post(CHAT, content=b"{}")).json()

        self.assertEqual(asyncio.run(run()), BODY)


if __name__ == "__main__":
    unittest.main()
