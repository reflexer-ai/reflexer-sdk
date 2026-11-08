"""Amazon Bedrock for the suite: its wire as its stand-in answers it, and each Python library a client calls it with, made
and called by its public API, with reflexer's line or without. Every key, credential, model and answer is made up.

A client calls Bedrock with a Bedrock API key (`keyed`, `Authorization: Bearer`) or signs its calls (SigV4) with
credentials of its own. The libraries: `boto3`, `aiobotocore`, and what is built on boto3 (`langchain-aws`'s
ChatBedrockConverse, `strands`'s BedrockModel, `pydantic-ai`'s BedrockConverseModel); `anthropic-bedrock` and
`anthropic-mantle` (anthropic's Bedrock clients); `litellm`; and the shipped lines at Bedrock's compatible routes,
`openai-compat` (`/openai/v1`) and `anthropic-compat` (`/anthropic`), which take a key only.
"""
import asyncio, base64, datetime, importlib.util, json, os, struct, time, zlib

REGION = "us-east-1"
RUNTIME = f"bedrock-runtime.{REGION}.amazonaws.com"
MANTLE = f"bedrock-mantle.{REGION}.api.aws"
NAMES = [RUNTIME, MANTLE]
MODEL = "anthropic.frontier-b-made-up-v1:0"  # made up, of Anthropic's family on Bedrock: LiteLLM's invoke route reads the body's format from it
BEARER = "ABSKbWFkZS11cC1iZWRyb2NrLWtleQ=="  # a Bedrock API key's form, made up
REFUSED = "ABSK-made-up-one-bedrock-refuses"  # another, which Bedrock's stand-in does not take
ACCESS_KEY, SECRET = "AKIDMADEUPMADEUP0001", "made-up-secret-access-key-of-the-suite"  # not of AWS's key form: no scanner takes it for one
EVENT_STREAM = "application/vnd.amazon.eventstream"
ARGUMENT = "ReflexerPassThrough"  # the botocore family's per-call skip, as a client writes it
TEXT = "Hi"
OPERATIONS = ("converse", "converse_stream", "invoke", "invoke_stream", "count_tokens")
STREAMED = {"converse_stream", "invoke_stream"}  # Bedrock's streamed operations, as its wire names them
STREAMED_OPS = STREAMED | {"messages_stream", "chat_stream"}
ENVIRONMENT = {  # every case's: no credential, profile or metadata service of the machine's is ever read
    "AWS_ACCESS_KEY_ID": ACCESS_KEY, "AWS_SECRET_ACCESS_KEY": SECRET, "AWS_DEFAULT_REGION": REGION,
    "AWS_CONFIG_FILE": "/nonexistent/aws-config", "AWS_SHARED_CREDENTIALS_FILE": "/nonexistent/aws-credentials",
    "AWS_EC2_METADATA_DISABLED": "true", "LITELLM_LOCAL_MODEL_COST_MAP": "True"}  # LiteLLM's prices from its own copy, not fetched
AMBIENT = ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION", "AWS_ENDPOINT_URL",
           "AWS_ENDPOINT_URL_BEDROCK_RUNTIME", "AWS_CA_BUNDLE", "AWS_ROLE_ARN", "AWS_WEB_IDENTITY_TOKEN_FILE",
           "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "ANTHROPIC_BEDROCK_MANTLE_BASE_URL")


# ---- the wire, as Bedrock's stand-in answers it

def wire_of(path):
    """Bedrock's operation a path names, or None."""
    for ending, wire in (("/converse-stream", "converse_stream"), ("/converse", "converse"),
                         ("/invoke-with-response-stream", "invoke_stream"), ("/invoke", "invoke"), ("/count-tokens", "count_tokens")):
        if "/model/" in path and path.split("?")[0].endswith(ending):
            return wire
    return None


def messages(text):
    return {"id": "msg_bdrk_made_up", "type": "message", "role": "assistant", "model": "frontier-b", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}], "stop_sequence": None, "usage": {"input_tokens": 3, "output_tokens": 1}}


def body_for(wire, text):
    usage = {"inputTokens": 3, "outputTokens": 1, "totalTokens": 4}
    if wire == "converse":
        return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "stopReason": "end_turn", "usage": usage,
                "metrics": {"latencyMs": 1}}
    if wire == "invoke":
        return messages(text)
    return {"inputTokens": 3}


def frame(headers, payload):
    """One frame of AWS's binary event stream: a prelude (lengths and their CRC32), headers, a payload, the frame's CRC32."""
    head = b"".join(bytes([len(name)]) + name.encode() + b"\x07" + struct.pack(">H", len(value)) + value.encode()
                    for name, value in headers.items())
    prelude = struct.pack(">II", 16 + len(head) + len(payload), len(head))
    message = prelude + struct.pack(">I", zlib.crc32(prelude)) + head + payload
    return message + struct.pack(">I", zlib.crc32(message))


def event(kind, data):
    return frame({":event-type": kind, ":content-type": "application/json", ":message-type": "event"}, json.dumps(data).encode())


def events_for(wire, text):
    """A stream's frames, one each, as Bedrock sends them."""
    if wire == "converse_stream":
        return [event("messageStart", {"role": "assistant"}),
                *[event("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": part}}) for part in (text[:4], text[4:])],
                event("contentBlockStop", {"contentBlockIndex": 0}), event("messageStop", {"stopReason": "end_turn"}),
                event("metadata", {"usage": {"inputTokens": 3, "outputTokens": 1, "totalTokens": 4}, "metrics": {"latencyMs": 1}})]
    steps = [{"type": "message_start", "message": messages("") | {"content": [], "stop_reason": None}},
             {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
             *[{"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": part}} for part in (text[:4], text[4:])],
             {"type": "content_block_stop", "index": 0}, {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}},
             {"type": "message_stop"}]
    return [event("chunk", {"bytes": base64.b64encode(json.dumps(step).encode()).decode()}) for step in steps]


WINDOW = 300.0  # seconds a SigV4 signature holds at Bedrock from the time it says it signed: AWS's five minutes


def refusal(arrival, window=WINDOW):
    """Bedrock's own refusal of a call whose key or signature it does not take, (status, headers, body), in the route's
    format, as Bedrock answers each; None for a call it takes. A signature it takes holds, and its signing time is within
    `window` of its arrival. Its own operations: AWS's error; its compatible routes: their format's, with no AWS error type."""
    auth = arrival.headers.get("authorization") or ""
    holds = auth.startswith("AWS4-HMAC-SHA256 ") and signature_holds(arrival)
    if auth == f"Bearer {BEARER}" or arrival.headers.get("x-api-key") == BEARER or (holds and in_window(arrival, window)):
        return None
    path, mantle = arrival.path.split("?")[0], arrival.host.split(":")[0] == MANTLE
    message = "made-up: Signature expired" if holds else "made-up: the key or signature is not valid"
    if wire_of(path):
        return 403, {"x-amzn-errortype": "InvalidSignatureException" if holds else "AccessDeniedException"}, {"message": message}
    if path.endswith("/chat/completions"):
        return 401, {}, {"error": {"type": "permission_denied_error", "code": "invalid_api_key" if mantle else "access_denied", "message": message}}
    return (401 if mantle else 403), {}, {"type": "error", "error": {"type": "authentication_error" if mantle else "permission_error", "message": message}}


def in_window(arrival, window):
    """Whether a signed call's signing time is within `window` seconds of its arrival, by the clock Bedrock judges it by."""
    signed = datetime.datetime.strptime(arrival.headers.get("x-amz-date", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
    return abs(arrival.wall - signed.timestamp()) <= window


SCOPES = {RUNTIME: (REGION, "bedrock"), MANTLE: (REGION, "bedrock-mantle")}  # each endpoint's signing region and service, as stock signs


def signature_holds(arrival):
    """Whether a SigV4 call checks as Bedrock checks it: its scope the endpoint's own region and service, its signature
    recomputed by botocore's own signer, over the headers it says it signed, at the time it says it signed, with the
    suite's made-up secret."""
    import botocore.auth, botocore.awsrequest, botocore.credentials
    auth = arrival.headers.get("authorization", "")
    if not auth.startswith("AWS4-HMAC-SHA256 "):
        return False
    parts = dict(part.strip().split("=", 1) for part in auth[len("AWS4-HMAC-SHA256 "):].split(","))
    key, _, region, service, _ = parts["Credential"].split("/")
    if key != ACCESS_KEY or (region, service) != SCOPES.get(arrival.host.split(":")[0]):  # Bedrock's own scope, not the one the call names
        return False
    signed = parts["SignedHeaders"].split(";")
    request = botocore.awsrequest.AWSRequest(arrival.method, f"https://{arrival.host}{arrival.path}", data=arrival.body,
                                             headers={name: arrival.headers.get(name, "") for name in signed})
    request.context["timestamp"] = arrival.headers.get("x-amz-date", "")
    signer = botocore.auth.SigV4Auth(botocore.credentials.Credentials(ACCESS_KEY, SECRET), service, region)
    return signer.signature(signer.string_to_sign(request, signer.canonical_request(request)), request) == parts["Signature"]


# ---- the libraries

class Outcome:
    """What the client saw of one call: its text, or its error."""

    def __init__(self, text=None, error=None, wall=0.0):
        self.text, self.error, self.wall = text, error, wall

    def __str__(self):
        if self.error is not None:
            return f"raised {type(self.error).__name__} in {self.wall:.2f}s"
        return f"answered {self.text!r} in {self.wall:.2f}s"


def botocore_config(settings):
    import botocore.config
    return botocore.config.Config(read_timeout=settings.get("timeout") or 60, connect_timeout=settings.get("timeout") or 60,
                                  retries={"total_max_attempts": 1 + settings.get("retries", 0), "mode": "standard"})


def boto3_kwargs(settings):
    """`session_token`: the suite's credentials given with it, explicitly: a session's credentials, once resolved from
    the variables, are kept for every client it makes after."""
    token = {"aws_access_key_id": ACCESS_KEY, "aws_secret_access_key": SECRET, "aws_session_token": settings["session_token"]} if settings.get("session_token") else {}
    return {"region_name": REGION, "config": botocore_config(settings), **token}


def one_call_headers(client, headers):
    """A client's own way to put a header on one botocore call: a `before-sign` handler, there for the call."""
    def add(request, **_):
        for name, value in (headers or {}).items():
            request.headers[name] = value
    client.meta.events.register("before-sign.bedrock-runtime.*", add, unique_id="suite-one-call")
    return lambda: client.meta.events.unregister("before-sign.bedrock-runtime.*", unique_id="suite-one-call")


def converse_text(answer):
    return answer["output"]["message"]["content"][0]["text"]


def delta_text(data):
    return data.get("delta", {}).get("text", "") if data.get("type") == "content_block_delta" else ""


def invoke_body(extra):
    return json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 8, "messages": [{"role": "user", "content": TEXT}]}
                      | (extra or {})).encode()


class Lib:
    """A library: `make(key, keyed, settings)` its client, through reflexer when `key` is given; `call(client, op, headers,
    args, extra)` one call by its public method, its text (a coroutine, async). `args`: the call's own arguments."""
    name, ops, is_async, botocore = "", (), False, False

    def call_sync(self, client, op, headers, args, extra):
        raise NotImplementedError


class Boto3(Lib):
    name, ops, botocore = "boto3", OPERATIONS, True

    def make(self, key, keyed, settings):
        import boto3, reflexer.boto3
        return (reflexer.boto3.client("bedrock-runtime", **boto3_kwargs(settings), reflexer_key=key, sample=settings.get("share", 1.0)) if key
                else boto3.client("bedrock-runtime", **boto3_kwargs(settings)))

    def call(self, client, op, headers=None, args=None, extra=None):
        undo, args = one_call_headers(client, headers), args or {}
        try:
            if op == "converse":
                return converse_text(client.converse(modelId=MODEL, messages=[{"role": "user", "content": [{"text": TEXT}]}], **args))
            if op == "converse_stream":
                out = client.converse_stream(modelId=MODEL, messages=[{"role": "user", "content": [{"text": TEXT}]}], **args)
                return "".join(e["contentBlockDelta"]["delta"]["text"] for e in out["stream"] if "contentBlockDelta" in e)
            if op == "invoke":
                return json.loads(client.invoke_model(modelId=MODEL, body=invoke_body(extra), **args)["body"].read())["content"][0]["text"]
            if op == "invoke_stream":
                out = client.invoke_model_with_response_stream(modelId=MODEL, body=invoke_body(extra), **args)
                return "".join(delta_text(json.loads(e["chunk"]["bytes"])) for e in out["body"])
            out = client.count_tokens(modelId=MODEL, input={"converse": {"messages": [{"role": "user", "content": [{"text": TEXT}]}]}}, **args)
            return f"tokens {out['inputTokens']}"
        finally:
            undo()


class Aiobotocore(Boto3):
    name, is_async = "aiobotocore", True

    async def make(self, key, keyed, settings):
        import aiobotocore.session, reflexer.aiobotocore
        client = await aiobotocore.session.get_session().create_client("bedrock-runtime", **boto3_kwargs(settings)).__aenter__()
        return reflexer.aiobotocore.through(client, key, sample=settings.get("share", 1.0)) if key else client

    async def call(self, client, op, headers=None, args=None, extra=None):
        undo, args = one_call_headers(client, headers), args or {}
        message = [{"role": "user", "content": [{"text": TEXT}]}]
        try:
            if op == "converse":
                return converse_text(await client.converse(modelId=MODEL, messages=message, **args))
            if op == "converse_stream":
                out = await client.converse_stream(modelId=MODEL, messages=message, **args)
                return "".join([e["contentBlockDelta"]["delta"]["text"] async for e in out["stream"] if "contentBlockDelta" in e])
            if op == "invoke":
                out = await client.invoke_model(modelId=MODEL, body=invoke_body(extra), **args)
                return json.loads(await out["body"].read())["content"][0]["text"]
            if op == "invoke_stream":
                out = await client.invoke_model_with_response_stream(modelId=MODEL, body=invoke_body(extra), **args)
                return "".join([delta_text(json.loads(e["chunk"]["bytes"])) async for e in out["body"]])
            out = await client.count_tokens(modelId=MODEL, input={"converse": {"messages": message}}, **args)
            return f"tokens {out['inputTokens']}"
        finally:
            undo()


def text_of_message(message):
    content = message.content
    return content if isinstance(content, str) else "".join(part.get("text", "") for part in content if isinstance(part, dict))


class LangchainAws(Lib):
    name, ops, botocore = "langchain-aws", ("converse", "converse_stream"), True

    def make(self, key, keyed, settings):
        from langchain_aws import ChatBedrockConverse
        return ChatBedrockConverse(model=MODEL, region_name=REGION, max_tokens=8, client=Boto3().make(key, keyed, settings))

    def call(self, model, op, headers=None, args=None, extra=None):
        undo = one_call_headers(model.client, headers)
        try:
            if op == "converse":
                return text_of_message(model.invoke(TEXT))
            return "".join(text_of_message(chunk) for chunk in model.stream(TEXT))
        finally:
            undo()


class Strands(Lib):
    """Strands' BedrockModel, its own client inside: reflexer's line wires the botocore client it holds."""
    name, ops, botocore = "strands", ("converse", "converse_stream"), True

    def make(self, key, keyed, settings):
        import reflexer.boto3
        from strands.models import BedrockModel
        model = BedrockModel(model_id=MODEL, region_name=REGION, boto_client_config=botocore_config(settings), streaming=False,
                             max_tokens=8, **({"api_key": settings.get("bedrock_key", BEARER)} if keyed else {}))
        if key:
            reflexer.boto3.through(model.client, key, sample=settings.get("share", 1.0))
        return model

    def call(self, model, op, headers=None, args=None, extra=None):
        from strands import Agent
        model.update_config(streaming=op == "converse_stream")
        undo = one_call_headers(model.client, headers)
        try:
            return str(Agent(model=model, callback_handler=None)(TEXT)).strip()
        finally:
            undo()


class PydanticAi(Lib):
    name, ops, botocore = "pydantic-ai", ("converse", "converse_stream"), True

    def make(self, key, keyed, settings):
        if importlib.util.find_spec("pydantic_ai") is None:  # its own group, as for the shipped lines: its floors are above ours
            from . import Cannot
            raise Cannot("pydantic-ai is not installed here: uv sync --group frameworks")
        from pydantic_ai.models.bedrock import BedrockConverseModel
        from pydantic_ai.providers.bedrock import BedrockProvider
        return BedrockConverseModel(MODEL, provider=BedrockProvider(bedrock_client=Boto3().make(key, keyed, settings)))

    def call(self, model, op, headers=None, args=None, extra=None):
        from pydantic_ai import Agent
        undo = one_call_headers(model.client, headers)
        try:
            if op == "converse":
                return Agent(model).run_sync(TEXT).output

            async def streamed():
                async with Agent(model).run_stream(TEXT) as result:
                    return "".join([part async for part in result.stream_text(delta=True)])
            return asyncio.run(streamed())
        finally:
            undo()


def without_litellms_line():
    """LiteLLM as stock in this process: what reflexer's line set, undone, and the clients LiteLLM made under it dropped."""
    import litellm
    from litellm.llms.custom_httpx.http_handler import HTTPHandler
    for name in ("client_session", "aclient_session", "sync_transport"):
        setattr(litellm, name, getattr(getattr(litellm, name, None), "reflexer_own", getattr(litellm, name, None)))
    litellm.callbacks[:] = [each for each in litellm.callbacks if type(each).__module__ != "reflexer.litellm"]
    litellm.in_memory_llm_clients_cache.flush_cache()
    litellm.module_level_client = HTTPHandler(timeout=litellm.request_timeout)


class Litellm(Lib):
    """LiteLLM's Bedrock routes: a call's arguments are its client; reflexer's line, `reflexer.litellm.through`, is the
    process's, so a stock client made after it undoes it."""
    name, ops = "litellm", ("converse", "converse_stream", "invoke", "invoke_stream")

    def make(self, key, keyed, settings):
        import reflexer.litellm
        made = {"aws_region_name": REGION, "num_retries": 0, "timeout": settings.get("timeout") or 60}
        made |= {"api_key": settings.get("bedrock_key", BEARER)} if keyed else {"aws_access_key_id": ACCESS_KEY, "aws_secret_access_key": SECRET}
        if key:
            reflexer.litellm.through(key, sample=settings.get("share", 1.0))
        else:
            without_litellms_line()
        return made

    def call(self, made, op, headers=None, args=None, extra=None):
        import litellm
        route = "converse" if op.startswith("converse") else "invoke"
        more = ({"stream": True} if op in STREAMED_OPS else {}) | ({"extra_headers": headers} if headers else {})
        out = litellm.completion(model=f"bedrock/{route}/{MODEL}", messages=[{"role": "user", "content": TEXT}], max_tokens=8,
                                 **made, **more, **(extra or {}))
        if op in STREAMED_OPS:
            return "".join((chunk.choices[0].delta.content or "") for chunk in out if chunk.choices)
        return out.choices[0].message.content


class AnthropicBedrock(Lib):
    name, ops = "anthropic-bedrock", ("invoke", "invoke_stream")

    def classes(self):
        import anthropic, reflexer.anthropic_bedrock
        return anthropic.AnthropicBedrock, reflexer.anthropic_bedrock.AnthropicBedrock

    def make(self, key, keyed, settings):
        stock, line = self.classes()
        config = {"aws_region": REGION, "max_retries": settings.get("retries", 0), "timeout": settings.get("timeout") or 60}
        config |= {"api_key": settings.get("bedrock_key", BEARER)} if keyed else {"aws_access_key": ACCESS_KEY, "aws_secret_key": SECRET}
        config |= {"aws_session_token": settings["session_token"]} if settings.get("session_token") and not keyed else {}
        return line(**config, reflexer_key=key, sample=settings.get("share", 1.0)) if key else stock(**config)

    def call(self, client, op, headers=None, args=None, extra=None):
        more = ({"extra_headers": headers} if headers else {}) | ({"extra_body": extra} if extra else {})
        made = dict(model=MODEL, max_tokens=8, messages=[{"role": "user", "content": TEXT}], **more)
        if op in STREAMED_OPS:
            return "".join(getattr(e.delta, "text", "") or "" for e in client.messages.create(stream=True, **made) if e.type == "content_block_delta")
        return client.messages.create(**made).content[0].text


class AnthropicMantle(AnthropicBedrock):
    name, ops = "anthropic-mantle", ("messages", "messages_stream")

    def classes(self):
        import anthropic, reflexer.anthropic_bedrock
        return anthropic.AnthropicBedrockMantle, reflexer.anthropic_bedrock.AnthropicBedrockMantle


class AnthropicCompat(AnthropicBedrock):
    """Anthropic's own SDK at Bedrock's `/anthropic`, a Bedrock API key as its key: the shipped line."""
    name, ops = "anthropic-compat", ("messages", "messages_stream")

    def make(self, key, keyed, settings):
        import anthropic, reflexer.anthropic
        config = {"base_url": f"https://{RUNTIME}/anthropic", "api_key": settings.get("bedrock_key", BEARER), "max_retries": settings.get("retries", 0),
                  "timeout": settings.get("timeout") or 60}
        return reflexer.anthropic.Anthropic(**config, reflexer_key=key, sample=settings.get("share", 1.0)) if key else anthropic.Anthropic(**config)


class OpenaiCompat(Lib):
    """The openai SDK at Bedrock's `/openai/v1`, a Bedrock API key as its key: the shipped line."""
    name, ops = "openai-compat", ("chat", "chat_stream")

    def make(self, key, keyed, settings):
        import openai, reflexer.openai
        config = {"base_url": f"https://{RUNTIME}/openai/v1", "api_key": settings.get("bedrock_key", BEARER), "max_retries": settings.get("retries", 0),
                  "timeout": settings.get("timeout") or 60}
        return reflexer.openai.OpenAI(**config, reflexer_key=key, sample=settings.get("share", 1.0)) if key else openai.OpenAI(**config)

    def call(self, client, op, headers=None, args=None, extra=None):
        more = ({"extra_headers": headers} if headers else {}) | ({"extra_body": extra} if extra else {})
        made = dict(model=MODEL, messages=[{"role": "user", "content": TEXT}], **more)
        if op in STREAMED_OPS:
            return "".join((c.choices[0].delta.content or "") for c in client.chat.completions.create(stream=True, **made) if c.choices)
        return client.chat.completions.create(**made).choices[0].message.content


LIBS = {lib.name: lib for lib in (Boto3(), Aiobotocore(), LangchainAws(), Strands(), PydanticAi(), Litellm(), AnthropicBedrock(),
                                   AnthropicMantle(), AnthropicCompat(), OpenaiCompat())}
BOTOCORE = tuple(name for name, lib in LIBS.items() if lib.botocore)
SIGNING = tuple(name for name in LIBS if not name.endswith("-compat"))  # those that can sign a call, as well as carry a key
COLUMNS = tuple(LIBS)



class Calls:
    """One case's Bedrock library: its clients made, by reflexer's line (`lines.bedrock_client`) or stock, and called, in
    one event loop of the case's own for an async library."""

    def __init__(self, t):
        self.t, self.lib = t, LIBS[t.sdk]
        self.loop, self.made = asyncio.new_event_loop() if self.lib.is_async else None, []

    def run(self, made):
        return self.loop.run_until_complete(made) if self.loop else made

    def client(self, line=True, keyed=True, **settings):
        """`keyed`: a Bedrock API key, which botocore takes from its variable as a client is made; else the suite's credentials."""
        if keyed and self.lib.botocore and self.lib.name != "strands":
            self.t.env(AWS_BEARER_TOKEN_BEDROCK=settings.get("bedrock_key", BEARER))
        else:
            os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
        made = self.t.lines.bedrock_client(self.t.world, self.t.sdk, keyed, **settings) if line else self.lib.make(None, keyed, settings)
        made = self.run(made)
        if self.loop:
            self.made.append(made)
        return made

    def close(self):
        """An async library's clients exited, and their loop closed: what a case's process leaves to its end, a test in a
        shared process does here."""
        for made in self.made:
            self.run(made.__aexit__(None, None, None))
        if self.loop:
            self.loop.close()

    def call(self, client, op=None, headers=None, args=None, extra=None):
        """One call, `op` the library's first by default: what the client saw, kept as the case's last."""
        from . import Cannot, Fail
        began = time.monotonic()
        try:
            outcome = Outcome(text=self.run(self.lib.call(client, op or self.lib.ops[0], headers, args, extra)), wall=time.monotonic() - began)
        except (Cannot, Fail):
            raise
        except Exception as error:
            outcome = Outcome(error=error, wall=time.monotonic() - began)
        self.t.last = outcome
        return outcome
