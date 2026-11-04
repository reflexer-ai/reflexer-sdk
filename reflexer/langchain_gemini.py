"""LangChain's ChatGoogleGenerativeAI, through reflexer: `ChatGoogleGenerativeAI(**config)` becomes
`reflexer.langchain_gemini.ChatGoogleGenerativeAI(**config, reflexer_key=key)`. Its public `client_args` alone."""
import langchain_google_genai
from . import BASE, supported
from .gemini import client_args

supported("langchain-google-genai", [4])


class ChatGoogleGenerativeAI(langchain_google_genai.ChatGoogleGenerativeAI):
    def __init__(self, *, reflexer_key, reflexer_base=BASE, sample=1.0, **config):
        config["client_args"] = client_args(reflexer_key, own=config.get("client_args"), base=reflexer_base, sample=sample)
        super().__init__(**config)
