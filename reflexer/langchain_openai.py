"""LangChain's ChatOpenAI, through reflexer: `ChatOpenAI(**config)` becomes
`reflexer.langchain_openai.ChatOpenAI(**config, reflexer_key=key)`. Its public arguments alone."""
import langchain_openai, openai, os
from . import BASE, supported
from .openai import async_http_client, http_client

supported("langchain-openai", [1])


class ChatOpenAI(langchain_openai.ChatOpenAI):
    def __init__(self, *, reflexer_key, reflexer_base=BASE, sample=1.0, **config):
        way = dict(base=reflexer_base, sample=sample)
        if config.get("http_client") is None and config.get("http_async_client") is None:
            # LangChain refuses its proxy beside an HTTP client, so the proxy goes in the client's own, under ours
            proxy = dict(proxy=config.pop("openai_proxy", os.environ.get("OPENAI_PROXY")) or None)
            config |= dict(openai_proxy=None, http_client=openai.DefaultHttpxClient(**proxy),
                           http_async_client=openai.DefaultAsyncHttpxClient(**proxy))
        config["http_client"] = http_client(reflexer_key, own=config.get("http_client"), **way)
        config["http_async_client"] = async_http_client(reflexer_key, own=config.get("http_async_client"), **way)
        super().__init__(**config)
