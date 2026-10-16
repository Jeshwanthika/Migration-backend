from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_json_atomic(path: Path, data) -> None:
    """Write JSON so a reader never sees a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_json(path: Path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def safe_child(root: Path, relative: str):
    """Resolve `relative` inside `root`. Returns the path, or None if it escapes the folder or is not a file."""
    if not relative or "\x00" in relative:
        return None
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if root not in target.parents or not target.is_file():
        return None
    return target
