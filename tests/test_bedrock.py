"""Amazon Bedrock's promises (SECURITY.md), each checked through every Bedrock line on its real library, over the
acceptance suite's stand-ins in this process (real sockets and TLS, names resolved to this machine only), and each check
shown red under a planted fault; and what the lines read of another's package that no public name gives.
Offline, every key, credential and answer made up. Run: python -m unittest tests.test_bedrock"""
import asyncio, os, socket, sys, tempfile, shutil, types, unittest
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
SAVED = {}


def setUpModule():
    SAVED.update(socket=(socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex), env=dict(os.environ))
    folder = tempfile.mkdtemp(prefix="reflexer-bedrock-")
    SAVED["folder"], SAVED["certs"] = folder, certs.Certs(folder, harness.NAMES)
    for name in bedrock.AMBIENT:
        os.environ.pop(name, None)
    os.environ.update(bedrock.ENVIRONMENT, SSL_CERT_FILE=SAVED["certs"].ca, AWS_CA_BUNDLE=SAVED["certs"].ca)
    harness.resolver.install()


def tearDownModule():
    socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex = SAVED["socket"]
    os.environ.clear()
    os.environ.update(SAVED["env"])
    shutil.rmtree(SAVED["folder"], ignore_errors=True)


def world(lib):
    """A world of stand-ins of its own, as each acceptance case's process has. LiteLLM keeps its HTTP clients across
    calls, connected to the last world's stand-ins: dropped, as a process of its own would start with none."""
    import litellm
    litellm.in_memory_llm_clients_cache.flush_cache()
    made = harness.World((SAVED["certs"].context(), SAVED["certs"].untrusted()))
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


def signed_as_stock():
    """{lib: whether a signed call reached Bedrock only, its signature held, and its headers as a stock client's}."""
    found = {}
    for lib in LINES:
        made, calls = world(lib)
        outcome = calls.call(calls.client(line=False, keyed=False))
        assert made.provider.seen, f"{lib}: {outcome} {outcome.error!r}"
        stock = made.provider.seen[-1]
        calls.call(calls.client(keyed=False))
        ours = made.provider.seen[-1]
        calls.close()
        same = [name for name in ("content-type", "host", "accept") if stock.headers.get(name) != ours.headers.get(name)]
        found[lib] = (not made.reflexer.seen and bedrock.signature_holds(ours) and ours.body == stock.body and not same
                      and set(ours.headers) == set(stock.headers))
    return found


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


def holders(roots, secret, most=500000):
    """The paths by which `secret` is reached from `roots`, following every object reference (`gc.get_referents`): a
    bound method's object, a function's closure, defaults and attributes (`__wrapped__` among them), and the locals of the SDK's own frames, a traceback's
    among them; not into modules, classes, code, a function's globals or another's frames, which are the program's own.
    Past `most` objects it fails: a walk cut short proves nothing."""
    import gc
    seen, pending, found = set(), [(root, "root") for root in roots], []
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


def in_clear(error, secret):
    """The locals of every frame but the tests' own, the SDK's and its libraries', on an error's traceback and those it
    chains, that show `secret` as an error tracker capturing locals writes them: by their `repr`, a container's holding
    its items'. The line's own state stays reachable from them, as the client's HTTP client holds it; what such a tracker
    ships is what is written."""
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
                found += [f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_code.co_name}.{name}" for name, value in frame.f_locals.items() if secret in repr(value)]
            step = step.tb_next
    return sorted(set(found))


class Stop(BaseException):
    """Made up: what is not an `Exception`, raised as reflexer's leg is sent, as gevent's `Timeout` or a ^C is."""


def asked(arrange, op=None, extra=None):
    """A scene: reflexer arranged, a call made (`op`, with its own fields), whose error the client gets."""
    def scene(made, calls):
        arrange(made)
        given = op if op in calls.lib.ops else ("messages" if "messages" in calls.lib.ops else calls.lib.ops[0])
        return calls.call(calls.client(), given, extra=extra).error
    return scene


def deadline(made, calls):
    """A scene: the client's own deadline (`asyncio.wait_for`) cancels its call while reflexer stalls."""
    made.reflexer.set("stall")
    client = calls.client()
    try:
        calls.run(asyncio.wait_for(calls.lib.call(client, calls.lib.ops[0], None, None, None), 0.5))
    except asyncio.TimeoutError as error:
        return error


def stopped(made, calls):
    """A scene: a `BaseException` raised in urllib3 as reflexer's leg is sent."""
    import urllib3.connectionpool
    real, client = urllib3.connectionpool.HTTPConnectionPool._make_request, calls.client()

    def stopping(pool, *args, **kwargs):
        if pool.host in harness.REFLEXER_NAMES:
            raise Stop()
        return real(pool, *args, **kwargs)
    with mock.patch.object(urllib3.connectionpool.HTTPConnectionPool, "_make_request", stopping):
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
}


def errors_in_clear():
    """{(lib, scene): the frames' locals showing the key on the error the client got} (empty: none), through the
    Bedrock lines and the shipped lines at Bedrock's routes."""
    found = {}
    for scene, (made_by, libs) in ERRORS.items():
        for lib in libs:
            made, calls = world(lib)
            error = made_by(made, calls)
            calls.close()
            found[(lib, scene)] = in_clear(error, harness.make_key()) if error is not None else ["no error raised"]
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

    def test_a_bedrock_key_reaches_only_bedrock_or_reflexer_and_a_signature_only_bedrock(self):
        keyed, signed = arrivals(), arrivals(keyed=False)
        for lib in LINES:
            with self.subTest(lib=lib):
                self.assertEqual(holding(keyed, bedrock.BEARER)[lib], ["bedrock", "reflexer"])
                self.assertEqual(holding(signed, "AWS4-HMAC-SHA256")[lib], ["bedrock"])
                self.assertEqual(holding(signed, bedrock.BEARER)[lib] + holding(keyed, bedrock.SECRET)[lib] + holding(signed, bedrock.SECRET)[lib], [])

    def test_a_signed_call_never_goes_to_reflexer_and_is_as_stock(self):
        for lib, held in signed_as_stock().items():
            with self.subTest(lib=lib):
                self.assertTrue(held)

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

    def test_an_error_raised_to_the_client_shows_no_key_in_any_frame(self):
        for (lib, scene), shown in errors_in_clear().items():
            with self.subTest(lib=lib, scene=scene):
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

    def test_a_signed_call_sent_to_reflexer_turns_it_red(self):
        with mock.patch.object(reflexer.bedrock, "keyed", lambda headers: True):
            signed = arrivals(keyed=False, scenes={"served": SCENES["served"]})
            self.assertTrue(all("reflexer" in who for who in holding(signed, "AWS4-HMAC-SHA256").values()))
            self.assertFalse(any(signed_as_stock().values()))

    def test_a_signed_call_changed_turns_it_red(self):
        def changed(request, headers, body):
            headers["x-made-up"] = "1"
            return request
        with mock.patch.object(reflexer.bedrock, "straight", changed), mock.patch.object(reflexer.boto3, "straight", changed), \
                mock.patch.object(reflexer.aiobotocore, "straight", changed):
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
                mock.patch.object(reflexer.aiobotocore, "straight", unguarded):
            self.assertTrue(all(signed_replays_reaching_bedrock().values()))

    def test_headers_of_ours_kept_on_a_signed_call_turns_it_red(self):
        def keeping(request, headers, body):
            return request
        with mock.patch.object(reflexer.bedrock, "straight", keeping), mock.patch.object(reflexer.boto3, "straight", keeping), \
                mock.patch.object(reflexer.aiobotocore, "straight", keeping):
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

    def test_a_key_in_a_frame_of_the_lines_on_an_error_turns_it_red(self):
        # a frame of the line's own file holding the key as a replay raises through it
        straight = eval(compile("lambda request, headers, body, kept=key: real(request, headers, body)", reflexer.boto3.__file__, "eval"),
                        {"real": reflexer.bedrock.straight, "key": harness.make_key()})
        with mock.patch.object(reflexer.boto3, "straight", straight):
            self.assertTrue(errors_in_clear()[("boto3", "replay, reflexer busy")])

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
