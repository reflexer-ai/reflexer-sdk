# Acceptance

What the SDK must do, checked through the real provider SDKs over real sockets and real TLS, with no mock transport. Offline: stand-ins play reflexer and the providers on this machine, and nothing here can reach a real one. Every key, model and answer is made up.

## Run

From the repository's root:

    uv run --locked python tests/acceptance/run.py                       # a table, about a minute
    uv run --locked python tests/acceptance/run.py --only stall --sdk openai
    uv run --locked python -m unittest tests.acceptance.test_controls    # the controls, a few minutes

`pass`: held. `fail`: broken; the run exits 1. `cannot`: the case cannot apply, and says what the client sees. `open`: a known gap, failing on what is not built yet; reported, not failing the run. `-`: that SDK has no such call. `--json PATH` also writes what each cell saw and measured; the outage traces' phases are under `data`.

## The files

- `cases.py`: each case, run once per SDK it names: `openai`, `azure`, `anthropic`, `gemini` (async: `client.aio`), and `acme`, a made-up provider (`harness/acme.py`) that shows what adding one takes.
- `cases_bedrock.py`: Amazon Bedrock's, once per library a client calls it with (`harness/bedrock.py`: boto3, aiobotocore, langchain-aws, Strands, Pydantic AI, LiteLLM, anthropic's Bedrock and Mantle clients, and the shipped lines at Bedrock's OpenAI and Anthropic routes), with a Bedrock API key or signing (SigV4). Bedrock's stand-in answers its JSON and its binary event stream, and refuses a signature as Bedrock does: one botocore's own signer does not recompute, or whose signing time is out of its window at arrival (`window`, five minutes, shortened by the cases that outlast it).
- `lines.py`: the SDK under test, each client made by the one line a client writes.
- `harness/`: the stand-ins (`standins.py`, its modes at its top), the resolver, the certificates.
- `faults.py` and `test_controls.py`: the controls. Each fault breaks one thing the SDK promises; the test checks each turns its cases red, and that every case but those it lists, with their reasons, is turned red by some fault. So a green run means something. Its `CONDITIONS` are a slow machine's moments, planted in the stand-ins (`run.py --condition NAME`): a stand-in slow to notice a client left, a stall on reflexer's return after an outage, the case's process frozen where each case judged by real time breaks (`FREEZES`); the test checks the cases they touch stay green, and that each condition came about. So a red run means something too.

## What a case gets

One process per case and SDK, forked after the SDKs are imported, killed at its limit with all it started: its patches and environment die with it, and a hang or a crash fails that case only. Nothing of the caller's environment reaches it (`AMBIENT` in `run.py`).

`t.reflexer`, `t.provider`, `t.elsewhere` (a redirect's target), `t.runner` (plain http, as a model runner on the client's machine) and `t.proxy`. Each stand-in records what reached it in `.seen`: host, path, headers, body. After every case the suite checks that the reflexer key reached no one but reflexer, that a Bedrock API key or a signature reached only reflexer or Bedrock, and the client's AWS secret no one, and that the header skipping reflexer for a call never left the machine. No credential, profile or metadata service of the machine's is read: each case's AWS settings are made up (`harness/bedrock.py`, `ENVIRONMENT`).

`harness/resolver.py` makes `api.reflexer.ai`, `api.openai.com`, `api.anthropic.com`, `generativelanguage.googleapis.com`, `openrouter.ai`, `api.groq.com`, `made-up.openai.azure.com`, `api.acme.example`, Bedrock's `bedrock-runtime.us-east-1.amazonaws.com` and `bedrock-mantle.us-east-1.api.aws`, `elsewhere.example` and `runner.example` (plain http) reach their stand-ins; any other name fails to resolve, and any address off this machine refuses. The certificate authority is made per run and trusted through `SSL_CERT_FILE`, and botocore's `AWS_CA_BUNDLE`.

## Limits

- Real time: bounds carry a margin for a busy machine. A case marked `steady` does not judge a try during which its process went unscheduled past `harness.STALL` (a `Ticker` thread sees it): it tries again, afresh, each try in its own limit, and fails when every try stalled (`run.py --tries 1` judges its first). The outage traces try again when a call paid the timeout in an up phase. The breaker's cap, minutes of failures away, is checked on a clock of its own in `tests/test_logic.py`.
- At the 1% share a trace reaches reflexer a few times: a direction, not a rate.
- A dead phase in a trace accepts and resets, so its attempts can be counted; `dead` refuses, and counts nothing.
