# reflexer with Gemini

Send your Gemini calls through reflexer, in Python or TypeScript: change one import and one line.

**Before you begin:** you need `google-genai` 2 (Python) or `@google/genai` 2 from 2.29.0 (TypeScript), and the environment variable `REFLEXER_KEY` set to the reflexer key you got at onboarding. The examples are plain JavaScript: in a `.ts` file, write the key as `process.env.REFLEXER_KEY!`.

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
- from google.genai import Client
+ from reflexer.gemini import Client

- client = Client()
+ client = Client(reflexer_key=os.environ["REFLEXER_KEY"])
  reply = client.models.generate_content(model="frontier-x", contents="Hi")
  print(reply.text)
```

```text
Hello! How can I help you today?
```

TypeScript: the same change.

<!-- example: served js -->
```diff
- import { GoogleGenAI } from "@google/genai";
+ import { GoogleGenAI } from "@reflexer-ai/sdk/gemini";

- const client = new GoogleGenAI({});
+ const client = new GoogleGenAI({ reflexerKey: process.env.REFLEXER_KEY });
  const reply = await client.models.generateContent({ model: "frontier-x", contents: "Hi" });
  console.log(reply.text);
```

```text
Hello! How can I help you today?
```

Make async calls with `client.aio`, as before.

## 3. Verify

The reply looks the same whether reflexer or Gemini answered. The `Reflexer-Answered-By` header names who answered: `reflexer`, or `provider` when reflexer forwarded the call to Gemini. The reply has no such header when the SDK sent the call directly to Gemini.

<!-- example: served -->
```python
import os
from reflexer.gemini import Client

client = Client(reflexer_key=os.environ["REFLEXER_KEY"])
reply = client.models.generate_content(model="frontier-x", contents="Hi")
print(reply.sdk_http_response.headers["reflexer-answered-by"])
```

```text
reflexer
```

<!-- example: served -->
```js
import { GoogleGenAI } from "@reflexer-ai/sdk/gemini";

const client = new GoogleGenAI({ reflexerKey: process.env.REFLEXER_KEY });
const reply = await client.models.generateContent({ model: "frontier-x", contents: "Hi" });
console.log(reply.sdkHttpResponse.headers["reflexer-answered-by"]);
```

```text
reflexer
```

A reply from reflexer has a `model_version` (TypeScript `modelVersion`) that ends in `-reflexer`. Gemini's reply has no field for a price, so reflexer puts the price, in nano USD, in the `Reflexer-Cost` header.

## Behavior

- **Reflexer down, slow or busy:** the SDK sends the call directly to Gemini, and your code gets Gemini's answer. The SDK logs a warning (Python: on the `reflexer` logger; TypeScript: with `console.warn`). After a failure, the SDK sends the next calls directly to Gemini too, for about a minute at most. Then the SDK tries reflexer again.
- **Timeouts, Python:** your client's timeout applies to the call to reflexer. If that timeout expires, the SDK sends the call directly to Gemini, with the same timeout. So one call can take up to two times your timeout. If reflexer had already forwarded the call, Gemini may run the call twice and bill it twice.
- **Timeouts, TypeScript:** if reflexer's answer has not started after `headersTimeout` (300 seconds by default), the SDK sends the call directly to Gemini. If your client's own timeout expires first, that attempt fails with a timeout error. If your provider SDK then retries the call, the SDK sends the retry directly to Gemini. In both cases, if reflexer had already forwarded the call, Gemini may run the call twice and bill it twice.
- **Key refused:** if reflexer refuses your reflexer key, your provider SDK raises its authentication error, and the SDK does not send the call to Gemini. If your reflexer key was revoked less than one day ago, the SDK still sends your calls directly to Gemini, and logs a warning.
- **Which calls:** the SDK sends to reflexer only the calls that return a model's message. The SDK sends all other calls, and all calls to `http`, `localhost` or a private IP, to the address your code gave them, as before.
- **What leaves your machine:** the SDK sends the call to reflexer, with your Gemini key. When reflexer does not answer the call itself, reflexer uses this key to forward the call to Gemini. Only reflexer receives your reflexer key.
- **No timeout by default, Python:** google-genai sets no timeout, so no timeout of yours limits how long a call waits for reflexer. Set one in `http_options={"timeout": 60_000}` (milliseconds).
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. If you remove the line, your code works as before.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).

## Options

- `sample=0.01` (TypeScript `sample: 0.01`): the SDK sends that share of the calls to reflexer, and the other calls directly to Gemini.
- `config={"http_options": {"headers": {"Reflexer-Pass-Through": "1"}}}` on a call (TypeScript: `config: { httpOptions: { headers: { "Reflexer-Pass-Through": "1" } } }`): the SDK sends that call directly to Gemini.
- `config={"http_options": {"extra_body": {"replay_response": answer}}}` on a call (TypeScript: `config: { httpOptions: { extraBody: { replay_response: answer } } }`): a [dry run](advanced.md#a-dry-run-give-reflexer-your-providers-answer). You give reflexer your Gemini answer, and neither the SDK nor reflexer sends the call to Gemini.
- `reflexer_base=` (TypeScript `reflexerBase`): reflexer's address, if reflexer gave you another one.

All options: [Advanced](advanced.md).

## Supported versions

`google-genai` 2 on Python 3.10+, `@google/genai` 2 from 2.29.0 on Node 20.3+. With another release, the SDK raises an error before any call. `@google/genai` before 2.23.0 does not accept a `fetch`, so the SDK cannot send its calls to reflexer: they go directly to Gemini.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
