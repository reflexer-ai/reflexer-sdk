"""openai's own clients, through reflexer: `openai.OpenAI(**config)` becomes `reflexer.openai.OpenAI(**config, reflexer_key=key)`,
or, on the stock class, `openai.OpenAI(http_client=reflexer.openai.http_client(key), **config)`."""
import openai
from . import supported
from .transport import setup_client, setup_http_client
from .wires import AZURE, CHAT

supported("openai", [3])

http_client             = setup_http_client(openai.DefaultHttpxClient,      CHAT)
async_http_client       = setup_http_client(openai.DefaultAsyncHttpxClient, CHAT)
azure_http_client       = setup_http_client(openai.DefaultHttpxClient,      AZURE)
azure_async_http_client = setup_http_client(openai.DefaultAsyncHttpxClient, AZURE)

OpenAI           = setup_client(openai.OpenAI,           http_client)
AsyncOpenAI      = setup_client(openai.AsyncOpenAI,      async_http_client)
AzureOpenAI      = setup_client(openai.AzureOpenAI,      azure_http_client)
AsyncAzureOpenAI = setup_client(openai.AsyncAzureOpenAI, azure_async_http_client)
