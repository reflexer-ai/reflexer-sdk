"""LangChain's classes, through reflexer, on its real packages over the HTTP library's mock transport; values made up.
Run: python -m unittest tests.test_langchain"""
import asyncio, gc, json, os, sys, unittest
from unittest import mock
from langchain_core.runnables import ConfigurableField

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import httpx, httpx2, openai
import langchain_openai
import reflexer, reflexer.openai, reflexer.transport
from reflexer.langchain_gemini import ChatGoogleGenerativeAI
from reflexer.langchain_openai import ChatOpenAI

SECRET = "rfx1_aaaaakq_" + "a" * 52
KEY = f"{SECRET}_{reflexer.checksum(SECRET)}"  # made up, of the form
REFLEXER = "api.reflexer.ai"
CHAT = {"id": "rfx-made-up", "object": "chat.completion", "created": 1, "model": "frontier-x-reflexer",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "made up"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4, "cost": 1.2e-05}}
GEMINI = {"candidates": [{"content": {"role": "model", "parts": [{"text": "made up"}]}, "finishReason": "STOP"}],
          "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1, "totalTokenCount": 4},
          "modelVersion": "frontier-z-reflexer", "responseId": "rfx-made-up"}


def world(body, reflexer_busy=False):
    """A handler answering every host, and the requests it got."""
    seen = []

    def handler(request):
        seen.append(request)
        library = httpx if isinstance(request, httpx.Request) else httpx2
        if reflexer_busy and request.url.host == REFLEXER:
            return library.Response(503, headers={"reflexer-status-origin": "reflexer"})
        ours = {"reflexer-status-origin": "reflexer", "reflexer-answered-by": "reflexer"} if request.url.host == REFLEXER else {}
        return library.Response(200, content=json.dumps(body).encode(), headers={"content-type": "application/json"} | ours)

    return handler, seen


def openai_chat(handler):
    own = dict(http_client=openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
               http_async_client=openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)))
    return ChatOpenAI(model="frontier-x", api_key="made-up", max_retries=0, reflexer_key=KEY, **own)


def azure_chat(handler):
    """LangChain's own class, given reflexer's HTTP clients for Azure by its public arguments."""
    own = dict(http_client=reflexer.openai.azure_http_client(KEY, own=openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler))),
               http_async_client=reflexer.openai.azure_async_http_client(
                   KEY, own=openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler))))
    return langchain_openai.AzureChatOpenAI(azure_endpoint="https://made-up.openai.azure.com", azure_deployment="made-up",
                                            api_version="2024-10-21", api_key="made-up", max_retries=0, **own)


def gemini_chat(handler):
    return ChatGoogleGenerativeAI(model="frontier-z", api_key="made-up", retries=1, reflexer_key=KEY,
                                  client_args={"transport": httpx.MockTransport(handler)})


def keyed_hosts(make, body):
    """The hosts that got the key, reflexer busy so the call falls back, sync and async."""
    handler, seen = world(body, reflexer_busy=True)
    chat = make(handler)
    chat.invoke("Hi")
    asyncio.run(chat.ainvoke("Hi"))
    return sorted({request.url.host for request in seen if "reflexer-key" in request.headers}), {r.url.host for r in seen}


class Lines(unittest.TestCase):
    def test_a_call_goes_to_reflexer_and_its_answer_back(self):
        for name, make, body in (("openai", openai_chat, CHAT), ("azure", azure_chat, CHAT), ("gemini", gemini_chat, GEMINI)):
            with self.subTest(name):
                handler, seen = world(body)
                chat = make(handler)
                self.assertEqual(chat.invoke("Hi").content, "made up")
                self.assertEqual(asyncio.run(chat.ainvoke("Hi")).content, "made up")
                self.assertEqual({request.url.host for request in seen}, {REFLEXER})

    def test_the_key_reaches_only_reflexer_through_langchain(self):
        for name, make, body in (("openai", openai_chat, CHAT), ("azure", azure_chat, CHAT), ("gemini", gemini_chat, GEMINI)):
            with self.subTest(name):
                keyed, hosts = keyed_hosts(make, body)
                self.assertEqual(keyed, [REFLEXER])
                self.assertGreater(len(hosts), 1, "it never fell back")

    def test_langchains_own_proxy_setting_is_taken_not_refused(self):
        with mock.patch.dict(os.environ, {"OPENAI_PROXY": "http://proxy.example:3128"}):
            ChatOpenAI(model="frontier-x", api_key="made-up", reflexer_key=KEY)
        ChatOpenAI(model="frontier-x", api_key="made-up", openai_proxy="", reflexer_key=KEY)

    def test_a_key_not_of_the_form_raises(self):
        with self.assertRaises(ValueError):
            ChatOpenAI(model="frontier-x", api_key="made-up", reflexer_key="rfx1_made_up")


def key_on_the_clients_own_request(real):
    def broken(way, request):
        request.headers["reflexer-key"] = KEY
        return real(way, request)
    return broken


class Configurable(unittest.TestCase):
    """LangChain's `configurable_fields` builds the class again from its fields: reflexer's clients among them, not its key."""

    def test_a_field_set_at_run_time_goes_to_reflexer(self):
        for name, make, body in (("openai", openai_chat, CHAT), ("gemini", gemini_chat, GEMINI)):
            with self.subTest(name):
                handler, seen = world(body)
                chat = make(handler).configurable_fields(temperature=ConfigurableField(id="temperature"))
                configured = chat.with_config(configurable={"temperature": 0.25})
                self.assertEqual(configured.invoke("Hi").content, "made up")
                self.assertEqual(asyncio.run(configured.ainvoke("Hi")).content, "made up")
                self.assertEqual({request.url.host for request in seen}, {REFLEXER})
                self.assertTrue(all("0.25" in request.content.decode() for request in seen))

    def test_a_model_built_again_keeps_the_options(self):
        sent = {"reflexer-answer": "false", "reflexer-store": "false", "reflexer-pass-through": "true", "reflexer-timeout-ms": "2500"}
        options = dict(reflexer_answer=False, reflexer_store=False, reflexer_pass_through=True, reflexer_timeout_ms=2500)
        makers = (("openai", lambda handler: ChatOpenAI(model="frontier-x", api_key="made-up", max_retries=0, reflexer_key=KEY, **options,
                                                         http_client=openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
                                                         http_async_client=openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler))),
                   CHAT),
                  ("gemini", lambda handler: ChatGoogleGenerativeAI(model="frontier-z", api_key="made-up", retries=1, reflexer_key=KEY, **options,
                                                                    client_args={"transport": httpx.MockTransport(handler)}), GEMINI))
        for name, make, body in makers:
            with self.subTest(name):
                handler, seen = world(body)
                chat = make(handler).configurable_fields(temperature=ConfigurableField(id="temperature"))
                chat.with_config(configurable={"temperature": 0.25}).invoke("Hi")
                self.assertEqual([{header: request.headers.get(header) for header in sent} for request in seen], [sent])

    def test_a_model_built_again_and_dropped_leaves_the_defaults_clients_open(self):
        """LangChain closes a dropped model's clients; stock, each model built again has its own."""
        handler, _ = world(GEMINI)
        chat = gemini_chat(handler)
        chat.invoke("Hi")
        chat.configurable_fields(temperature=ConfigurableField(id="temperature")).with_config(configurable={"temperature": 0.25}).invoke("Hi")
        gc.collect()
        inner = [made.inner for made in chat.client_args["transport"].made[False].values()]
        self.assertTrue(inner)
        self.assertFalse(any(client.is_closed for client in inner))

    def test_without_reflexers_clients_a_missing_key_still_raises(self):
        for make in (lambda: ChatOpenAI(model="frontier-x", api_key="made-up"),
                     lambda: ChatGoogleGenerativeAI(model="frontier-z", api_key="made-up")):
            with self.assertRaisesRegex(Exception, "not a reflexer key"):
                make()


class StreamedUsage(unittest.TestCase):
    """LangChain asks a stream for its usage, so its price, unless it was given an HTTP client: reflexer's class gives
    one, and keeps the choice the stock class makes for the client's own settings."""

    def settings(self):  # made anew for each class: LangChain edits what it is given
        return ({}, {"stream_usage": False}, {"stream_usage": None}, {"base_url": "https://gateway.example/v1"},
                {"openai_proxy": "http://proxy.example:3128"}, {"model_kwargs": {"made_up": 1}, "also_made_up": 2},
                {"model_kwargs": {"temperature": 0.5}})

    def test_reflexers_class_streams_usage_as_the_stock_class_would(self):
        for stock_settings, settings in zip(self.settings(), self.settings()):
            with self.subTest(settings):
                stock = langchain_openai.ChatOpenAI(model="frontier-x", api_key="made-up", **stock_settings)
                ours = ChatOpenAI(model="frontier-x", api_key="made-up", reflexer_key=KEY, **settings)
                self.assertEqual(ours._should_stream_usage(), stock._should_stream_usage())
                self.assertEqual((ours.model_kwargs, ours.temperature), (stock.model_kwargs, stock.temperature))


class Broken(unittest.TestCase):
    def test_the_key_on_the_clients_own_request_turns_it_red(self):
        with mock.patch.object(reflexer.transport, "to_reflexer", key_on_the_clients_own_request(reflexer.transport.to_reflexer)), \
                mock.patch.object(reflexer.transport, "OURS", "not-ours-"):
            for make, body in ((openai_chat, CHAT), (azure_chat, CHAT), (gemini_chat, GEMINI)):
                self.assertNotEqual(keyed_hosts(make, body)[0], [REFLEXER])


if __name__ == "__main__":
    unittest.main()
