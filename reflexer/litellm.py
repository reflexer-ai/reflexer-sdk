"""LiteLLM's calls, through reflexer: one line, before the first call, `reflexer.litellm.through(key)`. A call whose wire
reflexer takes (OpenAI's, Azure OpenAI's, Anthropic's, Gemini's, Bedrock's: `wires.py`, `bedrock.py`), at its provider's
own host, goes through it, sync or async, streamed or not, from the client's own code or a framework's; any other call
goes as stock, as does one given its own `client`.

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
Its sync HTTP client and its sessions live as long as the process: a close of one of LiteLLM's clients over them leaves
them open. Its async HTTP clients, one per event loop, live in LiteLLM's own cache, as LiteLLM's do. Run again, the line
takes the place of the last, over what the client had before it.

A Bedrock call given `api_key`, a Bedrock API key, goes through reflexer, and so does a signed one (SigV4). Its fallback:
LiteLLM signs it before any hook of its own runs, and none signs it anew, so the fallback is the same signed call.
Reflexer's leg is bounded, to its answer's head, by what is left of the signature's window, by this machine's clock, the
one LiteLLM signs by: so the fallback reaches Bedrock while its signature holds.

A call's timeout: LiteLLM posts by a given client with no `timeout` on some routes (Bedrock's converse, Gemini's context
caching), where stock builds its client with it; so the handler the hook gives each call is made with the call's own.
"""
import asyncio, contextvars, copy, datetime, functools, inspect, re, threading, time
import httpx, litellm
from litellm.integrations.custom_logger import CustomLogger
from litellm.litellm_core_utils.completion_timeout import CompletionTimeout
from litellm.litellm_core_utils.request_timeout_resolver import get_configured_request_timeout
from litellm.utils import supports_httpx_timeout
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler, HTTPHandler
from . import BASE, Reflexer, checked, supported
from .bedrock import BEDROCK, Keyed, straight
from .transport import STRAIGHT, Through, body_of
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

    def __init__(self, inner, reflexers):
        self.reflexers = reflexers
        self.inner, self.lock, self.name = inner, threading.Lock(), f"reflexer-litellm-{id(self)}"
        self.lines = self.over(inner) if isinstance(inner, (httpx.Client, httpx.AsyncClient)) else None

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
            if inner is None or inner.is_closed:  # closed by LiteLLM's own cleanup, as its handlers remake theirs
                inner = self.inner()
                litellm.in_memory_llm_clients_cache.set_cache(self.name, inner, litellm_owned_client=True)
        return self.over(inner)

    def line_of(self, request, lines):
        return next((line for line, host in lines if at(request.url.host, host) and re.search(line.reflexer.way[2], request.url.path)), None)

    def handle_request(self, request):
        if request.url.scheme == PROBE.partition(":")[0]:  # the line's own, as it runs: answered here
            return httpx.Response(204)
        checked(request.headers)  # a wrong value raises here, before anything is sent, on any call
        lines, send = self.now()
        line = self.line_of(request, lines)
        return line.handle_request(request) if line else send(straight(request, request.headers, body_of(request)))

    async def handle_async_request(self, request):
        checked(request.headers)
        lines, send = self.now()
        line = self.line_of(request, lines)
        return await (line.handle_async_request(request) if line else send(straight(request, request.headers, body_of(request))))

    def close(self):
        pass

    async def aclose(self):
        pass


class Kept(httpx.AsyncClient):
    """The session the line gives LiteLLM for the openai SDK's async calls, when the client gave none: one for the process,
    as LiteLLM takes it, so a close of an SDK client over it, LiteLLM's cleanup's, leaves it open, for the next."""

    async def aclose(self):
        pass


def ways(key, base=BASE, sample=1.0, **options):
    """Each wire's way to reflexer, its line and its hosts: one for the process, shared by every client of the line's, so
    one breaker per wire, sync and async alike. `options`: `namespace`, `answer`, `store`, `pass_through`, `timeout_ms`,
    as every other line takes them (`Reflexer`)."""
    return [(Reflexer(key, wire, base, sample, **options), line, host) for wire, line, host in LINES]


def split(own, way):
    """The client's own HTTP client, through reflexer, as `setup_http_client` splits one: its hooks run once, above, and
    never see our key; the copy under ours shares its connections."""
    inner = copy.copy(own)
    inner.event_hooks = {}
    return type(own)(transport=Wires(inner, way), event_hooks=own.event_hooks, auth=own.auth, params=own.params,
                     headers=own.headers, cookies=own.cookies.jar, timeout=own.timeout, follow_redirects=own.follow_redirects,
                     max_redirects=own.max_redirects, base_url=own.base_url)


class Handler(AsyncHTTPHandler):
    """LiteLLM's own async handler, made with our transport, for one call: by its timeout, as stock makes its own."""


class Hook(CustomLogger):
    """Gives each async completion of a provider on LiteLLM's own handlers a handler of ours, as its `client`, unless it
    has one: the only way into those calls."""

    def __init__(self, transport):
        super().__init__()
        self.transport = transport

    async def async_pre_call_deployment_hook(self, kwargs, call_type):
        """Each call LiteLLM makes of `acompletion`, its own fallbacks to another provider included, which carry the first
        call's arguments: ours goes only where it is taken; a call given the client's own aiohttp session keeps it."""
        if call_type == "acompletion" and isinstance(kwargs.get("client"), (type(None), Handler)) and kwargs.get("shared_session") is None:
            taken = provider(kwargs)
            timeout = CompletionTimeout.resolve(kwargs.get("timeout"), kwargs, taken, global_timeout=get_configured_request_timeout(),
                                                supports_httpx_timeout=supports_httpx_timeout)  # as stock resolves it
            kwargs["client"] = Handler(transport=self.transport, timeout=timeout) if taken in HANDLED else None
        return kwargs


def provider(kwargs):
    """The call's provider, as LiteLLM reads it from its model; None for a model it cannot read, whose call fails as stock."""
    try:
        model = kwargs.get("model") or getattr(kwargs.get("litellm_logging_obj"), "model", None)  # given by name, or by position
        return litellm.get_llm_provider(model=model, custom_llm_provider=kwargs.get("custom_llm_provider"),
                                        api_base=kwargs.get("api_base"))[1]
    except litellm.BadRequestError:
        return None


PROBE = "reflexer-probe://line/"  # a scheme no HTTP transport or proxy takes: a client not sending by the probe fails, sending nothing


def sends_by_it():
    """Whether an HTTP client LiteLLM's handlers make sends by `litellm.sync_transport`, which it reads but does not
    document: tried as the line runs, on a probe ours answers here, so a release that drops it fails the line, never sends
    a call straight unseen."""
    try:
        return HTTPHandler(client=httpx.Client()).create_client().get(PROBE).status_code == 204
    except httpx.HTTPError:
        return False


def session(kind, transport, own, way):
    """The session the line gives LiteLLM: as LiteLLM's own, or over the client's own when it set one."""
    outer = kind(transport=transport, follow_redirects=True) if own is None else split(own, way)
    outer.reflexer_own = own
    return outer


def through(reflexer_key, base=BASE, sample=1.0, namespace=None, answer=True, store=True, pass_through=False, timeout_ms=None):
    """The line: every LiteLLM call whose wire reflexer takes, through reflexer, from now on in this process."""
    way = ways(reflexer_key, base, sample, namespace=namespace, answer=answer, store=store, pass_through=pass_through,
               timeout_ms=timeout_ms)  # a key, an address or an option refused before anything changes
    was = getattr(litellm, "sync_transport", None)
    given = {"client_session": getattr(litellm, "client_session", None), "aclient_session": getattr(litellm, "aclient_session", None), "sync_transport": was}
    own = {name: getattr(value, "reflexer_own", value) for name, value in given.items()}  # the client's, under a last line's
    try:
        litellm.sync_transport = own["sync_transport"]  # so LiteLLM's own HTTP client, made now by its settings, is over it
        sync = Wires(HTTPHandler(client=httpx.Client()).create_client(), way)  # a handler holding none over the client's
        # own transport, whose finalizer would close it
        aio = Wires(lambda: AsyncHTTPHandler().create_client(None, None), way)  # LiteLLM's own, one per event loop
        sync.reflexer_own, litellm.sync_transport = own["sync_transport"], sync
        if not sends_by_it():
            raise RuntimeError("LiteLLM does not send its handlers' calls by `litellm.sync_transport`: a release that dropped it, or `force_ipv4`")
    except BaseException:
        litellm.sync_transport = was
        raise
    litellm.client_session, litellm.aclient_session = session(httpx.Client, sync, own["client_session"], way), session(Kept, aio, own["aclient_session"], way)
    litellm.input_callback[:] = [each for each in litellm.input_callback if not isinstance(each, Hook)]  # where LiteLLM filed the last
    litellm.callbacks[:] = [each for each in litellm.callbacks if not isinstance(each, Hook)] + [Hook(aio)]
    litellm.in_memory_llm_clients_cache.flush_cache()  # the clients LiteLLM made before, kept for reuse: made anew, by the line
    litellm.module_level_client = HTTPHandler(timeout=litellm.request_timeout)  # its one kept apart, made anew as LiteLLM makes it
