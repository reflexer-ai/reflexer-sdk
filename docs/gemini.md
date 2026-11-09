# reflexer with Gemini

Reflexer in front of your Gemini calls, Python or TypeScript, by changing one import and one line.

**Before you begin:** `google-genai` 2 (Python) or `@google/genai` 2 from 2.29.0 (TypeScript), and `REFLEXER_KEY` set to the key you got at onboarding. In a `.ts` file, write the key as `process.env.REFLEXER_KEY!`: the examples are plain JavaScript.

## 1. Install

Not on PyPI or npm yet: install from a clone of this repository ([README](../README.md#install)).

```sh
pip install --build-constraint reflexer-sdk/build-constraints.txt ./reflexer-sdk
```

```sh
npm install /path/to/reflexer-sdk/typescript/reflexer-ai-sdk-VERSION.tgz
```
## 2. Add the line

Python: change the import, and add your reflexer key at the end of the line that makes the client.

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

Async calls by `client.aio`, as before.

## 3. Verify

The reply looks the same either way. The `Reflexer-Answered-By` header says who answered: `reflexer`, or `provider` when reflexer forwarded the call to Gemini; it is absent when the call went to Gemini directly.

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

Gemini's reply has no field for a price: a reply from reflexer has a `model_version` (TypeScript `modelVersion`) ending in `-reflexer`, and its price, in nano USD, is in the `Reflexer-Cost` header.

## Behavior

- **Reflexer down, slow or busy:** the call goes to Gemini, and your code gets Gemini's answer. The SDK logs a warning (Python: the `reflexer` logger; TypeScript: `console.warn`). After a failure, the next calls go to Gemini too, for about a minute at most, then reflexer is tried again.
- **Timeouts, Python:** your client's timeout covers the call to reflexer. If it fires, the call goes to Gemini with the same timeout, so a call can take up to twice it. If reflexer had already forwarded the call, Gemini may run it, and bill it, twice.
- **Timeouts, TypeScript:** if reflexer's answer has not started after `headersTimeout` (300 seconds by default), the call goes to Gemini. If your client's own timeout fires first, that try fails as a timeout, and a retry of your SDK's, if it makes one, goes to Gemini. Either way, if reflexer had already forwarded the call, Gemini may run it, and bill it, twice.
- **Key refused:** if reflexer refuses your reflexer key, your SDK raises its authentication error; the call does not go to Gemini. A key revoked less than a day ago still sends calls to Gemini, with a warning.
- **Which calls:** only the calls that return a model's message go to reflexer. Other calls, and calls to `http`, `localhost` or a private IP, go where they were sent, as before.
- **What leaves your machine:** the call, with your Gemini key, goes to reflexer, which uses the key to forward the call to Gemini when it does not answer. The reflexer key goes to reflexer only.
- **No timeout by default, Python:** google-genai sets none, so nothing of yours bounds the wait at reflexer: set one in `http_options={"timeout": 60_000}` (milliseconds).
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. Remove the line and your code is as it was.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).

## Options

- `sample=0.01` (TypeScript `sample: 0.01`): send that share of the calls to reflexer, the rest to Gemini.
- `config={"http_options": {"headers": {"Reflexer-Pass-Through": "1"}}}` on a call (TypeScript: `config: { httpOptions: { headers: { "Reflexer-Pass-Through": "1" } } }`): that call goes to Gemini.
- `config={"http_options": {"extra_body": {"replay_response": answer}}}` on a call (TypeScript: `config: { httpOptions: { extraBody: { replay_response: answer } } }`): a [dry run](advanced.md#a-dry-run-give-reflexer-your-providers-answer), your Gemini answer given, which never reaches Gemini.
- `reflexer_base=` (TypeScript `reflexerBase`): reflexer's address, if you were given another.

All of them: [Advanced](advanced.md).

## Supported versions

`google-genai` 2 on Python 3.10+, `@google/genai` 2 from 2.29.0 on Node 20.3+. Another release raises before any call; `@google/genai` before 2.23.0 takes no `fetch`, so its calls go to Gemini.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
