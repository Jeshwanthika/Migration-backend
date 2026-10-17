"""Group procedures into chunks that fit the size setting. A procedure is never cut (FR-AN2)."""
from __future__ import annotations


def make_chunks(procedures: list, max_chars: int) -> list:
    """Greedy grouping in source order. A procedure larger than max_chars gets a chunk of its own."""
    chunks, current, size = [], [], 0
    for proc in procedures:
        length = len(proc.text)
        if current and size + length > max_chars:
            chunks.append(current)
            current, size = [], 0
        current.append(proc)
        size += length
    if current:
        chunks.append(current)
    return chunks


def halves(chunk: list) -> list:
    """Split a chunk into two smaller ones, keeping source order. Used when a request is too large to send."""
    middle = (len(chunk) + 1) // 2
    return [chunk[:middle], chunk[middle:]]
