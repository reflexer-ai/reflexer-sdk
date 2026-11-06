# TypeScript

Node 20.3 or newer. The package, `@reflexer-ai/sdk`, has no dependencies: it plugs into the provider SDK you already use, by its `fetch` option. To install it: [README.md, **Quick start**](../README.md#quick-start). The examples are plain JavaScript, which TypeScript takes as is, in ES modules (`"type": "module"`, or `.mjs`): they use `import` and top-level `await`.

## The key and the address

Each of reflexer's classes below takes `reflexerKey`, the key you got at onboarding (`rfx1_...`); the `fetch` makers ([below](#a-client-you-do-not-make-yourself)) and Bedrock's `bedrock.wrap` take it as an argument. A key not of that form throws when the client is made, before any call. The examples read it from `REFLEXER_KEY`.

`reflexerBase` is reflexer's address (`base` in the options of the `fetch` makers and `bedrock.wrap`), `https://api.reflexer.ai` unless you were given another; it must be `https`.

Everything else stays as you had it: your provider's key and options, your own `fetch`. The examples leave the provider's key to the provider SDK, which reads it from its usual environment variable.

## OpenAI

<!-- example: served -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";

// const client = new OpenAI();
const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY });

const answer = await client.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] });
console.log(answer.choices[0].message.content);
```

`AzureOpenAI`, from the same module, the same way. The Responses API goes through too. A router or model host that speaks OpenAI's format works by its `baseURL`, as before.

## Anthropic

<!-- example: served -->
```js
import { Anthropic } from "@reflexer-ai/sdk/anthropic";

// const client = new Anthropic();
const client = new Anthropic({ reflexerKey: process.env.REFLEXER_KEY });

const answer = await client.messages.create({ model: "your-model", max_tokens: 1024, messages: [{ role: "user", content: "Hi" }] });
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

## A client you do not make yourself

When other code makes the provider's client, keep its class and give it reflexer's `fetch`:

<!-- example: served -->
```js
import OpenAI from "openai";
import { GoogleGenAI } from "@google/genai";
import * as reflexer from "@reflexer-ai/sdk";

const key = process.env.REFLEXER_KEY;
const client = new OpenAI({ fetch: reflexer.openai.fetch(key) });
console.log((await client.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] })).choices[0].message.content);

const gemini = new GoogleGenAI({ httpOptions: { fetch: reflexer.gemini.fetch(key) } });
console.log((await gemini.models.generateContent({ model: "your-model", contents: "Hi" })).text);
```

The makers: `reflexer.openai.fetch`, `reflexer.azure.fetch`, `reflexer.anthropic.fetch`, `reflexer.gemini.fetch`. A `fetch` of your own carries both reflexer's leg and the provider's: give it as before on reflexer's classes, or as `reflexer.openai.fetch(key, { fetch: yourFetch })`.

## The AI SDK

Node 22 or newer, its own floor. Its providers take a `fetch`: give them reflexer's.

<!-- example: served -->
```js
import { createAnthropic } from "@ai-sdk/anthropic";
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { createOpenAI } from "@ai-sdk/openai";
import { generateText } from "ai";
import * as reflexer from "@reflexer-ai/sdk";

const key = process.env.REFLEXER_KEY;
const openai = createOpenAI({ fetch: reflexer.openai.fetch(key) });
const anthropic = createAnthropic({ fetch: reflexer.anthropic.fetch(key) });
const google = createGoogleGenerativeAI({ fetch: reflexer.gemini.fetch(key) });

for (const model of [openai("your-model"), anthropic("your-model"), google("your-model")]) {
  console.log((await generateText({ model, prompt: "Hi" })).text);
}
```

On Gemini the AI SDK names the model you asked for, not the answer's; the `reflexer-answered-by` header, in `result.response.headers`, says who answered on every provider.

## LangChain.js

`@langchain/openai` needs Node 22 or newer, its own floor.

<!-- example: served -->
```js
import { AzureChatOpenAI, ChatOpenAI } from "@langchain/openai";
import * as reflexer from "@reflexer-ai/sdk";

const key = process.env.REFLEXER_KEY;

// const chat = new ChatOpenAI({ model: "your-model" });
const chat = new ChatOpenAI({ model: "your-model", configuration: { fetch: reflexer.openai.fetch(key) } });
console.log((await chat.invoke("Hi")).content);

const azure = new AzureChatOpenAI({ azureOpenAIApiDeploymentName: "your-deployment", configuration: { fetch: reflexer.azure.fetch(key) } });
console.log((await azure.invoke("Hi")).content);
```

`@langchain/anthropic`'s `ChatAnthropic` takes a `fetch`, but bundles a major of `@anthropic-ai/sdk` this SDK is not tested on: given reflexer's, its calls throw. `@langchain/google-genai` takes no `fetch`. So reflexer cannot reach either's calls.

## Amazon Bedrock

Both ways of calling Bedrock go through reflexer, with the same code:

- With a Bedrock API key: the key goes to reflexer with the call, as any provider's key does.
- Signed with your AWS credentials (SigV4): reflexer gets the signed call, but never passes your signature on. When it does not answer, your library sends the call to Bedrock: AWS JS, LangChain.js and AnthropicBedrock sign it again; the AI SDK sends it as first signed, and stops waiting for reflexer while the signature still holds. Your AWS secret stays with your library's signer; the call reflexer gets carries your access key's id, and with temporary credentials the session token.

Each example below runs both ways: with the key in `AWS_BEARER_TOKEN_BEDROCK`, and signed.

AWS JS, and LangChain.js on it:

<!-- example: served bedrock -->
```js
import { BedrockRuntimeClient, ConverseCommand } from "@aws-sdk/client-bedrock-runtime";
import { ChatBedrockConverse } from "@langchain/aws";
import * as bedrock from "@reflexer-ai/sdk/bedrock";

// const client = new BedrockRuntimeClient({ region: "us-east-1" });
const client = bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1" }), process.env.REFLEXER_KEY);

const answer = await client.send(new ConverseCommand({ modelId: "your-model-id", messages: [{ role: "user", content: [{ text: "Hi" }] }] }));
console.log(answer.output.message.content[0].text);

const chat = new ChatBedrockConverse({ model: "your-model-id", region: "us-east-1", client });
console.log((await chat.invoke("Hi")).content);
```

`bedrock.wrap` works with AWS JS's default handler on Node; it refuses the fetch handler that browser and edge builds use. A client that sets its own `requestHandler` gives it to `bedrock.requestHandler(key, { handler, signer })`, with the client's `signer` for a signed call.

AnthropicBedrock, with reflexer's `fetch` and its middleware, last of yours:

<!-- example: served bedrock -->
```js
import { AnthropicBedrock } from "@anthropic-ai/bedrock-sdk";
import * as bedrock from "@reflexer-ai/sdk/bedrock";

// const client = new AnthropicBedrock({ awsRegion: "us-east-1" });
const client = new AnthropicBedrock({ awsRegion: "us-east-1", fetch: bedrock.fetch(process.env.REFLEXER_KEY), middleware: [bedrock.anthropicMiddleware] });

const answer = await client.messages.create({ model: "your-model-id", max_tokens: 1024, messages: [{ role: "user", content: "Hi" }] });
console.log(answer.content[0].text);
```

The AI SDK's Bedrock provider (Node 22 or newer), with reflexer's `fetch` and its middleware:

<!-- example: served bedrock -->
```js
import { createAmazonBedrock } from "@ai-sdk/amazon-bedrock";
import { generateText, wrapLanguageModel } from "ai";
import * as bedrockAi from "@reflexer-ai/sdk/bedrock-ai";

// const model = createAmazonBedrock({ region: "us-east-1" })("your-model-id");
const model = wrapLanguageModel({
  model: createAmazonBedrock({ region: "us-east-1", fetch: bedrockAi.fetch(process.env.REFLEXER_KEY) })("your-model-id"),
  middleware: bedrockAi.middleware,
});
console.log((await generateText({ model, prompt: "Hi" })).text);
```

What each Bedrock library cannot do: [SECURITY.md, **Known limits**](../SECURITY.md#known-limits).

## Skip reflexer for one call

The `Reflexer-Pass-Through` header sends one call straight to the provider.

- OpenAI, Azure, Anthropic, AnthropicBedrock: `{ headers: { "Reflexer-Pass-Through": "1" } }` as the call's request options.
- Gemini: `config: { httpOptions: { headers: { "Reflexer-Pass-Through": "1" } } }` in the call.
- LangChain.js's `ChatOpenAI`: `{ options: { headers: { "Reflexer-Pass-Through": "1" } } }` as `invoke`'s second argument.
- The AI SDK: `headers: { "Reflexer-Pass-Through": "1" }` in the call; on Bedrock, `providerOptions: { reflexer: { passThrough: true } }`.
- AWS JS: `client.send(command, { reflexerPassThrough: true })`. The option is not in AWS JS's types: TypeScript needs a cast. Where you do not make the `send` call yourself, as in LangChain.js, set the header by a middleware of yours on the client.

<!-- example: straight bedrock -->
```js
import { BedrockRuntimeClient, ConverseCommand } from "@aws-sdk/client-bedrock-runtime";
import { OpenAI } from "@reflexer-ai/sdk/openai";
import { GoogleGenAI } from "@reflexer-ai/sdk/gemini";
import * as bedrock from "@reflexer-ai/sdk/bedrock";
import * as reflexer from "@reflexer-ai/sdk";
import { ChatOpenAI } from "@langchain/openai";

const reflexerKey = process.env.REFLEXER_KEY;
const headers = { "Reflexer-Pass-Through": "1" };

const openai = new OpenAI({ reflexerKey });
const answer = await openai.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] }, { headers });
console.log(answer.choices[0].message.content);

const gemini = new GoogleGenAI({ reflexerKey });
console.log((await gemini.models.generateContent({ model: "your-model", contents: "Hi", config: { httpOptions: { headers } } })).text);

const chat = new ChatOpenAI({ model: "your-model", configuration: { fetch: reflexer.openai.fetch(reflexerKey) } });
console.log((await chat.invoke("Hi", { options: { headers } })).content);

const client = bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1" }), reflexerKey);
const converse = new ConverseCommand({ modelId: "your-model-id", messages: [{ role: "user", content: [{ text: "Hi" }] }] });
console.log((await client.send(converse, { reflexerPassThrough: true })).output.message.content[0].text);
```

## Send only a share of the calls

`sample` is the share of calls that go to reflexer; the rest go straight to the provider. Reflexer's classes take it beside `reflexerKey`; the `fetch` makers and `bedrock.wrap`, in their options.

<!-- example: straight -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";

const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY, sample: 0.01 }); // 1% of the calls

const answer = await client.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] });
console.log(answer.choices[0].message.content);
```

## How long reflexer may take

`headersTimeout`, in the options of the `fetch` makers and `bedrock.wrap`, is how long reflexer's leg waits for its answer to start before the call goes straight; by default 300 seconds. What else happens when reflexer is slow: [behaviour.md](behaviour.md).

<!-- example: served -->
```js
import OpenAI from "openai";
import * as reflexer from "@reflexer-ai/sdk";

const client = new OpenAI({ fetch: reflexer.openai.fetch(process.env.REFLEXER_KEY, { headersTimeout: 10_000 }) }); // 10 s

const answer = await client.chat.completions.create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] });
console.log(answer.choices[0].message.content);
```

## Who answered

<!-- example: served -->
```js
import { OpenAI } from "@reflexer-ai/sdk/openai";

const client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY });

const { data: answer, response } = await client.chat.completions
  .create({ model: "your-model", messages: [{ role: "user", content: "Hi" }] })
  .withResponse();
console.log(answer.choices[0].message.content);
console.log(answer.model);                                  // ends in "-reflexer" when reflexer answered
console.log(answer.usage.cost);                             // reflexer's price, in USD
console.log(response.headers.get("reflexer-answered-by"));  // "reflexer", or "provider" when reflexer passed the call on
```

What each field means, and what you see when reflexer is down or slow: [behaviour.md](behaviour.md).

## Versions

Tested on openai 7, @anthropic-ai/sdk 1, @google/genai 2 from 2.29.0, @aws-sdk/client-bedrock-runtime 3 from 3.1160.0 and @ai-sdk/amazon-bedrock 5 from 5.0.132. On any other release reflexer throws where the stock SDK would answer: on import for `@reflexer-ai/sdk/openai` and `@reflexer-ai/sdk/anthropic`, on the call otherwise. So a new release never sends your calls astray. One exception: @google/genai before 2.23.0 takes no `fetch`, so its calls go to Google as stock does, never through reflexer.
