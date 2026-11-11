"""The live check's own verdicts, on made-up headers: it must fail on a broken wire and pass a sound one."""
import os, sys, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "live"))
import check


class Judge(unittest.TestCase):
    def test_a_sound_served_answer_passes(self):
        self.assertEqual(check.judge({"reflexer-answered-by": "reflexer", "reflexer-cost-nano-usd": "12000", "reflexer-request-id": "x"},
                                     "frontier-x-reflexer", 1.2e-05), [])

    def test_a_served_answer_without_its_model_or_price_fails(self):
        self.assertEqual(len(check.judge({"reflexer-answered-by": "reflexer"}, "frontier-x", None)), 3)

    def test_a_pass_through_priced_by_reflexer_fails(self):
        self.assertTrue(check.judge({"reflexer-answered-by": "provider", "reflexer-cost-nano-usd": "5"}, "frontier-x", 0.5))

    def test_a_straight_call_passes(self):
        self.assertEqual(check.judge({}, "frontier-x", None), [])


class Endpoint(unittest.TestCase):
    def test_no_endpoint_is_taken_by_default(self):
        with mock.patch.dict(os.environ, {"REFLEXER_KEY": "made-up"}, clear=True), self.assertRaises(SystemExit) as raised:
            check.main(["openai"])
        self.assertEqual(str(raised.exception), "set REFLEXER_BASE")


class Replay(unittest.TestCase):
    def test_from_its_field_or_reflexer_passes(self):
        self.assertFalse(check.replay_broken({}, "from the replay"))
        self.assertFalse(check.replay_broken({"reflexer-answered-by": "reflexer"}, "anything"))

    def test_from_the_provider_fails(self):
        self.assertTrue(check.replay_broken({"reflexer-answered-by": "provider"}, "from the replay"))
        self.assertTrue(check.replay_broken({}, "from the provider"))


if __name__ == "__main__":
    unittest.main()
