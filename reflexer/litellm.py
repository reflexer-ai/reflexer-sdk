"""LiteLLM's Bedrock calls, through reflexer: its handlers take `client=` per call, an `HTTPHandler` of LiteLLM's,
`litellm.completion(model="bedrock/...", client=reflexer.litellm.client(key))`. Ours is LiteLLM's own default handler,
whose `create_client` gives LiteLLM's HTTP client reflexer's transport; `async_client` for `acompletion`. No setting of
LiteLLM's reaches every Bedrock call: the line is per call. A call given `api_key`, a Bedrock API key, goes through
reflexer, and so does a signed one (SigV4).

A signed call's fallback: LiteLLM signs it before any hook of its own runs, and none signs it anew, so the fallback is
the same signed call. Reflexer's leg is bounded, to its answer's head, by what is left of the signature's window, by
this machine's clock, the one LiteLLM signs by: so the fallback reaches Bedrock while its signature holds.

The call's timeout: LiteLLM's converse handler, not streamed, posts by a given client with no `timeout`, where stock
builds its client with it; so ours takes it from the call's own parameters, which LiteLLM hands `post` with its
`logging_obj`. A release that moves them fails the call, never drops its timeout.
"""
import asyncio, contextvars, datetime, inspect, threading, time
import httpx
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler, HTTPHandler
from . import BASE, supported
from .bedrock import BEDROCK, Keyed, setup_http_client
from .transport import STRAIGHT, Through

supported("litellm", [1])
WINDOW = {"header": "x-amz-date", "seconds": 300.0, "margin": 30.0}  # a signature's: AWS's five minutes; the margin provisional


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


http_client = setup_http_client(httpx.Client, BEDROCK, Windowed)
async_http_client = setup_http_client(httpx.AsyncClient, BEDROCK, Windowed)


def asked(timeout, logging_obj):
    """The call's own timeout: the one given to `post`, else the call's, as stock would have built its client with."""
    if timeout is not None or logging_obj is None:
        return timeout
    given = logging_obj.model_call_details["litellm_params"]["timeout"]
    return httpx.Timeout(given) if isinstance(given, (int, float)) else given


def client(reflexer_key, base=BASE, sample=1.0):
    class Handler(HTTPHandler):
        def create_client(self):
            return http_client(reflexer_key, own=super().create_client(), base=base, sample=sample)

        def post(self, *args, timeout=None, logging_obj=None, **kwargs):
            return super().post(*args, timeout=asked(timeout, logging_obj), logging_obj=logging_obj, **kwargs)
    return Handler()


def async_client(reflexer_key, base=BASE, sample=1.0):
    class Handler(AsyncHTTPHandler):
        def create_client(self, *args, **kwargs):
            return async_http_client(reflexer_key, own=super().create_client(*args, **kwargs), base=base, sample=sample)

        async def post(self, *args, timeout=None, logging_obj=None, **kwargs):
            return await super().post(*args, timeout=asked(timeout, logging_obj), logging_obj=logging_obj, **kwargs)
    return Handler()
