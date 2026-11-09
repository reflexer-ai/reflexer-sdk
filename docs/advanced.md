# Advanced

For tuning reflexer once your calls go through it. Each section: what it does, its default, then how.

## Skip reflexer for one call

The `Reflexer-Pass-Through` header sends one call to your provider; it is taken off before the call leaves your machine, but for a few Bedrock clients ([Known limits](limits.md)). Every call goes through reflexer by default.

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

| Library | How to skip |
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

langchain-aws, Strands and Pydantic AI on Bedrock make the boto3 call themselves: set the header by a hook on the client, for as long as it is registered.

<!-- example: straight bedrock -->
```python
import os
from langchain_aws import ChatBedrockConverse
import reflexer.boto3

client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
chat = ChatBedrockConverse(model="frontier-x", client=client)

def skip_reflexer(request, **_):
    request.headers["Reflexer-Pass-Through"] = "1"

client.meta.events.register("before-sign.bedrock-runtime.Converse", skip_reflexer)
print(chat.invoke("Hi").content)
client.meta.events.unregister("before-sign.bedrock-runtime.Converse", skip_reflexer)
```

```text
Hello! How can I help you today?
```

LangChain.js on Bedrock: the same header, set by a middleware of yours on the AWS SDK client. In a `.ts` file, `client.send(command, { reflexerPassThrough: true })` needs its options cast to `any`.

## A dry run: give reflexer your provider's answer

A call whose body carries your provider's answer, in the field `replay_response` at its top, is a dry run: reflexer answers, or compares its answer with yours, as if your provider had answered with it, and your provider is never called. Calls carry no such field by default. A dry run goes to reflexer whatever the share of calls sent there. If reflexer cannot take it (down, busy, failing), or the call cannot go to reflexer (it carries the skip header, is no call for a model's message, or its address is one reflexer cannot reach: `http`, local, private), the call fails instead of going to your provider: with `ReplayNotTaken`, or with your SDK's connection error caused by it, as your SDK reports its HTTP client's failures. The reply is reflexer's answer, or your own when reflexer has none: `Reflexer-Answered-By` is `reflexer` on the first and absent on the second ([what reflexer adds](reference.md#what-reflexer-adds-to-a-response)).

<!-- example: served python -->
```python
import os
from reflexer.openai import OpenAI

client = OpenAI(reflexer_key=os.environ["REFLEXER_KEY"])
answer = {"id": "chatcmpl-made-up", "object": "chat.completion", "created": 1, "model": "frontier-x",
          "choices": [{"index": 0, "finish_reason": "stop",
                       "message": {"role": "assistant", "content": "Hello! How can I help you today?"}}]}
reply = client.chat.completions.create(model="frontier-x", messages=[{"role": "user", "content": "Hi"}],
                                       extra_body={"replay_response": answer})
print(reply.choices[0].message.content)
```

```text
Hello! How can I help you today?
```

<!-- example: served js -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";

const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY });
const answer = { id: "chatcmpl-made-up", object: "chat.completion", created: 1, model: "frontier-x",
  choices: [{ index: 0, finish_reason: "stop", message: { role: "assistant", content: "Hello! How can I help you today?" } }] };
const reply = await client.chat.completions.create({ model: "frontier-x", messages: [{ role: "user", content: "Hi" }],
  replay_response: answer });
console.log(reply.choices[0].message.content);
```

```text
Hello! How can I help you today?
```

Gemini takes the field in the call's `http_options`:

<!-- example: served python -->
```python
import os
from reflexer.gemini import Client

client = Client(reflexer_key=os.environ["REFLEXER_KEY"])
answer = {"candidates": [{"content": {"role": "model", "parts": [{"text": "Hello! How can I help you today?"}]}}]}
reply = client.models.generate_content(model="frontier-x", contents="Hi",
                                       config={"http_options": {"extra_body": {"replay_response": answer}}})
print(reply.text)
```

```text
Hello! How can I help you today?
```

<!-- example: served js -->
```js
import { GoogleGenAI } from "@reflexer-ai/sdk/gemini";

const client = new GoogleGenAI({ reflexerKey: process.env.REFLEXER_KEY });
const answer = { candidates: [{ content: { role: "model", parts: [{ text: "Hello! How can I help you today?" }] } }] };
const reply = await client.models.generateContent({ model: "frontier-x", contents: "Hi",
  config: { httpOptions: { extraBody: { replay_response: answer } } } });
console.log(reply.text);
```

```text
Hello! How can I help you today?
```

On Bedrock, the field goes in the body of `InvokeModel`, which you write; Converse has no place for it:

<!-- example: served bedrock -->
```python
import json, os
import reflexer.boto3

client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
answer = {"id": "msg_made-up", "type": "message", "role": "assistant", "model": "frontier-x", "stop_reason": "end_turn",
          "content": [{"type": "text", "text": "Hello! How can I help you today?"}]}
body = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 64, "messages": [{"role": "user", "content": "Hi"}],
        "replay_response": answer}
reply = json.loads(client.invoke_model(modelId="frontier-x", body=json.dumps(body))["body"].read())
print(reply["content"][0]["text"])
```

```text
Hello! How can I help you today?
```

<!-- example: served bedrock -->
```js
import { BedrockRuntimeClient, InvokeModelCommand } from "@aws-sdk/client-bedrock-runtime";
import * as bedrock from "@reflexer-ai/sdk/bedrock";

const client = bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1" }), process.env.REFLEXER_KEY);
const answer = { id: "msg_made-up", type: "message", role: "assistant", model: "frontier-x", stop_reason: "end_turn",
  content: [{ type: "text", text: "Hello! How can I help you today?" }] };
const body = { anthropic_version: "bedrock-2023-05-31", max_tokens: 64, messages: [{ role: "user", content: "Hi" }],
  replay_response: answer };
const reply = await client.send(new InvokeModelCommand({ modelId: "frontier-x", body: JSON.stringify(body), contentType: "application/json" }));
console.log(JSON.parse(new TextDecoder().decode(reply.body)).content[0].text);
```

```text
Hello! How can I help you today?
```

Where each library takes it:

| Library | Where the field goes |
|---|---|
| OpenAI, Anthropic, Anthropic's Bedrock clients (Python) | `extra_body={"replay_response": answer}` on the call |
| Gemini (Python) | `config={"http_options": {"extra_body": {"replay_response": answer}}}` |
| boto3, aiobotocore | the body of an `InvokeModel` call, at its top |
| OpenAI, Anthropic (TypeScript) | `replay_response: answer` among the call's parameters |
| Gemini (TypeScript) | `config: { httpOptions: { extraBody: { replay_response: answer } } }` |
| The AWS SDK for JavaScript | the body of an `InvokeModelCommand`, at its top |

The answer takes the form your provider's would: your provider's whole answer for a call that is not streamed, as above; the text of its stream, as one string, for a streamed call. Reflexer refuses another form, and any dry run on Bedrock's streamed calls (`InvokeModelWithResponseStream`, `ConverseStream`), with a 400: your SDK raises its error for a bad request.

A body given as a stream is not read, so a dry run sent that way is not seen as one, and goes as any other call: give the body whole, as the provider SDKs do ([Known limits](limits.md#every-library)).

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

Every reflexer client, and every function that takes the key, takes `sample`; in TypeScript, the `fetch` functions and `bedrock.wrap` in their options.

## How long reflexer may take

Python: your client's own timeout covers the call to reflexer. When it fires, the call goes to your provider with the same timeout, so a call can take up to twice your timeout; if reflexer had already forwarded the call, your provider may run it, and bill it, twice. Set the timeout as you would without reflexer. google-genai sets none by default: set one, `http_options={"timeout": 60_000}` (milliseconds).

TypeScript: `headersTimeout` is how long the call to reflexer waits for its answer to start, then the call goes to your provider. By default 300 seconds. Set it in the options of a `fetch` or `bedrock.wrap`; reflexer's classes do not take it. Your client's own timeout covers both calls: if it fires first, that try fails as a timeout, and a retry of your SDK's, if it makes one, goes to your provider; if reflexer had already forwarded the call, your provider may run it, and bill it, twice.

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

Reflexer's calls go by your HTTP client, with its proxy and TLS settings; its hooks (httpx's `event_hooks`) see your calls to your provider, never reflexer's, which carry the reflexer key; its transport, or its own `send`, carries both ([Security](../SECURITY.md), P8): one that logs headers logs the reflexer key too. In TypeScript your `fetch` carries both. Give it to reflexer's class as before (`http_client=`; Gemini `http_options={"httpx_client": ...}`; TypeScript `fetch`, Gemini `httpOptions: { fetch }`), or to a function as `own=` (TypeScript `{ fetch }`). [Another library](other-libraries.md) shows each. LangChain's `ChatOpenAI` (Python) given no HTTP client puts its `openai_proxy`, or `OPENAI_PROXY`, on the HTTP client it makes, so reflexer's calls go by your proxy too.

## Async

`AsyncOpenAI`, `AsyncAzureOpenAI`, `AsyncAnthropic`, `AsyncAnthropicBedrock` and `AsyncAnthropicBedrockMantle` change as their sync classes do; Gemini's `client.aio` as before; aiobotocore and `reflexer.litellm.async_client` on [Bedrock](bedrock.md).

Next: [Reference](reference.md) · [When reflexer fails](when-reflexer-fails.md)
