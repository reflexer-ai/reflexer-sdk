"""Amazon Bedrock's promises (SECURITY.md), each checked through every Bedrock line on its real library, over the
acceptance suite's stand-ins in this process (real sockets and TLS, names resolved to this machine only), and each check
shown red under a planted fault; and what the lines read of another's package that no public name gives.
Offline, every key, credential and answer made up. Run: python -m unittest tests.test_bedrock"""
import asyncio, datetime, json, os, socket, sys, tempfile, shutil, time, types, unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path[:0] = [os.path.join(ROOT, "tests", "acceptance"), ROOT]
import harness, lines  # noqa: E402 the acceptance suite's stand-ins and lines
from harness import bedrock, certs  # noqa: E402
import reflexer, reflexer.transport  # noqa: E402
import reflexer.aiobotocore, reflexer.anthropic_bedrock, reflexer.bedrock, reflexer.boto3, reflexer.litellm  # noqa: E402

import importlib.util  # noqa: E402
LINES = tuple(lib for lib in bedrock.SIGNING  # Bedrock's own lines: each library that can carry a key and sign; pydantic-ai's
              if lib != "pydantic-ai" or importlib.util.find_spec("pydantic_ai"))  # group is its own, as for the shipped lines
RUNTIME = tuple(lib for lib in LINES if lib != "anthropic-mantle")  # whose signed calls go to reflexer: the node signs the runtime's
SIGNS_ANEW = tuple(lib for lib in RUNTIME if lib != "litellm")  # whose line reaches the library's own signer for the fallback
VOLATILE = {"authorization", "x-amz-date", "amz-sdk-invocation-id", "amz-sdk-request", "x-stainless-retry-count", "content-length",
            "x-stainless-read-timeout", "x-stainless-raw-response"}  # what differs between two calls made alike; the last, anthropic's with any middleware
SAVED = {}
TIMEZONE = "America/Sao_Paulo"  # CI runs in UTC, where a signing time read as local time would pass unseen


def setUpModule():
    SAVED.update(socket=(socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex), env=dict(os.environ))
    folder = tempfile.mkdtemp(prefix="reflexer-bedrock-")
    SAVED["folder"], SAVED["certs"] = folder, certs.Certs(folder, harness.NAMES)
    for name in bedrock.AMBIENT:
        os.environ.pop(name, None)
    os.environ.update(bedrock.ENVIRONMENT, SSL_CERT_FILE=SAVED["certs"].ca, AWS_CA_BUNDLE=SAVED["certs"].ca, TZ=TIMEZONE)
    if hasattr(time, "tzset"):
        time.tzset()
    harness.resolver.install()


def tearDownModule():
    socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = SAVED["socket"]
    os.environ.clear()
    os.environ.update(SAVED["env"])
    if hasattr(time, "tzset"):
        time.tzset()
    shutil.rmtree(SAVED["folder"], ignore_errors=True)


def world(lib):
    """A world of stand-ins of its own, as each acceptance case's process has. LiteLLM keeps its HTTP clients across
    calls, connected to the last world's stand-ins: dropped, as a process of its own would start with none. The last
    world's stand-ins are closed, as a case's process ends with them: a process holding every world's sockets passes
    the descriptor numbers a stand-in's `select` takes."""
    import litellm
    litellm.in_memory_llm_clients_cache.flush_cache()
    for standin in SAVED.pop("standins", ()):
        standin._cut_connections()
        standin._close()
    made = harness.World((SAVED["certs"].context(), SAVED["certs"].untrusted()))
    SAVED["standins"] = [made.reflexer, made.provider, made.elsewhere, made.runner]
    test = harness.Test(lines, lib, made)
    import logging
    logging.getLogger().removeHandler(test.logs)
    return made, bedrock.Calls(test)


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


def litellm_leg(seconds=2.0, margin=0.5, is_async=False):
    """LiteLLM's signed call, reflexer stalled, the window shortened to `seconds` at Bedrock's stand-in and in the line:
    (what the client saw, the seconds it took, whether Bedrock took it). `is_async`: by `acompletion` and its line."""
    import time, litellm
    made, calls = world("litellm")
    made.provider.window = seconds
    made.reflexer.set("stall")
    with mock.patch.dict(reflexer.litellm.WINDOW, seconds=seconds, margin=margin):
        began = time.monotonic()
        if is_async:
            given = calls.client(keyed=False, timeout=10 * seconds, line=False) | {"client": reflexer.litellm.async_client(made.key)}
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


def holders(roots, secret, most=500000):
    """The paths by which `secret` is reached from `roots`, following every object reference (`gc.get_referents`), a
    bound method's object included, as any code the client runs could follow it; not into modules, classes, code or
    functions, whose globals are the program's own."""
    import gc
    seen, pending, found = set(), [(root, "root") for root in roots], []
    while pending and len(seen) < most:
        thing, path = pending.pop()
        if id(thing) in seen:
            continue
        seen.add(id(thing))
        if isinstance(thing, (str, bytes, bytearray)):
            found += [path] if (secret in thing if isinstance(thing, str) else secret.encode() in thing) else []
            continue
        if isinstance(thing, type) or type(thing).__name__ in ("module", "function", "code", "frame", "cell"):
            continue
        pending += [(held, f"{path}>{type(held).__name__}") for held in gc.get_referents(thing)]
    return found


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


class Promises(unittest.TestCase):
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

    def test_litellm_a_signed_calls_leg_ends_while_its_signature_holds(self):
        for is_async in (False, True):
            with self.subTest(is_async=is_async):
                text, took, taken = litellm_leg(is_async=is_async)
                self.assertEqual((text, taken), (harness.STRAIGHT_TEXT, True))
                self.assertLess(took, 2.0)

    def test_through_each_bedrock_line_a_call_reflexer_does_not_take_still_reaches_bedrock(self):
        for scene in ("busy", "dead"):
            for lib, (text, reached) in reached_bedrock_after(SCENES[scene]).items():
                with self.subTest(lib=lib, scene=scene):
                    self.assertEqual((text, reached), (harness.STRAIGHT_TEXT, True))

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

    def test_nothing_a_served_call_hands_the_client_holds_the_key(self):
        for lib, where in what_the_client_is_handed().items():
            with self.subTest(lib=lib):
                self.assertEqual(where, [])

    def test_a_calls_own_read_timeout_holds_on_reflexers_leg(self):
        self.assertEqual(straight_within(0.5), {"boto3": True, "aiobotocore": True})

    def test_a_private_name_renamed_fails_the_line_as_it_is_made(self):
        """What no public name reaches, read as the line is made: a release renaming it raises there, before any call."""
        import aiobotocore.httpsession
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
        import aiobotocore.config, aiobotocore.httpxsession, aiobotocore.session, boto3
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

    def test_litellm_a_timeout_moved_fails_the_call_never_drops_it(self):
        """LiteLLM's converse route hands `post` no timeout: the line reads the call's own, and a release that moves it
        fails the call loudly, never sends it with LiteLLM's default of minutes."""
        given = types.SimpleNamespace(model_call_details={"litellm_params": {"timeout": 1.5}})
        self.assertEqual(reflexer.litellm.asked(None, given).read, 1.5)
        self.assertEqual(reflexer.litellm.asked(2.0, given), 2.0)
        for moved in (types.SimpleNamespace(), types.SimpleNamespace(model_call_details={}),
                      types.SimpleNamespace(model_call_details={"litellm_params": {}})):
            with self.subTest(moved=moved), self.assertRaises((AttributeError, KeyError)):
                reflexer.litellm.asked(None, moved)


class Broken(unittest.TestCase):
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
        self.assertFalse(text == harness.STRAIGHT_TEXT and taken and took < 2.0)

    def test_litellm_a_leg_unbounded_turns_it_red(self):
        with mock.patch.object(reflexer.litellm, "within", lambda seconds, send: send()), \
                mock.patch.object(reflexer.litellm, "awithin", lambda seconds, sent: sent):
            for is_async in (False, True):
                with self.subTest(is_async=is_async):
                    text, took, taken = litellm_leg(is_async=is_async)
                    self.assertFalse(text == harness.STRAIGHT_TEXT and taken and took < 2.0)

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
        """A release of aiohttp keeping the request's headers where they cannot be forgotten: the answer is not handed on."""
        made, calls = world("aiobotocore")
        with mock.patch.object(reflexer.aiobotocore.gc, "get_referents", lambda held: []):
            outcome = calls.call(calls.client())
        calls.close()
        self.assertEqual((outcome.text, bool(made.provider.seen)), (harness.STRAIGHT_TEXT, True))

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
