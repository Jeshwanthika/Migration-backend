"""Classify a VBA module from its Attribute lines (spec FR-EX2)."""
from __future__ import annotations

import re

_ATTR_RE = re.compile(r'^\s*Attribute\s+(VB_\w+)\s*=\s*"?([^"\r\n]*)"?\s*$', re.IGNORECASE)
_WORKSHEET_GUID = "00020820-0000-0000-C000-000000000046"
_WORKBOOK_GUID = "00020819-0000-0000-C000-000000000046"
_CHART_GUID = "00020821-0000-0000-C000-000000000046"
_CLASS_GUID = "FCFB3D2A-A0FA-1068-A738-08002B3371B5"


def parse_attributes(code: str) -> dict:
    attrs = {}
    for line in code.splitlines():
        match = _ATTR_RE.match(line)
        if match:
            attrs.setdefault(match.group(1).lower(), match.group(2))
    return attrs


def module_name(code: str, fallback: str) -> str:
    name = parse_attributes(code).get("vb_name", "").strip()
    return name or fallback


def classify_module(name: str, code: str, vba_filename: str = "") -> str:
    attrs = parse_attributes(code)
    base = attrs.get("vb_base", "").upper()
    if _WORKSHEET_GUID in base or _CHART_GUID in base:
        return "sheet"
    if _WORKBOOK_GUID in base or name.lower() == "thisworkbook":
        return "workbook"
    if base.count("{") >= 2:  # UserForms carry two GUIDs in VB_Base
        return "form"
    if _CLASS_GUID in base:
        return "class"
    if vba_filename.lower().endswith(".frm"):
        return "form"
    if vba_filename.lower().endswith(".cls"):
        return "class"
    return "standard"


def meaningful_line_count(code: str) -> int:
    """Lines that are real code: not blank, not Attribute lines, not Option lines."""
    count = 0
    for line in code.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith("attribute ") or lowered.startswith("option "):
            continue
        count += 1
    return count
