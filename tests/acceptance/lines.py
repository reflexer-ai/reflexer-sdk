"""The SDK under test: each client made by the one line a client writes, from what it would give the stock class.
`faults.py` plants its faults here and in `reflexer`, never in a case."""
import httpx

import reflexer.anthropic, reflexer.gemini, reflexer.openai
from reflexer.transport import setup_http_client
from harness import acme, bedrock


def one_line_class(sdk, is_async):
    return {
        ("openai", False): reflexer.openai.OpenAI, ("openai", True): reflexer.openai.AsyncOpenAI,
        ("azure", False): reflexer.openai.AzureOpenAI, ("azure", True): reflexer.openai.AsyncAzureOpenAI,
        ("anthropic", False): reflexer.anthropic.Anthropic, ("anthropic", True): reflexer.anthropic.AsyncAnthropic,
        ("gemini", False): reflexer.gemini.Client, ("gemini", True): reflexer.gemini.Client,  # its async is `client.aio`
    }[sdk, is_async]


# What adding a provider takes: its wire's data, and the HTTP client its SDK makes when the client gives none.
acme_http_client = setup_http_client(lambda: httpx.Client(follow_redirects=True), {
    "reflexer_path": "/acme",
    "provider":      "https://api.acme.example",
    "calls":         r"/v2/ask$",
})


def client(world, sdk, is_async=False, **config):
    """`sdk(**config)` as a client writes it with reflexer: `world.key` its key, `world.share` its `sample`."""
    if sdk == "acme":
        return acme.Acme(**config | {"http_client": acme_http_client(world.key, own=config.get("http_client"), sample=world.share)})
    return one_line_class(sdk, is_async)(reflexer_key=world.key, sample=world.share, **config)


def bedrock_client(world, lib, keyed=True, **settings):
    """A Bedrock library's client as a client writes it with reflexer's line (`harness/bedrock.py`, each `make`): with a
    Bedrock API key (`keyed`), or signing its calls. A coroutine on aiobotocore."""
    return bedrock.LIBS[lib].make(world.key, keyed, settings | {"share": world.share})


def litellm_line(world):
    """LiteLLM's line, the process's: `world.key` its key, `world.share` its `sample`."""
    import reflexer.litellm
    reflexer.litellm.through(world.key, sample=world.share)
