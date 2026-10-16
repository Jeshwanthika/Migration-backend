import json
import tempfile
import unittest
from pathlib import Path

from app.core.errors import BlockerError
from app.core.llm import LlmGateway, LlmPermanentError, LlmSchemaError, LlmTransientError
from app.core.llm.gateway import parse_json_text
from app.core.llm.gemini import classify_error
from tests.fakes import FakeProvider, fake_settings


def no_errors(_data):
    return []


class Slept:
    def __init__(self):
        self.times = []

    def __call__(self, seconds):
        self.times.append(seconds)


class ParseTests(unittest.TestCase):
    def test_plain_and_fenced_json(self):
        self.assertEqual(parse_json_text('{"a": 1}'), {"a": 1})
        self.assertEqual(parse_json_text('```json\n{"a": 1}\n```'), {"a": 1})

    def test_bad_json_raises(self):
        with self.assertRaises(ValueError):
            parse_json_text("not json")


class ClassifyTests(unittest.TestCase):
    def err(self, code):
        e = Exception("x")
        e.code = code
        return e

    def test_statuses(self):
        self.assertIsInstance(classify_error(self.err(429)), LlmTransientError)
        self.assertIsInstance(classify_error(self.err(503)), LlmTransientError)
        for code in (400, 401, 403, 404):
            self.assertIsInstance(classify_error(self.err(code)), LlmPermanentError)
        self.assertIn("GEMINI_API_KEY", str(classify_error(self.err(401))))
        self.assertIn("GEMINI_MODEL", str(classify_error(self.err(404))))

    def test_network_errors_are_transient(self):
        self.assertIsInstance(classify_error(TimeoutError()), LlmTransientError)
        self.assertIsInstance(classify_error(ConnectionError()), LlmTransientError)
        self.assertIsInstance(classify_error(ValueError("weird")), LlmPermanentError)


class GatewayTests(unittest.TestCase):
    def test_retries_transient_then_succeeds_with_backoff(self):
        provider = FakeProvider([LlmTransientError("429"), LlmTransientError("429"), {"ok": 1}])
        sleep = Slept()
        gw = LlmGateway(provider, fake_settings(llm_retries=3, llm_backoff_base_seconds=2.0), sleep=sleep, rng=lambda: 1.0)
        self.assertEqual(gw.call_json("n", "s", "p", no_errors), {"ok": 1})
        self.assertEqual(sleep.times, [2.0, 4.0])
        self.assertEqual(gw.calls, 1)

    def test_gives_up_after_retries(self):
        provider = FakeProvider([LlmTransientError("429")] * 3)
        gw = LlmGateway(provider, fake_settings(llm_retries=2), sleep=Slept())
        with self.assertRaises(LlmTransientError) as ctx:
            gw.call_json("n", "s", "p", no_errors)
        self.assertIn("2 retries", str(ctx.exception))
        self.assertEqual(len(provider.calls), 3)

    def test_permanent_error_is_not_retried(self):
        provider = FakeProvider([LlmPermanentError("bad key")])
        gw = LlmGateway(provider, fake_settings(), sleep=Slept())
        with self.assertRaises(LlmPermanentError):
            gw.call_json("n", "s", "p", no_errors)
        self.assertEqual(len(provider.calls), 1)

    def test_delay_between_calls(self):
        now = [100.0]
        sleep = Slept()
        provider = FakeProvider([{"a": 1}, {"a": 2}])
        gw = LlmGateway(provider, fake_settings(llm_call_delay_seconds=4.0), sleep=sleep, clock=lambda: now[0])
        gw.call_json("n", "s", "p", no_errors)
        self.assertEqual(sleep.times, [])           # first call never waits
        now[0] += 1.5
        gw.call_json("n", "s", "p", no_errors)
        self.assertEqual(sleep.times, [2.5])        # waits out the rest of the 4 s gap

    def test_reask_on_schema_failure_then_success(self):
        provider = FakeProvider([{"bad": True}, {"good": True}])
        validate = lambda d: [] if d.get("good") else ["good is required"]
        gw = LlmGateway(provider, fake_settings(schema_reask=2), sleep=Slept())
        self.assertEqual(gw.call_json("n", "s", "p", validate), {"good": True})
        self.assertIn("good is required", provider.calls[1][1])

    def test_invalid_json_then_gives_up(self):
        provider = FakeProvider(["nope", "still nope"])
        gw = LlmGateway(provider, fake_settings(schema_reask=1), sleep=Slept())
        with self.assertRaises(LlmSchemaError):
            gw.call_json("n", "s", "p", no_errors)
        self.assertEqual(len(provider.calls), 2)

    def test_token_budget_blocks(self):
        provider = FakeProvider([{"a": 1}, {"a": 2}])
        gw = LlmGateway(provider, fake_settings(max_tokens_per_run=20), sleep=Slept())
        gw.call_json("n", "s", "p", no_errors)       # 15 tokens used
        gw.call_json("n", "s", "p", no_errors)       # 30 now
        with self.assertRaises(BlockerError):
            gw.call_json("n", "s", "p", no_errors)

    def test_budget_counts_tokens_from_earlier_stages(self):
        gw = LlmGateway(FakeProvider([{"a": 1}]), fake_settings(max_tokens_per_run=100), tokens_before=100, sleep=Slept())
        with self.assertRaises(BlockerError):
            gw.call_json("n", "s", "p", no_errors)

    def test_log_has_prompt_and_response_and_no_key(self):
        folder = Path(tempfile.mkdtemp())
        gw = LlmGateway(FakeProvider([{"a": 1}]), fake_settings(gemini_api_key="SECRET-KEY"), log_dir=folder, sleep=Slept())
        gw.call_json("analyzer", "sys", "the prompt", no_errors)
        text = (folder / "analyzer.jsonl").read_text()
        entry = json.loads(text.splitlines()[0])
        self.assertEqual(entry["prompt"], "the prompt")
        self.assertEqual(entry["response"], '{"a": 1}')
        self.assertNotIn("SECRET-KEY", text)


if __name__ == "__main__":
    unittest.main()
