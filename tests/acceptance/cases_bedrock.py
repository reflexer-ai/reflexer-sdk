"""Amazon Bedrock's cases, on each library a client calls it with (`harness/bedrock.py`), over the suite's stand-ins.

A call carrying a Bedrock API key goes to reflexer and falls back straight, as any provider's; a call the library signs
(SigV4) never goes to reflexer, and reaches Bedrock as the library made it. Registered beside `cases.py`'s, by its import.
"""
import gc, json, re, time, warnings

import harness
from cases import CLIENT_TIMEOUT, case, reflexer_status, reflexers_leg_held_no_longer_than_the_timeout
from harness import STRAIGHT_TEXT, bedrock, standins
from harness.bedrock import BOTOCORE, SIGNING, Calls

ALL = bedrock.COLUMNS
HTTPX_LINES = ("anthropic-bedrock", "anthropic-mantle", "litellm")  # Bedrock's own lines on LiteLLM's and anthropic's HTTP clients
RUNTIME = f"https://{bedrock.RUNTIME}"
UPSTREAM = {"anthropic-mantle": f"https://{bedrock.MANTLE}/anthropic", "openai-compat": f"{RUNTIME}/openai",
            "anthropic-compat": f"{RUNTIME}/anthropic"}  # the rest: Bedrock's runtime
PATH = {"anthropic-mantle": "/anthropic/v1/messages", "openai-compat": "/openai/v1/chat/completions", "anthropic-compat": "/anthropic/v1/messages"}
NO_TOP_FIELD = "its calls put no field of the client's at the body's top"
SHIPPED = {lib: "the shipped line, at Bedrock's compatible route: its own cases are the shipped suite's" for lib in ("openai-compat", "anthropic-compat")}
VOLATILE = {"authorization", "x-amz-date", "amz-sdk-invocation-id", "amz-sdk-request", "x-stainless-retry-count", "x-stainless-read-timeout",
            "content-length"}  # what differs between two calls made alike: their time, their id, their signature


def bedrock_case(behaviour, libs=ALL, **options):
    return case(behaviour, sdks=libs, **options)


def served(t, outcome):
    t.check(outcome.error is None, f"the client's call failed: {outcome}")
    t.check(outcome.text == standins.SERVED_TEXT, f"expected reflexer's answer: {outcome}")
    t.check(t.to_reflexer(), "served, yet reflexer saw nothing")


def straight(t, outcome):
    t.check(outcome.error is None, f"the client's call failed: {outcome}")
    t.check(outcome.text == STRAIGHT_TEXT, f"expected Bedrock's answer: {outcome}")
    t.check(t.provider.seen, "answered, yet Bedrock saw nothing")


def signed_as_stock(t, calls, headers=None):
    """A signed call: straight, never at reflexer, its signature checked as Bedrock checks it, and what reached Bedrock as
    a stock client's same call, but for what differs between any two calls, and for `headers`, ours, which a stock client
    would send on."""
    stock = calls.client(line=False, keyed=False)
    calls.call(stock)
    as_stock = t.provider.seen[-1]
    outcome = calls.call(calls.client(keyed=False), headers=headers)
    straight(t, outcome)
    t.check(not t.reflexer.seen, f"a signed call reached reflexer: {t.reflexer.seen}")
    arrival = t.provider.seen[-1]
    t.check(bedrock.signature_holds(arrival), f"Bedrock refuses its signature: {arrival.headers.get('authorization', '')[:60]}")
    ours, stocks = ({name: re.sub(r" m/[^ ]+", "", value) if name == "user-agent" else value for name, value in each.headers.items()
                     if name not in VOLATILE and not name.startswith("reflexer-")} for each in (arrival, as_stock))
    # botocore's user agent names the features its process used so far (` m/`): two stock clients differ there too
    t.check(ours == stocks and arrival.body == as_stock.body, f"not as stock: {sorted(set(ours.items()) ^ set(stocks.items()))}")


# ---- routing: a call carrying a key reaches reflexer with both keys; a signed call never does

@bedrock_case("bedrock routing")
def bedrock_a_keyed_call_reaches_reflexer_with_both_keys(t):
    calls = Calls(t)
    served(t, calls.call(calls.client()))
    arrival = t.to_reflexer()[-1]
    auth = arrival.headers.get("authorization") or arrival.headers.get("x-api-key", "")
    t.check(arrival.headers.get("reflexer-key") == t.world.key, "reflexer's key missing")
    t.check(bedrock.BEARER in auth, f"the Bedrock API key missing: {auth[:20]}")
    t.check(arrival.headers.get("reflexer-upstream") == UPSTREAM.get(t.sdk, RUNTIME), f"upstream: {arrival.headers.get('reflexer-upstream')}")
    expected = PATH.get(t.sdk, "/bedrock/model/")
    t.check(arrival.path.startswith(expected), f"reached {arrival.path}, not {expected}")


@bedrock_case("bedrock routing")
def bedrock_each_operation_is_served(t):
    calls = Calls(t)
    client = calls.client()
    for op in calls.lib.ops:
        if op != "count_tokens":
            served(t, calls.call(client, op))
    t.note(f"{len([op for op in calls.lib.ops if op != 'count_tokens'])} operations served")


@bedrock_case("bedrock routing", libs=("boto3", "aiobotocore"))
def bedrock_count_tokens_goes_straight(t):
    calls = Calls(t)
    outcome = calls.call(calls.client(), "count_tokens")
    t.check(outcome.error is None and outcome.text == "tokens 3", f"{outcome}")
    t.check(not t.reflexer.seen and t.provider.seen, f"reflexer {len(t.reflexer.seen)}, Bedrock {len(t.provider.seen)}")


@bedrock_case("bedrock routing", libs=SIGNING)
def bedrock_a_signed_call_never_reaches_reflexer_and_is_as_stock(t):
    calls = Calls(t)
    signed_as_stock(t, calls)


@bedrock_case("bedrock routing", libs=("boto3",))
def sampling_on_bedrock_none_sends_all_straight(t):
    t.world.share = 0.0
    calls = Calls(t)
    client = calls.client()
    for _ in range(5):
        straight(t, calls.call(client))
    t.check(not t.to_reflexer(), f"reflexer got {len(t.to_reflexer())} calls at a share of none")


# ---- no harm: whatever fails on the way to reflexer, the client's own call still goes

def no_harm(name, arrange, libs=ALL):
    @bedrock_case("bedrock no harm", libs=libs, name=f"no_harm_on_bedrock_{name}")  # no shipped case's name inside: `--only` takes parts
    def check(t):
        calls = Calls(t)
        client = calls.client()
        arrange(t)
        straight(t, calls.call(client))
    return check


no_harm("reflexer_dead", lambda t: t.reflexer.set("dead"))
no_harm("connection_reset", lambda t: t.reflexer.set("reset"))
no_harm("balancers_own_answer", lambda t: t.reflexer.set("reply", status=401, body={"message": "made-up"}))
no_harm("reflexer_busy", lambda t: reflexer_status(t, 503, body={"message": "made-up"}))
no_harm("reflexer_500", lambda t: reflexer_status(t, 500, body={"message": "made-up"}))
no_harm("answer_dropped", lambda t: t.reflexer.set("drop"))
no_harm("answer_not_http", lambda t: t.reflexer.set("garbage"))
no_harm("certificate_not_trusted", lambda t: t.reflexer.set("badcert"))
no_harm("provider_unreachable_from_reflexer", lambda t: reflexer_status(t, 502, origin="connection", body={"message": "made-up"}))


@bedrock_case("bedrock no harm")
def no_harm_on_bedrock_an_answer_cut_is_an_error_never_sent_twice(t):
    """Reflexer's answer cut after its head: the client's error, as from Bedrock; never sent to Bedrock too."""
    calls = Calls(t)
    client = calls.client()
    t.reflexer.set("cut")
    outcome = calls.call(client)
    t.check(outcome.error is not None or outcome.text != standins.SERVED_TEXT, f"a cut answer read as whole: {outcome}")
    t.check(not t.provider.seen, f"sent to Bedrock too: {t.provider.seen}")


@bedrock_case("bedrock no harm", libs=tuple(lib for lib in SIGNING), na=SHIPPED)
def no_harm_on_bedrock_a_handshake_refused_once_is_tried_again(t):
    """Reflexer refuses one TLS handshake by an alert, as a garbled ClientHello is refused: no byte of the call left, so
    its leg is tried once more and served, and the breaker counts nothing: the next call is served too."""
    calls = Calls(t)
    client = calls.client()
    t.reflexer.set("ok", refuse_tls=1)
    served(t, calls.call(client))
    served(t, calls.call(client))
    t.check(t.reflexer.refused_tls == 1, f"{t.reflexer.refused_tls} handshakes refused, not one")


# ---- skip: one call straight, by an argument or a header; the flag never leaves the machine

@bedrock_case("bedrock skip")
def bedrock_skip_as_a_header_goes_straight(t):
    calls = Calls(t)
    straight(t, calls.call(calls.client(), headers=t.skip_headers()))
    t.check(not t.to_reflexer(), f"reflexer got a skipped call: {t.to_reflexer()}")


@bedrock_case("bedrock skip", libs=("boto3", "aiobotocore"))
def bedrock_skip_as_an_argument_goes_straight(t):
    calls = Calls(t)
    straight(t, calls.call(calls.client(), args={bedrock.ARGUMENT: True}))
    t.check(not t.to_reflexer(), f"reflexer got a skipped call: {t.to_reflexer()}")


@bedrock_case("bedrock skip")
def skip_on_bedrock_holds_for_one_call_only(t):
    calls = Calls(t)
    client = calls.client()
    calls.call(client, headers=t.skip_headers())
    served(t, calls.call(client))


SIGNS_EVERY_HEADER = {lib: "it signs every header: on a call it signs, the flag reaches Bedrock as the client set it, and the call "
                             "never goes to reflexer" for lib in ("anthropic-bedrock", "anthropic-mantle")}


@bedrock_case("bedrock skip", libs=tuple(lib for lib in SIGNING if lib not in SIGNS_EVERY_HEADER), na=SIGNS_EVERY_HEADER)
def bedrock_skip_on_a_signed_call_leaves_no_flag_and_the_signature_holds(t):
    calls = Calls(t)
    signed_as_stock(t, calls, headers=t.skip_headers())


# ---- the key, the replay, a redirect

@bedrock_case("bedrock bad key")
def bad_key_on_bedrock_raises_before_anything_is_sent(t):
    t.world.key = "rfx1_not-a-key"
    calls = Calls(t)
    try:
        calls.call(calls.client())
    except ValueError:
        pass
    else:
        t.check(False, "a key not of the form was taken")
    t.check(not t.reflexer.seen and not t.provider.seen, f"sent: reflexer {len(t.reflexer.seen)}, Bedrock {len(t.provider.seen)}")
    t.world.key = harness.make_key()  # the invariants' key


REPLAY_OP = {"boto3": "invoke", "aiobotocore": "invoke", "anthropic-bedrock": "invoke", "anthropic-mantle": "messages",
             "openai-compat": "chat", "anthropic-compat": "messages"}


@bedrock_case("bedrock replay", libs=tuple(REPLAY_OP), na={lib: NO_TOP_FIELD for lib in ALL if lib not in REPLAY_OP})
def bedrock_a_replay_reflexer_does_not_take_never_reaches_bedrock(t):
    calls = Calls(t)
    client = calls.client()
    reflexer_status(t, 503, body={"message": "made-up"})
    outcome = calls.call(client, REPLAY_OP[t.sdk], extra={"replay_response": {"id": "made-up"}})
    t.check(outcome.error is not None, f"a replay answered: {outcome}")
    t.check(not t.provider.seen, f"a replay reached Bedrock: {t.provider.seen}")


@bedrock_case("bedrock redirect")
def redirect_on_bedrock_relayed_by_reflexer_goes_straight(t):
    calls = Calls(t)
    client = calls.client()
    t.reflexer.set("redirect")
    straight(t, calls.call(client))
    t.check(not t.elsewhere.seen, f"the redirect was followed: {t.elsewhere.seen}")


# ---- timeout: the client's own holds on reflexer's leg

@bedrock_case("bedrock timeout", steady=True)
def bedrock_the_clients_timeout_holds_on_reflexers_leg(t):
    calls = Calls(t)
    client = calls.client(timeout=CLIENT_TIMEOUT)
    t.reflexer.set("stall")
    straight(t, calls.call(client))
    reflexers_leg_held_no_longer_than_the_timeout(t)


# ---- the breaker, and what the client's own client keeps

@bedrock_case("bedrock breaker", libs=("boto3", "anthropic-bedrock", "litellm"))
def bedrock_a_failure_opens_the_breaker(t):
    calls = Calls(t)
    client = calls.client()
    t.reflexer.set("dead")
    straight(t, calls.call(client))
    t.reflexer.set("ok")
    before = len(t.reflexer.seen)
    straight(t, calls.call(client))
    t.check(len(t.reflexer.seen) == before, "reflexer tried again within the breaker's backoff")


@bedrock_case("bedrock kept", libs=BOTOCORE)
def bedrock_a_handler_of_the_clients_that_answers_is_the_answer(t):
    """A `before-send` handler of the client's answers the call (a stub, a cache): reflexer is not asked, nor Bedrock."""
    import botocore.awsrequest
    calls = Calls(t)
    client = calls.client()
    events = (client if calls.lib.name in ("boto3", "aiobotocore") else client.client).meta.events
    body = json.dumps(bedrock.body_for("converse", "stubbed")).encode()

    class Raw:  # the stub's body, as each library's response reads it
        def stream(self, **_):
            return iter([body])

        async def read(self):
            return body
    if calls.lib.is_async:
        import aiobotocore.awsrequest
        answer = aiobotocore.awsrequest.AioAWSResponse("https://made-up", 200, {"content-type": "application/json"}, Raw())
    else:
        answer = botocore.awsrequest.AWSResponse("https://made-up", 200, {"content-type": "application/json"}, Raw())
    events.register_first("before-send.bedrock-runtime.Converse", lambda **_: answer)
    outcome = calls.call(client)
    t.check(outcome.error is None and "stubbed" in (outcome.text or ""), f"{outcome}")
    t.check(not t.reflexer.seen and not t.provider.seen, f"reflexer {len(t.reflexer.seen)}, Bedrock {len(t.provider.seen)}")


@bedrock_case("bedrock kept", libs=("anthropic-bedrock", "anthropic-mantle"))
def bedrock_the_sdks_own_copy_stays_on_reflexer(t):
    calls = Calls(t)
    served(t, calls.call(calls.client().with_options(max_retries=0)))


@bedrock_case("bedrock kept", libs=("boto3",))
def bedrock_a_closed_client_leaves_no_connection_to_reflexer(t):
    """Reflexer's leg goes by the client's own HTTP session: closing the client closes its connections to reflexer too."""
    calls = Calls(t)
    client = calls.client()
    served(t, calls.call(client))
    client.close()
    gone = time.monotonic() + 2.0
    while t.reflexer.connections and time.monotonic() < gone:
        time.sleep(0.02)
    t.check(not t.reflexer.connections, f"{len(t.reflexer.connections)} connections to reflexer left after close()")


@bedrock_case("bedrock kept", libs=("aiobotocore",))
def bedrock_aiobotocore_a_client_entered_in_a_second_event_loop_is_served(t):
    """One client, entered in one event loop, closed, then entered in another, as aiobotocore allows: reflexer's leg goes
    by the session aiobotocore opens for that loop, so the second loop's calls are served, and nothing is left unclosed."""
    import asyncio, aiobotocore.session, reflexer.aiobotocore
    t.env(AWS_BEARER_TOKEN_BEDROCK=bedrock.BEARER)
    made, held = aiobotocore.session.get_session().create_client("bedrock-runtime", **bedrock.boto3_kwargs({})), []

    async def use(first):
        if first:
            held.append(reflexer.aiobotocore.through(await made.__aenter__(), t.world.key))
        else:
            await held[0].__aenter__()
        texts = [await bedrock.LIBS["aiobotocore"].call(held[0], "converse") for _ in range(2)]
        await held[0].__aexit__(None, None, None)
        return texts

    with warnings.catch_warnings(record=True) as warned:
        warnings.simplefilter("always")
        texts = asyncio.run(use(True)) + asyncio.run(use(False))
        gc.collect()
    t.check(texts == [standins.SERVED_TEXT] * 4, f"served {texts}")
    unclosed = [str(each.message) for each in warned if "nclosed" in str(each.message)]
    t.check(not unclosed, f"left unclosed: {unclosed[:2]}")


@bedrock_case("bedrock kept")
def bedrock_the_key_stays_out_of_what_the_client_can_log(t):
    """Every logger at DEBUG, botocore's and the libraries' own among them: no record holds the reflexer key."""
    import logging
    root, level = logging.getLogger(), logging.getLogger().level
    root.setLevel(logging.DEBUG)
    try:
        calls = Calls(t)
        client = calls.client()
        served(t, calls.call(client))
        t.reflexer.set("dead")
        straight(t, calls.call(client))
    finally:
        root.setLevel(level)
    held = [record for record in t.logs.records if t.world.key in record]
    t.check(t.logs.records, "nothing was logged at DEBUG: the check saw nothing")
    t.check(not held, f"{len(held)} records hold the key: {held[0][:120] if held else ''}")
