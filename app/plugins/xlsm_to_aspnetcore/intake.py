"""Intake check: a plain validation function, not an agent (decision D-3)."""
from __future__ import annotations

import zipfile
from pathlib import Path

from app.plugins.base import IntakeResult

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MAX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024  # guards against zip bombs


def _reject(status: int, code: str, message: str) -> IntakeResult:
    return IntakeResult(False, status, code, message)


def check_xlsm(path: Path, filename: str, max_upload_bytes: int) -> IntakeResult:
    path = Path(path)
    if not filename or not filename.lower().endswith(".xlsm"):
        return _reject(400, "bad_extension", "Only .xlsm files are accepted.")
    if not path.is_file():
        return _reject(400, "missing_file", "No file was received.")
    size = path.stat().st_size
    if size == 0:
        return _reject(400, "empty_file", "The file is empty.")
    if size > max_upload_bytes:
        limit_mb = max_upload_bytes // (1024 * 1024)
        return _reject(413, "file_too_large", f"The file is larger than the {limit_mb} MB limit.")

    with open(path, "rb") as handle:
        head = handle.read(8)
    if head == OLE_MAGIC:
        return _reject(
            422, "encrypted_or_legacy",
            "This file is password-protected or is an old binary workbook. "
            "Remove the password or save it as a .xlsm file, then upload it again.",
        )
    if not zipfile.is_zipfile(path):
        return _reject(422, "corrupt_file", "The file is not a valid .xlsm workbook (it is not a readable zip archive).")

    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                return _reject(422, "corrupt_file", "The workbook archive is corrupt.")
            total = sum(info.file_size for info in archive.infolist())
            if total > MAX_UNCOMPRESSED_BYTES:
                return _reject(422, "too_large_unpacked", "The workbook unpacks to an unreasonable size.")
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError, NotImplementedError, RuntimeError) as exc:
        return _reject(422, "corrupt_file", f"The workbook archive could not be read: {exc}")

    if "xl/workbook.xml" not in names:
        return _reject(422, "not_a_workbook", "The file is not an Excel workbook (xl/workbook.xml is missing).")
    if "xl/vbaProject.bin" not in names:
        return _reject(422, "no_macros", "The workbook contains no VBA macros (xl/vbaProject.bin is missing).")
    return IntakeResult(True)
