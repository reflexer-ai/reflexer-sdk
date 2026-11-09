# reflexer with Anthropic

Reflexer in front of your Anthropic calls, Python or TypeScript, by changing one import and one line.

**Before you begin:** `anthropic` 2 (Python) or `@anthropic-ai/sdk` 1 (TypeScript), and `REFLEXER_KEY` set to the key you got at onboarding. In a `.ts` file, write the key as `process.env.REFLEXER_KEY!`: the examples are plain JavaScript.

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
- from anthropic import Anthropic
+ from reflexer.anthropic import Anthropic

- client = Anthropic()
+ client = Anthropic(reflexer_key=os.environ["REFLEXER_KEY"])
  reply = client.messages.create(model="frontier-x", max_tokens=1024, messages=[{"role": "user", "content": "Hi"}])
  print(reply.content[0].text)
```

```text
Hello! How can I help you today?
```

TypeScript: the same change.

<!-- example: served js -->
```diff
- import Anthropic from "@anthropic-ai/sdk";
+ import { Anthropic } from "@reflexer-ai/sdk/anthropic";

- const client = new Anthropic();
+ const client = new Anthropic({ reflexerKey: process.env.REFLEXER_KEY });
  const reply = await client.messages.create({ model: "frontier-x", max_tokens: 1024, messages: [{ role: "user", content: "Hi" }] });
  console.log(reply.content[0].text);
```

```text
Hello! How can I help you today?
```

`AsyncAnthropic` changes the same way.

## 3. Verify

The reply looks the same either way. The `Reflexer-Answered-By` header says who answered: `reflexer`, or `provider` when reflexer forwarded the call to Anthropic; it is absent when the call went to Anthropic directly.

<!-- example: served -->
```python
import os
from reflexer.anthropic import Anthropic

client = Anthropic(reflexer_key=os.environ["REFLEXER_KEY"])
raw = client.messages.with_raw_response.create(model="frontier-x", max_tokens=1024, messages=[{"role": "user", "content": "Hi"}])
print(raw.headers["reflexer-answered-by"])
```

```text
reflexer
```

<!-- example: served -->
```js
import { Anthropic } from "@reflexer-ai/sdk/anthropic";

const client = new Anthropic({ reflexerKey: process.env.REFLEXER_KEY });
const { response } = await client.messages.create({ model: "frontier-x", max_tokens: 1024, messages: [{ role: "user", content: "Hi" }] }).withResponse();
console.log(response.headers.get("reflexer-answered-by"));
```

```text
reflexer
```

A reply from reflexer has a `model` ending in `-reflexer`, and `usage.cost` holds its price in USD.

## Behavior

- **Reflexer down, slow or busy:** the call goes to Anthropic, and your code gets Anthropic's answer. The SDK logs a warning (Python: the `reflexer` logger; TypeScript: `console.warn`). After a failure, the next calls go to Anthropic too, for about a minute at most, then reflexer is tried again.
- **Timeouts, Python:** your client's timeout covers the call to reflexer. If it fires, the call goes to Anthropic with the same timeout, so a call can take up to twice it. If reflexer had already forwarded the call, Anthropic may run it, and bill it, twice.
- **Timeouts, TypeScript:** if reflexer's answer has not started after `headersTimeout` (300 seconds by default), the call goes to Anthropic. If your client's own timeout fires first, that try fails as a timeout, and a retry of your SDK's, if it makes one, goes to Anthropic. Either way, if reflexer had already forwarded the call, Anthropic may run it, and bill it, twice.
- **Key refused:** if reflexer refuses your reflexer key, your SDK raises its authentication error; the call does not go to Anthropic. A key revoked less than a day ago still sends calls to Anthropic, with a warning.
- **Which calls:** only the calls that return a model's message go to reflexer. Other calls, and calls to `http`, `localhost` or a private IP, go where they were sent, as before.
- **What leaves your machine:** the call, with your Anthropic key, goes to reflexer, which uses the key to forward the call to Anthropic when it does not answer. The reflexer key goes to reflexer only.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. Remove the line and your code is as it was.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).

## Options

- `sample=0.01` (TypeScript `sample: 0.01`): send that share of the calls to reflexer, the rest to Anthropic.
- `extra_headers={"Reflexer-Pass-Through": "1"}` on a call (TypeScript: `{ headers: { "Reflexer-Pass-Through": "1" } }` as its second argument): that call goes to Anthropic.
- `reflexer_base=` (TypeScript `reflexerBase`): reflexer's address, if you were given another.
- Your own HTTP client, as `http_client=` (TypeScript `fetch`): reflexer's calls go by it too.

All of them: [Advanced](advanced.md).

## Supported versions

`anthropic` 2 on Python 3.10+, `@anthropic-ai/sdk` 1 on Node 20.3+. Another major raises before any call.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
