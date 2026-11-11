# reflexer with Pydantic AI

Send the calls of Pydantic AI's OpenAI, Anthropic and Gemini models through reflexer. For Bedrock, see [Bedrock](bedrock.md#langchain-aws-pydantic-ai-strands).

**Before you begin:** you need Pydantic AI 2 on Python 3.10+, and the environment variable `REFLEXER_KEY` set to the reflexer key you got at onboarding.

## 1. Install

The SDK is not on PyPI or npm yet. Install it from a clone of this repository ([README](../README.md#install)).

```sh
pip install --build-constraint reflexer-sdk/build-constraints.txt ./reflexer-sdk  # pip 26.1 or later
```
## 2. Add the line

Give the provider reflexer's client.

<!-- example: served python -->
```diff
  import os
  from pydantic_ai import Agent
  from pydantic_ai.models.openai import OpenAIChatModel
  from pydantic_ai.providers.openai import OpenAIProvider
+ from reflexer.openai import AsyncOpenAI

- provider = OpenAIProvider()
+ provider = OpenAIProvider(openai_client=AsyncOpenAI(reflexer_key=os.environ["REFLEXER_KEY"]))
  print(Agent(OpenAIChatModel("frontier-x", provider=provider)).run_sync("Hi").output)
```

```text
Hello! How can I help you today?
```

Anthropic: `AnthropicProvider(anthropic_client=reflexer.anthropic.AsyncAnthropic(reflexer_key=...))`. Gemini: `GoogleProvider(client=reflexer.gemini.Client(reflexer_key=...))`.

## 3. Verify

The reply looks the same whether reflexer or your provider answered. A reply from reflexer has a model name that ends in `-reflexer`.

<!-- example: served -->
```python
import os
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from reflexer.openai import AsyncOpenAI

provider = OpenAIProvider(openai_client=AsyncOpenAI(reflexer_key=os.environ["REFLEXER_KEY"]))
print(Agent(OpenAIChatModel("frontier-x", provider=provider)).run_sync("Hi").response.model_name)
```

```text
frontier-x-reflexer
```

## Behavior

- **Reflexer down, slow or busy:** the SDK sends the call directly to your provider, and your code gets your provider's answer. The SDK logs a warning on the `reflexer` logger. After a failure, the SDK sends the next calls directly to your provider too, for about a minute at most. Then the SDK tries reflexer again.
- **Timeouts, Python:** your client's timeout applies to the call to reflexer. If that timeout expires, the SDK sends the call directly to your provider, with the same timeout. So one call can take up to two times your timeout. If reflexer had already forwarded the call, your provider may run the call twice and bill it twice.
- **Key refused:** if reflexer refuses your reflexer key, your provider SDK raises its authentication error, and the SDK does not send the call to your provider. If your reflexer key was revoked less than one day ago, the SDK still sends your calls directly to your provider, and logs a warning.
- **Which calls:** the SDK sends to reflexer only the calls that return a model's message. The SDK sends all other calls, and all calls to `http`, `localhost` or a private IP, to the address your code gave them, as before.
- **What leaves your machine:** the SDK sends the call to reflexer, with your provider key. When reflexer does not answer the call itself, reflexer uses this key to forward the call to your provider. Only reflexer receives your reflexer key.
- **Gemini, no timeout by default:** google-genai sets no timeout, so no timeout of yours limits how long a call waits for reflexer. Give `reflexer.gemini.Client` the argument `http_options={"timeout": 60_000}` (milliseconds).
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. If you remove the line, your code works as before.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).

## Options

- `sample=0.01` on reflexer's client: the SDK sends that share of the calls to reflexer, and the other calls directly to your provider.
- `run_sync("Hi", model_settings={"extra_headers": {"Reflexer-Skip": "true"}})`: the SDK sends that run's calls directly to your provider (OpenAI and Anthropic).

All options: [Advanced](advanced.md).

## Supported versions

Pydantic AI 2 on Python 3.10+, with `openai` 3, `anthropic` 2 and `google-genai` 2.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
