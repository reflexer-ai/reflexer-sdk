"""anthropic's Bedrock clients, through reflexer: `anthropic.AnthropicBedrock(**config)` becomes
`reflexer.anthropic_bedrock.AnthropicBedrock(**config, reflexer_key=key)`; Mantle's, `AnthropicBedrockMantle`, the same.

A client given a Bedrock API key (`api_key`, or `AWS_BEARER_TOKEN_BEDROCK`) sends its calls through reflexer, and so does
one that signs (SigV4) on Bedrock's runtime. The SDK signs each attempt as it makes it, and runs its documented client
middleware around each: ours, last of the client's, takes the skip's header off before the SDK signs, and lets a signed
call's first attempt go to reflexer alone; given no answer there, it makes the attempt again, which the SDK signs anew
and our transport sends straight. Mantle's go by the anthropic wire, Mantle as the upstream, with no middleware of ours;
a signed one, to Mantle as stock: reflexer takes signed calls on Bedrock's runtime only.
"""
import contextvars, inspect
import anthropic
from . import BASE, OURS, PASS_THROUGH, supported
from .anthropic import MESSAGES
from .bedrock import BEDROCK, Keyed, setup_http_client, straight
from .transport import STRAIGHT, Through, setup_client

supported("anthropic", [2])
CALL = contextvars.ContextVar("reflexer_call", default=None)  # set by our middleware around an attempt: {"skipped"} or {"straight"}


class Straight(Exception):
    """Reflexer's leg gave a signed call no answer: our middleware makes the attempt again, straight."""


class Again(Keyed):
    """Bedrock's runtime, for a call our middleware made: one it skipped goes straight. A signed call's first attempt takes
    the shipped legs, but its straight leg is not sent: our middleware makes the attempt again, which the SDK signs anew
    and this sends as the SDK made it."""

    def __init__(self, reflexer, inner):
        super().__init__(reflexer, inner)
        send = self.send

        def leg(request):
            if withheld(request):
                raise again(CALL.get())
            return send(request)

        async def aleg(request):
            if withheld(request):
                raise again(CALL.get())
            return await send(request)

        self.send = aleg if inspect.iscoroutinefunction(inner.send) else leg

    def handle_request(self, request):
        return self.straight(request) if (CALL.get() or {}).get("skipped") else super().handle_request(request)

    async def handle_async_request(self, request):
        return await (self.straight(request) if (CALL.get() or {}).get("skipped") else super().handle_async_request(request))

    def signed_call(self, request):
        return Through.handle_request(self, request) if self.first(request) else self.straight(request)

    async def asigned_call(self, request):
        return await (Through.handle_async_request(self, request) if self.first(request) else self.straight(request))

    @staticmethod
    def first(request):
        """Whether this is the call's first attempt by our middleware, which tries reflexer: marked so for its legs, with
        the headers of ours its signature covers, which the shipped straight leg takes off; no header of its signature's own."""
        call = CALL.get()
        if call is None or call.get("straight"):
            return False
        kept = dict(request.headers)
        straight(None, kept, None)  # takes off those of ours its signature does not cover, as the call's straight leg does
        call["first"], call["ours"] = True, {name: value for name, value in kept.items() if name.lower().startswith(OURS)}
        return True


def withheld(request):
    """Whether a signed call's straight leg, on our middleware's first attempt, waits for the attempt made again: only
    after reflexer's leg was sent, which may have taken the signature's time. One never sent (sampled out, the breaker
    open) goes now, the headers of ours its signature covers put back: the shipped straight leg took them off."""
    call = CALL.get() or {}
    if not call.get("first"):
        return False
    if STRAIGHT not in request.extensions:
        call["sent"] = True
        return False
    if call.get("sent"):
        return True
    request.headers.update(call["ours"])
    return False


def again(call):
    """Reflexer's leg gave no answer, and may have taken the signature's time: the call goes straight by an attempt the SDK
    signs anew."""
    call["straight"], call["first"] = True, False
    return Straight("the call goes straight, signed anew")


class Middleware(anthropic.Middleware):
    """Last of the client's middleware: it runs once per attempt the SDK makes, before the SDK signs it."""

    @staticmethod
    def attempt(request):
        """(the attempt, its call's own state), the skip's header taken off: it never leaves, and the call goes straight."""
        headers = dict(request.headers)
        if not any(name.lower() == PASS_THROUGH for name in headers):
            return request, {}
        return request.copy(headers={name: value for name, value in headers.items() if name.lower() != PASS_THROUGH}), {"skipped": True}

    def handle(self, request, call_next):
        request, call = self.attempt(request)
        token = CALL.set(call)
        try:
            return call_next(request)
        except Exception:
            if not call.get("straight"):
                raise
            return call_next(request)
        finally:
            CALL.reset(token)

    async def handle_async(self, request, call_next):
        request, call = self.attempt(request)
        token = CALL.set(call)
        try:
            return await call_next(request)
        except Exception:
            if not call.get("straight"):
                raise
            return await call_next(request)
        finally:
            CALL.reset(token)


def bedrock_client(cls, make_http_client, ours=()):
    """The shipped line's client, `ours` last of the client's middleware; its copy keeps our HTTP client (the SDK's own
    copy of a Bedrock client drops it, and would make one with no key)."""

    class Client(setup_client(cls, make_http_client)):
        def __init__(self, *args, reflexer_key=None, reflexer_base=BASE, sample=1.0, http_client=None, middleware=(), **config):
            if not hasattr(http_client, "reflexer_through"):
                http_client = make_http_client(reflexer_key, own=http_client, base=reflexer_base, sample=sample)
            self.reflexer_http_client = http_client
            middleware = (*[each for each in middleware or () if not isinstance(each, Middleware)], *[made() for made in ours])
            super().__init__(*args, http_client=http_client, **({"middleware": middleware} if middleware else {}), **config)

        def copy(self, *args, http_client=None, **config):
            return super().copy(*args, http_client=http_client or self.reflexer_http_client, **config)

        with_options = copy

    Client.__name__ = Client.__qualname__ = cls.__name__
    return Client


bedrock_http_client       = setup_http_client(anthropic.DefaultHttpxClient,      BEDROCK, Again)
bedrock_async_http_client = setup_http_client(anthropic.DefaultAsyncHttpxClient, BEDROCK, Again)
mantle_http_client        = setup_http_client(anthropic.DefaultHttpxClient,      MESSAGES)
mantle_async_http_client  = setup_http_client(anthropic.DefaultAsyncHttpxClient, MESSAGES)

AnthropicBedrock            = bedrock_client(anthropic.AnthropicBedrock,            bedrock_http_client,       [Middleware])
AsyncAnthropicBedrock       = bedrock_client(anthropic.AsyncAnthropicBedrock,       bedrock_async_http_client, [Middleware])
AnthropicBedrockMantle      = bedrock_client(anthropic.AnthropicBedrockMantle,      mantle_http_client)
AsyncAnthropicBedrockMantle = bedrock_client(anthropic.AsyncAnthropicBedrockMantle, mantle_async_http_client)
