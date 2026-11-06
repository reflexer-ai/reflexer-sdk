# What your code sees

The same for Python and TypeScript. Where the two differ, it says so.

## Which calls go to reflexer

The calls that return a model's message: OpenAI's and Azure's Chat Completions and Responses, Anthropic's Messages, Gemini's `generateContent`, Bedrock's Converse and InvokeModel, each streamed or not. Every other call (embeddings, files, listing models, counting tokens) goes straight to the provider, as does a call to an address reflexer cannot reach: plain `http`, `localhost`, a private IP address.

## Reflexer's answer

It is your provider's format, with nothing changed by the SDK, so the code that reads answers keeps working.

- A served answer's `model` ends in `-reflexer`, and its price in USD is at `usage.cost`, where cost tools already look. Gemini's answers have no field for a price: theirs is in the `Reflexer-Cost` header, and the model is at `model_version` (TypeScript: `modelVersion`).
- Converse's answers have no `model`: on Bedrock, read the headers below.
- Every response from reflexer carries the headers `Reflexer-Request-Id`, `Reflexer-Answered-By` (`reflexer`, or `provider` when reflexer passed the call on) and `Reflexer-Cost` (in nano USD). A call that went straight to the provider has none of them.
- A stream arrives as your provider SDK reads it, event by event; its usage, when your SDK asks for one, holds the price.
- A provider's error raises your SDK's own error class, as before. An answer cut midway raises your SDK's own error too, as a cut from the provider would, with no price on it; reflexer's bill holds the price.

## When reflexer fails

The call goes to your provider, as it would without reflexer, and your code gets the provider's answer. That holds whatever the failure: reflexer unreachable, a TLS error, reflexer busy or failing (a 429 or a 5xx), an answer that is not reflexer's, reflexer unable to reach your provider.

- The SDK logs a warning naming only the kind of failure, never a message's text: in Python on the `reflexer` logger, in TypeScript by `console.warn`.
- After a failure the next calls go straight too, for a while, longer at each failure in a row and never more than about a minute; then reflexer is tried again. Reflexer can also ask the SDK to send calls straight for a while, when it is busy.
- A key reflexer refuses raises your SDK's authentication error, as a provider's refusal would. A key revoked less than a day ago sends every call straight instead, with a warning, until its grace ends.

## When reflexer is slow

- Python: your client's own timeout covers reflexer's leg. When it fires there, the call goes to the provider with the same timeout, so a call can take up to twice your timeout; if reflexer had already passed the call on, your provider may run it twice.
- TypeScript: reflexer's leg waits `headersTimeout` for its answer to start ([typescript.md, **How long reflexer may take**](typescript.md#how-long-reflexer-may-take)), then the call goes straight. Your client's own timeout covers both legs: when it fires during reflexer's leg, the call fails as a timeout, and your SDK's own retry goes straight.

On Bedrock some libraries differ: [SECURITY.md, **Known limits**](../SECURITY.md#known-limits).

## What goes where

- The reflexer key goes to reflexer only.
- Your provider's key goes with each call to reflexer, which passes it on with the call when it passes the call on to your provider. On a signed Bedrock call, your AWS secret stays with your library's signer.
- No header of reflexer's reaches your provider, except on some signed Bedrock calls (Anthropic's Bedrock and Mantle clients, the AI SDK's provider): [Known limits](../SECURITY.md#known-limits).

What the SDK promises, and the check that holds each promise: [SECURITY.md](../SECURITY.md).

## Known limits

Every case where the SDK does less than the above, with what you see: [SECURITY.md, **Known limits**](../SECURITY.md#known-limits).
