import json
import unittest

import httpx

from app.core.errors import BlockerError
from app.core.llm import LlmPermanentError, LlmTransientError, create_provider
from app.core.llm.groq import GroqProvider, classify_status
from tests.fakes import fake_settings


def provider_with(handler):
    p = GroqProvider("gsk-test", "openai/gpt-oss-120b")
    p._client = httpx.Client(transport=httpx.MockTransport(handler), headers=p._client.headers)
    return p


def ok(content, usage=None):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}],
                                     "usage": usage or {"prompt_tokens": 7, "completion_tokens": 3}})


class GroqProviderTests(unittest.TestCase):
    def test_sends_messages_json_mode_and_reads_usage(self):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers["Authorization"]
            seen["body"] = json.loads(request.content)
            return ok('{"a": 1}')

        result = provider_with(handler).generate("sys", "prompt")
        self.assertEqual(result.text, '{"a": 1}')
        self.assertEqual((result.input_tokens, result.output_tokens), (7, 3))
        self.assertEqual(seen["auth"], "Bearer gsk-test")
        self.assertEqual(seen["body"]["model"], "openai/gpt-oss-120b")
        self.assertEqual(seen["body"]["response_format"], {"type": "json_object"})
        self.assertEqual([m["role"] for m in seen["body"]["messages"]], ["system", "user"])

    def test_plain_text_mode_has_no_response_format(self):
        seen = {}

        def handler(request):
            seen["body"] = json.loads(request.content)
            return ok("hello")

        provider_with(handler).generate("sys", "prompt", json_output=False)
        self.assertNotIn("response_format", seen["body"])

    def test_http_errors_are_classified(self):
        with self.assertRaises(LlmTransientError):
            provider_with(lambda r: httpx.Response(429, json={})).generate("s", "p")
        with self.assertRaises(LlmPermanentError) as e:
            provider_with(lambda r: httpx.Response(401, json={})).generate("s", "p")
        self.assertIn("GROQ_API_KEY", str(e.exception))

    def test_network_error_is_transient(self):
        def handler(request):
            raise httpx.ConnectError("down")
        with self.assertRaises(LlmTransientError):
            provider_with(handler).generate("s", "p")

    def test_empty_answer_is_transient(self):
        with self.assertRaises(LlmTransientError):
            provider_with(lambda r: ok("")).generate("s", "p")


class ClassifyStatusTests(unittest.TestCase):
    def test_statuses(self):
        self.assertIsInstance(classify_status(429), LlmTransientError)
        self.assertIsInstance(classify_status(503), LlmTransientError)
        for code in (400, 401, 403, 404, 413):
            self.assertIsInstance(classify_status(code), LlmPermanentError)
        self.assertIn("GROQ_MODEL", str(classify_status(404)))

    def test_invalid_json_mode_output_is_transient(self):
        body = {"error": {"code": "json_validate_failed", "message": "Failed to generate JSON"}}
        self.assertIsInstance(classify_status(400, body), LlmTransientError)


class FactoryTests(unittest.TestCase):
    def test_groq_needs_key_and_model(self):
        with self.assertRaises(BlockerError) as e:
            create_provider(fake_settings(llm_provider="groq", groq_model="m"))
        self.assertIn("GROQ_API_KEY", str(e.exception))
        with self.assertRaises(BlockerError) as e:
            create_provider(fake_settings(llm_provider="groq", groq_api_key="k"))
        self.assertIn("GROQ_MODEL", str(e.exception))

    def test_groq_is_built(self):
        p = create_provider(fake_settings(llm_provider="groq", groq_api_key="k", groq_model="m"))
        self.assertIsInstance(p, GroqProvider)
        self.assertEqual(p.model, "m")


if __name__ == "__main__":
    unittest.main()
