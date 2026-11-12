# reflexer with OpenAI

Send your OpenAI calls through reflexer, in Python or TypeScript: change one import and one line.

**Before you begin:** you need `openai` 3 (Python) or `openai` 7 (TypeScript), and the environment variable `REFLEXER_KEY` set to the reflexer key you got at onboarding. The examples are plain JavaScript: in a `.ts` file, write the key as `process.env.REFLEXER_KEY!`.

## 1. Install

The SDK is not on PyPI or npm yet. Install it from a clone of this repository ([README](../README.md#install)).

```sh
pip install --build-constraint reflexer-sdk/build-constraints.txt ./reflexer-sdk  # pip 26.1 or later
```

```sh
npm install /path/to/reflexer-sdk/typescript/reflexer-ai-sdk-VERSION.tgz
```
## 2. Add the line

Python: change the import. Then add your reflexer key as the last argument of the line that creates the client.

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

TypeScript: the same change.

<!-- example: served js -->
```diff
- import OpenAI from "openai";
+ import { OpenAI } from "@reflexer-ai/sdk/openai";

- const client = new OpenAI();
+ const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY });
  const reply = await client.chat.completions.create({ model: "frontier-x", messages: [{ role: "user", content: "Hi" }] });
  console.log(reply.choices[0].message.content);
```

```text
Hello! How can I help you today?
```

Change `AsyncOpenAI`, `AzureOpenAI` and `AsyncAzureOpenAI` the same way. Change any other client of OpenAI's format the same way, for example a client whose `base_url` (TypeScript: `baseURL`) points to a router. For chat completions to OpenRouter or Vercel AI Gateway, reflexer uses a route made for that router, so it handles the router's own request fields. Calls to the Responses API also go through reflexer.

## 3. Verify

The reply looks the same whether reflexer or OpenAI answered. The `Reflexer-Answered-By` header names who answered: `reflexer`, or `provider` when reflexer forwarded the call to OpenAI. The reply has no such header when the SDK sent the call directly to OpenAI.

<!-- example: served -->
```python
import os
from reflexer.openai import OpenAI

client = OpenAI(reflexer_key=os.environ["REFLEXER_KEY"])
raw = client.chat.completions.with_raw_response.create(model="frontier-x", messages=[{"role": "user", "content": "Hi"}])
print(raw.headers["reflexer-answered-by"])
```

```text
reflexer
```

<!-- example: served -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";

const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY });
const { response } = await client.chat.completions.create({ model: "frontier-x", messages: [{ role: "user", content: "Hi" }] }).withResponse();
console.log(response.headers.get("reflexer-answered-by"));
```

```text
reflexer
```

A reply from reflexer has a `model` that ends in `-reflexer`, and its `usage.cost` holds its price in USD.

## Behavior

- **Reflexer down, slow or busy:** the SDK sends the call directly to OpenAI, and your code gets OpenAI's answer. The SDK logs a warning (Python: on the `reflexer` logger; TypeScript: with `console.warn`). After a failure, the SDK sends the next calls directly to OpenAI too, for about a minute at most. Then the SDK tries reflexer again.
- **Timeouts, Python:** your client's timeout applies to the call to reflexer. If that timeout expires, the SDK sends the call directly to OpenAI, with the same timeout. So one call can take up to two times your timeout. If reflexer had already forwarded the call, OpenAI may run the call twice and bill it twice.
- **Timeouts, TypeScript:** if reflexer's answer has not started after `headersTimeout` (300 seconds by default), the SDK sends the call directly to OpenAI. If your own timeout expires first, while the call is at reflexer, the result depends on how your library ends the call. If your timeout ends the call with a `TimeoutError`, as `AbortSignal.timeout` and the AI SDK's `timeout` do, the SDK sends the call directly to OpenAI, with a new timeout as long as the time your timeout ran (the same length, when your timeout started with the call). So one call can take up to two times your timeout, and a cancel of yours does not stop that second call. A streamed AI SDK call fails instead, with a timeout error. The OpenAI, Anthropic and Gemini SDKs end a call at their timeout in the same way as at a cancel, so the SDK cannot tell the two apart: that attempt fails with a timeout error. If your provider SDK then retries the call, the SDK sends the retry directly to OpenAI. In every case, if reflexer had already forwarded the call, OpenAI may run the call twice and bill it twice.
- **Key refused:** if reflexer refuses your reflexer key, your provider SDK raises its authentication error, and the SDK does not send the call to OpenAI. If your reflexer key was revoked less than one day ago, the SDK still sends your calls directly to OpenAI, and logs a warning.
- **Which calls:** the SDK sends to reflexer only the calls that return a model's message. The SDK sends all other calls, and all calls to `http`, `localhost` or a private IP, to the address your code gave them, as before.
- **What leaves your machine:** the SDK sends the call to reflexer, with your OpenAI key. When reflexer does not answer the call itself, reflexer uses this key to forward the call to OpenAI. Only reflexer receives your reflexer key.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. If you remove the line, your code works as before.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).

## Options

- `sample=0.01` (TypeScript `sample: 0.01`): the SDK sends that share of the calls to reflexer, and the other calls directly to OpenAI.
- `extra_headers={"Reflexer-Skip": "true"}` on a call (TypeScript: `{ headers: { "Reflexer-Skip": "true" } }` as its second argument): the SDK sends that call directly to OpenAI.
- `extra_body={"replay_response": answer}` on a call (TypeScript: `replay_response: answer` among its parameters): a [dry run](advanced.md#a-dry-run-give-reflexer-your-providers-answer). You give reflexer your OpenAI answer, and neither the SDK nor reflexer sends the call to OpenAI.
- `reflexer_base=` (TypeScript `reflexerBase`): reflexer's address, if reflexer gave you another one.
- Your own HTTP client, as `http_client=` (TypeScript `fetch`): the SDK also sends the calls to reflexer through it.

All options: [Advanced](advanced.md).

## Supported versions

`openai` 3 on Python 3.10+, `openai` 7 on Node 20.3+ (openai 7 itself asks for Node 22; the SDK's tests also run on Node 20). With another major version, the SDK raises an error at import, before any call.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
