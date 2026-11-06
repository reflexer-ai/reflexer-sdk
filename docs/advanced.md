# Advanced

For tuning reflexer once your calls go through it. Each section: what it does, its default, then how.

## Skip reflexer for one call

The `Reflexer-Pass-Through` header sends one call to your provider. It never leaves your machine. Every call goes through reflexer by default.

<!-- example: straight -->
```python
import os
from reflexer.openai import OpenAI

client = OpenAI(reflexer_key=os.environ["REFLEXER_KEY"])
reply = client.chat.completions.create(model="frontier-x", messages=[{"role": "user", "content": "Hi"}],
                                       extra_headers={"Reflexer-Pass-Through": "1"})
print(reply.choices[0].message.content)
```

```text
Hello! How can I help you today?
```

<!-- example: straight -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";

const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY });
const reply = await client.chat.completions.create({ model: "frontier-x", messages: [{ role: "user", content: "Hi" }] },
  { headers: { "Reflexer-Pass-Through": "1" } });
console.log(reply.choices[0].message.content);
```

```text
Hello! How can I help you today?
```

On Bedrock the skip is an argument of the call:

<!-- example: straight bedrock -->
```python
import os
import reflexer.boto3

client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
reply = client.converse(modelId="frontier-x", messages=[{"role": "user", "content": [{"text": "Hi"}]}], ReflexerPassThrough=True)
print(reply["output"]["message"]["content"][0]["text"])
```

```text
Hello! How can I help you today?
```

<!-- example: straight bedrock -->
```js
import { BedrockRuntimeClient, ConverseCommand } from "@aws-sdk/client-bedrock-runtime";
import * as bedrock from "@reflexer-ai/sdk/bedrock";

const client = bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1" }), process.env.REFLEXER_KEY);
const command = new ConverseCommand({ modelId: "frontier-x", messages: [{ role: "user", content: [{ text: "Hi" }] }] });
console.log((await client.send(command, { reflexerPassThrough: true })).output.message.content[0].text);
```

```text
Hello! How can I help you today?
```

Where each library takes it:

| Library | The skip |
|---|---|
| OpenAI, Anthropic, Anthropic's Bedrock clients, LiteLLM, LangChain's `ChatOpenAI` (Python) | `extra_headers={"Reflexer-Pass-Through": "1"}` on the call |
| Gemini (Python) | `config={"http_options": {"headers": {"Reflexer-Pass-Through": "1"}}}` |
| LangChain's `ChatGoogleGenerativeAI` | `http_options={"headers": {"Reflexer-Pass-Through": "1"}}` on `invoke` |
| Pydantic AI (OpenAI, Anthropic) | `model_settings={"extra_headers": {"Reflexer-Pass-Through": "1"}}` on the run |
| boto3, aiobotocore | `ReflexerPassThrough=True` on the call |
| OpenAI, Anthropic, AnthropicBedrock (TypeScript) | `{ headers: { "Reflexer-Pass-Through": "1" } }` as the call's second argument |
| Gemini (TypeScript) | `config: { httpOptions: { headers: { "Reflexer-Pass-Through": "1" } } }` |
| The AI SDK | `headers: { "Reflexer-Pass-Through": "1" }` in `generateText`; on Bedrock, `providerOptions: { reflexer: { passThrough: true } }` |
| LangChain.js | `invoke("Hi", { options: { headers: { "Reflexer-Pass-Through": "1" } } })` |
| The AWS SDK for JavaScript | `client.send(command, { reflexerPassThrough: true })` |

langchain-aws, Strands, Pydantic AI on Bedrock and LangChain.js on Bedrock make the call themselves: [Known limits](../SECURITY.md#known-limits).

## Send a share of the calls

`sample` is the share of calls that go to reflexer; the rest go to your provider. By default 1: every call. Each call is drawn on its own.

<!-- example: straight -->
```python
import os
from reflexer.openai import OpenAI

client = OpenAI(reflexer_key=os.environ["REFLEXER_KEY"], sample=0.01)  # 1% to reflexer
reply = client.chat.completions.create(model="frontier-x", messages=[{"role": "user", "content": "Hi"}])
print(reply.choices[0].message.content)
```

```text
Hello! How can I help you today?
```

<!-- example: straight -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";

const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY, sample: 0.01 }); // 1% to reflexer
const reply = await client.chat.completions.create({ model: "frontier-x", messages: [{ role: "user", content: "Hi" }] });
console.log(reply.choices[0].message.content);
```

```text
Hello! How can I help you today?
```

Every reflexer client and function takes `sample`; in TypeScript, the `fetch` functions and `bedrock.wrap` in their options.

## How long reflexer may take

Python: your client's own timeout covers the call to reflexer; when it fires, the call goes to your provider with the same timeout. Set the timeout as you would without reflexer.

TypeScript: `headersTimeout` is how long the call to reflexer waits for its answer to start, then the call goes to your provider. By default 300 seconds. Set it in the options of a `fetch` or `bedrock.wrap`; reflexer's classes do not take it.

<!-- example: served -->
```js
import OpenAI from "openai";
import * as reflexer from "@reflexer-ai/sdk";

const fetch = reflexer.openai.fetch(process.env.REFLEXER_KEY, { headersTimeout: 10_000 }); // 10 s, then to OpenAI
const reply = await new OpenAI({ fetch }).chat.completions.create({ model: "frontier-x", messages: [{ role: "user", content: "Hi" }] });
console.log(reply.choices[0].message.content);
```

```text
Hello! How can I help you today?
```

## Reflexer's address

`https://api.reflexer.ai` by default. If you were given another: `reflexer_base=` on a Python class or `reflexer.boto3.client`, `base=` on the other Python functions; `reflexerBase` on a TypeScript class, `base` in a `fetch`'s or `bedrock.wrap`'s options. It must be `https`.

## Your own HTTP client

Reflexer's calls go by your HTTP client, with its proxy, TLS settings and hooks: give it to reflexer's class as before (`http_client=`; TypeScript `fetch`), or to a function as `own=` (TypeScript `{ fetch }`). [Another library](other-libraries.md) shows each.

## Async

`AsyncOpenAI`, `AsyncAzureOpenAI`, `AsyncAnthropic`, `AsyncAnthropicBedrock` and `AsyncAnthropicBedrockMantle` change as their sync classes do; Gemini's `client.aio` as before; aiobotocore and `reflexer.litellm.async_client` on [Bedrock](bedrock.md).

Next: [Reference](reference.md) · [When reflexer fails](when-reflexer-fails.md)
