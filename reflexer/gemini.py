"""google-genai's own client, through reflexer: `genai.Client(**config)` becomes `reflexer.gemini.Client(**config, reflexer_key=key)`.

Public names alone. The transport also goes by itself: `genai.Client(http_options={"httpx_client": reflexer.gemini.http_client(key)})`.
A served answer's model and id are at `model_version` and `response_id`; reflexer's price, at `sdk_http_response.headers`.
"""
import httpx, inspect
from google import genai
try:
    import httpx2
    LIBRARIES = (httpx2, httpx)  # either, as google-genai is set to use
except ImportError:
    LIBRARIES = (httpx,)
from . import BASE, Reflexer, supported
from .transport import Both, Through, closed_unless_its_loop_ended, setup_http_client
from .wires import GENERATE

supported("google-genai", [2])

http_client       = setup_http_client(httpx.Client,      GENERATE)
async_http_client = setup_http_client(httpx.AsyncClient, GENERATE)


def own_client(kind, given, arguments):
    """The HTTP client it would have built, by what it takes: `client_args` may hold what only aiohttp takes."""
    taken = {name: value for name, value in (arguments or {}).items() if name in inspect.signature(kind).parameters}
    return given or kind(**{"follow_redirects": True} | taken)


ABOVE = ("event_hooks", "auth", "params", "headers", "cookies", "timeout", "follow_redirects", "max_redirects", "base_url")  # what the outer client acts on


def library_of(request):
    return next((library for library in LIBRARIES if isinstance(request, library.Request)), httpx)


def client_args(key, own=None, base=BASE, sample=1.0, namespace=None, answer=True, store=True, pass_through=False, timeout_ms=None):
    """What to give as both `client_args` and `async_client_args`, for what builds its own `genai.Client` and takes only
    those. `own`, the client's own: split as `setup_http_client`
    splits a client, so its hooks run once, above, and never see our key. A transport given also keeps the SDK off aiohttp."""
    own, one = own or {}, Reflexer(key, GENERATE, base, sample, namespace=namespace, answer=answer, store=store, pass_through=pass_through, timeout_ms=timeout_ms)
    below = {name: value for name, value in own.items() if name not in ABOVE}
    above = {name: value for name, value in own.items() if name in ABOVE}
    return {"follow_redirects": True} | above | {"transport": Both(library_of, lambda library: Through(one, own_client(library.Client, None, below)),
                                                                   lambda library: Through(one, own_client(library.AsyncClient, None, below)))}


class Client(genai.Client):
    def __init__(self, *, reflexer_key, reflexer_base=BASE, sample=1.0, reflexer_namespace=None, reflexer_answer=True, reflexer_store=True,
                 reflexer_pass_through=False, reflexer_timeout_ms=None, http_options=None, **config):
        options = genai.types.HttpOptions.model_validate(http_options or {})
        way = dict(base=reflexer_base, sample=sample, namespace=reflexer_namespace, answer=reflexer_answer,
                 store=reflexer_store, pass_through=reflexer_pass_through, timeout_ms=reflexer_timeout_ms)
        self.reflexer_http = http_client(reflexer_key, own_client(httpx.Client, options.httpx_client, options.client_args), **way)
        self.reflexer_built = options.httpx_client is None
        self.reflexer_async_built = options.httpx_async_client is None
        self.reflexer_async_http = async_http_client(reflexer_key, options.httpx_async_client, **way) if options.httpx_async_client is not None \
            else httpx.AsyncClient(**client_args(reflexer_key, options.async_client_args, **way))  # one for each event loop, as stock's own
        super().__init__(http_options=options.model_copy(update={
            "httpx_client": self.reflexer_http, "httpx_async_client": self.reflexer_async_http,
        }), **config)
        self.aio.aclose = self.closing_async(self.aio.aclose)

    def closing_async(self, aclose):
        async def closing():
            await aclose()
            if self.reflexer_async_built:
                await closed_unless_its_loop_ended(self.reflexer_async_http)

        return closing

    def close(self):
        """It closes only what it built, and it was handed ours; a client's own stays the client's."""
        super().close()
        if self.reflexer_built:
            self.reflexer_http.close()
