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
