"""LangChain's ChatGoogleGenerativeAI, through reflexer: `ChatGoogleGenerativeAI(**config)` becomes
`reflexer.langchain_gemini.ChatGoogleGenerativeAI(**config, reflexer_key=key)`. Its public `client_args` alone."""
import langchain_google_genai
from . import BASE, supported
from .gemini import client_args
from .transport import Both

supported("langchain-google-genai", [4])


class ChatGoogleGenerativeAI(langchain_google_genai.ChatGoogleGenerativeAI):
    def __init__(self, *, reflexer_key=None, reflexer_base=BASE, sample=1.0, **config):
        if reflexer_key is None and isinstance(ours := (config.get("client_args") or {}).get("transport"), Both):
            # LangChain building it again from its fields (`configurable_fields`): our way, in a transport of its own, which
            # LangChain closes with it
            config["client_args"] = config["client_args"] | {"transport": Both(ours.library_of, *ours.makers.values())}
            return super().__init__(**config)
        config["client_args"] = client_args(reflexer_key, own=config.get("client_args"), base=reflexer_base, sample=sample)
        super().__init__(**config)
