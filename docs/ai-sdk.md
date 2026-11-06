# reflexer with the AI SDK

Reflexer in front of the AI SDK's OpenAI, Anthropic and Google providers. On Bedrock: [Bedrock](bedrock.md#the-ai-sdk-on-bedrock-node-22).

**Before you begin:** `ai` 7 with its providers at 4, on Node 22+, and `REFLEXER_KEY` set to the key you got at onboarding. In a `.ts` file, write the key as `process.env.REFLEXER_KEY!`: the examples are plain JavaScript.

## 1. Install

Not on PyPI or npm yet: install from a clone of this repository ([README](../README.md#install)).

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

The reply looks the same either way. The `Reflexer-Answered-By` header says who answered: `reflexer`, or `provider` when reflexer forwarded the call to your provider; it is absent when the call went to your provider directly.

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

- **Reflexer down, slow or busy:** the call goes to your provider, and your code gets your provider's answer. The SDK logs a warning by `console.warn`. After a failure, the next calls go to your provider too, for about a minute at most, then reflexer is tried again.
- **Timeouts, TypeScript:** if reflexer's answer has not started after `headersTimeout` (300 seconds by default), the call goes to your provider. If your client's own timeout fires first, that try fails as a timeout, and your SDK's retry goes to your provider. Either way, if reflexer had already forwarded the call, your provider may run it, and bill it, twice.
- **Key refused:** if reflexer refuses your reflexer key, your SDK raises its authentication error; the call does not go to your provider. A key revoked less than a day ago still sends calls to your provider, with a warning.
- **Which calls:** only the calls that return a model's message go to reflexer. Other calls, and calls to `http`, `localhost` or a private IP, go where they were sent, as before.
- **What leaves your machine:** the call, with your provider key, goes to reflexer, which uses the key to forward the call to your provider when it does not answer. The reflexer key goes to reflexer only.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. Remove the line and your code is as it was.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).
## Options

- `reflexer.openai.fetch(key, { sample: 0.01 })`: send that share of the calls to reflexer, the rest to your provider.
- `generateText({ ..., headers: { "Reflexer-Pass-Through": "1" } })`: that call goes to your provider.
- `{ headersTimeout: 10_000 }` in the `fetch`'s options: how long reflexer may take to start its answer, in ms.

All of them: [Advanced](advanced.md).

## Supported versions

Tested on `ai` 7 with `@ai-sdk/openai`, `@ai-sdk/anthropic` and `@ai-sdk/google` 4, on Node 22+.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
