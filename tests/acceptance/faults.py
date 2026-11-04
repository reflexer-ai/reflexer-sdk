"""Faults planted in the SDK one at a time, each breaking one thing it promises, so that each case is seen to fail when
what it checks breaks (`test_controls.py`). `run.py --fault NAME` plants one in every case's own forked process, where
it dies with the case. A fault changes the SDK (`reflexer`) or the client's line (`lines.py`), never a case."""
import builtins, copy, json, time, types

import httpx, httpx2
from google.genai import types as genai_types

import reflexer, reflexer.gemini, reflexer.transport as transport
import harness, lines
from harness import standins

real_to_reflexer, real_route, real_read, real_note = transport.to_reflexer, reflexer.Reflexer.route, reflexer.read, reflexer.Breaker.note
real_client, real_without_its_cookie = lines.client, transport.without_its_cookie
REFLEXER_HOST = harness.REFLEXER_NAMES[0]


# Where a fault lands

def on_the_request_to_reflexer(change):
    """The request to reflexer, changed after the SDK made it."""
    def made(reflexer_, request):
        ours = real_to_reflexer(reflexer_, request)
        return ours if ours is None else change(ours)
    transport.to_reflexer = made


def on_reflexers_answer(change):
    """Reflexer's answer, changed where the SDK takes it, before the client's HTTP client reads it."""
    transport.without_its_cookie = lambda answer: change(real_without_its_cookie(answer))


def on_every_answer(change, leg):
    """Each answer the SDK hands up whose request `leg` picks, read whole when JSON, then changed."""
    real, real_async = transport.Through.handle_request, transport.Through.handle_async_request

    def picked(answer):
        return leg(answer) and "json" in answer.headers.get("content-type", "")

    def handle(self, request):
        answer = real(self, request)
        if picked(answer):
            answer.read()
            return change(answer)
        return answer

    async def handle_async(self, request):
        answer = await real_async(self, request)
        if picked(answer):
            await answer.aread()
            return change(answer)
        return answer

    transport.Through.handle_request, transport.Through.handle_async_request = handle, handle_async


def from_reflexer(answer):
    return answer.request.url.host == REFLEXER_HOST


def rebuilt(answer, content, drop=()):
    """A read answer with another body, as a response of the same HTTP library."""
    headers = {name: value for name, value in answer.headers.items()
               if name not in ("content-length", "content-encoding", *drop)}
    return type(answer)(answer.status_code, headers=headers, content=content, request=answer.request)


def edited_json(edit, drop=(), more=None):
    def change(answer):
        changed = rebuilt(answer, json.dumps(edit(answer.json(), answer)).encode(), drop)
        changed.headers.update(more or {})
        return changed
    return change


def on_the_line(around):
    """The client's line: `around(real, world, sdk, is_async, config)` makes the client in its place."""
    lines.client = lambda world, sdk, is_async=False, **config: around(real_client, world, sdk, is_async, config)


# What each fault changes

def key_on_the_clients_own_request(reflexer_, request):
    request.headers["reflexer-key"] = reflexer_.key
    return real_to_reflexer(reflexer_, request)


def hop_losing_its_mark(reflexer_, request):
    request.extensions.pop(transport.STRAIGHT, None)
    return real_to_reflexer(reflexer_, request)


def skip_sticks(self, url, headers, replay=False):
    if reflexer.PASS_THROUGH in headers:
        self.sample = 0.0
    return real_route(self, url, headers, replay)


def route_without(*names):
    def route(self, url, headers, replay=False):
        made = real_route(self, url, headers, replay)
        return made and (made[0], {name: value for name, value in made[1].items() if name not in names})
    return route


def route_keeping_the_clients_headers(self, url, headers, replay=False):
    made = real_route(self, url, headers, replay)
    return made and (made[0], {name: value for name, value in headers.items() if name != "host"} | made[1])


def calls_also(pattern):
    real = reflexer.Reflexer.__init__

    def init(self, *args, **kwargs):
        real(self, *args, **kwargs)
        self.calls = pattern(self.calls)
    return init


def read_meaning(replaced):
    def read(status, origin, straight_for):
        return replaced(status, origin, straight_for) or real_read(status, origin, straight_for)
    return read


def note_counting_each(self, meaning, straight_for):
    self.open_until = 0.0
    real_note(self, meaning, straight_for)


def note_never_resetting(self, meaning, straight_for):
    kept = self.backoff
    real_note(self, meaning, straight_for)
    self.backoff = max(kept, self.backoff)


def halved(ours):
    ours.extensions["timeout"] = {name: value and value / 2 for name, value in ours.extensions["timeout"].items()}
    return ours


def without_extensions(ours):
    ours.extensions = {}
    return ours


def body_changed(ours):
    headers = {name: value for name, value in ours.headers.items() if name != "content-length"}
    return type(ours)(ours.method, ours.url, headers=headers, content=ours.content + b" ", extensions=ours.extensions)


def body_read_first(reflexer_, request):
    request.read()
    return real_to_reflexer(reflexer_, request)


def a_body_not_read_counted_as_a_failure(reflexer_, request):
    if transport.body_of(request) is None:
        raise RuntimeError("a body not read yet")
    return real_to_reflexer(reflexer_, request)


def streams_go_straight(reflexer_, request):
    wants = b'"stream":true' in request.content.replace(b" ", b"") or "streamGenerate" in str(request.url)
    return None if wants else real_to_reflexer(reflexer_, request)


def read_whole(answer):
    answer.read()
    return answer


def bytes_edited(answer):
    answer.read()
    return rebuilt(answer, answer.content.replace(b'"id"', b'"_edited": 1, "id"', 1))


def refusing_gzip(answer):
    if answer.headers.get("content-encoding") == "gzip":
        raise ValueError("this reader takes no gzip")
    return answer


def without_the_price(body, answer):
    usage = body.get("usage")
    return body | {"usage": {name: value for name, value in usage.items() if name != "cost"}} if isinstance(usage, dict) else body


def priced(body, answer):
    if answer.headers.get("reflexer-answered-by") != "provider":
        return body
    usage = "usageMetadata" if "usageMetadata" in body else "usage"
    return body | {usage: body.get(usage, {}) | {"cost": 1.0}}


def dressed_as_served(body, answer):
    return standins.as_served(answer.request.url.path, body)


def keeping_its_hooks(client):
    """A copy whose hooks cannot be cleared: they run on reflexer's leg too."""
    made = copy.copy(client)
    made.__class__ = builtins.type(builtins.type(client).__name__, (builtins.type(client),),
                                   {"event_hooks": property(lambda self: self._event_hooks, lambda self, hooks: None)})
    return made


def copying_then_closing(client):
    made = copy.copy(client)
    client.close()
    return made


def type_taking_over(thing):
    """`type`, as the SDK reads it, except that the client's own HTTP client is routed too."""
    kind = builtins.type(thing)
    if not issubclass(kind, (httpx.Client, httpx2.Client)):
        return kind

    def made(**settings):
        outer = kind(**settings)
        thing._transport = outer._transport
        return outer
    return made


def one_library_only(thing):
    return httpx2.Request if isinstance(thing, (httpx.Request, httpx2.Request)) else builtins.type(thing)


def every_argument_taken(kind, given, arguments):
    return given or kind(**{"follow_redirects": True} | (arguments or {}))


class GeminiAnswer(genai_types.GenerateContentResponse):
    """A class of the SDK's own around gemini's answer."""


def gemini_answer_dressed(real, world, sdk, is_async, config):
    made = real(world, sdk, is_async, **config)
    if sdk == "gemini":
        generate = made.models.generate_content

        def dressed(**kwargs):
            answer = generate(**kwargs)
            answer.__class__ = GeminiAnswer
            return answer
        made.models.generate_content = dressed
    return made


class Delegate:
    """Not a client of the SDK's class: what isinstance sees."""

    def __init__(self, client):
        self.__dict__["client"] = client

    def __getattr__(self, name):
        return getattr(self.client, name)


def stock(real, world, sdk, is_async, config):
    return world.stock(sdk, is_async, **config)


def stock_pointed_at_reflexer(real, world, sdk, is_async, config):
    """A stock client with reflexer's address and key: no fallback."""
    ours = {"Reflexer-Key": world.key}
    if sdk == "gemini":
        options = dict(config.pop("http_options", {})) | {"base_url": "https://api.reflexer.ai/gemini/", "headers": ours}
        return world.stock(sdk, is_async, http_options=options, **config)
    if sdk == "azure":
        raise harness.Cannot("no such stock client")
    base = {"openai": "https://api.reflexer.ai/openai/v1", "anthropic": "https://api.reflexer.ai/anthropic", "acme": "https://api.reflexer.ai/acme"}[sdk]
    if sdk == "acme":
        return world.stock(sdk, is_async, **config | {"base_url": base})
    return world.stock(sdk, is_async, **config | {"base_url": base, "default_headers": ours})


def drops_the_clients_http_client(real, world, sdk, is_async, config):
    config.pop("http_client", None)
    config.get("http_options", {}).pop("httpx_client", None)
    return real(world, sdk, is_async, **config)


def share_ignored(real, world, sdk, is_async, config):
    world.share = 1.0
    return real(world, sdk, is_async, **config)


def sets_its_own_retries(real, world, sdk, is_async, config):
    return real(world, sdk, is_async, **config | {"max_retries": 3})


def not_the_sdks_class(real, world, sdk, is_async, config):
    return Delegate(real(world, sdk, is_async, **config))


def with_options_is_stock(real, world, sdk, is_async, config):
    made = real(world, sdk, is_async, **config)
    if hasattr(made, "with_options"):
        made.with_options = lambda **kwargs: harness.stock_class(sdk, is_async)(**config)
    return made


def calls_the_public_method_twice(real, world, sdk, is_async, config):
    made = real(world, sdk, is_async, **config)
    if sdk == "openai":
        create = made.chat.completions.create
        made.chat.completions.create = lambda **kwargs: (create(**kwargs), create(**kwargs))[1]
    return made


def errors_of_our_own(real, world, sdk, is_async, config):
    made = real(world, sdk, is_async, **config)
    if sdk == "openai":
        create = made.chat.completions.create

        def ours_or_raise(**kwargs):
            try:
                return create(**kwargs)
            except Exception as failure:
                raise RuntimeError("an error of the SDK's own") from failure
        made.chat.completions.create = ours_or_raise
    return made


def setter(owner, name, value):
    return lambda: setattr(owner, name, value)


FAULTS = {
    # where the key goes, what is routed
    "key_on_every_request": lambda: (setattr(transport, "to_reflexer", key_on_the_clients_own_request),
                                     setattr(transport, "OURS", "not-ours-")),  # and the straight leg strips none of it
    "flag_not_read": setter(reflexer, "PASS_THROUGH", "x-nothing"),
    "skip_sticks": setter(reflexer.Reflexer, "route", skip_sticks),
    "hop_loses_its_mark": setter(transport, "to_reflexer", hop_losing_its_mark),
    "routes_everything": setter(reflexer.Reflexer, "__init__", calls_also(lambda calls: "/v1/.*$|/v1beta/.*$|/openai/.*$")),
    "routes_chat_only": setter(reflexer.Reflexer, "__init__", calls_also(lambda calls: calls.replace("|responses", ""))),
    "key_not_checked": setter(reflexer, "check", lambda key: None),
    "reaches_this_machine": setter(reflexer, "reachable", lambda address: True),
    "no_upstream": setter(reflexer.Reflexer, "route", route_without("reflexer-upstream")),
    "provider_key_dropped": setter(reflexer.Reflexer, "route", route_without("authorization", "x-api-key", "x-goog-api-key", "x-acme-key", "api-key")),
    "clients_headers_steer": setter(reflexer.Reflexer, "route", route_keeping_the_clients_headers),
    "body_changed": lambda: on_the_request_to_reflexer(body_changed),
    "body_read_first": setter(transport, "to_reflexer", body_read_first),
    "body_not_read_counted": setter(transport, "to_reflexer", a_body_not_read_counted_as_a_failure),
    "streams_go_straight": setter(transport, "to_reflexer", streams_go_straight),
    "timeout_dropped": lambda: on_the_request_to_reflexer(without_extensions),
    "timeout_halved": lambda: on_the_request_to_reflexer(halved),
    # what reflexer's response means
    "trips_on_providers_status": setter(reflexer, "read", read_meaning(lambda s, o, f: reflexer.FAILED if o == "provider" and s >= 400 else None)),
    "connection_counted": setter(reflexer, "read", read_meaning(lambda s, o, f: reflexer.FAILED if o == "connection" else None)),
    "busy_with_straight_counted": setter(reflexer, "read", read_meaning(lambda s, o, f: reflexer.FAILED if s >= 500 and f else None)),
    "redirect_is_an_answer": setter(reflexer, "read", read_meaning(lambda s, o, f: reflexer.ANSWER if 300 <= s < 400 else None)),
    "balancer_is_an_answer": setter(reflexer, "read", read_meaning(lambda s, o, f: reflexer.ANSWER if o is None else None)),
    "busy_is_an_answer": setter(reflexer, "read", read_meaning(lambda s, o, f: reflexer.ANSWER if o == "reflexer" and (s == 429 or s >= 500) else None)),
    "no_grace": setter(reflexer, "read", read_meaning(lambda s, o, f: reflexer.ANSWER if o == "reflexer" and s < 500 and s != 429 and f else None)),
    "expired_goes_straight": setter(reflexer, "read", read_meaning(lambda s, o, f: reflexer.ASKED if o == "reflexer" and 400 <= s < 429 else None)),
    "no_grace_warning": setter(reflexer, "log", types.SimpleNamespace(warning=lambda *a: None)),
    # the breaker
    "no_backoff": setter(reflexer.Breaker, "open_for", lambda self, seconds: None),
    "no_doubling": setter(reflexer, "BACKOFF_CAP", reflexer.BACKOFF),
    "obeys_one": setter(reflexer, "OBEYED_AFTER", 1),
    "never_obeys": setter(reflexer, "OBEYED_AFTER", 10**9),
    "reads_any_straight": setter(reflexer, "whole", lambda value: 30 if value else None),
    "counts_each_in_flight": setter(reflexer.Breaker, "note", note_counting_each),
    "never_resets": setter(reflexer.Breaker, "note", note_never_resetting),
    # the answer
    "strips_the_price": lambda: on_every_answer(edited_json(without_the_price, drop=("reflexer-cost", "reflexer-answered-by")), from_reflexer),
    "straight_dressed_as_served": lambda: on_every_answer(edited_json(dressed_as_served, more=standins.OURS), lambda a: not from_reflexer(a)),
    "prices_a_pass_through": lambda: on_every_answer(edited_json(priced), from_reflexer),
    "reads_answers_whole": lambda: on_reflexers_answer(read_whole),
    "edits_bytes": lambda: on_reflexers_answer(bytes_edited),
    "takes_no_gzip": lambda: on_every_answer(refusing_gzip, lambda answer: True),
    "cookie_for_anyone": setter(transport, "without_its_cookie", lambda answer: answer),
    # the client's own HTTP client and settings
    "hooks_on_both_legs": setter(transport, "copy", types.SimpleNamespace(copy=keeping_its_hooks)),
    "closes_the_clients_own_http_client": setter(transport, "copy", types.SimpleNamespace(copy=copying_then_closing)),
    "routes_the_clients_own_http_client": setter(transport, "type", type_taking_over),
    "one_library_only": setter(transport, "type", one_library_only),
    "tells_ours_by_a_name_a_client_may_use": setter(transport, "hasattr", lambda thing, name: builtins.hasattr(thing, "reflexer")),
    "every_gemini_argument_taken": setter(reflexer.gemini, "own_client", every_argument_taken),
    # the client's line
    "stock": lambda: on_the_line(stock),
    "stock_pointed_at_reflexer": lambda: on_the_line(stock_pointed_at_reflexer),
    "drops_the_clients_http_client": lambda: on_the_line(drops_the_clients_http_client),
    "share_ignored": lambda: on_the_line(share_ignored),
    "sets_its_own_retries": lambda: on_the_line(sets_its_own_retries),
    "not_the_sdks_class": lambda: on_the_line(not_the_sdks_class),
    "with_options_is_stock": lambda: on_the_line(with_options_is_stock),
    "calls_the_public_method_twice": lambda: on_the_line(calls_the_public_method_twice),
    "errors_of_our_own": lambda: on_the_line(errors_of_our_own),
    "gemini_answer_dressed": lambda: on_the_line(gemini_answer_dressed),
}


# A slow machine's moments, planted in the stand-ins, never in the SDK or a case: `run.py --condition NAME`. The cases
# `test_controls.py` lists for each must stay green under it, so that a busy machine cannot turn them red.

def late_notice():
    """The stand-in's thread, slow to be scheduled: a stalled stand-in notices a client left some time after it did,
    within the slack a case allows a busy machine."""
    import cases
    real_select = standins.select.select

    def slow(readable, writable, broken, timeout):
        ready = real_select(readable, writable, broken, timeout)
        if ready[0]:
            time.sleep(cases.MARGIN / 2)
        return ready
    standins.select = types.SimpleNamespace(select=slow)


def a_stall_on_the_return():
    """The machine stalled past the client's timeout once, on reflexer's first answer after an outage: the call trying
    reflexer again pays its timeout and counts a failure, as on a machine frozen at that moment."""
    import cases
    real_answer, stalled = standins.Standin.answer, []

    def answer(self, handler, arrival):
        after_an_outage = any(seen.path is None for seen in self.seen)  # `reset` records its attempts with no path
        if self.is_reflexer and self.mode == "ok" and after_an_outage and not stalled:
            stalled.append(arrival)
            time.sleep(cases.CLIENT_TIMEOUT + cases.MARGIN)
        return real_answer(self, handler, arrival)
    standins.Standin.answer = answer


CONDITIONS = {"late_notice": late_notice, "a_stall_on_the_return": a_stall_on_the_return}
