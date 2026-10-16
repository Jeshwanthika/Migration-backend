"""Validate artifacts against the JSON Schema files in backend/schemas/."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.core.errors import BlockerError

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


@lru_cache(maxsize=None)
def _load_schema(name: str) -> dict:
    with open(SCHEMA_DIR / f"{name}.schema.json", "r", encoding="utf-8") as handle:
        return json.load(handle)


def schema_errors(name: str, data) -> list:
    """Return readable error strings, empty if data matches the named schema."""
    try:
        import jsonschema
    except ImportError as exc:
        raise BlockerError("The 'jsonschema' package is not installed on the server.") from exc
    validator = jsonschema.Draft202012Validator(_load_schema(name))
    errors = sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.path])
    return [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors]


def validate_artifact(name: str, data) -> None:
    """Raise BlockerError if data does not match the artifact's schema."""
    errors = schema_errors(name, data)
    if errors:
        raise BlockerError(f"Internal error: {name} did not match its schema at {errors[0]}")
