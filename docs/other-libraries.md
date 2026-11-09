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

Each takes your own HTTP client as `own=`, and keeps its proxy and TLS settings; its hooks see your calls to your provider, never reflexer's; its transport carries both, the reflexer key included. Gemini takes `client_args`: give the same dict as both `client_args` and `async_client_args`; without the async one, async calls skip reflexer.

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

## Verify

The reply looks the same either way. The response's `Reflexer-Answered-By` header is `reflexer` when reflexer answered: read it however your library shows headers, as on [OpenAI](openai.md#3-verify).

## Behavior

- **Reflexer down, slow or busy:** the call goes to your provider, and your code gets your provider's answer. The SDK logs a warning (Python: the `reflexer` logger; TypeScript: `console.warn`). After a failure, the next calls go to your provider too, for about a minute at most, then reflexer is tried again.
- **Timeouts, Python:** your client's timeout covers the call to reflexer. If it fires, the call goes to your provider with the same timeout, so a call can take up to twice it. If reflexer had already forwarded the call, your provider may run it, and bill it, twice.
- **Timeouts, TypeScript:** if reflexer's answer has not started after `headersTimeout` (300 seconds by default), the call goes to your provider. If your client's own timeout fires first, that try fails as a timeout, and a retry of your SDK's, if it makes one, goes to your provider. Either way, if reflexer had already forwarded the call, your provider may run it, and bill it, twice.
- **Key refused:** if reflexer refuses your reflexer key, your SDK raises its authentication error; the call does not go to your provider. A key revoked less than a day ago still sends calls to your provider, with a warning.
- **Which calls:** only the calls that return a model's message go to reflexer. Other calls, and calls to `http`, `localhost` or a private IP, go where they were sent, as before.
- **What leaves your machine:** the call, with your provider key, goes to reflexer, which uses the key to forward the call to your provider when it does not answer. The reflexer key goes to reflexer only.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. Remove the line and your code is as it was.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
