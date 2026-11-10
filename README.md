# reflexer: Muscle memory for your LLM calls

Your app makes some LLM calls again and again. reflexer answers these calls with the answer your provider would give, at a lower price. Your provider answers all other calls, as before.

To use reflexer, you change one import and one line. You keep the provider SDK you already use.

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

This is the whole change. The reply has OpenAI's format, as before. If you undo these two changed lines, your code is as it was before.

What you get:

- Your code gets your provider SDK's types, fields and errors, as before.
- When reflexer is down, slow or busy, the SDK sends the call directly to your provider.
- The SDK sends your call, with your provider key, to reflexer. When reflexer does not answer the call, reflexer forwards it to your provider. The SDK sends the reflexer key only to reflexer. [Security](SECURITY.md).
- The SDK has no dependencies. It uses the provider SDK you already have.
- The tests run every code example in these docs and check that it prints the output shown.

Python 3.10+ · Node 20.3+ · [Apache-2.0](LICENSE)

## Install

The package is not on PyPI or npm yet. Install it from a clone of this repository. The commands below build it the same way as a release: pip uses only the Python build tools that `build-constraints.txt` pins by hash (this needs pip 26.1 or later), and npm runs no install script of any dependency.

```sh
git clone https://github.com/reflexer-ai/reflexer-sdk
pip install --build-constraint reflexer-sdk/build-constraints.txt ./reflexer-sdk
```

```sh
git clone https://github.com/reflexer-ai/reflexer-sdk
cd reflexer-sdk/typescript && npm ci --ignore-scripts && npm pack  # makes reflexer-ai-sdk-VERSION.tgz
npm install /path/to/reflexer-sdk/typescript/reflexer-ai-sdk-VERSION.tgz  # in your project
```

Then set the environment variable `REFLEXER_KEY` to the key you received at onboarding. If you do not have a key, write to hello@reflexer.ai.

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

Is your library not in this table? If it accepts your provider SDK's client, an HTTP client or a `fetch`, see [another library](docs/other-libraries.md).

Then: [When reflexer fails](docs/when-reflexer-fails.md) · [Advanced](docs/advanced.md) (skip one call, sampling, timeouts) · [Reference](docs/reference.md) · [Known limits](docs/limits.md) · [Contributing](CONTRIBUTING.md)
