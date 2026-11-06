# reflexer

Put reflexer in front of your LLM calls by changing one line of your code:

<!-- example: served python -->
```diff
- import openai
+ import os, reflexer.openai
- client = openai.OpenAI()
+ client = reflexer.openai.OpenAI(reflexer_key=os.environ["REFLEXER_KEY"])
  answer = client.chat.completions.create(model="your-model", messages=[{"role": "user", "content": "Hi"}])
  print(answer.choices[0].message.content)
```

<!-- example: served js -->
```diff
- import OpenAI from "openai";
+ import { OpenAI } from "@reflexer-ai/sdk/openai";
- const client = new OpenAI();
+ const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY });
  const answer = await client.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] });
  console.log(answer.choices[0].message.content);
```

- Your code reads the same answers: your provider's format, unchanged.
- If reflexer does not answer a call, or cannot be reached, the call goes to your provider as before.
- No dependencies: it plugs into the provider SDK you already have. Its security promises: [SECURITY.md](SECURITY.md).

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

Then set `REFLEXER_KEY` to the key you got at onboarding, and run the block above. To check that reflexer answered, `answer.model` ends in `-reflexer`.

## Your library

- Python: [OpenAI and Azure](docs/python.md#openai), [Anthropic](docs/python.md#anthropic), [Gemini](docs/python.md#gemini), [LangChain](docs/python.md#langchain), [Pydantic AI](docs/python.md#pydantic-ai), [Amazon Bedrock](docs/python.md#amazon-bedrock) (boto3, aiobotocore, LangChain, Pydantic AI, Strands, Anthropic's Bedrock clients, LiteLLM).
- TypeScript: [OpenAI and Azure](docs/typescript.md#openai), [Anthropic](docs/typescript.md#anthropic), [Gemini](docs/typescript.md#gemini), [the AI SDK](docs/typescript.md#the-ai-sdk), [LangChain.js](docs/typescript.md#langchainjs), [Amazon Bedrock](docs/typescript.md#amazon-bedrock) (the AWS SDK, LangChain.js, AnthropicBedrock, the AI SDK).
- Don't see yours? If it takes your provider SDK's client, an HTTP client or a `fetch`: [Python](docs/python.md#keeping-your-librarys-own-class), [TypeScript](docs/typescript.md#keeping-your-librarys-own-class).

Each page also covers skipping reflexer for one call, sending it a share of the calls, and who answered. What happens when reflexer is down or slow: [What your code sees](docs/behaviour.md). Every limit: [Known limits](SECURITY.md#known-limits). Every example here runs in the tests: [Contributing](CONTRIBUTING.md).
