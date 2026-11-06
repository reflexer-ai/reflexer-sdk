# reflexer with Gemini

Reflexer in front of your Gemini calls, Python or TypeScript, by changing one import and one line.

**Before you begin:** the `google-genai` package (Python 2) or `@google/genai` (TypeScript 2, from 2.29.0), and `REFLEXER_KEY` set to the key you got at onboarding.

## 1. Install

Not on PyPI or npm yet: install from a clone of this repository ([README](../README.md#install)).

```sh
pip install ./reflexer-sdk
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

The reply looks the same either way. The `Reflexer-Answered-By` header says who answered: `reflexer`.

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

Gemini's reply has no field for a price: a served reply's `model_version` (TypeScript `modelVersion`) ends in `-reflexer`, and its price, in nano USD, is in the `Reflexer-Cost` header.

## Behavior

- **Reflexer down, slow or busy:** the call goes to Gemini, and your code gets Gemini's answer. The SDK logs a warning (Python: the `reflexer` logger; TypeScript: `console.warn`). After a failure, the next calls go to Gemini too, for about a minute at most, then reflexer is tried again.
- **Timeouts, Python:** your client's timeout covers the call to reflexer; if it fires, the call goes to Gemini with the same timeout, so a call can take up to twice it.
- **Timeouts, TypeScript:** after `headersTimeout` (300 seconds by default) the call goes to Gemini; your client's own timeout covers both calls, and if it fires first, that try fails as a timeout and your SDK's retry goes to Gemini.
- **What leaves your machine:** the call, with your Gemini key, goes to reflexer, which uses the key to call Gemini. The reflexer key goes to reflexer only.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. Remove the line and your code is as it was.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](../SECURITY.md#known-limits).
## Options

- `sample=0.01` (TypeScript `sample: 0.01`): send that share of the calls to reflexer, the rest to Gemini.
- `config={"http_options": {"headers": {"Reflexer-Pass-Through": "1"}}}` on a call (TypeScript: `config: { httpOptions: { headers: { "Reflexer-Pass-Through": "1" } } }`): that call goes to Gemini.
- `reflexer_base=` (TypeScript `reflexerBase`): reflexer's address, if you were given another.

All of them: [Advanced](advanced.md).

## Supported versions

`google-genai` 2 on Python 3.10+, `@google/genai` 2 from 2.29.0 on Node 20.3+. Another release raises before any call; `@google/genai` before 2.23.0 takes no `fetch`, so its calls go to Gemini.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
