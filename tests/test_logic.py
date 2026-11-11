"""The logic on plain values: no SDK, no server, no network. Run: python -m unittest tests.test_logic"""
import os, sys, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import reflexer
from reflexer import ANSWER, ASKED, FAILED, GRACE

secret = "rfx1_aaaaakq_" + "a" * 52
KEY = f"{secret}_{reflexer.checksum(secret)}"
WIRE = {"reflexer_path": "/openai", "provider": "https://api.openai.com", "calls": r"/v1/(chat/completions|responses)$"}
ROUTED = WIRE | {"routers": {  # as reflexer/openai.py's: a router with a route of its own at reflexer, by its host
    "openrouter.ai":        {"reflexer_path": "/openrouter", "provider": "https://openrouter.ai", "calls": r"/api/v1/chat/completions$"},
    "ai-gateway.vercel.sh": {"reflexer_path": "/vercel", "provider": "https://ai-gateway.vercel.sh", "calls": r"/v1/chat/completions$"}}}
CHAT = "https://api.openai.com/v1/chat/completions"
OURS = {"reflexer-request-id": "made-up", "reflexer-status-origin": "reflexer", "content-type": "application/json"}  # as the HTTP library gives them
LONG = 10**6  # seconds: past every wait


def spread_of_returns(clients=8):
    """How far apart, in seconds, clients that failed at the same moment try reflexer again."""
    clock = Clock()
    breakers = [reflexer.Breaker(clock) for _ in range(clients)]
    for breaker in breakers:
        breaker.note(reflexer.FAILED, None)
    returns = [breaker.open_until for breaker in breakers]
    return max(returns) - min(returns)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Route(unittest.TestCase):
    def setUp(self):
        self.reflexer = reflexer.Reflexer(KEY, WIRE)

    def test_a_message_call_goes_to_reflexer_with_the_key(self):
        url, headers = self.reflexer.route(CHAT, {"authorization": "Bearer sk-made-up"})
        self.assertEqual(url, "https://api.reflexer.ai/openai/v1/chat/completions")
        self.assertEqual(headers, {"authorization": "Bearer sk-made-up", "reflexer-key": KEY})

    def test_the_lines_namespace_goes_on_each_call_and_a_calls_own_wins(self):
        way = reflexer.Reflexer(KEY, WIRE, namespace="team-a")
        self.assertEqual(way.route(CHAT, {})[1]["reflexer-namespace"], "team-a")
        self.assertEqual(way.route(CHAT, {"reflexer-namespace": "team-b"})[1]["reflexer-namespace"], "team-b")
        self.assertNotIn("reflexer-namespace", self.reflexer.route(CHAT, {})[1])

    def test_a_base_of_the_clients_own_is_named_as_the_upstream(self):
        _, headers = self.reflexer.route("https://api.groq.com/openai/v1/chat/completions", {})
        self.assertEqual(headers["reflexer-upstream"], "https://api.groq.com/openai")

    def test_a_router_with_a_route_of_its_own_takes_it_for_the_calls_it_serves(self):
        """Reflexer reads a router's own body keys only on its route; its default base names no upstream."""
        way = reflexer.Reflexer(KEY, ROUTED)
        for url, to, upstream in (
                ("https://openrouter.ai/api/v1/chat/completions", "/openrouter/api/v1/chat/completions", None),
                ("https://ai-gateway.vercel.sh/v1/chat/completions", "/vercel/v1/chat/completions", None),
                ("https://openrouter.ai:8443/api/v1/chat/completions", "/openrouter/api/v1/chat/completions", "https://openrouter.ai:8443"),
                ("https://openrouter.ai/api/v1/responses", "/openai/v1/responses", "https://openrouter.ai/api"),  # not its route: as before
                ("https://ai-gateway.vercel.sh/v1/responses", "/openai/v1/responses", "https://ai-gateway.vercel.sh")):
            made, headers = way.route(url, {})
            self.assertEqual((made, headers.get("reflexer-upstream")), (f"https://api.reflexer.ai{to}", upstream), url)
        self.assertIsNone(way.route("https://openrouter.ai/api/v1/models", {}))

    def test_straight(self):
        self.assertIsNone(self.reflexer.route("https://api.openai.com/v1/models", {}))
        self.assertIsNone(self.reflexer.route(CHAT, {reflexer.PASS_THROUGH: "1"}))
        self.assertIsNone(self.reflexer.route("http://localhost:11434/v1/chat/completions", {}))
        self.assertIsNone(reflexer.Reflexer(KEY, WIRE, sample=0.0).route(CHAT, {}))
        for private in ("https://localhost./v1/chat/completions", "https://10.0.0.5/v1/chat/completions"):
            self.assertIsNone(self.reflexer.route(private, {}), private)

    def test_a_private_address_in_another_notation_goes_straight(self):
        """As the system's resolver reads an IPv4 address (inet_aton), which the client's HTTP client goes by."""
        for host in ("10.1", "127.1", "167772161", "0x0a000001", "0300.0250.0.1", "0X0A.1", "10.0.0.5.", "0"):
            self.assertIsNone(self.reflexer.route(f"https://{host}/v1/chat/completions", {}), host)
        for host in ("8.8.8.8", "134744072", "0x08080808", "8.526344", "1.2.3.4.5", "10.1.example", "0x", "0x1g", "08.0.0.1", "1.16777216"):
            self.assertIsNotNone(self.reflexer.route(f"https://{host}/v1/chat/completions", {}), host)  # public, or a name

    def test_no_userinfo_in_the_upstream(self):
        _, headers = self.reflexer.route("https://user:made-up@router.example/v1/chat/completions", {})
        self.assertEqual(headers["reflexer-upstream"], "https://router.example")

    def test_a_key_not_of_the_form_raises(self):
        with self.assertRaises(ValueError):
            reflexer.Reflexer(KEY[:-1] + "a", WIRE)


class Construction(unittest.TestCase):
    def test_a_trailing_slash_on_the_base_is_no_double_slash(self):
        url, _ = reflexer.Reflexer(KEY, WIRE, base="https://reflexer.example/").route(CHAT, {})
        self.assertEqual(url, "https://reflexer.example/openai/v1/chat/completions")

    def test_a_base_that_would_carry_the_key_in_clear_raises(self):
        for base in ("http://reflexer.example", None):
            with self.assertRaises((ValueError, AttributeError)):
                reflexer.Reflexer(KEY, WIRE, base=base)
        reflexer.Reflexer(KEY, WIRE, base="http://127.0.0.1:8000")  # a stand-in on this machine

    def test_a_sample_not_a_number_from_0_to_1_raises(self):
        for sample in (-0.1, 1.5, float("nan"), "0.5", None, True):
            with self.assertRaisesRegex(ValueError, "^sample must be a number from 0 to 1: the share of calls that the SDK sends to reflexer$"):
                reflexer.Reflexer(KEY, WIRE, sample=sample)
        for sample in (0, 0.5, 1):
            reflexer.Reflexer(KEY, WIRE, sample=sample)

    def test_a_namespace_that_cannot_go_as_a_header_raises(self):
        for namespace in ("", " team", "team\r\nx-made-up: 1", "équipe", 7):
            with self.assertRaisesRegex(ValueError, "^a namespace may contain only"):
                reflexer.Reflexer(KEY, WIRE, namespace=namespace)
        for namespace in (None, "team-a", "Team A/2026"):
            reflexer.Reflexer(KEY, WIRE, namespace=namespace)

    def test_a_typo_in_a_provider_file_raises_when_the_client_is_made(self):
        with self.assertRaises(KeyError):
            reflexer.Reflexer(KEY, {"provider": "https://made-up.example"})


class Read(unittest.TestCase):
    def meaning(self, status, headers):
        return reflexer.read(status, headers.get("reflexer-status-origin"), reflexer.whole(headers.get("reflexer-straight")))

    def test_each_meaning(self):
        told = OURS | {"reflexer-straight": "5"}
        for status, headers, meaning in [
            (200, OURS, ANSWER),
            (200, told, ANSWER),  # an answer, not sent again
            (401, OURS, ANSWER),  # the client's SDK raises it, naming the reflexer key
            (200, {}, FAILED),  # none of our headers: the load balancer's
            (401, {}, FAILED),
            (429, OURS, FAILED),
            (503, OURS, FAILED),
            (529, OURS, FAILED),  # anthropic's overload
            (503, told, ASKED),
            (529, told, ASKED),
            (502, OURS | {"reflexer-status-origin": "connection"}, ASKED),
            (502, OURS | {"reflexer-status-origin": "relay"}, ASKED),  # the same meaning under its new name
            (200, OURS | {"reflexer-status-origin": "relay"}, ASKED),
            (204, {"reflexer-request-id": "made-up", "reflexer-status-origin": "reflexer", "reflexer-cost": "0"}, ANSWER),  # reflexer asked not to answer: its empty answer, never the provider's
            (401, told, GRACE),
            (400, told, GRACE),  # gemini's key error
            (500, OURS | {"reflexer-status-origin": "provider"}, ANSWER),  # a provider's status never trips it
        ]:
            self.assertEqual(self.meaning(status, headers), meaning, (status, headers))

    def test_a_straight_not_of_the_form_is_ignored(self):
        for value in ("5.0", "\u00b2", "9" * 400, "9" * 5000):
            self.assertIsNone(reflexer.whole(value), value)

    def test_a_429_saying_go_straight_is_no_key_in_its_grace(self):
        self.assertEqual(self.meaning(429, OURS | {"reflexer-straight": "5"}), ASKED)

    def test_a_redirect_goes_straight(self):
        self.assertEqual(self.meaning(307, OURS | {"reflexer-status-origin": "provider"}), ASKED)


class Breaker(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.breaker = reflexer.Breaker(self.clock)

    def test_a_failure_opens_it_for_a_while(self):
        self.breaker.note(FAILED, None)
        self.assertTrue(self.breaker.is_open())
        self.clock.now += reflexer.BACKOFF * (1 + reflexer.JITTER)
        self.assertFalse(self.breaker.is_open())

    def test_failures_in_a_row_double_up_to_the_cap(self):
        waits = []
        for _ in range(LONG.bit_length()):
            self.breaker.note(FAILED, None)
            waits.append(self.breaker.open_until - self.clock.now)
            self.clock.now = self.breaker.open_until
        self.assertLess(waits[0], 2 * reflexer.BACKOFF)
        self.assertGreater(waits[1], waits[0])
        self.assertLessEqual(max(waits), reflexer.BACKOFF_CAP * (1 + reflexer.JITTER))
        self.assertGreaterEqual(waits[-1], reflexer.BACKOFF_CAP)

    def test_an_answer_ends_the_row(self):
        self.breaker.note(FAILED, None)
        self.clock.now = self.breaker.open_until
        self.breaker.note(ANSWER, None)
        self.breaker.note(FAILED, None)
        self.assertLess(self.breaker.open_until - self.clock.now, 2 * reflexer.BACKOFF)

    def test_calls_in_flight_count_as_one_failure(self):
        for _ in range(8):
            self.breaker.note(FAILED, None)
        self.assertLessEqual(self.breaker.open_until, reflexer.BACKOFF * (1 + reflexer.JITTER))

    def test_a_long_outage_never_overflows(self):
        for _ in range(LONG.bit_length() * 100):
            self.clock.now = self.breaker.open_until
            self.breaker.note(FAILED, None)

    def test_not_counted_keeps_it_closed(self):
        self.breaker.note(ASKED, None)
        self.breaker.note(GRACE, None)
        self.assertFalse(self.breaker.is_open())

    def test_told_twice_in_a_row_opens_it_for_those_seconds(self):
        self.breaker.note(ANSWER, 30)
        self.assertFalse(self.breaker.is_open())
        self.breaker.note(ANSWER, 30)
        self.assertTrue(self.breaker.is_open())
        self.clock.now += 30 * (1 + reflexer.JITTER)
        self.assertFalse(self.breaker.is_open())

    def test_clients_failing_at_once_do_not_return_together(self):
        self.assertGreater(spread_of_returns(), 0)

    def test_no_jitter_turns_it_red(self):
        with mock.patch.object(reflexer, "JITTER", 0.0):
            self.assertEqual(spread_of_returns(), 0)

    def test_the_jitter_stays_small_on_a_long_wait(self):
        self.breaker.note(ANSWER, 86400)
        self.breaker.note(ANSWER, 86400)
        self.assertLessEqual(self.breaker.open_until, 86400 + reflexer.BACKOFF_CAP * reflexer.JITTER)

    def test_a_shorter_wait_does_not_cut_a_longer_one(self):
        self.breaker.note(ANSWER, 86400)
        self.breaker.note(ANSWER, 86400)
        self.breaker.note(ANSWER, 5)
        self.assertGreaterEqual(self.breaker.open_until, 86400)

    def test_told_twice_not_in_a_row_does_not(self):
        self.breaker.note(ANSWER, 30)
        self.breaker.note(ANSWER, None)
        self.breaker.note(ANSWER, 30)
        self.assertFalse(self.breaker.is_open())


class Together(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.reflexer = reflexer.Reflexer(KEY, WIRE, clock=self.clock)

    def test_a_failure_sends_this_call_and_the_next_straight(self):
        with self.assertLogs("reflexer", "WARNING") as logged:
            self.reflexer.failed(ValueError("text that could quote a request"))
        self.assertNotIn("text that could quote", logged.output[0])
        self.assertIsNone(self.reflexer.route(CHAT, {}))
        self.clock.now += reflexer.BACKOFF * (1 + reflexer.JITTER)
        self.assertTrue(self.reflexer.goes_straight(401, {}))  # the load balancer's own
        self.assertIsNone(self.reflexer.route(CHAT, {}))

    def test_an_answer_does_not(self):
        self.assertFalse(self.reflexer.goes_straight(200, OURS))
        self.assertIsNotNone(self.reflexer.route(CHAT, {}))

    def test_a_key_in_its_grace_warns(self):
        with self.assertLogs("reflexer", "WARNING"):
            self.assertTrue(self.reflexer.goes_straight(401, OURS | {"reflexer-straight": "3600"}))


if __name__ == "__main__":
    unittest.main()
