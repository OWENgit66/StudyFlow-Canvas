"""Conservative layout warnings and margin removal; never reconstruct formulas."""

from collections import defaultdict
from math import ceil
import re
from statistics import median

import pymupdf

from app.schemas.document import ParsedPage, ParsingWarning, TextSpan
from app.services.document_chunking import clean_text

MARGIN = 0.08
MIN_REPEAT_RATIO = 0.7
MIN_REPEAT_PAGES = 3


def extract_page(page, number: int) -> ParsedPage:
    # Keep the existing text extraction exactly; dict is separate evidence, not replacement text.
    raw = page.get_text("text", sort=True)
    # Inferred spaces can move a span origin to the preceding baseline. Disable them
    # only in layout evidence; raw text extraction remains unchanged.
    flags = (pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES) | pymupdf.TEXT_INHIBIT_SPACES
    layout = page.get_text("dict", flags=flags)
    spans = []
    line_index = 0
    for block in layout["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            spans.extend(TextSpan(**{k: s[k] for k in ("text", "bbox", "origin", "font", "size", "flags")},
                                  line_index=line_index, direction=line["dir"]) for s in line["spans"])
            line_index += 1
    result = ParsedPage(page_number=number, raw_text=raw, text=clean_text(raw),
                        width=page.rect.width, height=page.rect.height, spans=spans)
    detect_quality(result)
    return result


def detect_quality(page: ParsedPage) -> None:
    if not page.raw_text.strip():
        page.warnings.append(ParsingWarning(code="empty_text", message="No extractable text."))
        page.warnings.append(ParsingWarning(code="possible_scanned_page",
                            message="May be blank, image-only or scanned; no OCR was performed."))
    occurrences = page.raw_text.count("\ufffd")
    if occurrences:
        page.warnings.append(ParsingWarning(code="encoding_warning", occurrences=occurrences,
                            message="Unicode replacement characters preserved; source text may be missing."))
    formula, symbols = set(), set()
    lines = defaultdict(list)
    for i, span in enumerate(page.spans):
        if span.text.strip():
            lines[span.line_index].append((i, span))
    for entries in lines.values():
        for i, span in entries:
            if abs(span.direction[1]) > 0.05:
                continue  # Baseline rule applies only to horizontal writing.
            shifted = bool(span.flags & 1)  # PyMuPDF superscript flag, not a formula assertion.
            for _, neighbor in entries:
                if neighbor is span or span.size >= neighbor.size * 0.85:
                    continue
                gap = max(neighbor.bbox[0] - span.bbox[2], span.bbox[0] - neighbor.bbox[2], 0)
                dy = abs(span.origin[1] - neighbor.origin[1])
                if gap <= neighbor.size and 0.12 * neighbor.size <= dy <= 0.65 * neighbor.size:
                    shifted = True
            if shifted:
                formula.add(i)
                if not any(c.isalnum() for c in span.text):
                    symbols.add(i)
    if formula:
        page.warnings.append(ParsingWarning(code="suspicious_formula_layout", occurrences=len(formula),
                            span_indices=sorted(formula), message="Raised/lowered spans may lose structure in plain text; no formula reconstruction."))
    if symbols:
        page.warnings.append(ParsingWarning(code="unusual_symbol_position", occurrences=len(symbols),
                            span_indices=sorted(symbols), message="Symbols have shifted baselines; plain-text positioning may be unreliable."))


def _lines(page):
    groups = defaultdict(list)
    for i, span in enumerate(page.spans):
        groups[span.line_index].append((i, span))
    return list(groups.values())


def remove_repeated_margins(pages: list[ParsedPage]) -> None:
    """Remove only complete, unambiguously matched text lines; retain uncertain cases."""
    candidates = defaultdict(list)
    for page in pages:
        if not page.width or not page.height:
            continue
        body_sizes = [s.size for s in page.spans if s.text.strip()
                      and MARGIN * page.height < s.origin[1] < (1 - MARGIN) * page.height]
        if not body_sizes:
            continue
        for entries in _lines(page):
            spans = [s for _, s in entries]
            text = "".join(s.text for s in spans).strip()
            if not text or len(text) > 100 or any(abs(s.direction[1]) > 0.05 for s in spans):
                continue
            x = min(s.bbox[0] for s in spans) / page.width
            y0 = min(s.bbox[1] for s in spans) / page.height
            y1 = max(s.bbox[3] for s in spans) / page.height
            zone = "header" if y1 <= MARGIN else "footer" if y0 >= 1 - MARGIN else None
            if not zone or max(s.size for s in spans) > median(body_sizes) * 0.8:
                continue
            # Visual numbering must equal the physical source page; arbitrary numbers stay.
            match = re.fullmatch(r"(?:Page\s+)?([0-9]+)", text, flags=re.IGNORECASE)
            if match and int(match[1]) == page.page_number:
                key_text = "<physical-page-number>"
                x = max(s.bbox[2] for s in spans) / page.width  # Stable right-aligned numbering.
            elif len(text) >= 8 and len(text.split()) >= 2 and not match:
                key_text = text
            else:
                continue
            key = (zone, key_text, round(x / 0.02), round(y0 / 0.02))
            candidates[key].append((page, text, entries))
    required = max(MIN_REPEAT_PAGES, ceil(len(pages) * MIN_REPEAT_RATIO))
    accepted = defaultdict(list)
    for key, matches in candidates.items():
        if len({p.page_number for p, _, _ in matches}) >= required:
            for page, text, entries in matches:
                # Same phrase elsewhere on this page makes the mapping ambiguous: preserve it.
                all_lines = ["".join(s.text for _, s in line).strip() for line in _lines(page)]
                if all_lines.count(text) == 1:
                    accepted[page.page_number].append((key[0], text, entries))
    for page in pages:
        entries = accepted[page.page_number]
        if not entries:
            continue
        # A raw line may contain both a left footer and a right page number.
        choices = sorted({text for _, text, _ in entries}, key=len, reverse=True)
        part = "(?:" + "|".join(re.escape(t) for t in choices) + ")"
        pattern = re.compile(r"\s*" + part + r"(?:\s+" + part + r")*\s*")
        kept, removed_indices = [], []
        for line in page.raw_text.splitlines():
            if pattern.fullmatch(line):
                matched = [(zone, text, spans) for zone, text, spans in entries if text in line]
                # Don't remove a repeated body line that happens to look like a margin.
                if page.raw_text.splitlines().count(line) != 1:
                    kept.append(line)
                    continue
                for zone, _, spans in matched:
                    if zone == "header":
                        page.repeated_headers_removed += 1
                    else:
                        page.repeated_footers_removed += 1
                    removed_indices.extend(i for i, _ in spans)
            else:
                kept.append(line)
        page.text = clean_text("\n".join(kept))
        count = page.repeated_headers_removed + page.repeated_footers_removed
        if count:
            page.warnings.append(ParsingWarning(code="repeated_header_footer", occurrences=count,
                span_indices=removed_indices, message="Repeated small margin text removed from cleaned text only; raw text and spans retained."))
