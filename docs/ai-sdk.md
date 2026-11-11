# reflexer with the AI SDK

Send the calls of the AI SDK's OpenAI, Anthropic and Google providers through reflexer. For Bedrock, see [Bedrock](bedrock.md#the-ai-sdk-on-bedrock-node-22).

**Before you begin:** you need `ai` 7 with its providers at version 4, on Node 22+, and the environment variable `REFLEXER_KEY` set to the reflexer key you got at onboarding. The examples are plain JavaScript: in a `.ts` file, write the key as `process.env.REFLEXER_KEY!`.

## 1. Install

The SDK is not on PyPI or npm yet. Install it from a clone of this repository ([README](../README.md#install)).

```sh
npm install /path/to/reflexer-sdk/typescript/reflexer-ai-sdk-VERSION.tgz
```
## 2. Add the line

Give the provider reflexer's `fetch`.

<!-- example: served js -->
```diff
  import { createOpenAI } from "@ai-sdk/openai";
  import { generateText } from "ai";
+ import * as reflexer from "@reflexer-ai/sdk";

- const openai = createOpenAI();
+ const openai = createOpenAI({ fetch: reflexer.openai.fetch(process.env.REFLEXER_KEY) });
  console.log((await generateText({ model: openai("frontier-x"), prompt: "Hi" })).text);
```

```text
Hello! How can I help you today?
```

Anthropic: `createAnthropic({ fetch: reflexer.anthropic.fetch(key) })`. Google: `createGoogleGenerativeAI({ fetch: reflexer.gemini.fetch(key) })`.

## 3. Verify

The reply looks the same whether reflexer or your provider answered. The `Reflexer-Answered-By` header names who answered: `reflexer`, or `provider` when reflexer forwarded the call to your provider. The reply has no such header when the SDK sent the call directly to your provider.

<!-- example: served -->
```js
import { createOpenAI } from "@ai-sdk/openai";
import { generateText } from "ai";
import * as reflexer from "@reflexer-ai/sdk";

const openai = createOpenAI({ fetch: reflexer.openai.fetch(process.env.REFLEXER_KEY) });
const result = await generateText({ model: openai("frontier-x"), prompt: "Hi" });
console.log(result.response.headers["reflexer-answered-by"]);
```

```text
reflexer
```

## Behavior

- **Reflexer down, slow or busy:** the SDK sends the call directly to your provider, and your code gets your provider's answer. The SDK logs a warning with `console.warn`. After a failure, the SDK sends the next calls directly to your provider too, for about a minute at most. Then the SDK tries reflexer again.
- **Timeouts, TypeScript:** if reflexer's answer has not started after `headersTimeout` (300 seconds by default), the SDK sends the call directly to your provider. If your client's own timeout expires first, that attempt fails with a timeout error. If your provider SDK then retries the call, the SDK sends the retry directly to your provider. In every case, if reflexer had already forwarded the call, your provider may run the call twice and bill it twice.
- **Key refused:** if reflexer refuses your reflexer key, your provider SDK raises its authentication error, and the SDK does not send the call to your provider. If your reflexer key was revoked less than one day ago, the SDK still sends your calls directly to your provider, and logs a warning.
- **Which calls:** the SDK sends to reflexer only the calls that return a model's message. The SDK sends all other calls, and all calls to `http`, `localhost` or a private IP, to the address your code gave them, as before.
- **What leaves your machine:** the SDK sends the call to reflexer, with your provider key. When reflexer does not answer the call itself, reflexer uses this key to forward the call to your provider. Only reflexer receives your reflexer key.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. If you remove the line, your code works as before.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).

## Options

- `reflexer.openai.fetch(key, { sample: 0.01 })`: the SDK sends that share of the calls to reflexer, and the other calls directly to your provider.
- `generateText({ ..., headers: { "Reflexer-Skip": "true" } })`: the SDK sends that call directly to your provider.
- `{ headersTimeout: 10_000 }` in the `fetch`'s options: how long reflexer may take to start its answer, in ms.

All options: [Advanced](advanced.md).

## Supported versions

Tested on `ai` 7 with `@ai-sdk/openai`, `@ai-sdk/anthropic` and `@ai-sdk/google` 4, on Node 22+.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
