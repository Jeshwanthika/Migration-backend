import unittest

from app.core.llm.factory import create_provider
from app.core.schema_validation import schema_errors
from app.plugins.xlsm_to_aspnetcore import analyzer_prompts, spec_prompts
from app.plugins.xlsm_to_aspnetcore.gen import methods
from tests.fakes import fake_settings


class MockProviderTests(unittest.TestCase):
    def setUp(self):
        self.p = create_provider(fake_settings(llm_provider="mock"))

    def test_analyzer_answer_is_valid(self):
        import json
        r = self.p.generate(analyzer_prompts.SYSTEM_PROMPT, "Procedures to analyze:\n' ---- Sub Foo ----\nSub Foo()\nEnd Sub")
        self.assertEqual(schema_errors("analysis_chunk", json.loads(r.text)), [])

    def test_spec_answer_is_valid(self):
        import json
        r = self.p.generate(spec_prompts.SYSTEM_PROMPT, "' ---- [PRC-001] Sub Foo ----\nx")
        d = json.loads(r.text)
        self.assertEqual(schema_errors("spec_chunk", d), [])
        self.assertEqual(d["rules"][0]["source_ref"], ["PRC-001"])

    def test_generator_system_prompt_is_recognised(self):
        self.assertIn("C# method bodies", methods.SYSTEM_PROMPT)
        self.assertTrue(spec_prompts.RECONCILE_SYSTEM.startswith("You compare entity names"))


if __name__ == "__main__":
    unittest.main()
