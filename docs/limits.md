# Known limits

For when reflexer does less than the library pages say. Each row: the case, what happens, and what you can do. The full list, with the check that holds each promise: [SECURITY.md](../SECURITY.md#known-limits).

## Every library

| Case | What happens | What you can do |
|---|---|---|
| Reflexer is slow | Python: the call goes to your provider when your timeout fires, so it can take up to twice your timeout. TypeScript: your timeout covers both calls; if it fires during the call to reflexer, that try fails, and a retry of your SDK's, if it makes one, goes to your provider. Either way, if reflexer had already forwarded the call, your provider may run it, and bill it, twice | Keep your timeouts as before; in TypeScript, a lower `headersTimeout` ([Advanced](advanced.md#how-long-reflexer-may-take)) |
| A `base_url` on a private name (a host only your network knows) | The call goes to reflexer first, which cannot reach the host and sends it back; it then goes to the host directly: one more trip | Skip reflexer for those calls, or leave them on a stock client |
| TypeScript: a call given as a `Request` object, or with a streamed body | It goes to your provider, not reflexer | Pass the body as a string or bytes, as the provider SDKs do |
| Python: you cancel a call, or press ^C, while it is at reflexer | The error keeps its type, message and your frames, but none below the SDK's transport and no error it came while handling: those hold the reflexer key | Nothing |
| Python: making a client fails (a provider key or region missing) | The SDK's frames on that error can hold the reflexer key, as the provider SDK's hold your provider key | If an error tracker records frame variables, have it scrub `reflexer_key` and `key` |
| TypeScript: you cancel a call while it is at reflexer | Counted as a reflexer failure: the next calls go to your provider for a while | Nothing |
| Python: threads sharing one client open new connections at once | A CPython bug ([python/cpython#141012](https://github.com/python/cpython/issues/141012)) can garble a TLS handshake. If it hits the call to reflexer, the call goes to your provider, and so do your next calls for about a second ([When reflexer fails](when-reflexer-fails.md#reflexer-is-down-or-unreachable)); no reply is wrong. Amazon Bedrock's lines first try reflexer once more. On Alpine (musl), the same bug can crash the process, with or without reflexer | Nothing |
| TypeScript: a `fetch` dispatcher of yours that follows redirects | It could carry the reflexer key to a redirect's target | Keep redirects off for reflexer's address |

## Libraries

| Case | What happens | What you can do |
|---|---|---|
| openai (TypeScript) with X.509 workload identity | It takes no custom `fetch`, so its calls cannot go through reflexer | Use a key |
| `@google/genai` before 2.23.0 | It takes no `fetch`: its calls go to Gemini, never to reflexer | Upgrade to 2.29.0 or later |
| LangChain's `ChatAnthropic` (Python and LangChain.js), `@langchain/google-genai` | Their calls cannot go through reflexer | Use the provider's client, or another LangChain model class |
| LangChain's own classes given an HTTP client | They stop asking a stream for its usage and price | Pass `stream_usage=True` |
| LangChain's TCP keepalive (`http_socket_options`) | Not applied on reflexer's classes | Set it on an HTTP client of yours, given as `http_client` |
| LangChain's `dumpd`, then `loads` | Gives back LangChain's own class, without reflexer | Make the model with reflexer's class again |
| Pydantic AI on Python 3.10 | Its last release for 3.10 fails Anthropic's calls, with the stock client too | Python 3.11 or later |
| Gemini's automatic function calling (google-genai; `@google/genai` given a `CallableTool`) | One SDK call can make several HTTP calls, and the reply shows only the last one's price (`Reflexer-Cost`); your bill counts them all | Run the tool loop yourself: each call's reply then shows its price |
| The AI SDK on Gemini | It names the model you asked for, not the reply's | Read `result.response.headers["reflexer-answered-by"]` |
| LiteLLM: a `client_session`, `aclient_session` or `sync_transport` set after the line, or `litellm.callbacks = [...]` replacing the list | The calls they cover go to your provider directly: OpenAI's and Azure's for the sessions; Anthropic's, Gemini's and Bedrock's, sync for the transport and async for the callbacks | Set yours before the line; append to `litellm.callbacks` |
| LiteLLM's TLS, certificate and proxy settings (`ssl_verify`, `SSL_CERTIFICATE`, the proxy variables) | Read as the line runs: one changed after it does not apply to LiteLLM's sync calls to any provider, and a call's own `ssl_verify` does not apply to them, nor to `acompletion`'s calls to Anthropic, Gemini and Bedrock: such a call to a host whose certificate is not trusted fails | Set them, globally, before the line |
| LiteLLM with `force_ipv4` | The line raises `RuntimeError`: LiteLLM then sends its calls by a transport of its own. Turned on after the line, Anthropic's, Gemini's and Bedrock's sync calls go to your provider | Leave `force_ipv4` off |
| LiteLLM: a call to another host (a router or gateway as `api_base`, an OpenAI-compatible provider, Azure on your own domain or its government and China clouds, Bedrock's Mantle) | It goes to that host as before, not through reflexer | Call the provider's own host |
| LiteLLM's async calls other than `acompletion` (`litellm.anthropic.messages.acreate`, say) to Anthropic, Gemini or Bedrock | They go to your provider as before | Use `acompletion` |
| LiteLLM: an OpenAI call given `shared_session=` | It goes through reflexer by the line's HTTP client, not your session | Set your session as `litellm.aclient_session` before the line |
| LiteLLM: a call given its own `client=`, or an Anthropic, Gemini or Bedrock call given `shared_session=`; async calls LiteLLM sends by its Responses API (`openai/responses/...` models, and chat calls it routes there) | They go to your provider as before | Leave `client=` and `shared_session=` out |
| LiteLLM on Gemini 3 models | LiteLLM calls them at `v1alpha`, which reflexer does not take: they go to Gemini directly | Nothing yet |

## Amazon Bedrock

| Case | What happens | What you can do |
|---|---|---|
| A signed call, with no role granted to reflexer at onboarding | Reflexer cannot forward it; if it does not answer, your library sends it to Bedrock: two trips | Grant reflexer the role at onboarding, or use a Bedrock API key |
| LiteLLM and the AI SDK, signed | They cannot sign a call again: if reflexer does not answer while the signature holds (about five minutes), the call goes to Bedrock as first signed; a clock far behind AWS's can see it refused | Keep your machine's clock synced |
| A Bedrock API key limited to your network (source IP, VPC endpoint) | Bedrock refuses reflexer's forward; the call then goes to Bedrock from your machine: one more trip | Use a key without that limit, or a role |
| Anthropic's Bedrock and Mantle clients, signed | They sign every header, so a reflexer header you set reaches Bedrock; a signed call to Mantle goes to Bedrock directly | Nothing |
| langchain-aws, Strands, Pydantic AI | They make the boto3 call themselves: no per-call argument reaches it | Skip with a hook on the client ([Advanced](advanced.md#skip-reflexer-for-one-call)) |
| `ReflexerPassThrough=True` on a stock boto3 client | botocore refuses it | Use it on reflexer's client only |
| The AWS SDK for JavaScript, `reflexerPassThrough` | Not in the SDK's types | Cast the options to `any` in a `.ts` file |
| The AWS SDK for JavaScript with its fetch handler (a browser or edge build) | `bedrock.wrap` refuses it, since fetch follows redirects with the key | Use the Node handlers, the default on Node |
| aiobotocore on another HTTP session class | Refused when the client is given to reflexer | Use aiobotocore's own session |
| The AI SDK on Bedrock, streamed, when its timeout fires at reflexer | The call fails as a timeout | Lower `headersTimeout` below your timeout |
| The AI SDK on Bedrock, not streamed, and AnthropicBedrock (TypeScript), when the timeout fires at reflexer | The call goes to Bedrock with the timeout again: up to twice it | Lower `headersTimeout` below your timeout |
| The AI SDK on Bedrock | Needs Node 22, its own floor | Node 22 or later |

Next: [When reflexer fails](when-reflexer-fails.md) · [Reference](reference.md)
