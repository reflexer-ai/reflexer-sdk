# What your code sees

## Which calls go to reflexer

Calls that return a model's message: Chat Completions and Responses (OpenAI, Azure), Messages (Anthropic), `generateContent` (Gemini), Converse and InvokeModel (Bedrock), streamed or not. Everything else (embeddings, files, model lists, token counts) goes straight to the provider, and so does a call to plain `http`, `localhost` or a private IP.

## Reflexer's answer

Your provider's format, unchanged, so your code reads it as before.

- `model` ends in `-reflexer`, and `usage.cost` holds the price in USD. Gemini: the model is at `model_version`, the price only in the `Reflexer-Cost` header. Converse has no `model`: read the headers.
- Headers: `Reflexer-Answered-By` is `reflexer`, or `provider` when reflexer passed the call on; `Reflexer-Cost` is the price in nano USD; `Reflexer-Request-Id` names the call. A call that went to your provider directly has none of them.
- Streams arrive event by event; their usage holds the price. Errors raise your SDK's own classes.

## When reflexer is down

The call goes to your provider and you get its answer, as without reflexer. A warning names the failure (Python: the `reflexer` logger; TypeScript: `console.warn`). The next calls go to your provider too, for up to about a minute, then reflexer is tried again.

A key reflexer refuses raises your SDK's authentication error. A key revoked less than a day ago sends calls to your provider, with a warning.

## When reflexer is slow

- Python: your client's timeout covers the call to reflexer; when it fires, the call goes to your provider with the same timeout.
- TypeScript: after `headersTimeout` ([typescript.md](typescript.md#how-long-reflexer-may-take)) the call goes to your provider. Your client's own timeout covers the call to reflexer and the one to your provider together: if it fires while reflexer is answering, that try fails as a timeout, and your SDK's retry goes to your provider.

So a call can take up to twice your timeout, and your provider may run it twice. This, and every other limit: [Known limits](../SECURITY.md#known-limits).

## Keys

The reflexer key goes to reflexer only. Your provider key goes with the call to reflexer, which uses it to pass the call on. Your AWS secret never leaves your library's signer.
