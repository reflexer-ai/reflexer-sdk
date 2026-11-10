# Reference

Use this page to look up a name. Every public name of the SDK takes the same few arguments. This page lists these arguments first, then the names, in groups by use. Each library page shows how to use its names.

## The arguments

**`reflexer_key`** (Python) · **`reflexerKey`** (TypeScript): `str`, required. Your reflexer key, `rfx1_...`, which you receive at onboarding. To get one, write to hello@reflexer.ai. Read the key from the environment. Never commit it. If the key does not have this form, the SDK raises `ValueError` (TypeScript: `Error`) when you create the client. The functions take the key as their first argument; `through` takes it as its second argument.

**`reflexer_base`** · **`reflexerBase`** · **`base`**: `str`, optional, default `"https://api.reflexer.ai"`. The address of reflexer. It must use `https`. Functions name this argument `base` (Python's `http_client`, `client_args`, `through`, `litellm.client`; TypeScript's `fetch` functions and `bedrock.wrap`).

**`sample`**: `float` from 0 to 1, optional, default 1. The share of calls that the SDK sends to reflexer. The SDK sends the other calls directly to your provider. [Advanced](advanced.md#send-a-share-of-the-calls).

**`reflexer_namespace`** · **`reflexerNamespace`** · **`namespace`**: `str`, optional. A name for a group of your calls. reflexer keeps each group separate from your other calls. For example, use one namespace per product or per environment. If you give no namespace, your calls are in your default namespace. Allowed characters: ASCII letters, digits and signs, and single spaces between them. For any other value, the SDK raises `ValueError` (TypeScript: `Error`) when you create the client. Functions name this argument `namespace`, as they do for `base`. [Advanced](advanced.md#keep-calls-apart-a-namespace).

**`own`** (Python functions) · **`fetch`** (TypeScript options): optional; the default is your provider SDK's own. Your HTTP client or `fetch` (for `reflexer.gemini.client_args`: your `client_args` dict). The SDK also sends its calls to reflexer through it. [Advanced](advanced.md#your-own-http-client).

**`Reflexer-Pass-Through`** (a header) · **`ReflexerPassThrough`** (boto3's argument) · **`reflexerPassThrough`** (the AWS SDK's option): set it on one call, and the SDK sends that call directly to your provider. [Advanced](advanced.md#skip-reflexer-for-one-call).

**`headersTimeout`** (TypeScript `fetch` functions and `bedrock.wrap`): milliseconds, optional, default 300000. The time the SDK waits for reflexer's answer to start. After this time, the SDK sends the call directly to your provider. [Advanced](advanced.md#how-long-reflexer-may-take).

## Python

### Clients

Each class takes the arguments of the provider SDK's class (the stock class), and also `reflexer_key`, `reflexer_base`, `sample` and `reflexer_namespace`. Everything else is the same as in the stock class.

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
| `reflexer.openai.http_client`, `async_http_client`, `azure_http_client`, `azure_async_http_client`; `reflexer.anthropic.http_client`, `async_http_client` | An HTTP client for the stock class's `http_client=` | `key, own=None, base=…, sample=1.0, namespace=None` | [other libraries](other-libraries.md) |
| `reflexer.gemini.http_client`, `async_http_client` | An HTTP client for google-genai's `httpx_client` and `httpx_async_client` | `key, own=None, base=…, sample=1.0, namespace=None` | [other libraries](other-libraries.md) |
| `reflexer.gemini.client_args` | A dict for both `client_args` and `async_client_args` | `key, own=None, base=…, sample=1.0, namespace=None` | [other libraries](other-libraries.md) |
| `reflexer.boto3.client` | A boto3 client | boto3's arguments, and `reflexer_key`, `reflexer_base`, `sample`, `reflexer_namespace` | [bedrock](bedrock.md#boto3) |
| `reflexer.boto3.through`, `reflexer.aiobotocore.through` | The client you give, which now sends its calls through reflexer | `client, reflexer_key, base=…, sample=1.0, namespace=None` | [bedrock](bedrock.md#aiobotocore) |
| `reflexer.litellm.client`, `async_client` | An HTTP handler for LiteLLM's `client=` | `reflexer_key, base=…, sample=1.0, namespace=None` | [bedrock](bedrock.md#litellm) |

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

Each class takes the options of the provider SDK's class, and also `reflexerKey`, `reflexerBase`, `sample` and `reflexerNamespace`.

| Name | From | Stock class | Page |
|---|---|---|---|
| `OpenAI`, `AzureOpenAI` | `@reflexer-ai/sdk/openai` | `openai`'s | [openai](openai.md) |
| `Anthropic` | `@reflexer-ai/sdk/anthropic` | `@anthropic-ai/sdk`'s | [anthropic](anthropic.md) |
| `GoogleGenAI` | `@reflexer-ai/sdk/gemini` | `@google/genai`'s | [gemini](gemini.md) |

### Functions

| Name | From | Returns | Takes |
|---|---|---|---|
| `openai.fetch`, `azure.fetch`, `anthropic.fetch`, `gemini.fetch` | `@reflexer-ai/sdk` | A `fetch` for the provider SDK's `fetch` option | `key, { base, sample, namespace, fetch, headersTimeout }` |
| `wrap` | `@reflexer-ai/sdk/bedrock` | The AWS SDK client you give, which now sends its calls through reflexer | `client, key, { base, sample, namespace, headersTimeout }` |
| `fetch` | `@reflexer-ai/sdk/bedrock` | A `fetch` for AnthropicBedrock | `key, { base, sample, namespace, fetch, headersTimeout }` |
| `anthropicMiddleware` | `@reflexer-ai/sdk/bedrock` | AnthropicBedrock's `middleware`; put it after all your own middleware | (a value) |
| `requestHandler` | `@reflexer-ai/sdk/bedrock` | An AWS SDK request handler that wraps your own handler. Use it for a client that sets its own `requestHandler`, because such a client cannot use `wrap`. Also give it the client's `signer`: without the signer, the SDK sends signed calls directly to Bedrock | `key, { handler, signer, base, sample, namespace, headersTimeout }` |
| `fetch` | `@reflexer-ai/sdk/bedrock-ai` | A `fetch` for the AI SDK's Bedrock provider | `key, { base, sample, namespace, fetch, headersTimeout }` |
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

- A malformed key: `ValueError` (TypeScript `Error`), when you create the client. [When reflexer fails](when-reflexer-fails.md#your-reflexer-key-is-malformed).
- An untested release of your provider SDK: `ImportError` at import (TypeScript: `Error`, at import or at the first call). [When reflexer fails](when-reflexer-fails.md#your-provider-sdk-is-a-release-reflexer-is-not-tested-on).
- A reflexer address that is not `https`: `ValueError` (TypeScript `Error`), when you create the client.
- A `sample` that is not a number from 0 to 1: `ValueError` (TypeScript `Error`), when you create the client.
- `through` on a client that already sends its calls through reflexer: `ValueError`. aiobotocore with another HTTP session class, or with an aiohttp release that the SDK cannot work with: `TypeError`.
- TypeScript `GoogleGenAI`, when your headers replace both `User-Agent` and `x-goog-api-client`, so that its calls name no `@google/genai` version: `Error`, at the call.
- A [dry run](advanced.md#a-dry-run-give-reflexer-your-providers-answer) that reflexer cannot accept: `reflexer.ReplayNotTaken` (TypeScript: `ReplayNotTaken`, from `@reflexer-ai/sdk`), or the connection error of your provider SDK that it causes.
- TypeScript, Bedrock: `bedrock.wrap` or `requestHandler` on a handler that is already wrapped, or on the AWS SDK's fetch handler: `Error`, when you wrap it.
- Every other error that your code receives is your provider SDK's own error, as before.

## What reflexer adds to a response

- In a reply from reflexer, `model` ends in `-reflexer`, and `usage.cost` holds the price in USD. A stream's usage holds the price too. Gemini replies and Bedrock Converse replies do not have these fields. In a Gemini reply, `model_version` (TypeScript `modelVersion`) ends in `-reflexer`. A Converse reply names no model and has no cost: read the headers below, `Reflexer-Answered-By` and `Reflexer-Cost`.
- Headers that reflexer adds to every response it sends: `Reflexer-Request-Id`, the call's id; `Reflexer-Cost`, the price in nano USD, which is 0 when reflexer did not answer. `Reflexer-Answered-By`: `reflexer` when reflexer answered; `provider` when reflexer forwards what your provider sent. `Reflexer-Answered-By` is absent on errors and refusals that reflexer itself returns, including a 502 when reflexer cannot reach your provider. It is also absent on a dry run's reply that is your own answer. A call that the SDK sent directly to your provider has none of these headers.
- `Reflexer-Reason`: why reflexer answered or did not answer, such as `served`, `not_seen_repeating` or `low_confidence`. It is for debugging. It is off by default; reflexer enables it for some accounts.

## Versions

For each provider SDK, the SDK runs only on the major versions that it is tested on. On a new major version, the SDK raises an error before any call, until a release of the SDK is tested on that major version. The SDK does not check the versions of the AI SDK's OpenAI, Anthropic and Google providers. Each library page lists the releases that the SDK supports. The package is at 0.1.0 and has no release yet.

Next: [When reflexer fails](when-reflexer-fails.md) · [Known limits](limits.md)
