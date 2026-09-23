"""Deterministic per-page splitting with source slices and bounded overlap."""

import re


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    # Preserve indentation, internal spacing, symbols and short lines (including code).
    lines = [line.rstrip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")


def split_page(text: str, size: int, overlap: int):
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Require size > 0 and 0 <= overlap < size")
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer useful-sized paragraphs, then lines, sentences, word boundaries.
            minimum = start + max(size // 2, overlap + 1)
            window = text[minimum:end]
            for pattern in [r"\n\n", r"\n", r"[.!?。！？](?:\s+|(?=[^\x00-\x7f]))", r"\s+"]:
                matches = list(re.finditer(pattern, window))
                if matches:
                    end = minimum + matches[-1].end()
                    break
        content = text[start:end]
        if content.strip():
            yield content
        if end == len(text):
            break
        next_start = max(start + 1, end - overlap)
        # Move forward to a word boundary within the overlap when possible.
        if next_start > 0 and text[next_start - 1:next_start].isalnum() and text[next_start:next_start + 1].isalnum():
            boundary = re.search(r"\s+", text[next_start:end])
            if boundary:
                next_start += boundary.end()
        start = next_start
