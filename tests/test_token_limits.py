"""Token-aware behavior: pacing under a tokens-per-minute limit, and splitting chunks that are too large."""
import re
import unittest

from app.core.llm import LlmGateway, LlmRequestTooLarge, LlmTransientError
from app.core.llm.gateway import TokenWindow, estimate_tokens
from app.plugins.xlsm_to_aspnetcore.analyzer_prompts import SYSTEM_PROMPT as ANALYZER_SYSTEM
from app.plugins.xlsm_to_aspnetcore.chunker import halves
from app.plugins.xlsm_to_aspnetcore.spec_architect import build_spec
from tests.fakes import FakeProvider, fake_settings
from tests.test_analyzer import VBA, full_reply
from tests.test_analyzer import run as run_analyzer
from tests.test_spec import analysis_fixture, good_chunk

PROC_RE = re.compile(r"' ---- (?:\[[^\]]+\] )?(?:Sub|Function|Property \w+) (\w+) ----")


def procs_in(prompt):
    return PROC_RE.findall(prompt)


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def gateway(provider, **settings):
    clock = Clock()
    return LlmGateway(provider, fake_settings(**settings), sleep=clock.sleep, clock=clock, window=TokenWindow()), clock


class WindowTests(unittest.TestCase):
    def test_no_wait_under_the_limit(self):
        w = TokenWindow()
        w.add(0, 3000, 500)
        self.assertEqual(w.wait_for(10, 4000, 8000), 0)

    def test_waits_until_old_tokens_expire(self):
        w = TokenWindow()
        w.add(0, 5000, 500)
        w.add(20, 2000, 500)
        self.assertAlmostEqual(w.wait_for(30, 3000, 8000), 30)  # the 5000 from t=0 frees up at t=60
        self.assertEqual(w.wait_for(61, 3000, 8000), 0)

    def test_expected_output_learns_from_replies(self):
        w = TokenWindow()
        self.assertEqual(w.expected_output(), 1500)
        w.add(0, 1000, 300)
        w.add(1, 1000, 700)
        self.assertEqual(w.expected_output(), 700)

    def test_halves_keep_order(self):
        self.assertEqual(halves([1, 2, 3]), [[1, 2], [3]])
        self.assertEqual(halves([1, 2]), [[1], [2]])


class GatewayPacingTests(unittest.TestCase):
    def test_paces_calls_under_the_limit_instead_of_hitting_429(self):
        gw, clock = gateway(FakeProvider([{"a": 1}] * 4), llm_tokens_per_minute=40, llm_call_delay_seconds=0)
        for _ in range(4):
            gw.call_json("n", "s", "p", lambda d: [])
        # Each call costs 15 tokens, so the fourth one would pass 40 within the minute and has to wait.
        self.assertEqual(len([s for s in clock.slept if s > 0]), 1)
        self.assertGreater(clock.slept[-1], 50)

    def test_no_pacing_without_a_known_limit(self):
        gw, clock = gateway(FakeProvider([{"a": 1}] * 3))
        for _ in range(3):
            gw.call_json("n", "s", "p", lambda d: [])
        self.assertEqual(clock.slept, [])

    def test_uses_the_limit_the_provider_reports(self):
        provider = FakeProvider([{"a": 1}])
        provider.tokens_per_minute = 8000
        gw, _ = gateway(provider)
        self.assertEqual(gw.tokens_per_minute(), 8000)
        self.assertEqual(gw.max_input_tokens(), 4000)
        self.assertTrue(gw.fits("s", "x" * 1000))
        self.assertFalse(gw.fits("s", "x" * 20000))

    def test_configured_input_cap_wins(self):
        gw, _ = gateway(FakeProvider([]), llm_tokens_per_minute=8000, llm_max_input_tokens=100)
        self.assertFalse(gw.fits("", "x" * 400))

    def test_request_larger_than_the_limit_is_refused_without_a_call(self):
        provider = FakeProvider([])
        gw, _ = gateway(provider, llm_tokens_per_minute=100)
        with self.assertRaises(LlmRequestTooLarge):
            gw.call_json("n", "s", "x" * 2000, lambda d: [])
        self.assertEqual(provider.calls, [])

    def test_retry_after_is_honored(self):
        provider = FakeProvider([LlmTransientError("429", retry_after=7.5), {"ok": 1}])
        gw, clock = gateway(provider, llm_backoff_base_seconds=0)
        gw.call_json("n", "s", "p", lambda d: [])
        self.assertIn(7.5, clock.slept)

    def test_estimate(self):
        self.assertEqual(estimate_tokens("a" * 33), 10)


class SplittingTests(unittest.TestCase):
    @staticmethod
    def analyzer_responder(reject_multi=True):
        def respond(prompt, _n):
            names = procs_in(prompt)
            if reject_multi and len(names) > 1:
                return LlmRequestTooLarge("413 too large")
            return full_reply(*names)
        return respond

    def test_analyzer_splits_a_chunk_the_provider_rejects_as_too_large(self):
        provider = FakeProvider(responder=self.analyzer_responder())
        (model, flags), _ = run_analyzer(provider)
        self.assertTrue(all(p["analyzed"] for p in model["procedures"]))
        self.assertEqual(sum(1 for _s, prompt in provider.calls if len(procs_in(prompt)) == 1), 3)
        self.assertFalse([f for f in flags if f["code"] == "CHUNK_ANALYSIS_FAILED"])

    def test_analyzer_splits_before_sending_when_the_prompt_is_too_large(self):
        whole = FakeProvider(responder=self.analyzer_responder(reject_multi=False))
        run_analyzer(whole)
        cap = estimate_tokens(ANALYZER_SYSTEM, whole.calls[0][1]) - 1  # the whole module no longer fits
        provider = FakeProvider(responder=self.analyzer_responder(reject_multi=False))
        (model, _flags), _ = run_analyzer(provider, llm_max_input_tokens=cap)
        self.assertTrue(all(p["analyzed"] for p in model["procedures"]))
        self.assertGreater(len(provider.calls), 1)
        self.assertTrue(all(estimate_tokens(ANALYZER_SYSTEM, p) <= cap for _s, p in provider.calls))

    def test_single_procedure_too_large_is_flagged_not_fatal(self):
        def respond(prompt, _n):
            names = procs_in(prompt)
            if "Beep" in names:
                return LlmRequestTooLarge("413 too large")
            return full_reply(*names)
        (model, flags), _ = run_analyzer(FakeProvider(responder=respond))
        procs = {p["name"]: p for p in model["procedures"]}
        self.assertTrue(procs["ImportData"]["analyzed"])
        self.assertFalse(procs["Beep"]["analyzed"])
        self.assertTrue([f for f in flags if f["code"] == "CHUNK_ANALYSIS_FAILED"])

    def test_spec_splits_a_chunk_the_provider_rejects_as_too_large(self):
        analysis = analysis_fixture()

        def respond(prompt, _n):
            if prompt.startswith("Entities:"):
                return {"merge": []}
            if len(procs_in(prompt)) > 1:
                return LlmRequestTooLarge("413 too large")
            return good_chunk()
        provider = FakeProvider(responder=respond)
        s = fake_settings()
        spec = build_spec(VBA, analysis, LlmGateway(provider, s, sleep=lambda _s: None, window=TokenWindow()), s)
        self.assertFalse([f for f in spec["flags"] if f["code"] == "SPEC_CHUNK_FAILED"])
        self.assertTrue(spec["entities"])
        self.assertEqual(spec["usage"]["chunks"], 3)


if __name__ == "__main__":
    unittest.main()
