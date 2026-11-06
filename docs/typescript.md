# TypeScript

Node 20.3 or newer; install: [README](../README.md#install). The examples are ES modules (`import`, top-level `await`). Give reflexer's client your reflexer key (`rfx1_...`, from onboarding; a malformed one throws at once). Everything else stays yours: the provider key, options, `fetch`. To change reflexer's address (`https://api.reflexer.ai` by default), pass `reflexerBase` to a class, or `base` in the options of a `fetch` or `bedrock.wrap`. In a `.ts` file, write the key as `process.env.REFLEXER_KEY!`, and the price as `(answer.usage as any)?.cost`.

## OpenAI

<!-- example: served -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";
// const client = new OpenAI();
const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY });
const answer = await client.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] });
console.log(answer.choices[0].message.content);
```

`AzureOpenAI`, from the same module, works the same way, as do the Responses API and any OpenAI-compatible router set by `baseURL`.

## Anthropic

<!-- example: served -->
```js
import { Anthropic } from "@reflexer-ai/sdk/anthropic";
// const client = new Anthropic();
const client = new Anthropic({ reflexerKey: process.env.REFLEXER_KEY });
const answer = await client.messages.create({ model: "your-model", max_tokens: 1024,
  messages: [{ role: "user", content: "Hi" }] });
console.log(answer.content[0].text);
```

## Gemini

<!-- example: served -->
```js
import { GoogleGenAI } from "@reflexer-ai/sdk/gemini";
// const client = new GoogleGenAI({});
const client = new GoogleGenAI({ reflexerKey: process.env.REFLEXER_KEY });
const answer = await client.models.generateContent({ model: "your-model", contents: "Hi" });
console.log(answer.text);
```

## Keeping your library's own class

Give it reflexer's `fetch`.

<!-- example: served -->
```js
import OpenAI from "openai";
import * as reflexer from "@reflexer-ai/sdk";
// const client = new OpenAI();
const client = new OpenAI({ fetch: reflexer.openai.fetch(process.env.REFLEXER_KEY) });
const answer = await client.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] });
console.log(answer.choices[0].message.content);
```

- Azure, Anthropic: `reflexer.azure.fetch`, `reflexer.anthropic.fetch`.
- Gemini: `new GoogleGenAI({ httpOptions: { fetch: reflexer.gemini.fetch(key) } })`.

Each takes your own `fetch` as `{ fetch }`.

## The AI SDK

Node 22 or newer.

<!-- example: served -->
```js
import { createOpenAI } from "@ai-sdk/openai";
import { generateText } from "ai";
import * as reflexer from "@reflexer-ai/sdk";
// const openai = createOpenAI();
const openai = createOpenAI({ fetch: reflexer.openai.fetch(process.env.REFLEXER_KEY) });
console.log((await generateText({ model: openai("your-model"), prompt: "Hi" })).text);
```

`createAnthropic` with `reflexer.anthropic.fetch`, and `createGoogleGenerativeAI` with `reflexer.gemini.fetch`, the same way.

## LangChain.js

`@langchain/openai` needs Node 22 or newer.

<!-- example: served -->
```js
import { ChatOpenAI } from "@langchain/openai";
import * as reflexer from "@reflexer-ai/sdk";
// const chat = new ChatOpenAI({ model: "your-model" });
const chat = new ChatOpenAI({ model: "your-model", configuration: { fetch: reflexer.openai.fetch(process.env.REFLEXER_KEY) } });
console.log((await chat.invoke("Hi")).content);
```

`AzureChatOpenAI` the same way, with `reflexer.azure.fetch`. What LangChain.js cannot do here: [Known limits](../SECURITY.md#known-limits).

## Amazon Bedrock

The same code works with a Bedrock API key (`AWS_BEARER_TOKEN_BEDROCK`) and with your AWS credentials (SigV4). With your credentials, reflexer passes a call on to Bedrock only if you granted it a role in your AWS account at onboarding; otherwise a call it does not answer goes from your machine to Bedrock, as when reflexer is down. What each library cannot do: [Known limits](../SECURITY.md#known-limits).

### The AWS SDK

<!-- example: served bedrock -->
```js
import { BedrockRuntimeClient, ConverseCommand } from "@aws-sdk/client-bedrock-runtime";
import * as bedrock from "@reflexer-ai/sdk/bedrock";
// const client = new BedrockRuntimeClient({ region: "us-east-1" });
const client = bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1" }), process.env.REFLEXER_KEY);
const command = new ConverseCommand({ modelId: "your-model-id", messages: [{ role: "user", content: [{ text: "Hi" }] }] });
console.log((await client.send(command)).output.message.content[0].text);
```

### LangChain.js

<!-- example: served bedrock -->
```js
import { BedrockRuntimeClient } from "@aws-sdk/client-bedrock-runtime";
import { ChatBedrockConverse } from "@langchain/aws";
import * as bedrock from "@reflexer-ai/sdk/bedrock";
const client = bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1" }), process.env.REFLEXER_KEY);
// const chat = new ChatBedrockConverse({ model: "your-model-id", region: "us-east-1" });
const chat = new ChatBedrockConverse({ model: "your-model-id", region: "us-east-1", client });
console.log((await chat.invoke("Hi")).content);
```

### AnthropicBedrock

<!-- example: served bedrock -->
```js
import { AnthropicBedrock } from "@anthropic-ai/bedrock-sdk";
import * as bedrock from "@reflexer-ai/sdk/bedrock";
// const client = new AnthropicBedrock({ awsRegion: "us-east-1" });
const client = new AnthropicBedrock({ awsRegion: "us-east-1", fetch: bedrock.fetch(process.env.REFLEXER_KEY),
  middleware: [bedrock.anthropicMiddleware] }); // keep bedrock.anthropicMiddleware last
const answer = await client.messages.create({ model: "your-model-id", max_tokens: 1024,
  messages: [{ role: "user", content: "Hi" }] });
console.log(answer.content[0].text);
```

### The AI SDK

<!-- example: served bedrock -->
```js
import { createAmazonBedrock } from "@ai-sdk/amazon-bedrock";
import { generateText, wrapLanguageModel } from "ai";
import * as bedrockAi from "@reflexer-ai/sdk/bedrock-ai";
// const model = createAmazonBedrock({ region: "us-east-1" })("your-model-id");
const bedrock = createAmazonBedrock({ region: "us-east-1", fetch: bedrockAi.fetch(process.env.REFLEXER_KEY) });
const model = wrapLanguageModel({ model: bedrock("your-model-id"), middleware: bedrockAi.middleware });
console.log((await generateText({ model, prompt: "Hi" })).text);
```

## Skip reflexer for one call

<!-- example: straight -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";
const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY });
const answer = await client.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] },
  { headers: { "Reflexer-Pass-Through": "1" } });
console.log(answer.choices[0].message.content);
```

- Anthropic, AnthropicBedrock, the AI SDK's `generateText`: the same `headers`.
- LangChain.js: `invoke("Hi", { options: { headers: { "Reflexer-Pass-Through": "1" } } })`.
- Gemini: `config: { httpOptions: { headers: { "Reflexer-Pass-Through": "1" } } }`.
- The AI SDK on Bedrock: `providerOptions: { reflexer: { passThrough: true } }`.
- The AWS SDK: `{ reflexerPassThrough: true }` as `send`'s second argument, as below. LangChain.js on Bedrock: [Known limits](../SECURITY.md#known-limits).

<!-- example: straight bedrock -->
```js
import { BedrockRuntimeClient, ConverseCommand } from "@aws-sdk/client-bedrock-runtime";
import * as bedrock from "@reflexer-ai/sdk/bedrock";
const client = bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1" }), process.env.REFLEXER_KEY);
const converse = new ConverseCommand({ modelId: "your-model-id", messages: [{ role: "user", content: [{ text: "Hi" }] }] });
console.log((await client.send(converse, { reflexerPassThrough: true })).output.message.content[0].text);
```

## Send a share of the calls

<!-- example: straight -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";
const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY, sample: 0.01 }); // 1% to reflexer, the rest to OpenAI
const answer = await client.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] });
console.log(answer.choices[0].message.content);
```

`sample` goes in the options of every `fetch` and `bedrock.wrap` too.

## How long reflexer may take

<!-- example: served -->
```js
import OpenAI from "openai";
import * as reflexer from "@reflexer-ai/sdk";
const fetch = reflexer.openai.fetch(process.env.REFLEXER_KEY, { headersTimeout: 10_000 }); // ms, then the call goes to OpenAI
const client = new OpenAI({ fetch });
const answer = await client.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] });
console.log(answer.choices[0].message.content);
```

300 seconds by default. `bedrock.wrap` takes it too; reflexer's classes do not, so use a `fetch` for it.

## Who answered

<!-- example: served -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";
const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY });
const call = client.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] });
const { data: answer, response } = await call.withResponse();
console.log(answer.choices[0].message.content);
console.log(answer.model, answer.usage?.cost); // model ends in "-reflexer"; cost in USD
console.log(response.headers.get("reflexer-answered-by") ?? "your provider, directly"); // or "reflexer", or "provider" (passed on)
```

If reflexer is down or slow, the call goes to your provider and your code gets its answer, with a warning by `console.warn`. More: [What your code sees](behaviour.md).

## Versions

Tested on openai 7, @anthropic-ai/sdk 1, @google/genai 2 from 2.29.0, @aws-sdk/client-bedrock-runtime 3 from 3.1160.0 and @ai-sdk/amazon-bedrock 5 from 5.0.132. On another major, or below its floor, reflexer throws where the stock SDK would answer.
