# Known limits

This page is for cases where reflexer does less than the library pages say. Each row gives the case, what happens, and what you can do. The full list, with the check that tests each promise: [SECURITY.md](../SECURITY.md#known-limits).

## Every library

| Case | What happens | What you can do |
|---|---|---|
| Reflexer is slow | Python: when your timeout expires, the SDK sends the call directly to your provider. So a call can take up to twice your timeout. TypeScript: your timeout applies to both calls. If your timeout expires during the call to reflexer, that try fails. If your provider SDK then retries, the retry goes directly to your provider. In both languages: if reflexer had already forwarded the call, your provider may run the call twice, and bill it twice | Keep your timeouts as before. In TypeScript, you can lower `headersTimeout` ([Advanced](advanced.md#how-long-reflexer-may-take)) |
| A `base_url` on a private name (a host that only your network knows) | The SDK sends the call to reflexer first. Reflexer cannot reach the host and sends the call back. Then the SDK sends the call to the host directly. This adds one round trip | Skip reflexer for those calls, or use a client without reflexer for them |
| TypeScript: a call given as a `Request` object, or with a streamed body | The SDK sends the call directly to your provider, not to reflexer | Pass the body as a string or as bytes, as the provider SDKs do |
| A [dry run](advanced.md#a-dry-run-give-reflexer-your-providers-answer) whose body is given as a stream | The SDK does not see the call as a dry run. The SDK sends it as a normal call, and your provider may receive it | Give the whole body at once, as the provider SDKs do |
| Python: you cancel a call, or press ^C, while the call is at reflexer | The error keeps its type, its message and your frames. The error does not keep the frames below the SDK's transport, or the error that Python was handling when it raised this one: those hold the reflexer key | Nothing |
| Python: making a client fails (a provider key or region is missing), or LiteLLM makes its HTTP client again during a call | The SDK's frames on that error can hold the reflexer key, in the same way that the provider SDK's frames hold your provider key | If an error tracker records frame variables, configure it to hide `reflexer_key` and `key` |
| TypeScript: you cancel a call while the call is at reflexer | The SDK counts this as a reflexer failure: the SDK sends the next calls directly to your provider for some time | Nothing |
| Python: threads that share one client open new connections at the same time | A CPython bug ([python/cpython#141012](https://github.com/python/cpython/issues/141012)) can corrupt a TLS handshake. If this happens on the call to reflexer, the SDK sends the call directly to your provider. The SDK also sends your next calls directly to your provider for about one second ([When reflexer fails](when-reflexer-fails.md#reflexer-is-down-or-unreachable)). No reply is wrong. The reflexer clients for Amazon Bedrock first try reflexer once more. On Alpine (musl), the same bug can crash the process, with or without reflexer | Nothing |
| TypeScript: a `fetch` dispatcher of yours that follows redirects | The dispatcher could send the reflexer key to the target of a redirect | Do not follow redirects for reflexer's address |

## Libraries

| Case | What happens | What you can do |
|---|---|---|
| openai (TypeScript) with X.509 workload identity | It accepts no custom `fetch`, so its calls cannot go through reflexer | Use a key |
| `@google/genai` before 2.23.0 | It accepts no `fetch`: its calls go to Gemini, never to reflexer | Upgrade to 2.29.0 or later |
| LangChain's `ChatAnthropic` (Python and LangChain.js), `@langchain/google-genai` | Their calls cannot go through reflexer | Use the provider's client, or another LangChain model class |
| LangChain's own classes given an HTTP client | They do not ask a stream for its usage and price | Pass `stream_usage=True` |
| LangChain's TCP keepalive (`http_socket_options`) | Reflexer's classes do not apply it | Set it on your own HTTP client, and pass that client as `http_client` |
| LangChain's `dumpd`, then `loads` | The result is LangChain's own class, without reflexer | Make the model again with reflexer's class |
| Pydantic AI on Python 3.10 | Its last release for 3.10 fails Anthropic's calls, also without reflexer | Use Python 3.11 or later |
| Gemini's automatic function calling (google-genai; `@google/genai` given a `CallableTool`) | One SDK call can make several HTTP calls. The reply shows only the price of the last HTTP call (`Reflexer-Cost-Nano-Usd`). Your bill counts all of them | Run the tool loop yourself: then each call's reply shows its own price |
| The AI SDK on Gemini | It reports the model that you asked for, not the model in the reply | Read `result.response.headers["reflexer-answered-by"]` |
| LiteLLM: your code sets `client_session`, `aclient_session` or `sync_transport` after the line, or replaces the list with `litellm.callbacks = [...]` | The SDK no longer sees the calls that setting covers, and LiteLLM sends them directly to your provider: OpenAI's and Azure's calls for the two sessions; Anthropic's, Gemini's and Bedrock's sync calls for `sync_transport`, and their async calls for the callbacks | Set your own settings before the line. Append to `litellm.callbacks` instead of replacing it |
| LiteLLM: a call's own `ssl_verify` | It does not apply to LiteLLM's sync calls to any provider or host, or to `acompletion`'s calls to Anthropic, Gemini and Bedrock. These calls use LiteLLM's global TLS settings (`litellm.ssl_verify`, `SSL_VERIFY`, `SSL_CERT_FILE`, `SSL_CERTIFICATE`) as they are when the line runs. For async calls: as they are when LiteLLM makes the HTTP client of each event loop. `Reflexer-Skip: true` does not change this. The result is the same or stricter: a call that asks for no certificate check is still checked, and a call that gives its own certificate fails. The one exception: if LiteLLM's global check is off (`litellm.ssl_verify = False`, or `SSL_VERIFY=false`), a call that asks for the check is not checked. Then the line logs a warning on the `reflexer` logger | Set LiteLLM's global setting before the line. Or give the call its own client. LiteLLM sends that call directly to your provider, with its own setting: sync `client=HTTPHandler(client=httpx.Client(verify=...))`, async `client=AsyncHTTPHandler(ssl_verify=...)` (both from `litellm.llms.custom_httpx.http_handler`) |
| LiteLLM: you change its global TLS, certificate or proxy settings after the line | The change does not apply to LiteLLM's sync calls, to any provider | Set them before the line |
| LiteLLM with `force_ipv4` | The line raises `RuntimeError`, because LiteLLM then sends its calls by a transport of its own. If you turn `force_ipv4` on after the line, LiteLLM sends Anthropic's, Gemini's and Bedrock's sync calls directly to your provider | Leave `force_ipv4` off |
| LiteLLM: a call to another host (a router or gateway given as `api_base`, an OpenAI-compatible provider, Azure on your own domain or on its government and China clouds, Bedrock's Mantle) | LiteLLM sends the call to that host as before, not through reflexer | Call the provider's own host |
| LiteLLM: async calls to Anthropic, Gemini or Bedrock other than `acompletion` (for example `litellm.anthropic.messages.acreate`) | LiteLLM sends them directly to your provider, as before | Use `acompletion` |
| LiteLLM: an OpenAI call given `shared_session=` | The SDK sends the call through reflexer by the line's HTTP client, not by your session | Set your session as `litellm.aclient_session` before the line |
| LiteLLM: a call given its own `client=`, an Anthropic, Gemini or Bedrock call given `shared_session=`, and the async calls that LiteLLM sends by its Responses API (`openai/responses/...` models, and chat calls that LiteLLM routes there) | LiteLLM sends them directly to your provider, as before | Leave out `client=` and `shared_session=` |

## Amazon Bedrock

| Case | What happens | What you can do |
|---|---|---|
| A signed call, when you did not grant a role to reflexer at onboarding | Reflexer cannot forward the call. If reflexer does not answer, your library sends the call to Bedrock: two round trips | Grant reflexer the role at onboarding, or use a Bedrock API key |
| LiteLLM and the AI SDK, signed | They cannot sign a call again. If reflexer does not answer while the signature is valid (about five minutes), the SDK sends the call to Bedrock with its first signature. If your clock is far behind the AWS clock, Bedrock can refuse the call | Keep your machine's clock synchronized |
| A Bedrock API key limited to your network (source IP, VPC endpoint) | Bedrock refuses the call that reflexer forwards. Then the SDK sends the call to Bedrock from your machine: one more round trip | Use a key without that limit, or a role |
| Anthropic's Mantle client (Python), signed | The SDK sends the call directly to Bedrock. The client signs every header, so Bedrock receives any reflexer header that you set on the call | Pass a namespace or an option to the client (`reflexer_namespace`, `reflexer_store`, ...) |
| The AI SDK on Bedrock, signed, with a reflexer header on the call (`Reflexer-Answer`, `Reflexer-Namespace`, ...) | The AI SDK signs every header, so the SDK sends the call directly to Bedrock, which receives the header. For example, with `Reflexer-Answer: false` on the call, you get Bedrock's answer, and Bedrock bills the call | Pass the option or the namespace to the line (`answer`, `namespace`, ...) |
| boto3, aiobotocore, the AWS SDK for JavaScript and Anthropic's Bedrock client, signed, with `Reflexer-Namespace` on the call | The client signs the header, so Bedrock receives it too. The option headers (`Reflexer-Answer`, ...) reach only reflexer | Pass the namespace to the client |
| boto3, aiobotocore and the AWS SDK for JavaScript, signed, when reflexer did not answer and signing the call again fails | The SDK sends the call to Bedrock with its first signature. Python logs the warning "signing the call again failed" | Nothing |
| langchain-aws, Strands, Pydantic AI | They make the boto3 call themselves, so no per-call argument reaches it | Skip reflexer with a hook on the client ([Advanced](advanced.md#skip-reflexer-for-one-call)) |
| `ReflexerSkip=True` on a boto3 client without reflexer | botocore refuses it | Use it only on reflexer's client |
| The AWS SDK for JavaScript, `reflexerSkip` | It is not in the AWS SDK's types | Cast the options to `any` in a `.ts` file |
| The AWS SDK for JavaScript with its fetch handler (a browser or edge build) | `bedrock.wrap` refuses it, because fetch follows redirects and would send the key with them | Use the Node handlers (the default on Node) |
| aiobotocore on another HTTP session class | The SDK refuses the client when you give the client to reflexer | Use aiobotocore's own session |
| The AI SDK on Bedrock, streamed, when its timeout expires during the call to reflexer | The call fails with a timeout error | Set `headersTimeout` lower than your timeout |
| The AI SDK on Bedrock, not streamed, and AnthropicBedrock (TypeScript), when the timeout expires during the call to reflexer | Then the SDK sends the call to Bedrock, with your timeout again. So the call can take up to twice your timeout | Set `headersTimeout` lower than your timeout |
| The AI SDK on Bedrock | The AI SDK itself needs Node 22 or later | Use Node 22 or later |

Next: [When reflexer fails](when-reflexer-fails.md) · [Reference](reference.md)
