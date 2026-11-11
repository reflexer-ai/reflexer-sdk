"""One run against a real reflexer endpoint, through each provider SDK: what the stand-ins cannot show.

    REFLEXER_BASE=https://... REFLEXER_KEY=rfx1_... OPENAI_API_KEY=... python tests/live/check.py [openai anthropic gemini replay]

Each SDK named, with its provider key in the environment (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) and
optionally its model (`OPENAI_MODEL`, ...) and base URL (`OPENAI_BASE_URL`, ... : a provider stand-in), makes one call.
It prints who answered, the model, the price and the request id, and fails on what breaks the SDK's wire: a served answer
with no `-reflexer` model or no price, or a call that reached nobody. Never run by CI: it needs the endpoint and keys."""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import reflexer

MODELS = {"openai": "gpt-4o-mini", "anthropic": "claude-haiku-4-5", "gemini": "gemini-2.5-flash"}  # defaults, any may be given


def env(name, default=None):
    value = os.environ.get(name, default)
    if value is None:
        raise SystemExit(f"set {name}")
    return value


REPLAY = {"id": "made-up", "object": "chat.completion", "created": 1, "model": "made-up",
          "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "from the replay"}}],
          "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


def replayed(key, base):
    """A request carrying `replay_response` (OpenAI's format): answered from the field, never by the provider."""
    import reflexer.openai
    client = reflexer.openai.OpenAI(api_key=env("OPENAI_API_KEY"), reflexer_key=key, reflexer_base=base, max_retries=0)
    raw = client.chat.completions.with_raw_response.create(model=env("OPENAI_MODEL", MODELS["openai"]), messages=[
        {"role": "user", "content": "Say hi"}], extra_body={"replay_response": REPLAY})
    return raw.headers, raw.parse().choices[0].message.content


def replayed_stream(key, base):
    """The same, streamed: the field a stream's text, whose events the SDK reads as the provider's."""
    import json
    import reflexer.openai
    chunk = REPLAY | {"object": "chat.completion.chunk", "choices": [{"index": 0, "finish_reason": None, "delta": {
        "role": "assistant", "content": "from the replay"}}]}
    client = reflexer.openai.OpenAI(api_key=env("OPENAI_API_KEY"), reflexer_key=key, reflexer_base=base, max_retries=0)
    raw = client.chat.completions.with_raw_response.create(model=env("OPENAI_MODEL", MODELS["openai"]), stream=True, messages=[
        {"role": "user", "content": "Say hi"}], extra_body={"replay_response": f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n"})
    return raw.headers, "".join(event.choices[0].delta.content or "" for event in raw.parse() if event.choices)


def call(sdk, key, base):
    model = env(f"{sdk.upper()}_MODEL", MODELS[sdk])
    provider_key, provider_base = env(f"{sdk.upper()}_API_KEY"), os.environ.get(f"{sdk.upper()}_BASE_URL")
    on = dict(reflexer_key=key, reflexer_base=base)
    if sdk == "openai":
        import reflexer.openai
        client = reflexer.openai.OpenAI(api_key=provider_key, base_url=provider_base, **on)
        raw = client.chat.completions.with_raw_response.create(model=model, messages=[{"role": "user", "content": "Say hi"}])
        made = raw.parse()
        return raw.headers, made.model, getattr(made.usage, "cost", None)
    if sdk == "anthropic":
        import reflexer.anthropic
        client = reflexer.anthropic.Anthropic(api_key=provider_key, base_url=provider_base, **on)
        raw = client.messages.with_raw_response.create(model=model, max_tokens=16, messages=[{"role": "user", "content": "Say hi"}])
        made = raw.parse()
        return raw.headers, made.model, getattr(made.usage, "cost", None)
    import reflexer.gemini
    options = {"base_url": provider_base} if provider_base else None
    made = reflexer.gemini.Client(api_key=provider_key, http_options=options, **on).models.generate_content(model=model, contents="Say hi")
    return made.sdk_http_response.headers, made.model_version, None  # gemini's object holds no price: its headers do


def judge(headers, model, cost):
    """What breaks the wire, as text; empty when it holds."""
    answered = headers.get("reflexer-answered-by")
    if answered == "reflexer":
        return [problem for problem, broken in (
            (f"a served answer's model is {model}, not ending in -reflexer", not str(model).endswith("-reflexer")),
            ("a served answer with no Reflexer-Cost-Nano-Usd", headers.get("reflexer-cost-nano-usd") is None),
            ("a served answer with no request id", headers.get("reflexer-request-id") is None)) if broken]
    if answered == "provider":
        return ["a pass through with a price written by reflexer"] if cost is not None and headers.get("reflexer-cost-nano-usd") not in (None, "0") else []
    return []  # no header of reflexer's: the call went straight, which the SDK allows


def provider_refusal(error):
    """A provider's own error, passed through untouched: its headers, read as an answer's would be."""
    response = getattr(error, "response", None)
    if response is None:
        raise error
    return response.headers, f"(the provider's {response.status_code})", None


def replay_broken(headers, text):
    """A replay is answered by reflexer, or from its field: never by anyone else."""
    by = headers.get("reflexer-answered-by")
    return by not in (None, "reflexer") or (by is None and text != "from the replay")


def main(sdks):
    key, base, failed = env("REFLEXER_KEY"), env("REFLEXER_BASE"), False  # no default: a key goes to the endpoint named
    if "replay" in sdks:
        sdks = [sdk for sdk in sdks if sdk != "replay"]
        for way, replay in (("replay", replayed), ("replay, streamed", replayed_stream)):
            headers, text = replay(key, base)
            print(f"{way}: answered by {headers.get('reflexer-answered-by', 'its field')}, text {text!r}, "
                  f"Reflexer-Cost-Nano-Usd {headers.get('reflexer-cost-nano-usd')}, id {headers.get('reflexer-request-id')}")
            if replay_broken(headers, text):
                print("  broken: a replay answered by someone else than reflexer or its field", file=sys.stderr)
                failed = True
    for sdk in sdks:
        try:
            headers, model, cost = call(sdk, key, base)
        except Exception as error:  # a made-up provider key: the provider's own refusal is a sound pass through
            headers, model, cost = provider_refusal(error)
        print(f"{sdk}: answered by {headers.get('reflexer-answered-by', 'the provider, straight')}, model {model}, "
              f"Reflexer-Cost-Nano-Usd {headers.get('reflexer-cost-nano-usd')}, usage.cost {cost}, id {headers.get('reflexer-request-id')}")
        for problem in judge(headers, model, cost):
            print(f"  broken: {problem}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or list(MODELS)))
