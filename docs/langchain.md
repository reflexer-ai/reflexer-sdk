# reflexer with LangChain

Send the calls of LangChain's OpenAI and Gemini chat models (Python), and of its OpenAI models (LangChain.js), through reflexer. For Bedrock, see [Bedrock](bedrock.md#langchain-aws-pydantic-ai-strands).

**Before you begin:** you need `langchain-openai` 1 or `langchain-google-genai` 4 (Python), or `@langchain/openai` (LangChain.js, Node 22+), and the environment variable `REFLEXER_KEY` set to the reflexer key you got at onboarding. The examples are plain JavaScript: in a `.ts` file, write the key as `process.env.REFLEXER_KEY!`.

## 1. Install

The SDK is not on PyPI or npm yet. Install it from a clone of this repository ([README](../README.md#install)).

```sh
pip install --build-constraint reflexer-sdk/build-constraints.txt ./reflexer-sdk  # pip 26.1 or later
```

```sh
npm install /path/to/reflexer-sdk/typescript/reflexer-ai-sdk-VERSION.tgz
```
## 2. Add the line

Python: change the import. Then add your reflexer key as the last argument of the line that creates the model.

<!-- example: served python -->
```diff
  import os
- from langchain_openai import ChatOpenAI
+ from reflexer.langchain_openai import ChatOpenAI

- chat = ChatOpenAI(model="frontier-x")
+ chat = ChatOpenAI(model="frontier-x", reflexer_key=os.environ["REFLEXER_KEY"])
  print(chat.invoke("Hi").content)
```

```text
Hello! How can I help you today?
```

<!-- example: served python -->
```diff
  import os
- from langchain_google_genai import ChatGoogleGenerativeAI
+ from reflexer.langchain_gemini import ChatGoogleGenerativeAI

- chat = ChatGoogleGenerativeAI(model="frontier-x")
+ chat = ChatGoogleGenerativeAI(model="frontier-x", reflexer_key=os.environ["REFLEXER_KEY"])
  print(chat.invoke("Hi").content)
```

```text
Hello! How can I help you today?
```

`AzureChatOpenAI` is LangChain's own class: give it reflexer's HTTP clients. Also give it `stream_usage=True`, so that a stream keeps its usage and price.

<!-- example: served python -->
```diff
  import os
  from langchain_openai import AzureChatOpenAI
+ import reflexer.openai

+ key = os.environ["REFLEXER_KEY"]
- chat = AzureChatOpenAI(azure_deployment="frontier-x")
+ chat = AzureChatOpenAI(azure_deployment="frontier-x", stream_usage=True,
+                        http_client=reflexer.openai.azure_http_client(key), http_async_client=reflexer.openai.azure_async_http_client(key))
  print(chat.invoke("Hi").content)
```

```text
Hello! How can I help you today?
```

LangChain.js: give the model reflexer's `fetch`.

<!-- example: served js -->
```diff
  import { ChatOpenAI } from "@langchain/openai";
+ import * as reflexer from "@reflexer-ai/sdk";

- const chat = new ChatOpenAI({ model: "frontier-x" });
+ const chat = new ChatOpenAI({ model: "frontier-x", configuration: { fetch: reflexer.openai.fetch(process.env.REFLEXER_KEY) } });
  console.log((await chat.invoke("Hi")).content);
```

```text
Hello! How can I help you today?
```

Change `AzureChatOpenAI` the same way, with `reflexer.azure.fetch`.

## 3. Verify

The reply looks the same whether reflexer or your provider answered. A reply from reflexer has a model name that ends in `-reflexer`.

<!-- example: served -->
```python
import os
from reflexer.langchain_openai import ChatOpenAI

chat = ChatOpenAI(model="frontier-x", reflexer_key=os.environ["REFLEXER_KEY"])
print(chat.invoke("Hi").response_metadata["model_name"])
```

```text
frontier-x-reflexer
```

<!-- example: served -->
```js
import { ChatOpenAI } from "@langchain/openai";
import * as reflexer from "@reflexer-ai/sdk";

const chat = new ChatOpenAI({ model: "frontier-x", configuration: { fetch: reflexer.openai.fetch(process.env.REFLEXER_KEY) } });
console.log((await chat.invoke("Hi")).response_metadata.model_name);
```

```text
frontier-x-reflexer
```

## Behavior

- **Reflexer down, slow or busy:** the SDK sends the call directly to your provider, and your code gets your provider's answer. The SDK logs a warning (Python: on the `reflexer` logger; TypeScript: with `console.warn`). After a failure, the SDK sends the next calls directly to your provider too, for about a minute at most. Then the SDK tries reflexer again.
- **Timeouts, Python:** your client's timeout applies to the call to reflexer. If that timeout expires, the SDK sends the call directly to your provider, with the same timeout. So one call can take up to two times your timeout. If reflexer had already forwarded the call, your provider may run the call twice and bill it twice.
- **Timeouts, TypeScript:** if reflexer's answer has not started after `headersTimeout` (300 seconds by default), the SDK sends the call directly to your provider. If your own timeout expires first, while the call is at reflexer, the result depends on how your library ends the call. If your timeout ends the call with a `TimeoutError`, as `AbortSignal.timeout` and the AI SDK's `timeout` do, the SDK sends the call directly to your provider, with a new timeout as long as the time your timeout ran (the same length, when your timeout started with the call). So one call can take up to two times your timeout, and a cancel of yours does not stop that second call. A streamed call fails instead, with a timeout error. The OpenAI, Anthropic and Gemini SDKs end a call at their timeout in the same way as at a cancel, so the SDK cannot tell the two apart: that attempt fails with a timeout error. If your provider SDK then retries the call, the SDK sends the retry directly to your provider. In every case, if reflexer had already forwarded the call, your provider may run the call twice and bill it twice.
- **Key refused:** if reflexer refuses your reflexer key, your provider SDK raises its authentication error, and the SDK does not send the call to your provider. If your reflexer key was revoked less than one day ago, the SDK still sends your calls directly to your provider, and logs a warning.
- **Which calls:** the SDK sends to reflexer only the calls that return a model's message. The SDK sends all other calls, and all calls to `http`, `localhost` or a private IP, to the address your code gave them, as before.
- **What leaves your machine:** the SDK sends the call to reflexer, with your provider key. When reflexer does not answer the call itself, reflexer uses this key to forward the call to your provider. Only reflexer receives your reflexer key.
- **Gemini, no timeout by default:** google-genai sets no timeout, so no timeout of yours limits how long a call waits for reflexer. Give `ChatGoogleGenerativeAI` a `timeout=`.
- **Not covered:** the calls of `ChatAnthropic` (Python and LangChain.js) and `@langchain/google-genai` cannot go through reflexer: [Known limits](limits.md).
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. If you remove the line, your code works as before.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).

## Options

- `sample=0.01` (LangChain.js: `{ sample: 0.01 }` in the `fetch`'s options): the SDK sends that share of the calls to reflexer, and the other calls directly to your provider.
- `chat.invoke("Hi", extra_headers={"Reflexer-Skip": "true"})` (Gemini: `http_options={"headers": {"Reflexer-Skip": "true"}}`; LangChain.js: `invoke("Hi", { options: { headers: { "Reflexer-Skip": "true" } } })`): the SDK sends that call directly to your provider.
- `reflexer_base=` (LangChain.js `{ base }`): reflexer's address, if reflexer gave you another one.

All options: [Advanced](advanced.md).

## Supported versions

`langchain-openai` 1 and `langchain-google-genai` 4 on Python 3.10+. With another major version, the SDK raises an error at import. LangChain.js on `openai` 7, Node 22+: the SDK checks the versions at the first call.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
