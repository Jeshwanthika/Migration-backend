import json

from app.core.llm.base import LlmProvider, LlmResult


class FakeProvider(LlmProvider):
    """Scripted provider. Each script item is a dict/str (reply) or an Exception (raised)."""
    name = "fake"
    model = "fake-model"

    def __init__(self, script=None, responder=None):
        self.script = list(script or [])
        self.responder = responder
        self.calls = []

    def generate(self, system, prompt, *, json_output=True):
        self.calls.append((system, prompt))
        if self.responder is not None:
            item = self.responder(prompt, len(self.calls))
        else:
            item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        text = item if isinstance(item, str) else json.dumps(item)
        return LlmResult(text=text, input_tokens=10, output_tokens=5)


def fake_settings(**overrides):
    from pathlib import Path
    from app.core.settings import Settings
    base = dict(workspace_root=Path("."), llm_call_delay_seconds=0, llm_backoff_base_seconds=0, llm_retries=2,
                schema_reask=1, chunk_max_chars=12000)
    base.update(overrides)
    return Settings(**base)
