"""Quick check of GEMINI_API_KEY and GEMINI_MODEL. Run from the backend folder:

    python scripts/check_gemini.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import BlockerError  # noqa: E402
from app.core.llm import LlmError, LlmGateway, create_provider  # noqa: E402
from app.core.settings import Settings  # noqa: E402


def main() -> int:
    settings = Settings.from_env()
    try:
        provider = create_provider(settings)
        print(f"Trying model {provider.model} (up to {settings.llm_retries} retries with backoff)...")
        gateway = LlmGateway(provider, settings)
        data = gateway.call_json("check", "Reply with JSON only.", 'Return {"ok": true}', lambda d: [])
    except (BlockerError, LlmError) as exc:
        print(f"FAILED: {exc}")
        return 1
    print(f"OK. Model {provider.model} answered: {data}")
    print(f"Tokens used: {gateway.tokens_used}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
