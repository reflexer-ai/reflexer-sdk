"""aiobotocore's bedrock-runtime clients, through reflexer: `reflexer.aiobotocore.through(client, key)` on a client made
by `session.create_client("bedrock-runtime", ...)`, once entered. As `reflexer.boto3`, async: aiobotocore emits
`before-send` and awaits its handlers, ours after them all.

Reflexer's leg goes by the client's own aiohttp session, the one its endpoint sends by, with the client's connector,
proxy, TLS and timeouts, asked to follow no redirect: aiobotocore's own `send` follows them, our key on. No public name
reaches that session: `client._endpoint`'s `_get_session` and `_proxy_config`, read once, here; a release that renames
one fails this line as the client makes it, never a call.
"""
import asyncio
import yarl
import aiobotocore.awsrequest, aiobotocore.httpsession, botocore.awsrequest, botocore.exceptions
from . import BASE, Reflexer, supported
from .bedrock import BEDROCK, aagain_if_refused, answered, botocore_route, lower, skip_taken, straight

supported("aiobotocore", [3])
EVENT = "before-send."


def through(client, reflexer_key, base=BASE, sample=1.0):
    """Ours after every `before-send` handler of the client's, on its own emitter; reflexer's leg by its own aiohttp
    session. A client on another HTTP session class (`AioConfig(http_session_cls=...)`) raises here: its session takes
    no aiohttp request, and every call would go straight."""
    reflexer = Reflexer(reflexer_key, BEDROCK, base, sample)
    own, events = client._endpoint.http_session, client.meta.events
    if not isinstance(own, aiobotocore.httpsession.AIOHTTPSession):
        raise TypeError(f"reflexer's line takes aiobotocore's own aiohttp session, not {type(own).__name__}")
    if getattr(events, "reflexer_through", False):
        raise ValueError("this client already goes through reflexer")
    session_for, proxy_url_for, proxy_headers_for = own._get_session, own._proxy_config.proxy_url_for, own._proxy_config.proxy_headers_for
    emit = events.emit

    async def send(leg):
        """As aiobotocore's own `send` makes the request (a model call is a POST), by the session it would use, with no
        redirect followed, and the call's own read timeout, if it has one, as aiobotocore's own send takes it."""
        proxy = proxy_url_for(leg.url)
        session = await session_for(proxy)
        read = (leg.context or {}).get("read_timeout")
        timeout = {} if read is None else {"timeout": type(session.timeout)(sock_connect=session.timeout.sock_connect, sock_read=read)}
        response = await session.post(yarl.URL(leg.url, encoded=True), headers=lower(leg.headers) | {"accept-encoding": "identity"},
                                      data=leg.body, proxy=proxy, proxy_headers=proxy_headers_for(leg.url), allow_redirects=False, **timeout)
        headers = {name.decode().lower(): value.decode() for name, value in response.raw_headers}
        return aiobotocore.awsrequest.AioAWSResponse(str(response.url), response.status, headers, Answer(response))

    async def before_send(request):
        route = botocore_route(reflexer, request)
        if route is not None:
            leg = botocore.awsrequest.AWSRequest(request.method, route[0], data=request.body, headers=route[1], stream_output=True).prepare()
            leg.context = request.context  # the call's own settings for its session, such as a read timeout of its own
            try:
                answer = await aagain_if_refused(lambda: send(leg))
            except Exception as failure:
                reflexer.failed(failure)
            else:
                if not reflexer.goes_straight(answer.status_code, answer.headers):
                    return await read_served(answer, request)
                answer.raw.close()  # its body unread, its connection not reused
        straight(request, request.headers, request.body if isinstance(request.body, bytes) else None)
        return None

    async def emitted(event_name, **kwargs):
        skip_taken(event_name, kwargs, before=True)
        responses = await emit(event_name, **kwargs)
        skip_taken(event_name, kwargs, before=False)
        if event_name.startswith(EVENT) and not answered(responses):
            responses.append((before_send, await before_send(kwargs["request"])))
        return responses

    events.emit, events.reflexer_through = emitted, True
    return client


class Answer:
    """Reflexer's aiohttp answer, as aiobotocore reads a body, without the request it answered: aiohttp keeps that
    request's headers, our key among them, where a client's `after-call` handler and the body's stream would reach them."""

    def __init__(self, response):
        self.content, self.url, self.status = response.content, response.url, response.status
        self.read, self.close, self.release = response.read, response.close, response.release


async def read_served(answer, request):
    """Reflexer's answer, as aiobotocore's own session gives one: read here unless the client streams it. A body cut after
    its head is the client's error, as from the provider, never sent to the provider too."""
    if not request.stream_output:
        try:
            await answer.content
        except asyncio.TimeoutError as error:
            raise botocore.exceptions.ReadTimeoutError(endpoint_url=request.url, error=error) from None
        except Exception as error:
            raise botocore.exceptions.ConnectionClosedError(endpoint_url=request.url, error=error) from None
    return answer
