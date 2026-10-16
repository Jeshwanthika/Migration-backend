"""Rule-based scan for the partial and unsupported constructs in the coverage matrix (FR-AN5).

It runs next to the LLM, so a construct from the matrix is flagged even when the model misses it.
"""
from __future__ import annotations

import re

from app.plugins.xlsm_to_aspnetcore.procedures import strip_comment

PARTIAL = "partial"
UNSUPPORTED = "unsupported"
IGNORABLE = "ignorable"   # Excel-only behavior that is simply dropped. Reported as Info.

# (code, level, regex, label, suggested action)
RULES = [
    ("WIN32_DECLARE", UNSUPPORTED, r"^\s*(?:Public\s+|Private\s+)?Declare\s+", "Win32 Declare call",
     "Replace with a managed .NET API or remove the call."),
    ("COM_AUTOMATION", UNSUPPORTED,
     r"CreateObject\s*\(\s*\"(?!Scripting\.(?:Dictionary|FileSystemObject)\b)(?!ADODB\.)[^\"]*\"|\bGetObject\s*\(",
     "COM automation of another application", "Reimplement with a .NET library or stub the call."),
    ("DATABASE_ACCESS", UNSUPPORTED, r"\bADODB\.|\bDAO\.|\bOpenDatabase\b|\bDBEngine\b|CreateObject\s*\(\s*\"ADODB\.",
     "ADODB or DAO database connection", "Use Entity Framework or another data layer."),
    ("SHELL_CALL", UNSUPPORTED, r"(?<![\w.])Shell\s*[\(\"]", "Shell command", "Remove, or call Process.Start deliberately."),
    ("SENDKEYS", UNSUPPORTED, r"\bSendKeys\b", "SendKeys", "No equivalent in a web app. Remove."),
    ("ONTIME_SCHEDULER", UNSUPPORTED, r"\bApplication\.(?:OnTime|OnKey)\b", "Application.OnTime or OnKey",
     "Use a hosted background service if the schedule matters."),
    ("CHARTS", UNSUPPORTED, r"\bChartObjects?\b|\bCharts\.Add\b|\.SetSourceData\b", "Programmatic chart",
     "Use a charting library in the page."),
    ("PIVOT_TABLES", UNSUPPORTED, r"\bPivotTables?\b|\bPivotCaches?\b|\bPivotFields?\b", "Pivot table",
     "Rebuild as a grouped query."),
    ("ACTIVEX_CONTROLS", UNSUPPORTED, r"\bOLEObjects?\b|\bAddOLEObject\b", "ActiveX control",
     "Replace with an HTML control."),
    ("CLIPBOARD", UNSUPPORTED, r"\bDataObject\b|\bClipboard\b", "Clipboard access", "Remove."),
    ("WORKSHEET_CHANGE_EVENT", PARTIAL, r"^\s*(?:Private\s+|Public\s+)?Sub\s+(?:Worksheet_Change|Workbook_SheetChange)\b",
     "Worksheet_Change event cascade", "Review the rule as an explicit service call."),
    ("FILE_WRITE", PARTIAL, r"\bOpen\s+.+\s+For\s+(?:Output|Append|Binary)\b|^\s*(?:Print|Write)\s+#|CreateObject\s*\(\s*\"Scripting\.FileSystemObject\"|\bFileSystemObject\b",
     "File write", "Write under a configured folder on the server."),
    ("EXPORT_PDF", UNSUPPORTED, r"\.ExportAsFixedFormat\b", "Excel PDF export through COM",
     "Generate the PDF with a .NET PDF library."),
    ("APPLICATION_STATE", PARTIAL, r"\bApplication\.(?:Calculation|Calculate)\b",
     "Application calculation mode", "Check whether the behavior still matters."),
    ("EXCEL_UI_ONLY", IGNORABLE,
     r"\bApplication\.(?:ScreenUpdating|EnableEvents|DisplayAlerts|StatusBar|DefaultFilePath|PathSeparator|Cursor)\b|\bActiveWindow\b|\.PageSetup\b|\.(?:Select|Activate)\b",
     "Excel-only UI or environment setting (dropped in the migration)", "Remove it, or replace with the web equivalent."),
    ("DYNAMIC_RANGE", IGNORABLE, r"\bRange\s*\(\s*(?:\"[^\"]*\"\s*&|[A-Za-z_]\w*\s*&)",
     "Row or column address built from variables", "Becomes a loop or query over rows."),
    ("FORMAT_DEPENDENT", PARTIAL, r"\b(?:If|ElseIf|Select\s+Case)\b.*\.(?:Interior\.Color|Interior\.ColorIndex|Font\.\w+|NumberFormat)\b",
     "Logic that depends on cell formatting", "Store the state as data instead."),
]
_COMPILED = [(code, level, re.compile(rx, re.IGNORECASE), label, action) for code, level, rx, label, action in RULES]


def scan_procedure(proc) -> list:
    """Return findings for one procedure: dicts with code, level, line, snippet, label, suggested_action."""
    findings = []
    for offset, raw in enumerate(proc.lines):
        text = strip_comment(raw)
        if not text.strip():
            continue
        for code, level, regex, label, action in _COMPILED:
            if regex.search(text):
                findings.append({
                    "code": code, "level": level, "line": proc.start_line + offset,
                    "snippet": raw.strip()[:200], "label": label, "suggested_action": action,
                })
    return findings


def scan_declarations(code: str, procedures: list) -> list:
    """Declare statements sit outside procedures, so scan the module-level lines too."""
    covered = set()
    for proc in procedures:
        covered.update(range(proc.start_line, proc.end_line + 1))
    findings = []
    for number, raw in enumerate(code.split("\n"), start=1):
        if number in covered:
            continue
        text = strip_comment(raw)
        for rule_code, level, regex, label, action in _COMPILED:
            if rule_code in ("WIN32_DECLARE", "ACTIVEX_CONTROLS") and regex.search(text):
                findings.append({"code": rule_code, "level": level, "line": number, "snippet": raw.strip()[:200],
                                 "label": label, "suggested_action": action})
    return findings
