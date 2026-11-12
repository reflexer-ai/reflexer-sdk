# Advanced

This page shows how to tune reflexer after your calls go through it. Each section says what a setting does, what its default is, and how to set it.

## Skip reflexer for one call

By default, every call goes through reflexer. To skip reflexer for one call, set the `Reflexer-Skip` header to `true` on that call: the SDK then sends the call directly to your provider. With the value `false`, the SDK does not skip reflexer: the call goes as if it had no such header. The SDK reads the value in any case (`TRUE` is `true`). Any other value is an error: the SDK raises a `ValueError` (Python) or throws an `Error` (TypeScript) before it sends anything, or your provider SDK raises its connection error, caused by that error. The SDK removes this header: neither reflexer nor your provider receives it. The exception is a few Bedrock clients, which send the header to Bedrock ([Known limits](limits.md)).

<!-- example: straight -->
```python
import os
from reflexer.openai import OpenAI

client = OpenAI(reflexer_key=os.environ["REFLEXER_KEY"])
reply = client.chat.completions.create(model="frontier-x", messages=[{"role": "user", "content": "Hi"}],
                                       extra_headers={"Reflexer-Skip": "true"})
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
  { headers: { "Reflexer-Skip": "true" } });
console.log(reply.choices[0].message.content);
```

```text
Hello! How can I help you today?
```

On Bedrock, you skip reflexer with an argument of the call. Its value is a boolean: `false` does not skip reflexer, and any other value, the string `"false"` included, is an error, as for the header:

<!-- example: straight bedrock -->
```python
import os
import reflexer.boto3

client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
reply = client.converse(modelId="frontier-x", messages=[{"role": "user", "content": [{"text": "Hi"}]}], ReflexerSkip=True)
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
console.log((await client.send(command, { reflexerSkip: true })).output.message.content[0].text);
```

```text
Hello! How can I help you today?
```

Where each library takes it:

| Library | How to skip |
|---|---|
| OpenAI, Anthropic, Anthropic's Bedrock clients, LiteLLM, LangChain's `ChatOpenAI` (Python) | `extra_headers={"Reflexer-Skip": "true"}` on the call |
| Gemini (Python) | `config={"http_options": {"headers": {"Reflexer-Skip": "true"}}}` |
| LangChain's `ChatGoogleGenerativeAI` | `http_options={"headers": {"Reflexer-Skip": "true"}}` on `invoke` |
| Pydantic AI (OpenAI, Anthropic) | `model_settings={"extra_headers": {"Reflexer-Skip": "true"}}` on the run |
| boto3, aiobotocore | `ReflexerSkip=True` on the call |
| OpenAI, Anthropic, AnthropicBedrock (TypeScript) | `{ headers: { "Reflexer-Skip": "true" } }` as the call's second argument |
| Gemini (TypeScript) | `config: { httpOptions: { headers: { "Reflexer-Skip": "true" } } }` |
| The AI SDK | `headers: { "Reflexer-Skip": "true" }` in `generateText`; on Bedrock, `providerOptions: { reflexer: { skip: true } }` |
| LangChain.js | `invoke("Hi", { options: { headers: { "Reflexer-Skip": "true" } } })` |
| The AWS SDK for JavaScript | `client.send(command, { reflexerSkip: true })` |

On Bedrock, langchain-aws, Strands and Pydantic AI make the boto3 call themselves. For these libraries, set the header with a hook on the client. The hook sets the header on every call while the hook is registered.

<!-- example: straight bedrock -->
```python
import os
from langchain_aws import ChatBedrockConverse
import reflexer.boto3

client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
chat = ChatBedrockConverse(model="frontier-x", client=client)

def skip_reflexer(request, **_):
    request.headers["Reflexer-Skip"] = "true"

client.meta.events.register("before-sign.bedrock-runtime.Converse", skip_reflexer)
print(chat.invoke("Hi").content)
client.meta.events.unregister("before-sign.bedrock-runtime.Converse", skip_reflexer)
```

```text
Hello! How can I help you today?
```

LangChain.js on Bedrock: set the same header with your own middleware on the AWS SDK client. In a `.ts` file, cast the options of `client.send(command, { reflexerSkip: true })` to `any`.

## A dry run: give reflexer your provider's answer

A dry run is a call whose body carries your provider's answer, in the field `replay_response` at the top level of the body. On a dry run, reflexer answers, or compares its answer with yours, as if your provider had given your answer. Neither the SDK nor reflexer calls your provider. By default, calls carry no such field. The SDK sends every dry run to reflexer, whatever the share of calls in `sample`.

A dry run fails, and the SDK does not send it to your provider, in these cases: reflexer cannot accept it (reflexer is down, busy or failing), or the SDK cannot send the call to reflexer (the call carries the skip header, it is not a call for a model's message, or its address is one that reflexer cannot reach: `http`, local, private). The error is `ReplayNotTaken`, or the connection error of your provider SDK that `ReplayNotTaken` causes: this depends on how your provider SDK reports the failures of its HTTP client. The reply is reflexer's answer, or your own answer when reflexer has none. `Reflexer-Answered-By` is `reflexer` on reflexer's answer, and is absent on your own answer ([what reflexer adds](reference.md#what-reflexer-adds-to-a-response)).

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

On Bedrock, put the field in the body of `InvokeModel`; you write this body yourself. Converse has no place for the field:

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

Your answer has the form of your provider's answer. For a call that is not streamed, give your provider's whole answer, as above. For a streamed call, give the text of the stream as one string. reflexer refuses any other form with a 400. reflexer also refuses with a 400 any dry run on Bedrock's streamed calls (`InvokeModelWithResponseStream`, `ConverseStream`). On a 400, your provider SDK raises its error for a bad request.

The SDK does not read a body that you give as a stream. So the SDK does not detect a dry run sent in this way, and handles it as any other call. Give the whole body at once, as the provider SDKs do ([Known limits](limits.md#every-library)).

## Send a share of the calls

`sample` is the share of calls that the SDK sends to reflexer. The SDK sends the other calls directly to your provider. The default is 1: the SDK sends every call to reflexer. The SDK makes a separate random choice for each call.

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

Every reflexer client takes `sample`. Every function that takes the key also takes `sample`. In TypeScript, the `fetch` functions and `bedrock.wrap` take it in their options.

## Keep calls apart: a namespace

A namespace is a name for a group of your calls. reflexer keeps each group separate from your other calls. For example, use one namespace per product, team or environment, so that reflexer does not mix the calls of a test environment with the calls of production. If you give no namespace, your calls are in your default namespace. Give the namespace once, next to your key:

<!-- example: served -->
```python
import os
from reflexer.openai import OpenAI

client = OpenAI(reflexer_key=os.environ["REFLEXER_KEY"], reflexer_namespace="checkout")
reply = client.chat.completions.create(model="frontier-x", messages=[{"role": "user", "content": "Hi"}])
print(reply.choices[0].message.content)
```

```text
Hello! How can I help you today?
```

<!-- example: served -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";

const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY, reflexerNamespace: "checkout" });
const reply = await client.chat.completions.create({ model: "frontier-x", messages: [{ role: "user", content: "Hi" }] });
console.log(reply.choices[0].message.content);
```

```text
Hello! How can I help you today?
```

The SDK sends the namespace only to reflexer, never to your provider. To use another namespace on one call, set the `Reflexer-Namespace` header on that call. This header has priority over the client's namespace. Set it in the same way as for [skipping reflexer for one call](#skip-reflexer-for-one-call), with `Reflexer-Namespace` and your namespace in place of `Reflexer-Skip` and `true`. On Bedrock's signed calls, give the namespace on the client instead ([Known limits](limits.md#amazon-bedrock)). The functions that take the key take `namespace`, as they take `base`.

## Tell reflexer what to do with your calls

Four options tell reflexer what to do with your calls. You give them next to your key. If you do not give an option, the SDK sends nothing for it, and reflexer uses its default.

- `reflexer_answer` (TypeScript: `reflexerAnswer`), default `True`. With `False`, reflexer does not answer: it asks no model and no provider, and it returns an empty answer in your provider's format, so your code gets a reply with no text instead of an error. Reflexer's team tested this with the OpenAI and Anthropic SDKs, whole and streamed.
- `reflexer_store` (`reflexerStore`), default `True`. With `False`, reflexer keeps no copy of the call.
- `reflexer_pass_through` (`reflexerPassThrough`), default `False`. With `True`, reflexer never answers itself: it forwards the call to your provider (for a replay, it returns the replay's answer).
- `reflexer_timeout_ms` (`reflexerTimeoutMs`), default none. A whole number of milliseconds, from 1. reflexer waits at most this long for its own answer, then it forwards the call to your provider. This option can only make reflexer's own limit shorter: for a value above that limit, reflexer returns an error (HTTP 400).

<!-- example: served -->
```python
import os
from reflexer.openai import OpenAI

client = OpenAI(reflexer_key=os.environ["REFLEXER_KEY"], reflexer_store=False, reflexer_timeout_ms=2000)
reply = client.chat.completions.create(model="frontier-x", messages=[{"role": "user", "content": "Hi"}])
print(reply.choices[0].message.content)
```

```text
Hello! How can I help you today?
```

<!-- example: served -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";

const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY, reflexerStore: false, reflexerTimeoutMs: 2000 });
const reply = await client.chat.completions.create({ model: "frontier-x", messages: [{ role: "user", content: "Hi" }] });
console.log(reply.choices[0].message.content);
```

```text
Hello! How can I help you today?
```

The SDK checks each option when you create the client. `reflexer_answer`, `reflexer_store` and `reflexer_pass_through` must be `True` or `False` (a number or a string is refused). `reflexer_timeout_ms` must be a whole number from 1. For any other value, the SDK raises `ValueError` (TypeScript: `Error`). The SDK sends the options only to reflexer, never to your provider.

To change an option for one call, set its header on that call: `Reflexer-Answer`, `Reflexer-Store` or `Reflexer-Pass-Through` with `true` or `false`, or `Reflexer-Timeout-Ms` with a number of milliseconds. The header has priority over the client's option. Set it in the same way as for [skipping reflexer for one call](#skip-reflexer-for-one-call). On signed calls through Anthropic's Mantle client or the AI SDK, give the option on the client instead ([Known limits](limits.md#amazon-bedrock)). The SDK checks the header's value before it sends anything; for a wrong value, it raises `ValueError` (TypeScript: `Error`). The functions that take the key take `answer`, `store`, `pass_through` and `timeout_ms` (TypeScript options: `answer`, `store`, `passThrough`, `timeoutMs`), as they take `base`.

## How long reflexer may take

Python: your client's own timeout applies to the call to reflexer. When this timeout expires, the SDK sends the call directly to your provider, with the same timeout. So a call can take up to twice your timeout. If reflexer had already forwarded the call to your provider, your provider may run the call twice and bill it twice. Set the timeout as you would without reflexer. google-genai sets no timeout by default, so set one: `http_options={"timeout": 60_000}` (milliseconds).

TypeScript: `headersTimeout` is the time the SDK waits for reflexer's answer to start. After this time, the SDK sends the call directly to your provider. The default is 300 seconds. Set it in the options of a `fetch` or of `bedrock.wrap`; reflexer's classes do not take it. If your client's own timeout expires first and ends the call with a `TimeoutError` (`AbortSignal.timeout`, the AI SDK's `timeout`), the SDK sends the call directly to your provider, with a new timeout as long as the time your timeout ran. So a call can take up to twice your timeout. The OpenAI, Anthropic and Gemini SDKs end a call at their timeout in the same way as at a cancel, so the SDK cannot tell the two apart: that try fails with a timeout error. After this failure, the SDK sends calls directly to your provider for a short time, so a retry by your provider SDK goes directly to your provider. On Bedrock, some clients behave differently: [Known limits](limits.md#amazon-bedrock). If reflexer had already forwarded the call to your provider, your provider may run the call twice and bill it twice.

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

The default is `https://api.reflexer.ai`. If you received another address, give it with `reflexer_base=` on a Python class or `reflexer.boto3.client`, `base=` on the other Python functions; `reflexerBase` on a TypeScript class, `base` in a `fetch`'s or `bedrock.wrap`'s options. The address must use `https`.

## Your own HTTP client

The SDK sends its calls to reflexer through your HTTP client, with the client's proxy and TLS settings. Your client's hooks (httpx's `event_hooks`) see your calls to your provider. The hooks never see the calls to reflexer, which carry the reflexer key. Your client's transport, or its own `send`, carries both kinds of calls ([Security](../SECURITY.md), P8). So a transport or `send` that logs headers also logs the reflexer key. In TypeScript, your `fetch` carries both kinds of calls. Give your client to reflexer's class as before (`http_client=`; Gemini `http_options={"httpx_client": ...}`; TypeScript `fetch`, Gemini `httpOptions: { fetch }`), or to a function as `own=` (TypeScript `{ fetch }`). [Another library](other-libraries.md) shows each case. When you give LangChain's `ChatOpenAI` (Python) no HTTP client, it makes one and puts its `openai_proxy`, or `OPENAI_PROXY`, on it. So the SDK's calls to reflexer also go through your proxy. For LiteLLM, set its `client_session` and `aclient_session` before the line: the line keeps them, under its own clients.

## Async

You change `AsyncOpenAI`, `AsyncAzureOpenAI`, `AsyncAnthropic`, `AsyncAnthropicBedrock` and `AsyncAnthropicBedrockMantle` in the same way as their sync classes. Gemini's `client.aio` works as before. For aiobotocore, see [Bedrock](bedrock.md). LiteLLM's `acompletion` goes through reflexer by the same line as `completion` ([LiteLLM](litellm.md)).

Next: [Reference](reference.md) · [When reflexer fails](when-reflexer-fails.md)
