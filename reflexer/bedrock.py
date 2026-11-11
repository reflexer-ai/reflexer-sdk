"""Amazon Bedrock's wire, and what its lines share, apart from the files every provider shares: a direct call to OpenAI or
Anthropic runs as shipped. The wire: which calls go to reflexer. It names no provider, as Azure's does not: every call
names its upstream, its region in its host.

A call that carries a Bedrock API key (`Authorization: Bearer`) goes to reflexer, the key among its headers, as any
provider's key does; it falls back to the same call, straight. A call to Bedrock's runtime the library signed (SigV4)
goes to reflexer as signed; reflexer never passes the client's signature on, and answers from what it holds or sends
the call back. Its fallback is signed anew by the library's own signer after reflexer's leg, where a line reaches one (the botocore family,
anthropic's Bedrock clients), so it is as fresh as stock's. What leaves for Bedrock is as the library made it, less any
header of ours its signature does not cover, which never leaves.

What the lines share: `keyed`, `signed`, `straight`, the botocore family's per-call skip and signer (`skip_taken`,
`signed_anew`), reflexer's leg tried once more when TLS refused its connection (`again_if_refused`), and the httpx lines'
transport (`Keyed`, `setup_http_client`).
"""
import copy, inspect, re
from . import BASE, OURS, OPTION_HEADERS, SKIP, Reflexer, ReplayNotTaken, checked, is_replay, skips, text
from .transport import STRAIGHT, Through, body_of

BEDROCK = {
    "reflexer_path": "/bedrock",
    "calls":         r"/model/[^/]+/(invoke|invoke-with-response-stream|converse|converse-stream)$",
}
SKIPPED_HERE = "reflexer_skip"  # in a botocore call's context: this call goes straight
GIVEN_HERE = "reflexer_given"  # in a botocore call's context: the call's own headers for reflexer, taken off before it is signed
SIGNER = "reflexer_signer"  # in a botocore call's context: the client's own signer and operation, as botocore gives them to `before-sign`
UNSIGNED = "reflexer_unsigned"  # in a botocore call's context: its URL, body and headers as they came to `before-sign`, before the client's handlers
ARGUMENT = "ReflexerSkip"  # the botocore family's per-call skip, a call's argument: `client.converse(..., ReflexerSkip=True)`
NOT_A_SKIP_ARGUMENT = f"the {ARGUMENT} argument must be True or False: True sends the call directly to the provider, False lets the call go through reflexer"


def keyed(headers):
    """Whether the call carries a Bedrock API key, which reflexer passes on as any provider's key; not a signature."""
    auth = headers.get("authorization") or ""
    return (auth.decode() if isinstance(auth, bytes) else auth).lower().startswith("bearer ")  # a scheme's name, in any case


def signed(headers):
    """Whether the library signed the call by SigV4, AWS's signature over it, which holds a few minutes from its signing time."""
    auth = headers.get("authorization") or ""
    return (auth.decode() if isinstance(auth, bytes) else auth).startswith("AWS4-HMAC-SHA256 ")


def straight(request, headers, body):
    """The client's own call, for Bedrock: no header of ours leaves but one its signature covers, which a signed call keeps
    so that Bedrock still takes it. A replay never goes. `headers`, the request's own, changed in place."""
    if body is not None and is_replay(body):
        raise ReplayNotTaken("reflexer did not accept this replay, and the SDK never sends a replay to the provider")
    auth = headers.get("authorization") or ""
    signed = re.search(r"SignedHeaders=([^,\s]+)", auth.decode() if isinstance(auth, bytes) else auth)
    covered = set(signed[1].split(";")) if signed else set()
    for name in [name for name in headers if name.lower().startswith(OURS) and name.lower() not in covered]:
        del headers[name]
    return request


def lower(headers):
    return {name.lower(): value.decode() if isinstance(value, bytes) else value for name, value in headers.items()}


def skip_taken(event_name, kwargs, before):
    """The botocore family's per-call skip and the call's own headers for reflexer (`OPTION_HEADERS`), taken off where botocore would carry it to Bedrock, and kept in the call's
    context: the argument, from the call's parameters before botocore validates them (`provide-client-params`, before the
    client's own handlers); the header, from the request after the client's own `before-sign` handlers, before it is signed."""
    if before and event_name.startswith("provide-client-params.") and ARGUMENT in kwargs["params"]:
        given = kwargs["params"].pop(ARGUMENT)
        if not isinstance(given, bool):  # "false" too: a wrong value raises, before anything is sent
            raise ValueError(NOT_A_SKIP_ARGUMENT)
        kwargs["context"][SKIPPED_HERE] = given
    if before and event_name.startswith("before-sign."):
        request = kwargs["request"]
        request.context[UNSIGNED] = (request.url, request.data, lower(request.headers))
    if not before and event_name.startswith("before-sign."):
        request = kwargs["request"]
        request.context[SIGNER] = (kwargs.get("request_signer"), kwargs.get("operation_name"))
        ours = {name: ", ".join(text(each) for each in values) for name in OPTION_HEADERS if (values := request.headers.get_all(name))}  # every value, as the skip's
        checked(ours)  # a wrong value raises, two values too, before anything is sent
        request.context[GIVEN_HERE] = ours  # for reflexer's leg only
        for name in request.context[GIVEN_HERE]:
            del request.headers[name]
        given = request.headers.get_all(SKIP)  # every value, as a header held twice: read together, as httpx joins them
        if given and skips(", ".join(value.decode() if isinstance(value, bytes) else value for value in given)):  # a wrong value raises, before anything is sent
            request.context[SKIPPED_HERE] = True
        del request.headers[SKIP]


def botocore_route(reflexer, request):
    """A botocore call's way to reflexer, (url, headers), or None: only a call carrying a key or signed, not skipped, its
    body in memory (one that is not could not be sent twice)."""
    body = request.body if isinstance(request.body, bytes) else None
    headers = lower(request.headers)
    if body is None or not (keyed(headers) or signed(headers)) or (request.context or {}).get(SKIPPED_HERE):
        return None
    return reflexer.route(request.url, headers | (request.context or {}).get(GIVEN_HERE, {}), is_replay(body))


def signing_anew(request, unprepared):
    """The client's own botocore signer for a signed call after reflexer's leg, and what it signs: (signer, operation,
    the request as it came to `before-sign`), or None. botocore's signer takes a request before botocore prepares it
    (`unprepared`, botocore's `AWSRequest`), its context shared; the client's `before-sign` handlers run on it again, as on
    any attempt botocore signs, and a header set after signing stays unsigned, as stock."""
    signer, operation = (request.context or {}).get(SIGNER, (None, None))
    if signer is None or not signed(lower(request.headers)):
        return None
    url, data, headers = request.context[UNSIGNED]
    made = unprepared(request.method, url, data=data, headers=headers)
    made.context = request.context
    return signer, operation, made


def signed_anew(request, made):
    """The straight request as the client's own signer just made it anew, however long reflexer's leg took: its URL, body
    and headers, those set after signing kept."""
    prepared = made.prepare()
    request.url, request.body = prepared.url, prepared.body
    for name, value in prepared.headers.items():
        request.headers[name] = value


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
    """The shipped `Through`, for a Bedrock call: a call carrying a key goes to reflexer and falls back to the same call,
    straight; reflexer's leg is tried once more when TLS refused it while connecting. A signed call takes `signed_call`:
    here straight, as the library made it, as Mantle's: reflexer takes signed calls on Bedrock's runtime only; a line whose library signs
    Bedrock's runtime calls gives its own. Any other call goes straight (`straight`)."""

    def __init__(self, reflexer, inner):
        super().__init__(reflexer, inner)
        self.as_made = send = self.send

        def leg(request):  # reflexer's leg: the one request of ours not marked straight
            return send(request) if STRAIGHT in request.extensions else again_if_refused(lambda: send(request))

        async def aleg(request):
            return await (send(request) if STRAIGHT in request.extensions else aagain_if_refused(lambda: send(request)))

        self.send = aleg if inspect.iscoroutinefunction(inner.send) else leg

    def handle_request(self, request):
        checked(request.headers)  # a wrong value raises here, before anything is sent
        if keyed(request.headers):
            return super().handle_request(request)
        return (self.signed_call if signed(request.headers) else self.straight)(request)

    async def handle_async_request(self, request):
        checked(request.headers)
        if keyed(request.headers):
            return await super().handle_async_request(request)
        return await (self.asigned_call if signed(request.headers) else self.straight)(request)

    def straight(self, request):
        """The client's own call, as the library made it; a coroutine on an async client."""
        return self.as_made(straight(request, request.headers, body_of(request)))

    signed_call = asigned_call = straight


def setup_http_client(stock, wire, transport=Keyed):
    """The shipped `setup_http_client`, with Bedrock's transport, `Keyed` or a line's own."""

    def http_client(key, own=None, base=BASE, sample=1.0, namespace=None, answer=True, store=True, pass_through=False, timeout_ms=None):
        own = own or stock()
        inner = copy.copy(own)  # the client's own object stays as it was, for its other users; they share connections
        inner.event_hooks = {}  # they run once, above, and never see our key
        outer = type(own)(transport=transport(Reflexer(key, wire, base, sample, namespace=namespace, answer=answer, store=store, pass_through=pass_through, timeout_ms=timeout_ms), inner), event_hooks=own.event_hooks, auth=own.auth,
                          params=own.params, headers=own.headers, cookies=own.cookies.jar, timeout=own.timeout,
                          follow_redirects=own.follow_redirects, max_redirects=own.max_redirects, base_url=own.base_url)
        outer.reflexer_through = dict(key=key, base=base, sample=sample, namespace=namespace, answer=answer, store=store, pass_through=pass_through, timeout_ms=timeout_ms)  # what a copy given its own HTTP client is made with
        return outer

    return http_client
