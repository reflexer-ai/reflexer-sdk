"""boto3's bedrock-runtime clients, through reflexer: `boto3.client("bedrock-runtime", **config)` becomes
`reflexer.boto3.client("bedrock-runtime", **config, reflexer_key=key)`; a client made elsewhere (a wrapper's), by
`reflexer.boto3.through(client, key)`. A call carrying a Bedrock API key goes to reflexer, and so does a signed one.

botocore has no public HTTP client option. Its documented `before-send` event "allows a response to be returned that
fulfills the request": botocore runs every handler of the event and takes the first answer, in its handlers' order. Ours
goes after them all, by the client's own emitter: when no handler of the client's answered (a stub, a cache), it sends
reflexer's leg, a copy of the request with our headers, by the client's own HTTP session, which fires no event and
follows no redirect; no answer of ours lets botocore send the client's own request, straight, a signed one signed anew
by the client's own signer, which botocore hands its `before-sign` handlers. Where can my key go? On the copy, to
reflexer's address only. My AWS credentials? Only the client's signer reads them, as stock.

The client's HTTP session is botocore's endpoint's, `client._endpoint`: no public name reaches it. Read once, here; a
release that renames it fails this line as the client makes it, never a call.
"""
import boto3, botocore.awsrequest, botocore.exceptions
import urllib3.exceptions
from . import BASE, Reflexer, log, supported
from .bedrock import BEDROCK, again_if_refused, answered, botocore_route, signed_anew, signing_anew, skip_taken, straight

supported("boto3", [1])
EVENT = "before-send."


def client(*args, reflexer_key=None, reflexer_base=BASE, sample=1.0, **config):
    """`boto3.client(*args, **config)`, through reflexer."""
    return through(boto3.client(*args, **config), reflexer_key, reflexer_base, sample)


def through(client, reflexer_key, base=BASE, sample=1.0):
    """Ours after every `before-send` handler of the client's, on its own emitter; reflexer's leg by its own HTTP session:
    its pool, proxies, TLS and timeouts."""
    reflexer = Reflexer(reflexer_key, BEDROCK, base, sample)
    send, events = client._endpoint.http_session.send, client.meta.events
    if getattr(events, "reflexer_through", False):  # twice, each call would try reflexer twice
        raise ValueError("this client already goes through reflexer")
    emit = events.emit

    def before_send(request):
        route = botocore_route(reflexer, request)
        if route is not None:
            leg = botocore.awsrequest.AWSRequest(request.method, route[0], data=request.body, headers=route[1], stream_output=True).prepare()
            leg.context = request.context  # the call's own settings for its session, such as a read timeout of its own
            try:
                answer = again_if_refused(lambda: send(leg))
            except Exception as failure:
                reflexer.failed(failure)
            else:
                if not reflexer.goes_straight(answer.status_code, answer.headers):
                    return read_served(answer, request)
                answer.raw.close()  # its body unread: one that stalls or breaks holds nothing up
        straight(request, request.headers, request.body if isinstance(request.body, bytes) else None)
        anew = route and signing_anew(request, botocore.awsrequest.AWSRequest)
        if anew:
            try:
                anew[0].sign(anew[1], anew[2])
                signed_anew(request, anew[2])
            except Exception as failure:  # the client's own signer failed anew: the call goes as it was first signed
                log.warning("signing the call anew failed (%s); it goes as first signed", type(failure).__name__)
        return None  # botocore sends it, straight

    def emitted(event_name, **kwargs):
        skip_taken(event_name, kwargs, before=True)
        responses = emit(event_name, **kwargs)
        skip_taken(event_name, kwargs, before=False)
        if event_name.startswith(EVENT) and not answered(responses):
            responses.append((before_send, before_send(kwargs["request"])))
        return responses

    events.emit, events.reflexer_through = emitted, True
    return client


def read_served(answer, request):
    """Reflexer's answer, as botocore's own session gives one: read here unless the client streams it. A body cut after its
    head is the client's error, as from the provider, never sent to the provider too: reflexer passed the call on."""
    if not request.stream_output:
        try:
            answer.content
        except urllib3.exceptions.ReadTimeoutError as error:
            raise botocore.exceptions.ReadTimeoutError(endpoint_url=request.url, error=error) from None
        except Exception as error:
            raise botocore.exceptions.ConnectionClosedError(endpoint_url=request.url, error=error) from None
    return answer
