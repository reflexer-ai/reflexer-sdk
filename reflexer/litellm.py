"""LiteLLM's calls, through reflexer: one line, before the first call, `reflexer.litellm.through(key)`. A call whose wire
reflexer takes (OpenAI's, Azure OpenAI's, Anthropic's, Gemini's, Bedrock's: `wires.py`, `bedrock.py`) goes through it,
sync or async, streamed or not, from the client's own code or a framework's; any other call goes as stock.

No one setting of LiteLLM's reaches every call, so the line sets the four that together do, each by its public name, and
makes no class of LiteLLM's different:
- `client_session`, `aclient_session`: the HTTP clients LiteLLM gives the openai SDK, for OpenAI's and Azure's calls.
  Ours, over the client's own when it set one.
- `sync_transport`: the transport of every HTTP client LiteLLM's own handlers make, for the other providers' sync calls.
  Ours, over an HTTP client LiteLLM made as the line ran, by its settings then (TLS, certificate, proxies, HTTP/2). Read
  by LiteLLM, not documented: the line checks, as it runs, that LiteLLM's handlers send by it, and fails there if not, so
  a release dropping it fails the line, never sends a call straight unseen.
- `callbacks`: a callback's `async_pre_call_deployment_hook`, the one way into the other providers' async calls, gives each
  `acompletion` our handler as its `client`, as a client could on each call.
What the line makes lives as long as the process, as LiteLLM's own clients do: a close of one leaves it open. Run again,
it takes the place of the last, over what the client had before it.

A Bedrock call given `api_key`, a Bedrock API key, goes through reflexer, and so does a signed one (SigV4). Its fallback:
LiteLLM signs it before any hook of its own runs, and none signs it anew, so the fallback is the same signed call.
Reflexer's leg is bounded, to its answer's head, by what is left of the signature's window, by this machine's clock, the
one LiteLLM signs by: so the fallback reaches Bedrock while its signature holds.

A call's timeout: LiteLLM's Bedrock converse handler, not streamed, posts by a given client with no `timeout`, where stock
builds its client with it; so our handler takes it from the call's own parameters, which LiteLLM hands `post` with its
`logging_obj`. A release that moves them fails the call, never drops its timeout.
"""
import asyncio, contextvars, copy, datetime, functools, inspect, re, threading, time
import httpx, litellm
from litellm.integrations.custom_logger import CustomLogger
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler, HTTPHandler
from . import BASE, Reflexer, supported
from .bedrock import BEDROCK, Keyed, straight
from .transport import STRAIGHT, Through
from .wires import AZURE, CHAT, GENERATE, MESSAGES

supported("litellm", [1])
WINDOW = {"header": "x-amz-date", "seconds": 300.0, "margin": 30.0}  # a signature's: AWS's five minutes; the margin provisional
HANDLED = ("anthropic", "gemini", "bedrock")  # the providers whose async calls take our handler as their `client`


class Windowed(Keyed):
    """Bedrock's transport, a signed call's two legs as a keyed call's, reflexer's bounded to its answer's head by what is
    left of the signature's window; none when none is left."""

    def __init__(self, reflexer, inner):
        super().__init__(reflexer, inner)
        send = self.send

        def leg(request):
            seconds = None if STRAIGHT in request.extensions else left(request.headers)
            return send(request) if seconds is None else within(seconds, lambda: send(request))

        async def aleg(request):
            seconds = None if STRAIGHT in request.extensions else left(request.headers)
            return await (send(request) if seconds is None else awithin(seconds, send(request)))

        self.send = aleg if inspect.iscoroutinefunction(inner.send) else leg

    def signed_call(self, request):
        return Through.handle_request(self, request) if (left(request.headers) or 0) > 0 else self.straight(request)

    async def asigned_call(self, request):
        return await (Through.handle_async_request(self, request) if (left(request.headers) or 0) > 0 else self.straight(request))


def left(headers):
    """Seconds reflexer's leg may take so that Bedrock still takes the call's signature after it, by the clock LiteLLM
    signs by; or None for a call with no signing time."""
    try:
        at = datetime.datetime.strptime(headers.get(WINDOW["header"]) or "", "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    return at.timestamp() + WINDOW["seconds"] - WINDOW["margin"] - time.time()


def within(seconds, send):
    """`send()`, reflexer's leg to its answer's head, given up after `seconds`, where httpx bounds each read only. A leg
    given up runs on in its own thread, to the call's own timeouts; an answer that comes late is closed unread."""
    held, lock, done, context = {}, threading.Lock(), threading.Event(), contextvars.copy_context()

    def leg():
        try:
            outcome = (True, context.run(send))
        except Exception as failure:
            outcome = (False, failure)
        with lock:
            held["outcome"], late = outcome, held.get("late")
        if late and outcome[0]:
            outcome[1].close()
        done.set()
    threading.Thread(target=leg, daemon=True).start()
    done.wait(seconds)
    with lock:
        if "outcome" not in held:
            held["late"] = True
            raise TimeoutError("reflexer's answer did not start while the signature holds")
    answered, value = held["outcome"]
    if not answered:
        raise value
    return value


def awithin(seconds, sent):
    """`within`, for a coroutine: the leg cancelled at the bound."""
    return asyncio.wait_for(sent, seconds)


LINES = (  # each wire's line, and the hosts its calls go to: the provider's own, or Azure's and AWS's domains, whose hosts are each client's
    (CHAT, Through, "api.openai.com"), (AZURE, Through, ".azure.com"), (MESSAGES, Through, "api.anthropic.com"),
    (GENERATE, Through, "generativelanguage.googleapis.com"), (BEDROCK, Windowed, ".amazonaws.com"),
)


def at(host, where):
    """Whether a call's host is `where`: that host, or, written with a leading dot, any host of that domain."""
    return host.endswith(where) if where.startswith(".") else host == where


class Wires:
    """A transport, by duck typing, for every wire above: a call goes by the line of the wire whose calls it is, at its host;
    any other as stock, LiteLLM's other providers' (a router, Bedrock's Mantle) among them, our headers off. `inner`: the
    HTTP client under it; or, async, a function making one, for each event loop, kept in LiteLLM's own cache of its HTTP
    clients, which keys them by their loop, and closes them, as its own, once they leave it. Shared by many HTTP clients:
    a close of one leaves it, and the client under it, open."""

    def __init__(self, inner, key, base=BASE, sample=1.0):
        self.reflexers = [(Reflexer(key, wire, base, sample), line, host) for wire, line, host in LINES]
        self.inner, self.lock, self.name = inner, threading.Lock(), f"reflexer-litellm-{id(self)}"
        self.lines = None if callable(inner) else self.over(inner)

    def over(self, inner):
        """Its lines over one HTTP client, and that client's own send, for a call no line takes."""
        return [(line(reflexer, inner), host) for reflexer, line, host in self.reflexers], \
            functools.partial(inner.send, stream=True, follow_redirects=False, auth=None)

    def now(self):
        """Its lines and send: over its one HTTP client, or over the running event loop's own."""
        if self.lines is not None:
            return self.lines
        with self.lock:
            inner = litellm.in_memory_llm_clients_cache.get_cache(self.name)
            if inner is None:
                inner = self.inner()
                litellm.in_memory_llm_clients_cache.set_cache(self.name, inner, litellm_owned_client=True)
        return self.over(inner)

    def line_of(self, request, lines):
        return next((line for line, host in lines if at(request.url.host, host) and re.search(line.reflexer.calls, request.url.path)), None)

    def handle_request(self, request):
        lines, send = self.now()
        line = self.line_of(request, lines)
        return line.handle_request(request) if line else send(straight(request, request.headers, None))

    async def handle_async_request(self, request):
        lines, send = self.now()
        line = self.line_of(request, lines)
        return await (line.handle_async_request(request) if line else send(straight(request, request.headers, None)))

    def close(self):
        pass

    async def aclose(self):
        pass


def split(own, way):
    """The client's own HTTP client, through reflexer, as `setup_http_client` splits one: its hooks run once, above, and
    never see our key; the copy under ours shares its connections."""
    inner = copy.copy(own)
    inner.event_hooks = {}
    return type(own)(transport=Wires(inner, **way), event_hooks=own.event_hooks, auth=own.auth, params=own.params,
                     headers=own.headers, cookies=own.cookies.jar, timeout=own.timeout, follow_redirects=own.follow_redirects,
                     max_redirects=own.max_redirects, base_url=own.base_url)


def asked(timeout, logging_obj):
    """The call's own timeout: the one given to `post`, else the call's, as stock would have built its client with."""
    if timeout is not None or logging_obj is None:
        return timeout
    given = logging_obj.model_call_details["litellm_params"]["timeout"]
    return httpx.Timeout(given) if isinstance(given, (int, float)) else given


class Handler(AsyncHTTPHandler):
    """LiteLLM's own async handler, made with our transport."""

    async def post(self, *args, timeout=None, logging_obj=None, **kwargs):
        return await super().post(*args, timeout=asked(timeout, logging_obj), logging_obj=logging_obj, **kwargs)


class Hook(CustomLogger):
    """Gives each async completion of a provider on LiteLLM's own handlers our handler, as its `client`, unless it has one."""

    def __init__(self, handler):
        super().__init__()
        self.handler = handler

    async def async_pre_call_deployment_hook(self, kwargs, call_type):
        if call_type == "acompletion" and kwargs.get("client") is None and provider(kwargs) in HANDLED:
            kwargs["client"] = self.handler
        return kwargs


def provider(kwargs):
    """The call's provider, as LiteLLM reads it from its model; None for a model it cannot read, whose call fails as stock."""
    try:
        model = kwargs.get("model") or getattr(kwargs.get("litellm_logging_obj"), "model", None)  # given by name, or by position
        return litellm.get_llm_provider(model=model, custom_llm_provider=kwargs.get("custom_llm_provider"),
                                        api_base=kwargs.get("api_base"))[1]
    except litellm.BadRequestError:
        return None


SET = ("client_session", "aclient_session", "sync_transport")
PROBE = "http://127.0.0.1:0/"  # a port nothing listens on, here: a client not sending by the probe fails at once, sending nothing


def sends_by_it():
    """Whether an HTTP client LiteLLM's handlers make sends by `litellm.sync_transport`, which it reads but does not
    document: tried as the line runs, on a probe answering here, so a release that drops it fails the line, never sends
    a call straight unseen."""
    litellm.sync_transport = httpx.MockTransport(lambda request: httpx.Response(204))
    try:
        return HTTPHandler(client=httpx.Client()).create_client().get(PROBE).status_code == 204
    except httpx.HTTPError:
        return False


def through(reflexer_key, base=BASE, sample=1.0):
    """The line: every LiteLLM call whose wire reflexer takes, through reflexer, from now on in this process."""
    way = dict(key=reflexer_key, base=base, sample=sample)
    Reflexer(reflexer_key, CHAT, base, sample)  # a key or an address refused before anything changes
    was = getattr(litellm, "sync_transport", None)
    own = {name: getattr(getattr(litellm, name, None), "reflexer_own", getattr(litellm, name, None)) for name in SET}  # the client's
    try:
        litellm.sync_transport = own["sync_transport"]  # so LiteLLM's own HTTP client, made now by its settings, is over it
        sync = Wires(HTTPHandler(client=httpx.Client()).create_client(), **way)  # a handler holding none over the client's
        # own transport, whose finalizer would close it
        aio = Wires(lambda: AsyncHTTPHandler().create_client(None, None), **way)  # LiteLLM's own, one per event loop
        sync.reflexer_own = own["sync_transport"]
        if not sends_by_it():
            raise RuntimeError("LiteLLM does not send its handlers' calls by `litellm.sync_transport`: a release that dropped it, or `force_ipv4`")
        litellm.sync_transport = sync
    except BaseException:
        litellm.sync_transport = was
        raise
    for name, kind, transport in (("client_session", httpx.Client, sync), ("aclient_session", httpx.AsyncClient, aio)):
        outer = kind(transport=transport, follow_redirects=True) if own[name] is None else split(own[name], way)  # as LiteLLM's own
        outer.reflexer_own = own[name]
        setattr(litellm, name, outer)
    litellm.callbacks[:] = [each for each in litellm.callbacks if not isinstance(each, Hook)] + [Hook(Handler(transport=aio))]
    litellm.in_memory_llm_clients_cache.flush_cache()  # the clients LiteLLM made before, kept for reuse: made anew, by the line
    litellm.module_level_client = HTTPHandler(timeout=litellm.request_timeout)  # its one kept apart, made anew as LiteLLM makes it
