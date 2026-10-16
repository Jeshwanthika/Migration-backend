"""Pattern-based VBA procedure splitter (FR-AN2, FR-AN4).

The platform, not the LLM, decides where each procedure starts and ends, so line
numbers always match the source text. Lines are 1-based within the module's code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADER_RE = re.compile(
    r"^\s*(?:(?P<scope>Public|Private|Friend|Global)\s+)?(?:Static\s+)?"
    r"(?P<kind>Sub|Function|Property\s+(?:Get|Let|Set))\s+(?P<name>[A-Za-z_]\w*)",
    re.IGNORECASE,
)
_END_RE = re.compile(r"^\s*End\s+(?P<kind>Sub|Function|Property)\b", re.IGNORECASE)
_REM_RE = re.compile(r"^\s*Rem\b", re.IGNORECASE)


@dataclass
class Procedure:
    name: str
    kind: str                      # Sub, Function, Property Get, Property Let, Property Set
    scope: str                     # Public, Private, Friend, Global or "" (VBA default is Public)
    params: list
    returns: str | None
    start_line: int
    end_line: int
    text: str
    terminated: bool = True
    lines: list = field(default_factory=list, repr=False)


def strip_comment(line: str) -> str:
    """Remove a trailing ' comment, leaving quoted strings alone."""
    in_string = False
    for index, ch in enumerate(line):
        if ch == '"':
            in_string = not in_string
        elif ch == "'" and not in_string:
            return line[:index]
    return line


def _is_comment(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("'") or bool(_REM_RE.match(line))


def _logical_lines(lines: list):
    """Yield (first_line_no, last_line_no, text) joining ' _' continuation lines. Comments are dropped."""
    index = 0
    total = len(lines)
    while index < total:
        start = index
        text = strip_comment(lines[index]).rstrip()
        while text.endswith("_") and (len(text) == 1 or text[-2] in " \t") and index + 1 < total:
            index += 1
            text = text[:-1].rstrip() + " " + strip_comment(lines[index]).strip()
        yield start + 1, index + 1, text
        index += 1


def _split_top_level(text: str) -> list:
    parts, depth, current, in_string = [], 0, [], False
    for ch in text:
        if ch == '"':
            in_string = not in_string
        if not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(current))
                current = []
                continue
        current.append(ch)
    if "".join(current).strip():
        parts.append("".join(current))
    return parts


def _balanced_params(text: str, open_index: int):
    """Return (params_text, index_after_close) for the parenthesis at open_index."""
    depth = 0
    in_string = False
    for index in range(open_index, len(text)):
        ch = text[index]
        if ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return text[open_index + 1:index], index + 1
    return text[open_index + 1:], len(text)


_PARAM_RE = re.compile(
    r"^\s*(?P<optional>Optional\s+)?(?P<mode>ByVal\s+|ByRef\s+)?(?P<array>ParamArray\s+)?"
    r"(?P<name>[A-Za-z_]\w*)(?P<paren>\s*\(\s*\))?\s*(?:As\s+(?P<type>[\w\.]+))?\s*(?:=\s*(?P<default>.+))?$",
    re.IGNORECASE,
)


def parse_params(text: str) -> list:
    params = []
    for piece in _split_top_level(text):
        match = _PARAM_RE.match(piece.strip())
        if not match:
            params.append({"name": piece.strip(), "type": "Variant", "optional": False, "by_val": False})
            continue
        type_name = match.group("type") or "Variant"
        if match.group("paren") or match.group("array"):
            type_name += "()"
        params.append({
            "name": match.group("name"),
            "type": type_name,
            "optional": bool(match.group("optional")),
            "by_val": (match.group("mode") or "").strip().lower() == "byval",
        })
    return params


def parse_header(text: str):
    """Return (scope, kind, name, params, returns) or None if text is not a procedure header."""
    match = _HEADER_RE.match(text)
    if not match:
        return None
    kind_words = match.group("kind").split()
    kind = kind_words[0].capitalize() if len(kind_words) == 1 else f"Property {kind_words[1].capitalize()}"
    params, rest_index = [], match.end()
    after = text[match.end():]
    paren = after.find("(")
    if paren != -1 and not after[:paren].strip():
        inner, end = _balanced_params(after, paren)
        params = parse_params(inner)
        rest = after[end:]
    else:
        rest = after
    returns = None
    as_match = re.match(r"\s*As\s+([\w\.]+(?:\(\))?)", rest, re.IGNORECASE)
    if as_match and kind != "Sub":
        returns = as_match.group(1)
    return (match.group("scope") or "", kind, match.group("name"), params, returns)


def split_module(code: str):
    """Split module code into (declarations_text, procedures).

    declarations_text holds module-level lines outside any procedure (Option, Dim, Const,
    Type, Enum, Declare, events) without blank lines, comments or Attribute lines.
    """
    lines = code.split("\n")
    procedures = []
    declarations = []
    open_proc = None
    for first, last, text in _logical_lines(lines):
        if open_proc is None:
            header = parse_header(text) if not _is_comment(lines[first - 1]) else None
            if header:
                scope, kind, name, params, returns = header
                open_proc = {"scope": scope, "kind": kind, "name": name, "params": params,
                             "returns": returns, "start": first}
            elif text.strip() and not re.match(r"^\s*Attribute\s", text, re.IGNORECASE) and not _is_comment(lines[first - 1]):
                declarations.append(text.strip())
            continue
        end = _END_RE.match(text)
        if end and end.group("kind").lower() == open_proc["kind"].split()[0].lower():
            procedures.append(_build(open_proc, lines, first_end=last, terminated=True))
            open_proc = None
    if open_proc is not None:
        procedures.append(_build(open_proc, lines, first_end=len(lines), terminated=False))
    return "\n".join(declarations), procedures


def _build(info: dict, lines: list, first_end: int, terminated: bool) -> Procedure:
    start, end = info["start"], first_end
    body = lines[start - 1:end]
    return Procedure(
        name=info["name"], kind=info["kind"], scope=info["scope"], params=info["params"],
        returns=info["returns"], start_line=start, end_line=end, text="\n".join(body),
        terminated=terminated, lines=body,
    )


def procedure_id(module: str, proc: Procedure, taken: set) -> str:
    """Stable id like Module.Name. Property Get/Let/Set and repeats get a suffix."""
    base = f"{module}.{proc.name}"
    candidate = base
    if candidate in taken and proc.kind.startswith("Property"):
        candidate = f"{base}.{proc.kind.split()[1]}"
    counter = 2
    while candidate in taken:
        candidate = f"{base}.{counter}"
        counter += 1
    taken.add(candidate)
    return candidate


def signature(proc: Procedure) -> str:
    args = ", ".join(f"{p['name']} As {p['type']}" for p in proc.params)
    tail = f" As {proc.returns}" if proc.returns else ""
    return f"{proc.kind} {proc.name}({args}){tail}"
