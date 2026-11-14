"""The transport, offline on the HTTP library's own mock transport; all values made up.
Run: python -m unittest tests.test_transport
"""
import asyncio, json, os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import httpx, httpx2
import reflexer, reflexer.gemini
from reflexer.transport import setup_http_client

CHAT = "https://api.openai.com/v1/chat/completions"
WIRE = {"reflexer_path": "/openai", "provider": "https://api.openai.com", "calls": r"/v1/chat/completions$"}
SERVED = {"reflexer-request-id": "made-up", "reflexer-answered-by": "reflexer", "reflexer-cost-nano-usd": "12000", "reflexer-status-origin": "reflexer"}
BODY = {"id": "made-up", "usage": {"in": 1}}
SECRET = "rfx1_aaaaakq_" + "a" * 52
KEY = f"{SECRET}_{reflexer.checksum(SECRET)}"  # made up, of the form
LONG = 10**6  # seconds: past every wait
HUNG_UP_WITHIN = 5  # seconds the stand-in is given to see a cancelled call's socket close


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

    def test_openais_wire_is_the_routed_one_the_logic_is_tested_on(self):
        import reflexer.openai
        from tests.test_logic import ROUTED
        self.assertEqual(reflexer.openai.CHAT, ROUTED)

    def test_gemini_wraps_no_method_of_its_client(self):
        client = reflexer.gemini.Client(reflexer_key=KEY, api_key="made-up")
        self.assertNotIn("_generate_content", vars(client.models))
        self.assertNotIn("_generate_content", vars(client.aio.models))


class Skip(unittest.TestCase):
    """`Reflexer-Skip` on one call: true goes straight, false goes to reflexer, any other value raises before anything
    is sent. It reaches no one; nor does another header of ours."""

    def test_true_goes_straight_and_the_header_reaches_no_one(self):
        client, seen, _ = wrapped(served)
        client.post(CHAT, content=b"{}", headers={"Reflexer-Skip": "TRUE"})
        self.assertEqual([request.url.host for request in seen], ["api.openai.com"])
        self.assertNotIn("reflexer-skip", seen[0].headers)

    def test_false_goes_to_reflexer_and_the_header_reaches_no_one(self):
        client, seen, _ = wrapped(busy)
        client.post(CHAT, content=b"{}", headers={"Reflexer-Skip": "False", "Reflexer-Made-Up": "1"})
        self.assertEqual([request.url.host for request in seen], ["api.reflexer.ai", "api.openai.com"])
        for request in seen:
            self.assertNotIn("reflexer-skip", request.headers)
            self.assertNotIn("reflexer-made-up", request.headers)

    def test_a_calls_option_headers_reach_reflexer_alone_and_a_wrong_one_raises_before_anything_is_sent(self):
        given = {"Reflexer-Answer": "false", "Reflexer-Store": "False", "Reflexer-Pass-Through": "TRUE", "Reflexer-Timeout-Ms": "100"}
        client, seen, _ = wrapped(busy)
        client.post(CHAT, content=b"{}", headers=given)
        self.assertEqual([(request.url.host, {name: request.headers.get(name) for name in given}) for request in seen],
                         [("api.reflexer.ai", given), ("api.openai.com", dict.fromkeys(given))])
        for library in (httpx, httpx2):
            for header, value in (("Reflexer-Answer", "no"), ("Reflexer-Store", "1"), ("Reflexer-Pass-Through", ""), ("Reflexer-Timeout-Ms", "0")):
                client, seen, _ = wrapped(served, library)
                with self.assertRaisesRegex(ValueError, f"^the {header} header must be ", msg=header):
                    client.post(CHAT, content=b"{}", headers={header: value})
                self.assertEqual(seen, [])

    def test_another_value_raises_and_nothing_is_sent(self):
        for library in (httpx, httpx2):
            client, seen, _ = wrapped(served, library)
            with self.assertRaises(ValueError) as raised:
                client.post(CHAT, content=b"{}", headers={"Reflexer-Skip": "1"})
            self.assertEqual(str(raised.exception), reflexer.NOT_A_SKIP)
            self.assertEqual(seen, [])

    def test_another_value_raises_on_an_async_client_and_nothing_is_sent(self):
        seen = []

        def handler(request):
            seen.append(request)
            return served(request)
        own = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        client = setup_http_client(None, WIRE)(KEY, own=own)
        with self.assertRaises(ValueError):
            asyncio.run(client.post(CHAT, content=b"{}", headers={"Reflexer-Skip": "maybe"}))
        self.assertEqual(seen, [])


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
            client.post(CHAT, content=self.REPLAY, headers={"Reflexer-Skip": "true"})
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


class EmptyAnswer(unittest.TestCase):
    """Reflexer asked not to answer: its empty 204, origin reflexer, is reflexer's answer, handed to the client's SDK as it
    came, never a call to the provider, streamed or not, sync or async."""
    EMPTY = {"reflexer-request-id": "made-up", "reflexer-cost": "0", "reflexer-status-origin": "reflexer"}  # no content-type

    def answer(self, request):
        if request.url.host == "api.reflexer.ai":
            return httpx2.Response(204, headers=self.EMPTY)
        return httpx2.Response(200, json={"from": "provider"})

    def test_it_reaches_the_client_as_it_came(self):
        client, seen, _ = wrapped(self.answer)
        made = client.post(CHAT, content=b"{}")
        self.assertEqual((made.status_code, made.content, made.headers.get("reflexer-cost")), (204, b"", "0"))
        self.assertEqual([request.url.host for request in seen], ["api.reflexer.ai"])

    def test_through_the_real_sdk_never_a_call_to_the_provider(self):
        import openai
        for stream in (False, True):
            client, seen, _ = wrapped(self.answer)
            sdk = openai.OpenAI(api_key="made-up", http_client=client, max_retries=0)
            made = sdk.chat.completions.create(model="frontier-x", messages=[], stream=stream)
            list(made) if stream else None
            self.assertEqual([request.url.host for request in seen], ["api.reflexer.ai"], f"stream {stream}")

    def test_async_through_the_real_sdk_never_a_call_to_the_provider(self):
        import openai
        for stream in (False, True):
            seen = []
            own = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda request: (seen.append(request), self.answer(request))[1]))
            client = setup_http_client(None, WIRE)(KEY, own=own)

            async def call():
                sdk = openai.AsyncOpenAI(api_key="made-up", http_client=client, max_retries=0)
                made = await sdk.chat.completions.create(model="frontier-x", messages=[], stream=stream)
                if stream:
                    [chunk async for chunk in made]
            asyncio.run(call())
            self.assertEqual([request.url.host for request in seen], ["api.reflexer.ai"], f"stream {stream}")


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


    def test_the_lines_options_reach_reflexer_alone_and_a_copy_keeps_them(self):
        import anthropic, openai
        import reflexer.anthropic, reflexer.openai
        options = dict(reflexer_answer=False, reflexer_store=False, reflexer_pass_through=True, reflexer_timeout_ms=2500)
        sent = {"reflexer-answer": "false", "reflexer-store": "false", "reflexer-pass-through": "true", "reflexer-timeout-ms": "2500"}
        for module, made, stock in ((reflexer.openai, lambda c: c.chat.completions.create(model="m", messages=[]), openai),
                                    (reflexer.anthropic, lambda c: c.messages.create(model="m", max_tokens=1, messages=[]), anthropic)):
            seen = []

            def busy_reflexer(request):
                seen.append(request)
                if request.url.host == "api.reflexer.ai":
                    return httpx2.Response(503, headers={"reflexer-status-origin": "reflexer"})
                return served(request)
            own = lambda: stock.DefaultHttpxClient(transport=httpx2.MockTransport(busy_reflexer))
            cls = module.OpenAI if module is reflexer.openai else module.Anthropic
            client = cls(api_key="made-up", reflexer_key=KEY, max_retries=0, http_client=own(), **options)
            for one in (client, client.with_options(http_client=own())):
                seen.clear()
                try:
                    made(one)
                except Exception:
                    pass  # the made-up body is no real answer; what each leg carried is what is checked
                self.assertEqual([(r.url.host, {name: r.headers.get(name) for name in sent}) for r in seen],
                                 [("api.reflexer.ai", sent),
                                  ("api.openai.com" if module is reflexer.openai else "api.anthropic.com", dict.fromkeys(sent))],
                                 module.__name__)
            with self.assertRaisesRegex(ValueError, "^reflexer_answer must be true or false"):
                cls(api_key="made-up", reflexer_key=KEY, reflexer_answer="false")

    def test_the_lines_namespace_reaches_reflexer_alone_and_a_copy_keeps_it(self):
        import anthropic, openai
        import reflexer.anthropic, reflexer.openai
        for module, made, stock in ((reflexer.openai, lambda c: c.chat.completions.create(model="m", messages=[]), openai),
                                    (reflexer.anthropic, lambda c: c.messages.create(model="m", max_tokens=1, messages=[]), anthropic)):
            seen = []

            def busy_reflexer(request):
                seen.append(request)
                if request.url.host == "api.reflexer.ai":
                    return httpx2.Response(503, headers={"reflexer-status-origin": "reflexer"})
                return served(request)
            own = lambda: stock.DefaultHttpxClient(transport=httpx2.MockTransport(busy_reflexer))
            cls = module.OpenAI if module is reflexer.openai else module.Anthropic
            client = cls(api_key="made-up", reflexer_key=KEY, reflexer_namespace="team-a", max_retries=0, http_client=own())
            for one in (client, client.with_options(http_client=own())):
                seen.clear()
                try:
                    made(one)
                except Exception:
                    pass  # the made-up body is no real answer; what each leg carried is what is checked
                self.assertEqual([(r.url.host, r.headers.get("reflexer-namespace")) for r in seen],
                                 [("api.reflexer.ai", "team-a"), ("api.openai.com" if module is reflexer.openai else "api.anthropic.com", None)],
                                 module.__name__)


class GeminiWithAiohttp(unittest.TestCase):
    """google-genai sends async calls by aiohttp when it is installed, unless given an HTTP client or a transport."""

    def calls_reach(self, make):
        import aiohttp  # installed, as a client may have it
        seen = []

        def handler(request):
            seen.append(request.url.host)
            return httpx.Response(503 if request.url.host == "api.reflexer.ai" else 200,
                                  headers={"reflexer-status-origin": "reflexer"} if request.url.host == "api.reflexer.ai" else {},
                                  json={"candidates": [{"content": {"role": "model", "parts": [{"text": "made up"}]}}]})

        client = make(handler)
        if client._api_client._use_aiohttp():  # google-genai's own choice, read so no call leaves this machine
            return ["aiohttp, past reflexer"]
        asyncio.run(client.aio.models.generate_content(model="m", contents="x"))
        return seen

    def test_reflexers_client_keeps_async_calls_on_reflexers_way(self):
        made = lambda handler: reflexer.gemini.Client(api_key="made-up", reflexer_key=KEY, http_options={
            "httpx_async_client": httpx.AsyncClient(transport=httpx.MockTransport(handler))})
        self.assertEqual(self.calls_reach(made)[0], "api.reflexer.ai")

    def test_the_stock_client_given_reflexers_arguments_does_too(self):
        from google import genai
        made = lambda handler: genai.Client(api_key="made-up", http_options={
            "client_args": reflexer.gemini.client_args(KEY, own={"transport": httpx.MockTransport(handler)}),
            "async_client_args": reflexer.gemini.client_args(KEY, own={"transport": httpx.MockTransport(handler)})})
        self.assertEqual(self.calls_reach(made)[0], "api.reflexer.ai")


    def test_a_sync_client_alone_leaves_async_calls_to_aiohttp_and_the_check_says_so(self):
        from google import genai
        made = lambda handler: genai.Client(api_key="made-up", http_options={
            "httpx_client": reflexer.gemini.http_client(KEY, own=httpx.Client(transport=httpx.MockTransport(handler)))})
        self.assertEqual(self.calls_reach(made), ["aiohttp, past reflexer"])


class GeminiContinuation(unittest.TestCase):
    """google-genai's automatic continuation, on by default: a reply ending in `CONTINUATION` with a token makes the
    library call again. Pins what the client reads of each call's headers (docs/limits.md); each hop answered
    with its own price, model and text."""

    def client(self, seen):
        def handler(request):
            hop = len(seen)
            seen.append(request.url.host)
            last = hop == 1
            candidate = {"content": {"role": "model", "parts": [{"text": f"part{hop} "}]},
                         "finishReason": "STOP" if last else "CONTINUATION"} | ({} if last else {"continuationToken": "bWFkZS11cA=="})
            body = {"candidates": [candidate], "modelVersion": f"m{hop}-reflexer",
                    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": hop + 1, "totalTokenCount": 11 + hop}}
            headers = {"reflexer-cost-nano-usd": str(1000 * (hop + 1)), "reflexer-request-id": f"made-up-{hop}",
                       "reflexer-answered-by": "reflexer", "reflexer-status-origin": "reflexer"}
            if "alt=sse" in str(request.url):
                return httpx.Response(200, headers=headers | {"content-type": "text/event-stream"},
                                      content=f"data: {json.dumps(body)}\n\n".encode())
            return httpx.Response(200, headers=headers, json=body)

        return reflexer.gemini.Client(api_key="made-up", reflexer_key=KEY, http_options={
            "httpx_client": httpx.Client(transport=httpx.MockTransport(handler)),
            "httpx_async_client": httpx.AsyncClient(transport=httpx.MockTransport(handler))})

    @staticmethod
    def read(reply):
        headers = reply.sdk_http_response.headers
        return (reply.text, headers["reflexer-cost-nano-usd"], headers["reflexer-request-id"], reply.model_version,
                reply.usage_metadata.total_token_count)

    def test_one_call_not_streamed_shows_only_the_last_http_calls_price_and_model_and_the_usage_summed(self):
        for name, call in (("sync", lambda c: c.models.generate_content(model="m", contents="x")),
                           ("async", lambda c: asyncio.run(c.aio.models.generate_content(model="m", contents="x")))):
            seen = []
            self.assertEqual(self.read(call(self.client(seen))), ("part0 part1 ", "2000", "made-up-1", "m1-reflexer", 23), name)
            self.assertEqual(seen, ["api.reflexer.ai"] * 2, name)

    def test_streamed_each_chunk_shows_its_own_http_calls_price_and_the_usage_so_far(self):
        async def chunks(client):
            return [chunk async for chunk in await client.aio.models.generate_content_stream(model="m", contents="x")]

        for name, call in (("sync", lambda c: list(c.models.generate_content_stream(model="m", contents="x"))),
                           ("async", lambda c: asyncio.run(chunks(c)))):
            seen = []
            self.assertEqual([self.read(chunk) for chunk in call(self.client(seen))],
                             [("part0 ", "1000", "made-up-0", "m0-reflexer", 11), ("part1 ", "2000", "made-up-1", "m1-reflexer", 23)], name)
            self.assertEqual(seen, ["api.reflexer.ai"] * 2, name)

    def test_turned_off_one_call_is_one_http_call_with_its_own_price(self):
        seen = []
        reply = self.client(seen).models.generate_content(model="m", contents="x", config={"automatic_continuation": False})
        self.assertEqual(self.read(reply), ("part0 ", "1000", "made-up-0", "m0-reflexer", 11))
        self.assertEqual(reply.candidates[0].continuation_token, b"made-up")
        self.assertEqual(seen, ["api.reflexer.ai"])


class GeminisArguments(unittest.TestCase):
    def test_a_request_of_a_subclass_finds_its_library(self):
        class Mine(httpx2.Request):
            pass

        both = reflexer.gemini.client_args(KEY)["transport"]
        self.assertIsInstance(both.through(Mine("POST", "https://example.invalid/")).inner, httpx2.Client)

    def test_its_clients_closed_by_one_genai_client_are_made_again_for_the_next(self):
        both = reflexer.gemini.client_args(KEY)["transport"]
        request = httpx.Request("POST", "https://example.invalid/")
        both.through(request)
        both.close()  # what one genai client does on its way out, when several share these arguments
        self.assertFalse(both.through(request).inner.is_closed)

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


class GeminiClosing(unittest.TestCase):
    """Reflexer's Gemini client closes as stock's does. On a real local socket kept alive: a mock transport holds no
    connection to close."""

    def setUp(self):
        import http.server, json, threading

        class Kept(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"  # the connection stays open, in the pool of the event loop that made it

            def do_POST(self):
                self.rfile.read(int(self.headers.get("content-length", 0)))
                body = json.dumps({"candidates": [{"content": {"role": "model", "parts": [{"text": "made up"}]}}]}).encode()
                self.send_response(200)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST

            def log_message(self, *_):
                pass

        self.servers = [http.server.ThreadingHTTPServer(("127.0.0.1", 0), Kept) for _ in range(2)]  # two origins, as reflexer and Google
        for server in self.servers:
            threading.Thread(target=server.serve_forever, daemon=True).start()
        self.server = self.servers[0]

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()

    def test_async_closed_in_a_later_event_loop_as_stock(self):
        """Its async calls made in one event loop, its close in a later one: as google-genai closes a client collected
        while a loop runs (`__del__`). Stock's aiohttp sessions of a loop that ended are left, not closed."""
        local = f"http://127.0.0.1:{self.server.server_port}"
        client = reflexer.gemini.Client(api_key="made-up", reflexer_key=KEY, reflexer_base=local, http_options={"base_url": local})
        self.assertEqual(asyncio.run(client.aio.models.generate_content(model="m", contents="x")).text, "made up")
        asyncio.run(client.aio.aclose())  # raises nothing

    def test_async_calls_in_one_event_loop_then_another_as_stock(self):
        """Two `asyncio.run`s on one client: stock keeps an HTTP session for each event loop, so the second loop's call
        never meets a connection of the first's. Reflexer's client, `client_args` given to stock's, and LangChain's."""
        from google import genai
        from reflexer.langchain_gemini import ChatGoogleGenerativeAI
        local = f"http://127.0.0.1:{self.server.server_port}"
        gemini = reflexer.gemini.Client(api_key="made-up", reflexer_key=KEY, reflexer_base=local, http_options={"base_url": local})
        shared = reflexer.gemini.client_args(KEY, base=local)
        stock = genai.Client(api_key="made-up", http_options={"base_url": local, "client_args": shared, "async_client_args": shared})
        chat = ChatGoogleGenerativeAI(model="m", api_key="made-up", retries=1, reflexer_key=KEY, reflexer_base=local, base_url=local)
        for name, call in (("gemini", lambda: gemini.aio.models.generate_content(model="m", contents="x")),
                           ("client_args", lambda: stock.aio.models.generate_content(model="m", contents="x")),
                           ("langchain", lambda: chat.ainvoke("x"))):
            with self.subTest(name):
                for _ in range(2):
                    self.assertIn("made up", str(asyncio.run(call())))

    def test_async_each_event_loops_client_closes_in_its_own_loop_as_stock(self):
        """As stock closes its sessions: an ended loop's is dropped, this loop's closed here, a running loop's in that loop."""
        import threading, time
        both = reflexer.gemini.client_args(KEY)["transport"]
        client, url = httpx.AsyncClient(transport=both), f"http://127.0.0.1:{self.server.server_port}/"
        asyncio.run(client.post(url, content=b"{}"))
        other = asyncio.new_event_loop()
        threading.Thread(target=other.run_forever, daemon=True).start()
        self.addCleanup(other.call_soon_threadsafe, other.stop)
        self.assertEqual(asyncio.run_coroutine_threadsafe(client.post(url, content=b"{}"), other).result(10).status_code, 200)
        self.assertEqual(len(both.made[True]), 1, "an ended loop's client was kept")
        made = []

        async def close_here():
            await client.post(url, content=b"{}")
            made.extend(both.made[True].values())  # the running loop's and this one's
            await client.aclose()
        asyncio.run(close_here())
        for _ in range(100):
            if all(through.inner.is_closed for through in made):
                break
            time.sleep(0.05)
        self.assertTrue(len(made) == 2 and all(through.inner.is_closed for through in made), "a loop's client was left open")

    def test_async_a_stopped_event_loops_client_is_dropped_as_an_ended_ones(self):
        """A loop stopped but not closed (`run_until_complete` done) runs nothing sent to it: its client is dropped, as stock
        drops its sessions of a loop that does not run, with no close left there never awaited."""
        import gc, warnings
        both = reflexer.gemini.client_args(KEY)["transport"]
        client, url = httpx.AsyncClient(transport=both), f"http://127.0.0.1:{self.server.server_port}/"
        stopped = asyncio.new_event_loop()
        self.assertEqual(stopped.run_until_complete(client.post(url, content=b"{}")).status_code, 200)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            asyncio.run(client.aclose())
            stopped.close()
            gc.collect()
        self.assertEqual([str(each.message) for each in caught if issubclass(each.category, RuntimeWarning)], [])

    def test_async_shared_arguments_closed_in_a_later_event_loop_as_stock(self):
        both = reflexer.gemini.client_args(KEY)["transport"]
        client = httpx.AsyncClient(transport=both)
        self.assertEqual(asyncio.run(client.post(f"http://127.0.0.1:{self.server.server_port}/", content=b"{}")).status_code, 200)
        asyncio.run(both.aclose())  # raises nothing

    def test_async_shared_arguments_closed_in_a_later_event_loop_cut_no_other_call(self):
        """One client's close, held for another's call in flight in a later event loop, runs as that call lands."""
        both = reflexer.gemini.client_args(KEY)["transport"]
        one, other = httpx.AsyncClient(transport=both), httpx.AsyncClient(transport=both)
        first, second = (f"http://127.0.0.1:{server.server_port}/" for server in self.servers)
        self.assertEqual(asyncio.run(one.get(first)).status_code, 200)

        async def in_flight():
            async with other.stream("GET", second) as answer:
                await one.aclose()
                return answer.status_code, await answer.aread()
        self.assertEqual(asyncio.run(in_flight())[0], 200)

    def test_any_other_failure_to_close_is_raised(self):
        class Failing:
            async def aclose(self):
                raise RuntimeError("made up")
        with self.assertRaises(RuntimeError):
            asyncio.run(reflexer.transport.closed_unless_its_loop_ended(Failing()))


class SharedArguments(unittest.TestCase):
    """Two clients made from one `client_args`, as stock each closing its own: one closing cuts nothing of the other's
    in flight. On a real local socket: closing a mock transport cuts nothing."""

    def setUp(self):
        import http.server, threading
        self.go_on = threading.Event()
        self.hung_up = threading.Event()
        go_on, hung_up = self.go_on, self.hung_up

        class Slow(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    if self.path == "/hold":  # no headers until let go
                        go_on.wait(10)
                    self.send_response(200)
                    self.send_header("content-length", "8")
                    self.end_headers()
                    self.wfile.write(b"made")
                    self.wfile.flush()
                    go_on.wait(10)
                    self.wfile.write(b"-up!")
                except (BrokenPipeError, ConnectionResetError):
                    if self.path != "/hold":
                        raise
                    hung_up.set()  # the client closed its socket: what a cancelled call does

            def log_message(self, *_):
                pass

        class Recording(http.server.ThreadingHTTPServer):
            def handle_error(self, request, client_address):  # the default prints the traceback to stderr
                self.errors.append(sys.exc_info()[1])

        self.server = Recording(("127.0.0.1", 0), Slow)
        self.server.errors = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/slow"  # no message call: it goes straight, by our clients

    def tearDown(self):
        self.go_on.set()
        self.server.shutdown()
        self.server.server_close()
        self.assertEqual(self.server.errors, [], "the stand-in's handler raised")

    def test_one_closing_leaves_the_others_call_in_flight_whole(self):
        both = reflexer.gemini.client_args(KEY)["transport"]
        one, other = httpx.Client(transport=both), httpx.Client(transport=both)
        with one.stream("GET", self.url) as answer:
            parts = answer.iter_bytes()
            first = next(parts)
            shared = list(both.made[False].values())
            other.close()
            self.go_on.set()
            self.assertEqual(first + b"".join(parts), b"made-up!")
        one.close()
        self.assertTrue(shared and all(made.inner.is_closed for made in shared), "a retired client was left open")

    def test_async_one_closing_leaves_the_others_call_in_flight_whole(self):
        async def run():
            both = reflexer.gemini.client_args(KEY)["transport"]
            one, other = httpx.AsyncClient(transport=both), httpx.AsyncClient(transport=both)
            async with one.stream("GET", self.url) as answer:
                parts = answer.aiter_bytes()
                first = await parts.__anext__()
                shared = list(both.made[True].values())
                await other.aclose()
                self.go_on.set()
                body = first + b"".join([part async for part in parts])
            await one.aclose()
            return body, bool(shared) and all(made.inner.is_closed for made in shared)

        self.assertEqual(asyncio.run(run()), (b"made-up!", True))


    def dead_port(self):
        import socket
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0))
            return f"http://127.0.0.1:{free.getsockname()[1]}/"  # closed again: nothing listens

    def test_a_failed_call_raises_its_own_error(self):
        both = reflexer.gemini.client_args(KEY)["transport"]
        with self.assertRaises(httpx.ConnectError):
            httpx.Client(transport=both).get(self.dead_port())

        async def run():
            await httpx.AsyncClient(transport=both).get(self.dead_port())
        with self.assertRaises(httpx.ConnectError):
            asyncio.run(run())

    def test_a_cancelled_call_stays_cancelled(self):
        async def run():
            client = httpx.AsyncClient(transport=reflexer.gemini.client_args(KEY)["transport"])
            task = asyncio.ensure_future(client.get(self.url.replace("/slow", "/hold")))
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            finally:
                await client.aclose()
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(run())
        self.go_on.set()  # the stand-in writes to the closed socket
        self.assertTrue(self.hung_up.wait(HUNG_UP_WITHIN), "the client never hung up")

    def test_a_call_racing_a_close_is_sent_on_an_open_client(self):
        import threading
        self.go_on.set()
        both = reflexer.gemini.client_args(KEY)["transport"]
        one, other = httpx.Client(transport=both), httpx.Client(transport=both)
        one.get(self.url)  # its HTTP clients made
        real, paused, resume = both.lock, threading.Event(), threading.Event()

        class Held:  # the racing call held at the lock until the other client has closed
            def __enter__(self):
                if threading.current_thread().name == "racing":
                    paused.set()
                    resume.wait(10)
                return real.__enter__()

            def __exit__(self, *failure):
                return real.__exit__(*failure)
        both.lock, got = Held(), []
        racing = threading.Thread(target=lambda: got.append(one.get(self.url).content), name="racing")
        racing.start()
        paused.wait(10)
        other.close()
        resume.set()
        racing.join(10)
        self.assertEqual(got, [b"made-up!"])

    def test_a_body_dropped_unclosed_lets_the_retired_client_close(self):
        import gc
        self.go_on.set()
        both = reflexer.gemini.client_args(KEY)["transport"]
        one, other = httpx.Client(transport=both), httpx.Client(transport=both)
        answer = one.send(one.build_request("GET", self.url), stream=True)
        shared = list(both.made[False].values())
        other.close()
        del answer
        gc.collect()
        self.assertTrue(shared and all(made.inner.is_closed for made in shared), "a dropped body kept a retired client open")

    def test_async_a_body_dropped_unclosed_lets_the_retired_client_close(self):
        import gc
        self.go_on.set()

        async def run():
            both = reflexer.gemini.client_args(KEY)["transport"]
            one, other = httpx.AsyncClient(transport=both), httpx.AsyncClient(transport=both)
            answer = await one.send(one.build_request("GET", self.url), stream=True)
            shared = list(both.made[True].values())
            await other.aclose()
            del answer
            gc.collect()
            await one.get(self.url)  # the next call closes what a dropped body left due
            return bool(shared) and all(made.inner.is_closed for made in shared)
        self.assertTrue(asyncio.run(run()), "a dropped body kept a retired client open")


    def test_async_a_retired_client_of_a_running_loop_closes_in_that_loop(self):
        """A body dropped in one running loop leaves its retired client due: another loop's next call sends its close there,
        as `aclose` does, and does not close it in its own."""
        import gc, threading
        self.go_on.set()
        both = reflexer.gemini.client_args(KEY)["transport"]
        one, other = httpx.AsyncClient(transport=both), httpx.AsyncClient(transport=both)
        running, closed_in = asyncio.new_event_loop(), []
        threading.Thread(target=running.run_forever, daemon=True).start()
        self.addCleanup(running.call_soon_threadsafe, running.stop)

        async def drop_and_close():
            answer = await one.send(one.build_request("GET", self.url), stream=True)
            for through in both.made[True].values():
                real = through.inner.aclose

                async def recorded(real=real):
                    closed_in.append(asyncio.get_running_loop())
                    await real()
                through.inner.aclose = recorded
            await other.aclose()
            del answer
            gc.collect()
        asyncio.run_coroutine_threadsafe(drop_and_close(), running).result(10)
        self.assertEqual(len(both.overdue), 1)

        async def next_call():
            return (await one.get(self.url)).content
        self.assertEqual(asyncio.run(next_call()), b"made-up!")
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0.1), running).result(10)  # what was sent there has run
        self.assertEqual(closed_in, [running], "a running loop's client was closed elsewhere, or not at all")

    def test_async_a_retired_client_of_a_finished_loop_does_not_fail_the_next_call(self):
        """Its close comes due in a loop that ended: what fails closing it is no call's of the next loop."""
        import gc
        self.go_on.set()
        both = reflexer.gemini.client_args(KEY)["transport"]
        one, other = httpx.AsyncClient(transport=both), httpx.AsyncClient(transport=both)

        async def drop_and_close():
            await one.send(one.build_request("GET", self.url), stream=True)
            await other.aclose()
        asyncio.run(drop_and_close())
        gc.collect()

        async def next_call():
            return (await one.get(self.url)).content
        self.assertEqual(asyncio.run(next_call()), b"made-up!")


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
