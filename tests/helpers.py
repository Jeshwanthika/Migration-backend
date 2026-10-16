import io
import zipfile
from pathlib import Path


def make_zip(path: Path, names=("xl/workbook.xml", "xl/vbaProject.bin", "[Content_Types].xml")) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(n, "x")
    return path
