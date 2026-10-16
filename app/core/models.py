"""Shared constants and small helpers for run records and flags."""
from __future__ import annotations

from datetime import datetime, timezone

RUN_RUNNING = "RUNNING"
RUN_COMPLETED = "COMPLETED"
RUN_COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
RUN_FAILED = "FAILED"

NODE_PENDING = "pending"
NODE_RUNNING = "running"
NODE_DONE = "done"
NODE_FAILED = "failed"
NODE_SKIPPED = "skipped"

SEV_INFO = "Info"
SEV_WARNING = "Warning"
SEV_BLOCKER = "Blocker"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def new_flag(code, severity, reason, *, support=None, source_ref=None, snippet=None, suggested_action=None) -> dict:
    """Build a flag object as defined in section 9 of the spec."""
    return {
        "code": code,
        "severity": severity,
        "support": support,
        "source_ref": source_ref,
        "snippet": snippet,
        "reason": reason,
        "suggested_action": suggested_action,
    }


def has_warnings(flags) -> bool:
    """True if any flag is a Warning or Blocker. Info flags never change the run status."""
    return any(f.get("severity") in (SEV_WARNING, SEV_BLOCKER) for f in (flags or []))
