# Reference

For looking a name up. Every public name of the SDK takes the same few arguments: they come first, then the names, grouped by how they are used. How to use each: its library page.

## The arguments

**`reflexer_key`** (Python) · **`reflexerKey`** (TypeScript): `str`, required. Your reflexer key, `rfx1_...`, from onboarding; to get one, contact us at hello@reflexer.ai. Read it from the environment; never commit it. A key not of that form raises `ValueError` (TypeScript: `Error`) when the client is made. The functions take it as their first argument; `through` as its second.

**`reflexer_base`** · **`reflexerBase`** · **`base`**: `str`, optional, default `"https://api.reflexer.ai"`. Reflexer's address. `https` only. `base` is the name on functions (Python's `http_client`, `client_args`, `through`, `litellm.client`; TypeScript's `fetch` functions and `bedrock.wrap`).

**`sample`**: `float` from 0 to 1, optional, default 1. The share of calls that go to reflexer; the rest go to your provider. [Advanced](advanced.md#send-a-share-of-the-calls).

**`own`** (Python functions) · **`fetch`** (TypeScript options): optional, default your provider SDK's own. Your HTTP client or `fetch` (for `reflexer.gemini.client_args`, your `client_args` dict); reflexer's calls go by it too. [Advanced](advanced.md#your-own-http-client).

**`Reflexer-Pass-Through`** (a header) · **`ReflexerPassThrough`** (boto3's argument) · **`reflexerPassThrough`** (the AWS SDK's option): on one call, that call goes to your provider. [Advanced](advanced.md#skip-reflexer-for-one-call).

**`headersTimeout`** (TypeScript `fetch` functions and `bedrock.wrap`): milliseconds, optional, default 300000. How long the call to reflexer waits for its answer to start, then the call goes to your provider. [Advanced](advanced.md#how-long-reflexer-may-take).

## Python

### Clients

Each is the provider SDK's class, taking `reflexer_key`, `reflexer_base` and `sample` beside its own arguments; everything else is the stock class's.

| Name | Stock class | Page |
|---|---|---|
| `reflexer.openai.OpenAI` | `openai.OpenAI` | [openai](openai.md) |
| `reflexer.openai.AsyncOpenAI` | `openai.AsyncOpenAI` | [openai](openai.md) |
| `reflexer.openai.AzureOpenAI` | `openai.AzureOpenAI` | [openai](openai.md) |
| `reflexer.openai.AsyncAzureOpenAI` | `openai.AsyncAzureOpenAI` | [openai](openai.md) |
| `reflexer.anthropic.Anthropic` | `anthropic.Anthropic` | [anthropic](anthropic.md) |
| `reflexer.anthropic.AsyncAnthropic` | `anthropic.AsyncAnthropic` | [anthropic](anthropic.md) |
| `reflexer.gemini.Client` | `google.genai.Client` | [gemini](gemini.md) |
| `reflexer.langchain_openai.ChatOpenAI` | `langchain_openai.ChatOpenAI` | [langchain](langchain.md) |
| `reflexer.langchain_gemini.ChatGoogleGenerativeAI` | `langchain_google_genai.ChatGoogleGenerativeAI` | [langchain](langchain.md) |
| `reflexer.anthropic_bedrock.AnthropicBedrock` | `anthropic.AnthropicBedrock` | [bedrock](bedrock.md) |
| `reflexer.anthropic_bedrock.AsyncAnthropicBedrock` | `anthropic.AsyncAnthropicBedrock` | [bedrock](bedrock.md) |
| `reflexer.anthropic_bedrock.AnthropicBedrockMantle` | `anthropic.AnthropicBedrockMantle` | [bedrock](bedrock.md) |
| `reflexer.anthropic_bedrock.AsyncAnthropicBedrockMantle` | `anthropic.AsyncAnthropicBedrockMantle` | [bedrock](bedrock.md) |

<!-- example: served -->
```python
import os
from reflexer.anthropic import Anthropic

client = Anthropic(reflexer_key=os.environ["REFLEXER_KEY"], sample=1.0)
print(client.messages.create(model="frontier-x", max_tokens=1024, messages=[{"role": "user", "content": "Hi"}]).content[0].text)
```

```text
Hello! How can I help you today?
```

### Functions

| Name | Returns | Takes | Page |
|---|---|---|---|
| `reflexer.openai.http_client`, `async_http_client`, `azure_http_client`, `azure_async_http_client`; `reflexer.anthropic.http_client`, `async_http_client` | An HTTP client for the stock class's `http_client=` | `key, own=None, base=…, sample=1.0` | [other libraries](other-libraries.md) |
| `reflexer.gemini.http_client`, `async_http_client` | An HTTP client for google-genai's `httpx_client` and `httpx_async_client` | `key, own=None, base=…, sample=1.0` | [other libraries](other-libraries.md) |
| `reflexer.gemini.client_args` | A dict for both `client_args` and `async_client_args` | `key, own=None, base=…, sample=1.0` | [other libraries](other-libraries.md) |
| `reflexer.boto3.client` | A boto3 client | boto3's arguments, and `reflexer_key`, `reflexer_base`, `sample` | [bedrock](bedrock.md#boto3) |
| `reflexer.boto3.through`, `reflexer.aiobotocore.through` | The client given, now through reflexer | `client, reflexer_key, base=…, sample=1.0` | [bedrock](bedrock.md#aiobotocore) |
| `reflexer.litellm.client`, `async_client` | An HTTP handler for LiteLLM's `client=` | `reflexer_key, base=…, sample=1.0` | [bedrock](bedrock.md#litellm) |

<!-- example: served python bedrock -->
```python
import os
import boto3, reflexer.boto3

client = reflexer.boto3.through(boto3.client("bedrock-runtime", region_name="us-east-1"), os.environ["REFLEXER_KEY"], sample=1.0)
print(client.converse(modelId="frontier-x", messages=[{"role": "user", "content": [{"text": "Hi"}]}])["output"]["message"]["content"][0]["text"])
```

```text
Hello! How can I help you today?
```

## TypeScript

### Classes

Each is the provider SDK's class, taking `reflexerKey`, `reflexerBase` and `sample` beside its own options.

| Name | From | Stock class | Page |
|---|---|---|---|
| `OpenAI`, `AzureOpenAI` | `@reflexer-ai/sdk/openai` | `openai`'s | [openai](openai.md) |
| `Anthropic` | `@reflexer-ai/sdk/anthropic` | `@anthropic-ai/sdk`'s | [anthropic](anthropic.md) |
| `GoogleGenAI` | `@reflexer-ai/sdk/gemini` | `@google/genai`'s | [gemini](gemini.md) |

### Functions

| Name | From | Returns | Takes |
|---|---|---|---|
| `openai.fetch`, `azure.fetch`, `anthropic.fetch`, `gemini.fetch` | `@reflexer-ai/sdk` | A `fetch` for the provider SDK's `fetch` option | `key, { base, sample, fetch, headersTimeout }` |
| `wrap` | `@reflexer-ai/sdk/bedrock` | The AWS SDK client given, now through reflexer | `client, key, { base, sample, headersTimeout }` |
| `fetch` | `@reflexer-ai/sdk/bedrock` | A `fetch` for AnthropicBedrock | `key, { base, sample, fetch, headersTimeout }` |
| `anthropicMiddleware` | `@reflexer-ai/sdk/bedrock` | AnthropicBedrock's `middleware`, last of yours | (a value) |
| `requestHandler` | `@reflexer-ai/sdk/bedrock` | An AWS SDK request handler around your own, for a client that sets its own `requestHandler` and so cannot use `wrap`; give it the client's `signer` too, or signed calls go to Bedrock directly | `key, { handler, signer, base, sample, headersTimeout }` |
| `fetch` | `@reflexer-ai/sdk/bedrock-ai` | A `fetch` for the AI SDK's Bedrock provider | `key, { base, sample, fetch, headersTimeout }` |
| `middleware` | `@reflexer-ai/sdk/bedrock-ai` | For `wrapLanguageModel` | (a value) |

<!-- example: served -->
```js
import Anthropic from "@anthropic-ai/sdk";
import * as reflexer from "@reflexer-ai/sdk";

const client = new Anthropic({ fetch: reflexer.anthropic.fetch(process.env.REFLEXER_KEY, { sample: 1, headersTimeout: 300_000 }) });
console.log((await client.messages.create({ model: "frontier-x", max_tokens: 1024, messages: [{ role: "user", content: "Hi" }] })).content[0].text);
```

```text
Hello! How can I help you today?
```

## Errors

- A malformed key: `ValueError` (TypeScript `Error`), when the client is made. [When reflexer fails](when-reflexer-fails.md#your-reflexer-key-is-malformed).
- An untested release of your provider SDK: `ImportError` at import (TypeScript: `Error`, at import or at the first call). [When reflexer fails](when-reflexer-fails.md#your-provider-sdk-is-a-release-reflexer-is-not-tested-on).
- A reflexer address that is not `https`: `ValueError` (TypeScript `Error`), when the client is made.
- A `sample` that is not a number from 0 to 1: `ValueError` (TypeScript `Error`), when the client is made.
- `through` on a client already through reflexer: `ValueError`. aiobotocore on another HTTP session class: `TypeError`.
- TypeScript, Bedrock: `bedrock.wrap` or `requestHandler` on a handler already wrapped, or on the AWS SDK's fetch handler: `Error`, when wrapped.
- Anything else your code sees is your provider SDK's own error, as before.

## What reflexer adds to a response

- A reply from reflexer has a `model` ending in `-reflexer`, and `usage.cost` holds its price in USD, also in a stream's usage. Gemini's has no such field: `model_version` (TypeScript `modelVersion`) ends in `-reflexer`.
- Headers, on every response from reflexer: `Reflexer-Answered-By`, `reflexer`, or `provider` when reflexer forwarded the call; `Reflexer-Cost`, the price in nano USD; `Reflexer-Request-Id`, the call's id. A call that went to your provider directly has none.

## Versions

The SDK runs only on the majors of each provider SDK it is tested on: a new major raises before any call, until a release of the SDK is tested on it. The AI SDK's OpenAI, Anthropic and Google providers are not checked. The releases each supports are on its library page. The package is at 0.1.0 and has no release yet.

Next: [When reflexer fails](when-reflexer-fails.md) · [Known limits](limits.md)
