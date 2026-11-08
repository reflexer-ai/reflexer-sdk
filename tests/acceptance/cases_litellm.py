"""LiteLLM's cases, on each provider whose wire reflexer takes (`harness/litellm.py`; Bedrock's through LiteLLM:
`cases_bedrock.py`, `litellm`): reflexer's one line for the process, `reflexer.litellm.through(key)`, takes each call,
sync and async, streamed or not, and falls back as every line does. Registered beside `cases.py`'s, by its import."""
import asyncio

from cases import case, overloaded, reflexer_status
from harness import PASS_THROUGH, litellm

ALL = litellm.COLUMNS
WAYS = ((False, False), (True, False), (False, True), (True, True))  # (async, streamed)


@case("litellm", sdks=ALL)
def litellm_a_call_reaches_reflexer_with_both_keys(t):
    t.lines.litellm_line(t.world)
    t.served(litellm.ask(t))
    arrival = t.to_reflexer()[-1]
    t.check(arrival.headers.get("reflexer-key") == t.world.key, "reflexer's key missing")
    t.check(litellm.CALLS[t.sdk]["api_key"] in arrival.headers.get(litellm.KEY_HEADER[t.sdk], ""), "the provider's key missing")
    t.check(arrival.headers.get("reflexer-upstream") == litellm.UPSTREAM.get(t.sdk), f"upstream: {arrival.headers.get('reflexer-upstream')}")


@case("litellm", sdks=ALL)
def litellm_each_way_is_served_async_and_streamed(t):
    t.lines.litellm_line(t.world)
    for is_async, stream in WAYS:
        t.served(litellm.ask(t, is_async, stream))
    t.check(len(t.to_reflexer()) == len(WAYS), f"reflexer saw {len(t.to_reflexer())} of {len(WAYS)} calls")


@case("litellm", sdks=ALL)
def litellm_reflexer_busy_goes_straight(t):
    reflexer_status(t, overloaded(t.sdk.removeprefix("litellm-")))
    for is_async, stream in WAYS:
        t.lines.litellm_line(t.world)  # anew: a breaker closed, so each call tries reflexer
        t.straight(litellm.ask(t, is_async, stream))
    t.check(len(t.to_reflexer()) == len(WAYS), f"reflexer saw {len(t.to_reflexer())} of {len(WAYS)} calls")


@case("litellm", sdks=ALL)
def litellm_reflexer_dead_goes_straight(t):
    t.reflexer.set("dead")
    for is_async, stream in WAYS:
        t.lines.litellm_line(t.world)
        t.straight(litellm.ask(t, is_async, stream))


@case("litellm", sdks=ALL)
def litellm_skip_goes_straight_and_its_flag_stays_here(t):
    t.lines.litellm_line(t.world)
    for is_async in (False, True):
        t.straight(litellm.ask(t, is_async, headers=t.skip_headers()))
    t.check(not t.to_reflexer(), f"reflexer got a skipped call: {t.to_reflexer()}")
    t.check(not any(PASS_THROUGH.lower() in arrival.headers for arrival in t.provider.seen), "the flag reached the provider")


@case("litellm", sdks=ALL)
def litellm_the_key_stays_out_of_what_the_client_can_log(t):
    """A callback of the client's own gets every call's `kwargs`, its standard logging payload among them: no key."""
    import json, litellm as library
    from litellm.integrations.custom_logger import CustomLogger
    heard = []

    class Logger(CustomLogger):
        def log_success_event(self, kwargs, response_obj, start_time, end_time):
            heard.append(repr(kwargs) + json.dumps(kwargs.get("standard_logging_object"), default=str))

        async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
            self.log_success_event(kwargs, response_obj, start_time, end_time)

    async def settle():  # LiteLLM logs once the call returned
        for _ in range(500):
            if len(heard) > before:
                return
            await asyncio.sleep(0.01)
    library.callbacks.append(Logger())
    t.lines.litellm_line(t.world)
    for is_async, stream in WAYS:
        before = len(heard)
        t.served(litellm.ask(t, is_async, stream, settle=settle))
    t.check(len(heard) >= len(WAYS), f"the callback heard {len(heard)} of {len(WAYS)} calls")
    t.check(not any(t.world.key in each for each in heard), "a callback of the client's saw the reflexer key")
