"""anthropic's own clients, through reflexer: `anthropic.Anthropic(**config)` becomes `reflexer.anthropic.Anthropic(**config, reflexer_key=key)`,
or, on the stock class, `anthropic.Anthropic(http_client=reflexer.anthropic.http_client(key), **config)`."""
import anthropic
from . import supported
from .transport import setup_client, setup_http_client

supported("anthropic", [2])

MESSAGES = {
    "reflexer_path": "/anthropic",
    "provider":      "https://api.anthropic.com",
    "calls":         r"/v1/messages$",
}

http_client       = setup_http_client(anthropic.DefaultHttpxClient,      MESSAGES)
async_http_client = setup_http_client(anthropic.DefaultAsyncHttpxClient, MESSAGES)

Anthropic      = setup_client(anthropic.Anthropic,      http_client)
AsyncAnthropic = setup_client(anthropic.AsyncAnthropic, async_http_client)
