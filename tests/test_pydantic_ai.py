"""Pydantic AI, given reflexer's clients by its own public arguments: no code of reflexer's for it. On its real package
over the HTTP library's mock transport; values made up. Run: python -m unittest tests.test_pydantic_ai"""
import asyncio, os, sys, unittest

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import anthropic, httpx, httpx2, openai
import reflexer.anthropic, reflexer.gemini, reflexer.openai
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from tests.test_langchain import CHAT, GEMINI, KEY, REFLEXER, world

RESPONSE = {"id": "rfx-made-up", "object": "response", "created_at": 1, "status": "completed", "model": "frontier-x-reflexer",
            "output": [{"type": "message", "id": "msg-made-up", "status": "completed", "role": "assistant",
                        "content": [{"type": "output_text", "text": "made up", "annotations": []}]}],
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
            "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4, "cost": 1.2e-05,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}
MESSAGE = {"id": "rfx-made-up", "type": "message", "role": "assistant", "model": "frontier-y-reflexer",
           "content": [{"type": "text", "text": "made up"}], "stop_reason": "end_turn", "stop_sequence": None,
           "usage": {"input_tokens": 3, "output_tokens": 1, "cost": 1.2e-05}}
# Pydantic AI's last release for Python 3.10 fails an Anthropic call with the stock client too, before sending it
STOCK_FAILS = {"anthropic": sys.version_info < (3, 11)}


def openai_model(kind):
    def make(handler):
        own = openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler))
        client = reflexer.openai.AsyncOpenAI(api_key="made-up", max_retries=0, http_client=own, reflexer_key=KEY)
        return kind("frontier-x", provider=OpenAIProvider(openai_client=client))
    return make


def messages(handler):
    own = anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler))
    client = reflexer.anthropic.AsyncAnthropic(api_key="made-up", max_retries=0, http_client=own, reflexer_key=KEY)
    return AnthropicModel("frontier-y", provider=AnthropicProvider(anthropic_client=client))


def gemini(handler):
    own = {"transport": httpx.MockTransport(handler)}
    client = reflexer.gemini.Client(api_key="made-up", http_options={"async_client_args": own}, reflexer_key=KEY)
    return GoogleModel("frontier-z", provider=GoogleProvider(client=client))


MODELS = (("openai chat", openai_model(OpenAIChatModel), CHAT), ("openai responses", openai_model(OpenAIResponsesModel), RESPONSE),
          ("anthropic", messages, MESSAGE), ("gemini", gemini, GEMINI))


def run(model):
    return asyncio.run(Agent(model).run("Hi"))


class PydanticAI(unittest.TestCase):
    def test_a_call_goes_to_reflexer_and_its_answer_back(self):
        for name, make, body in MODELS:
            with self.subTest(name):
                if STOCK_FAILS.get(name):
                    self.skipTest("fails with the stock client too, on this Python")
                handler, seen = world(body)
                result = run(make(handler))
                self.assertEqual(result.output, "made up")
                self.assertTrue(result.response.model_name.endswith("-reflexer"))
                self.assertEqual({request.url.host for request in seen}, {REFLEXER})

    def test_reflexer_busy_falls_back_and_the_key_reaches_only_reflexer(self):
        for name, make, body in MODELS:
            with self.subTest(name):
                if STOCK_FAILS.get(name):
                    self.skipTest("fails with the stock client too, on this Python")
                handler, seen = world(body, reflexer_busy=True)
                self.assertEqual(run(make(handler)).output, "made up")
                self.assertEqual(len({request.url.host for request in seen}), 2, "it never fell back")
                keyed = {request.url.host for request in seen if any(KEY in value for value in request.headers.values())}
                self.assertEqual(keyed, {REFLEXER})


if __name__ == "__main__":
    unittest.main()
