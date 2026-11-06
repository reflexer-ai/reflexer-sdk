# Python

Python 3.10 or newer. The package has no dependencies: it plugs into the provider SDK you already use. To install it: [README.md, **Quick start**](../README.md#quick-start).

## The key and the address

Each of reflexer's clients below takes `reflexer_key`, the key you got at onboarding (`rfx1_...`); the makers of HTTP clients ([below](#a-client-you-do-not-make-yourself)) take it as their first argument, and Bedrock's `through` as its second. A key not of that form raises `ValueError` when the client is made, before any call. The examples read it from `REFLEXER_KEY`.

`reflexer_base` (`base` on the makers and `through`) is reflexer's address, `https://api.reflexer.ai` unless you were given another; it must be `https`.

Everything else stays as you had it: your provider's key, its settings, your own HTTP client. The examples leave the provider's key to the provider SDK, which reads it from its usual environment variable.

## OpenAI

<!-- example: served -->
```python
import os
import reflexer.openai

# client = openai.OpenAI()
client = reflexer.openai.OpenAI(reflexer_key=os.environ["REFLEXER_KEY"])

answer = client.chat.completions.create(model="your-model", messages=[{"role": "user", "content": "Hi"}])
print(answer.choices[0].message.content)
```

`AsyncOpenAI` the same way. The Responses API goes through too. A router or model host that speaks OpenAI's format works by its `base_url`, as before.

## Azure OpenAI

<!-- example: served -->
```python
import os
import reflexer.openai

# client = openai.AzureOpenAI()
client = reflexer.openai.AzureOpenAI(reflexer_key=os.environ["REFLEXER_KEY"])

answer = client.chat.completions.create(model="your-deployment", messages=[{"role": "user", "content": "Hi"}])
print(answer.choices[0].message.content)
```

`AsyncAzureOpenAI` the same way.

## Anthropic

<!-- example: served -->
```python
import os
import reflexer.anthropic

# client = anthropic.Anthropic()
client = reflexer.anthropic.Anthropic(reflexer_key=os.environ["REFLEXER_KEY"])

answer = client.messages.create(model="your-model", max_tokens=1024, messages=[{"role": "user", "content": "Hi"}])
print(answer.content[0].text)
```

`AsyncAnthropic` the same way.

## Gemini

<!-- example: served -->
```python
import os
import reflexer.gemini

# client = genai.Client()
client = reflexer.gemini.Client(reflexer_key=os.environ["REFLEXER_KEY"])

answer = client.models.generate_content(model="your-model", contents="Hi")
print(answer.text)
```

Async calls by `client.aio`, as stock.

## A client you do not make yourself

When other code makes the provider's client, keep its class and give it reflexer's HTTP client:

<!-- example: served -->
```python
import os
import openai, reflexer.openai
from google import genai
import reflexer.gemini

key = os.environ["REFLEXER_KEY"]
client = openai.OpenAI(http_client=reflexer.openai.http_client(key))
print(client.chat.completions.create(model="your-model", messages=[{"role": "user", "content": "Hi"}]).choices[0].message.content)

args = reflexer.gemini.client_args(key)
gemini = genai.Client(http_options={"client_args": args, "async_client_args": args})
print(gemini.models.generate_content(model="your-model", contents="Hi").text)
```

The makers: `reflexer.openai.http_client`, `async_http_client`, `azure_http_client`, `azure_async_http_client`; `reflexer.anthropic.http_client`, `async_http_client`; `reflexer.gemini.client_args`. Each takes `own=`, an HTTP client of yours (for Gemini, your `client_args`), whose proxy, TLS settings and hooks it keeps. On Gemini, give `client_args` as both arguments: with only one, google-genai may send async calls by aiohttp, past reflexer.

## LangChain

<!-- example: served -->
```python
import os
import reflexer.langchain_openai, reflexer.langchain_gemini

# chat = ChatOpenAI(model="your-model")
chat = reflexer.langchain_openai.ChatOpenAI(model="your-model", reflexer_key=os.environ["REFLEXER_KEY"])
print(chat.invoke("Hi").content)

# chat = ChatGoogleGenerativeAI(model="your-model")
chat = reflexer.langchain_gemini.ChatGoogleGenerativeAI(model="your-model", reflexer_key=os.environ["REFLEXER_KEY"])
print(chat.invoke("Hi").content)
```

`AzureChatOpenAI` is LangChain's own class, given reflexer's HTTP clients; LangChain's own `ChatOpenAI` takes them the same way, from `reflexer.openai.http_client` and `async_http_client`. Given an HTTP client, LangChain stops asking a stream for its usage and price: pass `stream_usage=True` to keep them.

<!-- example: served -->
```python
import os
import reflexer.openai
from langchain_openai import AzureChatOpenAI

key = os.environ["REFLEXER_KEY"]
chat = AzureChatOpenAI(azure_deployment="your-deployment", stream_usage=True,
                       http_client=reflexer.openai.azure_http_client(key), http_async_client=reflexer.openai.azure_async_http_client(key))
print(chat.invoke("Hi").content)
```

`ChatAnthropic` takes no HTTP client, so reflexer cannot reach its calls. On reflexer's LangChain clients, LangChain's TCP keepalive (`http_socket_options`) does not apply: it is set only on HTTP clients LangChain makes itself. LangChain's serialization (`dumpd`, then `loads`) gives back LangChain's own class, without reflexer.

## Pydantic AI

Its providers take the provider SDK's client: give them reflexer's. On Python 3.10, Pydantic AI's last release for it fails Anthropic's calls, with the stock client too.

<!-- example: served -->
```python
import os
import reflexer.anthropic, reflexer.gemini, reflexer.openai
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

key = os.environ["REFLEXER_KEY"]
openai = OpenAIProvider(openai_client=reflexer.openai.AsyncOpenAI(reflexer_key=key))
anthropic = AnthropicProvider(anthropic_client=reflexer.anthropic.AsyncAnthropic(reflexer_key=key))
google = GoogleProvider(client=reflexer.gemini.Client(reflexer_key=key))

for model in OpenAIChatModel("your-model", provider=openai), AnthropicModel("your-model", provider=anthropic), GoogleModel("your-model", provider=google):
    print(Agent(model).run_sync("Hi").output)
```

## Amazon Bedrock

Both ways of calling Bedrock go through reflexer, with the same code:

- With a Bedrock API key: the key goes to reflexer with the call, as any provider's key does.
- Signed with your AWS credentials (SigV4): reflexer gets the signed call, but never passes your signature on. When it does not answer, your library sends the call to Bedrock: boto3, aiobotocore and Anthropic's Bedrock clients sign it again; LiteLLM sends it as first signed, and stops waiting for reflexer while the signature still holds. Your AWS secret stays with your library's signer; the call reflexer gets carries your access key's id, and with temporary credentials the session token.

Each example below runs both ways: with the key in `AWS_BEARER_TOKEN_BEDROCK`, and signed.

boto3:

<!-- example: served bedrock -->
```python
import os
import reflexer.boto3

# client = boto3.client("bedrock-runtime", region_name="us-east-1")
client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])

answer = client.converse(modelId="your-model-id", messages=[{"role": "user", "content": [{"text": "Hi"}]}])
print(answer["output"]["message"]["content"][0]["text"])
```

A client made elsewhere, by boto3 or aiobotocore (once entered):

<!-- example: served bedrock -->
```python
import asyncio, os
import boto3, aiobotocore.session
import reflexer.boto3, reflexer.aiobotocore

key = os.environ["REFLEXER_KEY"]
hi = [{"role": "user", "content": [{"text": "Hi"}]}]

client = reflexer.boto3.through(boto3.client("bedrock-runtime", region_name="us-east-1"), key)
print(client.converse(modelId="your-model-id", messages=hi)["output"]["message"]["content"][0]["text"])

async def main():
    async with aiobotocore.session.get_session().create_client("bedrock-runtime", region_name="us-east-1") as client:
        reflexer.aiobotocore.through(client, key)
        answer = await client.converse(modelId="your-model-id", messages=hi)
        print(answer["output"]["message"]["content"][0]["text"])

asyncio.run(main())
```

What is built on boto3 takes reflexer's client: langchain-aws, Pydantic AI, Strands.

<!-- example: served bedrock -->
```python
import os
import reflexer.boto3
from langchain_aws import ChatBedrockConverse
from pydantic_ai import Agent
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.providers.bedrock import BedrockProvider
from strands import Agent as StrandsAgent
from strands.models import BedrockModel

key = os.environ["REFLEXER_KEY"]
client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=key)

print(ChatBedrockConverse(model="your-model-id", client=client).invoke("Hi").content)
print(Agent(BedrockConverseModel("your-model-id", provider=BedrockProvider(bedrock_client=client))).run_sync("Hi").output)

model = BedrockModel(model_id="your-model-id", region_name="us-east-1")  # Strands makes its own client
reflexer.boto3.through(model.client, key)
print(StrandsAgent(model=model, callback_handler=None)("Hi"))
```

Anthropic's Bedrock client. `AsyncAnthropicBedrock`, and Mantle's `AnthropicBedrockMantle` and `AsyncAnthropicBedrockMantle`, work the same way; on Mantle, a signed call goes to Mantle as before, not through reflexer.

<!-- example: served bedrock -->
```python
import os
import reflexer.anthropic_bedrock

# client = anthropic.AnthropicBedrock(aws_region="us-east-1")
client = reflexer.anthropic_bedrock.AnthropicBedrock(aws_region="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])

answer = client.messages.create(model="your-model-id", max_tokens=1024, messages=[{"role": "user", "content": "Hi"}])
print(answer.content[0].text)
```

LiteLLM takes reflexer's HTTP client per call. Make it once and give it to every call, so that its connections, and what it learns of reflexer's failures, last. `reflexer.litellm.async_client` for `acompletion`.

<!-- example: served bedrock -->
```python
import os
import litellm, reflexer.litellm

bedrock = reflexer.litellm.client(os.environ["REFLEXER_KEY"])

# answer = litellm.completion(model="bedrock/converse/your-model-id", messages=[{"role": "user", "content": "Hi"}])
answer = litellm.completion(model="bedrock/converse/your-model-id", messages=[{"role": "user", "content": "Hi"}], client=bedrock)
print(answer.choices[0].message.content)
```

Bedrock's OpenAI and Anthropic routes take reflexer's OpenAI and Anthropic clients above, with `base_url` theirs and the Bedrock API key as `api_key`.

What each Bedrock library cannot do: [SECURITY.md, **Known limits**](../SECURITY.md#known-limits).

## Skip reflexer for one call

The `Reflexer-Pass-Through` header sends one call straight to the provider.

- OpenAI, Azure, Anthropic, Anthropic's Bedrock clients, LiteLLM, LangChain's `ChatOpenAI.invoke`: `extra_headers={"Reflexer-Pass-Through": "1"}` on the call.
- Pydantic AI on OpenAI or Anthropic: `model_settings={"extra_headers": {"Reflexer-Pass-Through": "1"}}` on the run.
- Gemini: `config={"http_options": {"headers": {"Reflexer-Pass-Through": "1"}}}` on the call.
- boto3 and aiobotocore: `ReflexerPassThrough=True` on the call.
- langchain-aws, Pydantic AI on Bedrock, Strands: they make the boto3 call themselves, so the header is set by a `before-sign` handler you register on the boto3 client, for as long as it is registered.

<!-- example: straight bedrock -->
```python
import os
import reflexer.boto3, reflexer.gemini, reflexer.langchain_openai, reflexer.openai
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

key = os.environ["REFLEXER_KEY"]
straight = {"Reflexer-Pass-Through": "1"}

openai = reflexer.openai.OpenAI(reflexer_key=key)
answer = openai.chat.completions.create(model="your-model", messages=[{"role": "user", "content": "Hi"}], extra_headers=straight)
print(answer.choices[0].message.content)

gemini = reflexer.gemini.Client(reflexer_key=key)
print(gemini.models.generate_content(model="your-model", contents="Hi", config={"http_options": {"headers": straight}}).text)

chat = reflexer.langchain_openai.ChatOpenAI(model="your-model", reflexer_key=key)
print(chat.invoke("Hi", extra_headers=straight).content)

model = OpenAIChatModel("your-model", provider=OpenAIProvider(openai_client=reflexer.openai.AsyncOpenAI(reflexer_key=key)))
print(Agent(model).run_sync("Hi", model_settings={"extra_headers": straight}).output)

bedrock = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=key)
answer = bedrock.converse(modelId="your-model-id", messages=[{"role": "user", "content": [{"text": "Hi"}]}], ReflexerPassThrough=True)
print(answer["output"]["message"]["content"][0]["text"])
```

## Send only a share of the calls

`sample` is the share of calls that go to reflexer; the rest go straight to the provider. Every client and maker above takes it.

<!-- example: any -->
```python
import os
import reflexer.openai

client = reflexer.openai.OpenAI(reflexer_key=os.environ["REFLEXER_KEY"], sample=0.01)  # 1% of the calls

answer = client.chat.completions.create(model="your-model", messages=[{"role": "user", "content": "Hi"}])
print(answer.choices[0].message.content)
```

## Who answered

<!-- example: served -->
```python
import os
import reflexer.openai

client = reflexer.openai.OpenAI(reflexer_key=os.environ["REFLEXER_KEY"])

raw = client.chat.completions.with_raw_response.create(model="your-model", messages=[{"role": "user", "content": "Hi"}])
answer = raw.parse()
print(answer.choices[0].message.content)
print(answer.model)                         # ends in "-reflexer" when reflexer answered
print(answer.usage.cost)                    # reflexer's price, in USD
print(raw.headers["Reflexer-Answered-By"])  # "reflexer", or "provider" when reflexer passed the call on
```

On Gemini, whose answers have no field for a price: `answer.model_version`, and `answer.sdk_http_response.headers["reflexer-cost"]` (nano USD).

What each field means, and what you see when reflexer is down or slow: [behaviour.md](behaviour.md).

## Versions

Tested on openai 3, anthropic 2, google-genai 2, langchain-openai 1, langchain-google-genai 4, boto3 1, aiobotocore 3 and LiteLLM 1. Importing reflexer's module for an SDK on another major version raises `ImportError`, so a new release never sends your calls astray.
