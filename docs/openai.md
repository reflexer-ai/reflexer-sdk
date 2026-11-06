# reflexer with OpenAI

Reflexer in front of your OpenAI calls, Python or TypeScript, by changing one import and one line.

**Before you begin:** `openai` 3 (Python) or `openai` 7 (TypeScript), and `REFLEXER_KEY` set to the key you got at onboarding. In a `.ts` file, write the key as `process.env.REFLEXER_KEY!`: the examples are plain JavaScript.

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

`AsyncOpenAI`, `AzureOpenAI` and `AsyncAzureOpenAI` change the same way, and so does any client of OpenAI's format pointed elsewhere by `base_url` (TypeScript: `baseURL`), such as a router. The Responses API goes through too.

## 3. Verify

The reply looks the same either way. The `Reflexer-Answered-By` header says who answered: `reflexer`, or `provider` when reflexer forwarded the call to OpenAI; it is absent when the call went to OpenAI directly.

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

A reply from reflexer has a `model` ending in `-reflexer`, and `usage.cost` holds its price in USD.

## Behavior

- **Reflexer down, slow or busy:** the call goes to OpenAI, and your code gets OpenAI's answer. The SDK logs a warning (Python: the `reflexer` logger; TypeScript: `console.warn`). After a failure, the next calls go to OpenAI too, for about a minute at most, then reflexer is tried again.
- **Timeouts, Python:** your client's timeout covers the call to reflexer. If it fires, the call goes to OpenAI with the same timeout, so a call can take up to twice it. If reflexer had already forwarded the call, OpenAI may run it, and bill it, twice.
- **Timeouts, TypeScript:** if reflexer's answer has not started after `headersTimeout` (300 seconds by default), the call goes to OpenAI. If your client's own timeout fires first, that try fails as a timeout, and your SDK's retry goes to OpenAI. Either way, if reflexer had already forwarded the call, OpenAI may run it, and bill it, twice.
- **Key refused:** if reflexer refuses your reflexer key, your SDK raises its authentication error; the call does not go to OpenAI. A key revoked less than a day ago still sends calls to OpenAI, with a warning.
- **Which calls:** only the calls that return a model's message go to reflexer. Other calls, and calls to `http`, `localhost` or a private IP, go where they were sent, as before.
- **What leaves your machine:** the call, with your OpenAI key, goes to reflexer, which uses the key to forward the call to OpenAI when it does not answer. The reflexer key goes to reflexer only.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. Remove the line and your code is as it was.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).
## Options

- `sample=0.01` (TypeScript `sample: 0.01`): send that share of the calls to reflexer, the rest to OpenAI.
- `extra_headers={"Reflexer-Pass-Through": "1"}` on a call (TypeScript: `{ headers: { "Reflexer-Pass-Through": "1" } }` as its second argument): that call goes to OpenAI.
- `reflexer_base=` (TypeScript `reflexerBase`): reflexer's address, if you were given another.
- Your own HTTP client, as `http_client=` (TypeScript `fetch`): reflexer's calls go by it too.

All of them: [Advanced](advanced.md).

## Supported versions

`openai` 3 on Python 3.10+, `openai` 7 on Node 20.3+. Another major raises at import, before any call.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
