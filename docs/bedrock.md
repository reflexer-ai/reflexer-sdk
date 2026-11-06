# reflexer with Amazon Bedrock

Reflexer in front of your Bedrock calls, from boto3, aiobotocore, LiteLLM, Anthropic's Bedrock clients, and what is built on them; or from the AWS SDK for JavaScript, AnthropicBedrock and the AI SDK.

**Before you begin:** your Bedrock library, and `REFLEXER_KEY` set to the key you got at onboarding. Your Bedrock credentials stay as they are: a Bedrock API key (`AWS_BEARER_TOKEN_BEDROCK`) or your AWS credentials, which sign each call (SigV4). The same code works with either.

## 1. Install

Not on PyPI or npm yet: install from a clone of this repository ([README](../README.md#install)).

```sh
pip install ./reflexer-sdk
```

```sh
npm install /path/to/reflexer-sdk/typescript/reflexer-ai-sdk-VERSION.tgz
```
## 2. Add the line

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

A client made elsewhere goes through reflexer too: `reflexer.boto3.through(client, os.environ["REFLEXER_KEY"])`.

### aiobotocore

Give reflexer the client inside its `async with`.

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

They call Bedrock through a boto3 client: give them reflexer's.

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

`AsyncAnthropicBedrock`, `AnthropicBedrockMantle` and `AsyncAnthropicBedrockMantle` change the same way.

### LiteLLM

LiteLLM takes reflexer's HTTP client per call. Make it once, and give it to every call.

<!-- example: served python bedrock -->
```diff
  import os
  import litellm
+ import reflexer.litellm

+ bedrock = reflexer.litellm.client(os.environ["REFLEXER_KEY"])
- reply = litellm.completion(model="bedrock/converse/frontier-x", messages=[{"role": "user", "content": "Hi"}])
+ reply = litellm.completion(model="bedrock/converse/frontier-x", messages=[{"role": "user", "content": "Hi"}], client=bedrock)
  print(reply.choices[0].message.content)
```

```text
Hello! How can I help you today?
```

`reflexer.litellm.async_client` for `acompletion`.

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

Add reflexer's `fetch`, and its middleware last of yours.

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

Bedrock's OpenAI and Anthropic endpoints take the [OpenAI](openai.md) and [Anthropic](anthropic.md) lines, with Bedrock's `base_url` and your Bedrock API key as the key.

## 3. Verify

The reply looks the same either way. The `Reflexer-Answered-By` header says who answered: `reflexer`. With boto3, and so with langchain-aws, Pydantic AI and Strands, which use its client:

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

Elsewhere: Anthropic's Python clients by `with_raw_response`, as on [Anthropic](anthropic.md#3-verify); LiteLLM in `reply._hidden_params["additional_headers"]`; the AWS SDK for JavaScript does not return response headers.

## Behavior

- **Reflexer down, slow or busy:** the call goes to Bedrock, and your code gets Bedrock's answer. The SDK logs a warning (Python: the `reflexer` logger; TypeScript: `console.warn`). After a failure, the next calls go to Bedrock too, for about a minute at most, then reflexer is tried again.
- **Timeouts, Python:** your client's timeout covers the call to reflexer; if it fires, the call goes to Bedrock with the same timeout, so a call can take up to twice it.
- **Timeouts, TypeScript:** after `headersTimeout` (300 seconds by default) the call goes to Bedrock; your client's own timeout covers both calls, and if it fires first, that try fails as a timeout and your SDK's retry goes to Bedrock.
- **What leaves your machine:** the call, with your Bedrock key, goes to reflexer, which uses the key to call Bedrock. The reflexer key goes to reflexer only.
- **A signed call:** reflexer never passes your signature on. If you granted reflexer a role in your AWS account at onboarding, reflexer can pass the call on to Bedrock itself; otherwise a call it does not answer goes from your machine to Bedrock, signed again by your library, as when reflexer is down. Your AWS secret never leaves your library.
- **Mantle:** with a Bedrock API key, through reflexer; signed calls go to Bedrock directly.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. Remove the line and your code is as it was.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](../SECURITY.md#known-limits).
## Options

- `sample=0.01` (TypeScript `{ sample: 0.01 }` in the options of `bedrock.wrap` or the `fetch`): send that share of the calls to reflexer, the rest to Bedrock.
- `ReflexerPassThrough=True` on a boto3 or aiobotocore call (the AWS SDK for JavaScript: `client.send(command, { reflexerPassThrough: true })`; the AI SDK: `providerOptions: { reflexer: { passThrough: true } }`; Anthropic's clients and LiteLLM: `extra_headers={"Reflexer-Pass-Through": "1"}`): that call goes to Bedrock.
- `reflexer_base=` (TypeScript `{ base }`): reflexer's address, if you were given another.

All of them: [Advanced](advanced.md).

## Supported versions

Python 3.10+: boto3 1, aiobotocore 3, `anthropic` 2, LiteLLM 1. Node 20.3+: `@aws-sdk/client-bedrock-runtime` 3 from 3.1160.0, `@anthropic-ai/bedrock-sdk` on `@anthropic-ai/sdk` 1, `@ai-sdk/amazon-bedrock` 5 from 5.0.132 (Node 22+). Another release raises before any call.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
