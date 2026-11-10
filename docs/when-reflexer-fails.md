# When reflexer fails

This page is for a call that did not work as you expected. In most cases you do nothing: the SDK sends the call directly to your provider, as if reflexer were not there.

| Situation | What reflexer does | What you do |
|---|---|---|
| Reflexer is down or unreachable | The SDK sends the call directly to your provider and logs a warning | Nothing |
| Reflexer is busy or failing (a 429 or a 5xx) | The same | Nothing |
| Your provider answers with an error (a 429, a 5xx…) | Reflexer passes the error to your provider SDK. Your provider SDK handles it as it does without reflexer, retries included. If Bedrock refuses the call that reflexer forwards: [Known limits](limits.md#amazon-bedrock) | As without reflexer |
| Reflexer's answer stops before it is complete | Your provider SDK raises its error for an incomplete answer. The SDK does not send the call to your provider | As for an incomplete answer from your provider |
| Reflexer is slow | Python: your timeout ends the wait. TypeScript: `headersTimeout` ends the wait (300 s by default). Then the SDK sends the call directly to your provider | Set your timeout as before. In TypeScript, you can lower `headersTimeout` ([Advanced](advanced.md#how-long-reflexer-may-take)) |
| Your reflexer key is malformed | The SDK raises an error when you make the client, before any call | Copy the key again from onboarding |
| Reflexer refuses your key | Your provider SDK raises its own authentication error | Check the key, or ask for a new one |
| Your key was revoked less than a day ago | The SDK sends calls directly to your provider and logs a warning | Ask for a new key |
| Your provider SDK is a release reflexer is not tested on | The SDK raises an error at import or at the first call. The SDK does not check the release of the AI SDK's OpenAI, Anthropic and Google providers | Use a supported release (each library page lists them) |
| One call must not go through reflexer | — | Skip reflexer for that call: [Advanced](advanced.md#skip-reflexer-for-one-call) |

**Before you begin:** you need a working call through reflexer, from your library's page.

## Reflexer is down or unreachable

**Problem:** the SDK could not reach reflexer, or the reply did not come from reflexer. Examples: a refused connection, a TLS error, a reply that is not HTTP, an error from a proxy or a load balancer. This is normal during an outage, or on a network that blocks reflexer.

**What happens:** the SDK sends the call directly to your provider, and your code gets your provider's answer. The SDK logs a warning that names the failure. The warning never contains the text of a message. Python logs it on the `reflexer` logger; TypeScript logs it with `console.warn`. After a failure, the SDK also sends the next calls directly to your provider, for about one second. Each further failure in a row doubles this time, up to one minute. After this time, the SDK tries reflexer again.

**Trigger it:** give the SDK an address where nothing listens. In the warning, "straight" means "directly to your provider, without reflexer".

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

**Problem:** reflexer answered with a 429 or a 5xx, or reflexer asked the SDK to send calls to your provider for some time. This is normal when reflexer receives many calls at once.

**What happens:** the SDK sends the call directly to your provider. After a failure, the SDK also sends the next calls directly to your provider, as when reflexer is down. When two answers in a row from reflexer ask for this, the SDK sends the next calls directly to your provider, for the time that reflexer asked. The SDK never follows a redirect from reflexer: it sends that call directly to your provider.

## Reflexer is slow

**Problem:** reflexer did not answer before your timeout.

**What happens, Python:** your client's own timeout also applies to the call to reflexer. google-genai sets no timeout by default: set one in `http_options={"timeout": ...}`. When the timeout expires, the SDK sends the call directly to your provider, with the same timeout. So a call can take up to twice your timeout. If reflexer had already forwarded the call, your provider may run the call twice, and bill it twice.

**What happens, TypeScript:** the SDK waits `headersTimeout` (300 seconds by default) for the start of reflexer's answer. Then the SDK sends the call directly to your provider. Your client's own timeout applies to both calls. If your timeout expires first, that try fails with a timeout error. After this failure, the SDK sends calls directly to your provider for a short time, so a retry by your provider SDK goes directly to your provider. On Bedrock, some clients behave differently: [Known limits](limits.md#amazon-bedrock). If reflexer had already forwarded the call, your provider may run the call twice, and bill it twice. To wait less: [Advanced](advanced.md#how-long-reflexer-may-take).

## Your reflexer key is malformed

**Problem:** the key does not have reflexer's form, `rfx1_...`. For example, part of the key is missing, or the key has a typo.

**What happens:** the SDK raises an error when you make the client, before it sends anything.

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

**Problem:** the key has the right form, but reflexer does not accept it.

**What happens:** your provider SDK raises its own authentication error, the same error that a refusal from your provider gives. The SDK does not send the call to your provider. One exception: if the key was revoked less than a day ago, the SDK sends calls directly to your provider and logs the warning "the reflexer key is revoked; calls go straight to the provider until its grace ends".

## Your provider SDK is a release reflexer is not tested on

**Problem:** you use a new major version of your provider SDK, or (TypeScript) a release older than the oldest supported release.

**What happens:** in Python, importing reflexer's module for your provider SDK raises `ImportError`. In TypeScript, the SDK throws an error at import (`openai`, `@anthropic-ai/sdk`), or at the first call in place of the answer (`@google/genai`, Bedrock's libraries). So the SDK never sends a call to a place you did not expect. Each library page lists the supported releases.

For every other limit, library by library: [Known limits](limits.md).

Next: [Advanced](advanced.md) · [Reference](reference.md)
