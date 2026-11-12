# reflexer with Amazon Bedrock

Send your Bedrock calls through reflexer. Python: from boto3, aiobotocore, LiteLLM, Anthropic's Bedrock clients, and the libraries built on them. TypeScript: from the AWS SDK for JavaScript, AnthropicBedrock and the AI SDK.

**Before you begin:** you need your Bedrock library, and the environment variable `REFLEXER_KEY` set to the reflexer key you got at onboarding. Keep your Bedrock credentials as they are: a Bedrock API key (`AWS_BEARER_TOKEN_BEDROCK`), or your AWS credentials, which your library uses to sign each call (SigV4). The same code works with both kinds. The examples are plain JavaScript: in a `.ts` file, write the key as `process.env.REFLEXER_KEY!`.

## 1. Install

The SDK is not on PyPI or npm yet. Install it from a clone of this repository ([README](../README.md#install)).

```sh
pip install --build-constraint reflexer-sdk/build-constraints.txt ./reflexer-sdk  # pip 26.1 or later
```

```sh
npm install /path/to/reflexer-sdk/typescript/reflexer-ai-sdk-VERSION.tgz
```
## 2. Add the line

Python: [boto3](#boto3) · [aiobotocore](#aiobotocore) · [langchain-aws, Pydantic AI, Strands](#langchain-aws-pydantic-ai-strands) · [Anthropic's Bedrock clients](#anthropics-bedrock-clients) · [LiteLLM](#litellm). TypeScript: [the AWS SDK](#the-aws-sdk-for-javascript-and-langchainjs-on-it) · [AnthropicBedrock](#anthropicbedrock-typescript) · [the AI SDK](#the-ai-sdk-on-bedrock-node-22).

### boto3

<!-- example: served python bedrock -->
```diff
  import os
  import boto3
+ import reflexer.boto3

- client = boto3.client("bedrock-runtime", region_name="us-east-1")
+ client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
  reply = client.converse(modelId="frontier-x", messages=[{"role": "user", "content": [{"text": "Hi"}]}])
  print(reply["output"]["message"]["content"][0]["text"])
```

```text
Hello! How can I help you today?
```

If your code creates the client elsewhere, send its calls through reflexer with `reflexer.boto3.through(client, os.environ["REFLEXER_KEY"])`.

### aiobotocore

Inside the client's `async with` block, give the client to reflexer.

<!-- example: served python bedrock -->
```diff
  import asyncio, os
  import aiobotocore.session
+ import reflexer.aiobotocore

  async def main():
      async with aiobotocore.session.get_session().create_client("bedrock-runtime", region_name="us-east-1") as client:
+         reflexer.aiobotocore.through(client, os.environ["REFLEXER_KEY"])
          reply = await client.converse(modelId="frontier-x", messages=[{"role": "user", "content": [{"text": "Hi"}]}])
          print(reply["output"]["message"]["content"][0]["text"])

  asyncio.run(main())
```

```text
Hello! How can I help you today?
```

### langchain-aws, Pydantic AI, Strands

These libraries call Bedrock through a boto3 client. Give them reflexer's boto3 client.

<!-- example: served python bedrock -->
```diff
  import os
  from langchain_aws import ChatBedrockConverse
+ import reflexer.boto3

- chat = ChatBedrockConverse(model="frontier-x", region_name="us-east-1")
+ client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
+ chat = ChatBedrockConverse(model="frontier-x", client=client)
  print(chat.invoke("Hi").content)
```

```text
Hello! How can I help you today?
```

<!-- example: served python bedrock -->
```diff
  import os
  from pydantic_ai import Agent
  from pydantic_ai.models.bedrock import BedrockConverseModel
  from pydantic_ai.providers.bedrock import BedrockProvider
+ import reflexer.boto3

- provider = BedrockProvider(region_name="us-east-1")
+ client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
+ provider = BedrockProvider(bedrock_client=client)
  print(Agent(BedrockConverseModel("frontier-x", provider=provider)).run_sync("Hi").output)
```

```text
Hello! How can I help you today?
```

<!-- example: served python bedrock -->
```diff
  import os
  from strands import Agent
  from strands.models import BedrockModel
+ import reflexer.boto3

  model = BedrockModel(model_id="frontier-x", region_name="us-east-1")
+ reflexer.boto3.through(model.client, os.environ["REFLEXER_KEY"])
  print(Agent(model=model, callback_handler=None)("Hi"))
```

```text
Hello! How can I help you today?
```

### Anthropic's Bedrock clients

<!-- example: served python bedrock -->
```diff
  import os
- from anthropic import AnthropicBedrock
+ from reflexer.anthropic_bedrock import AnthropicBedrock

- client = AnthropicBedrock(aws_region="us-east-1")
+ client = AnthropicBedrock(aws_region="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
  reply = client.messages.create(model="frontier-x", max_tokens=1024, messages=[{"role": "user", "content": "Hi"}])
  print(reply.content[0].text)
```

```text
Hello! How can I help you today?
```

Change `AsyncAnthropicBedrock`, `AnthropicBedrockMantle` and `AsyncAnthropicBedrockMantle` the same way.

### LiteLLM

Run one line, once, before your first call. From then on, the SDK sends LiteLLM's Bedrock calls through reflexer, and its calls to the other providers that reflexer takes ([LiteLLM](litellm.md)).

<!-- example: served python bedrock -->
```diff
  import os
  import litellm
+ import reflexer.litellm

+ reflexer.litellm.through(os.environ["REFLEXER_KEY"])
  reply = litellm.completion(model="bedrock/converse/frontier-x", messages=[{"role": "user", "content": "Hi"}])
  print(reply.choices[0].message.content)
```

```text
Hello! How can I help you today?
```

The same line covers `acompletion` and `stream=True`.

### The AWS SDK for JavaScript, and LangChain.js on it

<!-- example: served js bedrock -->
```diff
  import { BedrockRuntimeClient, ConverseCommand } from "@aws-sdk/client-bedrock-runtime";
+ import * as bedrock from "@reflexer-ai/sdk/bedrock";

- const client = new BedrockRuntimeClient({ region: "us-east-1" });
+ const client = bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1" }), process.env.REFLEXER_KEY);
  const reply = await client.send(new ConverseCommand({ modelId: "frontier-x", messages: [{ role: "user", content: [{ text: "Hi" }] }] }));
  console.log(reply.output.message.content[0].text);
```

```text
Hello! How can I help you today?
```

LangChain.js's `ChatBedrockConverse` takes the wrapped client: `new ChatBedrockConverse({ model: "frontier-x", region: "us-east-1", client })`.

### AnthropicBedrock (TypeScript)

Add reflexer's `fetch`. Add reflexer's middleware after all of your own middleware.

<!-- example: served js bedrock -->
```diff
  import { AnthropicBedrock } from "@anthropic-ai/bedrock-sdk";
+ import * as bedrock from "@reflexer-ai/sdk/bedrock";

- const client = new AnthropicBedrock({ awsRegion: "us-east-1" });
+ const client = new AnthropicBedrock({ awsRegion: "us-east-1", fetch: bedrock.fetch(process.env.REFLEXER_KEY), middleware: [bedrock.anthropicMiddleware] });
  const reply = await client.messages.create({ model: "frontier-x", max_tokens: 1024, messages: [{ role: "user", content: "Hi" }] });
  console.log(reply.content[0].text);
```

```text
Hello! How can I help you today?
```

### The AI SDK on Bedrock (Node 22+)

Add reflexer's `fetch` to the provider, and its middleware to the model.

<!-- example: served js bedrock -->
```diff
  import { createAmazonBedrock } from "@ai-sdk/amazon-bedrock";
- import { generateText } from "ai";
+ import { generateText, wrapLanguageModel } from "ai";
+ import * as bedrockAi from "@reflexer-ai/sdk/bedrock-ai";

- const bedrock = createAmazonBedrock({ region: "us-east-1" });
+ const bedrock = createAmazonBedrock({ region: "us-east-1", fetch: bedrockAi.fetch(process.env.REFLEXER_KEY) });
- const model = bedrock("frontier-x");
+ const model = wrapLanguageModel({ model: bedrock("frontier-x"), middleware: bedrockAi.middleware });
  console.log((await generateText({ model, prompt: "Hi" })).text);
```

```text
Hello! How can I help you today?
```

For Bedrock's OpenAI and Anthropic endpoints, make the change on the [OpenAI](openai.md) or [Anthropic](anthropic.md) page. Use Bedrock's `base_url`, and your Bedrock API key as `api_key`.

## 3. Verify

The reply looks the same whether reflexer or Bedrock answered. The `Reflexer-Answered-By` header names who answered: `reflexer`, or `provider` when reflexer forwarded the call to Bedrock. The reply has no such header when the SDK sent the call directly to Bedrock.

With boto3, and so also with langchain-aws, Pydantic AI and Strands, which use a boto3 client:

<!-- example: served bedrock -->
```python
import os
import reflexer.boto3

client = reflexer.boto3.client("bedrock-runtime", region_name="us-east-1", reflexer_key=os.environ["REFLEXER_KEY"])
reply = client.converse(modelId="frontier-x", messages=[{"role": "user", "content": [{"text": "Hi"}]}])
print(reply["ResponseMetadata"]["HTTPHeaders"]["reflexer-answered-by"])
```

```text
reflexer
```

With AnthropicBedrock:

<!-- example: served bedrock -->
```js
import { AnthropicBedrock } from "@anthropic-ai/bedrock-sdk";
import * as bedrock from "@reflexer-ai/sdk/bedrock";

const client = new AnthropicBedrock({ awsRegion: "us-east-1", fetch: bedrock.fetch(process.env.REFLEXER_KEY), middleware: [bedrock.anthropicMiddleware] });
const { response } = await client.messages.create({ model: "frontier-x", max_tokens: 1024, messages: [{ role: "user", content: "Hi" }] }).withResponse();
console.log(response.headers.get("reflexer-answered-by"));
```

```text
reflexer
```

The AWS SDK for JavaScript does not return the headers with the reply. Read the header with a middleware.

<!-- example: served bedrock -->
```js
import { BedrockRuntimeClient, ConverseCommand } from "@aws-sdk/client-bedrock-runtime";
import * as bedrock from "@reflexer-ai/sdk/bedrock";

const client = bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1" }), process.env.REFLEXER_KEY);
client.middlewareStack.add((next) => async (args) => {
  const out = await next(args);
  console.log(out.response.headers["reflexer-answered-by"]);
  return out;
}, { step: "deserialize" });
await client.send(new ConverseCommand({ modelId: "frontier-x", messages: [{ role: "user", content: [{ text: "Hi" }] }] }));
```

```text
reflexer
```

In the other libraries: aiobotocore, as with boto3; Anthropic's Python clients, with `with_raw_response`, as on [Anthropic](anthropic.md#3-verify); LiteLLM, in `reply._hidden_params["additional_headers"]["llm_provider-reflexer-answered-by"]`; the AI SDK, in `result.response.headers`.

## Behavior

- **Reflexer down, slow or busy:** the SDK sends the call directly to Bedrock, and your code gets Bedrock's answer. The SDK logs a warning (Python: on the `reflexer` logger; TypeScript: with `console.warn`). After a failure, the SDK sends the next calls directly to Bedrock too, for about a minute at most. Then the SDK tries reflexer again.
- **Timeouts, Python:** your client's timeout applies to the call to reflexer. If that timeout expires, the SDK sends the call directly to Bedrock, with the same timeout. So one call can take up to two times your timeout. If reflexer had already forwarded the call, Bedrock may run the call twice and bill it twice.
- **Timeouts, TypeScript:** if reflexer's answer has not started after `headersTimeout` (300 seconds by default), the SDK sends the call directly to Bedrock. If your client's own timeout expires first, the result depends on the library. AnthropicBedrock and the AI SDK (not streamed) send the call to Bedrock again, with the same timeout, so one call can take up to two times your timeout. The AI SDK (streamed) fails with a timeout error. In every case, if reflexer had already forwarded the call, Bedrock may run the call twice and bill it twice.
- **Key refused:** if reflexer refuses your reflexer key, your provider SDK raises its authentication error, and the SDK does not send the call to Bedrock. If your reflexer key was revoked less than one day ago, the SDK still sends your calls directly to Bedrock, and logs a warning.
- **Which calls:** the SDK sends to reflexer only the calls that return a model's message. The SDK sends all other calls, and all calls to `http`, `localhost` or a private IP, to the address your code gave them, as before.
- **What leaves your machine:** the SDK sends the call to reflexer, with your Bedrock key. When reflexer does not answer the call itself, reflexer uses this key to forward the call to Bedrock. Only reflexer receives your reflexer key.
- **A signed call:** the SDK sends the call to reflexer exactly as your library signed it: the call, its signature, your access key ID and, with temporary credentials, your session token. The SDK never sends your AWS secret: only your library's signer reads it. Reflexer never forwards your signature. If you gave reflexer a role in your AWS account at onboarding, reflexer can forward the call to Bedrock itself. Otherwise, when reflexer does not answer a call, the SDK sends the call directly to Bedrock, as when reflexer is down, and your library signs the call again. LiteLLM and the AI SDK do not sign the call again: the SDK sends it with its first signature, while that signature is still valid ([Known limits](limits.md)).
- **Mantle:** Python only. With a Bedrock API key, the SDK sends Mantle calls to reflexer. The SDK sends signed Mantle calls directly to Bedrock.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. If you remove the line, your code works as before.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).

## Options

- `sample=0.01` (TypeScript `{ sample: 0.01 }` in the options of `bedrock.wrap` or the `fetch`): the SDK sends that share of the calls to reflexer, and the other calls directly to Bedrock.
- To skip reflexer for one call, so that the SDK sends it directly to Bedrock:
  - boto3, aiobotocore: `ReflexerSkip=True` on the call.
  - The AWS SDK for JavaScript: `client.send(command, { reflexerSkip: true })`; in a `.ts` file, cast the options to `any`.
  - langchain-aws, Pydantic AI, Strands: add your own hook on the boto3 client: [Advanced](advanced.md#skip-reflexer-for-one-call).
  - The AI SDK: `providerOptions: { reflexer: { skip: true } }`.
  - Anthropic's clients, LiteLLM: `extra_headers={"Reflexer-Skip": "true"}`; AnthropicBedrock (TypeScript): `{ headers: { "Reflexer-Skip": "true" } }` as the call's second argument.
- A [dry run](advanced.md#a-dry-run-give-reflexer-your-providers-answer): you give reflexer your Bedrock answer, and neither the SDK nor reflexer sends the call to Bedrock. Put `replay_response` at the top level of an `InvokeModel` body. On Anthropic's clients, use `extra_body={"replay_response": answer}` (AnthropicBedrock in TypeScript: `replay_response: answer` among the call's parameters, cast to `any` in a `.ts` file).
- Reflexer's address, if reflexer gave you another one: `reflexer_base=` on `reflexer.boto3.client` and Anthropic's classes, `base=` on the `through` functions (TypeScript `{ base }`).

All options: [Advanced](advanced.md).

## Supported versions

- Python 3.10+: boto3 1, aiobotocore 3, `anthropic` 2, LiteLLM 1, langchain-aws 1, Strands 1, Pydantic AI 2.
- Node 20.3+: `@aws-sdk/client-bedrock-runtime` 3 from 3.1160.0, `@anthropic-ai/bedrock-sdk` on `@anthropic-ai/sdk` 1, `@ai-sdk/amazon-bedrock` 5 from 5.0.132 (Node 22+).

With another major version of boto3, aiobotocore, `anthropic`, LiteLLM or the TypeScript libraries, the SDK raises an error before any call.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
