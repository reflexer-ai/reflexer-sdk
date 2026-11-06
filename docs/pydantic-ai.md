# reflexer with Pydantic AI

Reflexer in front of Pydantic AI's OpenAI, Anthropic and Gemini models. On Bedrock: [Bedrock](bedrock.md#langchain-aws-pydantic-ai-strands).

**Before you begin:** `pydantic-ai`, and `REFLEXER_KEY` set to the key you got at onboarding.

## 1. Install

Not on PyPI or npm yet: install from a clone of this repository ([README](../README.md#install)).

```sh
pip install ./reflexer-sdk
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

The reply looks the same either way. A served reply's model name ends in `-reflexer`.

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

- **Reflexer down, slow or busy:** the call goes to your provider, and your code gets your provider's answer. The SDK logs a warning on the `reflexer` logger. After a failure, the next calls go to your provider too, for about a minute at most, then reflexer is tried again.
- **Timeouts, Python:** your client's timeout covers the call to reflexer; if it fires, the call goes to your provider with the same timeout, so a call can take up to twice it.
- **What leaves your machine:** the call, with your your provider key, goes to reflexer, which uses the key to call your provider. The reflexer key goes to reflexer only.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. Remove the line and your code is as it was.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](../SECURITY.md#known-limits).
## Options

- `sample=0.01` on reflexer's client: send that share of the calls to reflexer, the rest to your provider.
- `run_sync("Hi", model_settings={"extra_headers": {"Reflexer-Pass-Through": "1"}})`: that run's calls go to your provider (OpenAI and Anthropic).

All of them: [Advanced](advanced.md).

## Supported versions

Pydantic AI 2 on Python 3.10+, with `openai` 3, `anthropic` 2 and `google-genai` 2.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
