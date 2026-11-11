"""What the SDK must do, as cases over real sockets, real TLS and the real provider SDKs.

A case: `@case("behaviour")` on `def name_said_as_the_behaviour(t)`, run once per SDK in a process of its own. `t` is a
`harness.Test`. Passing: returns. Failing: `t.check` or any exception. After each, `Test.invariants`: the reflexer key
and the skip's flag never arrived where they must not.
"""
import asyncio, json, logging, pickle, statistics, threading, time, typing

import harness
from harness import AZURE_ENDPOINT, SERVED_TEXT, STRAIGHT_TEXT, make_key, standins

CASES = []
MESSAGE_SDKS = ("openai", "anthropic", "gemini")
WITH_AZURE = MESSAGE_SDKS + ("azure",)
RAW_SDKS = ("openai", "anthropic", "azure")  # those with `with_raw_response` and `with_options`
DEFAULT_LIMIT = 25.0  # seconds a case may take, at most; past it the process is killed and the case fails
NO_RAW = "google-genai has no such method on its client"

# Stalls: a client's timeout, a slow provider, a slow pass through, in seconds
CLIENT_TIMEOUT, SLOW_PROVIDER, SLOW_PASS_THROUGH = 1.0, 0.6, 0.7
MARGIN = 0.6  # seconds of scheduling allowed on a real-time bound, on a machine running other cases
TRIES_ON_A_SLOW_MACHINE = 5  # a case bound to real time tries again when the machine was too slow to judge it
FIRST_BACKOFF, JITTER = 1.0, 0.2  # the breaker's first wait and its jitter, read only by the cases on doubling
QUICK_CALL = 0.1  # seconds: a call that paid no timeout


def case(behaviour, sdks=WITH_AZURE, limit=DEFAULT_LIMIT, open_on=(), na=None, name=None, steady=False):
    """`open_on`: SDKs on which a failure is **open**: a known gap, not built yet, reported and not failing the run.
    `na`: {sdk: why this SDK has no such thing}: stays in the table as cannot. `steady`: judged by real time, so a try
    during which the machine stalled the case's process (`harness.STALL`) is not judged, and is made again, afresh, up to
    `TRIES_ON_A_SLOW_MACHINE`; `limit` is then each try's."""
    def register(function):
        tries = TRIES_ON_A_SLOW_MACHINE if steady else 1
        CASES.append({"name": name or function.__name__, "behaviour": behaviour, "sdks": tuple(sdks), "limit": limit,
                      "tries": tries, "open_on": tuple(open_on), "na": na or {}, "run": function})
        return function
    return register


def overloaded(sdk):
    """The format's own overloaded status."""
    return 529 if sdk == "anthropic" else 503


def key_error(sdk):
    """The format's authentication error, naming reflexer's key: (status, body)."""
    if sdk == "gemini":
        return 400, {"error": {"code": 400, "message": "Reflexer-Key is not valid", "status": "INVALID_ARGUMENT"}}
    return 401, {"error": {"message": "Reflexer-Key is not valid", "type": "invalid_request_error", "code": "invalid_api_key"}}


def provider_error(sdk, status=429):
    if sdk == "gemini":
        return {"error": {"code": status, "message": "made-up", "status": "RESOURCE_EXHAUSTED"}}
    return {"error": {"message": "made-up", "type": "rate_limit_error"}}


def reflexer_status(t, status, origin="reflexer", more=None, body=None):
    headers = ({"Reflexer-Status-Origin": origin} if origin else {}) | {"Retry-After": "0"} | (more or {})
    t.reflexer.set("reply", status=status, headers=headers, body=body or provider_error(t.sdk, status))


def provider_key_at(arrival, sdk):
    return any(harness.PROVIDER_KEY[sdk] in value for value in arrival.headers.values())


def next_call_tries_reflexer(t, first):
    """`first(client)` makes a call that must not count against reflexer: had it counted, the client's breaker would
    hold its next call for the first backoff. So the next call goes well within it; a try on a machine too slow for that
    is made again with a fresh client, so slowness cannot pass a counted failure."""
    for _ in range(TRIES_ON_A_SLOW_MACHINE):
        client = t.client()  # each a breaker of its own
        began = time.monotonic()
        first(client)
        t.reflexer.set("ok")
        before = len(t.reflexer.seen)
        outcome = t.ask(client)
        arrived = [arrival.at for arrival in t.reflexer.seen[before:]]
        if not arrived or arrived[0] - began < FIRST_BACKOFF / 2:  # judged by when it reached reflexer, not when it began
            return t.served(outcome)
    t.check(False, f"no try fast enough to judge, in {TRIES_ON_A_SLOW_MACHINE}")


def not_counted(t, failing):
    """A response that sends the call straight without counting against reflexer."""
    def first(client):
        failing()
        t.straight(t.ask(client))
    next_call_tries_reflexer(t, first)


def spam_until(condition, seconds, call, pause=0.005):
    """Calls one at a time until `condition()`, or `seconds` pass. Returns the seconds it took, or None."""
    began = time.monotonic()
    while time.monotonic() - began < seconds:
        call()
        if condition():
            return time.monotonic() - began
        time.sleep(pause)
    return None


# ---- skip: pass through per call; the flag never leaves the machine

@case("skip")
def skip_goes_straight_and_its_flag_stays_here(t):
    client = t.client()
    outcome = t.skip(client)
    t.straight(outcome)
    t.check(not t.to_reflexer(), f"reflexer got a skipped call: {t.to_reflexer()}")


@case("skip")
def skip_holds_for_one_call_only(t):
    client = t.client()
    t.skip(client)
    t.served(t.ask(client))


# ---- sampling: a share of calls to reflexer, the rest straight

SAMPLED_CALLS = 200
A_TENTH = 0.1
FOUR_SIGMA = 4 * (SAMPLED_CALLS * A_TENTH * (1 - A_TENTH)) ** 0.5  # a binomial's spread: a bound with a source


def sampled(t, share):
    t.world.share = share
    client = t.client()
    for _ in range(SAMPLED_CALLS):
        outcome = t.ask(client)
        t.check(outcome.error is None, f"a call failed: {outcome}")
    return len(t.to_reflexer()), len(t.provider.seen)


@case("sampling")
def sampling_none_sends_all_straight(t):
    reached, straight = sampled(t, 0.0)
    t.check((reached, straight) == (0, SAMPLED_CALLS), f"share none: reflexer {reached}, provider {straight}")


@case("sampling")
def sampling_full_sends_all_to_reflexer(t):
    reached, straight = sampled(t, 1.0)
    t.check((reached, straight) == (SAMPLED_CALLS, 0), f"share full: reflexer {reached}, provider {straight}")


@case("sampling")
def sampling_a_tenth_sends_about_a_tenth(t):
    reached, straight = sampled(t, A_TENTH)
    t.check(reached + straight == SAMPLED_CALLS, f"calls lost: reflexer {reached}, provider {straight}")
    t.check(abs(reached - SAMPLED_CALLS * A_TENTH) <= FOUR_SIGMA, f"share a tenth of {SAMPLED_CALLS}: reflexer {reached}")


# ---- routing: only message calls go to reflexer; `Reflexer-Key` and `Reflexer-Upstream` built

MESSAGE_PATH = {
    "openai": "/openai/v1/chat/completions",
    "anthropic": "/anthropic/v1/messages",
    "gemini": "/gemini/v1beta/models/frontier-z:generateContent",
    "azure": f"/azure/openai/deployments/frontier-d/chat/completions?api-version={harness.AZURE_VERSION}",
}


@case("routing")
def routing_a_message_call_reaches_reflexer_with_both_keys(t):
    t.served(t.ask(t.client()))
    arrival = t.reflexer.seen[0]
    t.check(arrival.host == "api.reflexer.ai", f"host {arrival.host}")
    t.check(arrival.path == MESSAGE_PATH[t.sdk], f"path {arrival.path}, expected {MESSAGE_PATH[t.sdk]}")
    t.check(arrival.headers.get("reflexer-key") == t.world.key, "no Reflexer-Key on it")
    t.check(provider_key_at(arrival, t.sdk), "the provider's key is not on it")
    upstream = arrival.headers.get("reflexer-upstream")
    t.check(upstream == (AZURE_ENDPOINT if t.sdk == "azure" else None), f"Reflexer-Upstream {upstream}")
    t.check(not t.provider.seen, "served, and the provider was called too")


@case("routing", sdks=("openai",))
def routing_openai_responses_reach_reflexer(t):
    client = t.client()
    answer = client.responses.create(model="frontier-x", input="Hi")
    t.note(f"answered {answer.output_text!r}")
    t.check(answer.output_text == SERVED_TEXT, answer.output_text)
    t.check(t.reflexer.seen[0].path == "/openai/v1/responses", t.reflexer.seen[0].path)


@case("routing", sdks=("azure",))
def routing_azure_responses_reach_reflexer(t):
    answer = t.client().responses.create(model="frontier-d", input="Hi")
    t.check(answer.output_text == SERVED_TEXT, answer.output_text)
    t.check(t.reflexer.seen[0].path == f"/azure/openai/responses?api-version={harness.AZURE_VERSION}", t.reflexer.seen[0].path)


@case("routing")
def routing_a_stream_call_reaches_reflexer(t):
    t.served(t.stream(t.client()))
    path = t.reflexer.seen[0].path
    t.check(path.startswith(MESSAGE_PATH[t.sdk].replace(":generateContent", ":streamGenerateContent")), path)


@case("routing")
def routing_other_calls_go_straight(t):
    client = t.client()
    made = client.models.list()
    list(made) if t.sdk == "gemini" else made
    t.check(not t.reflexer.seen, f"reflexer got a call that is no message: {t.reflexer.seen}")
    t.check(t.provider.seen, "the provider got nothing")
    t.note(f"the provider got {t.provider.seen[0]}")


ROUTER_BASE = {"openai": "https://openrouter.ai/api/v1", "anthropic": "https://openrouter.ai/api", "gemini": "https://openrouter.ai/api/"}


@case("routing", sdks=("anthropic", "gemini"))
def routing_a_router_is_named_as_the_upstream(t):
    t.served(t.ask(t.client(base_url=ROUTER_BASE[t.sdk])))
    upstream = t.reflexer.seen[0].headers.get("reflexer-upstream")
    t.check(upstream == "https://openrouter.ai/api", f"Reflexer-Upstream {upstream}")
    t.note(f"upstream {upstream}")


@case("routing", sdks=("openai",))
def routing_a_router_with_a_route_of_its_own_takes_it(t):
    t.served(t.ask(t.client(base_url=ROUTER_BASE[t.sdk])))
    arrival = t.reflexer.seen[0]
    t.check(arrival.path == "/openrouter/api/v1/chat/completions", f"path {arrival.path}")
    t.check("reflexer-upstream" not in arrival.headers, f"Reflexer-Upstream {arrival.headers.get('reflexer-upstream')}")


@case("routing", sdks=("openai",))
def routing_a_hosted_runner_is_named_as_the_upstream(t):
    t.served(t.ask(t.client(base_url="https://api.groq.com/openai/v1")))
    upstream = t.reflexer.seen[0].headers.get("reflexer-upstream")
    t.check(upstream == "https://api.groq.com/openai", f"Reflexer-Upstream {upstream}")


@case("routing", sdks=MESSAGE_SDKS)
def routing_a_runner_on_this_machine_goes_straight(t):
    """Reflexer cannot reach a runner on the client's machine: the call goes straight."""
    suffix = "/v1" if t.sdk == "openai" else ""
    outcome = t.ask(t.client(base_url=f"http://127.0.0.1:{t.runner.port}{suffix}"))
    t.check(outcome.error is None, f"{outcome}")
    t.check(not t.to_reflexer(), f"reflexer got it: {t.to_reflexer()}")
    t.check(t.runner.seen, "the runner got nothing")


@case("routing", sdks=MESSAGE_SDKS)
def routing_a_plain_http_base_goes_straight(t):
    suffix = "/v1" if t.sdk == "openai" else ""
    outcome = t.ask(t.client(base_url=f"http://runner.example{suffix}"))
    t.check(outcome.error is None, f"{outcome}")
    t.check(not t.to_reflexer(), f"reflexer got it: {t.to_reflexer()}")
    t.check(t.runner.seen, "the runner got nothing")


@case("routing")
def routing_the_key_never_reaches_a_provider(t):
    client = t.client()
    t.served(t.ask(client))
    t.skip(client)
    t.reflexer.set("busy", status=overloaded(t.sdk))
    t.ask(client)
    t.check(len(t.provider.seen) == 2, f"provider saw {t.provider.seen}")
    for arrival in t.provider.seen:
        t.check("reflexer-key" not in arrival.headers, f"Reflexer-Key at the provider: {arrival}")
        t.check(not [name for name in arrival.headers if name.startswith("reflexer-")], f"a header of ours at the provider: {arrival.headers}")
        t.check(provider_key_at(arrival, t.sdk), f"its own key missing at the provider: {arrival}")


@case("routing", sdks=WITH_AZURE)
def routing_the_body_is_the_clients_on_both_legs(t):
    client = t.client()
    reflexer_status(t, overloaded(t.sdk))
    t.straight(t.ask(client))
    sent, straight = t.reflexer.seen[0].body, t.provider.seen[0].body
    t.check(sent == straight, f"reflexer got {sent[:80]!r}, the provider {straight[:80]!r}")


# ---- bad key: a key not of the form raises before anything is sent

BAD_KEYS = {"cut": "rfx1_typo", "wrong checksum": make_key()[:-1] + ("a" if make_key()[-1] != "a" else "b"),
            "missing": None, "another's form": "sk-made-up"}


@case("bad key", sdks=MESSAGE_SDKS)
def bad_key_raises_before_anything_is_sent(t):
    for label, key in BAD_KEYS.items():
        t.world.key = key
        raised = None
        try:
            outcome = t.ask(t.client())
            raised = outcome.error
        except Exception as error:
            raised = error
        t.world.key = harness.make_key()
        everything = t.reflexer.seen + t.provider.seen
        t.check(raised is not None, f"{label}: nothing raised")
        t.check(not everything, f"{label}: raised {type(raised).__name__}, after sending {everything}")
    t.note(f"each of {len(BAD_KEYS)} raised {type(raised).__name__}, nothing sent")


# ---- no harm: whatever fails on the way to reflexer, the client's own call still goes

def no_harm(name, arrange, sdks=WITH_AZURE):
    @case("no harm", sdks=sdks, name=f"no_harm_{name}")
    def check(t):
        client = t.client()
        arrange(t)
        outcome = t.ask(client)
        t.straight(outcome)
    return check


no_harm("reflexer_dead", lambda t: t.reflexer.set("dead"))
no_harm("connection_reset", lambda t: t.reflexer.set("reset"))
no_harm("balancers_own_answer", lambda t: t.reflexer.set("reply", status=key_error(t.sdk)[0], body=key_error(t.sdk)[1]))
no_harm("reflexer_busy", lambda t: reflexer_status(t, overloaded(t.sdk)))
no_harm("reflexer_500", lambda t: reflexer_status(t, 500))
no_harm("reflexer_429", lambda t: reflexer_status(t, 429))
no_harm("answer_dropped", lambda t: t.reflexer.set("drop"))
no_harm("answer_not_http", lambda t: t.reflexer.set("garbage"))
no_harm("certificate_not_trusted", lambda t: t.reflexer.set("badcert"))
no_harm("provider_unreachable_from_reflexer", lambda t: reflexer_status(t, 502, origin="connection"))


@case("no harm", sdks=("openai", "anthropic", "azure"), steady=True)
def no_harm_with_the_sdks_own_retries(t):
    """`max_retries` left to the SDK's default: a dead reflexer costs no retry's wait."""
    t.reflexer.set("dead")
    t.straight(t.ask(t.client(retries=None)))
    t.check(t.last.wall < 1.0 + MARGIN, f"waited {t.last.wall:.2f}s")


# ---- breaker: a failure sends the call straight and backs off, doubling, with jitter, in flight counted once;
#      `Reflexer-Straight` obeyed after two in a row; a provider's status never trips it

@case("breaker", steady=True)
def breaker_opens_on_a_failure(t):
    client = t.client()
    t.reflexer.set("reset")
    t.straight(t.ask(client))
    tried = len(t.reflexer.seen)
    t.check(tried == 1, f"tried reflexer {tried} times on one call")
    t.straight(t.ask(client))
    t.check(len(t.reflexer.seen) == 1, f"tried again at once: {len(t.reflexer.seen)}")
    t.check(t.last.wall < QUICK_CALL + MARGIN, f"the next call waited {t.last.wall:.2f}s")


def attempts_while_dead(t, client, seconds):
    t.reflexer.set("reset")
    began = time.monotonic()
    while time.monotonic() - began < seconds:
        t.ask(client)
        t.check(t.last.error is None, f"a call failed while reflexer was dead: {t.last}")
        time.sleep(0.005)
    return [a.at for a in t.reflexer.seen if a.path is None]


DOUBLING_WINDOW = 9.0  # seconds: 1, 2 and 4 with jitter end inside it


@case("breaker", sdks=("openai",), steady=True)
def breaker_backs_off_doubling(t):
    """The cap is in `tests/test_logic.py`, on a clock: reaching it here would take minutes."""
    times = attempts_while_dead(t, t.client(), DOUBLING_WINDOW)
    gaps = [later - earlier for earlier, later in zip(times, times[1:])]
    t.note("gaps " + ", ".join(f"{gap:.2f}" for gap in gaps))
    t.check(len(gaps) >= 3, f"expected three waits in {DOUBLING_WINDOW}s, saw {len(gaps)}")
    least_ratio = 2 / (1 + JITTER)
    for earlier, later in zip(gaps, gaps[1:]):
        t.check(later >= earlier * least_ratio * 0.9, f"a wait did not double: {earlier:.2f}, then {later:.2f}")


JITTER_RUNS = 8


@case("breaker", sdks=("openai",), limit=30.0)
def measure_how_far_apart_clients_return(t):
    """Records the spread of the first waits of clients failing at once. On a shared machine its noise is as large as the
    jitter, so no bound is held here: tests/test_logic.py holds the jitter, on a clock of its own."""
    waits = []
    for _ in range(JITTER_RUNS):
        t.reflexer.seen.clear()
        t.reflexer.set("reset")
        client = t.client()
        t.ask(client)
        began = time.monotonic()
        waited = spam_until(lambda: len(t.reflexer.seen) >= 2, 4.0, lambda: t.ask(client))
        t.check(waited is not None, "it never tried reflexer again")
        waits.append(time.monotonic() - began)
    t.note("first waits " + ", ".join(f"{wait:.3f}" for wait in waits))
    t.data["spread"] = round(max(waits) - min(waits), 3)


@case("breaker", sdks=("openai",), steady=True)
def breaker_an_answer_resets_the_backoff(t):
    """Two failures double the wait; one answer; the next failure waits the first wait again, not the next double."""
    client = t.client()
    t.reflexer.set("reset")
    t.ask(client)
    t.check(spam_until(lambda: len(t.reflexer.seen) >= 2, FIRST_BACKOFF * 2, lambda: t.ask(client)) is not None, "no return after the first wait")
    t.reflexer.set("ok")
    t.check(spam_until(lambda: t.reflexer.seen[-1].path is not None, FIRST_BACKOFF * 4, lambda: t.ask(client)) is not None, "no return to reflexer")
    t.reflexer.set("reset")
    before = len(t.reflexer.seen)
    t.ask(client)
    t.check(len(t.reflexer.seen) == before + 1, "an answer did not close it")
    began = time.monotonic()
    waited = spam_until(lambda: len(t.reflexer.seen) > before + 1, FIRST_BACKOFF * 2, lambda: t.ask(client))
    t.note(f"after an answer, the wait was {time.monotonic() - began:.2f}s")
    t.check(waited is not None, f"the wait did not go back to the first: over {FIRST_BACKOFF * 2}s")


FLIGHT = 8  # calls in flight when reflexer fails


@case("breaker", sdks=("openai",), steady=True)
def breaker_counts_calls_in_flight_once(t):
    client = t.client()
    t.reflexer.set("busy", delay=0.3)
    threads = [threading.Thread(target=lambda: request_quiet(t, client)) for _ in range(FLIGHT)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    t.check(len(t.reflexer.seen) == FLIGHT, f"reflexer saw {len(t.reflexer.seen)} of {FLIGHT}")
    t.reflexer.set("ok")
    began = time.monotonic()
    waited = spam_until(lambda: len(t.reflexer.seen) > FLIGHT, FIRST_BACKOFF * 4, lambda: t.ask(client))
    t.note(f"{FLIGHT} failures in flight, then a wait of {(time.monotonic() - began):.2f}s")
    t.check(waited is not None and waited < FIRST_BACKOFF * 2, f"backed off as if counted each: {waited}")


def request_quiet(t, client):
    harness.request(t.sdk, client, False, False, {})


@case("breaker")
def breaker_a_providers_status_never_trips_it(t):
    client = t.client()
    for status in (429, 500):
        t.reflexer.set("reply", status=status, headers=standins.PROVIDERS_THROUGH_US | {"Retry-After": "0"}, body=provider_error(t.sdk, status))
        outcome = t.ask(client)
        t.check(outcome.error is not None, f"the provider's {status} did not reach the client: {outcome}")
    t.check(not t.provider.seen, f"a provider's status was sent straight: {t.provider.seen}")
    t.reflexer.set("ok")
    t.served(t.ask(client))
    t.check(len(t.to_reflexer()) == 3, f"reflexer saw {len(t.to_reflexer())}: the breaker opened")


@case("breaker", sdks=MESSAGE_SDKS)
def breaker_one_straight_header_is_not_obeyed(t):
    client = t.client()
    t.reflexer.set("ok", headers={"Reflexer-Straight": "30"})
    t.served(t.ask(client))
    t.reflexer.set("ok")
    t.served(t.ask(client))
    t.check(len(t.to_reflexer()) == 2, f"reflexer saw {len(t.to_reflexer())}: one response alone sent it away")


STRAIGHT_SECONDS = 1


@case("breaker", sdks=MESSAGE_SDKS, steady=True)
def breaker_two_straight_headers_are_obeyed_then_it_returns(t):
    client = t.client()
    t.reflexer.set("ok", headers={"Reflexer-Straight": str(STRAIGHT_SECONDS)})
    t.served(t.ask(client))
    t.served(t.ask(client))
    t.reflexer.set("ok")
    began = time.monotonic()
    t.straight(t.ask(client))
    t.check(len(t.to_reflexer()) == 2, f"not obeyed: reflexer saw {len(t.to_reflexer())}")
    waited = spam_until(lambda: len(t.to_reflexer()) >= 3, STRAIGHT_SECONDS * 3, lambda: t.ask(client))
    t.check(waited is not None, f"it never returned after {STRAIGHT_SECONDS}s")
    gone = time.monotonic() - began
    t.note(f"straight for {gone:.2f}s")
    t.check(gone >= STRAIGHT_SECONDS * 0.8, f"it returned after {gone:.2f}s, told {STRAIGHT_SECONDS}")


@case("breaker", sdks=("openai",))
def breaker_a_straight_header_it_does_not_know_is_ignored(t):
    client = t.client()
    for value in ("soon", "-5", "1.5"):
        t.reflexer.set("ok", headers={"Reflexer-Straight": value})
        t.served(t.ask(client))
        t.served(t.ask(client))
    t.check(len(t.to_reflexer()) == 6, f"reflexer saw {len(t.to_reflexer())} of 6")


@case("breaker", sdks=MESSAGE_SDKS)
def breaker_busy_with_straight_goes_straight_uncounted(t):
    not_counted(t, lambda: reflexer_status(t, overloaded(t.sdk), more={"Reflexer-Straight": "30"}))


@case("breaker", sdks=MESSAGE_SDKS)
def breaker_provider_unreachable_is_not_counted(t):
    not_counted(t, lambda: reflexer_status(t, 502, origin="connection"))


# The outage trace. A dead phase resets connections, so that its attempts are counted.
UP, DEAD, BUSY, STALLED = "up", "dead", "busy", "stalled"
TRACE = ((UP, 3.0), (DEAD, 8.0), (UP, 10.0), (BUSY, 6.0), (UP, 8.0), (STALLED, 6.0), (UP, 10.0))
TRACE_RATE = 100  # calls a second at most, one at a time, each on a fixed timeline: a slower client makes fewer
TRACE_TRIES = 2  # a try a stall of the machine left unjudged is run once more
TRACE_LIMIT = TRACE_TRIES * sum(seconds for _, seconds in TRACE) + 25.0
ONE_PERCENT = 0.01


def set_phase(t, phase):
    if phase == UP:
        t.reflexer.set("ok")
    elif phase == DEAD:
        t.reflexer.set("reset")
    elif phase == BUSY:
        t.reflexer.set("busy")
    else:
        t.reflexer.set("stall")


def run_trace(t, share):
    t.world.share = share
    client = t.client()
    rows, began = [], time.monotonic()
    slot = 0
    for phase, seconds in TRACE:
        set_phase(t, phase)
        row = {"phase": phase, "seconds": seconds, "calls": 0, "to_reflexer": 0, "failed": 0, "paid_timeout": 0, "wall": 0.0}
        before = len(t.to_reflexer())
        ends = time.monotonic() + seconds
        while time.monotonic() < ends:
            outcome = t.ask(client, timeout=CLIENT_TIMEOUT)
            row["calls"] += 1
            row["wall"] += outcome.wall
            row["failed"] += outcome.error is not None
            row["paid_timeout"] += outcome.wall >= CLIENT_TIMEOUT * 0.9
            slot += 1
            ahead = began + slot / TRACE_RATE - time.monotonic()
            if ahead > 0:
                time.sleep(ahead)
        row["to_reflexer"] = len(t.to_reflexer()) - before
        row["wall"] = round(row["wall"], 2)
        rows.append(row)
    t.data["trace"] = rows
    for row in rows:
        t.note(f"{row['phase']} {row['seconds']:.0f}s: {row['calls']} calls, {row['to_reflexer']} to reflexer, {row['paid_timeout']} paid the timeout, {row['failed']} failed")
    return rows


def traced(t, share):
    """The rows of a try the machine did not stall. In an up phase reflexer answers at once, so a call there that paid
    the client's timeout was the machine's stall: it counted a failure the breaker's backoff then doubles on through the
    busy and stalled phases, with no answer between to reset it, and the last phase cannot see it return."""
    for _ in range(TRACE_TRIES):
        rows = run_trace(t, share)
        if not any(row["paid_timeout"] for row in rows if row["phase"] == UP):
            return rows
        t.note("a call paid the timeout in an up phase: the machine stalled; tried again")
    t.check(False, f"a call paid the timeout in an up phase, where reflexer answers at once, on each of {TRACE_TRIES} tries: "
                   f"the machine stalled each time, or the SDK waits on an answering reflexer: {rows}")


def judge_trace(t, rows, share):
    t.check(sum(row["failed"] for row in rows) == 0, "a client's call failed during the outage")
    for row in rows:
        if row["phase"] == DEAD:
            allowed = max(row["calls"] * share * 0.25, 8)
            t.check(row["to_reflexer"] <= allowed, f"{row['to_reflexer']} calls tried a dead reflexer of {row['calls']}, at most {allowed:.0f}")
    last = rows[-1]
    expected = last["calls"] * share
    t.check(last["to_reflexer"] >= expected * 0.3, f"after the outage {last['to_reflexer']} of {last['calls']} reached reflexer, share {share}: it did not return")


@case("breaker", sdks=("openai",), limit=TRACE_LIMIT)
def breaker_outage_trace_at_the_full_share(t):
    judge_trace(t, traced(t, 1.0), 1.0)
    t.last = None


@case("breaker", sdks=("openai",), limit=TRACE_LIMIT)
def breaker_outage_trace_at_the_one_percent_share(t):
    """Few calls reach reflexer at this share: a direction, not a rate."""
    judge_trace(t, traced(t, ONE_PERCENT), ONE_PERCENT)
    t.last = None


# ---- grace: a key "Expired" under a day goes straight, with a warning; otherwise the error reaches the client

@case("grace")
def grace_a_key_expired_under_a_day_goes_straight_with_a_warning(t):
    client = t.client()
    status, body = key_error(t.sdk)
    t.reflexer.set("reply", status=status, headers={"Reflexer-Status-Origin": "reflexer", "Reflexer-Straight": "3600"}, body=body)
    t.straight(t.ask(client))
    said = t.logs.records
    t.check(said, "no warning was logged")
    t.note(f"warned: {said[0][:70]}")


@case("grace")
def grace_a_key_expired_over_a_day_raises_to_the_client(t):
    client = t.client()
    status, body = key_error(t.sdk)
    t.reflexer.set("reply", status=status, headers={"Reflexer-Status-Origin": "reflexer"}, body=body)
    outcome = t.ask(client)
    t.check(outcome.error is not None, f"expected the key's error: {outcome}")
    t.check(not t.provider.seen, f"it went straight: {t.provider.seen}")
    t.check("Reflexer-Key" in str(outcome.error), f"the error does not name the key: {outcome.error}")


# ---- timeout: the client's per-call timeout holds on reflexer's leg. Stall's cases, a client's timeout of 1 s.

@case("timeout", steady=True)
def timeout_the_clients_holds_on_reflexers_leg(t):
    client = t.client()
    t.reflexer.set("stall")
    outcome = t.ask(client, timeout=CLIENT_TIMEOUT)
    t.straight(outcome)
    t.check(t.reflexer.seen, "reflexer's leg was not tried")
    reflexers_leg_held_no_longer_than_the_timeout(t)


def reflexers_leg_held_no_longer_than_the_timeout(t):
    """How long the client stayed on stalled reflexer, read once the stand-in noticed it left: a moment later, on a
    thread a busy machine may be slow to schedule."""
    arrival, noticed_by = t.reflexer.seen[0], time.monotonic() + MARGIN
    while arrival.left_after is None and time.monotonic() < noticed_by:
        time.sleep(0.01)
    held = arrival.left_after
    t.note(f"the client left reflexer after {held and round(held, 2)}s")
    t.check(held is not None and held <= CLIENT_TIMEOUT + MARGIN, f"reflexer's leg held {held}s")


def stock_wall(t, slow):
    """The same call against a stock client, to compare with."""
    t.provider.set("ok", delay=slow)
    outcome = t.ask(t.stock(), timeout=CLIENT_TIMEOUT)
    wall = outcome.wall
    t.provider.seen.clear()
    return wall, outcome


@case("timeout", steady=True)
def stall_reflexer_stalled_provider_at_six_tenths(t):
    """Stock answers it in 0.6 s. The SDK waits out the client's timeout on a stalled reflexer, then goes straight:
    the cost is bounded here; telling a stalled reflexer from a slow provider is open, below."""
    stock, outcome = stock_wall(t, SLOW_PROVIDER)
    t.check(outcome.error is None, f"stock failed: {outcome}")
    client = t.client()
    t.reflexer.set("stall")
    outcome = t.ask(client, timeout=CLIENT_TIMEOUT)
    t.note(f"stock answered in {stock:.2f}s")
    t.data |= {"stock_wall": round(stock, 3), "wall": round(outcome.wall, 3)}
    t.straight(outcome)
    t.check(outcome.wall <= CLIENT_TIMEOUT + SLOW_PROVIDER + MARGIN, f"waited {outcome.wall:.2f}s")


@case("timeout", steady=True)
def stall_slow_pass_through_at_seven_tenths(t):
    """Stock answers it in 0.7 s; reflexer's leg must not be given up on, nor the provider called too."""
    stock, outcome = stock_wall(t, SLOW_PASS_THROUGH)
    t.check(outcome.error is None, f"stock failed: {outcome}")
    t.provider.set("ok")
    client = t.client()
    t.reflexer.set("passed", delay=SLOW_PASS_THROUGH)
    outcome = t.ask(client, timeout=CLIENT_TIMEOUT)
    t.note(f"stock answered in {stock:.2f}s")
    t.data |= {"stock_wall": round(stock, 3), "wall": round(outcome.wall, 3), "reflexer": len(t.to_reflexer()), "provider": len(t.provider.seen)}
    t.check(outcome.error is None, f"the pass through did not reach the client: {outcome}")
    t.check(not t.provider.seen, f"both legs were called: {t.provider.seen}")


STALL_RUN = 12.0  # seconds


@case("timeout", sdks=("openai",), limit=STALL_RUN + 15.0)
def stall_every_call_answered_while_reflexer_stalls(t):
    """Counts the calls that paid a whole timeout, one call at a time. All must be answered."""
    client = t.client()
    t.reflexer.set("stall")
    calls = paid = 0
    ends = time.monotonic() + STALL_RUN
    while time.monotonic() < ends:
        outcome = t.ask(client, timeout=CLIENT_TIMEOUT)
        t.check(outcome.error is None, f"a call failed: {outcome}")
        calls += 1
        paid += outcome.wall >= CLIENT_TIMEOUT * 0.9
    t.last = None
    t.data |= {"calls": calls, "paid_timeout": paid}
    t.note(f"{paid} of {calls} calls paid a full timeout in {STALL_RUN:.0f}s")
    t.check(calls >= STALL_RUN // CLIENT_TIMEOUT, f"only {calls} calls in {STALL_RUN}s")


@case("timeout", open_on=WITH_AZURE)
def open_a_stalled_reflexer_told_from_a_slow_provider(t):
    """Open: reflexer stalled, the provider at 0.6 s; answered inside the client's 1 s only if the SDK could tell
    the two apart, which it cannot yet."""
    t.provider.set("ok", delay=SLOW_PROVIDER)
    client = t.client()
    t.reflexer.set("stall")
    outcome = t.ask(client, timeout=CLIENT_TIMEOUT)
    t.straight(outcome)
    t.check(outcome.wall < CLIENT_TIMEOUT, f"took {outcome.wall:.2f}s against the client's {CLIENT_TIMEOUT}s")


# ---- redirect: a redirect relayed by reflexer goes straight; the reflexer key never follows one

def relayed_redirect(t, status, ours):
    client = t.client()
    t.reflexer.set("reply", status=status, headers=ours | {"location": standins.REDIRECT_TARGET}, body=b"")
    t.straight(t.ask(client))
    t.check(not t.elsewhere.seen, f"the redirect was followed: {t.elsewhere.seen}")


@case("redirect")
def redirect_relayed_by_reflexer_goes_straight(t):
    relayed_redirect(t, 307, standins.PROVIDERS_THROUGH_US)


@case("redirect")
def redirect_with_none_of_our_headers_goes_straight(t):
    relayed_redirect(t, 302, {})


MESSAGE_PATH_AT_A_PROVIDER = {"openai": "/v1/chat/completions", "anthropic": "/v1/messages", "gemini": "/v1beta/models/frontier-z:generateContent",
                              "azure": "/openai/deployments/frontier-d/chat/completions"}


@case("redirect")
def redirect_on_a_straight_call_stays_straight(t):
    """Its target looks like a message call, so a hop that lost the call's mark would go to reflexer."""
    client = t.client(http={"follow_redirects": True})
    t.provider.set("reply", status=302, headers={"location": f"https://elsewhere.example{MESSAGE_PATH_AT_A_PROVIDER[t.sdk]}"}, body=b"")
    outcome = t.skip(client)
    t.check(outcome.error is None, f"{outcome}")
    t.check(t.elsewhere.seen, "the client's own redirect was not followed")
    t.check(not t.reflexer.seen, f"a hop of a straight call reached reflexer: {t.reflexer.seen}")


@case("redirect")
def redirect_the_clients_setting_holds(t):
    client = t.client(http={"follow_redirects": False})
    t.provider.set("reply", status=302, headers={"location": "https://elsewhere.example/x"}, body=b"")
    t.skip(client)
    t.check(not t.elsewhere.seen, f"the client said not to follow: {t.elsewhere.seen}")


# ---- fields: what reflexer writes, the request id at `id`, reflexer in `model`, the price at `usage.cost`; the SDK
#      leaves them as they came

EXPECTED_FIELDS = {"request_id": standins.REQUEST_ID, "answered_by": "reflexer", "cost": int(standins.SERVED_COST)}
EXPECTED_COST = int(standins.SERVED_COST) / 10**9


@case("fields")
def fields_on_a_served_answer(t):
    outcome = t.ask(t.client())
    t.served(outcome)
    ours = harness.fields(t.sdk, outcome.answer)
    t.check(ours == EXPECTED_FIELDS, f"it says {ours}")
    t.note(f"it says {ours}")


@case("fields", sdks=("openai", "azure", "anthropic", "gemini"))
def fields_a_served_answers_model_shows_reflexer(t):
    """A tool's cost-by-model shows reflexer, with the frontier name for a tool that prices from a table."""
    outcome = t.ask(t.client())
    t.served(outcome)
    model = outcome.answer.model_version if t.sdk == "gemini" else outcome.answer.model
    t.check(model.endswith("-reflexer") and model.startswith("frontier-"), f"its model is {model}")


@case("fields")
def fields_in_the_objects_dump(t):
    outcome = t.ask(t.client())
    t.served(outcome)
    dump = outcome.answer.model_dump()
    price = dump["sdk_http_response"]["headers"]["reflexer-cost-nano-usd"] if t.sdk == "gemini" else dump["usage"]["cost"]
    t.check(price in (standins.SERVED_COST, EXPECTED_COST), f"its dump holds {price}")


@case("fields", sdks=("openai", "anthropic", "azure"))
def fields_a_pass_through_keeps_the_providers_cost(t):
    PROVIDER_COST = 0.0042
    t.reflexer.set("passed", usage={"cost": PROVIDER_COST})
    outcome = t.ask(t.client())
    t.check(outcome.error is None, f"{outcome}")
    cost = harness.usage_cost(t.sdk, outcome.answer)
    t.check(cost == PROVIDER_COST, f"usage.cost is {cost}, the provider's is {PROVIDER_COST}")


@case("fields", sdks=("gemini",))
def fields_a_pass_through_writes_no_cost(t):
    t.reflexer.set("passed")
    outcome = t.ask(t.client())
    t.check(outcome.error is None, f"{outcome}")
    t.check(t.to_reflexer() and not t.provider.seen, f"it did not pass through reflexer: {t.saw()}")
    t.check(harness.usage_cost(t.sdk, outcome.answer) is None, "a cost written on a pass through")


@case("fields")
def fields_an_answer_that_went_straight_carries_none(t):
    client = t.client()
    reflexer_status(t, overloaded(t.sdk))
    outcome = t.ask(client)
    t.straight(outcome)
    ours = harness.fields(t.sdk, outcome.answer)
    t.check(not ours, f"a straight answer carries {ours}")


@case("fields", sdks=("openai", "azure", "anthropic"))
def fields_a_streams_usage_holds_the_price(t):
    outcome = t.stream(t.client())
    t.served(outcome)
    prices = [harness.usage_cost(t.sdk, chunk) for chunk, _ in outcome.chunks]
    t.check(EXPECTED_COST in prices, f"its chunks hold {prices}")


@case("fields", sdks=("openai", "anthropic"))
def fields_on_a_streams_final_object(t):
    client = t.client()
    if t.sdk == "openai":
        with client.chat.completions.stream(model="frontier-x", messages=harness.MESSAGES) as stream:
            final = stream.get_final_completion()
    else:
        with client.messages.stream(model="frontier-y", max_tokens=8, messages=harness.MESSAGES) as stream:
            final = stream.get_final_message()
    ours = harness.fields(t.sdk, final)
    t.check(ours, f"the final object carries none: {type(final).__name__}")


@case("fields", sdks=RAW_SDKS)
def fields_leave_a_responses_bytes_untouched(t):
    """The client's raw view is the wire's: the SDK edits no byte."""
    client = t.client()
    raw = client.chat.completions.with_raw_response.create(model=harness.MODEL[t.sdk], messages=harness.MESSAGES) if t.sdk != "anthropic" else \
        client.messages.with_raw_response.create(model=harness.MODEL[t.sdk], max_tokens=8, messages=harness.MESSAGES)
    path = t.reflexer.seen[0].path
    sent = json.dumps(standins.as_served(path, standins.body_for(path, SERVED_TEXT))).encode()
    got = raw.http_response.content
    t.check(got == sent, f"the bytes changed: {got[:120]!r}")
    t.check(raw.headers.get("reflexer-cost-nano-usd") == standins.SERVED_COST, "our header is not in the raw view")


@case("fields", sdks=("openai", "azure"))
def fields_an_object_with_no_room_keeps_its_answer(t):
    client = t.client()
    made = client.post("/chat/completions", body={"model": harness.MODEL[t.sdk], "messages": harness.MESSAGES}, cast_to=typing.Dict[str, object])  # a bare `dict` raises in openai 3.0, `dict[...]` on Python 3.10
    t.check(made.get("model") == "frontier-x-reflexer", f"got {made}")


# ---- gzip: the SDKs ask `gzip, deflate, zstd`

@case("gzip")
def gzip_a_served_answer_with_its_fields(t):
    client = t.client()
    t.reflexer.set("ok", gzip=True)
    outcome = t.ask(client)
    t.served(outcome)
    t.note(f"gzipped on reflexer's leg: {t.reflexer.seen[0].gzipped}")
    t.check(harness.fields(t.sdk, outcome.answer) == EXPECTED_FIELDS, f"it says {harness.fields(t.sdk, outcome.answer)}")


@case("gzip")
def gzip_a_pass_through(t):
    client = t.client()
    t.reflexer.set("passed", gzip=True)
    outcome = t.ask(client)
    t.check(outcome.error is None and outcome.text == STRAIGHT_TEXT, f"{outcome}")
    ours = harness.fields(t.sdk, outcome.answer)
    t.check(not ours or ours["answered_by"] == "provider", f"a pass through says it was served: {ours}")
    t.check(not t.provider.seen, f"sent to the provider too: {t.provider.seen}")


@case("gzip")
def gzip_a_straight_answer(t):
    client = t.client()
    t.provider.set("ok", gzip=True)
    t.straight(t.skip(client))


# ---- an answer cut or broken after reflexer took the call: an error as from the provider, never sent twice

@case("no harm")
def no_harm_an_answer_cut_is_an_error_never_sent_twice(t):
    client = t.client()
    t.reflexer.set("cut")
    outcome = t.ask(client)
    t.check(outcome.error is not None, f"{outcome}")
    t.check(not t.provider.seen, f"billed twice: sent to the provider too: {t.provider.seen}")


@case("no harm")
def no_harm_an_answer_broken_is_an_error_never_sent_twice(t):
    client = t.client()
    t.reflexer.set("ok", headers={"content-encoding": "gzip"}, body=b"not gzip")
    outcome = t.ask(client)
    t.check(outcome.error is not None, f"{outcome}")
    t.check(not t.provider.seen, f"billed twice: sent to the provider too: {t.provider.seen}")


@case("routing", sdks=("openai",))
def routing_a_clients_own_reflexer_headers_never_steer_or_leave(t):
    """A client's header of our names: its upstream steers nothing, and on a straight call none reaches the provider."""
    ours = {"Reflexer-Upstream": "https://elsewhere.example", "Reflexer-Namespace": "made-up", "Reflexer-Made-Up": "made-up"}
    client = t.client(default_headers=ours)
    t.served(t.ask(client))
    seen = t.reflexer.seen[0].headers
    t.check("reflexer-upstream" not in seen, f"the client's upstream reached reflexer: {seen.get('reflexer-upstream')}")
    t.check(seen.get("reflexer-namespace") == "made-up", "the namespace, which is the client's to set, did not reach reflexer")
    t.skip(client)
    left = [name for name in t.provider.seen[0].headers if name.lower().startswith("reflexer-")]
    t.check(not left, f"reached the provider: {left}")


@case("fields", sdks=("gemini",))
def fields_leave_geminis_object_what_it_was(t):
    """Our fields change nothing else about its object: its class, equality, pickling, a round trip of its dump."""
    answer = t.ask(t.client()).answer
    kind = type(answer)
    t.check(kind.__name__ == "GenerateContentResponse" and kind.__module__ == "google.genai.types", f"its class is {kind}")
    t.check(pickle.loads(pickle.dumps(answer)).text == answer.text, "it does not pickle")
    t.check(kind.model_validate(answer.model_dump(exclude={"sdk_http_response"})).text == answer.text, "its dump does not read back")


@case("kept", sdks=("gemini",))
def kept_geminis_own_options_as_stock_takes_them(t):
    """`client_args` as stock takes them, and `with` closing what it opened."""
    client = t.client(gemini_options={"client_args": {"follow_redirects": False}, "async_client_args": {"ssl": False}})
    t.served(t.ask(client))
    with t.client() as closing:
        t.ask(closing)
    t.check(closing._api_client._httpx_client.is_closed, "`with` left its HTTP client open")


@case("no harm", sdks=("openai",))
def no_harm_a_body_not_read_goes_straight_and_counts_no_failure(t):
    """A raw upload's generator could not be sent twice: straight, and the next call still tries reflexer."""
    def first(client):
        client.post("/chat/completions", content=(part for part in [b"{}"]), cast_to=object)
        t.check(not t.reflexer.seen, f"reflexer got it: {t.reflexer.seen}")
    next_call_tries_reflexer(t, first)


# ---- stream



@case("stream")
def stream_served_through_reflexer(t):
    outcome = t.stream(t.client())
    t.served(outcome)
    t.check(not t.provider.seen, f"the provider too: {t.provider.seen}")


@case("stream")
def stream_arrives_event_by_event(t):
    """Reflexer sends the rest of the stream only once the SDK has handed up its first event: an SDK that waits for more
    than an event holds it back, and whatever the machine's pace, nothing is judged by time."""
    client = t.client()
    handed = threading.Event()
    t.reflexer.set("ok", handshake=handed)
    outcome = t.stream(client, handed=handed)
    t.served(outcome)
    held = t.reflexer.seen[0].handed_first
    t.check(held, f"the first event was not handed up before the rest was sent: it arrived in one piece ({held})")


@case("stream")
def stream_reflexer_busy_goes_straight(t):
    client = t.client()
    reflexer_status(t, overloaded(t.sdk))
    t.straight(t.stream(client))


@case("stream")
def stream_reflexer_dead_goes_straight(t):
    client = t.client()
    t.reflexer.set("dead")
    t.straight(t.stream(client))


@case("stream")
def stream_skip_goes_straight(t):
    client = t.client()
    t.straight(t.stream(client, headers=t.skip_headers()))
    t.check(not t.to_reflexer(), f"reflexer got it: {t.to_reflexer()}")


# ---- async: async clients; gemini's is `client.aio`

@case("async")
def async_served_with_fields(t):
    async def body():
        outcome = await t.ask_async(t.client(is_async=True))
        t.served(outcome)
        t.check(harness.fields(t.sdk, outcome.answer) == EXPECTED_FIELDS, f"it says {harness.fields(t.sdk, outcome.answer)}")
    t.run_async(body)


@case("async")
def async_reflexer_busy_goes_straight(t):
    async def body():
        client = t.client(is_async=True)
        reflexer_status(t, overloaded(t.sdk))
        t.straight(await t.ask_async(client))
        t.check(t.reflexer.seen, "reflexer was never tried")
    t.run_async(body)


@case("async")
def async_reflexer_dead_goes_straight(t):
    async def body():
        client = t.client(is_async=True)
        t.reflexer.set("reset")
        t.straight(await t.ask_async(client))
        t.check(t.reflexer.seen, "reflexer was never tried")
    t.run_async(body)


@case("async")
def async_skip_goes_straight(t):
    async def body():
        client = t.client(is_async=True)
        t.straight(await t.skip_async(client))
        t.check(not t.to_reflexer(), f"reflexer got it: {t.to_reflexer()}")
    t.run_async(body)


@case("async", steady=True)
def async_the_clients_timeout_holds_on_reflexers_leg(t):
    async def body():
        client = t.client(is_async=True)
        t.reflexer.set("stall")
        t.straight(await t.ask_async(client, timeout=CLIENT_TIMEOUT))
        t.check(t.reflexer.seen, "reflexer was never tried")
        arrival, noticed_by = t.reflexer.seen[0], time.monotonic() + MARGIN
        while arrival.left_after is None and time.monotonic() < noticed_by:  # in its loop: a leg its client left open stays open
            await asyncio.sleep(0.01)
        reflexers_leg_held_no_longer_than_the_timeout(t)
    t.run_async(body)


@case("async")
def async_stream_served(t):
    async def body():
        t.served(await t.stream_async(t.client(is_async=True)))
    t.run_async(body)


@case("async")
def async_redirect_goes_straight(t):
    async def body():
        client = t.client(is_async=True)
        t.reflexer.set("redirect")
        t.straight(await t.ask_async(client))
        t.check(t.reflexer.seen, "reflexer was never tried")
        t.check(not t.elsewhere.seen, f"the redirect was followed: {t.elsewhere.seen}")
    t.run_async(body)


# ---- kept: proxies and HTTP settings; hooks once, never the key; `with_options`; `isinstance`; a cost tool sees one call

@case("kept")
def kept_isinstance(t):
    client = t.client()
    cls = harness.stock_class(t.sdk)
    t.check(isinstance(client, cls), f"{type(client).__name__} is not a {cls.__name__}")


def provider_error_class(sdk):
    if sdk in ("openai", "azure"):
        import openai
        return openai.RateLimitError
    if sdk == "anthropic":
        import anthropic
        return anthropic.RateLimitError
    from google.genai import errors
    return errors.ClientError


@case("kept")
def kept_a_providers_error_raises_the_sdks_own_class(t):
    client = t.client()
    wanted = provider_error_class(t.sdk)
    t.reflexer.set("reply", status=429, headers=standins.PROVIDERS_THROUGH_US | {"Retry-After": "0"}, body=provider_error(t.sdk))
    relayed = t.ask(client)
    t.check(isinstance(relayed.error, wanted), f"through reflexer: {relayed}")
    t.reflexer.set("ok")
    t.provider.set("reply", status=429, headers={"Retry-After": "0"}, body=provider_error(t.sdk))
    straight = t.skip(client)
    t.check(isinstance(straight.error, wanted), f"straight: {straight}")


@case("kept", na={"gemini": NO_RAW}, sdks=RAW_SDKS)
def kept_with_options_stays_on_reflexer(t):
    client = t.client()
    copied = client.with_options(timeout=5.0)
    outcome = t.ask(copied)
    t.served(outcome)
    t.check(harness.fields(t.sdk, outcome.answer) == EXPECTED_FIELDS, f"it says {harness.fields(t.sdk, outcome.answer)}")
    t.served(t.ask(client))


@case("kept", na={"gemini": NO_RAW}, sdks=RAW_SDKS, steady=True)
def kept_with_options_timeout_holds(t):
    client = t.client()
    t.reflexer.set("stall")
    t.straight(t.ask(client.with_options(timeout=CLIENT_TIMEOUT)))
    t.check(t.last.wall <= CLIENT_TIMEOUT + MARGIN, f"waited {t.last.wall:.2f}s")


@case("kept", na={"gemini": NO_RAW}, sdks=RAW_SDKS)
def kept_with_raw_response(t):
    client = t.client()
    raw = client.chat.completions.with_raw_response.create(model=harness.MODEL[t.sdk], messages=harness.MESSAGES) if t.sdk != "anthropic" else \
        client.messages.with_raw_response.create(model=harness.MODEL[t.sdk], max_tokens=8, messages=harness.MESSAGES)
    made = raw.parse()
    t.check(harness.text_of(t.sdk, made) == SERVED_TEXT, f"parsed {made}")
    t.check(harness.fields(t.sdk, made) == EXPECTED_FIELDS, f"parsed object carries {harness.fields(t.sdk, made)}")


@case("kept")
def kept_the_clients_http_settings_on_both_legs(t):
    client = t.client(http={"headers": {"x-mine": "kept"}})
    t.served(t.ask(client))
    t.check(t.reflexer.seen[0].headers.get("x-mine") == "kept", "the client's header did not reach reflexer")
    reflexer_status(t, overloaded(t.sdk))
    t.straight(t.ask(client))
    t.check(t.provider.seen[0].headers.get("x-mine") == "kept", "the client's header did not reach the provider")


def hooked(t, seen, hook=None):
    def on_request(request):
        seen.append(dict(request.headers))

    def on_response(response):
        seen.append(dict(response.request.headers))
        if hook:
            hook(response)

    return t.client(http={"event_hooks": {"request": [on_request], "response": [on_response]}})


@case("kept")
def kept_hooks_run_once_and_never_see_the_key_on_a_served_call(t):
    seen = []
    t.served(t.ask(hooked(t, seen)))
    t.check(len(seen) == 2, f"the hooks ran {len(seen)} times, expected request and response once each")
    t.check(not [h for h in seen if "reflexer-key" in h], "a hook saw the reflexer key")


@case("kept")
def kept_hooks_run_once_and_never_see_the_key_on_a_fallback(t):
    seen = []
    client = hooked(t, seen)
    reflexer_status(t, overloaded(t.sdk))
    t.straight(t.ask(client))
    t.check(len(seen) == 2, f"the hooks ran {len(seen)} times, expected request and response once each")
    t.check(not [h for h in seen if "reflexer-key" in h], "a hook saw the reflexer key")


@case("kept")
def kept_a_raising_hook_is_the_clients_own(t):
    seen = []
    client = hooked(t, seen, hook=lambda response: response.raise_for_status())
    t.reflexer.set("reply", status=429, headers=standins.PROVIDERS_THROUGH_US, body=provider_error(t.sdk))
    t.ask(client)
    t.check(t.last.error is not None, f"{t.last}")
    t.check(seen, "the client's hook never ran")
    t.ask(client)
    t.check(not t.provider.seen, f"a client's raising hook sent the call straight: {t.provider.seen}")
    t.check(len(t.to_reflexer()) == 2, f"the breaker opened on a client's hook: reflexer saw {len(t.to_reflexer())}")


def own_auth(sdk):
    if sdk in ("openai", "azure", "anthropic"):
        import httpx2 as library
    else:
        import httpx as library

    class Mine(library.Auth):
        def auth_flow(self, request):
            request.headers["x-mine-auth"] = "kept"
            yield request

    return Mine()


@case("kept")
def kept_the_clients_auth_on_both_legs(t):
    client = t.client(http={"auth": own_auth(t.sdk)})
    t.served(t.ask(client))
    t.check(t.reflexer.seen[0].headers.get("x-mine-auth") == "kept", "the client's Auth did not reach reflexer")
    reflexer_status(t, overloaded(t.sdk))
    t.straight(t.ask(client))
    t.check(t.provider.seen[0].headers.get("x-mine-auth") == "kept", "the client's Auth did not reach the provider")


@case("kept")
def kept_proxy_http_proxy_set_no_proxy_not(t):
    """`HTTP_PROXY` set, `NO_PROXY` not: where each leg goes. https legs stay off it, as stock."""
    t.env(HTTP_PROXY=t.proxy.url)
    client = t.client()
    outcome = t.ask(client)
    t.note(f"through the proxy: tunnels {t.proxy.tunnels}, plain {t.proxy.plain}")
    t.served(outcome)
    reflexer_status(t, overloaded(t.sdk))
    t.straight(t.ask(client))
    t.note(f"then, with a fallback: tunnels {t.proxy.tunnels}, plain {t.proxy.plain}")


@case("kept", sdks=MESSAGE_SDKS)
def kept_proxy_http_proxy_takes_a_plain_http_runner(t):
    t.env(HTTP_PROXY=t.proxy.url)
    suffix = "/v1" if t.sdk == "openai" else ""
    outcome = t.ask(t.client(base_url=f"http://runner.example{suffix}"))
    t.check(t.proxy.plain, f"it did not go through the client's proxy: {outcome}")
    t.check(outcome.error is None, f"{outcome}")
    t.note(f"through the proxy: {t.proxy.plain[0]}")


@case("kept")
def kept_proxy_https_proxy_takes_each_leg(t):
    t.env(HTTPS_PROXY=t.proxy.url)
    client = t.client()
    t.served(t.ask(client))
    t.check("api.reflexer.ai" in t.proxy.tunnels, f"reflexer's leg went round the proxy: {t.proxy.tunnels}")
    reflexer_status(t, overloaded(t.sdk))
    t.straight(t.ask(client))
    t.check(t.provider.seen[0].host in t.proxy.tunnels, f"the straight leg went round the proxy: {t.proxy.tunnels}")
    t.note(f"tunnels {t.proxy.tunnels}")


@case("kept")
def kept_proxy_the_clients_explicit_proxy_takes_each_leg(t):
    client = t.client(http={"proxy": t.proxy.url})
    t.served(t.ask(client))
    t.check("api.reflexer.ai" in t.proxy.tunnels, f"reflexer's leg went round the proxy: {t.proxy.tunnels}")
    reflexer_status(t, overloaded(t.sdk))
    t.straight(t.ask(client))
    t.check(t.provider.seen[0].host in t.proxy.tunnels, f"the straight leg went round the proxy: {t.proxy.tunnels}")


COST_TOOL_TARGET = {"openai": ("openai.resources.chat.completions", "Completions", "create"),
                    "azure": ("openai.resources.chat.completions", "Completions", "create"),
                    "anthropic": ("anthropic.resources.messages", "Messages", "create"),
                    "gemini": ("google.genai.models", "Models", "generate_content")}


def patched_cost_tool(t):
    """As a cost tool does: wrapping the SDK's own public method on its class, reading the object it returns."""
    import importlib
    module, cls, method = COST_TOOL_TARGET[t.sdk]
    owner = getattr(importlib.import_module(module), cls)
    original = getattr(owner, method)
    read = []

    def tool(self, *args, **kwargs):
        made = original(self, *args, **kwargs)
        read.append(harness.usage_cost(t.sdk, made))
        return made

    setattr(owner, method, tool)
    return read


@case("kept")
def kept_a_cost_tool_patching_the_sdk_sees_one_call_and_our_cost(t):
    read = patched_cost_tool(t)
    t.served(t.ask(t.client()))
    t.check(len(read) == 1 and (read[0] == EXPECTED_COST or t.sdk == "gemini"), f"the tool read {read}, expected once {EXPECTED_COST}")


@case("kept")
def kept_a_cost_tool_patching_after_the_client_was_made_sees_it_too(t):
    client = t.client()
    read = patched_cost_tool(t)
    t.served(t.ask(client))
    t.check(len(read) == 1 and (read[0] == EXPECTED_COST or t.sdk == "gemini"), f"the tool read {read}, expected once {EXPECTED_COST}")


@case("kept")
def kept_a_cost_tool_sees_one_call_on_a_fallback(t):
    read = patched_cost_tool(t)
    client = t.client()
    reflexer_status(t, overloaded(t.sdk))
    t.straight(t.ask(client))
    t.check(len(read) == 1, f"the tool saw {len(read)} calls for one of the client's")


@case("kept", sdks=("openai", "anthropic", "azure"))
def kept_the_sdks_own_retries(t):
    """A provider's status relayed: the SDK retries it as its own, reflexer seeing each try."""
    client = t.client(retries=1)
    t.reflexer.set("reply", status=429, headers=standins.PROVIDERS_THROUGH_US | {"Retry-After": "0"}, body=provider_error(t.sdk))
    t.ask(client)
    t.check(len(t.to_reflexer()) == 2, f"reflexer saw {len(t.to_reflexer())} tries, expected the first and one retry")
    t.check(not t.provider.seen, f"it went straight: {t.provider.seen}")


@case("kept", sdks=("openai", "anthropic"))
def kept_the_key_stays_out_of_what_the_client_can_log(t):
    logging.getLogger().setLevel(logging.DEBUG)
    client = t.client()
    create = client.chat.completions if t.sdk == "openai" else client.messages
    more = {"max_tokens": 8} if t.sdk == "anthropic" else {}
    t.reflexer.set("passed")
    raw = create.with_raw_response.create(model=harness.MODEL[t.sdk], messages=harness.MESSAGES, **more)
    t.check("reflexer-key" not in raw.http_request.headers, "the key is on the raw view's request")
    status, body = key_error(t.sdk)
    t.reflexer.set("reply", status=status, headers={"Reflexer-Status-Origin": "reflexer"}, body=body)
    outcome = t.ask(client)
    t.check(outcome.error is not None, f"{outcome}")
    t.check("reflexer-key" not in outcome.error.request.headers, "the key is on the error's request")
    leaked = [line for line in t.logs.records if t.world.key in line]
    t.check(not leaked, f"the key is in the logs: {leaked[0][:100] if leaked else ''}")


@case("kept", sdks=("openai",))
def kept_a_shared_http_client_stays_the_clients(t):
    shared = harness.own_http_client("openai", False, {})
    mine = harness.config_for("openai") | {"http_client": shared}
    t.lines.client(t.world, "openai", False, **mine)
    t.ask(harness.stock_class("openai")(**mine))
    t.check(not t.to_reflexer(), f"a stock client on the shared HTTP client reached reflexer: {t.to_reflexer()}")
    t.check(len(t.provider.seen) == 1, f"provider saw {t.provider.seen}")


@case("kept", sdks=("openai",))
def kept_a_legacy_httpx_client(t):
    import httpx
    made = t.lines.client(t.world, "openai", False, **(harness.config_for("openai") | {"http_client": httpx.Client()}))
    t.served(t.ask(made))
    t.check(harness.fields("openai", t.last.answer) == EXPECTED_FIELDS, "no fields")


@case("kept", sdks=("openai",))
def kept_reflexers_cookie_never_reaches_the_provider(t):
    client = t.client()
    t.reflexer.set("ok", headers={"set-cookie": "made-up=1"})
    t.served(t.ask(client))
    t.skip(client)
    t.check(t.provider.seen and "cookie" not in t.provider.seen[0].headers, f"reflexer's cookie reached the provider: {t.provider.seen[0].headers}")


@case("kept", sdks=("openai",))
def kept_a_body_not_read_goes_straight(t):
    """Raw `client.post(content=generator)`: a body that could not be sent twice goes straight."""
    client = t.client()
    client.post("/chat/completions", content=(part for part in [b"{}"]), cast_to=object)
    t.check(not t.to_reflexer(), f"reflexer got it: {t.to_reflexer()}")
    t.check(t.provider.seen, "the provider got nothing")


@case("kept", sdks=("gemini",))
def kept_the_clients_own_transport_stays_open(t):
    import gc, httpx
    closed = []

    class Tracked(httpx.HTTPTransport):
        def close(self):
            closed.append(True)
            super().close()

    client = t.client(gemini_options={"client_args": {"transport": Tracked()}})
    gc.collect()
    t.check(not closed, "the transport was closed under the client")
    t.served(t.ask(client))


@case("kept", sdks=("openai",))
def kept_a_clients_attribute_named_like_ours_skips_nothing(t):
    http = harness.own_http_client("openai", False, {})
    http.wrapped = http.reflexer = "the client's own"
    client = t.lines.client(t.world, "openai", False, **(harness.config_for("openai") | {"http_client": http}))
    t.served(t.ask(client))


# ---- measures: recorded, not judged

TIMED_CALLS = 40


@case("measure")
def measure_time_added_on_loopback(t):
    """Median seconds per served call against the same stand-in as stock on the provider's name."""
    stock = t.stock()
    stock_walls = [t.ask(stock).wall for _ in range(TIMED_CALLS)]
    t.check(t.last.error is None, f"stock failed: {t.last}")
    client = t.client()
    here_walls = [t.ask(client).wall for _ in range(TIMED_CALLS)]
    t.check(t.last.error is None, f"{t.last}")
    median_stock, median_here = statistics.median(stock_walls), statistics.median(here_walls)
    t.data |= {"stock_median_ms": round(median_stock * 1000, 2), "here_median_ms": round(median_here * 1000, 2), "calls": TIMED_CALLS}
    t.note(f"median of {TIMED_CALLS} calls: stock {median_stock * 1000:.1f} ms, here {median_here * 1000:.1f} ms")
    t.last = None


# ---- a new provider: a made-up SDK (`harness/acme.py`), through reflexer by its wire's data alone (`lines.py`)

ACME = ("acme",)


@case("new provider", sdks=ACME)
def new_provider_a_message_call_reaches_reflexer_with_its_fields(t):
    t.served(t.ask(t.client()))
    arrival = t.reflexer.seen[0]
    t.check(arrival.path == "/acme/v2/ask", arrival.path)
    t.check(arrival.headers.get("reflexer-key") == t.world.key, "no Reflexer-Key on it")
    t.check(arrival.headers.get("x-acme-key") == harness.PROVIDER_KEY["acme"], "the provider's key is not on it")
    t.check(harness.fields("acme", t.last.answer) == EXPECTED_FIELDS, f"it says {harness.fields('acme', t.last.answer)}")


@case("new provider", sdks=ACME)
def new_provider_busy_goes_straight(t):
    client = t.client()
    reflexer_status(t, 503)
    t.straight(t.ask(client))


@case("new provider", sdks=ACME)
def new_provider_skip_goes_straight(t):
    t.straight(t.skip(t.client()))
    t.check(not t.to_reflexer(), f"reflexer got it: {t.to_reflexer()}")


# ---- measures, again

@case("measure", sdks=WITH_AZURE)
def measure_what_each_4xx_of_reflexers_does(t):
    """Recorded, not judged: which 4xx of reflexer's, with no `Reflexer-Straight`, reach the client as errors."""
    client = t.client()
    what = []
    for status in (400, 403, 404, 413):
        reflexer_status(t, status)
        outcome = t.ask(client)
        what.append(f"{status} {'raised' if outcome.error is not None else 'answered'}")
    t.note(", ".join(what))
    t.last = None


import cases_bedrock  # noqa: E402,F401 Amazon Bedrock's cases, registered beside these
