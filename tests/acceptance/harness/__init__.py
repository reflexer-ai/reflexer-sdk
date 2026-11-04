"""What a case calls: its world of stand-ins, the stock SDKs, one call through an SDK's public method, what reflexer's
answer says. A case: `cases.py`."""
import asyncio, base64, hashlib, logging, os, random, threading, time, uuid

from . import resolver, standins
from .standins import STRAIGHT_TEXT, SERVED_TEXT, Proxy, Standin

MODEL = {"openai": "frontier-x", "azure": "frontier-d", "anthropic": "frontier-y", "gemini": "frontier-z", "acme": "frontier-a"}
MESSAGES = [{"role": "user", "content": "Hi"}]
PROVIDER_KEY = {"openai": "sk-made-up", "azure": "az-made-up", "anthropic": "sk-ant-made-up", "gemini": "ai-made-up", "acme": "acme-made-up"}
AZURE_ENDPOINT = "https://made-up.openai.azure.com"
AZURE_VERSION = "2024-10-21"
PASS_THROUGH = "Reflexer-Pass-Through"
REFLEXER_NAMES = ["api.reflexer.ai"]
PROVIDER_NAMES = ["api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com", "openrouter.ai",
                  "api.groq.com", "made-up.openai.azure.com", "api.acme.example"]
ELSEWHERE_NAMES = ["elsewhere.example"]
RUNNER_NAMES = ["runner.example"]
NAMES = REFLEXER_NAMES + PROVIDER_NAMES + ELSEWHERE_NAMES + RUNNER_NAMES


class Cannot(Exception):
    """A case that cannot apply; its text says what the client sees."""


class Fail(Exception):
    """A case's check failed; its text says what the client saw."""


def make_key(client="aaaaakq", secret="a" * 52):
    """A made-up key of reflexer's form, computed here apart from the SDK's own check."""
    body = f"rfx1_{client}_{secret}"
    check = base64.b32encode(hashlib.sha256(body.encode()).digest()[:4]).decode().lower().rstrip("=")
    return f"{body}_{check}"


class World:
    """The stand-ins of one case, reached at their real-looking names by the resolver."""

    def __init__(self, contexts):
        good, bad = contexts
        self.reflexer = Standin("reflexer", good, bad, is_reflexer=True)
        self.provider = Standin("provider", good, bad)
        self.elsewhere = Standin("elsewhere", good, bad)
        self.runner = Standin("runner")  # plain http, as a model runner on the client's own machine
        self.proxy = Proxy()
        self.key, self.share = make_key(), 1.0
        resolver.hosts.clear()
        for names, standin in ((REFLEXER_NAMES, self.reflexer), (PROVIDER_NAMES, self.provider),
                               (ELSEWHERE_NAMES, self.elsewhere), (RUNNER_NAMES, self.runner)):
            for name in names:
                resolver.add(name, standin.port)

    def stock(self, sdk, is_async=False, **config):
        return stock_class(sdk, is_async)(**config)


def stock_class(sdk, is_async=False):
    if sdk == "openai":
        import openai
        return openai.AsyncOpenAI if is_async else openai.OpenAI
    if sdk == "azure":
        import openai
        return openai.AsyncAzureOpenAI if is_async else openai.AzureOpenAI
    if sdk == "anthropic":
        import anthropic
        return anthropic.AsyncAnthropic if is_async else anthropic.Anthropic
    if sdk == "gemini":
        from google import genai
        return genai.Client
    if sdk == "acme":
        from . import acme
        return acme.Acme
    raise ValueError(sdk)


def own_http_client(sdk, is_async, http):
    """The HTTP client a client hands the SDK, with its own settings."""
    if sdk in ("openai", "azure"):
        import openai
        return (openai.DefaultAsyncHttpxClient if is_async else openai.DefaultHttpxClient)(**http)
    if sdk == "anthropic":
        import anthropic
        return (anthropic.DefaultAsyncHttpxClient if is_async else anthropic.DefaultHttpxClient)(**http)
    import httpx
    return (httpx.AsyncClient if is_async else httpx.Client)(**http)


def config_for(sdk, is_async=False, http=None, base_url=None, retries=0, gemini_options=None, default_headers=None):
    """What a client passes the stock class. `retries=None`: the SDK's default."""
    config = {"api_key": PROVIDER_KEY[sdk]} | ({"default_headers": default_headers} if default_headers else {})
    made = own_http_client(sdk, is_async, http) if http is not None else None
    if sdk == "gemini":
        options = dict(gemini_options or {})
        if base_url:
            options["base_url"] = base_url
        if made is not None:
            options["httpx_async_client" if is_async else "httpx_client"] = made
        if options:
            config["http_options"] = options
        return config
    if sdk == "acme":
        if base_url:
            config["base_url"] = base_url
        if made is not None:
            config["http_client"] = made
        return config
    if retries is not None:
        config["max_retries"] = retries
    if base_url:
        config["base_url"] = base_url
    if made is not None:
        config["http_client"] = made
    if sdk == "azure":
        config |= {"azure_endpoint": AZURE_ENDPOINT, "api_version": AZURE_VERSION}
    return config


def per_call(sdk, headers=None, timeout=None):
    """What one call adds, in the SDK's own form."""
    if sdk == "gemini":
        options = {}
        if headers:
            options["headers"] = headers
        if timeout is not None:
            options["timeout"] = int(timeout * 1000)
        return {"config": {"http_options": options}} if options else {}
    extra = {}
    if headers:
        extra["extra_headers"] = headers
    if timeout is not None:
        extra["timeout"] = timeout
    return extra


def request(sdk, client, is_async, stream, extra):
    """One message call through the SDK's public method: its value, or its coroutine when async."""
    if sdk in ("openai", "azure"):
        more = {"stream": True} if stream else {}
        return client.chat.completions.create(model=MODEL[sdk], messages=MESSAGES, **more, **extra)
    if sdk == "anthropic":
        more = {"stream": True} if stream else {}
        return client.messages.create(model=MODEL[sdk], max_tokens=8, messages=MESSAGES, **more, **extra)
    if sdk == "gemini":
        models = client.aio.models if is_async else client.models
        method = models.generate_content_stream if stream else models.generate_content
        return method(model=MODEL[sdk], contents="Hi", **extra)
    if sdk == "acme":
        return client.ask(MODEL[sdk], "Hi", **extra)
    raise ValueError(sdk)


def text_of(sdk, answer):
    if sdk in ("openai", "azure"):
        return answer.choices[0].message.content
    if sdk == "anthropic":
        return answer.content[0].text
    return answer.text


def chunk_text(sdk, chunk):
    if sdk in ("openai", "azure"):
        return (chunk.choices[0].delta.content or "") if chunk.choices else ""
    if sdk == "anthropic":
        delta = getattr(chunk, "delta", None)
        return getattr(delta, "text", "") or ""
    return chunk.text or ""


def usage_cost(sdk, answer):
    """The USD at the usage's `cost` on an answer, where cost tools read it, or None."""
    usage = getattr(answer, "usage_metadata" if sdk == "gemini" else "usage", None)
    return getattr(usage, "cost", None)


def fields(sdk, answer):
    """What a served answer says of reflexer, read where a client's tools read it: {"request_id", "answered_by", "cost"},
    or None. On gemini, whose objects hold no price: the headers its object keeps."""
    if sdk == "gemini":
        headers = getattr(getattr(answer, "sdk_http_response", None), "headers", None) or {}
        return {"request_id": headers["reflexer-request-id"], "answered_by": "reflexer", "cost": int(headers["reflexer-cost"])} \
            if headers.get("reflexer-answered-by") == "reflexer" else None
    cost = usage_cost(sdk, answer)
    served = str(getattr(answer, "id", "")).startswith("rfx-") or (sdk == "acme" and cost is not None)
    if not served or cost is None:
        return None
    request_id = standins.REQUEST_ID if sdk == "acme" else str(uuid.UUID(answer.id.removeprefix("rfx-")))
    return {"request_id": request_id, "answered_by": "reflexer", "cost": round(cost * 10**9)}


class Outcome:
    """What the client saw of one call."""

    def __init__(self, sdk, answer=None, error=None, wall=0.0, chunks=None):
        self.sdk, self.answer, self.error, self.wall, self.chunks = sdk, answer, error, wall, chunks
        self.text = None
        if error is None:
            try:
                self.text = "".join(chunk_text(sdk, c) for c, _ in chunks) if chunks is not None else text_of(sdk, answer)
            except Exception as failure:
                self.text = f"<unreadable: {type(failure).__name__}>"

    def __str__(self):
        if self.error is not None:
            return f"raised {type(self.error).__name__} in {self.wall:.2f}s"
        return f"answered {self.text!r} in {self.wall:.2f}s"


class Collected(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(f"{record.name} {record.levelname} {record.getMessage()}")


class Test:
    """One case on one SDK: its world, the SDK under test (`lines`), what it saw. `saw` is built from the last call
    unless a case says more."""

    def __init__(self, lines, sdk, world):
        self.lines, self.sdk, self.world = lines, sdk, world
        self.reflexer, self.provider, self.elsewhere, self.runner, self.proxy = (
            world.reflexer, world.provider, world.elsewhere, world.runner, world.proxy)
        self.notes, self.data, self.last, self.local_flags = [], {}, None, set()
        self.logs = Collected()
        logging.getLogger().addHandler(self.logs)

    # Setting up

    def env(self, **values):
        os.environ.update(values)

    def client(self, is_async=False, sdk=None, **options):
        """The SDK under test's client, given what a client passes the stock class (`config_for`)."""
        sdk = sdk or self.sdk
        return self.lines.client(self.world, sdk, is_async, **config_for(sdk, is_async, **options))

    def stock(self, is_async=False, **options):
        return stock_class(self.sdk, is_async)(**config_for(self.sdk, is_async, **options))

    # Calling

    def ask(self, client, headers=None, timeout=None):
        began = time.monotonic()
        try:
            answer = request(self.sdk, client, False, False, per_call(self.sdk, headers, timeout))
            self.last = Outcome(self.sdk, answer=answer, wall=time.monotonic() - began)
        except (Fail, Cannot):
            raise
        except Exception as error:
            self.last = Outcome(self.sdk, error=error, wall=time.monotonic() - began)
        return self.last

    async def ask_async(self, client, headers=None, timeout=None):
        began = time.monotonic()
        try:
            answer = await request(self.sdk, client, True, False, per_call(self.sdk, headers, timeout))
            self.last = Outcome(self.sdk, answer=answer, wall=time.monotonic() - began)
        except (Fail, Cannot):
            raise
        except Exception as error:
            self.last = Outcome(self.sdk, error=error, wall=time.monotonic() - began)
        return self.last

    def skip_headers(self):
        """The header that skips reflexer for one call; it must never leave this machine."""
        self.local_flags.add(PASS_THROUGH.lower())
        return {PASS_THROUGH: "1"}

    def skip(self, client, timeout=None):
        return self.ask(client, headers=self.skip_headers(), timeout=timeout)

    async def skip_async(self, client):
        return await self.ask_async(client, headers=self.skip_headers())

    def stream(self, client, headers=None):
        began, chunks = time.monotonic(), []
        try:
            for chunk in request(self.sdk, client, False, True, per_call(self.sdk, headers)):
                chunks.append((chunk, time.monotonic() - began))
            self.last = Outcome(self.sdk, wall=time.monotonic() - began, chunks=chunks)
        except (Fail, Cannot):
            raise
        except Exception as error:
            self.last = Outcome(self.sdk, error=error, wall=time.monotonic() - began, chunks=chunks)
        return self.last

    async def stream_async(self, client):
        began, chunks = time.monotonic(), []
        try:
            made = await request(self.sdk, client, True, True, {})
            async for chunk in made:
                chunks.append((chunk, time.monotonic() - began))
            self.last = Outcome(self.sdk, wall=time.monotonic() - began, chunks=chunks)
        except (Fail, Cannot):
            raise
        except Exception as error:
            self.last = Outcome(self.sdk, error=error, wall=time.monotonic() - began, chunks=chunks)
        return self.last

    def run_async(self, body):
        return asyncio.run(body())

    # Reading

    def to_reflexer(self):
        return self.reflexer.message_arrivals()

    def note(self, text):
        self.notes.append(text)

    def check(self, condition, message):
        if not condition:
            raise Fail(message)

    def straight(self, outcome):
        """The client got the provider's own answer."""
        self.check(outcome.error is None, f"the client's call failed: {outcome}")
        self.check(outcome.text == STRAIGHT_TEXT, f"expected the provider's answer: {outcome}")
        self.check(self.provider.seen, "answered, yet the provider saw nothing")

    def served(self, outcome):
        """The client got reflexer's answer."""
        self.check(outcome.error is None, f"the client's call failed: {outcome}")
        self.check(outcome.text == SERVED_TEXT, f"expected reflexer's answer: {outcome}")
        self.check(self.to_reflexer(), "served, yet reflexer saw nothing")

    def legs(self):
        return f"reflexer {len(self.to_reflexer())}, provider {len(self.provider.seen)}"

    def saw(self):
        parts = list(self.notes)
        if self.last is not None:
            parts.insert(0, str(self.last))
        parts.append(self.legs())
        return "; ".join(parts)

    def invariants(self):
        """Checked after every case: what must never have arrived."""
        key = self.world.key
        others = [("provider", self.provider.seen), ("elsewhere", self.elsewhere.seen), ("runner", self.runner.seen),
                  ("proxy in the clear", self.proxy.plain)]
        for who, arrivals in others:
            for arrival in arrivals:
                carried = key and (any(key in value for value in arrival.headers.values())
                                   or key.encode() in (arrival.body or b"") or key in (arrival.path or ""))
                self.check(not carried, f"the reflexer key reached the {who}: {arrival}")
        for arrival in self.reflexer.seen + self.provider.seen + self.elsewhere.seen + self.runner.seen + self.proxy.plain:
            left = self.local_flags & set(arrival.headers)
            self.check(not left, f"the skip's flag {sorted(left)} left the machine: {arrival}")


def seed_for(name):
    random.seed(int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big"))


STALL = 0.15  # seconds this process may go unscheduled in a try judged by real time; past it, the try is not judged
TICK = 0.01


class Ticker:
    """How long this process went unscheduled, at worst, since it began: a thread ticking, its lateness kept. A
    machine that froze or starved the process shows here; a slow SDK does not."""

    def __init__(self):
        self.last, self.worst, self.ticking = time.monotonic(), 0.0, True
        threading.Thread(target=self.tick, daemon=True).start()

    def tick(self):
        while self.ticking:
            time.sleep(TICK)
            now = time.monotonic()
            self.worst, self.last = max(self.worst, now - self.last - TICK), now

    def stop(self):
        """Its worst lateness, a stall just ended counted before its thread woke to see it."""
        self.ticking = False
        return max(self.worst, time.monotonic() - self.last - TICK)
