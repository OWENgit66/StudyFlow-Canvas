"""Temporary warning-aware prompts; never alter stored text or reconstruct math."""
import re

from app.schemas.knowledge import KnowledgeInput
from app.services.symbolic_safety import MATH, UNREADABLE_SYMBOL, mask_unreadable

MATH_OMITTED = '[MATHEMATICAL EXPRESSION OMITTED — PDF layout is unreliable]'
# Extend an obvious expression to adjacent factors/function names without
# consuming surrounding words or sentence punctuation. This is not Math OCR.
ADJACENT = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789αβγδεζηθικλμνξοπρστυφχψω(){}[]^_+-=*/−×÷<>≤≥')


def mask_warned_math(text: str, warnings: list[str]) -> tuple[str, int]:
    text, unreadable_count = mask_unreadable(text)
    if 'suspicious_formula_layout' not in warnings:
        return text, unreadable_count
    lines, count = [], unreadable_count
    for line in text.splitlines(keepends=True):
        spans = []
        markers = [m.span() for m in re.finditer(re.escape(UNREADABLE_SYMBOL), line)]
        for match in MATH.finditer(line):
            if any(match.start() < end and match.end() > start for start, end in markers):
                continue  # Keep the neutral marker intact, including its underscore.
            if re.fullmatch(r'[A-Za-z]{2,}(?:-[A-Za-z]{2,})+', match.group()):
                continue  # Ordinary hyphenated prose is not mathematics.
            start, end = match.span()
            while start and line[start - 1] in ADJACENT:
                start -= 1
            while end < len(line) and line[end] in ADJACENT:
                end += 1
            if spans and start <= spans[-1][1]:
                spans[-1] = (spans[-1][0], max(end, spans[-1][1]))
            else:
                spans.append((start, end))
        for start, end in reversed(spans):
            line = line[:start] + MATH_OMITTED + line[end:]
        count += len(spans)
        lines.append(line)
    return ''.join(lines), count


def prepare_ai_chunks(chunks: list[KnowledgeInput]) -> tuple[list[KnowledgeInput], dict[str, int]]:
    prepared, stats = [], {'chunks_masked': 0, 'segments_masked': 0}
    for chunk in chunks:
        text, count = mask_warned_math(chunk.content, chunk.warnings)
        prepared.append(chunk.model_copy(update={'content': text}))
        stats['chunks_masked'] += bool(count)
        stats['segments_masked'] += count
    return prepared, stats
