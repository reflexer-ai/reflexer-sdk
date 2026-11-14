# reflexer with another library

Your library has no page here, but it accepts your provider SDK's client, an HTTP client or a `fetch`? Then give your library reflexer's client, HTTP client or `fetch` instead.

**Before you begin:** you need the environment variable `REFLEXER_KEY` set to the reflexer key you got at onboarding.

## It takes your provider SDK's client

Give it reflexer's client: [OpenAI](openai.md), [Anthropic](anthropic.md), [Gemini](gemini.md), [Bedrock](bedrock.md). Pydantic AI works this way: [Pydantic AI](pydantic-ai.md).

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

The HTTP clients of the SDK:

| For | Sync | Async |
|---|---|---|
| OpenAI | `reflexer.openai.http_client` | `reflexer.openai.async_http_client` |
| Azure OpenAI | `reflexer.openai.azure_http_client` | `reflexer.openai.azure_async_http_client` |
| Anthropic | `reflexer.anthropic.http_client` | `reflexer.anthropic.async_http_client` |

Each one accepts your own HTTP client as `own=`, and keeps that client's proxy and TLS settings. Your client's hooks see your calls to your provider, never the calls to reflexer. Your client's transport sends both kinds of calls, so it also carries the reflexer key. Gemini takes `client_args` instead: give the same dict as both `client_args` and `async_client_args`. Without `async_client_args`, async calls do not go through reflexer: they go directly to Gemini.

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

The SDK also has `reflexer.azure.fetch`, `reflexer.anthropic.fetch` and `reflexer.gemini.fetch` (Gemini takes it in `httpOptions: { fetch }`). Each one accepts your own `fetch` as `{ fetch }`.

## It takes none of these

Then the SDK cannot send its calls through reflexer yet. Open an issue on this repository, with the library's name.

## Verify

The reply looks the same whether reflexer or your provider answered. The response's `Reflexer-Answered-By` header is `reflexer` when reflexer answered. Read the header in the way your library shows headers, as on [OpenAI](openai.md#3-verify).

## Behavior

- **Reflexer down, slow or busy:** the SDK sends the call directly to your provider, and your code gets your provider's answer. The SDK logs a warning (Python: on the `reflexer` logger; TypeScript: with `console.warn`). After a failure, the SDK sends the next calls directly to your provider too, for about a minute at most. Then the SDK tries reflexer again.
- **Timeouts, Python:** your client's timeout applies to the call to reflexer. If that timeout expires, the SDK sends the call directly to your provider, with the same timeout. So one call can take up to two times your timeout. If reflexer had already forwarded the call, your provider may run the call twice and bill it twice.
- **Timeouts, TypeScript:** if reflexer's answer has not started after `headersTimeout` (300 seconds by default), the SDK sends the call directly to your provider. If your own timeout expires first, while the call is at reflexer, the result depends on how your library ends the call. If your timeout ends the call with a `TimeoutError`, as `AbortSignal.timeout` and the AI SDK's `timeout` do, the SDK sends the call directly to your provider, with a new timeout as long as the time your timeout ran (the same length, when your timeout started with the call). So one call can take up to two times your timeout, and a cancel of yours does not stop that second call. A streamed call fails instead, with a timeout error. The OpenAI and Gemini SDKs, and Anthropic's stock class given reflexer's `fetch`, end a call at their timeout in the same way as at a cancel, so the SDK cannot tell the two apart: that attempt fails with a timeout error. If your provider SDK then retries the call, the SDK sends the retry directly to your provider. In every case, if reflexer had already forwarded the call, your provider may run the call twice and bill it twice.
- **Key refused:** if reflexer refuses your reflexer key, your provider SDK raises its authentication error, and the SDK does not send the call to your provider. If your reflexer key was revoked less than one day ago, the SDK still sends your calls directly to your provider, and logs a warning.
- **Which calls:** the SDK sends to reflexer only the calls that return a model's message. The SDK sends all other calls, and all calls to `http`, `localhost` or a private IP, to the address your code gave them, as before.
- **What leaves your machine:** the SDK sends the call to reflexer, with your provider key. When reflexer does not answer the call itself, reflexer uses this key to forward the call to your provider. Only reflexer receives your reflexer key.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. If you remove the reflexer client, your code works as before.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)
