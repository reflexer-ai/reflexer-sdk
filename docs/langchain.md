# reflexer with LangChain

Reflexer in front of LangChain's OpenAI and Gemini chat models in Python, and its OpenAI models in LangChain.js. On Bedrock: [Bedrock](bedrock.md#langchain-aws-pydantic-ai-strands).

**Before you begin:** `langchain-openai` 1 or `langchain-google-genai` 4 (Python), or `@langchain/openai` (LangChain.js, Node 22+), and `REFLEXER_KEY` set to the key you got at onboarding. In a `.ts` file, write the key as `process.env.REFLEXER_KEY!`: the examples are plain JavaScript.

## 1. Install

Not on PyPI or npm yet: install from a clone of this repository ([README](../README.md#install)).

```sh
pip install ./reflexer-sdk
```

```sh
npm install /path/to/reflexer-sdk/typescript/reflexer-ai-sdk-VERSION.tgz
```
## 2. Add the line

Python: change the import, and add your reflexer key at the end of the line that makes the model.

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

`AzureChatOpenAI` is LangChain's own class: give it reflexer's HTTP clients, and `stream_usage=True` to keep a stream's usage and price.

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

`AzureChatOpenAI` the same way, with `reflexer.azure.fetch`.

## 3. Verify

The reply looks the same either way. A served reply's model name ends in `-reflexer`.

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

- **Reflexer down, slow or busy:** the call goes to your provider, and your code gets your provider's answer. The SDK logs a warning (Python: the `reflexer` logger; TypeScript: `console.warn`). After a failure, the next calls go to your provider too, for about a minute at most, then reflexer is tried again.
- **Timeouts, Python:** your client's timeout covers the call to reflexer. If it fires, the call goes to your provider with the same timeout, so a call can take up to twice it; if reflexer had already passed the call on, your provider may run it twice.
- **Timeouts, TypeScript:** after `headersTimeout` (300 seconds by default) the call goes to your provider. Your client's own timeout covers both calls: if it fires first, that try fails as a timeout and your SDK's retry goes to your provider; if reflexer had already passed the call on, your provider may run it twice.
- **Which calls:** only the calls that return a model's message go to reflexer. The others (embeddings, files, model lists) and calls to `http`, `localhost` or a private IP go to your provider directly.
- **What leaves your machine:** the call, with your provider key, goes to reflexer, which uses the key to pass the call on. The reflexer key goes to reflexer only.
- **Not covered:** `ChatAnthropic` (Python and LangChain.js) and `@langchain/google-genai`: [Known limits](../SECURITY.md#known-limits).
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. Remove the line and your code is as it was.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](../SECURITY.md#known-limits).
## Options

- `sample=0.01` (LangChain.js: `{ sample: 0.01 }` in the `fetch`'s options): send that share of the calls to reflexer, the rest to your provider.
- `chat.invoke("Hi", extra_headers={"Reflexer-Pass-Through": "1"})` (Gemini: `http_options={"headers": {"Reflexer-Pass-Through": "1"}}`; LangChain.js: `invoke("Hi", { options: { headers: { "Reflexer-Pass-Through": "1" } } })`): that call goes to your provider.
- `reflexer_base=` (LangChain.js `{ base }`): reflexer's address, if you were given another.

All of them: [Advanced](advanced.md).

## Supported versions

`langchain-openai` 1 and `langchain-google-genai` 4 on Python 3.10+, where another major raises at import. LangChain.js on `openai` 7, Node 22+, checked at the first call.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
