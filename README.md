# reflexer

Put reflexer in front of your LLM calls, from the provider SDK you already use: change one import and one line.

<!-- example: served python -->
```diff
  import os
- from openai import OpenAI
+ from reflexer.openai import OpenAI

- client = OpenAI()
+ client = OpenAI(reflexer_key=os.environ["REFLEXER_KEY"])
  reply = client.chat.completions.create(model="frontier-x", messages=[{"role": "user", "content": "Hi"}])
  print(reply.choices[0].message.content)
```

```text
Hello! How can I help you today?
```

The reply is OpenAI's format, as before. Remove the line and your code is as it was.

What you get:

- Your provider's answers, types and errors, unchanged.
- A call reflexer does not answer, or cannot be reached for, goes to your provider.
- No dependencies: the SDK plugs into the provider SDK you have. [Security](SECURITY.md).
- Every example in these docs runs in the tests.

Python 3.10+ · Node 20.3+

## Install

Not on PyPI or npm yet: install from a clone of this repository.

```sh
git clone https://github.com/reflexer-ai/reflexer-sdk
pip install ./reflexer-sdk
```

```sh
git clone https://github.com/reflexer-ai/reflexer-sdk
cd reflexer-sdk/typescript && npm ci && npm pack  # makes reflexer-ai-sdk-VERSION.tgz
npm install /path/to/reflexer-sdk/typescript/reflexer-ai-sdk-VERSION.tgz  # in your project
```

Then set `REFLEXER_KEY` to the key you got at onboarding.

## Pick your library

| Library | Python | TypeScript |
|---|---|---|
| [OpenAI](docs/openai.md), Azure OpenAI | `openai` | `openai` |
| [Anthropic](docs/anthropic.md) | `anthropic` | `@anthropic-ai/sdk` |
| [Gemini](docs/gemini.md) | `google-genai` | `@google/genai` |
| [Amazon Bedrock](docs/bedrock.md) | boto3, aiobotocore, langchain-aws, Pydantic AI, Strands, Anthropic's Bedrock clients, LiteLLM | the AWS SDK, LangChain.js, AnthropicBedrock, the AI SDK |
| [LangChain](docs/langchain.md) | `langchain-openai`, `langchain-google-genai` | `@langchain/openai` |
| [Pydantic AI](docs/pydantic-ai.md) | `pydantic-ai` | |
| [The AI SDK](docs/ai-sdk.md) | | `ai` |

Don't see yours? If it takes your provider SDK's client, an HTTP client or a `fetch`: [another library](docs/other-libraries.md).

Then: [When reflexer fails](docs/when-reflexer-fails.md) · [Advanced](docs/advanced.md) (skip one call, sampling, timeouts) · [Reference](docs/reference.md) · [Known limits](SECURITY.md#known-limits) · [Contributing](CONTRIBUTING.md)
