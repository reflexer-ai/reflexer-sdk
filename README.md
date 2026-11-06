# reflexer

Reflexer's SDK for Python and TypeScript. It sends your LLM calls through reflexer, on the provider SDK you already use: one line of your code changes. If reflexer does not answer a call, or cannot be reached, the call goes to your provider as before.

It has no dependency of its own: it plugs into the HTTP client of the provider SDK you have. Its security promises, and the check that holds each one: [SECURITY.md](SECURITY.md).

## Quick start

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

Add your reflexer key, given at onboarding, to the client you already make. Your provider's key and settings stay as they were.

<!-- example: served -->
```python
import os, reflexer.openai
# client = openai.OpenAI()
client = reflexer.openai.OpenAI(reflexer_key=os.environ["REFLEXER_KEY"])
answer = client.chat.completions.create(model="your-model", messages=[{"role": "user", "content": "Hi"}])
print(answer.choices[0].message.content)
```

<!-- example: served -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";
// const client = new OpenAI();
const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY });
const answer = await client.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] });
console.log(answer.choices[0].message.content);
```

## More

- [Python](docs/python.md): OpenAI, Azure, Anthropic, Gemini, LangChain, Pydantic AI; on Bedrock: boto3, aiobotocore, LangChain, Pydantic AI, Strands, Anthropic's Bedrock clients, LiteLLM.
- [TypeScript](docs/typescript.md): OpenAI, Azure, Anthropic, Gemini, the AI SDK, LangChain.js; on Bedrock: the AWS SDK, LangChain.js, AnthropicBedrock, the AI SDK.
- Both: skipping reflexer for one call, sampling, who answered.
- [What your code sees](docs/behaviour.md): reflexer's answer, and what happens when it is down or slow.
- [Known limits](SECURITY.md#known-limits). [Contributing](CONTRIBUTING.md).
