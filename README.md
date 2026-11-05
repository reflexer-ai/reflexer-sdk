# reflexer

Reflexer's SDK for Python and TypeScript. It sends a client's LLM calls through reflexer, on the provider SDK the client already uses. A call reflexer does not answer, or cannot be reached for, goes to the provider as before.

No dependency of its own: it plugs into the HTTP client of the provider SDK you already have. Its security promises, and the check that holds each one: [SECURITY.md](SECURITY.md).

## Use

One line changes; your own arguments stay as they were.

    # client = openai.OpenAI(api_key=openai_key)
    client = reflexer.openai.OpenAI(api_key=openai_key, reflexer_key=reflexer_key)

    # client = anthropic.Anthropic(api_key=anthropic_key)
    client = reflexer.anthropic.Anthropic(api_key=anthropic_key, reflexer_key=reflexer_key)

    # client = genai.Client(api_key=gemini_key)
    client = reflexer.gemini.Client(api_key=gemini_key, reflexer_key=reflexer_key)

Also `AsyncOpenAI`, `AzureOpenAI`, `AsyncAzureOpenAI` and `AsyncAnthropic`. A router or a runner on the OpenAI format works the same, by its `base_url`.

Or keep the stock class and give it reflexer's HTTP client:

    client = openai.OpenAI(api_key=openai_key, http_client=reflexer.openai.http_client(reflexer_key))
    client = genai.Client(api_key=gemini_key, http_options={"client_args": reflexer.gemini.client_args(reflexer_key),
                                                            "async_client_args": reflexer.gemini.client_args(reflexer_key)})

On Gemini, give both: with only `httpx_client`, google-genai sends async calls by aiohttp when it is installed, past reflexer. Streams pass through as the provider SDKs read them.

## TypeScript

The package is `@reflexer-ai/sdk`, not published yet. For now, build it from a clone of this repository and install the archive in your project:

    cd typescript && npm ci && npm pack            # makes reflexer-ai-sdk-VERSION.tgz
    npm install path/to/reflexer-ai-sdk-VERSION.tgz  # in your project

One line changes, as in Python; your own options stay as they were.

    // client = new OpenAI({ apiKey: openaiKey })
    import { OpenAI } from "@reflexer-ai/sdk/openai";
    const client = new OpenAI({ apiKey: openaiKey, reflexerKey });

    // client = new Anthropic({ apiKey: anthropicKey })
    import { Anthropic } from "@reflexer-ai/sdk/anthropic";
    const client = new Anthropic({ apiKey: anthropicKey, reflexerKey });

    // client = new GoogleGenAI({ apiKey: geminiKey })
    import { GoogleGenAI } from "@reflexer-ai/sdk/gemini";
    const client = new GoogleGenAI({ apiKey: geminiKey, reflexerKey });

Also `AzureOpenAI`, from `@reflexer-ai/sdk/openai`. Or keep the stock class and give it reflexer's `fetch`:

    import * as reflexer from "@reflexer-ai/sdk";
    new OpenAI({ apiKey: openaiKey, fetch: reflexer.openai.fetch(reflexerKey) });
    new AzureOpenAI({ ...azureOptions, fetch: reflexer.azure.fetch(reflexerKey) });
    new Anthropic({ apiKey: anthropicKey, fetch: reflexer.anthropic.fetch(reflexerKey) });
    new GoogleGenAI({ apiKey: geminiKey, httpOptions: { fetch: reflexer.gemini.fetch(reflexerKey) } });

A `fetch` of your own carries both reflexer's leg and the provider's: give it as before on the one-line classes, or as `reflexer.openai.fetch(reflexerKey, { fetch: yourFetch })`. Node 20.3 or newer, no dependency; the provider SDK is the one you have. Tested on openai 7, @anthropic-ai/sdk 1 and @google/genai 2 from 2.29.0: a call made by any other release throws, where the stock SDK would answer; on google-genai 2.23 to 2.28 too, which stock runs with undici's own timeouts.

## The AI SDK

Its providers take a `fetch`; give them reflexer's, nothing else changes:

    // openai = createOpenAI({ apiKey: openaiKey })
    openai = createOpenAI({ apiKey: openaiKey, fetch: reflexer.openai.fetch(reflexerKey) });
    anthropic = createAnthropic({ apiKey: anthropicKey, fetch: reflexer.anthropic.fetch(reflexerKey) });
    google = createGoogleGenerativeAI({ apiKey: geminiKey, fetch: reflexer.gemini.fetch(reflexerKey) });

On Gemini the AI SDK names the model you asked for, not the answer's; `result.response.headers["reflexer-answered-by"]` says who answered, on every provider.

## LangChain.js

    // chat = new ChatOpenAI({ model })
    chat = new ChatOpenAI({ model, configuration: { fetch: reflexer.openai.fetch(reflexerKey) } });
    chat = new AzureChatOpenAI({ ...azureOptions, configuration: { fetch: reflexer.azure.fetch(reflexerKey) } });

`@langchain/anthropic`'s `ChatAnthropic` takes a `fetch` too, but bundles `@anthropic-ai/sdk` 0.x, a major this SDK is not tested on: its calls throw. `@langchain/google-genai` is built on `@google/generative-ai`, which takes no `fetch`. So neither has a line here.

## LangChain

    # chat = ChatOpenAI(model=model)
    chat = reflexer.langchain_openai.ChatOpenAI(model=model, reflexer_key=reflexer_key)

    # chat = ChatGoogleGenerativeAI(model=model)
    chat = reflexer.langchain_gemini.ChatGoogleGenerativeAI(model=model, reflexer_key=reflexer_key)

Or LangChain's own `ChatOpenAI`, given `http_client=reflexer.openai.http_client(reflexer_key)` and `http_async_client=reflexer.openai.async_http_client(reflexer_key)`. `AzureChatOpenAI` the same way, given `reflexer.openai.azure_http_client(reflexer_key)` and `reflexer.openai.azure_async_http_client(reflexer_key)`. Given an HTTP client, LangChain stops asking a stream for its usage, and its price: pass `stream_usage=True` to keep it. Reflexer's class asks as LangChain's would for the same settings. LangChain's TCP keepalive (`http_socket_options`) applies only to the HTTP clients it builds itself: not on these lines. LangChain's serialization (`dumpd`, then `loads`) gives back its own class, without reflexer. `ChatAnthropic` takes no HTTP client, so it has no line here.

## Pydantic AI

Its providers take the provider SDK's client; give them reflexer's:

    OpenAIProvider(openai_client=reflexer.openai.AsyncOpenAI(api_key=openai_key, reflexer_key=reflexer_key))
    AnthropicProvider(anthropic_client=reflexer.anthropic.AsyncAnthropic(api_key=anthropic_key, reflexer_key=reflexer_key))
    GoogleProvider(client=reflexer.gemini.Client(api_key=gemini_key, reflexer_key=reflexer_key))

## Amazon Bedrock

A call carrying a Bedrock API key goes through reflexer, the key passed on with it as any provider's key; a call your library signs (SigV4) goes to Bedrock as before, and is not sent to reflexer.

    # client = boto3.client("bedrock-runtime", region_name=region)
    client = reflexer.boto3.client("bedrock-runtime", region_name=region, reflexer_key=reflexer_key)

    # a client made elsewhere: its botocore client
    reflexer.boto3.through(client, reflexer_key)  # on aiobotocore, once entered: reflexer.aiobotocore.through(client, reflexer_key)

    # client = anthropic.AnthropicBedrock(aws_region=region, api_key=bedrock_key)
    client = reflexer.anthropic_bedrock.AnthropicBedrock(aws_region=region, api_key=bedrock_key, reflexer_key=reflexer_key)

    # litellm.completion(model="bedrock/...", api_key=bedrock_key, messages=messages)
    bedrock_http = reflexer.litellm.client(reflexer_key)  # made once, given to each call: its connections and breaker last
    litellm.completion(model="bedrock/...", api_key=bedrock_key, messages=messages, client=bedrock_http)

boto3 and aiobotocore take the key from `AWS_BEARER_TOKEN_BEDROCK`. Also `AsyncAnthropicBedrock`, `AnthropicBedrockMantle` and `AsyncAnthropicBedrockMantle`; `reflexer.litellm.async_client` for `acompletion`. What is built on a boto3 client takes reflexer's: `ChatBedrockConverse(client=...)` (langchain-aws), `BedrockProvider(bedrock_client=...)` (Pydantic AI); Strands' `BedrockModel` holds its own, `reflexer.boto3.through(model.client, reflexer_key)`. Bedrock's OpenAI and Anthropic routes take the lines above, `base_url` theirs.

One call straight: on boto3 and aiobotocore, `client.converse(..., ReflexerPassThrough=True)`; on any line, the `Reflexer-Pass-Through` header (botocore's: by a `before-sign` handler of yours).

TypeScript:

    import * as bedrock from "@reflexer-ai/sdk/bedrock";

    // client = new BedrockRuntimeClient({ region, token: { token: bedrockKey }, authSchemePreference: ["httpBearerAuth"] })
    client = bedrock.wrap(new BedrockRuntimeClient({ region, token: { token: bedrockKey }, authSchemePreference: ["httpBearerAuth"] }), reflexerKey);

    // chat = new ChatBedrockConverse({ model, client })
    chat = new ChatBedrockConverse({ model, client: bedrock.wrap(client, reflexerKey) });

    // client = new AnthropicBedrock({ awsRegion, apiKey: bedrockKey })
    client = new AnthropicBedrock({ awsRegion, apiKey: bedrockKey, fetch: bedrock.fetch(reflexerKey), middleware: [bedrock.anthropicMiddleware] });

    // model = createAmazonBedrock({ region, apiKey: bedrockKey })(modelId)
    model = wrapLanguageModel({ model: createAmazonBedrock({ region, apiKey: bedrockKey, fetch: bedrock.fetch(reflexerKey) })(modelId), middleware: bedrock.aiMiddleware });

`bedrock.requestHandler(reflexerKey, { handler })` is the handler `wrap` gives AWS JS, for a client that sets its own `requestHandler`. One call straight: AWS JS `client.send(command, { reflexerPassThrough: true })`; the AI SDK `providerOptions: { reflexer: { passThrough: true } }`; or the `Reflexer-Pass-Through` header (AWS JS by a middleware of yours, AnthropicBedrock and the AI SDK in the call's headers). What each line cannot do: SECURITY.md, **Known limits**.

## What reflexer's answer looks like

The answer is your provider's format, unchanged by this SDK. A served answer's `model` ends in `-reflexer`, and its price in USD is at `usage.cost`, where cost tools already read it. Every response carries `Reflexer-Request-Id`, `Reflexer-Answered-By` and `Reflexer-Cost` (nano USD) headers. An answer cut mid-way raises your provider SDK's own error, as a cut from the provider would, with no price on it; reflexer's bill holds the price.

## Settings

- `sample=0.01` (TypeScript: `sample: 0.01`): send a share of the calls to reflexer, the rest straight to the provider.
- One call straight to the provider: `extra_headers={"Reflexer-Pass-Through": "1"}` (TypeScript: `{ headers: { "Reflexer-Pass-Through": "1" } }` as the call's request options). The header never leaves your machine.
- When reflexer fails, calls go straight to the provider for a while, backing off.
- TypeScript, `headersTimeout` (ms) in the `fetch` form's options: how long reflexer's leg waits for its answer to start before the call goes straight; by default undici's own, 300 s.

## Develop

    uv sync --group dev --group test --group frameworks --group bedrock
    uv run python -m unittest discover -s tests -t .
    uv run python tests/acceptance/run.py                     # acceptance: tests/acceptance/README.md
    uv run python -m unittest tests.acceptance.test_controls  # each fault planted in the SDK turns its cases red

    cd typescript && npm ci && npm run build && npm test     # TypeScript: types, gates, tests, each with its planted fault
