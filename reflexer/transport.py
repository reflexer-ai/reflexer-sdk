"""The client's HTTP client, through reflexer, by the one extension point the HTTP library documents: a transport.

Two clients. The outer one is what the SDK holds: the client's hooks, auth, cookies and redirects, on the client's own
request, which never holds our key. Under it, `Through` sends each exchange by the inner one, a copy of the client's, so
its proxies, TLS and connections hold. No private name is read, no class of the SDK's or the library's changes, and no
answer is touched.
"""
import copy, functools, threading
from . import BASE, OURS, Reflexer, ReplayNotTaken, is_replay

STRAIGHT = "reflexer_straight"  # in a request's extensions: this call is the provider's, whatever it turns into
KEPT = ("timeout",)  # of a client's request extensions, what reflexer's request keeps: no callback of theirs sees our key


def setup_http_client(stock, wire):
    """What a provider file exports: a function making the HTTP client to give the SDK. `stock`, the SDK's own HTTP
    client when the client has none; `wire`, the provider file's data: see `Reflexer`."""

    def http_client(key, own=None, base=BASE, sample=1.0):
        own = own or stock()
        inner = copy.copy(own)  # the client's own object stays as it was, for its other users; they share connections
        inner.event_hooks = {}  # they run once, above, and never see our key
        outer = type(own)(transport=Through(Reflexer(key, wire, base, sample), inner),  # the rest: what the outer one acts on
                          event_hooks=own.event_hooks, auth=own.auth, params=own.params, headers=own.headers,
                          cookies=own.cookies.jar, timeout=own.timeout, follow_redirects=own.follow_redirects,
                          max_redirects=own.max_redirects, base_url=own.base_url)
        outer.reflexer_through = dict(key=key, base=base, sample=sample)  # what a copy given its own HTTP client is made with
        return outer

    return http_client


def setup_client(cls, make_http_client):
    """The one line: `cls(**config)` becomes `reflexer.cls(**config, reflexer_key=key)`. A subclass that only gives the SDK
    our HTTP client, by its public argument; the SDK's own copies (`with_options`) hand ours back in, with no key."""

    class Client(cls):
        def __init__(self, *args, reflexer_key=None, reflexer_base=BASE, sample=1.0, http_client=None, **config):
            if not hasattr(http_client, "reflexer_through"):
                http_client = make_http_client(reflexer_key, own=http_client, base=reflexer_base, sample=sample)
            self.reflexer_way = http_client.reflexer_through
            super().__init__(*args, http_client=http_client, **config)

        def copy(self, *args, http_client=None, **config):
            """The SDK's own copy. Given an HTTP client of the client's, it goes through reflexer the same way."""
            if http_client is not None and not hasattr(http_client, "reflexer_through"):
                http_client = make_http_client(**self.reflexer_way, own=http_client)
            return super().copy(*args, http_client=http_client, **config)

        with_options = copy

    Client.__name__ = Client.__qualname__ = cls.__name__
    return Client


def stays_straight(request):
    """The client's own call, for its provider: no header of ours leaves, and its redirects and auth rounds, which keep the
    mark, stay with its provider. A replay never does: the one call that cannot fall back."""
    if is_replay(body_of(request) or b""):
        raise ReplayNotTaken("reflexer did not take this replay, and a replay does not go to the provider")
    for name in dict(request.headers):
        if name.startswith(OURS):
            del request.headers[name]
    request.extensions[STRAIGHT] = True
    return request


def body_of(request):
    """Its bytes, or None for a body not read yet, which could not be sent twice, and is no failure of reflexer's."""
    try:
        return request.content
    except Exception:
        return None


def to_reflexer(reflexer, request):
    """The request as it goes to reflexer, or None. The client's own stays whole, for an auth round to send again."""
    body = body_of(request)
    route = None if STRAIGHT in request.extensions or body is None \
        else reflexer.route(str(request.url), dict(request.headers), is_replay(body))
    if route is None:
        return None
    url, headers = route
    same_library_request = type(request)  # httpx's or httpx2's: the client's own, never imported here
    kept = {name: value for name, value in request.extensions.items() if name in KEPT}  # the client's per-call timeout
    return same_library_request(request.method, url, headers=headers, content=body, extensions=kept)


class Through:
    """A transport, by duck typing: one HTTP exchange, going where the logic says. Whatever fails on the way to reflexer,
    the client's own call still goes. An answer cut after its headers left is read above, so it is an error as from the
    provider, never sent to the provider too."""

    def __init__(self, reflexer, inner):
        self.reflexer, self.inner = reflexer, inner
        self.send = functools.partial(inner.send, stream=True, follow_redirects=False, auth=None)
        self.flying, self.closing, self.lock = 0, False, threading.Lock()  # its calls in flight, counted when shared (`Both`)

    def landed(self, calls=-1):
        """Its calls in flight counted; whether its close, held for them, is now due."""
        with self.lock:
            self.flying += calls
            return self.closing and not self.flying

    def handle_request(self, request):
        try:
            ours = to_reflexer(self.reflexer, request)
            if ours is not None:
                answer = self.send(ours)
                if not self.reflexer.goes_straight(answer.status_code, answer.headers):
                    return without_its_cookie(answer)
                answer.close()
        except Exception as failure:
            self.reflexer.failed(failure)
        return self.send(stays_straight(request))

    async def handle_async_request(self, request):
        """`handle_request`, for an async client: the language asks for a second copy, not any provider."""
        try:
            ours = to_reflexer(self.reflexer, request)
            if ours is not None:
                answer = await self.send(ours)
                if not self.reflexer.goes_straight(answer.status_code, answer.headers):
                    return without_its_cookie(answer)
                await answer.aclose()
        except Exception as failure:
            self.reflexer.failed(failure)
        return await self.send(stays_straight(request))

    def close(self):
        """Its client's close, held until no call is in flight."""
        self.closing = True
        if self.landed(0):
            self.inner.close()

    async def aclose(self):
        self.closing = True
        if self.landed(0):
            await self.inner.aclose()

    def __enter__(self):
        return self

    def __exit__(self, *failure):
        self.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *failure):
        await self.aclose()


def landing(library, stream, through):
    """An answer's body as it came, of the library's own kind; its call landed on `through` once it is closed."""
    class Landing(library.SyncByteStream, library.AsyncByteStream):
        def __iter__(self):
            return iter(stream)

        def __aiter__(self):
            return stream.__aiter__()

        def close(self):
            try:
                stream.close()
            finally:
                through.landed() and through.inner.close()

        async def aclose(self):
            try:
                await stream.aclose()
            finally:
                through.landed() and await through.inner.aclose()
    return Landing()


def without_its_cookie(answer):
    """Reflexer's answer. The outer client would file its cookie under the provider's name, and send it there."""
    answer.headers.pop("set-cookie", None)
    return answer


class Both:
    """One transport for both of an SDK's HTTP clients, for what takes one set of arguments for the two (`client_args`).
    Its HTTP clients are made on first use, of the HTTP library the request is of: the SDK picks it, not this.
    `library_of(request)`, that library; `make(library)` and `make_async(library)`, a `Through` over a client of it.
    SDK clients made from one set of arguments share it: one closing closes its HTTP clients for the next call, each
    once its calls in flight land, so no client cuts another's call, as stock none would."""

    def __init__(self, library_of, make, make_async):
        self.library_of, self.makers, self.made = library_of, {False: make, True: make_async}, {False: {}, True: {}}
        self.lock = threading.Lock()  # threads at first use share one client

    def through(self, request, is_async=False):
        library, made = self.library_of(request), self.made[is_async]
        with self.lock:
            if library not in made:
                made[library] = self.makers[is_async](library)
            made[library].landed(+1)
            return made[library]

    def handle_request(self, request):
        through = self.through(request)
        try:
            answer = through.handle_request(request)
        except BaseException:
            landing(self.library_of(request), [], through).close()
            raise
        answer.stream = landing(self.library_of(request), answer.stream, through)
        return answer

    async def handle_async_request(self, request):
        through = self.through(request, is_async=True)
        try:
            answer = await through.handle_async_request(request)
        except BaseException:
            await landing(self.library_of(request), [], through).aclose()
            raise
        answer.stream = landing(self.library_of(request), answer.stream, through)
        return answer

    def out(self, is_async):
        with self.lock:
            out, self.made[is_async] = self.made[is_async].values(), {}
        return out

    def close(self):
        for through in self.out(False):
            through.close()

    async def aclose(self):
        for through in self.out(True):
            await through.aclose()

    def __repr__(self):  # what holds it may build a cache's key from its text
        return "reflexer.Both"
