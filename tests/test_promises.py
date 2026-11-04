"""The SDK's behaviour promises (SECURITY.md), each checked, and each check shown red under a planted fault.
Offline, on the HTTP library's mock transport; every value made up. Run: python -m unittest tests.test_promises"""
import os, sys, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import httpx2
import reflexer, reflexer.transport
from reflexer.transport import setup_http_client

SECRET = "rfx1_aaaaakq_" + "a" * 52
KEY = f"{SECRET}_{reflexer.checksum(SECRET)}"  # made up, of the form
WIRE = {"reflexer_path": "/openai", "provider": "https://api.openai.com", "calls": r"/v1/chat/completions$"}
CHAT = "https://api.openai.com/v1/chat/completions"
REFLEXER = "api.reflexer.ai"
REPLAY = b'{"model": "made-up", "replay_response": {"id": "made-up"}}'


def through(answer, **settings):
    """Our HTTP client over a client's own; what reached each host, with the headers it carried."""
    seen = []

    def handler(request):
        seen.append(request)
        return answer(request)

    own = httpx2.Client(transport=httpx2.MockTransport(handler), **settings)
    return setup_http_client(None, WIRE)(KEY, own=own), seen


def busy(request):
    if request.url.host == REFLEXER:
        return httpx2.Response(503, headers={"reflexer-status-origin": "reflexer"})
    return httpx2.Response(200, json={"from": "provider"})


def down(request):
    if request.url.host == REFLEXER:
        raise httpx2.ConnectError("made up")
    return httpx2.Response(200, json={"from": "provider"})


def redirected(request):
    if request.url.host == REFLEXER:
        return httpx2.Response(307, headers={"location": "https://elsewhere.example/v1", "reflexer-status-origin": "reflexer"})
    return httpx2.Response(200, json={"from": "provider"})


def hosts_given_the_key():
    """Every host that received the reflexer key, over a fallback, a redirect, and a client's own hook."""
    given, hooked = [], []
    for answer in (busy, down, redirected):
        client, seen = through(answer, follow_redirects=True, event_hooks={"request": [lambda r: hooked.append(dict(r.headers))]})
        client.post(CHAT, content=b"{}")
        given += [request.url.host for request in seen if "reflexer-key" in request.headers]
    given += ["a hook"] * sum("reflexer-key" in headers for headers in hooked)
    return sorted(set(given))


def a_replay_reached_the_provider():
    for answer in (busy, down):
        client, seen = through(answer)
        try:
            client.post(CHAT, content=REPLAY)
        except reflexer.ReplayNotTaken:
            pass
        if any(request.url.host != REFLEXER for request in seen):
            return True
    return False


def a_call_reflexer_could_not_take_reached_the_provider():
    for answer in (busy, down):
        client, _ = through(answer)
        try:
            if client.post(CHAT, content=b"{}").json() != {"from": "provider"}:
                return False
        except Exception:
            return False
    return True


def a_plain_http_address_for_reflexer_was_taken():
    try:
        reflexer.Reflexer(KEY, WIRE, base="http://api.reflexer.example")
        return True
    except ValueError:
        return False


class Promises(unittest.TestCase):
    def test_the_key_reaches_only_reflexer(self):
        self.assertEqual(hosts_given_the_key(), [REFLEXER])

    def test_a_replay_never_reaches_the_provider(self):
        self.assertFalse(a_replay_reached_the_provider())

    def test_a_call_reflexer_does_not_take_still_reaches_the_provider(self):
        self.assertTrue(a_call_reflexer_could_not_take_reached_the_provider())

    def test_reflexers_address_must_be_https(self):
        self.assertFalse(a_plain_http_address_for_reflexer_was_taken())


def key_on_the_clients_own_request(real):
    def broken(way, request):
        request.headers["reflexer-key"] = KEY
        return real(way, request)
    return broken


class Broken(unittest.TestCase):
    """Each check above, red with one fault planted in the SDK."""

    def test_the_key_on_the_clients_own_request_turns_it_red(self):
        with mock.patch.object(reflexer.transport, "to_reflexer", key_on_the_clients_own_request(reflexer.transport.to_reflexer)), \
                mock.patch.object(reflexer.transport, "OURS", "not-ours-"):
            self.assertNotEqual(hosts_given_the_key(), [REFLEXER])

    def test_hooks_given_the_key_turns_it_red(self):
        real = reflexer.transport.setup_http_client

        def keeps_hooks_below(stock, wire):
            made = real(stock, wire)

            def http_client(key, own=None, **way):
                outer = made(key, own=own, **way)
                outer._transport.inner.event_hooks = own.event_hooks
                return outer
            return http_client

        with mock.patch.object(sys.modules[__name__], "setup_http_client", keeps_hooks_below):
            self.assertIn("a hook", hosts_given_the_key())

    def test_no_replay_guard_turns_it_red(self):
        with mock.patch.object(reflexer.transport, "is_replay", lambda body: False):
            self.assertTrue(a_replay_reached_the_provider())

    def test_no_fallback_turns_it_red(self):
        with mock.patch.object(reflexer.transport, "stays_straight", mock.Mock(side_effect=RuntimeError("made up"))):
            self.assertFalse(a_call_reflexer_could_not_take_reached_the_provider())

    def test_any_address_taken_turns_it_red(self):
        with mock.patch.object(reflexer, "checked_base", lambda base: base):
            self.assertTrue(a_plain_http_address_for_reflexer_was_taken())


if __name__ == "__main__":
    unittest.main()
