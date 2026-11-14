"""Amazon Bedrock's promises (SECURITY.md), each checked through every Bedrock line on its real library, over the
acceptance suite's stand-ins in this process (real sockets and TLS, names resolved to this machine only), and each check
shown red under a planted fault; and what the lines read of another's package that no public name gives.
Offline, every key, credential and answer made up. Run: python -m unittest tests.test_bedrock"""
import asyncio, datetime, json, os, socket, sys, shutil, threading, time, traceback, types, unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path[:0] = [os.path.join(ROOT, "tests", "acceptance"), ROOT]
import harness, lines, scratch  # noqa: E402 the acceptance suite's stand-ins, lines and temp folders
from harness import bedrock, certs  # noqa: E402
import reflexer, reflexer.transport  # noqa: E402
import reflexer.aiobotocore, reflexer.anthropic_bedrock, reflexer.bedrock, reflexer.boto3, reflexer.litellm  # noqa: E402

import importlib.util  # noqa: E402
LINES = tuple(lib for lib in bedrock.SIGNING  # Bedrock's own lines: each library that can carry a key and sign; pydantic-ai's
              if lib != "pydantic-ai" or importlib.util.find_spec("pydantic_ai"))  # group is its own, as for the shipped lines
RUNTIME = tuple(lib for lib in LINES if lib != "anthropic-mantle")  # whose signed calls go to reflexer: the runtime's only
SIGNS_ANEW = tuple(lib for lib in RUNTIME if lib != "litellm")  # whose line reaches the library's own signer for the fallback
VOLATILE = {"authorization", "x-amz-date", "amz-sdk-invocation-id", "amz-sdk-request", "x-stainless-retry-count", "content-length",
            "x-stainless-read-timeout", "x-stainless-raw-response"}  # what differs between two calls made alike; the last, anthropic's with any middleware
SAVED = {}
TOKEN = "made-up-session-token-of-the-suite"  # a session token's place, made up
TIMEZONE = "America/Sao_Paulo"  # CI runs in UTC, where a signing time read as local time would pass unseen


def setUpModule():
    SAVED.update(socket=(socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex), env=dict(os.environ))
    folder = scratch.folder("bedrock")
    SAVED["folder"], SAVED["certs"] = folder, certs.Certs(folder, harness.NAMES)
    for name in bedrock.AMBIENT:
        os.environ.pop(name, None)
    os.environ.update(bedrock.ENVIRONMENT, SSL_CERT_FILE=SAVED["certs"].ca, AWS_CA_BUNDLE=SAVED["certs"].ca, TZ=TIMEZONE)
    if hasattr(time, "tzset"):
        time.tzset()
    SAVED["base"] = dict(os.environ)
    harness.resolver.install()


def tearDownModule():
    socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = SAVED["socket"]
    os.environ.clear()
    os.environ.update(SAVED["env"])
    if hasattr(time, "tzset"):
        time.tzset()
    shutil.rmtree(SAVED["folder"], ignore_errors=True)


def world(lib):
    """A world of stand-ins of its own, and its case (`harness.Test`) for a provider SDK, or its `bedrock.Calls`, as each acceptance case's process has. LiteLLM keeps its HTTP clients across
    calls, connected to the last world's stand-ins, and its line is the process's: both dropped, as a process of its own
    would start with neither. The last
    world's stand-ins are closed, as a case's process ends with them: a process holding every world's sockets passes
    the descriptor numbers a stand-in's `select` takes."""
    bedrock.without_litellms_line()
    for standin in SAVED.pop("standins", ()):
        standin._cut_connections()
        standin._close()
    for server in SAVED.pop("servers", ()):  # the last world's proxy: its loop ends within its poll, then its socket closes
        threading.Thread(target=lambda server=server: (server.shutdown(), server.server_close()), daemon=True).start()
    made = harness.World((SAVED["certs"].context(), SAVED["certs"].untrusted()))
    SAVED["standins"], SAVED["servers"] = [made.reflexer, made.provider, made.elsewhere, made.runner], [made.proxy.server]
    test = harness.Test(lines, lib, made)
    import logging
    logging.getLogger().removeHandler(test.logs)
    return made, (test if lib in harness.MODEL else bedrock.Calls(test))


SCENES = {"served": lambda w: w.reflexer.set("ok"), "busy": lambda w: w.reflexer.set("busy"), "dead": lambda w: w.reflexer.set("dead"),
          "redirected": lambda w: w.reflexer.set("redirect")}


def arrivals(keyed=True, scenes=SCENES):
    """{lib: [(who, arrival)]}: every request each stand-in got, a call made in each scene, through each line."""
    found = {}
    for lib in LINES:
        found[lib] = []
        for scene in scenes.values():
            made, calls = world(lib)
            scene(made)
            calls.call(calls.client(keyed=keyed))
            calls.close()
            found[lib] += [(who, arrival) for who, standin in (("reflexer", made.reflexer), ("bedrock", made.provider),
                                                                ("elsewhere", made.elsewhere)) for arrival in standin.seen]
    return found


def holding(found, secret):
    """{lib: the stand-ins any of whose requests held `secret`, in a header or the body}."""
    return {lib: sorted({who for who, arrival in seen if any(secret in value for value in arrival.headers.values())
                         or secret.encode() in (arrival.body or b"")}) for lib, seen in found.items()}


def signed_as_stock(scene=lambda w: w.reflexer.set("busy")):
    """{lib: whether a signed call, reflexer giving no answer, went to reflexer first (the runtime's) or never (Mantle's),
    and reached Bedrock taken, its signature holding, its headers and body as a stock client's but what differs between
    any two calls}."""
    found = {}
    for lib in LINES:
        made, calls = world(lib)
        outcome = calls.call(calls.client(line=False, keyed=False))
        assert made.provider.seen, f"{lib}: {outcome} {outcome.error!r}"
        stock = made.provider.seen[-1]
        scene(made)
        outcome = calls.call(calls.client(keyed=False))
        ours = made.provider.seen[-1]
        calls.close()
        kept = [{name: value for name, value in each.headers.items() if name not in VOLATILE and name != "user-agent"} for each in (ours, stock)]
        found[lib] = (outcome.text == harness.STRAIGHT_TEXT and bool(made.reflexer.seen) == (lib in RUNTIME)
                      and bedrock.signature_holds(ours) and ours.body == stock.body and kept[0] == kept[1])
    return found


def held_with_a_header_of_the_clients():
    """{lib: whether a signed call whose client sets a header in a `before-sign` handler of its own (as botocore's docs
    show) reached Bedrock taken, the header on it, reflexer busy}: the botocore family, whose fallback is signed anew."""
    found = {}
    for lib in ("boto3", "aiobotocore"):
        made, calls = world(lib)
        client = calls.client(keyed=False)
        client.meta.events.register("before-sign.bedrock-runtime.*", lambda request, **_: request.headers.__setitem__("X-Made-Up-Team", "made-up"))
        made.reflexer.set("busy")
        outcome = calls.call(client)
        calls.close()
        arrival = made.provider.seen[-1]
        found[lib] = (outcome.text == harness.STRAIGHT_TEXT and bedrock.signature_holds(arrival)
                      and arrival.headers.get("x-made-up-team") == "made-up")
    return found


def held_with_a_body_or_url_of_the_clients():
    """{(lib, what): whether a signed call whose client changes its body or its URL in a `before-sign` handler of its
    own reached Bedrock taken and changed once, as stock's, reflexer busy}: the botocore family, signing anew."""
    def body(request, **_):
        data = json.loads(request.data)
        request.data = json.dumps(data | {"system": data.get("system", []) + [{"text": "made-up house rule"}]}).encode()

    def url(request, **_):
        request.url += ("&" if "?" in request.url else "?") + "made-up-tag=1"
    found = {}
    for lib in ("boto3", "aiobotocore"):
        for what, handler in (("body", body), ("url", url)):
            made, calls = world(lib)
            client = calls.client(keyed=False)
            client.meta.events.register("before-sign.bedrock-runtime.*", handler)
            made.reflexer.set("busy")
            outcome = calls.call(client)
            calls.close()
            arrival = made.provider.seen[-1] if made.provider.seen else None
            once = arrival is not None and (len(json.loads(arrival.body).get("system", [])) == 1 if what == "body"
                                            else arrival.path.count("made-up-tag=1") == 1)
            found[(lib, what)] = outcome.text == harness.STRAIGHT_TEXT and once and bedrock.signature_holds(arrival)
    return found


def signing_times(delay=1.1):
    """{lib: (reflexer's x-amz-date, Bedrock's)}: a signed call whose leg to reflexer took `delay` seconds and no answer."""
    found = {}
    for lib in RUNTIME:
        made, calls = world(lib)
        made.reflexer.set("busy", delay=delay)
        calls.call(calls.client(keyed=False))
        calls.close()
        found[lib] = (made.reflexer.seen[-1].headers.get("x-amz-date"), made.provider.seen[-1].headers.get("x-amz-date"))
    return found


def async_anthropic_signing_times(delay=1.1):
    """AsyncAnthropicBedrock's signed call, reflexer busy after `delay` seconds: (reflexer's x-amz-date, Bedrock's, the text)."""
    made, _ = world("anthropic-bedrock")
    made.reflexer.set("busy", delay=delay)

    async def call():
        client = reflexer.anthropic_bedrock.AsyncAnthropicBedrock(aws_region=bedrock.REGION, aws_access_key=bedrock.ACCESS_KEY,
                                                                  aws_secret_key=bedrock.SECRET, max_retries=0, reflexer_key=made.key)
        answer = await client.messages.create(model=bedrock.MODEL, max_tokens=8, messages=[{"role": "user", "content": "Hi"}])
        await client.close()
        return answer.content[0].text
    text = asyncio.run(call())
    return made.reflexer.seen[-1].headers.get("x-amz-date"), made.provider.seen[-1].headers.get("x-amz-date"), text


def fallback_when_the_signer_fails():
    """boto3's signed call, reflexer busy, the client's signer failing when asked to sign it anew: (what the client saw,
    how many calls Bedrock got, whether the one it got carries the call's first signature)."""
    made, calls = world("boto3")
    client = calls.client(keyed=False)
    made.reflexer.set("busy")
    real, signed = client._request_signer.sign, []

    def sign(operation, request, **kwargs):
        if signed:
            raise RuntimeError("made-up: the signer failed")
        real(operation, request, **kwargs)
        signed.append(request.headers.get("authorization"))
    client._request_signer.sign = sign
    outcome = calls.call(client)
    return outcome.text, len(made.provider.seen), made.provider.seen[-1].headers.get("authorization") == signed[0]


def anthropic_attempts_with_no_leg(headers=None):
    """AnthropicBedrock's signed call sampled out of reflexer (share none), `headers` the call's own: (what the client
    saw, how many attempts its HTTP client's hooks saw, whether Bedrock took its signature)."""
    made, calls = world("anthropic-bedrock")
    seen = []
    client = reflexer.anthropic_bedrock.AnthropicBedrock(aws_region=bedrock.REGION, aws_access_key=bedrock.ACCESS_KEY, aws_secret_key=bedrock.SECRET,
                                                         max_retries=0, reflexer_key=made.key, sample=0.0,
                                                         http_client=reflexer.anthropic_bedrock.anthropic.DefaultHttpxClient(event_hooks={"request": [seen.append]}))
    try:
        text = client.messages.create(model=bedrock.MODEL, max_tokens=8, messages=[{"role": "user", "content": "Hi"}], extra_headers=headers).content[0].text
    except Exception as error:
        text = type(error).__name__
    arrival = made.provider.seen[-1] if made.provider.seen else None
    return text, len(seen), arrival is not None and bedrock.signature_holds(arrival)


def anthropic_error_after_a_leg():
    """AnthropicBedrock's signed call, reflexer busy, Bedrock unreachable: where the reflexer key is held in the frames of
    the error the client gets."""
    made, _ = world("anthropic-bedrock")
    made.reflexer.set("busy")
    made.provider.set("dead")
    client = reflexer.anthropic_bedrock.AnthropicBedrock(aws_region=bedrock.REGION, aws_access_key=bedrock.ACCESS_KEY, aws_secret_key=bedrock.SECRET,
                                                         max_retries=0, reflexer_key=made.key)
    try:
        client.messages.create(model=bedrock.MODEL, max_tokens=8, messages=[{"role": "user", "content": "Hi"}])
    except Exception as error:
        return in_clear(error, made.key)
    return ["no error"]


def anthropic_sampled_out(hook=None, provider="ok"):
    """AnthropicBedrock's signed call, with a session token, sampled out of reflexer, `hook` the client's own httpx request
    hook: (the headers of ours that reached Bedrock but its signature does not cover, whether Bedrock took it, where the
    error the client got, if any, shows the access key's id or the session token in clear in the frames; the last
    "no session token on the call" if none of its requests carried it)."""
    made, _ = world("anthropic-bedrock")
    made.provider.set(provider)
    tokens = []
    client = reflexer.anthropic_bedrock.AnthropicBedrock(aws_region=bedrock.REGION, aws_access_key=bedrock.ACCESS_KEY, aws_secret_key=bedrock.SECRET,
                                                         aws_session_token=TOKEN, max_retries=0, reflexer_key=made.key, sample=0.0,
                                                         http_client=reflexer.anthropic_bedrock.anthropic.DefaultHttpxClient(event_hooks={"request": [
                                                             *([hook] if hook else []), lambda request: tokens.append(request.headers.get("x-amz-security-token"))]}))
    shown = []
    try:
        client.messages.create(model=bedrock.MODEL, max_tokens=8, messages=[{"role": "user", "content": "Hi"}],
                               extra_headers={"Reflexer-Namespace": "made-up"})
    except Exception as error:
        shown = sorted({*in_clear(error, bedrock.ACCESS_KEY), *in_clear(error, TOKEN)})
    shown += [] if TOKEN in tokens else ["no session token on the call"]
    arrival = made.provider.seen[-1] if made.provider.seen else None
    if arrival is None:
        return None, False, shown
    signed = arrival.headers.get("authorization", "").partition("SignedHeaders=")[2].split(",")[0].split(";")
    return sorted(name for name in arrival.headers if name.startswith("reflexer-") and name not in signed), bedrock.signature_holds(arrival), shown


def per_attempt_change():
    """{lib: whether a signed call whose client's `before-sign` handler changes the body and the URL differently at each
    signing (a count of its runs) reached Bedrock taken, with the body and URL its signature covers}, reflexer busy."""
    found = {}
    for lib in ("boto3", "aiobotocore"):
        runs = []

        def handler(request, **_):
            runs.append(1)
            request.data = json.dumps(json.loads(request.data) | {"system": [{"text": f"made-up run {len(runs)}"}]}).encode()
            request.url = request.url.split("?")[0] + f"?made-up-run={len(runs)}"
        made, calls = world(lib)
        client = calls.client(keyed=False)
        client.meta.events.register("before-sign.bedrock-runtime.*", handler)
        made.reflexer.set("busy")
        outcome = calls.call(client)
        calls.close()
        arrival = made.provider.seen[-1] if made.provider.seen else None
        found[lib] = (outcome.text == harness.STRAIGHT_TEXT and arrival is not None and bedrock.signature_holds(arrival)
                      and json.loads(arrival.body)["system"] == [{"text": f"made-up run {len(runs)}"}] and arrival.path.endswith(f"?made-up-run={len(runs)}"))
    return found


LITELLM_WINDOW = 2.0  # seconds: the signature window the LiteLLM cases shorten AWS's five minutes to


def litellm_leg(seconds=LITELLM_WINDOW, margin=0.5, is_async=False):
    """LiteLLM's signed call, reflexer stalled, the window shortened to `seconds` at Bedrock's stand-in and in the line:
    (what the client saw, the seconds it took, whether Bedrock took it). `is_async`: by `acompletion` and its line."""
    import time, litellm
    made, calls = world("litellm")
    made.provider.window = seconds
    made.reflexer.set("stall")
    with mock.patch.dict(reflexer.litellm.WINDOW, seconds=seconds, margin=margin):
        began = time.monotonic()
        if is_async:
            given = calls.client(keyed=False, timeout=10 * seconds)
            try:
                text = asyncio.run(litellm.acompletion(model=f"bedrock/converse/{bedrock.MODEL}", messages=[{"role": "user", "content": "Hi"}],
                                                       max_tokens=8, **given)).choices[0].message.content
            except Exception:
                text = None
        else:
            text = calls.call(calls.client(keyed=False, timeout=10 * seconds)).text
    return text, time.monotonic() - began, bool(made.provider.seen) and made.provider.seen[-1].headers.get("authorization", "")[:4] == "AWS4"


def reached_bedrock_after(scene, extra=None):
    """{lib: what the client saw}, a call reflexer cannot take, `extra` the body's own fields."""
    found = {}
    for lib in LINES:
        made, calls = world(lib)
        scene(made)
        op = {"boto3": "invoke", "aiobotocore": "invoke"}.get(lib, calls.lib.ops[0])
        outcome = calls.call(calls.client(), op, extra=extra)
        calls.close()
        found[lib] = (outcome.text, bool(made.provider.seen))
    return found


REPLAYING = ("boto3", "aiobotocore", "anthropic-bedrock", "anthropic-mantle")  # those whose calls take a field at the body's top


def empty_answer_calls():
    """(lib, keyed, op): each line's every message call, carrying a key, and signed where its signed calls go to reflexer. Not
    aiobotocore's streamed ones: on an empty 204 its own event-stream reader can loop without end, as stock, with no
    reflexer in the way."""
    return [(lib, keyed, op) for lib in LINES for keyed in ((True, False) if lib in RUNTIME else (True,))
            for op in bedrock.LIBS[lib].ops if op != "count_tokens" and not (lib == "aiobotocore" and op in bedrock.STREAMED_OPS)]


def signed_replays_reaching_bedrock():
    """{lib: whether a signed call carrying a replay reached Bedrock}, reflexer busy."""
    found = {}
    for lib in REPLAYING:
        made, calls = world(lib)
        SCENES["busy"](made)
        calls.call(calls.client(keyed=False), {"boto3": "invoke", "aiobotocore": "invoke"}.get(lib, calls.lib.ops[0]),
                   extra={"replay_response": {"id": "made-up"}})
        calls.close()
        found[lib] = bool(made.provider.seen)
    return found


def after_signing(client):
    """A `before-send` handler of the client's, first of all, putting a header of ours on the call after it is signed."""
    def add(request, **_):
        request.headers["Reflexer-Namespace"] = "made-up"
    client.meta.events.register_first("before-send.bedrock-runtime.*", add)


def ours_on_signed_calls():
    """{(lib, how): (the headers of ours that reached Bedrock but the signature does not cover, whether it held)}: a
    signed call given a namespace of ours, where each library puts a call's headers, and on boto3 also after signing."""
    found = {}
    for lib, how in [(lib, "call") for lib in LINES] + [("boto3", "after signing"), ("aiobotocore", "after signing")]:
        made, calls = world(lib)
        SCENES["busy"](made)  # a signed call on Bedrock's runtime goes to reflexer first: here, its fallback
        client = calls.client(keyed=False)
        if how == "after signing":
            after_signing(client)
        calls.call(client, headers={"Reflexer-Namespace": "made-up"} if how == "call" else None)
        calls.close()
        arrival = made.provider.seen[-1]
        signed = arrival.headers.get("authorization", "").partition("SignedHeaders=")[2].split(",")[0].split(";")
        found[(lib, how)] = (sorted(name for name in arrival.headers if name.startswith("reflexer-") and name not in signed),
                             bedrock.signature_holds(arrival))
    return found


SDK = os.path.join(os.path.abspath(ROOT), "reflexer") + os.sep  # the SDK's own files: their frames' locals are followed
TESTS = os.path.join(os.path.abspath(ROOT), "tests") + os.sep


def holders(roots, secret, most=500000, beside=()):
    """The paths by which `secret` is reached from `roots`, following every object reference (`gc.get_referents`): a
    bound method's object, a function's closure, defaults and attributes (`__wrapped__` among them), and the locals of the SDK's own frames, a traceback's
    among them; not into modules, classes, code, a function's globals or another's frames, which are the program's own,
    nor into `beside`: what the client made with the key, which holds it as given. Past `most` objects it fails: a walk
    cut short proves nothing."""
    import gc
    seen, pending, found = {id(each) for each in beside}, [(root, "root") for root in roots], []
    while pending:
        if len(seen) >= most:
            raise AssertionError(f"the walk passed {most} objects, unfinished")
        thing, path = pending.pop()
        if id(thing) in seen:
            continue
        seen.add(id(thing))
        if isinstance(thing, (str, bytes, bytearray)):
            found += [path] if (secret in thing if isinstance(thing, str) else secret.encode() in thing) else []
            continue
        kind = type(thing).__name__
        if isinstance(thing, type) or kind in ("module", "code"):
            continue
        if kind == "function":
            held = [cell.cell_contents for cell in thing.__closure__ or () if cell_holds(cell)]
            held += list(thing.__defaults__ or ()) + list((thing.__kwdefaults__ or {}).values()) + list(vars(thing).values())
        elif kind == "frame":
            held = list(thing.f_locals.values()) if os.path.abspath(thing.f_code.co_filename).startswith(SDK) else []
        else:
            held = gc.get_referents(thing)
        pending += [(each, f"{path}>{type(each).__name__}") for each in held]
    return found


def cell_holds(cell):
    try:
        cell.cell_contents
        return True
    except ValueError:  # empty
        return False


def in_clear(error, secret, own=()):
    """The locals of every frame but the tests' own, the SDK's and its libraries', on an error's traceback and those it
    chains, that show `secret` as an error tracker capturing locals writes them: by their `repr`, a container's holding
    its items'. The line's own state stays reachable from them, as the client's HTTP client holds it; what such a tracker
    ships is what is written. `own`: the client's own requests, which show their signature as a stock client's frames
    show them, so a local shows the secret only past them."""
    def shows(value, within=()):
        if any(value is each for each in own) or id(value) in within:  # a container holding itself: shown once
            return False
        if type(value) is dict:
            return secret in repr(list(value)) or any(shows(each, (*within, id(value))) for each in value.values())
        if type(value) in (list, tuple, set):
            return any(shows(each, (*within, id(value))) for each in value)
        return secret in repr(value)

    found, seen, pending = [], set(), [error]
    while pending:
        each = pending.pop()
        if each is None or id(each) in seen:
            continue
        seen.add(id(each))
        pending += [each.__context__, each.__cause__]
        step = each.__traceback__
        while step is not None:
            frame = step.tb_frame
            if not os.path.abspath(frame.f_code.co_filename).startswith(TESTS):
                found += [f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_code.co_name}.{name}" for name, value in frame.f_locals.items() if shows(value)]
            step = step.tb_next
    return sorted(set(found))


class Stop(BaseException):
    """Made up: what is not an `Exception`, raised as reflexer's leg is sent, as gevent's `Timeout` or a ^C is."""


def asked(arrange, op=None, extra=None):
    """A scene: reflexer arranged, a call made (`op`, with its own fields), whose error the client gets. `client()` makes
    the client."""
    def scene(made, calls, client):
        arrange(made)
        given = op if op in calls.lib.ops else ("messages" if "messages" in calls.lib.ops else calls.lib.ops[0])
        return calls.call(client(), given, extra=extra).error
    return scene


def deadline(made, calls, client):
    """A scene: the client's own deadline (`asyncio.wait_for`) cancels its call while reflexer stalls."""
    made.reflexer.set("stall")
    client = client()
    try:
        calls.run(asyncio.wait_for(calls.lib.call(client, calls.lib.ops[0], None, None, None), 0.5))
    except asyncio.TimeoutError as error:
        return error


def stopped(made, calls, client):
    """A scene: a `BaseException` raised in urllib3 as reflexer's leg is sent."""
    import urllib3.connectionpool
    real, client = urllib3.connectionpool.HTTPConnectionPool._make_request, client()

    def stopping(pool, *args, **kwargs):
        if pool.host in harness.REFLEXER_NAMES:
            raise Stop()
        return real(pool, *args, **kwargs)
    with mock.patch.object(urllib3.connectionpool.HTTPConnectionPool, "_make_request", stopping):
        try:
            calls.run(calls.lib.call(client, calls.lib.ops[0], None, None, None))
        except Stop as error:
            return error


def stopped_counting(made, calls, client):
    """A scene: reflexer down, a `BaseException` lands as the SDK counts its leg's failure (in its log's handler, say)."""
    made.reflexer.set("dead")
    client = client()
    with mock.patch.object(reflexer.Reflexer, "failed", lambda *_: stop()):
        try:
            calls.run(calls.lib.call(client, calls.lib.ops[0], None, None, None))
        except Stop as error:
            return error


ERRORS = {  # scene: (the call, raising to the client, the line having taken it; the libraries it is made on)
    "cut": (asked(lambda w: w.reflexer.set("cut")), ("boto3", "aiobotocore", "anthropic-bedrock", "litellm")),
    "replay, reflexer busy": (asked(lambda w: w.reflexer.set("busy"), "invoke", {"replay_response": {"id": "made-up"}}),
                              ("boto3", "aiobotocore", "anthropic-bedrock", "anthropic-mantle", "anthropic-compat", "openai-compat")),
    "the client's deadline, reflexer stalled": (deadline, ("aiobotocore",)),
    "not an Exception, in the leg": (stopped, ("boto3",)),
    "not an Exception, as the leg's failure is counted": (stopped_counting, ("boto3", "aiobotocore")),
}
SIGNED_ERRORS = {"boto3", "aiobotocore", "anthropic-bedrock"}  # whose signed call also raises in a scene but "cut", which falls back


def scene_client(calls, keyed, own):
    """A scene's client: keyed, or signed with a session token; the botocore family's own requests and their headers kept
    in `own`, as they reach its `before-send` handlers."""
    def client():
        made = calls.client(keyed=keyed, **({} if keyed else {"session_token": TOKEN}))
        if calls.lib.botocore:
            made.meta.events.register("before-send", lambda request, **_: own.extend((request, request.headers)))
        return made
    return client


def token_carried(made, own):
    """Whether a signed scene's call carried its session token: on the client's own request, or as reflexer or Bedrock got it."""
    arrived = [arrival.headers.get("x-amz-security-token") for arrival in (*made.reflexer.seen, *made.provider.seen)]
    return TOKEN in arrived or any(TOKEN in repr(each) for each in own)


HTTPX = ("anthropic-bedrock", "anthropic-mantle", "litellm", "anthropic-compat", "openai-compat", "gemini")  # the lines on httpx:
# Bedrock's (`Keyed`), and the shipped ones (`Through`), Gemini's at its own route
LONG = 60  # seconds: past every deadline of a scene's
DEADLINE = 0.5  # seconds: a client's own deadline on a call reflexer stalls


def on_httpx(lib, key, keyed, is_async, http2):
    """An httpx line's call, as a client makes it (a coroutine when async), its client closed after it: with a Bedrock API
    key, or on anthropic's Bedrock client signed with a session token; its own HTTP client on HTTP/2 when asked, LiteLLM's
    by LiteLLM's own setting."""
    import anthropic, httpx, litellm, openai
    import reflexer.anthropic, reflexer.gemini, reflexer.openai
    message, prefix = [{"role": "user", "content": bedrock.TEXT}], "Async" if is_async else ""
    if lib == "litellm":
        os.environ["LITELLM_HTTP2"] = str(http2)
        reflexer.litellm.through(key)  # after the setting: LiteLLM's clients under the line are made by it
        given = dict(model=f"bedrock/converse/{bedrock.MODEL}", messages=message, max_tokens=8, aws_region_name=bedrock.REGION,
                     api_key=bedrock.BEARER, num_retries=0, timeout=LONG)
        async def undone():
            bedrock.without_litellms_line()
        return closing(lambda: (litellm.acompletion if is_async else litellm.completion)(**given), undone if is_async else bedrock.without_litellms_line, is_async)
    if lib == "gemini":
        own = {f"httpx{'_async' if is_async else ''}_client": getattr(httpx, f"{prefix}Client")(http2=True)} if http2 else {}
        client = reflexer.gemini.Client(api_key="made-up", reflexer_key=key, http_options=own)
        return closing(lambda: (client.aio if is_async else client).models.generate_content(model="made-up", contents=bedrock.TEXT),
                       client.aio.aclose if is_async else client.close, is_async)
    sdk = openai if lib == "openai-compat" else anthropic
    own = {"http_client": getattr(sdk, f"Default{prefix}HttpxClient")(http2=True)} if http2 else {}
    if lib.endswith("-compat"):
        made = {"base_url": f"https://{bedrock.RUNTIME}/{'openai/v1' if sdk is openai else 'anthropic'}", "api_key": bedrock.BEARER}
        client = getattr(reflexer.openai if sdk is openai else reflexer.anthropic, f"{prefix}{'OpenAI' if sdk is openai else 'Anthropic'}")
    else:
        made = {"aws_region": bedrock.REGION} | ({"api_key": bedrock.BEARER} if keyed else {
            "aws_access_key": bedrock.ACCESS_KEY, "aws_secret_key": bedrock.SECRET, "aws_session_token": TOKEN})
        client = getattr(reflexer.anthropic_bedrock, f"{prefix}AnthropicBedrock{'Mantle' if lib == 'anthropic-mantle' else ''}")
    client = client(**made, **own, max_retries=0, reflexer_key=key)
    if sdk is openai:
        return closing(lambda: client.chat.completions.create(model=bedrock.MODEL, messages=message), client.close, is_async)
    return closing(lambda: client.messages.create(model=bedrock.MODEL, max_tokens=8, messages=message), client.close, is_async)


def closing(call, close, is_async):
    """`call`, then `close` (a coroutine function when async, run in the call's own event loop), whatever the call raised:
    the scenes' clients left open would hold the process's descriptors."""
    import contextlib

    def ran():
        try:
            return call()
        finally:
            with contextlib.suppress(Exception):
                close()

    async def aran():
        try:
            return await call()
        finally:
            with contextlib.suppress(Exception):
                await close()
    return aran if is_async else ran


def at_our_headers(sync, carried, asynced=None):
    """httpcore's network streams patched, httpcore's and httpcore2's, sync and async: as one writes reflexer's leg's request
    headers, HTTP/1.1's or HTTP/2's (`_send_request_headers` below it, for reflexer's host), `sync()` runs on a sync
    stream, and on an async one `asynced()` is awaited (by default, the call waits past its client's deadline). Their
    headers' text kept in `carried`."""
    import contextlib, httpcore, httpcore2

    def ours():
        frame = sys._getframe(2)
        while frame is not None and frame.f_code.co_name != "_send_request_headers":
            frame = frame.f_back
        request = frame and frame.f_locals.get("request")
        if request is not None and request.url.host.decode() in harness.REFLEXER_NAMES:
            carried.append(repr(request.headers))
            return True
        return False

    def write(real):
        return lambda stream, *args, **kwargs: (ours() and sync()) or real(stream, *args, **kwargs)

    def awrite(real):
        async def written(stream, *args, **kwargs):
            if ours():
                await (asynced or hold)()
            return await real(stream, *args, **kwargs)
        return written
    patched = contextlib.ExitStack()
    for core in (httpcore, httpcore2):
        patched.enter_context(mock.patch.object(core._backends.sync.SyncStream, "write", write(core._backends.sync.SyncStream.write)))
        patched.enter_context(mock.patch.object(core._backends.anyio.AnyIOStream, "write", awrite(core._backends.anyio.AnyIOStream.write)))
    return patched


def stop():
    raise Stop()


async def hold():
    await asyncio.sleep(LONG)


async def cancel():
    """The client cancels its call (`task.cancel()`) here."""
    asyncio.current_task().cancel()
    await hold()


def fail():
    raise OSError("made up")


async def afail():
    fail()


def deadline_of(call):
    """The error the client's own deadline (`asyncio.wait_for`) raises on its call."""
    async def called():
        await asyncio.wait_for(call(), DEADLINE)
    try:
        asyncio.run(called())
    except asyncio.TimeoutError as error:
        return error


def stopped_at_our_headers(made, call, carried):
    """A scene, sync: a `BaseException` raised as reflexer's leg writes its request headers, as gevent's `Timeout` or a ^C is."""
    with at_our_headers(stop, carried):
        try:
            call()
        except Stop as error:
            return error


def cancelled_of(call):
    """The error the client gets cancelling its call (`asyncio.run` raising the cancel)."""
    try:
        asyncio.run(call())
    except asyncio.CancelledError as error:
        return error


def cancelled_at_our_headers(made, call, carried):
    """A scene, async: the client cancels its call as reflexer's leg writes its request headers."""
    with at_our_headers(None, carried, cancel):
        return cancelled_of(call)


def stopped_counting_a_failure(made, call, carried):
    """A scene, sync: reflexer's leg fails at its header write, and a `BaseException` lands as the SDK counts that failure
    (in its log's handler, say)."""
    with at_our_headers(fail, carried), mock.patch.object(reflexer.Reflexer, "failed", lambda *_: stop()):
        try:
            call()
        except Stop as error:
            return error


def cancelled_handling_a_failure(made, call, carried):
    """A scene, async: reflexer's leg fails at its header write, and the client cancels its call while a library below the
    leg handles that failure, as LiteLLM's aiohttp transport does retrying a session found closed."""
    import contextlib, httpcore, httpcore2

    def handling(real):
        async def handled(pool, *args, **kwargs):
            try:
                return await real(pool, *args, **kwargs)
            except OSError:
                await cancel()
        return handled
    with at_our_headers(None, carried, afail), contextlib.ExitStack() as patched:
        for core in (httpcore, httpcore2):
            patched.enter_context(mock.patch.object(core.AsyncConnectionPool, "handle_async_request",
                                                    handling(core.AsyncConnectionPool.handle_async_request)))
        return cancelled_of(call)


def deadline_while_stalled(made, call, carried):
    """A scene, async: the client's own deadline cancels its call while reflexer stalls."""
    made.reflexer.set("stall")
    return deadline_of(call)


HTTPX_ERRORS = {  # scene: (the call, raising to the client; whether its client is async, and whether it runs on HTTP/2 too)
    "not an Exception, at the header write": (stopped_at_our_headers, False, True),
    "the client's cancel, at the header write": (cancelled_at_our_headers, True, True),
    "the client's deadline, reflexer stalled": (deadline_while_stalled, True, False),  # the stand-ins speak HTTP/1.1 only
    "not an Exception, as the leg's failure is counted": (stopped_counting_a_failure, False, True),
    "the client's cancel, as a library below handles the leg's failure": (cancelled_handling_a_failure, True, True),
}


def httpx_scenes():
    """(lib, scene, keyed, is_async, http2): each httpx line in each scene, and a signed call where `SIGNED_ERRORS` has one."""
    for scene, (made_by, is_async, on_http2) in HTTPX_ERRORS.items():
        for lib in HTTPX:
            for http2 in (False, True) if on_http2 else (False,):
                if lib == "litellm" and is_async and made_by is not deadline_while_stalled and not http2:
                    continue  # by aiohttp on HTTP/1.1, whose writes these scenes do not reach: its scene, reflexer stalled
                for keyed in (True, False) if lib in SIGNED_ERRORS else (True,):
                    yield lib, scene, keyed, is_async, http2


def errors_in_clear():
    """{(lib, scene, keyed): the frames' locals on the error the client got showing the key, or on a signed call the
    access key's id (on its signature's header) or the session token past the client's own request} (empty: none),
    through the Bedrock lines and the shipped lines at Bedrock's routes, and the httpx lines each sync and async and on
    HTTP/1.1 and HTTP/2 (Gemini's at its own route)."""
    found = {}
    for scene, (made_by, libs) in ERRORS.items():
        for lib, keyed in [(lib, True) for lib in libs] + [(lib, False) for lib in libs if lib in SIGNED_ERRORS and scene != "cut"]:
            made, calls = world(lib)
            own = []
            error = made_by(made, calls, scene_client(calls, keyed, own))
            calls.close()
            found[(lib, scene, keyed)] = shown(error, made, keyed, own, own)
    for lib, scene, keyed, is_async, http2 in httpx_scenes():
        made, _ = world(lib if lib in bedrock.LIBS else "openai-compat")  # Gemini's stand-ins: any line's
        if http2:
            made.reflexer.context.set_alpn_protocols(["h2", "http/1.1"])  # the world's stand-ins, reflexer's among them, take HTTP/2
        carried, made_by = [], HTTPX_ERRORS[scene][0]
        error = made_by(made, on_httpx(lib, made.key, keyed, is_async, http2), carried)
        landed = made.reflexer.seen if made_by is deadline_while_stalled else carried  # the scene ran where it says
        found[(lib, f"{scene}{', HTTP/2' if http2 else ''}{', async' if is_async else ''}", keyed)] = \
            shown(error, made, keyed, (), carried) + ([] if landed else ["the scene did not land on reflexer's leg"])
    return found


def shown(error, made, keyed, own, carried):
    """What the frames' locals on `error` show (`errors_in_clear`); `carried`, what of the call the line sent, beside
    what reached the stand-ins, to check a signed call carried its session token."""
    if error is None:
        return ["no error raised"]
    signed = [] if keyed else [*in_clear(error, bedrock.ACCESS_KEY, own), *in_clear(error, TOKEN, own),
                               *([] if token_carried(made, carried) else ["no session token on the call"])]
    return sorted({*in_clear(error, harness.make_key()), *signed})


def what_the_client_is_handed():
    """{lib: where the reflexer key is held in what a served call hands the client: its `after-call` handler's response,
    and the answer it returns, a body's raw stream within}."""
    found = {}
    for lib in ("boto3", "aiobotocore"):
        made, calls = world(lib)
        client, handed = calls.client(), []
        client.meta.events.register("after-call.bedrock-runtime", lambda http_response=None, **_: handed.append(http_response))
        out, message = {}, [{"role": "user", "content": [{"text": bedrock.TEXT}]}]

        async def answered():
            out["answer"] = await client.invoke_model(modelId=bedrock.MODEL, body=bedrock.invoke_body(None))
            out["stream"] = await client.converse_stream(modelId=bedrock.MODEL, messages=message)  # its body still to read
        if calls.loop:
            calls.run(answered())
        else:
            out["answer"] = client.invoke_model(modelId=bedrock.MODEL, body=bedrock.invoke_body(None))
            out["stream"] = client.converse_stream(modelId=bedrock.MODEL, messages=message)
        found[lib] = holders([handed, out], harness.make_key())
        calls.close()
    return found


HTTPX_LINES = (("openai", False), ("openai", True), ("anthropic", False), ("anthropic", True), ("gemini", False), ("gemini", True),
               ("anthropic-bedrock", False))


def what_an_httpx_line_hands_the_client():
    """{(sdk, is_async): (where the reflexer key is held in what a served call hands the client, the text it then reads)},
    on each line over the HTTP library: the answer, and the streamed one before its body is read, with the response and
    its request, body stream and extensions within; and each response a response hook of the client's receives. The
    SDK client, its HTTP clients and its `Reflexer`, which the client made with the key, are not walked into."""
    import gc, httpx, httpx2
    found = {}
    for sdk, is_async in HTTPX_LINES:
        hooked, out = [], {}

        async def ahook(response):
            hooked.append(response)
        http = {"event_hooks": {"response": [ahook if is_async else hooked.append]}}
        made, t = world(sdk)
        if sdk == "anthropic-bedrock":
            client = reflexer.anthropic_bedrock.AnthropicBedrock(aws_region=bedrock.REGION, api_key=bedrock.BEARER, max_retries=0, reflexer_key=made.key,
                                                                 http_client=reflexer.anthropic_bedrock.anthropic.DefaultHttpxClient(**http))
            t = types.SimpleNamespace(sdk="anthropic")
        else:
            client = t.client(is_async, http=http)
        made.reflexer.set("ok")

        async def answered():
            out["answer"] = await harness.request(t.sdk, client, True, False, {})
            out["stream"] = await harness.request(t.sdk, client, True, True, {})
        if is_async:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(answered())
        else:
            out["answer"] = harness.request(t.sdk, client, False, False, {})
            out["stream"] = harness.request(t.sdk, client, False, True, {})
        ours = (reflexer.Reflexer, httpx.Client, httpx.AsyncClient, httpx2.Client, httpx2.AsyncClient)
        beside = [client] + [each for each in gc.get_objects() if issubclass(type(each), ours)]  # by type: a dead weak proxy raises on isinstance
        where = holders([hooked, out], made.key, beside=beside)
        async def streamed():
            return [chunk async for chunk in out["stream"]]
        chunks = loop.run_until_complete(streamed()) if is_async else list(out["stream"])
        if is_async:
            loop.close()
        found[(sdk, is_async)] = (where, bool(harness.text_of(t.sdk, out["answer"])) and bool(chunks))
    return found


def straight_within(seconds):
    """{lib: whether a call whose own read timeout (`read_timeout` in its context, set by a handler of the client's)
    is `seconds` went straight within twice it, reflexer stalled and the client's config allowing minutes}."""
    import time
    found = {}
    for lib in ("boto3", "aiobotocore"):
        made, calls = world(lib)
        client = calls.client(timeout=60)
        client.meta.events.register_first("before-send.bedrock-runtime.*", lambda request, **_: request.context.update(read_timeout=seconds))
        made.reflexer.set("stall")
        began = time.monotonic()
        outcome = calls.call(client)
        found[lib] = outcome.text == harness.STRAIGHT_TEXT and bool(made.reflexer.seen) and time.monotonic() - began < 2 * seconds + 1
        calls.close()
    return found


class Case(unittest.TestCase):
    """Each test starts from the module's environment: a harness client sets a Bedrock API key's variable, which a client
    made after it, in the same process, would take."""

    def setUp(self):
        os.environ.clear()
        os.environ.update(SAVED["base"])


class Promises(Case):
    def test_through_each_bedrock_line_the_key_reaches_only_reflexer(self):
        for lib, who in holding(arrivals(), harness.make_key()).items():
            with self.subTest(lib=lib):
                self.assertEqual(who, ["reflexer"])

    def test_a_bedrock_key_or_signature_reaches_only_bedrock_or_reflexer_and_the_secret_no_one(self):
        keyed, signed = arrivals(), arrivals(keyed=False)
        for lib in LINES:
            with self.subTest(lib=lib):
                self.assertEqual(holding(keyed, bedrock.BEARER)[lib], ["bedrock", "reflexer"])
                self.assertEqual(holding(signed, "AWS4-HMAC-SHA256")[lib], ["bedrock", "reflexer"] if lib in RUNTIME else ["bedrock"])
                self.assertEqual(holding(signed, bedrock.BEARER)[lib] + holding(keyed, bedrock.SECRET)[lib] + holding(signed, bedrock.SECRET)[lib], [])

    def test_the_skip_header_true_skips_false_does_not_another_value_raises_and_none_leaves(self):
        """`Reflexer-Skip`, in any case, on a keyed call through each line: true goes straight, false goes to reflexer, any
        other value raises before anything is sent; the header reaches neither reflexer nor Bedrock."""
        for lib in LINES:
            for value, to_reflexer in (("TRUE", False), ("False", True), ("yes", None)):
                with self.subTest(lib=lib, value=value):
                    made, calls = world(lib)
                    outcome = calls.call(calls.client(), headers={"Reflexer-Skip": value})
                    everything = made.reflexer.seen + made.provider.seen
                    if to_reflexer is None:  # the ValueError, or the library's connection error that it causes
                        raised = [each for each in reflexer.bedrock.chain(outcome.error) if isinstance(each, ValueError)]
                        self.assertEqual([str(each) for each in raised][-1:], [reflexer.NOT_A_SKIP], repr(outcome.error))
                        self.assertEqual(everything, [])
                        continue
                    self.assertIsNone(outcome.error)
                    self.assertEqual(bool(made.reflexer.seen), to_reflexer)
                    self.assertEqual([arrival for arrival in everything if reflexer.SKIP in {name.lower() for name in arrival.headers}], [])

    def test_the_skip_header_repeated_on_botocore_raises_as_its_values_joined_do_and_none_leaves(self):
        """A header botocore holds twice, set by the client's own `before-sign` handler: its values are read together, as
        httpx joins them ("true, maybe"), so two values raise, before anything is sent."""
        for lib in ("boto3", "aiobotocore"):
            for values in (("true", "maybe"), ("true", "true")):
                with self.subTest(lib=lib, values=values):
                    made, calls = world(lib)
                    client = calls.client()
                    client.meta.events.register("before-sign.bedrock-runtime.*", lambda request, values=values, **_: [
                        request.headers.__setitem__("Reflexer-Skip", value) for value in values])
                    outcome = calls.call(client)
                    raised = [each for each in reflexer.bedrock.chain(outcome.error) if isinstance(each, ValueError)]
                    self.assertEqual([str(each) for each in raised][-1:], [reflexer.NOT_A_SKIP], repr(outcome.error))
                    self.assertEqual(made.reflexer.seen + made.provider.seen, [])

    def test_an_option_header_repeated_on_botocore_raises_as_its_values_joined_do_and_none_leaves(self):
        """An option's header botocore holds twice, as the skip's above: every value read, so two raise, as httpx's do."""
        for lib in ("boto3", "aiobotocore"):
            for header, values in (("Reflexer-Answer", ("true", "false")), ("Reflexer-Timeout-Ms", ("100", "200"))):
                with self.subTest(lib=lib, header=header):
                    made, calls = world(lib)
                    client = calls.client()
                    client.meta.events.register("before-sign.bedrock-runtime.*", lambda request, header=header, values=values, **_: [
                        request.headers.__setitem__(header, value) for value in values])
                    outcome = calls.call(client)
                    raised = [each for each in reflexer.bedrock.chain(outcome.error) if isinstance(each, ValueError)]
                    self.assertRegex(" ".join(str(each) for each in raised), f"the {header} header must be", repr(outcome.error))
                    self.assertEqual(made.reflexer.seen + made.provider.seen, [])

    def test_the_skip_argument_true_skips_false_does_not_another_value_raises_and_none_leaves(self):
        """`ReflexerSkip` on a keyed call through the botocore family: True goes straight, False goes to reflexer, anything
        but a boolean ("false" included) raises before anything is sent."""
        for lib in ("boto3", "aiobotocore"):
            for value, to_reflexer in ((True, False), (False, True), ("false", None), (1, None), (None, None)):
                with self.subTest(lib=lib, value=value):
                    made, calls = world(lib)
                    outcome = calls.call(calls.client(), args={reflexer.bedrock.ARGUMENT: value})
                    if to_reflexer is None:
                        raised = [each for each in reflexer.bedrock.chain(outcome.error) if isinstance(each, ValueError)]
                        self.assertEqual([str(each) for each in raised][-1:], [reflexer.bedrock.NOT_A_SKIP_ARGUMENT], repr(outcome.error))
                        self.assertEqual(made.reflexer.seen + made.provider.seen, [])
                        continue
                    self.assertIsNone(outcome.error)
                    self.assertEqual(bool(made.reflexer.seen), to_reflexer)

    def test_a_signed_call_goes_to_reflexer_and_falls_back_as_stock(self):
        for lib, held in signed_as_stock().items():
            with self.subTest(lib=lib):
                self.assertTrue(held)

    def test_a_signed_calls_fallback_is_signed_after_reflexers_leg(self):
        """The line reaches the library's own signer: the fallback's signing time is after the leg's, so a leg of any
        length leaves it fresh. LiteLLM's reuses its signature: its leg is bounded by the window instead (below)."""
        for lib, (at_reflexer, at_bedrock) in signing_times().items():
            with self.subTest(lib=lib):
                self.assertTrue(at_reflexer and at_bedrock)
                self.assertEqual(at_bedrock > at_reflexer, lib in SIGNS_ANEW, (at_reflexer, at_bedrock))

    def test_a_signed_calls_fallback_holds_with_a_before_sign_handler_of_the_clients(self):
        self.assertEqual(held_with_a_header_of_the_clients(), {"boto3": True, "aiobotocore": True})

    def test_async_anthropic_a_signed_calls_fallback_is_signed_after_reflexers_leg(self):
        at_reflexer, at_bedrock, text = async_anthropic_signing_times()
        self.assertEqual(text, harness.STRAIGHT_TEXT)
        self.assertGreater(at_bedrock, at_reflexer)

    def test_a_signer_failing_anew_sends_the_call_as_first_signed(self):
        self.assertEqual(fallback_when_the_signer_fails(), (harness.STRAIGHT_TEXT, 1, True))

    def test_a_signed_calls_fallback_holds_with_a_body_or_url_handler_of_the_clients(self):
        self.assertEqual([key for key, held in held_with_a_body_or_url_of_the_clients().items() if not held], [])

    def test_anthropic_a_signed_call_never_sent_to_reflexer_is_attempted_once(self):
        for headers in (None, {"Reflexer-Namespace": "made-up"}):  # one of ours under the signature: kept, as signed
            with self.subTest(headers=headers):
                self.assertEqual(anthropic_attempts_with_no_leg(headers), (harness.STRAIGHT_TEXT, 1, True))

    def test_anthropic_an_error_after_reflexers_leg_holds_no_key_in_its_frames(self):
        self.assertEqual(anthropic_error_after_a_leg(), [])

    def test_anthropic_a_call_never_sent_to_reflexer_keeps_out_a_header_of_ours_its_signature_does_not_cover(self):
        def hook(request):  # the client's own, after the SDK signed: uncovered
            request.headers["Reflexer-Made-Up"] = "made-up"
        uncovered, held, _ = anthropic_sampled_out(hook)
        self.assertEqual((uncovered, held), ([], True))

    def test_anthropic_an_error_after_a_call_never_sent_to_reflexer_shows_no_signature_in_the_sdks_frames(self):
        self.assertEqual(anthropic_sampled_out(provider="dead")[2], [])

    def test_a_fallback_signed_anew_carries_the_body_and_url_its_signature_covers(self):
        self.assertEqual(per_attempt_change(), {"boto3": True, "aiobotocore": True})

    def test_litellm_a_signed_calls_leg_ends_while_its_signature_holds(self):
        for is_async in (False, True):
            with self.subTest(is_async=is_async):
                text, took, taken = litellm_leg(is_async=is_async)
                # Bedrock's stand-in taking the straight call shows its signature still held; the time shows reflexer's
                # leg was cut by the window, not by the client's own timeout, ten windows long
                self.assertEqual((text, taken), (harness.STRAIGHT_TEXT, True))
                self.assertLess(took, LITELLM_WINDOW * 5)

    def test_through_each_bedrock_line_a_call_reflexer_does_not_take_still_reaches_bedrock(self):
        for scene in ("busy", "dead"):
            for lib, (text, reached) in reached_bedrock_after(SCENES[scene]).items():
                with self.subTest(lib=lib, scene=scene):
                    self.assertEqual((text, reached), (harness.STRAIGHT_TEXT, True))

    def test_through_each_bedrock_line_reflexers_empty_answer_is_the_clients_never_bedrocks(self):
        """Reflexer asked not to answer: its empty 204 goes to the client's library as reflexer's answer, a body of zero
        bytes read fine, never a call to Bedrock; whatever the library makes of it raises from no frame of the SDK's."""
        package = os.path.join(os.path.abspath(ROOT), "reflexer") + os.sep
        for lib, keyed, op in empty_answer_calls():
            with self.subTest(lib=lib, keyed=keyed, op=op):
                made, calls = world(lib)
                made.reflexer.set("empty")
                outcome = calls.call(calls.client(keyed=keyed), op)
                calls.close()
                frames = [] if outcome.error is None else traceback.extract_tb(outcome.error.__traceback__)
                # Pydantic AI asks again, on its own, for an output it did not get: reflexer, never Bedrock
                self.assertEqual((bool(made.reflexer.message_arrivals()), len(made.provider.seen)), (True, 0))
                self.assertFalse([f"{frame.filename}:{frame.lineno}" for frame in frames if os.path.abspath(frame.filename).startswith(package)])

    def test_through_each_bedrock_line_a_replay_never_reaches_bedrock(self):
        found = reached_bedrock_after(SCENES["busy"], extra={"replay_response": {"id": "made-up"}})
        for lib in REPLAYING:
            with self.subTest(lib=lib):
                self.assertEqual(found[lib], (None, False))

    def test_a_signed_replay_never_reaches_bedrock(self):
        self.assertEqual(signed_replays_reaching_bedrock(), {lib: False for lib in REPLAYING})

    def test_a_signed_call_carries_no_header_of_ours_its_signature_does_not_cover(self):
        for (lib, how), (uncovered, held) in ours_on_signed_calls().items():
            with self.subTest(lib=lib, how=how):
                self.assertEqual((uncovered, held), ([], True))

    def test_a_signed_calls_option_headers_reach_reflexer_alone_never_signed(self):
        given = {"reflexer-answer": "false", "reflexer-store": "false", "reflexer-pass-through": "true", "reflexer-timeout-ms": "100"}
        for lib in RUNTIME:
            with self.subTest(lib=lib):
                made, calls = world(lib)
                SCENES["busy"](made)
                calls.call(calls.client(keyed=False), headers={name.title(): value for name, value in given.items()})
                calls.close()
                to_reflexer, arrival = made.reflexer.seen[-1], made.provider.seen[-1]
                self.assertEqual({name: to_reflexer.headers.get(name) for name in given}, given)
                self.assertEqual(([name for name in arrival.headers if name in given], bedrock.signature_holds(arrival)), ([], True))

    def test_nothing_a_served_call_hands_the_client_holds_the_key(self):
        for lib, where in what_the_client_is_handed().items():
            with self.subTest(lib=lib):
                self.assertEqual(where, [])

    def test_nothing_a_served_call_on_an_httpx_line_hands_the_client_holds_the_key(self):
        for line, (where, read) in what_an_httpx_line_hands_the_client().items():
            with self.subTest(line=line):
                self.assertEqual((where, read), ([], True))

    def test_the_frame_check_reads_a_local_holding_itself(self):
        made = {}  # a frame of the line's file, as a library's frame may hold a dict that holds itself
        exec(compile("def outer(fail, key):\n    looped = {}\n    looped['itself'] = looped\n    looped['held'] = key\n    fail()", reflexer.boto3.__file__, "exec"), made)

        def fail():
            raise RuntimeError("made up")
        try:
            made["outer"](fail, harness.make_key())
        except RuntimeError as error:
            self.assertEqual(in_clear(error, harness.make_key()), ["boto3.py:outer.key", "boto3.py:outer.looped"])

    def test_an_error_raised_to_the_client_shows_no_key_signature_or_token_in_any_frame(self):
        for (lib, scene, keyed), shown in errors_in_clear().items():
            with self.subTest(lib=lib, scene=scene, keyed=keyed):
                self.assertEqual(shown, [])

    def test_a_calls_own_read_timeout_holds_on_reflexers_leg(self):
        self.assertEqual(straight_within(0.5), {"boto3": True, "aiobotocore": True})

    def test_a_private_name_renamed_fails_the_line_as_it_is_made(self):
        """What no public name reaches, read as the line is made: a release renaming it raises there, before any call."""
        key = harness.make_key()
        self.assertTrue(renamed_endpoint_fails_the_line())
        for name in ("_get_session", "_proxy_config", "_endpoint"):
            with self.subTest(name=name):
                async def entered():
                    import aiobotocore.session
                    async with aiobotocore.session.get_session().create_client("bedrock-runtime", region_name=bedrock.REGION) as made:
                        holder = made if name == "_endpoint" else made._endpoint.http_session
                        if name == "_get_session":
                            with mock.patch.object(aiobotocore.httpsession.AIOHTTPSession, "_get_session", new=None):
                                del aiobotocore.httpsession.AIOHTTPSession._get_session
                                reflexer.aiobotocore.through(made, key)
                        else:
                            setattr(holder, name + "_renamed", holder.__dict__.pop(name))
                            reflexer.aiobotocore.through(made, key)
                with self.assertRaises(AttributeError):
                    asyncio.run(entered())

    def test_a_line_that_cannot_carry_reflexers_leg_fails_as_it_is_made(self):
        """aiobotocore on another HTTP session class, or a client given the line twice: each raises as the line is made,
        where every call would otherwise go straight, or try reflexer twice."""
        import aiobotocore.config, aiobotocore.httpxsession, aiobotocore.session
        key = harness.make_key()

        async def on_httpx():
            config = aiobotocore.config.AioConfig(http_session_cls=aiobotocore.httpxsession.HttpxSession)
            async with aiobotocore.session.get_session().create_client("bedrock-runtime", region_name=bedrock.REGION, config=config) as made:
                reflexer.aiobotocore.through(made, key)
        with self.assertRaises(TypeError):
            asyncio.run(on_httpx())
        twice = reflexer.boto3.client("bedrock-runtime", region_name=bedrock.REGION, reflexer_key=key)
        with self.assertRaises(ValueError):
            reflexer.boto3.through(twice, key)

    def test_aiobotocore_a_session_with_hooks_of_its_own_or_headers_kept_otherwise_fails_the_line(self):
        """An aiohttp session of a subclass (trace hooks, middlewares) would see our headers; and where aiohttp's kept
        headers could not be forgotten, every served answer would be dropped: each raises as the line is made."""
        import aiobotocore.config, aiobotocore.httpsession, aiobotocore.session
        key = harness.make_key()

        class Own(aiobotocore.httpsession.AIOHTTPSession):
            pass

        async def made(config=None):
            async with aiobotocore.session.get_session().create_client("bedrock-runtime", region_name=bedrock.REGION, config=config) as client:
                reflexer.aiobotocore.through(client, key)
        with self.assertRaises(TypeError):
            asyncio.run(made(aiobotocore.config.AioConfig(http_session_cls=Own)))
        with mock.patch.object(reflexer.aiobotocore, "get_referents", lambda held: []), self.assertRaises(TypeError):
            asyncio.run(made())

class Broken(Case):
    """Each check above, red with one fault planted in the SDK."""

    def test_the_key_on_the_clients_own_request_turns_it_red(self):
        real_route, real_to_reflexer = reflexer.bedrock.botocore_route, reflexer.transport.to_reflexer

        def route(reflexer_, request):
            request.headers["reflexer-key"] = reflexer_.key
            return real_route(reflexer_, request)

        def to_reflexer(reflexer_, request):
            request.headers["reflexer-key"] = reflexer_.key
            return real_to_reflexer(reflexer_, request)
        with mock.patch.object(reflexer.boto3, "botocore_route", route), mock.patch.object(reflexer.aiobotocore, "botocore_route", route), \
                mock.patch.object(reflexer.transport, "to_reflexer", to_reflexer), mock.patch.object(reflexer.bedrock, "OURS", "not-ours-"), \
                mock.patch.object(reflexer.transport, "OURS", "not-ours-"):
            found = holding(arrivals(scenes={"busy": SCENES["busy"]}), harness.make_key())
        self.assertEqual([lib for lib, who in found.items() if who == ["reflexer"]], [])

    def test_a_redirect_followed_turns_it_red(self):
        """Each line's leg following a redirect: the httpx lines' inner client, aiobotocore's aiohttp session. botocore's
        own session follows none, whatever it is asked."""
        import aiohttp
        real_post = aiohttp.ClientSession.post
        with mock.patch.object(reflexer.transport.Through, "__init__", following(reflexer.transport.Through.__init__)), \
                mock.patch.object(aiohttp.ClientSession, "post", lambda self, url, **kwargs: real_post(self, url, **kwargs | {"allow_redirects": True})):
            found = arrivals(scenes={"redirected": lambda w: w.reflexer.set("reply", status=307, headers={"location": "https://elsewhere.example/moved"})})
        held = holding(found, harness.make_key())
        for lib in ("aiobotocore", "litellm", "anthropic-bedrock", "anthropic-mantle"):
            with self.subTest(lib=lib):
                self.assertIn("elsewhere", held[lib])

    def test_a_signed_mantle_call_sent_to_reflexer_turns_it_red(self):
        with mock.patch.object(reflexer.bedrock, "keyed", lambda headers: True):
            signed = arrivals(keyed=False, scenes={"served": SCENES["served"]})
            self.assertIn("reflexer", holding(signed, "AWS4-HMAC-SHA256")["anthropic-mantle"])
            self.assertFalse(signed_as_stock()["anthropic-mantle"])

    def test_a_signed_call_not_sent_to_reflexer_turns_it_red(self):
        with mock.patch.object(reflexer.bedrock, "signed", lambda headers: False):
            self.assertEqual([lib for lib in RUNTIME if "reflexer" in holding(arrivals(keyed=False), "AWS4-HMAC-SHA256")[lib]], [])
            self.assertFalse(any(signed_as_stock()[lib] for lib in RUNTIME))

    def test_the_secret_sent_turns_it_red(self):
        real = reflexer.bedrock.lower
        with mock.patch.object(reflexer.bedrock, "lower", lambda headers: real(headers) | {"x-made-up": bedrock.SECRET}):
            self.assertTrue(all(holding(arrivals(keyed=False), bedrock.SECRET)[lib] for lib in ("boto3", "aiobotocore")))

    def test_a_fallback_not_signed_anew_turns_it_red(self):
        with mock.patch.object(reflexer.bedrock, "signing_anew", lambda request, unprepared: None), \
                mock.patch.object(reflexer.boto3, "signing_anew", lambda request, unprepared: None), \
                mock.patch.object(reflexer.aiobotocore, "signing_anew", lambda request, unprepared: None), \
                mock.patch.object(reflexer.anthropic_bedrock, "withheld", lambda request: False):
            found = signing_times()
        self.assertEqual([lib for lib, (at_reflexer, at_bedrock) in found.items() if at_bedrock > at_reflexer], [])

    def test_a_fallback_signed_over_the_headers_its_handlers_already_set_turns_it_red(self):
        real = reflexer.bedrock.skip_taken

        def late(event_name, kwargs, before):  # the headers kept for signing anew, after the client's handlers ran
            real(event_name, kwargs, before)
            if not before and event_name.startswith("before-sign."):
                request = kwargs["request"]
                request.context[reflexer.bedrock.UNSIGNED] = (request.url, request.data, reflexer.bedrock.lower(request.headers))
        with mock.patch.object(reflexer.boto3, "skip_taken", late), mock.patch.object(reflexer.aiobotocore, "skip_taken", late):
            self.assertEqual(held_with_a_header_of_the_clients(), {"boto3": False, "aiobotocore": False})
            self.assertEqual([key for key, held in held_with_a_body_or_url_of_the_clients().items() if held], [])

    def test_async_anthropic_not_attempted_anew_turns_it_red(self):
        with mock.patch.object(reflexer.anthropic_bedrock, "withheld", lambda request: False):
            at_reflexer, at_bedrock, text = async_anthropic_signing_times()
        self.assertEqual(at_bedrock, at_reflexer)

    def test_a_fallback_signed_for_another_scope_turns_it_red(self):
        """The client's signer asked for another region or service on its second signing: Bedrock's stand-in refuses the
        scope, as Bedrock does, so the check goes red."""
        real = reflexer.bedrock.signing_anew
        for scope in ({"region_name": "eu-west-1"}, {"signing_name": "made-up-service"}):
            def elsewhere(request, unprepared, scope=scope):
                made = real(request, unprepared)
                if made is None:
                    return None
                signer, operation, copy = made

                class Elsewhere:  # the client's signer, given another scope
                    def sign(self, operation, request):
                        return signer.sign(operation, request, **scope)
                return Elsewhere(), operation, copy
            with self.subTest(scope=scope), mock.patch.object(reflexer.boto3, "signing_anew", elsewhere):
                made, calls = world("boto3")
                made.reflexer.set("busy")
                outcome = calls.call(calls.client(keyed=False))
                calls.close()
                self.assertNotEqual(outcome.text, harness.STRAIGHT_TEXT)

    def test_litellm_a_signing_time_read_as_local_time_turns_it_red(self):
        def local(headers):  # the window's clock slipped: x-amz-date read in this machine's time zone, not UTC
            try:
                at = datetime.datetime.strptime(headers.get("x-amz-date") or "", "%Y%m%dT%H%M%SZ")
            except ValueError:
                return None
            return at.timestamp() + reflexer.litellm.WINDOW["seconds"] - reflexer.litellm.WINDOW["margin"] - time.time()
        with mock.patch.object(reflexer.litellm, "left", local):
            text, took, taken = litellm_leg()
        self.assertFalse(text == harness.STRAIGHT_TEXT and taken and took < LITELLM_WINDOW * 5)

    def test_a_fallback_without_its_body_signed_anew_turns_it_red(self):
        real = reflexer.bedrock.signed_anew

        def headers_only(request, made):  # the body as first signed, the signature over the body signed anew
            body = request.body
            real(request, made)
            request.body = body
        for line in (reflexer.boto3, reflexer.aiobotocore):
            self.addCleanup(setattr, line, "signed_anew", getattr(line, "signed_anew"))
            setattr(line, "signed_anew", headers_only)
        self.assertEqual(per_attempt_change(), {"boto3": False, "aiobotocore": False})

    def test_a_fallback_without_its_url_signed_anew_turns_it_red(self):
        real = reflexer.bedrock.signed_anew

        def url_kept(request, made):  # the URL as first signed, the signature over the URL signed anew
            url = request.url
            real(request, made)
            request.url = url
        for line in (reflexer.boto3, reflexer.aiobotocore):
            self.addCleanup(setattr, line, "signed_anew", getattr(line, "signed_anew"))
            setattr(line, "signed_anew", url_kept)
        self.assertEqual(per_attempt_change(), {"boto3": False, "aiobotocore": False})

    def test_litellm_a_leg_unbounded_turns_it_red(self):
        with mock.patch.object(reflexer.litellm, "within", lambda seconds, send: send()), \
                mock.patch.object(reflexer.litellm, "awithin", lambda seconds, sent: sent):
            for is_async in (False, True):
                with self.subTest(is_async=is_async):
                    text, took, taken = litellm_leg(is_async=is_async)
                    self.assertFalse(text == harness.STRAIGHT_TEXT and taken and took < LITELLM_WINDOW * 5)

    def test_a_signed_call_changed_turns_it_red(self):
        def changed(request, headers, body):
            headers["x-made-up"] = "1"
            return request
        real = reflexer.transport.stays_straight

        def changed_shipped(request):  # LiteLLM's signed call falls back by the shipped legs
            request.headers["x-made-up"] = "1"
            return real(request)
        with mock.patch.object(reflexer.bedrock, "straight", changed), mock.patch.object(reflexer.boto3, "straight", changed), \
                mock.patch.object(reflexer.aiobotocore, "straight", changed), mock.patch.object(reflexer.transport, "stays_straight", changed_shipped):
            self.assertFalse(any(signed_as_stock().values()))

    def test_no_fallback_turns_it_red(self):
        with mock.patch.object(reflexer.Reflexer, "failed", lambda self, failure: (_ for _ in ()).throw(failure)):
            found = reached_bedrock_after(SCENES["dead"])
        self.assertFalse(any(seen == (harness.STRAIGHT_TEXT, True) for seen in found.values()), found)

    def test_no_replay_guard_turns_it_red(self):
        with mock.patch.object(reflexer.bedrock, "is_replay", lambda body: False), \
                mock.patch.object(reflexer.transport, "is_replay", lambda body: False):
            found = reached_bedrock_after(SCENES["busy"], extra={"replay_response": {"id": "made-up"}})
        self.assertTrue(all(found[lib][1] for lib in REPLAYING), found)

    def test_no_replay_guard_on_a_signed_call_turns_it_red(self):
        real = reflexer.bedrock.straight

        def unguarded(request, headers, body):
            return real(request, headers, body if reflexer.bedrock.keyed(headers) else None)
        with mock.patch.object(reflexer.bedrock, "straight", unguarded), mock.patch.object(reflexer.boto3, "straight", unguarded), \
                mock.patch.object(reflexer.aiobotocore, "straight", unguarded), \
                mock.patch.object(reflexer.transport, "is_replay", lambda body: False):  # anthropic's signed call: the shipped legs' guard too
            self.assertTrue(all(signed_replays_reaching_bedrock().values()))

    def test_headers_of_ours_kept_on_a_signed_call_turns_it_red(self):
        def keeping(request, headers, body):
            return request

        def keeping_shipped(request):  # LiteLLM's signed call falls back by the shipped legs
            request.extensions[reflexer.transport.STRAIGHT] = True
            return request
        with mock.patch.object(reflexer.bedrock, "straight", keeping), mock.patch.object(reflexer.boto3, "straight", keeping), \
                mock.patch.object(reflexer.aiobotocore, "straight", keeping), mock.patch.object(reflexer.transport, "stays_straight", keeping_shipped):
            found = ours_on_signed_calls()
        self.assertTrue(all(found[(lib, how)][0] for lib, how in (("boto3", "after signing"), ("aiobotocore", "after signing"), ("litellm", "call"))), found)

    def test_reflexers_answer_still_keeping_our_headers_goes_straight(self):
        """An answer keeping the request's headers where they cannot be forgotten, after the line was made: not handed on."""
        made, calls = world("aiobotocore")
        client = calls.client()
        with mock.patch.object(reflexer.aiobotocore, "get_referents", lambda held: []):
            outcome = calls.call(client)
        calls.close()
        self.assertEqual((outcome.text, bool(made.provider.seen)), (harness.STRAIGHT_TEXT, True))

    def test_reflexers_leg_raising_a_cancel_on_with_the_frames_below_turns_it_red(self):
        # each leg raises a cancel or a ^C on as it came: the frames below it, and the errors it came while handling
        as_it_came = lambda stopped: stopped  # noqa: E731
        with mock.patch.object(reflexer.transport, "alone", as_it_came), mock.patch.object(reflexer.boto3, "alone", as_it_came), \
             mock.patch.object(reflexer.aiobotocore, "alone", as_it_came):
            found = errors_in_clear()
        httpx = [scene for scene in found if scene[0] in HTTPX and scene[1].split(", HTTP/2")[0].split(", async")[0] in HTTPX_ERRORS]
        self.assertTrue(httpx)
        # reflexer stalled, httpcore's frames no longer hold the headers it sent: only aiohttp's (LiteLLM's async) go red
        self.assertEqual([scene for scene in httpx if not found[scene] and "stalled" not in scene[1]], [])
        for scene in [("litellm", "the client's deadline, reflexer stalled, async", True), ("boto3", "not an Exception, in the leg", True),
                      *[(lib, "not an Exception, as the leg's failure is counted", keyed) for lib in ("boto3", "aiobotocore") for keyed in (True, False)]]:
            self.assertTrue(found[scene], scene)

    def test_a_key_in_a_frame_of_the_lines_on_an_error_turns_it_red(self):
        # a frame of the line's own file holding the key as a replay raises through it
        straight = eval(compile("lambda request, headers, body, kept=key: real(request, headers, body)", reflexer.boto3.__file__, "eval"),
                        {"real": reflexer.bedrock.straight, "key": harness.make_key()})
        with mock.patch.object(reflexer.boto3, "straight", straight):
            self.assertTrue(errors_in_clear()[("boto3", "replay, reflexer busy", True)])

    def test_a_signature_kept_where_an_errors_frames_reach_it_turns_it_red(self):
        real = reflexer.anthropic_bedrock.Again.first

        def keeping(request):  # the call's signed headers kept on the call, which our middleware's frame holds
            held = real(request)
            reflexer.anthropic_bedrock.CALL.get()["signed"] = dict(request.headers)
            return held
        with mock.patch.object(reflexer.anthropic_bedrock.Again, "first", staticmethod(keeping)):
            self.assertTrue(anthropic_sampled_out(provider="dead")[2])

    def test_a_signature_in_a_frame_of_the_lines_on_an_error_turns_it_red(self):
        # a frame of the line's own file holding a copy of the signed headers as a replay raises through it
        made = {"real": reflexer.bedrock.straight}
        exec(compile("def straight(request, headers, body):\n    kept = dict(headers)\n    return real(request, headers, body)", reflexer.boto3.__file__, "exec"), made)
        straight = made["straight"]
        with mock.patch.object(reflexer.boto3, "straight", straight):
            self.assertTrue(errors_in_clear()[("boto3", "replay, reflexer busy", False)])

    def test_a_session_token_kept_where_an_errors_frames_reach_it_turns_it_red(self):
        real = reflexer.anthropic_bedrock.Again.first

        def keeping(request):  # the call's session token alone kept on the call, which our middleware's frame holds
            held = real(request)
            reflexer.anthropic_bedrock.CALL.get()["token"] = request.headers.get("x-amz-security-token")
            return held
        with mock.patch.object(reflexer.anthropic_bedrock.Again, "first", staticmethod(keeping)):
            self.assertTrue(errors_in_clear()[("anthropic-bedrock", "replay, reflexer busy", False)])
            self.assertTrue(anthropic_sampled_out(provider="dead")[2])

    def test_anthropic_every_header_of_ours_put_back_on_a_call_never_sent_turns_it_red(self):
        real = reflexer.anthropic_bedrock.Again.first

        def every(request):  # put back on a call never sent: every header of ours, those its signature does not cover among them
            held = real(request)
            call = reflexer.anthropic_bedrock.CALL.get()
            call["ours"] = {name: value for name, value in request.headers.items() if name.lower().startswith(reflexer.OURS)}
            return held

        def hook(request):
            request.headers["Reflexer-Made-Up"] = "made-up"
        with mock.patch.object(reflexer.anthropic_bedrock.Again, "first", staticmethod(every)):
            uncovered, _, _ = anthropic_sampled_out(hook)
        self.assertTrue(uncovered)

    def test_a_key_kept_in_a_closure_on_the_answer_turns_it_red(self):
        real, key = reflexer.aiobotocore.forgotten, harness.make_key()

        def keeping(response):
            made = real(response)
            return types.SimpleNamespace(content=made.content, url=made.url, status=made.status, read=made.read, close=made.close,
                                         release=made.release, hook=lambda: key)
        with mock.patch.object(reflexer.aiobotocore, "forgotten", keeping):
            self.assertTrue(what_the_client_is_handed()["aiobotocore"])

    def test_a_key_kept_in_a_functions_attributes_on_the_answer_turns_it_red(self):
        real, key = reflexer.aiobotocore.forgotten, harness.make_key()

        def keeping(response):
            made = real(response)

            def hook():
                return None
            hook.__wrapped__ = types.SimpleNamespace(kept=key)
            return types.SimpleNamespace(content=made.content, url=made.url, status=made.status, read=made.read, close=made.close,
                                         release=made.release, hook=hook)
        with mock.patch.object(reflexer.aiobotocore, "forgotten", keeping):
            self.assertTrue(what_the_client_is_handed()["aiobotocore"])

    def test_reflexers_request_kept_whole_under_its_answer_turns_it_red(self):
        def kept(step, info):
            return None

        async def akept(step, info):
            return None
        with mock.patch.object(reflexer.transport, "forget_sent", kept), mock.patch.object(reflexer.transport, "aforget_sent", akept):
            found = what_an_httpx_line_hands_the_client()
        self.assertTrue(all(where for where, _ in found.values()), found)

    def test_reflexers_own_answer_handed_on_turns_it_red(self):
        with mock.patch.object(reflexer.aiobotocore, "forgotten", lambda response: response):
            self.assertTrue(what_the_client_is_handed()["aiobotocore"])

    def test_a_private_name_read_at_each_call_turns_it_red(self):
        """A line that reads the client's HTTP session only as each call is sent: renamed, the line is made with no error."""
        real = reflexer.boto3.through

        class Later:  # the client, its endpoint read only when a call sends by it
            def __init__(self, client):
                self.meta, self.client = client.meta, client

            @property
            def _endpoint(self):
                return types.SimpleNamespace(http_session=types.SimpleNamespace(send=lambda leg: self.client._endpoint.http_session.send(leg)))

        def lazily(client, *args, **kwargs):
            real(Later(client), *args, **kwargs)
            return client
        with mock.patch.object(reflexer.boto3, "through", lazily):
            self.assertFalse(renamed_endpoint_fails_the_line())


def renamed_endpoint_fails_the_line():
    """Whether a boto3 client whose `_endpoint` a release renamed fails reflexer's line as it is made."""
    import boto3
    client = boto3.client("bedrock-runtime", region_name=bedrock.REGION)
    client._endpoint_renamed = client.__dict__.pop("_endpoint")
    try:
        reflexer.boto3.through(client, harness.make_key())
    except AttributeError:
        return True
    return False


def following(real_init):
    """The httpx lines' inner client, following redirects with our headers on."""
    def init(self, reflexer_, inner):
        real_init(self, reflexer_, inner)
        import functools
        self.send = functools.partial(inner.send, stream=True, follow_redirects=True, auth=None)
    return init


if __name__ == "__main__":
    unittest.main()
