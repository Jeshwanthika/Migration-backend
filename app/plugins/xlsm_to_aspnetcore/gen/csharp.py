"""Small helpers for writing safe C# and Razor text: names, types, escaping, and a light code check."""
from __future__ import annotations

import html
import re

from app.plugins.xlsm_to_aspnetcore.spec_merge import norm_field_type, norm_key, pascal

# Class names that would clash with common .NET types once their namespace is imported.
RESERVED_TYPE_NAMES = {
    "Object", "String", "Int32", "Int64", "Boolean", "Decimal", "Double", "DateTime", "TimeSpan", "Type", "List",
    "Dictionary", "Exception", "Console", "Math", "Convert", "Path", "File", "Directory", "Task", "Action", "Func",
    "Guid", "Environment", "Random", "Enum", "Array", "Attribute", "Buffer", "Nullable", "Version", "Uri", "Lazy",
    "Tuple", "Stream", "Thread", "Timer", "Encoding", "StringBuilder", "Regex", "Process", "HttpClient", "Page",
    "Controller", "Index", "Error", "Program", "Startup", "Models", "Services", "Infrastructure", "Pages",
    "Coerce", "ResultFormatter", "ReportFile", "IRepository", "JsonRepository", "IEntity", "BusinessRules",
}
MEMBER_RESERVED = {"Equals", "GetType", "ToString", "GetHashCode", "MemberwiseClone", "Finalize", "ReferenceEquals", "InputModel"}
CS_KEYWORDS = {
    "abstract", "as", "base", "bool", "break", "byte", "case", "catch", "char", "checked", "class", "const", "continue",
    "decimal", "default", "delegate", "do", "double", "else", "enum", "event", "explicit", "extern", "false", "finally",
    "fixed", "float", "for", "foreach", "goto", "if", "implicit", "in", "int", "interface", "internal", "is", "lock",
    "long", "namespace", "new", "null", "object", "operator", "out", "override", "params", "private", "protected",
    "public", "readonly", "ref", "return", "sbyte", "sealed", "short", "sizeof", "stackalloc", "static", "string",
    "struct", "switch", "this", "throw", "true", "try", "typeof", "uint", "ulong", "unchecked", "unsafe", "ushort",
    "using", "virtual", "void", "volatile", "while",
}
CS_TYPES = {"string": "string", "int": "int", "decimal": "decimal", "date": "DateTime", "datetime": "DateTime", "bool": "bool"}


def class_name(name: str) -> str:
    """C# class name for a spec entity."""
    base = pascal(name, "Item")
    return base + "Entity" if base in RESERVED_TYPE_NAMES else base


def unique(name: str, taken: set, reserved=()) -> str:
    candidate = name
    counter = 2
    while candidate in taken or candidate in reserved:
        candidate = f"{name}{counter}"
        counter += 1
    taken.add(candidate)
    return candidate


def member_name(name: str, owner: str, taken: set) -> str:
    """Property name that cannot clash with its class or with object members."""
    base = pascal(name, "Value")
    if base == owner or base in MEMBER_RESERVED:
        base += "Value"
    return unique(base, taken)


def param_name(name: str, taken: set) -> str:
    words = re.findall(r"[A-Za-z0-9]+", str(name or ""))
    base = "".join(w if i == 0 else w[:1].upper() + w[1:] for i, w in enumerate(words)) or "value"
    base = base[:1].lower() + base[1:]
    if base[0].isdigit():
        base = "v" + base
    if base in CS_KEYWORDS:
        base = "@" + base
    return unique(base, taken)


def cs_type(spec_type: str, entity_classes: dict) -> str:
    """Map a free-text spec type to a C# type. entity_classes: norm_key(entity name) -> class name."""
    text = str(spec_type or "").strip()
    is_list = bool(re.search(r"(\[\]|\(\)|^list\b|^array\b|^collection\b|\blist of\b|^ienumerable|^list<)", text, re.IGNORECASE))
    core = re.sub(r"(\[\]|\(\)|<|>|\blist of\b|^list\b|^array\b|^collection\b|^ienumerable|\bof\b)", " ", text, flags=re.IGNORECASE).strip()
    if norm_key(core) in entity_classes:
        item = entity_classes[norm_key(core)]
    else:
        item = CS_TYPES[norm_field_type(core)]
    return f"List<{item}>" if is_list else item


def cs_string(text) -> str:
    """A C# regular string literal."""
    s = str(text or "").replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n").replace("\t", "\\t")
    return f'"{s}"'


def comment_text(text) -> str:
    """Make text safe for a // comment: one line, no control characters."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def razor_text(text) -> str:
    """Text for a .cshtml body: HTML-escaped and with @ neutralised for Razor."""
    return html.escape(str(text or ""), quote=True).replace("@", "&#64;")


# ---------- a light check of LLM-written method bodies ----------
FORBIDDEN = [
    (r"\bProcess\b", "starting processes"),
    (r"System\.Diagnostics", "System.Diagnostics"),
    (r"\bAssembly\b|\bActivator\b|System\.Reflection", "reflection"),
    (r"Environment\.Exit|Environment\.FailFast", "ending the application"),
    (r"\b(?:File|Directory)\.(?:Delete|Move|Replace)\b|Directory\.CreateDirectory\(\s*\"[A-Za-z]:|\bRegistry\b", "deleting or moving files, or the registry"),
    (r"\bHttpClient\b|WebClient|System\.Net\.Sockets|WebRequest", "network access"),
    (r"\bDllImport\b|\bunsafe\b|\bMarshal\b", "native code"),
]
_BAD_DECLARATION = re.compile(r"^\s*(?:using\s+[A-Za-z_][\w.]*\s*;|namespace\b|(?:public|internal)\s+(?:static\s+|sealed\s+|partial\s+)*(?:class|record|struct|interface|enum)\b)", re.MULTILINE)


def braces_balanced(code: str) -> bool:
    """True if { } are balanced outside strings, chars and comments. Handles verbatim and interpolated strings roughly."""
    depth, i, n = 0, 0, len(code)
    while i < n:
        c = code[i]
        nxt = code[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            while i < n and code[i] != "\n":
                i += 1
            continue
        if c == "/" and nxt == "*":
            end = code.find("*/", i + 2)
            if end == -1:
                return False
            i = end + 2
            continue
        if c == "@" and nxt == '"' or (c in "$@" and nxt in "$@" and code[i + 2:i + 3] == '"'):
            i = code.find('"', i) + 1
            while i < n:
                if code[i] == '"':
                    if i + 1 < n and code[i + 1] == '"':
                        i += 2
                        continue
                    break
                i += 1
            i += 1
            continue
        if c == "$" and nxt == '"':
            i += 2
            while i < n and code[i] != '"':
                i += 2 if code[i] == "\\" else 1
            i += 1
            continue
        if c == '"':
            i += 1
            while i < n and code[i] != '"':
                i += 2 if code[i] == "\\" else 1
            i += 1
            continue
        if c == "'":
            i += 1
            while i < n and code[i] != "'":
                i += 2 if code[i] == "\\" else 1
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def check_body(body: str):
    """Return None if the method body looks acceptable, else a short reason."""
    if not body or not body.strip():
        return "the body is empty"
    if not braces_balanced(body):
        return "the braces do not balance"
    if _BAD_DECLARATION.search(body):
        return "the body declares a namespace, a type or a using directive"
    for pattern, label in FORBIDDEN:
        if re.search(pattern, body):
            return f"the body uses {label}"
    return None
