# reflexer with another library

Your library is not listed, but it takes your provider SDK's client, an HTTP client or a `fetch`? Give it reflexer's.

**Before you begin:** `REFLEXER_KEY` set to the key you got at onboarding.

## It takes your provider SDK's client

Give it reflexer's client: [OpenAI](openai.md), [Anthropic](anthropic.md), [Gemini](gemini.md), [Bedrock](bedrock.md). Pydantic AI is built this way: [Pydantic AI](pydantic-ai.md).

## It takes an HTTP client (Python)

Keep your library's own class, and give it reflexer's HTTP client.

<!-- example: served python -->
```diff
  import os
  import openai
+ import reflexer.openai

- client = openai.OpenAI()
+ client = openai.OpenAI(http_client=reflexer.openai.http_client(os.environ["REFLEXER_KEY"]))
  reply = client.chat.completions.create(model="frontier-x", messages=[{"role": "user", "content": "Hi"}])
  print(reply.choices[0].message.content)
```

```text
Hello! How can I help you today?
```

The other HTTP clients reflexer makes:

| For | Sync | Async |
|---|---|---|
| OpenAI | `reflexer.openai.http_client` | `reflexer.openai.async_http_client` |
| Azure OpenAI | `reflexer.openai.azure_http_client` | `reflexer.openai.azure_async_http_client` |
| Anthropic | `reflexer.anthropic.http_client` | `reflexer.anthropic.async_http_client` |

Each takes your own HTTP client as `own=`, and keeps its proxy, TLS settings and hooks. Gemini takes `client_args`, given twice, or its async calls go by aiohttp, past reflexer:

<!-- example: served python -->
```diff
  import os
  from google import genai
+ import reflexer.gemini

+ args = reflexer.gemini.client_args(os.environ["REFLEXER_KEY"])
- client = genai.Client()
+ client = genai.Client(http_options={"client_args": args, "async_client_args": args})
  print(client.models.generate_content(model="frontier-x", contents="Hi").text)
```

```text
Hello! How can I help you today?
```

## It takes a `fetch` (TypeScript)

Give it reflexer's `fetch`.

<!-- example: served js -->
```diff
  import OpenAI from "openai";
+ import * as reflexer from "@reflexer-ai/sdk";

- const client = new OpenAI();
+ const client = new OpenAI({ fetch: reflexer.openai.fetch(process.env.REFLEXER_KEY) });
  const reply = await client.chat.completions.create({ model: "frontier-x", messages: [{ role: "user", content: "Hi" }] });
  console.log(reply.choices[0].message.content);
```

```text
Hello! How can I help you today?
```

Also `reflexer.azure.fetch`, `reflexer.anthropic.fetch` and `reflexer.gemini.fetch` (Gemini takes it in `httpOptions: { fetch }`). Each takes your own `fetch` as `{ fetch }`.

## It takes none of these

Then its calls cannot go through reflexer yet. Open an issue on this repository naming it.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
