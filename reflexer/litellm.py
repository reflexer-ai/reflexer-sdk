"""LiteLLM's Bedrock calls, through reflexer: its handlers take `client=` per call, an `HTTPHandler` of LiteLLM's,
`litellm.completion(model="bedrock/...", client=reflexer.litellm.client(key))`. Ours is LiteLLM's own default handler,
whose `create_client` gives LiteLLM's HTTP client reflexer's transport; `async_client` for `acompletion`. No setting of
LiteLLM's reaches every Bedrock call: the line is per call. A call given `api_key`, a Bedrock API key, goes through
reflexer; a signed one, to Bedrock as stock.

The call's timeout: LiteLLM's converse handler, not streamed, posts by a given client with no `timeout`, where stock
builds its client with it; so ours takes it from the call's own parameters, which LiteLLM hands `post` with its
`logging_obj`. A release that moves them fails the call, never drops its timeout.
"""
import httpx
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler, HTTPHandler
from . import BASE, supported
from .bedrock import BEDROCK, setup_http_client

supported("litellm", [1])
http_client, async_http_client = setup_http_client(httpx.Client, BEDROCK), setup_http_client(httpx.AsyncClient, BEDROCK)


def asked(timeout, logging_obj):
    """The call's own timeout: the one given to `post`, else the call's, as stock would have built its client with."""
    if timeout is not None or logging_obj is None:
        return timeout
    given = logging_obj.model_call_details["litellm_params"]["timeout"]
    return httpx.Timeout(given) if isinstance(given, (int, float)) else given


def client(reflexer_key, base=BASE, sample=1.0):
    class Handler(HTTPHandler):
        def create_client(self):
            return http_client(reflexer_key, own=super().create_client(), base=base, sample=sample)

        def post(self, *args, timeout=None, logging_obj=None, **kwargs):
            return super().post(*args, timeout=asked(timeout, logging_obj), logging_obj=logging_obj, **kwargs)
    return Handler()


def async_client(reflexer_key, base=BASE, sample=1.0):
    class Handler(AsyncHTTPHandler):
        def create_client(self, *args, **kwargs):
            return async_http_client(reflexer_key, own=super().create_client(*args, **kwargs), base=base, sample=sample)

        async def post(self, *args, timeout=None, logging_obj=None, **kwargs):
            return await super().post(*args, timeout=asked(timeout, logging_obj), logging_obj=logging_obj, **kwargs)
    return Handler()
