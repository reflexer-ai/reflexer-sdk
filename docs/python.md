# Python

Python 3.10 or newer; install: [README](../README.md#quick-start). Give reflexer's client your reflexer key (`rfx1_...`, from onboarding; a malformed one raises `ValueError` at once). Everything else stays yours: the provider key, settings, HTTP client. `reflexer_base=` on a class, `base=` on a function, changes reflexer's address, `https://api.reflexer.ai` by default.

## OpenAI

<!-- example: served -->
```python
import os, reflexer.openai
# client = openai.OpenAI()
client = reflexer.openai.OpenAI(reflexer_key=os.environ["REFLEXER_KEY"])
answer = client.chat.completions.create(model="your-model", messages=[{"role": "user", "content": "Hi"}])
print(answer.choices[0].message.content)
```

`AsyncOpenAI`, `AzureOpenAI` and `AsyncAzureOpenAI` the same way. The Responses API too, and any router that speaks OpenAI's format, by its `base_url`.

## Anthropic

<!-- example: served -->
```python
import os, reflexer.anthropic
# client = anthropic.Anthropic()
client = reflexer.anthropic.Anthropic(reflexer_key=os.environ["REFLEXER_KEY"])
answer = client.messages.create(model="your-model", max_tokens=1024, messages=[{"role": "user", "content": "Hi"}])
print(answer.content[0].text)
```

`AsyncAnthropic` too.

## Gemini

<!-- example: served -->
```python
import os, reflexer.gemini
# client = genai.Client()
client = reflexer.gemini.Client(reflexer_key=os.environ["REFLEXER_KEY"])
answer = client.models.generate_content(model="your-model", contents="Hi")
print(answer.text)
```

## Keeping your library's own class

Give it reflexer's HTTP client.

<!-- example: served -->
```python
import os, openai, reflexer.openai
# client = openai.OpenAI()
client = openai.OpenAI(http_client=reflexer.openai.http_client(os.environ["REFLEXER_KEY"]))
answer = client.chat.completions.create(model="your-model", messages=[{"role": "user", "content": "Hi"}])
print(answer.choices[0].message.content)
```

- OpenAI: `reflexer.openai.http_client`, `async_http_client`, `azure_http_client`, `azure_async_http_client`.
- Anthropic: `reflexer.anthropic.http_client`, `async_http_client`.
- Gemini: `args = reflexer.gemini.client_args(key)`, given as both: `genai.Client(http_options={"client_args": args, "async_client_args": args})`.

Each takes your own HTTP client as `own=`.

## LangChain

<!-- example: served -->
```python
import os, reflexer.langchain_openai
# chat = ChatOpenAI(model="your-model")
chat = reflexer.langchain_openai.ChatOpenAI(model="your-model", reflexer_key=os.environ["REFLEXER_KEY"])
print(chat.invoke("Hi").content)
```

`reflexer.langchain_gemini.ChatGoogleGenerativeAI` the same way.

<!-- example: served -->
```python
import os, reflexer.openai
from langchain_openai import AzureChatOpenAI
# chat = AzureChatOpenAI(azure_deployment="your-deployment")
key = os.environ["REFLEXER_KEY"]
chat = AzureChatOpenAI(azure_deployment="your-deployment", stream_usage=True,  # streams keep their usage
                       http_client=reflexer.openai.azure_http_client(key),
                       http_async_client=reflexer.openai.azure_async_http_client(key))
print(chat.invoke("Hi").content)
```

What LangChain cannot do here: [Known limits](../SECURITY.md#known-limits).

## Pydantic AI

<!-- example: served -->
```python
import os, reflexer.openai
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
# provider = OpenAIProvider()
provider = OpenAIProvider(openai_client=reflexer.openai.AsyncOpenAI(reflexer_key=os.environ["REFLEXER_KEY"]))
print(Agent(OpenAIChatModel("your-model", provider=provider)).run_sync("Hi").output)
```

Anthropic the same way, `AnthropicProvider(anthropic_client=reflexer.anthropic.AsyncAnthropic(...))`; Gemini, `GoogleProvider(client=reflexer.gemini.Client(...))`.

## Amazon Bedrock

The same code works with a Bedrock API key (`AWS_BEARER_TOKEN_BEDROCK`) and with your AWS credentials (SigV4).

### boto3

<!-- example: served bedrock -->
```python
import os, reflexer.boto3
# client = boto3.client("bedrock-runtime", region_name="us-east-1")
client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
answer = client.converse(modelId="your-model-id", messages=[{"role": "user", "content": [{"text": "Hi"}]}])
print(answer["output"]["message"]["content"][0]["text"])
```

For a boto3 client made elsewhere: `reflexer.boto3.through(client, key)`.

### aiobotocore

<!-- example: served bedrock -->
```python
import asyncio, os, aiobotocore.session, reflexer.aiobotocore
async def main():
    async with aiobotocore.session.get_session().create_client("bedrock-runtime", region_name="us-east-1") as client:
        reflexer.aiobotocore.through(client, os.environ["REFLEXER_KEY"])
        answer = await client.converse(modelId="your-model-id", messages=[{"role": "user", "content": [{"text": "Hi"}]}])
        print(answer["output"]["message"]["content"][0]["text"])

asyncio.run(main())
```

### LangChain

<!-- example: served bedrock -->
```python
import os, reflexer.boto3
from langchain_aws import ChatBedrockConverse
# chat = ChatBedrockConverse(model="your-model-id", region_name="us-east-1")
client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
chat = ChatBedrockConverse(model="your-model-id", client=client)
print(chat.invoke("Hi").content)
```

### Pydantic AI

<!-- example: served bedrock -->
```python
import os, reflexer.boto3
from pydantic_ai import Agent
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.providers.bedrock import BedrockProvider
# provider = BedrockProvider(region_name="us-east-1")
client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
provider = BedrockProvider(bedrock_client=client)
print(Agent(BedrockConverseModel("your-model-id", provider=provider)).run_sync("Hi").output)
```

### Strands

<!-- example: served bedrock -->
```python
import os, reflexer.boto3
from strands import Agent
from strands.models import BedrockModel
model = BedrockModel(model_id="your-model-id", region_name="us-east-1")
reflexer.boto3.through(model.client, os.environ["REFLEXER_KEY"])
print(Agent(model=model, callback_handler=None)("Hi"))
```

### Anthropic's Bedrock clients

<!-- example: served bedrock -->
```python
import os, reflexer.anthropic_bedrock
# client = anthropic.AnthropicBedrock(aws_region="us-east-1")
client = reflexer.anthropic_bedrock.AnthropicBedrock(aws_region="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
answer = client.messages.create(model="your-model-id", max_tokens=1024, messages=[{"role": "user", "content": "Hi"}])
print(answer.content[0].text)
```

`AsyncAnthropicBedrock`, `AnthropicBedrockMantle` and `AsyncAnthropicBedrockMantle` too.

### LiteLLM

<!-- example: served bedrock -->
```python
import os, litellm, reflexer.litellm
bedrock = reflexer.litellm.client(os.environ["REFLEXER_KEY"])  # make it once, pass it to every call
# answer = litellm.completion(model="bedrock/converse/your-model-id", messages=[{"role": "user", "content": "Hi"}])
answer = litellm.completion(model="bedrock/converse/your-model-id", messages=[{"role": "user", "content": "Hi"}],
                            client=bedrock)
print(answer.choices[0].message.content)
```

`reflexer.litellm.async_client` for `acompletion`.

### Bedrock's OpenAI and Anthropic endpoints

The OpenAI and Anthropic clients above, with Bedrock's `base_url` and the Bedrock API key as `api_key`. What each Bedrock library cannot do: [Known limits](../SECURITY.md#known-limits).

## Skip reflexer for one call

<!-- example: straight -->
```python
import os, reflexer.openai
client = reflexer.openai.OpenAI(reflexer_key=os.environ["REFLEXER_KEY"])
answer = client.chat.completions.create(model="your-model", messages=[{"role": "user", "content": "Hi"}],
                                        extra_headers={"Reflexer-Pass-Through": "1"})
print(answer.choices[0].message.content)
```

- Anthropic, Anthropic's Bedrock clients, LiteLLM, LangChain's `invoke`: the same `extra_headers`.
- Pydantic AI: `model_settings={"extra_headers": {"Reflexer-Pass-Through": "1"}}`.
- Gemini: `config={"http_options": {"headers": {"Reflexer-Pass-Through": "1"}}}`.
- boto3, aiobotocore: an argument, below. Libraries built on them: [Known limits](../SECURITY.md#known-limits).

<!-- example: straight bedrock -->
```python
import os, reflexer.boto3
client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
answer = client.converse(modelId="your-model-id", messages=[{"role": "user", "content": [{"text": "Hi"}]}],
                         ReflexerPassThrough=True)
print(answer["output"]["message"]["content"][0]["text"])
```

## Send a share of the calls

<!-- example: straight -->
```python
import os, reflexer.openai
client = reflexer.openai.OpenAI(reflexer_key=os.environ["REFLEXER_KEY"], sample=0.01)  # 1% to reflexer, the rest to OpenAI
answer = client.chat.completions.create(model="your-model", messages=[{"role": "user", "content": "Hi"}])
print(answer.choices[0].message.content)
```

Every reflexer client and function above takes `sample`.

## Who answered

<!-- example: served -->
```python
import os, reflexer.openai
client = reflexer.openai.OpenAI(reflexer_key=os.environ["REFLEXER_KEY"])
raw = client.chat.completions.with_raw_response.create(model="your-model", messages=[{"role": "user", "content": "Hi"}])
answer = raw.parse()
print(answer.choices[0].message.content)
print(answer.model, getattr(answer.usage, "cost", ""))  # model ends in "-reflexer"; cost in USD
print(raw.headers.get("Reflexer-Answered-By", "your provider, directly"))  # or "reflexer", or "provider" (passed on by reflexer)
```

More, and what happens when reflexer is down or slow: [behaviour.md](behaviour.md).

## Versions

Tested on openai 3, anthropic 2, google-genai 2, langchain-openai 1, langchain-google-genai 4, boto3 1, aiobotocore 3 and LiteLLM 1. On another major version, importing reflexer's module raises `ImportError`.
