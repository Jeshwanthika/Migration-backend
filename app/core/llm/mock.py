"""Offline stand-in for a real model (LLM_PROVIDER=mock).

For testing the pipeline and the later phases without an API key or quota. It returns small, valid but
generic answers, so the migration spec and the generated app are placeholders: every method body throws
NotImplementedException. Never use it for a real migration."""
from __future__ import annotations

import json
import re

from app.core.llm.base import LlmProvider, LlmResult

_HEADER = re.compile(r"^' ---- (?:\[(?P<id>[^\]]+)\] )?(?P<kind>Sub|Function|Property \w+) (?P<name>\w+)", re.M)
_METHOD_ID = re.compile(r"^id: (\S+)", re.M)


class MockProvider(LlmProvider):
    name = "mock"
    model = "mock"

    def generate(self, system: str, prompt: str, *, json_output: bool = True) -> LlmResult:
        data = self._answer(system, prompt)
        return LlmResult(text=json.dumps(data), input_tokens=len(prompt) // 4, output_tokens=50)

    def _answer(self, system: str, prompt: str) -> dict:
        if system.startswith("You are a senior engineer analyzing"):
            return {"module_summary": "Mock analysis (no model was used).",
                    "procedures": [{"name": m["name"], "kind": m["kind"], "role": "utility",
                                    "summary": "Mock summary.", "calls": [], "reads": [], "writes": [],
                                    "support": "supported", "support_reason": "Mock provider: nothing was analyzed.",
                                    "constructs": []} for m in _HEADER.finditer(prompt)]}
        if system.startswith("You are a business analyst"):
            found = list(_HEADER.finditer(prompt))
            ids = [m["id"] for m in found if m["id"]]
            return {"entities": [{"name": "Item", "description": "Placeholder record from the mock provider.",
                                  "inferred": True, "source_ref": ids[:1],
                                  "fields": [{"name": "Name", "type": "string"}, {"name": "Amount", "type": "decimal"}]}] if ids else [],
                    "rules": [{"name": m["name"], "kind": "calculation", "description": f"Mock rule for {m['name']}.",
                               "inputs": [], "outputs": [], "entities": [], "source_ref": [m["id"]]} for m in found if m["id"]],
                    "screens": [], "workflows": [], "reports": [], "open_questions": []}
        if system.startswith("You compare entity names"):
            return {"merge": []}
        if "C# method bodies" in system:
            return {"methods": [{"id": mid, "body": 'throw new NotImplementedException("Placeholder from the mock provider.");'}
                                for mid in _METHOD_ID.findall(prompt)]}
        return {}
