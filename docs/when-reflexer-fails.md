# When reflexer fails

For when a call did not go as you expected. Most cases need nothing from you: the call goes to your provider, as it would without reflexer.

| Situation | What reflexer does | What you do |
|---|---|---|
| Reflexer is down or unreachable | The call goes to your provider; a warning is logged | Nothing |
| Reflexer is busy or failing (a 429 or a 5xx) | The same | Nothing |
| Reflexer is slow | Your timeout ends its wait; the call goes to your provider | Set your timeout as you would without reflexer |
| Your reflexer key is malformed | Raises when the client is made, before any call | Copy the key again from onboarding |
| Reflexer refuses your key | Your SDK raises its own authentication error | Check the key; ask for a new one |
| Your key was revoked in the last day | Calls go to your provider, with a warning | Ask for a new key |
| Your provider SDK is a release reflexer is not tested on | Raises at import or at the first call | Use a supported release (each library page lists them) |
| One call must not go through reflexer | — | Skip reflexer for that call: [Advanced](advanced.md#skip-reflexer-for-one-call) |

**Before you begin:** a working call through reflexer, from your library's page.

## Reflexer is down or unreachable

**Problem:** the SDK could not reach reflexer, or reflexer's answer was not one: a connection refused, a TLS error, a reply that is not HTTP. This is normal during an outage, or on a network that blocks reflexer.

**What happens:** the call goes to your provider, and your code gets its answer. The SDK logs a warning naming the failure, never a message's text: in Python on the `reflexer` logger, in TypeScript by `console.warn`. The next calls go to your provider too, for about a minute at most, then reflexer is tried again.

**Trigger it:** point the SDK at an address where nothing listens.

<!-- example: straight -->
```python
import os
from reflexer.openai import OpenAI

client = OpenAI(reflexer_key=os.environ["REFLEXER_KEY"], reflexer_base="https://127.0.0.1:1")
reply = client.chat.completions.create(model="frontier-x", messages=[{"role": "user", "content": "Hi"}])
print(reply.choices[0].message.content)
```

```text
the call to reflexer failed (ConnectError); it goes straight to the provider
Hello! How can I help you today?
```

<!-- example: straight -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";

const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY, reflexerBase: "https://127.0.0.1:1" });
const reply = await client.chat.completions.create({ model: "frontier-x", messages: [{ role: "user", content: "Hi" }] });
console.log(reply.choices[0].message.content);
```

```text
reflexer: the call to reflexer failed (TypeError); it goes straight to the provider
Hello! How can I help you today?
```

## Reflexer is busy or failing

**Problem:** reflexer answered with a 429 or a 5xx, or asked the SDK to send calls to your provider for a while. This is normal under load.

**What happens:** as when reflexer is down: the call goes to your provider, and the next ones too, for the time reflexer asked or about a minute at most.

## Reflexer is slow

**Problem:** reflexer took longer than your timeout to answer.

**What happens, Python:** your client's own timeout covers the call to reflexer. When it fires, the call goes to your provider with the same timeout, so a call can take up to twice your timeout; if reflexer had already passed the call on, your provider may run it twice.

**What happens, TypeScript:** the call to reflexer waits for its answer to start for `headersTimeout`, 300 seconds by default, then goes to your provider. Your client's own timeout covers both calls: if it fires first, that try fails as a timeout, and your SDK's retry goes to your provider; if reflexer had already passed the call on, your provider may run it twice. To wait less: [Advanced](advanced.md#how-long-reflexer-may-take).

## Your reflexer key is malformed

**Problem:** the key is not of reflexer's form, `rfx1_...`: cut short, or with a typo.

**What happens:** making the client raises, before anything is sent.

**Trigger it:**

<!-- example: raises -->
```python
from reflexer.openai import OpenAI

client = OpenAI(reflexer_key="rfx1_not-a-key")
```

```text
ValueError: not a reflexer key: expected rfx1_CLIENT_SECRET_CHECK, as given at onboarding
```

<!-- example: raises -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";

const client = new OpenAI({ reflexerKey: "rfx1_not-a-key" });
```

```text
Error: not a reflexer key: expected rfx1_CLIENT_SECRET_CHECK, as given at onboarding
```

## Reflexer refuses your key

**Problem:** the key has the right form, but reflexer does not take it.

**What happens:** your SDK raises its own authentication error, as your provider's refusal would: the call does not go to your provider. A key revoked less than a day ago still sends calls to your provider instead, with the warning "the reflexer key is revoked; calls go straight to the provider until its grace ends".

## Your provider SDK is a release reflexer is not tested on

**Problem:** a new major of your provider SDK, or (TypeScript) a release below the floor.

**What happens:** Python raises `ImportError` when you import reflexer's module for it; TypeScript throws at import (`openai`, `@anthropic-ai/sdk`) or at the first call (`@google/genai`, Bedrock's libraries), where the stock SDK would answer. Your calls never go astray. The supported releases are on each library page.

Every other limit, library by library: [Known limits](../SECURITY.md#known-limits).

Next: [Advanced](advanced.md) · [Reference](reference.md)
