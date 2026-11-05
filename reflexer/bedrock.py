"""Amazon Bedrock's wire, and what its lines share, apart from the files every provider shares: a direct call to OpenAI or
Anthropic runs as shipped. The wire: which calls go to reflexer. It names no provider, as Azure's does not: every call
names its upstream, its region in its host.

A call that carries a Bedrock API key (`Authorization: Bearer`) goes to reflexer, the key among its headers, as any
provider's key does; it falls back to the same call, straight. A call the library signed (SigV4) never goes to reflexer:
it reaches Bedrock as the library made it, less any header of ours its signature does not cover, which never leaves.

What the lines share: `keyed`, `straight`, the botocore family's per-call skip (`skip_taken`), reflexer's leg tried once
more when TLS refused its connection (`again_if_refused`), and the httpx lines' transport (`Keyed`, `setup_http_client`).
"""
import copy, inspect, re
from . import BASE, OURS, PASS_THROUGH, Reflexer, ReplayNotTaken, is_replay
from .transport import STRAIGHT, Through, body_of

BEDROCK = {
    "reflexer_path": "/bedrock",
    "calls":         r"/model/[^/]+/(invoke|invoke-with-response-stream|converse|converse-stream)$",
}
SKIPPED_HERE = "reflexer_pass_through"  # in a botocore call's context: this call goes straight
ARGUMENT = "ReflexerPassThrough"  # the botocore family's per-call skip, a call's argument: `client.converse(..., ReflexerPassThrough=True)`


def keyed(headers):
    """Whether the call carries a Bedrock API key, which reflexer passes on as any provider's key; not a signature."""
    auth = headers.get("authorization") or ""
    return (auth.decode() if isinstance(auth, bytes) else auth).lower().startswith("bearer ")  # a scheme's name, in any case


def straight(request, headers, body):
    """The client's own call, for Bedrock: no header of ours leaves but one its signature covers, which a signed call keeps
    so that Bedrock still takes it. A replay never goes. `headers`, the request's own, changed in place."""
    if body is not None and is_replay(body):
        raise ReplayNotTaken("reflexer did not take this replay, and a replay does not go to the provider")
    auth = headers.get("authorization") or ""
    signed = re.search(r"SignedHeaders=([^,\s]+)", auth.decode() if isinstance(auth, bytes) else auth)
    covered = set(signed[1].split(";")) if signed else set()
    for name in [name for name in headers if name.lower().startswith(OURS) and name.lower() not in covered]:
        del headers[name]
    return request


def lower(headers):
    return {name.lower(): value.decode() if isinstance(value, bytes) else value for name, value in headers.items()}


def skip_taken(event_name, kwargs, before):
    """The botocore family's per-call skip, taken off where botocore would carry it to Bedrock, and kept in the call's
    context: the argument, from the call's parameters before botocore validates them (`provide-client-params`, before the
    client's own handlers); the header, from the request after the client's own `before-sign` handlers, before it is signed."""
    if before and event_name.startswith("provide-client-params.") and kwargs["params"].pop(ARGUMENT, None):
        kwargs["context"][SKIPPED_HERE] = True
    if not before and event_name.startswith("before-sign."):
        request = kwargs["request"]
        for name in [name for name in request.headers if name.lower() == PASS_THROUGH]:
            del request.headers[name]
            request.context[SKIPPED_HERE] = True


def botocore_route(reflexer, request):
    """A botocore call's way to reflexer, (url, headers), or None: only a call carrying a key, not skipped, its body in
    memory (one that is not could not be sent twice)."""
    body = request.body if isinstance(request.body, bytes) else None
    headers = lower(request.headers)
    if body is None or not keyed(headers) or (request.context or {}).get(SKIPPED_HERE):
        return None
    return reflexer.route(request.url, headers, is_replay(body))


def answered(responses):
    """Whether a `before-send` handler of the client's answered the call (a stub, a cache): botocore takes the first answer."""
    return any(response is not None for _, response in responses)


def chain(failure):
    """The failure and every error it wraps, as each HTTP library wraps one."""
    seen, pending = {}, [failure]
    while pending:
        each = pending.pop()
        if isinstance(each, BaseException) and id(each) not in seen:
            seen[id(each)] = each
            given = getattr(each, "kwargs", None)  # botocore keeps the error it wraps there
            pending += [each.__cause__, each.__context__, *each.args, *(given.values() if isinstance(given, dict) else ())]
    return list(seen.values())


def connecting(each):
    """Whether the error was raised making the connection, before any byte of the request left: httpx's and httpcore's
    `ConnectError`, aiohttp's `ClientConnectorError`, or urllib3's, from inside its connection's `connect`."""
    if {kind.__name__ for kind in type(each).__mro__} & {"ConnectError", "ClientConnectorError"}:
        return True
    frame = each.__traceback__
    while frame is not None:
        if frame.tb_frame.f_code.co_name == "connect" and frame.tb_frame.f_globals.get("__name__") == "urllib3.connection":
            return True
        frame = frame.tb_next
    return False


def refused_at_tls(failure):
    """Whether TLS refused reflexer's leg by an alert while connecting, so no byte of the request left. A garbled
    ClientHello makes one: urllib3 and httpcore set ALPN on a shared context before each connection, which CPython copies
    unlocked into a connection on another thread."""
    errors = chain(failure)
    alerted = any(isinstance(each, OSError) and "ALERT" in str(getattr(each, "reason", None) or "") for each in errors)
    return alerted and any(connecting(each) for each in errors)


def again_if_refused(send):
    """`send()`, once more on a new connection if TLS refused it while connecting: not reflexer's failure, uncounted."""
    try:
        return send()
    except Exception as failure:
        if not refused_at_tls(failure):
            raise
    return send()


async def aagain_if_refused(send):
    """`again_if_refused`, for a coroutine."""
    try:
        return await send()
    except Exception as failure:
        if not refused_at_tls(failure):
            raise
    return await send()


class Keyed(Through):
    """The shipped `Through`, for a Bedrock call: reflexer's leg only for a call carrying a key, tried once more when TLS
    refused it while connecting. Any other call goes straight, as the library made it (`straight`)."""

    def __init__(self, reflexer, inner):
        super().__init__(reflexer, inner)
        self.as_made = send = self.send

        def leg(request):  # reflexer's leg: the one request of ours not marked straight
            return send(request) if STRAIGHT in request.extensions else again_if_refused(lambda: send(request))

        async def aleg(request):
            return await (send(request) if STRAIGHT in request.extensions else aagain_if_refused(lambda: send(request)))

        self.send = aleg if inspect.iscoroutinefunction(inner.send) else leg

    def handle_request(self, request):
        if keyed(request.headers):
            return super().handle_request(request)
        return self.as_made(straight(request, request.headers, body_of(request)))

    async def handle_async_request(self, request):
        if keyed(request.headers):
            return await super().handle_async_request(request)
        return await self.as_made(straight(request, request.headers, body_of(request)))


def setup_http_client(stock, wire):
    """The shipped `setup_http_client`, with `Keyed` for its transport."""

    def http_client(key, own=None, base=BASE, sample=1.0):
        own = own or stock()
        inner = copy.copy(own)  # the client's own object stays as it was, for its other users; they share connections
        inner.event_hooks = {}  # they run once, above, and never see our key
        outer = type(own)(transport=Keyed(Reflexer(key, wire, base, sample), inner), event_hooks=own.event_hooks, auth=own.auth,
                          params=own.params, headers=own.headers, cookies=own.cookies.jar, timeout=own.timeout,
                          follow_redirects=own.follow_redirects, max_redirects=own.max_redirects, base_url=own.base_url)
        outer.reflexer_through = dict(key=key, base=base, sample=sample)  # what a copy given its own HTTP client is made with
        return outer

    return http_client
