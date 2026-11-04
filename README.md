# reflexer

Reflexer's SDK for Python. It sends a client's LLM calls through reflexer, on the provider SDK the client already uses. A call reflexer does not answer, or cannot be reached for, goes to the provider as before.

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

## What reflexer's answer looks like

The answer is your provider's format, unchanged by this SDK. A served answer's `model` ends in `-reflexer`, and its price in USD is at `usage.cost`, where cost tools already read it. Every response carries `Reflexer-Request-Id`, `Reflexer-Answered-By` and `Reflexer-Cost` (nano USD) headers.

## Settings

- `sample=0.01`: send a share of the calls to reflexer, the rest straight to the provider.
- One call straight to the provider: `extra_headers={"Reflexer-Pass-Through": "1"}`. The header never leaves your machine.
- When reflexer fails, calls go straight to the provider for a while, backing off.

## Develop

    uv sync --group dev --group test
    uv run python -m unittest discover -s tests -t .
