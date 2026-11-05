"""anthropic's Bedrock clients, through reflexer: `anthropic.AnthropicBedrock(**config)` becomes
`reflexer.anthropic_bedrock.AnthropicBedrock(**config, reflexer_key=key)`; Mantle's, `AnthropicBedrockMantle`, the same.

A client given a Bedrock API key (`api_key`, or `AWS_BEARER_TOKEN_BEDROCK`) sends its calls through reflexer; one that
signs (SigV4) sends them to Bedrock as stock. Mantle's go by the anthropic wire, Mantle as the upstream.
"""
import anthropic
from . import BASE, supported
from .anthropic import MESSAGES
from .bedrock import BEDROCK, setup_http_client
from .transport import setup_client

supported("anthropic", [2])


def bedrock_client(cls, make_http_client):
    """The shipped line's client; its copy keeps our HTTP client (the SDK's own copy of a Bedrock client drops it, and
    would make one with no key)."""

    class Client(setup_client(cls, make_http_client)):
        def __init__(self, *args, reflexer_key=None, reflexer_base=BASE, sample=1.0, http_client=None, **config):
            if not hasattr(http_client, "reflexer_through"):
                http_client = make_http_client(reflexer_key, own=http_client, base=reflexer_base, sample=sample)
            self.reflexer_http_client = http_client
            super().__init__(*args, http_client=http_client, **config)

        def copy(self, *args, http_client=None, **config):
            return super().copy(*args, http_client=http_client or self.reflexer_http_client, **config)

        with_options = copy

    Client.__name__ = Client.__qualname__ = cls.__name__
    return Client


bedrock_http_client       = setup_http_client(anthropic.DefaultHttpxClient,      BEDROCK)
bedrock_async_http_client = setup_http_client(anthropic.DefaultAsyncHttpxClient, BEDROCK)
mantle_http_client        = setup_http_client(anthropic.DefaultHttpxClient,      MESSAGES)
mantle_async_http_client  = setup_http_client(anthropic.DefaultAsyncHttpxClient, MESSAGES)

AnthropicBedrock            = bedrock_client(anthropic.AnthropicBedrock,            bedrock_http_client)
AsyncAnthropicBedrock       = bedrock_client(anthropic.AsyncAnthropicBedrock,       bedrock_async_http_client)
AnthropicBedrockMantle      = bedrock_client(anthropic.AnthropicBedrockMantle,      mantle_http_client)
AsyncAnthropicBedrockMantle = bedrock_client(anthropic.AsyncAnthropicBedrockMantle, mantle_async_http_client)
