"""Narrow source-fidelity checks, never mathematical interpretation or repair."""
import re
import unicodedata

from app.schemas.knowledge import KnowledgeInput

UNREADABLE_SYMBOL = '[UNREADABLE_SYMBOL]'
FORMULA_RISKS = {'suspicious_formula_layout', 'unusual_symbol_position', 'encoding_warning',
                 'possible_scanned_page', 'empty_text', 'layout_review_recommended'}
# Replacement character and object replacement character, in addition to all
# Unicode private-use planes. Normal non-ASCII text is not unreadable.
REPLACEMENTS = {'\ufffd', '\ufffc'}
MALFORMED = re.compile(r'[=＝]\s*(?:\.{2,}|…+|⋯+|\[MATHEMATICAL EXPRESSION OMITTED[^\]\n]*\])\s*[=＝]')
ATOM = r'(?:[0-9]+(?:\.[0-9]+)?|[A-Za-zα-ωΑ-Ω][A-Za-z0-9α-ωΑ-Ω]*|\([^()\n]{1,80}\)|\{[^{}\n]{1,80}\})'
MATH = re.compile(ATOM + r'(?:\s*[=^_+*/−×÷<>≤≥⊕⊗±∓≠≈≡→←↔⇒⇔-]\s*' + ATOM + r')+'
                  r'|\\[A-Za-z]+(?:\{[^{}\n]{0,80}\})*'
                  r'|[A-Za-z0-9α-ωΑ-Ω]+[⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]+'
                  r'|[√∑∏∫][A-Za-z0-9α-ωΑ-Ω(){}]*')


def unreadable(char: str) -> bool:
    return unicodedata.category(char) == 'Co' or char in REPLACEMENTS


def has_unreadable(text: str) -> bool:
    return UNREADABLE_SYMBOL in text or any(unreadable(c) for c in text)


def mask_unreadable(text: str) -> tuple[str, int]:
    count = sum(unreadable(c) for c in text)
    return ''.join(UNREADABLE_SYMBOL if unreadable(c) else c for c in text), count


def reliable_symbol_source(source: KnowledgeInput) -> bool:
    return not (FORMULA_RISKS.intersection(source.warnings)
                or has_unreadable(source.content) or MALFORMED.search(source.content))


def unsafe_symbolic_content(text: str, sources: list[KnowledgeInput]) -> bool:
    # Even literal malformed extraction is insufficient mathematical evidence.
    if has_unreadable(text) or MALFORMED.search(text):
        return True
    reliable = [c.content for c in sources if reliable_symbol_source(c)]
    originals = [re.sub(r'\s+', '', value) for value in reliable]
    for match in MATH.finditer(text):
        expression = match.group()
        if re.fullmatch(r'[A-Za-z]{2,}(?:-[A-Za-z]{2,})+', expression):
            continue  # data-link, single-bit, etc. are ordinary prose.
        if re.fullmatch(r'(?:sign|symbol|delimiter)\s*=\s*(?:to|for|as|in|is)', expression):
            continue  # Mentioning a delimiter in prose is not an equation.
        if not any(re.sub(r'\s+', '', expression) in original for original in originals):
            return True
    # Unicode operators may stand alone or connect Chinese words not recognized
    # by ATOM. Do not interpret a font's private-use glyph as an operator.
    symbols = {c for c in text if ord(c) > 127 and unicodedata.category(c) == 'Sm'}
    if any(has_unreadable(c.content) for c in sources):
        symbols.update(c for c in text if c in '=^+/*')
    return any(not any(symbol in original for original in reliable) for symbol in symbols)
